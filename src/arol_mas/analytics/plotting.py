"""
Plot generation.

AROL's brief (slide 3, OBJECTIVE) explicitly asks for "repeatable,
explainable outputs (reports + plots/tables where relevant)", and the
example-queries slides have a whole "Visualization-oriented queries"
section ("plot the closing torque over time", "show a histogram of
closing torque values", "create a chart showing success rate per head",
"visualize failed closures over time"). Everything below is a thin,
deterministic wrapper (no LLM involved) that the agent can call like any
other WP2 tool - it saves a PNG under the configured plots directory and
returns its path, which the report template then embeds.

matplotlib is used with the non-interactive "Agg" backend since this
runs from a CLI/report-generation context, never a GUI.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from arol_mas.config import Settings
from arol_mas.ingestion.closure_detection import ClosureEventColumns as C


def _slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return slug[:max_len] or "plot"


def _save(fig, settings: Settings, name: str) -> str:
    out_dir = settings.resolve(settings.reports.plots_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{stamp}_{_slugify(name)}.png"
    fig.savefig(out_path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return str(out_path)


def plot_torque_over_time(events: pd.DataFrame, settings: Settings, head_id: str | None = None) -> dict:
    """'Plot the closing torque over time for successful closures.'"""
    subset = events[events[C.success]]
    if head_id:
        subset = subset[subset[C.head_id] == head_id]
    subset = subset.sort_values(C.timestamp)

    fig, ax = plt.subplots(figsize=(9, 4))
    if subset.empty:
        ax.set_title("No successful closures matched this filter")
    else:
        ts = pd.to_datetime(subset[C.timestamp])
        ax.plot(ts, subset[C.torque], marker=".", linestyle="none", alpha=0.4, markersize=3)
        title = "Closing torque over time (successful closures)"
        if head_id:
            title += f" - {head_id}"
        ax.set_title(title)
        ax.set_xlabel("Time")
        ax.set_ylabel("Torque (Nm)")
        fig.autofmt_xdate()

    path = _save(fig, settings, f"torque_over_time_{head_id or 'all'}")
    return {"plot_path": path, "n_points": int(len(subset))}


def plot_torque_histogram(events: pd.DataFrame, settings: Settings, successful_only: bool = True) -> dict:
    """'Show a histogram of closing torque values.'"""
    subset = events[events[C.success]] if successful_only else events

    fig, ax = plt.subplots(figsize=(7, 4))
    if subset.empty:
        ax.set_title("No closures matched this filter")
    else:
        ax.hist(subset[C.torque].dropna(), bins=40, edgecolor="white")
        ax.set_title("Closing torque distribution" + (" (successful only)" if successful_only else ""))
        ax.set_xlabel("Torque (Nm)")
        ax.set_ylabel("Count")

    path = _save(fig, settings, "torque_histogram")
    return {"plot_path": path, "n_points": int(len(subset))}


def plot_success_rate_per_head(events: pd.DataFrame, settings: Settings) -> dict:
    """'Create a chart showing success rate per head.'"""
    from arol_mas.analytics import kpi

    per_head = kpi.success_rate_per_head(events)

    fig, ax = plt.subplots(figsize=(max(6, 0.3 * len(per_head)), 4))
    if per_head.empty:
        ax.set_title("No closure events found")
    else:
        ordered = per_head.sort_values("head_id")
        ax.bar(ordered["head_id"], ordered["success_rate_pct"])
        ax.set_title("Success rate per head")
        ax.set_xlabel("Head")
        ax.set_ylabel("Success rate (%)")
        ax.set_ylim(0, 100)
        plt.setp(ax.get_xticklabels(), rotation=90)

    path = _save(fig, settings, "success_rate_per_head")
    return {"plot_path": path, "n_heads": int(len(per_head))}


def plot_failed_closures_over_time(events: pd.DataFrame, settings: Settings, freq: str = "1D") -> dict:
    """'Visualize failed closures over time.' 'Failed' here means AROL's
    own reject_signal=YES closures (see status_codes.py), not the broader
    'not successful' set which also includes No Load and non-reject faults."""
    failed = events[events[C.is_reject]]

    fig, ax = plt.subplots(figsize=(9, 4))
    if failed.empty:
        ax.set_title("No rejected closures found")
    else:
        ts = pd.to_datetime(failed[C.timestamp])
        counts = ts.dt.floor(freq).value_counts().sort_index()
        ax.bar(counts.index, counts.values, width=0.8 * (counts.index[1] - counts.index[0]) if len(counts) > 1 else 1)
        ax.set_title("Rejected closures over time")
        ax.set_xlabel("Time")
        ax.set_ylabel("Rejected closures")
        fig.autofmt_xdate()

    path = _save(fig, settings, "failed_closures_over_time")
    return {"plot_path": path, "n_rejected": int(len(failed))}
