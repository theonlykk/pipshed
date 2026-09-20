This message has a line count at the bottom

UNVERIFIED WORKING MATERIAL -- verify against the branch, not this file.

# archive `--l0churn` -- execution report (rev 2)

## Prompt read at

Commit `400d089f5da268436af98ca800c98c5b69e543ca` (file ended with `Line count: 185`).

## Branch and commit

- Branch: `feat/archive-l0churn`
- Implementation commit on origin: `be19efc6` ( `--l0churn` in `archive_counts.py` )
- Report commit on origin: `36eb68f`

## Diff stat (commit 1)

```
 scripts/archive_counts.py | 77 +++++++++++++++++++++++++++++++++++++++++++++++
 1 file changed, 77 insertions(+)
```

## Pre-flight (failure modes)

Established vocabulary (2026-09-20, not re-guessed):

```
action | role | count
PENDING | ENT | 6591
MODIFY |  | 2430
PENDING | EXT | 1040
REMOVE |  | 662
CLOSE_BY |  | 557
```

- `PENDING` with non-null non-zero `result_order`: **1987** of **7631** (join key present; not STOP).
- Second-query match on MODIFY: **560 matched**, **1870 unmatched** of **2430** total (matched > 0; not STOP).
- **Unmatched share ~77%** -- churn counts are a **lower bound** (placements before 14-day retention window).

## `--l0churn` output

Executed on archive-worker (same code as commit, via SSH; container not redeployed):

```
instance_id | modifies | failed | per_day | active_days | all_requests | churn_pct | first_seen | last_seen
GRIND_EURGBP_ALT | 139 | 2 | 17.4 | 8 | 288 | 48.3 | 2026-09-13 21:05:00.429645+00:00 | 2026-09-14 04:41:07.887754+00:00
GRIND_AUDNZD_ALT | 15 | 0 | 3.8 | 4 | 195 | 7.7 | 2026-09-16 05:51:00.469689+00:00 | 2026-09-18 11:17:53.321787+00:00
GRIND_GBPUSD_OPT | 13 | 0 | 1.6 | 8 | 1361 | 1.0 | 2026-09-14 09:13:04.054421+00:00 | 2026-09-17 15:44:09.299813+00:00
GRIND_AUDCAD_OPT | 12 | 0 | 1.5 | 8 | 2114 | 0.6 | 2026-09-14 01:56:39.236795+00:00 | 2026-09-18 10:55:00.191541+00:00
GRIND_AUDCHF_OPT | 12 | 0 | 1.5 | 8 | 990 | 1.2 | 2026-09-14 01:36:10.128485+00:00 | 2026-09-18 11:28:11.182872+00:00
GRIND_GBPUSD_ALT | 12 | 0 | 1.5 | 8 | 1307 | 0.9 | 2026-09-14 06:18:26.983536+00:00 | 2026-09-17 16:08:36.296493+00:00
GRIND_EURUSD_ALT | 10 | 0 | 1.3 | 8 | 268 | 3.7 | 2026-09-14 06:19:12.218136+00:00 | 2026-09-16 18:36:57.657226+00:00
GRIND_EURUSD_OPT | 10 | 0 | 1.4 | 7 | 502 | 2.0 | 2026-09-14 13:49:45.747933+00:00 | 2026-09-16 21:06:34.391981+00:00
GRIND_AUDNZD_OPT | 9 | 0 | 2.3 | 4 | 776 | 1.2 | 2026-09-16 05:25:36.606262+00:00 | 2026-09-18 11:26:25.301195+00:00
GRIND_NZDCAD_OPT | 9 | 0 | 2.3 | 4 | 282 | 3.2 | 2026-09-16 05:21:03.589204+00:00 | 2026-09-16 19:18:08.605957+00:00
GRIND_NZDCAD_ALT | 8 | 0 | 2.0 | 4 | 150 | 5.3 | 2026-09-16 05:33:19.832586+00:00 | 2026-09-18 13:50:51.315456+00:00
GRIND_AUDCAD_ALT | 6 | 0 | 0.8 | 8 | 883 | 0.7 | 2026-09-14 02:22:58.118740+00:00 | 2026-09-18 10:55:01.160974+00:00
GRIND_CADCHF_OPT | 6 | 0 | 0.8 | 8 | 817 | 0.7 | 2026-09-14 09:23:04.422140+00:00 | 2026-09-16 20:26:31.149287+00:00
GRIND_AUDCHF_ALT | 3 | 0 | 0.4 | 7 | 139 | 2.2 | 2026-09-14 02:47:10.093829+00:00 | 2026-09-17 07:49:03.543346+00:00
GRIND_CADCHF_ALT | 3 | 0 | 0.4 | 8 | 130 | 2.3 | 2026-09-14 09:28:33.577078+00:00 | 2026-09-14 16:54:11.378924+00:00
GRIND_EURGBP_OPT | 2 | 0 | 0.3 | 8 | 1078 | 0.2 | 2026-09-14 11:05:52.293953+00:00 | 2026-09-17 15:39:47.482130+00:00

modifies_total | matched | unmatched
2430 | 560 | 1870
```

After deploy, operator can run:

`railway ssh --service archive-worker -i "$HOME\.ssh\id_ed25519" python scripts/archive_counts.py --l0churn`

Line count: 73
