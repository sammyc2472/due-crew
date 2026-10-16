"""3.8.2: writes the kit in site/public/sev.js from due_crew/sev.py's
site_kit(), so duecrew.com's crew rows draw the add-on's own Pip, wearing
the closet's own drawings (board.row_sev's twin). Run it after Pip, its
row or the closet changes; the suite checks that running it changes nothing.

    python3 tools/gen_sev_js.py           # rewrites the kit in place
    python3 tools/gen_sev_js.py --check   # exit 1 if sev.js is behind sev.py

Needs nothing but Python: sev.py and the closet are pure, so the package's
Anki glue is never imported.
"""

import json
import os
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "site", "public", "sev.js")
BEGIN = "  // ---- made by tools/gen_sev_js.py from sev.site_kit(): change sev.py or the closet and run it, never by hand ----\n"
END = "  // ---- end of what's made ----\n"

if "due_crew" not in sys.modules:  # the pure modules alone (the suite has the package already)
    _pkg = types.ModuleType("due_crew")
    _pkg.__path__ = [os.path.join(REPO, "due_crew")]
    sys.modules["due_crew"] = _pkg
from due_crew import sev  # noqa: E402


def kit_js():
    """The kit as JS: one thing a line, so a drawing's change is its own line in a diff."""
    k = sev.site_kit()
    j = lambda v: json.dumps(v, ensure_ascii=True)  # noqa: E731
    things = "".join(f"      {j(key)}: {j(t)},\n" for key, t in k["things"].items())
    return (f"  const KIT = {{\n    row: {j(k['row'])},\n    held: {j(k['held'])},\n"
            f"    slots: {j(k['slots'])}, costume: {j(k['costume'])}, max: {j(k['max'])},\n"
            f"    things: {{\n{things}    }},\n  }};\n")


def render(text):
    """sev.js with its kit as sev.py makes it now; the rest as it is."""
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(BEGIN) > text.index(END):
        raise SystemExit("sev.js: the kit's markers aren't there once each, in order")
    head, rest = text.split(BEGIN)
    _old, tail = rest.split(END)
    return head + BEGIN + kit_js() + END + tail


def main(argv):
    with open(OUT, encoding="utf-8") as f:
        text = f.read()
    new = render(text)
    if "--check" in argv:
        print("sev.js is sev.py's" if new == text else "sev.js is behind sev.py: run tools/gen_sev_js.py")
        return 0 if new == text else 1
    if new != text:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(new)
    print(f"{os.path.relpath(OUT, REPO)}: {'written' if new != text else 'already sev.py’s'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
