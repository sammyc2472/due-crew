"""The board drawn whole (render), the You bubble (you_html), its banners and menus, the signed-out and
loading cards.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
import time

from ..logo import board_mark
from .. import sev as _sev

from .base import PARTY_TAB, PERIODS, YOU_MORE, _ago_secs, _by_theme, _fmt_time, _pycmd, hidden_tabs
from .style import _css
from .pip import HW_CSS, SEV_CSS, halloween_html, my_look
from .crew import _crew_picker, _decks_html, _head, _table_html
from .insights import _you_insights, ahead_line
from .plancards import _offer_banners, _you_plans
from .party import party_html
from .due import DUE_CSS, _due_html
from .dance import dance_html
from .fridge import fridge_html
from .squads import _squads_html
from .closet import CLOSET_CSS, closet_line
from .wrapped import wrapped_line
from .lobby import room_html


def notice_html(notice):
    """3.2.1: the admin's notice, one line on top of the board: the text,
    More when it has a link, and a dismiss. Escaped; the link never goes in
    the page (Python opens it)."""
    nid = int(notice.get("id") or 0)
    more = (f'<a class="wc" href="#" title="Opens in your browser" onclick="{_pycmd("noticeopen")}">More</a>'
            if notice.get("link") else "")
    return (f'<div class="dc-wrap notice"><span>&#128227;</span>'
            f'<span>{_html.escape(str(notice.get("text") or ""))}</span>{more}'
            f'<a class="wx" href="#" title="Dismiss" onclick="{_pycmd(f"noticex:{nid}")}">&times;</a></div>')


def _clock(ts, now=None):
    """3.9.9: when a refresh last got through, as a person says it: "3:10 PM"
    today, "Fri 3:10 PM" this past week, "2 Nov" before that; "" for never."""
    if not ts:
        return ""
    import datetime as _dt
    t, n = time.localtime(ts), time.localtime(now if now is not None else time.time())
    hm = f"{(t.tm_hour % 12) or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}"
    day = _dt.date(t.tm_year, t.tm_mon, t.tm_mday)
    back = (_dt.date(n.tm_year, n.tm_mon, n.tm_mday) - day).days
    if back <= 0:
        return hm
    if back < 7:
        return f"{day.strftime('%a')} {hm}"
    return f"{day.day} {day.strftime('%b')}"


def offline_html(fetched_at, now=None):
    """3.9.9 (Off the Board, 11, Sam's pick): Due Crew couldn't be reached
    (no network, or the server away), said plainly on top of every tab where
    the foot's "Couldn't sync" was the only word. What I study still counts:
    the next sync reads it from Anki. Try now is Refresh."""
    when = _clock(fetched_at, now)
    last = f" Last refresh {when}." if when else ""
    return (f'<div class="dc-wrap off" role="status"><span>&#9888;&#65039;</span>'
            f'<span>Can&rsquo;t reach Due Crew. Your studying still counts and sends when it&rsquo;s back.{last}</span>'
            f'<a class="wc" href="#" onclick="{_pycmd("refresh")}">Try now</a></div>')


def _review_banner(kind, info):
    """Personal month or year review, above the board. Local numbers only."""
    r = info["review"]
    if kind == "month":
        icon, title = "&#128197;", f'Your {_html.escape(str(info["name"]))}:'
        cmd_copy, cmd_x = "monthcopy", "monthdismiss"
    else:
        icon, title = "&#127881;", f'Your {_html.escape(str(info["key"]))}:'
        cmd_copy, cmd_x = "yearcopy", "yeardismiss"
    bits = [f'{int(r["reviews"]):,} reviews', _fmt_time(int(r["time_ms"] or 0)),
            f'{int(r["days"])} of {int(r["span"])} days']
    if kind == "month" and r.get("best_day"):
        bits.append(f'best day {int(r["best_day"][1]):,}')
    if kind == "year" and int(r.get("longest_run") or 0) > 1:
        bits.append(f'&#128293; {int(r["longest_run"])}-day run')
    return (f'<div class="dc-wrap"><span>{icon}</span>'
            f'<span><b>{title}</b> {" &middot; ".join(bits)}</span>'
            f'<a class="wc" href="#" title="Copy for the chat" '
            f'onclick="{_pycmd(cmd_copy)}">Copy</a>'
            f'<a class="wx" href="#" title="Dismiss" '
            f'onclick="{_pycmd(cmd_x)}">&times;</a></div>')


def crew_menu_items():
    """The footer's Crew menu (3.4 review, H5; 3.7.1, H3): people only, the
    same on every tab. What you post went to Share."""
    return [("Friends…", "friends"), ("Copy invite", "copyinvite"),
            ("Shared decks…", "decks")]


def share_menu_items(show_up, squad_ok=False):
    """The footer's Share menu (3.7.1, H3), as [(label, command)], a label of
    None being a heading: as text first, then as a picture, the same on
    every tab. Today's numbers aren't offered in just-show-up mode."""
    items = [(None, "As text")]
    if not show_up:
        items.append(("My day", "sharetoday"))
    items.append(("Our week", "sharecrewweek"))
    if squad_ok and not show_up:
        items.append(("The squad's day", "squadshare"))
    items.append((None, "As a picture"))
    if not show_up:
        items.append(("My day…", "picturetoday"))
    items += [("My week…", "pictureweek"), ("My year…", "pictureyear"),
              ("All time…", "picturealltime")]
    return items


def _split_wraps(html):
    """The banners in a run of them, one string each."""
    out, i = [], 0
    while True:
        j = html.find('<div class="dc-wrap', i)
        if j < 0:
            return out
        k = html.find('<div class="dc-wrap', j + 1)
        out.append(html[j:k if k >= 0 else len(html)])
        if k < 0:
            return out
        i = k


def _one_at_a_time(bans):
    """3.4 review, H6: the first banner shows; "1 of N ›" steps to the next
    (in the page, no request). Dismissing one still goes through Python."""
    bans = [b for b in bans if b]
    if len(bans) < 2:
        return "".join(bans)
    out = []
    step = ("var w=this.closest('.dc-wrap'),n=w.nextElementSibling||w.parentNode.firstElementChild;"
            "w.hidden=true;n.hidden=false;return false;")
    for i, b in enumerate(bans):
        more = f'<a class="wn" href="#" title="The next one" onclick="{step}">{i + 1} of {len(bans)} &rsaquo;</a>'
        cut = b.rfind('<a class="wx"')
        if cut < 0:
            cut = b.rfind("</div>")
        b = b[:cut] + more + b[cut:]
        if i:
            b = b.replace('<div class="dc-wrap', '<div hidden class="dc-wrap', 1)
        out.append(b)
    return f'<div class="dc-bans">{"".join(out)}</div>'


def render(data, cfg, fetched_at, wrap=None, deltas=None, exam_eve=None,
           rules_stale=False, squad_view=None, knocks=None, reviews=None,
           sync_error=False, live=False, tricky=None, milestones=None, room=None, plans=None,
           notice=None, asks=None, due=None, you=None, sticking=None, sev=None, milestone_sev=None, closet=None,
           halloween=None, wrapped=None, fridge=None, fridge_gone=None, ahead=None, dance=None, offline=False):
    """3.8.0: two parts, apart. On top the You bubble (you_html): due,
    Due's view (due_flow.view, None when Due is off), and you, its Plans and
    Insights ({tab, folded, plans, insights}; None draws Due alone). Under it
    the board, your people: Crew (Today, Week, Decks) and Squads.
    sticking: {deck name: deck id} of my decks Insights has, for Decks' links.
    live: I'm studying now (the footer offers to stop). tricky: flagged
    cards I share with a crewmate (Crew › Decks). milestones: [(uid, name,
    days)] for a crewmate's 100- or 365-day streak, with a one-tap cheer.
    room (2.12): {"mine": lobby or None, "invites": [...], "done": ...};
    see room_html. plans (3.1): {cards, offers} from plan_flow.board_view
    (the cards are You › Plans'; a squad's offers show on Squads too).
    notice (3.2.1): the admin's {id, text, link}, on top of every tab.
    asks (3.5.0): my own asks about cards (together.my_asks_view), Crew › Decks.
    sev (3.8.1): Pip beside the logo for a moment, {svg, ago} (rooms.board_sev), or None.
    milestone_sev (3.8.1): {uid: Pip's markup} for a streak banner, Pip in its emoji's place.
    closet (3.8.2): {keys, first}: what just came for Pip, for its line (closet_line).
    halloween (3.8.22): Halloween week's line, its bats and cobweb (halloween_html), or None.
    wrapped (3.9.0): {year, so_far, look} for the line that your year is ready (1 Dec to 15 Jan), or None.
    fridge (3.9.1): the doodles my crew sent (fridge.clean's), pinned around the Decks screen (fridge_html);
    fridge_gone: the one just taken down, for its Undo (closet_flow.gone).
    ahead (3.9.2): {did, name, day, n, week} when reviews in my most reviewed deck climb (ahead_line).
    dance (3.9.6): song of the moment's dance floor (song_flow.floor_view), for the Decks screen's corner (dance_html).
    offline (3.9.9): the last refresh couldn't reach Due Crew; a line on top of every tab (offline_html)."""
    period = cfg.get("period", "today")
    hidden = hidden_tabs(cfg)
    if period not in PERIODS or period in hidden:
        period = "today"  # a saved Plans (before 3.8.0) or a hidden view: Crew's Today
    show_up = bool(cfg.get("show_up"))
    pick = "" if period == "squads" else _crew_picker(period, show_up, hidden)
    body = (_decks_html(data, deltas, tricky, None, asks, sticking, pick) if period == "decks"
            else _squads_html(squad_view or {"state": "none"}, cfg,
                              {e.get("user_id"): e for e in data.get("entries") or [] if not e.get("you")})
            if period == "squads"
            else _table_html(data, cfg, period, pick))
    # 3.4 review, H6: one banner at a time, the most time-bound first; the
    # rest wait behind "1 of N ›". The admin's notice and my own room stay.
    bans = []
    if exam_eve and exam_eve.get("people"):
        # 2.10: a line for their exam-morning card, rather than a cheer now
        links = [f'<a class="dc-pl" href="#" title="Add a line to their good-luck card" '
                 f'onclick="{_pycmd("luckline:" + str(u))}">'
                 f'<b>{_html.escape(str(n))}</b></a>'
                 for u, n in exam_eve["people"]]
        if len(links) == 1:
            uid = exam_eve["people"][0][0]
            line = f'{links[0]}&rsquo;s exam is tomorrow.'
            act = (f'<a class="wc" href="#" title="They see it when they open Anki that morning" '
                   f'onclick="{_pycmd("luckline:" + str(uid))}">&#127808; Add a line to their card</a>')
        else:
            line = " and ".join(links) + " have exams tomorrow."
            act = ""
        bans.append(f'<div class="dc-wrap eve"><span>&#128214;</span>'
                    f'<span>{line}</span>{act}'
                    f'<a class="wx" href="#" title="Dismiss" '
                    f'onclick="{_pycmd("evedismiss")}">&times;</a></div>')
    for k in (knocks or [])[:3]:
        # someone in a squad added me: my add makes it mutual
        who = _html.escape(str(k.get("name", "?")))
        # a squadmate's add names the squad; an add by code (2.9) says so
        where = (f' from {_html.escape(str(k["squad"]))}' if k.get("squad")
                 else " your code" if k.get("via_code") else "")
        uid = str(k.get("uid", ""))
        bans.append(f'<div class="dc-wrap knock"><span>&#128075;</span>'
                    f'<span><b>{who}</b> added{"" if k.get("via_code") and not k.get("squad") else " you"}{where}</span>'
                    f'<a class="wc" href="#" title="Add back" '
                    f'onclick="{_pycmd("addback:" + uid)}">Add back</a>'
                    f'<a class="wx" href="#" title="Not now" '
                    f'onclick="{_pycmd("knockmute:" + uid)}">&times;</a></div>')
    for uid, who, days in (milestones or [])[:2]:
        emoji = "&#128175;" if int(days) < 365 else "&#127881;"
        fig = (milestone_sev or {}).get(uid)  # 3.8.1 (Sam's pick): Pip hops in the emoji's place
        icon = f'<span class="dc-fig">{_sev.slot(fig, 40)}</span>' if fig else f"<span>{emoji}</span>"
        bans.append(f'<div class="dc-wrap">{icon}'
                    f'<span><b>{_html.escape(str(who))}</b> just reached a {int(days)}-day streak.</span>'
                    f'<a class="wc" href="#" title="Send a cheer" '
                    f'onclick="{_pycmd("milestonecheer:" + str(uid))}">Send {emoji}</a>'
                    f'<a class="wx" href="#" title="Dismiss" '
                    f'onclick="{_pycmd("milestonex:" + str(uid))}">&times;</a></div>')
    if ahead and ahead.get("did"):
        bans.append(ahead_line(ahead))
    if wrapped and wrapped.get("year"):
        bans.append(wrapped_line(wrapped["year"], wrapped.get("so_far"), wrapped.get("look") or [], cfg.get("sev", True)))
    if closet and closet.get("keys") and cfg.get("sev", True):
        line = closet_line(closet["keys"], my_look(cfg), bool(closet.get("first")))
        if line:
            bans.append(line)
    lobby = ""
    if room and period in ("today", "week"):
        bans += [b for b in _split_wraps(room_html({"done": room.get("done"), "invites": room.get("invites"),
                                                     "fifteen_done": room.get("fifteen_done")}))]
        lobby = room_html({"mine": room.get("mine")})
    if wrap and not show_up:  # the week's totals are numbers
        extra = ""
        if (wrap.get("full_days") or 0) >= 3:
            extra = f' &middot; everyone showed up {wrap["full_days"]} of 7 days'
        if wrap.get("best_name"):
            extra += (f' &middot; {_html.escape(str(wrap["best_name"]))}&rsquo;s '
                      f'best week yet')
        if 0 < int(wrap.get("days_known") or 7) < 7:
            extra += f' &middot; from {int(wrap["days_known"])} of its 7 days'
        if wrap.get("milestone"):
            extra += (f' &middot; and the crew just passed '
                      f'<b>{_html.escape(str(wrap["milestone"]))} all-time</b>')
        bans.append(f'<div class="dc-wrap"><span>&#127881;</span>'
                    f'<span><b>Last week, together:</b> '
                    f'{wrap["reviews"]:,} reviews &middot; {_fmt_time(wrap["time_ms"])}{extra}</span>'
                    f'<a class="wc" href="#" title="Copy for the group chat" '
                    f'onclick="{_pycmd("wrapcopy")}">Copy</a>'
                    f'<a class="wx" href="#" title="Dismiss" '
                    f'onclick="{_pycmd("wrapdismiss")}">&times;</a></div>')
    for kind in ("month", "year"):
        if reviews and reviews.get(kind):
            bans.append(_review_banner(kind, reviews[kind]))
    if period == "squads":
        bans += _split_wraps(_offer_banners((plans or {}).get("offers")))  # and on You's Plans
    body = ((offline_html(fetched_at) if offline else "") + (notice_html(notice) if notice else "")
            + _one_at_a_time(bans) + lobby + body)

    # 3.4 review, H5: the day's two social actions as buttons, the rest in
    # one Crew menu, and Refresh and Settings as quiet icons
    left = ""
    if rules_stale:
        left += ('<span class="warn" title="The server is behind this version; '
                 'some sharing is paused until it catches up.">'
                 '&#9888; server catching up</span>')
    if period in ("today", "week") and not cfg.get("paused"):
        # 2.10: a dot by your name for an hour, so friends can join you
        left += (f'<a class="pb on" href="#" title="Stop showing that you\'re studying" '
                 f'onclick="{_pycmd("live")}">Stop studying</a>' if live else
                 f'<a class="pb on" href="#" title="A dot by your name for the next hour" '
                 f'onclick="{_pycmd("live")}">I&rsquo;m studying</a>')
        if not (room or {}).get("mine"):
            # 2.12: a study room for the crew
            left += (f'<a href="#" title="Rounds and breaks with your crew" '
                     f'onclick="{_pycmd("roomopen")}">Open a room</a>')  # 3.8.0: one pill in the footer
    left += (f'<a href="#" title="Friends" '
             f'onclick="{_pycmd("crewmenu")}">Crew</a>'  # 3.8.0 (Sam): no caret
             f'<a href="#" title="As text or a picture" '
             f'onclick="{_pycmd("sharemenu")}">Share</a>')
    n_pending = len(data.get("pending", []))
    if n_pending:
        left += (f'<a class="warn" href="#" title="You added them; you\'re crew when they add you back" '
                 f'onclick="{_pycmd("friends")}">{n_pending} waiting</a>')

    ago, _tone = _ago_secs(max(0.0, time.time() - fetched_at)) if fetched_at else ("just now", "")
    failed = ('<span class="warn" title="The last sync didn\'t reach the server. '
              'Your numbers are safe; Refresh tries again.">Couldn&rsquo;t sync</span>'
              ' &middot; ') if sync_error else ""
    foot = (f'<div class="dc-foot"><span class="fl">{left}</span><span class="sp"></span>'
            f'<span class="fr">{failed}<span class="upd">Updated {ago}</span>'
            f'<a class="ic" href="#" title="Refresh" onclick="{_pycmd("refresh")}">&#8635;</a>'
            f'<a class="ic" href="#" title="Settings" onclick="{_pycmd("settings")}">&#9881;&#xFE0E;</a></span></div>')

    # 3.8.1: Pip's moments; a crew room's Pips each wear their person's accent, by day or by night as the board
    seat = _by_theme(cfg, "#due-crew .dc-room .seat", "--sv-a: var(--sa-l);", "--sv-a: var(--sa-d);")
    # 3.8.2: and each crew row's Pip wears its person's colour, as the seats do
    seat += _by_theme(cfg, "#due-crew .dc-rsev", "--sv-a: var(--rs-l);", "--sv-a: var(--rs-d);")
    # the name's cell clips what spills out of it: room above the line for a Pip's hat, the whole
    # row's (tr.sv) so the name and the numbers stay on one line
    seat += f"\n    #due-crew tr.sv > td {{ padding-top: {(3 if cfg.get('compact') else 6) + 6}px; }}"
    sheet = f'<style>{SEV_CSS}{CLOSET_CSS}{HW_CSS if halloween else ""}{seat}{_sev.CSS}</style>' if cfg.get("sev", True) else ""
    people = {x.get("user_id"): x for x in data.get("entries") or []}  # 3.8.22: a plan's squad line, mine too
    return (f'<div id="due-crew" class="dc-frame dc-split">{_css(cfg)}<style>{DUE_CSS}</style>{sheet}'
            f'{you_html(cfg, due, you, people)}<div class="dc-sheet">'
            f'{_head(period, show_up, hidden, cfg.get("crew_view") or period, sev)}{halloween_html(halloween, cfg)}{body}{foot}</div>'
            f'{fridge_html(fridge, people, cfg, fridge_gone)}'  # 3.9.1: the doodles, pinned around the Decks screen
            f'{dance_html(dance, cfg)}</div>')  # 3.9.6: the dance floor, in its corner (dance_js puts it there)


def you_html(cfg, due=None, you=None, people=None):
    """3.8.0, the You bubble: Today, Upcoming and Later (Due's lists, when
    Due is on), then Plans and Insights unless hidden in Settings. due:
    due.view or None; you: {tab, folded, plans, insights, opened}, from the glue
    (None: Due's lists alone, as before). "" when there's nothing to show.
    people (3.8.22): {uid: crew entry}, mine too, for a plan's squad line."""
    if you is None:
        return _due_html(due)
    hidden = hidden_tabs(cfg)
    more = tuple(t for t in YOU_MORE if t[0] not in hidden) + ((PARTY_TAB,) if you.get("party_on") else ())
    keys = (["today", "upcoming", "later"] if due else []) + [k for k, _l in more]
    if not keys:
        return ""
    tab = you.get("tab") if you.get("tab") in keys else keys[0]
    body = (_you_plans(you.get("plans"), None if due else you.get("opened"), people, cfg) if tab == "plans"
            else _you_insights(you.get("insights")) if tab == "insights"
            else party_html(you.get("party")) if tab == "party" else "")
    return _due_html(due, more, tab if tab in dict(more) else None, body, folded=bool(you.get("folded")),
                     magic=cfg.get("magic_search", True) is not False)


def _card(cfg, title, body_html, sheet=""):
    head = board_mark() if title == "Due Crew" else f"<b>{title}</b>"
    return (f'<div id="due-crew">{_css(cfg)}{sheet}<div class="dc-card">'
            f'{head}<span>{body_html}</span></div></div>')


def signed_out_card(cfg, expired=False, gone=False, sev=None):
    """gone (Q4): the account was deleted after 12 months without activity.
    sev (3.8.1, Sam's pick): Pip's markup, waving beside the words until
    you start (rooms.signed_out_sev), or None."""
    if gone:
        return _card(cfg, "Welcome back",
                     f'Your Due Crew account was deleted after 12 months without activity, '
                     f'as the listing says. Your Anki and its cards are untouched. '
                     f'<a href="#" onclick="{_pycmd("setup")}">Start again with your email</a>; '
                     f'your crew can add you with your new code.')
    if expired:
        return _card(cfg, "Due Crew",
                     f'Your sign-in expired. '
                     f'<a href="#" onclick="{_pycmd("setup")}">Sign in again</a>')
    # 3.4 review, C4: one way in; the emailed code knows if the address is new
    words = (f'Your friends&rsquo; studying next to yours. Nothing is shared '
             f'until you start. <a href="#" onclick="{_pycmd("setup")}">Start with your email</a>')
    if not sev:
        return _card(cfg, "Due Crew", words)
    return _card(cfg, "Due Crew", f'<span class="dc-so"><span class="dc-hi">{_sev.slot(sev, 44)}</span><span>{words}</span></span>',
                 f'<style>{SEV_CSS}{_sev.CSS}</style>')


def loading_card(cfg):
    return _card(cfg, "Due Crew", "Catching up with your crew&hellip;")
