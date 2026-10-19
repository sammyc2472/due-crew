"""Labs, question IDs (docs/planner.md): after a practice block, the IDs of
the questions I missed, pasted any way the bank copies them, found in a
deck by its question tags (a last part of digits, under a bank's #part) and
brought back. Pure over a DeckIndex: the numbers come from the text, the
cards from the deck. Counted here; nothing is sent.

Every run of 3 to 9 digits is a number; only the ones the deck has as a
question count, so a date or a score pasted with them finds nothing and is
said as such ("3 numbers aren't questions here"), never guessed at.

Threads: what the missed questions have in common, by the deck's own tags
on their cards (by system, by resource): "Systems › Cardio · 9 of 15". A
question counts once a thread, however many cards it has. Over many
blocks (the misses this computer kept, flow.py), the same.
"""

import re

from .. import plans as P
from . import model as M

_NUM = re.compile(r"(?<![0-9])[0-9]{3,9}(?![0-9])")
_BANKS = ("#planner question banks",)  # a key no search is: kept with the index's searches


def numbers(text):
    """The numbers in pasted text, in the order first seen, once each, as
    the deck's tags have them (leading zeros off)."""
    out, seen = [], set()
    for m in _NUM.finditer(str(text or "")):
        n = m.group(0).lstrip("0") or "0"
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def banks(idx):
    """{bank: {number: {cid}}}: the deck's question tags, by bank (the tag's
    #part read, model.bank). Read once a deck, kept with its searches."""
    kept = idx._searches.get(_BANKS)
    if kept is None:
        kept = {}
        for low in idx.tag_keys:
            leaf = low.rsplit(M.SEP, 1)[-1].strip()
            if not leaf.isdigit():
                continue
            b = kept.setdefault(M.bank(idx.tag_names[low]), {})
            b.setdefault(leaf.lstrip("0") or "0", set()).update(idx.by_tag[low])
        idx._searches[_BANKS] = kept
    return kept


def find(idx, text, bank=None):
    """What a paste finds: {numbers, banks: [(bank, how many of the numbers it
    has)], bank (the one used: the asked one, else the one with the most),
    found: [number], missing: [number], cids: {cid}, by: {number: {cid}}}."""
    nums = numbers(text)
    all_banks = banks(idx)
    hits = sorted(((b, sum(1 for n in nums if n in q)) for b, q in all_banks.items()),
                  key=lambda x: (-x[1], x[0].lower()))
    hits = [h for h in hits if h[1]] or hits[:1]
    pick = bank if bank in all_banks else (hits[0][0] if hits else None)
    have = all_banks.get(pick) or {}
    by = {n: set(have[n]) for n in nums if n in have}
    cids = set().union(*by.values()) if by else set()
    return {"numbers": nums, "banks": hits, "bank": pick, "found": [n for n in nums if n in by],
            "missing": [n for n in nums if n not in by], "cids": cids, "by": by}


def tally(idx, cids):
    """{cards, open, shut (would open), leech (stay shut), new_shut, review}:
    review, the ones seen before (Anki's review cards, open or shut): what
    "bring back" puts due over the next days."""
    out = {"cards": 0, "open": 0, "shut": 0, "leech": 0, "new_shut": 0, "review": 0}
    for c in cids:
        queue, ctype = idx.cards[c]
        out["cards"] += 1
        if queue == -1:
            if c in idx.leech:
                out["leech"] += 1
                continue
            out["shut"] += 1
            out["new_shut"] += ctype == 0
        else:
            out["open"] += 1
        out["review"] += ctype == 2
    return out


def words(found, t, plan_dates=None):
    """The window's lines for a paste: [str]. found: find(); t: tally();
    plan_dates: [(plan name, [date label])] the cards are on, or None."""
    nums, got = found["numbers"], found["found"]
    if not nums:
        return ["Paste the IDs: Due Crew picks out the numbers."]
    lines = []
    if got:
        q = f"{len(got):,} question{'s' if len(got) != 1 else ''}"
        lines.append(f"{q} · {t['cards']:,} card{'s' if t['cards'] != 1 else ''} here")
        parts = [f"{t['open']:,} open already"] if t["open"] else []
        if t["shut"]:
            parts.append(f"{t['shut']:,} still shut")
        if t["leech"]:
            parts.append(f"{t['leech']:,} leech{'es' if t['leech'] != 1 else ''} stay shut")
        if parts:
            lines.append(", ".join(parts))
    else:
        lines.append("None of these are questions in this deck.")
    miss = found["missing"]
    if miss and got:
        shown = ", ".join(miss[:4]) + (" …" if len(miss) > 4 else "")
        lines.append(f"{len(miss):,} number{'s' if len(miss) != 1 else ''} aren’t questions here: {shown}"
                     if len(miss) != 1 else f"1 number isn’t a question here: {shown}")
    for name, dates in plan_dates or ():
        if dates:
            shown = ", ".join(dates[:3]) + (f" and {len(dates) - 3} more" if len(dates) > 3 else "")
            lines.append(f"On {name}: {shown}")
    return lines


THREADS = 6        # the threads a paste shows
THREAD_MIN = 2     # a thread is two questions or more


def _topic_paths(tag):
    """The paths a card's tag names a topic by, for threads: from the first
    part under its #/^ part down (Videos › Cardio, then › Heart failure); a
    tag with neither, from its first part (a #root left off). None for a
    question's own tag, Anki's leech and marked, and the plans' DueCrew tags."""
    low = str(tag).lower()
    if low in ("leech", "marked") or low == "duecrew" or low.startswith("duecrew::"):
        return []
    segs = str(tag).split(M.SEP)
    if segs[-1].strip().isdigit():
        return []
    ri = P._resource_at(segs)
    start = ri + 2 if ri >= 0 else (2 if len(segs) > 1 and segs[0][:1] in "#^" else 1)
    return [M.SEP.join(segs[:n]) for n in range(start, len(segs) + 1)]


def threads(idx, by, most=THREADS):
    """[{path, label, kind, n, of, qids, cids}]: the deck tags most of these
    questions share (by: {number: {cid}}, find()'s), most first; of each
    line of tags (Cardio, Cardio › Heart failure) the deepest one that has
    them all. A thread is THREAD_MIN questions or more."""
    tags_of = P._tags_of(idx)
    cover, spelled, cards = {}, {}, {}
    for q, cids in by.items():
        for c in cids:
            for low in tags_of.get(c, ()):
                for path in _topic_paths(idx.tag_names[low]):
                    k = path.lower()
                    cover.setdefault(k, set()).add(q)
                    cards.setdefault(k, set()).add(c)
                    spelled.setdefault(k, path)
    cand = sorted(((k, v) for k, v in cover.items() if len(v) >= THREAD_MIN),
                  key=lambda kv: (-len(kv[1]), -kv[0].count(M.SEP), kv[0]))
    chosen = []
    for k, v in cand:
        if len(chosen) >= most:
            break
        if any(k.startswith(o + M.SEP) or (o.startswith(k + M.SEP) and v == ov) for o, ov in chosen):
            continue  # under one already named, or above one that has the same questions
        chosen.append((k, v))
    n = len(by)
    return [{"path": spelled[k], "label": M.label(spelled[k]), "kind": M.kind(spelled[k]), "n": len(v), "of": n,
             "qids": sorted(v, key=lambda x: int(x)), "cids": cards[k]} for k, v in chosen]


def thread_words(t):
    """"Systems › Cardio · 9 of 15 questions"."""
    return f"{t['label']} · {t['n']:,} of {t['of']:,} question{'s' if t['of'] != 1 else ''}"


# ---- the misses this computer keeps (qids.json, flow.py: numbers only, never sent) ----

KEEP_PASTES = 200      # the pastes kept, newest
KEEP_NUMBERS = 20000   # numbers kept in all


def _nums(e):
    """A kept paste's numbers, as text; [] for one that isn't a list (a
    hand-edited or damaged qids.json never stops the window)."""
    n = e.get("n")
    return [str(x) for x in n if str(x).isdigit()] if isinstance(n, list) else []


def keep(log, day, did, bank, numbers):
    """The log with a paste's questions in it: one entry a day, deck and
    bank, its numbers once each; the newest KEEP_PASTES, KEEP_NUMBERS in all.
    log: [{day, deck, bank, n: [number]}], oldest first."""
    nums = [str(x) for x in numbers if str(x).isdigit()]
    out = [dict(e, n=_nums(e)) for e in log or [] if isinstance(e, dict)]
    if not nums:
        return out
    same = next((e for e in out if e.get("day") == day and e.get("deck") == did and e.get("bank") == bank), None)
    if same is None:
        same = {"day": str(day), "deck": did, "bank": str(bank or ""), "n": []}
        out.append(same)
    same["n"] += [x for x in nums if x not in set(same["n"])]
    out = out[-KEEP_PASTES:]
    while sum(len(e["n"]) for e in out) > KEEP_NUMBERS and len(out) > 1:
        out.pop(0)
    if out and len(out[-1]["n"]) > KEEP_NUMBERS:
        out[-1]["n"] = out[-1]["n"][-KEEP_NUMBERS:]
    return out


def kept(log, did, bank=None):
    """(numbers, pastes, since): every question kept for this deck (and
    bank, when given), once each, the newest paste's first; how many pastes;
    the first one's day."""
    mine = [e for e in log or [] if isinstance(e, dict) and e.get("deck") == did and (bank is None or e.get("bank") == bank)]
    seen, nums = set(), []
    for e in reversed(mine):
        for x in _nums(e):
            if x not in seen:
                seen.add(x)
                nums.append(x)
    return nums, len(mine), (mine[0].get("day") if mine else None)


def forget(log, did):
    """(the log without this deck's pastes, the ones taken out)."""
    gone = [e for e in log or [] if isinstance(e, dict) and e.get("deck") == did]
    return [e for e in log or [] if isinstance(e, dict) and e.get("deck") != did], gone
