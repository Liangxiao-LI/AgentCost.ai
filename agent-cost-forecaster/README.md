# Agent Cost Forecaster

A logging-first cost profiler and budget guard for Claude Code.

**Current stage: Milestone 1 — Observability**

> Run 100 prompts through Claude. Produce complete, traceable logs for every
> model call, tool call, token count, source URL, and cost.

---

## What this does

Instruments a real Claude agent (`claude-haiku-4-5-20251001` or `claude-sonnet-4-6`)
with `web_search` and `calculator` tools. Every model call and every tool call is
intercepted by an observer wrapper, logged to SQLite, and verifiable.

```
acf run "prompt"
  → Anthropic messages.create()
  → observed_tool_call wrapper (for each tool_use block)
  → log model_calls  (input/output/cache tokens, cost, stop_reason)
  → log tool_calls   (result tokens, source URLs, domains, latency)
  → SQLite: data/acf.db
```

No ML, no prediction yet — just ground-truth execution data that will drive
empirical profiles in Milestone 2.

---

## Setup

### 1. Prerequisites

- Python 3.11+
- An Anthropic API key

### 2. Create virtual environment and install

```bash
cd agent-cost-forecaster

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -e .
```

### 3. Set your API key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### 4. Select the Python interpreter in VSCode

Open the Command Palette → **Python: Select Interpreter** → choose
`.venv/bin/python` inside this folder. This clears the "package not installed"
hints in the editor.

### 5. (Optional) Change model

Edit `config/agent_config.yaml`. Default is `claude-haiku-4-5-20251001` (cheapest).
Switch to `claude-sonnet-4-6` to profile your real workload.

---

## Milestone 1: Observability Check

Follow these steps in order. By the end you should have 100+ complete, traceable
runs in SQLite and pass every integrity check.

### Step 1 — Smoke test: run one prompt

```bash
acf run "What is 15 percent of 2500?"
```

Expected: agent calls `calculator`. Output shows run ID, tool call count, tokens, cost.

```bash
acf run "Find the latest Nvidia quarterly revenue."
```

Expected: agent calls `web_search`. Source domains appear in the output.

### Step 2 — Inspect the trace

```bash
acf trace <run-id>
```

Shows every model call and tool call in the chain:

| Column | Meaning |
|--------|---------|
| `input` | Total input tokens for this model call |
| `cache_read` | Tokens served from prompt cache (cheaper rate) |
| `cache_write` | Tokens written to cache |
| `schema_tok` | Estimated tokens consumed by tool schemas |
| `tool_result_tok` | Tokens from preceding tool results (0 for call 0) |
| `stop_reason` | `end_turn` = final answer, `tool_use` = more tool calls needed |

**What to verify:**
- Last model call has `stop_reason = end_turn`
- `tool_result_tok` on the second model call is > 0 (search result was passed back)
- Each `web_search` call shows `traceability = full`

### Step 3 — Inspect source URLs

```bash
acf sources <run-id>
```

Shows which domains and URLs were returned and inserted by each tool call.
Every `web_search` call should show `full` traceability and at least one domain.

### Step 4 — Generate seed tasks

```bash
acf generate-tasks --n 3
```

Expands `data/seed_templates.yaml` into `data/seed_tasks.jsonl`.
Each template gets 3 variable substitutions. Result: ~100–120 tasks across:

| Category | Target |
|----------|--------|
| `web_search_required` | Profile search result token sizes |
| `calculator_required` | Profile deterministic tool behaviour |
| `no_tool_required` | Test false-positive suppression |
| `ambiguous` | Test router robustness |

```bash
head -3 data/seed_tasks.jsonl | python -m json.tool   # sanity check
```

### Step 5 — Dry run (10 tasks)

```bash
acf run-batch --limit 10
```

Watch for failures (red ✗). If web_search returns empty results, DuckDuckGo
may be rate-limiting — wait 30 seconds and retry.

### Step 6 — Full 100-task batch

```bash
acf run-batch
```

At `claude-haiku-4-5-20251001` prices, 100 tasks typically cost **$0.05–$0.20**.
Press `Ctrl-C` to stop early — completed runs are already logged.

### Step 7 — Verify log integrity

```bash
acf check
```

Six integrity checks:

| Check | What it catches |
|-------|----------------|
| Successful runs logged | At least one run completed |
| Token sum mismatches | `Σ model_calls.input_tokens ≠ agent_runs.actual_input_tokens` |
| Missing `result_tokens_inserted` | Tool call result not counted |
| Missing `source_traceability_status` | Metadata extraction failed |
| `web_search` with no source domains | URL parsing failed |

**Milestone 1 is complete when `acf check` passes with zero failures and
`≥ 100` successful runs are logged.**

### Step 8 — Query the database directly

```bash
sqlite3 data/acf.db
```

**Run summary:**
```sql
SELECT source,
       COUNT(*) AS runs,
       ROUND(AVG(actual_input_tokens), 0)  AS avg_input,
       ROUND(AVG(actual_output_tokens), 0) AS avg_output,
       ROUND(SUM(actual_total_cost_usd), 4) AS total_cost_usd
FROM agent_runs
WHERE success = 1
GROUP BY source;
```

**Tool call breakdown:**
```sql
SELECT tool_name,
       COUNT(*)                                  AS calls,
       ROUND(AVG(result_tokens_raw), 0)          AS avg_raw_tok,
       ROUND(AVG(result_tokens_inserted), 0)     AS avg_ins_tok,
       SUM(was_result_truncated)                 AS truncated,
       source_traceability_status
FROM tool_calls
WHERE success = 1
GROUP BY tool_name, source_traceability_status;
```

**Token sum integrity check (must return zero rows):**
```sql
SELECT r.run_id,
       r.actual_input_tokens        AS run_total,
       SUM(m.input_tokens)          AS mc_total,
       r.actual_input_tokens - SUM(m.input_tokens) AS discrepancy
FROM agent_runs r
JOIN model_calls m ON r.run_id = m.run_id
WHERE r.success = 1
GROUP BY r.run_id
HAVING discrepancy != 0;
```

**Cache token usage:**
```sql
SELECT model,
       SUM(cache_read_input_tokens)  AS total_cache_reads,
       SUM(cache_write_input_tokens) AS total_cache_writes,
       SUM(input_tokens)             AS total_input
FROM model_calls
GROUP BY model;
```

**Top source domains:**
```sql
SELECT d.value AS domain, COUNT(*) AS appearances
FROM tool_calls tc, json_each(tc.source_domains) AS d
WHERE tc.tool_name = 'web_search' AND tc.success = 1
GROUP BY d.value
ORDER BY appearances DESC
LIMIT 20;
```

---

## CLI reference

```bash
# Single run
acf run "Find the latest Apple revenue."
acf run "Calculate 22 percent of 1000."
acf run "Explain what a P/E ratio is."           # should use no tool
acf run "..." --source production                # sets quality score to 1.0

# Batch
acf generate-tasks                               # default: 3 expansions/template
acf generate-tasks --n 5                         # more variety
acf run-batch                                    # all tasks in seed_tasks.jsonl
acf run-batch --limit 20                         # first 20 only

# Inspection
acf trace <run-id>                               # model call + tool call chain
acf sources <run-id>                             # source URLs and domains

# Integrity
acf check                                        # verify all logs are complete
```

---

## Project structure

```
agent-cost-forecaster/
├── app/
│   ├── db.py              ← SQLite schema + connection factory
│   ├── pricing.py         ← Claude model pricing; compute_cost()
│   ├── tool_registry.py   ← Anthropic tool schemas; web_search + calculator implementations
│   ├── logger.py          ← All DB write operations
│   ├── executor.py        ← Anthropic agent loop + observed_tool_call wrapper
│   └── cli.py             ← acf CLI entry point
├── config/
│   └── agent_config.yaml  ← Target agent (model, tools, truncation, budget)
├── data/
│   ├── seed_templates.yaml  ← Prompt templates with variable substitution
│   └── seed_tasks.jsonl     ← Generated (after acf generate-tasks)
├── scripts/
│   └── generate_tasks.py    ← Standalone equivalent of acf generate-tasks
├── pyproject.toml
├── requirements.txt
└── .env.example
```

---

## Tools

| Tool | Implementation | API key needed |
|------|---------------|----------------|
| `web_search` | DuckDuckGo (`duckduckgo-search`) | No |
| `calculator` | Safe AST evaluator | No |
| LLM | Anthropic API (`anthropic` SDK) | Yes — `ANTHROPIC_API_KEY` |

DuckDuckGo is free and requires no key. It may rate-limit under heavy batch loads.
If you see empty search results, wait 30s between retries, or reduce `--limit`.

---

## Milestone progression

| Milestone | Gate | Week |
|-----------|------|------|
| **M1 — Observability** | `acf check` passes; ≥ 100 runs logged | 1–2 |
| M2 — Profiles | p50/p90 built per tool and prompt category | 3 |
| M3 — Prediction quality | Held-out p90 coverage ≥ 0.90 | 5 |
