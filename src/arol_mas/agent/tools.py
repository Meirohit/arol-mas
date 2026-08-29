"""
Wraps the WP2 analytics functions as tools the report agent can call via
Claude's tool-use API. Each entry pairs:
  - a JSON schema describing the tool to the model
  - a Python callable that executes it against the already-loaded
    closure-events table / raw dataframe held by the AgentContext

Keeping this as a flat registry (not a class hierarchy) makes it trivial
to unit-test each tool function directly, independent of the LLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

import pandas as pd

from arol_mas.analytics import anomaly, correlation, idle, kpi, trend
from arol_mas.config import Settings


@dataclass
class AgentContext:
    """Bundles the data & config every tool needs, set once per report run."""
    raw_df: pd.DataFrame
    events: pd.DataFrame
    settings: Settings


def _df_to_records(obj: Any, limit: int = 200) -> Any:
    """
    Tool results must be JSON-serializable for the API, and small enough
    to not blow the request size limit. A raw dataset can have millions
    of closure events, so any DataFrame-returning tool is capped here:
    we send back a total row count plus a bounded sample, never the
    full table. Callers that need "how many" get an exact number either
    way; callers that need "show me examples" get up to `limit` rows.
    """
    if isinstance(obj, pd.DataFrame):
        total = len(obj)
        sample = obj.head(limit).to_dict(orient="records")
        if total <= limit:
            return sample
        return {
            "total_rows": total,
            "returned_rows": limit,
            "note": f"Result truncated to the first {limit} of {total} rows - use aggregate/summary tools for full-dataset questions.",
            "rows": sample,
        }
    return obj


# --- tool implementations (thin wrappers around analytics/*) ---------------

def _tool_overall_success_rate(ctx: AgentContext, **_kwargs) -> dict:
    return kpi.overall_success_rate(ctx.events)


def _tool_success_rate_per_head(ctx: AgentContext, **_kwargs) -> Any:
    return _df_to_records(kpi.success_rate_per_head(ctx.events))


def _tool_torque_statistics(ctx: AgentContext, successful_only: bool = True, **_kwargs) -> dict:
    return kpi.torque_statistics(ctx.events, successful_only=successful_only)


def _tool_torque_statistics_per_head(ctx: AgentContext, successful_only: bool = True, **_kwargs) -> Any:
    return _df_to_records(kpi.torque_statistics_per_head(ctx.events, successful_only=successful_only))


def _tool_failed_vs_successful_torque(ctx: AgentContext, **_kwargs) -> dict:
    return kpi.failed_vs_successful_torque(ctx.events)


def _tool_time_range(ctx: AgentContext, **_kwargs) -> dict:
    return kpi.time_range(ctx.events)


def _tool_torque_moving_average(ctx: AgentContext, head_id: str | None = None, **_kwargs) -> Any:
    return _df_to_records(trend.torque_moving_average(ctx.events, ctx.settings, head_id=head_id))


def _tool_detect_drift(ctx: AgentContext, **_kwargs) -> Any:
    return _df_to_records(trend.detect_drift(ctx.events, ctx.settings))


def _tool_success_rate_over_time(ctx: AgentContext, freq: str = "1D", **_kwargs) -> Any:
    return _df_to_records(trend.success_rate_over_time(ctx.events, freq=freq))


def _tool_out_of_range_torque(ctx: AgentContext, exclude_zero_torque: bool = True, **_kwargs) -> Any:
    return _df_to_records(anomaly.out_of_range_torque(ctx.events, ctx.settings, exclude_zero_torque=exclude_zero_torque))


def _tool_zero_torque_summary(ctx: AgentContext, **_kwargs) -> dict:
    return anomaly.zero_torque_summary(ctx.events)


def _tool_statistical_outliers(ctx: AgentContext, z_threshold: float = 3.0, **_kwargs) -> Any:
    return _df_to_records(anomaly.statistical_outliers(ctx.events, z_threshold=z_threshold))


def _tool_head_with_most_failures(ctx: AgentContext, **_kwargs) -> dict:
    return anomaly.head_with_most_failures(ctx.events)


def _tool_fault_code_breakdown(ctx: AgentContext, **_kwargs) -> Any:
    return anomaly.fault_code_breakdown(ctx.events)


def _tool_torque_status_consistency_check(ctx: AgentContext, **_kwargs) -> dict:
    return anomaly.torque_status_consistency_check(ctx.events)


def _tool_torque_correlation_between_heads(ctx: AgentContext, head_a: str, head_b: str, **_kwargs) -> dict:
    return correlation.torque_correlation_between_heads(ctx.events, head_a, head_b, ctx.settings)


def _tool_torque_vs_success_correlation(ctx: AgentContext, **_kwargs) -> dict:
    return correlation.torque_vs_success_correlation(ctx.events)


def _tool_rank_heads_by_deviation(ctx: AgentContext, **_kwargs) -> Any:
    return _df_to_records(correlation.rank_heads_by_deviation(ctx.events))


def _tool_detect_idle_periods(ctx: AgentContext, **_kwargs) -> Any:
    return _df_to_records(idle.detect_idle_periods(ctx.raw_df, ctx.settings))


# --- registry ----------------------------------------------------------

TOOL_SPECS: list[Dict[str, Any]] = [
    {
        "name": "overall_success_rate",
        "description": "Total closure events, successes, failures, and overall success rate percentage.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "success_rate_per_head",
        "description": "Success rate broken down by capping head, sorted ascending (worst first).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "torque_statistics",
        "description": "Mean/min/max/std of closing torque, overall.",
        "input_schema": {
            "type": "object",
            "properties": {
                "successful_only": {"type": "boolean", "description": "Restrict to successful closures (default true)."}
            },
        },
    },
    {
        "name": "torque_statistics_per_head",
        "description": "Mean/min/max/std of closing torque, broken down per head.",
        "input_schema": {
            "type": "object",
            "properties": {
                "successful_only": {"type": "boolean"}
            },
        },
    },
    {
        "name": "failed_vs_successful_torque",
        "description": "Compares torque statistics between failed and successful closures.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "time_range",
        "description": "Start and end timestamp covered by the loaded dataset.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "torque_moving_average",
        "description": "Rolling mean of torque over successive closures, to visualize slow drift.",
        "input_schema": {
            "type": "object",
            "properties": {
                "head_id": {"type": "string", "description": "Optional single head id, e.g. 'H03'."}
            },
        },
    },
    {
        "name": "detect_drift",
        "description": "Flags heads whose recent torque mean has drifted from their own historical baseline (z-score based).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "success_rate_over_time",
        "description": "Success rate broken down by time period, e.g. daily.",
        "input_schema": {
            "type": "object",
            "properties": {
                "freq": {"type": "string", "description": "Pandas offset alias, e.g. '1D', '1H'. Default '1D'."}
            },
        },
    },
    {
        "name": "out_of_range_torque",
        "description": "Lists individual closures with torque outside the configured expected operating range. Returns a capped sample with a total count, not every row - use zero_torque_summary or statistical_outliers for aggregate/fleet-wide questions on large datasets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "exclude_zero_torque": {
                    "type": "boolean",
                    "description": "Default true. Zero-torque readings are usually 'No Load' cycles, not faults - set false to include them in this range check."
                }
            },
        },
    },
    {
        "name": "zero_torque_summary",
        "description": "Aggregate count and per-head percentage of zero-torque closure events. Always small regardless of dataset size - use this (not out_of_range_torque) to answer 'are there zero torque events' or 'how common are zero-torque readings' for large datasets.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "statistical_outliers",
        "description": "Per-head torque outliers based on z-score threshold.",
        "input_schema": {
            "type": "object",
            "properties": {
                "z_threshold": {"type": "number", "description": "Default 3.0"}
            },
        },
    },
    {
        "name": "head_with_most_failures",
        "description": "Identifies which head contributes the most reject_signal=YES (genuine quality failure) closures.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "fault_code_breakdown",
        "description": "Distribution of every non-success, non-no-load status code seen in the data, with AROL's own description and reject_signal for each - use for 'what kinds of errors are occurring' questions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "torque_status_consistency_check",
        "description": "Cross-checks the No Load status flag against the raw torque reading - flags cases where the two disagree (data-quality diagnostic, not a production KPI).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "torque_correlation_between_heads",
        "description": "Correlation of torque time series between two named heads.",
        "input_schema": {
            "type": "object",
            "properties": {
                "head_a": {"type": "string"},
                "head_b": {"type": "string"},
            },
            "required": ["head_a", "head_b"],
        },
    },
    {
        "name": "torque_vs_success_correlation",
        "description": "Correlation between torque value and closure success/failure.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "rank_heads_by_deviation",
        "description": "Ranks heads by how much they deviate from the fleet average on torque and success rate - use to answer 'which head behaves differently?'",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "detect_idle_periods",
        "description": "Lists sustained 'No Load' idle periods per head.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

_TOOL_IMPLS: Dict[str, Callable[..., Any]] = {
    "overall_success_rate": _tool_overall_success_rate,
    "success_rate_per_head": _tool_success_rate_per_head,
    "torque_statistics": _tool_torque_statistics,
    "torque_statistics_per_head": _tool_torque_statistics_per_head,
    "failed_vs_successful_torque": _tool_failed_vs_successful_torque,
    "time_range": _tool_time_range,
    "torque_moving_average": _tool_torque_moving_average,
    "detect_drift": _tool_detect_drift,
    "success_rate_over_time": _tool_success_rate_over_time,
    "out_of_range_torque": _tool_out_of_range_torque,
    "zero_torque_summary": _tool_zero_torque_summary,
    "statistical_outliers": _tool_statistical_outliers,
    "head_with_most_failures": _tool_head_with_most_failures,
    "fault_code_breakdown": _tool_fault_code_breakdown,
    "torque_status_consistency_check": _tool_torque_status_consistency_check,
    "torque_correlation_between_heads": _tool_torque_correlation_between_heads,
    "torque_vs_success_correlation": _tool_torque_vs_success_correlation,
    "rank_heads_by_deviation": _tool_rank_heads_by_deviation,
    "detect_idle_periods": _tool_detect_idle_periods,
}


def run_tool(name: str, tool_input: Dict[str, Any], ctx: AgentContext) -> Any:
    if name not in _TOOL_IMPLS:
        raise KeyError(f"Unknown tool '{name}'")
    return _TOOL_IMPLS[name](ctx, **tool_input)
