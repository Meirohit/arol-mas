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
) -> pd.DataFrame:
    """
    Filters the closure-events table by any combination of head, status
    category (success/no_load/reject/fault), and torque range.

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

    cols = [C.timestamp, C.head_id, C.torque, C.status_category, C.status_description]
    return result[cols].sort_values(C.timestamp).reset_index(drop=True)
