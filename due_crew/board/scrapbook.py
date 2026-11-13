"""The scrapbook, in the board's place: a year page, then months of keepsakes.

A part of the board (due_crew/board/, 3.9.10): see its __init__. It took
Wrapped's place (Sam: "let's have it replace wrapped"): the year's line and
numbers open each year's page, and the year picture card is its Share."""

import html as _html

from ..logo import board_mark
from .. import sev as _sev

from .base import ACCENTS, CARD_SHADOW, _by_theme, _pycmd, _short_day, accent_pair, button_reset
from .cheers import DOODLE_INK, _doodle_art
from .style import _css

SCRAP_PIP, SCRAP_ME = 30, 40
SCRAP_COLS = 3
_WEIGHT = {"pz": 6, "luck": 5, "tip": 5, "mine": 3, "cheer": 1}

SCRAP_CSS = """
    #due-crew.dc-sb, #due-crew.dc-sb .sb-m, #due-crew.dc-sb .sb-y { text-align: left; }
    __BUTTONS__
    #due-crew .sb-bar { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; margin: 2px 0 8px; }
    #due-crew .sb-bar b { font-size: 15px; }
    #due-crew .sb-bar .sp { flex: 1; }
    #due-crew .sb-bar a.back { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .sb-yr { border: 1px solid var(--dc-line); border-radius: 99px; padding: 1px 10px; font-weight: 700; font-size: 11.5px;
      color: var(--dc-muted); background: transparent; }
    #due-crew .sb-yr.on { background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }
    #due-crew .sb-n { color: var(--dc-muted); font-size: 11.5px; }
    /* the year page: Wrapped's place, in one block */
    #due-crew .sb-y { margin-top: 4px; padding: 14px 16px; border-radius: 12px; background: #20241f; color: #eef0ea; }
    #due-crew .sb-y .k, #due-crew .sb-m .k, #due-crew .sb-k .kk { font-size: 10.5px; font-weight: 700; letter-spacing: .06em;
      text-transform: uppercase; }
    #due-crew .sb-y .k { opacity: .7; }
    #due-crew .sb-y .l { font-size: 23px; line-height: 1.2; font-weight: 800; letter-spacing: -.02em; margin: 4px 0 8px; max-width: 26em; }
    #due-crew .sb-y .l em, #due-crew .sb-y a { font-style: normal; color: #7cc47f; }
    #due-crew .sb-y .s { display: flex; flex-wrap: wrap; gap: 5px 18px; font-size: 12px; opacity: .92; font-variant-numeric: tabular-nums; }
    #due-crew .sb-y .s b { font-size: 15px; }
    #due-crew .sb-y .a { display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
    #due-crew .sb-y a { font-weight: 700; text-decoration: none; }
    /* a month: its line, its numbers, its keepsakes */
    #due-crew .sb-m { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--dc-line); }
    #due-crew .sb-m .k { color: var(--dc-muted); }
    #due-crew .sb-m .l { font-size: 20px; line-height: 1.25; font-weight: 800; letter-spacing: -.015em; margin: 3px 0 2px; max-width: 30em; }
    #due-crew .sb-m .l em { font-style: normal; color: var(--dc-accent); }
    #due-crew .sb-m .s { color: var(--dc-muted); font-variant-numeric: tabular-nums; font-size: 12px; }
    #due-crew .sb-pin { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 18px; margin-top: 20px; }
    #due-crew .sb-col { display: grid; gap: 22px; align-content: start; min-width: 0; }
    #due-crew .sb-k { margin: 0; position: relative; display: block; min-width: 0; }
    #due-crew .sb-k .sv-slot { --sv-a: var(--a); flex: none; }
    #due-crew .sb-k:not(:hover) .sv, #due-crew .sb-k:not(:hover) .sv * { animation: none !important; }
    #due-crew .sb-acts { position: absolute; right: 6px; top: 6px; display: flex; gap: 4px; opacity: 0; }
    #due-crew .sb-k:hover .sb-acts, #due-crew .sb-k:focus-within .sb-acts { opacity: 1; }
    #due-crew .sb-acts button { font-size: 10.5px; font-weight: 700; padding: 2px 7px; border-radius: 99px; background: var(--dc-bg);
      color: var(--dc-ink); border: 1px solid var(--dc-line); }
    #due-crew .sb-acts button.del { color: #c0392b; }
    #due-crew .sb-w { display: flex; align-items: center; gap: 4px; margin-top: 3px; color: var(--sb-muted); white-space: nowrap; min-width: 0;
      font-size: 11.5px; }
    #due-crew .sb-w b { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    /* a polaroid, as the fridge draws it */
    #due-crew .sb-pz { background: var(--sb-bg); color: var(--sb-ink); padding: 8px 8px 7px; border-radius: 2px; box-shadow: var(--sb-sh);
      font-size: 11.5px; }
    #due-crew .sb-pz::before { content: ""; position: absolute; top: -8px; left: 50%; width: 54px; height: 16px; margin-left: -27px;
      background: var(--a); opacity: .62; transform: rotate(-4deg);
      clip-path: polygon(0 12%, 5% 0, 30% 6%, 60% 0, 95% 5%, 100% 0, 98% 50%, 100% 100%, 70% 94%, 40% 100%, 4% 95%, 0 100%, 2% 50%); }
    #due-crew .sb-pz .fp { aspect-ratio: 300 / 170; display: grid; place-items: center; overflow: hidden; background: var(--sb-photo); }
    #due-crew .sb-pz .fp svg { width: 100%; height: 100%; display: block; }
    #due-crew .sb-pz .dd-sign { font-size: 14px; line-height: 1.15; text-align: center; padding: 2px 6px; overflow-wrap: anywhere; color: var(--sb-ink); }
    #due-crew .sb-pz .fq { margin-top: 7px; text-align: center; overflow-wrap: anywhere; }
    #due-crew .sb-pz .sb-w { justify-content: center; }
    #due-crew .sb-pz .sb-w b { color: var(--sb-ink); }
    #due-crew .sb-pz .sb-w .sv-slot { margin: 9px 2px 0 4px; }
    /* a good-luck card: a ruled card; a tip: a sticky note */
    #due-crew .sb-luck { background: var(--sb-paper); color: var(--dc-ink); border-radius: 4px; padding: 12px 12px 8px; box-shadow: var(--sb-sh);
      border-top: 4px solid var(--a); }
    #due-crew .sb-tip { background: var(--sb-note); color: var(--sb-note-ink); padding: 12px 12px 8px; border-radius: 2px 2px 14px 2px;
      box-shadow: var(--sb-sh); }
    #due-crew .sb-k .kk { color: var(--dc-muted); }
    #due-crew .sb-tip .kk, #due-crew .sb-tip .sb-w { color: var(--sb-note-ink); opacity: .75; }
    #due-crew .sb-k .q { margin: 6px 0 4px; font-size: 13.5px; line-height: 1.4; font-weight: 600; overflow-wrap: anywhere; }
    #due-crew .sb-luck .sb-w .sv-slot, #due-crew .sb-tip .sb-w .sv-slot { margin: 6px 4px 0 2px; }
    /* something I did: a stub, my Pip beside it */
    #due-crew .sb-mine { display: flex; gap: 10px; align-items: flex-start; padding: 11px 12px; border-radius: 10px;
      border: 1.5px dashed var(--dc-accent); background: var(--dc-you-bg); }
    #due-crew .sb-mine .mp { flex: none; margin-top: 8px; }
    #due-crew .sb-mine .sv-slot { --sv-a: var(--dc-accent); }
    #due-crew .sb-mine .h { display: block; font-size: 15px; line-height: 1.2; margin: 2px 0 3px; overflow-wrap: anywhere; }
    #due-crew .sb-mine .u { color: var(--dc-muted); font-size: 12px; }
    /* a cheer's words: a slip */
    #due-crew .sb-cheer { display: grid; grid-template-columns: auto 1fr; gap: 2px 8px; align-items: baseline; padding: 7px 10px;
      border-radius: 6px; background: var(--dc-well); border-left: 3px solid var(--a); font-size: 12.5px; }
    #due-crew .sb-cheer .e { grid-row: span 2; font-size: 17px; line-height: 1; align-self: center; }
    #due-crew .sb-cheer .q { margin: 0; font-size: 12.5px; }
    #due-crew .sb-cheer .sb-w { margin: 0; color: var(--dc-muted); font-size: 11px; }
    #due-crew .sb-none { color: var(--dc-muted); padding: 18px 0 6px; max-width: 46em; }
    #due-crew .sb-foot { display: flex; justify-content: space-between; gap: 6px 14px; flex-wrap: wrap; margin-top: 18px; padding-top: 9px;
      border-top: 1px solid var(--dc-line); color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .sb-foot a { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew.dc-sb button:focus-visible, #due-crew.dc-sb a:focus-visible { outline: 2px solid var(--dc-accent) !important; outline-offset: 2px; }
""".replace("__BUTTONS__", button_reset("#due-crew.dc-sb button", "vertical-align: middle; font: inherit; cursor: pointer;"))
SCRAP_LIGHT = ("--sb-bg: #fff; --sb-photo: #f4f3ee; --sb-ink: #2b2d29; --sb-muted: #6b665a; --sb-paper: #fbf8f1; --sb-note: #fdf3d3; "
               "--sb-note-ink: #4a3d12; --sb-sh: " + CARD_SHADOW + ", 0 0 0 1px rgba(0,0,0,.05);")
SCRAP_DARK = ("--sb-bg: #33352f; --sb-photo: #23241f; --sb-ink: #e6e8e3; --sb-muted: #a3a79c; --sb-paper: #2e2c26; --sb-note: #45391a; "
              "--sb-note-ink: #f1e2b4; --sb-sh: 0 4px 14px rgba(0,0,0,.5), 0 0 0 1px rgba(255,255,255,.07);")


def _scrap_theme(cfg):
    """The page's own tokens by theme; each keepsake's accent, light or dark; a doodle's black ink reads light at night."""
    return (_by_theme(cfg, "#due-crew.dc-sb", SCRAP_LIGHT, SCRAP_DARK)
            + _by_theme(cfg, "#due-crew .sb-k", "--a: var(--al);", "--a: var(--ad);")
            + _by_theme(cfg, f'#due-crew .sb-pz path[stroke="{DOODLE_INK}"]', "", "stroke: #e6e8e3;"))


def _tone(x, person):
    """A keepsake's colours: its person's as they are now, else the one it came in (a polaroid's), else ours."""
    now = person.get("accent") if isinstance(person, dict) and person.get("accent") in ACCENTS else ""
    light, dark = accent_pair(now or x.get("a"))
    return f"--al:{light};--ad:{dark}"


def _who(x, person, pip):
    """Their Pip as it is now (in my crew, with Pip on), their name and the day."""
    e = _html.escape
    name = e(str(x.get("name") or "?"))
    fig = (_sev.slot(_sev.svg("idle", rest=True, look=person.get("look"), label=f"{name}’s Pip"), SCRAP_PIP)
           if pip and isinstance(person, dict) and person else "")
    when = _short_day(x.get("at"))
    return f'<figcaption class="sb-w">{fig}<b>{name}</b>{f" &middot; {when}" if when else ""}</figcaption>'


def _acts(x, pin=False):
    k = x.get("key") or ""
    up = (f'<button type="button" title="Back on your Decks screen" onclick="{_pycmd("scrappin:" + k)}">Pin up</button>' if pin else "")
    return (f'<span class="sb-acts">{up}<button type="button" class="del" title="Delete it for good" '
            f'onclick="{_pycmd("scrapdel:" + k)}">Delete</button></span>')


def _keepsake(x, people, pip, my_look):
    e = _html.escape
    k = x["k"]
    person = (people or {}).get(x.get("from")) or {}
    tone = _tone(x, person)
    if k == "pz":
        note = f'<div class="fq">&ldquo;{e(x["n"])}&rdquo;</div>' if x.get("n") else ""
        art = _doodle_art(x["d"], x.get("a"), str(x.get("name") or "?") + "’s drawing")
        return (f'<figure class="sb-k sb-pz" style="{tone}"><div class="fp">{art}</div>{note}{_who(x, person, pip)}{_acts(x, True)}</figure>')
    if k == "luck":
        return (f'<figure class="sb-k sb-luck" style="{tone}"><div class="kk">Good luck &middot; before your exam</div>'
                f'<div class="q">{e(x["n"])}</div>{_who(x, person, pip)}{_acts(x)}</figure>')
    if k == "tip":
        part = f' &middot; on a card in {e(x["part"])}' if x.get("part") else ""
        return (f'<figure class="sb-k sb-tip" style="{tone}"><div class="kk">A hook that helped{part}</div>'
                f'<div class="q">{e(x["n"])}</div>{_who(x, person, pip)}{_acts(x)}</figure>')
    if k == "cheer":
        emoji = e(x.get("e") or "") or "&#127881;"
        return (f'<figure class="sb-k sb-cheer" style="{tone}"><span class="e">{emoji}</span>'
                f'<div class="q">&ldquo;{e(x["n"])}&rdquo;</div>{_who(x, person, False)}{_acts(x)}</figure>')
    fig = (f'<span class="mp">{_sev.slot(_sev.svg(x.get("pose") or "cheer", rest=True, look=my_look, label="Your Pip"), SCRAP_ME)}</span>'
           if pip else "")
    when = _short_day(x.get("at"))
    return (f'<figure class="sb-k sb-mine">{fig}<div><div class="kk">You{f" &middot; {when}" if when else ""}</div>'
            f'<b class="h">{e(x["head"])}</b>{f"""<div class="u">{e(x["sub"])}</div>""" if x.get("sub") else ""}</div>{_acts(x)}</figure>')


def _columns(items, people, pip, my_look):
    """The keepsakes in columns, each next one in the shortest so far (CSS columns would cut a polaroid's tape off)."""
    cols, tall = [[] for _ in range(SCRAP_COLS)], [0] * SCRAP_COLS
    for x in items:
        i = tall.index(min(tall))
        cols[i].append(_keepsake(x, people, pip, my_look))
        tall[i] += _WEIGHT.get(x["k"], 3)
    return "".join(f'<div class="sb-col">{"".join(c)}</div>' for c in cols if c)


def _line(parts):
    e = _html.escape
    a, b, c = (list(parts) + ["", "", ""])[:3]
    return f'{e(a)}{f"<em>{e(b)}</em>" if b else ""}{e(c)}'


def scrapbook_html(view, cfg, people=None, my_look=None):
    """3.9.10: the scrapbook in the board's place (as Pip's closet and
    Settings are). view: scrap_flow.view's; every string in it is escaped
    here. people: {uid: crew entry}, for each sender's Pip and colour as
    they are now. On top the year's page (its line, its numbers, Share my
    year: the year picture card), then the months, newest first, each with
    its line and its keepsakes: Pin up on a polaroid, Delete on any."""
    e = _html.escape
    year = int(view.get("year") or 0)
    pip = bool(view.get("sev", cfg.get("sev", True)))
    years = "".join(f'<button type="button" class="sb-yr{" on" if int(y) == year else ""}" aria-pressed="{"true" if int(y) == year else "false"}" '
                    f'onclick="{_pycmd("scrapyear:" + str(int(y)))}">{int(y)}</button>' for y in view.get("years") or [year])
    n = int(view.get("n") or 0)
    stats = "".join(f'<span><b>{e(str(a))}</b> {e(str(b))}</span>' for a, b in view.get("ystats") or [])
    ypage = (f'<div class="sb-y"><div class="k">{year}{" so far" if view.get("so_far") else ""}</div>'
             f'<div class="l">{_line(view.get("yline") or ())}</div>'
             + (f'<div class="s">{stats}</div>' if stats else "")
             + f'<div class="a"><a href="#" onclick="{_pycmd("scrapshare:" + str(year))}">Share my year</a></div></div>')
    months = ""
    for m in view.get("months") or []:
        pin = _columns(m.get("items") or [], people, pip, my_look)
        months += (f'<div class="sb-m"><div class="k">{e(str(m.get("name") or ""))}</div>'
                   f'<div class="l">{_line(m.get("line") or ())}</div>'
                   + (f'<div class="s">{e(str(m["sub"]))}</div>' if m.get("sub") else "")
                   + (f'<div class="sb-pin">{pin}</div>' if pin else "") + '</div>')
    if not n:
        months += ('<div class="sb-none">Nothing kept yet this year. A drawing or a sign you take down from your Decks screen comes here, '
                   'with good-luck cards, hooks that helped, cheers that came with words, and what you finish.</div>')
    foot = ('<div class="sb-foot"><span>Kept on this computer. Never sent.</span>'
            + (f'<a href="#" onclick="{_pycmd("scrapempty")}">Empty the scrapbook&hellip;</a>' if view.get("any") else "") + '</div>')
    return (f'<div id="due-crew" class="dc-frame dc-sb">{_css(cfg)}<style>{_sev.CSS}{SCRAP_CSS}{_scrap_theme(cfg)}</style>'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span><span></span></div>'
            f'<div class="sb-bar"><a class="back" href="#" onclick="{_pycmd("scrapclose")}">&lsaquo; Board</a><b>Scrapbook</b>'
            f'<span class="sp"></span>{years}<span class="sb-n">{n:,} keepsake{"s" if n != 1 else ""}</span></div>'
            f'{ypage}{months}{foot}</div>')


def scrapbook_line(year, so_far, look, pip=True):
    """The board's line, 1 December to 15 January (Wrapped's, 3.9.0): the
    year's page is ready in the scrapbook. The x is for the year, on every
    computer (the account's wrapped_seen). Pip off: a gift."""
    fig = (f'<span class="dc-fig">{_sev.slot(_sev.svg("hop", rest=True, look=look, label="Your Pip"), 40)}</span>'
           if pip else "<span>&#127873;</span>")
    return (f'<div class="dc-wrap wr-line">{fig}'
            f'<span><b>Your {int(year)}{" so far" if so_far else ""}</b> is in your scrapbook: the year, and what your crew sent you.</span>'
            f'<a class="wc" href="#" onclick="{_pycmd("scrapbook:" + str(int(year)))}">Open &#9654;</a>'
            f'<a class="wx" href="#" title="Not this year" onclick="{_pycmd("wrappedx:" + str(int(year)))}">&times;</a></div>')
