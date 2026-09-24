This message has a line count at the bottom

# PIPSHED: FLEET SELECTED BY ENVIRONMENT (A SECOND SERVICE SHOWS FLEET B), TESTS FIRST

## AUDIT TRAIL

| item | detail | status |
|---|---|---|
| Why | The operator wants the full dashboard for Fleet B (IC Markets 53066709, ids `GRIND_<PAIR>_OPTB` / `_ALTB`). Plan: run the SAME repo as a second Railway web service with `GRIND_FLEET=B`, sharing Redis and Postgres; the existing service is unchanged | design |
| Base | pipshed `main` at `0390f0e` | verified by Claude |
| Instance list | `GRIND_INSTANCES` (`app.py:62-81`, 18 cycle-3 ids) drives the dashboard, rings, aggregates, scalps and `/status`; `GRIND_DEFAULT_INSTANCE` (`:203`) and `GRIND_KNOWN_SYMBOLS` (`:219`) derive from it; `GRIND_B_INSTANCES` (`:87`) is defined AFTER `GRIND_OPT_INSTANCES` (`:84`) | verified |
| Arm split | OPT/ALT decided by `inst.endswith("_OPT")` / `endswith("_ALT")` at `:83-84` and `:730-731`; `_OPTB` / `_ALTB` match neither, so Fleet B's arms would be empty | verified |
| Fetches | the dashboard fetches only absolute `/api/...` paths; a second service needs NO template change for data | verified |

## FOR GEMINI

- **Q1.** Env-selected fleet in one codebase, deployed as a second service,
  instead of a `/linux` path (which would thread a fleet parameter through
  every route and fetch). Accept?
- **Q2.** An unknown `GRIND_FLEET` value falls back to fleet A (the
  cycle-3 list) with a logged warning. Accept, or should it refuse to
  start?

## BRANCH

`feat/fleet-select` from `origin/main` (`0390f0e`). TWO commits (tests +
stub, then implementation), push after each. Run
`scripts/verify_fleet_select.py` after each commit and include its full
output in the reply. No merge.

## 1. BUILD (`app.py`, commit 2)

1. Rename the current 18-id list to `GRIND_A_INSTANCES` (same ids, same
   order). Move `GRIND_B_INSTANCES` up so it is defined directly after it.
2. Then:
   `GRIND_FLEET = os.environ.get("GRIND_FLEET", "A").strip().upper()`;
   if it is neither `"A"` nor `"B"`, log a warning and use `"A"`;
   `GRIND_INSTANCES = GRIND_B_INSTANCES if GRIND_FLEET == "B" else
   GRIND_A_INSTANCES`.
3. Helper `_grind_slot(inst)`: the third `_`-separated part; if it is
   `OPTB` or `ALTB`, drop the trailing `B`. So `GRIND_GBPUSD_OPT` -> `OPT`,
   `GRIND_GBPUSD_OPTB` -> `OPT`, `GRIND_AUDNZD_ALTB` -> `ALT`.
4. Use it in BOTH arm splits: `GRIND_OPT_INSTANCES` / `GRIND_ALT_INSTANCES`
   (`:83-84`) and the ring split (`:730-731`): `_grind_slot(inst) == "OPT"`
   / `== "ALT"`.
5. Label: `GRIND_FLEET_LABEL = os.environ.get("GRIND_FLEET_LABEL", "")`.
   `dashboard()` passes `fleet_label=GRIND_FLEET_LABEL`; in
   `templates/dashboard.html`, directly after the `logo` div inside
   `.header`, add `{% if fleet_label %}<span class="fleet-label">{{
   fleet_label }}</span>{% endif %}` with a small amber style. Nothing
   else in the template changes.
6. `/status_b` keeps using `GRIND_B_INSTANCES` directly (unchanged).

## 2. TESTS (commit 1) -- new `scripts/verify_fleet_select.py`

Style of `scripts/verify_fleet_b_status.py` (`FSn OK` / `FSn FAIL`, one
final `SUMMARY passed=<p> failed=<f>`, exit 1 on failure). Each fleet case
imports `app` in a FRESH subprocess with the environment set (so module
constants are recomputed), and prints a JSON line the parent parses.

- **FS1** no `GRIND_FLEET`: 18 ids, first `GRIND_GBPUSD_OPT`, 9 OPT and 9
  ALT (regression lock).
- **FS2** `GRIND_FLEET=B`: `GRIND_INSTANCES == GRIND_B_INSTANCES` (11
  ids), `GRIND_DEFAULT_INSTANCE == "GRIND_GBPUSD_OPTB"`.
- **FS3** `GRIND_FLEET=B`: `GRIND_OPT_INSTANCES` has 9 ids, all ending
  `_OPTB`; `GRIND_ALT_INSTANCES` is exactly `GRIND_AUDNZD_ALTB`,
  `GRIND_NZDCAD_ALTB` (any order).
- **FS4** `_grind_slot` on `GRIND_GBPUSD_OPT`, `GRIND_GBPUSD_OPTB`,
  `GRIND_AUDNZD_ALT`, `GRIND_AUDNZD_ALTB` -> `OPT`, `OPT`, `ALT`, `ALT`.
- **FS5** `GRIND_FLEET=b` -> the B list; `GRIND_FLEET=X` -> the A list.
- **FS6** `GRIND_FLEET=B`: `_build_grind_ring_summaries` over live cards for
  all 11 ids gives ring `nzd_ext` whose `instances` are exactly the four
  ids `GRIND_NZDCAD_OPTB`, `GRIND_NZDCAD_ALTB`, `GRIND_AUDNZD_OPTB`,
  `GRIND_AUDNZD_ALTB` with 2 instances in each arm summary, and ring
  `eur_gbp_usd` whose `instances` are the three `_OPTB` ids with 3 in the
  OPT arm and 0 in the ALT arm. (Checking the ids, not just the counts,
  matters: the cycle-3 list also has 2 + 2 in `nzd_ext`.)
- **FS7** with `GRIND_FLEET_LABEL="Fleet B"`, GET `/` contains
  `Fleet B`; with it unset, the page does not contain `fleet-label`.

**Stub (commit 1):** `_grind_slot` returns the third part unchanged;
no fleet selection; no label. Expected exactly: FS1 OK; FS2-FS7 FAIL;
`SUMMARY passed=1 failed=6`. **Real (commit 2):** `SUMMARY passed=7
failed=0`, `verify_fleet_b_status.py` still 6/6, and every other
`scripts/verify_*.py` ends as on `main` (known failures only:
`verify_fxgrind_panel.py`, `verify_grind_exposure.py`,
`verify_grind_pnl_render.py` -- backlog C33).

## NEGATIVE SPACE

- With `GRIND_FLEET` unset, behaviour must be byte-for-byte today's.
- No change to the archive worker, migrations, `/status_b`, auth, or the
  telemetry push path. No Railway configuration from Cursor.
- ASCII only. Stage by exact path. No merge, no PR.

## REPLY

The two commit hashes, `git ls-remote origin refs/heads/feat/fleet-select`,
and the verify outputs requested above.

Line count: 101
