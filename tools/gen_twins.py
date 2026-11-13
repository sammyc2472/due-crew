"""3.9.12, the foundations round: constants the site restated by hand are
written from the add-on's own, so a number changes in one place.

    python3 tools/gen_twins.py           # rewrites each line in place
    python3 tools/gen_twins.py --check   # exit 1 if a line is behind its Python

What it writes (each a single line, found by its `const NAME = `, in the
file named; the line says where it's from):

    site/public/table.js    NEEDS         gamenight.NEEDS (what each game needs from tonight's pack)
    site/public/builder.js  MAX           planner/build.CEILINGS (a plan's limits)
    site/public/builder.js  SAVES_A_DAY   planner/build.SAVES_A_DAY

The suite checks that running it changes nothing. A rule (a function) isn't
a constant: those are still twins, each with its test. Needs nothing but
Python: the modules read are pure, so the package's Anki glue is never
imported (as tools/gen_sev_js.py).
"""

import json
import os
import re
import sys
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if "due_crew" not in sys.modules:  # the pure modules alone (the suite has the package already)
    _pkg = types.ModuleType("due_crew")
    _pkg.__path__ = [os.path.join(REPO, "due_crew")]
    sys.modules["due_crew"] = _pkg
    _pl = types.ModuleType("due_crew.planner")
    _pl.__path__ = [os.path.join(REPO, "due_crew", "planner")]
    sys.modules["due_crew.planner"] = _pl


def _obj(d):
    """A flat dict as a JS object literal on one line: bare keys, JSON values."""
    return "{ " + ", ".join(f"{k}: {json.dumps(list(v) if isinstance(v, tuple) else v)}" for k, v in d.items()) + " }"


def lines():
    """[(file, const name, the whole line it should be, leading spaces kept)]."""
    from due_crew import gamenight
    from due_crew.planner import build
    made = "made by tools/gen_twins.py from"
    return [
        ("table.js", "NEEDS", f"const NEEDS = {_obj(gamenight.NEEDS)};  // {made} gamenight.NEEDS"),
        ("builder.js", "MAX", f"const MAX = {_obj(build.CEILINGS)};  // {made} planner/build.CEILINGS"),
        ("builder.js", "SAVES_A_DAY", f"const SAVES_A_DAY = {int(build.SAVES_A_DAY)};  // {made} planner/build.SAVES_A_DAY (planput: a person's saves a day, every plan's)"),
    ]


def stale(write=False):
    """The lines that aren't what their Python says; write: put them right."""
    out = []
    by_file = {}
    for f, name, want in lines():
        by_file.setdefault(f, []).append((name, want))
    for f, wants in by_file.items():
        path = os.path.join(REPO, "site", "public", f)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        new = text
        for name, want in wants:
            start = "const MAX = { sets:" if name == "MAX" else f"const {name} = "  # builder.js has other MAXes: the plan's begins with sets
            found = re.findall(rf"(?m)^([ \t]*){re.escape(start)}.*$", new)
            if len(found) != 1:
                out.append((f, name, f"found {len(found)} lines, wanted one"))
                continue
            line = found[0] + want
            if not re.search(rf"(?m)^{re.escape(line)}$", new):
                out.append((f, name, "behind"))
                new = re.sub(rf"(?m)^[ \t]*{re.escape(start)}.*$", lambda _m: line, new)
        if write and new != text:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(new)
    return out


if __name__ == "__main__":
    check = "--check" in sys.argv
    behind = stale(write=not check)
    for f, name, why in behind:
        print(f"{f}: {name}: {why}" + ("" if check else " (written)"))
    if not behind:
        print("the site's constants are their Python's")
    sys.exit(1 if check and behind else 0)
