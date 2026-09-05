# AROL Telemetry Report Agent — Architecture

This is the standalone technical documentation requested by AROL's deliverables
slide (p.11: "Technical documentation: architecture, data schema, analytics
methods, agent decision flow"). It is referenced from
`src/arol_mas/ingestion/closure_detection.py`'s module docstring and expands on
the summary in `README.txt`.

## 1. System architecture

```
                    data/pools/<name>/*.csv
                            |
                            v
      +----------------------------------------------+
      |  WP1 - src/arol_mas/ingestion/                |
      |  loader.py: streams one file at a time         |
      |    -> schema.py: per-file validation            |
      |    -> closure_detection.py: Count-delta diff     |
      |       (carry-row across file boundaries)          |
      |    -> analytics/idle.py: idle-run detection        |
      |       (carry-state across file boundaries)           |
      +----------------------------------------------+
                            |
                events DataFrame + idle_periods DataFrame
                            |
                            v
      +----------------------------------------------+
      |  WP2 - src/arol_mas/analytics/                 |
      |  kpi / trend / anomaly / correlation / plotting  |
      |  - pure functions: DataFrame in -> dict/DataFrame |
      |    or dict out. No LLM involved. Every number a    |
      |    report cites traces back to exactly one of these |
      +----------------------------------------------+
                            |
                registered as tools in agent/tools.py
                            |
                            v
      +----------------------------------------------+
      |  WP3 - src/arol_mas/agent/                     |
      |  orchestrator.py: Claude tool-use loop            |
      |    system prompt -> user query -> Claude picks     |
      |    tool(s) -> tool result fed back -> repeat until  |
      |    Claude writes the final structured report text    |
      |  report_writer.py: renders report.md.j2, saves it,    |
      |    embeds any plot_path as a Markdown image             |
      +----------------------------------------------+
                            |
                            v
      +----------------------------------------------+
      |  WP4 - src/arol_mas/cli/main.py (+ webapi/)    |
      |  typer commands: ask / report / validate /        |
      |  list-pools. Resolves --pool vs --date vs           |
      |  --start-date/--end-date into a file list, builds     |
      |  an AgentContext, runs the agent, saves + prints        |
      |  the report. webapi/server.py exposes the same flow      |
      |  over REST for the React frontend in webapp/.              |
      +----------------------------------------------+
```

### Why ingestion is split from analytics

WP1 never touches the LLM and WP2 never touches raw files — `events` (one row
per real closure) and `idle_periods` are the only handoff between them. This
split is what makes the deterministic layer testable in isolation (see
`tests/test_kpi.py`, `test_closure_detection.py`, `test_schema_validation.py`,
etc. — none of them need an API key) and is why the agent's outputs are
reproducible: given the same `events` table, every tool call returns the exact
same number every time, regardless of what the LLM decides to ask for.

## 2. Data schema

**Raw input** (`data/pools/<name>/*.csv|json|parquet`): one row per poll, one
`timestamp` column, and per head (`H01`…`H36`) three columns —
`{head} AppTorque`, `{head} Status`, `{head} Count`. Column suffixes are
configurable via `config.yaml`'s `schema:` section, not hard-coded. See
README.txt section 4 for the full column reference and the real AROL sample
file's exact shape (690 rows × 109 columns × 36 heads).

**Internal `events` schema** (one row per REAL closure, not per poll) —
`ClosureEventColumns` in `ingestion/closure_detection.py`:

| column               | meaning                                                            |
|----------------------|---------------------------------------------------------------------|
| `event_timestamp`    | poll timestamp at which the Count increase was observed            |
| `head_id`            | e.g. `H01`                                                          |
| `torque`             | AppTorque value live on that poll                                   |
| `status`             | raw status code live on that poll                                    |
| `success`            | `True` only for status 0 ("Closure OK")                              |
| `is_no_load`         | `True` only for status 2 ("No Load")                                  |
| `is_reject`          | `True` for any `reject_signal == YES` status                          |
| `is_fault`           | `True` for `reject_signal == NO`, non-success, non-No-Load status       |
| `status_category`    | one of `success` / `no_load` / `reject` / `fault` / `unknown`           |
| `status_description` | AROL's human-readable description of the status code                    |
| `count`              | the head's Count value at that closure                                   |
| `count_seq_gap`      | `count.diff()` at detection time; >1 means the polling interval missed intermediate closures for that head (logged, never fabricated) |

`idle_periods` (from `analytics/idle.py`): one row per contiguous "No Load" run
per head lasting at least `analytics.idle_no_load_seconds`, with `head_id`,
`start`, `end`, `duration_s`.

## 3. Analytics methods (WP2)

- **kpi.py** — success/reject/fault counts and rates, overall and per-head;
  torque mean/min/max/std, overall and per-head. **No Load closures are
  excluded from every success/reject-rate denominator** (they are not capping
  attempts) — this is the single most important convention in the whole
  analytics layer; every other module follows it.
- **trend.py** — rolling torque average (per head, over successive closures);
  z-score drift detection (first-half vs second-half baseline, per head);
  success rate and capping speed bucketed by calendar period or by
  hour-of-day; capping speed via AROL's requested incremental/expanding
  average of inter-closure time deltas (slide 5), computed across all heads
  and all statuses (a machine-cycle-rate metric, not a quality metric).
- **anomaly.py** — fixed-range and zero-torque flags; per-head z-score
  statistical outliers; which head has the most genuine rejects; fault-code
  breakdown; a torque-vs-status consistency check (do "No Load" and
  "~zero torque" actually agree with each other on this dataset?).
- **correlation.py** — torque correlation between two named heads (aligned by
  closure index, since heads don't share identical timestamps, not by
  timestamp — see §6 for the documented trade-off); torque-vs-success
  correlation; per-head deviation ranking from the fleet average.
- **filters.py** — generic event listing/filtering by head, status category,
  torque range, and/or date range — the catch-all for ad-hoc questions that
  don't match a dedicated tool.
- **plotting.py** — matplotlib PNGs (torque over time, torque histogram,
  success rate per head, failed closures over time), saved under
  `reports/plots/` and returned as a path for the report to embed. Satisfies
  the OBJECTIVE slide's "reports + plots/tables where relevant" requirement.

All of WP2 is pure functions (DataFrame in → dict/DataFrame out), independent
of the LLM, and unit-tested directly (see `tests/`).

## 4. Agent decision flow (WP3)

For a single `ask` / `report` call:

1. **CLI/web API resolves scope → events.** Decides between `--pool` (one
   folder) and `--date`/`--start-date`/`--end-date` (a period, possibly
   spanning multiple pool folders — see `loader.resolve_period_files`),
   builds the file list, streams it, and produces the `events` +
   `idle_periods` tables. 100% deterministic, no LLM call.
2. **Claude receives the query + tool list.** `orchestrator.py` sends the
   user's question, a system prompt (status-code terminology, pipeline
   internals for meta-questions, and guidance on which tools are safe for
   fleet-wide vs single-head/day questions — see §5), and the full
   `TOOL_SPECS` schema (28 tools) to the model.
3. **Claude calls zero or more tools, in a loop** (capped at
   `agent.max_tool_iterations`, default 6). Each call goes through
   `run_tool()` in `tools.py`, dispatching to the matching analytics function
   against the `AgentContext`. Results are fed back to Claude, which can call
   more tools based on what it learned (e.g. `success_rate_per_head` →
   spot an outlier head → `torque_statistics_per_head` filtered to that head).
4. **Claude writes the final report** in the fixed structure AROL's brief
   requires (p.7): `Goal → Data used → Analyses executed → Findings →
   Confidence & limits → Next checks`. It is instructed to use only numbers
   tools actually returned and to embed any `plot_path` as a Markdown image.
5. **`report_writer.py` renders and saves** the report via `report.md.j2`,
   including the full tool-call trace, so any report is auditable after the
   fact — every number can be traced back to the exact tool call that
   produced it.

### Graceful failure

If a tool call raises, the orchestrator logs the exception and returns an
`{"error": ...}` tool result instead of crashing the run; Claude is instructed
to note the gap in Confidence & Limits rather than fabricate a number.

## 5. Known correctness issues found and fixed (project audit)

A full audit of the codebase (2026-09) found and fixed three real defects,
none of which were caught by the existing 43-test suite (now 50, with
regression tests added for the two schema bugs):

1. **False-positive "invalid torque" flood.** `schema.validate_schema()`
   used to flag *every* zero-torque reading as a data-quality problem, even
   though zero torque is normal and expected during "No Load" (status 2)
   cycles — which is the *dominant* outcome on real AROL data (~80%+ of raw
   closures, per `data/generate_sample_data.py`'s own calibration). On a
   1-hour synthetic test this produced ~104,000 false positives across 36
   heads, which would have made `dataset_quality_summary` — the tool behind
   AROL's own example query "Are there any missing or invalid torque
   values?" — wildly misleading. **Fix**: zero torque is now only flagged
   when it occurs *without* a "No Load" status (which is exactly the
   condition `anomaly.torque_status_consistency_check` already treats as
   suspicious on the cleaned events table — the schema-level check is now
   the raw-polling-data equivalent of that same idea, applied consistently).
2. **Dead validation check.** The "timestamp is not monotonically
   increasing" check could never fire, because every call site
   (`load_pool`, `load_pool_streaming`, `validate_pool_files`) sorted the
   dataframe by timestamp immediately *before* calling `validate_schema` —
   so the check only ever saw already-sorted data. **Fix**: every call site
   now validates before sorting.
3. **Truncation-bias gap on `torque_moving_average`.** Unlike
   `list_closure_events`, this tool's description did not warn that an
   unscoped, fleet-wide call returns only a capped sample of the
   *earliest*-timestamped rows — for "did average torque change over the
   observed month?" asked without a head/date filter, the agent would
   silently see only the first few minutes of a month-long dataset. **Fix**:
   added the same explicit warning `list_closure_events` carries, and
   pointed the agent (in both the tool description and the system prompt)
   toward `detect_drift` for fleet-wide trend questions instead.

## 6. Known limitations / next steps (carried over from README.txt)

- `analytics.torque_expected_range_nm` in `config.yaml` is still a
  placeholder — tune it against real successful-closure torque values once
  more of the real dataset is available (e.g. via `torque_statistics`).
- Closure timestamps are approximated as the polling timestamp at which the
  Count increment was observed; finer reconstruction via cycle-time
  interpolation is possible if higher precision is needed.
- Correlation between heads is computed by aligning the i-th closure of each
  head (heads don't share identical timestamps); an alternative is
  time-window binning — worth comparing empirically if this project's
  experimental-evaluation section is expanded.
- The closure-events table returned by the streaming loaders is not itself
  dtype-optimized (unlike the raw per-file data); on a full quarter of real
  data it can still reach tens of millions of rows in memory. Agent-facing
  tools already return capped samples/aggregates, so this mainly affects
  ad-hoc analysis outside the CLI/agent, not the CLI's own memory ceiling.
- Idle-run merging across a file boundary closes a run using the last
  timestamp actually observed if it doesn't continue into the next file,
  which can under-report a run's true duration by up to one polling
  interval at the boundary.
