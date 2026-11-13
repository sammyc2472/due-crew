"""Plans, the glue: a follower's day (3.8.1): Welcome back, Held back, the week's load."""

import copy
import datetime

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from .. import schedule as S
from ..app import _bg
from ..app import _state
from ..app import cfg
from ..app import client
from ..errs import oops

from .morning import _after_change, _hold_yes, _open_now, _shut_by_plan, _state_cfg
from .days import _browse, _plan_idx, _raw
from .state import _deck_ok, _pcfg, _psave, _swap, _today, followed, mine
from .cards import ask_later, run
from .pace import move_date
from .lessons import refresh_progress


# ---- 3.8.1: a follower's day (plans, round three) ----
# Welcome back, the morning's dates, what Hold back keeps, why a date left
# cards shut, Study on a date, my own load beside the plan's. All local but
# Push my dates back (one PATCH, on its click).

REVIEWS_AHEAD = 63  # days of my own reviews due the week can show (nine weeks)


def reviews_by_day(col, today, days=REVIEWS_AHEAD):
    """My own load beside what the plan opens: {iso day: reviews due} in my
    whole Anki, today (overdue too) and the days ahead, by Anki's due day.
    One query; a card in a filtered deck isn't counted."""
    now, base, out = int(col.sched.today), S.d(today), {}
    for k, n in col.db.all("SELECT due - ?, count() FROM cards WHERE queue IN (2, 3) AND odid = 0 AND due < ? "
                           "GROUP BY due", now, now + int(days)) or []:
        day = S.iso(base + datetime.timedelta(days=max(0, int(k))))
        out[day] = out.get(day, 0) + int(n)
    return out


def _note_pace(col, today):
    """refresh_progress: my pace (a new card's seconds, a review's, my usual
    day's minutes) for the load view, read once an Anki day
    (`_state["plan_pace"]`: (day, pace)). 28 days of the answer log."""
    hit = _state.get("plan_pace")
    if hit and hit[0] == today:
        return
    from .. import magic, magic_flow
    try:
        pace = magic_flow.Ops().pace()
    except Exception:
        oops()
        pace = dict(magic.PACE)
    _state["plan_pace"] = (today, pace)


def load_view(plan_list, state, today):
    """3.9.9, You › Plans' load across plans (plans.load_week), from what
    the last refresh read: no collection reads. Plans on this computer's
    deck that run on their days (not paused, not at my own pace)."""
    from .. import magic
    hit = _state.get("plan_pace")
    pace = hit[1] if hit and hit[0] == today else dict(magic.PACE)
    prog, lds, sets = _state.get("plan_progress") or {}, _state.get("plan_load") or {}, []
    end = P._later(today, P.LOAD_DAYS - 1)
    back = _state.get("load_moved")
    for p in plan_list:
        st = state.get(p["id"])
        if not st or p.get("paused") or P.own_pace(p) or not (mw.col and _deck_ok(mw.col, st.get("deck_id"))):
            continue
        doc, ld, pg = mine(p)["doc"], lds.get(p["id"]) or {}, prog.get(p["id"]) or {}
        moved = p.get("moved") or {}
        for u in P.units(doc):
            day = str(u.get("opens") or "")
            if not (today <= day <= end or (back and (p["id"], u["id"]) == tuple(back))):
                continue
            if u["id"] in ld:
                ask = P.load_ask(ld[u["id"]], day, today)
            else:
                _o, s, t = pg.get(u["id"], [0, 0, 0])
                ask = max(0, (int(t) or P.unit_total(u)) - int(s))
            ev = P.event_of(doc, u)
            sets.append({"pid": p["id"], "plan": str(p.get("name") or P.plan_title(p)), "uid": u["id"],
                         "name": str(u.get("name") or "?"), "day": day, "ask": ask,
                         "moved": int(moved.get(u["id"]) or 0), "cap": str((ev or {}).get("day") or "")})
    return P.load_week(sets, _day_due(today), today, pace, back=back)


def load_move(pid, uid, days):
    """The load view's Move: this set `days` later for me (my follow, never
    the plan), and remembered so the view offers Put it back."""
    _state["load_moved"] = (pid, uid)
    move_date(pid, uid, days)


def _note_reviews(col, today):
    """refresh_progress: reviews_by_day, read again only when the collection
    or the day changed (`_state["plan_reviews"]`: ((mod, day), {day: n}))."""
    key = (getattr(col, "mod", None), today)
    hit = _state.get("plan_reviews")
    if hit and key[0] is not None and hit[0] == key:
        return
    _state["plan_reviews"] = (key, reviews_by_day(col, today))


def _day_due(today):
    """{iso day: reviews due} for the week's day lines; today's is Due's own
    count (Anki's limits, learning too) when Due has read it."""
    got = _state.get("plan_reviews")
    out = dict(got[1]) if got and got[0][1] == today else {}
    hit = _state.get("due_reviews")
    if hit and hit[1] and today:
        out[today] = int(hit[1].get("due") or 0)
    return out


def _week_more(week, st, prog, today):
    """card_view's week with what only this computer knows: what a date left
    shut when it opened (leeches, picks this copy doesn't have: _tally's
    counts), Study on a date with cards open, and each day's own load
    (reviews due) beside what the plan opens. A key only where there's
    something to say."""
    lee, miss = (st or {}).get("leeches") or {}, (st or {}).get("missing") or {}
    mine = _day_due(today) if st else {}
    for d in week:
        n = int(mine.get(d["day"]) or 0)
        if n and d["day"] >= today:
            d["mine"] = n
        for r in d["units"]:
            if r["state"] not in ("open", "done"):
                continue
            if st and int(((prog or {}).get(r["uid"]) or [0])[0]):
                r["study"] = True
            m = miss.get(r["uid"])
            why = {"lee": int(lee.get(r["uid"]) or 0), "miss": int(m[0]) if isinstance(m, (list, tuple)) and m else 0}
            if why["lee"] or why["miss"]:
                r["why"] = why


def browse_leeches(pid, uid):
    """Why didn't it open: Anki's browser on a date's leeches, which a plan
    never opens."""
    got = _plan_idx(pid)
    if not got:
        return
    _p, st, doc, idx = got
    u = next((x for x in P.units(doc) if x["id"] == uid), None)
    if u is None:
        return
    try:
        cids = {c for c in idx.match(u, _swap(st), doc) if c in idx.leech and idx.cards[c][0] == -1}
    except Exception:
        oops()
        return
    _browse(cids, empty="No leeches in it now.")


# -- what Hold back keeps --

HELD_LINES = 8  # dates the Held back sheet names


def held_count(pid):
    """How many cards this plan holds shut here now that Open them would open
    (Hold back's, Put back's; a leech never opens): the plan's ··· menu says
    it, the same number as its sheet."""
    v = held_view(pid) if mw.col else None
    return int(v["n"]) if v else 0


def _held_now(st, doc, idx):
    """3.8.1: the cards the plan holds shut here now: in `held`, suspended, and
    on no date that opened here (a card I suspended myself after its date
    opened isn't the plan's to show or open)."""
    shut = {c for c in _shut_by_plan(st) if c in idx.cards and idx.cards[c][0] == -1}
    opened = {k for k, v in (st.get("applied") or {}).items() if not str(v).startswith("skip:")} | set(st.get("own_opened") or {})
    for u in P.units(doc):
        if u["id"] in opened and shut:
            shut -= idx.match(u, _swap(st), doc)
    return shut


def held_view(pid):
    """What the Held back sheet says: {name, n, lines, more, why, leeches,
    holding}: n and lines are what Open them opens, by date; leeches, the
    held ones that stay shut. Raw strings (the sheet shows them as plain
    text); None when the plan doesn't run here."""
    got = _plan_idx(pid)
    if not got:
        return None
    p, st, doc, idx = got
    shut = _held_now(st, doc, idx)
    held = shut - idx.leech
    own, holding = P.own_pace(p), _hold_yes(p, st)
    lines = []
    for name, opens, n in P.held_rows(idx, doc, held, _swap(st)):
        if name is None:
            lines.append(f"On no set now · {n:,}")
        else:
            lines.append(f"{name} · {n:,}" if own or not opens else f"{name} · {P.fmt_day(opens)} · {n:,}")
    if holding:
        why = ("You said yes to Hold back: the new cards of sets you haven't opened wait, suspended, till you open them."
               if own else "You said yes to Hold back: the new cards of sets still to come wait, suspended, till their day.")
    elif own:
        why = "You put these back. They open when you open their set again."
    else:
        why = "Hold back is off; these stayed suspended."
    return {"name": str(p.get("name") or "The plan"), "n": len(held), "lines": lines[:HELD_LINES],
            "more": max(0, len(lines) - HELD_LINES), "why": why, "holding": holding, "leeches": len(shut & idx.leech)}


def show_held(pid, ask=None):
    """The plan's ··· menu, Held back: N cards…: what it holds and why; Open
    them · Stop holding back · Close."""
    v = held_view(pid)
    if not v or not v["n"]:
        tooltip("Nothing held back now.")
        return
    if ask is None:
        from ..ui.held_dialog import ask_held
        ask = lambda view: ask_held(mw, view)  # noqa: E731
    choice = ask(v)
    if choice in ("open", "stop"):
        open_held(pid, stop=choice == "stop")


def open_held(pid, stop=False):
    """Open what the plan holds shut here, as one undo step (a leech stays
    shut). Hold back stays on for what an author adds later (the opened
    cards stay in `held`, so it never shuts them again); stop: and it's off
    (`hold_yes`)."""
    got = _plan_idx(pid)
    if not got:
        return
    p, st, doc, idx = got
    held = sorted(_held_now(st, doc, idx))
    name = p.get("name") or "plan"
    n = P.open_cards(mw.col, held, f"Due Crew: open what {name} held back") if held else 0
    if stop:
        _hold_yes(p, st)
        st["hold_yes"] = False
    pc = _pcfg()
    pc["plans"] = _state_cfg(pc)
    _psave(pc)
    if n:
        _after_change()
    refresh_progress()
    said = f"Opened {n:,} card{'s' if n != 1 else ''}. Edit › Undo suspends them again." if n else "Nothing to open."
    tooltip(said + (" Nothing more is held back." if stop else ""), period=5000)
    app.swap(cfg())


# -- Welcome back --

def _away(col, plan_list, state, today):
    """{plan id: {days, units, n}}: each plan on its dates (not at my own pace,
    not paused, not on a 3.2 schedule or even dates, which open in slices)
    whose morning would open dates from AWAY_DAYS or more days on which I
    studied nothing in Anki (no answer at all, any deck: the revlog after
    the day's sync, phone included). days: those days; units: every date
    the morning would open for it; n: their cards. Cheap when there's
    nothing to ask: the revlog (one query) and the deck are read only for
    a plan with that many days' dates waiting."""
    from ..stats.queries import StatsQueries
    out, studied = {}, None
    since = S.iso(S.d(today) - datetime.timedelta(days=P.AWAY_LOOK))
    for p in plan_list:
        q = mine(p)
        st = state.get(p["id"])
        if (p.get("paused") or P.own_pace(p) or p.get("sched") or not st or S.has_even(q["doc"])
                or not _deck_ok(col, st.get("deck_id"))):
            continue
        applied, later = st.get("applied") or {}, st.get("later") or {}
        waiting = {str(u.get("opens")) for u in P.units(q["doc"])
                   if since <= str(u.get("opens") or "") < today and applied.get(u["id"]) is None
                   and str(later.get(u["id"]) or "") <= today}
        if len(waiting) < P.AWAY_DAYS:
            continue
        if studied is None:
            sq = StatsQueries(col)
            studied = {sq.day_label(int(a)) for a in sq.studied_days_ago(P.AWAY_LOOK + 1)}
        if len(waiting - studied) < P.AWAY_DAYS:
            continue
        dry = run(col, [p], copy.deepcopy(state), today, dry=True)
        uids = list(dry["units"].get(p["id"]) or [])
        by = {u["id"]: u for u in P.units(q["doc"])}
        days = P.away_days([by[x] for x in uids if x in by], applied, today, studied, since)
        if len(days) >= P.AWAY_DAYS:
            out[p["id"]] = {"days": days, "units": uids, "n": int((dry["per"].get(p["id"]) or [[], 0])[1])}
    return out


def _put_away(plan_list, today):
    """The morning, before it opens: a plan Welcome back will ask about keeps
    what it would open shut till then (`later`, as Not today does), so it's
    never opened before the question; its question waits in `away`."""
    if not mw.col:
        return {}
    c = _pcfg()
    state = _state_cfg(c)
    try:
        away = _away(mw.col, plan_list, state, today)
    except Exception:
        oops()
        return {}
    for pid, info in away.items():
        ask_later(state[pid], info["units"], today)
        state[pid]["away"] = dict(info, day=today)
    if away:
        c["plans"] = state
        _psave(c)
    return away


def _release_away(st, today):
    """The question answered with Open or Push: its dates aren't kept back any more."""
    info = (st or {}).pop("away", None) or {}
    tomorrow = S.iso(S.d(today) + datetime.timedelta(days=1))
    later = (st or {}).get("later") or {}
    for uid in info.get("units") or []:
        if later.get(uid) == tomorrow:
            later.pop(uid)


def welcome_back(pids, ask=None):
    """Main thread, after the morning (on Decks): each plan _put_away kept
    back asks Welcome back: Open them · Push my dates back N days (N: the
    days I studied nothing; the follow's shift, one PATCH) · Not today
    (nothing opens; tomorrow morning asks again)."""
    for pid in pids:
        try:
            _welcome_one(pid, ask)
        except Exception:
            oops()


def _welcome_one(pid, ask=None):
    p = next((x for x in followed() if x["id"] == pid), None)
    c = _pcfg()
    state = _state_cfg(c)
    st = state.get(pid)
    info = (st or {}).get("away") or {}
    today = _today()
    if p is None or p.get("paused") or not mw.col or info.get("day") != today:
        return
    days = [str(x) for x in info.get("days") or []]
    choice = (ask or _ask_away)(str(p.get("name") or "The plan"), days, len(info.get("units") or []), int(info.get("n") or 0))
    if choice == "open":
        _release_away(st, today)
        c["plans"] = state
        _psave(c)
        _open_now([p])
        app.swap(cfg())
    elif choice == "push":
        n = len(days)
        shift = min(365, int((_raw(pid) or {}).get("shift") or 0) + n)
        cl, gen = client(), app.generation

        def done(res):
            if gen != app.generation:
                return
            if res is None:
                tooltip("Couldn't reach Due Crew. Check your connection. Tomorrow morning asks again.")
                app.swap(cfg())
                return
            pc = _pcfg()
            st2 = _state_cfg(pc).get(pid)
            if st2 is not None:
                _release_away(st2, today)
                _psave(pc)
            if not res.get("paused"):
                _open_now([x for x in followed() if x["id"] == pid], toast=False)  # what's due on my new days
            tooltip(f"Your dates moved {n} day{'s' if n != 1 else ''} later. The plan's stay put.", period=5000)
            app.swap(cfg())
        _bg(lambda: cl.set_days(pid, shift=shift), done)
    else:
        app.swap(cfg())  # Not today, or closed: nothing opens; tomorrow morning asks again


def _ask_away(name, days, n_dates, n_cards):
    from ..rooms import sev_on  # 3.8.1: Pip waves from its corner, as Settings › Pip says
    from ..ui.away_dialog import ask_away
    return ask_away(mw, name, days, n_dates, n_cards, sev=sev_on())
