# AROL-MAS Query Guide

What you can ask `arol-mas ask "..."` (or the preset `arol-mas report kpi|anomalies|drift`),
organized the same way AROL's own proposal deck organizes example questions, plus a
scoping/syntax reference. Every category below is backed by one or more of the 27 tools
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