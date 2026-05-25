"""acf CLI — Agent Cost Forecaster command-line interface.

Commands:
  acf run "prompt"                    Run a single prompt and log the trace
  acf run-batch [--tasks file]        Run tasks from a JSONL file
  acf generate-tasks [--n N]          Expand seed_templates.yaml → seed_tasks.jsonl
  acf trace <run-id>                  Show model call + tool call chain for a run
  acf sources <run-id>                Show source URLs and domains for a run
  acf check                           Verify log integrity (token sum check)
"""

import argparse
import json
import os
import sys
from pathlib import Path

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
    count_schema_tokens,
    get_enabled_tools,
    get_tool_schemas,
    load_config,
)


# ── Shared setup ─────────────────────────────────────────────────────────────

def _setup(config: dict) -> str:
    """Init DB, seed pricing, return agent_config_id."""
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


# ── acf run ──────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    agent_config_id = _setup(config)

    _print(f"Model : {config['agent']['model']}", "dim")
    _print(f"Prompt: {args.prompt[:120]}{'...' if len(args.prompt) > 120 else ''}", "dim")

    result = run_agent(args.prompt, config, agent_config_id, source=args.source)

    if _RICH:
        t = Table(title="Run Result", show_lines=True)
        t.add_column("Field", style="cyan", no_wrap=True)
        t.add_column("Value")
        t.add_row("Run ID", result["run_id"])
        t.add_row("Trace ID", result["trace_id"])
        t.add_row("Model calls", str(result["model_calls"]))
        t.add_row("Tool calls", str(result["tool_calls"]))
        t.add_row("Tools used", ", ".join(result["tools_called"]) or "none")
        t.add_row("Input tokens", str(result["total_input_tokens"]))
        t.add_row("Output tokens", str(result["total_output_tokens"]))
        t.add_row("Total cost", f"${result['total_cost_usd']:.6f}")
        t.add_row("Success", "[green]✓[/green]" if result["success"] else "[red]✗[/red]")
        console.print(t)
        if result.get("final_answer"):
            console.print(f"\n[bold]Answer:[/bold] {result['final_answer'][:400]}")
    else:
        print(f"\nRun ID:        {result['run_id']}")
        print(f"Trace ID:      {result['trace_id']}")
        print(f"Tools used:    {', '.join(result['tools_called']) or 'none'}")
        print(f"Input tokens:  {result['total_input_tokens']}")
        print(f"Output tokens: {result['total_output_tokens']}")
        print(f"Total cost:    ${result['total_cost_usd']:.6f}")
        print(f"Success:       {'yes' if result['success'] else 'no'}")
        if result.get("final_answer"):
            print(f"\nAnswer: {result['final_answer'][:400]}")

    db_path = os.environ.get("ACF_DB_PATH", "data/acf.db")
    _print(f"\nLogged to {db_path}", "dim")


# ── acf run-batch ─────────────────────────────────────────────────────────────

def cmd_run_batch(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    agent_config_id = _setup(config)

    tasks_path = Path(args.tasks)
    if not tasks_path.exists():
        print(f"Tasks file not found: {args.tasks}", file=sys.stderr)
        sys.exit(1)

    tasks = [json.loads(line) for line in tasks_path.read_text().splitlines() if line.strip()]
    if args.limit:
        tasks = tasks[: args.limit]

    total = len(tasks)
    succeeded = failed = 0
    total_cost = 0.0

    _print(f"Running {total} tasks (model: {config['agent']['model']})...\n")

    for i, task in enumerate(tasks, 1):
        prompt = task.get("prompt", "")
        category = task.get("category", "unknown")
        source = args.source

        try:
            result = run_agent(prompt, config, agent_config_id, source=source)
            succeeded += 1
            total_cost += result["total_cost_usd"]
            tools_str = ",".join(result["tools_called"]) or "none"
            if _RICH:
                console.print(
                    f"  [{i:>3}/{total}] [green]✓[/green] [{category}] "
                    f"{prompt[:70]}{'…' if len(prompt) > 70 else ''}"
                    f" → tools={tools_str}  ${result['total_cost_usd']:.6f}"
                )
            else:
                print(f"  [{i}/{total}] OK [{category}] ${result['total_cost_usd']:.6f}")
        except Exception as exc:
            failed += 1
            if _RICH:
                console.print(f"  [{i:>3}/{total}] [red]✗[/red] [{category}] {prompt[:60]} → {exc}")
            else:
                print(f"  [{i}/{total}] FAIL [{category}]: {exc}")

    print()
    _print(f"Batch complete: {succeeded}/{total} succeeded, {failed} failed")
    _print(f"Total cost:     ${total_cost:.6f}")
    _print(f"Logged to:      {os.environ.get('ACF_DB_PATH', 'data/acf.db')}")


# ── acf generate-tasks ────────────────────────────────────────────────────────

def cmd_generate_tasks(args: argparse.Namespace) -> None:
    import random
    import yaml

    templates_path = Path(args.templates)
    if not templates_path.exists():
        print(f"Templates file not found: {args.templates}", file=sys.stderr)
        sys.exit(1)

    with open(templates_path) as f:
        data = yaml.safe_load(f)

    variables: dict = data.get("variables", {})
    tasks: list[dict] = []

    for category_name, category_data in data.items():
        if category_name == "variables" or not isinstance(category_data, dict):
            continue
        target_tools: list = category_data.get("target_tools", [])
        templates: list = category_data.get("templates", [])

        for template in templates:
            for _ in range(args.n):
                prompt = template
                for var_name, values in variables.items():
                    placeholder = f"{{{var_name}}}"
                    if placeholder in prompt:
                        prompt = prompt.replace(placeholder, str(random.choice(values)))
                tasks.append({
                    "prompt": prompt,
                    "category": category_name,
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

    category_counts: dict[str, int] = {}
    for t in tasks:
        category_counts[t["category"]] = category_counts.get(t["category"], 0) + 1
    for cat, count in sorted(category_counts.items()):
        _print(f"  {cat}: {count}", "dim")


# ── acf trace ────────────────────────────────────────────────────────────────

def cmd_trace(args: argparse.Namespace) -> None:
    conn = get_connection()
    run = conn.execute("SELECT * FROM agent_runs WHERE run_id = ?", (args.run_id,)).fetchone()
    if not run:
        print(f"Run not found: {args.run_id}", file=sys.stderr)
        conn.close()
        sys.exit(1)

    model_calls = conn.execute(
        "SELECT * FROM model_calls WHERE run_id = ? ORDER BY call_index", (args.run_id,)
    ).fetchall()
    tool_calls = conn.execute(
        "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY call_index", (args.run_id,)
    ).fetchall()
    conn.close()

    if _RICH:
        console.print(f"\n[bold]Run[/bold]  {run['run_id']}")
        console.print(f"Trace  {run['trace_id']}")
        console.print(f"Source {run['source']}   Quality {run['sample_quality_score']} ({run['sample_quality_reason']})")
        console.print(f"Cost   ${run['actual_total_cost_usd']:.6f}   "
                      f"In={run['actual_input_tokens']} Out={run['actual_output_tokens']}")
        console.print(f"Tools called  {run['actual_tools_called']}")
        console.print()

        mc_table = Table(title=f"Model Calls ({len(model_calls)})", show_lines=True)
        mc_table.add_column("idx", style="dim")
        mc_table.add_column("input", justify="right")
        mc_table.add_column("output", justify="right")
        mc_table.add_column("cached", justify="right")
        mc_table.add_column("schema_tok", justify="right")
        mc_table.add_column("tool_result_tok", justify="right")
        mc_table.add_column("finish")
        mc_table.add_column("cost", justify="right", style="green")
        for mc in model_calls:
            mc_table.add_row(
                str(mc["call_index"]),
                str(mc["input_tokens"]),
                str(mc["output_tokens"]),
                str(mc["cached_input_tokens"] or 0),
                str(mc["tool_schema_tokens"]),
                str(mc["tool_result_tokens_inserted"] or 0),
                mc["finish_reason"] or "",
                f"${mc['cost_usd']:.6f}",
            )
        console.print(mc_table)

        if tool_calls:
            tc_table = Table(title=f"Tool Calls ({len(tool_calls)})", show_lines=True)
            tc_table.add_column("idx", style="dim")
            tc_table.add_column("tool")
            tc_table.add_column("raw_tok", justify="right")
            tc_table.add_column("ins_tok", justify="right")
            tc_table.add_column("trunc")
            tc_table.add_column("traceability")
            tc_table.add_column("latency_ms", justify="right")
            tc_table.add_column("ok")
            for tc in tool_calls:
                tc_table.add_row(
                    str(tc["call_index"]),
                    tc["tool_name"],
                    str(tc["result_tokens_raw"] or "–"),
                    str(tc["result_tokens_inserted"] or "–"),
                    "yes" if tc["was_result_truncated"] else "no",
                    tc["source_traceability_status"] or "–",
                    str(tc["latency_ms"] or "–"),
                    "[green]✓[/green]" if tc["success"] else "[red]✗[/red]",
                )
            console.print(tc_table)
    else:
        print(f"\nRun   {run['run_id']}")
        print(f"Cost  ${run['actual_total_cost_usd']:.6f}  in={run['actual_input_tokens']} out={run['actual_output_tokens']}")
        for mc in model_calls:
            print(f"  model[{mc['call_index']}] in={mc['input_tokens']} out={mc['output_tokens']} finish={mc['finish_reason']}")
        for tc in tool_calls:
            ok = "ok" if tc["success"] else "fail"
            print(f"  tool[{tc['call_index']}] {tc['tool_name']} raw={tc['result_tokens_raw']} ins={tc['result_tokens_inserted']} {ok}")


# ── acf sources ───────────────────────────────────────────────────────────────

def cmd_sources(args: argparse.Namespace) -> None:
    conn = get_connection()
    tool_calls = conn.execute(
        "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY call_index", (args.run_id,)
    ).fetchall()
    conn.close()

    if not tool_calls:
        print(f"No tool calls found for run: {args.run_id}")
        return

    for tc in tool_calls:
        domains = json.loads(tc["source_domains"] or "[]")
        urls_returned = json.loads(tc["source_urls_returned"] or "[]")
        status = tc["source_traceability_status"] or "unknown"
        ok = "✓" if tc["success"] else "✗"

        if _RICH:
            colour = "green" if status == "full" else ("yellow" if status == "partial" else "red")
            console.print(f"\n[bold]{ok} {tc['tool_name']}[/bold] (call {tc['call_index']}) "
                          f"traceability=[{colour}]{status}[/{colour}]")
            if domains:
                console.print(f"  Domains: {', '.join(domains)}")
            for url in urls_returned[:8]:
                console.print(f"    • {url}", style="dim")
            if len(urls_returned) > 8:
                console.print(f"    … and {len(urls_returned) - 8} more", style="dim")
            if tc["result_tokens_inserted"] is not None:
                console.print(f"  Tokens inserted: {tc['result_tokens_inserted']} "
                               f"(raw: {tc['result_tokens_raw']})")
        else:
            print(f"\n{ok} {tc['tool_name']} (call {tc['call_index']}) [{status}]")
            if domains:
                print(f"  Domains: {', '.join(domains)}")
            for url in urls_returned[:5]:
                print(f"    {url}")


# ── acf check ────────────────────────────────────────────────────────────────

def cmd_check(args: argparse.Namespace) -> None:
    """Verify log integrity: Σ model_calls.input_tokens == agent_runs.actual_input_tokens."""
    conn = get_connection()

    total_runs = conn.execute("SELECT COUNT(*) FROM agent_runs WHERE success = 1").fetchone()[0]
    total_tool_calls = conn.execute("SELECT COUNT(*) FROM tool_calls").fetchone()[0]

    discrepancies = conn.execute("""
        SELECT
            r.run_id,
            r.actual_input_tokens                AS run_total,
            SUM(m.input_tokens)                  AS mc_total,
            r.actual_input_tokens - SUM(m.input_tokens) AS delta
        FROM agent_runs r
        JOIN model_calls m ON r.run_id = m.run_id
        WHERE r.success = 1
        GROUP BY r.run_id
        HAVING delta != 0
    """).fetchall()

    missing_result_tokens = conn.execute("""
        SELECT COUNT(*) FROM tool_calls
        WHERE success = 1 AND result_tokens_inserted IS NULL
    """).fetchone()[0]

    missing_source_status = conn.execute("""
        SELECT COUNT(*) FROM tool_calls
        WHERE success = 1 AND source_traceability_status IS NULL
    """).fetchone()[0]

    web_search_no_domains = conn.execute("""
        SELECT COUNT(*) FROM tool_calls
        WHERE success = 1
          AND tool_name = 'web_search'
          AND (source_domains = '[]' OR source_domains IS NULL)
    """).fetchone()[0]

    conn.close()

    all_ok = not discrepancies and missing_result_tokens == 0 and web_search_no_domains == 0

    if _RICH:
        t = Table(title="Log Integrity Check", show_lines=True)
        t.add_column("Check", style="cyan")
        t.add_column("Result")

        def _row(label: str, value, ok: bool) -> None:
            colour = "green" if ok else "red"
            t.add_row(label, f"[{colour}]{value}[/{colour}]")

        _row("Successful runs logged", total_runs, total_runs > 0)
        _row("Tool calls logged", total_tool_calls, True)
        _row("Token sum mismatches (must be 0)", len(discrepancies), len(discrepancies) == 0)
        _row("Tool calls missing result_tokens_inserted", missing_result_tokens, missing_result_tokens == 0)
        _row("Tool calls missing traceability_status", missing_source_status, missing_source_status == 0)
        _row("web_search calls with no source domains", web_search_no_domains, web_search_no_domains == 0)
        console.print(t)

        if discrepancies:
            console.print("\n[bold red]Token sum discrepancies:[/bold red]")
            for row in discrepancies:
                console.print(f"  run_id={row['run_id']}  run_total={row['run_total']}  "
                               f"mc_total={row['mc_total']}  delta={row['delta']}")

        if all_ok:
            console.print("\n[bold green]All checks passed — logs look complete.[/bold green]")
        else:
            console.print("\n[bold red]Some checks failed — review the issues above.[/bold red]")
            sys.exit(1)
    else:
        print(f"Successful runs:          {total_runs}")
        print(f"Tool calls logged:        {total_tool_calls}")
        print(f"Token sum mismatches:     {len(discrepancies)}")
        print(f"Missing result tokens:    {missing_result_tokens}")
        print(f"Missing traceability:     {missing_source_status}")
        print(f"web_search no domains:    {web_search_no_domains}")

        if discrepancies:
            print("\nToken sum discrepancies:")
            for row in discrepancies:
                print(f"  {row['run_id']}  delta={row['delta']}")

        if all_ok:
            print("\nAll checks passed.")
        else:
            print("\nSome checks failed.")
            sys.exit(1)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="acf",
        description="Agent Cost Forecaster — Milestone 1: Logging and Observability",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # acf run
    p_run = sub.add_parser("run", help="Run a single prompt and log the trace")
    p_run.add_argument("prompt", help="The user prompt")
    p_run.add_argument("--config", default="config/agent_config.yaml", metavar="PATH")
    p_run.add_argument("--source", default="synthetic", choices=["synthetic", "production"])

    # acf run-batch
    p_batch = sub.add_parser("run-batch", help="Run tasks from a JSONL file")
    p_batch.add_argument("--tasks", default="data/seed_tasks.jsonl", metavar="PATH")
    p_batch.add_argument("--limit", type=int, default=None, metavar="N")
    p_batch.add_argument("--config", default="config/agent_config.yaml", metavar="PATH")
    p_batch.add_argument("--source", default="synthetic", choices=["synthetic", "production"])

    # acf generate-tasks
    p_gen = sub.add_parser("generate-tasks", help="Expand seed_templates.yaml into seed_tasks.jsonl")
    p_gen.add_argument("--templates", default="data/seed_templates.yaml", metavar="PATH")
    p_gen.add_argument("--output", default="data/seed_tasks.jsonl", metavar="PATH")
    p_gen.add_argument("--n", type=int, default=3, help="Expansions per template (default 3)")

    # acf trace
    p_trace = sub.add_parser("trace", help="Show model call + tool call chain for a run")
    p_trace.add_argument("run_id", help="Run ID to inspect")

    # acf sources
    p_src = sub.add_parser("sources", help="Show source URLs and domains for a run")
    p_src.add_argument("run_id", help="Run ID to inspect")

    # acf check
    sub.add_parser("check", help="Verify log integrity (token sum check + completeness)")

    args = parser.parse_args()

    dispatch = {
        "run": cmd_run,
        "run-batch": cmd_run_batch,
        "generate-tasks": cmd_generate_tasks,
        "trace": cmd_trace,
        "sources": cmd_sources,
        "check": cmd_check,
    }

    if args.command not in dispatch:
        parser.print_help()
        sys.exit(0)

    dispatch[args.command](args)


if __name__ == "__main__":
    main()
