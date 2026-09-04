AROL TELEMETRY REPORT AGENT
============================
Agentic AI for Telemetry Analysis on AROL Capping Machines
Project Q3 - Politecnico di Torino - Prof. Stefano Quer


1. WHAT THIS IS
----------------
An agentic system that:
  - ingests raw polling telemetry from AROL capping machines (WP1)
  - detects real closure events from noisy, over-sampled polling data
    by tracking per-head Count-column deltas
  - runs a set of deterministic analytics tools over the cleaned data
    (WP2): success rate, torque statistics, trend/drift, anomalies,
    correlation, idle-time detection
  - uses an LLM-driven "report agent" (WP3, via the Claude API) that
    interprets a free-text or preset request, decides which analytics
    tools to call and in what order, and writes a structured,
    explainable report
  - exposes everything through a CLI (WP4)


2. REQUIREMENTS
----------------
  - Python 3.10 or newer
  - An Anthropic API key (only required for "report" / "ask" commands;
    the deterministic analytics layer works without it - see tests/)

Set the API key before running agent commands:

    export ANTHROPIC_API_KEY=sk-ant-...   (Linux/Mac)
    set ANTHROPIC_API_KEY=sk-ant-...      (Windows cmd)


3. INSTALLATION
----------------
From the project root:

    pip install -r requirements.txt
    pip install -e .

This installs the "arol-mas" command. Alternatively, run everything
with PYTHONPATH=src and "python -m arol_mas.cli.main" instead of
"arol-mas".


4. DATASET FORMAT
------------------
Each "dataset pool" is a folder under data/pools/<pool_name>/ containing
one or more CSV, JSON, or Parquet files with this wide-format schema
(one row per polling sample), matching the real AROL sample dataset
(q3_dataset_sample_20260401.csv - 690 rows, 109 columns, 36 heads):

    timestamp,
    H01 Count, H02 Count, ..., H36 Count,
    H01 AppTorque, H02 AppTorque, ..., H36 AppTorque,
    H01 Status, H02 Status, ..., H36 Status

  timestamp   ISO-8601 UTC timestamp of the poll
  H0X AppTorque   torque reading (Nm) live at that poll for head X
  H0X Status      status/fault code live at that poll for head X. See
                  "STATUS CODE MEANING" below - this is not a simple
                  pass/fail flag.
  H0X Count       monotonically increasing counter for head X; it
                  increments exactly once per REAL closure event

Note the column names are SPACE-separated ("H01 Count"), not
underscore-separated. This is configured in config.yaml under
schema.torque_suffix / schema.status_suffix / schema.count_suffix -
if AROL later hands you a differently-formatted export, only that
config section needs to change, not the code.

Because the polling rate is faster than the machine's production
cycle, most consecutive rows repeat the same Count value for a head.
A closure event is detected precisely when a head's Count increases
between two consecutive polls - NOT by comparing whole rows for
duplication. This is the core cleaning logic (see
src/arol_mas/ingestion/closure_detection.py).

To use the real AROL sample file, place it directly at:
    data/pools/sample_pool/q3_dataset_sample_20260401.csv

A synthetic dataset pool matching this exact schema (36 heads) can
also be generated with:

    python data/generate_sample_data.py \
        --out data/pools/sample_pool/telemetry.csv \
        --minutes 11.5 --poll-hz 1.0

A pool of data:

    data/pools/2026-03/telemetry_<machine_id>_2026-03-01.csv
    data/pools/2026-03/telemetry_<machine_id>_2026-03-02.csv
    ...
    data/pools/2026-03/telemetry_<machine_id>_2026-03-31.csv

`arol-mas report` / `ask` / `validate` load every file in a pool and
treat it as one continuous dataset. See section 4a below for how this
scales to a full month or more without exhausting memory.


4a. LOADING A FULL MONTH (OR MORE) OF REAL DATA
--------------------------------------------------
A single real AROL daily export is ~55-60 MB (86,400 polling rows x
109 columns). So  `load_pool_streaming()` (src/arol_mas/ingestion/loader.py,
used by every CLI command) processes one file at a time: it detects
that file's closure events and idle periods - both of which collapse
the 86,400 raw rows into a much smaller table - then discards the raw
polling data before loading the next file. Column dtypes are also
downcast (float64 -> float32, int64 -> the smallest int type that
fits) to roughly halve the memory each file needs while it's loaded.

A closure or an idle "No Load" run can span the exact boundary between
two daily files (e.g. a run still in progress at midnight). To avoid
splitting or double-counting these:
  - closure detection carries a single row (the previous file's last
    row) into the next file, so the Count-delta check at the first row
    of a new file is still correct;
  - idle-period detection carries an explicit "still open" state per
    head across files, and merges it back into one run if the idle
    period continues at the start of the next file.
This is covered by tests/test_streaming_loader.py, which builds the
exact same data split across one file vs. two and asserts identical
results.

On a real month of AROL data (36 heads, ~86,400 rows/day) this
processes roughly 1 day/second and peaks at well under 1 GB RAM
regardless of how many months are in the pool, since memory use is
bounded by one file at a time, not by the whole pool.


5. CONFIGURATION
-----------------
All paths and tunables live in config/config.yaml - nothing is
hard-coded in source. Key settings:

  data.pools_dir            where dataset pools live
  data.default_pool         pool used when --pool is omitted
  heads.ids                 which head IDs to expect (36 for the real
                             AROL sample: H01..H36)
  schema.torque_suffix/status_suffix/count_suffix   real column format
  analytics.torque_expected_range_nm   used by anomaly detection
  agent.model                Claude model used by the report agent

Point at a different config file with --config path/to/other.yaml or
the AROL_CONFIG environment variable.


6. STATUS CODE MEANING
------------------------
Status codes are sourced from AROL's own status-code table (project
file: Status-code-to-meaning_mapping), implemented in
src/arol_mas/ingestion/status_codes.py. Every closure event is
classified into exactly one of four categories:

  success   status 0 ("Closure OK")
  no_load   status 2 ("No Load") - the station cycled with NO BOTTLE
            PRESENT. This is not a capping attempt, and is excluded
            from every success-rate / reject-rate denominator. On the
            real AROL sample, this is the majority case (~80%+ of raw
            closures) - do not mistake it for a failure.
  reject    any status where AROL's own reject_signal = YES (a genuine
            quality failure: SlowTorque, ClosureTorque, tracking error,
            etc.)
  fault     any other non-zero, non-no-load status (reject_signal = NO:
            No Closure, No InTorque, No CapTurns, Following Error, Bad
            Closure) - a diagnostic anomaly, but not a quality reject
            by AROL's own flag.

All success-rate and reject-rate KPIs use "attempted" (= total closures
minus no_load) as the denominator, not raw closure count. Two analytics
tools exist specifically to work with this: fault_code_breakdown (which
non-reject faults are occurring, with AROL's descriptions) and
torque_status_consistency_check (flags rows where the No Load status
and the raw torque reading disagree - a data-quality diagnostic).

If you obtain a different/updated status-code table from AROL, update
STATUS_TABLE in status_codes.py - it is the single source of truth for
this classification.


7. RUNNING
-----------
List available dataset pools:

    arol-mas list-pools

Validate a pool's schema without generating a report:

    arol-mas validate --pool sample_pool

Generate a preset report (kind is one of: kpi, anomalies, drift):

    arol-mas report kpi       --pool sample_pool
    arol-mas report anomalies --pool sample_pool
    arol-mas report drift     --pool sample_pool
    (Ex: arol-mas report kpi --start-date 2026-03-01 --end-date 2026-03-07)

Ask a free-text question (the agent decides which tools to call):

    arol-mas ask "Which head shows the lowest success rate?" --pool sample_pool
    arol-mas ask "Why is head 5 underperforming?" --pool sample_pool
    arol-mas ask "Compare average torque of successful vs failed closures" --pool sample_pool
    (Ex: arol-mas ask "How many closures had torque above 2.5 Nm?" --pool 2026-03)

Every run writes a timestamped Markdown report file into reports/
(configurable via reports.output_dir) containing:
  Goal / Data used / Analyses executed / Findings / Confidence & limits
  / Next checks, plus a trace of every tool call the agent made.


7a. RUNNING THE WEB UI (optional, WP4 web variant)
-----------------------------------------------------
This is an additional transport on top of the same WP1-WP3 code -
nothing analytical lives in it. Two processes:

Backend (FastAPI, from the project root, with ANTHROPIC_API_KEY set):

    pip install -r requirements.txt
    python -m uvicorn arol_mas.webapi.server:app --reload --reload-dir src --port 8000

(--reload-dir src keeps the auto-reloader from watching data/ and
reports/, which otherwise triggers restarts every time a dataset pool
or report file changes.)

Frontend (from webapp/):

    cd webapp
    npm install
    npm run dev

Then open the Vite dev server URL (default http://localhost:5173).
It talks to the backend at VITE_API_BASE (webapp/.env, default
http://localhost:8000).

For a production build: `npm run build` in webapp/ produces webapp/dist/,
which can be served by any static file server.


8. TESTING
-----------
    PYTHONPATH=src pytest tests/ -v

Tests cover the closure-detection algorithm (the core cleaning logic)
and the deterministic KPI functions, independent of the LLM agent, so
they run without an API key.


9. PROJECT STRUCTURE
----------------------
  config/config.yaml             all configuration
  data/generate_sample_data.py   synthetic dataset generator
  src/arol_mas/config.py         config loader
  src/arol_mas/ingestion/        WP1: loading, schema validation,
                                  closure detection
  src/arol_mas/analytics/        WP2: kpi, trend, anomaly, correlation,
                                  idle-detection tools
  src/arol_mas/agent/            WP3: tool registry + orchestrator
                                  (report agent) + report templates
  src/arol_mas/cli/               WP4: command-line interface
  src/arol_mas/webapi/           WP4 (web variant): FastAPI backend
                                  serving the same agent over REST
  webapp/                        WP4 (web variant): React/Vite frontend
  tests/                         pytest suite
  reports/                       generated report output (created at
                                  runtime)

# Architecture & Agent Decision Flow

## System architecture

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
      |  WP4 - src/arol_mas/cli/main.py                |
      |  typer commands: ask / report / validate /        |
      |  list-pools. Resolves --pool vs --date vs           |
      |  --start-date/--end-date into a file list, builds     |
      |  an AgentContext, runs the agent, saves + prints        |
      |  the report                                                |
      +----------------------------------------------+
```

## Why ingestion is split from analytics

WP1 never touches the LLM and WP2 never touches raw files - `events`
(one row per real closure) and `idle_periods` are the only handoff
between them. This split is what makes the deterministic layer testable
in isolation (see `tests/test_kpi.py`, `test_closure_detection.py`, etc.
- none of them need an API key) and is why the agent's outputs are
reproducible: given the same `events` table, every tool call returns the
exact same number every time, regardless of what the LLM decides to ask
for.

## Data schema

Raw input: one row per poll, one `timestamp` column, and per head
(`H01`...`H36`) three columns - `{head} AppTorque`, `{head} Status`,
`{head} Count`. See README.txt section 4 for the full column reference.

Internal `events` schema (one row per REAL closure, not per poll) -
`ClosureEventColumns` in `ingestion/closure_detection.py`:
`event_timestamp, head_id, torque, status, is_success, is_no_load,
is_reject, is_fault, status_category, status_description, count,
seq_gap`. `seq_gap` is >1 when the polling interval missed intermediate
closures for that head (logged, not fabricated - see README section
10's known limitations).

## Analytics methods (one line each - see each module's docstring for
the full method)

- **kpi.py**: success/reject/fault counts and rates, overall and
  per-head; torque mean/min/max/std, overall and per-head.
- **trend.py**: rolling torque average; z-score drift detection (recent
  window vs. baseline window, per head); success rate and capping speed
  bucketed by time period or by hour-of-day.
- **anomaly.py**: out-of-range/zero torque flags; z-score statistical
  outliers; which head has the most genuine rejects; fault-code
  breakdown; torque-vs-status consistency check.
- **correlation.py**: torque correlation between two named heads
  (aligns the i-th closure of each, since heads don't share identical
  timestamps); torque-vs-success correlation; per-head deviation ranking
  from fleet average.
- **filters.py**: generic event listing/filtering by head, status
  category, torque range, and/or date range - the catch-all for ad-hoc
  questions that don't match a dedicated tool.
- **plotting.py**: matplotlib PNGs (torque over time, torque histogram,
  success rate per head, failed closures over time), saved under
  `reports/plots/` and returned as a path for the report to embed.

## Agent decision flow (WP3)

For a single `ask`/`report` call:

1. **CLI resolves scope -> events.** `cli/main.py` decides between
   `--pool` (one folder), `--date`/`--start-date`/`--end-date` (a period,
   possibly spanning multiple pool folders - see `loader.py`), builds
   the file list, streams it, and produces the `events` +
   `idle_periods` tables. This step is 100% deterministic and involves
   no LLM call.
2. **Claude receives the query + tool list.** `orchestrator.py` sends
   the user's question, the system prompt (status-code terminology +
   pipeline description, so meta-questions like "how were duplicates
   removed" are grounded in what the code actually does, not guessed),
   and the full `TOOL_SPECS` schema to the model.
3. **Claude calls zero or more tools, in a loop.** Each tool call goes
   through `run_tool()` in `tools.py`, which dispatches to the matching
   analytics function against the `AgentContext` (the loaded
   events/idle_periods/settings). Results are fed back to Claude, which
   can call more tools based on what it learned (e.g. call
   `success_rate_per_head` first, see an outlier head, then call
   `torque_statistics_per_head` filtered to just that head next -
   this is the "autonomously selecting analysis steps" objective slide
   3 asks for).
4. **Claude writes the final report text** in the fixed structure: goal
   -> data used -> analyses executed -> findings -> confidence & limits
   -> next checks. It is instructed to use only numbers tools actually
   returned, never invent figures, and to embed any `plot_path` as a
   Markdown image.
5. **`report_writer.py` renders and saves** the report through
   `report.md.j2`, including the full tool-call trace, so the report is
   both human-readable and auditable after the fact - anyone can see
   exactly which tools ran with which arguments and re-derive the
   numbers independently (as this project's own QA process has done
   repeatedly - see the "how the numbers were verified" note below).

### Graceful failure

If a tool call raises (e.g. a real bug once found in `success_rate_per_head`
on a zero-attempted head), the orchestrator logs the exception, the tool
returns nothing rather than crashing the whole run, and Claude is
expected to note the gap explicitly in Confidence & Limits and fall back
to other tools rather than fabricating a number - see any report where a
tool failure appears in the log but the final report still reads
coherently and honestly about what it could and couldn't determine.

## How the numbers were verified

Every core metric this system produces (success rates, torque stats,
per-head reject counts, capping speed, idle-period boundaries) has been
independently re-derived from the raw CSVs using plain pandas - outside
this codebase entirely - during development, and matched exactly. This
is the strongest evidence available that the ingestion/analytics layer
is computing correctly rather than merely running without errors.


10. KNOWN LIMITATIONS / NEXT STEPS
-------------------------------------
  - torque_expected_range_nm in config.yaml is still a placeholder -
    tune it against real successful-closure torque values once you
    have more of the real dataset to inspect (e.g. via
    torque_statistics on a real pool).
  - Closure timestamps are approximated as the polling timestamp at
    which the Count increment was observed; finer reconstruction via
    cycle-time interpolation is possible if higher precision is
    needed.
  - Correlation between heads is computed by aligning the i-th closure
    of each head (heads don't share identical timestamps); an
    alternative is time-window binning, worth comparing in the
    documentation's experimental evaluation section.
  - The closure-events table returned by load_pool_streaming is not
    itself dtype-optimized (unlike the raw per-file data) - on a full
    quarter of real data it can still reach tens of millions of rows
    in memory. The agent-facing tools already return capped
    samples/aggregates rather than the full table, so this mainly
    affects how long ad-hoc analysis outside the CLI/agent takes, not
    the CLI's own memory ceiling.
  - Idle-run merging across a file boundary (see section 4a) closes a
    run using the last timestamp actually observed if it doesn't
    continue into the next file, which can under-report a run's true
    duration by up to one polling interval at the boundary - the
    exact end is between the two files, not directly observed.


11. QUERY COVERAGE
---------------------
Every example query in AROL's proposal slides (pp.13-15) maps to a
tool, with a few gaps closed since the first version of this repo:
  - Filtering/conditional queries ("show all failed events for head 3",
    "torque above X Nm") -> list_closure_events (generic filter tool)
  - "time of day and failure probability" -> success_rate_by_hour_of_day
    (success_rate_over_time groups by calendar day, not by
    hour-of-day pooled across days, so it couldn't answer this)
  - "missing or invalid torque values" -> dataset_quality_summary
    (surfaces the schema-validation issues collected once at load time)
  - Visualization-oriented queries (plot/histogram/chart/dashboard) ->
    plot_torque_over_time, plot_torque_histogram,
    plot_success_rate_per_head, plot_failed_closures_over_time - all
    save a PNG under reports/plots/ and return its path, which the
    agent embeds as a Markdown image in the saved report. This also
    covers the OBJECTIVE slide's "reports + plots/tables where
    relevant" requirement, which the tool set didn't address before.
  - Meta/system questions ("what preprocessing steps were applied",
    "how were duplicates removed") are answered from the agent's own
    system-prompt knowledge of the pipeline rather than a dedicated
    tool, since they're questions about the system, not the data.
