import pandas as pd

from arol_mas.analytics.anomaly import out_of_range_torque, zero_torque_summary
from arol_mas.agent.tools import _df_to_records


def _events(rows):
    return pd.DataFrame(rows, columns=["event_timestamp", "head_id", "torque", "status", "success"])


def test_zero_torque_excluded_from_out_of_range_by_default(settings):
    events = _events([
        ("t1", "H01", 0.0, 0, True),   # zero torque - should be excluded by default
        ("t2", "H01", 9.9, 0, True),   # genuinely out of range
        ("t3", "H01", 2.5, 0, True),   # in range
    ])
    result = out_of_range_torque(events, settings)
    assert len(result) == 1
    assert result.iloc[0]["torque"] == 9.9


def test_zero_torque_included_when_requested(settings):
    events = _events([
        ("t1", "H01", 0.0, 0, True),
        ("t2", "H01", 2.5, 0, True),
    ])
    result = out_of_range_torque(events, settings, exclude_zero_torque=False)
    assert len(result) == 1
    assert result.iloc[0]["torque"] == 0.0


def test_zero_torque_summary_counts_correctly():
    events = _events([
        ("t1", "H01", 0.0, 0, True),
        ("t2", "H01", 0.0, 0, True),
        ("t3", "H01", 2.5, 0, True),
        ("t4", "H02", 2.5, 0, True),
    ])
    summary = zero_torque_summary(events)
    assert summary["total_events"] == 4
    assert summary["zero_torque_events"] == 2
    assert summary["zero_torque_pct"] == 50.0
    h01 = next(r for r in summary["per_head"] if r["head_id"] == "H01")
    assert h01["zero_torque_count"] == 2
    assert h01["zero_torque_pct"] == round(100 * 2 / 3, 1)


def test_large_dataframe_result_is_truncated_not_dumped_whole():
    big = pd.DataFrame({"x": range(10_000)})
    result = _df_to_records(big, limit=200)
    assert isinstance(result, dict)
    assert result["total_rows"] == 10_000
    assert result["returned_rows"] == 200
    assert len(result["rows"]) == 200


def test_small_dataframe_result_passes_through_as_plain_list():
    small = pd.DataFrame({"x": range(5)})
    result = _df_to_records(small, limit=200)
    assert isinstance(result, list)
    assert len(result) == 5
