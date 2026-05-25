"""SQLite schema and connection factory.

All tables use TEXT primary keys (UUIDs stored as strings) and TEXT for
JSON fields so the schema migrates cleanly to Postgres without type changes.
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = os.environ.get("ACF_DB_PATH", "data/acf.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_pricing (
    pricing_id                       TEXT PRIMARY KEY,
    provider                         TEXT NOT NULL,     -- "anthropic" | "openai"
    model                            TEXT NOT NULL,
    effective_from                   TEXT NOT NULL,
    effective_to                     TEXT,              -- NULL = currently active
    input_cost_per_1m_tokens         REAL NOT NULL,
    output_cost_per_1m_tokens        REAL NOT NULL,
    cache_read_cost_per_1m_tokens    REAL,
    cache_write_cost_per_1m_tokens   REAL,
    source_url                       TEXT,
    created_at                       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_configs (
    agent_config_id              TEXT PRIMARY KEY,
    agent_version                TEXT NOT NULL,
    model                        TEXT NOT NULL,
    system_prompt_hash           TEXT NOT NULL,
    tool_registry_hash           TEXT NOT NULL,
    temperature                  REAL NOT NULL,
    max_tool_calls               INTEGER NOT NULL,
    tool_result_truncation_chars INTEGER,
    created_at                   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_runs (
    run_id                  TEXT PRIMARY KEY,
    trace_id                TEXT NOT NULL,
    agent_config_id         TEXT NOT NULL,
    user_prompt_hash        TEXT NOT NULL,
    user_prompt_tokens      INTEGER,
    tools_exposed           TEXT NOT NULL,   -- JSON list
    source                  TEXT NOT NULL,   -- "synthetic" | "production"
    actual_tools_called     TEXT,            -- JSON list; filled after run
    actual_input_tokens     INTEGER,
    actual_output_tokens    INTEGER,
    actual_total_cost_usd   REAL,
    success                 INTEGER,
    latency_ms              INTEGER,
    sample_quality_score    REAL,
    sample_quality_reason   TEXT,
    created_at              TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_calls (
    model_call_id                TEXT PRIMARY KEY,
    trace_id                     TEXT NOT NULL,
    run_id                       TEXT NOT NULL,
    call_index                   INTEGER NOT NULL,    -- 0 = first call in this run
    model                        TEXT NOT NULL,
    input_tokens                 INTEGER NOT NULL,
    output_tokens                INTEGER NOT NULL,
    cache_read_input_tokens      INTEGER DEFAULT 0,   -- tokens served from prompt cache
    cache_write_input_tokens     INTEGER DEFAULT 0,   -- tokens written to prompt cache
    tool_schema_tokens           INTEGER NOT NULL,    -- estimated; same for all calls in a run
    tool_result_tokens_inserted  INTEGER DEFAULT 0,   -- from preceding tool results; 0 for call 0
    finish_reason                TEXT,                -- "end_turn" | "tool_use" | "max_tokens"
    cost_usd                     REAL,
    latency_ms                   INTEGER,
    created_at                   TEXT NOT NULL
);

-- Σ model_calls.input_tokens per run_id MUST equal agent_runs.actual_input_tokens.
-- Any discrepancy is a logging bug. Use `acf check` to detect it.

CREATE TABLE IF NOT EXISTS tool_calls (
    call_id                      TEXT PRIMARY KEY,
    trace_id                     TEXT NOT NULL,
    run_id                       TEXT NOT NULL,
    triggered_by_model_call_id   TEXT NOT NULL,
    consumed_by_model_call_id    TEXT,             -- NULL until next model call is logged
    call_index                   INTEGER NOT NULL,
    tool_name                    TEXT NOT NULL,
    tool_type                    TEXT NOT NULL DEFAULT 'function',
    arguments_json               TEXT,
    result_hash                  TEXT,
    result_preview               TEXT,             -- first 500 chars of raw result
    result_tokens_raw            INTEGER,          -- tokens in full raw result
    result_tokens_inserted       INTEGER,          -- tokens actually sent to model (after truncation)
    was_result_truncated         INTEGER,
    source_urls_returned         TEXT,             -- JSON list of all URLs returned
    source_urls_inserted         TEXT,             -- JSON list of URLs whose content entered context
    source_domains               TEXT,             -- JSON list of normalized domains
    source_traceability_status   TEXT,             -- "full" | "partial" | "none"
    success                      INTEGER NOT NULL DEFAULT 0,
    error_message                TEXT,
    latency_ms                   INTEGER,
    created_at                   TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = get_connection()
    with conn:
        conn.executescript(_SCHEMA)
    conn.close()
