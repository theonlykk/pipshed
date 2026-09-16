UNVERIFIED WORKING MATERIAL -- verify against the branch, not this file.

# Dashboard rings loop -- execution report

## Context

- Prompt read at commit: 7420f4a
- Branch base: origin/main 7420f4a (prompt listed 58bea78; main HEAD was 7420f4a at execution time)
- Branch: ix/dashboard-rings-from-config
- Block comparison: identical after normalization (ring id, ring number, label text removed)

## Commit 1 (53d71e8) -- verify script only

`
git diff --stat 7420f4a..53d71e8
 scripts/verify_dashboard_rings.py | 134 ++++++++++++++++++++++++++++++++++++++
 1 file changed, 134 insertions(+)
`

### Verify output at commit 1

`
﻿1 OK: all four new instance IDs in GRIND_INSTANCES
2 OK: len(GRIND_INSTANCES) == 18
3 OK: original fourteen present in original order
4 OK: nzd_ext ring symbols are ["NZDCAD", "AUDNZD"]
5 OK: GRIND_OPT_INSTANCES and GRIND_ALT_INSTANCES each have 9 entries
6 OK: NZDCAD and AUDNZD in GRIND_KNOWN_SYMBOLS
7 OK: _grind_instances_for_ring(nzd_ext) returns the four new IDs
8 OK: GRIND_DEFAULT_INSTANCE unchanged
4a OK: grind symbol from instance_id; net_mtm 0.0 -> +0.00; layers 0 long / 2 short
4c OK: grind EURGBP long+short rows; entry dash; per-direction net_pnl
4c-ii OK: bidirectional grind renders two rows with net_pnl dash on both
4d OK: tracked counts match len(GRIND_INSTANCES) == 18
4e OK: grind_rings structure matches GRIND_RINGS mapping
4a OK: per-ring arm cards NO DATA; grind_rings key present
4b OK: ring eur_gbp_usd ù 3/3 OPT live, summed layers/fills/scalps, api_count=max(11)
4b-ii OK: unseeded ring renders NO DATA independently
4c OK: halted instance surfaced on ring OPT arm card
4d OK: 2/3 live reads DEGRADED
Unit OK: _summarize_grind_arm uses max(api_count)
1 PASS: grindRing-eur_gbp_usd present in rendered page
1 PASS: grindRing-aud_cad_chf present in rendered page
1 PASS: grindRing-nzdchf_pilot present in rendered page
1 FAIL: grindRing-nzd_ext present in rendered page (missing)
2 FAIL: rendered SECTION count == 4 (got 3)
3 FAIL: raw template SECTION count == 1 (got 3)
4 FAIL: raw template does not contain GRIND_NZDCHF_OPT (found hardcoded instance id)
5 PASS: grindCards-eur_gbp_usd present in rendered page
5 PASS: grindOptStatus-eur_gbp_usd present in rendered page
5 PASS: grindAltStatus-eur_gbp_usd present in rendered page
5 PASS: instanceBar-eur_gbp_usd present in rendered page
5 PASS: grindCards-aud_cad_chf present in rendered page
5 PASS: grindOptStatus-aud_cad_chf present in rendered page
5 PASS: grindAltStatus-aud_cad_chf present in rendered page
5 PASS: instanceBar-aud_cad_chf present in rendered page
5 PASS: grindCards-nzdchf_pilot present in rendered page
5 PASS: grindOptStatus-nzdchf_pilot present in rendered page
5 PASS: grindAltStatus-nzdchf_pilot present in rendered page
5 PASS: instanceBar-nzdchf_pilot present in rendered page
5 FAIL: grindCards-nzd_ext present in rendered page (missing)
5 FAIL: grindOptStatus-nzd_ext present in rendered page (missing)
5 FAIL: grindAltStatus-nzd_ext present in rendered page (missing)
5 FAIL: instanceBar-nzd_ext present in rendered page (missing)
6 PASS: grindRing-eur_gbp_usd found for ordering
6 PASS: grindRing-aud_cad_chf found for ordering
6 PASS: grindRing-nzdchf_pilot found for ordering
6 FAIL: grindRing-nzd_ext found for ordering (missing)
6 FAIL: grindRing sections appear in GRIND_RINGS key order
7 PASS: label "EUR / GBP / USD" present for ring eur_gbp_usd
7 PASS: label "AUD / CAD / CHF" present for ring aud_cad_chf
7 PASS: label "NZDCHF (pilot)" present for ring nzdchf_pilot
7 FAIL: label "NZD extension" present for ring nzd_ext (missing)
11 check(s) failed.
4a OK: 18 grind_cards all no_data; 4 rings present
4b OK (halted=false): grind card fields populated correctly
4b OK (halted=true): halt/invariant/peer flags correct
python : Traceback (most recent call last):
At C:\Users\Khalid Khan\AppData\Local\Temp\ps-script-02cbe849-ee64-4652-9eb6-f989d3b45ae1.ps1:101 char:693
+ ... nd_panel.py ---"; python scripts/verify_fxgrind_panel.py 2>&1; Write- ...
+                       ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (Traceback (most recent call last)::String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
  File "D:\pipshed\scripts\verify_fxgrind_panel.py", line 152, in <module>
    sys.exit(main())
             ^^^^^^
  File "D:\pipshed\scripts\verify_fxgrind_panel.py", line 123, in main
    assert data["intraday_mae"]["source_instance"] == "GRIND_GBPUSD_OPT"
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

`

## Commit 2 (3b7c66) -- app.py + dashboard.html

`
git diff --stat 53d71e8..f3b7c66
 app.py                   |   9 ++-
 templates/dashboard.html | 163 ++++++++---------------------------------------
 2 files changed, 33 insertions(+), 139 deletions(-)
`

### Full diff commit 2

`
diff --git a/app.py b/app.py
index af403c0..13c6313 100644
--- a/app.py
+++ b/app.py
@@ -1502,7 +1502,14 @@ def telemetry_live():
 
 @app.route("/")
 def dashboard():
-    return render_template("dashboard.html")
+    rings_ctx = {
+        ring_id: {
+            "label": ring["label"],
+            "instances": _grind_instances_for_ring(ring_id),
+        }
+        for ring_id, ring in GRIND_RINGS.items()
+    }
+    return render_template("dashboard.html", rings=rings_ctx)
 
 
 @app.route("/api/telemetry/pod_closed", methods=["POST"])
diff --git a/templates/dashboard.html b/templates/dashboard.html
index 46f6e7f..6d28f91 100644
--- a/templates/dashboard.html
+++ b/templates/dashboard.html
@@ -892,143 +892,53 @@
   </div>
 </div>
 
-<div class="grind-ring-section" id="grindRing-eur_gbp_usd">
-  <div class="instance-group-label">Ring 1 — EUR / GBP / USD</div>
+{% for ring_id, ring in rings.items() %}
+<div class="grind-ring-section" id="grindRing-{{ ring_id }}">
+  <div class="instance-group-label">Ring {{ loop.index }} — {{ ring.label }}</div>
   <div class="grind-arm-compare-strip">
-    <div class="grind-arm-compare-col opt" id="grindArmCompareOpt-eur_gbp_usd">
+    <div class="grind-arm-compare-col opt" id="grindArmCompareOpt-{{ ring_id }}">
       <div class="grind-arm-compare-title">Arm A <span class="grind-arm-label">(OPT)</span></div>
-      <div id="grindOptHaltedBanner-eur_gbp_usd" style="display:none"></div>
-      <div class="grind-arm-compare-status no-data" id="grindOptStatus-eur_gbp_usd">Arm A: …</div>
-      <div class="grind-arm-compare-detail" id="grindOptDetail-eur_gbp_usd">Loading…</div>
+      <div id="grindOptHaltedBanner-{{ ring_id }}" style="display:none"></div>
+      <div class="grind-arm-compare-status no-data" id="grindOptStatus-{{ ring_id }}">Arm A: …</div>
+      <div class="grind-arm-compare-detail" id="grindOptDetail-{{ ring_id }}">Loading…</div>
       <div class="grind-arm-compare-metrics">
         <div class="grind-arm-realised-block">
           <div class="grind-arm-metric-label grind-pnl-label" title="Deal profit + swap + commission for today. Includes commission, unlike Net MTM.">Realised today</div>
-          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindOptRealised-eur_gbp_usd">—</div>
+          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindOptRealised-{{ ring_id }}">—</div>
         </div>
-        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindOptLayers-eur_gbp_usd">—</div></div>
-        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindOptActivity-eur_gbp_usd">—</div></div>
-        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindOptMtm-eur_gbp_usd">—</div></div>
-        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindOptApi-eur_gbp_usd">—</div></div>
+        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindOptLayers-{{ ring_id }}">—</div></div>
+        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindOptActivity-{{ ring_id }}">—</div></div>
+        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindOptMtm-{{ ring_id }}">—</div></div>
+        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindOptApi-{{ ring_id }}">—</div></div>
       </div>
     </div>
-    <div class="grind-arm-compare-col alt" id="grindArmCompareAlt-eur_gbp_usd">
+    <div class="grind-arm-compare-col alt" id="grindArmCompareAlt-{{ ring_id }}">
       <div class="grind-arm-compare-title">Arm B <span class="grind-arm-label">(ALT)</span></div>
-      <div id="grindAltHaltedBanner-eur_gbp_usd" style="display:none"></div>
-      <div class="grind-arm-compare-status no-data" id="grindAltStatus-eur_gbp_usd">Arm B: …</div>
-      <div class="grind-arm-compare-detail" id="grindAltDetail-eur_gbp_usd">Loading…</div>
+      <div id="grindAltHaltedBanner-{{ ring_id }}" style="display:none"></div>
+      <div class="grind-arm-compare-status no-data" id="grindAltStatus-{{ ring_id }}">Arm B: …</div>
+      <div class="grind-arm-compare-detail" id="grindAltDetail-{{ ring_id }}">Loading…</div>
       <div class="grind-arm-compare-metrics">
         <div class="grind-arm-realised-block">
           <div class="grind-arm-metric-label grind-pnl-label" title="Deal profit + swap + commission for today. Includes commission, unlike Net MTM.">Realised today</div>
-          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindAltRealised-eur_gbp_usd">—</div>
+          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindAltRealised-{{ ring_id }}">—</div>
         </div>
-        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindAltLayers-eur_gbp_usd">—</div></div>
-        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindAltActivity-eur_gbp_usd">—</div></div>
-        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindAltMtm-eur_gbp_usd">—</div></div>
-        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindAltApi-eur_gbp_usd">—</div></div>
+        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindAltLayers-{{ ring_id }}">—</div></div>
+        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindAltActivity-{{ ring_id }}">—</div></div>
+        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindAltMtm-{{ ring_id }}">—</div></div>
+        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindAltApi-{{ ring_id }}">—</div></div>
       </div>
     </div>
   </div>
   <div class="instance-group">
     <div class="instance-group-label">Instances</div>
-    <div class="instance-bar" id="instanceBar-eur_gbp_usd"></div>
+    <div class="instance-bar" id="instanceBar-{{ ring_id }}"></div>
   </div>
   <div class="grind-cards-section">
     <div class="instance-group-label">Instance cards</div>
-    <div class="grind-cards-grid" id="grindCards-eur_gbp_usd"></div>
-  </div>
-</div>
-
-<div class="grind-ring-section" id="grindRing-aud_cad_chf">
-  <div class="instance-group-label">Ring 2 — AUD / CAD / CHF</div>
-  <div class="grind-arm-compare-strip">
-    <div class="grind-arm-compare-col opt" id="grindArmCompareOpt-aud_cad_chf">
-      <div class="grind-arm-compare-title">Arm A <span class="grind-arm-label">(OPT)</span></div>
-      <div id="grindOptHaltedBanner-aud_cad_chf" style="display:none"></div>
-      <div class="grind-arm-compare-status no-data" id="grindOptStatus-aud_cad_chf">Arm A: …</div>
-      <div class="grind-arm-compare-detail" id="grindOptDetail-aud_cad_chf">Loading…</div>
-      <div class="grind-arm-compare-metrics">
-        <div class="grind-arm-realised-block">
-          <div class="grind-arm-metric-label grind-pnl-label" title="Deal profit + swap + commission for today. Includes commission, unlike Net MTM.">Realised today</div>
-          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindOptRealised-aud_cad_chf">—</div>
-        </div>
-        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindOptLayers-aud_cad_chf">—</div></div>
-        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindOptActivity-aud_cad_chf">—</div></div>
-        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindOptMtm-aud_cad_chf">—</div></div>
-        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindOptApi-aud_cad_chf">—</div></div>
-      </div>
-    </div>
-    <div class="grind-arm-compare-col alt" id="grindArmCompareAlt-aud_cad_chf">
-      <div class="grind-arm-compare-title">Arm B <span class="grind-arm-label">(ALT)</span></div>
-      <div id="grindAltHaltedBanner-aud_cad_chf" style="display:none"></div>
-      <div class="grind-arm-compare-status no-data" id="grindAltStatus-aud_cad_chf">Arm B: …</div>
-      <div class="grind-arm-compare-detail" id="grindAltDetail-aud_cad_chf">Loading…</div>
-      <div class="grind-arm-compare-metrics">
-        <div class="grind-arm-realised-block">
-          <div class="grind-arm-metric-label grind-pnl-label" title="Deal profit + swap + commission for today. Includes commission, unlike Net MTM.">Realised today</div>
-          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindAltRealised-aud_cad_chf">—</div>
-        </div>
-        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindAltLayers-aud_cad_chf">—</div></div>
-        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindAltActivity-aud_cad_chf">—</div></div>
-        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindAltMtm-aud_cad_chf">—</div></div>
-        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindAltApi-aud_cad_chf">—</div></div>
-      </div>
-    </div>
-  </div>
-  <div class="instance-group">
-    <div class="instance-group-label">Instances</div>
-    <div class="instance-bar" id="instanceBar-aud_cad_chf"></div>
-  </div>
-  <div class="grind-cards-section">
-    <div class="instance-group-label">Instance cards</div>
-    <div class="grind-cards-grid" id="grindCards-aud_cad_chf"></div>
-  </div>
-</div>
-
-<div class="grind-ring-section" id="grindRing-nzdchf_pilot">
-  <div class="instance-group-label">Ring 3 — NZDCHF (pilot)</div>
-  <div class="grind-arm-compare-strip">
-    <div class="grind-arm-compare-col opt" id="grindArmCompareOpt-nzdchf_pilot">
-      <div class="grind-arm-compare-title">Arm A <span class="grind-arm-label">(OPT)</span></div>
-      <div id="grindOptHaltedBanner-nzdchf_pilot" style="display:none"></div>
-      <div class="grind-arm-compare-status no-data" id="grindOptStatus-nzdchf_pilot">Arm A: …</div>
-      <div class="grind-arm-compare-detail" id="grindOptDetail-nzdchf_pilot">Loading…</div>
-      <div class="grind-arm-compare-metrics">
-        <div class="grind-arm-realised-block">
-          <div class="grind-arm-metric-label grind-pnl-label" title="Deal profit + swap + commission for today. Includes commission, unlike Net MTM.">Realised today</div>
-          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindOptRealised-nzdchf_pilot">—</div>
-        </div>
-        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindOptLayers-nzdchf_pilot">—</div></div>
-        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindOptActivity-nzdchf_pilot">—</div></div>
-        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindOptMtm-nzdchf_pilot">—</div></div>
-        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindOptApi-nzdchf_pilot">—</div></div>
-      </div>
-    </div>
-    <div class="grind-arm-compare-col alt" id="grindArmCompareAlt-nzdchf_pilot">
-      <div class="grind-arm-compare-title">Arm B <span class="grind-arm-label">(ALT)</span></div>
-      <div id="grindAltHaltedBanner-nzdchf_pilot" style="display:none"></div>
-      <div class="grind-arm-compare-status no-data" id="grindAltStatus-nzdchf_pilot">Arm B: …</div>
-      <div class="grind-arm-compare-detail" id="grindAltDetail-nzdchf_pilot">Loading…</div>
-      <div class="grind-arm-compare-metrics">
-        <div class="grind-arm-realised-block">
-          <div class="grind-arm-metric-label grind-pnl-label" title="Deal profit + swap + commission for today. Includes commission, unlike Net MTM.">Realised today</div>
-          <div class="grind-arm-realised-value grind-arm-metric-value" id="grindAltRealised-nzdchf_pilot">—</div>
-        </div>
-        <div><div class="grind-arm-metric-label">Open layers</div><div class="grind-arm-metric-value" id="grindAltLayers-nzdchf_pilot">—</div></div>
-        <div><div class="grind-arm-metric-label">Scalps today</div><div class="grind-arm-metric-value" id="grindAltActivity-nzdchf_pilot">—</div></div>
-        <div><div class="grind-arm-metric-label grind-pnl-label" title="Position profit + swap only; excludes commission.">Net MTM</div><div class="grind-arm-metric-value" id="grindAltMtm-nzdchf_pilot">—</div></div>
-        <div><div class="grind-arm-metric-label">API today</div><div class="grind-arm-metric-value" id="grindAltApi-nzdchf_pilot">—</div></div>
-      </div>
-    </div>
-  </div>
-  <div class="instance-group">
-    <div class="instance-group-label">Instances</div>
-    <div class="instance-bar" id="instanceBar-nzdchf_pilot"></div>
-  </div>
-  <div class="grind-cards-section">
-    <div class="instance-group-label">Instance cards</div>
-    <div class="grind-cards-grid" id="grindCards-nzdchf_pilot"></div>
+    <div class="grind-cards-grid" id="grindCards-{{ ring_id }}"></div>
   </div>
 </div>
+{% endfor %}
 
 <div class="card" id="carrySection" style="margin-bottom:16px">
   <div class="card-label">Carry (per night, pips)</div>
@@ -1162,30 +1072,7 @@
 </div>
 
 <script>
-  const GRIND_RINGS = {
-    eur_gbp_usd: {
-      label: 'EUR / GBP / USD',
-      instances: [
-        'GRIND_GBPUSD_OPT', 'GRIND_GBPUSD_ALT',
-        'GRIND_EURUSD_OPT', 'GRIND_EURUSD_ALT',
-        'GRIND_EURGBP_OPT', 'GRIND_EURGBP_ALT',
-      ],
-    },
-    aud_cad_chf: {
-      label: 'AUD / CAD / CHF',
-      instances: [
-        'GRIND_AUDCAD_OPT', 'GRIND_AUDCAD_ALT',
-        'GRIND_AUDCHF_OPT', 'GRIND_AUDCHF_ALT',
-        'GRIND_CADCHF_OPT', 'GRIND_CADCHF_ALT',
-      ],
-    },
-    nzdchf_pilot: {
-      label: 'NZDCHF (pilot)',
-      instances: [
-        'GRIND_NZDCHF_OPT', 'GRIND_NZDCHF_ALT',
-      ],
-    },
-  };
+  const GRIND_RINGS = {{ rings|tojson }};
   const GRIND_RING_IDS = Object.keys(GRIND_RINGS);
   const GRIND_INSTANCES = GRIND_RING_IDS.reduce(function(acc, ringId) {
     return acc.concat(GRIND_RINGS[ringId].instances);

`

### Verify output at commit 2

`
--- verify (c2 nzd) ---
﻿1 OK: all four new instance IDs in GRIND_INSTANCES
2 OK: len(GRIND_INSTANCES) == 18
3 OK: original fourteen present in original order
4 OK: nzd_ext ring symbols are ["NZDCAD", "AUDNZD"]
5 OK: GRIND_OPT_INSTANCES and GRIND_ALT_INSTANCES each have 9 entries
6 OK: NZDCAD and AUDNZD in GRIND_KNOWN_SYMBOLS
7 OK: _grind_instances_for_ring(nzd_ext) returns the four new IDs
8 OK: GRIND_DEFAULT_INSTANCE unchanged

--- verify (c2 gaps) ---
﻿4a OK: grind symbol from instance_id; net_mtm 0.0 -> +0.00; layers 0 long / 2 short
4c OK: grind EURGBP long+short rows; entry dash; per-direction net_pnl
4c-ii OK: bidirectional grind renders two rows with net_pnl dash on both
4d OK: tracked counts match len(GRIND_INSTANCES) == 18
4e OK: grind_rings structure matches GRIND_RINGS mapping

--- verify (c2 arm) ---
﻿4a OK: per-ring arm cards NO DATA; grind_rings key present
4b OK: ring eur_gbp_usd ù 3/3 OPT live, summed layers/fills/scalps, api_count=max(11)
4b-ii OK: unseeded ring renders NO DATA independently
4c OK: halted instance surfaced on ring OPT arm card
4d OK: 2/3 live reads DEGRADED
Unit OK: _summarize_grind_arm uses max(api_count)

--- verify (c2 rings) ---
﻿1 PASS: grindRing-eur_gbp_usd present in rendered page
1 PASS: grindRing-aud_cad_chf present in rendered page
1 PASS: grindRing-nzdchf_pilot present in rendered page
1 PASS: grindRing-nzd_ext present in rendered page
2 PASS: rendered SECTION count == 4 (got 4)
3 PASS: raw template SECTION count == 1 (got 1)
4 PASS: raw template does not contain GRIND_NZDCHF_OPT
5 PASS: grindCards-eur_gbp_usd present in rendered page
5 PASS: grindOptStatus-eur_gbp_usd present in rendered page
5 PASS: grindAltStatus-eur_gbp_usd present in rendered page
5 PASS: instanceBar-eur_gbp_usd present in rendered page
5 PASS: grindCards-aud_cad_chf present in rendered page
5 PASS: grindOptStatus-aud_cad_chf present in rendered page
5 PASS: grindAltStatus-aud_cad_chf present in rendered page
5 PASS: instanceBar-aud_cad_chf present in rendered page
5 PASS: grindCards-nzdchf_pilot present in rendered page
5 PASS: grindOptStatus-nzdchf_pilot present in rendered page
5 PASS: grindAltStatus-nzdchf_pilot present in rendered page
5 PASS: instanceBar-nzdchf_pilot present in rendered page
5 PASS: grindCards-nzd_ext present in rendered page
5 PASS: grindOptStatus-nzd_ext present in rendered page
5 PASS: grindAltStatus-nzd_ext present in rendered page
5 PASS: instanceBar-nzd_ext present in rendered page
6 PASS: grindRing-eur_gbp_usd found for ordering
6 PASS: grindRing-aud_cad_chf found for ordering
6 PASS: grindRing-nzdchf_pilot found for ordering
6 PASS: grindRing-nzd_ext found for ordering
6 PASS: grindRing sections appear in GRIND_RINGS key order
7 PASS: label "EUR / GBP / USD" present for ring eur_gbp_usd
7 PASS: label "AUD / CAD / CHF" present for ring aud_cad_chf
7 PASS: label "NZDCHF (pilot)" present for ring nzdchf_pilot
7 PASS: label "NZD extension" present for ring nzd_ext (found at offset 34217)
All dashboard ring checks passed.

--- verify (c2 panel) ---
﻿4a OK: 18 grind_cards all no_data; 4 rings present
4b OK (halted=false): grind card fields populated correctly
4b OK (halted=true): halt/invariant/peer flags correct
python : Traceback (most recent call last):
At C:\Users\Khalid Khan\AppData\Local\Temp\ps-script-13272c6e-5668-45ec-89cc-56dcd5233f48.ps1:101 char:401
+ ... t -Encoding utf8; python scripts/verify_fxgrind_panel.py 2>&1 | Out-F ...
+                       ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (Traceback (most recent call last)::String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
 
  File "D:\pipshed\scripts\verify_fxgrind_panel.py", line 152, in <module>
    sys.exit(main())
             ^^^^^^
  File "D:\pipshed\scripts\verify_fxgrind_panel.py", line 123, in main
    assert data["intraday_mae"]["source_instance"] == "GRIND_GBPUSD_OPT"
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError

`

## Notes

- Regression scripts erify_nzd_ext_registration.py, erify_grind_display_gaps.py, erify_grind_arm_cards.py: EXIT 0 at both commits.
- erify_fxgrind_panel.py: EXIT 1 at both commits (AssertionError line 123, unchanged).
- erify_dashboard_rings.py: EXIT 1 at commit 1 (11 checks failed as expected), EXIT 0 at commit 2.
