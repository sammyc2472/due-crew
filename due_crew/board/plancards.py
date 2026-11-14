"""You › Plans: a plan's card, its path, Behind…, the joys, my own pace, plan offers.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
import re as _re

from .. import views as _views
from .. import plans as _P
from ..words import later as _later, t as _t, tn as _tn
from .base import _ins_dname, _pycmd
from .pip import PCREW_PIP, squad_pip
from .planweek import _crew_line, _plan_notes, _week_html
from .insights import _ins_day


def _plans_html(plans, people=None, cfg=None):
    """3.3: the plans, a card each; 3.5.0: with none, the ways in. Round
    five (Sam's pick 3): two or more, one at a time, their names a switch
    in the card's head (_plan_switch) with one Your plans…; the one shown
    is the plan Browse › Show on my plan jumped to, else this computer's
    pick (`plan_pick`), else the first."""
    cards = (plans or {}).get("cards") or []
    if not cards:
        return _plans_empty_html(plans)
    if len(cards) == 1:
        return _plan_card_html(cards[0], people, cfg)
    card = _picked_plan(cards, cfg)
    return _plan_card_html(card, people, cfg, head=_plan_switch(cards, card))


def _picked_plan(cards, cfg=None):
    """The plan You › Plans shows when there are two or more."""
    pick = (cfg or {}).get("plan_pick")
    return (next((c for c in cards if c.get("focus")), None)
            or next((c for c in cards if pick and str(c.get("id")) == str(pick)), None) or cards[0])


def _plan_switch(cards, card):
    """Round five, pick 3: the card's head with two or more plans: their
    names, the one shown pressed and an amber dot on any that's behind, its
    line ("week 3 of 9 · 6 following"), and Your plans… on it. A name two
    plans share shows their whole titles. The authors' words: escaped."""
    e = _html.escape
    names = [str(c.get("name") or str(c.get("title") or _t("Plan")).split(" · ")[0]) for c in cards]
    pills = ""
    for c, nm in zip(cards, names):
        word = nm if names.count(nm) == 1 else str(c.get("title") or nm)
        late = 0 if c.get("catch") else int((c.get("status") or {}).get("behind") or 0)
        dot = f'<i class="dot" title="{_t("{n} behind", n=f"{late:,}")}"></i>' if late else ""
        on = c is card
        pills += (f'<a href="#" class="{"on" if on else ""}" aria-pressed="{"true" if on else "false"}" '
                  f'title="{e(str(c.get("title") or nm))}" onclick="{_pycmd("planpick:" + str(c.get("id", "")))}">'
                  f'{e(word)}{dot}</a>')
    pid = str(card.get("id", ""))
    return (f'<div class="pk psk"><span class="psw">{pills}</span><span>{e(str(card.get("sub") or ""))}</span>'
            f'<span class="acts"><a class="pbt" href="#" title="{_t("Its weeks and sets, Insights, and your settings for it")}" '
            f'onclick="{_pycmd("planyours:" + pid)}">{_t("Your plans&hellip;")}</a></span></div>')


def _you_plans(plans, opened=None, people=None, cfg=None):
    """3.8.0, You › Plans: a plan offered to one of my squads, then each plan
    I follow; following none, the ways in. opened: this morning's line, here
    only when Due is off (it's under Today otherwise). Round five: no head
    row (3.9.3's Open plans and New plan ▾): each plan's Your plans…, and
    New plan in that window."""
    if opened and not opened.get("dates") and (plans or {}).get("opened_dates"):
        opened = dict(opened, dates=plans["opened_dates"])  # 3.8.1: its dates, as Due's Today has them
    return (_opened_line(opened) + _invite_lines((plans or {}).get("invites"))
            + _offer_banners((plans or {}).get("offers")) + _plans_html(plans, people, cfg)
            + _load_html((plans or {}).get("load")))


_LOAD_INK = ("var(--dc-accent)", "var(--dc-hours)", "var(--dc-fresh)", "var(--dc-ink)")


def _load_html(load):
    """3.9.9, the week across plans (plans.load_week), under the plan's
    card when two plans have something in the next seven days: a row a day,
    my reviews and each plan's new cards as one bar at my own pace, the
    day's time; a heavy day's line, with one press that moves its smallest
    set to the nearest day with room (my follow only), and Put it back after. Plan and
    set names are their authors': escaped."""
    if not load:
        return ""
    from .. import plans as P
    e = _html.escape
    ink = lambda i: _LOAD_INK[min(i, len(_LOAD_INK) - 1)]
    key = f'<span><i style="background:var(--dc-faded)"></i>{_t("Reviews due")}</span>' + "".join(
        f'<span><i style="background:{ink(i)}"></i>{e(p["name"])}</span>' for i, p in enumerate(load["plans"]))
    top = max(1, int(load.get("top") or 1))
    rows = ""
    for d in load["days"]:
        said = ", ".join([_t("{n} reviews", n=f'{d["rev"]:,}')] + [
            _t("{n} new in {plan}", n=f"{n:,}", plan=p["name"]) for n, p in zip(d["parts"], load["plans"]) if n])
        width = 100 * d["min"] / top
        inks = ["var(--dc-faded)"] + [ink(i) for i in range(len(d["parts"]))]
        segs = "".join(f'<i style="width:{width * sh:.1f}%;background:{c}"></i>' for sh, c in zip(d["share"], inks) if sh)
        rows += (f'<div class="lwd{" now" if d["today"] else ""}" title="{e(said)}"><span class="d">{e(_t(d["dow"]))} {int(d["num"])}</span>'
                 f'<span class="st">{segs}</span>'
                 f'<span class="n{" hv" if d["heavy"] else ""}">{P.load_time(d["min"]) if d["min"] else "&ndash;"}</span></div>')
    foot = ""
    back, hint = load.get("back"), load.get("hint")
    if back:
        cmd = _pycmd(f'planmoveback:{back["pid"]}:{back["uid"]}')
        foot += (f'<div class="lwh"><span>{_t("{name} moved to {day}.", name=e(back["name"]), day=e(P.day_said(back["day"])))}</span>'
                 f'<a href="#" onclick="{cmd}">{_t("Put it back")}</a></div>')
    if hint:
        day = _t("Today") if hint["day"] == load["days"][0]["day"] else P.weekday_or_day_said(hint["day"], load["days"][0]["day"])
        new, rev = f'{hint["new"]:,}', f'{hint["rev"]:,}'
        if hint["plans"] > 1:
            what = (_t("{n} new across {plans} plans on top of {rev} reviews.", n=new, plans=hint["plans"], rev=rev) if hint["rev"]
                    else _t("{n} new across {plans} plans.", n=new, plans=hint["plans"]))
        else:
            what = _t("{n} new on top of {rev} reviews.", n=new, rev=rev) if hint["rev"] else _t("{n} new.", n=new)
        mv = hint.get("move")
        link = ""
        if mv:
            cmd = _pycmd(f'planmoveto:{mv["pid"]}:{mv["uid"]}:{int(mv["n"])}')
            link = (f'<a href="#" title="{_t("Changes your days only, never the plan")}" onclick="{cmd}">'
                    + _t("Move {name} to {day}", name=e(mv["name"]),
                         day=e(P.weekday_or_day_said(mv["to"], load["days"][0]["day"]))) + '</a>')
        foot += (f'<div class="lwh"><span><b>{_t("{day} is heavy:", day=e(day))}</b> {what}</span>{link}</div>')
    note = (_t("Times use your own pace per card.") if load.get("known")
            else _t("Times use a typical pace until there's more of yours to read."))
    return (f'<div class="lw"><div class="pwh"><b>{_t("Everything this week")}</b></div><div class="lwk">{key}</div>{rows}{foot}'
            f'<div class="lwx">{note}</div></div>')


def _invite_lines(invites):
    """3.8.1: an invite to co-write a plan, or to keep one, a line each above
    the plans, with Yes and No. Names are the server's: escaped."""
    e = _html.escape
    out = ""
    for x in invites or []:
        pid, who, name = str(x.get("id", "")), e(str((x.get("by") or {}).get("name") or "?")), e(str(x.get("name") or _t("Plan")))
        who, name = f"<b>{who}</b>", f"<b>{name}</b>"
        said = (_t("{who} offered you {name} to keep.", who=who, name=name) if x.get("kind") == "owner"
                else _t("{who} asked you to co-write {name}. Its tags would go on your notes in Anki.", who=who, name=name))
        out += (f'<div class="dc-wrap inv"><span>&#128221;</span><span>{said}</span><span class="yn">'
                f'<a class="wc" href="#" onclick="{_pycmd(f"planinvite:{pid}:yes")}">{_t("Yes")}</a>'
                f'<a class="wc" href="#" onclick="{_pycmd(f"planinvite:{pid}:no")}">{_t("No")}</a></span></div>')
    return out


def _opened_dates(dates):
    """3.8.1: what the morning opened, by date: "Renal physiology 80 ·
    Antiarrhythmics 40", each name opening Browse on that date's new cards;
    four or more: the first two "and 2 more". Names are the author's:
    escaped here."""
    dates = [d for d in dates or [] if isinstance(d, (list, tuple)) and len(d) >= 4]
    if not dates:
        return ""
    shown = dates if len(dates) <= 3 else dates[:2]
    out = " &middot; ".join(
        f'<a class="tp" href="#" title="{_t("Browse its new cards")}" onclick="{_pycmd(f"planopened:{d[0]}:{d[1]}")}">'
        f'{_html.escape(str(d[2]))}</a> {int(d[3]):,}' for d in shown)
    return ": " + (_t("{sets} and {n} more", sets=out, n=len(dates) - len(shown)) if len(dates) > len(shown) else out)


def _opened_line(op):
    """3.8.0, from the plan's old Today box: what this morning opened, with
    Not today (its undo; 3.8.1, the name the update line's has) while that's
    still Anki's latest step. 3.8.1: by date, each a way to its new cards."""
    n = int((op or {}).get("n") or 0)
    if not n:
        return ""
    # 3.8.0: Sync now while AnkiWeb hasn't had them (a phone gets them from there)
    sync = (f'<a href="#" title="{_t("Anki&rsquo;s sync, so your phone has them")}" onclick="{_pycmd("plansync")}">{_t("Sync now")}</a>'
            if op.get("sync") else "")
    sets = _opened_dates(op.get("dates"))[2:]  # without its ": "
    if op.get("decks") and sets:  # Today's lesson, B: each lesson a deck of its own
        said = _P.tn("This morning opened {n} new card: {sets}, in your decks", "This morning opened {n} new cards: {sets}, in your decks",
                     n, sets=sets)
    elif op.get("decks"):
        said = _P.tn("This morning opened {n} new card, in your decks.", "This morning opened {n} new cards, in your decks.", n)
    elif sets:
        said = _P.tn("This morning opened {n} new card: {sets}", "This morning opened {n} new cards: {sets}", n, sets=sets)
    else:
        said = _P.tn("This morning opened {n} new card.", "This morning opened {n} new cards.", n)
    return (f'<div class="du-line"><span>{said}</span>'
            f'<span class="acts">{sync}<a href="#" title="{_t("They open tomorrow morning")}" onclick="{_pycmd("plannottoday")}">'
            f'{_t("Not today")}</a></span></div>')


def _plans_empty_html(plans=None):
    """3.5.0: the Plans tab with no plan. Plans, end to end (frame 1): a box
    for a plan's code or its link, with Follow (plan_flow's Follow, the code
    looked up); my exam, when Settings has one ahead and no plan I follow
    or write ends by it, with Plan the way there (a new plan finishing by
    it); and Make a plan and the library, with Your plans… when I write
    one. What's typed goes as typed (encoded: a link has its ':'), and
    Python reads the code from it."""
    e = _html.escape
    plans = plans or {}
    add = ("var v=(document.getElementById('dc-plancode').value||'').trim().slice(0,300);"
           "pycmd('duecrew:planfollowcode:'+encodeURIComponent(v)+'|'+window.dcBK);return false;")
    out = (f'<div class="dc-pways"><div class="pfw"><input id="dc-plancode" placeholder="{_t("A plan&rsquo;s code or link")}" '
           f'aria-label="{_t("A plan&rsquo;s code or link")}" onkeydown="if(event.key===\'Enter\'){{{add}}}">'
           f'<a class="pbt" href="#" onclick="{add}">{_t("Follow")}</a></div>')
    ex = plans.get("exam") or {}
    if ex.get("day") and int(ex.get("days") or 0) > 0:
        n = int(ex["days"])
        day = f'<b>{e(_ins_dname(ex["day"], long=True))}</b>'
        said = _t("Your exam: {day}, tomorrow", day=day) if n == 1 else _t("Your exam: {day}, in {n} days", day=day, n=f"{n:,}")
        out += (f'<div class="pwl"><span>{said}</span><span class="acts">'
                f'<a href="#" title="{_t("A new plan that finishes by then")}" onclick="{_pycmd("planopennew:" + str(ex["day"]))}">'
                f'{_t("Plan the way there")}</a></span></div>')
    yours = (f'<a href="#" title="{_t("Every plan you write or follow")}" onclick="{_pycmd("planyours")}">{_t("Your plans&hellip;")}</a>'
             if plans.get("writes") else "")
    return out + (f'<div class="pwl"><span class="mu">{_t("Or a plan of your own")}</span><span class="acts">'
                  f'<a href="#" onclick="{_pycmd("planopennew")}">{_t("Make a plan")}</a>{yours}'
                  f'<a href="#" onclick="{_pycmd("planlibrary")}">{_t("The library")} &#8599;</a></span></div></div>')


def _plan_card_html(card, people=None, cfg=None, head=None):
    """3.5.0, a plan I follow (You › Plans since 3.8.0). Round five: the
    plan's card, Your plans… its one button (its weeks and dates, Insights,
    my settings for it, where Plan ▾ and Open went), its day in a line
    (_plan_status), the week as seven small days whose click opens that
    day's dates whole under it (Sam's pick A: "when a day is clicked, the
    full assignments for that day open in that plans tab"), what it says
    about now (_plan_now: a quiz coming, cards at risk), one note at most,
    and the crew. head: the switch between plans in place of its name
    (_plan_switch). Plans, end to end (frame 16): the whole plan as a path
    above the week (_plan_path), and what's behind its own line with
    Behind… (_plan_behind), where Catch up… was. Plan, date and event names
    are the author's: escaped here."""
    _views.seen("plan", card)  # 3.9.12: its shape, checked as it's drawn (a slip is counted, and drawn anyway)
    e = _html.escape
    pid = str(card.get("id", ""))
    out = '<div class="dc-pc">' + (head or (
        f'<div class="pk"><b>{e(str(card.get("title") or _t("Plan")))}</b>'
        f'<span>{e(str(card.get("sub") or ""))}</span>'
        f'<span class="acts"><a class="pbt" href="#" title="{_t("Its weeks and sets, Insights, and your settings for it")}" '
        f'onclick="{_pycmd("planyours:" + pid)}">{_t("Your plans&hellip;")}</a></span></div>'))
    tabs = card.get("tabs") or {}
    if card.get("no_deck"):
        out += (f'<div class="dc-line">{_t("No deck here has this plan&rsquo;s cards yet.")} '
                f'<a href="#" onclick="{_pycmd("plandeck:" + pid)}">{_t("Pick a deck")}</a></div>')
    out += (_plan_path(card) + _exam_ask(card, pid) + _joy_line(card, pid) + _plan_status(card, pid) + _plan_slid(card, pid)
            + (_plan_line(card, pid) or _plan_behind(card, pid) or _joy_caught(card)) + _week_html(card, pid) + _plan_now(card, pid))
    notes = _plan_notes(card, pid)
    if notes:
        out += notes[0]
    crew = _squad_line(pid, tabs, people, cfg)
    if not crew:
        # 3.8.0: not in its squad: the crew who follow it, and the way in
        crew = _crew_line(card)
        if not card.get("team_ask"):
            join = f'<a href="#" onclick="{_pycmd(f"planteamjoin:{pid}:ask")}">{_t("Join its squad")}</a>'
            crew = f"{crew} &middot; {join}" if crew else join
    if crew:
        out += f'<div class="pcrew">{crew}</div>'
    return out + "</div>"


def _plan_status(card, pid):
    """Round five: the plan's day in a line, "93 to go today"; "" when
    today's dates are seen. Plans, end to end: what's behind is a line of
    its own (_plan_behind)."""
    togo = int((card.get("status") or {}).get("togo") or 0)
    if not togo:
        return ""
    lesson = card.get("lesson_deck") or {}  # Today's lesson, B: today's is a deck of its own
    act = ""
    if lesson.get("today"):
        uid = str(lesson["today"])
        act = (f'<a href="#" title="{_t("A filtered deck: today&rsquo;s set&rsquo;s new cards and its learning ones due now")}" '
               f'onclick="{_pycmd(f"planstudydate:{pid}:{uid}")}">{_t("Study")}</a>')
    # 3.9.6: the first morning says so all day, and Pip says let's go just after the words, once
    one = (card.get("joy") or {}).get("day1")
    first = f'<b class="jd1">{_t("Day one")}</b> &middot; ' if one else ""
    pip = (f'<span class="jgo" data-joy="go"{_joy_ago(one["ago"])}><span class="jgp" aria-hidden="true">{one["pip"]}</span></span>'
           if one and one.get("ago") is not None and one.get("pip") else "")
    said = (_t("{n} to go today, in your decks", n=f"<b>{togo:,}</b>") if lesson else _t("{n} to go today", n=f"<b>{togo:,}</b>"))
    return (f'<div class="pst"><span>{first}{said}</span>{pip}'
            + (f'<span class="acts">{act}</span>' if act else "") + '</div>')


PATH_WORDS = {"done": "d", "behind": "b", "catch": "c", "now": "t", "ahead": "a", "skip": "s"}


def _plan_path(card):
    """Plans, end to end (frame 16): the whole plan as a path, a segment a
    lesson in its order (done filled, behind amber, today outlined, ahead
    plain, skipped hollow), its last quiz or exam a small diamond at the
    end; under it the first lesson's day and the end's name and day. Each
    segment says its lesson on a hover, and its click opens the day it opens
    in the week below (3.9.6). While a catch-up runs, what it's
    catching up on isn't called behind (round five's rule): half filled. A
    long plan's segments close up (no gaps past 120). Names are the
    author's: escaped here."""
    e = _html.escape
    p = card.get("path") or {}
    ls = [x for x in p.get("lessons") or [] if isinstance(x, dict)]
    if not ls:
        return ""
    pid = _html.escape(str(card.get("id") or ""), quote=True) if _re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(card.get("id") or "")) else ""
    segs, n = "", {}

    def state(x):
        st = str(x.get("state") or "ahead")
        return "catch" if st == "behind" and card.get("catch") else st

    def jump(day):  # 3.9.6, after the last check: a click opens its day's details in the week below (plan_flow.jump_to)
        day = str(day or "")
        # 3.9.9: a button to the keyboard too: one stop for the whole path, the arrows walk it (page.KEYS_JS)
        return (f' role="button" tabindex="-1" data-rove="1" onclick="{_pycmd(f"planjump:{pid}:{day}")}"'
                if pid and _re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else "")

    keep = _path_keep(ls, p, card.get("joy"))
    pieces, i = 0, 0
    while i < len(ls):
        x, st = ls[i], state(ls[i])
        n[st] = n.get(st, 0) + 1
        if keep is not None and i not in keep and st in PATH_FOLD:
            j = i + 1
            while j < len(ls) and j not in keep and state(ls[j]) == st:
                n[st] += 1
                j += 1
            if j - i > 1:
                # Sam's pick A (a long plan): a run of sets that don't need me folds into one, with its count under it
                run, last = ls[i:j], j == len(ls)
                first, end = str(run[0].get("name") or "?"), str(run[-1].get("name") or "?")
                said = _t(PATH_FOLD[st], n=j - i)
                to = run[-1] if st == "done" else run[0]
                span = _t("{a} to {b}", a=e(first), b=e(end))
                segs += (f'<i class="run {PATH_WORDS.get(st, "a")}{" rl" if last else ""}" style="flex:{min(j - i, 8)} 1 0" '
                         f'title="{span} &middot; {said}" aria-label="{span}, {said}"{jump(to.get("opens"))}><span>{said}</span></i>')
                pieces += 1
                i = j
                continue
        left = f'{int(x.get("left") or 0):,}'
        word = {"done": _t("done"), "behind": _t("{n} left", n=left), "skip": _t("skipped"),
                "catch": _t("catching up &middot; {n} left", n=left),
                "now": _t("today &middot; {n} to go", n=left) if x.get("left") else _t("today")}.get(
            st, _ins_dname(x.get("opens"), long=True))
        cls = PATH_WORDS.get(st, "a") + (" t" if x.get("today") and st == "done" else "")
        play, inner = _joy_seg(card.get("joy"), str(x.get("uid") or ""), st)
        segs += f'<i class="{cls}" title="{e(str(x.get("name") or "?"))} &middot; {word}" aria-label="{e(str(x.get("name") or "?"))}, {word.replace(" &middot; ", ", ")}"{play}{jump(x.get("opens"))}>{inner}</i>'
        pieces += 1
        i += 1
    end = p.get("end") or {}
    ev = bool(end.get("event"))
    when = _ins_dname(end.get("day"), long=True)
    if ev:
        segs += f'<em title="{e(str(end.get("name") or _t("Exam")))} &middot; {when}"></em>'
    said = ", ".join(_t(w, n=n[k]) for k, w in PATH_SAID if n.get(k))
    if ev:
        said = _t("{sets}, then {name} on {day}", sets=said, name=e(str(end.get("name") or _t("Exam"))), day=when)
    gap = "" if pieces <= 30 else " g2" if pieces <= 60 else " g1" if pieces <= 120 else " g0"
    gap += " fold" if keep is not None else ""
    right = (f'{e(str(end.get("name") or _t("Exam")))} &middot; {when}' if ev else _t("Ends {day}", day=when) if when else "")
    segs = segs.replace(' tabindex="-1" data-rove', ' tabindex="0" data-rove', 1)  # the path's one stop
    return (f'<div class="ppath{gap}" role="group" aria-label="{_t("Sets: {sets}. Arrow keys move along them.", sets=said)}">{segs}</div>'
            f'<div class="ppl"><span>{_ins_dname(p.get("first"), long=True)}</span><span>{right}</span></div>')


PATH_FOLD_PAST = 16  # Sam's pick: a plan longer than this folds the sets that don't need me
PATH_FOLD = {"done": _later("{n} done"), "ahead": _later("{n} to come"), "skip": _later("{n} skipped")}
# the path said to a screen reader: how many sets in each state
PATH_SAID = (("done", _later("{n} done")), ("behind", _later("{n} behind")), ("catch", _later("{n} catching up")),
             ("now", _later("{n} today")), ("ahead", _later("{n} to come")), ("skip", _later("{n} skipped")))


def _path_keep(ls, p, joy=None):
    """Which sets a long path shows one by one (Sam's pick A, past
    PATH_FOLD_PAST sets), or None to show them all: every set behind (or
    catching up), the two before today's, today's, the next four, and any a
    joy plays on (its pop, caught up, a milestone's sparkle); runs of the
    rest fold, done, to come or skipped, each one piece with its count."""
    if len(ls) <= PATH_FOLD_PAST:
        return None
    at = next((i for i, x in enumerate(ls) if x.get("state") == "now"), None)
    if at is None:
        k = int((p or {}).get("at") or 0)
        at = max(0, min(len(ls) - 1, k - 1)) if k else 0
    keep = {i for i in range(at - 2, at + 5) if 0 <= i < len(ls)}
    keep |= {i for i, x in enumerate(ls) if x.get("state") == "behind"}
    joy = joy or {}
    hot = {str((joy.get("pop") or {}).get("uid") or ""), str((joy.get("line") or {}).get("uid") or "")}
    hot |= {str(u) for u in (joy.get("caught") or {}).get("uids") or []}
    keep |= {i for i, x in enumerate(ls) if str(x.get("uid") or "") in hot - {""}}
    return keep


def _joy_ago(ago):
    return f' style="--ago:{max(0.0, float(ago)):.2f}s"'


def _joy_seg(joy, uid, state):
    """3.9.6: a path segment playing one of the plan's joys (motion.js's
    joy): (its attributes, what goes in it). A set done pops ("pop"), Pip
    on it while it's out (still, then gone, with Reduce motion); what was
    behind turns the accent ("caught"); a milestone's set sparkles
    ("spark"). --ago: how long it's been out, so a redraw goes on from
    there. The glue says what plays (plan_flow.joy); Pip is sev.py's."""
    joy = joy or {}
    pop, line, caught = joy.get("pop") or {}, joy.get("line") or {}, joy.get("caught") or {}
    if state != "done" or not uid:
        return "", ""
    if pop.get("uid") == uid and pop.get("ago") is not None:
        pip = f'<span class="jpp" aria-hidden="true">{pop["pip"]}</span>' if pop.get("pip") else ""
        return f' data-joy="pop"{_joy_ago(pop["ago"])}', pip
    if caught.get("ago") is not None and uid in (caught.get("uids") or []):
        return f' data-joy="caught"{_joy_ago(caught["ago"])}', ""
    if line.get("ago") is not None and line.get("key") in ("half", "threeq") and line.get("uid") == uid:
        return f' data-joy="spark"{_joy_ago(line["ago"])}', ""
    return "", ""


def _joy_line(card, pid):
    """3.9.6: the plan's line about where it's got to, under the path: a
    milestone today (halfway, three-quarters, the last set), with Share and
    × (gone for today, as it would be tomorrow); or, every set done, the
    finish line, with Share, for as long as I follow it. The plan's and
    set's names are the author's: escaped here."""
    e = _html.escape
    j = card.get("joy") or {}
    share = lambda key: (f'<a href="#" title="{_t("As text or a picture")}" '  # noqa: E731
                         f'onclick="{_pycmd(f"planjoyshare:{pid}:{key}")}">{_t("Share")}</a>')
    if j.get("fin"):
        return (f'<div class="pst jfin"><span><b>{_t("Finished")}</b> &middot; {e(str(j["fin"].get("words") or ""))}</span>'
                f'<span class="acts">{share("fin")}</span></div>')
    ln = j.get("line") or {}
    key = ln.get("key")
    if key not in ("half", "threeq", "last"):
        return ""
    name = e(str(card.get("name") or _t("the plan")))
    words = (_t("Halfway through {name}", name=name) if key == "half" else _t("Three-quarters through {name}", name=name)
             if key == "threeq" else _t("The last set of {name}", name=name))
    sub = (_t("{name}, today", name=e(str(ln.get("name") or ""))) if key == "last"
           else _t("{n} of {of} sets", n=f'{int(ln.get("n") or 0):,}', of=f'{int(ln.get("of") or 0):,}'))
    play = f' data-joy="line"{_joy_ago(ln["ago"])}' if ln.get("ago") is not None else ""
    return (f'<div class="pst jml"{play}><span><b>{words}</b> &middot; {sub}</span><span class="acts">{share(key)}'
            f'<a class="jx" href="#" title="{_t("Not now")}" onclick="{_pycmd(f"planjoyx:{pid}:{key}")}">&times;</a></span></div>')


def _joy_caught(card):
    """3.9.6: Behind cleared, its line says so for the rest of the day, every
    time: "Caught up · 2 · Inflammation, all 101 seen", a small 🎉 that pops
    once. The set's name is the author's: escaped here."""
    c = (card.get("joy") or {}).get("caught") or {}
    if not c.get("uids"):
        return ""
    more = int(c.get("more") or 0)
    name = _html.escape(str(c.get("name") or "?"))
    name = _t("{name} and {n} more", name=name, n=more) if more else name
    play = f' data-joy="tada"{_joy_ago(c["ago"])}' if c.get("ago") is not None else ""
    seen = _t("{name}, all {n} seen", name=name, n=f'{int(c.get("n") or 0):,}')
    return (f'<div class="pst jcu"><span><b>{_t("Caught up")}</b> &middot; {seen}</span>'
            f'<span class="acts"><span class="jta" aria-hidden="true"{play}>&#127881;</span></span></div>')


def _exam_ask(card, pid):
    """3.9.9 (Sam's pick B, "Exams and Limits"): the plan's exam, asked once:
    Make it mine (my exam, the crew's countdown, the good-luck card) or Not
    now. Moved since I made it mine: Move mine, or keep my day. The exam's
    name is the author's: escaped here (plans.exam_offer)."""
    a = card.get("exam_ask")
    if not a:
        return ""
    e = _html.escape
    day = e(_ins_dname(a["day"], long=True))
    yes, no = _pycmd(f"planexam:yes:{pid}"), _pycmd(f"planexam:no:{pid}")
    if a.get("was"):
        return (f'<div class="pst pex"><span>{_t("{name} moved to {day}. Move your exam too?", name=e(a["ename"]), day=f"<b>{day}</b>")}</span>'
                f'<span class="acts"><a href="#" onclick="{yes}">{_t("Move mine")}</a>'
                f'<a href="#" onclick="{no}">{_t("Keep {day}", day=e(_ins_dname(a["was"], long=True)))}</a></span></div>')
    return (f'<div class="pst pex"><span>{_t("{name} is {day}. Make it your exam?", name=e(a["ename"]), day=f"<b>{day}</b>")}</span>'
            f'<span class="acts"><a href="#" title="{_t("Your exam in Settings: the countdown your crew sees, and the good-luck card")}" '
            f'onclick="{yes}">{_t("Make it mine")}</a><a href="#" onclick="{no}">{_t("Not now")}</a></span></div>')


def _plan_slid(card, pid):
    """Slide on Behind…, today: the line that says so, with its Undo (the
    way back on the same screen)."""
    n = int(card.get("slid") or 0)
    if n <= 0:
        return ""
    return (f'<div class="pst"><span>{_tn("Your dates moved {n} day later", "Your dates moved {n} days later", n)}</span>'
            f'<span class="acts"><a href="#" title="{_t("Your dates back where they were")}" '
            f'onclick="{_pycmd("planunslide:" + pid)}">{_t("Undo")}</a></span></div>')


def _plan_behind(card, pid):
    """Plans, end to end (frame 18): what's behind, one line, "Behind · 2 ·
    Inflammation, 31 left", with Behind… (the sheet: Slide, Fit it in, Skip
    what's left; plan_board.behind). None while a catch-up runs (its own
    note says so) or while 3.2's missed-days question is up (it has its
    own three ways). The lesson's name is the author's: escaped here."""
    b = card.get("behind") or {}
    if not b.get("left") or card.get("catch") or (card.get("session") or {}).get("ask"):
        return ""
    more = int(b.get("more") or 0)
    name = _html.escape(str(b.get("name") or "?"))
    name = _t("{name} and {n} more", name=name, n=more) if more else name
    left = _t("{name}, {n} left", name=name, n=f'{int(b["left"]):,}')
    return (f'<div class="pst pbh"><span class="late">{_t("Behind")} &middot; {left}</span>'
            f'<span class="acts"><a href="#" title="{_t("Slide your dates, fit it in, or skip what&rsquo;s left")}" '
            f'onclick="{_pycmd("planbehind:" + pid)}">{_t("Behind&hellip;")}</a></span></div>')


def _plan_line(card, pid):
    """3.9.10, catching up (Sam's: "the options should be study or
    ignore"), in Behind's place: each day owed a row, oldest first, with
    Study (its deck; a day that waited opens first) and Ignore (the
    follow's skip; the week has Undo skip); today's set, waiting, under
    them. The week stays below. Names are the author's: escaped here."""
    ln = card.get("line") or {}
    rows = ln.get("rows") or []
    if not rows:
        return ""
    e = _html.escape
    n, left = len(rows), int(ln.get("left") or 0)
    out = (f'<div class="pln"><div class="plh"><span><b>{_t("Catching up")}</b> &middot; '
           f'{_tn("{n} day, {new} new", "{n} days, {new} new", n, new=f"{left:,}")}</span>'
           f'<span class="acts"><a href="#" title="{_t("Open each day as it comes again")}" onclick="{_pycmd("planlineoff:" + pid)}">'
           f'{_t("Don&rsquo;t wait")}</a></span></div>')
    for i, r in enumerate(rows):
        uid = str(r.get("uid") or "")
        seen = int(r.get("total") or 0) - int(r.get("left") or 0)
        count = (_t("{n} left", n=f'{int(r.get("left") or 0):,}') if r.get("opened") and seen > 0
                 else _t("{n} new", n=f'{int(r.get("left") or 0):,}'))
        out += (f'<div class="plr"><span class="d">{e(str(r.get("when") or ""))}</span><b>{e(str(r.get("name") or "?"))}</b>'
                f'<span class="n">{count}</span>'
                f'<a class="go{" on" if i == 0 else ""}" href="#" title="{_t("A deck of its new cards")}" onclick="{_pycmd(f"planlinestudy:{pid}:{uid}")}">{_t("Study")}</a>'
                f'<a class="ig" href="#" title="{_t("Leave it out. The week has Undo skip.")}" onclick="{_pycmd(f"planskip:{pid}:{uid}")}">{_t("Ignore")}</a></div>')
    for r in ln.get("next") or []:
        waits = _t("{n} new &middot; waiting", n=f'{int(r.get("total") or 0):,}')
        out += (f'<div class="plr wait"><span class="d">{_t("Today")}</span><b>{e(str(r.get("name") or "?"))}</b>'
                f'<span class="n">{waits}</span></div>')
    return out + "</div>"


def _plan_now(card, pid):
    """3.8.0: what the plan's Today box said that Today, the tab beside it,
    doesn't: that it's paused, a day with no new cards, and the next
    exam's cards at risk (card["ins"], from Insights), with Study."""
    e = _html.escape
    if card.get("paused"):
        return (f'<div class="pn"><span>{_t("No new cards while it&rsquo;s paused.")}</span>'
                f'<span class="acts"><a href="#" onclick="{_pycmd("planresume:" + pid)}">{_t("Resume now")}</a></span></div>')
    out = _own_html(card.get("own"), pid) if card.get("own") else ""
    out += _quiz_line(card, pid)
    kind = (card.get("session") or {}).get("kind")
    if kind in ("rest", "catchup", "taper"):
        word = (_t("Today is a rest day: reviews, and no new cards.") if kind == "rest"
                else _t("Today is in its catch-up week: reviews, and no new cards.") if kind == "catchup"
                else _t("Today is in its taper: reviews, and no new cards."))
        out += f'<div class="pn"><span>{word}</span></div>'
    ins = card.get("ins") or {}
    n = int(ins.get("n") or 0)
    if n and ins.get("did"):
        did = int(ins["did"])
        wd, dn = _ins_day(ins.get("day"))
        when = (_t("{name} on {day}", name=f'<b>{e(str(ins["name"]))}</b>', day=f"{wd} {dn}") if ins.get("name") else f"{wd} {dn}")
        cards = (f'<a class="tp" href="#" title="{_t("Browse them")}" onclick="{_pycmd(f"insbrowse:{did}:h")}">'
                 f'{_P.tn("{n} card", "{n} cards", n)}</a>')
        out += (f'<div class="pn"><span>{_t("{cards} Anki won&rsquo;t show you before {when}", cards=cards, when=when)}</span>'
                # 3.9.5 (Sam's FSRS rule): a deck only before a date
                + (f'<span class="acts"><a href="#" title="{_t("A filtered deck of them, the most missed first")}" '
                   f'onclick="{_pycmd(f"insstudy:{did}:h")}">{_t("Study {n}", n=f"{n:,}")}</a></span>'
                   if ins.get("name") else "") + '</div>')
    return out


def _quiz_line(card, pid):
    """3.8.1 (plans, rethought), Study for a quiz: from three days out, the
    event, its prep days left, the cards its dates opened here, and Study for
    it (one deck of them, the shakiest first). The event's name is the
    author's: escaped here."""
    qz = card.get("quiz")
    if not qz:
        return ""
    e = _html.escape
    pf = card.get("prep") or {}
    left = int(pf.get("left") or 0) if pf.get("day") == qz.get("day") and pf.get("name") == qz.get("name") else 0
    n = int(qz.get("open") or 0)
    name = f'<b>{e(str(qz.get("name") or "?"))}</b>'
    what = _t("For {name} today", name=name) if qz.get("today") else _t("For {name} on {day}", name=name, day=e(str(qz.get("when") or "")))
    return (f'<div class="pn"><span>{what}'
            + (' &middot; ' + _tn("{n} more day of prep", "{n} more days of prep", left) if left else "")
            + ' &middot; ' + _P.tn("{n} card open from its sets", "{n} cards open from its sets", n) + '</span>'
            f'<span class="acts"><a href="#" title="{_t("A filtered deck: its sets&rsquo; open cards, the shakiest first")}" '
            f'onclick="{_pycmd(f"planquiz:{pid}:" + str(qz.get("id") or ""))}">{_t("Study for it")}</a></span></div>')


def _own_html(ow, pid):
    """3.8.0, at my own pace: Up next with Open and Open and study, what
    follows, the last step's Undo (or Put back). No Behind; 3.9.10: what's
    open and not finished as rows (Study, Ignore), and no line measuring me
    against the plan's dates. Names are the author's:
    escaped here."""
    e = _html.escape
    out = ""
    rows = ow.get("open") or []
    if rows:  # 3.9.10: what I opened and haven't finished, as the line on a dated plan: Study or Ignore
        left = sum(int(r.get("left") or 0) for r in rows)
        out += (f'<div class="pln"><div class="plh"><span><b>{_t("Open")}</b> &middot; '
                f'{_tn("{n} set, {new} new", "{n} sets, {new} new", len(rows), new=f"{left:,}")}</span></div>')
        for i, r in enumerate(rows):
            uid = str(r.get("uid") or "")
            new = _t("{n} new", n=f'{int(r.get("left") or 0):,}')
            out += (f'<div class="plr"><b>{e(str(r.get("name") or "?"))}</b><span class="n">{new}</span>'
                    f'<a class="go{" on" if i == 0 else ""}" href="#" title="{_t("A deck of its new cards")}" onclick="{_pycmd(f"planstudydate:{pid}:{uid}")}">{_t("Study")}</a>'
                    f'<a class="ig" href="#" title="{_t("Leave it out. The week has Undo skip.")}" onclick="{_pycmd(f"planskip:{pid}:{uid}")}">{_t("Ignore")}</a></div>')
        out += "</div>"
    out += '<div class="pnx">'
    nx = ow.get("next")
    if nx:
        n = int(nx.get("n") or 0)
        out += (f'<div class="nx"><span class="nx1"><span class="lbl">{_t("Up next")}</span> <b>{e(str(nx.get("name") or "?"))}</b>'
                + (f' <small>{_t("{n} new", n=f"{n:,}")}</small>' if n else "") + '</span>'
                f'<span class="nx2"><a class="bt" href="#" onclick="{_pycmd("planpaceopen:" + pid)}">{_t("Open")}</a>'
                f'<a class="bt2" href="#" onclick="{_pycmd("planpacestudy:" + pid)}">{_t("Open and study")}</a></span></div>')
        then, more = ow.get("then") or [], int(ow.get("more") or 0)
        items = ow.get("then_items") or []
        if items:
            # 3.8.1: any date after Then opens now, ahead of the rest (and says so, with its Undo)
            then = []
            for x in items:
                go = _pycmd(f"planpaceopen:{pid}:{x.get('uid') or ''}")
                then.append(f'<a class="nx3" href="#" title="{_t("Open it now, ahead of the rest")}" onclick="{go}">'
                            f'{e(str(x.get("name") or "?"))}</a> {int(x.get("n") or 0):,}')
        else:
            then = [e(str(x)) for x in then]
        if then:
            sets = " &middot; ".join(then + ([_t("{n} more", n=f"{more:,}")] if more else []))
            out += f'<div class="pq">{_t("Then {sets}", sets=sets)}</div>'
    else:
        out += f'<div class="pq">{_t("Every set of it is open.")}</div>'
    if ow.get("last"):
        out += (f'<div class="pnl">{e(str(ow["last"]))} '
                f'<a href="#" onclick="{_pycmd("planpaceundo:" + pid)}">{_t("Undo")}</a></div>')
    elif ow.get("back"):
        b = ow["back"]
        put, unseen = _t("Put back {name}", name=e(str(b.get("name") or "?"))), _t("{n} not seen yet", n=f'{int(b.get("n") or 0):,}')
        out += (f'<div class="pq"><a href="#" onclick="{_pycmd("planpaceback:" + pid)}">{put}</a>'
                f' &middot; {unseen}</div>')
    return out + "</div>"


def _squad_line(pid, tabs, people=None, cfg=None):
    """3.8.0, the Plan tab's line about the plan's squad: faces, how many
    showed up, and the way there (the newest question from someone else
    when there is one). "" when I'm not in it. 3.8.22 (Sam: "under squad we
    haven't switched to pips"): who showed up are their Pips, as on the
    Squads tab (squad_pip: mine and a crewmate's in colour and look, anyone
    else plain), from the uids beside their emojis (who); Pip off, or a
    server without them, the emojis. people: {uid: crew entry}, mine too."""
    e = _html.escape
    s = tabs.get("summary")
    if not s:
        return ""
    emojis, who, people = s.get("faces") or [], s.get("who") or [], people or {}
    pips = [squad_pip(u, (people.get(u) or {}).get("name") or _t("A squadmate"), (people.get(u) or {}).get("you"),
                      people, cfg, PCREW_PIP, k)
            for k, u in enumerate(who[:len(emojis)])] if cfg is not None and len(who) >= len(emojis) else []
    faces = (f'<span class="pips">{"".join(pips)}</span>' if pips and all(pips)
             else "".join(e(str(x)) for x in emojis))
    n, of = int(s.get("shown") or 0), int(s.get("of") or 0)
    out = f'{faces} ' + _t("Squad: {n} of {of} showed up", n=n, of=of) if n else _t("Squad: {n} in it", n=of)
    last, unread = s.get("last"), int(tabs.get("unread") or 0)
    go = (_t("{name} asked", name=e(str(last.get("name") or "?"))) if last and unread
          else _t("{n} new", n=unread) if unread else _t("Open"))
    return out.strip() + f' &middot; <a href="#" onclick="{_pycmd(f"squadplan:{pid}")}">{go} &rsaquo;</a>'


def _team_ago(at, now=None):
    import time as _time
    d = max(0, int((now or _time.time()) - int(at or 0)))
    if d < 60:
        return _t("now")
    if d < 3600:
        return _t("{n}m", n=d // 60)
    if d < 86400:
        return _t("{n}h", n=d // 3600)
    return _t("yesterday") if d < 2 * 86400 else _t("{n}d", n=d // 86400)


def _offer_banners(offers):
    """3.1: a plan offered to one of my squads. Names escaped."""
    e = _html.escape
    out = ""
    for o in offers or []:
        oid = str(o.get("id", ""))
        out += ('<div class="dc-wrap"><span>&#128197;</span>'
                + '<span>' + _t("{who} offered {squad} a plan: {name}", who=f'<b>{e(str(o.get("owner") or "?"))}</b>',
                                squad=e(str(o.get("squad") or "")), name=e(str(o.get("name") or ""))) + '</span>'
                f'<a class="wc" href="#" onclick="{_pycmd("planlook:" + oid)}">{_t("Look")}</a>'
                f'<a class="wx" href="#" title="{_t("Not now")}" onclick="{_pycmd("planofferx:" + oid)}">&times;</a></div>')
    return out
