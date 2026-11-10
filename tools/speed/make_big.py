"""The speed budget's big collection (tools/speed_budget.py): on Anki's own
engine and schema, 30,000 notes (36,000 cards), 500 decks, a million answers
over two years, a day in progress. Decks and the schema by Anki; rows by
sqlite3. No deck, bank or series is named: "Big Step 1"."""
import os, random, sqlite3, sys, time

from anki.collection import Collection

PATH = sys.argv[1]
N_NOTES, N_LOG, N_DECKS, DAYS = 30000, 1000000, 500, 730
random.seed(7)
for ext in ("", "-wal", "-shm"):
    if os.path.exists(PATH + ext):
        os.remove(PATH + ext)
col = Collection(PATH)
cutoff = int(col.sched.day_cutoff)
sday = int(col.sched.today)
mid = col.models.by_name("Basic")["id"]
systems = ["Cardio", "Renal", "Pulm", "Neuro", "GI", "Heme", "Endo", "Repro", "MSK", "Derm", "Psych", "Immuno"]
names = ["Big Step 1"] + [f"Big Step 1::{s}" for s in systems] + \
        [f"Big Step 1::{s}::Part {k:02d}" for s in systems for k in range(1, 21)]
names += ["Block 3"] + [f"Block 3::Week {k:02d}" for k in range(1, 13)]
k = 0
while len(names) < N_DECKS:
    k += 1
    names.append(f"Old decks::Course {k // 20:02d}::Lecture {k:03d}")
dids = [int(col.decks.id(n)) for n in names]
leafs_big = dids[13:13 + 240]
leafs_block = dids[254:266]
leafs_old = dids[266:]
col.close()

db = sqlite3.connect(PATH)
R = "#Big_Step1_v12"
fam = [f"{R}::#V&B::{i:02d}_{s}::{j:02d}_Topic_{j}" for i, s in enumerate(systems, 1) for j in range(1, 60)]
fam += [f"{R}::#Lectures::{s}::{k:02d}_Section_{k}::{j:02d}_Lecture_Name_{j}" for s in systems for k in range(1, 8) for j in range(1, 16)]
fam += [f"{R}::#Review_Book::{s}::{k:02d}_Chapter::{j:02d}_Page_{j}" for s in systems for k in range(1, 12) for j in range(1, 20)]
fam += [f"{R}::^Systems::{s}::{t}" for s in systems for t in ("Anatomy", "Physiology", "Pathology", "Pharmacology", "Micro")]
qids = [f"{R}::#QBank::Step::{100000 + j}" for j in range(12000)]
now_ms = int(time.time() * 1000)
notes, cards = [], []
cid = 1500000000000
card_meta = []  # (cid, did)
for i in range(N_NOTES):
    nid = 1400000000000 + i * 7
    tags = " " + " ".join(random.sample(fam, 5) + random.sample(qids, 2)) + " "
    notes.append((nid, f"g{i:09d}", mid, 1700000000, -1, tags, f"front {i} about a thing\x1fback {i}", f"front {i}", i, 0, ""))
    r = random.random()
    did = random.choice(leafs_big) if r < 0.85 else random.choice(leafs_block) if r < 0.93 else random.choice(leafs_old)
    for ordn in range(2 if i % 5 == 0 else 1):
        cid += 3
        card_meta.append((cid, nid, did, ordn))
random.shuffle(card_meta)
n_cards = len(card_meta)
studied = card_meta[: int(n_cards * 0.62)]          # started
new_open = card_meta[int(n_cards * 0.62): int(n_cards * 0.67)]  # new, unsuspended
new_susp = card_meta[int(n_cards * 0.67):]           # new, suspended (a big shared deck ships so)

# the log: each studied card starts on a day, weighted flat; then ~1,370 rows a day pick started cards
start_day = {}
by_day = [[] for _ in range(DAYS + 1)]
for c in studied:
    d = random.randint(0, DAYS - 1)  # days ago it started (0 = today excluded below)
    d = max(1, d)
    start_day[c[0]] = d
    by_day[d].append(c[0])
rows = []
ivl = {}
pool = []
per_day = N_LOG // DAYS
rid_seen = set()
for ago in range(DAYS, -1, -1):
    day_start = (cutoff - (ago + 1) * 86400) * 1000
    newc = by_day[ago] if ago <= DAYS else []
    todays = []
    for c in newc:
        todays.append((c, 0))
        todays.append((c, 0))
        pool.append(c)
        ivl[c] = 0
    n = per_day if ago else 300
    left = max(0, n - len(todays))
    for _ in range(left):
        todays.append((random.choice(pool), 1) if pool else None)
    span = (10 if ago else 3) * 3600 * 1000
    for item in todays:
        if not item:
            continue
        c, typ = item
        t = day_start + 6 * 3600000 + random.randrange(span)
        while t in rid_seen:
            t += 1
        rid_seen.add(t)
        last = ivl[c]
        if typ == 0:
            ease, new = random.choice((1, 3, 3, 3)), -600
            if last < 0:
                new = 1
        else:
            if random.random() < 0.12:
                ease, new = 1, 1
                typ = 1
            else:
                ease = random.choice((2, 3, 3, 3, 3, 4))
                new = min(300, max(1, int(max(1, last) * 1.6) + 1))
        ivl[c] = new
        rows.append((t, c, -1, ease, new, last, 2500, random.randint(2000, 15000), typ))
# top up to N_LOG with manual rows? no: trim or leave
rows = rows[:N_LOG] if len(rows) > N_LOG else rows
print("revlog rows", len(rows))
for (c, nid, did, ordn) in studied:
    iv = max(1, ivl.get(c, 1))
    r = random.random()
    if r < 0.02:
        typ, queue, due = 1, 1, int(time.time()) + 600   # learning
    elif r < 0.05:
        typ, queue, due = 2, -1, sday + random.randint(-5, 60)  # suspended review
    else:
        typ, queue = 2, 2
        due = sday + (random.randint(-3, 0) if random.random() < 0.05 else random.randint(0, min(iv, 200)))
    lapses = 8 if random.random() < 0.01 else random.randint(0, 3)
    cards.append((c, nid, did, ordn, 1700000000, -1, typ, queue, due, iv, 2500, 10, lapses, 0, 0, 0, 0,
                  '{"s":%0.2f,"d":%0.2f,"dr":0.9}' % (iv * 1.1, random.uniform(3, 8))))
pos = 0
for (c, nid, did, ordn) in new_open:
    pos += 1
    cards.append((c, nid, did, ordn, 1700000000, -1, 0, 0, pos, 0, 0, 0, 0, 0, 0, 0, 0, ""))
for (c, nid, did, ordn) in new_susp:
    pos += 1
    cards.append((c, nid, did, ordn, 1700000000, -1, 0, -1, pos, 0, 0, 0, 0, 0, 0, 0, 0, ""))
db.executemany("INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)", notes)
db.executemany("INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", cards)
db.executemany("INSERT INTO revlog VALUES (?,?,?,?,?,?,?,?,?)", rows)
db.commit()  # (ANALYZE is Anki's, below: its notes index has a collation sqlite3 alone lacks)
print("notes", db.execute("select count() from notes").fetchone(), "cards", db.execute("select count() from cards").fetchone(),
      "revlog", db.execute("select count() from revlog").fetchone(), "decks", len(dids))
print(db.execute("select count() from revlog where id >= ?", ((cutoff - 57 * 86400) * 1000,)).fetchone(), "rows in 8 weeks")
db.close()
print("size MB", os.path.getsize(PATH) // 1000000)

# two years back, so today is day 730 and the log sits where the reviews say it does; FSRS on
col = Collection(PATH)
col.db.execute("update col set crt = crt - ?", DAYS * 86400)
col.db.execute("update cards set due = due + ? where type = 2", DAYS)
col.set_config("fsrs", True)
col.db.execute("analyze")
col.close()
