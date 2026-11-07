"""Pip on the board: a crew row's, a squadmate's, a stamp's and a card's Pip, Halloween's line, Pip's own styles
(SEV_CSS), the look I wear (my_look).

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html

from .. import closet as _closet
from .. import sev as _sev

from .base import DEFAULT_ACCENT, _by_theme, _pycmd, accent_pair, palette


def my_look(cfg):
    """3.8.2: what my Pip has on: things I have, as the closet draws them."""
    have = _closet.clean_closet(cfg.get("sev_closet"))
    return [k for k in _closet.clean(cfg.get("sev_look")) if k in have]


HW_PIP = 34  # 3.8.22: a Halloween thing on the week's line
HW_BAT = ('<svg class="hwbat" style="--d:{d}s" viewBox="0 0 40 20" aria-hidden="true"><g class="w">'
          '<path d="M20 9 C17 4 12 3 6 5 C9 7 9 10 7 12 C11 11 14 12 16 15 C17 13 18 12 20 12 C22 12 23 13 24 15 '
          'C26 12 29 11 33 12 C31 10 31 7 34 5 C28 3 23 4 20 9 Z"/></g>'
          '<circle class="e" cx="18.6" cy="9.5" r=".9"/><circle class="e" cx="21.4" cy="9.5" r=".9"/></svg>')
HW_WEB = ('<svg class="hwweb" viewBox="0 0 60 60" aria-hidden="true"><path d="M60 0 L0 0 M60 0 L60 60 M60 0 L8 30 M60 0 '
          'L30 52 M60 0 L2 14 M60 0 L46 58 M46 0 Q48 6 60 14 M32 0 Q36 12 60 28 M18 0 Q24 18 60 42"/></svg>')
HW_CSS = """
    #due-crew .dc-hw { position: relative; overflow: hidden; display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px;
      text-align: left; margin: 0 0 8px; padding: 3px 30px 3px 10px; border-radius: 10px; background: var(--dc-well); font-size: 12.5px; }
    #due-crew .dc-hw .hwl { color: var(--dc-hours); font-weight: 700; text-decoration: none; }
    #due-crew .dc-hw .hwd, #due-crew .dc-hw .hwn { color: var(--dc-muted); }
    #due-crew .dc-hw .hws { color: var(--dc-hours); font-weight: 600; }
    #due-crew .dc-hw .hwt { display: inline-flex; align-items: flex-end; gap: 3px; padding-top: 6px; }
    #due-crew .dc-hw .hwk { display: inline-flex; line-height: 0; }
    #due-crew .dc-hw .hwk.off { opacity: .32; filter: grayscale(1); }
    #due-crew .dc-hw .hwk .sv, #due-crew .dc-hw .hwk .sv * { animation: none !important; }
    #due-crew .dc-hw .wx { position: absolute; right: 9px; top: 50%; transform: translateY(-50%); z-index: 2;
      color: var(--dc-muted); text-decoration: none; font-size: 16px; line-height: 1; }
    #due-crew .dc-hw .wx:hover { color: var(--dc-ink); }
    #due-crew .dc-hw .hwweb { position: absolute; right: -1px; top: -1px; width: 30px; height: 30px; pointer-events: none;
      fill: none; stroke: var(--dc-muted); stroke-width: 1; opacity: .5; }
    #due-crew .dc-hw .hwbat { position: absolute; left: -30px; top: 3px; width: 26px; height: 13px; opacity: 0; pointer-events: none; z-index: 3; }
    #due-crew .dc-hw .hwbat path { fill: var(--dc-ink); opacity: .85; }
    #due-crew .dc-hw .hwbat .e { fill: var(--dc-hours); }
    @media (prefers-reduced-motion: no-preference) {
      /* three bats across the line, once a day: past the logo's line, never over it (Sam) */
      #due-crew .dc-hw .hwbat { animation: dc-hwbat 4.2s linear calc(var(--d) - var(--ago, 0s)) both; }
      /* their wings flap for the flight, then stop (3.9.1: they flapped on out of sight, the frames never ending) */
      #due-crew .dc-hw .hwbat .w { transform-box: fill-box; transform-origin: 50% 50%;
        animation: dc-hwflap .22s ease-in-out calc(var(--d) - var(--ago, 0s)) 20 alternate; }
      @keyframes dc-hwbat { 0% { opacity: 1; left: -30px; transform: translateY(2px); } 25% { transform: translateY(-2px); }
        50% { transform: translateY(3px); } 75% { transform: translateY(-1px); } 100% { opacity: 1; left: calc(100% + 10px); transform: translateY(1px); } }
      @keyframes dc-hwflap { from { transform: scaleY(1); } to { transform: scaleY(.45); } }
    }
"""


def halloween_html(hw, cfg):
    """3.8.22, Halloween week (24 to 31 Oct; Sam's pick, round three): a line
    under the board's head with this week's days, the five things in
    order (mine in colour), the next and when; three bats across it once a
    day (hw["bats"]: how long they've been out, as Pip by the logo; None
    after); and when every Pip on the crew's rows has a Halloween thing on
    (hw["spooky"]: how many), a cobweb in its corner and a line about it.
    Nothing with Pip off. hw: closet.halloween's, from closet_flow."""
    if not hw or not cfg.get("sev", True):
        return ""
    e = _html.escape
    days = int(hw.get("days") or 0)
    said = "a thing a day for five days" if not days else f'{days} day{"" if days == 1 else "s"} so far'
    things = "".join(
        f'<span class="hwk {"on" if got else "off"}" title="{e(_closet.BY[k]["name"])}: '
        f'{"a day" if n == 1 else str(n) + " days"} of Halloween week">'
        f'{_sev.slot(_sev.svg("idle", rest=True, look=[k], label=_closet.BY[k]["name"]), HW_PIP)}</span>'
        for k, n, got in hw.get("things") or [] if k in _closet.BY)
    nxt = hw.get("next")
    if nxt:
        name = e(_closet.BY[nxt[0]]["name"].lower())
        more = int(nxt[1])
        when = ((f"tomorrow: the {name}" if hw.get("today") else f"study today for the {name}") if more == 1
                else f"the {name} in {more} more days")
    elif all(got for _k, _n, got in hw.get("things") or []):
        when = "all five: Pip&rsquo;s ready"
    else:
        when = "the rest next year"
    n = int(hw.get("spooky") or 0)
    spooky = f'<span class="hws">A spooky crew: all {n} of you dressed up.</span>' if n else ""
    ago = hw.get("bats")
    bats = "".join(HW_BAT.format(d=d) for d in (0, .5, 1.1)) if ago is not None else ""
    return (f'<div class="dc-hw" style="--ago:{float(ago or 0):.2f}s">{bats}{HW_WEB if n else ""}'
            f'<a class="hwl" href="#" title="Pip&rsquo;s closet" onclick="{_pycmd("closet")}">Halloween week</a>'
            f'<span class="hwd">{said}</span><span class="hwt">{things}</span><span class="hwn">{when}</span>{spooky}'
            f'<a class="wx" href="#" title="Hide until next year" onclick="{_pycmd("closethw")}">&times;</a></div>')


def row_sev(row, cfg, size=None, nth=None):
    """3.8.2: someone's Pip on a crew row, in the emoji's place: their colour
    and their look (mine: this computer's), still until the row is pointed
    at. My own opens the closet. None with Pip off. nth (3.9.0): its place
    among Pips that move together (a bingo square's stamps, a plan card's
    squad line), so each blinks on its own clock (sev.blink), as a room's
    seats do."""
    if not cfg.get("sev", True):
        return None
    light, dark = accent_pair(cfg.get("accent") if row.get("you") else row.get("accent"))
    look = my_look(cfg) if row.get("you") else row.get("look")
    label = "Your Pip" if row.get("you") else _html.escape(f'{row.get("name") or "?"}’s Pip', quote=True)
    fig = _sev.slot(_sev.svg("idle", rest=True, look=look, label=label), size or _sev.ROW_SIZE)  # the site's rows too (sev.site_kit)
    style = f'--rs-l:{light};--rs-d:{dark}' + (f';{_sev.blink_css(nth)}' if nth is not None else "")
    if row.get("you"):
        return (f'<a class="dc-rsev" href="#" title="Pip&rsquo;s closet" style="{style}" '
                f'onclick="{_pycmd("closet")}">{fig}</a>')
    return f'<span class="dc-rsev" style="{style}">{fig}</span>'


PCREW_PIP = 26  # 3.8.22: a Pip on a plan card's squad line, its slot a line of its small text
SETTINGS_PIP = 44  # 3.8.22: mine in Settings › You, beside my name and status


def squad_pip(uid, name, you, people, cfg, size=None, nth=None):
    """3.8.21: someone's Pip on the Squads tab, in the emoji's place (Sam: "the
    squads page still has the old emojis"): mine as on my row; a crewmate's
    in their colour and look (a mutual friend's, which only the crew brings);
    anyone else plain, in the default colour, since all a squadmate shares is
    a name and an emoji. people: {uid: crew entry}. None with Pip off."""
    p = (people or {}).get(uid) or {}
    return row_sev({"you": bool(you), "name": name, "accent": p.get("accent"), "look": p.get("look")}, cfg, size, nth)


STAMP_PIP = 40  # 3.8.22: who stamped a bingo square, bigger than the emoji was (Sam: "make the bingo stamps bigger")
BINGO_PIP_CSS = """
    #due-crew .bg-sq.stamped { padding-bottom: 34px; }
    #due-crew .bg-sq .st.sp { width: auto; height: auto; background: none; box-shadow: none; border-radius: 0; bottom: 4px; }
    #due-crew .bg-sq .st.sp .dc-rsev { display: inline-block; line-height: 0; margin: 0; }
    #due-crew .bg-sq:not(:hover) .dc-rsev .sv, #due-crew .bg-sq:not(:hover) .dc-rsev .sv * { animation: none !important; } #due-crew .bg-sq:hover .dc-rsev .sv { --sv-on: var(--sv-hover, infinite); }
"""


def stamp_pip(uid, name, people, cfg, nth=None):
    """3.8.22: who stamped a bingo square, as their Pip: mine and a
    crewmate's in colour and look, a squadmate's plain (all they share is a
    name and an emoji). The square is a button, so never a link: mine
    doesn't open the closet from here."""
    p = (people or {}).get(uid) or {}
    you = bool(p.get("you"))
    return row_sev({"name": name, "accent": cfg.get("accent") if you else p.get("accent"),
                    "look": my_look(cfg) if you else p.get("look")}, cfg, STAMP_PIP, nth) or ""


def card_sev(row, cfg, size=44):
    """3.8.2: someone's Pip on their profile card, in the emoji's place, as
    on their row: their colour, their look (mine: this computer's), waving
    once as the card opens. The card sits outside the board, so the colours
    come with it. None with Pip off."""
    if not cfg.get("sev", True):
        return None
    light, dark = accent_pair(cfg.get("accent") if row.get("you") else row.get("accent"))
    look = my_look(cfg) if row.get("you") else row.get("look")
    label = "Your Pip" if row.get("you") else _html.escape(f'{row.get("name") or "?"}’s Pip', quote=True)

    def colours(theme, a):
        p = palette(theme, cfg.get("accent", DEFAULT_ACCENT))
        return f"--sv-a: {a}; --sv-line: {p['line']}; --sv-amb: {p['hours']}; --sv-mut: {p['muted']};"
    css = _by_theme(cfg, "#dc-profile .dc-psev", colours("light", light), colours("dark", dark))
    fig = _sev.slot(_sev.svg("hello", look=look, label=label), size)
    return (f'<style>{css}\n#dc-profile .dc-psev {{ display: inline-block; flex: none; line-height: 0; margin: 0 2px; }}</style>'
            f'<span class="dc-psev">{fig}</span>')


# 3.8.1: Pip on the board wears the board's colours; its size is its body's
SEV_CSS = """
    #due-crew { --sv-a: var(--dc-accent); --sv-line: var(--dc-line); --sv-amb: var(--dc-hours); --sv-mut: var(--dc-muted); }
    /* its feet on the logo's line, a little shorter than the wordmark is tall */
    #due-crew .dc-sev { display: inline-block; margin-left: 8px; vertical-align: middle; line-height: normal;
      position: relative; top: -1px; }
    /* by the logo it's a moment: out for a few seconds, then gone (still, it just goes) */
    #due-crew .dc-sev.once { animation: dc-sev-go 0s linear calc(5s - var(--ago, 0s)) forwards; }
    @keyframes dc-sev-go { to { visibility: hidden; } }
    @media (prefers-reduced-motion: no-preference) {
      #due-crew .dc-sev.once { transform-origin: 50% 100%;
        animation: dc-sev-pop 5s linear calc(0s - var(--ago, 0s)) forwards; }
      @keyframes dc-sev-pop { 0% { transform: scale(0); } 7% { transform: scale(1.12); } 11%, 90% { transform: scale(1); }
        100% { transform: scale(0); visibility: hidden; } }
    }
    /* a crew room's members as their Pips: side by side, not overlapping as the circles do */
    #due-crew .dc-room .fc.sv-seats { gap: 3px; align-items: center; }
    #due-crew .dc-room .fc .seat { display: inline-flex; }
    #due-crew .dc-fif .rgw { display: inline-flex; align-items: center; gap: 8px; }
    #due-crew .dc-fif .rt { text-align: left; }
    /* the session's line: Pip and its stack, the box's own padding around them (stack_reach) */
    #due-crew .dc-wrap .dc-fig { display: inline-flex; flex: none; }
    /* signed out: Pip waves beside the words, until you start */
    #due-crew .dc-card .dc-so { display: inline-flex; align-items: center; gap: 8px; text-align: left; max-width: 100%; }
    #due-crew .dc-card .dc-hi { flex: none; line-height: 0; }
    #due-crew .dc-sess { text-align: left; }
    #due-crew .dc-fif .rw { flex-wrap: wrap; justify-content: flex-end; }
    #due-crew .du-nudge { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 9px; align-items: center;
      font-size: 12.5px; padding: 6px 2px 8px; text-align: left; }
    #due-crew .du-nudge .nz { position: relative; width: 34px; height: 28px; overflow: hidden; }
    #due-crew .du-nudge .nz svg { position: absolute; left: -7px; top: -19px; width: 48px; height: 48px; }
    #due-crew .du-nudge .du-go { margin: 0; }
    #due-crew .du-nudge .x { color: var(--dc-muted); font-weight: 400; margin-left: 10px; text-decoration: none; }
"""
