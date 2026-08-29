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

Ask a free-text question (the agent decides which tools to call):

    arol-mas ask "Which head shows the lowest success rate?" --pool sample_pool
    arol-mas ask "Why is head 5 underperforming?" --pool sample_pool
    arol-mas ask "Compare average torque of successful vs failed closures" --pool sample_pool

Every run writes a timestamped Markdown report file into reports/
(configurable via reports.output_dir) containing:
  Goal / Data used / Analyses executed / Findings / Confidence & limits
  / Next checks, plus a trace of every tool call the agent made.


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
  tests/                         pytest suite
  reports/                       generated report output (created at
                                  runtime)


10. KNOWN LIMITATIONS / NEXT STEPS
-------------------------------------
  - torque_expected_range_nm in config.yaml is still a placeholder -
    tune it against real successful-closure torque values once you
    have more of the real dataset to inspect.
  - Closure timestamps are approximated as the polling timestamp at
    which the Count increment was observed; finer reconstruction via
    cycle-time interpolation is possible if higher precision is
    needed.
  - Correlation between heads is computed by aligning the i-th closure
    of each head (heads don't share identical timestamps); an
    alternative is time-window binning, worth comparing in the
    documentation's experimental evaluation section.
