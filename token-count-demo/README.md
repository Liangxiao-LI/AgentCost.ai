# OpenAI Input Token Counting Demo

A small CLI tool that calls OpenAI's `POST /v1/responses/input_tokens` endpoint
to measure how different payload types affect input token counts — **before** any
model generation happens.

## What this demo shows

| Case | What it tests |
|------|---------------|
| `simple_text` | Bare text string — the smallest possible payload |
| `instructions` | System/developer instructions added alongside the user prompt |
| `conversation` | Multi-turn history (each prior turn is re-sent in full) |
| `tools` | Function schema injected into the context window |
| `image` | Vision image processed into tile tokens |
| `rag_context` | Large retrieved context (100× paragraph) simulating RAG |
| `weather_no_tools` | Weather question without tools (delta baseline) |
| `weather_with_tools` | Same question with tool schema (delta comparison) |

After the main table the demo prints **delta comparisons** that show exactly how
many extra tokens each addition contributes.

## What counts as input tokens

- User text (prompt)
- System / developer instructions
- Full conversation history (every prior turn)
- Tool / function schemas (name + description + parameter JSON Schema)
- Images (tokenised into resolution-dependent tiles)
- Retrieved documents injected into the prompt (RAG context)

## What does NOT get counted by this pre-run endpoint

- Output tokens the model will generate
- Future agent steps or reasoning loops that have not happened yet
- Tool-call results that have not been added to the conversation
- Retries, re-plans, or additional retrieval rounds

For agents, total cost requires summing every model call plus generated output,
tool results, retrieved documents, and repeated loop steps.

---

## Setup

```bash
# 1. Clone / enter the project
cd token-count-demo

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set your OpenAI API key
export OPENAI_API_KEY="sk-..."
# (or copy .env.example → .env and load it with `source .env`)
```

## Usage

```bash
# Run all cases (pretty table via rich)
python -m token_count_demo.main

# Use a different model
python -m token_count_demo.main --model gpt-4o

# Run a single named case
python -m token_count_demo.main --case tools
python -m token_count_demo.main --case image
python -m token_count_demo.main --case rag_context

# Raw JSON output (useful for scripting)
python -m token_count_demo.main --json

# Combine flags
python -m token_count_demo.main --model gpt-4o --case conversation --json
```

### Available case names

`simple_text`, `instructions`, `conversation`, `tools`, `image`,
`rag_context`, `weather_no_tools`, `weather_with_tools`

## What to look for in the output

1. **Instructions overhead** — `instructions` vs `simple_text` shows the extra
   tokens a system prompt always adds, even if it is short.

2. **Tool schema overhead** — `weather_with_tools` vs `weather_no_tools` isolates
   the token cost of the function definition itself. Complex tools with long
   descriptions or many parameters are proportionally more expensive.

3. **RAG context explosion** — `rag_context` vs `simple_text` shows how
   retrieval-augmented prompts can dwarf everything else in the context window.

4. **Image tile count** — `image` shows that vision input is tokenised into a
   fixed number of tiles based on resolution, not on the semantic content.

5. **Conversation growth** — each additional turn in `conversation` adds roughly
   as many tokens as that message contains, with a small per-message overhead.

## Project structure

```
token-count-demo/
├── README.md
├── requirements.txt
├── .env.example
└── token_count_demo/
    ├── __init__.py
    ├── client.py   ← OpenAI client factory + API key check
    ├── cases.py    ← all test-case definitions
    └── main.py     ← CLI entry point, table rendering, delta comparisons
```

## Extending with new cases

Add a new dict to the list returned by `build_cases()` in `cases.py`:

```python
{
    "name": "my_case",
    "description": "What this case tests",
    "payload": {
        "model": model,
        "input": "...",
        # any other fields accepted by the endpoint
    },
},
```

It will automatically appear in `--case my_case` and in the full run.
