"""
Idle-state detection: identifies periods where a head reports a sustained
"No Load" status, using the RAW polling data (not the closure-events
table), since idle time is by definition between closures.
"""
from __future__ import annotations

import pandas as pd

from arol_mas.config import Settings
from arol_mas.ingestion.schema import all_head_columns
from arol_mas.ingestion import status_codes


def detect_idle_periods(raw_df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """
    Returns one row per contiguous "No Load" run per head that lasts at
    least `idle_no_load_seconds`, with start/end/duration. "No Load"
    (status 2) comes from AROL's own status-code mapping, not a config
    placeholder.
    """
    ts_col = settings.schema_.timestamp_col
    min_duration = settings.analytics.idle_no_load_seconds

    results = []
    for hc in all_head_columns(settings):
        if hc.status_col not in raw_df.columns:
            continue
        sub = raw_df[[ts_col, hc.status_col]].copy()
        sub["is_idle"] = sub[hc.status_col].apply(status_codes.classify) == status_codes.CATEGORY_NO_LOAD

        # group consecutive True/False runs
        sub["run_id"] = (sub["is_idle"] != sub["is_idle"].shift()).cumsum()
        for _, run in sub[sub["is_idle"]].groupby("run_id"):
            start, end = run[ts_col].iloc[0], run[ts_col].iloc[-1]
            duration_s = (end - start).total_seconds()
            if duration_s >= min_duration:
                results.append({
                    "head_id": hc.head_id,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "duration_s": round(duration_s, 1),
                })

    df = pd.DataFrame(results)
    return df.sort_values("duration_s", ascending=False) if not df.empty else df
