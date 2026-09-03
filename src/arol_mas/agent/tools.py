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

from arol_mas.analytics import anomaly, correlation, filters, kpi, plotting, trend
from arol_mas.config import Settings
from arol_mas.ingestion.closure_detection import ClosureEventColumns as _EventCols


@dataclass
class AgentContext:
    """
    Bundles the data & config every tool needs, set once per report run.

    Note there is no raw wide-format polling DataFrame here on purpose:
    for a multi-day/multi-month pool that raw data can be several GB, so
    loader.load_pool_streaming() extracts everything a tool could need
    from it (closure events, idle periods, data-quality issues) one file
    at a time and discards the raw rows immediately after - see
    loader.py for why. idle_periods and data_quality_issues below are
    that precomputed output, not raw data.
    """
    events: pd.DataFrame
    settings: Settings
    idle_periods: pd.DataFrame = None
    data_quality_issues: list = None

    def __post_init__(self):
        if self.idle_periods is None:
            self.idle_periods = pd.DataFrame(columns=["head_id", "start", "end", "duration_s"])
        if self.data_quality_issues is None:
            self.data_quality_issues = []


def _scope_events(events: pd.DataFrame, start_date: str | None, end_date: str | None) -> pd.DataFrame:
    """
    Restricts the FULL events table (every column, not just the reduced
    set list_closure_events returns) to a date/time range, for tools like
    success_rate_over_time and torque_moving_average that need to run
    their own aggregation logic on a sub-period rather than a flat list
    of rows. See filters.list_closure_events for the exact semantics of
    start_date/end_date (end_date is inclusive through end-of-day when
    no time-of-day is given).
    """
    if start_date is None and end_date is None:
        return events
    ts = pd.to_datetime(events[_EventCols.timestamp])
    if start_date is not None:
        start_ts = pd.Timestamp(start_date)
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize("UTC")
        events = events[ts >= start_ts]
        ts = pd.to_datetime(events[_EventCols.timestamp])
    if end_date is not None:
        end_ts = pd.Timestamp(end_date)
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize("UTC")
        if end_ts.time() == pd.Timestamp("2000-01-01").time():
            end_ts = end_ts + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        events = events[ts <= end_ts]
    return events


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


def _tool_torque_moving_average(
    ctx: AgentContext, head_id: str | None = None, start_date: str | None = None, end_date: str | None = None, **_kwargs
) -> Any:
    return _df_to_records(
        trend.torque_moving_average(_scope_events(ctx.events, start_date, end_date), ctx.settings, head_id=head_id)
    )


def _tool_detect_drift(ctx: AgentContext, **_kwargs) -> Any:
    return _df_to_records(trend.detect_drift(ctx.events, ctx.settings))


def _tool_success_rate_over_time(
    ctx: AgentContext, freq: str = "1D", start_date: str | None = None, end_date: str | None = None, **_kwargs
) -> Any:
    return _df_to_records(trend.success_rate_over_time(_scope_events(ctx.events, start_date, end_date), freq=freq))


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
    return _df_to_records(ctx.idle_periods)


def _tool_success_rate_by_hour_of_day(ctx: AgentContext, **_kwargs) -> Any:
    return _df_to_records(trend.success_rate_by_hour_of_day(ctx.events))


def _tool_capping_speed_summary(ctx: AgentContext, **_kwargs) -> Any:
    return trend.capping_speed_summary(ctx.events)


def _tool_capping_speed_over_time(ctx: AgentContext, freq: str = "1D", **_kwargs) -> Any:
    return _df_to_records(trend.capping_speed_over_time(ctx.events, freq=freq))


def _tool_list_closure_events(
    ctx: AgentContext,
    head_id: str | None = None,
    status_category: str | None = None,
    torque_min: float | None = None,
    torque_max: float | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    **_kwargs,
) -> Any:
    return _df_to_records(
        filters.list_closure_events(
            ctx.events, head_id=head_id, status_category=status_category,
            torque_min=torque_min, torque_max=torque_max,
            start_date=start_date, end_date=end_date,
        )
    )


def _tool_dataset_quality_summary(ctx: AgentContext, **_kwargs) -> dict:
    issues = ctx.data_quality_issues or []
    return {
        "total_issues": len(issues),
        "issues": issues[:50],
        "note": "Truncated to first 50." if len(issues) > 50 else None,
    }


def _tool_plot_torque_over_time(ctx: AgentContext, head_id: str | None = None, **_kwargs) -> dict:
    return plotting.plot_torque_over_time(ctx.events, ctx.settings, head_id=head_id)


def _tool_plot_torque_histogram(ctx: AgentContext, successful_only: bool = True, **_kwargs) -> dict:
    return plotting.plot_torque_histogram(ctx.events, ctx.settings, successful_only=successful_only)


def _tool_plot_success_rate_per_head(ctx: AgentContext, **_kwargs) -> dict:
    return plotting.plot_success_rate_per_head(ctx.events, ctx.settings)


def _tool_plot_failed_closures_over_time(ctx: AgentContext, freq: str = "1D", **_kwargs) -> dict:
    return plotting.plot_failed_closures_over_time(ctx.events, ctx.settings, freq=freq)


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
        "description": "Rolling mean of torque over successive closures, to visualize slow drift. Optionally scoped to a date/time range.",
        "input_schema": {
            "type": "object",
            "properties": {
                "head_id": {"type": "string", "description": "Optional single head id, e.g. 'H03'."},
                "start_date": {"type": "string", "description": "Optional ISO date/datetime. Inclusive."},
                "end_date": {"type": "string", "description": "Optional ISO date/datetime. If only a date (no time), inclusive through end of that day."},
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
        "description": "Success rate broken down by time period, e.g. daily. Optionally scoped to a date/time range, e.g. 'daily breakdown for the first week' or 'success rate on March 5th'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "freq": {"type": "string", "description": "Pandas offset alias, e.g. '1D', '1H'. Default '1D'."},
                "start_date": {"type": "string", "description": "Optional ISO date/datetime. Inclusive."},
                "end_date": {"type": "string", "description": "Optional ISO date/datetime. If only a date (no time), inclusive through end of that day."},
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
    {
        "name": "success_rate_by_hour_of_day",
        "description": "Success rate pooled by hour-of-day (0-23) across every day in the dataset - use for 'is there a correlation between time of day and failure probability?' (success_rate_over_time groups by calendar day/period instead and cannot show this).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "capping_speed_summary",
        "description": "Overall capping speed in pieces/hour for the scoped period, using an incremental (expanding) average across all closure events - use for 'what is the capping speed / throughput / production rate'. Counts every closure event across all heads, including No Load cycles, since this is about machine cycle rate, not quality.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "capping_speed_over_time",
        "description": "Capping speed (pieces/hour) broken down by time period, e.g. daily - use for 'how did throughput/speed change over time' rather than a single overall figure.",
        "input_schema": {
            "type": "object",
            "properties": {"freq": {"type": "string", "description": "Pandas offset alias, e.g. '1D', '1H'. Default '1D'."}},
        },
    },
    {
        "name": "list_closure_events",
        "description": "Lists individual closure events filtered by any combination of head, status category (success/no_load/reject/fault), torque range, and date/time range. Use for ad-hoc filtering questions like 'show all failed closures for head 3' or 'how many closures had torque above X Nm' that don't match a more specific tool. Returns a capped sample with a total count for large results, like every other listing tool. IMPORTANT: for any question scoped to a specific day, week, or date range (e.g. 'last week', 'March 5-10', 'the first week of the dataset'), you MUST pass start_date/end_date - without them the capped sample returns only the EARLIEST-timestamped rows from the WHOLE dataset, silently giving a wrong answer for anything not near the very start.",
        "input_schema": {
            "type": "object",
            "properties": {
                "head_id": {"type": "string", "description": "e.g. 'H03'"},
                "status_category": {"type": "string", "enum": ["success", "no_load", "reject", "fault"]},
                "torque_min": {"type": "number"},
                "torque_max": {"type": "number"},
                "start_date": {"type": "string", "description": "ISO date/datetime, e.g. '2026-03-05' or '2026-03-05T14:00:00Z'. Inclusive."},
                "end_date": {"type": "string", "description": "ISO date/datetime. If only a date (no time) is given, inclusive through the END of that day."},
            },
        },
    },
    {
        "name": "dataset_quality_summary",
        "description": "Schema-validation issues found while loading the dataset (missing values, negative/zero torque readings, out-of-order or decreasing counters), collected once at load time across every file in the pool - use for 'are there any missing or invalid values' questions.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "plot_torque_over_time",
        "description": "Generates and saves a scatter plot of closing torque over time for successful closures, optionally for a single head. Returns the saved PNG path - reference it in the report so the user knows where to find it.",
        "input_schema": {
            "type": "object",
            "properties": {"head_id": {"type": "string", "description": "Optional single head id, e.g. 'H03'."}},
        },
    },
    {
        "name": "plot_torque_histogram",
        "description": "Generates and saves a histogram of closing torque values. Returns the saved PNG path.",
        "input_schema": {
            "type": "object",
            "properties": {"successful_only": {"type": "boolean", "description": "Default true."}},
        },
    },
    {
        "name": "plot_success_rate_per_head",
        "description": "Generates and saves a bar chart of success rate per head. Returns the saved PNG path.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "plot_failed_closures_over_time",
        "description": "Generates and saves a bar chart of rejected-closure counts over time (daily by default). Returns the saved PNG path.",
        "input_schema": {
            "type": "object",
            "properties": {"freq": {"type": "string", "description": "Pandas offset alias, e.g. '1D', '1H'. Default '1D'."}},
        },
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
    "success_rate_by_hour_of_day": _tool_success_rate_by_hour_of_day,
    "capping_speed_summary": _tool_capping_speed_summary,
    "capping_speed_over_time": _tool_capping_speed_over_time,
    "list_closure_events": _tool_list_closure_events,
    "dataset_quality_summary": _tool_dataset_quality_summary,
    "plot_torque_over_time": _tool_plot_torque_over_time,
    "plot_torque_histogram": _tool_plot_torque_histogram,
    "plot_success_rate_per_head": _tool_plot_success_rate_per_head,
    "plot_failed_closures_over_time": _tool_plot_failed_closures_over_time,
}


def run_tool(name: str, tool_input: Dict[str, Any], ctx: AgentContext) -> Any:
    if name not in _TOOL_IMPLS:
        raise KeyError(f"Unknown tool '{name}'")
    return _TOOL_IMPLS[name](ctx, **tool_input)