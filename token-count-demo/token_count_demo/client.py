import os
from openai import OpenAI


def get_client() -> OpenAI:
    """Return an authenticated OpenAI client.

    Raises SystemExit if OPENAI_API_KEY is not set so callers get a clear
    error message rather than an opaque authentication failure later.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SystemExit(
            "Error: OPENAI_API_KEY environment variable is not set.\n"
            "Export it before running:  export OPENAI_API_KEY='sk-...'"
        )
    return OpenAI(api_key=api_key)
