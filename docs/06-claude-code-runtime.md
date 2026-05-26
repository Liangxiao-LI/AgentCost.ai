# Claude Code as First Target Runtime

## Claude Code as First Target Runtime

The first target agent runtime is **Claude Code**, because it is the agent the founder already uses most. Agent Cost Forecaster should not build its own agent runtime in Milestone 1. Instead, it instruments Claude API execution — the same model calls Claude Code makes.

```
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
- Logging every `messages.create()` call: input tokens, output tokens, cache tokens
- Logging every tool call: arguments, result, source URLs, latency, tokens inserted

The executor does not replicate Claude Code's full feature set. It replicates the **observable API surface** — model calls and tool calls — with the same models and tools.

### Why Not Build a Custom Runtime in Milestone 1

Building a custom runtime would:
- Add complexity that delays the first logged run
- Produce profiles that do not match real Claude Code behavior
- Create a gap between what you observe and what you actually use

Using the Anthropic SDK with the same models and tools means the logged profiles reflect Claude Code's actual token cost structure.

### Agent Configuration

Use Claude Haiku for batch logging (low cost, high volume). Switch to `claude-sonnet-4-6` when you want to profile the model you actually use in production.

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

### Tool Schema Format

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

### API-Equivalent Pricing

These are the prices used to compute `api_equivalent_cost_usd`. Under Claude Code Pro subscription, they are imputed values — not actual billed amounts. All prices are per 1M tokens (`price_unit = "per_1m_tokens"`).

| Model | `input_price_per_1m` | `output_price_per_1m` | `cache_read_price_per_1m` | `cache_write_price_per_1m` |
|-------|----------------------|-----------------------|---------------------------|----------------------------|
| `claude-haiku-4-5-20251001` | $0.80 | $4.00 | $0.08 | $1.00 |
| `claude-sonnet-4-6` | $3.00 | $15.00 | $0.30 | $3.75 |

### MCP Tools — Deferred to Milestone 2+

Claude Code uses MCP (Model Context Protocol) servers for tools like Brave Search, file access, and custom integrations. MCP tool wrapping requires intercepting at the MCP client level, which is more complex than plain function tools.

In Milestone 1, approximate Claude Code's tool behavior using Anthropic function tools (`web_search` via DuckDuckGo, `calculator`). Add real MCP tool interception in Milestone 2 once the logging loop is proven with function tools.

---

## Claude Code Pro Cost Accounting

Claude Code Pro is a **subscription-based product**, not a direct Anthropic API billing arrangement. This has concrete implications for how Agent Cost Forecaster represents cost.

### Two Cost Dimensions

| Field | Meaning |
|-------|---------|
| `actual_api_equivalent_cost_usd` | The theoretical API cost of the run, computed from observed token usage using Anthropic's public API pricing table. This is **imputed**, not billed. Used for all profiling, p50/p90 estimation, and budget guard comparisons. |
| `actual_cash_cost_usd` | Real money spent — e.g. the Claude Code Pro subscription fee, prorated or allocated per run. Under a subscription, the marginal per-run cash cost is zero, but the founder may allocate a share of the monthly fee for accounting purposes. |

### `billing_mode` and `cost_basis`

Every run and model call carries two classification fields:

- `billing_mode` — the commercial billing arrangement: `"claude_code_pro_subscription"` / `"anthropic_api"` / `"openai_api"` / `"enterprise_contract"`
- `cost_basis` — how to interpret the monetary cost field: `"api_equivalent_imputed"` / `"actual_api_billed"` / `"subscription_allocated"` / `"unknown"`

When `billing_mode = "claude_code_pro_subscription"`, every cost field labelled as `api_equivalent_cost_usd` carries `cost_basis = "api_equivalent_imputed"`. The system must never present this as exact billed cost.

### API-Equivalent Cost Formula

```
api_equivalent_cost_usd =
    input_tokens                / 1_000_000 * input_price_per_1m
  + output_tokens               / 1_000_000 * output_price_per_1m
  + cache_read_input_tokens     / 1_000_000 * cache_read_price_per_1m
  + cache_write_input_tokens    / 1_000_000 * cache_write_price_per_1m
```

Pricing values come from the `model_pricing` table and are snapshotted at prediction and logging time so historical comparisons survive price changes.

### Why API-Equivalent Cost Is Still Useful Under Subscription

Although the per-run cash cost is zero under Claude Code Pro, API-equivalent cost is still the right unit for profiling:

- **Comparable across runs** — the same prompt on a heavier day costs more in token terms.
- **Comparable across models** — swap Haiku for Sonnet and the cost impact is immediately visible.
- **Comparable across providers** — switching from Claude to GPT-4o is measurable in the same unit.
- **Directly transferable** — if the founder later deploys via the direct Anthropic API, the profiles already use the right unit.

### `actual_cash_cost_usd` vs. `actual_api_equivalent_cost_usd`

`actual_cash_cost_usd` answers: *"How much money did I actually spend?"* Under Claude Code Pro it is either zero at the per-run level or a prorated share of the monthly subscription. It is **not used** for p50/p90 profiling, calibration, or budget guard comparisons — those all use `actual_api_equivalent_cost_usd`.

When `billing_mode = "anthropic_api"`, `actual_api_equivalent_cost_usd` may also equal the actual billed amount. In that case `cost_basis = "actual_api_billed"` and the two fields converge. The field naming and formula stay identical — only `cost_basis` changes.

If pricing is unknown: log tokens and set `cost_basis = "unknown"`. Never block logging because pricing is missing.
