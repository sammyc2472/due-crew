"""Crew: the head row and its picker, a crew row, the table, presence, the Decks view and asks.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
from datetime import datetime

from ..logo import board_mark
from .. import sev as _sev

from .base import (BENCH_MAX, CREW_VIEWS, HEADERS, ROW_CAP, _NW_ROOM, _ago, _cell, _even_rows, _fmt_time, _label,
                   accent_pair, away_words, initial,
    _pycmd, _reviews_cell, _showed, build_deck_groups, build_rows, plan_target, sort_key,
    week_labels)
from .pip import row_sev


def crew_views(show_up=False, hidden=frozenset()):
    """3.8.0: Crew's views, picked under the pills: Today, Week, Decks; in
    show-up mode This week (one view for both) and Decks. Decks can hide."""
    first = (("today", "This week"),) if show_up else CREW_VIEWS[:2]
    return first + (CREW_VIEWS[2:] if "decks" not in hidden else ())


def _crew_on(period, show_up=False):
    """The Crew view a period draws as: show-up mode draws Week as This week."""
    return "today" if show_up and period == "week" else period


def _head(period, show_up=False, hidden=frozenset(), crew="today", sev=None):
    """3.8.0: the board is your people: Crew and Squads. Crew's views are
    picked under the pills (_crew_picker), and the Crew pill goes back to
    the one last picked."""
    views = dict(crew_views(show_up, hidden))
    crew = _crew_on(crew, show_up)
    crew = crew if crew in views else "today"
    keys = (("crew", "Crew"), ("squads", "Squads"))
    on = "squads" if period == "squads" else "crew"
    keys = tuple((k, label) for k, label in keys if k not in hidden)
    pills = ""
    for key, label in keys:
        cls = "dc-pill on" if on == key else "dc-pill"
        pills += (f'<a class="{cls}" href="#" '
                  f'onclick="{_pycmd("period:" + (crew if key == "crew" else key))}">{label}</a>')
    # 3.8.1: Pip beside the logo, never on it (the logo itself never changes),
    # and only for a moment: it pops in, plays it, and goes (Sam)
    beside = (f'<a class="dc-sev once" href="#" title="Pip&rsquo;s closet" onclick="{_pycmd("closet")}" '
              f'style="--ago:{float(sev.get("ago") or 0):.2f}s">{_sev.slot(sev["svg"], 36)}</a>'
              if sev and sev.get("svg") else "")  # 3.8.2: Pip's closet is a click away
    return (f'<div class="dc-head"><span class="dc-title">{board_mark()}{beside}</span>'
            f'<span>{pills}</span></div>')


def _crew_picker(period, show_up=False, hidden=frozenset()):
    """3.8.0: Crew's views, picked as a squad is (the Squads tab's .dc-sw).
    Nothing when there's only one."""
    views = crew_views(show_up, hidden)
    if len(views) < 2:
        return ""
    period = _crew_on(period, show_up)
    on = ' class="on"'
    return ('<div class="dc-sw">' + "".join(
        f'<a{on if period == k else ""} data-t="{t}" href="#" onclick="{_pycmd("period:" + k)}">{t}</a>'
        for k, t in views) + "</div>")


def _corner(inner):
    """3.8.0, head row B (Sam's pick): a picker in the table's top-left
    corner, over the rank and the name, where the header was empty."""
    return f'<th class="lt dc-corner" colspan="2">{inner}</th>'


def _chip(row):
    """3.4 review, T1: the one thing beside a name, the most time-bound:
    a room or studying now, an exam within two weeks, back today, away,
    a plan week done. The rest is on the person's card. T2: green only
    for studying now, amber only for an exam; the others grey."""
    if row["quiet"]:
        return ""
    if row.get("room"):
        # the room's title is a friend's name: escaped
        return f' <span class="dc-live"></span><span class="chip live">in {_html.escape(str(row["room"]))}</span>'
    if row.get("live"):
        return ' <span class="dc-live"></span><span class="chip live">studying now</span>'
    if row.get("exam"):
        return f' <span class="chip exam">{_html.escape(str(row["exam"]))}</span>'
    if row.get("back"):
        return ' <span class="chip">back today</span>'
    if row.get("away"):
        away = str(row["away"])
        return f' <span class="chip">{_html.escape(away if away == "away" else "away · " + away)}</span>'
    r = row.get("recap")
    if r:
        return (f' <span class="chip" title="{_html.escape(str(r.get("name") or ""))}">'
                f'week {int(r.get("n") or 0)} done</span>')
    return ""


def _who(row, cfg):
    """3.8.2: a crew row's name, with their Pip in the emoji's place (Pip
    on), or their emoji (Pip off), as before."""
    fig = row_sev(row, cfg)
    return (fig, _html.escape(str(row["name"]))) if fig else ("", _label(row["name"], row.get("emoji")))


def _row_html(row, rank, cfg, period="today", held=False):
    """held (3.9.9): a cheer I sent them while Due Crew couldn't be reached, waiting to go."""
    fig, name = _who(row, cfg)
    cls = ("you" if row["you"] else "") + (" sv" if fig else "") + (" ch" if held and not row["you"] else "")
    extra = ""
    la = ""
    if row["paused"]:
        cls += " dim"
        extra = ' <span class="dc-note">&middot; on a break</span>'
        cells = f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3
    elif row.get("notyet"):
        cls += " dim"
        # a phone's reviews reach us only once their computer's Anki syncs,
        # so say when we last heard, not that they haven't studied
        txt, _tone = _ago(row["last_updated"])
        when = f" as of {txt}" if txt and txt != "just now" else ""
        extra = (' <span class="la faded">&middot; nothing '
                 f'{"this week" if period == "week" else "yet"}{when}</span>')
        cells = f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3
    elif row["quiet"]:
        cls += " dim"
        cells = f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3
        # T2: when they last synced is a quiet row's whole story; the others
        # show it on their card
        txt, _tone = _ago(row["last_updated"])
        if txt:
            la = f'<span class="la faded">({txt})</span>'
    else:
        if row["stale"]:
            cls += " dim"
            extra = ' <span class="la faded">&middot; yesterday</span>'
        elif row.get("showup"):  # 3.9.10, one grid: the tick is in the name's line (it had a column of its own)
            n = int(row.get("days_wk") or 0)
            extra = ' <span class="la faded">&#10003;' + (f' {n} day{"s" if n != 1 else ""} this week' if n else "") + '</span>'
        # T5: how many were new shows on the Week tab, where it's the story
        cells = (f'<td class="n">{_reviews_cell(row["reviews"], row.get("new") if period == "week" else None)}</td>'
                 f'<td class="n">{_cell(row["time_ms"], _fmt_time)}</td>'
                 f'<td class="n">{_cell(row["retention"], lambda v: f"{v:.1f}%")}</td>'
                 f'<td class="n">{_cell(row["streak"])}</td>')
    chip = _chip(row)
    status = ""
    if row.get("status"):
        st = _html.escape(str(row["status"]))
        # 2.10: a status that starts with a number is a plan, ticked by the
        # day's reviews; without shared reviews it stays a plain status
        target = plan_target(row["status"])
        done = row.get("reviews")
        lead = ""
        if target and isinstance(done, int) and not row.get("stale"):
            if done >= target:
                lead = "&#10003; "
            else:
                pct = min(100, round(100 * done / target))
                lead = (f'&#128221; <span class="dc-plan"><i style="width:{pct}%"></i></span>'
                        f'{done:,} &middot; ')
        status = f'<div class="dc-stw"><span class="dc-st" title="{st}">{lead}{st}</span></div>'
    if row["you"]:
        cheer = ""
        name = (f'{fig}<a class="dc-pl" href="#" title="See what your crew sees" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{name}</a>')
    else:
        # 3.9.1: the cheer is a pill after the name (and its chip), where the eye already is
        cheer = (f'<a class="dc-cpill" href="#" title="Send a cheer" aria-label="Cheer {_html.escape(str(row["name"]), quote=True)}" '
                 f'onclick="{_pycmd("cheerpick:" + str(row["user_id"]))}">&#127881; Cheer</a>') if not held else (
            # 3.9.9 (Off the Board, 11): sent while Due Crew couldn't be reached; it goes with the next refresh that does
            f'<a class="dc-cpill held" href="#" title="Sends when Due Crew is back" '
            f'aria-label="Cheer for {_html.escape(str(row["name"]), quote=True)}, waiting to send" '
            f'onclick="{_pycmd("cheerpick:" + str(row["user_id"]))}">&#127881; Waiting<span class="ts"> to send</span></a>')
        # 3.0.1: right-click for Mute cheers and Report…
        # 3.8.2: their Pip opens the profile too, outside the name's underline
        sev_link = (f'<a class="dc-rsevl" href="#" tabindex="-1" aria-hidden="true" '
                    f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{fig}</a>') if fig else ""
        name = (sev_link + f'<a class="dc-pl" href="#" title="Open profile" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}" '
                f'oncontextmenu="{_pycmd("rowmenu:" + str(row["user_id"]))}">{name}</a>')
    return (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
            f'<td class="nm">{name}{chip}{la}{extra}{cheer}{status}</td>{cells}</tr>')


def _solo_html(data):
    """3.4 review, C5: until a friend adds me back, the invite is the board
    (in show-up mode too, 3.8.0)."""
    if len(data["entries"]) != 1:
        return ""
    code = str(data.get("my_code") or "")
    spaced = f"{code[:4]} {code[4:]}" if len(code) == 6 else code
    # 3.5.0: a friend's, a plan's or a squad's code, or a whole invite
    add = ("var v=(document.getElementById('dc-addcode').value||'').toUpperCase()"
           ".replace(/[^A-Z0-9 \\/]/g,' ').slice(0,200);"
           "pycmd('duecrew:addcode:'+v+'|'+window.dcBK);return false;")
    pending = [str(x) for x in data.get("pending") or []]
    if not pending:
        wait = "Send a friend your invite. Once you’ve added each other, they’re here."
    elif len(pending) <= 2:
        wait = f"Waiting for {' and '.join(_html.escape(x) for x in pending)} to add you back."
    else:
        wait = f"Waiting for {len(pending)} people to add you back."
    return (f'<div class="dc-empty"><b>Bring your crew</b>'
            f'<span style="color: var(--dc-muted);">{wait}</span>'
            f'<div class="row">{f"<span class=dc-code>{_html.escape(spaced)}</span>" if code else ""}'
            f'<a class="bt on" href="#" onclick="{_pycmd("copyinvite")}">Copy invite</a></div>'
            f'<div class="row"><input id="dc-addcode" placeholder="A code, or paste an invite" '
            f'onkeydown="if(event.key===\'Enter\'){{{add}}}">'
            f'<a class="bt" href="#" onclick="{add}">Add</a></div></div>')


def _table_html(data, cfg, period, pick=""):
    """pick: Crew's views (_crew_picker), in the header's corner."""
    sort = sort_key(cfg)
    fresh, dormant = build_rows(data["entries"], data["labels"],
                                data.get("tomorrow", ""), period, cfg)
    held = set(data.get("held") or ())  # 3.9.9: cheers waiting for Due Crew to be reachable
    heads = _corner(pick) if pick else "<th></th><th></th>"
    if sort == "week":
        sort = "reviews"
    for key, label in HEADERS:
        on = "on" if key == sort else ""
        arrow = " &#9662;" if key == sort else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{label}{arrow}</a></th>')
    if cfg.get("show_up"):
        fresh, dormant = build_rows(data["entries"], data["labels"],
                                    data.get("tomorrow", ""), "today", cfg)
        return _presence_html(fresh, dormant, data["labels"], data["entries"], pick, cfg) + _solo_html(data)
    body = ""
    for row in fresh:
        rank = ""  # 3.9.10, one grid: no first column at all. 3.9.9 (Sam, the design mocks' 2): no medals, no places: the order says it, and this isn't a race
        body += _row_html(row, rank, cfg, period, held=row["user_id"] in held)
    # 3.9.12 (SC: "keep yesterday at the bottom but not distinguished by a header ... and put the bench
    # without the zzz or clear separation"): a friend who's been away longer than yesterday, or is on a
    # break, has no row: their Pip sits on the bench under the board (_bench_html). Q3's fold of the
    # long quiet went with it: the bench says how long for each.
    bench = [r for r in dormant if (r["quiet"] or r["paused"]) and not r["you"]]
    for row in dormant:
        if row not in bench:
            body += _row_html(row, "", cfg, period, held=row["user_id"] in held)
    body = _even_rows(body)
    solo = _solo_html(data)
    # the name column ellipsizes, so the table can never outgrow the card;
    # past the row cap it scrolls inside it
    # 3.9.9: what it's sorted by, for a narrow window's two columns (style.py)
    return (_scroll(f'<table class="dc-s-{sort}"><tr>{heads}</tr>{body}</table>', body.count('<tr class='))
            + _bench_html(bench, cfg) + solo)


def _bench_html(rows, cfg):
    """3.9.12, the bench: who hasn't been here since before yesterday, or is on a break, as their Pips
    asleep in a line under the board (their colour and look, no z's, no line between it and the rows),
    each with a name and how long; a click is their profile, where a cheer is. With Pip off: an initial
    in its place. Names are the server's: escaped."""
    if not rows:
        return ""
    e = _html.escape
    seats = ""
    for row in rows[:BENCH_MAX]:
        name = str(row.get("name") or "?")
        how = "on a break" if row["paused"] else away_words(row.get("last_updated"))
        light, dark = accent_pair(row.get("accent"))
        if cfg.get("sev", True):
            fig = (f'<span class="dc-rsev" style="--rs-l:{light};--rs-d:{dark}">'
                   + _sev.slot(_sev.svg("nap", rest=True, look=row.get("look"), label=e(f"{name}’s Pip, away", quote=True)), BENCH_PIP)
                   + '</span>')
        else:
            fig = f'<span class="bi" style="--rs-l:{light};--rs-d:{dark}">{e(initial(name))}</span>'
        seats += (f'<a class="bn" href="#" title="{e(name, quote=True)}{" · " + how if how else ""}" '
                  f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{fig}'
                  f'<span class="bm">{e(name)}</span><span class="bw">{how}</span></a>')
    more = len(rows) - BENCH_MAX
    if more > 0:
        seats += f'<span class="bn more">+{more} more</span>'
    return f'<div class="dc-bench" aria-label="Not here lately">{seats}</div>'


BENCH_PIP = 30


def _scroll(html, rows):
    """Past ROW_CAP rows a view scrolls inside the card instead of growing
    the page: the header stays put and, after a render, the you-row is
    scrolled into view (keep_me_in_view_js). Under the cap nothing wraps,
    so small crews are untouched."""
    return f'<div class="dc-scroll">{html}</div>' if rows > ROW_CAP else html


# a deck row without a "+N today" line holds its place, filled when another
# row has one, so the rows stay evenly spaced (_even_rows, for the bars)
_DD_ROOM = "<!--dd-->"


def _even_bars(html):
    if 'class="dc-delta"' in html:
        return html.replace(_DD_ROOM, '<span class="dc-delta">&nbsp;</span>')
    return html.replace(_DD_ROOM, "")


def _bar(name, is_me, d, delta=None, today_labels=(), pip=None):
    """One person's progress through one shared deck. Three fills on one
    track: mature (solid), seen (faded), then unlocked-but-unseen (hatched) —
    so a deck worked through by unsuspending it a topic at a time shows how
    much is in play, not just a sliver of the whole. Everything is a percent
    of the person's own copy. The row's tooltip carries the exact numbers."""
    total = max(int(d.get("total") or 0), 1)
    seen, mature = int(d.get("seen") or 0), int(d.get("mature") or 0)
    pct = lambda n: min(100, round(100 * n / total))
    opened = d.get("open")
    open_html = ""
    if opened is not None:
        # the hatch starts where "seen" ends rather than lying under it: the
        # seen fill is translucent, and a hatch beneath it shows through
        # (caught by eye in the preview; the string tests couldn't see it)
        start = pct(seen)
        span = max(pct(int(opened)) - start, 0)
        open_html = f'<i class="fo" style="left:{start}%;width:{span}%;"></i>'
    counts = f'{seen:,} / {int(d.get("total") or 0):,}'
    ret = d.get("ret")
    if ret is not None:
        counts += f' &middot; {float(ret):.0f}%'
    chips = []
    # "today" is only true on the day it was written
    if d.get("today") and d.get("day") in today_labels:
        chips.append(f'+{int(d["today"]):,} today')
    if delta:
        chips.append(f'+{delta:,} wk')
    chip_html = (f'<span class="dc-delta">{" &middot; ".join(chips)}</span>' if chips else _DD_ROOM)
    tip = [f'{seen:,} seen', f'{mature:,} mature']
    if opened is not None:
        tip.append(f'{int(opened):,} unsuspended')
    tip.append(f'{int(d.get("total") or 0):,} total')
    if delta:
        tip.append(f'+{delta:,} this week')
    if ret is not None:
        tip.append(f'{float(ret):.1f}% retention, last 7 days')
    return (f'<div class="dr{" me" if is_me else ""}" title="{_html.escape(" · ".join(tip))}">'
            f'<span class="dn">{pip or ""}<b>{_html.escape(str(name))}</b></span>'
            f'<div class="dtrack">{open_html}<i class="fs" style="width:{pct(seen)}%;"></i>'
            f'<i class="fm" style="width:{pct(mature)}%;"></i></div>'
            f'<span class="dc-count"><span>{counts}</span>{chip_html}</span></div>')


def _presence_html(fresh, dormant, labels, entries, pick="", cfg=None):
    """The board in show-up mode: one view in place of Today and Week — a
    square per day, Monday to today, nothing to rank. Sorted by days showed
    up, then name; today is the last square, so who showed up today reads
    off the right-hand column. pick: Crew's views, in the header's corner
    (3.8.0), and "N showed up today" goes under the table."""
    days_of = {e["user_id"]: e.get("days") or {} for e in entries}
    week = list(reversed(week_labels(labels)))  # Monday first
    # sorted by what is on screen: squares lit this week, then name
    lit = lambda r: sum(1 for lb in week if _showed(days_of.get(r["user_id"], {}).get(lb)))
    fresh = sorted(fresh, key=lambda r: (-lit(r), r["name"].lower()))
    today_n = sum(1 for r in fresh if r.get("studied_today"))
    letters = ""
    for lb in week:
        cls = "sqh on" if lb == labels[0] else "sqh"
        letters += f'<th class="{cls}">{"MTWTFSS"[datetime.fromisoformat(lb).weekday()]}</th>'
    said = f"{today_n} showed up today"
    heads = (_corner(pick) if pick else f'<th class="lt" colspan="2">{said}</th>') + letters
    body = ""
    for row in fresh + dormant:
        fig, name = _who(row, cfg or {"sev": False})
        name = fig + name
        cls, note = ("you" if row["you"] else "") + (" sv" if fig else ""), ""
        if row["paused"]:
            cls += " dim"
            note = ' <span class="dc-note">&middot; on a break</span>'
        elif row["quiet"]:
            cls += " dim"
            txt, tone = _ago(row["last_updated"])
            note = f' <span class="la {tone}">({txt})</span>' if txt else ""
        elif row["stale"]:
            cls += " dim"
            note = ' <span class="la faded">&middot; yesterday</span>'
        elif row.get("away"):
            note = f' <span class="la faded">&#9992;&#65039; {_html.escape(str(row["away"]))}</span>'
        docs = days_of.get(row["user_id"], {})
        cells = "".join(
            '<td class="sqc"><i class="sq %s"></i></td>' % (
                "on" if _showed(docs.get(lb)) else "away" if (docs.get(lb) or {}).get("away") else "")
            for lb in week)
        body += (f'<tr class="{cls.strip()}"><td class="rk"></td>'
                 f'<td class="nm">{name}{note}</td>{cells}</tr>')
    return (_scroll(f'<table><tr>{heads}</tr>{body}</table>', body.count('<tr class='))
            + (f'<div class="dc-line dc-sum">{said}</div>' if pick else ""))


def _tricky_html(tricky, mine=None):
    """2.10: cards a crewmate flagged, listed only when I have the same note.
    3.5.0, K3: under their own headings, "Asked of you" (asks about cards
    I have down first) and "Your asks", each with where it stands. Their
    text is theirs, and a card's text is my own copy's: escaped."""
    out = ""
    asked = (tricky or [])[:6]
    if asked:
        out += '<div class="dc-flag-h">Asked of you</div>'
    for t in asked:
        who = _html.escape(str(t.get("name", "?")))
        text = _html.escape(str(t.get("text") or "a card"))
        deck = _html.escape(str(t.get("deck") or ""))
        cmd = f'tricktip:{t.get("uid", "")}:{int(t.get("index", 0))}'
        q = _html.escape(str(t.get("q") or ""))
        where = f'&ldquo;{text}&rdquo;{" &middot; " + deck if deck else ""}' + (" &middot; you have this down" if t.get("known") else "")
        say = (f'<b>{who}</b>: &ldquo;{q}&rdquo;' if q
               else f'<b>{who}</b> finds this one tricky') + f'<small>{where}</small>'
        out += (f'<div class="dc-flag"><span>{say}</span>'
                f'<a href="#" title="One line; it shows when the card comes up for them" '
                f'onclick="{_pycmd(cmd)}">Tip</a></div>')
    mine = (mine or [])[:6]
    if mine:
        out += '<div class="dc-flag-h">Your asks</div>'
    for a in mine:
        text = _html.escape(str(a.get("text") or "a card"))
        who = [_html.escape(str(w)) for w in a.get("who") or []]
        if a.get("state") == "answered":
            said = f'{who[0] if who else "A crewmate"} answered'
            tag = f'<span class="dc-ask-st on">{len(who) or 1} tip{"" if len(who) <= 1 else "s"}</span>'
        else:
            said = (f'{", ".join(who[:2])}{" and more" if len(who) > 2 else ""} '
                    f'{"knows" if len(who) == 1 else "know"} this') if who else "Nobody's answered yet"
            tag = ('<span class="dc-ask-st">waiting</span>'
                   + (f'<a href="#" title="Your crew stops seeing it" '
                      f'onclick="{_pycmd("unask:" + str(int(a["index"])))}">Take back</a>'
                      if isinstance(a.get("index"), int) else ""))
        out += f'<div class="dc-flag"><span>&ldquo;{text}&rdquo;<small>{said}</small></span>{tag}</div>'
    return out


def _decks_html(data, deltas=None, tricky=None, plans=None, mine=None, sticking=None, pick="", cfg=None):
    return _decks_body(data, deltas, sticking, pick, _tricky_html(tricky, mine), cfg)


# 3.7.1, I6: a key drawn like the bars, no words about hovering
_DKEY = '<span class="dkey"><i class="fm"></i>mature<i class="fs"></i>seen<i class="fo"></i>unsuspended</span>'


def _decks_body(data, deltas=None, sticking=None, pick="", asks="", cfg=None):
    """Crew › Decks: pick (Crew's views) on a line of its own, the key at its
    right when the bars come next (3.8.0, head row B); asks, the cards asked
    about, between them and the bars, with the key under the bars."""
    deltas = deltas or {}
    labels = data.get("labels") or []
    # a friend ahead of my timezone writes my "tomorrow" as their today
    today_labels = tuple(lb for lb in (labels[0] if labels else "", data.get("tomorrow")) if lb)
    groups, extras = build_deck_groups(data["entries"])
    # 3.9.10, one grid: each row's Pip and name on the left, where a crew row's are
    pips = {e.get("user_id"): row_sev(e, cfg) for e in data["entries"]} if cfg is not None else {}
    up = bool(pick) and not asks and bool(groups)
    top = f'<div class="dc-pline">{pick}{_DKEY if up else ""}</div>' if pick else ""
    if not groups:  # a friend's alone isn't drawn (extras, since 2.7): the way in
        return (top + asks + '<div class="dc-line">No shared decks yet. '
                f'<a href="#" onclick="{_pycmd("decks")}">Pick decks to share</a></div>')
    html = ""
    for g in groups:
        label = _html.escape(str(g["label"]))  # (3.9.10: no "How it's sticking" beside it; Insights has it)
        rows = "".join(
            _bar(n, me, d, deltas.get((uid, d.get("name", ""))), today_labels, pips.get(uid))
            for n, me, d, uid in g["rows"])
        html += f'<div class="dg"><div class="dgh">{label}</div>{rows}</div>'
    html = _scroll(_even_bars(html), sum(len(g["rows"]) for g in groups))
    if groups and not up:
        html += f'<div class="dc-line" style="padding-top: 2px;">{_DKEY}</div>'
    # 3.9.10: sharing another deck starts here, under the ones I share (never in the foot: it's this tab's alone)
    html += f'<div class="dc-add"><a href="#" title="Pick the decks your crew sees" onclick="{_pycmd("decks")}">+ Share a deck</a></div>'
    return top + asks + html
