# MVP Scope, Milestones, and Core Concepts

## MVP Scope and Milestones

### Milestones

**Milestone 1 — Observability**
Run 100 prompts through a real target agent. Produce complete, traceable logs for every model call, tool call, token count, source URL, and API-equivalent imputed cost. Actual subscription cash cost (e.g. Claude Code Pro monthly fee) is tracked separately in `actual_cash_cost_usd`.

**Milestone 2 — Profiles**
Use those 100 logged runs to build empirical p50/p90 tool profiles — one distribution per tool, one per prompt category.

**Milestone 3 — Prediction quality**
Run a held-out batch and show that the predicted p90 API-equivalent cost captures 90%+ of actual API-equivalent costs.

Everything else — embedding routers, supervised classifiers, training datasets, dashboards — comes after Milestone 3.

### Product Positioning

- *See exactly what your agent costs while it runs.*
- *A logging-first cost profiler and budget guard for tool-using AI agents.*

### Goals and Non-Goals

**Goals**
- Estimate total agent run cost before execution (p50 and p90 ranges).
- Predict which tools an agent is likely to call, and how many times.
- Guard against budget overruns before the agent starts.
- Profile per-tool token cost empirically from real execution logs.
- Explain which components drive cost and how to reduce them.
- Build training data automatically via synthetic task generation.
- Improve prediction accuracy continuously through a closed calibration loop.
- Log execution data in a privacy-safe way by default.
- Track which external sources were used by each tool call.

**Non-Goals**
- Not a billing system — does not charge users or integrate with payment processors.
- Not an agent framework — it instruments agent runtimes; it does not replace them.
- Not a model fine-tuner — models are treated as black boxes.
- Not a universal tokenizer — tokenization is delegated to model-specific libraries.
- Not a real-time latency predictor — latency is logged but is not the primary estimate target.

---

## Core Concepts

### The Target Agent

Agent Cost Forecaster does not create a new agent. It instruments a **target agent** — the real agent whose cost we want to predict and monitor. Before running anything, the founder must explicitly configure that target agent:

- `model` — which model the agent runs on
- `system_prompt` — the agent's identity and behavior guidelines
- `tools_exposed` — which tools are always passed to the model
- `temperature` and `max_tool_calls` — model inference settings
- `tool_result_truncation_policy` — how tool outputs are inserted into context
- `budget_limits` — per-task and per-batch cost ceilings
- `privacy_mode` — how much raw data to store

**Config versioning:** Changing the system prompt, tool schema, model, temperature, or truncation policy must create a new `agent_config_id`. The `tool_registry_hash` (SHA-256 of all enabled tool schemas) and `system_prompt_hash` both change, and the old `agent_config_id` is closed. Never mix training data from different configs — the signal becomes contradictory.

### Tools Exposed, Predicted, and Actually Called

These three concepts are distinct. Confusing them produces bad cost estimates.

**Tools exposed to the model** — all tool schemas passed to the model in the context window, whether or not the model uses any of them. Schema tokens are always paid for all exposed tools, not just predicted ones. This is the most common source of underestimation: a caller passes 15 tool schemas "just in case" and pays ~2,000 tokens per call for schemas the model never touches.

```
tool_schema_tokens = Σ schema_tokens(tool_i)  for all exposed tools
```

This is a fixed, computable cost. No probability weighting.

**Tools predicted by the router** — the subset the router believes the agent will actually call, expressed as a probability distribution. Used to weight the *variable* portion of the cost estimate (argument tokens + result tokens + follow-up reasoning).

```
predicted_variable_cost = Σ_i P(tool_i) × E(calls_i) × E(tokens_per_call_i)
```

**Tools actually called by the agent** — ground truth, recorded after execution by the observed tool call wrapper. Calibration compares this against the router's predictions. A tool that is exposed but not predicted and then actually called is a routing miss — the most expensive kind, because its variable token cost was entirely absent from the estimate.

| Field | Table | Meaning |
|-------|-------|---------|
| `tools_exposed` | `predictions`, `agent_runs` | All tool names passed to the model |
| `tool_schema_tokens` | `predictions`, `model_calls` | Fixed token cost for all exposed schemas |
| `tools_predicted` | `predictions` | RouterOutput (probabilities + expected calls) |
| `actual_tools_called` | `agent_runs` | Ground truth after execution |

### API-Equivalent Cost vs. Cash Cost

All cost profiling, p50/p90 estimation, calibration, and budget guard comparisons use **API-equivalent imputed cost** (`api_equivalent_cost_usd`), computed from observed token counts using the provider's public pricing table — regardless of the actual billing arrangement.

This is distinct from **cash cost** (`actual_cash_cost_usd`), which is real money spent. Under Claude Code Pro subscription, the marginal per-run cash cost is zero. See [06-claude-code-runtime.md](06-claude-code-runtime.md) for the full model.

Every run carries two classification fields:
- `billing_mode` — the commercial arrangement: `"claude_code_pro_subscription"` / `"anthropic_api"` / `"openai_api"`
- `cost_basis` — how to interpret the cost field: `"api_equivalent_imputed"` / `"actual_api_billed"` / `"unknown"`

### Traceability

Every prediction and execution is fully traceable through IDs.

```
trace_id
  → prediction_id         (pre-run cost estimate)
  → run_id                (agent execution)
      → model_call_id[0]  (initial model call)
          → tool_call_id[0]   (first tool invoked)
      → model_call_id[1]  (model processes tool result)
          → tool_call_id[1]   (second tool invoked)
      → model_call_id[2]  (final answer)
```

Each tool call row carries two model call references:
- `triggered_by_model_call_id` — the model call that requested this tool
- `consumed_by_model_call_id` — the later model call that consumed this result

**Complete ID and hash inventory:**

```
trace_id              ← spans prediction + run
prediction_id
run_id
task_id               ← synthetic task that generated the prompt
agent_config_id
pricing_id
model_call_id
tool_call_id
tool_registry_hash    ← SHA-256 of all enabled tool schemas
system_prompt_hash    ← SHA-256 of system prompt text
user_prompt_hash      ← salted SHA-256 of normalized prompt
result_hash           ← SHA-256 of raw tool result
```

ID fields connect rows across tables. Hash fields identify content and version without storing sensitive raw text.
