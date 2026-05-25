"""Agent executor: Anthropic API loop with observed tool call wrapper.

Core rule: the agent never calls tools directly. Every tool call goes through
observed_tool_call(), which logs start → execute → result before returning
the result to the model.

Anthropic-specific notes:
  - system prompt is a top-level parameter, not a message
  - stop_reason is "end_turn" | "tool_use" | "max_tokens"  (not "stop" / "tool_calls")
  - tool_use blocks live in response.content (mixed with text blocks)
  - block.input is already a dict (not a JSON string like OpenAI's function.arguments)
  - all tool results for one turn go in a single "user" message as tool_result blocks
  - cache tokens: cache_read_input_tokens and cache_write_input_tokens are separate fields
"""

import hashlib
import json
import time
import uuid

from anthropic import Anthropic

from . import logger as log
from .pricing import compute_cost, get_pricing
from .tool_registry import (
    call_tool,
    count_schema_tokens,
    count_text_tokens,
    extract_tool_metadata,
    get_tool_schemas,
)


# ── Truncation ────────────────────────────────────────────────────────────────

def _truncate(result: dict, max_chars: int) -> tuple[dict, bool]:
    """Fit result within max_chars when JSON-serialised.

    For search results: drops tail items until it fits.
    For everything else: truncates the serialised string directly.
    """
    serialised = json.dumps(result)
    if len(serialised) <= max_chars:
        return result, False

    if "results" in result and isinstance(result["results"], list):
        truncated = dict(result)
        while truncated["results"] and len(json.dumps(truncated)) > max_chars:
            truncated["results"] = truncated["results"][:-1]
        return truncated, True

    return {"content": serialised[:max_chars], "_truncated": True}, True


# ── observed_tool_call ────────────────────────────────────────────────────────

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
    """Execute one tool through the observer wrapper.

    Returns (inserted_result, call_id).
    inserted_result is what gets sent back to the model.
    call_id is our internal tool_calls primary key.
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
        result_hash = hashlib.sha256(raw_str.encode()).hexdigest()
        result_tokens_raw = count_text_tokens(raw_str, model)

        inserted_result, was_truncated = _truncate(raw_result, max_chars)
        inserted_str = json.dumps(inserted_result)
        result_tokens_inserted = count_text_tokens(inserted_str, model)

        metadata = extract_tool_metadata(tool_name, raw_result)

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
            latency_ms=int((time.time() - started_at) * 1000),
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


# ── Agent loop ────────────────────────────────────────────────────────────────

def run_agent(
    prompt: str,
    config: dict,
    agent_config_id: str,
    source: str = "synthetic",
) -> dict:
    """Run one prompt through the Claude agent and log every model call and tool call.

    Returns a summary dict with run_id, trace_id, token totals, and cost.
    """
    agent = config["agent"]
    model: str = agent["model"]
    system_prompt: str = agent.get("system_prompt", "You are a helpful assistant.")
    max_tool_calls: int = agent.get("max_tool_calls", 5)
    max_tokens: int = agent.get("max_tokens", 4096)
    max_chars: int = config.get("truncation", {}).get("tool_result_max_chars", 4000)

    tool_names = [t["name"] for t in config.get("tools", []) if t.get("enabled", True)]
    schemas = get_tool_schemas(tool_names)
    schema_tokens = count_schema_tokens(schemas, model)

    pricing = get_pricing(model)
    client = Anthropic()

    trace_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    log.create_run(
        run_id=run_id,
        trace_id=trace_id,
        agent_config_id=agent_config_id,
        user_prompt=prompt,
        user_prompt_tokens=count_text_tokens(prompt, model),
        tools_exposed=tool_names,
        source=source,
    )

    # Anthropic: system is a top-level parameter; messages are user/assistant only.
    messages: list[dict] = [{"role": "user", "content": prompt}]

    call_index = 0
    tool_call_index = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    tools_called: list[str] = []
    # (our_call_id) — pending until consumed_by is known after next model call
    pending_our_call_ids: list[str] = []
    tool_result_tokens_for_next_call = 0
    success = True
    final_answer = ""
    run_started_at = time.time()

    try:
        while call_index <= max_tool_calls:
            call_started_at = time.time()
            model_call_id = str(uuid.uuid4())

            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                tools=schemas or [],
                messages=messages,
                temperature=agent.get("temperature", 0),
            )

            call_latency_ms = int((time.time() - call_started_at) * 1000)
            usage = response.usage
            input_tokens: int = usage.input_tokens
            output_tokens: int = usage.output_tokens
            cache_read: int = getattr(usage, "cache_read_input_tokens", 0) or 0
            cache_write: int = getattr(usage, "cache_write_input_tokens", 0) or 0

            call_cost = (
                compute_cost(pricing, input_tokens, output_tokens, cache_read, cache_write)
                if pricing else 0.0
            )
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
                cache_read_input_tokens=cache_read,
                cache_write_input_tokens=cache_write,
                tool_schema_tokens=schema_tokens,
                tool_result_tokens_inserted=tool_result_tokens_for_next_call,
                finish_reason=response.stop_reason,
                cost_usd=call_cost,
                latency_ms=call_latency_ms,
            )
            tool_result_tokens_for_next_call = 0

            # Back-fill consumed_by for tool calls whose results fed this model call.
            for our_call_id in pending_our_call_ids:
                log.update_tool_call_consumed_by(our_call_id, model_call_id)
            pending_our_call_ids = []

            if response.stop_reason != "tool_use":
                final_answer = " ".join(
                    block.text for block in response.content if hasattr(block, "text")
                ).strip()
                break

            # Append assistant turn before executing tools.
            messages.append({"role": "assistant", "content": response.content})

            # Execute all tool_use blocks in this turn; collect results for one user message.
            tool_results: list[dict] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                inserted_result, our_call_id = observed_tool_call(
                    tool_name=block.name,
                    arguments=block.input,  # already a dict in Anthropic SDK
                    run_id=run_id,
                    trace_id=trace_id,
                    call_index=tool_call_index,
                    triggered_by_model_call_id=model_call_id,
                    model=model,
                    max_chars=max_chars,
                )

                tools_called.append(block.name)
                tool_call_index += 1
                pending_our_call_ids.append(our_call_id)

                inserted_str = json.dumps(inserted_result)
                tool_result_tokens_for_next_call += count_text_tokens(inserted_str, model)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": inserted_str,
                })

            # Anthropic requires all tool results in a single user message.
            messages.append({"role": "user", "content": tool_results})
            call_index += 1

    except Exception:
        success = False
        raise

    finally:
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
            latency_ms=int((time.time() - run_started_at) * 1000),
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
