# Execution and Logging Loop

## Core Rule

The agent must never call tools directly. **All tool calls must go through an observed wrapper.** Never ask the model what tools it used — observe runtime events directly.

```
Agent wants to call tool
→ observed_tool_call wrapper
→ log tool start (create tool_call row, status=running)
→ call real tool
→ extract result metadata (source URLs, token counts, latency)
→ log result (finish tool_call row)
→ return result to agent
```

## Observer Pseudocode

```python
def observed_tool_call(
    tool_name: str,
    arguments: dict,
    run_id: str,
    triggered_by_model_call_id: str,
) -> Any:
    started_at = time.time()

    tool_call_id = logger.create_tool_call(
        run_id=run_id,
        triggered_by_model_call_id=triggered_by_model_call_id,
        tool_name=tool_name,
        arguments_json=arguments,
        status="running",
    )

    try:
        result = tool_registry.call(tool_name, arguments)
        metadata = extract_tool_metadata(tool_name, result)

        logger.finish_tool_call(
            tool_call_id=tool_call_id,
            success=True,
            result_hash=hash_text(str(result)),
            result_preview=str(result)[:500],
            result_tokens_raw=count_tokens(str(result)),
            result_tokens_inserted=count_inserted_tokens(result),
            source_urls_returned=metadata.get("source_urls_returned", []),
            source_urls_inserted=metadata.get("source_urls_inserted", []),
            source_domains=metadata.get("source_domains", []),
            latency_ms=int((time.time() - started_at) * 1000),
        )
        return result

    except Exception as e:
        logger.finish_tool_call(
            tool_call_id=tool_call_id,
            success=False,
            error_message=str(e),
            latency_ms=int((time.time() - started_at) * 1000),
        )
        raise
```

## MVP Constraint

All external access in the MVP must go through registered tools. Do not allow unmonitored browser access, direct HTTP requests, or code interpreter network access. If `code_interpreter` can call `requests.get()` freely, the system cannot reliably track which websites were used or how many tokens resulted.

## Source URL Tracking

Track not just which tool was called, but which external sources were returned and inserted.

| Field | Meaning |
|-------|---------|
| `source_urls_returned` | All URLs returned by the tool (e.g. all 10 search results) |
| `source_urls_inserted` | URLs whose content was inserted into the LLM context (e.g. top 3) |
| `source_urls_cited` | URLs cited in the final answer, if parseable |
| `source_domains` | Normalized domains from returned URLs |
| `source_traceability_status` | `full` / `partial` / `none` |

A `web_search` may return 10 results but insert only the top 3 snippets into context. Only inserted content affects token cost. Citation appears in the final answer and may lag both.

**Example `web_search` result — observer extracts:**

```json
{
  "source_urls_returned": [
    "https://nvidianews.nvidia.com/...",
    "https://investor.nvidia.com/..."
  ],
  "source_domains": ["nvidianews.nvidia.com", "investor.nvidia.com"]
}
```

## MCP Tool Wrapper

For MCP tools, wrap the MCP client to record `mcp_server_name`, `mcp_tool_name`, arguments, response metadata, source URLs if returned, latency, token counts, and success/error. If an MCP server does not return source URLs, set `source_traceability_status = "partial"`.

## Privacy-Safe Logging

### Prompt Hashing

Production prompt text is sensitive. Hash it instead of storing it raw.

```python
import hashlib, os

SECRET_SALT = os.environ["PROMPT_HASH_SALT"]

def normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.strip().split())

def hash_prompt(prompt: str) -> str:
    normalized = normalize_prompt(prompt)
    return hashlib.sha256((SECRET_SALT + normalized).encode("utf-8")).hexdigest()
```

- Same normalized prompt + same salt → same hash (allows deduplication)
- Salted hash resists dictionary attacks
- Synthetic runs may store full prompt text; production runs default to hash + token count only

### Privacy Modes

| Mode | Behavior |
|------|----------|
| `off` | Store everything. Local development only. |
| `hash_only` | Store hashes and metadata; no raw text. |
| `redact_pii` | Attempt to remove emails, names, phone numbers, IDs. |
| `synthetic_only` | Full data for synthetic runs; metadata only for production runs. |

Recommended MVP default: `synthetic_only`.

`result_tokens_raw` and `result_tokens_inserted` are always stored regardless of privacy mode — they contain no raw text. Source URLs may need domain allowlisting in production privacy modes.

## Logging Flows

**Synthetic batch runs:**

```
1. task_generator
   ├─ reads seed_templates.yaml (MVP) or queries calibration for coverage gaps (Phase 5+)
   └─ writes to seed_tasks.jsonl (MVP) or synthetic_tasks table (Phase 4+)

2. agent_executor (scripts/run_batch.py in MVP)
   ├─ calls predictor.predict() → budget check → skip if blocked
   ├─ runs agent through real model API
   ├─ observed_tool_call wrapper intercepts each tool invocation
   ├─ token_usage_tracker captures per-model-call token counts
   └─ cost_tracker accumulates total API-equivalent cost; stops batch if budget exceeded

3. run_logger
   └─ writes ExecutionResult → agent_runs (source=synthetic)
   └─ writes ModelCallEvent list → model_calls
   └─ writes ToolCallEvent list → tool_calls (with source URLs)
   └─ back-fills predictions.run_id
   └─ assigns sample_quality_score
```

**Production runs:**

```
1. Agent runtime calls POST /log-run with prediction_id (if available)

2. run_logger
   └─ enforces privacy mode
   └─ writes agent_runs (source=production)
   └─ writes model_calls
   └─ writes tool_calls (source_urls stored even if result_text is not)
   └─ back-fills predictions.run_id if prediction_id provided
   └─ assigns sample_quality_score = 1.0 if success

3. cost_profiler
   └─ production samples weighted most heavily in profiles

4. calibration (nightly)
   └─ separates synthetic vs. production accuracy
   └─ if production accuracy < synthetic: flags distribution shift
```

**Logging invariant:** `Σ model_calls.input_tokens == agent_runs.actual_input_tokens`. A discrepancy flags a logging bug.
