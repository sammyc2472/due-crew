"""Languages (due_crew/words.py): what the code asks for against what each language's file has.

    python3 tools/words.py            every language: missing, unused, wrong (exit 1 on any)
    python3 tools/words.py --keys     the English phrases the code asks for, one a line

A phrase is the first argument of t(), tn() (its two), _t(), _tn() or later()/_later(), a plain string."""
import ast
import glob
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _words():
    """words.py by its file: importing due_crew itself needs Anki."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("dc_words", os.path.join(REPO, "due_crew", "words.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
CALLS = {"t": 1, "_t": 1, "later": 1, "_later": 1, "tn": 2, "_tn": 2}


def keys():
    out = {}
    for path in sorted(glob.glob(os.path.join(REPO, "due_crew", "**", "*.py"), recursive=True)):
        if path.endswith(os.path.join("due_crew", "words.py")):
            continue
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
                for arg in node.args[:CALLS.get(name, 0)]:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        out.setdefault(arg.value, os.path.relpath(path, REPO))
    words = _words()
    for m in words.MONTHS + words.DAYS:
        out.setdefault(m, "due_crew/words.py")
    out.setdefault(words.NOTE, "due_crew/words.py")
    return out


def report():
    """{code: {"missing": [...], "unused": [...], "wrong": [...]}} for every language but English."""
    words = _words()
    asked = keys()
    out = {}
    for code in words.NAMES:
        if code == words.EN:
            continue
        try:
            with open(os.path.join(REPO, "due_crew", "lang", code + ".json"), encoding="utf-8") as f:
                have = json.load(f)
        except (OSError, ValueError):
            have = {}
        out[code] = {"missing": sorted(k for k in asked if k not in have), "unused": sorted(k for k in have if k not in asked),
                     "wrong": words.wrong(code)}
    return out


if __name__ == "__main__":
    if "--keys" in sys.argv:
        print("\n".join(sorted(keys())))
        sys.exit(0)
    bad = 0
    for code, r in report().items():
        n = sum(len(v) for v in r.values())
        bad += n
        print(f"{code}: {len(r['missing'])} missing, {len(r['unused'])} unused, {len(r['wrong'])} wrong")
        for kind in ("missing", "unused", "wrong"):
            for line in r[kind][:40]:
                print(f"  {kind}: {line}")
    sys.exit(1 if bad else 0)
