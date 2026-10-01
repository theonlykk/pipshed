"""Verification for the dashboard's secondary text colour (operator 30 Sep:
"the dark grey font is so hard to read").

--muted (labels, card lines, legends; 50 uses) must read clearly on both
backgrounds and still look secondary next to --text:
- WCAG contrast of --muted on --surface (cards) and on --bg (page) >= 6.0;
- --text against --muted >= 2.0, so the two greys stay distinct.
At #666 the card contrast is 3.15:1 (hand-computed with the WCAG formula).
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "templates", "dashboard.html")


def luminance(hex_colour):
    h = hex_colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    def chan(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (chan(int(h[i:i + 2], 16)) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted([luminance(a), luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def root_vars():
    src = open(TEMPLATE, encoding="utf-8").read()
    block = re.search(r":root\s*\{(.*?)\}", src, re.S).group(1)
    return dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{3,6})", block))


def check_ct1(v):
    c = contrast(v["muted"], v["surface"])
    if c < 6.0:
        raise AssertionError(f"--muted {v['muted']} on --surface {v['surface']}: {c:.2f} < 6.0")
    return f"--muted on --surface {c:.2f}:1"


def check_ct2(v):
    c = contrast(v["muted"], v["bg"])
    if c < 6.0:
        raise AssertionError(f"--muted {v['muted']} on --bg {v['bg']}: {c:.2f} < 6.0")
    return f"--muted on --bg {c:.2f}:1"


def check_ct3(v):
    # guard: muted must stay visibly secondary to --text
    c = contrast(v["text"], v["muted"])
    if c < 2.0:
        raise AssertionError(f"--text vs --muted only {c:.2f}:1")
    return f"--text vs --muted {c:.2f}:1 (guard)"


CHECKS = [("CT1", check_ct1), ("CT2", check_ct2), ("CT3", check_ct3)]


def main():
    v = root_vars()
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            print(f"{name} OK: {fn(v)}")
            passed += 1
        except Exception as exc:  # noqa: BLE001
            print(f"{name} FAIL: {exc}")
            failed += 1
    print(f"SUMMARY passed={passed} failed={failed}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
