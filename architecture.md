# Agent Cost Forecaster — Architecture

## Project Overview

Agent Cost Forecaster is a logging-first cost profiler and budget guard for tool-using AI agents. It instruments a real agent, observes every model call, tool call, token, source URL, and cost, and builds empirical p50/p90 profiles from those logs. Once enough runs are logged, those profiles drive cost predictions for future runs.

The system is self-improving because it continuously feeds new execution logs back into the profiling and calibration loop.

```
Stage 1 — Log:     acf run → observe model calls + tool calls → log tokens, URLs, cost
Stage 2 — Profile: acf profiles --update → compute p50/p90 per tool and prompt category
Stage 3 — Predict: acf predict → estimate cost from empirical profiles → apply budget guard
Stage 4 — Validate: acf run-batch --heldout → compare predicted vs actual → p90 coverage
```

This document is organized from smallest to largest: Founder Reality Check and MVP first, full scaled architecture second, long-term extensions last.

---

## Founder Reality Check

The long-term product is a self-improving cost forecasting system for tool-using AI agents. But for a solo founder, the first product should be:

> **A logging-first cost profiler and budget guard for tool-using AI agents.**

The first thing to prove is not perfect prediction. The first thing to prove is **reliable observability**.

Before any logs exist, prediction can only use conservative heuristics. Real prediction quality begins only after enough actual runs are logged and profiled. The core asset of the product is the traceable execution dataset — not the prediction algorithm.

This means the MVP is:

> **logging-first → profiling-second → prediction-third**

### Milestones

**Milestone 1 — Observability**
Run 100 prompts through a real target agent and produce complete, traceable logs for every model call, tool call, token count, source URL, and cost.

**Milestone 2 — Profiles**
Use those 100 logged runs to build empirical p50/p90 tool profiles — one distribution per tool, one per prompt category.

**Milestone 3 — Prediction quality**
Run a new held-out batch and show that predicted p90 cost captures 90%+ of actual costs.

Everything else — embedding routers, supervised classifiers, training datasets, dashboards — comes after Milestone 3 is proven.

### Product Positioning

- *See exactly what your agent costs while it runs.*
- *A logging-first cost profiler and budget guard for tool-using AI agents.*

### The Four-Stage MVP Loop

**Stage 1 — Logging loop**
```
acf run
→ observe model calls
→ observe tool calls
→ log token usage
→ log source URLs
→ log actual cost
```

**Stage 2 — Profiling loop**
```
acf profiles --update
→ compute p50/p90 per tool
→ compute p50/p90 per prompt category
→ compute average calls per tool
```

**Stage 3 — Prediction loop** *(requires Stage 2 data)*
```
acf predict
→ estimate cost from empirical profiles
→ return p50/p90
→ apply budget guard
→ explain cost drivers
```

**Stage 4 — Validation loop**
```
acf run-batch --heldout
→ compare predicted vs actual
→ calculate p90 coverage and underestimation rate
```

A solo founder working nights and weekends can complete all four stages in six weeks. Everything in this document that is not on that critical path is clearly marked as **later-stage**.

---

## Goals and Non-Goals

### Goals

- Estimate total agent run cost before execution (p50 and p90 ranges).
- Predict which tools an agent is likely to call, and how many times.
- Guard against budget overruns before the agent starts.
- Profile per-tool token cost empirically from real execution logs.
- Explain which components drive cost and how to reduce them.
- Build training data automatically via synthetic task generation.
- Improve prediction accuracy continuously through a closed calibration loop.
- Log execution data in a privacy-safe way by default.
- Track which external sources were used by each tool call.

### Non-Goals

- Not a billing system — does not charge users or integrate with payment processors.
- Not an agent framework — it instruments agent runtimes; it does not replace them.
- Not a model fine-tuner — models are treated as black boxes.
- Not a universal tokenizer — tokenization is delegated to model-specific libraries.
- Not a real-time latency predictor — latency is logged but is not the primary estimate target.

---

## Founder MVP Architecture

### Start With Two Tools Plus No-Tool

Do not try to support three or more tools from day one. Start with exactly:

1. **`web_search`** — high variance result size; the most interesting tool to profile
2. **`calculator`** — deterministic arguments and results; acts as a control
3. **`no_tool`** — not a real tool, but a task category for prompts that need no tool call

**Why these three and not `file_search`:**
- `web_search` gives high variance result size and is the most commercially relevant tool to profile.
- `calculator` gives deterministic, low-cost behavior that calibrates everything else.
- `no_tool` tests false positives and prevents unnecessary tool calls — essential for router calibration.
- `file_search` / RAG should be deferred: retrieval cost, chunking, and privacy issues make it significantly more complex. Do not add it until the basic predict → execute → log → profile loop is working.

### Five Core Modules

```
agent-cost-forecaster/
  app/
    tool_registry.py      ← ToolDefinition store + schema token counting
    predictor.py          ← routing + token estimation + price + budget guard
    executor.py           ← agent runner + tool call interception + token tracking
    logger.py             ← database writes for predictions, runs, model calls, tool calls
    profiler.py           ← p50/p90 profile computation + calibration summary
    pricing.py            ← model pricing table
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

### Module Consolidation Map

| Founder MVP module | Full-system modules it replaces |
|--------------------|--------------------------------|
| `predictor.py` | `router_predictor` + `token_estimator` + `price_estimator` |
| `executor.py` | `agent_executor` + `tool_call_observer` + `token_usage_tracker` + `cost_tracker` |
| `logger.py` | `run_logger` + database write operations |
| `profiler.py` | `cost_profiler` + `calibration` (summary) + profile updates |

When the product grows, split these into separate modules. Keep internal function boundaries clean so the split becomes a rename, not a rewrite.

### Use SQLite First

Do not start with Postgres unless there are real users, high concurrency, or more than 100k logged runs. SQLite requires zero infrastructure, is trivial to back up, easy to inspect locally, and exports cleanly to CSV / JSONL / Parquet. Keep the schema compatible with a future Postgres migration by avoiding SQLite-specific types.

### Use a Simple Batch Runner, Not a Task Queue

In the MVP, avoid Redis, Celery, Temporal, or async workers:

```bash
acf generate-tasks --n 100 --strategy template
acf run-batch --limit 100 --model gpt-4o-mini
acf profiles --update
acf calibration
```

A task queue can be added in Phase 6 if batch execution becomes too slow or needs parallelism.

---

## Target Agent Configuration

Agent Cost Forecaster does not create a new agent. It instruments a **target agent** — the real agent whose cost we want to predict and monitor. Before running anything, the founder must explicitly configure that target agent.

### First-Time Setup

The first configuration requires setting:

- `model` — which model the agent runs on
- `system_prompt` — the agent's identity and behavior guidelines
- `tools_exposed` — which tools are always passed to the model
- `temperature` and `max_tool_calls` — model inference settings
- `tool_result_truncation_policy` — how tool outputs are inserted into context
- `budget_limits` — per-task and per-batch cost ceilings
- `privacy_mode` — how much raw data to store

After this first configuration, synthetic task generation and batch execution can run automatically.

### Example `agent_config.yaml`

The first target runtime is Claude Code (see [Claude Code as the First Target Runtime](#claude-code-as-the-first-target-runtime)).

```yaml
agent:
  agent_version: "mvp-0.1"
  provider: "anthropic"              # "anthropic" | "openai"
  model: "claude-haiku-4-5-20251001" # cheap for batch logging; switch to claude-sonnet-4-6 for production profiling
  system_prompt: "You are a helpful assistant. Use tools only when necessary."
  temperature: 0
  max_tool_calls: 5

tools:
  - name: "web_search"
    enabled: true
    description: "Search the web for current or external information."
  - name: "calculator"
    enabled: true
    description: "Evaluate arithmetic expressions."

truncation:
  tool_result_max_chars: 4000

budget:
  max_task_cost_usd_p90: 0.02
  max_batch_cost_usd: 2.00

privacy:
  mode: "synthetic_only"
```

### Config Versioning

Changing system prompt, tool schema, model, temperature, or truncation policy must create a new `agent_config_id`. The `tool_registry_hash` (SHA-256 of all enabled tool schemas) and `system_prompt_hash` both change, and the old `agent_config_id` is closed. Training data from different configs must never be mixed without tracking the config — the training signal becomes contradictory.

---

## Claude Code as the First Target Runtime

The first target agent runtime is **Claude Code**, because this is the agent the founder already uses most.

Agent Cost Forecaster should not build its own agent runtime in Milestone 1. Instead, it should instrument Claude API execution — the same model calls that Claude Code makes.

```text
Milestone 1 should observe Claude Code, not replace Claude Code.
```

### What "Instrumenting Claude Code" Means

Claude Code is a CLI tool that:

1. Sends prompts to Claude models via the Anthropic API
2. Executes tools through MCP servers or built-in tools
3. Returns responses to the user

Instrumenting it means:

- Using the **Anthropic Python SDK** to call the same Claude models Claude Code uses
- Routing all tool calls through the `observed_tool_call` wrapper before execution
- Logging every `messages.create()` call: input tokens, output tokens, cache tokens, cost
- Logging every tool call: arguments, result, source URLs, latency, tokens inserted

The executor does not try to replicate Claude Code's full feature set. It replicates the **observable API surface** — model calls and tool calls — with the same models and tools.

### Why Not Build a Custom Agent Runtime in Milestone 1

Building a custom agent runtime would:

- Add complexity that delays the first logged run
- Produce profiles that don't match real Claude Code behavior
- Create a gap between what you observe and what you actually use

Using the Anthropic SDK with the same models and tools means the logged profiles reflect Claude Code's actual cost structure.

### First-Target Agent Config (Claude)

Use Claude Haiku for batch logging runs (low cost, high volume):

```yaml
agent:
  agent_version: "mvp-0.1"
  provider: "anthropic"
  model: "claude-haiku-4-5-20251001"
  system_prompt: "You are a helpful assistant. Use tools only when necessary."
  temperature: 0
  max_tool_calls: 5

tools:
  - name: "web_search"
    enabled: true
    description: "Search the web for current information."
  - name: "calculator"
    enabled: true
    description: "Evaluate arithmetic expressions."

truncation:
  tool_result_max_chars: 4000

budget:
  max_task_cost_usd_p90: 0.02
  max_batch_cost_usd: 2.00

privacy:
  mode: "synthetic_only"
```

Switch to `claude-sonnet-4-6` when you want to profile the model you actually use in production.

### Anthropic SDK Specifics

**Creating messages:**

```python
from anthropic import Anthropic
client = Anthropic()

response = client.messages.create(
    model=model,
    max_tokens=1024,
    system=system_prompt,
    tools=tools,       # list of dicts with name, description, input_schema
    messages=messages,
)
```

**Token usage (different from OpenAI):**

```python
usage = response.usage
input_tokens  = usage.input_tokens
output_tokens = usage.output_tokens
# Prompt cache fields (when prompt caching is active)
cache_read_input_tokens  = getattr(usage, "cache_read_input_tokens", 0) or 0
cache_write_input_tokens = getattr(usage, "cache_write_input_tokens", 0) or 0
```

**Detecting tool use and extracting calls:**

```python
stop_reason = response.stop_reason  # "end_turn" | "tool_use" | "max_tokens"

for block in response.content:
    if block.type == "tool_use":
        tool_name   = block.name
        arguments   = block.input   # already a dict, not a JSON string
        tool_use_id = block.id
```

**Tool result format (sent back to the model):**

```python
messages.append({"role": "assistant", "content": response.content})
messages.append({
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": json.dumps(inserted_result),
        }
    ],
})
```

### Claude Tool Schema Format

Anthropic uses `input_schema` instead of OpenAI's `parameters`:

```python
WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": "Search the web for current or external information.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
        },
        "required": ["query"],
    },
}
```

### Static Pricing (Claude Models)

| Model | Input (per 1M) | Output (per 1M) | Cache read (per 1M) | Cache write (per 1M) |
|-------|---------------|----------------|---------------------|----------------------|
| `claude-haiku-4-5-20251001` | $0.80 | $4.00 | $0.08 | $1.00 |
| `claude-sonnet-4-6` | $3.00 | $15.00 | $0.30 | $3.75 |

Log runs at Haiku scale (cheap, many runs). Verify the profile holds when switched to Sonnet.

### MCP Tools — Deferred to Milestone 2+

Claude Code uses MCP (Model Context Protocol) servers for tools like Brave Search, file access, and custom integrations. MCP tool wrapping requires intercepting at the MCP client level, which is more complex than plain function tools.

In Milestone 1, approximate Claude Code's tool behavior using Anthropic function tools (`web_search` via DuckDuckGo, `calculator`). Add real MCP tool interception in Milestone 2 once the logging loop is proven with function tools.

---

## Synthetic Data Generation Strategy

### Generation Phases

Do not generate synthetic tasks with an LLM first. Use templates.

| Phase | Strategy | When |
|-------|----------|------|
| 1 | Manually written seed templates | Week 1 |
| 2 | Template + variable sampling | Week 2 |
| 3 | Coverage-driven (target weak tools / low sample counts) | Week 4 |
| 4 | LLM-assisted generation | Only after logging loop is proven |

### Batch Sizes

- Batch 1: 100 tasks (prove the loop works)
- Batch 2: 300 tasks (enough for first empirical profiles)
- Batch 3: 1,000 tasks (enough to see calibration trends)

### First-Batch Distribution

| Category | Count | Purpose |
|----------|-------|---------|
| `web_search` required | 40 | Profile search result sizes |
| `calculator` required | 20 | Profile deterministic tool behavior |
| `no_tool` required | 25 | Test false positive suppression |
| `ambiguous` | 15 | Test router robustness |

### `seed_templates.yaml`

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

### `target_tools` vs `actual_tools_called`

These are different:

- `target_tools` — what the synthetic task was **designed** to test
- `actual_tools_called` — what the agent **actually did**

Example of a useful mismatch:

```json
{
  "prompt": "Find the latest Nvidia quarterly revenue.",
  "target_tools": ["web_search"],
  "actual_tools_called": []
}
```

This reveals that the agent did not call the tool even when it should have. Both routing miss types — calling a tool when not needed, and not calling a tool when needed — are calibration signals.

---

## Conceptual Cost Formula

```
estimated_total_cost =
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

---

## Tool Exposure, Prediction, and Execution

These three concepts sound related but are distinct. Confusing them leads to bad cost estimates.

### Tools Exposed to the Model

All tool schemas passed to the model in the context window — whether or not the model uses any of them. **Schema tokens are always paid for all exposed tools, not just the predicted ones.** This is one of the most common sources of underestimation: a caller passes 15 tool schemas "just in case" and pays ~2,000 tokens per call for schemas the model never touches.

```
tool_schema_tokens = Σ schema_tokens(tool_i)  for all exposed tools
```

This is a fixed, computable cost. No probability weighting needed.

### Tools Predicted by the Router

The subset of exposed tools the router believes the agent will actually call, expressed as a probability distribution. Used to weight the **variable** portion of the cost estimate (argument tokens + result tokens + follow-up reasoning). The router predicts over the exposed set only — it cannot predict a tool that is not exposed.

```
predicted_variable_cost = Σ_i P(tool_i) × E(calls_i) × E(tokens_per_call_i)
```

### Tools Actually Called by the Agent

Ground truth, recorded after execution by the observed tool call wrapper. This is what calibration compares against the router's predictions. A tool that is exposed but not predicted and then actually called is a routing miss — the most expensive kind, because its variable token cost was entirely absent from the estimate.

### In the Data Model

| Field | Table | Meaning |
|-------|-------|---------|
| `tools_exposed` | `predictions`, `agent_runs` | All tool names passed to the model |
| `tool_schema_tokens` | `predictions`, `model_calls` | Fixed token cost for all exposed schemas |
| `tools_predicted` | `predictions` | RouterOutput (probabilities + expected calls) |
| `actual_tools_called` | `agent_runs` | Ground truth after execution |

---

## Tool Call Monitoring and Source Tracking

### Core Rule

The agent must never call tools directly. **All tool calls must go through an observed wrapper.** The system must not ask the model what tools it used — it must observe runtime events directly.

```
Agent wants to call tool
→ observed_tool_call wrapper
→ log tool start (create tool_call row, status=running)
→ call real tool
→ extract result metadata (source URLs, token counts, latency)
→ log result (finish tool_call row)
→ return result to agent
```

### Observer Pseudocode

```python
def observed_tool_call(
    tool_name: str,
    arguments: dict,
    run_id: str,
    triggered_by_model_call_id: str,
) -> Any:
    started_at = time.time()

    tool_call_id = logger.create_tool_call(
        run_id=run_id,
        triggered_by_model_call_id=triggered_by_model_call_id,
        tool_name=tool_name,
        arguments_json=arguments,
        status="running",
    )

    try:
        result = tool_registry.call(tool_name, arguments)
        metadata = extract_tool_metadata(tool_name, result)

        logger.finish_tool_call(
            tool_call_id=tool_call_id,
            success=True,
            result_hash=hash_text(str(result)),
            result_preview=str(result)[:500],
            result_tokens_raw=count_tokens(str(result)),
            result_tokens_inserted=count_inserted_tokens(result),
            source_urls_returned=metadata.get("source_urls_returned", []),
            source_urls_inserted=metadata.get("source_urls_inserted", []),
            source_domains=metadata.get("source_domains", []),
            latency_ms=int((time.time() - started_at) * 1000),
        )
        return result

    except Exception as e:
        logger.finish_tool_call(
            tool_call_id=tool_call_id,
            success=False,
            error_message=str(e),
            latency_ms=int((time.time() - started_at) * 1000),
        )
        raise
```

### MVP Constraint

All external access in the MVP must go through registered tools. Do not allow unmonitored browser access, direct HTTP requests, or code interpreter network access. If `code_interpreter` can call `requests.get()` freely, the system cannot reliably track which websites were used or how many tokens resulted.

### Source URL Tracking

Track not just which tool was called, but which external sources were returned and inserted.

| Field | Meaning |
|-------|---------|
| `source_urls_returned` | All URLs returned by the tool (e.g. all 10 search results) |
| `source_urls_inserted` | URLs whose content was inserted into the LLM context (e.g. top 3) |
| `source_urls_cited` | URLs cited in the final answer, if parseable |
| `source_domains` | Normalized domains from returned URLs |
| `source_traceability_status` | `full` / `partial` / `none` |

**Why these are different:** A web_search may return 10 results but insert only the top 3 snippets into context. Only inserted content affects token cost. Citation appears only in the final answer and may lag both.

### Example `web_search` Result Structure

```json
{
  "query": "Nvidia latest revenue 2026",
  "results": [
    {"title": "NVIDIA Announces Financial Results",
     "url": "https://nvidianews.nvidia.com/...", "snippet": "..."},
    {"title": "NVIDIA Investor Relations",
     "url": "https://investor.nvidia.com/...", "snippet": "..."}
  ]
}
```

The observer extracts and stores:

```json
{
  "source_urls_returned": [
    "https://nvidianews.nvidia.com/...",
    "https://investor.nvidia.com/..."
  ],
  "source_domains": ["nvidianews.nvidia.com", "investor.nvidia.com"]
}
```

### MCP Tool Wrapper

For MCP tools, wrap the MCP client to record:

- `mcp_server_name`, `mcp_tool_name`, arguments
- response metadata, source URLs if returned
- latency, token counts, success/error

If an MCP server does not return source URLs, record the query, response hash, preview, and token counts, but set `source_traceability_status = "partial"`.

---

## Traceability Model

Every prediction and execution should be fully traceable through IDs.

### Core Trace Chain

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

### ID Fields vs Hash Fields

| Field type | Purpose |
|------------|---------|
| `trace_id`, `prediction_id`, `run_id`, etc. | Connect rows across tables |
| `user_prompt_hash`, `result_hash`, `system_prompt_hash`, `tool_registry_hash` | Identify content/version without storing sensitive raw text |

### Tool Call Links

Each tool call row carries two model call references:

- `triggered_by_model_call_id` — the model call that requested this tool
- `consumed_by_model_call_id` — the later model call that consumed this tool result

This creates an explicit, queryable chain across model calls and tool calls.

### Complete ID / Hash Inventory

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

---

## Module Descriptions

### 1. `tool_registry.py`

**Purpose:** Central store for all available tools and MCP tools.

Loads tool definitions at startup and provides a searchable registry. Each entry includes its name, type, description, input/output schemas, pre-computed schema token counts, and an optional per-call service fee. Computes and caches `tool_registry_hash` so prediction records can be tied to a specific registry snapshot.

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

Key methods:
- `register(tool: ToolDefinition)` — add or update a tool
- `get(tool_name: str) -> ToolDefinition`
- `list_enabled() -> list[ToolDefinition]`
- `registry_hash() -> str` — SHA-256 of all enabled schemas

---

### 2. `router_predictor.py`

**Purpose:** Predict which tools an agent will call for a given prompt.

Three-layer hybrid — use only what is available:

1. **Rule-based baseline** — keyword and intent patterns. Works with zero data. MVP only uses this.
2. **Embedding similarity** — cosine similarity between prompt and tool description embeddings. Phase 5.
3. **Supervised classifier** — trained on `router_training_examples`. Phase 8.

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

---

### 3. `token_estimator.py`

**Purpose:** Estimate total token usage before execution.

Uses model-specific tokenizers (`tiktoken` for OpenAI, `anthropic.beta.messages.count_tokens` for Claude).

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

**Key distinctions:**
- `tool_schema_tokens` is a fixed cost for all exposed tools — no probability weighting.
- Profile `result_tokens_inserted`, not `result_tokens_raw`. The truncation policy determines the gap.
- p90 substitutes p90 profile values; fixed terms are identical across p50 and p90.

Always list `tool_schema_tokens` as a line item in `main_cost_drivers` when it exceeds 200 tokens.

---

### 4. `price_estimator.py`

**Purpose:** Convert token estimates into monetary cost.

Provider-versioned pricing. At prediction time, snapshot the active `pricing_id` into the `predictions` row so historical cost comparisons survive provider price changes.

```python
@dataclass
class ModelPricing:
    pricing_id: str
    provider: str            # "openai" | "anthropic" | "google"
    model: str
    effective_from: date
    effective_to: date | None  # None = currently active
    input_cost_per_1k: float
    output_cost_per_1k: float
    cached_input_cost_per_1k: float | None
    reasoning_cost_per_1k: float | None  # o-series models
    source: str              # URL to provider pricing page
```

Never update a pricing row in place. Close it (`effective_to = today`) and insert a new one.

---

### 5. `budget_guard.py`

**Purpose:** Decide whether a predicted run is safe to execute given a configured budget.

```python
@dataclass
class BudgetDecision:
    limit_usd: float
    status: str          # "safe" | "warning" | "blocked" | "unknown"
    should_execute: bool
    reason: str
```

| Status | Condition |
|--------|-----------|
| `safe` | p90 cost is comfortably below budget |
| `warning` | p50 below budget but p90 near or above budget |
| `blocked` | p90 exceeds budget |
| `unknown` | insufficient profile data to estimate reliably |

---

### 6. `task_generator.py`

**Purpose:** Expand seed templates into executable synthetic tasks.

MVP: template-based only. Reads `seed_templates.yaml`, samples variables, writes `seed_tasks.jsonl`.

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

Safety: before executing each task, call `predictor.predict()`. Skip the task if p90 exceeds `pipeline.max_task_cost_usd_p90`.

---

### 7. `agent_executor.py`

**Purpose:** Run tasks through the configured target agent and collect ground-truth observations.

Instrumented wrapper around the agent runtime. Every tool call is intercepted by `observed_tool_call` before it reaches the real tool. Every model API response is captured by `token_usage_tracker`.

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
    total_cost_usd: float
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

### 8. `run_logger.py`

**Purpose:** Single write path for all execution data into the database.

Enforces privacy mode before writing. Generates `trace_id` once per prediction-run pair and propagates it to all child records.

Write paths:
- `log_prediction(prediction, agent_config_id) -> (prediction_id, trace_id)` — written at predict time; `run_id` is NULL
- `log_run(result: ExecutionResult, prediction_id: str | None) -> run_id` — written after execution; back-fills `predictions.run_id`
- `log_model_calls(run_id, calls: list[ModelCallEvent])` — one row per model API call
- `log_tool_calls(run_id, calls: list[ToolCallEvent])` — one row per tool call

Invariant: `Σ model_calls.input_tokens == agent_runs.actual_input_tokens`. A discrepancy flags a logging bug.

---

### 9. `cost_profiler.py`

**Purpose:** Build and maintain empirical token profiles per `(tool_name, model)` pair.

Reads `tool_calls` and computes p50 / p90 statistics. Falls back to cross-model averages when per-model samples are insufficient. Profiles `result_tokens_inserted`, not `result_tokens_raw`.

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

### 10. `calibration.py`

**Purpose:** Measure prediction accuracy and trigger profile updates.

**The two headline metrics are `p90_coverage` and `underestimation_rate`.** Target `p90_coverage ≥ 0.90` and `underestimation_rate ≤ 0.10` from the first week of real logging.

| Metric | Priority | Description |
|--------|----------|-------------|
| `p90_coverage` | **Primary** | Fraction of runs where actual cost ≤ p90 estimate. Target ≥ 0.90. |
| `underestimation_rate` | **Primary** | Fraction of runs where actual cost > p90. Target ≤ 0.10. |
| `cost_mape` | Secondary | Mean absolute percentage error on total cost |
| `token_mape` | Secondary | Mean absolute percentage error on total token count |
| `tool_top1_accuracy` | Secondary | Was the highest-probability tool actually called? |
| `tool_recall` | Secondary | Were all actually-called tools in the predicted set? |
| `no_tool_accuracy` | Secondary | Correct when no tool was needed |

When `underestimation_rate` rises: check whether a new tool with no profile was added, whether truncation policy changed, or whether a high-result-size tool is being called more often than expected. Then generate targeted synthetic tasks to close the gap.

---

### 11. `training_dataset_builder.py` *(Phase 5+)*

**Purpose:** Transform raw execution logs into structured training examples for the ML router.

Not needed in the MVP. Added in Phase 5 when there are hundreds of labeled runs per tool.

---

## Privacy-Safe Logging and Prompt Hashing

### Prompt Hashing

Production prompt text is sensitive. Hash it instead of storing it raw.

```python
import hashlib
import os

SECRET_SALT = os.environ["PROMPT_HASH_SALT"]

def normalize_prompt(prompt: str) -> str:
    return " ".join(prompt.strip().split())

def hash_prompt(prompt: str) -> str:
    normalized = normalize_prompt(prompt)
    return hashlib.sha256((SECRET_SALT + normalized).encode("utf-8")).hexdigest()
```

**Properties:**
- Same normalized prompt + same salt → same hash (allows deduplication)
- Hash is not realistically reversible
- Salted hash resists dictionary attacks
- Synthetic runs may store full prompt text
- Production runs should default to hash + token count only

### Privacy Modes

| Mode | Behavior |
|------|----------|
| `off` | Store everything. Local development only. |
| `hash_only` | Store hashes and metadata; no raw text. |
| `redact_pii` | Attempt to remove emails, names, phone numbers, IDs. |
| `synthetic_only` | Full data for synthetic runs; metadata only for production runs. |

Recommended MVP default: `synthetic_only`.

### Token Tracking (Always Stored)

`result_tokens_raw` and `result_tokens_inserted` are always stored regardless of privacy mode — they contain no raw text. Source URLs may need domain allowlisting or redaction in production privacy modes.

---

## Budget Guard

The budget guard runs on every prediction request. Every `/predict` call returns a `budget` object. This is a core product feature, not a future extension.

```json
{
  "budget": {
    "limit_usd": 0.02,
    "status": "warning",
    "should_execute": true,
    "reason": "p50 is within budget but p90 exceeds the limit."
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

---

## Cost Risk Explanation and Optimization Suggestions

Every prediction must explain what is driving its cost estimate. Every expensive prediction must suggest how to reduce it.

### Cost Drivers

Always list `tool_schema_tokens` first if it exceeds 200 tokens — most callers are unaware they are paying for schemas of tools the model never uses.

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
  ]
}
```

### Optimization Suggestions

Rule-based in the MVP:

```json
{
  "optimization_suggestions": [
    "Limit web_search result insertion to 1,000 tokens to reduce p90 by ~30%.",
    "Set max_tool_calls=2 for this prompt type."
  ]
}
```

### Tool Exposure Optimizer

Schema tokens are paid for all exposed tools, even unused ones. The system should recommend the minimal tool set.

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

### Prediction Modes

```
fast_predict (default):
  no model call; target latency < 200 ms
  uses rules + profiles
  returns prediction_id

deep_predict (later-stage):
  may call a cheap router model (e.g. gpt-4o-mini)
  higher accuracy for ambiguous prompts
```

---

## Data Model

### Table: `model_pricing`

| Column | Type | Notes |
|--------|------|-------|
| `pricing_id` | UUID | Primary key |
| `provider` | str | `openai` / `anthropic` / `google` / … |
| `model` | str | |
| `effective_from` | date | |
| `effective_to` | date | NULL = currently active |
| `input_cost_per_1k` | float | |
| `output_cost_per_1k` | float | |
| `cached_input_cost_per_1k` | float | NULL if not supported |
| `reasoning_cost_per_1k` | float | NULL except for reasoning models |
| `source` | str | URL to provider pricing page |

### Table: `agent_configs`

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

### Table: `predictions`

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
| `estimated_cost_usd_p50` | float | |
| `estimated_cost_usd_p90` | float | |
| `budget_status` | str | `safe` / `warning` / `blocked` / `unknown` |
| `budget_limit_usd` | float | |
| `confidence` | str | `high` / `medium` / `low` |
| `router_version` | str | `rules` / `embedding` / `classifier` |
| `prediction_mode` | str | `fast` / `deep` |
| `pricing_id` | UUID | FK → `model_pricing` — snapshot used at prediction time |
| `run_id` | UUID | FK → `agent_runs`; NULL until/unless the run executes |
| `created_at` | datetime | |

### Table: `agent_runs`

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
| `actual_tools_called` | JSON | Ground truth after execution |
| `actual_input_tokens` | int | Sum across all model calls in the run |
| `actual_output_tokens` | int | Sum across all model calls in the run |
| `actual_total_cost_usd` | float | |
| `latency_ms` | int | |
| `success` | bool | |
| `sample_quality_score` | float | 0.0–1.0 |
| `sample_quality_reason` | text | |

### Table: `model_calls`

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
| `cost_usd` | float | |
| `pricing_id` | UUID | FK → `model_pricing` |

`Σ model_calls.input_tokens` for a run must equal `agent_runs.actual_input_tokens`. Discrepancy = logging bug.

### Table: `tool_calls`

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

### Table: `tool_profiles`

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

### Table: `calibration_reports`

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

### Table: `synthetic_tasks` *(Week 4+)*

During Weeks 1–3, use `seed_tasks.jsonl` instead of this table. Add the table in Week 4 when the batch runner needs status tracking.

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

### Minimum Viable Fields

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
estimated_cost_usd_p50 REAL,
estimated_cost_usd_p90 REAL,
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
actual_total_cost_usd REAL,
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
cost_usd REAL,
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

---

## Fallback Profile Hierarchy

When a new tool has no empirical data, do not fail or return zero:

```
1. exact:        tool_name + model + agent_config_id
2. tool + model: tool_name + model
3. tool only:    tool_name (across all models)
4. type default: e.g. "web_search" | "calculator" | "file_search" | "database"
5. global:       average across all logged tool calls
6. conservative: hardcoded upper-bound safe fallback
```

When fallback is used, surface it in the prediction response:

```json
{
  "profile_source": "tool_type_default",
  "confidence": "low",
  "warnings": ["No empirical data for this tool yet. Using web_search type defaults."]
}
```

This prevents silent overconfidence and signals to the task generator to prioritize coverage for that tool.

---

## Sample Quality Scoring

Keep everything in the database. Weight selectively in training.

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

Runs with `score < 0.5` remain in `agent_runs` permanently and contribute to `p90_coverage` and `underestimation_rate` calibration.

---

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
   └─ cost = (input × input_rate + output × output_rate) / 1000
   └─ snapshots pricing_id
   └─ returns CostEstimate { p50_usd, p90_usd }

6. budget_guard
   └─ compares p50/p90 against limit_usd
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

---

## Self-Improving Pipeline Flow

```
1. task_generator
   ├─ reads seed_templates.yaml (MVP) or queries calibration for coverage gaps (Phase 5)
   ├─ expands templates into SyntheticTask list
   └─ writes to seed_tasks.jsonl (MVP) or synthetic_tasks table (Phase 4+)

2. agent_executor (scripts/run_batch.py in MVP)
   ├─ pulls next task
   ├─ calls predictor.predict() → budget check → skip if blocked
   ├─ runs agent through real model API
   ├─ observed_tool_call wrapper intercepts each tool invocation
   ├─ token_usage_tracker captures per-model-call token counts
   └─ cost_tracker accumulates total cost; stops batch if budget exceeded

3. run_logger
   └─ writes ExecutionResult → agent_runs (source=synthetic)
   └─ writes ModelCallEvent list → model_calls
   └─ writes ToolCallEvent list → tool_calls (with source URLs)
   └─ back-fills predictions.run_id
   └─ assigns sample_quality_score

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

---

## Logging and Calibration Flow (Production Runs)

```
1. Agent runtime calls POST /log-run with prediction_id (if available)

2. run_logger
   └─ enforces privacy mode
   └─ writes agent_runs (source=production)
   └─ writes model_calls
   └─ writes tool_calls (source_urls stored even if result_text is not)
   └─ back-fills predictions.run_id if prediction_id provided
   └─ assigns sample_quality_score = 1.0 if success

3. cost_profiler
   └─ production samples weighted most heavily in profiles

4. calibration (nightly)
   └─ separates synthetic vs. production accuracy
   └─ if production accuracy < synthetic: flags distribution shift
```

---

## API Design

### `POST /predict`

```json
// Request
{
  "prompt": "Find recent Nvidia earnings and calculate YoY growth.",
  "model": "gpt-4o",
  "tools_exposed": ["web_search", "calculator"],
  "system_prompt": "You are a helpful assistant.",
  "prediction_mode": "fast",
  "budget_limit_usd": 0.02
}

// Response
{
  "prediction_id": "pred-a1b2c3d4",
  "trace_id": "trace-xyz",
  "prediction_mode": "fast",
  "predicted_tools": [
    {"tool": "web_search", "probability": 0.88, "expected_calls": 1.4},
    {"tool": "calculator", "probability": 0.71, "expected_calls": 1.0}
  ],
  "no_tool_probability": 0.05,
  "estimated_tokens": {
    "input_p50": 2800, "input_p90": 5600,
    "output_p50": 310, "output_p90": 720
  },
  "estimated_cost_usd": {"p50": 0.0031, "p90": 0.0063},
  "budget": {
    "limit_usd": 0.02,
    "status": "safe",
    "should_execute": true,
    "reason": "p90 cost is comfortably below budget."
  },
  "tool_schema_tokens": 280,
  "tools_exposed": ["web_search", "calculator"],
  "main_cost_drivers": [
    {
      "component": "tool_schema_tokens",
      "reason": "2 tools exposed — fixed cost regardless of which are called",
      "estimated_tokens": 280
    },
    {
      "component": "web_search",
      "reason": "High probability of 1–2 search calls with variable result sizes",
      "estimated_tokens_p90": 3200
    }
  ],
  "optimization_suggestions": [
    "Limit web_search result insertion to 1,000 tokens to reduce p90 by ~25%.",
    "Set max_tool_calls=2 for this prompt type."
  ],
  "profile_source": "tool_model_profile",
  "confidence": "medium",
  "router_version": "rules",
  "warnings": []
}
```

### `POST /log-run`

```json
{
  "prediction_id": "pred-a1b2c3d4",
  "agent_config_id": "cfg-xyz",
  "actual_tools_called": ["web_search", "calculator"],
  "actual_input_tokens": 3700,
  "actual_output_tokens": 410,
  "actual_total_cost_usd": 0.0043,
  "latency_ms": 3200,
  "success": true,
  "model_calls": [
    {
      "call_index": 0, "model": "gpt-4o",
      "input_tokens": 720, "output_tokens": 0,
      "cached_input_tokens": 0, "reasoning_tokens": null,
      "tool_schema_tokens": 280, "tool_result_tokens_inserted": 0,
      "finish_reason": "tool_calls", "latency_ms": 850
    },
    {
      "call_index": 1, "model": "gpt-4o",
      "input_tokens": 2120, "output_tokens": 0,
      "cached_input_tokens": 720, "reasoning_tokens": null,
      "tool_schema_tokens": 280, "tool_result_tokens_inserted": 900,
      "finish_reason": "tool_calls", "latency_ms": 1100
    },
    {
      "call_index": 2, "model": "gpt-4o",
      "input_tokens": 860, "output_tokens": 410,
      "cached_input_tokens": 720, "reasoning_tokens": null,
      "tool_schema_tokens": 280, "tool_result_tokens_inserted": 12,
      "finish_reason": "stop", "latency_ms": 920
    }
  ],
  "tool_calls": [
    {
      "call_index": 0,
      "triggered_by_model_call_id": "mc_001",
      "tool_name": "web_search",
      "argument_tokens": 14,
      "result_tokens_raw": 2200,
      "result_tokens_inserted": 900,
      "was_result_truncated": true,
      "truncation_policy_applied": {"max_tokens": 1200},
      "source_urls_returned": ["https://investor.nvidia.com/...", "https://nvidianews.nvidia.com/..."],
      "source_domains": ["investor.nvidia.com", "nvidianews.nvidia.com"],
      "source_traceability_status": "full",
      "latency_ms": 1050, "success": true
    },
    {
      "call_index": 1,
      "triggered_by_model_call_id": "mc_002",
      "tool_name": "calculator",
      "argument_tokens": 12,
      "result_tokens_raw": 12,
      "result_tokens_inserted": 12,
      "was_result_truncated": false,
      "truncation_policy_applied": null,
      "source_urls_returned": [],
      "source_domains": [],
      "source_traceability_status": "none",
      "latency_ms": 8, "success": true
    }
  ]
}
```

### Additional Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /profiles/{tool_name}` | Current cost profile (`?model=gpt-4o` optional) |
| `GET /calibration/latest` | Most recent CalibrationReport |
| `GET /configs` | List known agent configs with their hashes |
| `GET /trace/{trace_id}` | Full trace: prediction → run → model calls → tool calls |
| `POST /update-profiles` | Batch-update profiles from historical logs (backfill) |

---

## CLI Design

Build the CLI before any API or dashboard. Validate the full loop via CLI first.

```bash
# Predict cost for a prompt
acf predict "Find recent Nvidia earnings and calculate YoY growth."
acf predict "..." --model gpt-4o --tools web_search,calculator --budget 0.05

# Run a single task and log the result
acf run "Find the latest Apple quarterly revenue." --log

# Generate synthetic tasks from templates
acf generate-tasks --n 100 --strategy template

# Run pending tasks through the configured target agent
acf run-batch --limit 100 --model gpt-4o-mini

# Full local loop: generate + run + update profiles
acf loop --n 100 --update-profiles

# Recompute tool profiles
acf profiles --update
acf profiles --show

# Show prediction vs actual for a run
acf compare --run-id run_001

# Show full trace for a run or prediction
acf trace --run-id run_001
acf trace --prediction-id pred_001

# Show websites / sources used by a run
acf sources --run-id run_001

# Suggest minimal tool set for a prompt
acf suggest-tools "Find Nvidia latest earnings and calculate YoY growth"

# Show calibration summary
acf calibration

# Export training dataset
acf export --format jsonl --output ./data/training.jsonl
```

**Expected daily flow:**

```
acf generate-tasks → acf run-batch → acf profiles --update → acf calibration
```

Output: readable table by default (`rich` if installed, plain text fallback). Pass `--json` for raw JSON.

---

## Example Trace

Prompt: *"Find Nvidia's latest revenue and calculate YoY growth."*

```json
{
  "trace_id": "trace_001",
  "prediction_id": "pred_001",
  "run_id": "run_001",
  "model": "gpt-4o",
  "tools_exposed": ["web_search", "calculator"],
  "predicted_cost_usd_p90": 0.0063,
  "actual_cost_usd": 0.0043,
  "p90_covered": true,
  "steps": [
    {
      "type": "model_call",
      "id": "mc_001",
      "call_index": 0,
      "input_tokens": 720,
      "output_tokens": 0,
      "tool_schema_tokens": 280,
      "tool_result_tokens_inserted": 0,
      "finish_reason": "tool_calls",
      "latency_ms": 850
    },
    {
      "type": "tool_call",
      "id": "tool_001",
      "triggered_by_model_call_id": "mc_001",
      "consumed_by_model_call_id": "mc_002",
      "tool_name": "web_search",
      "arguments_json": {"query": "Nvidia latest annual revenue 2026"},
      "result_tokens_raw": 2200,
      "result_tokens_inserted": 900,
      "was_result_truncated": true,
      "source_domains": ["investor.nvidia.com", "nvidianews.nvidia.com"],
      "source_traceability_status": "full",
      "latency_ms": 1050,
      "success": true
    },
    {
      "type": "model_call",
      "id": "mc_002",
      "call_index": 1,
      "input_tokens": 2120,
      "output_tokens": 0,
      "tool_schema_tokens": 280,
      "tool_result_tokens_inserted": 900,
      "cached_input_tokens": 720,
      "finish_reason": "tool_calls",
      "latency_ms": 1100
    },
    {
      "type": "tool_call",
      "id": "tool_002",
      "triggered_by_model_call_id": "mc_002",
      "consumed_by_model_call_id": "mc_003",
      "tool_name": "calculator",
      "arguments_json": {"expression": "(60922 - 26974) / 26974"},
      "result_tokens_raw": 12,
      "result_tokens_inserted": 12,
      "was_result_truncated": false,
      "source_domains": [],
      "source_traceability_status": "none",
      "latency_ms": 8,
      "success": true
    },
    {
      "type": "model_call",
      "id": "mc_003",
      "call_index": 2,
      "input_tokens": 860,
      "output_tokens": 410,
      "tool_schema_tokens": 280,
      "tool_result_tokens_inserted": 12,
      "cached_input_tokens": 720,
      "finish_reason": "stop",
      "latency_ms": 920
    }
  ],
  "totals": {
    "actual_input_tokens": 3700,
    "actual_output_tokens": 410,
    "actual_cost_usd": 0.0043,
    "model_calls": 3,
    "tool_calls": 2,
    "sources_used": ["investor.nvidia.com", "nvidianews.nvidia.com"]
  }
}
```

`acf trace --run-id run_001` outputs this in the terminal.

---

## Founder Part-Time Roadmap

Six weeks, nights and weekends. One working loop per week. Logging comes before prediction.

### Week 1 — Logging Infrastructure *(Milestone 1, part 1)*

- `db.py`: SQLite schema for `model_pricing`, `agent_configs`, `agent_runs`, `model_calls`, `tool_calls`
- `pricing.py`: static pricing for Claude models (`claude-haiku-4-5-20251001`, `claude-sonnet-4-6`); include OpenAI rows for future comparison
- `tool_registry.py`: load `web_search` and `calculator` from `agent_config.yaml`; define schemas in Anthropic `input_schema` format; count schema tokens; compute `tool_registry_hash`
- `executor.py`: call Claude via Anthropic SDK (`client.messages.create()`); handle `tool_use` blocks; route all tool calls through `observed_tool_call` wrapper; capture `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_write_input_tokens`
- `logger.py`: write `agent_runs`, `model_calls`, `tool_calls` (with source URLs); apply sample quality score
- `acf run "..."` CLI command: run a single prompt through Claude and log the full trace
- Verify: `Σ model_calls.input_tokens == agent_runs.actual_input_tokens`

### Week 2 — Batch Logging and Validation *(Milestone 1, part 2)*

- `data/seed_templates.yaml`: 100–200 prompts across `web_search`, `calculator`, `no_tool`, `ambiguous`
- `scripts/generate_tasks.py`: expand templates into `seed_tasks.jsonl`
- `scripts/run_batch.py`: run tasks sequentially; log all results
- `acf run-batch` CLI command
- Source URL tracking: verify `source_urls_returned`, `source_domains`, `source_traceability_status` are populated for all web_search calls
- Run 100 prompts end-to-end; verify every run produces a complete, traceable log
- **Milestone 1 complete when:** 100 runs logged, every model_call and tool_call has tokens, cost, and timestamps

### Week 3 — Empirical Profiles *(Milestone 2)*

- `profiler.py`: compute p50/p90 from logged `tool_calls.result_tokens_inserted`; compute per prompt category
- `scripts/update_profiles.py`: recompute `tool_profiles` on demand from all logged tool_calls
- `acf profiles --update` CLI command: rebuild profiles from stored logs
- `acf trace --run-id ...`: show full model_call → tool_call chain
- `acf sources --run-id ...`: show source domains used per run
- **Milestone 2 complete when:** p50/p90 profiles exist for `web_search`, `calculator`, and `no_tool`; all prompt categories covered

### Week 4 — First Prediction Mode *(Stage 3 begins)*

- `db.py`: add `predictions` and `tool_profiles` tables
- `predictor.py`: use empirical profiles (from Week 3) to estimate cost; rule-based router for tool prediction; budget guard; writes to `predictions` table with `trace_id`; returns `prediction_id`
- `acf predict` CLI command
- Output: estimated p50/p90 cost, budget status, prediction_id, tool_schema_tokens, main cost drivers, optimization suggestions
- Fallback: if no profile exists for a tool, use conservative p90 heuristic and flag as `confidence: low`
- `acf compare --run-id ...`: show predicted vs actual tokens and cost for any logged run

### Week 5 — Held-Out Evaluation *(Milestone 3)*

- Hold out 20–30 new prompts not used in Week 2 training batch
- `acf run-batch --heldout`: run held-out tasks, log actuals, compare against predictions
- `acf calibration` CLI command: print `p90_coverage`, `underestimation_rate`, token MAPE per tool
- Add `calibration_reports` table; persist each calibration run
- Add privacy-safe logging defaults (`synthetic_only` mode with salted prompt hash)
- **Milestone 3 complete when:** `p90_coverage ≥ 0.90` and `underestimation_rate ≤ 0.10` on held-out batch

### Week 6 — User Validation

- Polish `acf` CLI output (use `rich` table; `--json` flag)
- Write `README.md` with setup and demo commands
- Record a short demo: `acf run` → `acf profiles --update` → `acf predict` → `acf compare` → `acf trace`
- Talk to 10 agent builders; ask: *"Would you instrument your agent with this?"* and *"Would you trust these cost estimates?"*
- Decision point: next interface is SDK, API, CI integration, or dashboard — based on feedback

**Deferred until after validation:**

`acf predict` as a standalone pre-run step (currently requires logged profiles), FastAPI, Postgres, async queue, embedding router, supervised classifier, LLM-assisted task generation, `deep_predict`, multi-tenant support, `router_training_examples`, web dashboard.

---

## Later-Stage Roadmap

After the six-week MVP is validated with real users or real execution data:

### Phase 5 — Smarter Routing

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
- LLM-assisted synthetic task generation (Phase 4 of generation strategy)
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

---

## Future Extensions

| Extension | Notes |
|-----------|-------|
| **Multi-model comparison** | Estimate cost across `gpt-4o`, `claude-opus-4-7`, `gemini-2.0-flash` simultaneously |
| **Agent loop detection** | Predict loop depth for multi-step agents; multiply per-iteration cost |
| **Streaming cost updates** | Emit real-time token count updates mid-run for a live cost meter |
| **MCP server pricing** | Some MCP tools charge per-call fees; model as `service_fee_per_call_usd` in ToolProfile |
| **Budget guard v2** | Auto-suggest a cheaper model when current model's p90 would block execution |
| **Source domain allowlisting** | Configurable allowlist / blocklist of domains for web_search tools |
| **RAG cost profiling** | Add `file_search` / retrieval tools with chunk-level token profiling |

---

## Design Principles

### Founder Principles

1. **The first milestone is reliable observability, not prediction.** Run 100 prompts. Produce complete, traceable logs for every model call, tool call, token, source URL, and cost. Before logs exist, prediction can only use conservative heuristics.
2. **Logging-first, profiling-second, prediction-third.** The core asset is the traceable execution dataset. Real prediction quality begins only after enough actual runs are logged. The calibration loop cannot close without ground-truth logs.
3. **Start with two tools and no-tool.** `web_search`, `calculator`, and the no-tool case are enough to prove the loop.
4. **Configure the target agent explicitly before generating any data.** Never mix data from different agent configurations without tracking the config.
5. **All external access must go through registered, observed tools.** Never trust the model to self-report tool usage.
6. **Do not generate synthetic tasks with an LLM before the logging loop works.** Templates first.
7. **Synthetic data is for cold start, not final truth.** Production runs are the signal that matters most.
8. **Do not build the dashboard before the CLI.** The CLI validates the prediction loop at a fraction of the cost.
9. **Do not use Postgres before SQLite becomes limiting.** Zero infrastructure is a feature for a solo founder.
10. **Do not train ML before enough logs exist.** Rule-based routing is good enough until there are hundreds of labeled runs per tool.
11. **Budget protection is a core product feature.** Every prediction must return a budget decision. Never ship without it.
12. **Privacy-safe logging is the default.** Hash production prompts. Store source URLs even when raw text is not stored.
13. **Every prediction must explain its main cost drivers.** A number without explanation is not a product.
14. **Every expensive prediction must suggest how to reduce cost.** Cost reduction advice is the upsell.
15. **CLI > API > dashboard.** For a solo founder, in that order.

### System Principles

16. **Predict distributions, not single numbers.** Always return p50 and p90.
17. **tool_schema_tokens is a fixed cost for all exposed tools.** Always list it first in cost drivers when it is non-trivial.
18. **Profile result_tokens_inserted, not result_tokens_raw.** Truncation policy determines the gap; only inserted tokens affect model input cost.
19. **trace_id connects prediction, execution, model calls, tool calls, and source URLs.** Every record should be traceable end-to-end.
20. **Separate token cost from service cost.** MCP tool API fees are not model context tokens.
21. **Make profiles model-specific.** The same tool returns different token counts under different tokenizers.
22. **Calibrate continuously.** Store both predictions and actuals for every run; treat accuracy as a product metric.
23. **Fail gracefully.** If a tool has no profile, use the fallback hierarchy and signal the gap.
24. **Design for extensibility.** Adding a new tool requires only a registry entry.
25. **Never make a model call during fast_predict.** The default prediction path must return in < 200 ms.
26. **Optimize for underestimation prevention before perfect routing accuracy.** An overestimate is annoying; an underestimate breaks the budget guard.
27. **Source URLs are first-class observability data.** Store them even when raw result text is not stored.
28. **If a tool or MCP server does not return source metadata, mark source_traceability_status as partial.** Never silently drop traceability information.
