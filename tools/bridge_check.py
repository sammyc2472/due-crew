"""Does the 2.x bridge hold? Reads both sides and compares, person by person.

    npx firebase-tools projects:list > /dev/null     # refreshes your Google login
    python3 tools/bridge_check.py

For everyone: which version they're on, and whether their week, name and
emoji, shared decks, heatmap and squad rows are the same in D1 (3.x) and
Firestore (2.x). The bridge runs every 15 minutes, so something changed in
the last quarter hour can show as behind; run it again after the next
quarter hour before worrying. Read-only on both sides. Prints names, never
addresses.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_users import FIRESTORE, google_token  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS_PREFIX = FIRESTORE.split("/v1/", 1)[1]
DAY_KEYS = ("studied", "reviews", "studyTimeMs", "accuracy", "streak", "newCards")
ROW_KEYS = [("reviews", "reviews"), ("day", "day"), ("streak", "streak"), ("week", "week"),
            ("studyTimeMs", "study_time_ms"), ("newCards", "new_cards")]


def d1(sql):
    """Rows from the live D1, through wrangler (your own login). Tries twice;
    on a second failure, shows what wrangler said."""
    for attempt in (1, 2):
        run = subprocess.run(["npx", "wrangler", "d1", "execute", "due-crew", "--remote", "--env=", "--json",
                              "--command", sql], cwd=os.path.join(ROOT, "worker"), capture_output=True, text=True)
        if run.returncode == 0:
            return json.loads(run.stdout)[0]["results"]
        if attempt == 2:
            sys.exit("wrangler couldn't read D1:\n" + "\n".join((run.stderr + run.stdout).strip().splitlines()[-12:]))
        time.sleep(3)


def _pv(f):
    if "integerValue" in f:
        return int(f["integerValue"])
    if "doubleValue" in f:
        return float(f["doubleValue"])
    for k in ("booleanValue", "stringValue", "timestampValue"):
        if k in f:
            return f[k]
    if "arrayValue" in f:
        return [_pv(x) for x in f["arrayValue"].get("values", [])]
    if "mapValue" in f:
        return {k: _pv(x) for k, x in f["mapValue"].get("fields", {}).items()}
    return None


def firestore(token, paths):
    """{path: doc} for the paths that exist."""
    out = {}
    for i in range(0, len(paths), 100):
        body = json.dumps({"documents": [f"{DOCS_PREFIX}/{p}" for p in paths[i:i + 100]]}).encode()
        req = urllib.request.Request(f"{FIRESTORE}:batchGet", data=body, method="POST")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=60) as r:
            for item in json.loads(r.read()):
                found = item.get("found")
                if found:
                    out[found["name"].split("/documents/", 1)[1]] = {
                        k: _pv(v) for k, v in (found.get("fields") or {}).items()}
    return out


def days(week):
    """{label: (studied, reviews, …)} of a week, whichever side it came from."""
    return {lb: tuple((d or {}).get(k) for k in DAY_KEYS)
            for lb, d in ((week or {}).get("days") or {}).items()}


def same_numbers(a, b):
    """Equal, treating 87 and 87.0 as the same number."""
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) < 1e-9
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same_numbers(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_numbers(a[k], b[k]) for k in a)
    return a == b


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def deck_key(decks):
    """The decks as the Worker keeps them (validate.ts decks): entries with a
    sig and a total only, seen and mature capped."""
    out = []
    for d in decks or []:
        if not isinstance(d, dict) or not isinstance(d.get("sig"), list) or not _int(d.get("total")):
            continue
        total = d["total"]
        seen = min(_int(d.get("seen")) or 0, total)
        name = " ".join(str(d.get("name")).split())[:200] if isinstance(d.get("name"), str) else "?"
        out.append((name, total, seen, min(_int(d.get("mature")) or 0, seen)))
    return sorted(out)


def emoji_key(e):
    """An emoji as the Worker keeps it: one, or none."""
    return e if isinstance(e, str) and 1 <= len(e) <= 16 and not any(c.isalnum() or c == " " for c in e) else ""


def main():
    people = d1("SELECT u.uid, u.name, u.emoji, u.client_version, w.doc, d.json AS decks, h.json AS heat "
                "FROM users u LEFT JOIN weeks w ON w.uid = u.uid LEFT JOIN decks d ON d.uid = u.uid "
                "LEFT JOIN heatmaps h ON h.uid = u.uid ORDER BY u.name")
    members = d1("SELECT m.squad, q.name AS squad_name, m.uid, m.reviews, m.day, m.streak, m.week, "
                 "m.study_time_ms, m.new_cards FROM members m JOIN squads q ON q.id = m.squad")
    paths = [p for r in people for p in (f"users/{r['uid']}", f"users/{r['uid']}/shared/week",
                                         f"users/{r['uid']}/shared/decks", f"users/{r['uid']}/shared/heatmap")]
    paths += [f"squads/{m['squad']}/members/{m['uid']}" for m in members]
    fs = firestore(google_token(), paths)

    rows_by_uid = {}
    for m in members:
        rows_by_uid.setdefault(m["uid"], []).append(m)

    problems = 0
    on3 = sum(1 for r in people if str(r["client_version"] or "").startswith("3."))
    print(f"{len(people)} people: {on3} on 3.x, {len(people) - on3} still on 2.x\n")
    for r in people:
        uid, v3 = r["uid"], str(r["client_version"] or "").startswith("3.")
        prof = fs.get(f"users/{uid}")
        fweek = fs.get(f"users/{uid}/shared/week")
        dweek = json.loads(r["doc"]) if r["doc"] else None
        marks = []

        def mark(label, ok, why=""):
            nonlocal problems
            if ok is None:
                marks.append(f"{label} –")
            elif ok:
                marks.append(f"{label} ✓")
            else:
                problems += 1
                marks.append(f"{label} ✗{' (' + why + ')' if why else ''}")

        # the week: whichever side is the truth must be on the other one
        if not dweek and not fweek:
            mark("week", None)
        elif not (dweek and fweek):
            mark("week", False, "only in " + ("D1" if dweek else "Firestore"))
        else:
            a, b = days(dweek), days(fweek)
            if v3:
                # 2.x keeps an extra day at the back of the window: compare D1's days
                diff = [lb for lb in a if not same_numbers(a[lb], b.get(lb))]
            else:
                diff = [lb for lb in b if lb in a and not same_numbers(a[lb], b[lb])] + [lb for lb in b if lb not in a][:1]
            mark("week", not diff, f"{len(diff)} day(s) differ, e.g. {diff[0]}" if diff else "")
        if prof is None:
            mark("name", None)
        else:
            ok = ((prof.get("displayName") or "").strip()[:60] or (r["name"] or "")) == (r["name"] or "") \
                and emoji_key(prof.get("emoji")) == (r["emoji"] or "")
            mark("name/emoji", ok, "differ")
            if v3:
                # 2.x reads a friend's week doc only when their profile says 2.9 or newer
                mark("2.x reads the week", str(prof.get("clientVersion", "")).startswith("3."), "profile still says 2.x")
        fdecks = (fs.get(f"users/{uid}/shared/decks") or {}).get("decks")
        ddecks = json.loads(r["decks"]) if r["decks"] else None
        if fdecks is None and ddecks is None:
            mark("decks", None)
        else:
            mark("decks", deck_key(fdecks) == deck_key(ddecks), "differ")
        fheat = (fs.get(f"users/{uid}/shared/heatmap") or {}).get("counts")
        dheat = json.loads(r["heat"])["counts"] if r["heat"] else None
        if fheat is None and dheat is None:
            mark("heatmap", None)
        else:
            mark("heatmap", same_numbers(fheat or {}, dheat or {}), "differ")
        both = [m for m in rows_by_uid.get(uid, []) if f"squads/{m['squad']}/members/{uid}" in fs]
        bad = [m["squad_name"] for m in both
               if not all(same_numbers(fs[f"squads/{m['squad']}/members/{uid}"].get(fk), m[dk]) for fk, dk in ROW_KEYS)]
        if both:
            mark(f"squads {len(both) - len(bad)}/{len(both)}", not bad, ", ".join(bad))
        print(f"  {(r['name'] or '?')[:18]:<18} {'3.x' if v3 else '2.x'}   " + "   ".join(marks))
    print(f"\n{'All in step.' if not problems else f'{problems} thing(s) out of step.'}"
          + ("" if not problems else " If you changed something in the last 15 minutes, run this again after the next quarter hour."))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
