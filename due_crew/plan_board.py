"""Plans, end to end: the clicks You › Plans has that plan_flow didn't.

- Behind… (planbehind:<plan id>): the board's sheet (sheets.ask_item, one
  of a few) titled "A day behind on <plan>". Slide N days is my follow's
  shift, N days more (the days I'm behind), one request, as Push my dates
  back… is; Fit it in is G5's catch-up (plan_flow.start_catch: Anki's
  today-only limit, each morning) over three days, and over a week when
  that's fewer a day (Catch up…'s five days stays on Due's and Insights'
  Catch up…); Skip what's left skips the lessons behind on my follow, one
  request (their cards stay as they are; the week has Undo skip). Not now
  does nothing. The words are plans.behind_sheet's.
- The empty tab's box (planfollowcode:<what was typed, encoded>): a plan's
  code, or its link (duecrew.com/p/CODE), into plan_flow's Follow.
- Make a plan, Plan the way there (planopennew[:<day>]): the new plan
  window (planner.web.open_new, finishing by my exam's day), or planner's
  New plan where that window isn't in this build.

Main thread; requests in the background through plan_flow's _bg. Nothing
new is sent: shift and skipped are the follow's own fields."""

import re
from urllib.parse import unquote

from . import plan_flow as F
from . import plans as P

_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def view(pid):
    """(plan, its path, what's behind, cards waiting from earlier days) for
    a plan I follow and run here, as its card has them; None when nothing's
    behind (or it isn't one: paused, at my own pace, no deck here)."""
    p = next((x for x in F.followed() if x["id"] == pid), None)
    st = F._state_cfg().get(pid)
    if p is None or not st or p.get("paused") or P.own_pace(p) or not F.mw.col or not F._deck_ok(F.mw.col, st.get("deck_id")):
        return None
    today = F._today()
    prog = (F._state.get("plan_progress") or {}).get(pid) or {}
    path = P.path(F._plan_doc(p), prog, today, applied=st.get("applied") or {}, shift=int(p.get("shift") or 0),
                  skipped=p.get("skipped") or (), moved=p.get("moved"), sched=bool(p.get("sched")))
    b = P.behind_of(path, today)
    if b is None:
        return None
    return p, path, b, P.waiting_new(p["doc"], prog, today)


def behind(pid):
    """Behind…: the sheet, then the way picked."""
    got = view(pid)
    if got is None:
        F.app.swap(F.cfg())  # it isn't behind any more: the card catches up
        return
    p, path, b, waiting = got
    sheet = P.behind_sheet(str(p.get("name") or "the plan"), b, path, waiting, shift=int(p.get("shift") or 0))
    ways = sheet["ways"]
    from . import sheets
    sheets.ask_item(sheet["title"], sheet["text"], [w["label"] for w in ways],
                    lambda i: _take(pid, ways[i]), yes=ways[0]["yes"],
                    notes=[w["note"] for w in ways], yes_each=[w["yes"] for w in ways], no_label="Not now")


def _take(pid, way):
    if way["key"] == "slide":
        slide(pid, int(way["days"]))
    elif way["key"] == "fit":
        F.start_catch(pid, int(way["days"]), int(way["extra"]))
    elif way["key"] == "skip":
        skip(pid, way["uids"])


def slide(pid, days):
    """My dates `days` later (the follow's shift), one request. What a
    shorter shift had made due stays open; nothing opens or shuts."""
    raw = F._raw(pid)
    if raw is None or days <= 0:
        return
    shift = min(365, int(raw.get("shift") or 0) + int(days))
    cl = F.client()

    def done(res):
        if res is None:
            F.tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        F.tooltip(f"Your dates moved {days} day{'s' if days != 1 else ''} later. The crew's stay put.")
        F.app.swap(F.cfg())

    F._bg(lambda: cl.set_days(pid, shift=shift), done)


def skip(pid, uids):
    """The lessons behind, skipped on my follow, one request: off what's
    behind, their cards as they are (a date that opened never closes)."""
    raw = F._raw(pid)
    uids = [u for u in uids or [] if isinstance(u, str) and u]
    if raw is None or not uids:
        return
    have = [u for u in raw.get("skipped") or [] if u not in uids]
    cl = F.client()

    def done(res):
        if res is None:
            F.tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        F.app.swap(F.cfg())

    F._bg(lambda: cl.set_days(pid, skipped=have + uids), done)


def follow(raw):
    """The empty tab's Follow: the code in what was typed (P.link_code),
    into Follow, which looks it up (and with nothing typed, opens to type one)."""
    F.open_follow(P.link_code(unquote(str(raw or ""))[:600]))


def open_new(day=""):
    """Make a plan, or Plan the way there (finishing by `day`, my exam's)."""
    finish = day if _DAY.fullmatch(str(day or "")) else None
    try:
        from .planner import web
        go = web.open_new
    except (ImportError, AttributeError):
        go = None
    if go is not None:
        go(start=None, finish_by=finish)
        return
    from .planner import flow
    flow.open_new()
