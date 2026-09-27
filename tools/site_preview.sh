#!/usr/bin/env bash
# A local duecrew.com to click through: both Workers in `wrangler dev`, a
# local database with a sample crew and plan, and a link that signs you in
# as Dre, the plan's author. Nothing touches the real site or database.
#
#   tools/site_preview.sh            # then open the link it prints; Ctrl-C to stop
#
# Needs node (npx) and python3. Run from anywhere in the repo.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
PORT="${PORT:-8787}"
STATE="site/.wrangler/state"

echo "Setting up a fresh local database…"
rm -rf "$STATE"
(cd worker && { [ -d node_modules ] || npm ci --legacy-peer-deps --silent; } \
  && npx wrangler d1 migrations apply due-crew --local --env="" --persist-to "../$STATE" >/dev/null)

TOKEN=$(python3 -c "import secrets,base64;print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('='))")
HASH=$(python3 -c "import hashlib,sys;print(hashlib.sha256(sys.argv[1].encode()).hexdigest())" "$TOKEN")
SEED=$(mktemp)
trap 'rm -f "$SEED"' EXIT
python3 - "$HASH" > "$SEED" <<'PY'
import json, sys, time, datetime
h = sys.argv[1]
now = int(time.time())
today = datetime.date.today()
mon = today - datetime.timedelta(days=today.weekday()) - datetime.timedelta(days=14)  # two weeks in
d = lambda n: (mon + datetime.timedelta(days=n)).isoformat()
q = lambda s: "'" + str(s).replace("'", "''") + "'"
tags = [["Step1", 1960], ["Step1::Cardio", 312], ["Step1::Cardio::Heart_failure", 48], ["Step1::Cardio::Arrhythmia", 61],
        ["Step1::Cardio::Valves", 39], ["Step1::Cardio::Pharm", 164], ["Step1::Renal", 402], ["Step1::Renal::Physiology", 212],
        ["Step1::Renal::Pharm", 190], ["Step1::Pulm", 288], ["Step1::Pulm::Asthma", 74], ["Step1::Pulm::COPD", 58],
        ["Step1::Pulm::Physiology", 156], ["Step1::Neuro", 398], ["Step1::Neuro::Anatomy", 221], ["Step1::Neuro::Pharm", 177]]
decks = [["Step 1::Extras", 96], ["Step 1::Extras::Images", 41]]
units = [
  {"id": "hf", "name": "Heart failure", "opens": d(0), "due": d(7), "tags": ["Step1::Cardio::Heart_failure"], "decks": [], "cards": []},
  {"id": "arr", "name": "Arrhythmia", "opens": d(7), "due": d(14), "tags": ["Step1::Cardio::Arrhythmia"], "decks": [], "cards": [["gA1", 0], ["gA2", 1]]},
  {"id": "renp", "name": "Renal physiology", "opens": d(14), "due": d(21), "tags": ["Step1::Renal::Physiology"], "decks": [], "cards": []},
  {"id": "renm", "name": "Renal pharm", "opens": d(21), "due": d(28), "tags": ["Step1::Renal::Pharm"], "decks": [], "cards": []},
  {"id": "pulm", "name": "Pulm", "opens": d(28), "due": d(35), "tags": ["Step1::Pulm"], "decks": ["Step 1::Extras"], "cards": []},
]
doc = {"deck": "Step 1", "units": units}
out = []
for uid, name in [("dre", "Dre"), ("maya", "Maya"), ("nia", "Nia"), ("jonah", "Jonah")]:
    out.append(f"INSERT INTO users (uid, email, name, created_at) VALUES ({q(uid)}, {q(uid + '@example.com')}, {q(name)}, {now});")
out.append(f"INSERT INTO sessions (token_hash, uid, device, created_at, last_used) VALUES ({q(h)}, 'dre', 'preview', {now}, {now});")
out.append(f"INSERT INTO squads (id, name, founder, open, created_at) VALUES ('busmpreview', 'Busm', 'dre', 1, {now});")
for uid in ["dre", "maya", "nia"]:
    out.append(f"INSERT INTO members (squad, uid, name, joined_at) VALUES ('busmpreview', {q(uid)}, {q(uid.title())}, {now});")
out.append(f"INSERT INTO plan_trees (uid, deck, doc, at) VALUES ('dre', 'Step 1', {q(json.dumps({'tags': tags, 'decks': decks}))}, {now});")
out.append("INSERT INTO plans (id, code, owner, name, line, audience, squad, doc, version, created_at, updated_at) VALUES "
           f"('stepplanpreview1', '7KQ4MX2D', 'dre', 'Step 1', 'Organ systems, one a week, done by January.', 'code', 'busmpreview', {q(json.dumps(doc))}, 3, {now}, {now});")
prog = {"maya": {"hf": [48, 48, 48], "arr": [63, 63, 63], "renp": [212, 120, 212]},
        "nia": {"hf": [48, 48, 48], "arr": [63, 40, 63], "renp": [212, 30, 212]}}
for uid, p in prog.items():
    out.append(f"INSERT INTO plan_follows (plan, uid, share, paused, progress, at) VALUES ('stepplanpreview1', {q(uid)}, 1, 0, {q(json.dumps(p))}, {now});")
out.append(f"INSERT INTO plan_follows (plan, uid, share, paused, at) VALUES ('stepplanpreview1', 'jonah', 0, 0, {now});")
print("\n".join(out))
PY
(cd worker && npx wrangler d1 execute due-crew --local --env="" --persist-to "../$STATE" --file "$SEED" >/dev/null)

echo "Starting duecrew.com and its API on http://localhost:$PORT …"
cd site
npx wrangler dev -c wrangler.toml -c ../worker/wrangler.toml --port "$PORT" --ip 127.0.0.1 &
DEV=$!
trap 'kill $DEV 2>/dev/null; rm -f "$SEED"' EXIT INT TERM
for _ in $(seq 1 60); do
  curl -fsS "http://localhost:$PORT/api/version" >/dev/null 2>&1 && break
  sleep 1
done
LINK=$(curl -fsS -X POST "http://localhost:$PORT/api/auth/link" -H "authorization: Bearer $TOKEN" \
  | python3 -c "import json,sys;print(json.load(sys.stdin)['token'])")
cat <<EOF

  Ready. Open this within five minutes (it signs you in as Dre, once):

    http://localhost:$PORT/plans/new?deck=Step%201#$LINK

  Then try:  http://localhost:$PORT/plans                    your plans
             http://localhost:$PORT/plans/stepplanpreview1/edit   the builder, with a sample plan
             http://localhost:$PORT/plans/stepplanpreview1        progress (counts only)
             http://localhost:$PORT/p/7KQ4MX2D                  a shared link (try a private window too)

  Sign-in by code works too; the email lands in wrangler's log above instead of an inbox.
  Ctrl-C stops it.
EOF
wait $DEV
