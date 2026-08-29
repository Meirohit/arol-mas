"""
Baseline deterministic KPI functions. These are the "reliable tools" the
report agent (WP3) calls - each one is a small, pure, testable function
over the closure-events table, matching the expected outputs shown on
pages 16-18 of the AROL brief.
"""
from __future__ import annotations

import pandas as pd

from arol_mas.ingestion.closure_detection import ClosureEventColumns as C


def overall_success_rate(events: pd.DataFrame) -> dict:
    """
    Matches 'What percentage of capping operations were successful?'

    'No Load' closures (station cycled with no bottle present) are
    excluded from the denominator - they are not capping attempts, and
    including them would understate the true success rate. 'Reject'
    closures are quality failures (machine's own reject_signal=YES).
    'Fault' closures are non-reject diagnostic anomalies (reject_signal=NO,
    e.g. 'No Closure', 'Bad Closure') - reported separately since AROL's
    own reject_signal does not treat them as failures.
    """
    total = len(events)
    if total == 0:
        return {
            "total_closures": 0, "no_load": 0, "attempted": 0,
            "successful": 0, "rejected": 0, "faults": 0,
            "success_rate_pct": None, "reject_rate_pct": None,
        }
    no_load = int(events[C.is_no_load].sum())
    attempted = total - no_load
    successful = int(events[C.success].sum())
    rejected = int(events[C.is_reject].sum())
    faults = int(events[C.is_fault].sum())
    return {
        "total_closures": total,
        "no_load": no_load,
        "attempted": attempted,
        "successful": successful,
        "rejected": rejected,
        "faults": faults,
        "success_rate_pct": round(100 * successful / attempted, 1) if attempted else None,
        "reject_rate_pct": round(100 * rejected / attempted, 1) if attempted else None,
    }


def success_rate_per_head(events: pd.DataFrame) -> pd.DataFrame:
    """Matches the head-level performance comparison table (page 17).
    Denominator excludes No Load closures - see overall_success_rate."""
    if events.empty:
        return pd.DataFrame(columns=["head_id", "total_closures", "no_load", "attempted", "successful", "rejected", "success_rate_pct"])

    grouped = events.groupby(C.head_id).agg(
        total_closures=(C.success, "size"),
        no_load=(C.is_no_load, "sum"),
        successful=(C.success, "sum"),
        rejected=(C.is_reject, "sum"),
    )
    grouped["attempted"] = grouped["total_closures"] - grouped["no_load"]
    grouped["success_rate_pct"] = (100 * grouped["successful"] / grouped["attempted"].replace(0, pd.NA)).round(1)
    return grouped.reset_index()[
        ["head_id", "total_closures", "no_load", "attempted", "successful", "rejected", "success_rate_pct"]
    ].sort_values("success_rate_pct")


def torque_statistics(events: pd.DataFrame, successful_only: bool = True) -> dict:
    """Matches 'What is the average closing torque for successful capping operations?'"""
    subset = events[events[C.success]] if successful_only else events
    if subset.empty:
        return {"n_events": 0, "mean_nm": None, "min_nm": None, "max_nm": None, "std_nm": None}
    t = subset[C.torque]
    return {
        "n_events": int(len(subset)),
        "mean_nm": round(float(t.mean()), 2),
        "min_nm": round(float(t.min()), 2),
        "max_nm": round(float(t.max()), 2),
        "std_nm": round(float(t.std()), 2) if len(t) > 1 else 0.0,
    }


def torque_statistics_per_head(events: pd.DataFrame, successful_only: bool = True) -> pd.DataFrame:
    subset = events[events[C.success]] if successful_only else events
    if subset.empty:
        return pd.DataFrame(columns=["head_id", "n_events", "mean_nm", "min_nm", "max_nm", "std_nm"])
    grouped = subset.groupby(C.head_id)[C.torque].agg(
        n_events="count", mean_nm="mean", min_nm="min", max_nm="max", std_nm="std"
    ).round(2).fillna(0.0)
    return grouped.reset_index()


def failed_vs_successful_torque(events: pd.DataFrame) -> dict:
    """
    Matches 'Compare the average torque of successful vs failed closures.'

    'Failed' here means reject_signal=YES closures specifically - NOT
    simply 'not successful', which would wrongly lump in No Load closures
    (torque is always ~0 there by definition, which would badly distort
    the comparison).
    """
    return {
        "successful": torque_statistics(events, successful_only=True),
        "rejected": torque_statistics(events[events[C.is_reject]], successful_only=False),
    }


def time_range(events: pd.DataFrame) -> dict:
    """Matches 'Show me the time range covered by the dataset.'"""
    if events.empty:
        return {"start": None, "end": None}
    ts = pd.to_datetime(events[C.timestamp])
    return {"start": ts.min().isoformat(), "end": ts.max().isoformat()}
