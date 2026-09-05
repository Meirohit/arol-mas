"""
Loads one or more dataset "pools" (CSV/JSON/Parquet) and normalizes them
into a single, timestamp-sorted DataFrame with a consistent internal schema.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
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

# Real AROL exports are named e.g.
# telemetry_<machine_id>_2026-03-01.csv - this lets resolve_period_files()
# figure out which files fall in a requested date range from the
# filenames alone, without opening every file in every pool.
_FILENAME_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


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

    # Validate BEFORE sorting: validate_schema's "timestamp is not
    # monotonically increasing" check is only meaningful on the data in
    # the order it actually arrived in. Sorting first (as this function
    # used to) makes that check permanently vacuous - it can never fire,
    # since by the time it runs the data has already been reordered into
    # a monotonic sequence.
    problems = validate_schema(df, settings)
    df = df.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)

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


def _file_date(path: Path) -> date | None:
    """Best-effort: pull a YYYY-MM-DD out of the filename. Returns None if
    the filename doesn't contain one (e.g. the bundled sample_pool file) -
    such files are always included by resolve_period_files() rather than
    silently dropped, since we can't tell whether they're in range."""
    m = _FILENAME_DATE_RE.search(path.stem)
    if not m:
        return None
    try:
        return date.fromisoformat(m.group(1))
    except ValueError:
        return None


def resolve_period_files(
    settings: Settings,
    pools: List[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> List[Path]:
    """
    Resolves which files to load for a request scoped by date range
    rather than (or in addition to) a single pool name - this is what
    lets a query span across pool folders, e.g. "Feb 12 to March 15"
    when Feb and March live in separate pool directories
    (data/pools/2026-02/, data/pools/2026-03/).

    pools=None searches every pool directory under settings.pools_dir;
    pools=["2026-02", "2026-03"] restricts the search to just those.
    start_date/end_date are inclusive; either or both may be omitted to
    leave that side of the range open. Filtering is done from the
    filename's embedded date (see _file_date) without opening any file,
    so this is cheap even across a large number of pools/files. A file
    whose filename has no parseable date is always included, since we
    have no cheap way to know if it's in range - such files are rare
    (only the bundled synthetic sample_pool doesn't follow the dated
    naming convention).

    IMPORTANT: real AROL exports do NOT necessarily contain data for the
    calendar day named in the filename - a file named "..._2026-03-07.csv"
    was observed to actually contain rows from 2026-03-06 16:00 UTC
    through 2026-03-07 15:59:59 UTC (an offset shift-day/timezone
    convention in the source export), so the true tail of calendar
    2026-03-07 lives in the file named "..._2026-03-08.csv" instead. To
    guarantee full coverage of the requested calendar range regardless of
    this kind of offset, the filename-date search window below is widened
    by one day on each side; load_period_streaming then trims the
    resulting EVENTS (by their actual timestamp, not by which file they
    came from) back down to the exact requested
    [start_date 00:00, end_date 23:59:59] window - see its docstring.
    """
    if pools is None:
        pool_dirs = [settings.pools_dir / p for p in list_pools(settings)]
    else:
        pool_dirs = [settings.pools_dir / p for p in pools]
        missing = [d for d in pool_dirs if not d.exists()]
        if missing:
            raise FileNotFoundError(f"Dataset pool(s) not found: {[d.name for d in missing]}")

    start = date.fromisoformat(start_date) if start_date else None
    end = date.fromisoformat(end_date) if end_date else None
    # Widen by one day on each side - see the IMPORTANT note above.
    search_start = (start - timedelta(days=1)) if start is not None else None
    search_end = (end + timedelta(days=1)) if end is not None else None

    matched: List[Path] = []
    for pool_dir in pool_dirs:
        if not pool_dir.exists():
            continue
        for p in pool_dir.iterdir():
            if p.suffix.lower() not in _LOADERS:
                continue
            file_date = _file_date(p)
            if file_date is None:
                matched.append(p)
                continue
            if search_start is not None and file_date < search_start:
                continue
            if search_end is not None and file_date > search_end:
                continue
            matched.append(p)

    matched.sort(key=lambda p: (_file_date(p) or date.min, p.name))
    if not matched:
        raise FileNotFoundError(
            f"No files found for the requested period "
            f"(start_date={start_date}, end_date={end_date}, pools={pools or 'all'})."
        )
    return matched


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


def _validate_files(files: List[Path], settings: Settings) -> List[str]:
    """Shared core of validate_pool_files/validate_period_files: loads,
    checks, and discards each file in turn rather than concatenating the
    whole set into memory."""
    ts_col = settings.schema_.timestamp_col
    problems: List[str] = []
    for path in files:
        df = _load_single_file(path)
        df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce", utc=True)
        # Validate before sorting - see load_pool's comment on the same
        # pattern; sorting first makes the monotonicity check vacuous.
        for p in validate_schema(df, settings):
            problems.append(f"{path.name}: {p}")
        del df
    return problems


def validate_pool_files(settings: Settings, pool_name: str | None = None) -> List[str]:
    """
    Lightweight schema validation that never concatenates the whole pool
    into memory - it loads, checks, and discards each file in turn. Use
    this (not load_pool) for the `validate` CLI command, since a pool can
    hold weeks/months of daily files.
    """
    _, files = _pool_files(settings, pool_name)
    return _validate_files(files, settings)


def validate_period_files(
    settings: Settings, pools: List[str] | None = None, start_date: str | None = None, end_date: str | None = None
) -> List[str]:
    """Same as validate_pool_files, but scoped by date range (and
    optionally a list of pools) instead of a single pool name - see
    resolve_period_files."""
    files = resolve_period_files(settings, pools=pools, start_date=start_date, end_date=end_date)
    return _validate_files(files, settings)


def _stream_files(files: List[Path], settings: Settings, strict: bool, label: str) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Shared core of load_pool_streaming/load_period_streaming: processes
    files one at a time so a multi-month (or cross-pool, date-scoped)
    request never needs to hold more than one day's raw polling data in
    memory at once. See load_pool_streaming's docstring for the full
    rationale and the carry-row/carry-state mechanisms that keep
    closures and idle runs correct across file boundaries.
    """
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

        # Validate before sorting - see load_pool's identical comment;
        # the monotonicity check is meaningless once the rows have
        # already been reordered.
        for p in validate_schema(df, settings):
            quality_issues.append(f"{path.name}: {p}")

        df = df.dropna(subset=[ts_col]).sort_values(ts_col).reset_index(drop=True)

        total_raw_rows += len(df)

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
            f"{len(files)} file(s) in {label}:\n"
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
        "Streamed %s: %d files, %d raw rows total -> %d closure events, %d idle runs",
        label, len(files), total_raw_rows, len(events), len(idle_periods),
    )
    return events, idle_periods, meta


def load_pool_streaming(
    settings: Settings, pool_name: str | None = None, strict: bool = False
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Memory-bounded alternative to load_pool(), for pools that hold many
    large daily files (e.g. a full month or several months of AROL
    telemetry - each real day file is ~55-60 MB / 86,400 rows / 109
    columns; concatenating 3 months of those into one DataFrame before
    doing anything else, as load_pool() does, needs several GB of RAM).

    Instead, files are processed one at a time (see _stream_files):
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

    For a request scoped by date range instead of (or spanning) a single
    pool folder, use load_period_streaming instead.
    """
    pool_name, files = _pool_files(settings, pool_name)
    return _stream_files(files, settings, strict, label=f"pool '{pool_name}'")


def load_period_streaming(
    settings: Settings,
    pools: List[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    strict: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, dict]:
    """
    Same memory-bounded streaming as load_pool_streaming, but scoped by
    date range (via resolve_period_files) instead of a single pool name -
    this is what makes a request like "Feb 12 to March 15" work even
    though February and March live in separate pool directories: the
    file search spans every pool under settings.pools_dir (or just the
    ones named in `pools`, if given).

    Which FILES get read is decided by filename (widened by a day on
    each side - see resolve_period_files) rather than by opening every
    file to check its contents, since that's what keeps this cheap. But
    real AROL exports don't reliably put calendar day D's data entirely
    inside the file named for day D (observed: a file named for day D
    actually contains ~16:00 UTC day D-1 through ~15:59:59 UTC day D),
    so after streaming, the resulting EVENTS (and idle periods) are
    trimmed by their actual timestamp back down to the exact requested
    [start_date 00:00:00, end_date 23:59:59] window - this is what makes
    the answer calendar-exact rather than just "whichever files happened
    to be named close enough."
    """
    files = resolve_period_files(settings, pools=pools, start_date=start_date, end_date=end_date)
    label = f"period {start_date or '...'} to {end_date or '...'}" + (f" (pools={pools})" if pools else "")
    events, idle_periods, meta = _stream_files(files, settings, strict, label=label)

    if start_date is not None or end_date is not None:
        ts_field = closure_detection.ClosureEventColumns.timestamp
        start_ts = pd.Timestamp(start_date, tz="UTC") if start_date else None
        end_ts = (pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)) if end_date else None

        before = len(events)
        if not events.empty:
            # events[ts_field]'s dtype isn't guaranteed to be tz-aware
            # at this point (depends on how it flowed through
            # closure_detection/pd.concat), so force it explicitly
            # before comparing against the tz-aware start_ts/end_ts -
            # otherwise pandas raises on the comparison instead of
            # silently doing the wrong thing, which was actually useful
            # here: it's what caught this during testing.
            ts = pd.to_datetime(events[ts_field], utc=True)
            mask = pd.Series(True, index=events.index)
            if start_ts is not None:
                mask &= ts >= start_ts
            if end_ts is not None:
                mask &= ts <= end_ts
            events = events[mask].reset_index(drop=True)
        trimmed = before - len(events)

        if not idle_periods.empty:
            idle_ts = pd.to_datetime(idle_periods["start"], utc=True)
            if start_ts is not None:
                idle_periods = idle_periods[idle_ts >= start_ts]
                idle_ts = pd.to_datetime(idle_periods["start"], utc=True)
            if end_ts is not None:
                idle_periods = idle_periods[idle_ts <= end_ts]
            idle_periods = idle_periods.reset_index(drop=True)

        meta["trimmed_to_exact_range"] = True
        meta["events_trimmed_out"] = trimmed
        logger.info(
            "Trimmed to exact calendar range [%s, %s]: %d events removed (were outside the "
            "requested window despite being in a file whose name fell in range), %d remain",
            start_date, end_date, trimmed, len(events),
        )

    return events, idle_periods, meta