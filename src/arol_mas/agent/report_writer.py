"""Renders a ReportResult to a Markdown file using the Jinja2 template,
saving into the configured reports output directory (never a hard-coded path)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from arol_mas.agent.orchestrator import ReportResult
from arol_mas.config import Settings


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:max_len] or "report"


def save_report(result: ReportResult, settings: Settings, dataset_label: str) -> Path:
    template_dir = settings.resolve(settings.reports.template_dir)
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    template = env.get_template("report.md.j2")

    rendered = template.render(
        generated_at=datetime.now(timezone.utc).isoformat(),
        dataset_label=dataset_label,
        query=result.query,
        report_text=result.report_text,
        tool_calls=result.tool_calls,
    )

    out_dir = settings.reports_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{stamp}_{_slugify(result.query)}.md"
    out_path.write_text(rendered, encoding="utf-8")
    return out_path
