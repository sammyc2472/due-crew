"""Put 2.x squads and their members into D1, straight from Firestore. Once.

    npx firebase-tools projects:list > /dev/null     # refreshes your Google login
    python3 tools/restore_squads.py squads.sql
    cd worker && npx wrangler d1 execute due-crew --remote --env="" --file ../squads.sql
    rm ../squads.sql

3.0 only knows a squad once a member on 3.x restores it, and only knows the
members who have updated; the rest of a squad appears as each person
updates. This fills that in from Firestore now: every squad, its founder,
its block list and its members with their last row, for accounts that
exist on the Worker. It only ever adds: a squad or a member D1 already has
stays as it is, and nobody on a block list is added. After this, the
bridge keeps the rows in step (as updates only).

Run it once. Anyone removed from a squad in 3.x since the move would come
back if it ran again later.

Standard library only. Prints counts, never names or addresses.
"""

import json
import os
import re
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from import_users import FIRESTORE, google_token  # noqa: E402
from restore_friends import UID  # noqa: E402

SQUAD_ID = re.compile(r"^[0-9a-f]{24}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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


def listing(token, path):
    """[(doc id, fields)] for a collection, page by page."""
    out, page = [], ""
    while True:
        url = f"{FIRESTORE}/{path}?pageSize=300" + (f"&pageToken={urllib.parse.quote(page, safe='')}" if page else "")
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        for doc in data.get("documents") or []:
            out.append((doc["name"].rsplit("/", 1)[-1], {k: _pv(v) for k, v in (doc.get("fields") or {}).items()}))
        page = data.get("nextPageToken") or ""
        if not page:
            return out


def q(v):
    """A SQL literal: NULL, a number, or a quoted string."""
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def one_line(v, n):
    return " ".join(str(v or "").split())[:n]


def _int(v, hi=None):
    ok = isinstance(v, int) and not isinstance(v, bool) and v >= 0 and (hi is None or v <= hi)
    return v if ok else None


def row_values(m):
    """A 2.x member doc as D1's row columns, anything malformed left empty."""
    acc = m.get("accuracy")
    emoji = m.get("emoji")
    return {
        "day": m["day"] if isinstance(m.get("day"), str) and DATE.fullmatch(m["day"]) else None,
        "reviews": _int(m.get("reviews")),
        "study_time_ms": _int(m.get("studyTimeMs")),
        "accuracy": acc if isinstance(acc, (int, float)) and not isinstance(acc, bool) and 0 <= acc <= 100 else None,
        "streak": _int(m.get("streak")),
        "week": _int(m.get("week"), 7),
        "emoji": emoji if isinstance(emoji, str) and 1 <= len(emoji) <= 16 else None,
        "new_cards": _int(m.get("newCards")),
    }


def sql(squads):
    """squads: [(id, doc, [(uid, member doc)])]. Additive statements only."""
    now = "CAST(strftime('%s','now') AS INTEGER)"
    out = []
    for sid, doc, members in squads:
        if not SQUAD_ID.fullmatch(sid):
            continue
        founder = str(doc.get("founder") or "")
        name = one_line(doc.get("name"), 24).strip() or "squad"
        if UID.fullmatch(founder):
            out.append(f"INSERT INTO squads (id, name, founder, open, created_at) SELECT {q(sid)}, {q(name)}, "
                       f"{q(founder)}, {1 if doc.get('open') is not False else 0}, {now} "
                       f"WHERE EXISTS (SELECT 1 FROM users WHERE uid = {q(founder)}) ON CONFLICT DO NOTHING;")
        for b in (doc.get("banned") or [])[:200]:
            if isinstance(b, str) and UID.fullmatch(b):
                out.append(f"INSERT INTO bans (squad, uid) SELECT {q(sid)}, {q(b)} "
                           f"WHERE EXISTS (SELECT 1 FROM squads WHERE id = {q(sid)}) ON CONFLICT DO NOTHING;")
        for uid, m in members:
            if not UID.fullmatch(uid):
                continue
            r = row_values(m)
            cols = ", ".join(r)
            vals = ", ".join(q(v) for v in r.values())
            out.append(
                f"INSERT INTO members (squad, uid, name, joined_at, {cols}, updated_at) "
                f"SELECT {q(sid)}, {q(uid)}, {q(one_line(m.get('name'), 60) or '?')}, {now}, {vals}, {now} "
                f"WHERE EXISTS (SELECT 1 FROM squads WHERE id = {q(sid)}) "
                f"AND EXISTS (SELECT 1 FROM users WHERE uid = {q(uid)}) "
                f"AND NOT EXISTS (SELECT 1 FROM bans WHERE squad = {q(sid)} AND uid = {q(uid)}) ON CONFLICT DO NOTHING;")
    return "\n".join(out) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    token = google_token()
    squads = [(sid, doc, listing(token, f"squads/{sid}/members")) for sid, doc in listing(token, "squads")]
    with open(argv[0], "w") as f:
        f.write(sql(squads))
    print(f"{len(squads)} squads, {sum(len(m) for _s, _d, m in squads)} memberships in Firestore; wrote {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
