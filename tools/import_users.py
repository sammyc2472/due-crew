"""The one-shot identity import at 3.0's cutover.

    firebase auth:export users.json --format=json --project anki-leaderboard-f6691
    DUE_CREW_ADMIN_TOKEN=... python3 tools/import_users.py users.json [--api https://api.duecrew.com] [--go]

Reads the export (uid and email for every account, and a display name where
Firebase Auth has one) and sends it to the Worker's POST /admin/import-users
in chunks. Without --go it only says what it would send. Safe to run twice:
the Worker imports by uid and skips what it already has.

Standard library only. Prints counts, never addresses.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

CHUNK = 500


def accounts(path):
    with open(path) as f:
        data = json.load(f)
    out = []
    for u in data.get("users") or []:
        uid, email = u.get("localId"), u.get("email")
        if isinstance(uid, str) and uid and isinstance(email, str) and email:
            row = {"uid": uid, "email": email}
            if isinstance(u.get("displayName"), str) and u["displayName"].strip():
                row["name"] = u["displayName"].strip()[:60]
            out.append(row)
    return out


def post(api, token, users):
    req = urllib.request.Request(api.rstrip("/") + "/admin/import-users", method="POST",
                                 data=json.dumps({"users": users}).encode())
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("export")
    ap.add_argument("--api", default="https://api.duecrew.com")
    ap.add_argument("--go", action="store_true", help="send it (default: a dry run)")
    args = ap.parse_args(argv)
    users = accounts(args.export)
    print(f"{len(users)} accounts with an email in the export")
    if not args.go:
        print("dry run: nothing sent (add --go)")
        return 0
    token = os.environ.get("DUE_CREW_ADMIN_TOKEN", "")
    if not token:
        print("set DUE_CREW_ADMIN_TOKEN (the Worker's ADMIN_TOKEN secret)", file=sys.stderr)
        return 2
    imported, skipped = 0, []
    for i in range(0, len(users), CHUNK):
        try:
            r = post(args.api, token, users[i:i + CHUNK])
        except urllib.error.HTTPError as e:
            print(f"refused: {e.code}", file=sys.stderr)
            return 1
        imported += r.get("imported", 0)
        skipped += r.get("skipped", [])
    print(f"imported {imported}; already there {len(users) - imported - len(skipped)}; skipped {len(skipped)}")
    for uid in skipped:
        print(f"  skipped uid {uid}: its address already signed in to 3.0 under a new uid, or it's malformed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
