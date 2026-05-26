# Six-Week Roadmap and Later-Stage Phases

## Six-Week Roadmap

Six weeks, nights and weekends. One working loop per week. Logging before prediction.

### Week 1 — Logging Infrastructure *(Milestone 1, part 1)*

- `db.py`: SQLite schema for `model_pricing`, `agent_configs`, `agent_runs`, `model_calls`, `tool_calls`
- `pricing.py`: static per-1M-token pricing for Claude models (`claude-haiku-4-5-20251001`, `claude-sonnet-4-6`); include OpenAI rows for future comparison; set `billing_mode = "claude_code_pro_subscription"` and `cost_basis = "api_equivalent_imputed"` as defaults for Claude Code Pro target
- `tool_registry.py`: load `web_search` and `calculator` from `agent_config.yaml`; define schemas in Anthropic `input_schema` format; count schema tokens; compute `tool_registry_hash`
- `executor.py`: call Claude via Anthropic SDK (`client.messages.create()`); handle `tool_use` blocks; route all tool calls through `observed_tool_call` wrapper; capture `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_write_input_tokens`
- `logger.py`: write `agent_runs`, `model_calls`, `tool_calls` (with source URLs); apply sample quality score
- `acf run "..."` CLI command: run a single prompt through Claude and log the full trace
- Verify: `Σ model_calls.input_tokens == agent_runs.actual_input_tokens`
- `auto_config.py`: generate `contributor_id` on first run; store in `~/.acf/contributor.json`; display first-run disclosure
- `acf/sync/anonymizer.py`: implement safe-fields filter as a pure function; write unit tests (no network needed)
- `acf/sync/syncer.py`: write sync loop skeleton with dry-run mode (logs payload, skips HTTP POST); register `atexit` hook; set `sync_status = "pending"` on every `model_calls` write
- `sync_status TEXT DEFAULT 'pending'` column in `model_calls` schema
- **Note:** Live sync to ingestion API is deferred to Week 6+. Weeks 1–5 run in dry-run mode.

### Week 2 — Batch Logging and Validation *(Milestone 1, part 2)*

- `data/seed_templates.yaml`: 100–200 prompts across `web_search`, `calculator`, `no_tool`, `ambiguous`
- `scripts/generate_tasks.py`: expand templates into `seed_tasks.jsonl`
- `scripts/run_batch.py`: run tasks sequentially; log all results
- `acf run-batch` CLI command
- Source URL tracking: verify `source_urls_returned`, `source_domains`, `source_traceability_status` are populated for all `web_search` calls
- Run 100 prompts end-to-end; verify every run produces a complete, traceable log
- **Milestone 1 complete when:** 100 runs logged, every `model_call` and `tool_call` has tokens, API-equivalent imputed cost, `billing_mode`, `cost_basis`, and timestamps

### Week 3 — Empirical Profiles *(Milestone 2)*

- `profiler.py`: compute p50/p90 from logged `tool_calls.result_tokens_inserted`; compute per prompt category
- `scripts/update_profiles.py`: recompute `tool_profiles` on demand from all logged `tool_calls`
- `acf profiles --update` CLI command: rebuild profiles from stored logs
- `acf trace --run-id ...`: show full `model_call` → `tool_call` chain
- `acf sources --run-id ...`: show source domains used per run
- **Milestone 2 complete when:** p50/p90 profiles exist for `web_search`, `calculator`, and `no_tool`; all prompt categories covered

### Week 4 — First Prediction Mode *(Stage 3 begins)*

- `db.py`: add `predictions` and `tool_profiles` tables
- `predictor.py`: use empirical profiles (from Week 3) to estimate cost; rule-based router for tool prediction; budget guard; writes to `predictions` table with `trace_id`; returns `prediction_id`
- `acf predict` CLI command
- Output: estimated p50/p90 API-equivalent cost, budget status, `prediction_id`, `tool_schema_tokens`, main cost drivers, optimization suggestions
- Fallback: if no profile exists for a tool, use conservative p90 heuristic and flag as `confidence: low`
- `acf compare --run-id ...`: show predicted vs actual tokens and API-equivalent cost for any logged run

### Week 5 — Held-Out Evaluation *(Milestone 3)*

- Hold out 20–30 new prompts not used in the Week 2 training batch
- `acf run-batch --heldout`: run held-out tasks, log actuals, compare against predictions
- `acf calibration` CLI command: print `p90_coverage`, `underestimation_rate`, token MAPE per tool
- Add `calibration_reports` table; persist each calibration run
- Add privacy-safe logging defaults (`synthetic_only` mode with salted prompt hash)
- **Milestone 3 complete when:** `p90_coverage ≥ 0.90` and `underestimation_rate ≤ 0.10` on held-out batch

### Week 6 — User Validation

- Polish `acf` CLI output (`rich` table; `--json` flag)
- Write `README.md` with setup and demo commands
- Record a short demo: `acf run` → `acf profiles --update` → `acf predict` → `acf compare` → `acf trace`
- Talk to 10 agent builders: *"Would you instrument your agent with this?"* and *"Would you trust these cost estimates?"*
- Decision point: next interface is SDK, API, CI integration, or dashboard — based on feedback

**Deferred until after validation:**
FastAPI, Postgres, async queue, embedding router, supervised classifier, LLM-assisted task generation, `deep_predict`, multi-tenant support, `router_training_examples`, web dashboard.

---

## Later-Stage Roadmap

After the six-week MVP is validated with real users or real execution data:

### Phase 5 — Community Profile Server + Smarter Routing

**Community network (go live):**
- Deploy ingestion API (FastAPI + contributor token auth)
- Set up S3/GCS data lake + Athena/BigQuery for admin queries
- Nightly job: recompute community profiles from lake → publish via `GET /v1/community/profiles`
- Enable live sync: remove dry-run flag; `model_calls` rows start flowing to the lake
- Launch contributor leaderboard at `agentcost.ai/contributors`
- Pin contributor wall to GitHub repo; publish social post

**Smarter routing:**
- `router_predictor.py`: add embedding similarity layer
- `training_dataset_builder.py`: feature extraction + quality-weighted JSONL export
- `calibration.py`: full metric suite with per-tool breakdown; persisted `calibration_reports` table
- Automated nightly calibration job; synthetic task generation driven by coverage gaps
- `POST /pipeline/run` and `GET /pipeline/status` endpoints

### Phase 6 — Scaled Infrastructure

- Migrate SQLite → Postgres (schema is compatible)
- Add async task queue (Celery + Redis, or Temporal)
- Replace `scripts/run_batch.py` with async workers
- Add `deep_predict` mode (route with `gpt-4o-mini`)
- LLM-assisted synthetic task generation
- Add `synthetic_tasks` database table

### Phase 7 — Dashboard and Observability

- Web dashboard: p90 coverage trend, cost drift by tool, source domain frequency, pipeline health
- Synthetic vs. production accuracy comparison panel
- Alert when `underestimation_rate > 0.10`
- Multi-tenant support (per-project tool registries and profiles)

### Phase 8 — Advanced Calibration

- Supervised classifier trained on `router_training_examples`
- Active learning: flag low-confidence predictions; prioritize similar prompts in next batch
- Distribution shift detection: alert when production accuracy lags synthetic
- Cache-aware estimation: track prompt cache hit rates; subtract cached-input cost from estimate

### Future Extensions

| Extension | Notes |
|-----------|-------|
| **Multi-model comparison** | Estimate cost across `gpt-4o`, `claude-opus-4-7`, `gemini-2.0-flash` simultaneously |
| **Agent loop detection** | Predict loop depth for multi-step agents; multiply per-iteration cost |
| **Streaming cost updates** | Emit real-time token count updates mid-run for a live cost meter |
| **MCP server pricing** | Some MCP tools charge per-call fees; model as `service_fee_per_call_usd` in ToolProfile |
| **Budget guard v2** | Auto-suggest a cheaper model when current model's p90 would block execution |
| **Source domain allowlisting** | Configurable allowlist / blocklist of domains for web_search tools |
| **RAG cost profiling** | Add `file_search` / retrieval tools with chunk-level token profiling |
