"""Insights and Settings in the HTML plan window (webface.py draws them
with page/tabs.js): the Qt tabs' work, as plain data for the page, and
what each of their clicks does (c_<name>, reached as the page's tabcmd).

Insights is insights_tab.py's (insights.py works it out): the workload by
week, how much of the deck and of each part, what's in it; the same for a
plan I follow, on my dates, with what I've seen. Never sent; worked out
when it's looked at, once a change. Settings is an author's
(settings_tab.py with shape.py's dates and pace, history_tab.py's Posts
and History) or a follower's (mine_tab.py, my follow; and Today's lesson,
plan_flow's when it has it).

Qt-free: a dialog that isn't HTML (Every week's lines, Your AI app)
opens lazily from the one click that needs it, parented to the window.
Requests only on a click, by the routes the Qt tabs use (remote.py,
flow.Ops). A plan's unit is a "set" here, as on the window's Plan tab
and in the Qt tabs. Names are the server's, the authors' and the deck's:
the page sets them as text."""

import datetime

from .. import plans as P
from . import build as B
from . import edits as E
from . import insights as INS
from . import model as M
from . import ops as O
from . import remote
from . import view as V

CATCHUP = ((0, "None"), (3, "Every 3rd week"), (4, "Every 4th week"))
MODES = (("daily", "Up to"), ("end", "Fit to the end"), ("placed", "I place each set"))
EARLY = ((0, "Off"), (1, "1 day"), (2, "2 days"), (3, "3 days"), (5, "5 days"), (7, "7 days"))
FOLLOW_KEYS = ("shift", "skipped", "moved", "paused", "own")
SOON_MS = 1800  # a follow's step, read again once its request is likely back (mine_tab._again)


def _on(name, **args):
    """A sheet's yes: this module's c_<name>, with args (and the sheet's fields)."""
    return {"cmd": "tabcmd", "args": dict(args, name=name)}


def _ask(w, name, title, words, yes, danger=False, **args):
    """Sure? A sheet whose yes is c_<name>(sure=True, **args)."""
    w.ask(title, words, yes, "tabcmd", dict(args, name=name), danger=danger)


def _st(w):
    """This window's own state for the two tabs, its plan's only."""
    st = getattr(w, "_tabs_st", None)
    if st is None:
        st = {"pid": None, "shape": {}, "by": {}, "crew": None, "posts": [], "ins": (None, None),
              "follow": (None, None), "tick": 0, "busy": set()}
        w._tabs_st = st
    pid = (w.plan or {}).get("id")
    if st["pid"] != pid:
        st.update(pid=pid, shape={}, crew=None, posts=[], follow=(None, None))
    return st


def _pid(w):
    return (w.plan or {}).get("id")


def _doc(w):
    """The plan as it shows here. An author's with every field the server
    keeps: the window's doc is read cleaned (its pace the days alone) till a
    change waits under it, and its dates and pace are the plan's own. A
    follower's: mine."""
    raw = (w.raw or {}).get("doc")
    if w.author() and not (w.draft and len(w.draft)) and isinstance(raw, dict):
        return raw
    return w.doc


def _pct(v, whole):
    return max(0.0, min(100.0, round(100.0 * float(v or 0) / float(whole), 2))) if whole else 0.0


def _pl(n, word, many=None):
    return f"{n:,} {word if n == 1 else (many or word + 's')}"


def _soon(w, fn):
    after = getattr(w, "after", None)
    if callable(after):
        after(SOON_MS, fn)
        return
    try:
        from aqt.qt import QTimer
        QTimer.singleShot(SOON_MS, fn)
    except ImportError:
        fn()


# ---- Insights ----

def insights(w):
    """Everything Insights draws: {none} (nothing to count, and why) or
    {work, deck, has}. Worked out once a change of the plan (or a way picked)."""
    if w.doc is None:
        return {"none": ""}
    st = _st(w)
    key = (getattr(w, "_ver", 0), _pid(w), w.author(), _way(w, w.idx.did) if w.idx is not None else None)
    if st["ins"][0] != key:
        st["ins"] = (key, _insights(w))
    return st["ins"][1]


def _insights(w):
    doc = _doc(w)
    if w.idx is None:
        return {"none": "This plan's deck isn't in this Anki, so there's nothing here to count."}
    per, cards = INS.held(w.idx, doc, w.swap)
    if not per:
        return {"none": "Nothing to count yet: the plan has no sets."}
    return {"work": _workload(w, doc), "deck": _deck(w, cards), "has": _contents(w, doc, per, cards)}


def _workload(w, doc):
    """Its weeks, a row each: new cards a study day against the pace (a line
    down its column) and reviews a day, each on its own scale, never added;
    the week's quiz or exam beside it."""
    t = w.deck_tree()
    pace = V.pace_of(doc)
    asks = V.week_asks(doc, t, pace) if t is not None else {}
    rows = INS.workload(doc, asks, w.ops.today())
    if not rows:
        return {"empty": "No new cards on its sets yet."}
    words, over = INS.workload_words(doc, rows, V.work(doc, t, pace))
    cap = max(x["cap"] for x in rows)
    new_top = max([x["new"] for x in rows] + [cap]) or 1
    rv_top = max(x["reviews"] for x in rows) or 1
    return {"words": words, "over": over,
            "newHead": "New a study day" + (f" · the line, your pace: {cap:,}" if cap else ""),
            "rvHead": "Reviews a day", "line": _pct(cap, new_top) if cap else None,
            "rows": [{"week": f"Week {x['n']}" + (", this week" if x["now"] else ""), "now": x["now"], "past": x["past"],
                      "span": x["span"], "events": ", ".join(x["events"]), "tip": INS.week_words(x),
                      "new": _pct(x["new"], new_top), "has": bool(x["new"]), "over": x["over"], "newWords": INS.new_words(x),
                      "rv": _pct(x["reviews"], rv_top), "hasRv": x["reviews"] > 0, "rvWords": INS.reviews_words(x)}
                     for x in rows]}


def _way(w, did):
    """The deck's way: the topic map's pick for it on this computer (ops.map_by), else this window's, else the best."""
    get = getattr(w.ops, "map_by", None)
    got = get(did) if callable(get) else None
    return got or _st(w)["by"].get(did)


def _deck(w, cards):
    """The plan's cards of the deck's (a follower's: what I've seen, then
    what's to go); then each part's, on one scale, the part it's mostly in
    split again."""
    idx = w.idx
    total = len(idx.home)
    out = {"words": INS.deck_words(idx.name.split("::")[-1], len(cards), total),
           "tip": INS.deck_words("", len(cards), total)}
    if w.author():
        out["bar"] = [{"v": _pct(len(cards), total), "k": "fill", "has": bool(cards)}]
    else:
        c = M.counts(idx, cards)
        seen = c["cards"] - c["new"]
        out["bar"] = [{"v": _pct(seen, total), "k": "fill", "has": seen > 0},
                      {"v": _pct(c["new"], total), "k": "soft", "has": c["new"] > 0}]
        out["key"] = f"You've seen {seen:,} of them; {c['new']:,} to go."
    tiles, ways = INS.deck_split(idx, _way(w, idx.did))
    rows, none, inside = INS.topics(tiles, cards)
    if not rows:
        return out
    on = next((x for x in ways if x["on"]), None)
    out["ways"] = [{"key": x["key"], "name": x["name"], "on": bool(x["on"])} for x in ways] if len(ways) > 1 else []
    out["by"] = (f"By {on['name']}" if on else "By") if len(ways) > 1 else (f"By {on['name']}" if on else "")
    out["parts"] = _parts(rows, none)
    if inside:
        name, krows, knone = inside
        out["inside"] = dict(_parts(krows, knone), head=f"Inside {name}")
    return out


def _parts(rows, none):
    """A part a row, the plan's share of it filled, every bar on one scale."""
    shown = rows[:12]
    scale = max((r["total"] for r in shown), default=1) or 1
    return {"rows": [{"name": r["name"], "fill": _pct(r["held"], scale), "track": _pct(r["total"], scale),
                      "words": f"{r['held']:,} of {r['total']:,} · {INS.pct(r['held'], r['total'])}"} for r in shown],
            "more": (f"and {len(rows) - len(shown):,} smaller ones with some of their cards in it"
                     if len(rows) > len(shown) else ""),
            "none": INS.none_words(none)}


def _exam_words(x):
    """insights.exam_words, as the page says it: "55 cards from 3 sets"."""
    if x["all"]:
        return f"everything: {x['cards']:,} cards"
    if not x["dates"]:
        return "no set for it yet"
    return f"{x['cards']:,} cards from {_pl(x['dates'], 'set')}"


def _contents(w, doc, per, cards):
    """What each quiz or exam tests, the biggest lessons (a click: that one
    on the Plan tab), cards on two lessons, leeches."""
    out = {"exams": [{"key": ["event", x["id"]], "day": x["day"], "dayw": M.day_words(x["day"]), "name": x["name"],
                      "words": _exam_words(x)} for x in INS.exams(doc, per, cards)],
           "big": [{"key": ["date", u["id"]], "day": str(u.get("opens")), "dayw": M.day_words(u.get("opens")),
                    "name": str(u.get("name") or "?"), "words": f"{n:,} cards"} for u, n in INS.biggest(doc, per)],
           "lines": []}
    two = INS.on_two(per)
    if two:
        out["lines"].append(f"{two:,} card{'s are' if two != 1 else ' is'} on two sets or more; each opens with the first.")
    leech = M.counts(w.idx, cards)["leech"]
    if leech:
        out["lines"].append(f"{leech:,} lee{'ches' if leech != 1 else 'ch'} on its sets stay{'' if leech != 1 else 's'} "
                            "shut: a plan never opens one.")
    return out


def c_map_by(w, key):
    """Another way to split the deck, for the board's topic map too (one pick a deck)."""
    if w.idx is None or not isinstance(key, str) or not key:
        return
    put = getattr(w.ops, "set_map_by", None)
    if callable(put):
        put(w.idx.did, key)
    _st(w)["by"][w.idx.did] = key
    _st(w)["ins"] = (None, None)
    w.push()


def c_go(w, key):
    """A quiz or a lesson picked in Insights: that one, on the Plan tab."""
    if not isinstance(key, list) or len(key) < 2 or key[0] not in ("date", "event"):
        return
    if (w.unit(key[1]) if key[0] == "date" else w.event_of(key[1])) is None:
        return
    w.tab, w.picked, w.side = "plan", (key[0], key[1]), "panel"
    w.push()


# ---- Settings ----

def settings(w):
    """Settings, an author's (the plan's) or a follower's (my follow)."""
    if w.doc is None or not w.plan:
        return {"none": ""}
    return _author(w) if w.author() else _follower(w)


def _raw(w):
    return w.raw or {}


def _owner(w):
    return w.author() and (w.plan or {}).get("role") == "owner"


def _eds(w):
    return [e for e in _raw(w).get("editors") or [] if isinstance(e, dict) and e.get("uid")]


def _ai_on():
    """Your AI app's switch on this computer, in a word (nothing when it can't be read)."""
    try:
        from . import mcp_host
        return "On" if mcp_host.settings()["on"] else "Off"
    except Exception:  # noqa: BLE001 (an install without it, or a config it can't read)
        return ""


def _squads(w):
    """The squads I'm in, [{id, name}], and the one the plan is offered to (a squad of mine I've left since)."""
    raw = _raw(w)
    squads = [{"id": q.get("id"), "name": str(q.get("name") or "?")} for q in (w.ops.my_squads() or [])
              if isinstance(q, dict) and q.get("id")]
    if raw.get("squad") and not any(q["id"] == raw["squad"] for q in squads):
        squads.append({"id": raw["squad"], "name": "A squad of mine"})
    return squads


def _author(w):
    raw = _raw(w)
    doc = raw.get("doc") or {}
    owner, busy = _owner(w), bool(w.busy)
    squads = _squads(w)
    offered = raw.get("handover")
    coas = []
    for e in _eds(w):
        pending = bool(e.get("pending"))
        coas.append({"uid": str(e["uid"]), "name": str(e.get("name") or "?"),
                     "what": "invited, waiting for a yes" if pending else "offered the plan" if e["uid"] == offered else "co-author",
                     "hand": owner and not pending and not offered,
                     "off": ("Take back the invite" if pending else "Take them off") if owner else ""})
    listed = raw.get("listed")
    why = ("Only a plan anyone with the code can follow goes in the library." if raw.get("audience") != "code"
           else "Put some sets on it first." if not P.units(doc) else "")
    lib_said = (f"Taken out of the library. {raw.get('listedNote') or ''} It stays yours, and its followers keep following. "
                "Send feedback if it's a mistake." if listed == -1
                else "Its owner lists it in the library." if not owner else why)
    code = str(raw.get("code") or "")
    n = w.followers()
    lines = B.every_clean(doc.get("every") or [])
    return {
        "role": "author", "pid": _pid(w), "owner": owner, "busy": busy,
        "name": str(raw.get("name") or ""), "line": str(raw.get("line") or ""), "url": str(doc.get("deckUrl") or ""),
        "urlTip": f"On its link page and poster, and in Anki for anyone with no deck called {doc.get('deck') or '?'}.",
        "shape": _shape_view(w),
        "every": "; ".join(f"{B.TODO_LABEL.get(x.get('k'), 'Do')}: {x.get('t') or ''}, {B.every_label(x['r'])}" for x in lines)
                 or "None",
        "code": code or "none yet", "hasCode": bool(code),
        "squads": squads, "squad": raw.get("squad") or None, "audience": "squad" if raw.get("audience") == "squad" else "code",
        "ownerOnly": "" if owner else ("Only people in a squad of its owner's can follow it. Its owner sets that."
                                       if raw.get("audience") == "squad" else "Anyone with the code can follow it. Its owner sets that."),
        "following": f"{n:,} following" if n else "Nobody follows it yet",
        "coauthors": coas, "canAsk": owner and len(coas) < 10, "offered": owner and bool(offered), "leave": not owner,
        "library": {"shown": owner and listed != -1, "on": listed == 1, "off": not (owner and not busy and (not why or listed == 1)),
                    "said": lib_said},
        "ai": _ai_on(), "canCopy": bool(E.first_day(doc)), "delete": owner,
    }


# -- the plan's dates and pace (shape.py) --

def _iso_ok(s):
    try:
        datetime.date.fromisoformat(str(s))
        return len(str(s)) == 10
    except ValueError:
        return False


def _events(doc):
    return sorted((e for e in doc.get("events") or [] if isinstance(e, dict) and e.get("day") and e.get("id")),
                  key=lambda e: str(e["day"]))


def _shape_base(w):
    """The plan's shape as it shows (with the changes waiting)."""
    doc = _doc(w)
    pace = V.pace_of(doc)
    start0 = B.plan_start(doc, B.next_monday(w.ops.today()))
    ev0, end0 = V.ends_with(doc)
    ph = doc.get("phases") or {}
    return {"start": start0, "end": f"event:{ev0['id']}" if ev0 is not None and ev0.get("id") else ("day" if end0 else "none"),
            "end_day": end0 or E._later(start0, 55), "days": [1 if x else 0 for x in (pace.get("days") or [1] * 7)],
            "mode": pace.get("mode") if pace.get("mode") in dict(MODES) else "daily", "daily": int(pace.get("daily") or 20),
            "taper": int(ph.get("taper") or 0), "catchup": int(ph.get("catchup") or 0)}


def _end_of(doc, v):
    kind = str(v.get("end") or "none")
    if kind.startswith("event:"):
        e = next((x for x in _events(doc) if str(x["id"]) == kind[6:]), None)
        return str(e["day"]) if e else None
    return v.get("end_day") if kind == "day" else None


def _shape_ops(w, base, v, touched):
    """The ops the rows make, only for what changed (shape.Shape.ops)."""
    doc = _doc(w)
    pace = V.pace_of(doc)
    out = []
    delta = (E._day(v["start"]) - E._day(base["start"])).days
    if delta and (P.units(doc) or doc.get("events") or doc.get("reviews") or doc.get("end")):
        out.append({"op": "shift_all", "days": delta})
    shifted = bool(out)
    end, kind = _end_of(doc, v), str(v.get("end") or "none")
    if end and shifted and not (kind == "day" and touched):
        end = E._later(end, delta)  # the exam (or the day it had) moves with the start
    end_now = E._later(doc["end"], delta) if shifted and doc.get("end") else doc.get("end")
    if (end or None) != (end_now or None):
        out.append({"op": "set_end", "end": end})
    days, mode, daily = list(v["days"]), v["mode"], int(v["daily"])
    if (mode, days, daily) != (pace.get("mode"), list(pace.get("days") or [1] * 7), int(pace.get("daily") or 20)):
        out.append({"op": "set_pace", "mode": mode, "days": days, "daily": daily, "cover": list(pace.get("cover") or [])})
    ph = doc.get("phases") or {}
    c, t = int(v["catchup"] or 0), int(v["taper"]) if end else 0
    if (c, t) != (int(ph.get("catchup") or 0), int(ph.get("taper") or 0)):
        out.append({"op": "set_phases", "catchup": c, "taper": t})
    return out


def _shape_now(w):
    """(the plan's, the rows' now, their ops or None, why not)."""
    st = _st(w)
    base = _shape_base(w)
    v = dict(base, **st["shape"])
    try:
        return base, v, _shape_ops(w, base, v, "end_day" in st["shape"]), ""
    except E.Refused as e:
        return base, v, None, str(e)


def _preview(w, ops):
    """What the change does, said before it goes in: [[style, words]]."""
    doc, ctx = _doc(w), w.ctx()
    try:
        after = doc
        for o in ops:
            o = O.check(after, o)
            after, _e, _t = O.apply(after, o, ctx)
    except E.Refused as e:
        return [["", str(e)]], True
    before_days = {u["id"]: u.get("opens") for u in P.units(doc)}
    moved = sum(1 for u in P.units(after) if before_days.get(u["id"]) not in (None, u.get("opens")))
    evs0 = {e.get("id"): e.get("day") for e in doc.get("events") or [] if isinstance(e, dict)}
    ev_moved = sum(1 for e in after.get("events") or [] if isinstance(e, dict) and evs0.get(e.get("id")) not in (None, e.get("day")))
    today = w.ops.today()
    now = {x["id"]: x.get("opens") for x in P.units(after)}
    opened = sum(1 for u in P.units(doc) if str(u.get("opens")) <= today and before_days.get(u["id"])
                 and u["id"] in now and now[u["id"]] != u.get("opens"))
    out = []
    if moved or ev_moved:
        bits = [_pl(moved, "set") if moved else "",
                f"{ev_moved:,} quiz{'zes' if ev_moved != 1 else ''} or exam{'s' if ev_moved != 1 else ''}" if ev_moved else ""]
        out += [["", "Saving moves "], ["b", " and ".join(b for b in bits if b)], ["", "."]]
        if opened:
            out.append(["", f" {opened:,} of them opened already: followers who have their cards keep them."])
    else:
        out.append(["", "No set moves."])
    ph = after.get("phases") or {}
    if int(ph.get("taper") or 0) and after.get("end"):
        n = int(ph["taper"])
        out.append(["", f" The last {n:,} day{'s' if n != 1 else ''} before {P.fmt_day(after['end'])} have no new cards."])
    return out, False


def _shape_view(w):
    base, v, ops, refused = _shape_now(w)
    doc = _doc(w)
    ends = [{"v": f"event:{e['id']}", "label": f"{e.get('name') or '?'} · {P.fmt_day(e['day'])}"} for e in _events(doc)]
    ends += [{"v": "day", "label": "A day…"}, {"v": "none", "label": "Nothing yet"}]
    catchups = [{"v": c, "label": label} for c, label in CATCHUP]
    if v["catchup"] not in dict(CATCHUP):
        catchups.append({"v": v["catchup"], "label": f"Every {v['catchup']}th week"})
    out = {"start": v["start"], "ends": ends, "end": v["end"] if any(x["v"] == v["end"] for x in ends) else "none",
           "endDay": v["end_day"], "days": v["days"], "modes": [{"v": k, "label": label} for k, label in MODES],
           "mode": v["mode"], "daily": v["daily"], "taper": v["taper"], "taperOff": not _end_of(doc, v),
           "catchups": catchups, "catchup": v["catchup"], "go": "Add to the changes" if w.waiting() else "Save", "preview": None}
    if refused:
        out["preview"] = {"parts": [["", refused]], "bad": True}
    elif ops:
        parts, bad = _preview(w, ops)
        out["preview"] = {"parts": parts, "bad": bad}
    return out


def c_shape(w, key, value=None):
    """A row of the shape changed: kept here, said under them till it goes in or is put back."""
    if not w.author() or w.doc is None:
        return
    st = _st(w)
    base = _shape_base(w)
    v = dict(base, **st["shape"])
    edits = st["shape"]
    try:
        if key == "start" and _iso_ok(value):
            edits["start"] = str(value)
        elif key == "end" and (value in ("day", "none") or (str(value).startswith("event:") and _end_of(_doc(w), {"end": value}))):
            edits["end"] = str(value)
        elif key == "end_day" and _iso_ok(value):
            edits["end_day"] = str(value)
        elif key == "day" and 0 <= int(value) <= 6:
            days = list(v["days"])
            days[int(value)] = 0 if days[int(value)] else 1
            if any(days):  # one study day at least
                edits["days"] = days
        elif key == "mode" and value in dict(MODES):
            edits["mode"] = value
        elif key == "daily":
            edits["daily"] = max(1, min(5000, int(value)))
        elif key == "taper":
            edits["taper"] = max(0, min(60, int(value)))
        elif key == "catchup" and 0 <= int(value) <= 52:
            edits["catchup"] = int(value)
    except (TypeError, ValueError):
        pass
    for k in [k for k in edits if k != "end_day" and edits[k] == base.get(k)]:
        del edits[k]
    w.push()


def c_shape_back(w):
    """Put it back: the rows as the plan has them."""
    _st(w)["shape"] = {}
    w.push()


def c_shape_save(w):
    """The rows' changes, in as one (with anyone following, waiting under the plan)."""
    st = _st(w)
    _base, _v, ops, refused = _shape_now(w)
    if refused:
        w.say(refused)
        return
    if not ops or w.busy:
        return

    def done(ok):
        if ok:
            st["shape"] = {}
            w.push()
    w.changes(ops, then=done)


def c_every(w):
    """Every week's lines (a Qt dialog for now, over the window)."""
    if not w.author() or w.busy:
        return
    from . import date_dialogs as DD
    dlg = DD.LinesDialog(w, "Every week", _doc(w).get("every") or [], every=True)
    if dlg.exec():
        w.change({"op": "set_every", "lines": dlg.lines()})


# -- name, line, the deck's link, who can follow --

def _took(w, pid, got, said, retry=None):
    """A settings request's answer for plan `pid`: the plan as it is now (in
    the window), or why not. Another plan picked since: not this one's."""
    if _pid(w) != pid or not w.author():
        return
    if not got:
        w.say("That didn't work: check your connection, then try again.")
        w.push()
        return
    outcome, what = got
    if outcome == "stale":
        w.took(what)
        if retry:
            retry()
        else:
            w.say("Someone changed this plan just now. It's up to date here: make the change again.")
        return
    if outcome != "saved":
        w.say(str(what))
        w.push()
        return
    w.took(what)
    w.say(said)


def _send(w, fields, summary, said):
    pid, version = w.plan["id"], _raw(w).get("version")

    def again():
        v = _raw(w).get("version")
        w.ops.ask(w, lambda cl: remote.save_meta(cl, pid, v, fields, summary), lambda got: _took(w, pid, got, said))
    w.ops.ask(w, lambda cl: remote.save_meta(cl, pid, version, fields, summary), lambda got: _took(w, pid, got, said, again))


def c_meta(w, name="", line=""):
    """Its name and one line, saved (one request)."""
    if not w.author() or w.busy:
        return
    name, line = " ".join(str(name or "").split())[:60], " ".join(str(line or "").split())[:120]
    raw = _raw(w)
    if name and (name, line) != (raw.get("name"), raw.get("line") or ""):
        _send(w, {"name": name, "line": line}, "renamed it", "Saved. Followers see the new name at their next refresh.")


def c_deck_url(w, url=""):
    """Where to get the deck: a change of the plan's (it waits with the others when anyone follows)."""
    if not w.author():
        return
    url = str(url or "").strip()[:300]
    if url != str((_raw(w).get("doc") or {}).get("deckUrl") or ""):
        w.change({"op": "set_deck_url", "url": url})


def c_who(w, squad=None, audience="code"):
    """Offer it to one of my squads, and who can follow (the owner's)."""
    if not _owner(w) or w.busy:
        return
    raw = _raw(w)
    q = next((x for x in _squads(w) if squad is not None and str(x["id"]) == str(squad)), None)
    squad, name = (q["id"], q["name"]) if q else (None, "")
    audience = "squad" if audience == "squad" and squad else "code"
    if (squad, audience) == (raw.get("squad") or None, raw.get("audience") or "code"):
        w.push()
        return
    _send(w, {"audience": audience, "squad": squad}, "who can follow",
          f"Only people in {name} can follow it now." if audience == "squad"
          else f"Offered to {name}. Anyone with the code can follow it." if squad
          else "Anyone with the code can follow it.")


def c_copy_link(w):
    code = str(_raw(w).get("code") or "")
    if code and w.author():
        w._copy(w.ops.site_url(f"/p/{code}"), "Copied: its link. Anyone who opens it can follow with the code, as Who can follow says.")


def c_open_page(w):
    code = str(_raw(w).get("code") or "")
    if code and w.author():
        w.ops.open_page(f"/p/{code}")


# -- Posts and History (history_tab.py's) --

def _who_said(w, x):
    me = w.ops.me()
    return "You" if me and x.get("uid") == me else str(x.get("name") or "?")


def _posts_sheet(w, rows, said="", text=""):
    n = w.followers()
    return dict({"kind": "posts", "title": f"Posts to the {n:,} following" if n else "Posts",
                 "words": said or ("" if rows else "Nothing posted yet. Followers see a post in Anki and on their home page."),
                 "fields": [{"name": "text", "value": text, "max": 200,
                             "hint": f"A line to the {n:,} following" if n else "A line to its followers (nobody follows it yet)"}],
                 "rows": [{"id": x.get("id"), "who": _who_said(w, x) + (" (co-author)" if x.get("coauthor") else ""),
                           "text": str(x.get("text") or "") + (" (sent with changes)" if x.get("withSave") else ""),
                           "ago": M.ago(x.get("at")), "remove": bool(x.get("remove"))} for x in rows],
                 "yes": "Post", "no": "Close"}, **_on("post"))


def c_posts(w, said=""):
    """Posts…: what followers were told (a send's line among it), newest first; a line to them."""
    if not w.author():
        return
    pid, st = w.plan["id"], _st(w)
    w.say("Loading…")

    def got(rows):
        if _pid(w) != pid:
            return
        if rows is None:
            w.say("Couldn't load the updates.")
            return
        st["posts"] = rows
        w.say("")
        w.sheet(_posts_sheet(w, rows, said))
    w.ops.ask(w, lambda cl: remote.posts(cl, pid), got)


def c_post(w, text="", sure=False):
    """A line to followers (five a day a plan)."""
    st = _st(w)
    text = " ".join(str(text or "").split())[:200]
    if not w.author() or not text or w.busy or "post" in st["busy"]:
        return  # (Enter again while it's on its way: one post)
    pid = w.plan["id"]
    st["busy"].add("post")
    w.say("Posting…")

    def done(got):
        st["busy"].discard("post")
        if _pid(w) != pid:
            return
        if not got or got[0] != "saved":
            why = "That didn't post. Try again." if not got else str(got[1])
            w.say(why)
            w.sheet(_posts_sheet(w, st["posts"], why, text))
            return
        c_posts(w, "Posted. Followers see it in Anki and on their home page.")
    w.ops.ask(w, lambda cl: remote.post(cl, pid, text), done)


def c_unpost(w, id=None, sure=False):  # noqa: A002 (the page's word)
    """A post taken back: its writer's, or the owner's."""
    st = _st(w)
    x = next((p for p in st["posts"] if p.get("id") == id and p.get("remove")), None)
    if not w.author() or x is None:
        return
    pid = w.plan["id"]

    def done(ok):
        if _pid(w) != pid:
            return
        if ok:
            c_posts(w)
        else:
            w.sheet(_posts_sheet(w, st["posts"], "That didn't work. Try again."))
    w.ops.ask(w, lambda cl: remote.unpost(cl, pid, x["id"]), done)


def c_history(w):
    """History (Undo's): every save, who and what, newest first; the latest one undoes."""
    if not w.author():
        return
    pid = w.plan["id"]

    def got(rows):
        if _pid(w) != pid:
            return
        if rows is None:
            w.say("Couldn't load the history.")
            return
        undo = rows[0] if rows and rows[0].get("undo") and rows[0].get("version") is not None else None
        w.sheet(dict({"kind": "history", "title": f"History · {w.plan_name() or 'the plan'}",
                      "words": "" if rows else ("No saves yet. Each one shows here, who made it and what it changed, "
                                                "and the latest can be undone."),
                      "rows": [{"who": _who_said(w, x), "text": str(x.get("summary") or ""), "ago": M.ago(x.get("at"))} for x in rows],
                      "yes": "Undo the latest" if undo else None, "no": "Close",
                      "tip": "Puts back what the latest save changed, for everyone (as the builder's Undo)"},
                     **_on("history_undo", version=undo["version"] if undo else None)))
    w.ops.ask(w, lambda cl: remote.log(cl, pid), got)


def c_history_undo(w, version=None, sure=False):
    if w.author() and version is not None and not w.busy:
        w.undo_latest(int(version))


# -- co-authors --

def c_coauthor_ask(w):
    """Ask one of my crew to co-write it: my crew read (one request), then the pick."""
    if not _owner(w) or w.busy:
        return
    raw, pid = _raw(w), w.plan["id"]
    have = {raw.get("owner")} | {e.get("uid") for e in _eds(w)}

    def got(crew):
        if _pid(w) != pid:
            return
        if crew is None:
            w.say("Couldn't load your crew. Try again.")
            return
        crew = [(uid, name) for uid, name in crew if uid not in have]
        if not crew:
            w.say("Co-authors come from your crew: you add each other.")
            return
        labels, seen = [], {}
        for _u, n in crew:  # two of my crew with one name: "Kai", "Kai (2)", so the pick is the one I meant
            seen[n] = seen.get(n, 0) + 1
            labels.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
        _st(w)["crew"] = (pid, dict(crew))
        w.sheet(dict({"kind": "pick", "title": "Ask a co-author", "words": "From your crew:",
                      "options": [{"v": uid, "label": label} for (uid, _n), label in zip(crew, labels)], "yes": "Ask"},
                     **_on("coauthor_add", uid=crew[0][0])))
    w.ops.ask(w, remote.crew, got)


def c_coauthor_add(w, uid=None, sure=False):
    crew = _st(w)["crew"]
    pid = _pid(w)
    if not _owner(w) or not crew or crew[0] != pid or uid not in crew[1]:
        return
    name = crew[1][uid]
    w.ops.ask(w, lambda cl: remote.add_editor(cl, pid, uid),
              lambda r: _took(w, pid, r, f"Asked {name}. They'll see it on their home page and in Anki."))


def _ed(w, uid):
    return next((e for e in _eds(w) if str(e.get("uid")) == str(uid)), None)


def _offer(w, uid):
    pid = w.plan["id"]
    w.ops.ask(w, lambda cl: remote.offer(cl, pid, uid),
              lambda r: _took(w, pid, r, "They'll see it on their home page and in Anki. It's theirs once they say yes."
                              if uid else "Taken back."))


def c_hand(w, uid=None):
    """Hand it to a co-author who said yes."""
    e = _ed(w, uid)
    if _owner(w) and not w.busy and e and not e.get("pending") and not _raw(w).get("handover"):
        _offer(w, e["uid"])


def c_unhand(w):
    """Take the offer back."""
    if _owner(w) and not w.busy and _raw(w).get("handover"):
        _offer(w, None)


def c_coauthor_off(w, uid=None, sure=False):
    """A co-author off it, or an invite taken back."""
    e = _ed(w, uid)
    if not _owner(w) or w.busy or e is None:
        return
    pid, name = w.plan["id"], str(e.get("name") or "?")

    def done(ok):
        if _pid(w) != pid:
            return
        if not ok:
            w.say(f"{name} is still {'asked' if e.get('pending') else 'a co-author'}. Try again.")
            return
        w.load()
    w.ops.ask(w, lambda cl: remote.remove_editor(cl, pid, e["uid"]), done)


def c_leave(w, sure=False):
    """A co-author leaves."""
    if not w.author() or _owner(w) or w.busy:
        return
    if not sure:
        _ask(w, "leave", f"Leave {_raw(w).get('name') or 'this plan'}?",
             "You stop co-writing it. Its tags stay on your notes until you take them off.", "Leave")
        return
    pid, me = w.plan["id"], w.ops.me()

    def done(ok):
        if ok:
            w.ops.reopen(None)
        else:
            w.say("That didn't work. Try again.")
    w.ops.ask(w, lambda cl: remote.remove_editor(cl, pid, me), done)


# -- the library, next year, a table, taking it down, Your AI app --

def c_listed(w, on=False):
    if not _owner(w) or w.busy or _raw(w).get("listed") == -1:
        return
    on, pid = bool(on), w.plan["id"]
    w.ops.ask(w, lambda cl: remote.set_listed(cl, pid, on),
              lambda r: _took(w, pid, r, "In the library." if on else "Out of the library."))


def c_next_year(w):
    """A copy of the plan, its first lesson a year on less a day (the same weekday), named for next year."""
    st = _st(w)
    if not w.author() or w.busy or "copy" in st["busy"]:
        return
    doc = _raw(w).get("doc") or {}
    first = E.first_day(doc)
    if not first:
        w.say("The plan has no sets to copy.")
        return
    pid, name = w.plan["id"], E.next_year_name(_raw(w).get("name"))
    start = E._later(first, 364)
    st["busy"].add("copy")  # one copy a click (the builder's too)
    w.say("Copying…")

    def job(cl):
        got = remote.copy(cl, pid, start)
        if got[0] == "saved":
            try:  # its name for next year: when that doesn't take, the copy is made all the same
                named = remote.save_meta(cl, got[1]["id"], got[1]["version"], {"name": name}, "named for next year")
            except Exception:  # noqa: BLE001 (no answer: the copy keeps the name the server gave it)
                named = None
            if named and named[0] == "saved":
                return named
        return got

    def done(got):
        st["busy"].discard("copy")
        if not got:
            w.say("That didn't copy: check your connection, then try again.")
        elif got[0] != "saved":
            w.say(str(got[1]))
        else:
            w.say(f"Copied: {got[1].get('name')}, its first set {P.fmt_day(start)}.")
            w.ops.reopen(got[1]["id"])
    w.ops.ask(w, job, done)


def c_table(w):
    """The lessons as a table (tab-separated: paste into a spreadsheet)."""
    if not w.author():
        return
    doc = w.doc or {}
    lines = ["Day\tSet\tFinish by\tTested on\tCards"]
    for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or "")):
        n = len(w.idx.match(u, w.swap, doc)) if w.idx is not None else ""
        ev = next((e.get("name") for e in doc.get("events") or [] if isinstance(e, dict) and e.get("id") == u.get("for")), "")
        lines.append("\t".join(str(x) for x in (u.get("opens"), u.get("name") or "", u.get("due") or "", ev or "", n)))
    for e in doc.get("events") or []:
        if isinstance(e, dict):
            lines.append("\t".join((str(e.get("day")), str(e.get("name") or ""), "", "(quiz or exam)", "")))
    w._copy("\n".join(lines) + "\n", f"Copied: {_pl(len(P.units(doc)), 'set')} as a table. Paste it into a spreadsheet.")


def c_delete_plan(w, sure=False):
    """The owner takes it down; followers keep what's open."""
    if not _owner(w) or w.busy:
        return
    if not sure:
        _ask(w, "delete_plan", f"Delete {_raw(w).get('name') or 'this plan'}?",
             "It's gone for everyone. Followers keep every card they have open; nothing is suspended.", "Delete it", danger=True)
        return
    pid = w.plan["id"]

    def done(ok):
        if ok:
            w.ops.reopen(None)
        else:
            w.say("That didn't work. Try again.")
    w.ops.ask(w, lambda cl: remote.delete(cl, pid), done)


def c_ai_app(w):
    """Your AI app (mcp_dialog, a Qt window for now, over this one)."""
    try:
        from . import mcp_dialog
    except ImportError:
        w.say("Not in this version yet.")
        return
    mcp_dialog.show(w)


# ---- Settings, a plan I follow (mine_tab.py) ----

def _lesson_deck(w, pid):
    """Today's lesson in a deck of its own too (plan_flow's, through the
    window's ops): True or False, or None when this Anki hasn't the choice."""
    get = getattr(w.ops, "lesson_deck_on", None)
    if not callable(get):
        return None
    try:
        on = get(pid)
    except Exception:  # noqa: BLE001 (a choice that can't be read isn't offered)
        return None
    return None if on is None else bool(on)


def _in_library(w):
    """A plan in the library (Make my own copy): `listed` (an author's), or
    the server's `library`, which a follower gets and clean_plan keeps."""
    return bool((w.plan or {}).get("listed") or (w.plan or {}).get("library"))


def _follow_bits(w, pid):
    """My follow as plan_flow keeps it, read once a change (Held back counts a deck)."""
    st = _st(w)
    key = (getattr(w, "_ver", 0), pid, st["tick"])
    if st["follow"][0] != key:
        ops = w.ops
        st["follow"] = (key, {"p": ops.follow_state(pid) or {}, "held": int(ops.held_count(pid) or 0),
                              "team": bool(ops.in_team(pid)), "reset": bool(ops.can_reset(pid)),
                              "lesson": _lesson_deck(w, pid)})
    return st["follow"][1]


def _follower(w):
    pid = w.plan["id"]
    got = _follow_bits(w, pid)
    p = got["p"]
    if not p:
        return {"role": "follower", "pid": pid, "gone": "You don't follow it on this account any more."}
    shift, own = int(p.get("shift") or 0), str(p.get("own") or "")
    names = {u["id"]: u for u in P.units(w.plan.get("doc") or {})}
    skips = []
    for uid in p.get("skipped") or []:
        u = names.get(uid)
        skips.append({"uid": uid, "label": f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}" if u else "a set taken off"})
    today, have = w.ops.today(), set(p.get("skipped") or [])
    ahead = [u for u in sorted(names.values(), key=lambda u: str(u.get("opens") or ""))
             if str(u.get("opens") or "") >= today and u["id"] not in have][:20]
    n, inside = got["held"], got["team"]
    early = int(p.get("early") or 0)
    return {
        "role": "follower", "pid": pid,
        "head": f"Following {p.get('name') or 'the plan'}" + (", paused" if p.get("paused") else ""),
        "shift": shift, "later": f"{_pl(shift, 'day')} later" if shift else "Some days later…",
        "skips": skips, "ahead": [{"uid": u["id"], "label": f"{P.fmt_day(u['opens'])} · {u.get('name') or '?'}"} for u in ahead],
        "own": own, "held": f"{_pl(n, 'card')}…" if n else "", "lesson": got["lesson"],
        "squad": "You're in it" if inside else "Not in it: join from the board's Squads tab",
        "squadTip": "Its squad sees that you showed up, never your numbers" if inside else "",
        "paused": bool(p.get("paused")), "copy": _in_library(w),
        "early": [{"n": k, "label": label, "on": early == k} for k, label in EARLY],
        "sched": bool(p.get("sched")), "reset": got["reset"],
    }


def _do(w, what, *args):
    """One of plan_flow's steps on my follow (through the window's ops); my
    follow read again once its request is likely back, and the plan with it
    when my dates moved."""
    pid = _pid(w)
    if not pid or w.author():
        return
    was = dict(w.ops.follow_state(pid) or {})
    getattr(w.ops, what)(pid, *args)
    _soon(w, lambda: _again(w, pid, was))


def _again(w, pid, was):
    if not w.alive() or _pid(w) != pid or w.author():
        return
    st = _st(w)
    st["tick"] += 1
    now = w.ops.follow_state(pid) or {}
    if any(was.get(k) != now.get(k) for k in FOLLOW_KEYS):
        w.load()
    else:
        w.push()


def _fresh(w):
    """My follow as it is now (the rows show what's so until a step changes it)."""
    st = _st(w)
    st["tick"] += 1
    return _follow_bits(w, _pid(w))["p"] if _pid(w) and not w.author() else {}


def c_shift(w, later=False):
    """My dates: as the plan, or some days later (plan_flow asks how many)."""
    p = _fresh(w)
    if p and (later or int(p.get("shift") or 0)):
        _do(w, "set_shift")
    w.push()


def c_skip(w, uid=None, on=True):
    """A lesson skipped, or skipped no more."""
    p = _fresh(w)
    if not p or not isinstance(uid, str):
        return
    if on and not any(u["id"] == uid for u in P.units(w.plan.get("doc") or {})):
        return
    if not on and uid not in (p.get("skipped") or []):
        return
    _do(w, "set_skip", uid, bool(on))
    w.push()


def c_own(w, own=""):
    """How its cards open: each morning on their dates (""), or when I'm ready."""
    p = _fresh(w)
    if p and own in ("", "ready") and str(p.get("own") or "") != own:
        _do(w, "set_own", own)
    w.push()


def c_own_next(w, on=False):
    """When I'm ready, the next opens once I've seen most of the last."""
    p = _fresh(w)
    if p and p.get("own"):
        _do(w, "set_own", "next" if on else "ready")


def c_early(w, n=0):
    p = _fresh(w)
    if p and not p.get("own") and int(n) in dict(EARLY):
        _do(w, "set_early", int(n))


def c_pause(w):
    p = _fresh(w)
    if p:
        _do(w, "resume" if p.get("paused") else "pause_until")


def c_held(w):
    if _fresh(w):
        _do(w, "show_held")


def c_change_deck(w):
    if _fresh(w):
        _do(w, "change_deck")


def c_open_everything(w):
    if _fresh(w):
        _do(w, "open_everything")


def c_schedule(w):
    p = _fresh(w)
    if p and p.get("sched"):
        _do(w, "open_schedule")


def c_reset(w):
    if _fresh(w):
        _do(w, "reset_days")


def c_stop_following(w):
    if _fresh(w):
        _do(w, "stop_following")


def c_copy_mine(w):
    """Make my own copy (a library plan): the same dates, mine to change."""
    if _fresh(w) and _in_library(w):
        w.ops.copy_plan(w, w.plan["id"], w.say)


def c_lesson_deck(w, on=False):
    """Today's lesson: A, it opens in my deck; B, in a deck of its own too."""
    pid = _pid(w)
    if not pid or w.author() or _lesson_deck(w, pid) is None:
        return
    w.ops.set_lesson_deck(pid, bool(on))
    _st(w)["tick"] += 1
    w.push()
