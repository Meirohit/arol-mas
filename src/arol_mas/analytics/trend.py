"""
Trend analysis: moving averages and drift detection on torque values,
plus time-based success-rate breakdowns.
"""
from __future__ import annotations

import pandas as pd

from arol_mas.config import Settings
from arol_mas.ingestion.closure_detection import ClosureEventColumns as C


def torque_moving_average(events: pd.DataFrame, settings: Settings, head_id: str | None = None) -> pd.DataFrame:
    """Rolling mean of torque over successive closure events, used to spot
    slow drift that a single overall average would hide."""
    subset = events[events[C.success]]
    if head_id:
        subset = subset[subset[C.head_id] == head_id]
    subset = subset.sort_values(C.timestamp)
    if subset.empty:
        return pd.DataFrame(columns=[C.timestamp, C.head_id, "torque_moving_avg"])

    window = settings.analytics.moving_average_window
    subset = subset.copy()
    subset["torque_moving_avg"] = (
        subset.groupby(C.head_id)[C.torque]
        .transform(lambda s: s.rolling(window=min(window, len(s)), min_periods=1).mean())
    )
    return subset[[C.timestamp, C.head_id, "torque_moving_avg"]]


def detect_drift(events: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """
    Flags heads whose recent torque mean has drifted more than
    `drift_zscore_threshold` standard deviations from their own historical
    baseline (first half of the dataset vs. second half).
    """
    results = []
    threshold = settings.analytics.drift_zscore_threshold
    subset = events[events[C.success]].sort_values(C.timestamp)

    for head_id, grp in subset.groupby(C.head_id):
        if len(grp) < 10:
            continue
        midpoint = len(grp) // 2
        baseline = grp[C.torque].iloc[:midpoint]
        recent = grp[C.torque].iloc[midpoint:]
        if baseline.std() == 0 or baseline.empty or recent.empty:
            continue
        z = (recent.mean() - baseline.mean()) / baseline.std()
        results.append({
            "head_id": head_id,
            "baseline_mean_nm": round(float(baseline.mean()), 2),
            "recent_mean_nm": round(float(recent.mean()), 2),
            "zscore": round(float(z), 2),
            "drift_detected": bool(abs(z) >= threshold),
        })

    return pd.DataFrame(results).sort_values("zscore", key=abs, ascending=False)


def success_rate_over_time(events: pd.DataFrame, freq: str = "1D") -> pd.DataFrame:
    """Matches 'Show a daily breakdown of successful vs failed closures.'
    No Load closures are excluded from the denominator (see kpi.overall_success_rate)."""
    if events.empty:
        return pd.DataFrame(columns=["period", "attempted", "successful", "rejected", "success_rate_pct"])
    ts = pd.to_datetime(events[C.timestamp])
    attempted = events[~events[C.is_no_load]].assign(_period=ts[~events[C.is_no_load]].dt.floor(freq))
    grouped = attempted.groupby("_period").agg(
        attempted=(C.success, "size"), successful=(C.success, "sum"), rejected=(C.is_reject, "sum")
    )
    grouped["success_rate_pct"] = (100 * grouped["successful"] / grouped["attempted"]).round(1)
    return grouped.reset_index().rename(columns={"_period": "period"})
