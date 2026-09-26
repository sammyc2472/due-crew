"""Put 2.x friendships back on the Worker, straight from Firestore.

    npx firebase-tools projects:list > /dev/null     # refreshes your Google login
    python3 tools/restore_friends.py friends.sql
    cd worker && npx wrangler d1 execute due-crew --remote --env="" --file ../friends.sql
    rm ../friends.sql

3.0.0's first sync lost the crew on most computers: a board refresh
replaced the friend list this computer remembered before the restore could
send it. Firestore still has every profile's `friends` array, which is the
list of people each person added. This writes one edge per entry, the same
edge that person made in 2.x, for accounts that exist on the Worker, never
overwriting; then clears the knocks those edges answer. Safe to run twice.

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

UID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def friend_lists(token):
    """{uid: [friend uid, ...]} from every profile's `friends` array."""
    out, page = {}, ""
    while True:
        url = (f"{FIRESTORE}/users?pageSize=300&mask.fieldPaths=friends"
               + (f"&pageToken={urllib.parse.quote(page, safe='')}" if page else ""))
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        for doc in data.get("documents") or []:
            arr = ((doc.get("fields") or {}).get("friends") or {}).get("arrayValue") or {}
            out[doc["name"].rsplit("/", 1)[-1]] = [
                v.get("stringValue", "") for v in arr.get("values") or []]
        page = data.get("nextPageToken") or ""
        if not page:
            return out


def edges(lists):
    """Sorted (owner, friend) pairs, uids checked so they're safe in SQL."""
    out = set()
    for owner, friends in lists.items():
        if not UID.match(owner):
            continue
        for f in friends:
            if f and f != owner and UID.match(f):
                out.add((owner, f))
    return sorted(out)


def sql(pairs):
    now = "CAST(strftime('%s','now') AS INTEGER)"
    lines = []
    for owner, friend in pairs:
        lines.append(
            f"INSERT INTO friends (owner, friend, at) SELECT '{owner}', '{friend}', {now} "
            f"WHERE EXISTS (SELECT 1 FROM users WHERE uid = '{owner}') "
            f"AND EXISTS (SELECT 1 FROM users WHERE uid = '{friend}') ON CONFLICT DO NOTHING;")
    # a knock is answered once its recipient has added the sender
    lines.append("DELETE FROM knocks WHERE EXISTS (SELECT 1 FROM friends "
                 "WHERE owner = knocks.to_uid AND friend = knocks.from_uid);")
    return "\n".join(lines) + "\n"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    lists = friend_lists(google_token())
    pairs = edges(lists)
    have = set(pairs)
    mutual = sum(1 for a, b in pairs if (b, a) in have) // 2
    with open(argv[0], "w") as f:
        f.write(sql(pairs))
    print(f"{len(lists)} profiles; {len(pairs)} adds, {mutual} of them mutual pairs; wrote {argv[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
