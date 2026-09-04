"""
WP4 - CLI interface (AROL's preferred option: "fast iteration").

Commands:
    arol-mas report kpi       --pool sample_pool
    arol-mas report anomalies --pool sample_pool
    arol-mas report drift     --pool sample_pool
    arol-mas ask "Which head shows the lowest success rate?" --pool sample_pool
    arol-mas list-pools
    arol-mas validate --pool sample_pool
"""
from __future__ import annotations

import logging
import os

import typer
from rich.console import Console
from rich.table import Table

from arol_mas.agent.orchestrator import ReportAgent
from arol_mas.agent.report_writer import save_report
from arol_mas.agent.tools import AgentContext
from arol_mas.config import load_config
from arol_mas.ingestion.loader import (
    list_pools,
    load_period_streaming,
    load_pool_streaming,
    validate_period_files,
    validate_pool_files,
)
from arol_mas.utils.logging_config import configure_logging

app = typer.Typer(help="AROL Telemetry Report Agent CLI")
console = Console()

_PRESET_QUERIES = {
    "kpi": "Generate a KPI report: overall success rate, per-head success rate, "
           "and torque statistics for successful closures.",
    "anomalies": "Generate an anomaly report: out-of-range torque readings, "
                 "statistical outliers, and which head contributes most to failures.",
    "drift": "Generate a drift report: has torque drifted from baseline for any head, "
              "and how has success rate evolved over time?",
}


def _build_context(
    pool: str, config: str | None, start_date: str | None = None, end_date: str | None = None, pools: str | None = None
) -> tuple[AgentContext, object, str]:
    settings = load_config(config)
    configure_logging(settings)

    if start_date or end_date:
        # Date-range mode spans across pool folders (e.g. "Feb 12 to
        # March 15" reaches into both the 2026-02 and 2026-03 pools) -
        # see loader.load_period_streaming / resolve_period_files.
        pool_list = [p.strip() for p in pools.split(",")] if pools else None
        events, idle_periods, meta = load_period_streaming(
            settings, pools=pool_list, start_date=start_date, end_date=end_date
        )
        label = f"{start_date or 'start'} to {end_date or 'end'}"
    else:
        # Streams the pool one file at a time (see loader.load_pool_streaming) -
        # this is what makes it safe to point a pool at a full month (or
        # several months) of daily telemetry files instead of just one.
        events, idle_periods, meta = load_pool_streaming(settings, pool_name=pool)
        label = pool or settings.data.default_pool

    ctx = AgentContext(
        events=events,
        settings=settings,
        idle_periods=idle_periods,
        data_quality_issues=meta["quality_issues"],
    )
    return ctx, settings, label


def _resolve_date_option(date: str | None, start_date: str | None, end_date: str | None) -> tuple[str | None, str | None]:
    """Lets --date 2026-03-04 stand in for --start-date 2026-03-04
    --end-date 2026-03-04 without making the user type the same date
    twice. Errors clearly rather than silently picking one if --date is
    combined with an explicit --start-date/--end-date, since it's not
    obvious which should win."""
    if date is None:
        return start_date, end_date
    if start_date is not None or end_date is not None:
        console.print("[red]Use either --date, or --start-date/--end-date, not both.[/red]")
        raise typer.Exit(code=1)
    return date, date


@app.command("list-pools")
def cmd_list_pools(config: str = typer.Option(None, help="Path to config.yaml")):
    """List available dataset pools."""
    settings = load_config(config)
    pools = list_pools(settings)
    if not pools:
        console.print(f"[yellow]No pools found in {settings.pools_dir}[/yellow]")
        raise typer.Exit(code=1)
    for p in pools:
        console.print(f"- {p}")


@app.command("validate")
def cmd_validate(
    pool: str = typer.Option(None, help="Dataset pool name (defaults to config default)"),
    date: str = typer.Option(None, help="Scope to a single day, e.g. 2026-03-04 (shorthand for --start-date/--end-date set to the same day)"),
    start_date: str = typer.Option(None, help="Scope to a date range instead of one pool, e.g. 2026-02-12"),
    end_date: str = typer.Option(None, help="End of the date range (inclusive), e.g. 2026-03-15"),
    pools: str = typer.Option(None, help="Comma-separated pool names to restrict the date-range search to (default: search all pools)"),
    config: str = typer.Option(None, help="Path to config.yaml"),
):
    """Run schema validation on a pool, a single day (--date), or a date
    range spanning multiple pools (--start-date/--end-date), without
    generating a report. Validates each file one at a time (see
    loader.validate_pool_files / validate_period_files) rather than
    loading everything into memory at once, so this is safe to run on a
    multi-month pool or period."""
    start_date, end_date = _resolve_date_option(date, start_date, end_date)
    settings = load_config(config)
    configure_logging(settings)
    if start_date or end_date:
        pool_list = [p.strip() for p in pools.split(",")] if pools else None
        problems = validate_period_files(settings, pools=pool_list, start_date=start_date, end_date=end_date)
    else:
        problems = validate_pool_files(settings, pool_name=pool)
    if not problems:
        console.print("[green]No schema issues found.[/green]")
    else:
        console.print(f"[red]{len(problems)} issue(s) found:[/red]")
        for p in problems:
            console.print(f"  - {p}")


@app.command("report")
def cmd_report(
    kind: str = typer.Argument(..., help="One of: kpi, anomalies, drift"),
    pool: str = typer.Option(None, help="Dataset pool name (defaults to config default)"),
    date: str = typer.Option(None, help="Scope to a single day, e.g. 2026-03-04 (shorthand for --start-date/--end-date set to the same day)"),
    start_date: str = typer.Option(None, help="Scope to a date range instead of one pool, e.g. 2026-02-12"),
    end_date: str = typer.Option(None, help="End of the date range (inclusive), e.g. 2026-03-15"),
    pools: str = typer.Option(None, help="Comma-separated pool names to restrict the date-range search to (default: search all pools)"),
    config: str = typer.Option(None, help="Path to config.yaml"),
):
    """Generate a preset report type via the agent."""
    if kind not in _PRESET_QUERIES:
        console.print(f"[red]Unknown report kind '{kind}'. Choose from: {list(_PRESET_QUERIES)}[/red]")
        raise typer.Exit(code=1)
    start_date, end_date = _resolve_date_option(date, start_date, end_date)
    _run_agent_and_save(_PRESET_QUERIES[kind], pool, config, start_date, end_date, pools)


@app.command("ask")
def cmd_ask(
    query: str = typer.Argument(..., help="Free-text question about the dataset"),
    pool: str = typer.Option(None, help="Dataset pool name (defaults to config default)"),
    date: str = typer.Option(None, help="Scope to a single day, e.g. 2026-03-04 (shorthand for --start-date/--end-date set to the same day)"),
    start_date: str = typer.Option(None, help="Scope to a date range instead of one pool, e.g. 2026-02-12"),
    end_date: str = typer.Option(None, help="End of the date range (inclusive), e.g. 2026-03-15"),
    pools: str = typer.Option(None, help="Comma-separated pool names to restrict the date-range search to (default: search all pools)"),
    config: str = typer.Option(None, help="Path to config.yaml"),
):
    """Ask a free-text question; the agent decides which tools to run.

    Use --pool for a single dataset pool (the usual case), --date for a
    single specific day (e.g. --date 2026-03-04), or
    --start-date/--end-date for a request scoped by date range instead -
    this can span multiple pool folders, e.g.
    --start-date 2026-02-12 --end-date 2026-03-15 reaches into both the
    2026-02 and 2026-03 pools automatically."""
    start_date, end_date = _resolve_date_option(date, start_date, end_date)
    _run_agent_and_save(query, pool, config, start_date, end_date, pools)


def _run_agent_and_save(
    query: str,
    pool: str | None,
    config: str | None,
    start_date: str | None = None,
    end_date: str | None = None,
    pools: str | None = None,
) -> None:
    logger = logging.getLogger(__name__)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        console.print(
            "[red]ANTHROPIC_API_KEY is not set.[/red] "
            "Export it before running agent-driven reports:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...\n\n"
            "(Deterministic analytics can still be inspected directly via "
            "arol_mas.analytics without the agent - see tests/ for examples.)"
        )
        raise typer.Exit(code=1)

    try:
        ctx, settings, dataset_label = _build_context(pool or "", config, start_date, end_date, pools)
    except Exception as exc:
        console.print(f"[red]Failed to load dataset: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[cyan]Running agent on '{dataset_label}' for:[/cyan] {query}")

    agent = ReportAgent(ctx)
    try:
        result = agent.run(query, dataset_label=dataset_label)
    except Exception as exc:
        logger.exception("Agent run failed")
        console.print(f"[red]Agent run failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    out_path = save_report(result, settings, dataset_label)

    console.rule("Report")
    console.print(result.report_text)
    console.rule()
    console.print(f"[green]Saved to {out_path}[/green]")

    if result.tool_calls:
        table = Table(title="Tool calls made by the agent")
        table.add_column("#")
        table.add_column("Tool")
        table.add_column("Input")
        for i, call in enumerate(result.tool_calls, 1):
            table.add_row(str(i), call["tool"], str(call["input"]))
        console.print(table)


def main():
    app()


if __name__ == "__main__":
    main()