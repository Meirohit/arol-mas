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
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from arol_mas.agent.orchestrator import ReportAgent, ReportResult
from arol_mas.agent.report_writer import save_report
from arol_mas.agent.tools import TOOL_SPECS, AgentContext
from arol_mas.config import load_config
from arol_mas.ingestion.loader import (
    list_pools,
    load_period_streaming,
    load_pool,
    load_pool_streaming,
)
from arol_mas.ingestion.schema import validate_schema
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

# Serve the reports/ directory (which contains reports/plots/*.png) over
# HTTP so relative image links embedded in report Markdown (e.g.
# "plots/xxx.png" - see analytics/plotting.py::_save()) resolve for a
# browser, not just for a local file-system Markdown viewer. Mounted with
# the default config's reports_dir; a request using a non-default
# --config would need its own reports_dir mounted too, but this server is
# explicitly a single-process demo server (see _REPORTS docstring below),
# not a multi-tenant deployment.
try:
    _default_settings = load_config(None)
    _default_settings.reports_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/report-files", StaticFiles(directory=str(_default_settings.reports_dir)), name="report-files")
except Exception:
    logger.exception("Could not mount /report-files static directory - report images may not render over HTTP")

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


def _png_path_to_data_uri(settings, plot_path: str) -> Optional[str]:
    """Read a PNG saved by analytics/plotting.py (path relative to
    settings.reports_dir - see plotting.py::_save()) and base64-encode it
    for inline embedding in the web UI, which has no filesystem access."""
    try:
        full_path = settings.reports_dir / plot_path
        with open(full_path, "rb") as f:
            data = f.read()
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    except Exception:
        logger.exception("Could not read plot file '%s' for data-URI embedding", plot_path)
        return None


def _charts_for_tool_calls(tool_calls: List[Dict[str, Any]], ctx: AgentContext) -> List[Dict[str, str]]:
    """
    Re-runs any of the four `plot_*` analytics tools (analytics/plotting.py)
    the agent actually called during this run, and returns their PNGs as
    base64 data URIs for inline display in the web UI.

    This reuses the exact same plotting functions the CLI uses (via
    agent.tools.run_tool - the same dispatcher the orchestrator calls) -
    single source of truth for chart rendering, rather than a second,
    separately-maintained matplotlib implementation that only covered 3 of
    the 4 plotting tools and could silently drift out of sync with them.
    """
    from arol_mas.agent.tools import run_tool

    charts: List[Dict[str, str]] = []
    plottable = {
        "plot_torque_over_time",
        "plot_torque_histogram",
        "plot_success_rate_per_head",
        "plot_failed_closures_over_time",
    }
    seen = set()
    for call in tool_calls:
        name = call["tool"]
        if name not in plottable or name in seen:
            continue
        seen.add(name)
        try:
            result = run_tool(name, call["input"], ctx)
        except Exception:
            logger.exception("Chart tool '%s' failed", name)
            continue

        plot_path = result.get("plot_path") if isinstance(result, dict) else None
        if not plot_path:
            continue
        image = _png_path_to_data_uri(ctx.settings, plot_path)
        if image:
            charts.append({"tool": name, "image": image})

    return charts


def _render_report_html_fragment(report_text: str) -> str:
    """
    Renders report_text (Markdown, written by the LLM) to an HTML fragment
    using the same `markdown` library as get_report_html, so headings/bold/
    tables/lists actually render instead of showing their raw "## " / "**"
    syntax. The frontend embeds this directly (see App.jsx's Entry
    component) instead of dumping report_text into a <pre> block, which is
    what previously made reports look inconsistently formatted - literal
    Markdown punctuation sitting inline with rendered prose, in a
    monospace font that wasn't distinguishing headings from body text.
    """
    import markdown as md_lib
    html = md_lib.markdown(report_text, extensions=["tables"])
    return html.replace('src="plots/', 'src="/report-files/plots/')


def _register_report(result: ReportResult, settings, dataset_label: str, charts: List[Dict[str, str]]) -> Dict[str, Any]:
    md_path = save_report(result, settings, dataset_label)
    report_id = uuid.uuid4().hex[:12]
    _REPORTS[report_id] = {
        "report_id": report_id,
        "query": result.query,
        "dataset_label": dataset_label,
        "report_text": result.report_text,
        "report_html": _render_report_html_fragment(result.report_text),
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
        raise HTTPException(status_code=400, detail=f"Failed to load dataset: {exc}") from exc

    agent = ReportAgent(ctx)
    try:
        result = agent.run(query, dataset_label=dataset_label)
    except Exception as exc:
        logger.exception("Agent run failed")
        raise HTTPException(status_code=502, detail=f"Agent run failed: {exc}") from exc

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
    body = r.get("report_html") or _render_report_html_fragment(r["report_text"])
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


def _dejavu_font_path() -> Optional[str]:
    """
    Locate the DejaVu Sans TTF bundled with matplotlib (a hard dependency
    of this project already - see requirements.txt), so the PDF export can
    use a real Unicode font instead of FPDF's built-in core fonts.

    This matters because report_text is written by the LLM in normal
    prose, which routinely contains characters outside FPDF's core-font
    Latin-1 range: em/en dashes (-), arrows (->), smart quotes, "x" for
    multiplication, degree signs, etc. FPDF's core "Helvetica" font raises
    FPDFUnicodeEncodingException on the first such character, which is why
    the PDF export previously failed on essentially every real report.
    """
    try:
        import matplotlib
        candidate = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans.ttf")
        candidate_bold = os.path.join(matplotlib.get_data_path(), "fonts", "ttf", "DejaVuSans-Bold.ttf")
        if os.path.isfile(candidate) and os.path.isfile(candidate_bold):
            return candidate, candidate_bold
    except Exception:
        pass
    return None, None


def _markdown_to_pdf_lines(text: str) -> List[tuple]:
    """
    Very small Markdown -> (text, style) line converter for the PDF export.
    Not a full renderer - just enough to stop "## Heading" / "**bold**"
    syntax from showing up literally in the PDF (which looked broken even
    on the rare occasion the old core-font PDF didn't crash outright).
    Returns a list of (line_text, style) where style is "h1"/"h2"/"body".
    """
    import re
    lines = []
    for raw in text.split("\n"):
        line = raw.rstrip()
        if line.startswith("## "):
            lines.append((line[3:].strip(), "h2"))
        elif line.startswith("# "):
            lines.append((line[2:].strip(), "h1"))
        else:
            # strip bold/italic markers - kept as plain text since FPDF's
            # multi_cell doesn't support inline mixed styling without a
            # lot more machinery than this export needs.
            clean = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
            clean = re.sub(r"\*(.*?)\*", r"\1", clean)
            lines.append((clean, "body"))
    return lines


def _embed_charts_in_pdf(pdf, charts: List[Dict[str, str]]) -> None:
    """
    Decodes each chart's base64 data URI (produced by
    _png_path_to_data_uri/_charts_for_tool_calls) and embeds it as an
    image in the PDF via fpdf2's Image support. Previously the PDF export
    only converted report_text to styled lines and silently dropped every
    "![...](plots/...)" reference - charts never appeared in the PDF at
    all, even though the same charts already render fine in the web UI
    and the HTML export.
    """
    import base64
    from io import BytesIO

    for chart in charts:
        image = chart.get("image")
        if not image or "," not in image:
            continue
        try:
            _, b64_data = image.split(",", 1)
            img_bytes = base64.b64decode(b64_data)
            pdf.ln(3)
            pdf.image(BytesIO(img_bytes), w=170)
            pdf.ln(2)
        except Exception:
            logger.exception("Could not embed chart '%s' in PDF export", chart.get("tool"))


@app.get("/api/reports/{report_id}/pdf")
def get_report_pdf(report_id: str):
    from fastapi.responses import Response
    from fpdf import FPDF

    r = _REPORTS.get(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown report id")

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    regular_path, bold_path = _dejavu_font_path()
    if regular_path:
        pdf.add_font("DejaVu", "", regular_path)
        pdf.add_font("DejaVu", "B", bold_path)
        body_font, bold_font = "DejaVu", "DejaVu"

        def _ascii_safe(s: str) -> str:
            return s
    else:
        # Fallback if matplotlib's bundled font can't be found for some
        # reason: still don't crash - replace anything outside Latin-1
        # with a safe placeholder instead of raising.
        body_font, bold_font = "Helvetica", "Helvetica"

        def _ascii_safe(s: str) -> str:
            return s.encode("latin-1", "replace").decode("latin-1")

    pdf.set_font(bold_font, "B", 16)
    pdf.multi_cell(0, 9, _ascii_safe("AROL Telemetry Report"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(body_font, "", 10)
    pdf.multi_cell(0, 6, _ascii_safe(f"Query: {r['query']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    for line_text, style in _markdown_to_pdf_lines(r["report_text"]):
        text = _ascii_safe(line_text)
        if style == "h1":
            pdf.set_font(bold_font, "B", 14)
            pdf.ln(3)
            pdf.multi_cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
        elif style == "h2":
            pdf.set_font(bold_font, "B", 12)
            pdf.ln(2)
            pdf.multi_cell(0, 7, text, new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font(body_font, "", 10)
            pdf.multi_cell(0, 5.5, text if text.strip() else " ", new_x="LMARGIN", new_y="NEXT")

    _embed_charts_in_pdf(pdf, r.get("charts") or [])

    out = bytes(pdf.output(dest="S"))
    return Response(content=out, media_type="application/pdf")
