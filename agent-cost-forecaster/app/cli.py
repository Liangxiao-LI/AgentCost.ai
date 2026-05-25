"""acf CLI — Agent Cost Forecaster.

Commands (Milestone 1 — Observability):
  acf run "prompt"          Run one prompt through Claude and log the full trace
  acf run-batch             Run tasks from seed_tasks.jsonl
  acf generate-tasks        Expand seed_templates.yaml → seed_tasks.jsonl
  acf trace <run-id>        Show model call + tool call chain
  acf sources <run-id>      Show source URLs and domains
  acf check                 Verify log integrity (token sum + completeness)
"""

import argparse
import json
import os
import random
import sys
from pathlib import Path

import yaml

try:
    from rich.console import Console
    from rich.table import Table
    _RICH = True
    console = Console()
except ImportError:
    _RICH = False
    console = None  # type: ignore[assignment]

from .db import get_connection, init_db
from .executor import run_agent
from .logger import get_or_create_agent_config
from .pricing import seed_pricing
from .tool_registry import (
    compute_system_prompt_hash,
    compute_tool_registry_hash,
    get_enabled_tools,
    get_tool_schemas,
)


# ── Config loading ────────────────────────────────────────────────────────────

def load_config(path: str = "config/agent_config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ── Shared setup ──────────────────────────────────────────────────────────────

def _setup(config: dict) -> str:
    """Initialise DB, seed pricing, return agent_config_id."""
    init_db()
    seed_pricing()
    tool_names = get_enabled_tools(config)
    schemas = get_tool_schemas(tool_names)
    return get_or_create_agent_config(
        config,
        tool_registry_hash=compute_tool_registry_hash(schemas),
        system_prompt_hash=compute_system_prompt_hash(
            config["agent"].get("system_prompt", "")
        ),
    )


def _print(msg: str, style: str = "") -> None:
    if _RICH:
        console.print(f"[{style}]{msg}[/{style}]" if style else msg)
    else:
        print(msg)


# ── acf run ───────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    agent_config_id = _setup(config)

    _print(f"Model : {config['agent']['model']}", "dim")
    _print(f"Prompt: {args.prompt[:120]}{'…' if len(args.prompt) > 120 else ''}", "dim")

    result = run_agent(args.prompt, config, agent_config_id, source=args.source)

    if _RICH:
        t = Table(title="Run Result", show_lines=True)
        t.add_column("Field", style="cyan", no_wrap=True)
        t.add_column("Value")
        t.add_row("Run ID",        result["run_id"])
        t.add_row("Trace ID",      result["trace_id"])
        t.add_row("Model calls",   str(result["model_calls"]))
        t.add_row("Tool calls",    str(result["tool_calls"]))
        t.add_row("Tools used",    ", ".join(result["tools_called"]) or "none")
        t.add_row("Input tokens",  str(result["total_input_tokens"]))
        t.add_row("Output tokens", str(result["total_output_tokens"]))
        t.add_row("Total cost",    f"${result['total_cost_usd']:.6f}")
        t.add_row("Success",       "[green]✓[/green]" if result["success"] else "[red]✗[/red]")
        console.print(t)
        if result.get("final_answer"):
            console.print(f"\n[bold]Answer:[/bold] {result['final_answer'][:500]}")
    else:
        print(f"\nRun ID:        {result['run_id']}")
        print(f"Trace ID:      {result['trace_id']}")
        print(f"Tools used:    {', '.join(result['tools_called']) or 'none'}")
        print(f"Input tokens:  {result['total_input_tokens']}")
        print(f"Output tokens: {result['total_output_tokens']}")
        print(f"Total cost:    ${result['total_cost_usd']:.6f}")
        if result.get("final_answer"):
            print(f"\nAnswer: {result['final_answer'][:500]}")

    _print(f"\nLogged → {os.environ.get('ACF_DB_PATH', 'data/acf.db')}", "dim")


# ── acf run-batch ──────────────────────────────────────────────────────────────

def cmd_run_batch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    agent_config_id = _setup(config)

    tasks_path = Path(args.tasks)
    if not tasks_path.exists():
        print(f"Tasks file not found: {args.tasks}", file=sys.stderr)
        sys.exit(1)

    tasks = [json.loads(l) for l in tasks_path.read_text().splitlines() if l.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    total = len(tasks)
    succeeded = failed = 0
    total_cost = 0.0

    _print(f"Running {total} tasks on {config['agent']['model']}…\n")

    for i, task in enumerate(tasks, 1):
        prompt = task.get("prompt", "")
        category = task.get("category", "unknown")
        try:
            result = run_agent(prompt, config, agent_config_id, source=args.source)
            succeeded += 1
            total_cost += result["total_cost_usd"]
            tools_str = ",".join(result["tools_called"]) or "none"
            if _RICH:
                console.print(
                    f"  [{i:>3}/{total}] [green]✓[/green] [{category}] "
                    f"{prompt[:65]}{'…' if len(prompt) > 65 else ''}"
                    f"  tools={tools_str}  ${result['total_cost_usd']:.6f}"
                )
            else:
                print(f"  [{i}/{total}] OK [{category}] ${result['total_cost_usd']:.6f}")
        except Exception as exc:
            failed += 1
            if _RICH:
                console.print(f"  [{i:>3}/{total}] [red]✗[/red] [{category}] {prompt[:65]} → {exc}")
            else:
                print(f"  [{i}/{total}] FAIL [{category}]: {exc}")

    print()
    _print(f"Batch done: {succeeded}/{total} succeeded, {failed} failed")
    _print(f"Total cost: ${total_cost:.6f}")
    _print(f"Logged → {os.environ.get('ACF_DB_PATH', 'data/acf.db')}")


# ── acf generate-tasks ─────────────────────────────────────────────────────────

def cmd_generate_tasks(args: argparse.Namespace) -> None:
    templates_path = Path(args.templates)
    if not templates_path.exists():
        print(f"Templates not found: {args.templates}", file=sys.stderr)
        sys.exit(1)

    with open(templates_path) as f:
        data = yaml.safe_load(f)

    variables: dict = data.get("variables", {})
    tasks: list[dict] = []

    for category, section in data.items():
        if category == "variables" or not isinstance(section, dict):
            continue
        target_tools: list = section.get("target_tools", [])
        for template in section.get("templates", []):
            for _ in range(args.n):
                prompt = template
                for var, values in variables.items():
                    if f"{{{var}}}" in prompt:
                        prompt = prompt.replace(f"{{{var}}}", str(random.choice(values)))
                tasks.append({
                    "prompt": prompt,
                    "category": category,
                    "target_tools": target_tools,
                    "generation_strategy": "template",
                })

    random.shuffle(tasks)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for task in tasks:
            f.write(json.dumps(task) + "\n")

    _print(f"Generated {len(tasks)} tasks → {output_path}")
    counts: dict[str, int] = {}
    for t in tasks:
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    for cat, n in sorted(counts.items()):
        _print(f"  {cat}: {n}", "dim")


# ── acf trace ──────────────────────────────────────────────────────────────────

def cmd_trace(args: argparse.Namespace) -> None:
    conn = get_connection()
    run = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (args.run_id,)).fetchone()
    if not run:
        print(f"Run not found: {args.run_id}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    mcs = conn.execute(
        "SELECT * FROM model_calls WHERE run_id = ? ORDER BY call_index", (args.run_id,)
    ).fetchall()
    tcs = conn.execute(
        "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY call_index", (args.run_id,)
    ).fetchall()
    conn.close()

    if _RICH:
        console.print(f"\n[bold]Run[/bold]   {run['run_id']}")
        console.print(f"Trace  {run['trace_id']}")
        console.print(f"Source {run['source']}  quality={run['sample_quality_score']} ({run['sample_quality_reason']})")
        console.print(
            f"Cost   ${run['actual_total_cost_usd']:.6f}  "
            f"in={run['actual_input_tokens']}  out={run['actual_output_tokens']}"
        )
        console.print(f"Tools called  {run['actual_tools_called']}\n")

        mc_t = Table(title=f"Model Calls ({len(mcs)})", show_lines=True)
        for col in ("idx", "input", "output", "cache_read", "cache_write", "schema_tok", "tool_result_tok", "stop_reason", "cost"):
            mc_t.add_column(col, justify="right" if col not in ("stop_reason",) else "left")
        for mc in mcs:
            mc_t.add_row(
                str(mc["call_index"]),
                str(mc["input_tokens"]),
                str(mc["output_tokens"]),
                str(mc["cache_read_input_tokens"] or 0),
                str(mc["cache_write_input_tokens"] or 0),
                str(mc["tool_schema_tokens"]),
                str(mc["tool_result_tokens_inserted"] or 0),
                mc["finish_reason"] or "",
                f"${mc['cost_usd']:.6f}",
            )
        console.print(mc_t)

        if tcs:
            tc_t = Table(title=f"Tool Calls ({len(tcs)})", show_lines=True)
            for col in ("idx", "tool", "raw_tok", "ins_tok", "trunc", "traceability", "ms", "ok"):
                tc_t.add_column(col)
            for tc in tcs:
                tc_t.add_row(
                    str(tc["call_index"]),
                    tc["tool_name"],
                    str(tc["result_tokens_raw"] or "–"),
                    str(tc["result_tokens_inserted"] or "–"),
                    "yes" if tc["was_result_truncated"] else "no",
                    tc["source_traceability_status"] or "–",
                    str(tc["latency_ms"] or "–"),
                    "[green]✓[/green]" if tc["success"] else "[red]✗[/red]",
                )
            console.print(tc_t)
    else:
        print(f"\nRun  {run['run_id']}")
        print(f"Cost ${run['actual_total_cost_usd']:.6f}  in={run['actual_input_tokens']} out={run['actual_output_tokens']}")
        for mc in mcs:
            print(f"  model[{mc['call_index']}] in={mc['input_tokens']} out={mc['output_tokens']} stop={mc['finish_reason']}")
        for tc in tcs:
            print(f"  tool[{tc['call_index']}] {tc['tool_name']} raw={tc['result_tokens_raw']} ins={tc['result_tokens_inserted']}")


# ── acf sources ────────────────────────────────────────────────────────────────

def cmd_sources(args: argparse.Namespace) -> None:
    conn = get_connection()
    tcs = conn.execute(
        "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY call_index", (args.run_id,)
    ).fetchall()
    conn.close()

    if not tcs:
        print(f"No tool calls found for run: {args.run_id}")
        return

    for tc in tcs:
        domains = json.loads(tc["source_domains"] or "[]")
        urls = json.loads(tc["source_urls_returned"] or "[]")
        status = tc["source_traceability_status"] or "unknown"
        ok = "✓" if tc["success"] else "✗"

        if _RICH:
            colour = "green" if status == "full" else ("yellow" if status == "partial" else "red")
            console.print(f"\n[bold]{ok} {tc['tool_name']}[/bold] (call {tc['call_index']})  "
                          f"traceability=[{colour}]{status}[/{colour}]")
            if domains:
                console.print(f"  Domains: {', '.join(domains)}")
            for url in urls[:8]:
                console.print(f"    • {url}", style="dim")
            if len(urls) > 8:
                console.print(f"    … and {len(urls) - 8} more", style="dim")
            if tc["result_tokens_inserted"] is not None:
                console.print(
                    f"  Tokens: {tc['result_tokens_inserted']} inserted  "
                    f"(raw: {tc['result_tokens_raw']})"
                )
        else:
            print(f"\n{ok} {tc['tool_name']} (call {tc['call_index']}) [{status}]")
            print(f"  Domains: {', '.join(domains)}")
            for url in urls[:5]:
                print(f"    {url}")


# ── acf check ──────────────────────────────────────────────────────────────────

def cmd_check(_args: argparse.Namespace) -> None:
    """Verify log integrity against six criteria."""
    conn = get_connection()

    total_runs = conn.execute(
        "SELECT COUNT(*) FROM agent_runs WHERE success = 1"
    ).fetchone()[0]

    total_tool_calls = conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]

    discrepancies = conn.execute("""
        SELECT r.run_id,
               r.actual_input_tokens                AS run_total,
               SUM(m.input_tokens)                  AS mc_total,
               r.actual_input_tokens - SUM(m.input_tokens) AS delta
        FROM agent_runs r
        JOIN model_calls m ON r.run_id = m.run_id
        WHERE r.success = 1
        GROUP BY r.run_id
        HAVING delta != 0
    """).fetchall()

    missing_result_tokens = conn.execute(
        "SELECT COUNT(*) FROM tool_calls WHERE success = 1 AND result_tokens_inserted IS NULL"
    ).fetchone()[0]

    missing_traceability = conn.execute(
        "SELECT COUNT(*) FROM tool_calls WHERE success = 1 AND source_traceability_status IS NULL"
    ).fetchone()[0]

    web_no_domains = conn.execute(
        """SELECT COUNT(*) FROM tool_calls
           WHERE success = 1 AND tool_name = 'web_search'
             AND (source_domains = '[]' OR source_domains IS NULL)"""
    ).fetchone()[0]

    conn.close()

    checks = [
        ("Successful runs logged",                    total_runs,            total_runs > 0),
        ("Tool calls logged",                          total_tool_calls,      True),
        ("Token sum mismatches (must be 0)",           len(discrepancies),    len(discrepancies) == 0),
        ("Tool calls missing result_tokens_inserted",  missing_result_tokens, missing_result_tokens == 0),
        ("Tool calls missing traceability_status",     missing_traceability,  missing_traceability == 0),
        ("web_search calls with no source domains",    web_no_domains,        web_no_domains == 0),
    ]
    all_ok = all(ok for _, _, ok in checks)

    if _RICH:
        t = Table(title="Log Integrity Check", show_lines=True)
        t.add_column("Check", style="cyan")
        t.add_column("Value", justify="right")
        t.add_column("Status")
        for label, value, ok in checks:
            t.add_row(label, str(value), "[green]pass[/green]" if ok else "[red]FAIL[/red]")
        console.print(t)

        if discrepancies:
            console.print("\n[bold red]Token sum discrepancies:[/bold red]")
            for row in discrepancies:
                console.print(
                    f"  run_id={row['run_id']}  "
                    f"run_total={row['run_total']}  mc_total={row['mc_total']}  "
                    f"delta={row['delta']}"
                )

        if all_ok:
            console.print("\n[bold green]All checks passed — logs are complete.[/bold green]")
        else:
            console.print("\n[bold red]Some checks failed.[/bold red]")
            sys.exit(1)
    else:
        for label, value, ok in checks:
            print(f"{'PASS' if ok else 'FAIL'}  {label}: {value}")
        if discrepancies:
            for row in discrepancies:
                print(f"  {row['run_id']}  delta={row['delta']}")
        if not all_ok:
            sys.exit(1)


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="acf",
        description="Agent Cost Forecaster — Milestone 1: Observability",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("run", help="Run one prompt through Claude and log the trace")
    p.add_argument("prompt")
    p.add_argument("--config", default="config/agent_config.yaml")
    p.add_argument("--source", default="synthetic", choices=["synthetic", "production"])

    p = sub.add_parser("run-batch", help="Run tasks from a JSONL file")
    p.add_argument("--tasks", default="data/seed_tasks.jsonl")
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--config", default="config/agent_config.yaml")
    p.add_argument("--source", default="synthetic", choices=["synthetic", "production"])

    p = sub.add_parser("generate-tasks", help="Expand seed_templates.yaml into seed_tasks.jsonl")
    p.add_argument("--templates", default="data/seed_templates.yaml")
    p.add_argument("--output", default="data/seed_tasks.jsonl")
    p.add_argument("--n", type=int, default=3, help="Expansions per template (default 3)")

    p = sub.add_parser("trace", help="Show model call + tool call chain for a run")
    p.add_argument("run_id")

    p = sub.add_parser("sources", help="Show source URLs and domains for a run")
    p.add_argument("run_id")

    sub.add_parser("check", help="Verify log integrity")

    args = parser.parse_args()

    commands = {
        "run":             cmd_run,
        "run-batch":       cmd_run_batch,
        "generate-tasks":  cmd_generate_tasks,
        "trace":           cmd_trace,
        "sources":         cmd_sources,
        "check":           cmd_check,
    }

    if args.command not in commands:
        parser.print_help()
        sys.exit(0)

    commands[args.command](args)


if __name__ == "__main__":
    main()
