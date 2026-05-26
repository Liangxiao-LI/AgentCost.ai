# Agent Cost Forecaster

> **Know what your AI agent will cost — before it runs.**

A logging-first cost profiler and budget guard for tool-using AI agents.

---

## Architecture

AgentCost.ai is a **local-first cost observability and governance pipeline** for AI agents. It intercepts LLM and tool calls with a 1-line SDK change, logs structured traces to local SQLite, builds empirical p50/p90 cost profiles, and predicts + guards run cost before execution. An optional future layer enables anonymized community benchmarking. The public repo covers Layers 1–5. Layer 6 is opt-in, future, and private.

> **Color key:** 🔵 Blue = existing agent runtime &nbsp;·&nbsp; 🟢 Green = AgentCost SDK (current OSS) &nbsp;·&nbsp; 🟡 Yellow = local storage &nbsp;·&nbsp; 🟣 Purple = analytics & governance (current OSS) &nbsp;·&nbsp; 🔴 Red = future cloud layer (Phase 5+, opt-in) &nbsp;·&nbsp; `──→` solid = current data flow (numbered) &nbsp;·&nbsp; `- -→` dashed = optional / future sync

```mermaid
%%{init: {'theme': 'base', 'themeVariables': {'primaryColor': '#f0f9ff', 'primaryTextColor': '#1e3a5f', 'primaryBorderColor': '#93c5fd', 'lineColor': '#64748b'}}}%%
flowchart TD

    classDef rt   fill:#dbeafe,stroke:#3b82f6,color:#1e3a5f
    classDef sdk  fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef sto  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef ana  fill:#ede9fe,stroke:#7c3aed,color:#4c1d95
    classDef cld  fill:#fee2e2,stroke:#dc2626,color:#7f1d1d
    classDef note fill:#f8fafc,stroke:#94a3b8,color:#334155,stroke-dasharray: 3 3

    subgraph L1["LAYER 1 · Developer & Agent Runtime"]
        DEV(["👤 Developer / Agent Builder"])
        AGENT["Existing AI Agent\nExample: Claude Code"]
        TOOLS["Agent Tool Calls\nExample: web_search"]
    end

    subgraph L2["LAYER 2 · SDK Instrumentation · 1-line code change"]
        direction LR
        A1["acf/integrations/anthropic.py\nDrop-in Anthropic SDK wrapper"]
        A2["acf/integrations/openai.py\nDrop-in OpenAI SDK wrapper"]
        A3["acf.patch()\nGlobal monkey-patch"]
        A4["acf.track()\nPer-session context manager"]
    end

    subgraph L3["LAYER 3 · Local Observability Core"]
        direction LR
        subgraph L3A[" "]
            direction TB
            EXE["executor.py"]
            EXE_N["File goal: Executor Wrapper\nWhat it does: capture per call\nExample capture: input/output tokens"]
        end
        subgraph L3B[" "]
            direction TB
            LOG["logger.py"]
            LOG_N["File goal: Event Logger\nWhat it does: normalize into traces\nExample compute: api_equivalent_cost_usd"]
        end
        subgraph L3C[" "]
            direction TB
            PRC["pricing.py"]
            PRC_N["File goal: Pricing Resolver\nWhat it does: snapshot token rates\nExample rate: per-1M token price"]
        end
    end

    subgraph L4["LAYER 4 · Local Storage"]
        direction LR
        subgraph L4A[" "]
            direction TB
            SQ[("SQLite ~/.acf/acf.db")]
            SQ_N["File goal: local cost-data store\nRecommended: local dev / OSS\nExample table: agent_runs"]
        end
        subgraph L4B[" "]
            direction TB
            PG[("PostgreSQL agentcost_engine_db")]
            PG_N["File goal: hosted DB for engine\nRecommended: production\nMigrate when: team or >100k runs"]
        end
    end

    subgraph L5["LAYER 5 · Analytics, Profiling & Governance"]
        direction LR
        subgraph L5A[" "]
            direction TB
            PRF["profiler.py"]
            PRF_N["File goal: Profiler\nWhat it does: build p50/p90 distributions\nExample metric: cost per model × tool"]
        end
        subgraph L5B[" "]
            direction TB
            PRD["predictor.py"]
            PRD_N["File goal: Cost Predictor\nWhat it does: pre-run p50/p90 estimate\nExample output: prediction_id + p90 USD"]
        end
        subgraph L5C[" "]
            direction TB
            BGD["Budget Guard"]
            BGD_N["Lives in: predictor.py\nWhat it does: gate execution by p90\nExample status: blocked"]
        end
        subgraph L5D[" "]
            direction TB
            CLI["acf CLI"]
            CLI_N["Component goal: user-facing commands\nWhat it does: run / inspect / predict\nExample command: acf predict"]
        end
        subgraph L5E[" "]
            direction TB
            DSH["acf dashboard (future)"]
            DSH_N["Component goal: visualize spend + traces\nWhat it does: charts + budget status\nExample stack: Streamlit MVP"]
        end
        subgraph L5G[" "]
            direction TB
            GLOSS["Glossary"]
            GLOSS_N["p50 = median estimate (50th percentile)\np90 = pessimistic estimate (90th percentile)\nhistorical tool_calls = past tool-call rows\nlogged in SQLite — the empirical sample"]
        end
    end

    subgraph L6["LAYER 6 · Community Benchmarking (opt-in, future)"]
        direction LR
        subgraph L6A[" "]
            direction TB
            ANO["acf/sync/"]
            ANO_N["Component goal: anonymized sync client\nWhat it does: upload aggregates only\nExample upload: token counts"]
        end
        subgraph L6B[" "]
            direction TB
            ING["Ingestion API"]
            ING_N["Component goal: receive contributor data\nWhat it does: token-auth FastAPI receiver\nExample route: POST /v1/ingest"]
        end
        subgraph L6C[" "]
            direction TB
            QUE["Buffer Queue"]
            QUE_N["Component goal: decouple ingest spikes\nWhat it does: buffers raw events\nExample stack: AWS SQS"]
        end
        subgraph L6D[" "]
            direction TB
            ELK[("Raw Event Lake")]
            ELK_N["Storage goal: archive anonymized events\nWhat it stores: Parquet, admin-only read\nExample path: s3://agentcost-community-logs/"]
        end
        subgraph L6E[" "]
            direction TB
            BLD["Profile Builder"]
            BLD_N["Component goal: nightly batch aggregator\nWhat it does: p50/p90 per model × tool\nExample runtime: AWS Lambda"]
        end
        subgraph L6F[" "]
            direction TB
            ART[("Shared Profile Store")]
            ART_N["Storage goal: publish shared profiles\nWhat it stores: public p50/p90 artifacts\nExample path: s3://agentcost-profile-artifacts/"]
        end
        subgraph L6G[" "]
            direction TB
            PUB["Community Profiles API"]
            PUB_N["Component goal: serve cold-start fallback\nWhat it does: returns shared profiles\nExample route: GET /v1/community/profiles"]
        end
    end

    %% ── Flows 1–3: agent runs, calls tools, SDK intercepts ──
    DEV -->|"① run agent"| AGENT
    AGENT -->|"② call LLMs + tools"| TOOLS
    AGENT -->|"③ SDK intercepts LLM calls"| A1
    AGENT -->|"③ or via global patch"| A3
    TOOLS -->|"③ SDK intercepts tool calls"| A1

    %% ── Flows 4–6: capture → normalize → store ──
    A1 -->|"④ observe each call"| EXE
    A2 -->|"④"| EXE
    A3 -->|"④"| EXE
    A4 -->|"④"| EXE
    EXE -->|"⑤ normalize + compute cost"| LOG
    PRC -.->|"token rates"| LOG
    LOG -->|"⑥ write structured trace"| SQ

    %% ── Flows 7–9: profile → predict → govern ──
    SQ -->|"⑦ read historical tool_calls"| PRF
    PRF -->|"updated p50/p90 profiles"| PRD
    SQ -->|"load profiles + pricing"| PRD
    PRD -->|"⑧ p50/p90 estimate + cost drivers"| BGD
    BGD -->|"should_execute + budget status"| CLI
    SQ -->|"⑨ query traces, costs, profiles"| CLI
    CLI --> DSH

    %% ── Flows 10–12: optional anonymized community sync ──
    SQ -->|"⑩ opt-in: read pending sync rows"| ANO
    ANO -.->|"⑩ anonymized aggregates only"| ING
    ING -.-> QUE -.-> ELK
    ELK -.->|"⑪ nightly aggregate build"| BLD
    BLD -.-> ART -.-> PUB
    PUB -.->|"⑫ download cold-start profiles"| SQ

    %% ── Color assignments ──
    class DEV,AGENT,TOOLS rt
    class A1,A2,A3,A4 sdk
    class EXE,LOG,PRC sdk
    class EXE_N,LOG_N,PRC_N note
    class SQ,PG sto
    class SQ_N,PG_N note
    class PRF,PRD,BGD,CLI,DSH,GLOSS ana
    class PRF_N,PRD_N,BGD_N,CLI_N,DSH_N,GLOSS_N note
    class ANO,ING,QUE,ELK,BLD,ART,PUB cld
    class ANO_N,ING_N,QUE_N,ELK_N,BLD_N,ART_N,PUB_N note
```

> _`predictor.py` lives in the public repo during M1–M4 (rule-based, fully local). Extracted to `agentcost-engine` at Phase 5 after M4 user validation. See [docs/05-architecture.md](docs/05-architecture.md) for the extraction plan._

**Public vs Private Boundary**

| Layer | Location | Status | Contains | Must NOT contain |
|---|---|---|---|---|
| SDK + CLI (Layers 2–5) | `AgentCost.ai` (this repo) | MVP — active | Instrumentation wrappers, executor, logger, profiler, local predictor, budget guard, all CLI commands | Cloud infra, ML router, paid API keys |
| Local SQLite | `~/.acf/acf.db` (user machine) | MVP — active | Token counts, tool calls, source URLs, API-equivalent cost, tool profiles, agent configs | Raw prompt text (salted-hashed before write), raw tool output text |
| Local config | `config/agent_config.yaml` | MVP — active | Model name, tools list, temperature, budget limits, privacy mode | API keys — use `ANTHROPIC_API_KEY` env var |
| Optional sync client | `acf/sync/` (this repo) | Dry-run MVP → live Phase 5+ | Anonymized: token counts, model, tool names, source domains, salted prompt hash | Raw prompts, tool arguments, result content, full source URLs |
| Private engine | `agentcost-engine` (separate repo) | Phase 5+ — not yet built | Hosted prediction API, ML router, community profile aggregation, PostgreSQL metadata DB | All raw user data — always stays local |
| Community data lake | `s3://agentcost-community-logs/` | Phase 5+ — planned | Anonymized JSONL/Parquet, admin-only read, queried via AWS Glue + Athena | Raw prompts, tool outputs, full URLs, contributor identifiers |
| Shared profile artifacts | `s3://agentcost-profile-artifacts/` | Phase 5+ — planned | Published p50/p90 per (tool × model), downloaded by SDK on startup as cold-start fallback | Individual run records, raw contributor data |

---

## Execution Lifecycle

```mermaid
sequenceDiagram
    actor Dev as Developer
    participant CLI as acf CLI
    participant PRED as predictor.py
    participant DB as SQLite
    participant EXE as executor.py
    participant TOOL as Tool
    participant LOG as logger.py
    participant PROF as profiler.py

    Dev->>CLI: acf predict "Find Nvidia revenue"
    CLI->>DB: load tool_profiles + model_pricing
    DB-->>PRED: p50/p90 profiles
    CLI->>PRED: predict(prompt, tools_exposed, budget)
    PRED->>PRED: token estimator → price estimator
    PRED-->>CLI: p50=$0.003  p90=$0.006  budget=warning
    CLI-->>Dev: prediction_id · cost estimate · budget status

    alt should_execute = true (safe or warning)
        Dev->>CLI: acf run "..." --prediction-id pred_001
        CLI->>EXE: execute(prompt, agent_config)
        EXE->>TOOL: observed_tool_call(web_search, query)
        TOOL-->>EXE: result + source_urls + result_tokens_raw=2200
        EXE->>LOG: record model_calls + tool_calls (result_tokens_inserted=900)
        LOG->>DB: write agent_runs · model_calls · tool_calls
        EXE-->>CLI: actual_api_equivalent_cost=$0.0043
        CLI->>PROF: acf profiles --update
        PROF->>DB: recompute p50/p90 from tool_calls
        Dev->>CLI: acf calibration
        CLI->>DB: compare predicted vs actual across runs
        CLI-->>Dev: p90_coverage=0.93 ✓  underestimation_rate=0.07 ✓
    else should_execute = false (blocked)
        CLI-->>Dev: BLOCKED — p90 exceeds budget limit
        Note over Dev,CLI: Run acf suggest-tools to reduce cost
    end
```

---

## How it works

1. **Instrument** — wrap your agent runtime with one line: import `acf/integrations/anthropic.py` (Mode A), call `acf.patch()` globally (Mode B), or use `acf.track()` context manager (Mode C)
2. **Log** — run `acf run`; `executor.py` captures every token count, tool call, and source URL via the `observed_tool_call` wrapper
3. **Store** — all structured traces are written locally to SQLite at `~/.acf/acf.db`; zero infrastructure required
4. **Profile** — run `acf profiles --update`; `profiler.py` computes empirical p50/p90 distributions per tool × model from logged `tool_calls`
5. **Predict** — run `acf predict` before execution; returns a p50/p90 cost estimate and `prediction_id` in under 200ms — no model call made
6. **Budget guard** — `predictor.py` returns `should_execute` (boolean), `status` (`safe / warning / blocked`), and the top cost drivers; your agent uses this to gate execution
7. **Calibrate** — run `acf calibration`; compares predicted vs actual across all held-out runs, targeting `p90_coverage ≥ 0.90` and `underestimation_rate ≤ 0.10`
8. **Sync (optional, Phase 5+)** — opt-in anonymized sync sends only token counts, model name, tool names, and source domains — never raw prompts or outputs — to the community data lake; shared p50/p90 profiles are downloaded on startup to improve cold-start predictions

**Two-repo structure:**

| Repo | What | Status |
|---|---|---|
| `AgentCost.ai` (this repo) | Open-source SDK: instrumentation, logging, profiling, local prediction, CLI | Active — contribute here |
| `agentcost-engine` (separate private repo) | Hosted prediction engine, ML router, community server, data lake | Phase 5+ — not yet built |

---

## How to Contribute

**The most valuable contribution: run the SDK.**
Every batch you run adds real execution data. Your anonymized token statistics (never raw text or prompts) flow to the community data lake and improve shared p50/p90 profiles for all tools — making cold-start predictions better for every new contributor.

**Code contributions (this repo):**
- `data/seed_templates.yaml` — add diverse prompts across `web_search`, `calculator`, `no_tool`, `ambiguous`
- `acf/integrations/` — add wrappers for new SDKs (OpenAI, Gemini, Mistral)
- `profiler.py` — improve p50/p90 profile computation or add new metrics
- `acf/sync/anonymizer.py` — strengthen privacy guarantees

Open an issue before starting any significant change.

---

## The Problem

Running a tool-using AI agent is expensive in ways that are hard to predict:

- **Tool schemas cost tokens** — every tool schema passed to the model is paid for on every call, even if the model never uses that tool.
- **Result size is variable** — a `web_search` can return 300 tokens or 3,000 tokens depending on the query.
- **Multi-step agents compound cost** — each tool call feeds results back into the next model call; costs multiply across turns.
- **Subscription billing hides the signal** — Claude Code Pro is a flat subscription, so you cannot see per-run cost without computing it yourself from token counts.

Agent Cost Forecaster solves this by logging everything, profiling the distributions, and returning a p50/p90 cost estimate before the agent runs.

---

## How It Works

```
Stage 1 — Log:      acf run              → observe model calls + tool calls → log tokens, URLs, api_equivalent_cost_usd
Stage 2 — Profile:  acf profiles         → compute p50/p90 per tool and prompt category
Stage 3 — Predict:  acf predict          → estimate cost from empirical profiles → apply budget guard
Stage 4 — Validate: acf run-batch --heldout → compare predicted vs actual → p90 coverage
```

**Logging comes first.** Before any real prediction, you need at least 100 logged runs. The system surfaces this constraint explicitly — there are no fake numbers before data exists.

---

## Quick Start

```bash
git clone https://github.com/Liangxiao-LI/AgentCost.ai.git
cd AgentCost.ai
pip install -r requirements.txt

# Set your Anthropic API key and prompt hash salt
export ANTHROPIC_API_KEY=sk-ant-...
export PROMPT_HASH_SALT=your-random-salt

# Configure your target agent
cp config/agent_config.yaml.example config/agent_config.yaml
# Edit: model, system_prompt, tools, budget limits

# Run a single prompt and log the result
acf run "Find the latest Nvidia quarterly revenue." --log

# Generate synthetic tasks and run a batch
acf generate-tasks --n 100 --strategy template
acf run-batch --limit 100 --model claude-haiku-4-5-20251001

# Build empirical profiles from logs
acf profiles --update

# Predict cost for a new prompt
acf predict "Find Nvidia's latest revenue and calculate YoY growth."

# Check calibration
acf calibration
```

---

## CLI Reference

```bash
# Predict cost before running
acf predict "..."
acf predict "..." --model claude-sonnet-4-6 --tools web_search,calculator --budget 0.05

# Run a single task and log it
acf run "..." --log

# Batch operations
acf generate-tasks --n 100 --strategy template
acf run-batch --limit 100 --model claude-haiku-4-5-20251001
acf loop --n 100 --update-profiles            # generate + run + update in one step

# Inspect results
acf profiles --update
acf profiles --show
acf compare --run-id run_001                  # predicted vs actual for a run
acf trace --run-id run_001                    # full model call → tool call chain
acf sources --run-id run_001                  # source domains used

# Optimization
acf suggest-tools "Find Nvidia earnings and calculate YoY growth"

# Calibration
acf calibration

# Export
acf export --format jsonl --output ./data/training.jsonl
```

Output is a readable table by default. Pass `--json` for raw JSON output.

---

## Key Concepts

### API-Equivalent Cost vs. Cash Cost

All profiling, p50/p90 estimation, calibration, and budget guard comparisons use **API-equivalent imputed cost** (`api_equivalent_cost_usd`): token counts × provider public pricing, regardless of billing arrangement.

Under Claude Code Pro subscription, the marginal per-run cash cost is zero. The system tracks this separately in `actual_cash_cost_usd`. Every run carries a `billing_mode` and `cost_basis` field so the distinction is never ambiguous.

```
api_equivalent_cost_usd =
    input_tokens / 1M × input_price_per_1m
  + output_tokens / 1M × output_price_per_1m
  + cache_read_tokens / 1M × cache_read_price_per_1m
  + cache_write_tokens / 1M × cache_write_price_per_1m
```

### Tool Schema Tokens — The Hidden Cost

Schema tokens are paid for **all exposed tools** on every model call, whether or not the model uses them. A caller passing 15 tool schemas "just in case" pays ~2,000 tokens per call for schemas the model never touches.

Agent Cost Forecaster always lists `tool_schema_tokens` first in its cost driver output and can suggest a minimal tool set for any prompt:

```
acf suggest-tools "Find Nvidia latest earnings and calculate YoY growth"

Recommended exposed tools: web_search, calculator
Do not expose: file_search (not predicted for this prompt type)
Estimated schema token saving: 380 tokens
```

### Budget Guard

Every `acf predict` call returns a budget decision with a clear boolean gate:

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

`status` values: `safe` / `warning` / `blocked` / `unknown`

### Calibration Target

The two primary metrics are:

| Metric | Target |
|--------|--------|
| `p90_coverage` | ≥ 0.90 — fraction of runs where actual cost ≤ p90 estimate |
| `underestimation_rate` | ≤ 0.10 — fraction of runs where actual cost > p90 |

`acf calibration` prints both metrics with per-tool breakdown.

### Traceability

Every prediction and execution is linked by a shared `trace_id`:

```
trace_id
  → prediction_id      (pre-run estimate)
  → run_id             (execution)
      → model_call_id  (each model API call)
          → tool_call_id (each tool invocation)
```

`acf trace --run-id run_001` renders the full chain in the terminal.

---

## Target Agent: Claude Code

The first target runtime is Claude Code, instrumented via the Anthropic Python SDK. The system calls the same Claude models Claude Code uses, routes all tool calls through an observed wrapper, and logs every `messages.create()` call.

Tools in the MVP:
- `web_search` — high variance result size; the most interesting tool to profile
- `calculator` — deterministic; acts as a control
- `no_tool` — tests false positive suppression

MCP tool wrapping is deferred to Milestone 2.

### Pricing Reference (API-equivalent, per 1M tokens)

| Model | Input | Output | Cache Read | Cache Write |
|-------|-------|--------|------------|-------------|
| `claude-haiku-4-5-20251001` | $0.80 | $4.00 | $0.08 | $1.00 |
| `claude-sonnet-4-6` | $3.00 | $15.00 | $0.30 | $3.75 |

---

## Privacy

Default privacy mode: `synthetic_only` — full data for synthetic runs, hashed metadata only for production runs.

Production prompt text is hashed with a salted SHA-256 before storage. Source URLs are always stored. `result_tokens_raw` and `result_tokens_inserted` are always stored regardless of privacy mode — they contain no raw text.

| Mode | Behavior |
|------|----------|
| `off` | Store everything. Local development only. |
| `hash_only` | Hashes and metadata; no raw text. |
| `redact_pii` | Remove emails, names, phone numbers. |
| `synthetic_only` | Full data for synthetic; metadata only for production. |

---

## Data Storage

SQLite for the MVP. Zero infrastructure, trivial to back up, exports cleanly to CSV/JSONL/Parquet. Schema is Postgres-compatible for a future migration.

Core tables: `predictions`, `agent_runs`, `model_calls`, `tool_calls`, `tool_profiles`, `model_pricing`, `agent_configs`.

---

## Six-Week Roadmap

| Week | Deliverable |
|------|-------------|
| 1 | Logging infrastructure: SQLite schema, executor, `acf run` |
| 2 | Batch logging: 100 runs end-to-end, source URL tracking (**Milestone 1**) |
| 3 | Empirical profiles: p50/p90 per tool, `acf trace`, `acf sources` (**Milestone 2**) |
| 4 | First prediction mode: `acf predict`, budget guard, cost drivers |
| 5 | Held-out evaluation: p90 coverage ≥ 0.90 on new prompts (**Milestone 3**) |
| 6 | User validation: CLI polish, demo, 10 conversations with agent builders |

Everything else — FastAPI, Postgres, embedding router, ML classifier, dashboard — is deferred until after Milestone 3 is validated with real users.

---

## Technical Docs

Full technical design is in the [`docs/`](docs/) folder: data model, module reference, API design, calibration pipeline, and design principles.
