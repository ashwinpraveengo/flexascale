# Demo and rehearsal runs (kept for transparency, excluded from all reports)

Runs started from the dashboard to rehearse or give the live demo (`docs/FINAL_DEMO_RUNBOOK.md`). They are not part of the planned benchmark (3 repeats × 6 scenarios of default HPA vs Auto, `logs/live_auto_batch_v2.out`), but the Comparison page and `scripts/build_live_report.py` pair any complete run that started at minimum replicas, so they are kept here rather than in `reports/experiments/`.

| Run | Reason |
| :--- | :--- |
| 20261026-133325-shopping-auto-flash_sale | Demo rehearsal (Auto, flash_sale, 25 users, 300 s), started at 13:33 with *Comparable start* on. Moved here by a decision taken before its result was inspected. |

## 20261026-133325-shopping-auto-flash_sale

Completed with a settled start and verified cleanup. Result for reference: 13.7 req/s, 0.39% failures, p95 700 ms, 1.94 replica-hours, peak 32 replicas.

In `reports/experiments/` it would have been paired with `20261026-110001-shopping-hpa-flash_sale` (2.5 h earlier, already the baseline of repeat 3): replica-hours +3.5%, p95 +55.6% (450 → 700 ms), failures −0.01 pp. As a 19th Auto pair, the pooled result would be replica-hours −3.5% [−6.1 … −0.9], p95 +5.6% [−6.2 … +17.3], failures −0.07 pp [−0.12 … −0.02]: still *Beats HPA on cost* under `docs/POLICY_V6.md` §3.1, against −3.9% [−6.5 … −1.3] for the 18 planned pairs.

## 2026-10-27 02:58–03:41: live plumbing smoke test of the v7 arms (docs/POLICY_V7.md §5)

`calibration_steady` at 45 users for 180 s (not an evaluation condition), with a provisional snapshot of `focal_bc_s1`
and temporary lab variants: `20261027-025811-shopping-flexascale-calibration_steady` (v7 model alone),
`20261027-031135-shopping-auto-calibration_steady` (Auto with the v7 model), `20261027-032629-shopping-flexascale-calibration_steady`
(the rule `limit_target(0.6/0.3)`). Only the plumbing was checked; the outcomes are not used anywhere.

## 2026-10-27 19:31–20:12: setup pilot for the clock-controlled replication (docs/POLICY_V7.md §3.7)

steady_browsing × {HPA-tuned, FlexaScale-RL} × 2 blocks under the `performance` power profile, to check that the shop ran
equally fast in both arms where scaling is identical: `20261027-193148-shopping-hpa_tuned-steady_browsing`,
`20261027-193749-shopping-flexascale-steady_browsing`, `20261027-194920-shopping-flexascale-steady_browsing`,
`20261027-200050-shopping-hpa_tuned-steady_browsing`. Not counted in any comparison.
