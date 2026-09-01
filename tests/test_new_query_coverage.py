"""
Covers the tools added to close gaps against AROL's example-queries
slides: generic filtering (page 2, "Filtering and conditional queries"),
hour-of-day correlation (page 2, "time of day and failure probability"),
and the plotting tools (page 3, "Visualization-oriented queries").
"""
from __future__ import annotations

import pandas as pd
import pytest

from arol_mas.analytics import filters, plotting, trend
from arol_mas.ingestion.closure_detection import ClosureEventColumns as C


@pytest.fixture
def events():
    rows = [
        # event_timestamp,             head_id, torque, status, success, is_no_load, is_reject, is_fault, status_category, status_description, count, seq_gap
        ("2026-05-20T02:00:00Z", "H01", 2.50, 0, True, False, False, False, "success", "Closure OK", 100, 1),
        ("2026-05-20T02:00:05Z", "H01", 9.90, 0, True, False, False, False, "success", "Closure OK", 101, 1),
        ("2026-05-20T14:00:00Z", "H02", 1.80, 64, False, False, True, False, "reject", "Bad Closure", 51, 1),
        ("2026-05-20T14:00:05Z", "H02", 2.40, 0, True, False, False, False, "success", "Closure OK", 52, 1),
    ]
    cols = [C.timestamp, C.head_id, C.torque, C.status, C.success, C.is_no_load,
            C.is_reject, C.is_fault, C.status_category, C.status_description, C.count, C.seq_gap]
    df = pd.DataFrame(rows, columns=cols)
    df[C.timestamp] = pd.to_datetime(df[C.timestamp], utc=True)
    return df


def test_list_closure_events_filters_by_head_and_status(events):
    result = filters.list_closure_events(events, head_id="H02", status_category="reject")
    assert len(result) == 1
    assert result.iloc[0][C.head_id] == "H02"


def test_list_closure_events_filters_by_torque_range(events):
    result = filters.list_closure_events(events, torque_min=5.0)
    assert len(result) == 1
    assert result.iloc[0][C.torque] == 9.90


def test_list_closure_events_rejects_unknown_status_category(events):
    with pytest.raises(ValueError):
        filters.list_closure_events(events, status_category="not_a_real_category")


def test_success_rate_by_hour_of_day_pools_across_days(events):
    result = trend.success_rate_by_hour_of_day(events)
    hours = set(result["hour"])
    assert hours == {2, 14}
    row_14 = result[result["hour"] == 14].iloc[0]
    assert row_14["attempted"] == 2
    assert row_14["successful"] == 1


def test_plot_torque_over_time_writes_file(settings, tmp_path, events):
    from pathlib import Path
    plot_settings = settings.model_copy(update={"project_root": tmp_path})
    result = plotting.plot_torque_over_time(events, plot_settings)
    assert Path(result["plot_path"]).exists()
    assert Path(result["plot_path"]).suffix == ".png"


def test_plot_success_rate_per_head_writes_file(settings, tmp_path, events):
    from pathlib import Path
    plot_settings = settings.model_copy(update={"project_root": tmp_path})
    result = plotting.plot_success_rate_per_head(events, plot_settings)
    assert Path(result["plot_path"]).exists()
