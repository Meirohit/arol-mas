"""
Loads one or more dataset "pools" (CSV/JSON/Parquet) and normalizes them
into a single, timestamp-sorted DataFrame with a consistent internal schema.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import pandas as pd

from arol_mas.config import Settings
from arol_mas.ingestion.schema import all_head_columns, validate_schema
from arol_mas.ingestion import closure_detection
from arol_mas.analytics import idle as idle_mod

logger = logging.getLogger(__name__)

_LOADERS = {
    ".csv": pd.read_csv,
    ".json": pd.read_json,
    ".parquet": pd.read_parquet,
}


def _load_single_file(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix not in _LOADERS:
        raise ValueError(
            f"Unsupported file type '{suffix}' for {path}. "
            f"Supported: {list(_LOADERS)}"
        )
    logger.info("Loading %s", path)
    return _LOADERS[suffix](path)


def load_pool(settings: Settings, pool_name: str | None = None, strict: bool = False) -> pd.DataFrame:
    """
    Load every supported file inside `pools_dir/pool_name/`, concatenate,
    sort by timestamp, and run schema validation.

    strict=True raises on validation problems instead of just logging them.
    """
    pool_name = pool_name or settings.data.default_pool
    pool_dir = settings.pools_dir / pool_name
    if not pool_dir.exists():
        raise FileNotFoundError(
            f"Dataset pool '{pool_name}' not found at {pool_dir}. "
            f"Check config.data.pools_dir / data.default_pool."
        )

    files = sorted(
        p for p in pool_dir.iterdir() if p.suffix.lower() in _LOADERS
    )
    if not files:
        raise FileNotFoundError(f"No supported data files found in {pool_dir}")

    frames: List[pd.DataFrame] = [_load_single_file(p) for p in files]
    df = pd.concat(frames, ignore_index=True)

    ts_col = settings.schema_.timestamp_col
    df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
    df = df.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)

    problems = validate_schema(df, settings)
    if problems:
        msg = f"Schema validation found {len(problems)} issue(s) in pool '{pool_name}':\n" + "\n".join(
            f"  - {p}" for p in problems
        )
        if strict:
            raise ValueError(msg)
        logger.warning(msg)

    logger.info("Loaded pool '%s': %d rows, %d files", pool_name, len(df), len(files))
    return df


def list_pools(settings: Settings) -> List[str]:
    if not settings.pools_dir.exists():
        return []
    return sorted(p.name for p in settings.pools_dir.iterdir() if p.is_dir())


def _pool_files(settings: Settings, pool_name: str | None) -> Tuple[str, List[Path]]:
    pool_name = pool_name or settings.data.default_pool
    pool_dir = settings.pools_dir / pool_name
    if not pool_dir.exists():
        raise FileNotFoundError(
            f"Dataset pool '{pool_name}' not found at {pool_dir}. "
            f"Check config.data.pools_dir / data.default_pool."
        )
    files = sorted(p for p in pool_dir.iterdir() if p.suffix.lower() in _LOADERS)
    if not files:
        raise FileNotFoundError(f"No supported data files found in {pool_dir}")
    return pool_name, files


def _optimize_dtypes(df: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """
    Downcasts the wide per-head columns (float64 -> float32,
    int64 -> the smallest integer type that fits) in place. This roughly
    halves the in-memory footprint of each day's raw file, which matters
    once a pool holds a full month (or several months) of daily files
    and load_pool_streaming processes them one at a time.
    """
    for hc in all_head_columns(settings):
        if hc.torque_col in df.columns:
            df[hc.torque_col] = pd.to_numeric(df[hc.torque_col], errors="coerce", downcast="float")
        if hc.status_col in df.columns:
            df[hc.status_col] = pd.to_numeric(df[hc.status_col], errors="coerce", downcast="integer")
        if hc.count_col in df.columns:
            df[hc.count_col] = pd.to_numeric(df[hc.count_col], errors="coerce", downcast="integer")
    return df


def validate_pool_files(settings: Settings, pool_name: str | None = None) -> List[str]:
    """
    Lightweight schema validation that never concatenates the whole pool
    into memory - it loads, checks, and discards each file in turn. Use
    this (not load_pool) for the `validate` CLI command, since a pool can
    hold weeks/months of daily files.
    """
    pool_name, files = _pool_files(settings, pool_name)
    ts_col = settings.schema_.timestamp_col
    problems: List[str] = []

    for path in files:
        df = _load_single_file(path)
        df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
        df = df.sort_values(ts_col).reset_index(drop=True)
        for p in validate_schema(df, settings):
            problems.append(f"{path.name}: {p}")
        del df

    return problems


def load_pool_streaming(
    settings: Settings, pool_name: str | None = None, strict: bool = False
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Memory-bounded alternative to load_pool(), for pools that hold many
    large daily files (e.g. a full month or several months of AROL
    telemetry - each real day file is ~55-60 MB / 86,400 rows / 109
    columns; concatenating 3 months of those into one DataFrame before
    doing anything else, as load_pool() does, needs several GB of RAM).

    Instead, files are processed one at a time:
      - each file's raw rows are used to detect closure events and idle
        periods (both of which are orders of magnitude smaller than the
        raw polling data - a day of 86,400 polling rows typically
        collapses to a few thousand real closure events per head), and
      - the raw file is then discarded before the next one is loaded.

    A single-row "tail" is carried from each file into the next so that a
    closure or idle run that happens to span a file boundary (e.g.
    midnight between two daily files) is still detected/merged correctly
    instead of being missed or double-counted - see
    closure_detection.detect_closures (diff against the carried-in row)
    and idle.detect_idle_periods_chunk (explicit open-run carry state).

    Returns (events_df, idle_periods_df, meta) where meta contains
    {"n_files", "total_raw_rows", "quality_issues"} - quality_issues is
    the same list validate_pool_files() would return, collected for free
    along the way so the agent can answer "were there missing/invalid
    values" without a second pass over the data.
    """
    pool_name, files = _pool_files(settings, pool_name)
    ts_col = settings.schema_.timestamp_col

    event_frames: List[pd.DataFrame] = []
    idle_frames: List[pd.DataFrame] = []
    open_idle_runs: dict = {}
    carry_tail: pd.DataFrame | None = None
    quality_issues: List[str] = []
    total_raw_rows = 0

    for path in files:
        df = _load_single_file(path)
        df = _optimize_dtypes(df, settings)
        df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
        df = df.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)

        for p in validate_schema(df, settings):
            quality_issues.append(f"{path.name}: {p}")

        total_raw_rows += len(df)

        # Prepend the previous file's last row so the Count diff at the
        # very first row of this file is still computed against the
        # correct prior value (see closure_detection.detect_closures -
        # its own first row always gets a NaN diff and is never itself
        # reported as a closure, so this never double-counts the carry
        # row's own event).
        chunk = pd.concat([carry_tail, df], ignore_index=True) if carry_tail is not None else df
        event_frames.append(closure_detection.detect_closures(chunk, settings))

        idle_chunk, open_idle_runs = idle_mod.detect_idle_periods_chunk(df, settings, open_idle_runs)
        if not idle_chunk.empty:
            idle_frames.append(idle_chunk)

        carry_tail = df.tail(1)
        del df, chunk
        logger.info("Streamed %s (%d raw rows so far)", path.name, total_raw_rows)

    final_idle = idle_mod.flush_open_idle_runs(open_idle_runs, settings)
    if not final_idle.empty:
        idle_frames.append(final_idle)

    if quality_issues:
        msg = (
            f"Schema validation found {len(quality_issues)} issue(s) across "
            f"{len(files)} file(s) in pool '{pool_name}':\n"
            + "\n".join(f"  - {p}" for p in quality_issues[:50])
            + ("\n  ... (truncated)" if len(quality_issues) > 50 else "")
        )
        if strict:
            raise ValueError(msg)
        logger.warning(msg)

    ts_field = closure_detection.ClosureEventColumns.timestamp
    non_empty_events = [f for f in event_frames if not f.empty]
    events = (
        pd.concat(non_empty_events, ignore_index=True).sort_values(ts_field).reset_index(drop=True)
        if non_empty_events else pd.DataFrame()
    )
    idle_periods = (
        pd.concat(idle_frames, ignore_index=True) if idle_frames
        else pd.DataFrame(columns=["head_id", "start", "end", "duration_s"])
    )

    meta = {"n_files": len(files), "total_raw_rows": total_raw_rows, "quality_issues": quality_issues}
    logger.info(
        "Streamed pool '%s': %d files, %d raw rows total -> %d closure events, %d idle runs",
        pool_name, len(files), total_raw_rows, len(events), len(idle_periods),
    )
    return events, idle_periods, meta
