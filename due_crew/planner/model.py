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
        rows.append({"key": ("search", q), "kind": "search", "group": GROUP["search"],
                     "name": str(q)[:60] + ("…" if len(str(q)) > 60 else ""), "raw": str(q),
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
