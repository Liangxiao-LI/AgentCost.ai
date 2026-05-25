"""Agent executor with observed tool call wrapper.

The core rule: the agent never calls tools directly.
Every tool call goes through observed_tool_call(), which logs start, result,
source URLs, and token counts before returning the result to the agent.
"""

import hashlib
import json
import time
import uuid

from openai import OpenAI

from . import logger as log
from .pricing import compute_cost, get_pricing
from .tool_registry import (
    call_tool,
    count_schema_tokens,
    count_text_tokens,
    extract_tool_metadata,
    get_tool_schemas,
)


# ── Truncation ───────────────────────────────────────────────────────────────

def _truncate_result(result: dict, max_chars: int) -> tuple[dict, bool]:
    """Truncate a tool result to fit within max_chars when JSON-serialised."""
    serialised = json.dumps(result)
    if len(serialised) <= max_chars:
        return result, False

    # For search results: drop items from the tail until it fits.
    if "results" in result and isinstance(result["results"], list):
        truncated = dict(result)
        while truncated["results"] and len(json.dumps(truncated)) > max_chars:
            truncated["results"] = truncated["results"][:-1]
        return truncated, True

    # Fallback: truncate the raw string.
    return {"content": serialised[:max_chars], "_truncated": True}, True


# ── observed_tool_call ───────────────────────────────────────────────────────

def observed_tool_call(
    tool_name: str,
    arguments: dict,
    run_id: str,
    trace_id: str,
    call_index: int,
    triggered_by_model_call_id: str,
    model: str,
    max_chars: int,
) -> tuple[dict, str]:
    """Execute a tool through the observer wrapper.

    Returns (inserted_result, call_id).
    inserted_result is what gets appended to the message history.
    call_id is our internal tool_calls PK (not the OpenAI tool_call_id).
    """
    started_at = time.time()
    call_id = str(uuid.uuid4())

    log.create_tool_call_row(
        call_id=call_id,
        trace_id=trace_id,
        run_id=run_id,
        triggered_by_model_call_id=triggered_by_model_call_id,
        call_index=call_index,
        tool_name=tool_name,
        arguments_json=json.dumps(arguments),
    )

    try:
        raw_result = call_tool(tool_name, arguments)
        raw_str = json.dumps(raw_result)
        result_tokens_raw = count_text_tokens(raw_str, model)
        result_hash = hashlib.sha256(raw_str.encode()).hexdigest()

        inserted_result, was_truncated = _truncate_result(raw_result, max_chars)
        inserted_str = json.dumps(inserted_result)
        result_tokens_inserted = count_text_tokens(inserted_str, model)

        metadata = extract_tool_metadata(tool_name, raw_result)
        latency_ms = int((time.time() - started_at) * 1000)

        log.finish_tool_call_row(
            call_id=call_id,
            success=True,
            result_hash=result_hash,
            result_preview=raw_str[:500],
            result_tokens_raw=result_tokens_raw,
            result_tokens_inserted=result_tokens_inserted,
            was_result_truncated=was_truncated,
            source_urls_returned=metadata["source_urls_returned"],
            source_urls_inserted=metadata["source_urls_inserted"],
            source_domains=metadata["source_domains"],
            source_traceability_status=metadata["source_traceability_status"],
            latency_ms=latency_ms,
        )
        return inserted_result, call_id

    except Exception as exc:
        log.finish_tool_call_row(
            call_id=call_id,
            success=False,
            error_message=str(exc),
            latency_ms=int((time.time() - started_at) * 1000),
        )
        raise


# ── Agent loop ───────────────────────────────────────────────────────────────

def run_agent(
    prompt: str,
    config: dict,
    agent_config_id: str,
    source: str = "synthetic",
) -> dict:
    """Run the target agent for one prompt and log every model call and tool call.

    Returns a summary dict with run_id, trace_id, token totals, and cost.
    """
    agent_cfg = config["agent"]
    model: str = agent_cfg["model"]
    system_prompt: str = agent_cfg.get("system_prompt", "You are a helpful assistant.")
    max_tool_calls: int = agent_cfg.get("max_tool_calls", 3)
    max_chars: int = config.get("truncation", {}).get("tool_result_max_chars", 4000)

    tool_names = [t["name"] for t in config.get("tools", []) if t.get("enabled", True)]
    schemas = get_tool_schemas(tool_names)
    schema_tokens = count_schema_tokens(schemas, model)

    pricing = get_pricing(model)
    client = OpenAI()

    trace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    prompt_tokens = count_text_tokens(prompt, model)

    log.create_run(
        run_id=run_id,
        trace_id=trace_id,
        agent_config_id=agent_config_id,
        user_prompt=prompt,
        user_prompt_tokens=prompt_tokens,
        tools_exposed=tool_names,
        source=source,
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    call_index = 0          # model call counter
    tool_call_index = 0     # tool call counter
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    tools_called: list[str] = []
    # (our_call_id, openai_tool_call_id) — needed to back-fill consumed_by
    pending_tool_call_ids: list[tuple[str, str]] = []
    # tokens from tool results inserted before the current model call
    tool_result_tokens_for_next_call = 0
    success = True
    final_answer = ""
    run_started_at = time.time()

    try:
        while call_index <= max_tool_calls:
            call_started_at = time.time()
            model_call_id = str(uuid.uuid4())

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                tools=schemas or None,
                temperature=agent_cfg.get("temperature", 0),
            )

            call_latency_ms = int((time.time() - call_started_at) * 1000)
            usage = response.usage
            input_tokens: int = usage.prompt_tokens
            output_tokens: int = usage.completion_tokens

            # Extract cached token count if the API returns it
            cached_input_tokens = 0
            if hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
                cached_input_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0

            call_cost = compute_cost(pricing, input_tokens, output_tokens, cached_input_tokens) if pricing else 0.0
            total_input_tokens += input_tokens
            total_output_tokens += output_tokens
            total_cost += call_cost

            log.log_model_call(
                model_call_id=model_call_id,
                trace_id=trace_id,
                run_id=run_id,
                call_index=call_index,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cached_input_tokens=cached_input_tokens,
                tool_schema_tokens=schema_tokens,
                tool_result_tokens_inserted=tool_result_tokens_for_next_call,
                finish_reason=response.choices[0].finish_reason,
                cost_usd=call_cost,
                latency_ms=call_latency_ms,
            )
            tool_result_tokens_for_next_call = 0

            # Back-fill consumed_by for all tool calls that fed into this model call
            for our_call_id, _ in pending_tool_call_ids:
                log.update_tool_call_consumed_by(our_call_id, model_call_id)
            pending_tool_call_ids = []

            choice = response.choices[0]
            if choice.finish_reason == "stop" or not choice.message.tool_calls:
                final_answer = choice.message.content or ""
                break

            # Append assistant turn before executing tools
            messages.append(choice.message)

            for tc in choice.message.tool_calls:
                tool_name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    arguments = {"raw": tc.function.arguments}

                inserted_result, our_call_id = observed_tool_call(
                    tool_name=tool_name,
                    arguments=arguments,
                    run_id=run_id,
                    trace_id=trace_id,
                    call_index=tool_call_index,
                    triggered_by_model_call_id=model_call_id,
                    model=model,
                    max_chars=max_chars,
                )

                tools_called.append(tool_name)
                tool_call_index += 1
                pending_tool_call_ids.append((our_call_id, tc.id))

                inserted_str = json.dumps(inserted_result)
                tool_result_tokens_for_next_call += count_text_tokens(inserted_str, model)

                messages.append({
                    "role": "tool",
                    "content": inserted_str,
                    "tool_call_id": tc.id,
                })

            call_index += 1

    except Exception:
        success = False
        raise

    finally:
        run_latency_ms = int((time.time() - run_started_at) * 1000)

        if source == "production":
            quality_score, quality_reason = (1.0, "production_success") if success else (0.2, "production_failed")
        else:
            quality_score, quality_reason = (0.6, "synthetic_success") if success else (0.2, "synthetic_failed")

        log.finish_run(
            run_id=run_id,
            actual_tools_called=tools_called,
            actual_input_tokens=total_input_tokens,
            actual_output_tokens=total_output_tokens,
            actual_total_cost_usd=total_cost,
            success=success,
            latency_ms=run_latency_ms,
            sample_quality_score=quality_score,
            sample_quality_reason=quality_reason,
        )

    return {
        "run_id": run_id,
        "trace_id": trace_id,
        "model_calls": call_index + 1,
        "tool_calls": tool_call_index,
        "tools_called": sorted(set(tools_called)),
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "total_cost_usd": total_cost,
        "success": success,
        "final_answer": final_answer,
    }
