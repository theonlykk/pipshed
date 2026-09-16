This message has a line count at the bottom

# CURSOR PROMPT -- PIPSHED: RENDER RING SECTIONS FROM GRIND_RINGS

## AUDIT TRAIL

| Item | Value |
|---|---|
| Repo | **theonlykk/pipshed** -- NOT fxmatrix |
| Design source | Claude (lead engineer), 2026-09-16 |
| Baseline commit | confirm origin/main HEAD before starting |
| Branch | fix/dashboard-rings-from-config |
| Urgency | a halt banner currently cannot render for the nzd_ext ring |

## THE DEFECT

`GRIND_RINGS` in `app.py` was extended with `nzd_ext` and four instances were
added to `GRIND_INSTANCES`. The API reflects this correctly -- the public
status endpoint returns the ring, its arms, and its `halted_instances`.

**The dashboard does not, because the ring list is duplicated twice more in
`templates/dashboard.html`:**

  1. A JavaScript constant at ~line 1165, `const GRIND_RINGS = {...}`, with
     three rings hardcoded and their instance IDs listed by hand.
  2. Three hardcoded HTML blocks, `<div class="grind-ring-section"
     id="grindRing-eur_gbp_usd">` at ~line 895, `-aud_cad_chf` at ~941 and
     `-nzdchf_pilot` at ~987. Each is ~46 lines carrying ~20 element ids
     suffixed with the ring id.

The comment above the Python `GRIND_RINGS` claims "one edit here adds a ring
everywhere downstream". That is false and has been for some time.

**This is live-impacting right now.** Two instances are halted in `nzd_ext`
(`GRIND_NZDCAD_ALT` I3_LONG_NAKED, `GRIND_AUDNZD_ALT` I3_SHORT_NAKED). The
API reports both. The dashboard shows neither, because there is no
`grindRing-nzd_ext` element for the JS to write into.

**The JS render loop is already generic** -- `GRIND_RING_IDS.forEach(...)`
builds ids as `'grindCards-' + ringId` and calls
`renderGrindArmCompareColumn(arm, ringId, ...)`. It would render `nzd_ext`
correctly today if the elements existed. Only the DATA and the MARKUP are
hardcoded. Do not change the render functions.

## DESIGN

Drive both duplicates from the Python config, so `GRIND_RINGS` in `app.py`
becomes the single source.

### Edit 1 -- pass the rings into the template, app.py

The route is currently:

    return render_template("dashboard.html")

Build an enriched mapping and pass it. The JS constant needs an `instances`
key that the Python `GRIND_RINGS` entries do not carry -- it is derived via
`instances_for_ring`. So:

    rings_ctx = {
        ring_id: {
            "label": ring["label"],
            "instances": instances_for_ring(ring_id),
        }
        for ring_id, ring in GRIND_RINGS.items()
    }
    return render_template("dashboard.html", rings=rings_ctx)

Preserve `GRIND_RINGS` insertion order -- the dashboard renders rings in that
order and `nzd_ext` must appear after `nzdchf_pilot`, as it does in `app.py`.

### Edit 2 -- the JS constant becomes generated

Replace the whole literal `const GRIND_RINGS = { ... };` block (through its
closing `};`) with:

    const GRIND_RINGS = {{ rings|tojson }};

Leave `GRIND_RING_IDS`, `GRIND_INSTANCES`, `currentInstance`,
`GRIND_TRACKED_COUNT` and `API_DAILY_LIMIT` exactly as they are -- they
derive from `GRIND_RINGS` and must stay derived.

### Edit 3 -- the three HTML blocks become one Jinja loop

Replace the three `grind-ring-section` blocks with a single:

    {% for ring_id, ring in rings.items() %}
    ... one copy of the block, with every occurrence of the hardcoded ring
        id replaced by {{ ring_id }} and the human label by {{ ring.label }}
    {% endfor %}

Take the `aud_cad_chf` block as the template -- compare all three first and
**STOP and report if they differ in anything other than the ring id and the
label**. If they diverge, the loop would silently change behaviour for one
of them.

Every `id="grindXxx-aud_cad_chf"` becomes `id="grindXxx-{{ ring_id }}"`.
There are about 20 distinct id prefixes; miss one and that element silently
stops updating for every ring.

## TESTS -- COMMIT 1, MUST NOT ALL PASS

Add `scripts/verify_dashboard_rings.py`, following the existing verify-script
style (plain asserts, `def main()`, non-zero exit on failure). It reads
`templates/dashboard.html` as TEXT -- no browser, no rendering.

  1. For every id in `pipshed.GRIND_RINGS`, the rendered template contains
     `id="grindRing-<ring_id>"`. Render via Flask's test client or
     `flask.render_template` inside an app context.
  2. The rendered output contains no literal `grindRing-aud_cad_chf` coming
     from a hardcoded source -- assert the COUNT of `grind-ring-section`
     occurrences equals `len(GRIND_RINGS)`.
  3. The RAW template file contains at most ONE `grind-ring-section`
     literal -- proving the three blocks were collapsed, not copied.
  4. The raw template does not contain the string `GRIND_NZDCHF_OPT` --
     proving the JS instance lists are no longer hardcoded.
  5. For each ring, the rendered output contains
     `id="grindCards-<ring_id>"`, `id="grindOptStatus-<ring_id>"` and
     `id="grindAltStatus-<ring_id>"`.

Expected at commit 1: checks 1, 2, 3, 4 and 5 FAIL for `nzd_ext`, and 3 and
4 FAIL outright. Report exactly which.

Expected at commit 2: all pass.

### Regression

Run at BOTH commits and report:

    python3 scripts/verify_nzd_ext_registration.py
    python3 scripts/verify_grind_display_gaps.py
    python3 scripts/verify_dashboard_rings.py

The first two must pass at both commits. **If either changes state, STOP.**

Note `verify_fxgrind_panel.py` fails at the baseline in at least one
environment, unrelated to this change. Run it, report its result at both
commits, but do not attempt to fix it here.

## COMMITS

Commit 1: `scripts/verify_dashboard_rings.py` only.
Commit 2: `app.py` and `templates/dashboard.html`.

## NEGATIVE SPACE

Do not:

  - touch the fxmatrix repo
  - change `GRIND_RINGS` or `GRIND_INSTANCES` in `app.py`
  - change any JS render function -- `renderGrindArmCompareColumn`,
    `renderGrindInstanceCards`, `renderAggregate`, `renderGrindBookTables`
  - change `GRIND_RING_IDS`, `GRIND_INSTANCES`, `currentInstance`,
    `GRIND_TRACKED_COUNT` or `API_DAILY_LIMIT` in the JS
  - change any CSS class name or any element id PREFIX
  - change any route other than the dashboard render call
  - deploy or trigger a Railway redeploy
  - `git add .` or `git add -u`
  - merge, rebase, amend, force-push, or open a PR

## FAILURE MODES

STOP and report, do not improvise, if:

  - the three `grind-ring-section` blocks differ in anything but ring id and
    label
  - any element id prefix appears in one block and not the others
  - `verify_nzd_ext_registration.py` or `verify_grind_display_gaps.py`
    changes state between commits
  - the rendered `grind-ring-section` count is not `len(GRIND_RINGS)`

## SELF-REVIEW BEFORE COMMITTING

  - the raw template has exactly one `grind-ring-section` literal
  - grep the raw template for `aud_cad_chf`, `eur_gbp_usd`, `nzdchf_pilot`,
    `nzd_ext`: zero matches
  - grep the raw template for `GRIND_GBPUSD_OPT`: zero matches
  - the Jinja loop preserves `GRIND_RINGS` insertion order
  - ASCII only in the new verify script

## RESPONSE FORMAT

Open with "This message has a line count at the bottom" and close with the
exact total. Branch from origin/main, make the two commits, and PUSH to
origin. Report the branch name, both commit hashes AS THEY EXIST ON ORIGIN,
`git diff --stat` per commit, the full diff of commit 2, and the output of
all four verify scripts at each commit. Do not abbreviate diffs.

Line count: 189
