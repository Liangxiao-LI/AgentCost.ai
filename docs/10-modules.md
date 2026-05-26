# Module Reference and System Diagram

The MVP uses five consolidated modules. This section documents both the MVP module interface and the logical full-system split for when each module grows large enough to separate.

## 0. `acf/integrations/` + `auto_config.py` *(Zero-Config Entry Point)*

**Purpose:** Enable drop-in integration for existing Anthropic/OpenAI API users with no setup required.

`auto_config.py` runs on first import of any `acf.integrations` module. It checks for `~/.acf/acf.db`; if absent, creates it silently using the minimal MVP schema. No YAML, no env vars, no explicit init call required. Project-specific DB path via `ACF_DB_PATH` env var.

`integrations/anthropic.py` wraps `anthropic.Anthropic`. The `messages.create()` method is intercepted: a timer starts, the real API call is made, then `response.usage` is read, `api_equivalent_cost_usd` is computed, and a row is written to `model_calls` with `integration_source = "sdk_wrapper"`. The returned response object is identical to the real SDK response — callers see no difference.

`integrations/openai.py` does the same for `openai.OpenAI`, mapping OpenAI's `usage.prompt_tokens` / `usage.completion_tokens` to the same schema fields.

`integrations/patch.py` implements `acf.patch()` by replacing `anthropic.Anthropic` and `openai.OpenAI` in their respective modules with the tracked versions. `acf.unpatch()` restores the originals.

**Limitation vs. full executor:** SDK wrapper mode captures model-level token counts but does not intercept individual tool calls, extract source URLs, apply truncation metadata, or support the full traceability chain (`triggered_by_model_call_id`, `consumed_by_model_call_id`). Runs logged via the SDK wrapper have `integration_source = "sdk_wrapper"` and are weighted lower in calibration than `executor` runs.

---

## 0b. `acf/sync/` *(Core — ships with Week 1 schema)*

**Purpose:** Buffer, anonymize, and upload `model_calls` rows to the community data lake. Download community profiles on startup.

`syncer.py` — reads `model_calls WHERE sync_status = "pending"` in batches of 500. For each batch, calls `anonymizer.build_payload()`, then `client.ingest()`. On success, marks rows `"synced"`. On failure, applies exponential backoff (1s, 2s, 4s, 8s, 16s); after 5 failures marks `"failed"` for retry next cycle. Registers itself via Python `atexit` so it fires automatically at session end. In dry-run mode (Weeks 1–5), logs the payload but skips the HTTP call.

`anonymizer.py` — pure function: takes a `model_calls` row dict plus agent config fields, returns a safe payload dict containing only the allowed fields plus `contributor_id`. Allowed fields include token counts, model metadata, tool names, cost fields, prompt/system hashes, and agent config metadata (temperature, truncation policy, budget limits, privacy mode). No network calls; fully testable without mocks.

`client.py` — thin HTTP wrapper around `httpx`. `ingest(batch)` posts to `POST /v1/ingest`. `fetch_community_profiles(models)` calls `GET /v1/community/profiles` and returns parsed rows. Auth is the local contributor token from `~/.acf/contributor.json`. Handles HTTP errors and timeouts without raising — logs and returns failure status so the syncer can handle retry logic.

---

## 1. `tool_registry.py` *(MVP)*

**Purpose:** Central store for all available tools and MCP tools.

Loads tool definitions at startup. Each entry includes its name, type, description, input/output schemas, pre-computed schema token counts, and an optional per-call service fee. Computes and caches `tool_registry_hash` so prediction records can be tied to a specific registry snapshot.

```python
@dataclass
class ToolDefinition:
    tool_name: str
    tool_type: str           # "function" | "mcp"
    description: str
    input_schema: dict
    output_schema: dict | None
    schema_tokens: int       # pre-counted at registration time
    provider: str            # e.g. "local", "mcp://weather-server"
    service_fee_per_call_usd: float | None
    enabled: bool
```

Key methods: `register()`, `get()`, `list_enabled()`, `registry_hash()`.

---

## 2. `predictor.py` *(MVP — covers router_predictor + token_estimator + price_estimator + budget_guard)*

**Repo:** `public` during M1–M4. Extracted to `agentcost-engine` (private repo) at Phase 5 kickoff (AGE-46). Keep internal function boundaries clean so the move is a copy, not a rewrite.

**Purpose:** Predict tool calls, estimate token usage, compute API-equivalent cost, and apply the budget guard. Split into separate modules in Phase 5.

**Router layer** — three-layer hybrid; use only what is available:

1. **Rule-based baseline** — keyword and intent patterns. Zero data required. MVP uses only this.
2. **Embedding similarity** — cosine similarity between prompt and tool description embeddings. *(Phase 5)*
3. **Supervised classifier** — trained on `router_training_examples`. *(Phase 8)*

```python
@dataclass
class ToolPrediction:
    tool: str
    probability: float
    expected_calls: float

@dataclass
class RouterOutput:
    predicted_tools: list[ToolPrediction]
    no_tool_probability: float
    confidence: str          # "high" | "medium" | "low"
    router_version: str      # "rules" | "embedding" | "classifier"
```

**Token estimator layer** — uses model-specific tokenizers (`tiktoken` for OpenAI, `anthropic.beta.messages.count_tokens` for Claude):

```
total_input_tokens =
    system_prompt_tokens                          ← fixed
  + base_prompt_tokens                            ← fixed
  + tool_schema_tokens (ALL exposed tools)        ← fixed; paid even if unused
  + conversation_history_tokens                   ← fixed
  + Σ_i [ P(tool_i) × E(calls_i)
          × (p50_argument_tokens_i
             + p50_result_tokens_inserted_i       ← after truncation; not result_tokens_raw
             + p50_followup_input_tokens_i) ]

total_output_tokens =
    Σ_i [ P(tool_i) × E(calls_i) × avg_followup_output_tokens_i ]
  + final_answer_tokens
```

Key distinctions:
- `tool_schema_tokens` is a fixed cost for all exposed tools — no probability weighting.
- Profile `result_tokens_inserted`, not `result_tokens_raw`. The truncation policy determines the gap.
- p90 substitutes p90 profile values; fixed terms are identical across p50 and p90.

**Price estimator layer** — computes `api_equivalent_cost_usd` using the formula from [06-claude-code-runtime.md](06-claude-code-runtime.md). Snapshots `pricing_id` and per-token prices. Never updates a pricing row in place — closes it (`effective_to = today`) and inserts a new one.

```python
@dataclass
class ModelPricing:
    pricing_id: str
    provider: str
    model: str
    effective_from: date
    effective_to: date | None          # None = currently active
    input_price_per_1m: float
    output_price_per_1m: float
    cache_read_price_per_1m: float | None
    cache_write_price_per_1m: float | None
    reasoning_price_per_1m: float | None  # o-series models
    price_unit: str                    # always "per_1m_tokens"
    pricing_basis: str                 # "public_api_pricing"
    pricing_source_url: str
```

**Budget guard layer:**

```python
@dataclass
class BudgetDecision:
    limit_usd: float
    status: str          # "safe" | "warning" | "blocked" | "unknown"
    should_execute: bool
    reason: str
```

---

## 3. `executor.py` *(MVP — covers agent_executor + tool_call_observer + token_usage_tracker + cost_tracker)*

**Purpose:** Run tasks through the configured target agent and collect ground-truth observations. Every tool call is intercepted by `observed_tool_call`; every model API response is captured by `token_usage_tracker`.

```python
@dataclass
class ExecutionResult:
    run_id: str
    trace_id: str
    task_id: str | None
    prediction_id: str | None
    agent_config_id: str
    actual_tools_called: list[str]
    model_call_events: list[ModelCallEvent]
    tool_call_events: list[ToolCallEvent]
    total_input_tokens: int
    total_output_tokens: int
    actual_api_equivalent_cost_usd: float   # imputed from token usage
    actual_cash_cost_usd: float             # 0.0 under subscription unless allocated
    billing_mode: str
    cost_basis: str
    latency_ms: int
    success: bool
    error: str | None
    sample_quality_score: float
    sample_quality_reason: str
```

Pipeline safety config:

```yaml
pipeline:
  max_batch_cost_usd: 1.00
  max_task_cost_usd_p90: 0.02
  max_tool_calls_per_run: 5
  stop_on_budget_exceeded: true
```

---

## 4. `logger.py` *(MVP — covers run_logger + database writes)*

**Purpose:** Single write path for all execution data into the database. Enforces privacy mode before writing. Generates `trace_id` once per prediction-run pair and propagates it to all child records.

Write paths:
- `log_prediction(prediction, agent_config_id) -> (prediction_id, trace_id)` — written at predict time; `run_id` is NULL
- `log_run(result: ExecutionResult, prediction_id: str | None) -> run_id` — written after execution; back-fills `predictions.run_id`
- `log_model_calls(run_id, calls: list[ModelCallEvent])` — one row per model API call
- `log_tool_calls(run_id, calls: list[ToolCallEvent])` — one row per tool call

---

## 5. `profiler.py` *(MVP — covers cost_profiler + calibration + profile updates)*

**Purpose:** Build and maintain empirical token profiles per `(tool_name, model)` pair. Reads `tool_calls` and computes p50 / p90 statistics. Falls back to cross-model averages when per-model samples are insufficient. Profiles `result_tokens_inserted`, not `result_tokens_raw`.

```python
@dataclass
class ToolProfile:
    tool_name: str
    model: str
    schema_tokens: int
    avg_argument_tokens: float
    p50_argument_tokens: float
    p90_argument_tokens: float
    p50_result_tokens_inserted: float
    p90_result_tokens_inserted: float
    avg_followup_input_tokens: float
    avg_followup_output_tokens: float
    avg_calls_per_trigger: float
    success_rate: float
    sample_count: int
    profile_version: int
    source_window_start: datetime
    source_window_end: datetime
    updated_at: datetime
```

---

## 6. `task_generator.py` *(MVP: `generate_tasks.py` script)*

**Purpose:** Expand seed templates into executable synthetic tasks. MVP: template-based only. Reads `seed_templates.yaml`, samples variables, writes `seed_tasks.jsonl`.

```python
@dataclass
class SyntheticTask:
    task_id: str
    prompt: str
    system_prompt: str
    model: str
    tools_exposed: list[str]
    target_tools: list[str]
    task_category: str       # "positive" | "negative" | "ambiguous"
    generation_strategy: str # "template" | "coverage_driven" | "llm_assisted"
    created_at: datetime
```

Safety: before executing each task, call `predictor.predict()`. Skip if p90 exceeds `pipeline.max_task_cost_usd_p90`.

---

## 7. `training_dataset_builder.py` *(Phase 5+)*

**Purpose:** Transform raw execution logs into structured training examples for the ML router. Not needed in the MVP. Added in Phase 5 when there are hundreds of labeled runs per tool.

---

## System Diagram

```mermaid
flowchart TD
    subgraph Target Agent Config
        CFG[agent_config.yaml] --> TR[tool_registry]
        CFG --> PR[predictor]
    end

    subgraph Pre-Run Prediction
        UPR([User Prompt]) --> PR
        TR -->|schemas + schema_tokens| PR
        TP[(tool_profiles)] -->|p50/p90 profiles| PR
        MP[(model_pricing)] --> PR
        PR -->|prediction_id + cost estimate + budget| OUT([Budget Decision\n+ Cost Drivers\n+ Suggestions])
    end

    subgraph Execution and Observation
        RUN[executor] --> OBS[observed_tool_call wrapper]
        OBS --> TOOL[real tool]
        TOOL -->|result + source URLs| OBS
        OBS --> LOG[logger]
        RUN --> LOG
        LOG --> DB[(SQLite DB\npredictions / agent_runs\nmodel_calls / tool_calls)]
    end

    subgraph Self-Improving Loop
        DB --> PROF[profiler / calibration]
        PROF -->|updated p50/p90| TP
        DB --> TDB[training_dataset_builder]
        TDB -->|labeled examples| RPML[router — later ML layer]
    end

    subgraph CLI
        CLI[acf CLI] --> PR
        CLI --> RUN
        CLI --> PROF
    end
```
