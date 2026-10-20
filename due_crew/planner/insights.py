"""Round five's Insights tab (docs/planner.md; Sam: "workload, content, the
amount of the deck relative to the whole"): what a plan asks and holds,
worked out. Workload: each week's new cards a study day and the reviews
they bring a day (a typical card's, view.week_asks), from the plan's
first week to its end. The deck: how many of its cards the plan holds,
and of each part of it (a big shared deck's resources and systems, else
its subdecks or top tags). What's in it: what each quiz or exam tests,
the biggest dates, cards on two dates, leeches. Pure: the plan doc and a
DeckIndex's cards, no Anki, no Qt; names and counts only."""

import datetime

from .. import plans as P
from . import build as B
from . import model as M
from . import view as V

SEP = "::"
_PARTS = ("#planner parts",)  # a key no search is: kept with the index's searches (they go when its notes change)
_ANKI_TAGS = {"leech", "marked", P.TAG_PARENT.lower()}  # Anki's own and the plans', never a part of the deck


def _d(iso):
    try:
        return datetime.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def held(idx, doc, swap=None):
    """({date id: its cards here}, every card on a date)."""
    per = {u["id"]: idx.match(u, swap, doc) for u in P.units(doc)}
    return per, set().union(*per.values()) if per else set()


def pct(part, whole):
    """"10%", "<1%", "all", "none"."""
    if not whole or not part:
        return "none"
    if part >= whole:
        return "all"
    p = part * 100 / whole
    return "<1%" if p < 1 else f"{int(p + 0.5) if p < 99 else 99}%"


# ---- workload ----

def _first(doc):
    days = [_d(u.get("opens")) for u in P.units(doc)] + [_d(e.get("day")) for e in doc.get("events") or [] if isinstance(e, dict)]
    days = [d for d in days if d]
    return min(days) if days else None


def _last(doc):
    days = [_d(B.last_day(doc)), _d(doc.get("end"))] + [_d(e.get("day")) for e in doc.get("events") or [] if isinstance(e, dict)]
    days = [d for d in days if d]
    return max(days) if days else None


def workload(doc, asks, today):
    """[{start, n, span, events, new, reviews, cards, over, top, cap, now,
    past}]: every week from the plan's first (week 1, as the Plan tab
    numbers them) to the one it ends in, a week with nothing new in it too.
    new is the new cards a study day that week, reviews the reviews a day
    they bring: two measures, two bars, never added (their days differ);
    cards is the week's whole, new and reviews, to find the busiest by;
    events the quizzes and exams that week."""
    first, last = _first(doc), _last(doc)
    if first is None or not asks:
        return []
    mon = first - datetime.timedelta(days=first.weekday())
    end = last - datetime.timedelta(days=last.weekday())
    evs = sorted((e for e in doc.get("events") or [] if isinstance(e, dict) and _d(e.get("day"))), key=lambda e: str(e["day"]))
    now = _d(today)
    out, n = [], 1
    while mon <= end:
        a = asks.get(mon.isoformat()) or {}
        sun = mon + datetime.timedelta(days=6)
        out.append({"start": mon.isoformat(), "n": n, "span": M.span_words(mon, sun),
                    "events": [str(e.get("name") or "?") for e in evs if mon <= _d(e["day"]) <= sun],
                    "new": int(a.get("new") or 0), "reviews": float(a.get("reviews") or 0),
                    "cards": float(a.get("new_week") or 0) + float(a.get("reviews_week") or 0),
                    "over": bool(a.get("over")), "top": int(a.get("top") or 0), "cap": int(a.get("cap") or 0),
                    "now": now is not None and mon <= now <= sun, "past": now is not None and sun < now})
        mon, n = mon + datetime.timedelta(days=7), n + 1
    return out


def new_words(w):
    """A week's new cards a study day: "20"; over the pace, its busiest day too ("18 · busiest day 41")."""
    return f"{w['new']:,} · busiest day {w['top']:,}" if w["over"] else f"{w['new']:,}"


def reviews_words(w):
    """A week's reviews a day: "~35", "0"."""
    r = B.about(w["reviews"])
    return "0" if r == "0" else f"~{r}"


def week_words(w):
    """The week in a sentence, for its tooltip: "Week 3, 26 Oct–1 Nov: 20
    new a study day, ~35 reviews a day; Cardio quiz"."""
    new = f"{w['new']:,} new a study day"
    if w["over"]:
        new += f" ({w['top']:,} on its busiest day, over the pace of {w['cap']:,})"
    out = f"Week {w['n']}, {w['span']}: {new}, {reviews_words(w)} reviews a day"
    return out + (f"; {', '.join(w['events'])}" if w["events"] else "")


def busiest(rows):
    """The week with the most cards in it, new and reviews, or None (the earlier on a tie)."""
    best = max(rows, key=lambda w: (w["cards"], -w["n"]), default=None)
    return best if best and best["cards"] > 0 else None


def workload_words(doc, rows, per_new):
    """The workload in a line: "1,284 new cards over 5 weeks. Busiest: week
    4, 2–8 Nov: 24 new a study day, ~115 reviews a day.", and the weeks
    over the pace ("Over the pace: weeks 3 and 5"), or ""."""
    if not rows:
        return "", ""
    total = sum(per_new.values())
    n = len(rows)
    words = f"{total:,} new card{'s' if total != 1 else ''} over {n} week{'s' if n != 1 else ''}."
    b = busiest(rows)
    if b:
        words += f" Busiest: week {b['n']}, {b['span']}: {b['new']:,} new a study day, {reviews_words(b)} reviews a day."
    over = [w["n"] for w in rows if w["over"]]
    if not over:
        return words, ""
    said = (f"week {over[0]}" if len(over) == 1
            else "weeks " + ", ".join(str(x) for x in over[:-1]) + f" and {over[-1]}")
    return words, f"Over the pace: {said}"


# ---- the deck, and how much of it the plan holds ----

def _tag_parts(idx):
    """{"resource": {name: {tag path}}, "system": {...}}: a big shared deck's
    #parts (Videos, Book, Bank) and the systems under its ^part (Cardio,
    Renal), each by the name it reads as, the same name under two roots one."""
    out = {"resource": {}, "system": {}}
    names = {}
    for low in idx.tag_keys:
        segs = low.split(SEP)
        ri = P._resource_at(segs)
        if ri < 0:
            continue
        spelled = idx.tag_names[low].split(SEP)
        if segs[ri].startswith("#"):
            how, j = "resource", ri
        else:
            how, j = "system", ri + 1 if len(segs) > ri + 1 else ri
        if segs[j].strip().isdigit():
            continue
        name = P._word(spelled[j])
        k = (how, name.lower())
        names.setdefault(k, name)
        out[how].setdefault(names[k], set()).add(SEP.join(segs[:j + 1]))
    return out


def _deck_parts(idx):
    """{name: {did}}: the deck's subdecks one level down."""
    out = {}
    for rel, did in idx.rel.items():
        if not rel:
            continue
        top = rel.split(SEP)[0]
        name = P._word(idx.spelled.get(top, top).split(SEP)[0] or top)
        out.setdefault(name, set()).add(did)
    return out


def _top_tags(idx):
    """{name: {tag path}}: the deck's tags by their first part, Anki's and the plans' own aside."""
    out = {}
    for low in idx.tag_keys:
        top = low.split(SEP)[0]
        if top.strip() in _ANKI_TAGS or top.strip().isdigit():
            continue
        out.setdefault(P._word(idx.tag_names[low].split(SEP)[0]), set()).add(top)
    return out


def parts(idx):
    """[(how, [(name, {cid})])]: the deck's parts as it files them:
    ("resource", …) and ("system", …) for a big shared deck's, else
    ("deck", …) its subdecks, else ("tag", …) its top tags; a way with one
    part only isn't one. Read once a deck, kept with its searches."""
    kept = idx._searches.get(_PARTS)
    if kept is not None:
        return kept
    out = []
    tp = _tag_parts(idx)
    for how in ("resource", "system"):
        if len(tp[how]) >= 2:
            out.append((how, [(name, set().union(*(idx.tag_cards(k) for k in keys))) for name, keys in tp[how].items()]))
    if not out:
        dp = _deck_parts(idx)
        if len(dp) >= 2:
            out.append(("deck", [(name, set().union(*(idx.by_deck.get(d, ()) for d in dids)) & idx.home)
                                 for name, dids in dp.items()]))
    if not out:
        tt = _top_tags(idx)
        if len(tt) >= 2:
            out.append(("tag", [(name, set().union(*(idx.tag_cards(k) for k in keys))) for name, keys in tt.items()]))
    idx._searches[_PARTS] = out
    return out


HOW = {"resource": "By resource", "system": "By system", "deck": "By subdeck", "tag": "By tag"}


def shares(groups, cards):
    """[(how, [{name, held, total}], [{name, held, total}])]: each part's
    cards and how many of them the plan holds, the parts it holds some of
    biggest first (drawn on one scale, so a big part looks big: the deck's
    whole, not each part's own), then the ones it holds none of, biggest
    first."""
    out = []
    for how, rows in groups:
        have, none = [], []
        for name, cids in rows:
            if not cids:
                continue
            n = len(cids & cards)
            (have if n else none).append({"name": name, "held": n, "total": len(cids)})
        have.sort(key=lambda r: (-r["total"], r["name"].lower()))
        none.sort(key=lambda r: (-r["total"], r["name"].lower()))
        out.append((how, have, none))
    return out


def none_words(none, most=4):
    """"Not in it: Renal, Repro, Psych and 6 more"."""
    if not none:
        return ""
    names = [r["name"] for r in none[:most]]
    more = len(none) - len(names)
    return "Not in it: " + ", ".join(names) + (f" and {more:,} more" if more else "")


def deck_words(name, cards, total):
    """"1,284 of Big Step 1's 12,480 cards (10%)"."""
    owner = f"{name}'s" if name else "the deck's"
    return f"{cards:,} of {owner} {total:,} cards ({pct(cards, total)})"


# ---- what's in it ----

def exams(doc, per, cards):
    """[{id, day, name, cards, dates}]: each quiz or exam by its day, with
    the cards on the dates that prep for it (view.prep); the last one with
    no date for it tests everything."""
    evs = sorted((e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("id")), key=lambda e: str(e.get("day")))
    last = V.last_event(doc)
    out = []
    for e in evs:
        us = V.prep(doc, e)
        if us:
            got = set().union(*(per.get(u["id"], set()) for u in us))
        else:
            got = cards if e is last else set()
        out.append({"id": e["id"], "day": str(e.get("day")), "name": str(e.get("name") or "?"),
                    "cards": len(got), "dates": len(us), "all": not us and e is last})
    return out


def exam_words(x):
    """"55 cards from 3 dates", "everything: 1,284 cards", "no date for it yet"."""
    if x["all"]:
        return f"everything: {x['cards']:,} cards"
    if not x["dates"]:
        return "no date for it yet"
    return f"{x['cards']:,} cards from {x['dates']:,} date{'s' if x['dates'] != 1 else ''}"


def biggest(doc, per, most=5):
    """[(date, cards)]: the dates holding the most cards, most first (the earlier first on a tie)."""
    us = [u for u in P.units(doc) if per.get(u["id"])]
    us.sort(key=lambda u: (-len(per[u["id"]]), str(u.get("opens"))))
    return [(u, len(per[u["id"]])) for u in us[:most]]


def on_two(per):
    """How many cards are on two dates or more (they open with the first)."""
    seen, twice = set(), set()
    for cids in per.values():
        twice |= cids & seen
        seen |= cids
    return len(twice)
