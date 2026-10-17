CHECKSUM: There is a checksum at the bottom. If you do not reach it, stop and tell the user before proceeding.

# Review of `prompts/cursor_twoarm_fleets.md` at `aa3cada`

Reviewed commit: `aa3cada87da86ff6095d62a80cdd0d9ebe9bb8c5` (`main`).

---

## 1. Audit Trail Verification (`s1`, `P1`–`P8`)

### P1 — Instance lists and retired set (`app.py` 76–174)
- **Claim:** `GRIND_A_INSTANCES` (18), `GRIND_B_INSTANCES` (11), `GRIND_C_INSTANCES` (11), `GRIND_D_INSTANCES` (11); `GRIND_RETIRED_INSTANCES` (10: four from A + six `AUDNZD`/`NZDCAD` `ALT{B,C,D}` twins); `GRIND_A_STRIP_INSTANCES` (7, hand-written); `GRIND_{B,C,D}_STRIP_INSTANCES` derived as `[i for i in GRIND_X_INSTANCES if i not in GRIND_RETIRED_INSTANCES]` (9 each today).
- **Check against `aa3cada`:** **VERIFIED.**
  - `app.py:76-93`:
    ```python
    GRIND_A_INSTANCES = [
        "GRIND_GBPUSD_OPT", "GRIND_GBPUSD_ALT", ..., "GRIND_AUDNZD_OPT", "GRIND_AUDNZD_ALT",
    ]
    ```
    (18 instances).
  - `app.py:95-107`: `GRIND_B_INSTANCES` (9 `_OPTB` + `"GRIND_AUDNZD_ALTB"`, `"GRIND_NZDCAD_ALTB"` = 11).
  - `app.py:109-121`: `GRIND_C_INSTANCES` (9 `_OPTC` + `"GRIND_AUDNZD_ALTC"`, `"GRIND_NZDCAD_ALTC"` = 11).
  - `app.py:123-135`: `GRIND_D_INSTANCES` (9 `_OPTD` + `"GRIND_AUDNZD_ALTD"`, `"GRIND_NZDCAD_ALTD"` = 11).
  - `app.py:146-157`:
    ```python
    GRIND_RETIRED_INSTANCES = frozenset({
        "GRIND_AUDNZD_ALT",
        "GRIND_NZDCAD_ALT",
        "GRIND_AUDCAD_OPT",
        "GRIND_NZDCHF_OPT",
        # C119 (3 Oct): the six IC twins retired at the Monday build
        "GRIND_AUDNZD_ALTB",
        "GRIND_NZDCAD_ALTB",
        "GRIND_AUDNZD_ALTC",
        "GRIND_NZDCAD_ALTC",
        "GRIND_AUDNZD_ALTD",
        "GRIND_NZDCAD_ALTD",
    })
    ```
  - `app.py:160-168`: `GRIND_A_STRIP_INSTANCES` (hand-written list of 7 `_OPT` IDs).
  - `app.py:172-174`:
    ```python
    GRIND_B_STRIP_INSTANCES = [i for i in GRIND_B_INSTANCES if i not in GRIND_RETIRED_INSTANCES]
    GRIND_C_STRIP_INSTANCES = [i for i in GRIND_C_INSTANCES if i not in GRIND_RETIRED_INSTANCES]
    GRIND_D_STRIP_INSTANCES = [i for i in GRIND_D_INSTANCES if i not in GRIND_RETIRED_INSTANCES]
    ```

### P2 — `FLEET_STRIP` (`app.py` 176–230)
- **Claim:** `FLEET_STRIP` has four entries (`A`, `B`, `C`, `D`), each with `letter`, `name`, `broker`, `url`, `instances` (`GRIND_X_STRIP_INSTANCES`), `lattice`, `daily_loss_limit_usd`, `cycle_start`, `start_balance`, `placeholder`.
- **Check against `aa3cada`:** **VERIFIED** (note: entry `"D"` also carries `"built": True` at `app.py:228`).
  - `app.py:176-230`:
    ```python
    FLEET_STRIP = [
        {
            "letter": "A",
            "name": "FTMO-IC 1514878887",
            "broker": "FTMO",
            "url": "https://pipshed.com",
            "instances": GRIND_A_STRIP_INSTANCES,
            "lattice": True,
            "daily_loss_limit_usd": 5000.0,
            "cycle_start": "2026-10-08",
            "start_balance": 100000.0,
            "placeholder": False,
        },
        ...
    ```
    (`"A"` at `app.py:177-191`, `"B"` at `app.py:192-202`, `"C"` at `app.py:203-214`, `"D"` at `app.py:215-229`).

### P3 — `GRIND_FLEET` and `GRIND_FLEET_INSTANCES` (`app.py` 232–248)
- **Claim:** `GRIND_FLEET` is read from `os.environ.get("GRIND_FLEET", "A").strip().upper()`; `GRIND_FLEET_INSTANCES` maps `A`, `B`, `C`, `D` to `GRIND_X_INSTANCES` (the full list, used by the fleet's own page and its `/api/g/<token>/status_<x>`); unknown values fall back to `A`.
- **Check against `aa3cada`:** **VERIFIED.**
  - `app.py:233-248`:
    ```python
    _grind_fleet_raw = os.environ.get("GRIND_FLEET", "A").strip().upper()
    GRIND_FLEET_INSTANCES = {
        "A": GRIND_A_INSTANCES,
        "B": GRIND_B_INSTANCES,
        "C": GRIND_C_INSTANCES,
        "D": GRIND_D_INSTANCES,
    }
    if _grind_fleet_raw in GRIND_FLEET_INSTANCES:
        GRIND_FLEET = _grind_fleet_raw
    else:
        logging.getLogger(__name__).warning(
            "Unknown GRIND_FLEET=%r; falling back to A", _grind_fleet_raw
        )
        GRIND_FLEET = "A"

    GRIND_INSTANCES = GRIND_FLEET_INSTANCES[GRIND_FLEET]
    ```
  - Also `app.py:921-1018` (`_build_fleet_b_status_payload`, `_build_fleet_c_status_payload`, `_build_fleet_d_status_payload`) read `GRIND_B_INSTANCES`, `GRIND_C_INSTANCES`, and `GRIND_D_INSTANCES`.

### P4 — `_grind_slot` and `GRIND_OPT_INSTANCES` / `GRIND_ALT_INSTANCES` (`app.py` 254–264)
- **Claim:** `_grind_slot(inst)` strips a trailing fleet letter from `OPTB`, `ALTB`, `OPTC`, `ALTC`, `OPTD`, `ALTD` so `GRIND_OPT_INSTANCES` and `GRIND_ALT_INSTANCES` work on any fleet.
- **Check against `aa3cada`:** **VERIFIED** (`_grind_slot` starts at line 253).
  - `app.py:253-264`:
    ```python
    def _grind_slot(inst):
        parts = inst.split("_")
        slot = parts[2] if len(parts) > 2 else ""
        if slot in ("OPTB", "ALTB", "OPTC", "ALTC", "OPTD", "ALTD"):
            return slot[:-1]
        return slot


    GRIND_OPT_INSTANCES = [i for i in GRIND_INSTANCES if _grind_slot(i) == "OPT"]
    GRIND_ALT_INSTANCES = [i for i in GRIND_INSTANCES if _grind_slot(i) == "ALT"]
    ```

### P5 — Placeholder handling (`app.py` 1264–1300, 1540)
- **Claim:** `_fleet_strip_placeholder_card(entry)` already builds a placeholder card when `entry.get("placeholder")` is true (`"NOT ATTACHED"` if `entry.get("built")` else `"NOT BUILT"`); `_fleet_books` and the S/R table skip entries where `entry.get("placeholder")` is true (`[e for e in FLEET_STRIP if not e.get("placeholder")]`).
- **Check against `aa3cada`:** **VERIFIED** (`_fleet_strip_placeholder_card` is at `app.py:1264-1307`; S/R table skip is at `app.py:1994`).
  - `app.py:1264-1307`:
    ```python
    def _fleet_strip_placeholder_card(entry):
        lim = entry.get("daily_loss_limit_usd")
        return {
            "letter": entry["letter"],
            ...
            "placeholder": True,
            "badge": "NOT ATTACHED" if entry.get("built") else "NOT BUILT",
            "status": "placeholder",
            ...
        }
    ```
  - `app.py:1540` (`_fleet_books`): `letters = [e["letter"] for e in FLEET_STRIP if not e.get("placeholder")]` and `app.py:1544-1545`: `if entry.get("placeholder"): continue`.
  - `app.py:1994` (`_fleet_scalps_per_roll`): `entries = [e for e in FLEET_STRIP if not e.get("placeholder")]`.
  - Also skipped at `app.py:1604,1608` (`_fleet_gaps`), `app.py:1735` (`_fleet_quotes`), `app.py:1796` (`_fleet_geometry`), `app.py:1854` (`_strip_states`), `app.py:1896` (`_build_fleet_strip_payload`), and `ejection_view.py:1092` (`ejection_views_for_fleets`).

### P6 — `GRIND_RINGS` and `_grind_instances_for_ring` (`app.py` 2059–2085, 2161–2164)
- **Claim:** `GRIND_RINGS` groups a fleet page's instances by symbol (`eur_gbp_usd`, `aud_cad_chf`, `nzdchf_pilot`, `nzd_ext`); `_grind_instances_for_ring(ring_id)` returns `[inst for inst in GRIND_INSTANCES if _grind_symbol(inst) in syms]`; `GBPCHF` is not in any ring's `symbols` today, so on C's page (`GRIND_FLEET=C`) `GRIND_GBPCHF_OPTC` and `GRIND_GBPCHF_ALTC` would not appear in any ring unless `GBPCHF` is in a ring's `symbols`.
- **Check against `aa3cada`:** **VERIFIED** (`GRIND_RINGS` ends at line 2086).
  - `app.py:2059-2086`:
    ```python
    GRIND_RINGS = {
        "eur_gbp_usd": {
            "label": "Ring 1 — EUR / GBP / USD",
            "symbols": ["GBPUSD", "EURUSD", "EURGBP"],
            "currencies": ["EUR", "GBP", "USD"],
        },
        "aud_cad_chf": { ... "symbols": ["AUDCAD", "AUDCHF", "CADCHF"], ... },
        "nzdchf_pilot": { ... "symbols": ["NZDCHF"], ... },
        "nzd_ext": { ... "symbols": ["NZDCAD", "AUDNZD"], ... },
    }
    ```
  - `app.py:2161-2164`:
    ```python
    def _grind_instances_for_ring(ring_id):
        syms = set(GRIND_RINGS[ring_id]["symbols"])
        return [inst for inst in GRIND_INSTANCES if _grind_symbol(inst) in syms]
    ```

### P7 — Telemetry push/action and Railway services (`app.py` 4001–4060; `RAILWAY.md`)
- **Claim:** `/api/telemetry/push` takes `instance_id = payload.get("instance_id", "unknown")` and writes `fxmatrix:state:{instance_id}` to Redis without checking `GRIND_INSTANCES`; `/api/telemetry/action` queues archive events for any `instance_id`. All EAs on every fleet push to `https://pipshed.com`; each fleet's own page is a separate Railway web service on the same repo and Redis (`pipshed` = A at `pipshed.com`, `pipshed Copy` = B, `pipshed Fleet C` = C, `pipshed Fleet D` = D) with `GRIND_FLEET=<letter>` and `GRIND_FLEET_LABEL=Fleet <letter>`.
- **Check against `aa3cada`:** **VERIFIED.**
  - `app.py:4001-4019`:
    ```python
    @app.route("/api/telemetry/push", methods=["POST"])
    def telemetry_push():
        ...
        instance_id = payload.get("instance_id", "unknown")
        ...
        r.set(f"fxmatrix:state:{instance_id}", json.dumps(payload), ex=REDIS_TTL_SECONDS)
    ```
  - `app.py:4022-4055`: `telemetry_action()` validates and enqueues archive items via `_enqueue_archive_items(r, items, received_at)` (`app.py:3947-3987`) without filtering `instance_id` against `GRIND_INSTANCES`.
  - `RAILWAY.md:14-18`:
    ```markdown
    | `pipshed` | web (`gunicorn app:app`) | `pipshed.com` — all EA pushes, archive intake, and Fleet A's page (`GRIND_FLEET` unset = `A`) |
    | `pipshed Copy` | web (`gunicorn app:app`) | `pipshed-copy-production.up.railway.app` — Fleet B's page (`GRIND_FLEET=B`, `GRIND_FLEET_LABEL=Fleet B`) |
    | `pipshed Fleet C` | web (`gunicorn app:app`) | `pipshed-fleet-c-production.up.railway.app` — Fleet C's page (`GRIND_FLEET=C`, `GRIND_FLEET_LABEL=Fleet C`) |
    | `pipshed Fleet D` | web (`gunicorn app:app`) | `pipshed-fleet-d-production.up.railway.app` — Fleet D's page (`GRIND_FLEET=D`, `GRIND_FLEET_LABEL=Fleet D`) |
    ```

### P8 — Existing checks that pin today's lists
- **Claim:**
  - `scripts/verify_fleet_strip.py` 306 (strip letters)
  - `scripts/verify_c119_twins_retired.py` 118 (`len(lst) == 11` on B, C, D)
  - `scripts/verify_c113_fleet_books.py` 155–158 (`want_fleets` and `want_rows`)
  - `scripts/verify_fleet_c_status.py` 33–45 (`GRIND_C_INSTANCES`)
  - `scripts/verify_fleet_d_status.py` 41–53 (`GRIND_D_INSTANCES`)
  - `scripts/verify_c137_sr_table.py` 433 (fleets ABCD)
- **Check against `aa3cada`:** **LINE CITATIONS VERIFIED, BUT THE LIST IS INCOMPLETE.**
  - `scripts/verify_fleet_strip.py:306`: `if letters != ["A", "B", "C", "D"]:`
  - `scripts/verify_c119_twins_retired.py:118`: `if len(lst) != 11 or not {f"GRIND_AUDNZD_ALT{letter}", f"GRIND_NZDCAD_ALT{letter}"} <= set(lst):`
  - `scripts/verify_c113_fleet_books.py:155-158`:
    ```python
    want_fleets = ["A", "B", "C", "D"]
    want_rows = ["GBPUSD", "EURUSD", "EURGBP", "AUDCHF", "CADCHF",
                 "NZDCAD", "AUDNZD", "AUDCAD", "NZDCHF"]
    ```
  - `scripts/verify_fleet_c_status.py:33-45`: `GRIND_C_INSTANCES = [ ... ]` (11 instances).
  - `scripts/verify_fleet_d_status.py:41-53`: `GRIND_D_INSTANCES = [ ... ]` (11 instances).
  - `scripts/verify_c137_sr_table.py:433`: `if not sr or sr.get("available") is not True or sr.get("fleets") != ["A", "B", "C", "D"]:` (Note: line 433 stays `["A", "B", "C", "D"]` because E is a placeholder, whereas `scripts/verify_c137_sr_table.py:453` pins `"GRIND_NZDCAD_OPTD"` on D's strip and **does** break!).
  - **Missing from P8:** Multiple other assertions inside those same files and across **9 other `scripts/verify_*.py` files** also pin today's C/D strip lists or retired set and fail when `s2` is applied (detailed in Section 3 below).

---

## 2. Answers to Reviewer Questions (`s7`, `Q1`–`Q5`)

### Q1: Are the instance lists in `s2` exact against the operator's plan (`EURUSD`, `AUDCAD`, `GBPCHF` OPT+ALT on C = 6; `GBPUSD`, `EURUSD`, `EURGBP`, `AUDCAD`, `AUDCHF`, `CADCHF` OPT+ALT on D = 12)?
- **Yes, the instance lists and strip derivations in `s2` are exact:**
  - **Fleet C:** `GRIND_C_INSTANCES` (11 today at `app.py:109-121` + 4 appended = 15) minus `GRIND_RETIRED_INSTANCES` (2 existing C twins `GRIND_AUDNZD_ALTC`, `GRIND_NZDCAD_ALTC` + 7 newly retired `_OPTC` = 9 retired on C) yields `GRIND_C_STRIP_INSTANCES` of **6** in exact order:
    `["GRIND_EURUSD_OPTC", "GRIND_AUDCAD_OPTC", "GRIND_EURUSD_ALTC", "GRIND_AUDCAD_ALTC", "GRIND_GBPCHF_OPTC", "GRIND_GBPCHF_ALTC"]`.
  - **Fleet D:** `GRIND_D_INSTANCES` (11 today at `app.py:123-135` + 6 appended = 17) minus `GRIND_RETIRED_INSTANCES` (2 existing D twins `GRIND_AUDNZD_ALTD`, `GRIND_NZDCAD_ALTD` + 3 newly retired `_OPTD` = 5 retired on D) yields `GRIND_D_STRIP_INSTANCES` of **12** in exact order:
    `["GRIND_GBPUSD_OPTD", "GRIND_EURUSD_OPTD", "GRIND_EURGBP_OPTD", "GRIND_AUDCAD_OPTD", "GRIND_AUDCHF_OPTD", "GRIND_CADCHF_OPTD", "GRIND_GBPUSD_ALTD", "GRIND_EURUSD_ALTD", "GRIND_EURGBP_ALTD", "GRIND_AUDCAD_ALTD", "GRIND_AUDCHF_ALTD", "GRIND_CADCHF_ALTD"]`.
  - **Total `GRIND_RETIRED_INSTANCES`:** 10 today + 7 from C + 3 from D = **20**.
- **Crucial side effect to note:** Because `GRIND_C_STRIP_INSTANCES` and `GRIND_D_STRIP_INSTANCES` now include live `_ALTC` and `_ALTD` instances, `_fleet_book_pair` (`app.py:1508-1513`) maps every `ALT*` instance to `<PAIR>*` (`EURUSD*`, `AUDCAD*`, `GBPCHF*`, `GBPUSD*`, `EURGBP*`, `AUDCHF*`, `CADCHF*`) in the cross-fleet `books`, `gaps`, `quotes`, and `geometry` tables (see Section 3.1).

### Q2: Does adding `GBPCHF` to `GRIND_RINGS["eur_gbp_usd"]["symbols"]` (`s2`) break any check on Fleet A's or Fleet B's ring layout?
- **No check on Fleet A's or Fleet B's ring layout breaks.**
  - `_grind_instances_for_ring(ring_id)` (`app.py:2161-2164`) filters `GRIND_INSTANCES` by `_grind_symbol(inst) in syms`. Neither `GRIND_A_INSTANCES` (`app.py:76-93`) nor `GRIND_B_INSTANCES` (`app.py:95-107`) has a `GBPCHF` instance, so `_grind_instances_for_ring("eur_gbp_usd")` is unchanged when `GRIND_FLEET` is `A` or `B` (`verify_nzd_ext_registration.py`, `verify_dashboard_rings.py`, `verify_grind_arm_cards.py`, `verify_fxgrind_panel.py`, and `verify_fleet_select.py` all pass on A and B).
- **However, it DOES break `check_fc6` in `scripts/verify_fleet_c_status.py:146-163` (and the new `_ALTD` instances break `check_fd6` in `scripts/verify_fleet_d_status.py:182-197`):**
  - On Fleet C (`GRIND_FLEET=C`), `eur_gbp_usd` gains `GRIND_EURUSD_ALTC`, `GRIND_GBPCHF_OPTC`, and `GRIND_GBPCHF_ALTC`, so `eur_opt_live` becomes `4` (was `3`), `eur_alt_live` becomes `2` (was `0`), and `len(eur_instances)` becomes `6` (was `3`).
  - On Fleet D (`GRIND_FLEET=D`), `eur_gbp_usd` gains `GRIND_GBPUSD_ALTD`, `GRIND_EURUSD_ALTD`, and `GRIND_EURGBP_ALTD`, so `eur_alt_live` becomes `3` (was `0`).

### Q3: Does `_fleet_strip_placeholder_card` (`app.py` 1264–1300) need any key on E's `FLEET_STRIP` entry beyond the ten in `s3`, or any change to its code?
- **No.** `_fleet_strip_placeholder_card(entry)` (`app.py:1264-1307`) only accesses `entry.get("daily_loss_limit_usd")`, `entry["letter"]`, `entry["name"]`, `entry["broker"]`, `entry.get("url")`, and `entry.get("built")`. With `"placeholder": True` and `"built"` omitted (falsy), it returns `"badge": "NOT BUILT"` and `"status": "placeholder"` with no code change.
- Every consumer of `FLEET_STRIP` (`_fleet_books` at `app.py:1540,1544`, `_fleet_gaps` at `app.py:1604,1608`, `_fleet_quotes` at `app.py:1735`, `_fleet_geometry` at `app.py:1796`, `_strip_states` at `app.py:1854`, `_build_fleet_strip_payload` at `app.py:1896`, `_fleet_scalps_per_roll` at `app.py:1994`, and `ejection_views_for_fleets` at `ejection_view.py:1092`) already skips entries where `entry.get("placeholder")` is truthy.
- (Visual note: `.fleet-strip` in `templates/dashboard.html:398,409` has `grid-template-columns: repeat(4, 1fr)`, so on `>=1600px` screens the 5th card wraps to a second row unless changed to `repeat(5, 1fr)`.)

### Q4: Are there any other places in `app.py`, `templates/dashboard.html`, `sr_table.py`, `archive_worker.py` or `ftmo_daily.py` that name `A` / `B` / `C` / `D` or `OPTB`..`ALTD` and need `E` / `OPTE` / `ALTE`?
- **Yes — two places have bugs/omissions:**
  1. **`templates/dashboard.html:2292-2299` (`fleetStripPair`) and `2333-2339` (`fleetStripAlertLabel`):**
     ```javascript
     function fleetStripPair(inst) {
       if (!inst) return '';
       var s = String(inst);
       if (s.indexOf('GRIND_') === 0) s = s.slice(6);
       s = s.replace(/_(OPTB|ALTB|OPTC|ALTC|OPT|ALT)$/, '');
       return s;
     }
     ...
     function fleetStripAlertLabel(a) {
       if (!a) return '';
       var p = fleetStripPair(a.instance_id);
       var inst = a.instance_id || '';
       var isAlt = /_(ALT|ALTB|ALTC)$/.test(inst);
       if (isAlt && p) p += '*';
     ```
     Both regexes stopped at `C` (`OPTB|ALTB|OPTC|ALTC` and `ALT|ALTB|ALTC`) — they are missing **`OPTD|ALTD`** as well as **`OPTE|ALTE`**! Because `s2` puts 6 `_ALTD` instances on Fleet D's strip, any strip alert on D renders `"GBPUSD_OPTD"` / `"GBPUSD_ALTD"` instead of `"GBPUSD"` / `"GBPUSD*"`. Updating line 2296 to `/_(OPT[BCDE]?|ALT[BCDE]?)$/` and line 2337 to `/_ALT[BCDE]?$/` fixes both D and E.
  2. **`app.py:251` (`GRIND_DEFAULT_INSTANCE = GRIND_INSTANCES[0]`):**
     When `GRIND_FLEET=E` and `GRIND_E_INSTANCES = []` (`s4`), `GRIND_INSTANCES[0]` raises `IndexError: list index out of range` at module import time (see Section 3.2).
- **`sr_table.py`, `archive_worker.py`, `ftmo_daily.py`, and `ejection_view.py` need no changes for `E` / `OPTE` / `ALTE`:**
  - `sr_table.py:32-44` (`pair_of`) uses `parts[2].startswith("ALT")`, which already handles `OPTE` and `ALTE`.
  - `archive_worker.py:725-727` (`_book_side_mtm`) checks `parts[0] == "GRIND"` and `parts[2] in ("L", "S")`, independent of slot suffix.
  - `ftmo_daily.py` has no fleet-letter or slot-suffix checks.
  - (`app.py:3905, 3924-3931` `api_public_grind_ejection` only accepts `fleet in ("A", "B", "C", "D")`, which is fine while E is a placeholder.)

### Q5: Is any Railway change needed for this commit?
- **No.** `pipshed` (`pipshed.com`) accepts any `instance_id` on `/api/telemetry/push` (`app.py:4001-4019`) and `/api/telemetry/action` (`app.py:4022-4055`); `pipshed Fleet C` (`GRIND_FLEET=C`) and `pipshed Fleet D` (`GRIND_FLEET=D`) already exist (`RAILWAY.md:14-18`); and Fleet E is a placeholder (`"placeholder": True`), so no `pipshed Fleet E` Railway service is needed until Fleet E is built.

---

## 3. Everything in `s2`–`s5` That Is Wrong, Ambiguous, or Would Make Cursor Improvise

### 3.1. [WRONG in `s5` / Major Behaviour Clash in `s2`] `_fleet_book_pair` turns every `_ALTC` and `_ALTD` strip instance into a `<PAIR>*` row (17 rows, not 10)
- **What `s5` says (`prompts/cursor_twoarm_fleets.md:89-92`):**
  > "`verify_c113_fleet_books.py` 155-158: `want_rows` gains `GBPCHF` at the END (rows follow first appearance across the non-placeholder strips A, B, C, D: A's seven, B adds AUDCAD and NZDCHF, C adds GBPCHF); `want_fleets` unchanged (E is a placeholder)."
- **Why this is false against `app.py` at `aa3cada`:**
  - `app.py:1508-1513` defines:
    ```python
    def _fleet_book_pair(instance_id):
        """GRIND_EURUSD_OPTB -> EURUSD; a twin (ALT slot) -> EURUSD*."""
        parts = instance_id.split("_")
        if len(parts) < 3 or parts[0] != "GRIND":
            return instance_id
        return parts[1] + ("*" if parts[2].startswith("ALT") else "")
    ```
  - `_fleet_books` (`app.py:1547-1551`), `_fleet_gaps` (`app.py:1611-1615`), `_fleet_quotes` (`app.py:1739-1743`), and `_fleet_geometry` (`app.py:1827-1832`) iterate `entry["instances"]` across `A`, `B`, `C`, `D` and key rows by `_fleet_book_pair(inst)`.
  - Because `s2` puts `GRIND_EURUSD_ALTC`, `GRIND_AUDCAD_ALTC`, `GRIND_GBPCHF_ALTC` into `GRIND_C_STRIP_INSTANCES` and `GRIND_GBPUSD_ALTD`, `GRIND_EURUSD_ALTD`, `GRIND_EURGBP_ALTD`, `GRIND_AUDCAD_ALTD`, `GRIND_AUDCHF_ALTD`, `GRIND_CADCHF_ALTD` into `GRIND_D_STRIP_INSTANCES`, `_fleet_book_pair(inst)` returns starred pair names (`EURUSD*`, `AUDCAD*`, `GBPCHF*`, `GBPUSD*`, `EURGBP*`, `AUDCHF*`, `CADCHF*`) for all of them!
  - Consequently, `books["rows"]` does **not** have 10 rows (`want_rows + ["GBPCHF"]`); it has **17 rows**:
    `["GBPUSD", "EURUSD", "EURGBP", "AUDCHF", "CADCHF", "NZDCAD", "AUDNZD", "AUDCAD", "NZDCHF", "EURUSD*", "AUDCAD*", "GBPCHF", "GBPCHF*", "GBPUSD*", "EURGBP*", "AUDCHF*", "CADCHF*"]`.
  - Furthermore, in `scripts/verify_c113_fleet_books.py`, three other checks also fail when `s2` is applied:
    - **`BK2` (`scripts/verify_c113_fleet_books.py:188`):** checks `("NZDCHF", "D"): {"live": True, "long": 0, "short": 9, "net": -9, "mtm": -3.0, "skew": -1.0}`, which becomes `None` because `GRIND_NZDCHF_OPTD` is retired in `s2`.
    - **`BK3` (`scripts/verify_c113_fleet_books.py:199`):** checks `_cell(books, "NZDCHF", "C") != {"live": False}`, which becomes `None` because `GRIND_NZDCHF_OPTC` is retired in `s2`.
    - **`BK4` (`scripts/verify_c113_fleet_books.py:214`):** checks `want_c = {"long": 16, "short": 16, "net": 0, "mtm": -4.0, "live": 8}` (from 8 live of 9 C strip instances), which becomes `{"long": 12, "short": 12, "net": 0, "mtm": -3.0, "live": 6}` (all 6 of C's new strip instances live in `fixture()`).

### 3.2. [WRONG in `s4`] `GRIND_FLEET=E` crashes `app.py` at import time with `IndexError`
- **What `s4` says (`prompts/cursor_twoarm_fleets.md:79-81`):**
  > "Define `GRIND_E_INSTANCES = []` and `GRIND_E_STRIP_INSTANCES = []` beside the other fleet lists; add `"E": GRIND_E_INSTANCES` to `GRIND_FLEET_INSTANCES` (`app.py` 234-239) so `GRIND_FLEET=E` is a valid fleet setting when E's service is created."
- **Why this crashes:** At `app.py:248-251`:
  ```python
  GRIND_INSTANCES = GRIND_FLEET_INSTANCES[GRIND_FLEET]

  # Default instance selected in dashboard dropdown
  GRIND_DEFAULT_INSTANCE = GRIND_INSTANCES[0]
  ```
  When `GRIND_FLEET=E` and `GRIND_E_INSTANCES = []`, `GRIND_INSTANCES[0]` raises `IndexError: list index out of range` on import. `s4` must specify `GRIND_DEFAULT_INSTANCE = GRIND_INSTANCES[0] if GRIND_INSTANCES else None` (or `""`).

### 3.3. [BUG in `s2`] Fleet C's `GRIND_DEFAULT_INSTANCE` (`app.py:251`) becomes a retired instance (`GRIND_GBPUSD_OPTC`)
- Because `s2` keeps the old 11 instances at the start of `GRIND_C_INSTANCES`, `GRIND_C_INSTANCES[0]` is `"GRIND_GBPUSD_OPTC"`, which `s2` adds to `GRIND_RETIRED_INSTANCES`.
- When `GRIND_FLEET=C`, `GRIND_DEFAULT_INSTANCE = GRIND_INSTANCES[0]` (`app.py:251`) selects `"GRIND_GBPUSD_OPTC"` (retired, no heartbeat in Redis), causing Fleet C's page to open on a dead instance and show `CONNECTION LOST` in the header badge — the exact C109 bug (`scripts/verify_c109_default_instance.py:1-14, 102-110`).
- `app.py:251` should choose the first non-retired instance:
  `GRIND_DEFAULT_INSTANCE = next((i for i in GRIND_INSTANCES if i not in GRIND_RETIRED_INSTANCES), GRIND_INSTANCES[0] if GRIND_INSTANCES else None)`.
  (Note: `check_dd2` in `scripts/verify_c109_default_instance.py:82` asserts `d["default"] == d["first"]`, which would then need to expect the first non-retired instance or `GRIND_C_INSTANCES` would need a live instance at index 0.)

### 3.4. [INCOMPLETE in `s5`] Unmentioned failing assertions inside the 5 files listed in `s5`
`s5` tells Cursor to update only specific lines in 5 files and says *"Do not touch any other file."* Even within those 5 files, the lines named in `s5` are not the only lines that fail:
1. **`scripts/verify_fleet_strip.py`** (`s5` only cites line 306):
   - `lines 41-53` (`GRIND_C_INSTANCES`) and `lines 56-68` (`GRIND_D_INSTANCES`): local 11-instance lists used by `_apply_fixture_fb2` (`lines 204-213`) and imported by 5 other test files.
   - `check_fs3` (`lines 358-359`): asserts `instances_live == 9` and `instances_total == 9` on Fleet C (now **6/6**).
   - `check_fs3d` (`lines 385-386`): asserts `instances_live == 9` and `instances_total == 9` on Fleet D (now **12/12**).
   - `check_fs4` subcheck 3 (`lines 422-432`): pushes a stale heartbeat to `"GRIND_GBPUSD_OPTC"` and expects C to be `DEGRADED` with a red `STALE` alert for `"GRIND_GBPUSD_OPTC"`. Because `"GRIND_GBPUSD_OPTC"` is retired from `GRIND_C_STRIP_INSTANCES` in `s2`, C ignores it and `FS4` fails.
   - `check_fs6` (`lines 487-524`): seeds `QUARANTINE_HALT` on `"GRIND_CADCHF_OPTC"` and `QUARANTINE_ENTER` on `"GRIND_AUDCHF_OPTC"` and expects 2 `EVENT` alerts on Fleet C's strip card. Both instances are retired from `GRIND_C_STRIP_INSTANCES` in `s2`, so `c_events` is `[]` and `FS6` fails.
   - `check_fs9` subchecks 2 & 3 (`lines 610-628`): uses `"GRIND_GBPUSD_OPTC"` (missing heartbeat) and `"GRIND_NZDCHF_OPTC"` (`book=None`) to test C's strip book completeness; both are retired from `GRIND_C_STRIP_INSTANCES` in `s2`, so `FS9` fails.
2. **`scripts/verify_c119_twins_retired.py`** (`s5` only cites line 118 `TR6`):
   - `check_tr1` (`line 63`): asserts `got != CYCLE3 | TWINS` (exact equality with 10 retired IDs, not `not (CYCLE3 | TWINS <= got)`).
   - `check_tr2` (`lines 71-75`): asserts `entry["instances"] == [f"GRIND_{p}_OPT{entry['letter']}" for p in PAIRS]` for all of `"BCD"` (false for C and D under `s2`).
   - `check_tr3` (`lines 82-86`): asserts `instances_total == 9` and `instances_live == 9` for all of `"BCD"` (C is 6, D is 12 under `s2`).
   - `check_tr5` (`lines 100-109`): asserts no row in `books`, `gaps`, or `quotes` ends with `"*"` (false under `s2` because C's and D's strips have `_ALTC` and `_ALTD` instances).
3. **`scripts/verify_c113_fleet_books.py`** (`s5` only cites lines 155–158):
   - `BK1` (`lines 155-158`), `BK2` (`line 188`), `BK3` (`line 199`), and `BK4` (`line 214`) all fail (see Section 3.1).
4. **`scripts/verify_fleet_c_status.py`** (`s5` only cites lines 33–45):
   - `check_fc1` (`line 54`: `len(insts) != 11`), `check_fc3` (`line 77`: `len(instances) != 11`), `check_fc5` (`lines 132-142`: `len(opt) != 9` and `set(alt) != {"GRIND_AUDNZD_ALTC", "GRIND_NZDCAD_ALTC"}`), `check_fc6` (`lines 153-162`: `eur_opt_live != 3 or eur_alt_live != 0`), and `check_fc7` (`lines 175-187`: strip list `!= 9 OPTC` and `instances_live != 9`) all fail.
5. **`scripts/verify_fleet_d_status.py`** (`s5` only cites lines 41–53):
   - `check_fd1` (`lines 60, 72`: `len(insts) != 11` and strip list `!= 9 OPTD`), `check_fd2` (`lines 85, 94`: `instances_total != 9` and `instances_live != 9`), `check_fd5` (`line 147`: `len(instances) != 11`), and `check_fd6` (`lines 185-196`: `set(alt) != {"GRIND_AUDNZD_ALTD", "GRIND_NZDCAD_ALTD"}` and `eur_alt_live != 0`) all fail.

### 3.5. [MISSING FROM `s5`] 9 other existing `scripts/verify_*.py` suites break when `s2` is applied
Because `s5` says *"Do not touch any other file"*, Cursor is forbidden from updating the following **9 verification scripts** that fail as a direct result of `s2`:
1. **`scripts/verify_c108_retired_critical.py` (`check_rc6`, lines 31–35, 97–99):** asserts `set(pipshed.GRIND_RETIRED_INSTANCES) == RETIRED` (the 10 IDs from C108/C119). Fails when `GRIND_RETIRED_INSTANCES` grows to 20.
2. **`scripts/verify_critical_resolved.py` (`check_cr2`, `check_cr3`, `check_cr4`, lines 55–58, 104–136):** uses `"GRIND_GBPUSD_OPTC"` to test that halted (`CR2`), `invariant_ok=False` (`CR3`), and missing-heartbeat (`CR4`) instances are **not** marked `resolved: True`. Because `s2` adds `"GRIND_GBPUSD_OPTC"` to `GRIND_RETIRED_INSTANCES`, `app.py:3811-3814` marks it `resolved: True` unconditionally, failing `CR2`, `CR3`, and `CR4` (and `scripts/verify_c131_reroll_resolved.py` `check_rr7` at line 222, which runs `verify_critical_resolved.py`).
3. **`scripts/verify_c90_d_commission.py` (`check_dm1`, `check_dm2`, `check_dm4`, lines 35, 87–105, 119–126):** uses `DUP_INST = "GRIND_NZDCAD_OPTD"`, which `s2` retires. `DM1` and `DM2` fail because `GRIND_NZDCAD_OPTD` is removed from `GRIND_D_STRIP_INSTANCES` (so Fleet D's strip card has no `DUPLICATE_MAGIC` alert for it); `DM4` fails because `/critical` marks retired `GRIND_NZDCAD_OPTD` as `resolved: True` even when halted.
4. **`scripts/verify_c97_orphan_ext.py` (`check_ox1`, `check_ox2`, `check_ox6`, `check_ox8`, lines 38, 101–120, 163–192):** uses `INST = "GRIND_NZDCAD_OPTD"`, which `s2` retires from `GRIND_D_STRIP_INSTANCES`, so Fleet D's strip card emits no `ORPHAN_EXT` alerts for `INST`.
5. **`scripts/verify_c114_quote_gap.py` (`qg2_one_sided_and_absent`, line 145; `qg6`, line 208):** asserts `("NZDCHF", "C"): {"live": False}`; retiring `GRIND_NZDCHF_OPTC` in `s2` makes `cell(gaps, "NZDCHF", "C")` return `None`.
6. **`scripts/verify_c115_quotes.py` (`qt3_no_roll_left`, line 209; `qt5_virtual_offer`, lines 229–231; `qt7`, line 283):** checks `cell(q, "NZDCHF", "D")`, `cell(q, "CADCHF", "C")`, and `cell(q, "NZDCHF", "C")`; all three instances (`GRIND_NZDCHF_OPTD`, `GRIND_CADCHF_OPTC`, `GRIND_NZDCHF_OPTC`) are retired in `s2`, so all three cells become `None`.
7. **`scripts/verify_c123_side_add.py` (`sa1_short_uses_its_own_add`, line 162; `sa5`, line 193):** checks `cell(q, "CADCHF", "C")`, which becomes `None` because `GRIND_CADCHF_OPTC` is retired in `s2`.
8. **`scripts/verify_c129_geometry.py` (`gt1`, `gt2`, `gt4`, `gt5`, `gt8`, lines 153–194, 258):** checks `("GBPUSD", "C")`, `("EURGBP", "C")`, `("NZDCAD", "D")`, `("NZDCHF", "C")`, and `("NZDCHF", "D")`; all five instances are retired in `s2`, so all five cells become `None`.
9. **`scripts/verify_c137_sr_table.py` (`check_st8`, line 453; `check_st14`, lines 560–571):** `ST8` checks `_find(sr["rows"]["D"], "GRIND_NZDCAD_OPTD", "S")`, which returns `None` because `GRIND_NZDCAD_OPTD` is retired from `GRIND_D_STRIP_INSTANCES` in `s2` (`app.py:2003`); `ST14` runs `verify_fleet_strip.py`, `verify_c113_fleet_books.py`, `verify_c114_quote_gap.py`, `verify_c129_geometry.py`, `verify_c123_side_add.py`, and `verify_c90_d_commission.py` as subprocesses (and `scripts/verify_c102_ejection_index.py` `check_ei5` at line 262 runs `verify_critical_resolved.py` and `verify_c137_sr_table.py`).

CHECKSUM: This message is 331 lines.
