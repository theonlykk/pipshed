"""Verification that dashboard ring sections derive from GRIND_RINGS config."""
import os
import sys
from pathlib import Path

SECTION = 'class="grind-ring-section"'


def _template_path():
    return Path(__file__).resolve().parent.parent / "templates" / "dashboard.html"


def _run_check(check_num, label, passed, detail=""):
    status = "PASS" if passed else "FAIL"
    line = f"{check_num} {status}: {label}"
    if detail:
        line += f" ({detail})"
    print(line)
    return passed


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    client = pipshed.app.test_client()
    resp = client.get("/")
    if resp.status_code != 200:
        print(f"GET / failed: status {resp.status_code}")
        return 1

    rendered = resp.get_data(as_text=True)
    raw = _template_path().read_text(encoding="utf-8")

    results = []
    ring_ids = list(pipshed.GRIND_RINGS.keys())
    expected_sections = len(ring_ids)

    # 1 -- grindRing id per ring
    for ring_id in ring_ids:
        ok = f'id="grindRing-{ring_id}"' in rendered
        results.append(_run_check(
            1,
            f'grindRing-{ring_id} present in rendered page',
            ok,
            "missing" if not ok else "",
        ))

    # 2 -- rendered section count
    rendered_count = rendered.count(SECTION)
    results.append(_run_check(
        2,
        f"rendered SECTION count == {expected_sections}",
        rendered_count == expected_sections,
        f"got {rendered_count}",
    ))

    # 3 -- raw template section count
    raw_count = raw.count(SECTION)
    results.append(_run_check(
        3,
        "raw template SECTION count == 1",
        raw_count == 1,
        f"got {raw_count}",
    ))

    # 4 -- no hardcoded GRIND_NZDCHF_OPT in raw template
    results.append(_run_check(
        4,
        "raw template does not contain GRIND_NZDCHF_OPT",
        "GRIND_NZDCHF_OPT" not in raw,
        "found hardcoded instance id" if "GRIND_NZDCHF_OPT" in raw else "",
    ))

    # 5 -- key element ids per ring
    for ring_id in ring_ids:
        for elem in (
            f'grindCards-{ring_id}',
            f'grindOptStatus-{ring_id}',
            f'grindAltStatus-{ring_id}',
            f'instanceBar-{ring_id}',
        ):
            ok = f'id="{elem}"' in rendered
            results.append(_run_check(
                5,
                f'{elem} present in rendered page',
                ok,
                "missing" if not ok else "",
            ))

    # 6 -- grindRing ids in config order
    positions = []
    for ring_id in ring_ids:
        needle = f'id="grindRing-{ring_id}"'
        pos = rendered.find(needle)
        results.append(_run_check(
            6,
            f"grindRing-{ring_id} found for ordering",
            pos != -1,
            "missing" if pos == -1 else "",
        ))
        if pos != -1:
            positions.append(pos)
    order_ok = positions == sorted(positions) and len(positions) == len(ring_ids)
    results.append(_run_check(
        6,
        "grindRing sections appear in GRIND_RINGS key order",
        order_ok,
    ))

    # 7 -- label strings in rendered page
    for ring_id in ring_ids:
        label = pipshed.GRIND_RINGS[ring_id]["label"]
        ok = label in rendered
        detail = ""
        if ok and ring_id == "nzd_ext":
            idx = rendered.find(label)
            detail = f"found at offset {idx}"
        results.append(_run_check(
            7,
            f'label "{label}" present for ring {ring_id}',
            ok,
            "missing" if not ok else detail,
        ))

    if all(results):
        print("All dashboard ring checks passed.")
        return 0
    print(f"{sum(1 for r in results if not r)} check(s) failed.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
