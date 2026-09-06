"""
Anomaly detection over closure events: out-of-range torque and
statistically unusual heads/periods.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from arol_mas.config import Settings
from arol_mas.ingestion.closure_detection import ClosureEventColumns as C


def out_of_range_torque(events: pd.DataFrame, settings: Settings, exclude_zero_torque: bool = True) -> pd.DataFrame:
    """
    Matches 'Are there torque values outside the expected operating range?'

    exclude_zero_torque=True (default) drops exact-zero torque readings,
    since on real AROL data these overwhelmingly represent "No Load"
    cycles (head rotated through its position with no bottle present),
    not genuine faults. Use zero_torque_summary() to quantify those
    separately, and pass exclude_zero_torque=False here if you
    specifically want zero readings included in the range check.
    """
    lo, hi = settings.analytics.torque_expected_range_nm
    mask = (events[C.torque] < lo) | (events[C.torque] > hi)
    if exclude_zero_torque:
        mask &= events[C.torque] != 0
    return events[mask][[C.timestamp, C.head_id, C.torque, C.status, C.success]].sort_values(C.timestamp)


def zero_torque_summary(events: pd.DataFrame) -> dict:
    """
    Aggregated (not row-level) view of zero-torque events: how many,
    on which heads, and what fraction of that head's total closures
    they represent. Use this instead of out_of_range_torque for
    'are there zero-torque events' style questions - it stays small
    regardless of dataset size, since it never returns one row per event.

    Note: with the AROL status-code mapping in place, 'No Load' (status 2)
    is the authoritative signal for this condition - see overall_success_rate
    and torque_status_consistency_check. This function is now mainly useful
    as an independent cross-check against that status field.
    """
    if events.empty:
        return {"total_events": 0, "zero_torque_events": 0, "zero_torque_pct": None, "per_head": []}

    zero_mask = events[C.torque] == 0
    total = len(events)
    n_zero = int(zero_mask.sum())

    per_head = (
        events.assign(_is_zero=zero_mask)
        .groupby(C.head_id)
        .agg(total_closures=(C.torque, "size"), zero_torque_count=("_is_zero", "sum"))
    )
    per_head["zero_torque_pct"] = (100 * per_head["zero_torque_count"] / per_head["total_closures"]).round(1)
    per_head = per_head.reset_index().sort_values("zero_torque_pct", ascending=False)

    return {
        "total_events": total,
        "zero_torque_events": n_zero,
        "zero_torque_pct": round(100 * n_zero / total, 1),
        "per_head": per_head.to_dict(orient="records"),
        "note": (
            "Cross-check only - the authoritative 'No Load' signal is "
            "status code 2 (see overall_success_rate's 'no_load' field). "
            "Use torque_status_consistency_check to see where the two "
            "signals disagree."
        ),
    }


def statistical_outliers(events: pd.DataFrame, z_threshold: float = 3.0) -> pd.DataFrame:
    """Per-head z-score outliers on torque, independent of the fixed range check above."""
    subset = events[events[C.success]].copy()
    if subset.empty:
        return subset

    def _zscore(group: pd.DataFrame) -> pd.DataFrame:
        std = group[C.torque].std()
        if not std or pd.isna(std):
            group["torque_zscore"] = 0.0
        else:
            group["torque_zscore"] = (group[C.torque] - group[C.torque].mean()) / std
        return group

    scored = subset.groupby(C.head_id, group_keys=False).apply(_zscore)
    return scored[scored["torque_zscore"].abs() >= z_threshold].sort_values(
        "torque_zscore", key=abs, ascending=False
    )


def head_with_most_failures(events: pd.DataFrame) -> dict:
    """
    Matches 'Which head contributes most to overall failures?'

    'Failures' means reject_signal=YES closures (the machine's own
    quality-reject flag) - not simply 'not successful', which would
    wrongly include No Load closures.
    """
    failed = events[events[C.is_reject]]
    if failed.empty:
        return {"head_id": None, "failure_count": 0}
    counts = failed.groupby(C.head_id).size().sort_values(ascending=False)
    return {"head_id": counts.index[0], "failure_count": int(counts.iloc[0])}


def fault_code_breakdown(events: pd.DataFrame) -> Any:
    """
    Distribution of every non-success, non-no-load status code seen in
    the data, with AROL's own description and reject_signal for each -
    the diagnostic drill-down behind the single reject-rate number.
    """
    subset = events[~events[C.success] & ~events[C.is_no_load]]
    if subset.empty:
        return []
    breakdown = (
        subset.groupby([C.status, C.status_description, C.is_reject])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    return breakdown.to_dict(orient="records")


def torque_status_consistency_check(events: pd.DataFrame) -> dict:
    """
    Cross-validates two independent signals that should agree: a closure
    marked 'No Load' (status 2) should have ~zero torque, and a closure
    with ~zero torque should generally be marked No Load. Rows where
    they disagree are worth a service engineer's attention - either a
    sensor/logging glitch or a mislabeled status.
    """
    no_load_nonzero_torque = events[events[C.is_no_load] & (events[C.torque] != 0)]
    zero_torque_not_no_load = events[(events[C.torque] == 0) & ~events[C.is_no_load]]
    return {
        "no_load_with_nonzero_torque_count": int(len(no_load_nonzero_torque)),
        "zero_torque_not_marked_no_load_count": int(len(zero_torque_not_no_load)),
        "note": (
            "Both counts should normally be near zero. Non-trivial counts "
            "suggest a sensor timing issue or that the No Load status "
            "isn't perfectly aligned with the torque reading on this line."
        ),
    }
