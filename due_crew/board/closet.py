"""Pip's closet: what I wear, what I can earn, the board's line about it.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
from datetime import date as _date

from ..logo import board_mark
from .. import closet as _closet
from .. import sev as _sev

from .base import _pycmd
from .style import _css
from .pip import SEV_CSS
from .settings import SETTINGS_CSS, _accent_swatches, _st_click


# ---- 3.8.2: Pip's closet ----

CLOSET_TABS = ("Yours", "To earn")
# the places on Pip, top to bottom, as the closet lists them; a costume over them all
CLOSET_PLACES = ("head", "face", "body", "hand", "back")
PLACE_NAMES = {"head": "Head", "face": "Face", "body": "Body", "hand": "Hand", "back": "Back", _closet.COSTUME: "Costume"}

CLOSET_CSS = """
    #due-crew.dc-closet { text-align: left; }
    #due-crew .cl-wrap { display: grid; grid-template-columns: 176px minmax(0, 1fr); gap: 16px; align-items: start; }
    @media (max-width: 560px) { #due-crew .cl-wrap { grid-template-columns: minmax(0, 1fr); } }
    #due-crew .cl-me { display: grid; gap: 8px; position: sticky; top: 6px; }
    #due-crew .cl-fig { width: 100%; display: grid; place-items: end center; padding: 20px 0 6px; border-radius: 12px;
      background: var(--dc-you-bg); }
    #due-crew .cl-fig svg.sv { width: 124px; height: 124px; }
    /* what's on, place by place: the one list of it */
    #due-crew .cl-ons { display: grid; gap: 1px; font-size: 12px; }
    #due-crew .cl-o { display: grid; grid-template-columns: 62px minmax(0, 1fr); align-items: baseline; gap: 4px;
      padding: 3px 6px; border-radius: 7px; min-height: 18px; }
    #due-crew .cl-o > span:first-child { font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
      color: var(--dc-muted); }
    #due-crew .cl-o button { font: inherit; font-weight: 700; color: var(--dc-ink); background: none; border: 0; padding: 0;
      margin: 0; box-shadow: none; cursor: pointer; text-align: left; border-radius: 0; }
    #due-crew .cl-o button::after { content: " \\00d7"; color: var(--dc-muted); font-weight: 400; }
    #due-crew .cl-o button:hover { color: var(--dc-accent); }
    #due-crew .cl-o i { font-style: normal; color: var(--dc-faded); }
    #due-crew .cl-o.cos { background: var(--dc-you-bg); }
    #due-crew .cl-ons.covered .cl-o:not(.cos) { opacity: .5; }
    #due-crew .cl-col { display: grid; gap: 5px; font-size: 12px; font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid var(--dc-line); }
    #due-crew .cl-col small { font-weight: 400; color: var(--dc-muted); margin-left: 4px; }
    #due-crew .cl-col .st-sw { flex-wrap: wrap; padding: 2px 3px; }
    #due-crew .cl-msg { font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .cl-msg:empty { display: none; }
    #due-crew .cl-msg b { color: var(--dc-ink); }
    #due-crew .cl-n { font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .cl-main { display: grid; gap: 14px; min-width: 0; }
    #due-crew .cl-sec { display: grid; gap: 6px; }
    #due-crew .cl-sec h4 { margin: 0; font-size: 10.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
      color: var(--dc-muted); display: flex; gap: 6px; align-items: baseline; }
    #due-crew .cl-sec h4 small { font-weight: 400; letter-spacing: 0; text-transform: none; }
    #due-crew .cl-next { font-size: 11.5px; color: var(--dc-muted); padding: 2px 0 4px; }
    #due-crew .cl-near { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 6px; }
    #due-crew .cl-nr { display: flex; gap: 6px; align-items: center; border: 1px solid var(--dc-line); border-radius: 9px;
      padding: 3px 8px 3px 2px; font-size: 11.5px; min-width: 0; }
    #due-crew .cl-nr > span:last-child { display: grid; gap: 2px; min-width: 0; flex: 1; }
    #due-crew .cl-nr small { color: var(--dc-muted); font-size: 10.5px; }
    #due-crew .cl-bar { display: block; height: 4px; border-radius: 99px; background: var(--dc-line); overflow: hidden; }
    #due-crew .cl-bar i { display: block; height: 100%; background: var(--dc-accent); border-radius: 99px; }
    #due-crew .cl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(86px, 1fr)); gap: 6px; }
    #due-crew .cl-grid.lk { grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); }
    /* a thing of mine: plain until it's on; on is the accent, filled, and says so */
    #due-crew .cl-t { display: grid; justify-items: center; align-content: start; gap: 1px; padding: 8px 3px 7px; border-radius: 10px;
      border: 1px solid var(--dc-line); background: var(--dc-bg); color: var(--dc-ink); font: inherit; cursor: pointer;
      position: relative; text-align: center; margin: 0; box-shadow: none; }
    #due-crew button.cl-t:hover { border-color: var(--dc-accent); }
    #due-crew .cl-t b { font-size: 11.5px; line-height: 1.2; }
    #due-crew .cl-t small { font-size: 10px; color: var(--dc-muted); line-height: 1.25; }
    #due-crew .cl-t small.w { color: var(--dc-hours); font-weight: 700; }
    #due-crew .cl-t .cl-f { height: 40px; display: grid; place-items: end center; margin-bottom: 3px; }
    #due-crew .cl-t.on { border: 2px solid var(--dc-accent); padding: 7px 2px 6px; background: var(--dc-you-bg); }
    #due-crew .cl-t.on b { color: var(--dc-accent); }
    #due-crew .cl-t.under { border: 1px dashed var(--dc-accent); }
    #due-crew .cl-badge { position: absolute; top: 4px; right: 4px; font-size: 9px; font-weight: 800; line-height: 1;
      padding: 3px 5px; border-radius: 99px; background: var(--dc-accent); color: var(--dc-accent-ink); letter-spacing: .02em; }
    #due-crew .cl-badge.u { background: var(--dc-well); color: var(--dc-muted); }
    #due-crew .cl-badge.n { right: auto; left: 4px; background: var(--dc-hours); color: var(--dc-bg); }
    /* one still to earn: no click, greyed, what it needs */
    #due-crew .cl-t.lk { cursor: default; background: var(--dc-well); border-color: transparent; }
    #due-crew .cl-t.lk .cl-f { filter: grayscale(1); opacity: .38; }
    #due-crew .cl-t.lk b { color: var(--dc-muted); }
    #due-crew .cl-t .cl-q { width: 34px; height: 34px; border-radius: 50%; border: 2px dashed var(--dc-faded);
      display: grid; place-items: center; color: var(--dc-muted); font-weight: 800; font-size: 17px; margin-bottom: 4px; }
    #due-crew .cl-t .cl-bar { width: 70%; margin: 3px 0 1px; }
    #due-crew .cl-t .sv *, #due-crew .cl-nr .sv * { animation: none !important; }
    #due-crew .cl-pills { display: flex; flex-wrap: wrap; gap: 4px; }
    #due-crew .cl-pills .st-pill.on::before { content: none; }
    #due-crew .cl-pills .st-pill.on { background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }
    #due-crew .cl-earn .dc-fig { display: inline-flex; flex: none; }
    /* crew rows (3.8.2): each person's Pip in their colour and look, in the emoji's place; still until pointed at */
    /* Pip's arms and what it holds reach past its slot (sev.SLOT): room beside it so they never touch the name,
       and above it for a hat, so the row is a touch taller than an emoji's */
    #due-crew .dc-rsev { display: inline-block; vertical-align: middle; margin: -3px 8px -6px 2px; line-height: 0; }
    #due-crew a.dc-rsev, #due-crew a.dc-rsevl { text-decoration: none; border: 0; }
    /* 3.9.10 (Sam: "the way the person who you're on kinda hovers / gets bigger is disruptive… just the cheer
       button appears"): a crew row's Pip is still, pointed at or not; the Cheer pill is what a row shows */
    #due-crew tr .dc-rsev .sv, #due-crew tr .dc-rsev .sv * { animation: none !important; }
    /* 3.8.22: a plan card's squad line: who showed up, side by side, still until it's pointed at */
    #due-crew .pcrew .pips { display: inline-flex; gap: 4px; vertical-align: middle; margin: 8px 5px 0 0; }  /* a hat clear of the line above */
    #due-crew .pcrew .pips .dc-rsev { margin: 0; }
    #due-crew .pcrew:not(:hover) .dc-rsev .sv, #due-crew .pcrew:not(:hover) .dc-rsev .sv * { animation: none !important; } #due-crew .pcrew:hover .dc-rsev .sv { --sv-on: var(--sv-hover, infinite); }
    @media (max-width: 380px) { #due-crew .dc-rsev { display: none; } }
"""


def _closet_day(day):
    """'3 Oct', or '3 Oct 2025' when it isn't this year's."""
    try:
        d = _date.fromisoformat(str(day))
    except ValueError:
        return ""
    return f"{d.day} {d:%b}" + ("" if d.year == _date.today().year else f" {d.year}")


def _wear_tile(t, have, look, shown, new):
    """A thing of mine: a button that puts it on, or takes it off. On says
    so (the accent, filled, a tick); one a costume covers says Under."""
    e = _html.escape
    k = t["k"]
    on, under = k in look and k in shown, k in look and k not in shown
    cls = "cl-t" + (" on" if on else " under" if under else "") + (" new" if k in new else "")
    badge = ('<span class="cl-badge">&#10003; On</span>' if on else '<span class="cl-badge u">Under</span>' if under else "")
    badge += '<span class="cl-badge n">New</span>' if k in new and not on else ""
    since = _closet_day(have.get(k))
    tip = e(f'Yours since {since}' if since else t.get("tip") or "")
    fig = f'<span class="cl-f">{_sev.slot(_sev.svg("idle", rest=True, look=[k], label=e(t["name"])), 52)}</span>'
    also = "".join(f'<small>and {PLACE_NAMES[p].lower()}</small>' for p in t.get("also") or ())
    also += f'<small>{e(t["rule"])}</small>'  # what earned it
    state = "on" if on else "under the costume" if under else "not on"
    return (f'<button class="{cls}" title="{tip}" aria-label="{e(t["name"])}, {state}" aria-pressed="{"true" if k in look else "false"}" '
            f'{_st_click("closetwear:" + k)}>{badge}{fig}<b>{e(t["name"])}</b>{also}</button>')


def _earn_tile(t, progress):
    """One still to earn: shown, never worn. What it needs, how far along;
    a secret, only that it is one."""
    e = _html.escape
    if t["group"] == "Secret":
        return ('<div class="cl-t lk" role="group" aria-label="A secret, not yet" title="You&rsquo;ll know it when it happens">'
                '<span class="cl-q" aria-hidden="true">?</span><b>A secret</b></div>')
    fig = f'<span class="cl-f">{_sev.slot(_sev.svg("idle", rest=True, look=[t["k"]], label=e(t["name"])), 52)}</span>'
    when = f'<small class="w">{e(t["when"])}</small>' if t.get("when") else ""
    bar = ""
    got, need = progress.get(t["k"]) or (0, 0)
    if got > 0:
        bar = (f'<span class="cl-bar" aria-hidden="true"><i style="width:{min(100, round(100 * got / need))}%"></i></span>'
               f'<small>{got:,} of {need:,}</small>')
    return (f'<div class="cl-t lk" role="group" aria-label="{e(t["name"])}, not yet" title="{e(t.get("tip") or "")}">'
            f'{fig}<b>{e(t["name"])}</b><small>{e(t["rule"])}</small>{when}{bar}</div>')


def _closet_ons(look):
    """What's on, place by place, each a button that takes it off; a
    costume over them, the rest waiting under it."""
    e = _html.escape
    cos = _closet.costume(look)
    rows = []
    if cos:
        rows.append(f'<div class="cl-o cos"><span>Costume</span><button title="Take it off" '
                    f'{_st_click("closetwear:" + cos)}>{e(_closet.BY[cos]["name"])}</button></div>')
    for p in CLOSET_PLACES:
        k = next((x for x in look if _closet.BY[x]["slot"] != _closet.COSTUME and p in _closet.places(x)), None)
        if k is None:
            what = "<i>&ndash;</i>"
        elif _closet.BY[k]["slot"] != p:  # the earmuffs' scarf
            what = f'<i>with the {e(_closet.BY[k]["name"].split(" and ")[0].lower())}</i>'
        else:
            what = f'<button title="Take it off" {_st_click("closetwear:" + k)}>{e(_closet.BY[k]["name"])}</button>'
        rows.append(f'<div class="cl-o"><span>{PLACE_NAMES[p]}</span>{what}</div>')
    return (f'<div class="cl-ons{" covered" if cos else ""}" aria-label="What your Pip has on">' + "".join(rows) + "</div>")


def closet_html(view, cfg):
    """3.8.2: Pip's closet, in place of the board (as Settings is).
    view: {tab, have: {thing: day}, look, near: [(k, got, need, unit)],
    progress: {k: (got, need)}, new: [k], msg, rest}, from the glue
    (closet_flow). On the left your Pip in what it has on, and what's on,
    place by place (each takes it off). Yours: your things by place, one at
    a time in each, the costumes over them; what's on is the accent with a
    tick. To earn: what you're close to, then the rest by how it's earned,
    greyed, never worn before it's earned; secrets a question mark."""
    e = _html.escape
    have = _closet.clean_closet(view.get("have"))
    look = [k for k in _closet.clean(view.get("look")) if k in have]
    shown = _closet.shown(look)
    tab = view.get("tab") if view.get("tab") in CLOSET_TABS else CLOSET_TABS[0]
    new = [k for k in view.get("new") or [] if k in have]
    progress = {k: v for k, v in (view.get("progress") or {}).items() if k in _closet.BY and k not in have}
    fig = _sev.svg("hello" if new else "idle", rest=bool(view.get("rest")), look=look, label="Your Pip")
    colour = (f'<div class="cl-col"><span>Colour <small>Pip and your board</small></span>'
              f'<span class="st-sw" role="group" aria-label="Colour">{_accent_swatches(cfg)}</span></div>')  # 3.9.0 (Sam)
    me = (f'<div class="cl-me"><div class="cl-fig">{fig}</div>{colour}{_closet_ons(look)}'
          f'<div class="cl-msg" aria-live="polite">{str(view.get("msg") or "")}</div>'
          + (f'<a class="st-lk" href="#" {_st_click("closetoff")}>Take it all off</a>' if look else "")
          + '</div>')
    left = len(_closet.THINGS) - len(have)
    counts = (len(have), left)
    pills = "".join(f'<button class="st-pill{" on" if t == tab else ""}" aria-pressed="{"true" if t == tab else "false"}" '
                    f'{_st_click(f"closettab:{i}")}>{e(t)} <small>{counts[i]}</small></button>' for i, t in enumerate(CLOSET_TABS))
    if tab == CLOSET_TABS[0]:
        secs = []
        for p in CLOSET_PLACES + (_closet.COSTUME,):
            mine = [t for t in _closet.THINGS if t["slot"] == p and t["k"] in have]
            if mine:
                body = '<div class="cl-grid">' + "".join(_wear_tile(t, have, look, shown, new) for t in mine) + "</div>"
            else:  # nothing here yet: the next one, and how far along
                todo = [t for t in _closet.THINGS if t["slot"] == p and t["group"] != "Secret"]
                nxt = max(todo, key=lambda t: (progress.get(t["k"], (0, 1))[0] / progress.get(t["k"], (0, 1))[1], -todo.index(t)))
                got = progress.get(nxt["k"], (0, 0))[0]
                body = (f'<div class="cl-next">Next: <b>{e(nxt["name"])}</b>, {e(nxt["rule"][:1].lower() + nxt["rule"][1:])}'
                        f'{f" ({got:,} so far)" if got else ""}</div>')
            secs.append(f'<section class="cl-sec"><h4>{"Costumes" if p == _closet.COSTUME else PLACE_NAMES[p]}'
                        f'{f" <small>{len(mine)}</small>" if mine else ""}</h4>{body}</section>')
        main = "".join(secs)
    else:
        near_html = ""
        if view.get("near"):
            near_html = ('<section class="cl-sec"><h4>Almost there</h4><div class="cl-near">' + "".join(
                f'<div class="cl-nr"><span>{_sev.slot(_sev.svg("idle", rest=True, look=[k], label=e(_closet.BY[k]["name"])), 34)}</span>'
                f'<span><b>{e(_closet.BY[k]["name"])}</b><span class="cl-bar"><i style="width:{min(100, round(100 * got / need))}%"></i></span>'
                f'<small>{got:,} of {need:,} {e(unit)}</small></span></div>'
                for k, got, need, unit in view.get("near")) + "</div></section>")
        secs = []
        for g in _closet.GROUPS:
            todo = [t for t in _closet.THINGS if t["group"] == g and t["k"] not in have]
            if todo:
                secs.append(f'<section class="cl-sec"><h4>{e(g)} <small>{len(todo)} to go</small></h4><div class="cl-grid lk">'
                            + "".join(_earn_tile(t, progress) for t in todo) + "</div></section>")
        main = near_html + ("".join(secs) or f'<div class="cl-next">All {len(_closet.THINGS)} earned.</div>')
    off = "" if cfg.get("sev", True) else '<div class="st-note">Pip is off in Settings, so nobody sees it for now.</div>'
    return (f'<div id="due-crew" class="dc-frame dc-set dc-closet">{_css(cfg)}<style>{SETTINGS_CSS}{SEV_CSS}{CLOSET_CSS}{_sev.CSS}</style>'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span></div>'
            f'<div class="st-bar"><a class="st-back" href="#" {_st_click("closetclose")}>&lsaquo; Board</a><b>Pip&rsquo;s closet</b>'
            f'<span class="cl-n">{len(have)} of {len(_closet.THINGS)}</span></div>'
            f'<div class="cl-wrap">{me}<div class="cl-main"><div class="cl-pills" role="group" aria-label="Show">{pills}</div>'
            f'{main}</div></div>{off}</div>')


def closet_line(news, look, first=False):
    """3.8.2: the board's line when something new is in the closet: Pip
    in it, its name and what earned it, Wear it (or Be one, a costume) and
    the closet. The day the closet comes it's one line for all of them."""
    e = _html.escape
    news = [k for k in news if k in _closet.BY]
    if not news:
        return ""
    k = news[-1]
    t = _closet.BY[k]
    fig = _sev.svg("hop", rest=True, look=_closet.wear(look, k) if k not in look else look, label="Your Pip")
    if first and len(news) > 1:
        words = f'<b>Pip&rsquo;s closet is open.</b> Your days so far earned it {len(news)} things.'
        acts = f'<a class="wc" href="#" onclick="{_pycmd("closet")}">See them</a>'
    elif len(news) > 1:
        names = ", ".join(e(_closet.BY[x]["name"]) for x in news[:-1]) + " and " + e(t["name"])
        words = f'<b>New for your Pip:</b> {names}.'
        acts = f'<a class="wc" href="#" onclick="{_pycmd("closet")}">See them</a>'
    else:
        words = f'<b>New for your Pip: {e(t["name"])}.</b> {e(t["rule"])}.'
        acts = (f'<a class="wc" href="#" onclick="{_pycmd("closetwear:" + k)}">{"Be one" if t["slot"] == _closet.COSTUME else "Wear it"}</a>'
                f'<a class="wc" href="#" onclick="{_pycmd("closet")}">Closet</a>')
    return (f'<div class="dc-wrap cl-earn"><span class="dc-fig">{_sev.slot(fig, 40)}</span><span>{words}</span>{acts}'
            f'<a class="wx" href="#" title="Later" onclick="{_pycmd("closetnew")}">&times;</a></div>')
