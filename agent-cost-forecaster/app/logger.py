"""Database write operations for all logging tables.

Every public function here corresponds to one write event in the agent lifecycle:
  create_run / finish_run        → agent_runs
  log_model_call                 → model_calls
  create_tool_call_row           → tool_calls (initial insert, status=running)
  finish_tool_call_row           → tool_calls (update with result)
  update_tool_call_consumed_by   → tool_calls (back-fill consumed_by_model_call_id)
  get_or_create_agent_config     → agent_configs
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone

from .db import get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── agent_configs ────────────────────────────────────────────────────────────

def get_or_create_agent_config(
    config: dict,
    tool_registry_hash: str,
    system_prompt_hash: str,
) -> str:
    """Return existing agent_config_id if this exact config was seen before, else insert."""
    agent = config["agent"]
    model = agent["model"]
    conn = get_connection()
    row = conn.execute(
        """SELECT agent_config_id FROM agent_configs
           WHERE tool_registry_hash = ? AND system_prompt_hash = ? AND model = ?""",
        (tool_registry_hash, system_prompt_hash, model),
    ).fetchone()
    if row:
        conn.close()
        return row["agent_config_id"]

    config_id = str(uuid.uuid4())
    truncation = config.get("truncation", {})
    with conn:
        conn.execute(
            """INSERT INTO agent_configs
               (agent_config_id, agent_version, model, system_prompt_hash,
                tool_registry_hash, temperature, max_tool_calls,
                tool_result_truncation_chars, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                config_id,
                agent.get("agent_version", "unknown"),
                model,
                system_prompt_hash,
                tool_registry_hash,
                agent.get("temperature", 0),
                agent.get("max_tool_calls", 3),
                truncation.get("tool_result_max_chars", 4000),
                _now(),
            ),
        )
    conn.close()
    return config_id


# ── agent_runs ───────────────────────────────────────────────────────────────

def create_run(
    run_id: str,
    trace_id: str,
    agent_config_id: str,
    user_prompt: str,
    user_prompt_tokens: int,
    tools_exposed: list[str],
    source: str,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO agent_runs
               (run_id, trace_id, agent_config_id, user_prompt_hash,
                user_prompt_tokens, tools_exposed, source, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                trace_id,
                agent_config_id,
                hash_text(user_prompt),
                user_prompt_tokens,
                json.dumps(tools_exposed),
                source,
                _now(),
            ),
        )
    conn.close()


def finish_run(
    run_id: str,
    actual_tools_called: list[str],
    actual_input_tokens: int,
    actual_output_tokens: int,
    actual_total_cost_usd: float,
    success: bool,
    latency_ms: int,
    sample_quality_score: float,
    sample_quality_reason: str,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE agent_runs SET
               actual_tools_called   = ?,
               actual_input_tokens   = ?,
               actual_output_tokens  = ?,
               actual_total_cost_usd = ?,
               success               = ?,
               latency_ms            = ?,
               sample_quality_score  = ?,
               sample_quality_reason = ?
               WHERE run_id = ?""",
            (
                json.dumps(sorted(set(actual_tools_called))),
                actual_input_tokens,
                actual_output_tokens,
                actual_total_cost_usd,
                1 if success else 0,
                latency_ms,
                sample_quality_score,
                sample_quality_reason,
                run_id,
            ),
        )
    conn.close()


# ── model_calls ──────────────────────────────────────────────────────────────

def log_model_call(
    model_call_id: str,
    trace_id: str,
    run_id: str,
    call_index: int,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int,
    tool_schema_tokens: int,
    tool_result_tokens_inserted: int,
    finish_reason: str,
    cost_usd: float,
    latency_ms: int,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO model_calls
               (model_call_id, trace_id, run_id, call_index, model,
                input_tokens, output_tokens, cached_input_tokens,
                tool_schema_tokens, tool_result_tokens_inserted,
                finish_reason, cost_usd, latency_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                model_call_id,
                trace_id,
                run_id,
                call_index,
                model,
                input_tokens,
                output_tokens,
                cached_input_tokens,
                tool_schema_tokens,
                tool_result_tokens_inserted,
                finish_reason,
                cost_usd,
                latency_ms,
                _now(),
            ),
        )
    conn.close()


# ── tool_calls ───────────────────────────────────────────────────────────────

def create_tool_call_row(
    call_id: str,
    trace_id: str,
    run_id: str,
    triggered_by_model_call_id: str,
    call_index: int,
    tool_name: str,
    arguments_json: str,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """INSERT INTO tool_calls
               (call_id, trace_id, run_id, triggered_by_model_call_id,
                call_index, tool_name, tool_type, arguments_json,
                success, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'function', ?, 0, ?)""",
            (
                call_id,
                trace_id,
                run_id,
                triggered_by_model_call_id,
                call_index,
                tool_name,
                arguments_json,
                _now(),
            ),
        )
    conn.close()


def finish_tool_call_row(
    call_id: str,
    success: bool,
    result_hash: str | None = None,
    result_preview: str | None = None,
    result_tokens_raw: int | None = None,
    result_tokens_inserted: int | None = None,
    was_result_truncated: bool = False,
    source_urls_returned: list | None = None,
    source_urls_inserted: list | None = None,
    source_domains: list | None = None,
    source_traceability_status: str = "none",
    latency_ms: int | None = None,
    error_message: str | None = None,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """UPDATE tool_calls SET
               success                    = ?,
               result_hash                = ?,
               result_preview             = ?,
               result_tokens_raw          = ?,
               result_tokens_inserted     = ?,
               was_result_truncated       = ?,
               source_urls_returned       = ?,
               source_urls_inserted       = ?,
               source_domains             = ?,
               source_traceability_status = ?,
               latency_ms                 = ?,
               error_message              = ?
               WHERE call_id = ?""",
            (
                1 if success else 0,
                result_hash,
                result_preview,
                result_tokens_raw,
                result_tokens_inserted,
                1 if was_result_truncated else 0,
                json.dumps(source_urls_returned or []),
                json.dumps(source_urls_inserted or []),
                json.dumps(source_domains or []),
                source_traceability_status,
                latency_ms,
                error_message,
                call_id,
            ),
        )
    conn.close()


def update_tool_call_consumed_by(call_id: str, consumed_by_model_call_id: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE tool_calls SET consumed_by_model_call_id = ? WHERE call_id = ?",
            (consumed_by_model_call_id, call_id),
        )
    conn.close()
