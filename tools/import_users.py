"""The one-shot identity import at 3.0's cutover.

    firebase auth:export users.json --format=json --project anki-leaderboard-f6691
    DUE_CREW_ADMIN_TOKEN=... python3 tools/import_users.py users.json [--firestore] [--go]

Reads the export (uid and email for every account) and sends it to the
Worker's POST /admin/import-users in chunks. --firestore also reads each
profile's display name and friend code from Firestore, with your own login
(the one `firebase auth:export` just used, or gcloud's), so everyone
keeps the name and the code they had: a 2.x install never kept its code
locally, and invites already sent would otherwise stop working. Without
--go it only says what it would send. Safe to run twice: the Worker
imports by uid and skips what it already has.

Standard library only. Prints counts, never addresses.
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 500
PROJECT = "anki-leaderboard-f6691"
FIRESTORE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"


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


def profiles(token):
    """{uid: (displayName, friendCode)} from Firestore's users collection,
    two fields each, page by page. Needs an owner's access token."""
    out, page = {}, ""
    while True:
        url = (f"{FIRESTORE}/users?pageSize=300&mask.fieldPaths=displayName&mask.fieldPaths=friendCode"
               + (f"&pageToken={urllib.parse.quote(page, safe='')}" if page else ""))
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        for doc in data.get("documents") or []:
            f = doc.get("fields") or {}
            out[doc["name"].rsplit("/", 1)[-1]] = (
                (f.get("displayName") or {}).get("stringValue", ""),
                (f.get("friendCode") or {}).get("stringValue", ""))
        page = data.get("nextPageToken") or ""
        if not page:
            return out


def google_token():
    """An access token for Firestore as the project's owner: gcloud's, or the
    one firebase-tools keeps after `firebase auth:export` (it refreshes it
    on every command, so run this right after the export)."""
    try:
        return subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    path = os.path.expanduser("~/.config/configstore/firebase-tools.json")
    try:
        with open(path) as f:
            token = (json.load(f).get("tokens") or {}).get("access_token")
    except (OSError, ValueError):
        token = None
    if not token:
        sys.exit("no Google login: run `firebase auth:export ...` first (or install gcloud)")
    return token


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
    ap.add_argument("--firestore", action="store_true",
                    help="also carry each profile's name and friend code (gcloud login)")
    ap.add_argument("--go", action="store_true", help="send it (default: a dry run)")
    args = ap.parse_args(argv)
    users = accounts(args.export)
    print(f"{len(users)} accounts with an email in the export")
    if args.firestore:
        found = profiles(google_token())
        for u in users:
            name, code = found.get(u["uid"], ("", ""))
            if name.strip():
                u["name"] = name.strip()[:60]
            if code:
                u["code"] = code
        print(f"{sum(1 for u in users if 'name' in u)} names and "
              f"{sum(1 for u in users if 'code' in u)} codes from Firestore")
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
