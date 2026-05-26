# API Design

> **Status: Planned — Phase 4+. The local executor and CLI (`acf run`, `acf predict`) are the MVP interface. The REST API described here is the target design, not yet implemented.**

## `POST /predict`

```json
// Request
{
  "prompt": "Find recent Nvidia earnings and calculate YoY growth.",
  "model": "gpt-4o",
  "tools_exposed": ["web_search", "calculator"],
  "system_prompt": "You are a helpful assistant.",
  "prediction_mode": "fast",
  "budget_limit_usd": 0.02
}

// Response
{
  "prediction_id": "pred-a1b2c3d4",
  "trace_id": "trace-xyz",
  "prediction_mode": "fast",
  "predicted_tools": [
    {"tool": "web_search", "probability": 0.88, "expected_calls": 1.4},
    {"tool": "calculator", "probability": 0.71, "expected_calls": 1.0}
  ],
  "no_tool_probability": 0.05,
  "estimated_tokens": {
    "input_p50": 2800, "input_p90": 5600,
    "output_p50": 310, "output_p90": 720
  },
  "estimated_api_equivalent_cost_usd": {"p50": 0.0031, "p90": 0.0063},
  "billing_mode": "claude_code_pro_subscription",
  "cost_basis": "api_equivalent_imputed",
  "budget": {
    "limit_usd": 0.02,
    "status": "safe",
    "should_execute": true,
    "reason": "p90 API-equivalent cost is comfortably below budget."
  },
  "tool_schema_tokens": 280,
  "tools_exposed": ["web_search", "calculator"],
  "main_cost_drivers": [
    {
      "component": "tool_schema_tokens",
      "reason": "2 tools exposed — fixed cost regardless of which are called",
      "estimated_tokens": 280
    },
    {
      "component": "web_search",
      "reason": "High probability of 1–2 search calls with variable result sizes",
      "estimated_tokens_p90": 3200
    }
  ],
  "optimization_suggestions": [
    "Limit web_search result insertion to 1,000 tokens to reduce p90 by ~25%.",
    "Set max_tool_calls=2 for this prompt type."
  ],
  "profile_source": "tool_model_profile",
  "confidence": "medium",
  "router_version": "rules",
  "warnings": []
}
```

## `POST /log-run`

```json
{
  "prediction_id": "pred-a1b2c3d4",
  "agent_config_id": "cfg-xyz",
  "actual_tools_called": ["web_search", "calculator"],
  "actual_input_tokens": 3700,
  "actual_output_tokens": 410,
  "actual_api_equivalent_cost_usd": 0.0043,
  "actual_cash_cost_usd": 0.0,
  "billing_mode": "claude_code_pro_subscription",
  "cost_basis": "api_equivalent_imputed",
  "latency_ms": 3200,
  "success": true,
  "model_calls": [
    {
      "call_index": 0, "model": "gpt-4o",
      "input_tokens": 720, "output_tokens": 0,
      "cached_input_tokens": 0, "reasoning_tokens": null,
      "tool_schema_tokens": 280, "tool_result_tokens_inserted": 0,
      "finish_reason": "tool_calls", "latency_ms": 850
    },
    {
      "call_index": 1, "model": "gpt-4o",
      "input_tokens": 2120, "output_tokens": 0,
      "cached_input_tokens": 720, "reasoning_tokens": null,
      "tool_schema_tokens": 280, "tool_result_tokens_inserted": 900,
      "finish_reason": "tool_calls", "latency_ms": 1100
    },
    {
      "call_index": 2, "model": "gpt-4o",
      "input_tokens": 860, "output_tokens": 410,
      "cached_input_tokens": 720, "reasoning_tokens": null,
      "tool_schema_tokens": 280, "tool_result_tokens_inserted": 12,
      "finish_reason": "stop", "latency_ms": 920
    }
  ],
  "tool_calls": [
    {
      "call_index": 0,
      "triggered_by_model_call_id": "mc_001",
      "tool_name": "web_search",
      "argument_tokens": 14,
      "result_tokens_raw": 2200,
      "result_tokens_inserted": 900,
      "was_result_truncated": true,
      "truncation_policy_applied": {"max_tokens": 1200},
      "source_urls_returned": ["https://investor.nvidia.com/...", "https://nvidianews.nvidia.com/..."],
      "source_domains": ["investor.nvidia.com", "nvidianews.nvidia.com"],
      "source_traceability_status": "full",
      "latency_ms": 1050, "success": true
    },
    {
      "call_index": 1,
      "triggered_by_model_call_id": "mc_002",
      "tool_name": "calculator",
      "argument_tokens": 12,
      "result_tokens_raw": 12,
      "result_tokens_inserted": 12,
      "was_result_truncated": false,
      "truncation_policy_applied": null,
      "source_urls_returned": [],
      "source_domains": [],
      "source_traceability_status": "none",
      "latency_ms": 8, "success": true
    }
  ]
}
```

## Additional Local Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /profiles/{tool_name}` | Current cost profile (`?model=gpt-4o` optional) |
| `GET /calibration/latest` | Most recent CalibrationReport |
| `GET /configs` | List known agent configs with their hashes |
| `GET /trace/{trace_id}` | Full trace: prediction → run → model calls → tool calls |
| `POST /update-profiles` | Batch-update profiles from historical logs (backfill) |

## Community Network Endpoints

### Ingestion — contributor-authenticated (write)

`POST /v1/ingest`
```json
// Request: batch of anonymized model_calls rows
{
  "contributor_id": "acf-7f3a...",
  "batch": [
    {
      "model": "claude-haiku-4-5-20251001",
      "input_tokens": 720, "output_tokens": 410,
      "cache_read_input_tokens": 0, "cache_write_input_tokens": 0,
      "api_equivalent_cost_usd": 0.0043,
      "billing_mode": "claude_code_pro_subscription",
      "cost_basis": "api_equivalent_imputed",
      "tool_name": "web_search", "tool_type": "function",
      "tools_exposed": ["web_search", "calculator"],
      "result_tokens_inserted": 900, "result_tokens_raw": 2200,
      "finish_reason": "tool_calls", "latency_ms": 850,
      "success": true, "source_domains": ["nvidianews.nvidia.com"],
      "integration_source": "sdk_wrapper",
      "user_prompt_hash": "a3f9c2...",
      "system_prompt_hash": "b1e4d7...",
      "temperature": 0, "max_tool_calls": 5,
      "tool_result_truncation_policy": {"max_tokens": 1200},
      "budget_limits": {"max_task_cost_usd_p90": 0.02},
      "privacy_mode": "synthetic_only"
    }
  ]
}
// Response
{ "accepted": 1, "rejected": 0 }
```

### Community profiles — public read

Pre-computed aggregates published by the admin. No raw data exposed.

`GET /v1/community/profiles?models=claude-haiku-4-5-20251001,claude-sonnet-4-6`
```json
{
  "profiles": [
    {
      "tool_name": "web_search", "model": "claude-haiku-4-5-20251001",
      "p50_result_tokens_inserted": 820, "p90_result_tokens_inserted": 2400,
      "avg_argument_tokens": 14, "avg_calls_per_trigger": 1.3,
      "sample_count": 142000, "contributor_count": 381,
      "profile_version": 47, "published_at": "2026-05-25T00:00:00Z"
    }
  ]
}
```

### Admin only — full lake access

The raw data lake is accessible exclusively to the project admin via admin-scoped API keys. No contributor or end-user can query, read, or enumerate raw synced records.

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/admin/lake/query` | Raw data lake query (admin token required) |
| `GET /v1/admin/contributors` | Full contributor list with stats and badges |
| `POST /v1/admin/profiles/publish` | Recompute community profiles and publish to public endpoint |
| `DELETE /v1/admin/contributors/{contributor_id}` | Process GDPR purge request |
