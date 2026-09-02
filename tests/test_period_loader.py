"""
Covers loading scoped by date range instead of (or spanning) a single
pool folder - e.g. "Feb 12 to March 15" when February and March live in
separate pool directories (data/pools/2026-02/, data/pools/2026-03/).
See loader.resolve_period_files / load_period_streaming.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from arol_mas.ingestion.loader import load_period_streaming, resolve_period_files


def _write_dated_pool(pools_dir: Path, pool_name: str, day_frames: dict[str, pd.DataFrame]) -> None:
    """day_frames: {'2026-02-27': df, '2026-02-28': df, ...} - filenames
    follow AROL's real naming convention so resolve_period_files can read
    the date straight out of the filename."""
    pool_dir = pools_dir / pool_name
    pool_dir.mkdir(parents=True, exist_ok=True)
    for day, frame in day_frames.items():
        out = frame.copy()
        out["timestamp"] = out["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        out.to_csv(pool_dir / f"telemetry_MACHINE_{day}.csv", index=False)


def _day_df(day: str, start_count: int) -> pd.DataFrame:
    rows = [
        (f"{day}T00:00:0{i}Z", 2.0, 0, start_count + i, 0.0, 2, 50)
        for i in range(3)
    ]
    cols = ["timestamp", "H01 AppTorque", "H01 Status", "H01 Count", "H02 AppTorque", "H02 Status", "H02 Count"]
    df = pd.DataFrame(rows, columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def _make_settings(settings, tmp_path: Path):
    return settings.model_copy(update={
        "data": settings.data.model_copy(update={"pools_dir": str(tmp_path / "pools")}),
        "project_root": tmp_path,
    })


@pytest.fixture
def two_month_pools(settings, tmp_path):
    scoped = _make_settings(settings, tmp_path)
    pools_dir = tmp_path / "pools"
    _write_dated_pool(pools_dir, "2026-02", {
        "2026-02-27": _day_df("2026-02-27", 100),
        "2026-02-28": _day_df("2026-02-28", 200),
    })
    _write_dated_pool(pools_dir, "2026-03", {
        "2026-03-01": _day_df("2026-03-01", 300),
        "2026-03-02": _day_df("2026-03-02", 400),
    })
    return scoped


def test_resolve_period_files_spans_multiple_pool_dirs(two_month_pools):
    files = resolve_period_files(two_month_pools, start_date="2026-02-28", end_date="2026-03-01")
    names = sorted(f.name for f in files)
    assert names == [
        "telemetry_MACHINE_2026-02-28.csv",
        "telemetry_MACHINE_2026-03-01.csv",
    ]


def test_resolve_period_files_excludes_files_outside_range(two_month_pools):
    files = resolve_period_files(two_month_pools, start_date="2026-02-28", end_date="2026-03-01")
    names = {f.name for f in files}
    assert "telemetry_MACHINE_2026-02-27.csv" not in names
    assert "telemetry_MACHINE_2026-03-02.csv" not in names


def test_resolve_period_files_can_restrict_to_named_pools(two_month_pools):
    # Even though the full date range would include both pools, an
    # explicit pools=[...] list restricts the search.
    files = resolve_period_files(
        two_month_pools, pools=["2026-02"], start_date="2026-02-01", end_date="2026-03-31"
    )
    assert all("2026-02" in f.parent.name for f in files)
    assert len(files) == 2


def test_load_period_streaming_spans_pool_boundary(two_month_pools):
    events, idle_periods, meta = load_period_streaming(
        two_month_pools, start_date="2026-02-28", end_date="2026-03-01"
    )
    assert meta["n_files"] == 2
    assert not events.empty


def test_resolve_period_files_raises_for_empty_result(two_month_pools):
    with pytest.raises(FileNotFoundError):
        resolve_period_files(two_month_pools, start_date="2027-01-01", end_date="2027-01-31")
