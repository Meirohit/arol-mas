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


@pytest.fixture
def multi_day_events():
    rows = [
        ("2026-03-01T10:00:00Z", "H01", 2.0, 0, True, False, False, False, "success", "Closure OK", 1, 1),
        ("2026-03-05T10:00:00Z", "H01", 2.1, 0, True, False, False, False, "success", "Closure OK", 2, 1),
        ("2026-03-05T23:59:50Z", "H02", 1.9, 64, False, False, True, False, "reject", "Bad Closure", 1, 1),
        ("2026-03-10T00:00:05Z", "H01", 2.2, 0, True, False, False, False, "success", "Closure OK", 3, 1),
        ("2026-03-20T10:00:00Z", "H01", 2.3, 0, True, False, False, False, "success", "Closure OK", 4, 1),
    ]
    cols = [C.timestamp, C.head_id, C.torque, C.status, C.success, C.is_no_load,
            C.is_reject, C.is_fault, C.status_category, C.status_description, C.count, C.seq_gap]
    df = pd.DataFrame(rows, columns=cols)
    df[C.timestamp] = pd.to_datetime(df[C.timestamp], utc=True)
    return df


def test_list_closure_events_filters_by_date_range(multi_day_events):
    # start_date/end_date given as bare dates -> end_date must be
    # inclusive through the END of that day, not its first instant, so
    # the 23:59:50 reject row on March 5th must NOT be silently excluded.
    result = filters.list_closure_events(multi_day_events, start_date="2026-03-05", end_date="2026-03-05")
    assert len(result) == 2
    assert set(result[C.status_category]) == {"success", "reject"}


def test_list_closure_events_date_range_excludes_outside_window(multi_day_events):
    result = filters.list_closure_events(multi_day_events, start_date="2026-03-02", end_date="2026-03-15")
    assert len(result) == 3  # Mar 5 (x2) + Mar 10 - excludes Mar 1 and Mar 20


def test_list_closure_events_date_range_combines_with_other_filters(multi_day_events):
    result = filters.list_closure_events(
        multi_day_events, start_date="2026-03-05", end_date="2026-03-05", status_category="reject"
    )
    assert len(result) == 1
    assert result.iloc[0][C.head_id] == "H02"


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


def test_capping_speed_summary_returns_a_positive_rate(events):
    result = trend.capping_speed_summary(events)
    assert result["n_events"] == 4
    assert result["overall_pieces_per_hour"] > 0


def test_capping_speed_summary_empty_events():
    result = trend.capping_speed_summary(pd.DataFrame())
    assert result["overall_pieces_per_hour"] is None
    assert result["n_events"] == 0


def test_capping_speed_over_time_two_days():
    rows = [
        ("2026-03-01T10:00:00Z", "H01", 2.0, 0, True, False, False, False, "success", "ok", 1, 1),
        ("2026-03-01T11:00:00Z", "H01", 2.0, 0, True, False, False, False, "success", "ok", 2, 1),
        ("2026-03-02T10:00:00Z", "H01", 2.0, 0, True, False, False, False, "success", "ok", 3, 1),
    ]
    cols = [C.timestamp, C.head_id, C.torque, C.status, C.success, C.is_no_load,
            C.is_reject, C.is_fault, C.status_category, C.status_description, C.count, C.seq_gap]
    df = pd.DataFrame(rows, columns=cols)
    df[C.timestamp] = pd.to_datetime(df[C.timestamp], utc=True)

    result = trend.capping_speed_over_time(df, freq="1D")
    assert len(result) == 2
    day1 = result[result["period"] == pd.Timestamp("2026-03-01", tz="UTC")].iloc[0]
    assert day1["n_events"] == 2
    assert day1["pieces_per_hour"] == pytest.approx(2 / 24, abs=0.05)