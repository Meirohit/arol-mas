# AROL-MAS Query Guide

What you can ask `arol-mas ask "..."` (or the preset `arol-mas report kpi|anomalies|drift`),
organized the same way AROL's own proposal deck organizes example questions, plus a
scoping/syntax reference. Every category below is backed by one or more of the 28 tools
in `src/arol_mas/agent/tools.py` - the agent decides which to call.

## Setup (once per session)

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

## Scoping a question

Every command below takes one of two scoping styles:

**A single pool** (a folder under `data/pools/`, typically one calendar month):
```powershell
arol-mas ask "..." --pool 2026-03
```
If `--pool` is omitted, the config's default pool is used.

**A date range**, which can span across pool folders (e.g. late Feb into March):
```powershell
arol-mas ask "..." --start-date 2026-02-12 --end-date 2026-03-15
```
A single day is 
```powershell
arol-mas validate --date 2026-03-04
```

Always validate a pool/period before your first query on it:
```powershell
arol-mas validate --pool 2026-03
```

---

## 1. Basic data exploration

```powershell
arol-mas ask "How many capping operations were performed in March 2026?" --pool 2026-03
arol-mas ask "How many closure events were performed by each head?" --pool 2026-03
arol-mas ask "Show me the time range covered by the dataset." --pool 2026-03
arol-mas ask "Are there any missing or invalid torque values?" --pool 2026-03
```
*Answered by `dataset_quality_summary` (missing values, negative torque, decreasing
counters, unparseable/out-of-order timestamps, collected once at load time). As of the
2026-09 audit, zero-torque readings are **not** included here unless they occur on a
closure that ISN'T marked "No Load" - zero torque is the expected reading during a
No Load cycle (head rotated with no bottle present, ~80%+ of raw closures on real AROL
data), so flagging every one of those as "invalid" used to flood this tool with tens of
thousands of false positives. Use `zero_torque_summary` if you specifically want the
raw zero-torque count including expected No Load ones.*

## 2. Quality and success-rate

```powershell
arol-mas ask "What percentage of capping operations were successful?" --pool 2026-03
arol-mas ask "How many closures ended with a positive outcome?" --pool 2026-03
arol-mas ask "How many failed capping operations were recorded?" --pool 2026-03
arol-mas ask "What is the success rate per capping head?" --pool 2026-03
arol-mas ask "Which head shows the lowest success rate?" --pool 2026-03
```

## 3. Torque-related analytics

```powershell
arol-mas ask "What is the average closing torque for successful capping operations?" --pool 2026-03
arol-mas ask "Show the torque distribution for all successful closures." --pool 2026-03
arol-mas ask "Are there torque values outside the expected operating range?" --pool 2026-03
arol-mas ask "Compare the average torque of successful vs failed closures." --pool 2026-03
arol-mas ask "Which head shows the highest torque variability?" --pool 2026-03
```

## 4. Time-based and trend

```powershell
arol-mas ask "How did the capping success rate evolve over time?" --pool 2026-03
arol-mas ask "Show a daily breakdown of successful vs failed closures." --pool 2026-03
arol-mas ask "Did the average torque change over the observed month?" --pool 2026-03
arol-mas ask "Is there a correlation between time of day and failure probability?" --pool 2026-03
```
*The "did average torque change" question is fleet-wide and unscoped - the agent is
instructed to reach for `detect_drift` (baseline-vs-recent per head, a small aggregated
result) rather than `torque_moving_average` here. `torque_moving_average` returns one
row per closure event, and when called unscoped over a full month it returns only a
capped sample of the EARLIEST-timestamped rows - the first few minutes of the month,
not a representative spread. It's the right tool for "how did torque trend for head 7
last week" (one head, narrow range), not for an unscoped fleet-wide month.*

*"Abnormal failure rate intervals" works too, but it's the agent reasoning over the
daily breakdown rather than a dedicated statistical test - treat it as a qualitative
answer, not a z-scored list of flagged days.*

## 5. Filtering and conditional

```powershell
arol-mas ask "Show only capping operations with a positive outcome." --pool 2026-03
arol-mas ask "List all failed capping events with torque below 1.9 Nm." --pool 2026-03
arol-mas ask "How many closures had torque above 2.5 Nm?" --pool 2026-03
arol-mas ask "Show all capping events for head 3 with a failed outcome." --pool 2026-03
arol-mas ask "List failed closures between March 5th and March 10th." --pool 2026-03
```
*Any filtering question scoped to a date range (e.g. "last week") needs the agent to
pass dates through - it's instructed to and does, but if a filtered answer looks like
it's only returning very early results, that's the tell something scoped wrong.*

## 6. Diagnostic and comparative

```powershell
arol-mas ask "Which capping head behaves differently from the others?" --pool 2026-03
arol-mas ask "Is there a head with an unusual number of failed closures?" --pool 2026-03
arol-mas ask "Compare performance between head 1 and head 2." --pool 2026-03
arol-mas ask "Which head contributes most to overall failures?" --pool 2026-03
arol-mas ask "Does higher torque correlate with higher success rate?" --pool 2026-03
```

## 7. Explanation-oriented (agentic reasoning)

```powershell
arol-mas ask "Why is the overall success rate lower on certain days?" --pool 2026-03
arol-mas ask "Explain why head 36 has more failed closures." --pool 2026-03
arol-mas ask "Summarize the main issues observed in the capping process." --pool 2026-03
arol-mas ask "Which signals should be monitored more closely?" --pool 2026-03
arol-mas ask "Generate a short report on capping quality for this dataset." --pool 2026-03
```
*These are answered by the agent composing several tools plus reasoning - there's no
single "right number" to fact-check, just whether the reasoning is well-supported by
the numbers it cites.*

## 8. Visualization

```powershell
arol-mas ask "Plot the closing torque over time for successful closures." --pool 2026-03
arol-mas ask "Show a histogram of closing torque values." --pool 2026-03
arol-mas ask "Create a chart showing success rate per head." --pool 2026-03
arol-mas ask "Visualize failed closures over time." --pool 2026-03
```
Each saves a PNG under `reports/plots/` and embeds it in the saved report.
*"Generate a dashboard" produces several separate plots + a text summary in one
report, not one composite dashboard image.*

## 9. Production rate / throughput

```powershell
arol-mas ask "What is the capping speed / production rate?" --pool 2026-03
arol-mas ask "How did throughput change day by day?" --pool 2026-03
```

## 10. Meta / system (about the pipeline itself)

```powershell
arol-mas ask "What preprocessing steps were applied to the raw data?" --pool 2026-03
arol-mas ask "How were duplicated closures detected and removed?" --pool 2026-03
arol-mas ask "What features are used to classify a successful closure?" --pool 2026-03
```

---

## Coverage check: every example query in AROL's slides (pp.13-15)

Verified against the tool registry in `src/arol_mas/agent/tools.py` during the 2026-09
audit. "Tool(s)" is what the agent is expected to call; "Verified" means the underlying
analytics function was exercised directly (not just via the LLM loop) against a
synthetic dataset and its output checked - either against a hand/pandas recomputation,
or against the exact-match unit tests in `tests/`.

| # | Query (AROL's wording) | Tool(s) | Verified |
|---|---|---|---|
| 1 | How many capping operations were performed in the selected month? | `overall_success_rate` (`total_closures`) | Yes - `test_kpi.py`, hand-recomputed |
| 2 | How many closure events were performed by each head? | `success_rate_per_head` (`total_closures`) | Yes - `test_kpi.py` |
| 3 | Show me the time range covered by the dataset. | `time_range` | Yes |
| 4 | Are there any missing or invalid torque values? | `dataset_quality_summary` | Yes - see §5 fix in `docs/architecture.md`; zero-torque false positives removed |
| 5 | What percentage of capping operations were successful? | `overall_success_rate` | Yes - hand-recomputed, matches AROL's own worked example (93.3%-style output) |
| 6 | How many closures ended with a positive outcome? | `overall_success_rate` (`successful`) | Yes |
| 7 | How many failed capping operations were recorded? | `overall_success_rate` (`rejected`, plus `faults` reported separately) | Yes - see terminology note in §2 above |
| 8 | What is the success rate per capping head? | `success_rate_per_head` | Yes - matches AROL's per-head table format (p.17) |
| 9 | Which head shows the lowest success rate? | `success_rate_per_head` (sorted ascending; agent reads first row) | Yes |
| 10 | What is the average closing torque for successful capping operations? | `torque_statistics` | Yes - hand-recomputed (mean/std matched exactly) |
| 11 | Show the torque distribution for all successful closures. | `plot_torque_histogram` | Yes - `test_new_query_coverage.py` checks the PNG is written |
| 12 | Are there torque values outside the expected operating range? | `out_of_range_torque` | Yes - `test_large_result_handling.py` |
| 13 | Compare the average torque of successful vs failed closures. | `failed_vs_successful_torque` | Yes |
| 14 | Which head shows the highest torque variability? | `torque_statistics_per_head` (agent sorts by `std_nm`) | Yes - no dedicated "highest variability" tool; the agent ranks the per-head table itself |
| 15 | How did the capping success rate evolve over time? | `success_rate_over_time` | Yes |
| 16 | Show a daily breakdown of successful vs failed closures. | `success_rate_over_time` | Yes |
| 17 | Are there specific time intervals with abnormal failure rates? | `success_rate_over_time` + agent reasoning | Qualitative only - see caveat in §4 above |
| 18 | Did the average torque change over the observed month? | `detect_drift` (not `torque_moving_average` unscoped - see fix in §5) | Yes - see caveat in §4 above |
| 19 | Is there a correlation between time of day and failure probability? | `success_rate_by_hour_of_day` | Yes - `test_new_query_coverage.py` |
| 20 | Show only capping operations with a positive outcome. | `list_closure_events` (`status_category="success"`) | Yes - `test_new_query_coverage.py` |
| 21 | List all failed capping events with torque below threshold. | `list_closure_events` (`status_category="reject"`, `torque_max=...`) | Yes |
| 22 | How many closures had torque above X Nm? | `list_closure_events` (`torque_min=X`) + `total_rows` for the exact count | Yes |
| 23 | Show all capping events for head 3 with a failed outcome. | `list_closure_events` (`head_id="H03"`, `status_category="reject"`) | Yes |
| 24 | Count successful closures after removing all duplicated entries. | `overall_success_rate` (`successful`) | Yes - de-duplication already happened during closure detection (§2 in `docs/architecture.md`); the events table IS the de-duplicated one, so no separate "dedup toggle" is needed |
| 25 | Which capping head behaves differently from the others? | `rank_heads_by_deviation` | Yes |
| 26 | Is there a head with an unusual number of failed closures? | `head_with_most_failures` or `rank_heads_by_deviation` | Yes |
| 27 | Compare performance between head 1 and head 2. | `success_rate_per_head` + `torque_statistics_per_head` (agent filters to H01/H02) | Yes |
| 28 | Which head contributes most to overall failures? | `head_with_most_failures` | Yes - `test_status_codes.py` confirms it uses reject, not all-non-success |
| 29 | Does higher torque correlate with higher success rate? | `torque_vs_success_correlation` | Yes |
| 30 | Why is the overall success rate lower on certain days? | agent composes `success_rate_over_time` + `fault_code_breakdown` + reasoning | Qualitative - no single "why" tool by design |
| 31 | Explain why head N has more failed closures. | agent composes `success_rate_per_head` + `torque_statistics_per_head` + `fault_code_breakdown` | Qualitative |
| 32 | Summarize the main issues observed in the capping process. | agent composes multiple tools | Qualitative |
| 33 | Which signals should be monitored more closely? | agent composes multiple tools + reasoning | Qualitative |
| 34 | Generate a short report on capping quality for this dataset. | `arol-mas report kpi` (preset) | Yes |
| 35 | Plot the closing torque over time for successful closures. | `plot_torque_over_time` | Yes - `test_new_query_coverage.py` |
| 36 | Show a histogram of closing torque values. | `plot_torque_histogram` | Yes |
| 37 | Create a chart showing success rate per head. | `plot_success_rate_per_head` | Yes - `test_new_query_coverage.py` |
| 38 | Visualize failed closures over time. | `plot_failed_closures_over_time` | Yes |
| 39 | Generate a dashboard summary of capping performance. | several `plot_*` tools + text summary in one report | By design, not one composite image - see caveat in §8 above |
| 40 | What preprocessing steps were applied to the raw data? | answered from the system prompt's pipeline description, no tool call | Yes - matches what the code actually does (§2-3 above) |
| 41 | How were duplicated closures detected and removed? | system prompt | Yes |
| 42 | Which assumptions were made during data cleaning? | system prompt | Yes |
| 43 | What features are used to classify a successful closure? | system prompt (status code 0 = success, from `status_codes.py`) | Yes |

**Result: all 43 example queries across AROL's 9 categories are answerable**, either by
a single deterministic tool, a combination the agent composes itself, or (for
inherently open-ended "why"/"summarize" questions) by the agent's own reasoning over
tool outputs - which is exactly the "autonomously selecting analysis steps" behavior
AROL's OBJECTIVE slide (p.3) asks for, not a gap.

---

## Preset reports

Canned versions of the most common request, useful for a quick demo:

```powershell
arol-mas report kpi --pool 2026-03
arol-mas report anomalies --pool 2026-03
arol-mas report drift --pool 2026-03
```
All three take `--start-date`/`--end-date`/`--pools` too, e.g.
`arol-mas report kpi --start-date 2026-03-01 --end-date 2026-03-07`.

## Every report is saved

Each `ask`/`report` run prints to the terminal *and* saves a Markdown file under
`reports/`, named from the timestamp and the question asked.