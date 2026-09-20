This message has a line count at the bottom

# ADD AN `--l0churn` VIEW TO archive_counts.py

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Purpose | Measure how often the ADR-124 flat-side recentre re-prices L0, per instance. EURGBP has run with `stranded (6) < width + deadband (7)` since deployment, so its stranded gate is permanently open and the deadband is its only brake | Derived from source, `grind_engine.mqh:1482-1524` |
| Decides | ADR-153's open question: the bound for `stranded`, and whether EURGBP's width or deadband changes on Wednesday | `docs/architecture/ADR-153-geometry-independence.md` |
| Baseline | pipshed `origin/main` at `4e5bef4` | read by Claude |
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

Add, in the style of the existing `CARRY_SQL` / `ROLLOVERS_SQL` constants,
ONE query that carries its own denominator so no eyeballing across tables
is needed:

    L0_CHURN_SQL = """
    WITH modify_counts AS (
        SELECT instance_id,
               count(*)                                   AS modifies,
               count(*) FILTER (WHERE NOT ok)             AS failed,
               min(received_at)                           AS first_seen,
               max(received_at)                           AS last_seen
        FROM send_logs
        WHERE action ILIKE '%MODIFY%'
          AND layer_index = 0
          AND role = 'ENT'
        GROUP BY instance_id
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

**`active_days` comes from the UNFILTERED CTE, deliberately.** Counting
distinct dates inside the filtered CTE would divide by the days on which a
modify happened, not the days the instance was running, and would inflate
the rate for an instance that churns sporadically -- 5 modifies on one
volatile day would read as 5.0/day rather than 0.5/day over ten. It counts
days the instance sent ANY request, which also handles instances that
started mid-window (the NZD pairs began 2026-09-16).

**The join direction matters.** It starts from `total_counts` and LEFT
JOINs the modifies, so an instance with ZERO layer-0 modifies still
appears with 0. That is the whole point of the query: the comparison is
EURGBP against instances that do not churn, and an inner join would erase
the baseline and return a single row.

**The `role = 'ENT'` filter is conditional on the vocabulary check** in
FAILURE MODES below. Without it an exit modify at layer 0 would be counted
as recentre churn. If `role` turns out not to carry `'ENT'`, STOP and
report the real values rather than dropping the filter or guessing a
replacement -- an unfiltered count answers a different question.

Wire `--l0churn` exactly like `--carry`: execute, print the header row and
the rows, return 0, with an empty message of
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

- **Run the vocabulary check FIRST, before writing the query:**
  `SELECT DISTINCT action, role, count(*) FROM send_logs GROUP BY 1,2
  ORDER BY 3 DESC`. Paste the result in the response. The query above
  assumes `action` carries a MODIFY-like value and `role` carries `'ENT'`.
  If either is wrong, STOP and report the real vocabulary rather than
  guessing a filter or dropping one.
- `layer_index` is null on modify rows: STOP, report, and include the
  distinct-value query above.
- `send_logs` retention (14 days) leaves under two days of data: report
  the window alongside the numbers.

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

Line count: 142
