"""
Generic filtering/listing over the closure-events table.

The deterministic analytics tools (kpi/trend/anomaly/correlation) each
answer one specific, pre-defined question. AROL's own example query list
also includes ad-hoc filtering questions that don't fit any single
pre-built tool - e.g. "list all failed capping events with torque below
threshold", "show all capping events for head 3 with a failed outcome",
"how many closures had torque above X Nm". This module gives the agent
one generic tool that covers that whole class of question instead of
needing a bespoke function per combination of filters.
"""
from __future__ import annotations

import pandas as pd

from arol_mas.ingestion.closure_detection import ClosureEventColumns as C

VALID_STATUS_CATEGORIES = {"success", "no_load", "reject", "fault"}


def list_closure_events(
    events: pd.DataFrame,
    head_id: str | None = None,
    status_category: str | None = None,
    torque_min: float | None = None,
    torque_max: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame:
    """
    Filters the closure-events table by any combination of head, status
    category (success/no_load/reject/fault), torque range, and date/time
    range.

    start_date/end_date accept an ISO date ("2026-03-05") or full
    ISO datetime ("2026-03-05T14:00:00Z"). When only a bare date is given,
    start_date is treated as the start of that day (00:00:00) and end_date
    as the END of that day (23:59:59.999...), i.e. end-inclusive - matching
    the semantics already used by tools.py::_scope_events() and
    loader.load_period_streaming() elsewhere in this codebase.

    Returns the matching rows (timestamp, head_id, torque, status_category,
    status_description). Callers that only need a count should use
    len(result) - the agent-facing tool wraps this with the same
    row-count-capping behaviour as every other listing tool, so it is safe
    to call even when a filter matches millions of rows.
    """
    result = events

    if head_id:
        result = result[result[C.head_id] == head_id]

    if status_category:
        if status_category not in VALID_STATUS_CATEGORIES:
            raise ValueError(
                f"Unknown status_category '{status_category}'. "
                f"Must be one of: {sorted(VALID_STATUS_CATEGORIES)}"
            )
        result = result[result[C.status_category] == status_category]

    if torque_min is not None:
        result = result[result[C.torque] >= torque_min]
    if torque_max is not None:
        result = result[result[C.torque] <= torque_max]

    if (start_date is not None or end_date is not None) and not result.empty:
        ts = pd.to_datetime(result[C.timestamp], utc=True)
        if start_date is not None:
            start_ts = pd.Timestamp(start_date)
            if start_ts.tzinfo is None:
                start_ts = start_ts.tz_localize("UTC")
            result = result[ts >= start_ts]
            ts = pd.to_datetime(result[C.timestamp], utc=True)
        if end_date is not None:
            end_ts = pd.Timestamp(end_date)
            if end_ts.tzinfo is None:
                end_ts = end_ts.tz_localize("UTC")
                # bare date (no time-of-day) -> inclusive through end of day
                if len(str(end_date)) <= 10:
                    end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            result = result[ts <= end_ts]

    cols = [C.timestamp, C.head_id, C.torque, C.status_category, C.status_description]
    return result[cols].sort_values(C.timestamp).reset_index(drop=True)
