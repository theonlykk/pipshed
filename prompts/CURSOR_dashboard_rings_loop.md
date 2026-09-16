This message has a line count at the bottom

# CURSOR PROMPT -- PIPSHED: RENDER RING SECTIONS FROM GRIND_RINGS (REV 2)

## AUDIT TRAIL

| Item | Value |
|---|---|
| Repo | **theonlykk/pipshed** -- NOT fxmatrix |
| Design source | Claude (lead engineer), 2026-09-16 |
| Review | Gemini approved rev 1, 2026-09-16 |
| Rev 2 | Claude verified rev 1 against source at 58bea78; four corrections, listed below |
| Baseline commit | pipshed origin/main `58bea78` -- confirm HEAD before starting |
| Branch | fix/dashboard-rings-from-config |
| Urgency | the dashboard cannot render the nzd_ext ring, including a halt banner |

### Rev 2 corrections (verified against source, not design changes)

| # | Rev 1 said | Source says | Fix |
|---|---|---|---|
| C1 | helper `instances_for_ring` | the function is `_grind_instances_for_ring` (app.py ~185) | use the real name |
| C2 | raw template has at most one `grind-ring-section` literal | CSS selectors `.grind-ring-section` at ~264 and ~269 also contain it; checks 2 and 3 could never pass | count `class="grind-ring-section"` instead |
| C3 | blocks differ only in ring id and label | the label line is `Ring 1 <sep> EUR / GBP / USD`; the ring NUMBER also differs, and `{{ ring.label }}` alone would drop it | use `loop.index` for the number |
| C4 | two nzd_ext instances are halted | they halted at 12:55Z and 12:59Z (archive ea_events) and were reinitialised by 14:32Z; none halted since | stated as history, not current state |

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
     `-nzdchf_pilot` at ~987. Each is ~46 lines carrying element ids
     suffixed with the ring id.

The comment above the Python `GRIND_RINGS` claims "one edit here adds a ring
everywhere downstream". That is false and has been for some time.

**Consequence, observed 2026-09-16:** GRIND_NZDCAD_ALT and GRIND_AUDNZD_ALT
halted at 12:55Z and 12:59Z. The API reported both. The dashboard showed
neither, because there is no `grindRing-nzd_ext` element for the JS to write
into, and both sat halted for about 90 minutes.

**The JS render loop is already generic** -- `GRIND_RING_IDS.forEach(...)`
builds ids as `'grindCards-' + ringId` and calls
`renderGrindArmCompareColumn(arm, ringId, ...)`. It would render `nzd_ext`
correctly today if the elements existed. Only the DATA and the MARKUP are
hardcoded. Do not change the render functions.

## DESIGN

Drive both duplicates from the Python config, so `GRIND_RINGS` in `app.py`
becomes the single source.

### Edit 1 -- pass the rings into the template, app.py

The route (`@app.route("/")`, function `dashboard`, ~line 1503) is currently:

    return render_template("dashboard.html")

Build an enriched mapping and pass it. The JS constant needs an `instances`
key that the Python `GRIND_RINGS` entries do not carry -- it is derived via
the existing helper `_grind_instances_for_ring`. So:

    rings_ctx = {
        ring_id: {
            "label": ring["label"],
            "instances": _grind_instances_for_ring(ring_id),
        }
        for ring_id, ring in GRIND_RINGS.items()
    }
    return render_template("dashboard.html", rings=rings_ctx)

Preserve `GRIND_RINGS` insertion order -- the dashboard renders rings in that
order and `nzd_ext` must appear after `nzdchf_pilot`, as it does in `app.py`.

If `_grind_instances_for_ring` does not exist at the baseline, STOP and
report. Do not write a replacement.

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
    ... one copy of the block ...
    {% endfor %}

Take the `aud_cad_chf` block as the template. Inside it:

  - every occurrence of the ring id `aud_cad_chf` becomes `{{ ring_id }}`
  - the label line currently reads, in the `instance-group-label` div,
    `Ring 2`, then a separator character, then `AUD / CAD / CHF`. It becomes
    `Ring {{ loop.index }}`, the SAME separator character copied byte for
    byte from the existing file, then `{{ ring.label }}`. Do not retype the
    separator; it is not ASCII.

Expected rendered labels: Ring 1 EUR / GBP / USD, Ring 2 AUD / CAD / CHF,
Ring 3 NZDCHF (pilot), Ring 4 NZD extension (each with the separator).

**Compare all three blocks first. STOP and report if they differ in anything
other than the ring id, the ring number and the label text.** Pre-verified at
58bea78: they do not. If that is no longer true, the loop would silently
change behaviour for one of them.

Every `id="grindXxx-aud_cad_chf"` becomes `id="grindXxx-{{ ring_id }}"`,
including `instanceBar-`. Miss one and that element silently stops updating
for every ring.

**Leave the CSS alone.** The selectors `.grind-ring-section` (~line 264) and
`.grind-ring-section:last-of-type` (~line 269) stay exactly as they are.

## TESTS -- COMMIT 1, MUST NOT ALL PASS

Add `scripts/verify_dashboard_rings.py`, following the existing verify-script
style: plain asserts, `def main()`, non-zero exit on failure, and import the
app the way `scripts/verify_nzd_ext_registration.py` does
(`sys.path.insert(...)` then `import app as pipshed`).

Render the dashboard with `pipshed.app.test_client().get("/")` and decode the
body. Read the raw template file separately as TEXT. If the GET needs Redis
or any other service to succeed, STOP and report.

In every check below, SECTION means the literal `class="grind-ring-section"`
(with the attribute name and quotes). Do NOT count the bare substring
`grind-ring-section`; it also appears in two CSS selectors.

  1. For every id in `pipshed.GRIND_RINGS`, the rendered page contains
     `id="grindRing-<ring_id>"`.
  2. The rendered page contains exactly `len(pipshed.GRIND_RINGS)`
     occurrences of SECTION.
  3. The RAW template contains exactly ONE occurrence of SECTION.
  4. The RAW template does not contain `GRIND_NZDCHF_OPT`.
  5. For each ring, the rendered page contains `id="grindCards-<ring_id>"`,
     `id="grindOptStatus-<ring_id>"`, `id="grindAltStatus-<ring_id>"` and
     `id="instanceBar-<ring_id>"`.
  6. The `id="grindRing-<ring_id>"` occurrences in the rendered page appear
     in the same order as `pipshed.GRIND_RINGS` keys.
  7. For each ring, the rendered page contains its `label` string.

Expected at commit 1, derived from the baseline template:

  - 1 FAIL (nzd_ext missing)
  - 2 FAIL (3 sections rendered, 4 rings)
  - 3 FAIL (3 in the raw template)
  - 4 FAIL (hardcoded in the JS constant)
  - 5 FAIL (nzd_ext missing)
  - 6 PASS (the three present rings are already in config order)
  - 7 FAIL for `NZD extension` -- **if it PASSES, report where the string
    was found**; it may occur outside the ring blocks

Write the script so every check runs and reports, rather than exiting on the
first failure, so the whole commit-1 picture is visible. Exit non-zero if any
check failed.

Expected at commit 2: all seven pass.

Checks 6 passing in BOTH states is expected and acceptable; it guards the
ordering, not the change. Any OTHER check passing in both states means it is
not testing the change -- report it.

### Regression

Run at BOTH commits and report the full output:

    python scripts/verify_nzd_ext_registration.py
    python scripts/verify_grind_display_gaps.py
    python scripts/verify_grind_arm_cards.py
    python scripts/verify_dashboard_rings.py

The first three must give the same result at both commits. **If any changes
state, STOP.**

`verify_fxgrind_panel.py` fails at the baseline in at least one environment,
unrelated to this change. Run it, report its result at both commits, but do
not attempt to fix it here.

## COMMITS

Commit 1: `scripts/verify_dashboard_rings.py` only.
Commit 2: `app.py` and `templates/dashboard.html` only.

## NEGATIVE SPACE

Do not:

  - touch the fxmatrix repo
  - change `GRIND_RINGS`, `GRIND_INSTANCES` or `_grind_instances_for_ring`
    in `app.py`
  - change any JS render function -- `renderGrindArmCompareColumn`,
    `renderGrindInstanceCards`, `renderAggregate`, `renderGrindBookTables`
  - change `GRIND_RING_IDS`, `GRIND_INSTANCES`, `currentInstance`,
    `GRIND_TRACKED_COUNT` or `API_DAILY_LIMIT` in the JS
  - change any CSS, any class name, or any element id PREFIX
  - change any route other than the dashboard render call
  - deploy or trigger a Railway redeploy
  - `git add .` or `git add -u`; stage files by exact name
  - `git stash`, check out files from other commits
  - merge, rebase, amend, force-push, or open a PR

## FAILURE MODES

STOP and report, do not improvise, if:

  - `_grind_instances_for_ring` does not exist at the baseline
  - the three blocks differ in anything but ring id, ring number and label
  - any element id prefix appears in one block and not the others
  - the dashboard GET needs Redis or another service
  - any of the three regression scripts changes state between commits
  - the rendered SECTION count at commit 2 is not `len(GRIND_RINGS)`

## SELF-REVIEW BEFORE COMMITTING

Derived from the design above:

  - the raw template has exactly ONE `class="grind-ring-section"`, and still
    has the two CSS selectors containing `.grind-ring-section`
  - grep the raw template for `aud_cad_chf`, `eur_gbp_usd`, `nzdchf_pilot`,
    `nzd_ext`: zero matches
  - grep the raw template for `GRIND_GBPUSD_OPT`: zero matches
  - grep the raw template for `loop.index`: exactly one match
  - the separator character in the label line is byte-identical to the
    baseline
  - the Jinja loop preserves `GRIND_RINGS` insertion order
  - ASCII only in the new verify script

## BRANCH INSTRUCTION

Branch `fix/dashboard-rings-from-config` from origin/main. Three commits:
tests, implementation, response file.
PUSH the branch to origin. Do NOT merge. Do NOT open a PR.

## RESPONSE FORMAT

Write your full response to `prompts/CURSOR_dashboard_rings_loop_response.md`
on the same branch, in a third commit containing only that file. Its first
line must be:

    UNVERIFIED WORKING MATERIAL -- verify against the branch, not this file.

It must contain: `git diff --stat` per commit, the full diff of commit 2 (do
not abbreviate), the result of the block comparison, and the full output of
all five scripts at each commit.

PUSH the branch. Then reply in chat with ONLY: the branch name, the commit
hashes AS THEY EXIST ON ORIGIN, and one line saying the report is pushed.

Line count: 264
