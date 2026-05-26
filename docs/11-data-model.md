# Data Model

## Table: `model_pricing`

| Column | Type | Notes |
|--------|------|-------|
| `pricing_id` | UUID | Primary key |
| `provider` | str | `openai` / `anthropic` / `google` / … |
| `model` | str | |
| `effective_from` | date | |
| `effective_to` | date | NULL = currently active |
| `input_price_per_1m` | float | USD per 1M input tokens |
| `output_price_per_1m` | float | USD per 1M output tokens |
| `cache_read_price_per_1m` | float | NULL if not supported |
| `cache_write_price_per_1m` | float | NULL if not supported |
| `reasoning_price_per_1m` | float | NULL except for reasoning models |
| `price_unit` | str | Always `"per_1m_tokens"` |
| `pricing_basis` | str | `"public_api_pricing"` |
| `pricing_source_url` | str | URL to provider pricing page |

## Table: `agent_configs`

| Column | Type | Notes |
|--------|------|-------|
| `agent_config_id` | UUID | Primary key |
| `created_at` | datetime | |
| `agent_version` | str | Semantic version or git SHA |
| `model` | str | |
| `system_prompt_hash` | str | SHA-256 |
| `tool_registry_hash` | str | SHA-256 of all enabled tool schemas |
| `temperature` | float | |
| `max_tool_calls` | int | |
| `tool_result_truncation_policy` | JSON | Default policy, e.g. `{"max_tokens": 1200}` |
| `notes` | text | |

## Table: `predictions`

| Column | Type | Notes |
|--------|------|-------|
| `prediction_id` | UUID | Primary key |
| `trace_id` | UUID | Shared with the linked run |
| `agent_config_id` | UUID | FK → `agent_configs` |
| `user_prompt_hash` | str | SHA-256 — never store raw prompt here unless privacy=off |
| `user_prompt_tokens` | int | |
| `model` | str | |
| `tools_exposed` | JSON | All tool names passed to the model |
| `tool_schema_tokens` | int | Fixed cost for all exposed schemas |
| `tools_predicted` | JSON | RouterOutput snapshot |
| `estimated_input_tokens_p50` | int | |
| `estimated_input_tokens_p90` | int | |
| `estimated_output_tokens_p50` | int | |
| `estimated_output_tokens_p90` | int | |
| `estimated_api_equivalent_cost_usd_p50` | float | API-equivalent imputed cost; see `cost_basis` |
| `estimated_api_equivalent_cost_usd_p90` | float | API-equivalent imputed cost; see `cost_basis` |
| `billing_mode` | str | `"claude_code_pro_subscription"` / `"anthropic_api"` / … |
| `cost_basis` | str | `"api_equivalent_imputed"` / `"actual_api_billed"` / `"unknown"` |
| `budget_status` | str | `safe` / `warning` / `blocked` / `unknown` |
| `budget_limit_usd` | float | Compared against `estimated_api_equivalent_cost_usd_p90` |
| `confidence` | str | `high` / `medium` / `low` |
| `router_version` | str | `rules` / `embedding` / `classifier` |
| `prediction_mode` | str | `fast` / `deep` |
| `pricing_id` | UUID | FK → `model_pricing` — snapshot used at prediction time |
| `run_id` | UUID | FK → `agent_runs`; NULL until/unless the run executes |
| `created_at` | datetime | |

## Table: `agent_runs`

| Column | Type | Notes |
|--------|------|-------|
| `run_id` | UUID | Primary key |
| `trace_id` | UUID | Shared with the linked prediction |
| `prediction_id` | UUID | FK → `predictions`; NULL if no pre-run prediction made |
| `task_id` | UUID | FK → `synthetic_tasks`; NULL for production runs |
| `agent_config_id` | UUID | FK → `agent_configs` |
| `timestamp` | datetime | |
| `model` | str | |
| `user_prompt` | text | NULL if privacy mode hides it |
| `user_prompt_hash` | str | Always stored |
| `user_prompt_tokens` | int | Always stored |
| `system_prompt_hash` | str | |
| `tool_registry_hash` | str | |
| `tools_exposed` | JSON | All tool names passed to the model |
| `source` | str | `synthetic` / `production` |
| `integration_source` | str | `sdk_wrapper` / `executor` / `api` — how this run was logged |
| `actual_tools_called` | JSON | Ground truth after execution |
| `actual_input_tokens` | int | Sum across all model calls in the run |
| `actual_output_tokens` | int | Sum across all model calls in the run |
| `actual_api_equivalent_cost_usd` | float | Imputed from token usage × API price; used for profiling and calibration |
| `actual_cash_cost_usd` | float | Real money spent; 0.0 per-run under subscription unless allocated |
| `subscription_allocation_usd` | float | Optional prorated share of monthly subscription fee; NULL if unused |
| `subscription_period_id` | str | FK to subscription period record; NULL if not subscription billing |
| `billing_mode` | str | `"claude_code_pro_subscription"` / `"anthropic_api"` / … |
| `cost_basis` | str | `"api_equivalent_imputed"` / `"actual_api_billed"` / `"subscription_allocated"` / `"unknown"` |
| `latency_ms` | int | |
| `success` | bool | |
| `sample_quality_score` | float | 0.0–1.0 |
| `sample_quality_reason` | text | |

## Table: `model_calls`

One row per model API call within a run.

| Column | Type | Notes |
|--------|------|-------|
| `model_call_id` | UUID | Primary key |
| `trace_id` | UUID | |
| `run_id` | UUID | FK → `agent_runs` |
| `call_index` | int | 0 = initial call |
| `model` | str | |
| `input_tokens` | int | |
| `output_tokens` | int | |
| `cached_input_tokens` | int | Subset of `input_tokens` |
| `reasoning_tokens` | int | NULL for non-reasoning models |
| `tool_schema_tokens` | int | Schema tokens for all exposed tools at this call |
| `tool_result_tokens_inserted` | int | Tokens from preceding tool result(s); 0 for initial call |
| `finish_reason` | str | `tool_calls` / `stop` / `length` / `content_filter` |
| `latency_ms` | int | |
| `api_equivalent_cost_usd` | float | Imputed from token counts × snapshotted price; see `cost_basis` |
| `billing_mode` | str | `"claude_code_pro_subscription"` / `"anthropic_api"` / … |
| `cost_basis` | str | `"api_equivalent_imputed"` / `"actual_api_billed"` / `"unknown"` |
| `integration_source` | str | `sdk_wrapper` / `executor` / `api` — how this call was captured |
| `sync_status` | str | `pending` / `synced` / `failed` / `excluded` (excluded = opted out) |
| `input_price_per_1m_snapshot` | float | Price per 1M input tokens at logging time |
| `output_price_per_1m_snapshot` | float | Price per 1M output tokens at logging time |
| `cache_read_price_per_1m_snapshot` | float | NULL if cache not active |
| `cache_write_price_per_1m_snapshot` | float | NULL if cache not active |
| `pricing_id` | UUID | FK → `model_pricing` |

`Σ model_calls.input_tokens` for a run must equal `agent_runs.actual_input_tokens`. Discrepancy = logging bug.

## Table: `tool_calls`

| Column | Type | Notes |
|--------|------|-------|
| `call_id` | UUID | Primary key |
| `trace_id` | UUID | |
| `run_id` | UUID | FK → `agent_runs` |
| `triggered_by_model_call_id` | UUID | The model call that requested this tool |
| `consumed_by_model_call_id` | UUID | The later model call that consumed this result; NULL until known |
| `call_index` | int | Order within the run |
| `tool_name` | str | |
| `tool_type` | str | `function` / `mcp` |
| `provider` | str | e.g. `local`, `mcp://weather-server` |
| `server_name` | str | MCP server name; NULL for local tools |
| `arguments_json` | JSON | NULL if privacy hides it |
| `request_metadata` | JSON | Any additional metadata about the request |
| `result_hash` | str | SHA-256 always stored |
| `result_preview` | text | First N chars; N configurable |
| `result_text` | text | NULL if privacy hides it |
| `response_metadata` | JSON | Any additional metadata about the response |
| `source_urls_returned` | JSON | All URLs returned by the tool |
| `source_urls_inserted` | JSON | URLs whose content was inserted into context |
| `source_urls_cited` | JSON | URLs cited in final answer (if parseable) |
| `source_domains` | JSON | Normalized domains from returned URLs |
| `source_traceability_status` | str | `full` / `partial` / `none` |
| `argument_tokens` | int | |
| `result_tokens_raw` | int | Total tokens in raw result |
| `result_tokens_inserted` | int | Tokens actually inserted into context (after truncation) |
| `was_result_truncated` | bool | |
| `truncation_policy_applied` | JSON | Actual policy used; may differ from config-level default |
| `followup_input_tokens` | int | |
| `followup_output_tokens` | int | |
| `latency_ms` | int | |
| `success` | bool | |
| `error_message` | text | NULL if success |
| `created_at` | datetime | |

## Table: `tool_profiles`

| Column | Type | Notes |
|--------|------|-------|
| `tool_name` | str | Composite PK with `model` |
| `model` | str | Composite PK with `tool_name` |
| `schema_tokens` | int | |
| `avg_argument_tokens` | float | |
| `p50_argument_tokens` | float | |
| `p90_argument_tokens` | float | |
| `p50_result_tokens_inserted` | float | Profiled from `result_tokens_inserted`, not raw |
| `p90_result_tokens_inserted` | float | |
| `avg_followup_input_tokens` | float | |
| `avg_followup_output_tokens` | float | |
| `avg_calls_per_trigger` | float | |
| `success_rate` | float | |
| `sample_count` | int | |
| `profile_version` | int | Incremented on each update |
| `source_window_start` | datetime | Oldest run included in this profile |
| `source_window_end` | datetime | Most recent run included |
| `updated_at` | datetime | |

## Table: `community_profiles`

Downloaded from `GET /v1/community/profiles` on startup (at most once per 24 hours). Used as level-0 fallback in the prediction engine. Read-only locally — never written by the user's own runs.

| Column | Type | Notes |
|--------|------|-------|
| `tool_name` | str | Composite PK with `model` |
| `model` | str | Composite PK with `tool_name` |
| `p50_result_tokens_inserted` | float | From community data lake |
| `p90_result_tokens_inserted` | float | |
| `avg_argument_tokens` | float | |
| `avg_calls_per_trigger` | float | |
| `sample_count` | int | Total contributor runs in this profile |
| `contributor_count` | int | Distinct contributors |
| `profile_version` | int | |
| `published_at` | datetime | When admin published this profile |
| `fetched_at` | datetime | When this client downloaded it |

## Table: `calibration_reports`

| Column | Type | Notes |
|--------|------|-------|
| `report_id` | UUID | Primary key |
| `created_at` | datetime | |
| `evaluation_window_start` | datetime | |
| `evaluation_window_end` | datetime | |
| `agent_config_id` | UUID | Which config this report covers |
| `model` | str | |
| `runs_evaluated` | int | |
| `p90_coverage` | float | **Primary** — target ≥ 0.90 |
| `underestimation_rate` | float | **Primary** — target ≤ 0.10 |
| `cost_mape` | float | |
| `token_mape` | float | |
| `tool_top1_accuracy` | float | |
| `tool_recall` | float | |
| `no_tool_accuracy` | float | |
| `flagged_tools` | JSON | Tools with high error rates or underestimation |
| `action_taken` | str | `profiles_refreshed` / `router_retrained` / `tasks_generated` |

## Table: `synthetic_tasks` *(Week 4+)*

During Weeks 1–3, use `seed_tasks.jsonl` instead of this table. Add it in Week 4 when the batch runner needs status tracking.

| Column | Type | Notes |
|--------|------|-------|
| `task_id` | UUID | Primary key |
| `prompt` | text | |
| `system_prompt` | text | |
| `model` | str | |
| `tools_exposed` | JSON | |
| `target_tools` | JSON | `[]` for negative tasks |
| `task_category` | str | `positive` / `negative` / `ambiguous` |
| `generation_strategy` | str | `template` / `coverage_driven` / `llm_assisted` |
| `status` | str | `queued` / `running` / `completed` / `failed` |
| `created_at` | datetime | |

---

## Minimal MVP Schema

For Weeks 1–3, use only these tables. Do not add `router_training_examples`, `calibration_reports` (use CLI output instead), or `synthetic_tasks` (use `seed_tasks.jsonl` instead).

**`predictions`**

```sql
prediction_id TEXT PRIMARY KEY,
trace_id TEXT NOT NULL,
agent_config_id TEXT NOT NULL,
user_prompt_hash TEXT NOT NULL,
user_prompt_tokens INTEGER NOT NULL,
model TEXT NOT NULL,
tools_exposed TEXT NOT NULL,        -- JSON list
tool_schema_tokens INTEGER NOT NULL,
tools_predicted TEXT,               -- JSON RouterOutput
estimated_api_equivalent_cost_usd_p50 REAL,   -- imputed; not actual billed under subscription
estimated_api_equivalent_cost_usd_p90 REAL,
billing_mode TEXT,                  -- "claude_code_pro_subscription" | "anthropic_api" | ...
cost_basis TEXT,                    -- "api_equivalent_imputed" | "actual_api_billed" | "unknown"
budget_status TEXT,
confidence TEXT,
pricing_id TEXT,
run_id TEXT,                        -- NULL until run executes
created_at TEXT NOT NULL
```

**`agent_runs`**

```sql
run_id TEXT PRIMARY KEY,
trace_id TEXT NOT NULL,
prediction_id TEXT,
agent_config_id TEXT NOT NULL,
user_prompt_hash TEXT NOT NULL,
user_prompt_tokens INTEGER NOT NULL,
tools_exposed TEXT NOT NULL,        -- JSON list
source TEXT NOT NULL,               -- "synthetic" | "production"
actual_tools_called TEXT,           -- JSON list
actual_input_tokens INTEGER,
actual_output_tokens INTEGER,
actual_api_equivalent_cost_usd REAL,  -- imputed from token usage × API price; used for profiling
actual_cash_cost_usd REAL,            -- real money spent; 0.0 at per-run level under subscription
billing_mode TEXT,                    -- "claude_code_pro_subscription" | "anthropic_api" | ...
cost_basis TEXT,                      -- "api_equivalent_imputed" | "actual_api_billed" | "unknown"
success INTEGER,
latency_ms INTEGER,
sample_quality_score REAL,
sample_quality_reason TEXT,
created_at TEXT NOT NULL
```

**`model_calls`**

```sql
model_call_id TEXT PRIMARY KEY,
trace_id TEXT NOT NULL,
run_id TEXT NOT NULL,
call_index INTEGER NOT NULL,
model TEXT NOT NULL,
input_tokens INTEGER NOT NULL,
output_tokens INTEGER NOT NULL,
cached_input_tokens INTEGER DEFAULT 0,
reasoning_tokens INTEGER,
tool_schema_tokens INTEGER NOT NULL,
tool_result_tokens_inserted INTEGER DEFAULT 0,
finish_reason TEXT,
api_equivalent_cost_usd REAL,         -- imputed; see cost_basis in agent_runs
billing_mode TEXT,
cost_basis TEXT,
integration_source TEXT,              -- "sdk_wrapper" | "executor" | "api"
sync_status TEXT DEFAULT 'pending',   -- "pending" | "synced" | "failed" | "excluded"
input_price_per_1m_snapshot REAL,
output_price_per_1m_snapshot REAL,
cache_read_price_per_1m_snapshot REAL,
cache_write_price_per_1m_snapshot REAL,
latency_ms INTEGER
```

**`tool_calls`**

```sql
call_id TEXT PRIMARY KEY,
trace_id TEXT NOT NULL,
run_id TEXT NOT NULL,
triggered_by_model_call_id TEXT NOT NULL,
consumed_by_model_call_id TEXT,     -- NULL until the next model call is logged
call_index INTEGER NOT NULL,
tool_name TEXT NOT NULL,
tool_type TEXT NOT NULL,
arguments_json TEXT,
result_hash TEXT,
result_preview TEXT,
result_tokens_raw INTEGER,
result_tokens_inserted INTEGER,
was_result_truncated INTEGER,
truncation_policy_applied TEXT,     -- JSON
source_urls_returned TEXT,          -- JSON list
source_urls_inserted TEXT,          -- JSON list
source_domains TEXT,                -- JSON list
source_traceability_status TEXT,
success INTEGER NOT NULL,
error_message TEXT,
latency_ms INTEGER,
created_at TEXT NOT NULL
```

**`tool_profiles`**

```sql
tool_name TEXT NOT NULL,
model TEXT NOT NULL,
p50_result_tokens_inserted REAL,
p90_result_tokens_inserted REAL,
avg_argument_tokens REAL,
avg_calls_per_trigger REAL,
success_rate REAL,
sample_count INTEGER,
updated_at TEXT NOT NULL,
PRIMARY KEY (tool_name, model)
```
