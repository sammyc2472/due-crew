"""Squads: a squad's table, a plan's squad, bingo.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import re as _re
from datetime import datetime

from ..logo import board_mark
from .. import sev as _sev

from .base import (HEADERS, QUIET_FOLD_DAYS, _NW_ROOM, _by_theme, _cell, _even_rows, _fmt_time,
    _label, _pycmd, _quiet_fold, _reviews_cell, _week_span, face, sort_key)
from .style import _css
from .pip import BINGO_PIP_CSS, squad_pip, stamp_pip
from .crew import _corner, _scroll
from .plancards import _team_ago


def _plan_squad_html(pid, tabs, people=None, cfg=None):
    """3.8.0, a plan's squad on the Squads tab (the plan's Team tab until
    then): who showed up today, its bingo, Ask the squad and its threads,
    and the way out. Names, words and topics are other people's: escaped here."""
    e = _html.escape
    st, v = tabs.get("team_state"), tabs.get("team")
    if v is None:
        if st == "failed":
            return (f'<div class="tq0">Couldn&rsquo;t reach Due Crew. '
                    f'<a href="#" onclick="{_pycmd(f"planteamretry:{pid}")}">Try again</a></div>')
        return '<div class="tq0 dc-wait">Fetching&hellip;</div>'
    if not v.get("on"):
        n = int(v.get("count") or 0)
        return (f'<div class="tjoin"><b>{f"{n} in its squad" if n else "No one in its squad yet"}</b>'
                '<span class="k">The squad sees that you showed up today, and your questions and answers; '
                'your progress counts for the plan&rsquo;s authors. Never your numbers.</span>'
                f'<a class="bt" href="#" onclick="{_pycmd(f"planteamjoin:{pid}")}">Join its squad</a></div>')
    me = tabs.get("me")

    def who_face(x, size=None, small=False):  # 3.8.21: their Pip, as on the squad's table; Pip off, the emoji
        pip = squad_pip(x.get("uid"), x.get("name"), x.get("uid") == me, people, cfg, size) if cfg is not None else None
        return pip or face(x.get("emoji"), x.get("name"), small=small)
    faces = ""
    for f in v.get("faces") or []:
        name = "You" if f.get("uid") == me else str(f.get("name") or "?")
        faces += (f'<div class="face{"" if f.get("shown") else " away"}"><span class="e">{who_face(f, 40)}</span>'
                  f'<b>{e(name)}</b></div>')
    if int(v.get("more") or 0):
        more = int(v["more"])
        faces += f'<div class="face more"><span class="e">+</span><b>{more:,} more</b></div>'
    head = f'Showed up today &middot; {int(v.get("shown") or 0)} of {int(v.get("count") or 0)}'
    if int(v.get("streak") or 0) > 1:
        head += f' &middot; {int(v["streak"])} days running'
    out = f'<div class="tg">{head}</div><div class="faces">{faces}</div>'
    b = v.get("bingo")
    if b:
        from ..team import bingo_line
        ev = b["ev"]
        cells = "".join(f'<i class="{"on" if (ev["middle"]["done"] if c == 4 else ev["squares"][CELLS_BINGO.index(c)]["done"]) else ""}"></i>'
                        for c in range(9))
        out += (f'<style>{BINGO_CSS}</style><div class="bg-card" style="margin-top:8px"><span class="bg-mini">{cells}</span>'
                f'<span class="bg-t"><b>Squad bingo</b><span>{e(bingo_line(ev))}</span></span>'
                f'<a href="#" onclick="{_pycmd(f"planteambingo:{pid}")}">Open</a></div>')
    draft = e(str(tabs.get("draft") or ""), quote=True)
    send = (f"var v=document.getElementById('dc-tqa-{_re.sub(r'[^A-Za-z0-9]', '', pid)}').value;"
            f"if(v.trim())pycmd('duecrew:planteamask:{pid}:'+encodeURIComponent(v.slice(0,280))+'|'+window.dcBK);return false;")
    iid = f"dc-tqa-{_re.sub(r'[^A-Za-z0-9]', '', pid)}"
    out += (f'<div class="tg">Ask the squad</div><div class="tqa"><input id="{iid}" maxlength="280" '
            f'placeholder="Ask anything&hellip;" value="{draft}" onkeydown="if(event.key===\'Enter\'){{{send}}}">'
            f'<a href="#" onclick="{send}">Ask</a></div>')
    known = tabs.get("known") or {}
    down, have = set(known.get("down") or []), set(known.get("have") or [])
    for a in v.get("asks") or []:
        aid = int(a["id"])
        who = "You" if a.get("mine") else f'{who_face(a, small=True)} <b>{e(str(a.get("name") or "?"))}</b>'
        if a.get("guid"):
            on = " on a card you have down" if a["guid"] in down else " on a card"
            head = f'<span>{who}{on}</span>'
            body = f'<div>&ldquo;{e(str(a.get("text") or ""))}&rdquo;</div>'
        else:
            head = f'<span>{who}: {e(str(a.get("text") or ""))}</span>'
            body = ""
        reps = ""
        for r in a.get("replies") or []:
            rid = int(r["id"])
            rn = "You" if r.get("mine") else e(str(r.get("name") or "?"))
            extra = ""
            if a.get("mine") and not r.get("mine"):
                extra = f'<a href="#" onclick="{_pycmd(f"planteamhelped:{pid}:{rid}")}">{"Helped &#10003;" if r.get("helped") else "That helped"}</a>'
            elif r.get("helped"):
                extra = '<span class="ok"> &#10003; helped</span>'
            if r.get("remove"):
                extra += f'<a href="#" onclick="{_pycmd(f"planteamremove:{pid}:{rid}")}">Remove</a>'
            elif not r.get("mine"):
                extra += f'<a class="q" href="#" onclick="{_pycmd(f"planteamreport:{pid}:{rid}")}">Report</a>'
            reps += (f'<div class="rep"><b>{rn}</b>{" (author)" if r.get("author") else ""}: '
                     f'{e(str(r.get("text") or ""))}{extra}</div>')
        n_rep = len(a.get("replies") or [])
        bits = [x for x in (str(a.get("topic") or ""),
                            f'{n_rep} repl{"ies" if n_rep != 1 else "y"}' if n_rep else "") if x]
        acts = f'<a href="#" onclick="{_pycmd(f"planteamreply:{pid}:{aid}")}">{"Answer" if a.get("guid") else "Reply"}</a>'
        if a.get("guid") and a["guid"] in have:
            acts += f'<a href="#" onclick="{_pycmd(f"planteamcard:{pid}:{aid}")}">See the card</a>'
        if a.get("remove"):
            acts += f'<a class="q" href="#" onclick="{_pycmd(f"planteamremove:{pid}:{aid}")}">Remove</a>'
        elif not a.get("mine"):
            acts += f'<a class="q" href="#" onclick="{_pycmd(f"planteamreport:{pid}:{aid}")}">Report</a>'
        out += (f'<div class="tq"><div class="t">{head}<span class="m">{_team_ago(a.get("act") or a.get("at"))}</span></div>'
                f'{body}{reps}<div class="t"><span class="card">{e(" · ".join(bits))}</span>'
                f'<span class="acts">{acts}</span></div></div>')
    if not v.get("asks"):
        out += '<div class="tq0">No questions yet.</div>'
    return out + (f'<div class="dc-line"><a href="#" onclick="{_pycmd("duetab:plans")}">Open the plan</a> &middot; '
                  f'<a href="#" onclick="{_pycmd(f"planteamleave:{pid}")}">Leave</a></div>')


SQUAD_FIELDS = {"reviews": "reviews", "time": "time_ms",
                "retention": "retention", "streak": "streak", "week": "week"}
# squads stay Today-only, so this column is a rolling count ("studied 5 of
# the last 7 days"), one int per member. Labelled for what it is: the crew's
# Week view is the calendar week, and the two must not share a word.


def _squad_add():
    """3.9.10: the way into another squad, on the Squads tab alone, under the one shown."""
    return (f'<div class="dc-add"><a href="#" title="With a squad&rsquo;s code, or start one" '
            f'onclick="{_pycmd("squadadd")}">+ Create / join a squad</a></div>')


def _switcher(view):
    parts = []
    for sq in view.get("squads") or []:
        on = ' class="on"' if sq["id"] == view.get("current") else ""
        nm = _html.escape(str(sq["name"]))
        parts.append(f'<a{on} href="#" title="{nm}" onclick="{_pycmd("squad:" + str(sq["id"]))}">{nm}</a>')
    for sq in view.get("plan_squads") or []:
        # 3.8.0: a plan's squad, named for the plan; the badge is its threads that moved
        on = sq["id"] == view.get("current")
        n = int(sq.get("unread") or 0)
        cls = ' class="on"' if on else ""
        badge = f"<i>{n}</i>" if n and not on else ""
        nm = _html.escape(str(sq["name"]))
        parts.append(f'<a{cls} href="#" title="{nm}" onclick="{_pycmd("squadplan:" + str(sq["pid"]))}">{nm}{badge}</a>')
    # (3.9.10: "+ join or create" is _squad_add, under the squad: it crowded this line)
    return '<div class="dc-sw">' + "".join(parts) + "</div>"


def squad_week(rows, day):
    """3.8.0: a squad's last 7 days together, totals only (nobody ahead of
    anybody): (study days between us, how many of us studied). A row's week
    is its 7 days to its own last sync, so a sync `age` days ago counts at
    most 7 - age of them, and one a week old or more none (a day ahead is
    today, a timezone ahead). Its twin is squadWeek in app.js."""
    try:
        today = datetime.fromisoformat(str(day)).date()
    except ValueError:
        return 0, 0
    days = []
    for r in rows or []:
        w = r.get("week")
        if not isinstance(w, (int, float)) or isinstance(w, bool) or w != w or abs(w) == float("inf"):
            continue
        try:
            age = (today - datetime.fromisoformat(str(r.get("day"))).date()).days
        except ValueError:
            continue
        if -1 <= age < 7:  # a day ahead: a friend ahead of my timezone, synced on their today
            days.append(min(7 - max(age, 0), max(0, int(w))))
    return sum(days), sum(1 for d in days if d)


def _squad_week_line(rows, day):
    days, people = squad_week(rows, day)
    if people < 2:
        return ""
    return f'<div class="dc-line dc-sum sqwk">Last 7 days: <b>{days:,}</b> study days between {people:,} of you</div>'


def _squads_html(view, cfg, crew_by=None):
    """A squad board: everyone here holds the same invite. No places (3.9.9), no
    medals, no cheers; these aren't necessarily people you know. Add lives
    on the person's card (click a name), not on the row. crew_by (3.8.21): my
    crew by uid, so a crewmate's Pip wears their colour and look."""
    state = view.get("state")
    sw = _switcher(view)
    if view.get("kind") == "plan":
        return sw + _plan_squad_html(str(view.get("pid") or ""), view, crew_by, cfg) + _squad_add()
    name = _html.escape(str(view.get("name") or "?"))
    if state == "none":
        return sw + '<div class="dc-line">No squads yet.</div>' + _squad_add()
    if state == "loading":
        return sw + '<div class="dc-line dc-wait">Fetching&hellip;</div>'
    if state == "error":
        return (sw + '<div class="dc-line">Couldn&rsquo;t '
                'load. Check your connection and Refresh.</div>')
    if state == "gone":
        return (sw + f'<div class="dc-line">You&rsquo;re no '
                f'longer in {name}. <a href="#" '
                f'onclick="{_pycmd("squaddrop:" + str(view.get("current", "")))}">Remove</a></div>')
    rows = view.get("rows") or []
    day, yesterday = view.get("day", ""), view.get("yesterday", "")
    sort = sort_key(cfg)  # the crew table's sort, same headers, same links
    hsort = "reviews" if sort == "week" else sort  # (3.9.10: no 7 days head; an older pick of it reads as Reviews, as on Crew)
    field = SQUAD_FIELDS[sort]
    # synced today with nothing studied yet: no numbers to rank, so these
    # sit under the ranked rows with dashes (as on Today)
    zero = lambda r: r.get("reviews") == 0 and not r.get("time_ms")
    live = sorted([r for r in rows if r.get("day") == day and not zero(r)],
                  key=lambda r: r.get(field) if r.get(field) is not None else -1,
                  reverse=True)
    waiting_today = [r for r in rows if r.get("day") == day and zero(r)]
    rest = sorted([r for r in rows if r.get("day") != day],
                  key=lambda r: r.get("day") or "", reverse=True)
    # Q3: members with no sync in 90+ days fold into one line, as on Today
    try:
        cut = (datetime.fromisoformat(day) - _dt.timedelta(days=QUIET_FOLD_DAYS)).date().isoformat()
    except Exception:
        cut = ""
    long_q = [r for r in rest if cut and not r.get("you") and str(r.get("day") or "") < cut]
    rest = [r for r in rest if r not in long_q] + long_q
    long_ids = {id(r) for r in long_q}
    people = int(view.get("people") or len(rows))
    headline = f'{people:,} in {name}'
    if view.get("open") is False:
        headline += " &middot; locked"
    if live:
        headline += (f' &middot; {len(live):,} studying today &middot; '
                     f'{int(view.get("reviews") or 0):,} reviews together')
    # 3.8.0, head row B: the squads' names in the table's corner, the
    # headline under it (rebuilt below when show-up mode is on)
    heads = _corner(sw)
    for key, label in HEADERS:  # 3.9.10, one grid: Crew's four columns; 7 days is in each name's line
        on = "on" if key == hsort else ""
        arrow = " &#9662;" if key == hsort else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{label}{arrow}</a></th>')
    show_up = bool(cfg.get("show_up"))
    numberless = lambda r: all(r.get(k) is None for k in ("reviews", "time_ms", "retention", "streak"))
    if show_up:
        live.sort(key=lambda r: (-(r.get("week") or 0), r["name"].lower()))
        headline = (f'{people:,} in {name}' + (" &middot; locked" if view.get("open") is False else "")
                    + (f" &middot; {len(live):,} showed up today" if live else ""))
        heads = (_corner(sw) + '<th><span style="color: var(--dc-muted); font-size: 11px; '
                 'font-weight: 700;">&#128197; 7 days</span></th>')
    body = ""
    folded = False
    for r in live + waiting_today + rest:
        uid = str(r["user_id"])
        pip = squad_pip(uid, r["name"], r.get("you"), crew_by, cfg)  # 3.8.21: Pip where the emoji was
        pname = _html.escape(str(r["name"])) if pip else _label(r["name"], r.get("emoji"))
        cls, note = "", ""
        if id(r) in long_ids:
            if not folded:
                body += _quiet_fold([{"name": x["name"], "last_updated": x.get("day")} for x in long_q]).replace(
                    f'colspan="{len(HEADERS) + 1}"', f'colspan="{2 + (1 if show_up else len(HEADERS))}"', 1)
                folded = True
            cls = "qh"
        if r.get("you"):
            cls = "you"
            link = (f'<a class="dc-pl" href="#" title="See what your crew sees" '
                    f'onclick="{_pycmd("profile:" + uid)}">{pname}</a>')
        else:
            if r.get("crew"):
                note = ' <span class="la faded">&middot; crew</span>'
            elif r.get("knocked_me"):
                note = ' <span class="la fresh">&middot; added you</span>'
            elif r.get("pending"):
                note = ' <span class="la faded">&middot; waiting</span>'
            link = (f'<a class="dc-pl" href="#" title="Open card" '
                    f'onclick="{_pycmd("ecard:" + uid)}">{pname}</a>')
        if not show_up and isinstance(r.get("week"), int) and not isinstance(r.get("week"), bool):
            note = f' <span class="la faded">&middot; {max(0, min(7, r["week"]))}/7 days</span>' + note
        if pip:  # beside the name, outside its underline, as on Crew; room above for a hat (tr.sv)
            link, cls = pip + link, cls + " sv"
        if r.get("day") != day:
            cls += " dim"
            when = "yesterday" if r.get("day") == yesterday else "quiet"
            note += f' <span class="la faded">&middot; {when}</span>'
            rank = ""
        elif zero(r):
            cls += " dim"
            note += ' <span class="la faded">&middot; nothing yet today</span>'
            rank = ""
        elif show_up or numberless(r):
            rank = ""
            note += ' <span class="la faded">&#10003;</span>'  # showed up: counted, not ranked (3.9.10: in the name's line)
        else:
            rank = ""  # 3.9.9 (Sam: "squads should definitely lose those places"): the order says it, as on Crew
        if show_up:
            body += (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
                     f'<td class="nm">{link}{note}</td>'
                     f'<td class="n">{_cell(r.get("week"), lambda v: f"{v}/7")}</td></tr>')
            continue
        if r.get("day") == day and zero(r):
            body += (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
                     f'<td class="nm">{link}{note}</td>'
                     f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3 + '</tr>')
            continue
        body += (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
                 f'<td class="nm">{link}{note}</td>'
                 f'<td class="n">{_reviews_cell(r.get("reviews"), r.get("new_cards"))}</td>'
                 f'<td class="n">{_cell(r.get("time_ms"), _fmt_time)}</td>'
                 f'<td class="n">{_cell(r.get("retention"), lambda v: f"{v:.1f}%")}</td>'
                 f'<td class="n">{_cell(r.get("streak"))}</td></tr>')
    body = _even_rows(body)
    # the squad's own line; Share today sits in the footer, as on Today
    acts = [f'<a href="#" onclick="{_pycmd("squadinvite")}">Copy invite</a>']
    if view.get("founder_me"):
        acts.append(f'<a href="#" onclick="{_pycmd("squadlock")}">'
                    f'{"Open" if view.get("open") is False else "Lock"}</a>')
    acts.append(f'<a href="#" onclick="{_pycmd("squadleave")}">Leave</a>')
    foot = ('<div class="dc-line">'
            + " &middot; ".join(acts) + "</div>") + _squad_add()
    bingo = (f"<style>{BINGO_CSS}</style>" + bingo_card_html(view["bingo"])) if view.get("bingo") else ""  # 3.6
    if not body:
        return (sw + bingo + '<div class="dc-line">No one&rsquo;s '
                'synced yet.</div>' + foot)
    # the bingo card under the table, the names it's for being in its corner
    return (_scroll(f'<table class="dc-s-{hsort}"><tr>{heads}</tr>{body}</table>' if not show_up
                    else f"<table><tr>{heads}</tr>{body}</table>", body.count('<tr class='))
            + f'<div class="dc-line dc-sum">{headline}</div>' + _squad_week_line(rows, day) + bingo + foot)


# ---- 3.6: squad bingo ----

BINGO_CSS = """
    /* the whole card's frame is #due-crew.bg-full itself: its rules say so */
    #due-crew .bg-card, #due-crew.bg-full, #due-crew .bg-row, #due-crew .bg-bar, #due-crew .bg-info { text-align: left; }
    #due-crew [hidden] { display: none !important; }
    #due-crew .bg-card { border-top: 1px solid var(--dc-line); border-bottom: 1px solid var(--dc-line); padding: 9px 0;
      margin: 2px 0 10px;  /* 3.8.0: a row between rules, no box */
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 12px; }
    #due-crew .bg-card .bg-t { display: grid; gap: 1px; flex: 1 1 180px; min-width: 0; }
    #due-crew .bg-card .bg-t span, #due-crew .bg-q { color: var(--dc-muted); }
    #due-crew .bg-card a, #due-crew a.bg-a { color: var(--dc-accent); font-weight: 700; text-decoration: none; white-space: nowrap; }
    #due-crew .bg-mini { display: grid; grid-template-columns: repeat(3, 9px); gap: 2px; flex: none; }
    #due-crew .bg-mini i { width: 9px; height: 9px; border-radius: 2px; background: var(--dc-line); }
    #due-crew .bg-mini i.on { background: var(--dc-accent); }
    #due-crew .bg-mini i.m { background: var(--dc-hours); }
    #due-crew .bg-bar { display: flex; align-items: baseline; gap: 4px 10px; flex-wrap: wrap; margin: 2px 0 10px; }
    #due-crew .bg-bar b { font-size: 15px; }
    #due-crew .bg-bar .bg-a:last-child { margin-left: auto; }
    #due-crew .bg-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
    #due-crew .bg-sq { position: relative; min-height: 118px; padding: 17px 5px 22px; border: 1px solid var(--dc-line) !important;
      border-radius: 9px; background: var(--dc-bg); color: var(--dc-ink); font: inherit; cursor: pointer;
      display: grid; align-content: start; justify-items: center; gap: 2px; text-align: center; }
    #due-crew .bg-sq .ic { font-size: 22px; line-height: 1.1; }
    #due-crew .bg-sq .tt { font-size: 12px; font-weight: 700; line-height: 1.2; }
    #due-crew .bg-sq .rl { font-size: 10.5px; line-height: 1.25; color: var(--dc-muted); }
    #due-crew .bg-sq .fm { position: absolute; top: 4px; left: 6px; font-size: 8px; font-weight: 700; letter-spacing: .05em;
      text-transform: uppercase; color: var(--dc-muted); }
    #due-crew .bg-sq .df { position: absolute; top: 4px; right: 6px; font-size: 7px; letter-spacing: 1px; color: var(--dc-muted); }
    #due-crew .bg-sq .tm { font-size: 9.5px; font-weight: 700; color: var(--dc-hours); background: var(--dc-amber-bg, rgba(178,106,0,.1));
      border-radius: 99px; padding: 0 6px; }
    #due-crew .bg-sq .tm.ok { color: var(--dc-accent); background: var(--dc-you-bg); }
    #due-crew .bg-sq .st { position: absolute; bottom: 3px; width: 22px; height: 22px; border-radius: 50%; display: grid;
      place-items: center; font-size: 13px; background: var(--dc-you-bg); box-shadow: inset 0 0 0 1.5px var(--dc-accent); }
    #due-crew .bg-sq.done { background: var(--dc-you-bg); }
    #due-crew .bg-sq.line { border-color: var(--dc-accent) !important; box-shadow: inset 0 0 0 1px var(--dc-accent) !important; }
    #due-crew .bg-sq.mid { border-color: var(--dc-hours) !important; }
    #due-crew .bg-sq.mid.done { border-color: var(--dc-accent) !important; }
    #due-crew .bg-sq.sel { outline: 2px solid var(--dc-ink) !important; outline-offset: -2px; }
    #due-crew .bg-sq .pb { width: 80%; height: 4px; border-radius: 2px; background: var(--dc-line); overflow: hidden; }
    #due-crew .bg-sq .pb i { display: block; height: 100%; background: var(--dc-hours); }
    #due-crew .bg-sq.done .pb i { background: var(--dc-accent); }
    #due-crew .bg-sq .pp { font-size: 9.5px; font-weight: 700; color: var(--dc-hours); }
    #due-crew .bg-row { display: flex; gap: 6px 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
    #due-crew .bg-shout { font-weight: 800; font-size: 15px; color: var(--dc-accent); letter-spacing: .03em; }
    #due-crew .bg-info { border-top: 1px solid var(--dc-line); margin-top: 10px; padding-top: 8px; font-size: 12px; }
    #due-crew .bg-info > div { display: grid; gap: 3px; }
    #due-crew .bg-info .k { color: var(--dc-muted); font-size: 11px; }
    #due-crew .bg-info .me { font-weight: 700; }
    @media (max-width: 460px) {
      #due-crew .bg-sq { min-height: 126px; padding: 15px 2px 20px; }
      #due-crew .bg-sq .tt { font-size: 11px; }
      #due-crew .bg-sq .rl { font-size: 9.5px; }
      #due-crew .bg-sq .fm { font-size: 7px; left: 4px; }
      #due-crew .bg-sq .st { width: 18px; height: 18px; font-size: 10px; }
    }
"""


def _bg_need(sq, need):
    # the number, never the share: "a third of you" said nothing in a small squad
    return f"{need} of you"


def bingo_card_html(bv):
    """The Squads tab's card, above the squad's table: the grid small, the
    middle's progress, what's closest to a line. Never who's ahead."""
    if not bv:
        return ""
    e = _html.escape
    card, ev = bv["card"], bv["ev"]
    cells = ""
    for c in range(9):
        if c == 4:
            cells += f'<i class="{"on" if ev["middle"]["done"] else "m"}"></i>'
        else:
            cells += f'<i class="{"on" if ev["squares"][CELLS_BINGO.index(c)]["done"] else ""}"></i>'
    m, mid = card["middle"], ev["middle"]
    if bv.get("new"):
        line = (f'&#129376; A new card. This week&rsquo;s middle: {e(m["icon"])} '
                f'<b>{e(m["name"])}</b>, {e(m["rule"][:1].lower() + m["rule"][1:])}.')
    else:
        stamps = sum(1 for q in ev["squares"] if q["done"]) + (1 if mid["done"] else 0)
        if ev["lines"] >= 8:
            state = "the whole card"
        elif ev["lines"]:
            state = "BINGO" if ev["lines"] == 1 else f'{ev["lines"]} lines'
        else:
            left = len(bv.get("closest") or [])
            state = "one away from bingo" if left == 1 else f"{left} away from bingo"
        line = f"{stamps} of 9 &middot; {state}"
    return (f'<div class="bg-card"><span class="bg-mini">{cells}</span>'
            f'<span class="bg-t"><b>Squad bingo</b><span>{line}</span></span>'
            f'<a href="#" onclick="{_pycmd("bingo")}">Open the card</a></div>')


CELLS_BINGO = (0, 1, 2, 3, 5, 6, 7, 8)


def bingo_html(bv, cfg, loading=False, team=False, people=None):
    """The whole card, in the board's place (like Settings). Every string
    from the server is escaped here. A square's details show in the page
    when it's clicked: no request. people (3.8.22): {uid: crew entry}, mine
    too, so who stamped a square shows as their Pip (stamp_pip)."""
    e = _html.escape
    pips = cfg.get("sev", True)
    sheet = (f'<style>{_sev.CSS}{BINGO_PIP_CSS}{_by_theme(cfg, "#due-crew .dc-rsev", "--sv-a: var(--rs-l);", "--sv-a: var(--rs-d);")}</style>'
             if pips else "")
    head = (f'<div id="due-crew" class="dc-frame bg-full">{_css(cfg)}<style>{BINGO_CSS}</style>{sheet}'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span></div>')
    team_card = bool(bv and bv.get("team")) or team  # 3.7.3: a plan team's card: counts, never who
    back = (f'<a class="bg-a" href="#" onclick="{_pycmd("planteambingoback")}">&lsaquo; Squads</a>' if team_card
            else f'<a class="bg-a" href="#" onclick="{_pycmd("bingoback")}">&lsaquo; Squads</a>')
    if not bv:
        said = "Fetching&hellip;" if loading else "No card this week yet. Refresh brings it."
        return head + (f'<div class="bg-bar">{back}<b>Squad bingo</b></div>'
                       f'<div class="bg-q{" dc-wait" if loading else ""}">{said}</div></div>')
    card, ev = bv["card"], bv["ev"]
    names, me = bv.get("names") or {}, bv.get("me")
    progress = bv.get("progress") or []
    lined = set(ev.get("cells") or [])
    squares, infos = "", ""
    fams = {"early": "Early", "spread": "Spread out", "focus": "Focus", "volume": "Bigger day", "fresh": "New cards",
            "often": "Showing up", "clean": "Keeping up", "wild": "Wildcard"}
    diffs = {"e": ("&#9679;", "easy"), "m": ("&#9679;&#9679;", "medium"), "h": ("&#9679;&#9679;&#9679;", "hard")}
    show = "var i=this.dataset.i;document.querySelectorAll('#due-crew .bg-info>div').forEach(function(x){x.hidden=x.dataset.i!==i});" \
           "document.querySelectorAll('#due-crew .bg-sq').forEach(function(x){x.classList.toggle('sel',x.dataset.i===i)});return false;"
    for c in range(9):
        cls = "line" if c in lined else ""
        if c == 4:
            m, mid = card["middle"], ev["middle"]
            pct = 100 if mid["done"] else int(100 * mid["have"] / max(1, mid["goal"]))
            free = m.get("type") == "free"
            said = "Unlocked" if mid["done"] else f'{mid["have"]} of {mid["goal"]} {e(m.get("unit") or "")}'.strip()
            prog = "" if free else (f'<span class="pb"><i style="width:{pct}%"></i></span>'
                                    f'<span class="pp">{said}</span>')
            squares += (f'<button class="bg-sq mid {"done" if mid["done"] else ""} {cls}" data-i="m" onclick="{show}">'
                        f'<span class="ic">{e(m["icon"]) if mid["done"] else "&#128274;"}</span>'
                        f'<span class="tt">{e(m["name"])}</span><span class="rl">{e(m["rule"])}</span>{prog}</button>')
            state = ("Unlocked. It counts toward all four lines through the middle." if mid["done"]
                     else f'{mid["have"]} of {mid["goal"]} so far. The squad unlocks it together.')
            infos += (f'<div data-i="m" hidden><b>{e(m["icon"])} {e(m["name"])}: {e(m["rule"])}</b>'
                      f'<span>{e(m["detail"])}</span><span class="k">{"This week the middle is free." if free else state}</span></div>')
            continue
        i = CELLS_BINGO.index(c)
        sq, st = card["squares"][i], ev["squares"][i]
        known = sq.get("type") in _BINGO_TYPES
        who = st.get("who") or []
        n_who = int(st.get("n", len(who)))
        team = ""
        if st["need"] > 1 or sq.get("need") in ("half", "third", "quarter"):
            so_far = " &#10003;" if st["done"] else f' &middot; {n_who}/{st["need"]}'
            team = (f'<span class="tm{" ok" if st["done"] else ""}">&#128101; {_bg_need(sq, st["need"])}'
                    f'{so_far}</span>')
        marks = "".join(
            f'<span class="st sp" style="right:{8 + k * 27}px;{"" if st["done"] else "opacity:.55"}" title="{e(names.get(u, ("?", ""))[0])}">'
            f'{stamp_pip(u, names.get(u, ("?", ""))[0], people, cfg, k)}</span>' if pips else
            f'<span class="st" style="right:{3 + k * 15}px;{"" if st["done"] else "opacity:.55"}" title="{e(names.get(u, ("?", ""))[0])}">'
            f'{e(names.get(u, ("?", ""))[1]) or "&#10003;"}</span>' for k, u in enumerate(who[:3]))
        dots, dname = diffs.get(sq.get("diff"), diffs["m"])
        rule = f'<span class="rl">{e(sq["rule"])}</span>' if known else ""
        squares += (f'<button class="bg-sq {"done" if st["done"] else ""} {cls}{" stamped" if pips and who else ""}" data-i="{i}" onclick="{show}">'
                    f'<span class="fm">{fams.get(sq.get("fam"), "")}</span><span class="df" title="{dname}">{dots}</span>'
                    f'<span class="ic">{e(sq["icon"])}</span><span class="tt">{e(sq["title"]) if known else "Update to play"}</span>'
                    f'{rule}{team}{marks}</button>')
        whose = ", ".join(e(names.get(u, ("?", ""))[0]) for u in who) if who else (f"{n_who} of you" if n_who else "")
        if st["need"] > 1 or sq.get("need") in ("half", "third", "quarter"):
            state = (f'A team square: {_bg_need(sq, st["need"])} have to pass the mark this week. '
                     + (f"Done by {whose}." if st["done"] else f"So far: {whose}." if whose else "Nobody yet."))
        else:
            state = f"Stamped by {whose}." if whose else "Not yet. Any one of you can stamp it."
        mine = ""
        if known and i < len(progress) and progress[i]:
            done, words = progress[i]
            if me in who or done:  # a team card has no who: my own progress says
                mine = '<span class="me">You: done.</span>'
            elif sq.get("type") in (bv.get("withheld") or ()):
                mine = (f'<span class="me">You: {e(words)}</span>'
                        '<span class="k">Your Privacy switches keep yours on this computer: it would say when or how much.</span>')
            else:
                mine = f'<span class="me">You: {e(words)}</span>'
        elif not known:
            mine = '<span class="k">New this week. Update Due Crew to play it; your squad can still stamp it.</span>'
        infos += (f'<div data-i="{i}" hidden><b>{e(sq["icon"])} {e(sq["title"])}</b>'
                  f'<span class="k">{fams.get(sq.get("fam"), "")} &middot; {dname}</span>'
                  f'<span>{e(sq["detail"])}</span>{mine}<span class="k">{state}</span></div>')
    stamps = sum(1 for q in ev["squares"] if q["done"]) + (1 if ev["middle"]["done"] else 0)
    if ev["lines"] >= 8:
        foot = '<span class="bg-shout">THE WHOLE CARD</span><span>All nine, together.</span>'
    elif ev["lines"]:
        foot = (f'<span class="bg-shout">BINGO!</span>'
                f'<span>{"A line" if ev["lines"] == 1 else str(ev["lines"]) + " lines"} this week.</span>')
    else:
        foot = f'<span class="bg-q">Closest: {e(", ".join(bv.get("closest") or []))}</span>'
    older = ""
    if ev.get("older"):
        n = ev["older"]
        older = f'<div class="bg-row bg-q">{n} of you need{"s" if n == 1 else ""} to update Due Crew to play.</div>'
    copy = ("" if team_card else
            f'<a class="bg-a" href="#" title="The grid in emoji, never who stamped what" onclick="{_pycmd("bingocopy")}">Copy for the group chat</a>')
    title = f'{e(bv.get("squad") or "Squad")} bingo'
    return (head
            + f'<div class="bg-bar">{back}<b>{title}</b>'
              f'<span class="bg-q">{e(_week_span(card["wk"]))} &middot; {stamps} of 9</span>{copy}</div>'
            + f'<div class="bg-grid">{squares}</div>'
            + f'<div class="bg-row">{foot}</div>' + older
            + f'<div class="bg-info"><div data-i=""></div>{infos}</div>'
            + "</div>")


_BINGO_TYPES = ("window", "minute", "sittings", "parts", "focus", "beat", "rel", "best",
                "newdays", "newdone", "days", "zero", "samehour")
