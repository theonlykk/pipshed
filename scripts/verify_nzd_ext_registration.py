"""Verification for NZDCAD and AUDNZD instance registration in app.py."""
import os
import sys

ORIGINAL_FOURTEEN = [
    "GRIND_GBPUSD_OPT",
    "GRIND_GBPUSD_ALT",
    "GRIND_EURUSD_OPT",
    "GRIND_EURUSD_ALT",
    "GRIND_EURGBP_OPT",
    "GRIND_EURGBP_ALT",
    "GRIND_AUDCAD_OPT",
    "GRIND_AUDCAD_ALT",
    "GRIND_AUDCHF_OPT",
    "GRIND_AUDCHF_ALT",
    "GRIND_CADCHF_OPT",
    "GRIND_CADCHF_ALT",
    "GRIND_NZDCHF_OPT",
    "GRIND_NZDCHF_ALT",
]

NEW_INSTANCES = [
    "GRIND_NZDCAD_OPT",
    "GRIND_NZDCAD_ALT",
    "GRIND_AUDNZD_OPT",
    "GRIND_AUDNZD_ALT",
]


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import app as pipshed

    # 1 -- all four new instance IDs present
    for inst in NEW_INSTANCES:
        assert inst in pipshed.GRIND_INSTANCES, inst
    print("1 OK: all four new instance IDs in GRIND_INSTANCES")

    # 2 -- total count
    assert len(pipshed.GRIND_INSTANCES) == 18
    print("2 OK: len(GRIND_INSTANCES) == 18")

    # 3 -- original fourteen prefix unchanged
    assert pipshed.GRIND_INSTANCES[:14] == ORIGINAL_FOURTEEN
    print("3 OK: original fourteen present in original order")

    # 4 -- nzd_ext ring
    assert "nzd_ext" in pipshed.GRIND_RINGS
    assert pipshed.GRIND_RINGS["nzd_ext"]["symbols"] == ["NZDCAD", "AUDNZD"]
    print('4 OK: nzd_ext ring symbols are ["NZDCAD", "AUDNZD"]')

    # 5 -- OPT/ALT derived lists
    assert len(pipshed.GRIND_OPT_INSTANCES) == 9
    assert len(pipshed.GRIND_ALT_INSTANCES) == 9
    for inst in NEW_INSTANCES:
        if inst.endswith("_OPT"):
            assert inst in pipshed.GRIND_OPT_INSTANCES, inst
        else:
            assert inst in pipshed.GRIND_ALT_INSTANCES, inst
    print("5 OK: GRIND_OPT_INSTANCES and GRIND_ALT_INSTANCES each have 9 entries")

    # 6 -- known symbols
    assert "NZDCAD" in pipshed.GRIND_KNOWN_SYMBOLS
    assert "AUDNZD" in pipshed.GRIND_KNOWN_SYMBOLS
    print("6 OK: NZDCAD and AUDNZD in GRIND_KNOWN_SYMBOLS")

    # 7 -- ring membership
    ring_instances = pipshed._grind_instances_for_ring("nzd_ext")
    assert ring_instances == NEW_INSTANCES
    print("7 OK: _grind_instances_for_ring(nzd_ext) returns the four new IDs")

    # 8 -- default instance unchanged
    assert pipshed.GRIND_DEFAULT_INSTANCE == "GRIND_GBPUSD_OPT"
    print("8 OK: GRIND_DEFAULT_INSTANCE unchanged")

    return 0


if __name__ == "__main__":
    sys.exit(main())
