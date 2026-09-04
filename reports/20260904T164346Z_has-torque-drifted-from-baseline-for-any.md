# AROL Telemetry Report

**Generated:** 2026-09-04T16:43:46.648902+00:00
**Dataset pool:** 2026-03
**Request:** Has torque drifted from baseline for any head?

---

I have everything I need. Here is the full report.

---

**Goal:** Determine whether closing torque has drifted from its historical baseline for any capping head in the March 2026 dataset.

**Data used:** Dataset pool 2026-03, covering 2026-03-01T16:00:01Z through 2026-03-03T15:49:25Z (approximately 47 hours). Tools called: `detect_drift`, `torque_statistics_per_head` (successful closures only), `torque_moving_average`, and `time_range`.

**Analyses executed:**
- Z-score drift detection per head (recent mean vs. historical baseline mean, flagged above threshold)
- Per-head torque statistics: mean, min, max, std across ~20,500 successful events per head
- Rolling (expanding) moving average of torque across the observation window to check for any gradual directional trends

---

**Findings:**

**No drift detected on any head.** The `detect_drift` tool evaluated all 36 heads (H01–H36) and returned `drift_detected: false` for every single one. Z-scores are uniformly tiny, ranging from **0.02 to 0.05** — far below the flagging threshold. Details:

| Metric | Value |
|---|---|
| Heads assessed | 36 |
| Heads flagging drift | **0** |
| Z-score range (all heads) | 0.02 – 0.05 |
| Baseline mean range across heads | 2.19 – 2.20 Nm |
| Recent mean range across heads | 2.20 Nm (all heads) |

**Per-head torque statistics** confirm an extremely tight, homogeneous fleet. All 36 heads share a mean of **2.20 Nm** on successful closures, with standard deviations ranging from **0.06 to 0.09 Nm**. The fleet is remarkably consistent. Two minor observations worth noting but not alarming:
- **H11 and H15** show a baseline mean of **2.19 Nm** vs. the 2.20 Nm majority — a negligible 0.01 Nm difference, well within normal variation.
- **H35** has the highest recorded single-event torque peak of **2.42 Nm** (vs. a fleet high of 2.21–2.34 Nm for other heads), and **H16** peaked at **2.34 Nm**. These are upper-range outliers but do not shift the head means.

**Moving average** readings in the first minutes of the dataset (the sample returned) show all heads tracking tightly between ~2.194 and ~2.203 Nm, with no directional trend visible across the observation window. One data point for H35 shows a transient spike to **2.236 Nm** in the moving average at 17:38:40 on March 1 — consistent with that head's higher max torque — but it appears to be a single event, not a sustained shift.

---

**Confidence & limits:**
- The dataset spans only ~47 hours (3 days, partial). The "historical baseline" used by `detect_drift` is derived from the same pool, not from a separate long-term reference dataset. If a systematic shift occurred before March 1, it would not be detectable here.
- The moving average was truncated to the first 200 rows of 739,675 — it covers only the very start of the observation window, so any drift occurring later in the month (e.g. March 2 or 3) is not visible in that sample.
- All z-scores are so close to zero that the fleet looks unusually uniform — this may reflect high manufacturing consistency, or it may indicate that the data resolution (torque encoded at 0.01 Nm precision) compresses variance.

---

**Next checks:**
1. **Investigate H35's torque peak (2.42 Nm):** Run `statistical_outliers` or `list_closure_events` filtered to H35 to confirm whether the high-max is a single spike or a recurring pattern — a sustained upper drift could precede mechanical wear.
2. **Extend the observation window:** Once more daily files from March are available, re-run `detect_drift` against a longer pool so the baseline and recent windows are truly distinct time periods rather than sub-segments of the same 47-hour stretch.
3. **Plot H35 torque over time:** Run `plot_torque_over_time(head_id="H35")` to visually confirm whether the 2.42 Nm peak is isolated or part of an emerging upward trend.

---

## Tool-call trace


1. `detect_drift({})`

2. `time_range({})`

3. `torque_statistics_per_head({'successful_only': True})`

4. `torque_moving_average({})`

