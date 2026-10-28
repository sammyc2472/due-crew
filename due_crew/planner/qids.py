"""QBank QIDs (docs/planner.md): a block's question IDs (missed or not),
pasted any way the bank copies them, found in a deck by
its question tags (a last part of digits, under a bank's #part). Pure over
a DeckIndex: the numbers come from the text, the cards from the deck.
Counted here; nothing is sent, nothing kept (3.9.3: the window reads this
paste only).

Every run of 3 to 9 digits is a number; only the ones the deck has as a
question count, so a date or a score pasted with them finds nothing and is
said as such ("3 numbers aren't questions here"), never guessed at.

3.9.3 (Sam): no In common; what's not sticking is Insights' to say, from
my answers once I've studied them. 3.9.5 (Study where the cards are):
Their topics, the map's parts the questions are in (topics), each with
the map's % and a Study of what I missed there.
"""

import re

from .. import team as T
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


def close(found):
    """Whether the paste's banks are close enough to ask which (3.9.3, Sam):
    the runner-up has at least half as many of its numbers as the first. One
    stray number in another bank isn't a question."""
    hits = [n for _b, n in found.get("banks") or () if n]
    return len(hits) > 1 and 2 * hits[1] >= hits[0]


def tally(idx, cids):
    """{cards, open, shut (Unsuspend would open), leech (stay suspended),
    new_shut, review}: review, the ones seen before (Anki's review cards,
    open or suspended)."""
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
    """The window's lines for a paste: [str], the counts first ([] for
    nothing pasted). found: find(); t: tally(); plan_dates: [(plan name,
    [date label])] the cards are on, or None."""
    nums, got = found["numbers"], found["found"]
    if not nums:
        return []
    if got:
        bits = [f"{len(got):,} question{'s' if len(got) != 1 else ''}", f"{t['cards']:,} card{'s' if t['cards'] != 1 else ''}"]
        if t["shut"]:
            bits.append(f"{t['shut']:,} suspended")
        if t["leech"]:
            bits.append(f"{t['leech']:,} leech{'es' if t['leech'] != 1 else ''} left suspended")
        lines = [" · ".join(bits)]
    else:
        lines = ["None of these are questions in this deck."]
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


TOPICS_SHOWN = 5  # Their topics: rows, the most questions first; the rest named in a line


def topics(idx, found, tiles, missed=()):
    """3.9.5 (Study where the cards are): the parts of the deck's map a
    paste's questions are in, by the map's split for this deck (tiles: its
    top level, team_flow.deck_map). [{i (its place on the map), name,
    questions, know, started, missed: [cid]}], the most questions first,
    then the map's order. A question counts once in each part its cards
    are in. A card falls in the tile holding it (a card in play), else in
    the biggest whose tags or subdeck it has: a bank's cards are often
    suspended, and the map holds only the ones in play (a card in two
    parts goes to the bigger, as the map has it). A card in none isn't
    said. missed: the map's (team_flow._missed), what each part's Study
    takes."""
    cids = set(found.get("cids") or ())
    tiles = list(tiles or ())
    if not cids or len(tiles) < 2:
        return []
    where, rest = {}, set(cids)
    for i, t in enumerate(tiles):
        for c in rest.intersection(T.tile_cards(t)):
            where[c] = i
        rest -= set(where)
    for t_i, t in enumerate(tiles):
        if not rest:
            break
        f = t.get("find") or {}
        got = set()
        for tag in f.get("tags") or ():
            got |= idx.tag_cards(tag)
        for path in f.get("decks") or ():
            got |= idx.deck_cards(path)
        for c in rest & got:
            where[c] = t_i
        rest -= got
    count = {}
    for n in found.get("found") or ():
        for i in {where[c] for c in (found.get("by") or {}).get(n, ()) if c in where}:
            count[i] = count.get(i, 0) + 1
    rows = [{"i": i, "name": str(tiles[i].get("name") or ""), "questions": q, "know": tiles[i].get("know"),
             "started": int(tiles[i].get("started") or 0), "missed": T.missed_in(tiles[i], missed)}
            for i, q in count.items()]
    rows.sort(key=lambda r: (-r["questions"], r["i"]))
    return rows


def topic_words(rows):
    """Each topic's line under its name, as the map has its part: "2
    questions · 66% here" (the first with a % says where; the rest, the %
    alone), "1 question · new", "1 question · too soon to say"."""
    out, said = [], False
    for r in rows:
        q, k = r["questions"], r["know"]
        if k is None:
            how = "too soon to say" if r["started"] else "new"
        else:
            how = f"{int(k)}%" + ("" if said else " here")
            said = True
        out.append(f"{q:,} question{'s' if q != 1 else ''} · {how}")
    return out


def more_topics(rows, shown=TOPICS_SHOWN):
    """The topics past the rows shown, in a line: "Also: Endo, MSK and 2 more", or ""."""
    rest = [r["name"] for r in rows[shown:]]
    if not rest:
        return ""
    names = rest[:3]
    return "Also: " + ", ".join(names) + (f" and {len(rest) - len(names):,} more" if len(rest) > len(names) else "")
