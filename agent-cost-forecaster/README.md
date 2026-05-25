# Agent Cost Forecaster

A logging-first cost profiler and budget guard for tool-using AI agents.

**Current stage: Milestone 1 — Observability**

> Run 100 prompts through a real agent. Produce complete, traceable logs for every
> model call, tool call, token count, source URL, and cost.

---

## What this does

Instruments a real OpenAI agent with `web_search` and `calculator` tools.
Every model call and every tool call is intercepted, logged to SQLite, and
verifiable. No ML, no prediction yet — just ground-truth execution data.

```
acf run "prompt"
  → observed_tool_call wrapper
  → log model_calls (input/output/cached tokens, cost)
  → log tool_calls  (result tokens, source URLs, domains, latency)
  → SQLite: data/acf.db
```

---

## Setup

### 1. Prerequisites

- Python 3.11+
- An OpenAI API key

### 2. Install

```bash
cd agent-cost-forecaster

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -e .
```

### 3. Set your API key

```bash
export OPENAI_API_KEY="sk-..."
```

### 4. (Optional) Change model or settings

Edit `config/agent_config.yaml`. Default model is `gpt-4o-mini`.

---

## Milestone 1: Observability Check

Follow these steps in order. By the end you should have 100+ complete, traceable
runs in SQLite and pass every integrity check.

### Step 1 — Smoke test: run one prompt

```bash
acf run "What is 15 percent of 2500?"
```

Expected output: a table showing run ID, trace ID, tool calls, tokens, cost.
The agent should call `calculator`.

```bash
acf run "Find the latest Nvidia quarterly revenue."
```

Expected: agent calls `web_search`. You'll see source domains in the output.

### Step 2 — Inspect the trace

Copy the run ID from the output above, then:

```bash
acf trace <run-id>
```

This shows every model call and tool call in the trace chain:

- Each model call: input tokens, output tokens, cached tokens, schema tokens,
  tool result tokens inserted, finish reason, cost
- Each tool call: raw tokens, inserted tokens, was it truncated, source
  traceability status, latency

**What to verify:**
- `finish_reason` of the last model call is `stop`
- `tool_result_tokens_inserted` on the second model call is > 0 (the search
  result was actually passed back to the model)
- Each tool call shows `source_traceability_status = full` for web_search

### Step 3 — Inspect source URLs

```bash
acf sources <run-id>
```

Shows which domains and URLs were returned and inserted by each tool call.
`web_search` calls should show `full` traceability and at least one domain.

### Step 4 — Generate seed tasks

```bash
acf generate-tasks --n 3
```

This expands `data/seed_templates.yaml` into `data/seed_tasks.jsonl`.
Each template is expanded 3 times with different variable substitutions.
You get roughly 100–120 tasks covering:

| Category | Purpose |
|----------|---------|
| `web_search_required` | Profile search result sizes |
| `calculator_required` | Profile deterministic tool behavior |
| `no_tool_required` | Test false positive suppression |
| `ambiguous` | Test router robustness |

Inspect the file to confirm variety:
```bash
head -5 data/seed_tasks.jsonl | python -m json.tool
```

### Step 5 — Run 10 tasks first (dry run)

Before committing to 100, run a small batch to confirm everything works:

```bash
acf run-batch --limit 10
```

Watch the output. Each line shows: category, prompt snippet, tools called,
cost per task. Failures are printed in red with the error.

### Step 6 — Run the full 100-task batch

```bash
acf run-batch
```

This runs all tasks in `data/seed_tasks.jsonl` sequentially.
At gpt-4o-mini prices, 100 tasks typically cost $0.05–$0.20 total.

To stop early: `Ctrl-C`. Completed runs are already logged.

### Step 7 — Verify log integrity

```bash
acf check
```

This runs six checks against the database:

| Check | Meaning |
|-------|---------|
| Successful runs logged | At least one run completed |
| Token sum mismatches | `Σ model_calls.input_tokens == agent_runs.actual_input_tokens` for every run |
| Tool calls missing `result_tokens_inserted` | Every successful tool call must have this field |
| Tool calls missing `source_traceability_status` | Every tool call must have a status |
| `web_search` calls with no source domains | Every web_search result must have domains |

**Milestone 1 is complete when `acf check` passes with zero failures and you
have ≥ 100 successful runs.**

### Step 8 — Spot-check the database directly

```bash
sqlite3 data/acf.db
```

Useful queries:

```sql
-- Run summary
SELECT
    source,
    COUNT(*) AS runs,
    ROUND(AVG(actual_input_tokens), 0) AS avg_input_tok,
    ROUND(AVG(actual_output_tokens), 0) AS avg_output_tok,
    ROUND(SUM(actual_total_cost_usd), 4) AS total_cost_usd
FROM agent_runs
WHERE success = 1
GROUP BY source;

-- Tool call summary by tool
SELECT
    tool_name,
    COUNT(*) AS calls,
    ROUND(AVG(result_tokens_raw), 0) AS avg_raw_tok,
    ROUND(AVG(result_tokens_inserted), 0) AS avg_inserted_tok,
    ROUND(AVG(latency_ms), 0) AS avg_latency_ms,
    SUM(was_result_truncated) AS truncated_count,
    source_traceability_status
FROM tool_calls
WHERE success = 1
GROUP BY tool_name, source_traceability_status;

-- Token sum integrity check (must return zero rows)
SELECT
    r.run_id,
    r.actual_input_tokens AS run_total,
    SUM(m.input_tokens) AS model_calls_total,
    r.actual_input_tokens - SUM(m.input_tokens) AS discrepancy
FROM agent_runs r
JOIN model_calls m ON r.run_id = m.run_id
WHERE r.success = 1
GROUP BY r.run_id
HAVING discrepancy != 0;

-- Top source domains across all web_search calls
SELECT
    domain.value AS domain,
    COUNT(*) AS appearances
FROM tool_calls tc,
     json_each(tc.source_domains) AS domain
WHERE tc.tool_name = 'web_search' AND tc.success = 1
GROUP BY domain.value
ORDER BY appearances DESC
LIMIT 20;
```

---

## CLI reference

```bash
# Run one prompt
acf run "Find the latest Apple revenue."
acf run "Calculate 22 percent of 1000."
acf run "Explain what a P/E ratio is."       # should use no tool

# Run options
acf run "..." --source production             # changes quality score to 1.0
acf run "..." --config config/agent_config.yaml

# Batch
acf generate-tasks --n 5                     # more tasks per template
acf run-batch                                # run all tasks in seed_tasks.jsonl
acf run-batch --limit 20                     # run first 20 only

# Inspection
acf trace <run-id>                           # full model + tool call chain
acf sources <run-id>                         # source URLs and domains

# Integrity
acf check                                    # verify all logs are complete
```

---

## Project structure

```
agent-cost-forecaster/
├── app/
│   ├── db.py              ← SQLite schema + connection
│   ├── pricing.py         ← Static model pricing; cost computation
│   ├── tool_registry.py   ← Tool schemas, implementations (web_search, calculator)
│   ├── logger.py          ← All DB write operations
│   ├── executor.py        ← Agent loop + observed_tool_call wrapper
│   └── cli.py             ← acf CLI entry point
├── config/
│   └── agent_config.yaml  ← Target agent configuration
├── data/
│   ├── seed_templates.yaml  ← Prompt templates
│   └── seed_tasks.jsonl     ← Generated (after acf generate-tasks)
├── scripts/
│   └── generate_tasks.py    ← Standalone script (same as acf generate-tasks)
├── pyproject.toml
├── requirements.txt
└── .env.example
```

---

## Milestone progression

| Milestone | Gate | Status |
|-----------|------|--------|
| **M1 — Observability** | `acf check` passes; ≥ 100 runs logged | Week 1–2 |
| M2 — Profiles | p50/p90 profiles built per tool | Week 3 |
| M3 — Prediction quality | Held-out p90 coverage ≥ 0.90 | Week 5 |

---

## Tools used

| Tool | Implementation | API key needed |
|------|---------------|----------------|
| `web_search` | DuckDuckGo (via `duckduckgo-search`) | No |
| `calculator` | Safe AST-based evaluator | No |
| LLM | OpenAI Chat Completions | Yes (`OPENAI_API_KEY`) |

DuckDuckGo is free and requires no API key. It may rate-limit under heavy batch
loads. If you see empty search results, add a short delay between tasks or switch
to Tavily (set `TAVILY_API_KEY` and update `tool_registry.py`).
