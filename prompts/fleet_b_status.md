This message has a line count at the bottom

# PIPSHED: FLEET B STATUS ENDPOINT (READ-ONLY), TESTS FIRST

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Why | Fleet B (fxmatrix `docs/architecture/fleet-b.md`, `85cd555`) runs 11 instances on IC Markets demo 53066709 with instance ids `GRIND_<PAIR>_OPTB` / `_ALTB`. Their heartbeats already arrive (`/api/telemetry/push` stores any instance id under `fxmatrix:state:<id>`), but no public view lists them | verified by Claude |
| Base | pipshed `main` at `e475506` | verified |
| Existing route | `public_grind_status` (`app.py` ~1229-1276): loops `GRIND_INSTANCES`, `_summarize_grind_instance_state(inst, raw)` (name-agnostic), `_public_grind_instance_fields(card)`, rings via `_build_grind_ring_summaries` | verified |
| Constraint | `GRIND_INSTANCES` is used in ~12 places (dashboard, aggregates, scalps). It must NOT change; Fleet B must not appear in any existing route | design |

## FOR GEMINI

- **Q1.** A separate read-only route with its own instance list, instead of
  making the dashboard fleet-aware tonight. The dashboard view of Fleet B
  is deferred. Accept?

## BRANCH

`feat/fleet-b-status` from `origin/main` (`e475506`). TWO commits (tests +
stub, then implementation), push after each. No merge.

## 1. BUILD (`app.py`)

- Constant, directly below `GRIND_ALT_INSTANCES`:
  `GRIND_B_INSTANCES = ["GRIND_GBPUSD_OPTB", "GRIND_EURUSD_OPTB",
  "GRIND_EURGBP_OPTB", "GRIND_AUDCAD_OPTB", "GRIND_AUDCHF_OPTB",
  "GRIND_CADCHF_OPTB", "GRIND_NZDCHF_OPTB", "GRIND_NZDCAD_OPTB",
  "GRIND_AUDNZD_OPTB", "GRIND_AUDNZD_ALTB", "GRIND_NZDCAD_ALTB"]`
- Pure helper `_fleet_summary(cards, raws)` -> dict:
  `instances_total` (len), `instances_live` (cards with `connection ==
  "live"`), `halted_instances` (ids with `halted is True`),
  `open_layers_long` / `open_layers_short` / `scalps` (sums over live
  cards, treating None as 0), `net_mtm` / `realised_pnl_today` (sums over
  live cards, rounded to 2 dp), `api_count` (max over live cards, or
  None), and `account_login` / `account_balance` / `account_equity` taken
  from the FIRST raw heartbeat (in `GRIND_B_INSTANCES` order) that parses
  as JSON and carries those keys (None if none does).
- Route, two decorators exactly like `public_grind_status`:
  `/api/g/<token>/status_b` and `/api/g/<token>/status_b/<path:_ignored>`.
  Wrong token -> 404 `{"error": "not found"}`. Otherwise for each id in
  `GRIND_B_INSTANCES`: `raw = r.get(f"fxmatrix:state:{inst}")`,
  `card = _summarize_grind_instance_state(inst, raw)`. Payload:
  `{"generated_at": <UTC ISO Z>, "fleet": "B", "instances": {inst:
  _public_grind_instance_fields(card)}, "summary": _fleet_summary(...)}`.
  No-cache headers via `_apply_no_cache_headers`. Exceptions: log and 500
  `{"error": "internal error"}`, as the existing route does.
- Add the route to the module docstring's route list.

## 2. TESTS (commit 1) -- new `scripts/verify_fleet_b_status.py`

Style of `scripts/verify_daily_snapshots.py`: each check in try/except,
prints `FBn OK: ...` / `FBn FAIL: ...`, ends with exactly one line
`SUMMARY passed=<p> failed=<f>`, exit 1 on any failure. FakeRedis, no
network.

- **FB1** `GRIND_B_INSTANCES` has 11 ids, all ending `OPTB` or `ALTB`, and
  none is in `GRIND_INSTANCES`.
- **FB2** `GRIND_INSTANCES` is unchanged: 18 ids, none ending `B`.
- **FB3** route with a wrong token -> 404.
- **FB4** with two B heartbeats in FakeRedis (one live with
  `net_mtm` 1.25, `scalps` 2, `open_layers_long` 1, `account_login`
  53066709, `account_balance` 10000.0, `account_equity` 10001.25; one with
  no key at all): 200, `fleet == "B"`, 11 instances listed, `summary`
  `instances_live == 1`, `net_mtm == 1.25`, `scalps == 2`,
  `open_layers_long == 1`, `account_login == 53066709`; and a cycle-3
  heartbeat (`GRIND_GBPUSD_OPT`) also in FakeRedis is NOT listed.
- **FB5** a B heartbeat in FakeRedis does NOT appear in the existing
  `/status` (regression lock: cycle 3's view is unchanged).
- **FB6** `_fleet_summary` with a halted live card lists it in
  `halted_instances`; with no live cards, sums are 0 and `api_count` is
  None.

**Stub (commit 1):** `GRIND_B_INSTANCES = []`, `_fleet_summary` returns
`{}`, the route exists and returns 404 for every token. Report the stub
run's full output. Expected exactly: FB1, FB4, FB6 FAIL; FB2, FB3, FB5 OK
(regression locks); `SUMMARY passed=3 failed=3`. Real branch: `SUMMARY passed=6
failed=0`, and every existing `scripts/verify_*.py` ends exactly as on
`main` (three known pre-existing failures: `verify_fxgrind_panel.py`,
`verify_grind_exposure.py`, `verify_grind_pnl_render.py` -- backlog C33).

## NEGATIVE SPACE

- Do not change `GRIND_INSTANCES`, `GRIND_RINGS`, any existing route, the
  dashboard, the archive worker, or migrations.
- No auth change: same public token as `/status`.
- ASCII only. Stage by exact path. No merge, no PR.

## REPLY

ONLY the two commit hashes and `git ls-remote origin
refs/heads/feat/fleet-b-status`.

Line count: 96
