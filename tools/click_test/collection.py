"""The robot's own collection, made with Anki's Python API before Anki
starts: a few hundred notes in two decks, basic and cloze, under
hierarchical tags (topics, a resource by chapter), and a month of review
history in the revlog, so the board, Due, Insights and the plan window all
have something to show. Every word in it is made up here."""

import os
import random
import time

SYSTEMS = ("Cardio", "Renal", "Pulm", "Neuro", "Heme")
TOPICS = ("Basics", "Signs", "Drugs", "Cases")
CHAPTERS = 12
COURSE, LANGUAGE = "Course", "Language"


def build(path, seed=7):
    """A new collection at path (any old one goes). Returns what it holds."""
    from anki.collection import AddNoteRequest, Collection
    for ext in ("", "-wal", "-shm"):
        if os.path.exists(path + ext):
            os.remove(path + ext)
    rnd = random.Random(seed)
    col = Collection(path)
    try:
        course = col.decks.id(COURSE)
        language = col.decks.id(LANGUAGE)
        basic = col.models.by_name("Basic")
        cloze = col.models.by_name("Cloze")
        reqs = []
        n = 0
        for s, system in enumerate(SYSTEMS, 1):
            for t, topic in enumerate(TOPICS, 1):
                for k in range(12):
                    n += 1
                    note = col.new_note(basic)
                    note["Front"] = f"{system} {topic.lower()}: fact {n}?"
                    note["Back"] = f"Answer {n}"
                    note.tags = [f"#Course::{s:02d}_{system}::{t:02d}_{topic}",
                                 f"#Book::Chapter_{(n % CHAPTERS) + 1:02d}"]
                    reqs.append(AddNoteRequest(note, course))
        for k in range(100):
            note = col.new_note(cloze)
            note["Text"] = f"Word {k} means {{{{c1::meaning {k}}}}} in the {{{{c2::form {k % 7}}}}}"
            note.tags = [f"#Lang::{('Verbs', 'Nouns', 'Phrases')[k % 3]}::Set_{k // 20 + 1}"]
            reqs.append(AddNoteRequest(note, language))
        col.add_notes(reqs)
        _history(col, rnd)
        out = {"notes": col.note_count(), "cards": col.card_count(),
               "decks": {COURSE: int(course), LANGUAGE: int(language)}}
    finally:
        col.close()
    return out


def _history(col, rnd):
    """About half the cards studied over the last 30 days (never today): a
    review a day or two apart each, then due from today to three weeks out."""
    cids = list(col.find_cards(""))
    rnd.shuffle(cids)
    studied = cids[:len(cids) // 2]
    now_ms = int(time.time() * 1000)
    day_ms = 86_400_000
    rows, seq = [], 0
    for i, cid in enumerate(studied):
        first = rnd.randint(4, 30)
        ivl = 0
        for d in range(first, 0, -rnd.randint(2, 5)):
            seq += 1
            ease = 1 if rnd.random() < 0.12 else rnd.choice((3, 3, 3, 4, 2))
            last, ivl = ivl, max(1, ivl * 2 if ease > 1 else 1)
            at = now_ms - d * day_ms - rnd.randint(0, 6) * 3_600_000 + seq
            rows.append((at, cid, -1, ease, ivl, last, 2500, rnd.randint(3000, 20000), 1 if last else 0))
    col.db.executemany("insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                       "values (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    due_today = studied[:45]
    later = studied[45:]
    col.sched.set_due_date(due_today, "0")
    for k in range(0, len(later), 20):
        col.sched.set_due_date(later[k:k + 20], f"{1 + k // 20}-{3 + k // 20}")
