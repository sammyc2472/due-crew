"""Due, the glue: what the box above the board shows, from this computer,
and what its clicks do. Main thread: every collection read and the one
leech step happen here; the only requests are the account settings
pushes my own items ride (app.save_cfg), as any setting does.

Account keys (every computer, and the site): `due_items` (my own to-dos),
`due_ticks` (the author's lines I ticked), `due_show` (show it), and
`due_suggest` (suggestions from my own Anki). Per computer, in the config:
`due_tab`, `due_fold` (my Hide/Show for one day; else Due folds
itself once the day is done), and `due_leeches` (recover leeches: it changes this
collection, so it's this computer's to say). Per profile, beside the
plans (plans.json): the day's dismissed suggestions and what recovering
leeches did today.
"""

import datetime
import time
import traceback
from urllib.parse import unquote

from aqt import mw
from aqt.utils import tooltip

from . import app
from . import due as D
from . import plans as P
from .app import _state, cfg, save_cfg

AGAIN_MIN = 10  # today's misses before the box suggests going over them
MISSES = P.our_deck("Today's misses")  # their filtered deck, under Due Crew's parent
LEECH_MIN = 3  # new leeches this week before it suggests a look
RECOVER_MAX = 200  # leeches recovered in a morning, at most
REVIEWS_FRESH = 30.0  # seconds a reviews-due count is good for


def _pf():
    from . import plan_flow
    return plan_flow


def _today():
    return _state["labels"][0] if _state.get("labels") else ""


def on(c):
    return bool(c.get("due_show", True))


def _items(c):
    return D.clean_items(c.get("due_items"))


def _ticks(c):
    return D.clean_ticks(c.get("due_ticks"))


def _save(c, items=None, ticks=None):
    if items is not None:
        c["due_items"] = items
    if ticks is not None:
        c["due_ticks"] = ticks
    save_cfg(c)  # an account key: pushed, newest save wins


# ---- what the box shows ----

def plan_dates(today):
    """(dates, events, review days) from the plans I follow and run here, as
    due.view takes them: each date with my numbers and its parts."""
    pf = _pf()
    prog = _state.get("plan_progress") or {}
    parts = _state.get("plan_parts") or {}
    sibs = _state.get("plan_sibs") or {}
    state = pf._state_cfg()
    end = D.iso(D.d(today) + datetime.timedelta(days=D.AHEAD))
    dates, events, reviews = [], [], []
    for p in pf.followed():
        st = state.get(p["id"])
        if p.get("paused") or not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
            continue
        doc, title = p["doc"], P.plan_title(p)
        named = {x["id"]: x for x in P.units(P.with_picks(doc, (_state.get("plan_picks") or {}).get(p["id"])))}  # 3.8.1
        evs = {e.get("id"): e for e in doc.get("events") or [] if isinstance(e, dict)}
        applied = st.get("applied") or {}
        crew, followers = p.get("crewDone") or {}, int(p.get("followers") or 0)
        upd = (_state.get("plan_updates") or {}).get(p["id"]) or {}
        own = P.own_pace(p)  # 3.8.0: the dates I opened are today's, till seen; nothing is behind or upcoming
        own_days = st.get("own_opened") or {}
        for u in P.units(doc):
            opens = str(u.get("opens") or "")
            a = applied.get(u["id"])
            pr = (prog.get(p["id"]) or {}).get(u["id"])
            o, s, t = pr or [0, 0, 0]
            if own:
                if not P.opened_here(applied, u, prog.get(p["id"]) or {}):
                    continue
                if int(t) and int(s) >= int(t) and own_days.get(u["id"]) != today:
                    continue
                opens = today
            if not opens or opens > end:
                continue
            # 3.7.2: an even date (or a 3.2 schedule) opens in slices and is
            # applied only when its window ends: while it runs, what's due is
            # what has opened so far
            running = not a and int(o) > 0 and bool(u.get("even") or p.get("sched"))
            if opens < today and (not (a or running) or str(a).startswith("skip:")):
                continue  # never opened here (followed after it): not mine to be behind on
            if not int(t) and opens < today and not u.get("todo"):
                continue  # nothing of it in my deck: nothing to be behind on
            ev = evs.get(u.get("for"))
            dates.append({"pid": p["id"], "uid": u["id"], "plan": title, "name": str(u.get("name") or "?"),
                          "opens": opens, "seen": int(s),
                          "total": int(o) if running else int(t) or (P.unit_total(u) if opens > today else 0),
                          # counted here and nothing of it in my deck: done once it's open (3.7.2)
                          "counted": pr is not None and opens <= today,
                          "parts": (parts.get(p["id"]) or {}).get(u["id"]) or [],
                          "sibs": (sibs.get(p["id"]) or {}).get(u["id"]),
                          "todo": [x for x in u.get("todo") or [] if isinstance(x, dict)],
                          "what": P.topics_line([u]), "topics": P.topic_view([named.get(u["id"], u)]),  # 3.8.0: each a link
                          "rm": P.topic_remarks(doc, [named.get(u["id"], u)]),  # 3.8.1: the authors' notes under its topics
                          "crew": [int(crew.get(u["id"]) or 0), followers] if followers > 1 else None,
                          "prep": str(ev.get("name") or "") if ev else None,
                          # 3.8.1: a date after its event reinforces it ("after Heme quiz"); Study
                          # on a date with cards open (a Due Crew deck of them); view() adds both to its row
                          "after": bool(ev) and P.reinforces(doc, u) is not None,
                          "study": opens <= today and int(o) > 0,
                          # 3.7.3: an author's update adds to it, waiting for Open (its count when it's
                          # the only date the update touches; -1: one of several)
                          "upd": (0 if u["id"] not in (upd.get("units") or []) else
                                  int(upd.get("n") or 0) if len(upd["units"]) == 1 else -1)})
        for e in evs.values():
            if today <= str(e.get("day") or "") <= end:
                events.append({"day": e["day"], "name": str(e.get("name") or "?"), "plan": title})
        for r in doc.get("reviews") or []:
            if isinstance(r, dict) and today <= str(r.get("day") or "") <= end:
                reviews.append({"day": r["day"], "plan": title})
    return dates, events, reviews


def plan_every(today):
    """3.8.0: the weekly lines of the plans I follow and run here, as
    due.view takes them: {pid, plan, first, last, lines}, from my first date
    to my last (or the plan's last event or end date, if later)."""
    pf = _pf()
    state = pf._state_cfg()
    out = []
    for p in pf.followed():
        st = state.get(p["id"])
        doc = p["doc"]
        lines = [x for x in doc.get("every") or [] if isinstance(x, dict)]
        if not lines or p.get("paused") or not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
            continue
        days = [str(u.get("opens") or "") for u in P.units(doc) if u.get("opens")]
        if not days:
            continue
        ends = days + [str(e.get("day") or "") for e in doc.get("events") or [] if isinstance(e, dict)]
        ends += [str(doc["end"])] if doc.get("end") else []
        out.append({"pid": p["id"], "plan": P.plan_title(p), "first": min(days), "last": max(ends), "lines": lines})
    return out


def _every_line(key, today, any_day=False):
    """(plan, line) for a weekly line's key, on today (or any day), else (None, None)."""
    pid = key.split(":")[0]
    for p in plan_every(today):
        if p["pid"] == pid:
            keys = D.every_keys(pid, p["lines"])
            if key in keys and (any_day or D.every_on(p, p["lines"][keys.index(key)], today)):
                return p, p["lines"][keys.index(key)]
    return None, None


def _reviews():
    """{due, done, back, at}: reviews and learning due now across my decks,
    whether I've reviewed today, and the learning cards back later today
    (how many, the first one's time). Cached a little: the board redraws often."""
    hit = _state.get("due_reviews")
    if hit and time.time() - hit[0] < REVIEWS_FRESH:
        return hit[1]
    out = None
    try:
        tree = mw.col.sched.deck_due_tree()
        due = sum(int(n.review_count) + int(n.learn_count) for n in tree.children)
        start = (mw.col.sched.day_cutoff - 86400) * 1000
        done = int(mw.col.db.scalar("SELECT count() FROM revlog WHERE id >= ? AND ease > 0", start) or 0)
        # 3.8.0: learning cards that come back later today (past Anki's learn-ahead)
        now = int(time.time())
        ahead = int(mw.col.get_config("collapseTime", 1200) or 0)
        back, first = mw.col.db.first("SELECT count(), min(due) FROM cards WHERE queue = 1 AND due > ? AND due < ?",
                                      now + ahead, int(mw.col.sched.day_cutoff)) or (0, None)
        t = time.localtime(int(first)) if back and first else None
        out = {"due": due, "done": done, "back": int(back or 0), "at": f"{t.tm_hour}:{t.tm_min:02d}" if t else "",
               "next": _next_deck(tree)}
        if back and first:
            _flip_at(int(first) - ahead)
    except Exception:
        traceback.print_exc()
    _state["due_reviews"] = (time.time(), out)
    return out


def _flip_at(when):
    """3.8.0: when the first learning card comes back (inside Anki's
    learn-ahead), Reviews says it's due: one timer, the earliest, redraws
    the box while the Decks screen shows it. Gone with the profile."""
    pending = _state.get("back_timer")
    if pending and pending[0] <= when and pending[1] == app.generation:
        return
    gen = app.generation
    _state["back_timer"] = (when, gen)
    delay = max(5, min(when - int(time.time()), 86400)) * 1000 + 2000

    def fire():
        if _state.get("back_timer") != (when, gen) or app.generation != gen:
            return
        _state["back_timer"] = None
        _state["due_reviews"] = None
        if getattr(mw, "state", "") == "deckBrowser":
            _swap(cfg())
    try:
        from aqt.qt import QTimer
        QTimer.singleShot(int(delay), fire)
    except Exception:
        traceback.print_exc()


def _day_state():
    pc = _pf()._pcfg()
    st = pc.get("due") if isinstance(pc.get("due"), dict) else {}
    if st.get("day") != _today():
        st = {"day": _today(), "dismissed": [], "recovered": []}
    return pc, st


def _put_day(pc, st):
    pc["due"] = st
    _pf()._psave(pc)


def suggestions(c, today):
    """At most two, from my own Anki: today's misses, new leeches."""
    if not c.get("due_suggest", True) or not mw.col:
        return []
    _pc, st = _day_state()
    gone = set(st.get("dismissed") or [])
    # every render asks; the answer changes only when the collection does
    key = (getattr(mw.col, "mod", None), _today(), tuple(sorted(gone)), bool(c.get("due_leeches")))
    hit = _state.get("due_suggest")
    if key[0] is not None and hit and hit[0] == key:
        return list(hit[1])
    out = []
    try:
        # 3.8.0: today's misses are Study today's last step, not a suggestion of their own
        if not c.get("due_leeches"):
            week = (mw.col.sched.day_cutoff - 8 * 86400) * 1000
            lee = int(mw.col.db.scalar(
                "SELECT count(DISTINCT c.nid) FROM cards c JOIN notes n ON n.id = c.nid "
                "WHERE (' ' || lower(n.tags) || ' ') LIKE '% leech %' "
                "AND c.id IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)", week) or 0)
            if lee >= LEECH_MIN and "leeches" not in gone:
                out.append({"key": "leeches", "text": f"{lee:,} new leeches this week", "go": "See them"})
    except Exception:
        traceback.print_exc()
    _state["due_suggest"] = (key, out[:2])
    return out[:2]


def notes():
    _pc, st = _day_state()
    n = len(st.get("recovered") or [])
    return [{"key": "recovered", "text": f"Recovered {n:,} leech{'es' if n != 1 else ''} as new cards",
             "go": "See them"}] if n and "recovered" not in (st.get("dismissed") or []) else []


YOU_TABS = D.TABS + ("plans", "insights")  # 3.8.0: the You bubble's tabs, Due's lists first


def you_tab(c):
    """The You bubble's tab on this computer (`due_tab`), Today when unknown."""
    tab = c.get("due_tab")
    return tab if tab in YOU_TABS else "today"


def folded(c, v):
    """The bubble folded or open: Due's own rule with its lists on (v), else
    my Hide/Show for today."""
    if v:
        return bool(v.get("folded"))
    choice = c.get("due_fold")
    return isinstance(choice, dict) and choice.get("day") == _today() and bool(choice.get("folded"))


def view(c):
    """due.view for the board, or None when the box is off or there's no day yet."""
    today = _today()
    if not on(c) or not today:
        return None
    try:
        dates, events, revs = plan_dates(today)
        items = D.prune(_items(c), today)
        v = D.view(today, dates, items, _ticks(c), tab=c.get("due_tab", "today"), events=events,
                   review_days=revs, reviews=_reviews() if mw.col else None,
                   suggestions=suggestions(c, today), notes=notes(), every=plan_every(today))
        v["folded"] = D.fold_state(c.get("due_fold"), v, today)
        v["done"] = D.done_for_today(v)
        # 3.8.0: the morning's line, with Not today; 3.8.1: and what it opened, by date
        v["opened"] = _pf().opened_view() if mw.col else None
        more = {(x["pid"], x["uid"]): x for x in dates}
        for r in v.get("rows") or []:
            x = more.get((r.get("pid"), r.get("uid"))) if r.get("kind") == "plan" else None
            if x:  # 3.8.1: what due.view's rows don't carry: "after" its event, Study
                r["after"], r["study"] = bool(x.get("after")), bool(x.get("study"))
        v["study_to"] = ((_reviews() or {}).get("next") or "") if v.get("study") and mw.col else ""
        # 3.8.1: "Fifteen?", when the day hasn't started by my usual time
        from . import rooms
        v["nudge"] = rooms.nudge(c, v, _day_state()[1].get("dismissed") or ())
        v["nudge_sev"] = rooms.nudge_sev() if v["nudge"] else None
    except Exception:
        traceback.print_exc()
        return None
    v["toast"] = _toast()
    return v


def _toast():
    t = _state.get("due_toast")
    if t and time.time() - t[0] < 20:
        return t[1]
    _state["due_toast"] = None
    return None


# ---- the morning and the refresh ----

def parts(col, idxs, today):
    """Main thread, with the refresh's deck reads: each date's resources
    (P.parts) for the dates the box shows today and behind."""
    if not today:
        return
    pf = _pf()
    state = pf._state_cfg()
    out, sibs = {}, {}  # sibs: {pid: {uid: [counted, buried today]}}
    for p in pf.followed():
        st = state.get(p["id"])
        if p.get("paused") or not st or not pf._deck_ok(col, st.get("deck_id")):
            continue
        idx = pf._index(col, st, idxs)
        applied = st.get("applied") or {}
        doc = p["doc"]
        prog = (_state.get("plan_progress") or {}).get(p["id"]) or {}
        for u in P.units(doc):
            opens = str(u.get("opens") or "")
            a = applied.get(u["id"])
            running = (not a and int((prog.get(u["id"]) or [0])[0]) > 0
                       and bool(u.get("even") or p.get("sched")))  # an even date part open (3.7.2)
            if P.own_pace(p):  # 3.8.0: at my own pace, the dates I opened
                opens = today if P.opened_here(applied, u, prog) else "9999"
            if opens == today or (opens < today and (a or running) and not str(a).startswith("skip:")):
                got = P.parts(idx, u, pf._swap(st), doc)
                if got:
                    out.setdefault(p["id"], {})[u["id"]] = got
                sib = idx.siblings(idx.match(u, pf._swap(st), doc))
                if sib[0]:
                    sibs.setdefault(p["id"], {})[u["id"]] = list(sib)
    _state["plan_parts"] = out
    _state["plan_sibs"] = sibs


def recover_leeches(col, label="Due Crew: recover leeches", cap=RECOVER_MAX):
    """Leeches back as new cards: the leech tag off, unsuspended, and reset
    (Anki's own Forget, back to their place among the new cards), as one
    undo step. A leech is a card of a note tagged leech that's suspended or
    has lapsed 8 times or more (a note's other cards are left alone).
    Returns the card ids."""
    rows = col.db.all(
        "SELECT c.id, c.nid FROM cards c JOIN notes n ON n.id = c.nid "
        "WHERE (' ' || lower(n.tags) || ' ') LIKE '% leech %' AND c.lapses > 0 AND (c.queue = -1 OR c.lapses >= 8) "
        f"ORDER BY c.id LIMIT {int(cap)}")
    if not rows:
        return []
    cids = [int(r[0]) for r in rows]
    nids = sorted({int(r[1]) for r in rows})
    pos = None
    if hasattr(col, "add_custom_undo_entry"):
        try:
            pos = col.add_custom_undo_entry(label)
        except Exception:
            pos = None
    col.tags.bulk_remove(nids, "leech")
    col.sched.unsuspend_cards(cids)
    col.sched.schedule_cards_as_new(cids, restore_position=True, reset_counts=True)
    if pos is not None and hasattr(col, "merge_undo_entries"):
        try:
            col.merge_undo_entries(pos)
        except Exception:
            pass
    return cids


def morning(c):
    """Once per Anki day, at the refresh: recover leeches when asked. Only on
    the Decks screen: mid-review its undo step would sit on my last answer
    (as the plans' morning waits for Decks)."""
    if not c.get("due_leeches") or not mw.col or not _today() or getattr(mw, "state", "") != "deckBrowser":
        return
    pc, st = _day_state()
    if st.get("leeches_done"):
        return
    st["leeches_done"] = True
    try:
        st["recovered"] = recover_leeches(mw.col)
    except Exception:
        traceback.print_exc()
        st["recovered"] = []
    _put_day(pc, st)
    if st["recovered"]:
        _pf()._after_change()


def recover_now():
    """3.8.0: Recover leeches switched on: today's go now, and it says what
    happened (it waited for the next refresh and said nothing)."""
    c = cfg()
    if not c.get("due_leeches") or not mw.col or not _today():
        return
    pc, st = _day_state()
    st["leeches_done"] = False
    _put_day(pc, st)
    morning(c)
    _pc, st = _day_state()
    n = len(st.get("recovered") or [])
    tooltip(f"{n:,} leech{'es' if n != 1 else ''} back as new cards. Edit › Undo puts {'them' if n != 1 else 'it'} back."
            if n else "No leeches to recover now. Each morning looks again.")


def after_refresh():
    """Every refresh: a fresh reviews count, and the morning (once a day)."""
    _state["due_reviews"] = None
    try:
        morning(cfg())
    except Exception:
        traceback.print_exc()


# ---- clicks ----

def _swap(c):
    if app.swap:
        app.swap(c)


def add(c, when, text, raw=False):
    """dueadd: `when` the add line's day button (today, later, a day), and
    a day said at the end of the text wins unless `raw`."""
    today = _today()
    if not today:
        return
    text = " ".join(unquote(text).split())
    day = today if when == "today" else "" if when == "later" else when
    rule = None
    if not raw:
        text, rule = D.parse_repeat(text)  # 3.8.0: "every mon" first
        if not rule:
            text, said = D.parse(text, today)
            if said is not None:
                day = said
    if not D.day_ok(day, today):
        day = today
    items = D.prune(_items(c), today)
    items, it = D.add(items, text, day, today, rule=rule)
    if not it:
        tooltip("That's 60 open. Tick or delete some first." if D.open_count(items) >= D.MAX_OPEN else "Nothing to add.")
        return
    _save(c, items=items)
    tab = c.get("due_tab", "today")
    if it.get("r"):
        shown = tab == "upcoming" or (tab == "today" and D.on_day(it, today))
        if not shown:
            _state["due_toast"] = (time.time(), {"text": "Added, " + D.repeat_label(it["r"]), "tab": "upcoming"})
    else:
        shown = (tab == "later" and not day) or (tab == "today" and day == today) or (
            tab == "upcoming" and day and day <= D.iso(D.d(today) + datetime.timedelta(days=D.AHEAD)))
    if not shown and not it.get("r"):
        _state["due_toast"] = (time.time(), {"text": "Added to " + (D.long_day(day, today) if day else "Later"),
                                             "tab": "later" if not day else "upcoming"})
    _swap(c)


def item_menu(c, ident):
    """⋯ on one of my items: its day, Edit…, Delete."""
    from aqt.qt import QMenu, QCursor
    today = _today()
    items = _items(c)
    it = next((x for x in items if x["id"] == ident), None)
    if not it or not today:
        return
    m = QMenu(mw)
    tomorrow = D.iso(D.d(today) + datetime.timedelta(days=1))
    if it.get("r"):
        # 3.8.0: a repeat has no day to move to; it stops instead
        m.addAction("Edit…").triggered.connect(lambda: _edit(ident))
        m.addAction("Stop repeating").triggered.connect(lambda: stop_repeat(cfg(), ident))
        m.addSeparator()
        m.addAction("Delete").triggered.connect(lambda: delete(cfg(), ident))
        m.exec(QCursor.pos())
        return

    def move(day):
        c2 = cfg()
        _save(c2, items=D.change(_items(c2), ident, today, d=day))
        _swap(c2)
    for label, day in (("Today", today), ("Tomorrow", tomorrow), ("Later", "")):
        a = m.addAction(label)
        a.setCheckable(True)
        a.setChecked(it["d"] == day)
        a.triggered.connect(lambda _=False, day=day: move(day))
    m.addAction("Pick a day…").triggered.connect(lambda: _pick_day(ident, it["d"] or tomorrow))
    m.addSeparator()
    m.addAction("Edit…").triggered.connect(lambda: _edit(ident))
    m.addAction("Delete").triggered.connect(lambda: delete(cfg(), ident))
    m.exec(QCursor.pos())


def _pick_day(ident, start):
    from aqt.qt import QDialog, QVBoxLayout, QCalendarWidget, QDate, QDialogButtonBox
    today = _today()
    dlg = QDialog(mw)
    dlg.setWindowTitle("Pick a day")
    lay = QVBoxLayout(dlg)
    cal = QCalendarWidget(dlg)
    t, s = D.d(today), D.d(start if start >= today else today)
    cal.setMinimumDate(QDate(t.year, t.month, t.day))
    mx = t + datetime.timedelta(days=D.MAX_AHEAD_DAYS)
    cal.setMaximumDate(QDate(mx.year, mx.month, mx.day))
    cal.setSelectedDate(QDate(s.year, s.month, s.day))
    lay.addWidget(cal)
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    if dlg.exec():
        q = cal.selectedDate()
        day = datetime.date(q.year(), q.month(), q.day()).isoformat()
        c = cfg()
        _save(c, items=D.change(_items(c), ident, today, d=day))
        _swap(c)


def _edit(ident):
    from aqt.utils import getText
    c = cfg()
    it = next((x for x in _items(c) if x["id"] == ident), None)
    if not it:
        return
    text, ok = getText("Edit to-do", parent=mw, default=it["t"], title="Due")
    if ok and " ".join(str(text).split()):
        c = cfg()
        _save(c, items=D.change(_items(c), ident, _today(), t=text))
        _swap(c)


def delete(c, ident):
    _save(c, items=D.remove(_items(c), ident))
    _swap(c)


def stop_repeat(c, ident):
    """3.8.0: a repeat becomes a one-off today."""
    _save(c, items=D.change(_items(c), ident, _today(), r=""))
    _swap(c)


def tick(c, ident):
    items = _items(c)
    it = next((x for x in items if x["id"] == ident), None)
    if it:
        today = _today()
        _save(c, items=D.change(items, ident, today, done=not D.done_on(it, today)))
        _swap(c)


def todo_tick(c, key):
    """An author's line, ticked by hand (only once its date has opened); a
    weekly one (3.8.0) for today, on its day."""
    today = _today()
    pid, uid, _h = (key.split(":") + ["", "", ""])[:3]
    if uid == "every":
        p, _ln = _every_line(key, today)
        if not p:
            return
        ticks = _ticks(c)
        if ticks.get(key) == today:
            ticks.pop(key, None)
        else:
            ticks[key] = today
        _save(c, ticks=D.clean_ticks(ticks))
        _swap(c)
        return
    dates, _e, _r = plan_dates(today)
    x = next((x for x in dates if x["pid"] == pid and x["uid"] == uid), None)
    keys = D.line_keys(pid, uid, (x or {}).get("todo"))
    if not x or key not in keys or x["opens"] > today:
        return
    n = keys.index(key)
    ticks = _ticks(c)
    if D.line_ticked(x, ticks)[n]:
        ticks.pop(key, None)
        ticks.pop(D.todo_key(pid, uid, n), None)  # one from before 3.7.2
    else:
        ticks[key] = today
    _save(c, ticks=D.clean_ticks(ticks))
    _swap(c)


def open_link(key):
    """An author's line's link, in the browser: only an https one on a date I follow."""
    pid, uid, _h = (key.split(":") + ["", "", ""])[:3]
    if uid == "every":
        _p, ln = _every_line(key, _today(), any_day=True)
        if ln and str(ln.get("url") or "").startswith("https://"):
            from aqt.utils import openLink
            openLink(ln["url"])
        return
    dates, _e, _r = plan_dates(_today())
    x = next((x for x in dates if x["pid"] == pid and x["uid"] == uid), None)
    todo = (x or {}).get("todo") or []
    keys = D.line_keys(pid, uid, todo)
    if key in keys and str(todo[keys.index(key)].get("url") or "").startswith("https://"):
        from aqt.utils import openLink
        openLink(todo[keys.index(key)]["url"])


def go(key):
    """A suggestion's or a note's button."""
    if not mw.col:
        return
    pf = _pf()
    if key == "again":
        start = (mw.col.sched.day_cutoff - 86400) * 1000
        cids = [int(x) for x in mw.col.db.list(
            "SELECT DISTINCT cid FROM revlog WHERE id >= ? AND ease = 1", start)][:500]
        if cids and pf._filtered(mw.col, MISSES, cids):
            pf._after_change()
            did = mw.col.decks.id_for_name(MISSES)
            if did:
                mw.col.decks.select(did)
                mw.moveToState("overview")
    elif key in ("leeches", "recovered"):
        import aqt
        browser = aqt.dialogs.open("Browser", mw)
        if key == "leeches":
            browser.search_for("tag:leech")
        else:
            _pc, st = _day_state()
            cids = st.get("recovered") or []
            if cids:
                browser.search_for("cid:" + ",".join(str(int(x)) for x in cids))


def dismiss(key):
    pc, st = _day_state()
    st["dismissed"] = list(dict.fromkeys(list(st.get("dismissed") or []) + [key]))[-20:]
    _put_day(pc, st)
    _swap(cfg())


def on_message(cmd, parts):
    """The board's Due commands (duetab, dueadd, …). True when handled."""
    c = cfg()
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "duetab" and arg in YOU_TABS:
        if arg in (c.get("hidden_tabs") or []):
            c["hidden_tabs"] = [k for k in c["hidden_tabs"] if k != arg]  # a link to it shows it again
        c["due_tab"] = arg
        c["due_fold"] = {"day": _today(), "folded": False}
        save_cfg(c)
        _state["due_toast"] = None
        _swap(c)
    elif cmd == "duefold":
        # Hide or Show by hand: it holds for today; tomorrow Due decides again
        c["due_fold"] = {"day": _today(), "folded": not folded(c, view(c))}
        save_cfg(c)
        _swap(c)
    elif cmd == "dueadd" and len(parts) > 4:
        # dueadd:WHEN:RAW:text (the text URI-encoded, so it may hold ":")
        add(c, arg, ":".join(parts[4:]), raw=parts[3] == "1")
    elif cmd == "duetick" and arg:
        tick(c, arg)
    elif cmd == "dueitem" and arg:
        item_menu(c, arg)
    elif cmd == "duedo" and arg:
        _save(c, items=D.change(_items(c), arg, _today(), d=_today()))
        _swap(c)
    elif cmd == "duetodo" and len(parts) > 4:
        todo_tick(c, ":".join(parts[2:5]))
    elif cmd == "duelink" and len(parts) > 4:
        open_link(":".join(parts[2:5]))
    elif cmd == "duego" and arg:
        go(arg)
    elif cmd == "duestudy":
        study_today()  # 3.8.0
    elif cmd == "duex" and arg:
        dismiss(arg)
    elif cmd == "dueshow" and arg in D.TABS:
        c["due_tab"] = arg
        save_cfg(c)
        _state["due_toast"] = None
        _swap(c)
    else:
        return False
    return True


# ---- 3.8.0: Study today, one button through the day ----

def _plan_decks():
    """The decks of the plans I follow (not paused), in plan order."""
    pf = _pf()
    st = pf._state_cfg()
    out = []
    for p in pf.followed():
        did = (st.get(p["id"]) or {}).get("deck_id")
        if p.get("paused") or not did or not pf._deck_ok(mw.col, did) or int(did) in out:
            continue
        out.append(int(did))
    return out


def _due_now(col, dids, tree=None):
    """{deck id: cards Anki would show now} for these decks and every top
    deck, from Anki's deck tree (its limits, its subdecks)."""
    out = {}

    def walk(node, top):
        if top or int(node.deck_id) in dids:
            out[int(node.deck_id)] = int(node.review_count) + int(node.learn_count) + int(node.new_count)
        for ch in node.children:
            walk(ch, False)
    for ch in (tree or col.sched.deck_due_tree()).children:
        walk(ch, True)
    return out


def _next_deck(tree):
    """3.8.0 (Board in Motion, 35): the deck Study today opens first, its
    last name, for the button; from the tree _reviews already read."""
    try:
        plan = _plan_decks()
        step = D.study_next(plan, _due_now(mw.col, set(plan), tree), 0, True)
        return str(mw.col.decks.name(int(step[1]))).split("::")[-1] if step else ""
    except Exception:
        traceback.print_exc()
        return ""


def _misses_today(col):
    start = (col.sched.day_cutoff - 86400) * 1000
    return [int(x) for x in col.db.list("SELECT DISTINCT cid FROM revlog WHERE id >= ? AND ease = 1", start)]


def study_today():
    """Study today › (the box, its folded line, Ctrl+Shift+S): the walk
    starts. Plans' decks first, then the deck with the most due, then
    today's misses, each in Anki's own review; it goes on when a deck runs
    out and ends when I leave the review."""
    if not mw.col:
        return
    _state["study_walk"] = {"misses": False, "steps": 0}
    study_step(first=True)


def study_step(first=False):
    w = _state.get("study_walk")
    if not w or not mw.col:
        return
    w["steps"] += 1
    step = None
    if w["steps"] <= D.STUDY_STEPS:
        try:
            plan = _plan_decks()
            misses = _misses_today(mw.col)
            step = D.study_next(plan, _due_now(mw.col, set(plan)),
                                len(misses) if len(misses) >= AGAIN_MIN else 0, w["misses"])
        except Exception:
            traceback.print_exc()
    if step and step[0] == "misses":
        w["misses"] = True
        pf = _pf()
        name = MISSES
        if pf._filtered(mw.col, name, _misses_today(mw.col)[:500]):
            pf._after_change()
            did = mw.col.decks.id_for_name(name)
            if did:
                return _study_deck(did, first, "today's misses")
        step = None
    if step:
        return _study_deck(step[1], first)
    _state["study_walk"] = None
    r = _reviews() or {}
    back = int(r.get("back") or 0)
    tooltip(f"Done for now · {back:,} learning card{'s' if back != 1 else ''} back at {r.get('at')}"
            if back and r.get("at") else "Nothing due now." if first else "Done for today.")
    if not first and getattr(mw, "state", "") != "deckBrowser":
        mw.moveToState("deckBrowser")


def _study_deck(did, first, label=None):
    try:
        mw.col.decks.select(int(did))
        if not first:
            tooltip("Next: " + (label or mw.col.decks.name(int(did))), period=2500)
        _state["study_walk"]["deck"] = int(did)
        mw.moveToState("review")
    except Exception:
        traceback.print_exc()
        _state["study_walk"] = None


def walk_keys(state, shortcuts):
    """Escape while Study today walks the review: the walk stops there, the
    deck stays open (Anki's review has no Escape of its own)."""
    if state == "review" and _state.get("study_walk"):
        shortcuts.append(("Esc", stop_walk))


def stop_walk():
    if _state.get("study_walk"):
        _state["study_walk"] = None
        tooltip("Study today stopped. This deck stays open.")


def on_state(new, old):
    """Anki's screen changed: a walk goes on when its deck runs out (Anki's
    review hands over to the deck's overview with nothing left), and ends
    when I leave it any other way."""
    if not _state.get("study_walk") or new == "review":
        return
    if new == "overview" and old == "review" and mw.col:
        try:
            left = sum(int(x) for x in mw.col.sched.counts())
        except Exception:
            left = 1
        if not left:
            from aqt.qt import QTimer
            QTimer.singleShot(0, study_step)
            return
    _state["study_walk"] = None
