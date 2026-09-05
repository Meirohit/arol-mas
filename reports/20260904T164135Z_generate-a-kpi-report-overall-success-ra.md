# AROL Telemetry Report

**Generated:** 2026-09-04T16:41:35.060404+00:00
**Dataset pool:** 2026-03
**Request:** Generate a KPI report: overall success rate, per-head success rate, and torque statistics for successful closures.

---

All data collected. Here is the full KPI report.

---

# AROL Capping Machine — KPI Report
**Dataset:** 2026-03 pool | **Period covered:** 2026-03-01T16:00:01Z → 2026-03-03T15:49:25Z

---

## Goal
Generate a KPI report covering overall success rate, per-head success rate, and torque statistics for successful closures across the March 2026 dataset.

## Data Used
March 2026 multi-file pool; analyses span 2026-03-01 16:00 UTC through 2026-03-03 15:49 UTC (~48 hours). Tools called: `time_range`, `overall_success_rate`, `success_rate_per_head`, `torque_statistics` (successful only), `torque_statistics_per_head` (successful only), `plot_success_rate_per_head`.

## Analyses Executed
- Overall fleet success/reject/no-load event counts and success rate
- Per-head success rate breakdown (36 heads, sorted ascending)
- Fleet-wide torque statistics restricted to successful closures
- Per-head torque statistics restricted to successful closures
- Success rate per head bar chart

---

## Findings

### 1. Overall Success Rate

| Metric | Value |
|---|---|
| Total closure cycles | 1,379,485 |
| No Load (no bottle present) | 639,799 |
| **Attempted** (with bottle) | **739,686** |
| Successful (Status 0 – Closure OK) | 739,675 |
| Rejected (reject_signal = YES) | **11** |
| Faults | 0 |
| **Overall success rate** | **100.0%** |
| Reject rate | ~0.0015% |

The fleet is operating at effectively 100% success rate across ~740K capping attempts. Only 11 rejects were registered over the ~48-hour window, and no fault-type status codes occurred at all.

---

### 2. Per-Head Success Rate

All 36 heads report a rounded success rate of **100.0%**. The 11 rejects are distributed across just 7 heads — all others recorded zero rejects:

| Head | Attempted | Rejected | Notes |
|---|---|---|---|
| H29 | 20,547 | **2** | Highest reject count |
| H32 | 20,527 | **2** | Tied highest |
| H36 | 20,540 | **2** | Tied highest |
| H07 | 20,562 | 1 | |
| H22 | 20,560 | 1 | |
| H31 | 20,539 | 1 | |
| H33 | 20,533 | 1 | |
| H35 | 20,560 | 1 | |
| H01–H06, H08–H21, H23–H28, H30, H34 | — | **0** | Fully clean |

No head is a structural outlier — the maximum reject count per head is 2 over ~48 hours (~20,500+ attempts per head).

![Success Rate Per Head](plots/20260904T164058Z_success-rate-per-head.png)

---

### 3. Torque Statistics — Successful Closures (Fleet-Wide)

| Statistic | Value |
|---|---|
| Events included | 739,675 |
| Mean torque | **2.20 Nm** |
| Minimum torque | 0.00 Nm |
| Maximum torque | 2.41 Nm |
| Std. deviation | 0.07 Nm |

The fleet torque is tightly clustered: the standard deviation is only 0.07 Nm around a mean of 2.20 Nm. The range 2.20 ± 3σ (0.21 Nm) spans essentially the full observed range (0 – 2.41 Nm), indicating very consistent closing behaviour.

---

### 4. Per-Head Torque Statistics — Successful Closures

All 36 heads share the same mean of **2.20 Nm**. The table below highlights the notable variations in peak and spread:

| Head | Mean (Nm) | Min (Nm) | Max (Nm) | Std (Nm) |
|---|---|---|---|---|
| H11 | **2.19** | 0.00 | 2.20 | 0.09 |
| H15 | **2.19** | 0.00 | 2.20 | 0.08 |
| H35 | 2.20 | 0.00 | **2.42** | 0.07 |
| H16 | 2.20 | 0.00 | **2.34** | 0.08 |
| H09 | 2.20 | 0.00 | **2.29** | 0.06 |
| H18 | 2.20 | 0.00 | **2.29** | 0.07 |
| H30 | 2.20 | 0.00 | **2.28** | 0.07 |
| All others | 2.20 | 0.00 | ≤2.23 | 0.06–0.09 |

Key observations:
- **H11 and H15** are the only heads with a mean of 2.19 Nm (marginally below fleet average), and both have a max capped at 2.20 Nm — worth confirming their calibration.
- **H35** recorded the single highest torque peak at **2.42 Nm**, slightly above all other heads.
- **H16** had the second-highest peak at **2.34 Nm**.
- Zero-torque minimums appear across all heads; these are expected "No Load" type artefacts within otherwise successful events and should be investigated via `zero_torque_summary` if they are a concern.

---

## Confidence & Limits

- **Window is only ~48 hours** (2026-03-01 to 2026-03-03) despite the dataset being labelled "2026-03" — results may not be representative of the full month if more files are available.
- **Zero-torque minimums** appear on every head within the successful-closure set; this may indicate occasional polling artefacts captured at the transition edge of an event, or genuine low-torque outliers. A `zero_torque_summary` and `torque_status_consistency_check` would clarify.
- **Reject counts are extremely low** (11 total), so per-head reject ranking is not yet statistically meaningful — a single additional reject per head would change relative rankings.
- Torque values are reported to 2 decimal places (Nm); sensor resolution limits finer comparison.

---

## Next Checks

1. **Zero-torque events** — run `zero_torque_summary` and `torque_status_consistency_check` to determine whether zero-Nm readings inside successful closures are polling artefacts or real low-force events requiring investigation.
2. **H11 & H15 calibration** — their mean torque (2.19 Nm) and max torque (capped at 2.20 Nm) differ from the rest of the fleet; run `detect_drift` and `torque_moving_average` scoped to those heads to check for ongoing under-torquing.
3. **H35 peak torque** — at 2.42 Nm it has the highest single-event reading; run `out_of_range_torque` and `statistical_outliers` to determine if this is an isolated spike or a recurring over-torque pattern.

---

## Tool-call trace


1. `overall_success_rate({})`

2. `success_rate_per_head({})`

3. `torque_statistics({'successful_only': True})`

4. `time_range({})`

5. `plot_success_rate_per_head({})`

6. `torque_statistics_per_head({'successful_only': True})`

