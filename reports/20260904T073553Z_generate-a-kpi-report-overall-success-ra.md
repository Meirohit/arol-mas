# AROL Telemetry Report

**Generated:** 2026-09-04T07:35:53.188008+00:00
**Dataset pool:** 2026-03
**Request:** Generate a KPI report: overall success rate, per-head success rate, and torque statistics for successful closures.

---

All tool results are in. Here is the full KPI report.

---

# AROL Capping Machine — March 2026 KPI Report

---

## Goal
Provide a comprehensive monthly KPI summary covering overall success rate, per-head success rate, and torque statistics for successful closures across the 36-head capping machine fleet.

---

## Data used
- **Dataset pool:** 2026-03 (daily files streamed across file boundaries)
- **Time range covered:** 2026-02-28T16:00:01 UTC → 2026-03-31T16:54:12 UTC (effectively the full month of March 2026, with a tail from the last hours of February at the start)
- **Tools called:** `time_range`, `overall_success_rate`, `success_rate_per_head`, `torque_statistics` (successful only), `torque_statistics_per_head` (successful only), `plot_success_rate_per_head`, `plot_torque_histogram`, `plot_torque_over_time`

---

## Analyses executed
- Overall fleet closure counts and success/reject/fault/no-load breakdown
- Per-head success rate (36 heads), sorted worst-first
- Fleet-wide torque statistics restricted to successful closures
- Per-head torque statistics restricted to successful closures
- Visualisation: success rate by head (bar chart), torque distribution (histogram), torque over time (scatter)

---

## Findings

### 1. Overall Fleet Performance

| Metric | Value |
|---|---|
| Total closure events (all statuses) | 11,426,125 |
| No Load cycles (station idle, no bottle) | 7,485,574 |
| **Attempted closures** (denominator) | **3,940,551** |
| Successful closures | 3,940,339 |
| Rejects (reject_signal = YES) | 203 |
| Faults (non-reject diagnostic codes) | 9 |
| **Fleet success rate** | **100.0%** |
| Reject rate | 0.0% |

The machine ran **~3.94 million capping attempts** across the month. Of those, **only 203 were flagged as genuine quality rejects** and just **9 as diagnostic faults** — a remarkably clean production run. No Load cycles account for 65.5% of all events, consistent with normal carousel idle-stroke behaviour.

---

### 2. Per-Head Success Rate

All 36 heads report a rounded success rate of **100.0%**. The per-head reject counts are very low in absolute terms, but there is meaningful spread when ranked by raw reject count:

| Rank | Head | Attempted | Successful | Rejects | Reject Count |
|---|---|---|---|---|---|
| ⚠️ 1 (worst) | **H36** | 109,446 | 109,425 | 19 | Highest |
| 2 | **H35** | 109,484 | 109,467 | 16 | |
| 3 | **H32** | 109,426 | 109,412 | 14 | |
| 4 | **H01** | 109,448 | 109,434 | 13 | |
| 4 | **H29** | 109,491 | 109,477 | 13 | |
| 4 | **H33** | 109,448 | 109,435 | 13 | |
| 7 | **H22** | 109,495 | 109,483 | 10 | |
| 7 | **H31** | 109,412 | 109,401 | 10 | |
| ✅ Best (tied) | **H09, H10** | ~109,454 | same | 0 | Zero rejects |

Two heads — **H09** and **H10** — produced zero rejects for the entire month. At the other end, **H36** (19), **H35** (16), and **H32** (14) account for a disproportionate share of the fleet's 203 total rejects and are the heads most worth monitoring going forward.

![Success Rate per Head](D:\system-device\arol-mas\reports\plots\20260904T073450Z_success-rate-per-head.png)

---

### 3. Torque Statistics — Successful Closures (Fleet-Wide)

| Statistic | Value |
|---|---|
| Events analysed | 3,940,339 |
| Mean torque | **2.05 Nm** |
| Min torque | **0.0 Nm** |
| Max torque | **3.13 Nm** |
| Std deviation | **0.14 Nm** |

The fleet torque is tightly clustered around 2.05 Nm with a standard deviation of only 0.14 Nm. The minimum of 0.0 Nm warrants attention (see Confidence & Limits). The maximum of 3.13 Nm is a single-head outlier (H07, see below).

![Torque Histogram — Successful Closures](D:\system-device\arol-mas\reports\plots\20260904T073450Z_torque-histogram.png)
![Torque over Time — All Heads](D:\system-device\arol-mas\reports\plots\20260904T073511Z_torque-over-time-all.png)

---

### 4. Per-Head Torque Statistics — Successful Closures

Every head shares an identical **mean of 2.05 Nm** and **std of 0.14 Nm**, confirming the fleet is uniformly calibrated. Differences appear only in the **maximum torque** recorded per head:

| Head | Max Torque (Nm) | Note |
|---|---|---|
| **H07** | **3.13** | 🔴 Highest — >0.7 Nm above typical ceiling |
| **H19** | 2.43 | Elevated |
| **H12** | 2.42 | Elevated |
| **H35** | 2.42 | Elevated — also top-3 in rejects |
| **H32** | 2.39 | Elevated — also top-3 in rejects |
| **H16** | 2.34 | Slightly elevated |
| **H04** | 2.32 | Slightly elevated |
| Most heads | 2.20–2.29 | Normal operating band |

**H07 stands out strongly**: its recorded max of 3.13 Nm is ~0.9 Nm above the next-worst head and ~0.5 Nm above the typical upper band seen across the fleet. Although H07's reject count is low (1), a torque spike this large in a successful closure is unusual and may indicate a momentary mechanical event or sensor anomaly.

---

## Confidence & Limits

- **Success rates are rounded to 100.0%** for all heads because reject counts (max 19 out of ~109,000 attempts) are below the precision of one decimal place. Absolute reject counts are the better comparator for between-head ranking.
- **Zero-torque readings appear in the min column for every head** (including successful closures). These are likely "No Load" polling artefacts captured just before the status flag updated, or genuine sensor dropouts — they should be cross-checked with `zero_torque_summary` and `torque_status_consistency_check` to confirm they are not masking real quality events.
- **H07's 3.13 Nm maximum** is a single data point (or very few); a single outlier poll in a ~109,000-event series does not necessarily indicate a systemic problem, but it is anomalous enough to warrant investigation.
- The dataset starts at 2026-02-28T16:00:01 UTC, meaning approximately 8 hours of late-February production are included. This is unlikely to materially affect a month-level KPI but should be noted for strict calendar-month comparisons.
- No comparative baseline (e.g. February 2026) is available in this pool, so trend direction cannot be assessed here.

---

## Next Checks

1. **Investigate H36, H35, and H32 

---

## Tool-call trace


1. `overall_success_rate({})`

2. `success_rate_per_head({})`

3. `torque_statistics({'successful_only': True})`

4. `torque_statistics_per_head({'successful_only': True})`

5. `time_range({})`

6. `plot_success_rate_per_head({})`

7. `plot_torque_histogram({'successful_only': True})`

8. `plot_torque_over_time({})`

