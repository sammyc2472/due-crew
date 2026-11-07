"""You › Plans' week: seven small days, a day's assignments, a plan's notes.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import re as _re

from .base import _pycmd


def _segs(segments):
    """[(text, bold)] from plans.py, escaped."""
    return "".join(f"<b>{_html.escape(str(t))}</b>" if b else _html.escape(str(t)) for t, b in segments)


def _week_html(card, pid):
    """This week (or the one ‹ › moved to). Round five, Sam's pick A: seven
    small days, each its bar and what's left (amber when it's behind), a
    quiz's name under its day; the names are in a day's details, which open
    under the week on its click with every date it holds, whole (its
    topics, the authors' notes and lines, what's left, what you can do with
    it) and its quiz; the same click shuts them, another
    day's switches (motion.js 8 moves them in and out)."""
    e = _html.escape
    week = card.get("week") or []
    if not week:
        return ""
    off = int(card.get("week_offset") or 0)
    first = week[0]
    title = "This week" if off == 0 else f'Week of {int(first["num"])} {_mon(first["day"])}'
    # 3.6.5: Today sits between the arrows, always; greyed on this week
    nav = (f'<span class="nav"><a href="#" title="Last week" onclick="{_pycmd(f"planweek:{pid}:prev")}">&lsaquo;</a>'
           f'<a href="#" class="tb{"" if off else " here"}" onclick="{_pycmd(f"planweek:{pid}:0")}">Today</a>'
           f'<a href="#" title="Next week" onclick="{_pycmd(f"planweek:{pid}:next")}">&rsaquo;</a></span>')
    out = f'<div class="pwh"><b>{title}</b>{nav}</div>'
    cells, details = "", ""
    # 3.8.0: a day's details open on a click, or on the day Browse › Show on my plan asked for
    focus = card.get("focus")
    sel = next((i for i, d in enumerate(week) if d["day"] == focus), None) if focus else None
    for i, d in enumerate(week):
        did = f"dc-pd-{_re.sub(r'[^A-Za-z0-9]', '', pid)}-{i}"
        live = [u for u in d["units"] if u["state"] != "skip"]
        new, seen = int(d.get("new") or 0), int(d.get("seen") or 0)
        # 3.7.81: with the plan load counted, a day asks what's new to me (or left of it), not its whole
        size, ask = (int(d["size"]), int(d.get("ask") or 0)) if d.get("size") is not None else (None, 0)
        whole, left = (size, ask) if size is not None else (new, max(0, new - seen))
        if not live:
            n = "rest" if d["rest"] else ""
        elif d["past"]:
            n = f'<span class="late">{left:,}<span class="w"> left</span></span>' if left else "&#10003;"
        elif d["today"]:
            n = f'{left:,}<span class="w"> to go</span>' if left else "&#10003;"
        else:
            n = f'{left if size is not None else new:,}<span class="w"> new</span>' if (left if size is not None else new) else "nothing new"
        bar = ""
        if live and whole and (d["past"] or d["today"]):
            pct = max(0, min(100, round(100 * (whole - left) / whole)))
            bar = (f'<span class="wbar{" late" if d["past"] and left else ""}" title="{whole - left:,} of {whole:,}">'
                   f'<i style="width:{pct}%"></i></span>')
        else:  # its place kept, so every day's words sit on one line
            bar = '<span class="wbar no"></span>'
        evs = "".join(f'<span class="ev">{e(x)}</span>' for x in d["events"])
        has = bool(d["units"] or d["events"])
        cls = ("pc" + (" now" if d["today"] else " past" if d["past"] else "") + (" off" if d["rest"] else "")
               + (" ev1" if d["events"] else "") + (" sel" if i == sel else ""))
        # a click picks the day and shows its details (motion.js moves them in); again shuts them
        click = (f' onclick="var w=this.parentNode,o=this.classList.contains(\'sel\'),x=document.getElementById(\'{did}\');'
                 f'w.querySelectorAll(\'.pc\').forEach(function(c){{c.classList.remove(\'sel\');}});'
                 f'w.parentNode.querySelectorAll(\'.pday\').forEach(function(y){{y.hidden=true;}});'
                 f'if(!o){{this.classList.add(\'sel\');if(x)x.hidden=false;}}return false;"') if has else ""
        num = f'<span class="d"><span class="dow">{e(d["dow"])} </span><b>{int(d["num"])}</b></span>'
        cells += f'<div class="{cls}"{click}>{num}{bar}<span class="n">{n}</span>{evs}</div>'
        if has:
            details += (f'<div class="pday" id="{did}"{"" if i == sel else " hidden"}><div class="ph"><b>{e(d["dow"])} {int(d["num"])} '
                        f'{_mon(d["day"])}{" &middot; today" if d["today"] else ""}</b>{_day_line(d)}{_day_study(pid, d)}</div>'
                        + "".join(_day_unit(pid, u, d) for u in d["units"])
                        + "".join(_day_event(x) for x in d["events"]) + '</div>')
    return out + f'<div class="pwk">{cells}</div>{details}'


def _day_unit(pid, u, d):
    """A date in its day's details, whole: its name (moved, for or after its
    quiz), what's left, its bar, its topics with the authors' notes, the
    authors' lines (Watch, Read, Do), and what can be done with it: Browse
    its cards and the ones left, Open now, Move…, Skip it, Put it back,
    Undo skip; why it left cards shut. Its Study is the day's (3.9.6,
    _day_study), one way to it."""
    e = _html.escape
    uid, state = str(u["uid"]), u["state"]
    total, seen = int(u["total"]), int(u["seen"])
    tag = ' <span class="mv">&middot; moved</span>' if u.get("moved") else ""
    if u.get("ev"):  # 3.8.1: "for Heme quiz", or "after Heme quiz" (reinforcement)
        tag += f' <span class="mv">&middot; {e(str(u["ev"]))}</span>'
    if state == "skip":
        num = "skipped"
    elif u.get("ld"):
        num = _load_words(u["ld"], d["past"] or d["today"])
    elif state == "later":
        num = f"{total:,} new" if total else ""
    else:
        num = f"{seen:,} / {total:,}" if total else ""
    acts = []
    if total and state != "skip":
        acts.append(f'<a href="#" onclick="{_pycmd(f"planbrowse:{pid}:{uid}")}">Browse {total:,} card{"s" if total != 1 else ""}</a>')
    if state == "open" and 0 < seen < total:
        acts.append(f'<a href="#" onclick="{_pycmd(f"planleft:{pid}:{uid}")}">{total - seen:,} left</a>')  # 3.8.0
    if state == "later" or (state in ("open", "done") and u.get("shut")):
        # 3.8.1: a date whose cards are all shut again (Edit › Undo), or at my own pace not opened yet
        acts.append(f'<a href="#" onclick="{_pycmd(f"plannow:{pid}:{uid}")}">Open now</a>')
    if not d["past"] and state in ("later", "open"):  # 3.7.6: from today on, a date not done moves later on my copy
        acts.append(f'<a href="#" onclick="{_pycmd(f"planmove:{pid}:{uid}")}">Move&hellip;</a>')
    if state == "later":
        acts.append(f'<a href="#" onclick="{_pycmd(f"planskip:{pid}:{uid}")}">Skip it</a>')
    if u.get("moved"):
        acts.append(f'<a href="#" onclick="{_pycmd(f"planmoveback:{pid}:{uid}")}">Put it back</a>')
    if state == "skip":
        acts.append(f'<a href="#" onclick="{_pycmd(f"planunskip:{pid}:{uid}")}">Undo skip</a>')
    bar = _wbar(min(seen, total), total) if total and state in ("open", "done") else ""
    # 3.6.5, P7: what's in it, as the site's print list groups it; 3.8.0: each topic opens its cards in Browse
    what = "".join(f'<span class="g">{f"<b>{e(str(g))}</b> &middot; " if g else ""}'
                   + " &middot; ".join(_topic_a(pid, uid, x, i) for x, i in xs) + '</span>'
                   + _remark_lines(xs, u.get("rm"), "rm")  # 3.8.1: the authors' notes under it
                   for g, xs in (u.get("what") or []))
    what += _todo_lines(pid, uid, u.get("todo"))
    return (f'<div class="pu{" skip" if state == "skip" else ""}"><div class="r"><span class="u"><b>{e(u["name"])}</b>{tag}</span>'
            f'<span class="n">{num}</span></div>{bar}' + (f'<div class="wi">{what}</div>' if what else "")
            + (f'<div class="acts">{"".join(acts)}</div>' if acts else "") + _why_shut(pid, uid, u.get("why")) + '</div>')


def _todo_lines(pid, uid, todo):
    """The authors' lines on a date ("▶ Watch · lecture 14"), a link opening
    in the browser when there's one (Due's duelink, by the line's key)."""
    from ..due import TODO_KINDS, line_keys
    e = _html.escape
    todo = [x for x in todo or [] if isinstance(x, dict)]
    out = ""
    for td, key in zip(todo, line_keys(pid, uid, todo)):
        text = e(str(td.get("t") or ""))
        url = str(td.get("url") or "")
        if url.startswith("https://"):
            text = f'<a class="tp" href="#" title="{e(url)}" onclick="{_pycmd("duelink:" + key)}">{text}</a>'
        out += f'<span><b>{e(TODO_KINDS.get(td.get("k"), "Do"))}</b> &middot; {text}</span>'
    return out


def _day_event(name):
    """A quiz or exam on its day, by name (its Study for it is the card's
    quiz row under the week, one way to it)."""
    return f'<div class="pev"><span><b>{_html.escape(name)}</b></span></div>'


def _why_shut(pid, uid, why):
    """3.8.1, why didn't it open: under a date in the week, a quiet line when
    it left cards shut: its leeches (Browse) and picks this copy doesn't have."""
    lee, miss = int((why or {}).get("lee") or 0), int((why or {}).get("miss") or 0)
    bits = []
    if lee:
        bits.append(f'<a class="tp" href="#" title="Browse them" onclick="{_pycmd(f"planleech:{pid}:{uid}")}">'
                    f'{lee:,} leech{"es" if lee != 1 else ""}</a> stay{"s" if lee == 1 else ""} suspended')
    if miss:
        bits.append(f'{miss:,} pick{"s aren" if miss != 1 else " isn"}&rsquo;t in your copy')
    return f'<div class="pwhy">{" &middot; ".join(bits)}</div>' if bits else ""


def _day_study(pid, d):
    """3.9.6 (Sam: "study all for the day ... not just for today for past
    days too ... when you've clicked on one of the days"): the day's details
    have one Study, in their head: a Due Crew deck of what the day asks now,
    its sets' new cards not seen yet and theirs due today (today: every set
    of the plan's due today too), never a review ahead. On a day with a set
    opened here; a set's own Study is this one."""
    if not any(u["state"] in ("open", "done") and not u.get("shut") for u in d.get("units") or []):
        return ""
    tip = ("A filtered deck: today&rsquo;s new cards and what&rsquo;s due today in this plan" if d.get("today")
           else "A filtered deck: its new cards not seen yet and what&rsquo;s due of it today")
    return (f'<span class="acts"><a href="#" title="{tip}" '
            f'onclick="{_pycmd("planstudyday:" + pid + ":" + str(d["day"]))}">Study</a></span>')


def _day_line(d):
    """3.8.1, shared and mine: a day's details say what the plan opens that
    day apart from my own load ("opens 120 cards · you: 300 reviews due");
    today and ahead only."""
    if d.get("past"):
        return ""
    new, mine = int(d.get("new") or 0), int(d.get("mine") or 0)
    bits = ([f"opens {new:,} card{'s' if new != 1 else ''}"] if new else []) + (  # every card its dates match, not only new ones
        [f"you: {mine:,} review{'s' if mine != 1 else ''} due"] if mine else [])
    return f'<span class="pdl">{" &middot; ".join(bits)}</span>' if bits else ""


def _remark_lines(xs, rm, cls):
    """3.8.1: the authors' notes on a tag ([[i, text]], plans.topic_remarks)
    under the topic row that names it: xs, that row's [[name, i]]. Each note
    once; the authors' words, escaped."""
    at = {int(i) for _x, i in xs or []}
    texts = []
    for i, text in rm or []:
        if int(i) in at and str(text) not in texts:
            texts.append(str(text))
    return "".join(f'<span class="{cls}">&#9432; {_html.escape(t)}</span>' for t in texts)


def _topic_a(pid, uids, name, i):
    """3.8.0: a plan's topic as a link to its cards in Anki's browser."""
    return (f'<a class="tp" href="#" title="Browse its cards" '
            f'onclick="{_pycmd(f"plantopic:{pid}:{uids}:{int(i)}")}">{_html.escape(str(name))}</a>')


def _topic_go(pid, uids, name, i):
    """3.9.5 (Sam: "for the filtered decks opening from a plan especially need
    that option to browse or make the filtered deck"): a plan's topic on
    Today: its name shows its two ways beside it, Study (its new cards and
    the ones due today, a deck of its own) and Browse."""
    e = _html.escape
    tid = "dc-tp-" + _re.sub(r"[^A-Za-z0-9]", "", f"{pid}-{uids}") + f"-{int(i)}"
    # 3.9.5 (Sam: "they should underline and show that they are being selected"): the name stays
    # underlined while its two ways show; the one clicked stays marked
    pick = "this.parentNode.querySelectorAll('a').forEach(function(y){y.classList.remove('on')});this.classList.add('on');"
    return (f'<a class="tp dc-tpn" href="#" onclick="var x=document.getElementById(\'{tid}\');'
            f'if(x){{x.hidden=!x.hidden;this.classList.toggle(\'on\',!x.hidden);}}return false;">'
            f'{e(str(name))}</a><span class="du-tpgo" id="{tid}" hidden>'
            f'<a href="#" title="A filtered deck: its new cards and the ones due today" onclick="{pick}{_pycmd(f"plantopicstudy:{pid}:{uids}:{int(i)}")}">Study</a>'
            f'<a href="#" onclick="{pick}{_pycmd(f"plantopic:{pid}:{uids}:{int(i)}")}">Browse</a></span>')


def _load_words(ld, now):
    """A date in its details: today and before, seen of its cards; ahead,
    what will be new that day and what I'll have seen before it."""
    s_, o_, l_ = (int(x) for x in ld)
    tot = s_ + o_ + l_
    if now:
        return f"{s_:,} of {tot:,} seen"
    return f"{l_:,} of {tot:,} new" + (f" &middot; {s_ + o_:,} already seen or in your Anki" if s_ + o_ else "")


def _wbar(done, total):
    """The Plans tab's bars: their own class, so nothing else's .bar reaches them."""
    pct = 0 if not total else max(0, min(100, round(100 * int(done) / int(total))))
    return f'<span class="wbar" title="{int(done):,} of {int(total):,}"><i style="width:{pct}%"></i></span>'


def _mon(iso):
    try:
        return f"{_dt.date.fromisoformat(str(iso)):%b}"
    except ValueError:
        return ""


def _crew_line(card):
    """"Crew: 5 done with Chapter 1", for the latest open date anyone in my
    crew finished."""
    e = _html.escape
    for r in reversed(card.get("rows") or []):
        crew = r.get("crew") or [0, 0]
        if r.get("state") in ("open", "now") and int(crew[0] or 0):
            return f'Crew: {int(crew[0]):,} done with {e(str(r.get("name") or "?"))}'
    return ""


def _plan_notes(card, pid):
    """Everything the plan has to say beyond today and the week, most
    pressing first; the tab shows the first. Each carries its own action."""
    e = _html.escape
    s = card.get("session") or {}
    out = []
    ask = s.get("ask")
    if ask:
        days = [str(d) for d in ask.get("days") or []]
        when = " and ".join(_short(d) for d in days[-2:]) if len(days) <= 2 else f"{len(days)} study days"
        a2 = (f'<a href="#" onclick="{_pycmd("planspread:" + pid)}">Spread them (+{int(ask["spread"]):,} a day)</a>')
        if ask.get("push"):
            n = int(ask["push"])
            a2 += f'<a href="#" onclick="{_pycmd("planpush:" + pid)}">Push my dates back {n} day{"s" if n != 1 else ""}</a>'
        a2 += f'<a href="#" onclick="{_pycmd("planleave:" + pid)}">Leave them</a>'
        out.append(f'<div class="pn warn"><span>Missed <b>{e(when)}</b>: {int(ask["waiting"]):,} new waiting</span>'
                   f'<span class="acts">{a2}</span></div>')
    upd = card.get("update")
    if upd and int(upd.get("n") or 0):
        # 3.7.3: an author's update adds to today or earlier: nothing opens until I say
        n = int(upd["n"])
        names = [str(x) for x in upd.get("names") or []]
        what = " and ".join(f"<b>{e(x)}</b>" for x in names) if len(names) <= 2 else f"<b>{len(names)} sets</b>"
        who = e(str(card.get("owner_name") or "The plan"))
        lim = s.get("limit")
        over = (f' Anki shows {int(lim):,} new a day in this deck.'
                if lim is not None and int(s.get("target") or 0) + n > int(lim) else "")
        out.append(f'<div class="pn"><span>{who} added {n:,} card{"s" if n != 1 else ""} to {what}.{over}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planupdopen:" + pid)}">Open {n:,}</a>'
                   f'<a href="#" title="They open tomorrow morning" onclick="{_pycmd("planupdlater:" + pid)}">Not today</a></span></div>')
    if card.get("team_ask"):
        # 3.7.6: shared progress before the team and sharing were one choice: asked once
        out.append('<div class="pn"><span>Join this plan&rsquo;s squad? The others in it see your name and the days you '
                   'show up, and your progress counts for its authors.</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planteamjoin:" + pid)}">Join</a>'
                   f'<a href="#" onclick="{_pycmd("planteamno:" + pid)}">No thanks</a></span></div>')
    for post in (card.get("posts") or [])[:1]:
        # 3.7.3: the authors' words to followers, the newest unread
        out.append(f'<div class="pn post"><span><b>{e(str(post.get("name") or "?"))}</b>: {e(str(post.get("text") or ""))}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planpostok:" + pid)}">OK</a></span></div>')
    if card.get("change"):
        out.append(f'<div class="pn"><span>{_segs(card["change"])}</span>'
                   f'<a href="#" onclick="{_pycmd("planok:" + pid)}">OK</a></div>')
    tn = card.get("tag_news")
    if tn and tn.get("names"):
        # 3.8.0: the plan's own tags, on my notes since today
        more = int(tn.get("more") or 0)
        miss = int(tn.get("missing") or 0)
        names = ", ".join(e(str(x)) for x in tn["names"])
        out.append(f'<div class="pn"><span>New tags: <b>{names}</b>{f" and {more} more" if more else ""}.'
                   f'{f" {miss:,} of their notes aren&rsquo;t in your deck." if miss else ""}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plantags:" + pid)}">Browse them</a>'
                   f'<a href="#" onclick="{_pycmd("plantagsok:" + pid)}">OK</a></span></div>')
    lim, want = s.get("limit"), int(s.get("target") or 0)
    if s.get("paused_new") and want and s.get("kind") == "study":
        # 3.9.2's audit: Stop new cards runs here; Raise would undo it till tomorrow morning
        on_cmd = _pycmd("insaheadon:" + str(int(s["paused_new"])))
        out.append(f'<div class="pn"><span>New cards are stopped in this deck (You &rsaquo; Insights): today&rsquo;s {want:,} '
                   f'new {"card waits" if want == 1 else "cards wait"}.</span>'
                   f'<span class="acts"><a href="#" onclick="{on_cmd}">Turn them back on</a></span></div>')
    elif lim is not None and want > int(lim) and s.get("kind") == "study":
        out.append(f'<div class="pn warn"><span>Anki shows {int(lim):,} new a day in this deck; today has {want:,}.</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planlimit:" + pid)}">Raise to {want:,}</a></span></div>')
    fb = int(s.get("fell_back") or 0)
    if fb and not card.get("fallback_ok"):
        out.append(f'<div class="pn"><span>{fb} set{"s use tags" if fb != 1 else " uses a tag"} your deck names differently, '
                   f'matched by their cards.</span><span class="acts"><a href="#" onclick="{_pycmd("planidsok:" + pid)}">OK</a></span></div>')
    # 3.6.5: what the plan left shut here, said once (OK until it grows).
    # 3.8.0: the leeches are the deck's, so they're on Insights
    _lee, miss, of = (list(card.get("aside") or []) + [0, 0, 0])[:3]
    ok = (list(card.get("aside_ok") or []) + [0, 0])[:2]
    if miss and int(miss) > int(ok[1]):
        out.append(f'<div class="pn"><span>{int(miss):,} of {int(of):,} exact cards aren\u2019t in your deck.</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planasideok:" + pid)}">OK</a></span></div>')
    if card.get("catch"):
        c = card["catch"]
        out.append(f'<div class="pn"><span>Catching up: +{int(c.get("extra") or 0):,} new a day to {e(str(c.get("until") or ""))}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plancatchstop:" + pid)}">Stop</a></span></div>')
    # round five: what's behind is the card's own line (_plan_status), with Catch up…
    # round five: one Catch up… a card: the status line's when it says what's behind
    if int(card.get("waiting") or 0) and not card.get("catch") and not int((card.get("status") or {}).get("behind") or 0):
        w = int(card["waiting"])
        out.append(f'<div class="pn"><span><b>{w:,}</b> new from earlier days waiting</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plancatch:" + pid)}">Catch up&hellip;</a></span></div>')
    if card.get("put_off"):
        names = [str(n) for n in card["put_off"]]
        what = " and ".join(f"<b>{e(n)}</b>" for n in names) if len(names) <= 2 else f"<b>{len(names)} sets</b>"
        # 3.8.1: put off by Welcome back's Not today, they wait: tomorrow morning asks again
        when = (f'wait{"s" if len(names) == 1 else ""} for tomorrow morning' if card.get("put_off_ask")
                else f'open{"s" if len(names) == 1 else ""} tomorrow morning')
        out.append(f'<div class="pn"><span>{what} {when}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planputback:" + pid)}">Open now</a></span></div>')
    pf, qz = card.get("prep"), card.get("quiz")
    # 3.8.1: Study for a quiz says this, in what the plan says about now (_plan_now)
    if pf and not (qz and qz.get("day") == pf.get("day") and qz.get("name") == pf.get("name")):
        left = int(pf.get("left") or 0)
        what = (f'<b>{e(str(pf.get("name") or "?"))}</b> is today' if pf.get("today")
                else f'For <b>{e(str(pf.get("name") or "?"))}</b> on {e(str(pf.get("when") or ""))}'
                + (f' &middot; {left} more day{"s" if left != 1 else ""} of prep' if left else ""))
        out.append(f'<div class="pn"><span>{what}</span></div>')
    for kind, segments in card.get("lines") or []:
        if kind != "behind":
            out.append(f'<div class="pn"><span>{_segs(segments)}</span></div>')
    r = s.get("recap")
    if r:
        a, b = r.get("sessions") or [0, 0]
        out.append(f'<div class="pn"><span><b>Week {int(r["n"])} done</b>: {int(a)} of {int(b)} sessions, '
                   f'{int(r.get("new") or 0):,} new cards{", on track" if r.get("on_track") else ""}.</span></div>')
    for c in s.get("checks") or []:
        n, got = int(c.get("n") or 0), int(c.get("answered") or 0)
        if got >= n and n:
            out.append(f'<div class="pn"><span>Checkpoint <b>{e(str(c.get("name") or ""))}</b> done: '
                       f'<b>{int(c.get("right") or 0):,} of {n:,}</b> right first time.</span></div>')
        elif n:
            out.append(f'<div class="pn"><span>&#10003; Built <b>Checkpoint &middot; {e(str(c.get("name") or ""))}</b>: '
                       f'{n:,} cards you&rsquo;ve missed most. {got:,} done.</span></div>')
    return out


def _short(iso):
    try:
        d = _dt.date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"{d:%a}"
