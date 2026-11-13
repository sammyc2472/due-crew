"""Plans, the glue: the board's plan commands."""

import datetime
import html
import re

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from ..app import _bg
from ..app import _state
from ..app import cfg
from ..app import client
from ..app import save_cfg
from ..errs import oops

from .lessons import _lesson_prune, _undo_ok, browse_opened, raise_limit, refresh_progress
from .state import _pcfg, _psave, _today, followed
from .morning import _state_cfg, post_seen, study_date, study_day, study_quiz, update_later, update_open
from .cards import aside, line_off, line_study, put_off
from .joys import joy_share, joy_x


# ---- board commands ----

def exam_answer(pid, mine):
    """3.9.9 (Sam's pick B): the card's question about a plan's exam,
    answered. Make it mine sets my exam to it (Settings' own setexam: the
    one before is kept as my last, as ever) and remembers which plan it came
    from, so a move asks again; Not now only remembers it was asked. Either
    way it isn't asked again about that day. Main thread."""
    c = cfg()
    today = _state["labels"][0] if _state["labels"] else ""
    ask = P.exam_offer(followed(), c.get("exam_date"), today, c.get("exam_asked"), c.get("exam_from"))
    if not ask or ask["pid"] != str(pid):
        return  # answered already, or the plan moved on
    c = dict(c)
    c["exam_asked"] = dict(P.clean_exam_asked(c.get("exam_asked")), **{ask["pid"]: ask["day"]})
    if mine:
        from ..settings_model import change
        try:
            changed = change(["setexam", ask["day"]], c, today=datetime.date.fromisoformat(today) if today else None)
        except ValueError:
            changed = None
        c.update(changed or {})
        c["exam_from"] = {"pid": ask["pid"], "day": ask["day"]}
    save_cfg(c)
    if mine:
        tooltip(f"Your exam: {P.fmt_day(ask['day'])}.")
    if app.swap:
        app.swap(c)


def on_message(cmd, parts):
    """duecrew:plan* from the board. True when handled."""
    if cmd.startswith("planteam"):
        from .. import team_flow  # 3.7.3: the plan's squad
        return team_flow.on_message(cmd, parts)
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "planundo":
        undo_morning()
    elif cmd == "plannottoday":
        undo_morning(put_off_too=True)
    elif cmd == "plansync":
        try:
            mw.on_sync_button_clicked()  # Anki's own Sync, as its top bar's button
        except Exception:
            oops()
    elif cmd == "plannow" and arg and len(parts) > 3:
        open_date(arg, parts[3])
    elif cmd == "planbrowse" and arg and len(parts) > 3:
        browse_date(arg, parts[3])
    elif cmd == "planleft" and arg:
        browse_left(arg, [x for x in (parts[3] if len(parts) > 3 else "").split("-") if x])
    elif cmd == "plantopic" and arg and len(parts) > 4:
        browse_topic(arg, [x for x in parts[3].split("-") if x], int(parts[4]) if parts[4].isdigit() else -1)
    elif cmd == "plantopicstudy" and arg and len(parts) > 4:  # 3.9.5: a topic on Today, as a deck of its own
        study_topic(arg, [x for x in parts[3].split("-") if x], int(parts[4]) if parts[4].isdigit() else -1)
    elif cmd == "planputback" and arg:
        open_put_off(arg)
    elif cmd == "planmove" and arg and len(parts) > 3:
        move_menu(arg, parts[3])
    elif cmd == "planmoveback" and arg and len(parts) > 3:
        move_date(arg, parts[3], 0)
    elif cmd == "planmoveto" and arg and len(parts) > 4 and parts[4].isdigit():  # 3.9.9: the load view's Move
        load_move(arg, parts[3], int(parts[4]))
    elif cmd == "planreset" and arg:
        reset_days(arg)
    elif cmd == "planskip" and arg and len(parts) > 3:
        set_skip(arg, parts[3], True)
    elif cmd == "planunskip" and arg and len(parts) > 3:
        set_skip(arg, parts[3], False)
    elif cmd == "plancatch" and arg:  # Due's Catch up…: Behind's sheet, as You › Plans has it; the old menu only where that has nothing
        from .. import plan_board
        if plan_board.view(arg) is not None:
            plan_board.behind(arg)
        else:
            catch_menu(arg)
    elif cmd == "planstudyday" and arg and len(parts) > 3:  # 3.9.6: a day's Study in You › Plans' week
        study_day(arg, parts[3])
    elif cmd == "planlinestudy" and arg and len(parts) > 3:  # 3.9.10: catching up: a row's Study
        line_study(arg, parts[3])
    elif cmd == "planlineoff" and arg:
        line_off(arg)
    elif cmd == "planbehind" and arg:  # plans, end to end: You › Plans' Behind…, the sheet
        from .. import plan_board
        plan_board.behind(arg)
    elif cmd == "planexam" and arg in ("yes", "no") and len(parts) > 3:  # 3.9.9: a plan's exam, mine or not now
        exam_answer(parts[3], arg == "yes")
    elif cmd == "planunslide" and arg:  # ...the card's Undo after Slide, the same day
        from .. import plan_board
        plan_board.unslide(arg)
    elif cmd == "planfollowcode":  # ...the empty tab's box: a plan's code or its link, into Follow
        from .. import plan_board
        plan_board.follow(arg)
    elif cmd == "planopennew":  # ...Make a plan; Plan the way there, finishing by my exam's day
        from .. import plan_board
        plan_board.open_new(arg)
    elif cmd == "plancatchstop" and arg:
        stop_catch(arg)
    elif cmd == "planjoyx" and arg and len(parts) > 3:  # 3.9.6: × on a milestone's line
        joy_x(arg, parts[3])
    elif cmd == "planjoyshare" and arg and len(parts) > 3:  # 3.9.6: Share on a joy's line, or the finish's banner
        joy_share(arg, parts[3])
    elif cmd == "planjump" and arg and len(parts) > 3 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[3]):
        # 3.9.6, after the last check: a set's segment on the path: its day's details, in its week
        if any(p.get("id") == arg for p in followed()):
            jump_to(arg, parts[3])
    elif cmd == "planweek" and arg and len(parts) > 3:
        # 3.5.0: the Plans tab's week, back and on (0: this week again); not saved
        weeks = _state.setdefault("plan_week", {})
        _state.pop("plan_focus", None)  # moving on lets go of a jumped-to day
        step = parts[3]
        weeks[arg] = 0 if step == "0" else max(-26, min(26, int(weeks.get(arg, 0)) + (1 if step == "next" else -1)))
        app.swap(cfg())
    elif cmd == "planpick" and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", arg or ""):
        # round five, pick 3: the plan You › Plans shows, with two or more (this computer's)
        c = cfg()
        c["plan_pick"] = arg
        _state.pop("plan_focus", None)  # another plan lets go of a jumped-to day
        save_cfg(c)
        app.swap(c)
    elif cmd == "planshift" and arg:
        set_shift(arg)
    elif cmd == "plansite" and arg and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", arg):
        open_site(f"/plans/{arg}")  # an id, nothing else: the link carries a sign-in token
    elif cmd == "planlibrary":
        open_site("/library")
    elif cmd == "planmake":
        _planner_flow().open_new()  # round five: one New plan
    elif cmd == "planyours":  # 3.9.3: Your plans, on a plan when the click names one
        open_yours(arg if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", arg or "") else None)
    elif cmd == "plannew":  # 3.9.3: You › Plans' New plan ▾
        new_plan_menu()
    elif cmd == "planstart":  # 3.9.3: New plan from a calendar (round five: the one New plan)
        _planner_flow().open_new()
    elif cmd == "planresume" and arg:
        p = next((x for x in followed() if x["id"] == arg), None)
        if p:
            back(arg) if p.get("since") else set_paused(arg, False)
    elif cmd == "planmenu" and arg:
        plan_menu(arg)
    elif cmd == "planpaceopen" and arg:  # 3.8.0, at my own pace: Open, Open and study, Undo, Put back
        if len(parts) > 3 and parts[3]:
            open_next(arg, uid=parts[3])  # 3.8.1: a date after "Then", opened ahead of the rest
        else:
            open_next(arg)
    elif cmd == "planopened" and arg and len(parts) > 3:  # 3.8.1: a date on the morning's line
        browse_opened(arg, parts[3])
    elif cmd == "planleech" and arg and len(parts) > 3:  # 3.8.1: a date's leeches, which stay shut
        browse_leeches(arg, parts[3])
    elif cmd == "planpacestudy" and arg:
        open_next(arg, study=True)
    elif cmd == "planpaceundo" and arg:
        own_undo(arg)
    elif cmd == "planpaceback" and arg:
        put_back_own(arg)
    elif cmd == "plantags" and arg:  # 3.8.0: the plan's tags, in Browse
        browse_tags(arg)
    elif cmd == "plantagsok" and arg:
        tags_seen(arg)
    elif cmd == "planok" and arg:
        seen_change(arg)
    elif cmd == "planupdopen" and arg:   # 3.7.3: an update's Open
        update_open(arg)
    elif cmd == "planupdlater" and arg:  # 3.7.3: an update's Not today
        update_later(arg)
    elif cmd == "planpostok" and arg:    # 3.7.3: the authors' post, read
        post_seen(arg)
    elif cmd == "plandeck" and arg:
        change_deck(arg)
    elif cmd == "planlook" and arg:
        offer = next((o for o in client().session.get("plan_offers") or [] if o.get("id") == arg), None)
        if offer:
            open_follow(code=offer.get("code") or "")
    elif cmd == "planstudy" and arg:
        study(arg)
    elif cmd == "plansched" and arg:
        open_schedule(arg)
    elif cmd == "planlimit" and arg:
        raise_limit(arg)
    elif cmd == "planstudydate" and arg and len(parts) > 3:
        study_date(arg, parts[3])
    elif cmd == "planquiz" and arg and len(parts) > 3:  # 3.8.1: Study for a quiz
        study_quiz(arg, parts[3])
    elif cmd == "planasideok" and arg:
        st = _state_cfg().get(arg)
        p = next((x for x in followed() if x.get("id") == arg), None)
        if st and p:
            pc = _pcfg()
            pc.setdefault("aside_ok", {})[arg] = aside(p, st)[:2]
            _psave(pc)
            app.swap(cfg())
    elif cmd == "planidsok" and arg:
        pc = _pcfg()
        pc.setdefault("fallback_ok", {})[arg] = True
        _psave(pc)
        app.swap(cfg())
    elif cmd == "planspread" and arg:
        set_catch(arg, "spread")
    elif cmd == "planleave" and arg:
        set_catch(arg, "leave")
    elif cmd == "planpush" and arg:
        push_back(arg)
    elif cmd == "planofferx" and arg:
        pc = _pcfg()
        pc["plan_offers_dismissed"] = (list(pc.get("plan_offers_dismissed") or []) + [arg])[-50:]
        _psave(pc)
        app.swap(cfg())
    elif cmd == "planinvite" and arg and len(parts) > 3 and parts[3] in ("yes", "no"):
        answer_invite(arg, parts[3] == "yes")  # 3.8.1: co-write it, or keep it
    else:
        return False
    return True


def answer_invite(pid, yes):
    """3.8.1: Yes or No to an invite on the board (to co-write a plan, or to
    keep one its owner hands me): one request, on the click. A yes makes me
    one of its authors: Browse's items at once, its tags on my notes when the
    plan next arrives (the refresh's stamp moved with the answer)."""
    cl = client()
    inv = next((x for x in cl.session.get("plan_invites") or [] if x.get("id") == pid), None)
    if inv is None or not cl.signed_in:
        return
    gen = app.generation

    def done(res):
        if gen != app.generation:
            return  # another profile or account since
        _got, status = res if res else (None, 0)
        name = html.escape(inv.get("name") or "the plan")
        if status == 404:
            tooltip(f"That invite to {name} was taken back.")
        elif status != 200:
            tooltip("Couldn't reach Due Crew. Check your connection." if not status else "That didn't go through. Try again later.")
        elif yes:
            tooltip(f"{name} is yours now." if inv.get("kind") == "owner" else f"You co-write {name} now.")
        app.swap(cfg())

    _bg(lambda: cl.answer_plan_invite(pid, yes), done)


def undo_morning(put_off_too=False):
    """The board's Undo: Anki's own undo, only while the step is its latest.
    The card and the numbers follow once the undo has happened, and only
    if it did. G2, Not today (put_off_too): the dates it opened open again
    on tomorrow's morning."""
    opened = _pcfg().get("plans_opened") or {}
    if not _undo_ok(opened.get("label")):
        tooltip("Anki has done something since. Use Edit › Undo.")
        app.swap(cfg())
        return

    def done(_out=None):
        # Undo: the units stay marked as applied, the next morning won't open them again;
        # Not today: they open on tomorrow's. A date opened in slices (an even
        # date, a 3.2 schedule) has no "won't open again": its next morning
        # opens what its schedule says is due, so plain Undo leaves it to that
        # (3.7.2; before, a window's last day stayed applied and its cards shut)
        pc = _pcfg()
        state = _state_cfg(pc)
        if put_off_too:
            for pid, uids in (opened.get("units") or {}).items():
                if pid in state:
                    # 3.8.1: at my own pace, each date back as it was (`was`)
                    put_off(state[pid], uids, _today(), was=(opened.get("was") or {}).get(pid))
        else:
            for pid, uids in (opened.get("spread") or {}).items():
                for uid in uids if pid in state else ():
                    (state[pid].get("applied") or {}).pop(uid, None)
                    (state[pid].get("src") or {}).pop(uid, None)
        if mw.col:
            _lesson_prune(mw.col, state)  # Today's lesson, B: the undo took the decks it built
        pc["plans"] = state
        pc["plans_opened"] = {}
        _psave(pc)
        try:
            mw.update_undo_actions()
        except Exception:
            pass
        refresh_progress()
        app.swap(cfg())

    try:
        from aqt.operations import CollectionOp
    except ImportError:
        CollectionOp = None
    if CollectionOp is not None:
        CollectionOp(mw, lambda col: col.undo()).success(done).run_in_background()
        return
    try:
        mw.undo()  # an Anki without CollectionOp: undo runs here, now
    except Exception:
        oops()
        return
    done()


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_planner_flow", "back", "browse_date", "browse_leeches", "browse_left", "browse_tags",
          "browse_topic", "catch_menu", "change_deck", "jump_to", "load_move", "move_date", "move_menu",
          "new_plan_menu", "open_date", "open_follow", "open_next", "open_put_off", "open_schedule",
          "open_site", "open_yours", "own_undo", "plan_menu", "push_back", "put_back_own", "reset_days",
          "seen_change", "set_catch", "set_paused", "set_shift", "set_skip", "stop_catch", "study",
          "study_topic", "tags_seen")
_planner_flow = back = browse_date = browse_leeches = browse_left = browse_tags = None
browse_topic = catch_menu = change_deck = jump_to = load_move = move_date = None
move_menu = new_plan_menu = open_date = open_follow = open_next = open_put_off = None
open_schedule = open_site = open_yours = own_undo = plan_menu = push_back = None
put_back_own = reset_days = seen_change = set_catch = set_paused = set_shift = None
set_skip = stop_catch = study = study_topic = tags_seen = None
