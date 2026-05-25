"""Claude model pricing and cost computation.

Pricing rows are never updated in place. To update prices:
  1. Set effective_to on the current active row.
  2. Insert a new row with effective_from = today.
This preserves the full pricing history and keeps historical run costs accurate.
"""

import uuid
from datetime import datetime, timezone

from .db import get_connection

# USD per 1M tokens — sourced from https://www.anthropic.com/pricing
_STATIC_PRICING = [
    {
        "provider": "anthropic",
        "model": "claude-haiku-4-5-20251001",
        "input_cost_per_1m_tokens": 0.80,
        "output_cost_per_1m_tokens": 4.00,
        "cache_read_cost_per_1m_tokens": 0.08,
        "cache_write_cost_per_1m_tokens": 1.00,
        "source_url": "https://www.anthropic.com/pricing",
    },
    {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "input_cost_per_1m_tokens": 3.00,
        "output_cost_per_1m_tokens": 15.00,
        "cache_read_cost_per_1m_tokens": 0.30,
        "cache_write_cost_per_1m_tokens": 3.75,
        "source_url": "https://www.anthropic.com/pricing",
    },
]


def seed_pricing() -> None:
    """Insert static pricing rows if no active row exists for each model."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        for row in _STATIC_PRICING:
            exists = conn.execute(
                "SELECT 1 FROM model_pricing WHERE model = ? AND effective_to IS NULL",
                (row["model"],),
            ).fetchone()
            if not exists:
                conn.execute(
                    """INSERT INTO model_pricing
                       (pricing_id, provider, model, effective_from, effective_to,
                        input_cost_per_1m_tokens, output_cost_per_1m_tokens,
                        cache_read_cost_per_1m_tokens, cache_write_cost_per_1m_tokens,
                        source_url, created_at)
                       VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        row["provider"],
                        row["model"],
                        now,
                        row["input_cost_per_1m_tokens"],
                        row["output_cost_per_1m_tokens"],
                        row.get("cache_read_cost_per_1m_tokens"),
                        row.get("cache_write_cost_per_1m_tokens"),
                        row.get("source_url"),
                        now,
                    ),
                )
    conn.close()


def get_pricing(model: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM model_pricing WHERE model = ? AND effective_to IS NULL",
        (model,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def compute_cost(
    pricing: dict,
    input_tokens: int,
    output_tokens: int,
    cache_read_input_tokens: int = 0,
    cache_write_input_tokens: int = 0,
) -> float:
    """Compute USD cost for one Anthropic API call.

    Anthropic billing breakdown:
      - cache_read_input_tokens  → charged at cache_read rate (~10% of input)
      - cache_write_input_tokens → charged at cache_write rate (~125% of input)
      - remaining input tokens   → charged at standard input rate
      - output tokens            → charged at output rate
    """
    regular_input = max(0, input_tokens - cache_read_input_tokens - cache_write_input_tokens)
    cache_read_rate = pricing.get("cache_read_cost_per_1m_tokens") or 0.0
    cache_write_rate = pricing.get("cache_write_cost_per_1m_tokens") or pricing["input_cost_per_1m_tokens"]

    return (
        regular_input              * pricing["input_cost_per_1m_tokens"]  / 1_000_000
        + cache_read_input_tokens  * cache_read_rate                      / 1_000_000
        + cache_write_input_tokens * cache_write_rate                     / 1_000_000
        + output_tokens            * pricing["output_cost_per_1m_tokens"] / 1_000_000
    )
