# Prediction and Budget Guard

## Conceptual Cost Formula

```
estimated_api_equivalent_cost =
    base_prompt_cost
  + expected_tool_call_cost
  + expected_tool_result_processing_cost
  + final_answer_cost

Where:

expected_tool_call_cost =
  Σ_i [ P(tool_i called | prompt, tool_set)
        × E(number_of_calls_i)
        × E(tokens_per_call_i) ]
```

Every term is estimated from the experiment database and the router predictor. Single numbers are never returned — all estimates are distributions (p50 / p90).

## Prediction Modes

```
fast_predict (default):
  no model call; target latency < 200 ms
  uses rules + profiles
  returns prediction_id

deep_predict (later-stage):
  may call a cheap router model (e.g. gpt-4o-mini)
  higher accuracy for ambiguous prompts
```

## Prediction Flow (Pre-Run)

```
1. Client sends: prompt, model, tools_exposed, history, prediction_mode, budget_limit_usd

2. tool_registry
   └─ resolves tools_exposed → list[ToolDefinition]
   └─ computes tool_schema_tokens (sum over all exposed tools)
   └─ computes tool_registry_hash

3. router_predictor
   └─ fast: rule-based → embedding → classifier (whichever is available)
   └─ returns RouterOutput { predictions, no_tool_probability, confidence, router_version }

4. token_estimator
   ├─ fixed: system_prompt + user_prompt + history + tool_schema_tokens
   └─ variable per predicted tool (weighted by probability):
       reads profile from tool_profiles using fallback hierarchy
       adds: argument_tokens + result_tokens_inserted + followup_input_tokens
       adds: followup_output_tokens
   └─ returns TokenEstimate { input_p50, input_p90, output_p50, output_p90 }
   └─ returns main_cost_drivers (tool_schema_tokens listed first if > 200 tokens)

5. price_estimator
   └─ looks up active ModelPricing row
   └─ api_equivalent_cost = (input / 1M × input_price_per_1m)
                           + (output / 1M × output_price_per_1m)
                           + (cache_read / 1M × cache_read_price_per_1m)
                           + (cache_write / 1M × cache_write_price_per_1m)
   └─ sets billing_mode and cost_basis based on agent config
   └─ snapshots pricing_id and per-token prices
   └─ returns CostEstimate { p50_api_equivalent_usd, p90_api_equivalent_usd, billing_mode, cost_basis }

6. budget_guard
   └─ compares estimated_api_equivalent_cost_usd_p90 against limit_usd
   └─ returns BudgetDecision { status, should_execute, reason }

7. optimization_advisor (rule-based in MVP)
   └─ generates optimization_suggestions

8. run_logger.log_prediction(prediction, agent_config_id)
   └─ generates trace_id and prediction_id
   └─ writes to predictions (run_id = NULL)
   └─ returns (prediction_id, trace_id) to caller

9. Response returned in < 200 ms (fast mode) — no model call made
   └─ caller receives prediction_id to pass to /log-run after execution
```

## Budget Guard

The budget guard runs on every prediction request. Every `/predict` call returns a `budget` object. This is a core product feature, not a future extension.

```json
{
  "budget": {
    "limit_usd": 0.02,
    "status": "warning",
    "should_execute": true,
    "reason": "p50 API-equivalent cost is within budget but p90 exceeds the limit."
  }
}
```

```yaml
budget:
  default_run_limit_usd: 0.02
  block_if_p90_exceeds_budget: true
  warn_if_confidence_low: true
```

Callers can override `limit_usd` per request. `should_execute` gives the agent runtime a clear boolean gate.

| Status | Condition |
|--------|-----------|
| `safe` | p90 API-equivalent cost is comfortably below budget |
| `warning` | p50 below budget but p90 near or above budget |
| `blocked` | p90 exceeds budget |
| `unknown` | insufficient profile data to estimate reliably |

**Two budget types — do not confuse them:**

| Budget type | What it answers | Field used |
|-------------|-----------------|------------|
| API-equivalent usage budget | "How token-heavy was this run?" | `estimated_api_equivalent_cost_usd_p90` |
| Subscription cash budget | "How much money did I spend this month?" | `actual_cash_cost_usd` (aggregated) |

The MVP budget guard uses API-equivalent cost. Subscription cash spend is fixed monthly and cannot drive a per-run block decision; API-equivalent cost scales with token usage.

## Cost Drivers and Optimization Suggestions

Every prediction must explain its cost drivers. Every expensive prediction must suggest how to reduce cost. Always list `tool_schema_tokens` first if it exceeds 200 tokens — most callers are unaware they are paying for schemas of tools the model never uses.

```json
{
  "tool_schema_tokens": 420,
  "tools_exposed": ["web_search", "calculator"],
  "main_cost_drivers": [
    {
      "component": "tool_schema_tokens",
      "reason": "2 tools exposed — schema cost is fixed regardless of which tools are called",
      "estimated_tokens": 420
    },
    {
      "component": "web_search",
      "reason": "High probability of multiple search calls",
      "estimated_tokens_p90": 4200
    }
  ],
  "optimization_suggestions": [
    "Limit web_search result insertion to 1,000 tokens to reduce p90 by ~30%.",
    "Set max_tool_calls=2 for this prompt type."
  ]
}
```

**Tool exposure optimizer** — schema tokens are paid for all exposed tools, even unused ones:

```bash
acf suggest-tools "Find Nvidia latest earnings and calculate YoY growth"
```

```
Recommended exposed tools:
  - web_search
  - calculator

Do not expose:
  - file_search (not predicted for this prompt type)

Estimated schema token saving: 380 tokens
```

Rule-based in the MVP. Model-specific in later phases.
