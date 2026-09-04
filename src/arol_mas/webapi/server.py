"""
WP4 (web variant) - FastAPI backend for the React frontend.

This does not replace the CLI (arol_mas.cli.main) - it's an additional
transport that reuses the exact same ingestion / analytics / agent code
(WP1-WP3). Nothing analytical lives here; this module is only:
  request in -> load pool -> ReportAgent.run() -> JSON out.

Run with:
    uvicorn arol_mas.webapi.server:app --reload --port 8000
(from the project root, with ANTHROPIC_API_KEY exported and
AROL_CONFIG / config/config.yaml resolvable as usual.)
"""
from __future__ import annotations

import base64
import io
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, HTMLResponse
from pydantic import BaseModel

from arol_mas.agent.orchestrator import ReportAgent, ReportResult
from arol_mas.agent.report_writer import save_report
from arol_mas.agent.tools import TOOL_SPECS, AgentContext
from arol_mas.config import load_config
from arol_mas.ingestion.loader import (
    list_pools,
    load_period_streaming,
    load_pool_streaming,
    validate_period_files,
    validate_pool_files,
)
from arol_mas.utils.logging_config import configure_logging

logger = logging.getLogger(__name__)

app = FastAPI(title="AROL Telemetry Report Agent API")

# Vite dev server default; adjust/extend via ALLOWED_ORIGINS env var
# (comma-separated) for a production deployment.
_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

_PRESET_QUERIES = {
    "kpi": "Generate a KPI report: overall success rate, per-head success rate, "
           "and torque statistics for successful closures.",
    "anomalies": "Generate an anomaly report: out-of-range torque readings, "
                 "statistical outliers, and which head contributes most to failures.",
    "drift": "Generate a drift report: has torque drifted from baseline for any head, "
              "and how has success rate evolved over time?",
}

# In-memory registry of generated reports for this process, so the
# frontend can fetch md/html/pdf renderings by id after the fact.
# (Simple by design - a single-process demo server, not a persistence layer.
# Restarting the server clears it; nothing here is a dataset of record.)
_REPORTS: Dict[str, Dict[str, Any]] = {}


class AskRequest(BaseModel):
    query: str
    pool: Optional[str] = None
    config: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    pools: Optional[List[str]] = None


class ReportRequest(BaseModel):
    kind: str
    pool: Optional[str] = None
    config: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    pools: Optional[List[str]] = None


def _build_context(
    pool: Optional[str],
    config: Optional[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    pools: Optional[List[str]] = None,
):
    """
    Mirrors cli.main._build_context: same streaming loaders, same
    AgentContext shape (events/idle_periods/data_quality_issues, no raw
    DataFrame - see agent.tools.AgentContext's docstring for why). If
    start_date/end_date are given, this can span multiple pool folders
    (via load_period_streaming) instead of a single --pool.
    """
    settings = load_config(config)
    configure_logging(settings)

    if start_date or end_date:
        events, idle_periods, meta = load_period_streaming(
            settings, pools=pools, start_date=start_date, end_date=end_date
        )
        label = f"{start_date or 'start'} to {end_date or 'end'}"
    else:
        events, idle_periods, meta = load_pool_streaming(settings, pool_name=pool)
        label = pool or settings.data.default_pool

    ctx = AgentContext(
        events=events,
        settings=settings,
        idle_periods=idle_periods,
        data_quality_issues=meta["quality_issues"],
    )
    return ctx, settings, label


def _fig_to_data_uri() -> str:
    buf = io.BytesIO()
    plt.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    plt.close()
    buf.seek(0)
    return "data:image/png;base64," + base64.b64encode(buf.read()).decode("ascii")


def _charts_for_tool_calls(tool_calls: List[Dict[str, Any]], ctx: AgentContext) -> List[Dict[str, str]]:
    """
    Best-effort visualization: re-run a couple of the analytics tools that
    were actually called during this agent run, if they produce data that
    plots meaningfully. This keeps the chart set tied to what the agent
    decided was relevant, rather than always drawing the same fixed panel.
    """
    from arol_mas.agent.tools import run_tool

    charts: List[Dict[str, str]] = []
    plottable = {"success_rate_per_head", "torque_statistics_per_head", "success_rate_over_time"}
    seen = set()
    for call in tool_calls:
        name = call["tool"]
        if name not in plottable or name in seen:
            continue
        seen.add(name)
        try:
            result = run_tool(name, call["input"], ctx)
        except Exception:
            continue

        rows = result.get("rows", result) if isinstance(result, dict) else result
        if not isinstance(rows, list) or not rows:
            continue

        try:
            if name == "success_rate_per_head":
                heads = [r.get("head_id", "?") for r in rows]
                rates = [r.get("success_rate_pct", r.get("success_rate", 0)) for r in rows]
                plt.figure(figsize=(6, 3.2))
                plt.bar(heads, rates, color="#2563eb")
                plt.ylabel("Success rate (%)")
                plt.title("Success rate per head")
                plt.xticks(rotation=90, fontsize=7)
                charts.append({"tool": name, "image": _fig_to_data_uri()})

            elif name == "torque_statistics_per_head":
                heads = [r.get("head_id", "?") for r in rows]
                means = [r.get("mean", 0) for r in rows]
                plt.figure(figsize=(6, 3.2))
                plt.bar(heads, means, color="#059669")
                plt.ylabel("Mean torque (Nm)")
                plt.title("Torque per head")
                plt.xticks(rotation=90, fontsize=7)
                charts.append({"tool": name, "image": _fig_to_data_uri()})

            elif name == "success_rate_over_time":
                xs = [str(r.get("period", i)) for i, r in enumerate(rows)]
                ys = [r.get("success_rate_pct", r.get("success_rate", 0)) for r in rows]
                plt.figure(figsize=(6, 3.2))
                plt.plot(xs, ys, marker="o", color="#7c3aed")
                plt.ylabel("Success rate (%)")
                plt.title("Success rate over time")
                plt.xticks(rotation=45, ha="right", fontsize=7)
                charts.append({"tool": name, "image": _fig_to_data_uri()})
        except Exception:
            logger.exception("Chart generation failed for tool '%s'", name)
            plt.close("all")

    return charts


def _register_report(result: ReportResult, settings, dataset_label: str, charts: List[Dict[str, str]]) -> Dict[str, Any]:
    md_path = save_report(result, settings, dataset_label)
    report_id = uuid.uuid4().hex[:12]
    _REPORTS[report_id] = {
        "report_id": report_id,
        "query": result.query,
        "dataset_label": dataset_label,
        "report_text": result.report_text,
        "tool_calls": result.tool_calls,
        "charts": charts,
        "md_path": str(md_path),
    }
    return _REPORTS[report_id]


def _run_agent(
    query: str,
    pool: Optional[str],
    config: Optional[str],
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    pools: Optional[List[str]] = None,
) -> Dict[str, Any]:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY is not set on the server. Export it before "
                   "starting uvicorn - see README section 2.",
        )
    try:
        ctx, settings, dataset_label = _build_context(pool, config, start_date, end_date, pools)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load dataset: {exc}")

    agent = ReportAgent(ctx)
    try:
        result = agent.run(query, dataset_label=dataset_label)
    except Exception as exc:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}")

    charts = _charts_for_tool_calls(result.tool_calls, ctx)
    return _register_report(result, settings, dataset_label, charts)


@app.get("/api/pools")
def get_pools(config: Optional[str] = None):
    settings = load_config(config)
    return {"pools": list_pools(settings), "default": settings.data.default_pool}


@app.get("/api/presets")
def get_presets():
    return {"presets": [{"kind": k, "prompt": v} for k, v in _PRESET_QUERIES.items()]}


@app.get("/api/tools")
def get_tools():
    return {"tools": [{"name": t["name"], "description": t["description"]} for t in TOOL_SPECS]}


@app.get("/api/validate")
def validate(pool: Optional[str] = None, config: Optional[str] = None):
    settings = load_config(config)
    raw_df = load_pool(settings, pool_name=pool, strict=False)
    problems = validate_schema(raw_df, settings)
    return {"pool": pool or settings.data.default_pool, "issues": problems}


@app.post("/api/report")
def post_report(req: ReportRequest):
    if req.kind not in _PRESET_QUERIES:
        raise HTTPException(status_code=400, detail=f"Unknown report kind '{req.kind}'. Choose from: {list(_PRESET_QUERIES)}")
    return _run_agent(_PRESET_QUERIES[req.kind], req.pool, req.config, req.start_date, req.end_date, req.pools)


@app.post("/api/ask")
def post_ask(req: AskRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query must not be empty")
    return _run_agent(req.query, req.pool, req.config, req.start_date, req.end_date, req.pools)


@app.get("/api/reports/{report_id}/md", response_class=PlainTextResponse)
def get_report_md(report_id: str):
    r = _REPORTS.get(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown report id")
    return r["report_text"]


@app.get("/api/reports/{report_id}/html", response_class=HTMLResponse)
def get_report_html(report_id: str):
    r = _REPORTS.get(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown report id")
    import markdown as md_lib
    body = md_lib.markdown(r["report_text"])
    charts_html = "".join(
        f'<figure><img src="{c["image"]}" style="max-width:600px"><figcaption>{c["tool"]}</figcaption></figure>'
        for c in r["charts"]
    )
    return (
        f"<html><head><meta charset='utf-8'><title>{r['query']}</title></head>"
        f"<body style='font-family:sans-serif;max-width:800px;margin:2rem auto'>"
        f"<h1>AROL Telemetry Report</h1><p><em>{r['query']}</em></p>{body}{charts_html}"
        f"</body></html>"
    )


@app.get("/api/reports/{report_id}/pdf")
def get_report_pdf(report_id: str):
    from fastapi.responses import Response
    from fpdf import FPDF

    r = _REPORTS.get(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown report id")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(0, 6, f"AROL Telemetry Report\n\nQuery: {r['query']}\n\n{r['report_text']}")
    out = bytes(pdf.output(dest="S"))
    return Response(content=out, media_type="application/pdf")
