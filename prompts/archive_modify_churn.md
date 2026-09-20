This message has a line count at the bottom

# ADD AN `--l0churn` VIEW TO archive_counts.py

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Purpose | Measure how often the ADR-124 flat-side recentre re-prices L0, per instance. EURGBP has run with `stranded (6) < width + deadband (7)` since deployment, so its stranded gate is permanently open and the deadband is its only brake | Derived from source, `grind_engine.mqh:1482-1524` |
| Decides | ADR-153's open question: the bound for `stranded`, and whether EURGBP's width or deadband changes on Wednesday | `docs/architecture/ADR-153-geometry-independence.md` |
| Baseline | pipshed `origin/main` at `1cb2d2f` | read by Claude |
| Supersedes | the first attempt, which correctly STOPPED: `prompts/archive_l0churn_response.md` on `feat/archive-l0churn`. Its vocabulary check is the input to this version | done |
| Scope | ONE new flag and ONE new SQL constant in `scripts/archive_counts.py`. Read-only | this spec |
| Review | Read-only analytics on the shadow DB. DeepSeek not required | ARCHITECT s2 |

## BRANCH

`feat/archive-l0churn` from `origin/main`, in the **pipshed** repo. Two
commits. Push. Do NOT merge, do NOT open a PR.

1. `L0_CHURN_SQL` constant plus the `--l0churn` flag wired into `main()`.
2. Nothing else. If commit 1 is complete, stop.

## CONTEXT

`send_logs` holds one row per order request:
`instance_id, magic, received_at, action, order_type, side, layer_index,
role, requested_price, volume, order_ticket, ok, retcode, duration_ms`.

An L0 recentre appears as a MODIFY on an ENT order at layer_index 0. The
exact `action` and `role` string values are NOT assumed by this spec --
see FAILURE MODES.

## DESIGN

**Why the first attempt stopped** (`prompts/archive_l0churn_response.md`,
branch `feat/archive-l0churn`): all 2430 MODIFY rows carry NULL `role` and
NULL `layer_index`. Root cause, from the EA source:
`Grind_ArchiveSendLogFields` (`fxmatrix` `ea/grind_archive.mqh:346-365`)
derives `slot`, `side`, `role` and `layer_index` by PARSING `req.comment`,
and an MT5 `TRADE_ACTION_MODIFY` request carries no comment. So those
columns cannot be populated on a modify. **This is not a pipeline defect
and needs no EA change.**

**The identity is recoverable by a join.** A modify carries the ticket of
the order it modifies in `order_ticket`; the placement that created that
order carries the same ticket in `result_order`, along with the role and
layer parsed from its comment. So: modify -> placement, on the ticket.

    L0_CHURN_SQL = """
    WITH placements AS (
        SELECT result_order AS ticket,
               instance_id,
               role,
               layer_index
        FROM send_logs
        WHERE action = 'PENDING'
          AND ok
          AND result_order IS NOT NULL
          AND result_order <> 0
    ),
    modify_counts AS (
        SELECT s.instance_id,
               count(*)                       AS modifies,
               count(*) FILTER (WHERE NOT s.ok) AS failed,
               min(s.received_at)             AS first_seen,
               max(s.received_at)             AS last_seen
        FROM send_logs s
        JOIN placements p
          ON p.ticket = s.order_ticket
         AND p.instance_id = s.instance_id
        WHERE s.action ILIKE '%MODIFY%'
          AND p.role = 'ENT'
          AND p.layer_index = 0
        GROUP BY s.instance_id
    ),
    total_counts AS (
        SELECT instance_id,
               count(*)                          AS all_requests,
               count(DISTINCT received_at::date) AS active_days
        FROM send_logs
        GROUP BY instance_id
    )
    SELECT t.instance_id,
           COALESCE(m.modifies, 0)                        AS modifies,
           COALESCE(m.failed, 0)                          AS failed,
           round(COALESCE(m.modifies, 0)::numeric
                 / NULLIF(t.active_days, 0), 1)           AS per_day,
           t.active_days,
           t.all_requests,
           round((COALESCE(m.modifies, 0)::numeric
                  / NULLIF(t.all_requests, 0)) * 100, 1)  AS churn_pct,
           m.first_seen,
           m.last_seen
    FROM total_counts t
    LEFT JOIN modify_counts m USING (instance_id)
    ORDER BY modifies DESC, t.instance_id
    """

**Three properties of that query, none of them accidental:**

- **`active_days` comes from the UNFILTERED CTE.** Counting distinct dates
  inside the filtered CTE would divide by the days a modify happened
  rather than the days the instance ran, inflating the rate for an
  instance that churns sporadically -- 5 modifies on one volatile day
  would read 5.0/day instead of 0.5/day over ten. It counts days the
  instance sent ANY request, which also handles instances that started
  mid-window (the NZD pairs began 2026-09-16).
- **The final join starts from `total_counts` and LEFT JOINs**, so an
  instance with ZERO layer-0 modifies still appears with 0. That is the
  point of the query: the comparison is EURGBP against instances that do
  not churn, and an inner join would erase the baseline.
- **The placement join is on ticket AND instance**, because tickets are
  unique per account but the guard against a mismatched row costs nothing.

**A second query, printed after the first, bounds what the join misses:**

    SELECT count(*)                                      AS modifies_total,
           count(*) FILTER (WHERE p.ticket IS NOT NULL)   AS matched,
           count(*) FILTER (WHERE p.ticket IS NULL)       AS unmatched
    FROM send_logs s
    LEFT JOIN (
        SELECT result_order AS ticket FROM send_logs
        WHERE action = 'PENDING' AND ok AND result_order IS NOT NULL
    ) p ON p.ticket = s.order_ticket
    WHERE s.action ILIKE '%MODIFY%'

Unmatched modifies are expected -- `send_logs` retains 14 days, so an
order placed before the window has no placement row. **If unmatched is a
large share of the total, say so in the report; the churn counts are then
a lower bound.**

Wire `--l0churn` exactly like `--carry`: execute both queries, print the
header row and the rows of each, return 0. Empty message for the first:
`no rows in send_logs yet.`

## NEGATIVE SPACE

- Do NOT touch the EA repo, the dashboard, the worker or any migration.
- Do NOT write to the database. The connection is already read-only; keep
  it that way.
- Do NOT change any existing flag, SQL constant or table list.
- Do NOT deploy or restart anything on Railway.
- No `git add .`; stage by exact path. No merge, no PR.
- ASCII only.

## FAILURE MODES -- STOP AND REPORT

The vocabulary was established on 2026-09-20 and is NOT to be re-guessed:
`action` is one of `PENDING`, `MODIFY`, `REMOVE`, `CLOSE_BY`; `role` is
`ENT` or `EXT` and is populated ONLY on `PENDING` rows.

- **`PENDING` rows do not carry `result_order`**, or it is null/zero on
  most of them: STOP. The join has no key and the query cannot be built as
  specified. Report counts of `PENDING` rows with and without
  `result_order`.
- **`matched` in the second query is zero:** STOP and report. It means
  modify `order_ticket` values do not correspond to placement
  `result_order` values, and the whole approach is wrong.
- **The distinct `action` / `role` values differ from the list above:**
  STOP and report the real ones.
- `send_logs` holds under two days of data: report the window alongside
  the numbers.

## SELF-REVIEW

Re-read the diff before committing: one file, one new constant, one new
flag, no existing line altered except the `argparse` block and the
`main()` dispatch.

## RESPONSE FORMAT

Write the full response to `prompts/archive_l0churn_response.md` on the
same branch: the commit hash AS IT EXISTS ON ORIGIN, the diff stat, the
distinct `action`/`role` values you found, and the OUTPUT of
`railway ssh --service archive-worker -i "$HOME\.ssh\id_ed25519"
python scripts/archive_counts.py --l0churn` if the operator has run it,
or a note that it is awaiting the operator. Open with
`This message has a line count at the bottom` and close with
`Line count: N`.

Reply in chat with ONLY: the branch name, the commit hash on origin, and
one line saying the report is pushed.

Line count: 185
