"""Rules tests against the Firestore EMULATOR — the only kind that proves
what firestore.rules enforces. Run from the repo root:

    cd tests/rules && firebase emulators:exec --only firestore \
        --project demo-due-crew "python3 emulator_rules_test.py"

The emulator accepts unsigned JWTs and uses their claims for request.auth,
so each actor below is just a bearer token with a `sub`. Admin writes (to
seed state the client could never write itself) use `Bearer owner`.

NOT EXECUTED where this file was written (no firebase-tools / Java there).
"""

import base64
import json
import os
import sys
import urllib.error
import urllib.request

HOST = os.environ.get("FIRESTORE_EMULATOR_HOST", "localhost:8080")
PROJECT = os.environ.get("GCLOUD_PROJECT", "demo-due-crew")
BASE = f"http://{HOST}/v1/projects/{PROJECT}/databases/(default)/documents"
PASSED, FAILED = 0, 0


def token(uid):
    hdr = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
    body = base64.urlsafe_b64encode(json.dumps({
        "sub": uid, "user_id": uid, "iss": f"https://securetoken.google.com/{PROJECT}",
        "aud": PROJECT, "iat": 0, "exp": 9999999999,
        "firebase": {"sign_in_provider": "password"}}).encode()).rstrip(b"=")
    return (hdr + b"." + body + b".").decode()


def call(method, path, uid=None, body=None, query=""):
    url = f"{BASE}/{path}{query}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer owner" if uid == "owner" else f"Bearer {token(uid)}" if uid else "")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {}


def fv(v):
    if isinstance(v, bool):
        return {"booleanValue": v}
    if isinstance(v, int):
        return {"integerValue": str(v)}
    if isinstance(v, list):
        return {"arrayValue": {"values": [fv(x) for x in v]}}
    return {"stringValue": str(v)}


def put(path, fields, uid, mask=None):
    keys = mask or list(fields)
    q = "?" + "&".join(f"updateMask.fieldPaths={k}" for k in keys)
    return call("PATCH", path, uid, {"fields": {k: fv(v) for k, v in fields.items()}}, q)[0]


def check(name, cond):
    global PASSED, FAILED
    PASSED += cond
    FAILED += (not cond)
    print(("PASS " if cond else "FAIL ") + name)


def main():
    # -- seed as admin: dave is alice's friend; nobody is in a squad yet
    for u, friends in (("alice", ["dave"]), ("bob", []), ("carol", []), ("dave", ["alice"])):
        put(f"users/{u}", {"displayName": u.title(), "friends": friends}, "owner")
    sid = "a" * 24
    squad = {"name": "busm", "founder": "alice", "open": True, "createdAt": "t"}

    # -- squads: the id is the invite; only the founder shapes it
    check("squad: founder creates", put(f"squads/{sid}", squad, "alice") in (200, 201))
    check("squad: cannot name someone else as founder", put("squads/" + "b" * 24, squad, "bob") == 403)
    check("squad: name too long rejected", put("squads/" + "c" * 24, dict(squad, founder="bob", name="x" * 25), "bob") == 403)
    check("squad: extra field rejected", put("squads/" + "d" * 24, dict(squad, founder="bob", code="KQ9P2X3A"), "bob") == 403)
    check("squad: anyone signed in may get it", call("GET", f"squads/{sid}", "carol")[0] == 200)
    check("squad: signed out cannot", call("GET", f"squads/{sid}")[0] == 403)
    check("squad: no listing", call("GET", "squads", "alice")[0] == 403)

    # -- members: join while open, own row only, allowed shape only
    member = {"name": "Alice", "joinedAt": "t"}
    check("member: founder joins own squad", put(f"squads/{sid}/members/alice", member, "alice") in (200, 201))
    check("member: bob joins while open", put(f"squads/{sid}/members/bob", dict(member, name="Bob"), "bob") in (200, 201))
    check("member: cannot join as someone else", put(f"squads/{sid}/members/carol", member, "bob") == 403)
    row = {"day": "2026-09-10", "reviews": 10, "studyTimeMs": 1000, "accuracy": 91.5, "streak": 3}
    check("row: member writes own numbers", put(f"squads/{sid}/members/bob", row, "bob") == 200)
    check("row: extra field rejected", put(f"squads/{sid}/members/bob", {"server": "x"}, "bob") == 403)
    check("row: negative reviews rejected", put(f"squads/{sid}/members/bob", {"reviews": -1}, "bob") == 403)
    check("row: bad day rejected", put(f"squads/{sid}/members/bob", {"day": "nope"}, "bob") == 403)
    check("row: cannot write someone else's", put(f"squads/{sid}/members/alice", {"reviews": 99}, "bob") == 403)

    # -- reads: members only
    check("board: member lists rows", call("GET", f"squads/{sid}/members", "bob")[0] == 200)
    check("board: non-member cannot list", call("GET", f"squads/{sid}/members", "carol")[0] == 403)
    check("board: non-member cannot get a row", call("GET", f"squads/{sid}/members/alice", "carol")[0] == 403)
    q = {"structuredQuery": {"from": [{"collectionId": "members"}], "limit": 1000}}
    check("board: member query allowed", call("POST", f"squads/{sid}:runQuery", "bob", q)[0] == 200)
    check("board: non-member query denied", call("POST", f"squads/{sid}:runQuery", "carol", q)[0] == 403)

    # -- the door: lock, founder only; existing members keep syncing
    check("lock: founder locks", put(f"squads/{sid}", {"open": False}, "alice") == 200)
    check("lock: non-founder cannot", put(f"squads/{sid}", {"open": True}, "bob") == 403)
    check("lock: join refused while locked", put(f"squads/{sid}/members/carol", dict(member, name="Carol"), "carol") == 403)
    check("lock: existing member still writes", put(f"squads/{sid}/members/bob", {"reviews": 11}, "bob") == 200)
    check("lock: founder cannot be handed off", put(f"squads/{sid}", {"founder": "bob"}, "alice") == 403)

    # -- knocks: both in the same squad
    knock = {"name": "Bob", "at": "t", "squad": sid}
    check("knock: squadmate to squadmate", put("users/alice/knocks/bob", knock, "bob") in (200, 201))
    check("knock: to a non-member rejected", put("users/carol/knocks/bob", knock, "bob") == 403)
    check("knock: from a non-member rejected", put("users/alice/knocks/carol", dict(knock, name="Carol"), "carol") == 403)
    check("knock: cannot forge sender id", put("users/alice/knocks/carol", knock, "bob") == 403)
    check("knock: extra fields rejected", put("users/alice/knocks/bob", dict(knock, crew="x"), "bob") == 403)
    check("knock: squad is required", put("users/alice/knocks/bob", {"name": "Bob", "at": "t"}, "bob") == 403)
    check("knock: owner reads and deletes", call("GET", "users/alice/knocks/bob", "alice")[0] == 200
          and call("DELETE", "users/alice/knocks/bob", "alice")[0] == 200)

    # -- remove and leave
    check("member: founder removes anyone", call("DELETE", f"squads/{sid}/members/bob", "alice")[0] == 200)
    put(f"squads/{sid}/members/bob", dict(member, name="Bob"), "owner")
    check("member: cannot remove someone else", call("DELETE", f"squads/{sid}/members/alice", "bob")[0] == 403)
    check("member: leaves", call("DELETE", f"squads/{sid}/members/bob", "bob")[0] == 200)
    check("board: after leaving, reads are denied", call("GET", f"squads/{sid}/members", "bob")[0] == 403)

    # -- cheers: friends only, three emoji, optional note <= 80 (rules-v5)
    cheer = {"emoji": "🔥", "name": "Dave", "at": "t"}
    check("cheer: friend sends", put("users/alice/cheers/dave", cheer, "dave") in (200, 201))
    check("cheer: with a note", put("users/alice/cheers/dave", dict(cheer, note="you're on fire"), "dave") in (200, 201))
    check("cheer: note over 80 chars rejected", put("users/alice/cheers/dave", dict(cheer, note="x" * 81), "dave") == 403)
    check("cheer: note must be a string", put("users/alice/cheers/dave", dict(cheer, note=5), "dave") == 403)
    check("cheer: extra field rejected", put("users/alice/cheers/dave", dict(cheer, link="http://x"), "dave") == 403)
    check("cheer: non-friend rejected", put("users/alice/cheers/bob", cheer, "bob") == 403)
    check("cheer: only the owner reads", call("GET", "users/alice/cheers/dave", "dave")[0] == 403)

    # -- friendship consent unchanged
    put("users/alice/daily_stats/2026-09-06", {"reviews": 10}, "alice")
    check("stats: friend reads", call("GET", "users/alice/daily_stats/2026-09-06", "dave")[0] == 200)
    check("stats: stranger denied", call("GET", "users/alice/daily_stats/2026-09-06", "bob")[0] == 403)

    # -- retired paths
    day = "2026-09-06"
    put(f"boards/{day}/rows/alice", {"name": "Alice", "reviews": 1}, "owner")
    check("retired: Everyone rows unreadable", call("GET", f"boards/{day}/rows/alice", "alice")[0] == 403)
    check("retired: Everyone rows unwritable", put(f"boards/{day}/rows/alice", {"name": "x"}, "alice") == 403)
    check("retired: owner may delete an Everyone row", call("DELETE", f"boards/{day}/rows/alice", "alice")[0] == 200)
    check("retired: cannot delete someone else's", call("DELETE", f"boards/{day}/rows/bob", "alice")[0] == 403)
    put("server_board/alice", {"name": "x"}, "owner")
    check("retired: old rows unreadable", call("GET", "server_board/alice", "alice")[0] == 403)
    check("retired: old rows unwritable", put("server_board/alice", {"name": "y"}, "alice") == 403)
    check("retired: owner may delete old row", call("DELETE", "server_board/alice", "alice")[0] == 200)
    check("retired: directory is gone", call("GET", "server_names/busm", "alice")[0] == 403)

    # -- markers cumulative
    for m in ("rules-v2", "rules-v3", "rules-v4", "rules-v5", "rules-v6"):
        check(f"marker {m}: get is allowed (404, not 403)", call("GET", f"meta/{m}", "alice")[0] == 404)
    check("marker rules-v9: not provisioned (403)", call("GET", "meta/rules-v9", "alice")[0] == 403)

    print(f"\n{PASSED}/{PASSED + FAILED} rules checks passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
