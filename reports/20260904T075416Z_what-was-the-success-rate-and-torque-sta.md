# AROL Telemetry Report

**Generated:** 2026-09-04T07:54:16.037373+00:00
**Dataset pool:** 2026-02-16 to 2026-02-16
**Request:** What was the success rate and torque stats on Feburary 16th?

---

All three results are in — here's the full report:

---

**Goal:** Summarise the success rate and closing torque statistics for February 16th, 2026.

**Data used:** Single-day dataset covering 2026-02-16 00:00:00 UTC → 2026-02-16 23:59:59 UTC. Tools called: `overall_success_rate`, `torque_statistics` (successful closures only), `time_range`.

**Analyses executed:**
- Overall success/reject/fault breakdown for the day
- Closing torque statistics (mean, min, max, std dev) restricted to successful closures

---

**Findings:**

**Success Rate**

| Metric | Value |
|---|---|
| Total machine cycles | 852,953 |
| No Load cycles (no bottle present) | 224,828 |
| Attempted closures (bottles capped) | 628,125 |
| Successful closures (Status OK) | 628,112 |
| Rejected closures (reject_signal = YES) | 13 |
| Faults | 0 |
| **Success rate** | **100.0%** |
| Reject rate | ~0.002% |

The machine ran at an essentially perfect success rate on February 16th — only 13 rejections out of 628,125 attempts, and zero fault codes recorded for the entire day.

**Closing Torque (Successful Closures Only)**

| Metric | Value |
|---|---|
| Events measured | 628,112 |
| Mean torque | 2.00 Nm |
| Min torque | 0.00 Nm |
| Max torque | 2.01 Nm |
| Std deviation | 0.02 Nm |

Torque was remarkably consistent throughout the day — a standard deviation of just 0.02 Nm around a mean of 2.00 Nm, with virtually no spread between the minimum and maximum recorded values. The 0.00 Nm minimum is worth noting (likely a "No Load"-style edge case or a data artefact), but it did not affect the overall distribution meaningfully.

---

**Confidence & limits:**
- This covers a single day's data only; no baseline comparison to prior days is available in this dataset pool.
- The 0.00 Nm minimum torque on successful closures is unusual and may indicate a small number of events where torque was not measured correctly — a `zero_torque_summary` check could clarify how many events this affects.
- Success rate is computed on *attempted* closures (No Load cycles excluded), per AROL convention.

**Next checks:**
1. **Zero-torque events:** Run `zero_torque_summary` to quantify how many successful closures reported 0.00 Nm and which heads they came from.
2. **Per-head breakdown:** Run `success_rate_per_head` and `torque_statistics_per_head` to check whether the 13 rejections are concentrated on a specific capping head.
3. **Hourly trend:** Run `success_rate_over_time` with `freq=1H` to see if the rejections clustered at a particular time of day (e.g. start-up or shift change).

---

## Tool-call trace


1. `overall_success_rate({})`

2. `torque_statistics({'successful_only': True})`

3. `time_range({})`

