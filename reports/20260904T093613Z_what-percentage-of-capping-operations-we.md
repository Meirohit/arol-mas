# AROL Telemetry Report

**Generated:** 2026-09-04T09:36:13.517418+00:00
**Dataset pool:** 2026-03
**Request:** What percentage of capping operations were successful?

---

Goal: Determine the percentage of capping operations that were successful in March 2026.

Data used: March 2026 dataset pool; `overall_success_rate` tool called to retrieve fleet-wide closure statistics.

Analyses executed:
- Overall success rate across all heads for the full month of March 2026.

Findings: Out of **1,379,485 total closure events** recorded in March 2026:

| Category | Count |
|---|---|
| No Load (no bottle present — excluded from rate) | 639,799 |
| **Attempted closures** (bottles present) | **739,686** |
| Successful closures (Status 0 – Closure OK) | 739,675 |
| Rejected closures (reject_signal = YES) | 11 |
| Faults (diagnostic codes) | 0 |

➡️ **Success rate: 100.0%** (rounded to one decimal place)

More precisely, only **11 rejections out of 739,686 attempted closures** were recorded — an exceptionally low reject rate of approximately **0.0015%** — with zero fault-status events observed across the entire month.

Confidence & limits:
- The success rate is calculated against *attempted* closures only (i.e., No Load / no-bottle cycles are correctly excluded from the denominator, per AROL's status-code definitions).
- The 100.0% figure is the result of rounding; the true rate is marginally below 100% due to the 11 rejections. The machine performed extremely well throughout March 2026.
- Results reflect data as loaded and validated by the pipeline; any polling gaps where intermediate closures were missed between polls would not be reflected in these counts.

Next checks:
1. **Investigate the 11 rejections** — use `head_with_most_failures` and `fault_code_breakdown` to identify which head(s) produced them and what status codes were involved.
2. **Check for temporal clustering** — run `success_rate_over_time` (daily frequency) to see if the 11 rejections were isolated to a specific day or period.
3. **Review dataset quality** — run `dataset_quality_summary` to confirm there are no schema issues (e.g., missed polls or counter jumps) that could have masked additional failure events.

---

## Tool-call trace


1. `overall_success_rate({})`

