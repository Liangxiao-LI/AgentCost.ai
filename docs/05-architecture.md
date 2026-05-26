# Founder MVP Architecture

## Two Tools Plus No-Tool

Start with exactly:

1. **`web_search`** — high variance result size; the most interesting tool to profile
2. **`calculator`** — deterministic arguments and results; acts as a control
3. **`no_tool`** — a task category for prompts that need no tool call; tests false positives

`file_search` / RAG is deferred. Retrieval cost, chunking, and privacy issues make it significantly more complex. Add it only after the basic predict → execute → log → profile loop works.

## File Structure

```
agent-cost-forecaster/
  acf/
    integrations/
      anthropic.py        ← drop-in Anthropic client wrapper (Mode A/B/C entry point)
      openai.py           ← drop-in OpenAI client wrapper
      patch.py            ← acf.patch() / acf.unpatch() monkey-patcher
    auto_config.py        ← zero-config init: creates ~/.acf/acf.db on first use
  sync/
    syncer.py           ← batch sync loop, retry logic, sync_status updates
    anonymizer.py       ← strips excluded fields; builds safe upload payload
    client.py           ← HTTP client for POST /v1/ingest and GET /v1/community/profiles
  app/
    tool_registry.py      ← ToolDefinition store + schema token counting
    predictor.py          ← routing + token estimation + price + budget guard
    executor.py           ← agent runner + tool call interception + token tracking
    logger.py             ← database writes for predictions, runs, model calls, tool calls
    profiler.py           ← p50/p90 profile computation + calibration summary
    pricing.py            ← model pricing table (per-1M token rates)
    db.py                 ← SQLite schema + migrations
  config/
    agent_config.yaml     ← target agent configuration (model, tools, truncation, budget)
  data/
    seed_templates.yaml   ← prompt templates: positive, negative, ambiguous
  scripts/
    generate_tasks.py     ← expand templates into seed_tasks.jsonl
    run_batch.py          ← pull tasks, run executor, write logs
    update_profiles.py    ← recompute tool profiles from logged tool_calls
    export_dataset.py     ← export runs + tool_calls as JSONL / CSV / Parquet
  architecture.md
```

## Module Consolidation

Each MVP module consolidates several full-system modules. When the product grows, split them. Keep internal function boundaries clean so the split becomes a rename, not a rewrite.

| MVP module | Full-system modules it covers |
|------------|-------------------------------|
| `predictor.py` | `router_predictor` + `token_estimator` + `price_estimator` + `budget_guard` |
| `executor.py` | `agent_executor` + `tool_call_observer` + `token_usage_tracker` + `cost_tracker` |
| `logger.py` | `run_logger` + database write operations |
| `profiler.py` | `cost_profiler` + `calibration` + profile updates |

## SQLite First

Do not start with Postgres unless there are real users, high concurrency, or more than 100k logged runs. SQLite requires zero infrastructure, is trivial to back up, easy to inspect locally, and exports cleanly to CSV / JSONL / Parquet. Keep the schema compatible with a future Postgres migration by avoiding SQLite-specific types.

## Simple Batch Runner

In the MVP, avoid Redis, Celery, Temporal, or async workers:

```bash
acf generate-tasks --n 100 --strategy template
acf run-batch --limit 100 --model claude-haiku-4-5-20251001
acf profiles --update
acf calibration
```

A task queue can be added in Phase 6 if batch execution becomes too slow.
