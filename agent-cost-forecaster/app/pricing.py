"""Static model pricing table and cost computation."""

import uuid
from datetime import datetime, timezone

from .db import get_connection

# Prices in USD per 1M tokens — update by closing the active row (effective_to = today)
# and inserting a new row. Never update in place.
_STATIC_PRICING = [
    {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "input_cost_per_1m_tokens": 0.15,
        "output_cost_per_1m_tokens": 0.60,
        "cached_input_cost_per_1m_tokens": 0.075,
        "source_url": "https://openai.com/api/pricing",
    },
    {
        "provider": "openai",
        "model": "gpt-4o",
        "input_cost_per_1m_tokens": 2.50,
        "output_cost_per_1m_tokens": 10.00,
        "cached_input_cost_per_1m_tokens": 1.25,
        "source_url": "https://openai.com/api/pricing",
    },
]


def seed_pricing() -> None:
    """Insert static pricing rows if no active row exists for each model."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        for row in _STATIC_PRICING:
            existing = conn.execute(
                "SELECT pricing_id FROM model_pricing WHERE model = ? AND effective_to IS NULL",
                (row["model"],),
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO model_pricing
                       (pricing_id, provider, model, effective_from, effective_to,
                        input_cost_per_1m_tokens, output_cost_per_1m_tokens,
                        cached_input_cost_per_1m_tokens, source_url, created_at)
                       VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        row["provider"],
                        row["model"],
                        now,
                        row["input_cost_per_1m_tokens"],
                        row["output_cost_per_1m_tokens"],
                        row.get("cached_input_cost_per_1m_tokens"),
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
    cached_input_tokens: int = 0,
) -> float:
    billable_input = input_tokens - cached_input_tokens
    cached_rate = pricing.get("cached_input_cost_per_1m_tokens") or pricing["input_cost_per_1m_tokens"]
    return (
        billable_input * pricing["input_cost_per_1m_tokens"] / 1_000_000
        + cached_input_tokens * cached_rate / 1_000_000
        + output_tokens * pricing["output_cost_per_1m_tokens"] / 1_000_000
    )
