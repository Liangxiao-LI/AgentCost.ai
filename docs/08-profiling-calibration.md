# Profiling and Calibration Loop

## Synthetic Task Generation

Do not generate synthetic tasks with an LLM first. Use templates.

| Phase | Strategy | When |
|-------|----------|------|
| 1 | Manually written seed templates | Week 1 |
| 2 | Template + variable sampling | Week 2 |
| 3 | Coverage-driven (target weak tools / low sample counts) | Week 4 |
| 4 | LLM-assisted generation | Only after logging loop is proven |

**Batch sizes:**
- Batch 1: 100 tasks (prove the loop works)
- Batch 2: 300 tasks (enough for first empirical profiles)
- Batch 3: 1,000 tasks (enough to see calibration trends)

**First-batch distribution:**

| Category | Count | Purpose |
|----------|-------|---------|
| `web_search` required | 40 | Profile search result sizes |
| `calculator` required | 20 | Profile deterministic tool behavior |
| `no_tool` required | 25 | Test false positive suppression |
| `ambiguous` | 15 | Test router robustness |

**`seed_templates.yaml`:**

```yaml
web_search_required:
  target_tools: ["web_search"]
  templates:
    - "Find the latest {company} quarterly revenue."
    - "What is the current stock price of {ticker}?"
    - "Search for the latest UK inflation rate."
    - "Find recent news about {company}."

calculator_required:
  target_tools: ["calculator"]
  templates:
    - "Calculate the percentage return from {start} to {end}."
    - "What is {a} percent of {b}?"
    - "Calculate CAGR from {start} to {end} over {years} years."

no_tool_required:
  target_tools: []
  templates:
    - "Explain what duration means in bond investing."
    - "Explain the Black-Litterman model intuitively."
    - "What is the difference between variance and standard deviation?"

ambiguous:
  target_tools: []
  templates:
    - "Explain how a web search engine works."
    - "When should an agent use a calculator?"
    - "What are the risks of relying on external tools?"

variables:
  company: [Nvidia, Apple, Microsoft, Tesla]
  ticker: [NVDA, AAPL, MSFT, TSLA]
  start: [100, 327, 58]
  end: [120, 416, 73]
  years: [1, 3, 5]
  a: [15, 22, 40]
  b: [200, 1000, 2500]
```

## `target_tools` vs `actual_tools_called`

- `target_tools` — what the synthetic task was **designed** to test
- `actual_tools_called` — what the agent **actually did**

```json
{
  "prompt": "Find the latest Nvidia quarterly revenue.",
  "target_tools": ["web_search"],
  "actual_tools_called": []
}
```

Both miss types — calling a tool when not needed, and not calling a tool when needed — are calibration signals.

## Sample Quality Scoring

Keep all runs in the database. Weight selectively in training.

| Run type | Default score | Rationale |
|----------|--------------|-----------|
| `production_success` | **1.0** | Real user, real tool result |
| `synthetic_success` | **0.6** | Designed prompt — good but not real |
| `production_failed` | **0.2** | Retain for calibration; low training weight |
| `synthetic_failed` | **0.2** | Same |
| `tool_error` | **0.3** | Tool behavior is real; routing label unreliable |
| `manual_debug` | **0.1** | Excluded from training by default |
| `ambiguous_prompt` | **0.3** | Hard label; noisy for classifier |

Training filter: `sample_quality_score >= 0.5` for initial training sets. Lower the threshold as the database grows.

Runs with `score < 0.5` remain in `agent_runs` permanently and contribute to `p90_coverage` and `underestimation_rate` calibration. All calibration comparisons use `actual_api_equivalent_cost_usd`, not `actual_cash_cost_usd`.

## Fallback Profile Hierarchy

When a new tool has no empirical data, do not fail or return zero:

```
0. community:    tool_name + model (community_profiles table — trained on all contributors)
1. exact:        tool_name + model + agent_config_id (local)
2. tool + model: tool_name + model (local)
3. tool only:    tool_name (across all models, local)
4. type default: e.g. "web_search" | "calculator" | "file_search" | "database"
5. global:       average across all logged tool calls (local)
6. conservative: hardcoded upper-bound safe fallback
```

Level 0 is used when a community profile exists and `sample_count ≥ 30`. It gives cold-start users accurate predictions from day one. Once a user accumulates enough local data (≥ 30 runs for a tool), levels 1–2 take precedence — their local data is more specific to their agent configuration.

When fallback is used, surface it in the prediction response:

```json
{
  "profile_source": "community",
  "community_sample_count": 142000,
  "confidence": "high"
}
```

```json
{
  "profile_source": "tool_type_default",
  "confidence": "low",
  "warnings": ["No empirical data for this tool yet. Using web_search type defaults."]
}
```

This prevents silent overconfidence and signals to the task generator to prioritize coverage for that tool.

## Calibration

**The two headline metrics are `p90_coverage` and `underestimation_rate`.** Target `p90_coverage ≥ 0.90` and `underestimation_rate ≤ 0.10` from the first week of real logging.

| Metric | Priority | Description |
|--------|----------|-------------|
| `p90_coverage` | **Primary** | Fraction of runs where actual API-equivalent cost ≤ p90 estimate. Target ≥ 0.90. |
| `underestimation_rate` | **Primary** | Fraction of runs where actual API-equivalent cost > p90. Target ≤ 0.10. |
| `cost_mape` | Secondary | Mean absolute percentage error on total API-equivalent cost |
| `token_mape` | Secondary | Mean absolute percentage error on total token count |
| `tool_top1_accuracy` | Secondary | Was the highest-probability tool actually called? |
| `tool_recall` | Secondary | Were all actually-called tools in the predicted set? |
| `no_tool_accuracy` | Secondary | Correct when no tool was needed |

When `underestimation_rate` rises: check whether a new tool with no profile was added, whether truncation policy changed, or whether a high-result-size tool is being called more often than expected. Then generate targeted synthetic tasks to close the gap.

**Full calibration pipeline:**

```
4. cost_profiler (scripts/update_profiles.py in MVP)
   └─ reads tool_calls (result_tokens_inserted)
   └─ recomputes p50/p90 per (tool_name, model)
   └─ upserts tool_profiles with new profile_version and source window

5. calibration (CLI: acf calibration)
   └─ computes p90_coverage and underestimation_rate
   └─ flags tools or models with high error rates
   └─ prints CalibrationReport (MVP: CLI output; later: persisted table)
   └─ if underestimation_rate > 0.10 → generate more targeted tasks

6. (Phase 5+) training_dataset_builder
   └─ extracts embeddings and labeled examples
   └─ writes router_training_examples weighted by sample_quality_score

7. (Phase 5+) router_predictor
   └─ retrains or fine-tunes with new labeled examples
```
