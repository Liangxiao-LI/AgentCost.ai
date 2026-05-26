# SDK Integration Layer

> **Status: Planned — MVP. The integration modes and CLI commands described here are the target design. `acf/integrations/` and zero-config storage are built in Week 1; `acf summary`, `acf log`, `acf predict` follow in Weeks 2–4.**

## Get Started in 3 Steps

For existing Claude Code / Anthropic API users, integration takes under two minutes.

**Step 1 — Install**

```bash
pip install agentcost-ai
```

**Step 2 — Change one line in your existing code**

```python
# Before (your existing code — unchanged otherwise)
from anthropic import Anthropic
client = Anthropic()

# After — identical API; every call is now tracked and synced
from acf.integrations.anthropic import Anthropic
client = Anthropic()
```

That's it. On the first call, ACF auto-initializes local storage, generates an anonymous contributor ID, shows a one-time disclosure, and begins syncing anonymized usage data to the community data lake. No config file. No extra API key. No restructuring of your code.

**Step 3 — Check your usage**

```bash
acf summary --today      # cost and tokens for today's calls
acf log --last 20        # per-call breakdown
```

---

## Three Integration Modes

**Mode A — Drop-in import (one line change)**

```python
# Before
from anthropic import Anthropic
client = Anthropic()

# After — identical API surface; every call is now logged and synced
from acf.integrations.anthropic import Anthropic
client = Anthropic()
```

```python
# OpenAI equivalent
from acf.integrations.openai import OpenAI
client = OpenAI()
```

**Mode B — Global patch (zero code change after one import)**

```python
import acf
acf.patch()  # monkey-patches anthropic and openai globally

from anthropic import Anthropic  # unchanged from your existing code
client = Anthropic()             # now tracked
```

```python
acf.unpatch()  # restore originals
```

**Mode C — Per-session context manager (explicit, selective tracking)**

```python
with acf.track(label="my-agent") as session:
    response = client.messages.create(...)

print(session.summary())
# ┌──────────────────────────────────────────────┐
# │ Calls: 1   Input: 720   Output: 410          │
# │ api_equivalent_cost_usd: $0.0043             │
# │ billing_mode: claude_code_pro_subscription   │
# │ Latency: 920 ms                              │
# └──────────────────────────────────────────────┘
```

---

## What Gets Captured Automatically

On every `messages.create()` (Anthropic) or `chat.completions.create()` (OpenAI) call, the wrapper captures:

| Field | Source |
|-------|--------|
| `input_tokens`, `output_tokens` | `response.usage` |
| `cache_read_input_tokens`, `cache_write_input_tokens` | `response.usage` (Anthropic only) |
| `model`, `finish_reason` / `stop_reason` | response fields |
| `tools_exposed`, `tool_schema_tokens` | request fields |
| Tool names called | `tool_use` blocks (names only unless `privacy=off`) |
| `api_equivalent_cost_usd` | computed from built-in pricing table |
| `billing_mode`, `cost_basis` | inferred from which client is used |
| `latency_ms` | wall-clock time around the API call |
| `integration_source` | `"sdk_wrapper"` |

Tool arguments, result content, and source URLs are **not** captured in SDK wrapper mode — those require the full executor pipeline. The `integration_source = "sdk_wrapper"` field marks these runs as partially observed, and they are weighted lower in the calibration loop than `executor` runs.

---

## Zero-Config Storage

On the first tracked call, ACF auto-initializes a local SQLite database at `~/.acf/acf.db` with no configuration required. No YAML, no env vars, no explicit init call.

To use a project-specific database instead:

```bash
export ACF_DB_PATH=./my-project/acf.db
```

---

## Immediate CLI Output

After integration, these commands work from day one:

```bash
acf summary                    # total tokens and cost across all logged calls
acf summary --today            # today only
acf log --last 20              # per-call table: model, tokens, cost, latency
acf spend --by-model           # cost breakdown by model
```

Once 100+ calls are logged, unlock profiling and prediction:

```bash
acf profiles --update          # compute p50/p90 per model and tool type
acf predict "your prompt"      # pre-run cost estimate with budget guard
```

---

## Onboarding Progression

The tracker delivers value from call #1. Profiling becomes reliable at ~30 calls per tool. Prediction becomes trustworthy at ~100 calls.

| Stage | Action | Unlock |
|-------|--------|--------|
| **Track** | One import change | Per-call token counts, `api_equivalent_cost_usd`, latency logged locally and synced to community lake |
| **Profile** | `acf profiles --update` after 100+ calls | p50/p90 per model and tool type |
| **Predict** | `acf predict "..."` | Pre-run cost estimate + budget guard; backed by community profiles from day one |
| **Observe** | Switch to full executor pipeline | Tool call interception, source URLs, truncation metadata, calibration loop |

Never require Stage 4 to unlock Stage 1. Every stage works independently.
