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
    state = pf._state_cfg()
    end = D.iso(D.d(today) + datetime.timedelta(days=D.AHEAD))
    dates, events, reviews = [], [], []
    for p in pf.followed():
        st = state.get(p["id"])
        if p.get("paused") or not st or not mw.col or not pf._deck_ok(mw.col, st.get("deck_id")):
            continue
        doc, title = p["doc"], P.plan_title(p)
        evs = {e.get("id"): e for e in doc.get("events") or [] if isinstance(e, dict)}
        applied = st.get("applied") or {}
        crew, followers = p.get("crewDone") or {}, int(p.get("followers") or 0)
        for u in P.units(doc):
            opens = str(u.get("opens") or "")
            if not opens or opens > end:
                continue
            if opens < today:
                a = applied.get(u["id"])
                if not a or str(a).startswith("skip:"):
                    continue  # never opened here (followed after it): not mine to be behind on
            o, s, t = (prog.get(p["id"]) or {}).get(u["id"], [0, 0, 0])
            if not int(t) and opens < today and not u.get("todo"):
                continue  # nothing of it in my deck: nothing to be behind on
            ev = evs.get(u.get("for"))
            dates.append({"pid": p["id"], "uid": u["id"], "plan": title, "name": str(u.get("name") or "?"),
                          "opens": opens, "seen": int(s), "total": int(t) or (P.unit_total(u) if opens > today else 0),
                          "parts": (parts.get(p["id"]) or {}).get(u["id"]) or [],
                          "todo": [x for x in u.get("todo") or [] if isinstance(x, dict)],
                          "what": P.topics_line([u]),
                          "crew": [int(crew.get(u["id"]) or 0), followers] if followers > 1 else None,
                          "prep": str(ev.get("name") or "") if ev else None})
        for e in evs.values():
            if today <= str(e.get("day") or "") <= end:
                events.append({"day": e["day"], "name": str(e.get("name") or "?"), "plan": title})
        for r in doc.get("reviews") or []:
            if isinstance(r, dict) and today <= str(r.get("day") or "") <= end:
                reviews.append({"day": r["day"], "plan": title})
    return dates, events, reviews


def _reviews():
    """{due, done}: reviews and learning due now across my decks, and
    whether I've reviewed today. Cached a little: the board redraws often."""
    hit = _state.get("due_reviews")
    if hit and time.time() - hit[0] < REVIEWS_FRESH:
        return hit[1]
    out = None
    try:
        tree = mw.col.sched.deck_due_tree()
        due = sum(int(n.review_count) + int(n.learn_count) for n in tree.children)
        start = (mw.col.sched.day_cutoff - 86400) * 1000
        done = int(mw.col.db.scalar("SELECT count() FROM revlog WHERE id >= ? AND ease > 0", start) or 0)
        out = {"due": due, "done": done}
    except Exception:
        traceback.print_exc()
    _state["due_reviews"] = (time.time(), out)
    return out


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
        start = (mw.col.sched.day_cutoff - 86400) * 1000
        n = int(mw.col.db.scalar("SELECT count(DISTINCT cid) FROM revlog WHERE id >= ? AND ease = 1", start) or 0)
        if n >= AGAIN_MIN and "again" not in gone:
            out.append({"key": "again", "text": f"Go over today's {n:,} misses", "go": "Study"})
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
                   suggestions=suggestions(c, today), notes=notes())
        v["folded"] = D.fold_state(c.get("due_fold"), v, today)
        v["done"] = D.done_for_today(v)
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
    out = {}
    for p in pf.followed():
        st = state.get(p["id"])
        if p.get("paused") or not st or not pf._deck_ok(col, st.get("deck_id")):
            continue
        idx = pf._index(col, st, idxs)
        applied = st.get("applied") or {}
        doc = p["doc"]
        for u in P.units(doc):
            opens = str(u.get("opens") or "")
            if opens == today or (opens < today and applied.get(u["id"])
                                  and not str(applied[u["id"]]).startswith("skip:")):
                got = P.parts(idx, u, pf._swap(st), doc.get("deck", ""))
                if got:
                    out.setdefault(p["id"], {})[u["id"]] = got
    _state["plan_parts"] = out


def recover_leeches(col, label="Due Crew: recover leeches", cap=RECOVER_MAX):
    """Leeches back as new cards: the leech tag off, unsuspended, and reset
    (Anki's own Forget, back to their place among the new cards), as one
    undo step. A leech is a card of a note tagged leech that's suspended or
    has lapsed 8 times or more (a note's other cards are left alone).
    Returns the card ids."""
    rows = col.db.all(
        "SELECT c.id, c.nid FROM cards c JOIN notes n ON n.id = c.nid "
        "WHERE (' ' || lower(n.tags) || ' ') LIKE '% leech %' AND (c.queue = -1 OR c.lapses >= 8) "
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
    """Once per Anki day, at the refresh: recover leeches when asked."""
    if not c.get("due_leeches") or not mw.col or not _today():
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
    if not raw:
        text, said = D.parse(text, today)
        if said is not None:
            day = said
    if not D.day_ok(day, today):
        day = today
    items = D.prune(_items(c), today)
    items, it = D.add(items, text, day, today)
    if not it:
        tooltip("That's 60 open. Tick or delete some first." if D.open_count(items) >= D.MAX_OPEN else "Nothing to add.")
        return
    _save(c, items=items)
    tab = c.get("due_tab", "today")
    shown = (tab == "later" and not day) or (tab == "today" and day == today) or (
        tab == "upcoming" and day and day <= D.iso(D.d(today) + datetime.timedelta(days=D.AHEAD)))
    if not shown:
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


def tick(c, ident):
    items = _items(c)
    it = next((x for x in items if x["id"] == ident), None)
    if it:
        _save(c, items=D.change(items, ident, _today(), done=not it["done"]))
        _swap(c)


def todo_tick(c, key):
    """An author's line, ticked by hand (only once its date has opened)."""
    today = _today()
    pid, uid, n = (key.split(":") + ["", "", ""])[:3]
    dates, _e, _r = plan_dates(today)
    x = next((x for x in dates if x["pid"] == pid and x["uid"] == uid), None)
    if not x or not n.isdigit() or int(n) >= len(x.get("todo") or []) or x["opens"] > today:
        return
    ticks = _ticks(c)
    if key in ticks:
        ticks.pop(key)
    else:
        ticks[key] = today
    _save(c, ticks=D.clean_ticks(ticks))
    _swap(c)


def open_link(key):
    """An author's line's link, in the browser: only an https one on a date I follow."""
    pid, uid, n = (key.split(":") + ["", "", ""])[:3]
    dates, _e, _r = plan_dates(_today())
    x = next((x for x in dates if x["pid"] == pid and x["uid"] == uid), None)
    todo = (x or {}).get("todo") or []
    if n.isdigit() and int(n) < len(todo) and str(todo[int(n)].get("url") or "").startswith("https://"):
        from aqt.utils import openLink
        openLink(todo[int(n)]["url"])


def go(key):
    """A suggestion's or a note's button."""
    if not mw.col:
        return
    pf = _pf()
    if key == "again":
        start = (mw.col.sched.day_cutoff - 86400) * 1000
        cids = [int(x) for x in mw.col.db.list(
            "SELECT DISTINCT cid FROM revlog WHERE id >= ? AND ease = 1", start)][:500]
        if cids and pf._filtered(mw.col, "Due Crew · today's misses", cids):
            pf._after_change()
            did = mw.col.decks.id_for_name("Due Crew · today's misses")
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
    if cmd == "duetab" and arg in D.TABS:
        c["due_tab"] = arg
        c["due_fold"] = {"day": _today(), "folded": False}
        save_cfg(c)
        _state["due_toast"] = None
        _swap(c)
    elif cmd == "duefold":
        # Hide or Show by hand: it holds for today; tomorrow Due decides again
        v = view(c)
        c["due_fold"] = {"day": _today(), "folded": not (v or {}).get("folded")}
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
