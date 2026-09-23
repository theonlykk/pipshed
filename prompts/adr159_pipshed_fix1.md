This message has a line count at the bottom

# PIPSHED: ADR-159 FIX 1 -- DS11 MUST GUARD THE OFFSET; ROLL BACK AFTER A SWALLOWED BUILD ERROR

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Base | `feat/adr159-daily-critical` at `f73147e` (commits `166c226`, `b519383`, `f73147e`) | verified by Claude on origin |
| Stub check | `SUMMARY passed=0 failed=16` at `166c226` | reproduced by Claude |
| Real branch | `SUMMARY passed=16 failed=0` at `f73147e`; migration `002` identical to spec; no hard-coded offset | reproduced by Claude |
| Pre-existing failures | `verify_fxgrind_panel.py`, `verify_grind_exposure.py`, `verify_grind_pnl_render.py` fail identically on `main` `b81a339`; NOT caused by this branch; out of scope here | verified by Claude |
| **Finding 1** | **Mutation test: with the broker offset disabled in `_scalp_utc_close` (`broker_utc_offset_s = 0` as its first line), DS11 still passes -- and so does the whole suite.** The implementation is correct; the test no longer guards it. Commit 2 moved DS11's times (fixing a real stub bug: 00:00 broker on 24 Sep is 21:00Z on the 23rd, i.e. inside) and in doing so lost the spec's row "inside only once the 10800 s offset is applied" | Claude |
| **Finding 2** | `try_daily_build` and `try_critical_build` swallow non-connection exceptions WITHOUT `conn.rollback()` (as does the pre-existing `try_carry_build`, which they copy). After a failed statement Postgres keeps the transaction aborted: every scheduled build then fails until a batch arrives, fails once, and rolls back. On a quiet weekend the banner would stay "stale" for hours | Claude |

## FOR GEMINI

- **Q1.** Fix 2 also changes the pre-existing `try_carry_build` (same
  bug, same one-line fix). Accept the change to existing code, or leave
  carry alone?

## BRANCH

Same branch, `feat/adr159-daily-critical`. THREE new commits on top of
`f73147e`; push after each. No merge.

1. **Tests.** DS11 extended and DS17 added (below). Run the verify
   script and record the output. Expected: DS11 OK (the code is already
   right), DS17 FAIL -- `SUMMARY passed=16 failed=1`.
   Then, WITHOUT committing, add `broker_utc_offset_s = 0` as the first
   line of `_scalp_utc_close` in `ftmo_daily.py`, run again, record
   the DS11 line (expected: `DS11 FAIL`), and revert with
   `git checkout -- ftmo_daily.py`. Confirm `git status -s` is clean.
2. **Fix.** Finding 2 (below). Expected: `SUMMARY passed=17 failed=0`.
3. **Response doc** `prompts/adr159_pipshed_fix1_response.md`.

## TEST CHANGES -- `scripts/verify_daily_snapshots.py`

**DS11**, keep every existing row and add two, same account, offset 10800:

| close_time_broker | UTC | in 23 Sep FTMO day? | gross_pnl |
|---|---|---|---|
| 2026-09-24 00:30:00 | 2026-09-23 21:30Z | IN (only with the offset) | 11.0 |
| 2026-09-23 00:30:00 | 2026-09-22 21:30Z | OUT (in without the offset) | 13.0 |

New expectations: `ejected_fills == 3`, `ejected_realised == 23.0`
(5 + 7 + 11), `eject_mismatch == 1` (3 fills, 2 `EJECT_FILLED` events).
All other DS11 assertions unchanged. (Checked by Claude against `f73147e`:
the real code gives 3 / 23.0 / 1. Under the mutation the count stays 3,
because the two new rows swap places, but `ejected_realised` becomes 25.0,
so DS11 fails on the realised assertion.)

**DS17** (new): the fake connection gains `rollback_count` and a
`rollback()` that increments it. With `fail_on_sql` set to match the
daily derived SELECT, `try_daily_build(conn, fake_redis, force=True)`
returns `None` and `rollback_count == 1`. Same for `try_critical_build`
with `fail_on_sql` matching the critical SELECT (a fresh connection,
`rollback_count == 1`). Name it `DS17 OK: swallowed build errors roll
back`.

## FIX -- `archive_worker.py`

In the generic `except Exception as exc:` branch of `try_daily_build`,
`try_critical_build` and `try_carry_build`, BEFORE the `log.warning`:

```
        try:
            conn.rollback()
        except Exception:
            pass
```

The connection-error branch (`OperationalError`, `InterfaceError`) is
unchanged: it still re-raises, and the caller reconnects. Nothing else
changes.

## NEGATIVE SPACE

- No change to `ftmo_daily.py` (the mutation is local and reverted), the
  migration, `app.py`, or the dashboard.
- No change to any other check's expectations.
- Every existing `scripts/verify_*.py` must end exactly as it did at
  `f73147e`: the three pre-existing failures stay as they are, and every
  other script passes. Do not touch the three failing scripts.
- ASCII only. Stage by exact path. No merge, no PR.

## RESPONSE FORMAT

`prompts/adr159_pipshed_fix1_response.md` (commit 3): the three new
hashes AS THEY EXIST ON ORIGIN (paste `git ls-remote origin
refs/heads/feat/adr159-daily-critical` and `git log --oneline -6
origin/feat/adr159-daily-critical`); the commit-1 verify output
verbatim; the mutation run's DS11 line and SUMMARY line verbatim, plus
`git status -s` after the revert; the commit-2 verify output verbatim;
and the last line of every other `scripts/verify_*.py`. Footer: true
line count. Reply in chat with ONLY the three hashes and one line saying
they are pushed.

Line count: 99
