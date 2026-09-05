# AROL Telemetry Report

**Generated:** 2026-09-04T09:33:06.859429+00:00
**Dataset pool:** 2026-03
**Request:** Generate a KPI report: overall success rate, per-head success rate, and torque statistics for successful closures.

---

All results are in. Here is the full KPI report.

---

# AROL Capping Machine — KPI Report
**Dataset:** 2026-03 pool | **Period covered:** 2026-03-01T16:00:01 UTC → 2026-03-03T15:49:25 UTC

---

## Goal
Provide a comprehensive KPI summary covering overall success rate, per-head success rate, and torque statistics for successful closures across the March 2026 dataset.

## Data used
- Dataset pool: 2026-03 (2 full days + partial day, 36 capping heads)
- Time range: 2026-03-01 16:00:01 UTC to 2026-03-03 15:49:25 UTC
- Tools called: `overall_success_rate`, `success_rate_per_head`, `torque_statistics` (successful only), `time_range`, `plot_success_rate_per_head`, `plot_torque_histogram`, `plot_torque_over_time`

## Analyses executed
- Fleet-wide success / reject / no-load event counts and success rate
- Per-head success rate, attempted closures, and reject counts (all 36 heads)
- Torque statistics (mean, min, max, std) restricted to successful closures
- Three visualisations: success rate bar chart, torque histogram, torque scatter over time

---

## Findings

### 1 · Overall Success Rate

| Metric | Value |
|---|---|
| Total closure events (all statuses) | 1,379,485 |
| No-Load cycles (no bottle present) | 639,799 |
| **Attempted closures** (denominator) | **739,686** |
| Successful closures | 739,675 |
| Rejected closures (reject_signal = YES) | 11 |
| Fault closures | 0 |
| **Success rate** | **100.0 %** |
| Reject rate | 0.0 % |

The machine delivered an effectively perfect success rate over the observed period. Only 11 genuine quality rejects were recorded across ~740 K capping attempts, and zero fault-status events occurred.

---

### 2 · Per-Head Success Rate

![Success rate per head](C:\Users\mkcha\Desktop\arol\reports\plots\20260904T093217Z_success-rate-per-head.png)

All 36 heads reported **100.0 %** success rate (rounded to one decimal place). The small number of rejects is spread across six heads only:

| Head | Attempted | Rejected | Notes |
|---|---|---|---|
| H07 | 20,562 | 1 | |
| H22 | 20,560 | 1 | |
| H29 | 20,547 | **2** | Highest reject count |
| H31 | 20,539 | 1 | |
| H32 | 20,527 | **2** | Highest reject count |
| H33 | 20,533 | 1 | |
| H35 | 20,560 | 1 | |
| H36 | 20,540 | **2** | Highest reject count |
| All other heads (H01–H06, H08–H21, H23–H28, H30, H34) | — | 0 | Perfect record |

H29, H32, and H36 each produced 2 rejects — the highest per-head count — though all remain statistically negligible relative to their attempt volumes (~20,500+).

---

### 3 · Torque Statistics (Successful Closures Only)

| Statistic | Value |
|---|---|
| Sample size (n) | 739,675 |
| Mean closing torque | **2.20 Nm** |
| Minimum torque | 0.00 Nm |
| Maximum torque | 2.41 Nm |
| Std deviation | **0.07 Nm** |

The torque distribution is remarkably tight: a standard deviation of only 0.07 Nm around a 2.20 Nm mean indicates highly consistent capping force across the entire fleet. The range spans 0.00–2.41 Nm; the 0.00 Nm minimum warrants a check (see *Next Checks*).

![Torque histogram (successful closures)](C:\Users\mkcha\Desktop\arol\reports\plots\20260904T093217Z_torque-histogram.png)

![Torque over time (all heads)](C:\Users\mkcha\Desktop\arol\reports\plots\20260904T093231Z_torque-over-time-all.png)

---

## Confidence & Limits

- **Short window:** The dataset covers only ~47.8 hours (roughly 2 days). KPIs at this scale are internally consistent but may not represent longer-term trends or seasonal variation.
- **Success rate rounding:** All per-head rates display as 100.0 % because reject counts (max 2 per head) are below the precision threshold for a ~20,500-attempt denominator. Absolute reject counts are the more informative metric here.
- **0.00 Nm minimum torque:** A minimum of 0.00 Nm on successful closures could indicate a sensor glitch, a "No Load" mis-classification, or data-quality issue rather than a true zero-force cap — this has not been validated in this report.
- **No fault events:** Zero fault-status records is a strong result but should be cross-checked against raw data integrity (e.g., dataset_quality_summary) to confirm no data was silently lost.

---

## Next Checks

1. **Zero-torque investigation:** Run `zero_torque_summary` and `torque_status_consistency_check` to confirm whether the 0.00 Nm minimum on successful closures reflects genuine readings or sensor/classification errors.
2. **Focus on H29, H32, H36:** Run `list_closure_events` filtered to each of these heads with `status_category = "reject"` to inspect the exact timestamps, torque values, and status codes of their 2-reject events and assess whether a pattern (e.g., time-of-day, torque spike) is present.
3. **Extend the time window:** Pull a full month (all of 2026-03) to check whether the near-perfect success rate holds over a longer horizon, and use `torque_moving_average` per head to detect slow drift that is invisible in a 2-day window.

---

## Tool-call trace


1. `overall_success_rate({})`

2. `success_rate_per_head({})`

3. `torque_statistics({'successful_only': True})`

4. `time_range({})`

5. `plot_success_rate_per_head({})`

6. `plot_torque_histogram({'successful_only': True})`

7. `plot_torque_over_time({})`

