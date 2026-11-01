"""What the HTML plan window draws (web.py), worked out here as plain
data: the plan's head, its lessons by week (List, Week, Month read the
same), the picked one's panel, the deck beside it. Pure: a window (a
core.PlanCore) and the window's own state in, dicts out, every name
the authors' and the deck's, plain text (the page sets textContent).

The Qt tabs (plan_tab.py, date_panel.py, deck_panel.py) work the same
things out the same way; this is their HTML face's."""

from .. import plans as P
from . import build as B
from . import edits as E
from . import model as M
from . import view as V
from .core import pick_label

VIEWS = (("resource", "By resource"), ("system", "By system"), ("other", "Other"), ("deck", "Subdecks"),
         ("plan", "The plan's own tags"))
FOUND_MAX = 200


def chip_name(r):
    g, n = str(r.get("group") or ""), str(r.get("name") or "")
    if r.get("kind") in ("search", "picks", "plan", "deck") or not g or g == "?" or g.lower() in n.lower():
        return n
    return f"{g} › {n}"


def _pl(n, word, many=None):
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


# ---- the head ----

def head(w):
    return {
        "plans": [{"id": p["id"], "label": pick_label(p)} for p in w.plans],
        "pid": (w.plan or {}).get("id") or w.current_pid(),
        "author": w.author(),
        "loaded": w.doc is not None,
        "owner": (w.plan or {}).get("role") == "owner",
        "name": w.plan_name(),
        "followers": w.followers(),
        "busy": bool(w.busy),
        "undo": [{"label": label, "what": list(what) if what else None, "on": bool(on and what)}
                 for label, what, on in w.undo_entries()],
    }


# ---- the Plan tab ----

def work_out(w):
    """(asks, counts, look, heavy), as plan_tab._work_out."""
    doc, t = w.doc, w.deck_tree()
    pace = V.pace_of(doc)
    asks = V.week_asks(doc, t, pace) if t is not None else {}
    counts = {u["id"]: len(w.idx.match(u, w.swap, doc)) for u in P.units(doc)} if w.idx is not None else {}
    look = V.needs_look(doc, counts, asks) if w.author() else {}
    heavy = None
    if w.author() and t is not None:
        placed = B.placed_keys(doc, t)
        hv = B.heavy(doc, t, pace, set(pace.get("cover") or []), B.plan_start(doc, w.ops.today()),
                     lambda u: B.unit_total(t, u, placed), w.ops.today())
        if hv:
            big = B.biggest(t, hv["unit"], placed)
            till = B.give_till(doc, pace.get("days") or [1] * 7, hv["unit"], hv["total"], hv["cap"])
            name = hv["unit"].get("name") or "a set"
            when = M.day_words(hv["a"]) if hv["a"] == hv["b"] else f"{M.day_words(hv['a'])} – {M.day_words(hv['b'])}"
            heavy = {"week": V.monday(hv["a"]), "uid": hv["unit"]["id"],
                     "words": f"{when}: {hv['top']:,} new a day, your pace is {hv['cap']:,}. "
                              f"{name} is {hv['total']:,} cards by {M.day_words(hv['last'])}.",
                     "spread": ({"label": f"Spread {B.label(t, big, placed)}…", "kind": B.kind_of(big), "path": B.path_of(big)}
                                if big else None),
                     "till": ({"label": f"Let it finish by {P.fmt_day(till)}", "due": till} if till > hv["last"] else None)}
    return asks, counts, look, heavy


def _taper(doc):
    n = int((doc.get("phases") or {}).get("taper") or 0)
    _ev, end = V.ends_with(doc)
    if not n or not end:
        return None
    return E._later(end, -n), E._later(end, -1)


def strips(w):
    """A follower's (or an author studying it here) today and behind, as plan_tab._strips."""
    doc, today = w.doc, w.ops.today()
    author = w.author()
    out = {"now": None, "behind": None}
    u, now = V.today_date(doc, today)
    studies = not author or w.own_steps()
    if u is not None and studies:
        name = str(u.get("name") or "?")
        if now and w.idx is not None:
            c = M.counts(w.idx, w.idx.match(u, w.swap, doc))
            out["now"] = {"head": "Today", "words": f"{name}, {c['new']:,} new of {c['cards']:,}", "uid": u["id"], "study": True}
        elif now:
            out["now"] = {"head": "Today", "words": name, "uid": u["id"], "study": True}
        else:
            out["now"] = {"head": "Next", "words": f"{P.fmt_day(u['opens'])}, {name}", "uid": u["id"], "study": False}
    behind = []
    if not author and w.idx is not None:
        for x in sorted(P.units(doc), key=lambda x: str(x.get("opens"))):
            if str(x.get("due") or x.get("opens")) < today:
                c = M.counts(w.idx, w.idx.match(x, w.swap, doc))
                if c["new"]:
                    behind.append((x, c["new"]))
    if behind:
        left = sum(n for _x, n in behind)
        names = ", ".join(f"{M.day_words(x['opens'])} {x.get('name') or '?'}" for x, _n in behind[:2])
        more = f", and {len(behind) - 2:,} more" if len(behind) > 2 else ""
        out["behind"] = {"words": f"{names}{more}: {_pl(left, 'card')} not seen yet", "button": f"Study the {left:,}",
                         "uids": [x["id"] for x, _n in behind]}
    return out


def cover(w):
    """What it covers: the plan's cards here, seen, open and not seen, still shut; and
    (an author's) the ticked cover not on a lesson yet."""
    if w.idx is None or w.doc is None:
        return None
    cids = set()
    for u in P.units(w.doc):
        cids |= w.idx.match(u, w.swap, w.doc)
    if not cids:
        return None
    c = M.counts(w.idx, cids)
    seen = c["cards"] - c["new"]
    open_new = max(0, c["open"] - seen)
    out = {"cards": c["cards"], "seen": seen, "open": open_new, "shut": max(0, c["cards"] - seen - open_new), "outside": 0}
    t = w.deck_tree()
    if w.author() and t is not None:
        cv = set(V.pace_of(w.doc).get("cover") or [])
        if cv:
            out["outside"] = B.cover_left(t, cv, B.placed_keys(w.doc, t))
    return out


def sending(w):
    """The changes waiting: how many, and the first three in words, each with the lesson it's on."""
    n = len(w.draft) if w.draft else 0
    if not (w.author() and n):
        return None
    items = []
    for c in w.draft.replay(w.ctx())[1][:3]:
        x = (c["entries"] or [{}])[0]
        what = x.get("what") or ""
        words = f"{what.partition(' · ')[2] or what} {str(x.get('verb') or 'changed').lower()}"
        go = next((k for k in c["touched"] if w.unit(k) is not None or w.event_of(k) is not None), None)
        items.append({"words": words, "key": ["date" if w.unit(go) is not None else "event", go] if go else None})
    return {"n": n, "items": items, "more": n - len(items)}


def _review_units(w, r):
    a, b = w.unit(r.get("from")), w.unit(r.get("to"))
    if a is None or b is None:
        return []
    lo, hi = sorted((str(a["opens"]), str(b["opens"])))
    return [u for u in sorted(P.units(w.doc), key=lambda x: str(x.get("opens") or "")) if lo <= str(u["opens"]) <= hi]


def review_label(w, r):
    a, b = w.unit(r.get("from")), w.unit(r.get("to"))
    names = (a or {}).get("name") or "?"
    if b is not None and b is not a:
        names += f" – {b.get('name') or '?'}"
    return f"{M.day_words(r.get('day'))} · Review · {names}"


def _date_item(w, u, fresh, counts, look, author, today):
    n = counts.get(u["id"])
    item = {"kind": "date", "key": ["date", u["id"]], "day": u["opens"], "dayw": M.day_words(u["opens"]),
            "name": str(u.get("name") or "?"), "notSent": bool(author and u["id"] in fresh),
            "past": str(u.get("due") or u["opens"]) < today}
    if u.get("due") and u["due"] != u["opens"]:
        item["span"] = f"{M.day_words(u['opens'])} – {M.day_words(u['due'])}"
    if author:
        item["right"], item["tone"] = (f"{n:,}" if n is not None else ""), "n"
    else:
        due = str(u.get("due") or u.get("opens"))
        if str(u["opens"]) > today:
            item["right"], item["tone"] = f"opens {M.day_words(u['opens'])}", "n"
        elif w.idx is not None:
            c = M.counts(w.idx, w.idx.match(u, w.swap, w.doc))
            item["right"] = "all seen" if not c["new"] else f"{c['new']:,} left" + ("" if due >= today else ", behind")
            item["tone"] = "n" if due >= today or not c["new"] else "warn"
            item["state"] = "done" if not c["new"] else ("late" if due < today else "now" if str(u["opens"]) <= today else "ahead")
        else:
            item["right"], item["tone"] = "", "n"
    if "state" not in item:
        item["state"] = ("now" if str(u["opens"]) <= today <= str(u.get("due") or u["opens"])
                         else "past" if str(u.get("due") or u["opens"]) < today else "ahead")
    rows = w.rows(u)
    bits = [chip_name(r) + (f" ({len(r['cids']):,})" if w.idx is not None else "") for r in rows[:6]]
    if len(rows) > 6:
        bits.append(f"and {len(rows) - 6:,} more")
    if w.idx is None:
        bits += [M.label(t) for t in (list(u.get("tags") or []) + list(u.get("decks") or []))[:6]]
    if bits:
        item["under"], item["underTone"] = ", ".join(bits), "muted"
    elif author and u["id"] in look:
        item["under"], item["underTone"] = "No cards yet", "warn"
    item["hay"] = " ".join([item["name"]] + [chip_name(r) for r in rows]
                           + [str(t) for t in (u.get("tags") or []) + (u.get("decks") or [])]).lower()
    return item


def _event_item(w, e, author):
    prep = V.prep(w.doc, e)
    if prep:
        a, b = min(str(u["opens"]) for u in prep), max(str(u.get("due") or u["opens"]) for u in prep)
        words = f"tests {M.day_words(a)} – {M.day_words(b)}" if a != b else f"tests {M.day_words(a)}"
    else:
        words = "tests everything" if e is V.last_event(w.doc) else "tests no set yet"
    item = {"kind": "event", "key": ["event", e["id"]], "day": e.get("day"), "dayw": M.day_words(e.get("day")),
            "name": str(e.get("name") or "?"), "right": words, "tone": "n", "hay": str(e.get("name") or "").lower()}
    if prep and not author and w.idx is not None:
        cids = set()
        for u in prep:
            cids |= w.idx.match(u, w.swap, w.doc)
        c = M.counts(w.idx, cids)
        item["under"], item["underTone"] = f"{c['cards']:,} cards, {c['cards'] - c['new']:,} seen", "muted"
    return item


def plan_tab(w):
    """Everything the Plan tab draws, as plan_tab's _strips and _draw_list."""
    doc, today, author = w.doc, w.ops.today(), w.author()
    asks, counts, look, heavy = work_out(w)
    fresh = w.draft.touched(w.ctx()) if w.draft else set()
    taper = _taper(doc)
    weeks = []
    for wk in M.weeks(doc, today):
        items = [_date_item(w, u, fresh, counts, look, author, today) for u in wk["dates"]]
        items += [_event_item(w, e, author) for e in wk["events"]]
        end = E._later(wk["start"], 6)
        for r in doc.get("reviews") or []:
            if isinstance(r, dict) and wk["start"] <= str(r.get("day") or "") <= end:
                us = _review_units(w, r)
                span = (f"{M.day_words(us[0]['opens'])} – {M.day_words(us[-1]['opens'])}" if len(us) > 1
                        else M.day_words(us[0]["opens"]) if us else "?")
                items.append({"kind": "review", "key": ["review", r.get("day")], "day": r.get("day"),
                              "dayw": M.day_words(r.get("day")), "name": f"Review: {span}", "hay": "review"})
        if taper and taper[0] <= end and taper[1] >= wk["start"]:
            d = max(taper[0], wk["start"])
            items.append({"kind": "taper", "key": None, "day": d, "dayw": M.day_words(d),
                          "name": f"No new cards: {M.day_words(taper[0])} – {M.day_words(taper[1])}"})
        order = {"date": 0, "event": 1, "review": 2, "taper": 3}
        items.sort(key=lambda x: (str(x["day"]), order[x["kind"]]))
        words, warn = V.week_words(asks.get(wk["start"]))
        past = end < today
        evs = ", ".join(e.get("name") or "?" for e in wk["events"])
        weeks.append({"start": wk["start"], "label": wk["label"] + (", this week" if wk["now"] else ""), "now": wk["now"],
                      "past": past, "words": words, "warn": warn,
                      "folded": f"{_pl(len(wk['dates']), 'set')}" + (f", {evs}" if evs else ""),
                      "look": any(x["kind"] == "date" and x["key"][1] in look for x in items),
                      "heavy": heavy if heavy and heavy["week"] == wk["start"] and author else None,
                      "items": items})
    # Month and Week: every lesson's days (a spread one on each), each day's new cards, the pace
    pace = V.pace_of(doc)
    t = w.deck_tree()
    per = V.work(doc, t, pace) if t is not None else {}
    cap = V.cap_of(doc, t, pace) if t is not None else 0
    cal = []
    for u in sorted(P.units(doc), key=lambda u: (str(u.get("opens")), str(u.get("name") or ""))):
        cal.append({"kind": "date", "key": ["date", u["id"]], "day": u["opens"], "last": u.get("due") or u["opens"],
                    "name": str(u.get("name") or "?")})
    for e in doc.get("events") or []:
        if isinstance(e, dict):
            cal.append({"kind": "event", "key": ["event", e.get("id")], "day": e.get("day"), "last": e.get("day"),
                        "name": str(e.get("name") or "?")})
    out = {"weeks": weeks, "today": today, "todayw": M.day_words(today), "look": sorted(look), "lookN": len(look),
           "cal": cal, "load": {d: n for d, n in per.items() if n}, "cap": cap or 0,
           "days": list(pace.get("days") or [1] * 7), "taper": list(taper) if taper else None,
           "sending": sending(w), "cover": cover(w), "hasDeck": w.deck_tree() is not None and author,
           "empty": ("No sets yet. Tick what the plan covers in the deck, or Add › A set." if author
                     else "No sets on this plan yet.") if not P.units(doc) and not doc.get("events") else ""}
    out.update(strips(w))
    if author:
        out["shape"] = [list(x) for x in V.shape_line(doc, t, pace, asks)]
    return out


# ---- the picked one, beside the plan ----

def _every_on(doc, x, day):
    from .. import due
    try:
        return bool(due.every_on({"first": B.plan_start(doc, ""), "last": B.last_day(doc)}, x, str(day)))
    except Exception:
        return False


def own_tag(doc, path):
    return str(path).lower().startswith(P.tag_base(doc).lower() + "::")


def extras(w, key):
    """(tag, without now, its extras' tags, its cards without them), as plan_tab.extras."""
    t = w.deck_tree()
    if not key or t is None or w.swap:
        return None
    if key[0] == "tag":
        path, without = key[1], False
    elif key[0] == "search":
        path, without = B.extras_of(t, key[1]), True
        if not path:
            return None
    else:
        return None
    kids = [B.path_of(k) for k in t.extra_kids(f"tag:{path}")]
    if not kids:
        return None
    main = max(0, t.n(f"tag:{path}") - sum(t.n(f"tag:{k}") for k in kids))
    return path, without, kids, main


def _also(w, u, key, cids):
    """Leave out cards also tagged's choices for one source, worked out once
    a plan version (a big deck's tags are read card by card)."""
    cache = getattr(w, "_also_cache", None)
    if cache is None or cache[0] != w._ver:
        cache = w._also_cache = (w._ver, {})
    k = (u["id"], tuple(str(x) for x in key))
    if k not in cache[1]:
        skip = [key[1]] if key[0] in ("tag", "cut") else []
        cache[1][k] = M.also_tagged(w.idx, cids, skip=skip, most=12)
    return cache[1][k]


def _move_to(doc, u, most=10):
    """[(label, uid)]: the lessons nearest this one by day, for Move to."""
    us = sorted((x for x in P.units(doc) if x.get("id") != u["id"]), key=lambda x: (str(x.get("opens")), str(x.get("name"))))
    if not us:
        return []
    at = sum(1 for x in us if str(x.get("opens")) < str(u.get("opens")))
    lo = max(0, min(at - most // 2, len(us) - most))
    return [(f"{x.get('name') or '?'} · {P.fmt_day(x.get('opens'))}", x["id"]) for x in us[lo:lo + most]]


def date_panel(w, u):
    doc, author, today = w.doc, w.author(), w.ops.today()
    out = {"kind": "date", "uid": u["id"], "name": str(u.get("name") or ""), "label": M.date_label(u),
           "opens": u["opens"], "due": u.get("due") or "", "even": bool(u.get("even")), "for": u.get("for") or "",
           "author": author}
    if author:
        evs = sorted((e for e in doc.get("events") or [] if isinstance(e, dict)), key=lambda e: str(e.get("day") or ""))
        out["events"] = [{"id": e.get("id"), "label": f"{e.get('name') or '?'} · {P.fmt_day(e.get('day'))}"
                          + (" (after it)" if str(e.get("day")) < str(u["opens"]) else "")} for e in evs]
    else:
        when = [f"Opens {P.fmt_day(u['opens'])}" if str(u["opens"]) > today else f"Opened {P.fmt_day(u['opens'])}"]
        if u.get("due"):
            when.append(f"finish by {P.fmt_day(u['due'])}")
        ev = P.for_words(doc, u) if u.get("for") else ""
        if ev:
            when.append(ev)
        out["meta"] = " · ".join(when)
    rows = w.rows(u)
    fresh = w.draft.touched(w.ctx()) if w.draft else set()
    srcs = []
    for i, r in enumerate(rows):
        key = list(r["key"])
        s = {"i": i, "name": chip_name(r), "n": len(r["cids"]) if w.idx is not None else None, "raw": str(r.get("raw") or ""),
             "key": key}
        if author:
            menu = []
            if key[0] in ("tag", "deck") and w.idx is not None:
                menu.append({"label": "Spread it…", "cmd": "spread", "args": {"key": key}})
            if key[0] in ("tag", "cut") and P.plan_tags(doc) and not own_tag(doc, key[1]):
                now = key[2] if key[0] == "cut" else None
                menu.append({"label": "Keep only cards also tagged", "sub": [
                    {"label": lb, "on": pid == now, "cmd": "set_cut", "args": {"tag": key[1], "ptag": pid}}
                    for lb, pid in [("All of it", None)] + [(t.get("name") or "?", t.get("id")) for t in P.plan_tags(doc)]]})
            ex = extras(w, key)
            if ex:
                path, without, kids, main_n = ex
                n_ex = max(0, (len(r["cids"]) - main_n)) if not without else 0
                label = (f"Leave out its extras ({n_ex:,} cards)" if not without and n_ex else
                         "Leave out its extras" if not without else "Put its extras back")
                menu.append({"label": label, "cmd": "op", "args": {"op": {
                    "op": "set_extras", "date": u["id"], "path": path, "without": not without, "kids": kids, "main_n": main_n}}})
            if key[0] in ("tag", "cut", "search") and w.idx is not None:  # a subdeck's are read in each follower's deck
                also = _also(w, u, key, r["cids"])
                if also:
                    menu.append({"label": "Leave out cards also tagged", "sub": [
                        {"label": f"{M.label(t)} ({n:,})", "cmd": "op", "args": {"op": {
                            "op": "leave_out", "date": u["id"], "key": key, "tag": t, "n": max(0, len(r["cids"]) - n)}}}
                        for t, n in also]})
            moves = _move_to(doc, u)
            menu.append({"label": "Move to", "sub": [
                {"label": lb, "cmd": "op", "args": {"op": {"op": "move_source", "date": u["id"], "key": key, "to": uid}}}
                for lb, uid in moves] + ([{"sep": True}] if moves else []) + [
                {"label": "Another day…", "cmd": "move_source_form", "args": {"i": i}}]})
            if key[0] in ("tag", "cut"):
                menu.append({"label": "A note for followers on it…", "cmd": "remark", "args": {"path": key[1]}})
            menu.append({"label": "Copy its search", "cmd": "copy_source", "args": {"i": i}})
            menu.append({"sep": True})
            menu.append({"label": "Take it off this set", "cmd": "op", "args": {"op": {
                "op": "take_cards", "date": u["id"], "key": key}}})
            s["menu"] = menu
        srcs.append(s)
    if w.idx is None:
        srcs += [{"i": -1, "name": M.label(t), "n": None, "raw": t, "key": None}
                 for t in list(u.get("tags") or []) + list(u.get("decks") or [])]
    out["sources"] = srcs
    cids = w.idx.match(u, w.swap, doc) if w.idx is not None else set()
    n = len(cids)
    out["n"] = n if w.idx is not None else None
    bits = ["changed, not sent"] if author and u["id"] in fresh else []
    if w.idx is not None and cids:
        c = M.counts(w.idx, cids)
        if author:
            bits.append(f"{c['new']:,} new")
            if c["leech"]:
                bits.append(f"{_pl(c['leech'], 'leech', 'leeches')} stay shut")
        else:
            left = c["shut"] - c["leech"]
            bits.append(f"{c['open']:,} open, {left:,} still shut" if left else f"all {c['open']:,} open")
        pace = M.pace_words(doc, u, c["new"]) if author else ""
        if pace:
            bits.append(pace)
    if w.idx is None:
        bits.append(f"its deck ({doc.get('deck') or '?'}) isn't in this Anki")
    out["said"] = ", ".join(bits)
    lines = [x for x in u.get("todo") or [] if isinstance(x, dict)]
    out["todo"] = [f"{B.TODO_LABEL.get(x.get('k'), 'Do')}: {x.get('t') or ''}" for x in lines]
    out["every"] = [f"{B.TODO_LABEL.get(x.get('k'), 'Do')}: {x.get('t') or ''} (every week)"
                    for x in B.every_clean(doc.get("every") or []) if _every_on(doc, x, u.get("opens"))]
    if author:
        after = sum(1 for x in P.units(doc) if str(x.get("opens")) > str(u["opens"]))
        more = [{"label": (f"Move this and the {_pl(after, 'set')} after it…" if after else "Move this set…"),
                 "cmd": "move_from"}, {"sep": True}]
        tags = P.plan_tags(doc)
        if tags and any(r["key"][0] == "tag" for r in rows):
            more.append({"label": "Keep only cards also tagged", "sub": [
                {"label": str(t.get("name") or "?"), "cmd": "keep_only", "args": {"ptag": t.get("id")}} for t in tags]})
        if u.get("due") and u["due"] > u["opens"]:
            more.append({"label": f"Spread its cards evenly to {P.fmt_day(u['due'])}", "on": bool(u.get("even")),
                         "cmd": "op", "args": {"op": {"op": "set_even", "date": u["id"], "on": not u.get("even")}}})
        else:
            more.append({"label": "Spread its cards evenly (give it a finish-by day first)", "off": True})
        more += [{"sep": True}, {"label": "Copy the set's search", "cmd": "copy_search"},
                 {"label": "Open its cards in my Anki now", "cmd": "open_now", "off": not cids or w.busy},
                 {"sep": True}, {"label": "Delete this set…", "cmd": "delete", "bad": True}]
        out["more"] = more
    return out


def event_panel(w, e):
    prep = V.prep(w.doc, e)
    items, cids = [], set()
    for u in prep:
        mine = w.idx.match(u, w.swap, w.doc) if w.idx is not None else set()
        cids |= mine
        items.append({"key": ["date", u["id"]], "label": M.date_label(u) + (f" · {len(mine):,}" if w.idx is not None else "")})
    if prep:
        c = M.counts(w.idx, cids) if w.idx is not None and cids else None
        said = f"Tests {_pl(len(prep), 'set')}" + (f" · {c['cards']:,} cards, {c['cards'] - c['new']:,} seen" if c else "")
    else:
        said = "No set leads up to it yet: pick it as a set's Leads up to."
    return {"kind": "event", "eid": e.get("id"), "name": str(e.get("name") or ""), "day": e.get("day"),
            "title": f"{P.fmt_day(e.get('day'))} · {e.get('name') or '?'}", "author": w.author(),
            "items": items, "said": said, "n": len(prep)}


def review_panel(w, r):
    us = _review_units(w, r)
    return {"kind": "review", "day": r.get("day"), "title": review_label(w, r), "author": w.author(),
            "said": f"That morning, followers get a Due Crew deck of what they've seen from these "
                    f"{_pl(len(us), 'set')}, most missed first."}


def panel(w, key):
    if not key or w.doc is None:
        return {"kind": "none", "words": "Pick a set on the left to see its cards here."}
    kind = key[0]
    if kind == "date":
        u = w.unit(key[1])
        return date_panel(w, u) if u is not None else panel(w, None)
    if kind == "event":
        e = w.event_of(key[1])
        return event_panel(w, e) if e is not None else panel(w, None)
    if kind == "review":
        r = w.review_of(key[1])
        return review_panel(w, r) if r is not None else panel(w, None)
    return panel(w, None)


# ---- the deck, beside the plan ----

class DeckState:
    """The deck panel's own: the lesson ticks add to (None: what the plan
    covers), what's ticked as cover, the view, Find, the rows opened."""

    def __init__(self):
        self.target = None
        self.cover = set()
        self.dirty = False
        self.view = "resource"
        self.find = ""
        self.opened = set()
        self.kinds = {}
        self.pid = None
        self._hay = (None, [], {}, {})

    def reset(self, pid, doc):
        if pid != self.pid:
            self.pid, self.dirty, self.target, self.find, self.opened = pid, False, None, "", set()
        if not self.dirty:
            self.cover = set(V.pace_of(doc or {}).get("cover") or [])


def _shown(t, st, key, view=None):
    view = view or st.view
    if view == "deck":
        return B.kind_of(key) == "deck"
    return B.kind_of(key) == "tag" and view in B.kinds_below(t, key, st.kinds)


def _where(w, st, key):
    doc, path = w.doc or {}, B.path_of(key)
    field = "tags" if B.kind_of(key) == "tag" else "decks"
    for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or "")):
        if any(str(x).lower() == path.lower() for x in u.get(field) or []):
            return ("on this set" if u["id"] == st.target else f"on {M.day_words(u['opens'])}"), u["id"]
    return "", None


def _hay_of(t, st):
    if st._hay[0] is not t:
        up = {k: p for p, ks in t.kids_of.items() for k in ks}
        rows, whole = [], {}
        for key in t.order:
            path = B.path_of(key)
            seg = path.split("::")[-1]
            whole[key] = (path + "\n" + B.tag_name(path)).lower()
            rows.append((key, (seg + "\n" + B.tag_word(seg)).lower(), whole[key]))
        st._hay = (t, rows, up, whole)
    return st._hay


def _finds(t, st, term, view=None, most=None):
    _t, rows, up, whole = _hay_of(t, st)
    out = []
    for key, own, path in rows:
        if (term in own or (term in path and term not in whole.get(up.get(key), ""))) \
                and _shown(t, st, key, view) and t.n(key):
            out.append(key)
            if most and len(out) >= most:
                break
    return out


def _node(w, st, t, key, name=None, kids=True):
    path = B.path_of(key)
    where, uid = _where(w, st, key)
    has = bool(kids and [k for k in t.kids(key) if _shown(t, st, k) and t.n(k)])
    return {"key": key, "name": name or B.tag_word(path.split("::")[-1]), "path": path, "where": where, "uid": uid,
            "n": t.n(key), "kids": has, "open": has and key in st.opened, "children": []}


def _fill_open(w, st, t, node):
    if node["open"]:
        for k in t.kids(node["key"]):
            if _shown(t, st, k) and t.n(k):
                c = _node(w, st, t, k)
                _fill_open(w, st, t, c)
                node["children"].append(c)


def _marks(w, st, t, nodes):
    doc = w.doc or {}
    placed = B.placed_keys(doc, t)
    u = w.unit(st.target) if st.target else None
    on_date = set(B.srcs(u)) if u else set()

    def mark(n):
        key = n["key"]
        if u is not None:
            on = key in on_date
            n["check"] = 1 if on else 0
            n["off"] = bool(not on and any(B.under(k, key) for k in on_date))
        else:
            on = B.ticked(st.cover, t, key, st.view, st.kinds)
            n["check"] = 1 if on else (2 if B.partly(st.cover, key) else 0)
            n["off"] = bool(B.covered(st.cover, key) and key not in st.cover)
        n["placed"] = bool(B.is_placed(key, placed) and key not in on_date)
        for c in n["children"]:
            mark(c)
    for n in nodes:
        mark(n)


def deck_panel(w, st):
    """The deck beside the plan, as deck_panel.DeckPanel draws it."""
    t, doc = w.deck_tree(), w.doc or {}
    if t is None:
        return {"none": "This plan's deck isn't in this Anki, so there's nothing to tick here."}
    st.kinds = {}
    have = set(B.kinds_below(t, "root:tag", st.kinds))
    views = [{"key": k, "label": lb} for k, lb in VIEWS[:2] if k in have]
    more = []
    for k, lb in VIEWS[2:]:
        if (k == "other" and "other" not in have) or (k == "deck" and not t.kids("root:deck")) \
                or (k == "plan" and not P.plan_tags(doc)):
            continue
        more.append({"key": k, "label": lb})
    if st.view in ("resource", "system") and st.view not in have:
        st.view = next((k for k, _l in VIEWS[:2] if k in have), "other" if "other" in have else "deck")
    if st.target and w.unit(st.target) is None:
        st.target = None
    u = w.unit(st.target) if st.target else None
    out = {"target": st.target, "targetLabel": M.date_label(u) if u else "", "view": st.view, "views": views,
           "more": more, "find": st.find, "notes": [], "nodes": [], "lines": []}
    if st.view == "plan":
        for x in P.plan_tags(doc):
            n = len(w.idx.plan_tag_cards(doc, x, w.swap)) if w.idx is not None else 0
            key = f"tag:{P.tag_path(doc, x)}"
            where, uid = _where(w, st, key)
            out["nodes"].append({"key": key, "name": str(x.get("name") or "?"), "path": P.tag_path(doc, x), "where": where,
                                 "uid": uid, "n": n, "kids": False, "open": False, "children": [], "ptag": x.get("id"),
                                 "check": 1 if where == "on this set" else 0, "off": not st.target})
    else:
        term = st.find.strip().lower()
        if term:
            found = _finds(t, st, term, most=FOUND_MAX + 1)
            many = len(found) > FOUND_MAX
            found = found[:FOUND_MAX]
            if not found:
                others = [(v, lb, len(_finds(t, st, term, v, most=FOUND_MAX))) for v, lb in VIEWS[:4] if v != st.view]
                others = [x for x in others if x[2]]
                out["lines"].append({"words": f"Nothing here has “{st.find.strip()}”." if others
                                     else f"Nothing in this deck has “{st.find.strip()}”."})
                for v, lb, n in others:
                    out["lines"].append({"words": f"{lb} has {n:,}{'+' if n >= FOUND_MAX else ''}", "view": v})
            else:
                _t, _rows, up, _whole = _hay_of(t, st)
                hit, show = set(found), set(found)
                for k in found:
                    p = up.get(k)
                    while p and p in t.order and p not in show:
                        show.add(p)
                        p = up.get(p)
                below = {}
                for k in sorted(show, key=t.order.get):
                    below.setdefault(up.get(k), []).append(k)

                def place(k, above):
                    while k not in hit and len(below.get(k) or []) == 1:
                        k = below[k][0]
                    path = B.path_of(k)
                    parts = [B.tag_word(x) for x in (path[len(B.path_of(above)) + 2:] if above else path).split("::")]
                    n = _node(w, st, t, k, name=" › ".join(parts), kids=k in hit and not below.get(k))
                    _fill_open(w, st, t, n)
                    for c in below.get(k) or []:
                        n["children"].append(place(c, k))
                    if n["children"] and not n["open"]:
                        n["open"] = True
                        n["kids"] = True
                    return n
                out["nodes"] = [place(k, None) for k in below.get("root:deck" if st.view == "deck" else "root:tag") or []]
                if many:
                    out["lines"].append({"words": f"The first {FOUND_MAX:,}: type more of a name to narrow them."})
        else:
            root = "root:deck" if st.view == "deck" else "root:tag"
            nodes = [_node(w, st, t, k) for k in t.kids(root) if _shown(t, st, k) and t.n(k)]
            if len(nodes) == 1 and not st.opened:  # one way down: opened to the first choice
                n = nodes[0]
                while n is not None and n["kids"]:
                    st.opened.add(n["key"])
                    n["open"] = True
                    _fill_open(w, st, t, n)
                    n = n["children"][0] if len(n["children"]) == 1 else None
            else:
                for n in nodes:
                    _fill_open(w, st, t, n)
            out["nodes"] = nodes
        _marks(w, st, t, out["nodes"])
    out["fill"] = _fill(w, st) if u is None and w.author() else None
    out["cardNotes"] = [{"id": r["id"], "label": f"{r['card'][0]} · card {int(r['card'][1]) + 1}: {str(r.get('text') or '')[:40]}"}
                        for r in doc.get("remarks") or [] if isinstance(r, dict) and r.get("card") and r.get("id")] \
        if u is None and w.author() else []
    return out


def _fill(w, st):
    """What's ticked, laid out: the words and the buttons, as deck_panel._said."""
    t, doc = w.deck_tree(), w.doc or {}
    out = {"words": "", "bad": False, "go": None, "alt": None, "week": False, "keep": st.dirty}
    if not st.cover:
        out["words"] = "Tick what the plan covers; then lay it out on its study days."
        return out
    pace = V.pace_of(doc)
    placed = B.placed_keys(doc, t)
    left = B.cover_left(t, st.cover, placed)
    if not left:
        out["words"] = "Everything ticked is on a set."
        return out
    daily = int(pace.get("daily") or 20)
    start = B.plan_start(doc, B.next_monday(w.ops.today()))
    ev, end = V.ends_with(doc)
    who = (ev or {}).get("name") or "the end"
    fin = B.finish_by(doc, t, pace, st.cover, start, daily)
    out["upto"] = [{"label": f"Before {e.get('name') or '?'} · {P.fmt_day(e.get('day'))}", "eid": e.get("id")}
                   for e in sorted((e for e in doc.get("events") or [] if isinstance(e, dict) and str(e.get("day") or "") > start),
                                   key=lambda e: str(e.get("day")))]
    out["week"] = True
    out["head"] = f"{left:,} ticked, not on a set."
    if end and fin and fin >= end:
        fit_end = E._later(end, -1) if ev else end
        d1 = B.end_daily(dict(doc, end=fit_end), t, pace, st.cover, start) or daily
        late = (E._day(fin) - E._day(end)).days
        out["bad"] = True
        out["words"] = f"At {daily:,} a day they'd end {P.fmt_day(fin)}, {_pl(late, 'day')} after {who}."
        out["go"] = {"label": f"Fit them before {who}: {d1:,} a day", "how": ["end", False, [fit_end, (ev or {}).get("id")]]}
        out["alt"] = {"label": f"Lay them out at {daily:,} anyway", "how": ["daily", False, None]}
    elif end and fin:
        out["words"] = f"At {daily:,} a day they end {P.fmt_day(fin)}, before {who}."
        out["go"] = {"label": f"Lay them out at {daily:,} a day", "how": ["daily", False, None]}
    else:
        out["words"] = f"At {daily:,} a day they end {P.fmt_day(fin)}." if fin else ""
        out["go"] = {"label": f"Lay them out at {daily:,} a day", "how": ["daily", False, None]}
    return out
