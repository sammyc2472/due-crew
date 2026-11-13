"""The glue: the Decks screen's draw: the board's HTML, its views, its scripts."""

import time

from aqt import mw
from aqt.utils import tooltip

from .. import ahead_flow
from .. import app
from .. import bingo_flow
from .. import board
from .. import due_flow
from .. import errs
from .. import errs_flow
from .. import gamenight_flow
from .. import magic_flow
from .. import plan_flow
from .. import rooms
from .. import sheets
from .. import together
from ..app import _state
from ..app import cfg
from ..app import client
from ..app import save_cfg
from ..errs import oops
from ..shares import review_banners
from ..social import _play_cheers
from ..squads import _fetch_squad
from ..squads import _squad_view
from ..squads import _visible_knocks
from ..ui import copy_text
from ..wrap import _arrivals
from ..wrap import _deck_deltas
from ..wrap import _exam_eve_info
from ..wrap import _wrap_data
from ..wrap import _wrap_info

from .refresh import _board_data, _morning_now, _push_if_stale, _run, refresh_board


def _board_off(c):
    """The board turned off in Settings, and none of the screens that show in
    its place open (Settings, the closet, Wrapped)."""
    return (not c.get("show_leaderboard", True) and not _state.get("settings_tab")
            and not _state.get("closet_open") and not _state.get("wrapped_open"))


def _closet(do):
    """3.8.2: tell Pip's closet (closet_flow); never in the way of the board."""
    try:
        from .. import closet_flow
        do(closet_flow)
    except Exception:
        oops()


def _closet_day(cf, today, entries):
    """At a refresh: the day's tallies, and anything newly earned."""
    rv = due_flow._reviews() or {}
    cf.note_day(today, entries, int(rv.get("done") or 0) > 0, rv.get("due"))
    cf.check(today)


def _rerender():
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()


def _deck_counts(content):
    """3.9.12 (deck_counts.py): the deck list's New and Due as what there is to do, behind its switch. One
    query a draw, on the main thread (the Decks screen's own draw); whatever goes wrong, Anki's list is as it was."""
    try:
        from .. import deck_counts
        if not cfg().get(deck_counts.SWITCH) or mw.col is None or not getattr(content, "tree", ""):
            return
        col = mw.col
        names = {int(d.id): d.name for d in col.decks.all_names_and_ids()}
        bury = {}
        for did in names:
            try:
                conf = col.decks.config_dict_for_deck_id(did)
                bury[did] = (bool((conf.get("new") or {}).get("bury")), bool((conf.get("rev") or {}).get("bury")))
            except Exception:
                bury[did] = (False, False)  # a filtered deck has no options of its own: as Anki counts it
        rows = col.db.all(deck_counts.QUERY, col.sched.today)
        content.tree = deck_counts.rewrite(content.tree, deck_counts.to_do(rows, bury, names))
    except Exception:
        oops()


def _on_render(deck_browser, content):
    _deck_counts(content)  # 3.9.12: Anki's own list without the siblings it will bury (Settings › Study; off by default)
    app.on_decks_render()
    content.stats += board.key_js()  # 3.9.1: the page's own scripts add the board's key to what they send
    try:
        c = cfg()
        if _state.get("settings_tab"):
            # 3.8.0: Settings shows whatever else is so (signed out, the board off)
            _state["board_shown"] = True
            content.stats += board.settings_html(_settings_view(), c)
            return
        if _state.get("closet_open"):
            _state["board_shown"] = True  # 3.8.2: Pip's closet, as Settings
            content.stats += board.closet_html(_closet_view(), c)
            return
        if _state.get("wrapped_open") and mw.col:
            _state["board_shown"] = True  # 3.9.10: the scrapbook (Wrapped's place, 3.9.0), as the closet
            content.stats += _scrap_html(c)
            return
        if not c.get("show_leaderboard", True):
            _state["board_shown"] = False
            return
        if not client().signed_in or client().session_dead:
            _state["board_shown"] = False
            content.stats += board.signed_out_card(c, expired=client().session_dead,
                                                   gone=client().deleted_quiet, sev=rooms.signed_out_sev())
        elif _state["entries"] is None:
            _state["board_shown"] = False
            content.stats += board.loading_card(c)
            refresh_board()
        else:
            _state["board_shown"] = True
            if magic_flow.on():
                # 3.9.9: under the deck list, over Anki's "Studied…" line
                # (3.9.9, Sam's screenshot: Anki puts content.tree inside its <table>, and a browser lifts a
                # div out of a table to above it; the start of content.stats is under the list, over "Studied…")
                content.stats = board.magic_field(c) + (content.stats or "")
            content.stats += _board_html(c)
            _push_if_stale()
    except Exception:
        oops()


def _bingo_view(c):
    sv = _squad_view(c)
    return bingo_flow.view(sv, c) if sv.get("state") == "ok" else None


def _squad_view_with_bingo(c):
    """The Squads tab's view, with this week's card when there is one (3.6).
    3.8.0: the plans' squads are pills too, and one of them may be picked."""
    from .. import team_flow
    sv = _squad_view(c)
    if c.get("period") != "squads":
        return sv  # only the Squads tab draws it; a plan's squad reads my collection for its card questions
    ps = team_flow.plan_squads()
    pv = team_flow.squad_view(c, ps)
    if pv:
        return dict(pv, squads=sv.get("squads") or [], plan_squads=ps)
    sv = dict(sv, plan_squads=ps)
    if sv.get("state") == "ok":
        bv = bingo_flow.view(sv, c)
        if bv:
            sv = dict(sv, bingo=bv)
            squares = (bv.get("ev") or {}).get("squares") or []
            _closet(lambda cf: cf.note_bingo(int((bv.get("ev") or {}).get("lines") or 0),
                                             bool(squares) and all(q.get("done") for q in squares),
                                             f'{(bv.get("card") or {}).get("wk")}:{bv.get("squad_id")}'))
            if bingo_flow.new_lines(bv):
                tooltip("BINGO! Your squad just made a line.", period=4000)
                _scrap(lambda sf: sf.moment("bingo", "Your squad made a bingo line", "", "cheer", (_state.get("labels") or [None])[0]))
    return sv


def _bingo_cmd(cmd):
    """3.6: open the card, go back, copy it for the group chat."""
    c = cfg()
    if cmd == "bingo":
        _state["bingo_open"] = True
        bingo_flow.seen()
        _swap(c)
        _fetch_squad()
    elif cmd == "bingoback":
        _state["bingo_open"] = False
        _swap(c)
    elif cmd == "bingocopy":
        bv = _bingo_view(c)
        if bv:
            from ..bingo import share_text
            copy_text(share_text(bv["card"], bv["ev"], bv["squad"]))
            tooltip("Copied.")


def _board_html(c):
    """The board from cache: one call for the first render and every swap."""
    from .. import closet_flow
    if _state.get("settings_tab"):
        return board.settings_html(_settings_view(), c)  # 3.5.0: Settings in its place
    if _state.get("closet_open"):
        return board.closet_html(_closet_view(), c)  # 3.8.2: Pip's closet in its place
    if _state.get("wrapped_open"):
        return _scrap_html(c)  # 3.9.10: the scrapbook in its place (Wrapped's, 3.9.0)
    if _state.get("team_bingo_open"):
        from .. import team_flow  # 3.7.3: a plan team's card in its place
        pid = _state["team_bingo_open"]
        tv = (_state.get("team_view") or {}).get(pid) or {}
        return board.bingo_html(team_flow.bingo_view(pid), c, loading=tv.get("state") == "fetching", team=True)
    if _state.get("bingo_open"):
        return board.bingo_html(_bingo_view(c), c,  # 3.6: the squad's card in its place
                                loading=_squad_view(c).get("state") == "loading" and bool(bingo_flow.card()),
                                people={e.get("user_id"): e for e in _state["entries"] or []})  # 3.8.22: stamps as Pips
    show_up = bool(c.get("show_up"))
    notice = _state.get("notice")
    if notice and notice["id"] in (_wrap_data().get("notices_dismissed") or []):
        notice = None
    due = due_flow.view(c)  # Due: the day's to-do, on top
    plans = plan_flow.board_view(c)  # 3.3: the plans I follow (3.8.0: You › Plans; offers on Squads too)
    _state["dance_view"] = _dance_view(c)  # 3.9.6: song of the moment's dance floor (seen once it's on the page)
    return board.render(_board_data(), c, _state["ts"], notice=notice,
                        wrap=_wrap_info(), deltas=_deck_deltas(),
                        exam_eve=_exam_eve_info(),
                        rules_stale=client().rules_stale,
                        squad_view=_squad_view_with_bingo(c), knocks=_visible_knocks(c),
                        reviews=review_banners(), sync_error=_state["sync_error"], offline=bool(_state.get("offline")),
                        live=together.is_live(),
                        tricky=together.tricky_view() if c.get("period") == "decks" else None,
                        asks=together.my_asks_view() if c.get("period") == "decks" else None,
                        milestones=None if show_up else _state["milestones"],
                        milestone_sev=None if show_up else rooms.milestone_sevs(_state["milestones"][:2]),
                        room=rooms.board_view(), plans=plans,
                        due=due, you=_you(c, due, plans), sticking=_sticking(c),
                        sev=rooms.board_sev(c, due), closet=_state.get("closet_new"),
                        halloween=closet_flow.halloween_view(_state["labels"][0] if _state["labels"] else "",
                                                             _state["entries"], c),
                        wrapped=_wrapped_banner(c), ahead=ahead_flow.board_line(c),
                        fridge=closet_flow.fridge(client().user_id),
                        fridge_gone=closet_flow.gone(), dance=_state["dance_view"])


def _dance_view(c):
    """3.9.6: the dance floor's view (song_flow.floor_view), or None; never in the way of the board."""
    try:
        from .. import song_flow
        return song_flow.floor_view(_state["entries"], c)
    except Exception:
        oops()
        return None


def _dance_seen():
    """3.9.6: the floor just drawn is on the page: what it showed is seen, so a new song hops in once."""
    view = _state.pop("dance_view", None)
    if view:
        try:
            from .. import song_flow
            song_flow.mark_seen(view)
        except Exception:
            oops()


def _calm_check(c, plans):
    """3.9.9, the calm board: the parts that now have something to show are
    let out, with the board's line. From what's at hand; never raises."""
    from .. import calm
    if not calm.on(c) or not calm.held(c):
        return
    try:
        entries = [e for e in (_state.get("entries") or []) if not e.get("me")]
        days = _state.get("calm_days")
        if (days is None or days[0] != errs.today()) and mw.col:
            first = mw.col.db.scalar("SELECT min(id) FROM revlog WHERE ease > 0")
            days = _state["calm_days"] = (errs.today(), None if not first else int((time.time() - int(first) / 1000) // 86400))
        facts = {"friends": len(entries), "squads": len(c.get("squads") or []),
                 "plans": len(plans or []) if isinstance(plans, (list, tuple)) else int(bool(plans)),
                 "days": days[1] if days else None}
        if calm.release(c, calm.ready(facts), news=True):
            save_cfg(c)
    except Exception:
        oops()


def _calm_cmd(c, parts):
    """The calm board's line and Show all."""
    from .. import calm
    cmd, arg = parts[1], parts[2] if len(parts) > 2 else ""
    if cmd == "calmall":
        calm.show_all(c)
        save_cfg(c)
        _swap(c)
    elif cmd == "calmx":
        if calm.seen(c):
            save_cfg(c)
        _swap(c)
    elif cmd == "calmopen":
        calm.seen(c, arg)
        save_cfg(c)
        if arg in ("squads", "decks"):
            _cmd_period(c, ["duecrew", "period", arg])
        else:
            due_flow.on_message("duetab", ["duecrew", "duetab", arg])


def _you(c, due, plans):
    """3.8.0, the You bubble over the board: its tab, folded or not, and the
    Plans or Insights it draws. Only the one on screen is worked out."""
    from .. import team_flow
    _calm_check(c, plans)
    hidden = board.hidden_tabs(c)
    you = {"tab": due_flow.you_tab(c), "folded": due_flow.folded(c, due), "plans": plans, "insights": None,
           "party_on": "party" not in hidden and gamenight_flow.shown()}  # 3.9.5: You › Pip Party, unless hidden in Settings
    if you["folded"]:
        return you
    keys = ((["today", "upcoming", "later"] if due else []) + [k for k, _l in board.YOU_MORE if k not in hidden]
            + ([board.PARTY_TAB[0]] if you["party_on"] else []))
    shown = you["tab"] if you["tab"] in keys else (keys[0] if keys else None)
    if shown:
        errs.used(shown if shown in ("plans", "insights", "party") else "due")  # 3.9.9: the tab on screen, once a day
    try:
        if shown == "plans":
            team_flow.plan_lines(plans.get("cards"))  # the next exam's cards at risk, a line a plan
            plan_flow.joy_claim(plans.get("cards"), c)  # 3.9.6: what's waiting to play on the plan shown plays now, once
            if not due and mw.col:
                you["opened"] = plan_flow.morning_opened()  # Due off: its Not today is here
        elif shown == "insights":
            you["insights"] = team_flow.you_view(c)
        elif shown == "party" and mw.col:
            you["party"] = gamenight_flow.tab_view(c)
    except Exception:
        oops()
    return you


def _sticking(c):
    """3.8.0, Crew › Decks: {name: deck id} of the decks I share, for their
    way to how they're sticking (You › Insights). Main thread."""
    if c.get("period") != "decks" or not mw.col:
        return None
    out = {}
    for did in c.get("shared_decks") or []:
        try:
            if mw.col.decks.get(int(did), default=False):
                out[str(mw.col.decks.name(int(did))).split("::")[-1]] = int(did)
        except Exception:
            continue
    return out


def _arrive_js():
    """3.8.0 (Board in Motion, 22): a friend arrives, said to the page once."""
    try:
        new = _arrivals(_state.get("entries"), client().user_id)
    except Exception:
        oops()
        return ""
    return "try{window.dcMotion&&dcMotion.arrive(%s);}catch(e){}" % board._json.dumps(new) if new else ""


# 3.9.1 (the efficiency run): the page the board's scripts last went to
# (app.pages). A page keeps them (motion.js, Due's add line, Find, the
# fridge's), and each loads once, so a swap on that page sends only what
# they do after a draw (it sent 77 KB of them at every click); a page drawn
# anew gets them all.
_SCRIPTS = {"page": None, "css": None, "html": None}  # 3.9.7: and the board stylesheet that page holds (board.swap_js)


def _board_js(drawn=False):
    """(keep_me_in_view_js, fridge_js) for this draw: with the scripts when
    the page was just drawn (drawn) or is another since they went. 3.9.6:
    fridge_js brings the dance floor's (dance_js) with it."""
    whole = drawn or _SCRIPTS["page"] != app.pages[0]
    _SCRIPTS["page"] = app.pages[0]
    if whole:
        _SCRIPTS["css"] = None  # 3.9.7: a page drawn anew holds no board stylesheet of its own (#dc-css) yet
    return board.keep_me_in_view_js(scripts=whole), board.fridge_js(scripts=whole)


def _on_did_render(deck_browser):
    keep, fridge = _board_js(drawn=True)
    mw.web.eval("window.dcBK=%s;" % board._json.dumps(board.BOARD_KEY)  # 3.9.1: as the page's own script set it
                + keep + _arrive_js() + fridge)  # 3.9.1: the doodles placed around the board, and draggable (3.9.6: and the dance floor)
    _dance_seen()
    _play_cheers()
    _joy_show()
    if _state.get("plans_midday") and not _run.closing:
        # 3.7.3: an update that came while reviewing waits for the Decks screen
        from aqt.qt import QTimer
        QTimer.singleShot(0, lambda: plan_flow.midday(plan_flow.followed()))
    waiting = _state.get("plans_morning")
    if waiting and not _run.closing:
        # 3.8.0: so does the morning (it came while reviewing, or before Decks first drew)
        from aqt.qt import QTimer
        QTimer.singleShot(0, lambda: _morning_now(waiting))
    together.show_luck_card()
    if not _run.closing:
        from aqt.qt import QTimer
        QTimer.singleShot(1500, ahead_flow.check)  # 3.9.2: once a day, the board's line when reviews climb
        from .. import habits_flow
        QTimer.singleShot(2500, habits_flow.check)  # 3.9.5: once a day, How you study (and the Fifteen at 35)
    sheets.redraw()  # 3.9.1: a question that was open goes back up on the page drawn anew
    rooms.refresh_widgets()
    if not _run.closing and not _state.get("wrapped_open"):
        from aqt.qt import QTimer
        QTimer.singleShot(900, _magic_howto)  # 3.9.7, round 2: Magic search's how-to, once a person


def _magic_howto():
    try:
        if not _run.closing and app.board_up():
            errs_flow.use_ready()
            magic_flow.show_board_howto()
    except Exception:
        oops()


def _last_studied(q, stats):
    """The most recent day label with answers in the last week: today when
    today has any, else the newest such day, else None. Main thread."""
    if int(stats.reviews or 0) > 0:
        return q.day_label(0)
    try:
        studied = [lb for lb, t in q.daily_totals(7).items() if t and t[0]]
    except Exception:
        oops()
        return None
    return max(studied) if studied else None


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_closet_view", "_cmd_period", "_joy_show", "_scrap", "_scrap_html", "_settings_view", "_swap",
          "_wrapped_banner", "k")
_closet_view = _cmd_period = _joy_show = _scrap = _scrap_html = _settings_view = None
_swap = _wrapped_banner = k = None
