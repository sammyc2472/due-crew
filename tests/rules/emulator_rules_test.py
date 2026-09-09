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
    # -- seed as admin: alice, bob share; carol does not; dave is alice's friend
    for u, friends, sharing in (("alice", ["dave"], True), ("bob", [], True),
                                ("carol", [], False), ("dave", ["alice"], False)):
        put(f"users/{u}", {"displayName": u.title(), "friends": friends, "openBoard": sharing}, "owner")
    day = "2026-09-06"
    row = {"name": "Alice", "reviews": 10, "studyTimeMs": 1000, "streak": 3}

    # -- rows: sharers only, own row only, allowed shape only
    check("row: sharer writes own row", put(f"boards/{day}/rows/alice", row, "alice") in (200, 201))
    check("row: cannot write someone else's row", put(f"boards/{day}/rows/bob", row, "alice") == 403)
    check("row: non-sharer cannot write a row", put(f"boards/{day}/rows/carol", row, "carol") == 403)
    check("row: extra field rejected", put(f"boards/{day}/rows/bob", dict(row, server="x"), "bob") == 403)
    check("row: negative reviews rejected", put(f"boards/{day}/rows/bob", dict(row, reviews=-1), "bob") == 403)
    check("row: bad day id rejected", put("boards/not-a-day/rows/bob", row, "bob") == 403)
    put(f"boards/{day}/rows/bob", dict(row, name="Bob", reviews=20), "bob")

    # -- reads: symmetric
    check("board: sharer can list the day", call("GET", f"boards/{day}/rows", "bob")[0] == 200)
    check("board: non-sharer cannot list", call("GET", f"boards/{day}/rows", "carol")[0] == 403)
    check("board: non-sharer cannot get a row", call("GET", f"boards/{day}/rows/alice", "carol")[0] == 403)
    q = {"structuredQuery": {"from": [{"collectionId": "rows"}],
                             "orderBy": [{"field": {"fieldPath": "reviews"}, "direction": "DESCENDING"}],
                             "limit": 1}}
    status, body = call("POST", f"boards/{day}:runQuery", "bob", q)
    check("board: top-N query allowed for sharers", status == 200)
    status, _ = call("POST", f"boards/{day}:runQuery", "carol", q)
    check("board: top-N query denied for non-sharers", status == 403)
    agg = {"structuredAggregationQuery": {"structuredQuery": {"from": [{"collectionId": "rows"}]},
                                          "aggregations": [{"alias": "n", "count": {}}]}}
    check("board: aggregation allowed for sharers", call("POST", f"boards/{day}:runAggregationQuery", "bob", agg)[0] == 200)
    check("board: aggregation denied for non-sharers", call("POST", f"boards/{day}:runAggregationQuery", "carol", agg)[0] == 403)

    # -- knocks: both on the board
    knock = {"name": "Alice", "at": "t"}
    check("knock: sharer to sharer", put("users/bob/knocks/alice", knock, "alice") in (200, 201))
    check("knock: to a non-sharer rejected", put("users/carol/knocks/alice", knock, "alice") == 403)
    check("knock: from a non-sharer rejected", put("users/bob/knocks/carol", knock, "carol") == 403)
    check("knock: cannot forge sender id", put("users/bob/knocks/carol", knock, "alice") == 403)
    check("knock: extra fields rejected", put("users/bob/knocks/alice", dict(knock, crew="x"), "alice") == 403)

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

    # -- retraction and retired paths
    check("retract: owner deletes own row", call("DELETE", f"boards/{day}/rows/alice", "alice")[0] == 200)
    check("retract: cannot delete someone else's row", call("DELETE", f"boards/{day}/rows/bob", "alice")[0] == 403)
    put("server_board/alice", {"name": "x"}, "owner")
    check("retired: old rows unreadable", call("GET", "server_board/alice", "alice")[0] == 403)
    check("retired: old rows unwritable", put("server_board/alice", {"name": "y"}, "alice") == 403)
    check("retired: owner may delete old row", call("DELETE", "server_board/alice", "alice")[0] == 200)
    check("retired: directory is gone", call("GET", "server_names/busm", "alice")[0] == 403)

    # -- markers cumulative
    for m in ("rules-v2", "rules-v3", "rules-v4", "rules-v5"):
        check(f"marker {m}: get is allowed (404, not 403)", call("GET", f"meta/{m}", "alice")[0] == 404)
    check("marker rules-v9: not provisioned (403)", call("GET", "meta/rules-v9", "alice")[0] == 403)

    print(f"\n{PASSED}/{PASSED + FAILED} rules checks passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
