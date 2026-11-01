"""Labs, the plan window's pure parts (docs/planner.md): a plan's weeks, a
date's sources one by one with what each holds in this copy, and the deck's
tags as a tree and a search, for the picker. Over a plan doc and a DeckIndex
(plans.py); no aqt, no network, no config.

A deck tag is named the way the deck files it: the first part after its
root that starts # is a resource (a video series, a book, a bank), ^ a
system; a last part of digits is a bank's question, by its number. Names
and counts only: the window escapes nothing because Qt shows them as text.
"""

import bisect
import datetime
import math
import re
import time

from .. import plans as P
from .. import schedule as S

SEP = "::"

# the groups of a date's sources, in the window's order
ORDER = ("resource", "system", "other", "question", "plan", "deck", "search", "picks")
GROUP = {"other": "Other tags", "plan": "This plan’s tags", "deck": "Subdecks",
         "search": "Searches", "picks": "Picked cards"}


# ---- a deck tag ----

def is_question(path):
    """A bank's question: its last part is only digits."""
    return str(path).rsplit(SEP, 1)[-1].strip().isdigit()


def kind(path):
    """"question", "resource" (#), "system" (^) or "other"."""
    if is_question(path):
        return "question"
    segs = str(path).split(SEP)
    ri = P._resource_at(segs)
    if ri < 0:
        return "other"
    return "system" if segs[ri].startswith("^") else "resource"


def split(path):
    """(group, topic) as the window names a deck tag: ("Videos", "Cardio ›
    Heart failure"). A tag with no #/^ part has group "" and its whole path
    for a topic, a #root left off; a resource tag itself has topic ""."""
    segs = str(path).split(SEP)
    ri = P._resource_at(segs)
    if ri >= 0:
        return P._word(segs[ri]), " › ".join(P._word(s) for s in segs[ri + 1:])
    rest = segs[1:] if len(segs) > 1 and segs[0][:1] in "#^" else segs
    return "", " › ".join(P._word(s) for s in rest)


def bank(path):
    """A question tag's bank: its #/^ part read, else its first part read."""
    segs = str(path).split(SEP)
    ri = P._resource_at(segs)
    return P._word(segs[ri]) if 0 <= ri < len(segs) - 1 else P._word(segs[0])


def label(path):
    """One line for a deck tag: "Videos › Cardio › Heart failure"."""
    g, t = split(path)
    return " › ".join(x for x in (g, t) if x) or str(path)


def counts(idx, cids):
    """{cards, new, open, shut, leech} for these cards here: new as plans
    counts it (not seen: a new sibling of a started note is seen), shut
    suspended, leech the suspended leeches (a plan never opens one)."""
    cids = set(cids)
    opened, seen, total = idx.counts(cids)
    leech = sum(1 for c in cids if c in idx.leech and idx.cards[c][0] == -1)
    return {"cards": total, "new": total - seen, "open": opened, "shut": total - opened, "leech": leech}


# ---- a date's sources ----

def sources(idx, unit, doc, swap=None):
    """[{key, kind, group, name, raw, cids}]: a date's sources here, one row
    each, grouped as ORDER has them (resources by first appearance). key
    says which part of the date it is, for taking it off: ("tag", path),
    ("cut", tag, in), ("deck", path), ("search", q), ("picks",). A bank's
    questions are one row a bank; raw is what Anki calls it (a tooltip)."""
    doc = doc if isinstance(doc, dict) else {}
    own = P.plan_tag_map(doc)
    rows, banks = [], {}
    for t in unit.get("tags") or []:
        pt = own.get(str(t).lower())
        cids = idx.match({"tags": [t]}, swap, doc)
        if pt:
            rows.append({"key": ("tag", t), "kind": "plan", "group": GROUP["plan"],
                         "name": str(pt.get("name") or "?"), "raw": str(t), "cids": cids})
            continue
        k = kind(t)
        if k == "question":
            b = banks.setdefault(bank(t), {"tags": [], "cids": set()})
            b["tags"].append(t)
            b["cids"] |= cids
            continue
        g, topic = split(t)
        rows.append({"key": ("tag", t), "kind": k, "group": g or (GROUP["other"] if k == "other" else "?"),
                     "name": topic or "all of it", "raw": str(t), "cids": cids})
    cut_q = set()
    for c in unit.get("cut") or []:
        pt = own.get(("id", c.get("in")))
        if not pt:
            continue  # its plan tag went: its search reads it, as an older add-on does
        cut_q.add(c.get("q"))
        g, topic = split(c.get("tag"))
        k = kind(c.get("tag"))
        rows.append({"key": ("cut", c.get("tag"), c.get("in")), "kind": k if k != "question" else "other",
                     "group": g or GROUP["other"], "name": f"{topic or 'all of it'} · {pt.get('name') or '?'}",
                     "raw": str(c.get("tag")), "cids": idx.match({"cut": [c]}, swap, doc)})
    for name, b in banks.items():
        n = len(b["tags"])
        rows.append({"key": ("questions", tuple(b["tags"])), "kind": "question", "group": name,
                     "name": f"{n:,} question{'s' if n != 1 else ''}", "raw": " ".join(b["tags"][:3]) + (" …" if n > 3 else ""),
                     "cids": b["cids"]})
    for d in unit.get("decks") or []:
        segs = str(d).split(SEP)
        rel = segs[1:] or segs
        rows.append({"key": ("deck", d), "kind": "deck", "group": GROUP["deck"],
                     "name": " › ".join(P._word(s) for s in rel), "raw": str(d),
                     "cids": idx.match({"decks": [d]}, swap, doc)})
    for q in unit.get("search") or []:
        if q in cut_q:
            continue
        # 3.9.3: named as the builder names it ("SLG 12 but not Pharm"); and "Path Book · the rest" (plans end to end)
        rows.append({"key": ("search", q), "kind": "search", "group": GROUP["search"],
                     "name": search_label(q), "raw": str(q),
                     "cids": idx.match({"search": [q]}, swap, doc)})
    picked = P.picks(unit)
    if picked:
        n = len(unit.get("cards") or []) + len(unit.get("cids") or [])
        m = len(unit.get("notes") or []) + len(unit.get("nids") or [])
        words = ", ".join(x for x in (f"{n:,} single card{'s' if n != 1 else ''}" if n else "",
                                      f"{m:,} note{'s' if m != 1 else ''}" if m else "") if x)
        rows.append({"key": ("picks",), "kind": "picks", "group": GROUP["picks"], "name": words or "picked",
                     "raw": "", "cids": idx.match(picked, swap, doc)})
    first = {}
    for i, r in enumerate(rows):
        first.setdefault((ORDER.index(r["kind"]), r["group"]), i)
    rows.sort(key=lambda r: (ORDER.index(r["kind"]), first[(ORDER.index(r["kind"]), r["group"])]))
    return rows


def grouped(rows):
    """[(group, [row])] in the rows' order."""
    out, at = [], {}
    for r in rows:
        key = (r["kind"] if r["kind"] in ("plan", "deck", "search", "picks") else "tags", r["group"])
        if key not in at:
            at[key] = len(out)
            out.append((r["group"], []))
        out[at[key]][1].append(r)
    return out


# ---- the plan's weeks ----

def _d(iso):
    try:
        return datetime.date.fromisoformat(str(iso))
    except ValueError:
        return None


def span_words(a, b):
    """"9–13 Nov", "30 Nov–4 Dec", "Mon 9 Nov" for one day."""
    if a == b:
        return f"{a:%a} {a.day} {a:%b}"
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}–{b.day} {b:%b}"
    return f"{a.day} {a:%b}–{b.day} {b:%b}"


def weeks(doc, today):
    """The plan's weeks with something on them, first to last: [{start (its
    Monday), n (week n of the plan), label, now, dates: [unit], events: [event]}],
    each date and event under the week of its day. label: "Week 3 · 9–13 Nov",
    from the first to the last day with something on it."""
    us = [u for u in P.units(doc) if _d(u.get("opens"))]
    evs = [e for e in (doc or {}).get("events") or [] if isinstance(e, dict) and _d(e.get("day"))]
    days = [_d(u["opens"]) for u in us] + [_d(e["day"]) for e in evs]
    if not days:
        return []
    first = S.monday(min(days))
    now = _d(today)
    by = {}
    for u in sorted(us, key=lambda x: str(x["opens"])):
        by.setdefault(S.monday(_d(u["opens"])), {"dates": [], "events": []})["dates"].append(u)
    for e in sorted(evs, key=lambda x: str(x["day"])):
        by.setdefault(S.monday(_d(e["day"])), {"dates": [], "events": []})["events"].append(e)
    out = []
    for mon in sorted(by):
        w = by[mon]
        on = [_d(u["opens"]) for u in w["dates"]] + [_d(e["day"]) for e in w["events"]]
        n = (mon - first).days // 7 + 1
        out.append({"start": mon.isoformat(), "n": n, "label": f"Week {n} · {span_words(min(on), max(on))}",
                    "now": now is not None and S.monday(now) == mon, "dates": w["dates"], "events": w["events"]})
    return out


def day_words(iso):
    """"Mon 9" (the week's line says the month)."""
    d = _d(iso)
    return f"{d:%a} {d.day}" if d else str(iso)


def date_label(u):
    return f"{day_words(u.get('opens'))} · {u.get('name') or '?'}"


def event_label(e):
    return f"{day_words(e.get('day'))} · {e.get('name') or '?'}"


def pick_week(ws, today):
    """The week to open on: this one, else the next one ahead, else the last."""
    if not ws:
        return None
    for w in ws:
        if w["now"]:
            return w
    return next((w for w in ws if w["start"] > str(today)), ws[-1])


def study_days(doc, unit):
    """(first, last, study days) of a date's window (schedule.window: its
    opens to its due, or to the day before the next date opens), counting
    the plan's study days (its pace; catch-up weeks and the taper are none)."""
    a, b = S.window(doc, unit)
    n, day = 0, a
    while day <= b:
        n += S.weight(doc, None, day) > 0
        day += datetime.timedelta(days=1)
    return a, b, n


def pace_words(doc, unit, new):
    """"over 3 study days, about 35 a day", or "" for a date of one day or none new."""
    _a, _b, n = study_days(doc, unit)
    if new <= 0 or n <= 1:
        return ""
    return f"over {n} study days, about {math.ceil(new / n):,} a day"


def first_here(idx, doc, swap=None):
    """{unit id: cards it's the first date to hold}, in date order (as the
    builder's "new here")."""
    seen, out = set(), {}
    for u in sorted(P.units(doc), key=lambda x: str(x.get("opens") or "")):
        cids = idx.match(u, swap, doc)
        out[u["id"]] = cids - seen
        seen |= cids
    return out


# ---- the deck's tags, for the picker ----

def children(idx, parent=""):
    """The tags one level under `parent` ("" for the top), as this copy
    writes them: [(path, name, has_children)], #-parts first, then ^, then
    the rest, each by name. A bank's questions (digit leaves) aren't listed:
    questions() counts them."""
    keys = idx.tag_keys
    low = str(parent).lower()
    if low:
        lo = bisect.bisect_left(keys, low + SEP)
        hi = bisect.bisect_left(keys, low + ":;")
        depth = low.count(SEP) + 1
    else:
        lo, hi, depth = 0, len(keys), 0
    seen = {}
    for k in keys[lo:hi]:
        parts = k.split(SEP)
        if len(parts) <= depth:
            continue
        child = SEP.join(parts[:depth + 1])
        if child in seen:
            seen[child][1] = seen[child][1] or len(parts) > depth + 1
            continue
        spelled = SEP.join(idx.tag_names[k].split(SEP)[:depth + 1])
        seen[child] = [spelled, len(parts) > depth + 1]
    out = []
    for child, (spelled, more) in seen.items():
        leaf = spelled.rsplit(SEP, 1)[-1]
        if leaf.strip().isdigit():
            continue
        out.append((spelled, P._word(leaf), more))
    order = lambda x: (0 if x[0].rsplit(SEP, 1)[-1][:1] == "#" else 1 if x[0].rsplit(SEP, 1)[-1][:1] == "^" else 2,
                       x[1].lower())
    return sorted(out, key=order)


def questions(idx, parent):
    """How many question tags (digit leaves) sit right under `parent`."""
    keys = idx.tag_keys
    low = str(parent).lower()
    lo = bisect.bisect_left(keys, low + SEP)
    hi = bisect.bisect_left(keys, low + ":;")
    depth = low.count(SEP) + 1
    return sum(1 for k in keys[lo:hi] if k.count(SEP) == depth and k.rsplit(SEP, 1)[-1].strip().isdigit())


_PATHS = ("#planner paths",)  # a key no search is: kept with the index's searches (they go when its notes change)


def _paths(idx):
    """[(lowercased path, as written, its words)]: every tag here and every
    path above one, question leaves aside. Read once a deck, then kept."""
    kept = idx._searches.get(_PATHS)
    if kept is None:
        got = {}
        for low in idx.tag_keys:
            parts, spelled = low.split(SEP), idx.tag_names[low].split(SEP)
            for n in range(1, len(parts) + 1):
                if parts[n - 1].strip().isdigit():
                    break
                key = SEP.join(parts[:n])
                if key not in got:
                    got[key] = SEP.join(spelled[:n])
        kept = sorted((k, v, k.replace("_", " ")) for k, v in got.items())
        idx._searches[_PATHS] = kept
    return kept


def find(idx, text, most=200):
    """Deck tags whose path holds every word of `text` (any case, _ as a
    space): [path as written], shallow before deep, at most `most`."""
    words = [w for w in str(text or "").lower().replace("_", " ").split() if w]
    if not words:
        return []
    hits = [(v.count(SEP), v.lower(), v) for k, v, words_of in _paths(idx) if all(w in words_of for w in words)]
    hits.sort()
    return [v for _d, _l, v in hits[:most]]


def tag_count(idx, path):
    """(cards, new) under a deck tag here."""
    cids = idx.tag_cards(path)
    c = counts(idx, cids) if cids else {"cards": 0, "new": 0}
    return c["cards"], c["new"]


def ago(at, now=None):
    """The builder's ago2, a history line's or a post's time: "just now",
    "5 min ago", "3 h ago", else the day."""
    m = round(((now if now is not None else time.time()) - int(at or 0)) / 60)
    if m < 1:
        return "just now"
    if m < 60:
        return f"{m} min ago"
    if m < 1440:
        return f"{round(m / 60)} h ago"
    return P.fmt_day(datetime.date.fromtimestamp(int(at)).isoformat())


# ---- plans end to end: a source's own search, a search's name, the tags beside some cards ----

def source_search(unit, key, swap=None):
    """One of a date's sources as an Anki search, to paste into Browse (the
    builder's Copy search on a chip): a tag's or a subdeck's
    (Tags.ankiSearch; a tag in this copy's spelling with a swap), a cut's
    own search, a search itself, a bank's questions any of them. None for
    picked cards: Show in Browse finds them."""
    from . import build as B
    k = key[0] if key else ""
    if k == "tag":
        return B.anki_search("tag", P.swapped(key[1], swap))
    if k == "deck":
        return B.anki_search("deck", key[1])
    if k == "cut":
        c = next((c for c in unit.get("cut") or [] if c.get("tag") == key[1] and c.get("in") == key[2]), None)
        return str(c["q"]) if c and c.get("q") else None
    if k == "search":
        return str(key[1])
    if k == "questions":
        qs = [B.anki_search("tag", P.swapped(t, swap)) for t in key[1]]
        return ("(" + " OR ".join(qs) + ")" if len(qs) > 1 else qs[0]) if qs else None
    return None


def date_search(unit, swap=None):
    """The whole date as one Anki search (⋯ › Copy its search for Anki): its
    tags and subdecks, and each of its searches in brackets, any of them;
    None for a date of picked cards only."""
    from . import build as B
    parts = ([B.anki_search("tag", P.swapped(t, swap)) for t in unit.get("tags") or []]
             + [B.anki_search("deck", d) for d in unit.get("decks") or []]
             + [f"({q})" for q in unit.get("search") or []])
    return (" OR ".join(parts) if len(parts) > 1 else parts[0]) if parts else None


_TERM = re.compile(r'(-?)\(?(?:"(tag|deck):((?:\\.|[^"\\])+)"|(tag|deck):((?:\\.|[^\s"()])+))', re.I)


def _terms(q):
    """[(negated, "tag" | "deck", path)]: a search's tag and subdeck terms, quoted (a subdeck's spaces) or not."""
    return [(neg == "-", (k1 or k2).lower(), re.sub(r"\\(.)", r"\1", p1 or p2)) for neg, k1, p1, k2, p2 in _TERM.findall(str(q))]


def _term_word(path):
    from . import build as B
    parts = [x for x in str(path).split(SEP) if x.replace("*", "")]
    return B.tag_word(parts[-1]).replace("*", "") if parts else ""


def search_label(q):
    """A search's name in Your plans: build.search_name's (the builder's),
    and what that can't read: the rest of a tag, its cards on none of the
    tags under it ("tag:X" -"tag:X::*": "Path Book · the rest"), and what
    Leave out writes on a tag kept to one of the plan's own or on a subdeck
    ("Hemolytic · High Yield but not Bank", "Cardio but not Extra")."""
    from . import build as B
    terms = _terms(q)
    pos = [(k, p) for n, k, p in terms if not n]
    have = {p.lower() for k, p in pos if k == "tag"}
    rest = {p[:-3].lower() for n, k, p in terms if n and k == "tag" and p.endswith("::*") and p[:-3].lower() in have}
    negs = [p for n, k, p in terms if n and not (k == "tag" and p.endswith("::*") and p[:-3].lower() in rest)]
    own = [p for k, p in pos if k == "tag" and p.lower().startswith(P.TAG_PARENT.lower() + SEP)]
    cut_like = len(pos) == 2 and len(own) == 1 and bool(negs)
    deck_less = any(k == "deck" for k, _p in pos) and bool(negs)
    if not pos or not (rest or cut_like or deck_less):
        return B.search_name(q)
    names = [_term_word(p) + (" · the rest" if k == "tag" and p.lower() in rest else "") for k, p in pos]
    if len(pos) == 2 and len(own) == 1:
        i = 0 if pos[0][1] == own[0] else 1
        main = f"{names[1 - i]} · {names[i]}"
    else:
        main = " and ".join(names)
    return f"{main} but not {', '.join(_term_word(p) for p in negs)}" if negs else main


def also_tagged(idx, cids, skip=(), most=12):
    """[(tag as written, n)]: the tags some of these cards carry and some
    don't (each tag, and every tag above one), the most cards first: what
    Keep only and Leave out cards also tagged can name, and A resource's
    Only. skip: tags left out with everything under and above them (the
    source's own); leech, marked, a bank's questions and Due Crew's never."""
    cids = set(cids)
    if not cids:
        return []
    of = P._tags_of(idx)
    lows = [str(s).lower() for s in skip]

    def skipped(low):
        return any(low == s or low.startswith(s + SEP) or s.startswith(low + SEP) for s in lows)
    count, spelled = {}, {}
    for c in cids:
        mine = set()
        for low in of.get(c) or ():
            parts, written = low.split(SEP), idx.tag_names.get(low, low).split(SEP)
            for n in range(1, len(parts) + 1):
                mine.add(SEP.join(parts[:n]))
                spelled.setdefault(SEP.join(parts[:n]), SEP.join(written[:n]))
        for low in mine:
            count[low] = count.get(low, 0) + 1
    out = [(spelled[low], n) for low, n in count.items()
           if 0 < n < len(cids) and low.split(SEP)[0] not in ("leech", "marked", P.TAG_PARENT.lower())
           and not is_question(low) and not skipped(low)]
    out.sort(key=lambda x: (-x[1], x[0].count(SEP), x[0].lower()))
    return out[:most]


def on_dates(doc, key):
    """The dates a deck tag or subdeck (a tree key, "tag:PATH") is on, in
    date order: as itself or under one of a date's tags or subdecks, a cut's
    tag (kept to a plan tag), or a search's own tag (what Leave out and the
    rest of a tag write: its first tag that isn't the plan's): the deck's
    "on Mon 9" for a chapter a resource plan keeps to its Only."""
    kind_, path = key.split(":", 1)
    low = path.lower()

    def holds(p):
        p = str(p).lower()
        return low == p or low.startswith(p + SEP)
    out = []
    for u in sorted(P.units(doc), key=lambda x: str(x.get("opens") or "")):
        srcs = list(u.get("tags" if kind_ == "tag" else "decks") or [])
        if kind_ == "tag":
            srcs += [c.get("tag") for c in u.get("cut") or []]
        for q in u.get("search") or []:
            terms = _terms(q)
            main = next((p for n, k, p in terms if not n and k == kind_
                         and not p.lower().startswith(P.TAG_PARENT.lower() + SEP)), None)
            out_of = any(n and k == kind_ and (holds(p) or (p.endswith("::*") and low.startswith(p[:-3].lower() + SEP)))
                         for n, k, p in terms)
            if main and not out_of:
                srcs.append(main)
        if any(holds(p) for p in srcs):
            out.append(u["id"])
    return out


# ---- plans end to end: A resource, at my pace (edits.resource_plan makes the plan) ----

def resource_name(path, only=None):
    """The plan's name from its part and its Only: "Path Book, high yield"."""
    name = label(path)
    if only:
        name = f"{name}, {P._word(str(only).split(SEP)[-1]).lower()}"
    return name[:60]


def chapters(tree, path):
    """A part's chapters, as A resource lays them out: the tags right under
    it that aren't a bank's questions, in the deck's order (the tree's,
    build.natural); [] for a part with none."""
    from . import build as B
    return [B.path_of(k) for k in tree.kids(f"tag:{path}") if B.kind_of(k) == "tag" and not is_question(B.path_of(k))]


def only_count(idx, path, only):
    """(the part's cards Only keeps, the part's cards) here: "2,110 of 3,924"."""
    whole = idx.tag_cards(path)
    return (len(whole & idx.tag_cards(only)) if only else len(whole)), len(whole)


def resource_parts(idx, tree, text="", most=8):
    """Which part (A resource's first question): [{path, name, chapters,
    questions, cards}], the deck's tags with chapters (or a bank's
    questions) right under them, found by `text`'s words (find's rule) or,
    with none, the deck's resources (a #part, and each tag right under
    one); the most chapters first, then the most cards."""
    from . import build as B
    if str(text or "").strip():
        paths = find(idx, text, most=400)
    else:
        paths = []
        for _k, v, _w in _paths(idx):
            segs = v.split(SEP)
            ri = P._resource_at(segs)
            if ri >= 0 and ri >= len(segs) - 2:  # a resource itself, or a tag right under one
                paths.append(v)
    out, seen = [], set()
    for p in paths:
        if p.lower() in seen:
            continue
        seen.add(p.lower())
        ch = chapters(tree, p) if tree is not None else [c for c, _n, _m in children(idx, p)]
        qs = questions(idx, p)
        if len(ch) < 2 and not qs:
            continue
        n = tree.n(f"tag:{p}") if tree is not None and tree.has(f"tag:{p}") else len(idx.tag_cards(p))
        out.append({"path": p, "name": label(p), "chapters": len(ch), "questions": qs, "cards": n})
    out.sort(key=lambda r: (r["chapters"] < 2, -r["chapters"], -r["cards"], B.natural(r["path"])))
    return out[:most]
