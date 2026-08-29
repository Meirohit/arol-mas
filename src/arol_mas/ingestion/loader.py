"""
Loads one or more dataset "pools" (CSV/JSON/Parquet) and normalizes them
into a single, timestamp-sorted DataFrame with a consistent internal schema.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import pandas as pd

from arol_mas.config import Settings
from arol_mas.ingestion.schema import validate_schema

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
