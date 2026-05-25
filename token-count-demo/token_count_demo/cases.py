"""Token counting test cases.

Each case is a dict with:
  name        – short slug used with --case
  description – one-line explanation of what this case tests
  payload     – kwargs passed directly to client.responses.input_tokens.count()

The tool schema used in Cases D and G is defined once and reused so the
comparison in Case G is exact.
"""

_WEATHER_TOOL = {
    "type": "function",
    "name": "get_weather",
    "description": "Get the current weather in a location",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {"type": "string"},
        },
        "required": ["location"],
    },
}

_WEATHER_QUESTION = "What is the weather in San Francisco?"

# A 100-repetition paragraph that simulates a RAG-retrieved context chunk.
_RETRIEVED_PARAGRAPH = (
    "The transformer architecture relies on self-attention mechanisms that "
    "allow each token to attend to every other token in the sequence. "
    "This enables parallel training and captures long-range dependencies "
    "more effectively than recurrent models. "
)
_LONG_CONTEXT = _RETRIEVED_PARAGRAPH * 100


def build_cases(model: str) -> list[dict]:
    """Return all test cases parameterised by the chosen model."""
    return [
        # ── Case A ──────────────────────────────────────────────────────────
        # Baseline: a single bare text string.  The smallest possible payload.
        {
            "name": "simple_text",
            "description": "Bare text prompt — the smallest possible payload",
            "payload": {
                "model": model,
                "input": "Tell me a joke.",
            },
        },

        # ── Case B ──────────────────────────────────────────────────────────
        # Adding a system/developer instruction.  Even a short instruction adds
        # tokens because it becomes a separate message in the context window.
        {
            "name": "instructions",
            "description": "System instructions + user prompt",
            "payload": {
                "model": model,
                "instructions": "You are a helpful assistant that explains concepts simply.",
                "input": "Explain quantum computing in one sentence.",
            },
        },

        # ── Case C ──────────────────────────────────────────────────────────
        # Multi-turn conversation.  Each prior turn is included verbatim, so
        # token count grows roughly linearly with history length.
        {
            "name": "conversation",
            "description": "Multi-turn conversation history",
            "payload": {
                "model": model,
                "input": [
                    {"role": "user", "content": "What is 2 + 2?"},
                    {"role": "assistant", "content": "2 + 2 equals 4."},
                    {"role": "user", "content": "What about 3 + 3?"},
                ],
            },
        },

        # ── Case D ──────────────────────────────────────────────────────────
        # Tool schema only.  The function definition (name, description,
        # parameter schema) is serialised and injected into the context, which
        # is why tools with rich descriptions / many parameters cost more.
        {
            "name": "tools",
            "description": "User prompt + one function tool schema",
            "payload": {
                "model": model,
                "tools": [_WEATHER_TOOL],
                "input": _WEATHER_QUESTION,
            },
        },

        # ── Case E ──────────────────────────────────────────────────────────
        # Image URL.  Vision-capable models tokenise images into a fixed number
        # of tiles; the exact count depends on image resolution and the
        # model's tile size.
        {
            "name": "image",
            "description": "User prompt + image URL (vision input)",
            "payload": {
                "model": model,
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_image",
                                "image_url": (
                                    "https://upload.wikimedia.org/wikipedia/commons/"
                                    "thumb/3/3f/Fronalpstock_big.jpg/"
                                    "640px-Fronalpstock_big.jpg"
                                ),
                            },
                            {
                                "type": "input_text",
                                "text": "Describe this image briefly.",
                            },
                        ],
                    }
                ],
            },
        },

        # ── Case F ──────────────────────────────────────────────────────────
        # Long retrieved context (simulated RAG).  100 repetitions of a
        # paragraph show how retrieval-augmented prompts balloon token counts.
        {
            "name": "rag_context",
            "description": "Large retrieved context (100× paragraph) simulating RAG",
            "payload": {
                "model": model,
                "input": (
                    "Here is retrieved context:\n\n"
                    + _LONG_CONTEXT
                    + "\n\nNow summarize the key points."
                ),
            },
        },

        # ── Case G-a ────────────────────────────────────────────────────────
        # Same question as Case D but WITHOUT any tools — used as the baseline
        # half of the tools-vs-no-tools delta comparison.
        {
            "name": "weather_no_tools",
            "description": "Weather question WITHOUT tool schema (delta baseline)",
            "payload": {
                "model": model,
                "input": _WEATHER_QUESTION,
            },
        },

        # ── Case G-b ────────────────────────────────────────────────────────
        # Same question WITH the tool schema.  The delta between G-a and G-b
        # shows exactly how many tokens the tool definition contributes.
        {
            "name": "weather_with_tools",
            "description": "Same weather question WITH tool schema (delta comparison)",
            "payload": {
                "model": model,
                "tools": [_WEATHER_TOOL],
                "input": _WEATHER_QUESTION,
            },
        },
    ]
