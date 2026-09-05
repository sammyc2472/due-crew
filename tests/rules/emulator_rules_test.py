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
KEY_A = "a" * 40   # crew A's key (sha1 in real life; any 40 chars here)
KEY_B = "b" * 40
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
    # -- seed as admin: three users; alice+bob share on crew A, carol on crew B
    for u, friends in (("alice", []), ("bob", []), ("carol", []), ("dave", [])):
        put(f"users/{u}", {"displayName": u.title(), "friends": friends, "openBoard": True}, "owner")
    put("users/dave", {"displayName": "Dave", "friends": [], "openBoard": False}, "owner")

    # -- membership: only under a key you name, only for yourself
    check("membership: create own", put(f"servers/{KEY_A}/members/alice", {"at": "t"}, "alice") in (200, 201))
    check("membership: cannot create for someone else", put(f"servers/{KEY_A}/members/bob", {"at": "t"}, "alice") == 403)
    put(f"servers/{KEY_A}/members/bob", {"at": "t"}, "bob")
    put(f"servers/{KEY_B}/members/carol", {"at": "t"}, "carol")
    put(f"servers/{KEY_A}/members/dave", {"at": "t"}, "dave")

    # -- rows: members only, own row only, allowed fields only
    row = {"name": "Alice", "day": "2026-09-05", "dayStart": 1, "reviews": 10, "studyTimeMs": 1000, "streak": 3}
    check("row: member writes own row", put(f"servers/{KEY_A}/board/alice", row, "alice") in (200, 201))
    check("row: non-member cannot write a row", put(f"servers/{KEY_B}/board/alice", row, "alice") == 403)
    check("row: extra field rejected", put(f"servers/{KEY_A}/board/bob", dict(row, server="x"), "bob") == 403)
    put(f"servers/{KEY_A}/board/bob", row, "bob")
    put(f"servers/{KEY_B}/board/carol", row, "carol")

    # -- reads: crew-scoped and symmetric
    check("board: member who shares can list crew A", call("GET", f"servers/{KEY_A}/board", "alice")[0] == 200)
    check("board: crew B member cannot list crew A", call("GET", f"servers/{KEY_A}/board", "carol")[0] == 403)
    check("board: member who is NOT sharing cannot peek", call("GET", f"servers/{KEY_A}/board", "dave")[0] == 403)
    check("board: outsider cannot get a single row", call("GET", f"servers/{KEY_A}/board/alice", "carol")[0] == 403)

    # -- knocks: both memberships in the named crew + both sharing
    knock = {"name": "Alice", "at": "t", "crew": KEY_A}
    check("knock: same crew, both sharing", put("users/bob/knocks/alice", knock, "alice") in (200, 201))
    check("knock: cross-crew rejected", put("users/carol/knocks/alice", knock, "alice") == 403)
    check("knock: crew you don't belong to rejected", put("users/carol/knocks/alice", dict(knock, crew=KEY_B), "alice") == 403)
    check("knock: recipient not sharing rejected", put("users/dave/knocks/alice", knock, "alice") == 403)
    check("knock: missing crew field rejected", put("users/bob/knocks/alice", {"name": "Alice", "at": "t"}, "alice") == 403)
    check("knock: cannot forge sender id", put("users/bob/knocks/carol", knock, "alice") == 403)

    # -- retraction: owner deletes row; row gone for everyone
    check("retract: owner deletes own row", call("DELETE", f"servers/{KEY_A}/board/alice", "alice")[0] == 200)
    check("retract: cannot delete someone else's row", call("DELETE", f"servers/{KEY_A}/board/bob", "alice")[0] == 403)

    # -- the retired collection is closed
    put("server_board/alice", {"name": "x"}, "owner")
    check("retired: old rows unreadable", call("GET", "server_board/alice", "alice")[0] == 403)
    check("retired: old rows unwritable", put("server_board/alice", {"name": "y"}, "alice") == 403)
    check("retired: owner may delete old row", call("DELETE", "server_board/alice", "alice")[0] == 200)

    # -- markers cumulative
    for m in ("rules-v2", "rules-v3", "rules-v4"):
        check(f"marker {m}: get is allowed (404, not 403)", call("GET", f"meta/{m}", "alice")[0] == 404)
    check("marker rules-v9: not provisioned (403)", call("GET", "meta/rules-v9", "alice")[0] == 403)

    print(f"\n{PASSED}/{PASSED + FAILED} rules checks passed")
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
