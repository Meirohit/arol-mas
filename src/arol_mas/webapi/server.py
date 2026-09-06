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
import re
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
    load_pool_streaming,
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


_PLOTTABLE_TOOLS = {
    "plot_torque_over_time",
    "plot_torque_histogram",
    "plot_success_rate_per_head",
    "plot_failed_closures_over_time",
}

# Matches the exact "![alt](path)" syntax the agent is instructed to write
# (see orchestrator.SYSTEM_PROMPT point 3) so we can tell which plot_path
# values it already embedded inline in report_text.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
# Same thing but keeping the alt text too, for substituting in the path
# without losing it - used only by the self-contained-download helpers
# below, kept separate so the single-group regex above (used with
# .findall()/.fullmatch() elsewhere) doesn't change shape.
_MD_IMAGE_ALT_PATH_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _charts_for_tool_calls(tool_calls: List[Dict[str, Any]], ctx: AgentContext) -> List[Dict[str, str]]:
    """
    Builds the web UI's chart list from the plot_path each plot_* tool
    already produced during the agent's OWN run (captured on
    tool_calls_log by orchestrator.ReportAgent.run), instead of re-running
    the tool a second time.

    This used to call run_tool(name, ...) again here, which (a) roughly
    doubled the cost of any chart-bearing report, since matplotlib
    rendering happened twice, and (b) produced a second, freshly
    timestamped PNG distinct from the one the agent already referenced
    inline in report_text - so the exact same chart appeared to render
    twice, with (occasionally) subtly different-looking output. Reading
    the plot_path captured on the first and only real execution fixes
    both: one render, one file, referenced from both places.
    """
    charts: List[Dict[str, str]] = []
    seen_paths = set()
    for call in tool_calls:
        name = call.get("tool")
        plot_path = call.get("plot_path")
        if name not in _PLOTTABLE_TOOLS or not plot_path or plot_path in seen_paths:
            continue
        seen_paths.add(plot_path)
        image = _png_path_to_data_uri(ctx.settings, plot_path)
        if image:
            charts.append({"tool": name, "image": image, "plot_path": plot_path})

    return charts


def _charts_by_path(r: Dict[str, Any]) -> Dict[str, str]:
    """plot_path -> base64 data URI, from every chart the agent produced
    (charts_all, not just the "extras" the grid shows) - the lookup used
    to make the md/html downloads self-contained (see
    _self_contained_markdown/_self_contained_html)."""
    return {
        c["plot_path"]: c["image"]
        for c in (r.get("charts_all") or [])
        if c.get("plot_path") and c.get("image")
    }


def _self_contained_markdown(report_text: str, charts_by_path: Dict[str, str]) -> str:
    """
    Rewrites every "![alt](plot_path)" reference in report_text to use a
    base64 data URI instead of the relative "plots/xxx.png" path that
    report_writer.save_report writes to disk.

    The relative path only resolves when the .md file is read from
    exactly where it lives on the server (reports/ next to reports/plots/)
    - which is true for the CLI and for the on-disk copy, but not for a
    file a person just downloaded via the browser: opened later in a
    Markdown viewer with no "plots/" folder beside it, the image is
    simply missing. A self-contained data URI works wherever the file
    ends up.
    """
    def _replace(match: "re.Match") -> str:
        alt, path = match.group(1), match.group(2)
        data_uri = charts_by_path.get(path)
        return f"![{alt}]({data_uri})" if data_uri else match.group(0)

    return _MD_IMAGE_ALT_PATH_RE.sub(_replace, report_text)


def _self_contained_html(html: str, charts_by_path: Dict[str, str]) -> str:
    """
    Same idea as _self_contained_markdown, but for the HTML export: the
    live web UI's src="/report-files/plots/xxx.png" only resolves through
    the FastAPI process that mounted /report-files (see the StaticFiles
    mount above) - fine when viewing the report at that URL in a browser,
    but a downloaded .html file opened later (or without the server
    running) has no such origin to resolve against, so the image is
    simply missing. Swapping in the same base64 data URI already computed
    for the chart grid makes the downloaded file open correctly anywhere.
    """
    for plot_path, data_uri in charts_by_path.items():
        html = html.replace(f'src="/report-files/{plot_path}"', f'src="{data_uri}"')
    return html


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

    # `charts` holds every plot_* tool the agent ran. Any of those the
    # agent already referenced inline via "![...](plot_path)" (per
    # orchestrator.SYSTEM_PROMPT point 3) render in report_html/report_text
    # already - repeating them in the "Charts" grid would show the same
    # image twice on the page. `charts` (extras only) is what the web UI's
    # grid and the HTML export use; `charts_all` keeps every chart so the
    # PDF export can still embed each one exactly where it's referenced in
    # the text, falling back to appending any true extras at the end.
    referenced_paths = set(_MD_IMAGE_RE.findall(result.report_text))
    extra_charts = [c for c in charts if c.get("plot_path") not in referenced_paths]

    _REPORTS[report_id] = {
        "report_id": report_id,
        "query": result.query,
        "dataset_label": dataset_label,
        "report_text": result.report_text,
        "report_html": _render_report_html_fragment(result.report_text),
        "tool_calls": result.tool_calls,
        "charts": extra_charts,
        "charts_all": charts,
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
    # Mirrors cli.main.cmd_validate: validate_pool_files streams and
    # discards each file in turn (see ingestion/loader.py) instead of
    # concatenating the whole pool into memory just to run schema checks -
    # the same reason the agent-facing loaders above are streaming too.
    problems = validate_pool_files(settings, pool_name=pool)
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


def _download_headers(report_id: str, ext: str) -> Dict[str, str]:
    """
    Content-Disposition: attachment so clicking a download link actually
    downloads the file instead of navigating the browser tab to open it
    inline - previously none of the md/html/pdf export endpoints set this
    header at all, so every "download" link just opened a new in-browser
    view of the content.
    """
    return {"Content-Disposition": f'attachment; filename="report_{report_id}.{ext}"'}


@app.get("/api/reports/{report_id}/md", response_class=PlainTextResponse)
def get_report_md(report_id: str):
    r = _REPORTS.get(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown report id")
    text = _self_contained_markdown(r["report_text"], _charts_by_path(r))
    return PlainTextResponse(text, headers=_download_headers(report_id, "md"))


@app.get("/api/reports/{report_id}/html", response_class=HTMLResponse)
def get_report_html(report_id: str):
    r = _REPORTS.get(report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Unknown report id")
    body = r.get("report_html") or _render_report_html_fragment(r["report_text"])
    body = _self_contained_html(body, _charts_by_path(r))
    charts_html = "".join(
        f'<figure><img src="{c["image"]}" style="max-width:600px"><figcaption>{c["tool"]}</figcaption></figure>'
        for c in r["charts"]
    )
    html = (
        f"<html><head><meta charset='utf-8'><title>{r['query']}</title></head>"
        f"<body style='font-family:sans-serif;max-width:800px;margin:2rem auto'>"
        f"<h1>AROL Telemetry Report</h1><p><em>{r['query']}</em></p>{body}{charts_html}"
        f"</body></html>"
    )
    return HTMLResponse(html, headers=_download_headers(report_id, "html"))


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


_TABLE_ROW_RE = re.compile(r"^\|(.+)\|$")
_TABLE_SEP_RE = re.compile(r"^\|[\s:\-|]+\|$")


def _parse_markdown_table_row(line: str) -> List[str]:
    return [cell.strip() for cell in line.strip()[1:-1].split("|")]


def _markdown_to_pdf_lines(text: str) -> List[tuple]:
    """
    Very small Markdown -> (content, style) block converter for the PDF
    export. Not a full renderer - just enough to stop "## Heading" /
    "**bold**" syntax, image references, and pipe tables from showing up
    as literal, unformatted text in the PDF (which looked broken even on
    the rare occasion the old core-font PDF didn't crash outright).

    A line that is exactly a Markdown image reference - "![alt](path)",
    which is precisely what the agent is instructed to write for a chart
    (see orchestrator.SYSTEM_PROMPT point 3) - is emitted as
    (path, "image") so the caller can embed the actual chart there.

    A header row immediately followed by a "|---|---|"-style separator
    row (GitHub-flavoured Markdown tables, which the `markdown` library's
    "tables" extension already renders correctly for the HTML export - see
    _render_report_html_fragment) is consumed as a whole block and
    emitted as (rows, "table"), rows being a list-of-lists with the
    header as rows[0]. Previously nothing here recognized table syntax at
    all: every row - including the "| --- | --- |" separator itself -
    came through as literal, unaligned pipe-delimited text in the PDF body.

    Returns a list of (content, style) where style is
    "h1"/"h2"/"body"/"image"/"table".
    """
    lines = text.split("\n")
    out: List[tuple] = []
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i].rstrip()
        stripped = raw.strip()

        if (
            _TABLE_ROW_RE.match(stripped)
            and i + 1 < n
            and _TABLE_SEP_RE.match(lines[i + 1].strip())
        ):
            rows = [_parse_markdown_table_row(stripped)]
            i += 2  # header + separator already consumed
            while i < n and _TABLE_ROW_RE.match(lines[i].strip()):
                rows.append(_parse_markdown_table_row(lines[i].strip()))
                i += 1
            out.append((rows, "table"))
            continue

        image_match = _MD_IMAGE_RE.fullmatch(stripped)
        if image_match:
            out.append((image_match.group(1), "image"))
        elif raw.startswith("## "):
            out.append((raw[3:].strip(), "h2"))
        elif raw.startswith("# "):
            out.append((raw[2:].strip(), "h1"))
        else:
            # strip bold/italic markers - kept as plain text since FPDF's
            # multi_cell doesn't support inline mixed styling without a
            # lot more machinery than this export needs.
            clean = re.sub(r"\*\*(.*?)\*\*", r"\1", raw)
            clean = re.sub(r"\*(.*?)\*", r"\1", clean)
            out.append((clean, "body"))
        i += 1
    return out


def _embed_chart_image_in_pdf(pdf, image: Optional[str], label: str) -> None:
    """
    Decodes a chart's base64 data URI (produced by
    _png_path_to_data_uri/_charts_for_tool_calls) and embeds it as an
    image in the PDF via fpdf2's Image support.
    """
    import base64
    from io import BytesIO

    if not image or "," not in image:
        return
    try:
        _, b64_data = image.split(",", 1)
        img_bytes = base64.b64decode(b64_data)
        pdf.ln(3)
        pdf.image(BytesIO(img_bytes), w=170)
        pdf.ln(2)
    except Exception:
        logger.exception("Could not embed chart '%s' in PDF export", label)


def _embed_table_in_pdf(pdf, rows: List[List[str]], body_font: str) -> None:
    """
    Renders a parsed Markdown table (rows[0] is the header) as an actual
    fpdf2 table instead of raw pipe-delimited text. Falls back to
    skipping silently (rather than crashing the whole export) if fpdf2
    can't lay it out - e.g. a pathologically wide table - since a missing
    table beats a failed PDF download.
    """
    if not rows:
        return
    try:
        pdf.set_font(body_font, "", 9)
        pdf.ln(2)
        with pdf.table() as table:
            for row_index, data_row in enumerate(rows):
                row = table.row()
                for cell in data_row:
                    row.cell(cell)
        pdf.ln(2)
        pdf.set_font(body_font, "", 10)
    except Exception:
        logger.exception("Could not render table in PDF export")


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

    # Lookup from plot_path -> chart, built from EVERY chart the agent
    # produced (charts_all), not just the "extras" the web UI's grid shows -
    # this is what lets an image referenced inline in report_text actually
    # render at that point in the PDF instead of as literal "![...](...)"
    # text (previously _markdown_to_pdf_lines didn't recognize image syntax
    # at all, so it always fell through to the "body" text branch below).
    charts_by_path = {
        c["plot_path"]: c for c in (r.get("charts_all") or []) if c.get("plot_path")
    }
    embedded_paths = set()

    for content, style in _markdown_to_pdf_lines(r["report_text"]):
        if style == "image":
            chart = charts_by_path.get(content)
            if chart:
                _embed_chart_image_in_pdf(pdf, chart.get("image"), chart.get("tool", content))
                embedded_paths.add(content)
            continue

        if style == "table":
            _embed_table_in_pdf(pdf, content, body_font)
            continue

        text = _ascii_safe(content)
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

    # Any chart the agent generated but never referenced inline (rare -
    # the system prompt tells it to always embed a plot_* result) still
    # gets appended, same as before, so it isn't silently lost from the PDF.
    leftover = [c for c in (r.get("charts") or []) if c.get("plot_path") not in embedded_paths]
    for chart in leftover:
        _embed_chart_image_in_pdf(pdf, chart.get("image"), chart.get("tool", ""))

    out = bytes(pdf.output(dest="S"))
    return Response(
        content=out,
        media_type="application/pdf",
        headers=_download_headers(report_id, "pdf"),
    )
