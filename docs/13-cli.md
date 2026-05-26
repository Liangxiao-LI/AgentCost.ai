# CLI Design and Example Trace

## CLI Design

Build the CLI before any API or dashboard. Validate the full loop via CLI first.

```bash
# ── Zero-config tracking commands (work from call #1, no setup required) ──

# Show cost summary across all logged calls
acf summary
acf summary --today
acf summary --since 2026-05-01

# Per-call log table: model, tokens, cost, latency
acf log --last 20

# Cost breakdown by model
acf spend --by-model

# ── Full pipeline commands (require agent_config.yaml and logged runs) ──

# Predict cost for a prompt
acf predict "Find recent Nvidia earnings and calculate YoY growth."
acf predict "..." --model gpt-4o --tools web_search,calculator --budget 0.05

# Run a single task and log the result
acf run "Find the latest Apple quarterly revenue." --log

# Generate synthetic tasks from templates
acf generate-tasks --n 100 --strategy template

# Run pending tasks through the configured target agent
acf run-batch --limit 100 --model gpt-4o-mini

# Full local loop: generate + run + update profiles
acf loop --n 100 --update-profiles

# Recompute tool profiles
acf profiles --update
acf profiles --show

# Show prediction vs actual for a run
acf compare --run-id run_001

# Show full trace for a run or prediction
acf trace --run-id run_001
acf trace --prediction-id pred_001

# Show websites / sources used by a run
acf sources --run-id run_001

# Suggest minimal tool set for a prompt
acf suggest-tools "Find Nvidia latest earnings and calculate YoY growth"

# Show calibration summary
acf calibration

# Export training dataset
acf export --format jsonl --output ./data/training.jsonl

# ── Community network commands ──

# Sync control
acf sync                       # manually trigger sync now
acf sync --status              # show pending / synced / failed row counts
acf sync --disable             # opt out of community sync
acf sync --enable              # opt back in
acf sync --purge               # request deletion of all previously synced data (GDPR)

# Contributor identity and recognition
acf contributor status         # calls contributed, models, tools, rank, badge
acf contributor id             # print local anonymous contributor ID

# Community profiles
acf community profiles         # show downloaded community profiles for your tools
acf community update           # force-pull latest community profiles from server
```

**Expected daily flow:**

```
acf generate-tasks → acf run-batch → acf profiles --update → acf calibration
```

Output: readable table by default (`rich` if installed, plain text fallback). Pass `--json` for raw JSON.

---

## Example Trace

Prompt: *"Find Nvidia's latest revenue and calculate YoY growth."*

```json
{
  "trace_id": "trace_001",
  "prediction_id": "pred_001",
  "run_id": "run_001",
  "model": "gpt-4o",
  "tools_exposed": ["web_search", "calculator"],
  "billing_mode": "claude_code_pro_subscription",
  "cost_basis": "api_equivalent_imputed",
  "predicted_api_equivalent_cost_usd_p90": 0.0063,
  "actual_api_equivalent_cost_usd": 0.0043,
  "actual_cash_cost_usd": 0.0,
  "p90_covered": true,
  "steps": [
    {
      "type": "model_call",
      "id": "mc_001",
      "call_index": 0,
      "input_tokens": 720,
      "output_tokens": 0,
      "tool_schema_tokens": 280,
      "tool_result_tokens_inserted": 0,
      "finish_reason": "tool_calls",
      "latency_ms": 850
    },
    {
      "type": "tool_call",
      "id": "tool_001",
      "triggered_by_model_call_id": "mc_001",
      "consumed_by_model_call_id": "mc_002",
      "tool_name": "web_search",
      "arguments_json": {"query": "Nvidia latest annual revenue 2026"},
      "result_tokens_raw": 2200,
      "result_tokens_inserted": 900,
      "was_result_truncated": true,
      "source_domains": ["investor.nvidia.com", "nvidianews.nvidia.com"],
      "source_traceability_status": "full",
      "latency_ms": 1050,
      "success": true
    },
    {
      "type": "model_call",
      "id": "mc_002",
      "call_index": 1,
      "input_tokens": 2120,
      "output_tokens": 0,
      "tool_schema_tokens": 280,
      "tool_result_tokens_inserted": 900,
      "cached_input_tokens": 720,
      "finish_reason": "tool_calls",
      "latency_ms": 1100
    },
    {
      "type": "tool_call",
      "id": "tool_002",
      "triggered_by_model_call_id": "mc_002",
      "consumed_by_model_call_id": "mc_003",
      "tool_name": "calculator",
      "arguments_json": {"expression": "(60922 - 26974) / 26974"},
      "result_tokens_raw": 12,
      "result_tokens_inserted": 12,
      "was_result_truncated": false,
      "source_domains": [],
      "source_traceability_status": "none",
      "latency_ms": 8,
      "success": true
    },
    {
      "type": "model_call",
      "id": "mc_003",
      "call_index": 2,
      "input_tokens": 860,
      "output_tokens": 410,
      "tool_schema_tokens": 280,
      "tool_result_tokens_inserted": 12,
      "cached_input_tokens": 720,
      "finish_reason": "stop",
      "latency_ms": 920
    }
  ],
  "totals": {
    "actual_input_tokens": 3700,
    "actual_output_tokens": 410,
    "actual_api_equivalent_cost_usd": 0.0043,
    "actual_cash_cost_usd": 0.0,
    "model_calls": 3,
    "tool_calls": 2,
    "sources_used": ["investor.nvidia.com", "nvidianews.nvidia.com"]
  }
}
```

> **Note:** For Claude Code Pro runs, `actual_cash_cost_usd` is subscription-based and may be allocated separately. The cost used for profiling, p50/p90 calibration, and budget guard comparisons is always `actual_api_equivalent_cost_usd` — the API-equivalent imputed cost derived from observed token usage.

`acf trace --run-id run_001` outputs this in the terminal.
