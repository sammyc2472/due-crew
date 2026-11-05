"""Your Wrapped: the year's story in the board's place, and its line.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html

from ..logo import board_mark
from .. import closet as _closet
from .. import sev as _sev

from .base import DEFAULT_ACCENT, _pycmd, accent_pair
from .style import _css
from .pip import SEV_CSS
from .settings import SETTINGS_CSS, _st_click


WRAPPED_CSS = """
    #due-crew.dc-wr { text-align: left; }
    #due-crew .wr-wrap { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 22px; align-items: start; }
    @media (max-width: 600px) { #due-crew .wr-wrap { grid-template-columns: minmax(0, 1fr); justify-items: center; } }
    #due-crew .wr-phone { position: relative; width: 300px; max-width: 100%; height: 560px; border-radius: 26px; overflow: hidden;
      background: #000; box-shadow: 0 10px 30px rgba(0,0,0,.18); outline: none; }
    #due-crew .wr-phone:focus-visible { box-shadow: 0 0 0 3px var(--dc-accent), 0 10px 30px rgba(0,0,0,.18); }
    #due-crew .wr-bars { position: absolute; top: 10px; left: 12px; right: 12px; display: flex; gap: 4px; z-index: 3; }
    #due-crew .wr-bars i { flex: 1; height: 3px; border-radius: 2px; background: rgba(255,255,255,.3); overflow: hidden; display: block; }
    #due-crew .wr-bars b { display: block; height: 100%; width: 0; background: #fff; }
    #due-crew .wr-phone.lt .wr-bars i { background: rgba(0,0,0,.14); } #due-crew .wr-phone.lt .wr-bars b { background: #222; }
    #due-crew .wr-s { position: absolute; inset: 0; background: var(--bg); color: #fff; padding: 36px 20px 18px; display: none;
      flex-direction: column; gap: 8px; }
    #due-crew .wr-s.on { display: flex; }
    #due-crew .wr-s.lt { color: #222; }
    #due-crew .wr-tap { position: absolute; top: 0; bottom: 0; width: 34%; background: transparent; border: 0; box-shadow: none;
      border-radius: 0; margin: 0; padding: 0; z-index: 2; cursor: pointer; }
    #due-crew .wr-tap.l { left: 0; } #due-crew .wr-tap.r { right: 0; width: 66%; }
    #due-crew .wk { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; opacity: .78; }
    #due-crew .wb { font-size: 40px; font-weight: 800; line-height: 1.04; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
    #due-crew .wb.long { font-size: 32px; }
    #due-crew .wl { font-size: 15px; line-height: 1.35; opacity: .92; }
    #due-crew .wsm { font-size: 13px; line-height: 1.35; opacity: .8; }
    #due-crew .wno { font-size: 13px; opacity: .8; margin-top: auto; }
    #due-crew .wtag { align-self: flex-start; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 99px;
      background: rgba(255,255,255,.16); }
    #due-crew .wr-s.lt .wtag { background: rgba(0,0,0,.08); }
    #due-crew .wp { align-self: center; margin-top: auto; line-height: 0; --sv-line: rgba(255,255,255,.18); }
    #due-crew .wp svg.sv { width: 128px; height: 128px; overflow: visible; }
    #due-crew .wp.xl svg.sv { width: 176px; height: 176px; }
    #due-crew .wh { display: grid; grid-template-rows: repeat(7, 1fr); grid-auto-flow: column; grid-auto-columns: 1fr; gap: 1.3px; margin: 6px 0 2px; }
    #due-crew .wh i { display: block; aspect-ratio: 1; border-radius: 1.2px; background: rgba(255,255,255,.1); }
    #due-crew .wh i.x { background: transparent; } #due-crew .wh i.f { background: rgba(255,255,255,.05); }
    #due-crew .wh i.l1 { background: color-mix(in srgb, var(--wa) 45%, transparent); } #due-crew .wh i.l2 { background: color-mix(in srgb, var(--wa) 65%, transparent); }
    #due-crew .wh i.l3 { background: color-mix(in srgb, var(--wa) 85%, transparent); } #due-crew .wh i.l4 { background: var(--wa); }
    #due-crew .wh i.r { background: #e0a458; }
    #due-crew .wg { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 10px; margin-top: 8px; font-size: 12.5px; opacity: .95; }
    #due-crew .wg b { display: block; font-size: 28px; line-height: 1.05; font-weight: 800; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
    #due-crew .wq { background: #fbf8f1; color: #2b2d29; border-radius: 12px; padding: 18px 14px; font-size: 16px; font-weight: 600;
      line-height: 1.35; margin: 6px 0 4px; box-shadow: 0 4px 14px rgba(0,0,0,.25); overflow-wrap: anywhere; }
    #due-crew .wt { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); justify-items: center; gap: 2px; margin-top: 6px; }
    #due-crew .wt .sv { width: 54px; height: 54px; overflow: visible; }
    #due-crew .wt .sv, #due-crew .wt .sv * { animation: none !important; }
    #due-crew .wpic { background: #fff; color: #222; border-radius: 16px; padding: 16px 12px 6px; display: grid; gap: 8px;
      box-shadow: 0 6px 18px rgba(0,0,0,.08); margin-top: 6px; }
    #due-crew .wpic .wk { text-align: center; opacity: .7; }
    #due-crew .wpic .wg { grid-template-columns: repeat(3, minmax(0, 1fr)); text-align: center; color: #6b6f67; margin: 0; }
    #due-crew .wpic .wg b { color: #222; font-size: 24px; }
    #due-crew .wpic .wp { margin: 0; --sv-line: #e2e2da; } #due-crew .wpic .wp svg.sv { width: 92px; height: 92px; }
    #due-crew .wpic .dc-mark { height: 14px; width: auto; justify-self: center; }
    #due-crew .wgo { position: relative; z-index: 4; align-self: center; margin-top: 10px; font: inherit; font-size: 13px; font-weight: 700;
      padding: 7px 14px; border-radius: 9px; border: 0; background: #2e7d32; color: #fff; cursor: pointer; }
    #due-crew .wr-side { display: grid; gap: 10px; align-content: start; font-size: 13px; max-width: 360px; }
    #due-crew .wr-side h3 { margin: 0; font-family: inherit; font-size: 17px; font-weight: 700; letter-spacing: normal; }
    #due-crew .wr-side p { margin: 0; color: var(--dc-muted); line-height: 1.45; }
    #due-crew .wr-years { display: flex; flex-wrap: wrap; gap: 6px; }
    #due-crew .wr-years a { padding: 3px 10px; border-radius: 99px; border: 1px solid var(--dc-line); color: var(--dc-ink); text-decoration: none; }
    #due-crew .wr-years a.on { background: var(--dc-accent); color: var(--dc-accent-ink); border-color: transparent; }
    #due-crew .wr-list { margin: 16px 0 0; padding: 12px 14px 12px 34px; border: 1px solid var(--dc-line); border-radius: 12px;
      display: grid; gap: 6px; font-size: 13px; line-height: 1.45; max-width: 640px; }
    #due-crew .wr-list[hidden] { display: none; }
    #due-crew .wr-btn { font: inherit; font-size: 12.5px; font-weight: 700; padding: 5px 12px; border-radius: 8px; border: 1px solid var(--dc-line);
      background: var(--dc-bg); color: var(--dc-ink); cursor: pointer; margin: 0; box-shadow: none; justify-self: start; }
"""


def _wr_heat(cells, accent, run=None):
    lo, hi = (run or ("", ""))
    out = []
    for c in cells:
        if c is None:
            out.append('<i class="x"></i>')
        elif c == "":
            out.append('<i class="f"></i>')
        else:
            day, lv = c
            out.append('<i class="r"></i>' if run and lo <= day <= hi else f'<i class="l{int(lv)}"></i>' if lv else "<i></i>")
    return f'<div class="wh" style="--wa:{accent}" aria-hidden="true">' + "".join(out) + "</div>"


def _wr_slide(i, total, sl, view, cfg):
    e = _html.escape
    look = view.get("look") or []
    kind = sl.get("kind")
    lt = kind == "picture"
    accent = accent_pair(cfg.get("accent", DEFAULT_ACCENT))
    pip_a = accent[0] if lt else accent[1]

    def pip(pose, size_cls="", lk=None):
        if not cfg.get("sev", True):
            return ""  # Pip off: the story without it
        return (f'<span class="wp {size_cls}" style="--sv-a:{pip_a}">'
                f'{_sev.svg(pose, look=look if lk is None else lk, label="Your Pip")}</span>')
    parts = []
    if kind != "picture":
        parts.append(f'<div class="wk">{e(sl.get("kicker") or "")}</div>')
    if sl.get("tag"):
        parts.append(f'<span class="wtag">{e(sl["tag"])}</span>')
    if sl.get("lead"):
        parts.append(f'<div class="wl">{e(sl["lead"])}</div>')
    if sl.get("big"):
        parts.append(f'<div class="wb{" long" if len(str(sl["big"])) > 12 else ""}">{e(sl["big"])}</div>')
    if sl.get("line") and kind != "crew":
        parts.append(f'<div class="wl">{e(sl["line"])}</div>')
    if kind == "days":
        parts.append(_wr_heat(view.get("heat") or [], accent[1]))
    if kind == "run":
        parts.append(_wr_heat(view.get("heat") or [], accent[1], sl.get("run")))
    if kind == "turned":
        parts.insert(2, f'<div class="wq">{e(sl.get("front") or "")}</div>')
    if kind == "things":
        parts.append('<div class="wt">' + "".join(
            _sev.svg("idle", rest=True, look=[k], label=e(_closet.BY[k]["name"])).replace('<svg ', f'<svg style="--sv-a:{pip_a}" ', 1)
            for k in sl.get("things") or [] if k in _closet.BY) + "</div>")
    if sl.get("grid") and kind != "picture":
        parts.append('<div class="wg">' + "".join(f"<div><b>{e(a)}</b>{e(b)}</div>" for a, b in sl["grid"]) + "</div>")
    if kind == "crew" and sl.get("line"):
        parts.append(f'<div class="wl">{e(sl["line"])}</div>')
    if sl.get("small") and kind != "picture":
        parts.append(f'<div class="wsm">{e(sl["small"])}</div>')
    if kind == "picture":
        nums = "".join(f"<div><b>{e(a)}</b>{e(b)}</div>" for a, b in sl.get("grid") or [])
        parts.append(f'<div class="wpic">{board_mark()}<div class="wk">{e(sl.get("kicker") or "")}</div>'
                     f'<div class="wg">{nums}</div>{pip("hop")}</div>'
                     f'<button class="wgo" onclick="{_pycmd("wrappedpic:" + str(int(view.get("year") or 0)))}">Make the picture</button>'
                     + (f'<div class="wno">{e(sl["small"])}</div>' if sl.get("small") else ""))
    elif sl.get("pose") and kind not in ("turned", "things", "days"):
        parts.append(pip(sl["pose"], "xl" if kind == "cover" else ""))
    if sl.get("note"):
        parts.append(f'<div class="wno">{e(sl["note"])}</div>')
    return (f'<section class="wr-s{" on" if i == 0 else ""}{" lt" if lt else ""}" style="--bg:{e(sl.get("bg") or "#12301a")}" '
            f'aria-roledescription="slide" aria-label="{i + 1} of {total}">{"".join(parts)}</section>')


def wrapped_html(view, cfg):
    """3.9.0, your Wrapped (Sam's pick, round three), in place of the board
    (as the closet is): the year's story on a phone-shaped card, slide by
    slide (wrapped.slides), Pip in your look; tap or the arrow keys move it,
    and it moves on by itself (wrapped_js; not with Reduce motion). Beside
    it the years Anki's history has, All on one page (every slide as
    text), and the way back. view: {year, years, slides, heat, look}."""
    from .. import wrapped as _w
    e = _html.escape
    sl = [s for s in view.get("slides") or [] if cfg.get("sev", True) or s.get("kind") != "things"]
    year = int(view.get("year") or 0)
    if sl:
        phone = (f'<div class="wr-phone" tabindex="0" aria-label="Your {year}, a story: the arrow keys or the sides move it">'
                 f'<div class="wr-bars">{"".join("<i><b></b></i>" for _ in sl)}</div>'
                 + "".join(_wr_slide(i, len(sl), s, view, cfg) for i, s in enumerate(sl))
                 + '<button class="wr-tap l" aria-label="Back"></button><button class="wr-tap r" aria-label="Next"></button></div>')
        lines = "".join(f"<li>{e(_w.words(s))}</li>" for s in sl)
        listing = f'<ol class="wr-list" id="wr-list" hidden>{lines}</ol>'
    else:
        phone = f'<div class="st-note">No reviews in {year} yet.</div>'
        listing = ""
    years = "".join(f'<a href="#" class="{"on" if y == year else ""}" onclick="{_pycmd("wrappedyear:" + str(int(y)))}">{int(y)}</a>'
                    for y in view.get("years") or [] if str(y).isdigit())
    side = (f'<div class="wr-side"><h3>Your {year}</h3>'
            '<p>Made on this computer from your own reviews. Nothing is sent, and only you see it unless you make the picture.</p>'
            + (f'<div class="wr-years" aria-label="Another year">{years}</div>' if years else "")
            + ('<button class="wr-btn" onclick="var l=document.getElementById(\'wr-list\');if(l){l.hidden=!l.hidden;}return false;">'
               'All on one page</button>' if sl else "")
            + (f'<a class="st-lk" href="#" {_st_click("wrappedcard")}>'
               f'{"Leave out the card you turned around" if view.get("card_on") else "Show the card you turned around"}</a>'
               if view.get("card") else "")
            + '</div>')
    sheet = f"{SEV_CSS}{WRAPPED_CSS}{_sev.CSS}" if cfg.get("sev", True) else WRAPPED_CSS
    return (f'<div id="due-crew" class="dc-frame dc-set dc-wr">{_css(cfg)}<style>{SETTINGS_CSS}{sheet}</style>'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span></div>'
            f'<div class="st-bar"><a class="st-back" href="#" {_st_click("wrappedclose")}>&lsaquo; Board</a><b>Your {year}</b></div>'
            f'<div class="wr-wrap">{phone}{side}</div>{listing}</div>')


def wrapped_js():
    """3.9.0: Wrapped's player, said to the page after the board draws it:
    the sides and the arrow keys move it, it moves on by itself and waits
    while the pointer is on it, each slide's Pip plays its moment as it
    comes; with Reduce motion it never moves on by itself. Once a card."""
    return """
    (function() {
        var ph = document.querySelector('#due-crew .wr-phone');
        if (!ph || ph.getAttribute('data-on')) { return; }
        ph.setAttribute('data-on', '1');
        var sl = [].slice.call(ph.querySelectorAll('.wr-s')), bars = [].slice.call(ph.querySelectorAll('.wr-bars b'));
        var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        var st = { i: 0, held: false, run: null }, PER = 6500;
        // 3.9.1 (the efficiency run): each slide's bar fills by one animation
        // the page runs itself (a frame loop drew all along, the last slide
        // and a held one too); held or hidden it waits, and the last runs none
        function go() {
            if (st.run) { if (st.held || document.hidden) { st.run.pause(); } else { st.run.play(); } }
        }
        function show(i) {
            st.i = Math.max(0, Math.min(sl.length - 1, i));
            if (st.run) { st.run.cancel(); st.run = null; }
            sl.forEach(function(s, j) { s.classList.toggle('on', j === st.i); });
            bars.forEach(function(b, j) { b.style.width = j < st.i || (j === st.i && (still || j === sl.length - 1)) ? '100%' : '0'; });
            ph.classList.toggle('lt', sl[st.i].classList.contains('lt'));
            if (!still) {
                sl[st.i].querySelectorAll('.wp svg.sv').forEach(function(v) { var c = v.cloneNode(true); v.parentNode.replaceChild(c, v); });
                if (st.i < sl.length - 1 && bars[st.i].animate) {
                    var b = bars[st.i];  // drawn full and scaled (the compositor's work, no layout a frame)
                    b.style.width = '100%'; b.style.transformOrigin = '0 50%';
                    var run = b.animate([{ transform: 'scaleX(0)' }, { transform: 'scaleX(1)' }], { duration: PER, fill: 'forwards' });
                    st.run = run;
                    run.onfinish = function() { if (st.run === run && document.body.contains(ph)) { show(st.i + 1); } };
                    go();
                }
            }
        }
        ph.querySelector('.wr-tap.l').addEventListener('click', function(ev) { ev.preventDefault(); show(st.i - 1); });
        ph.querySelector('.wr-tap.r').addEventListener('click', function(ev) { ev.preventDefault(); show(st.i + 1); });
        ph.addEventListener('keydown', function(ev) {
            if (ev.key === 'ArrowRight' || ev.key === ' ') { show(st.i + 1); ev.preventDefault(); }
            else if (ev.key === 'ArrowLeft') { show(st.i - 1); ev.preventDefault(); }
        });
        ph.addEventListener('mouseenter', function() { st.held = true; go(); });
        ph.addEventListener('mouseleave', function() { st.held = false; go(); });
        // 3.9.8 (the energy review): one page listener for whichever card is up (each card had added its own)
        window.dcWrGo = go;
        if (!window.dcWrVis) { window.dcWrVis = true; document.addEventListener('visibilitychange', function () { if (window.dcWrGo) { window.dcWrGo(); } }); }
        show(0);
        try { ph.focus({ preventScroll: true }); } catch (e) {}
    })();
    """


def wrapped_line(year, so_far, look, pip=True):
    """3.9.0: the board's line, 1 December to 15 January: your year is
    ready. Open plays it in the board's place; the x is for the year, on
    every computer (the account's wrapped_seen). Pip off: a gift."""
    fig = (f'<span class="dc-fig">{_sev.slot(_sev.svg("hop", rest=True, look=look, label="Your Pip"), 40)}</span>'
           if pip else "<span>&#127873;</span>")
    return (f'<div class="dc-wrap wr-line">{fig}'
            f'<span><b>Your {int(year)}{" so far" if so_far else ""}</b> is ready: your year in Anki{", as Pip saw it" if pip else ""}.</span>'
            f'<a class="wc" href="#" onclick="{_pycmd("wrappedopen:" + str(int(year)))}">Open &#9654;</a>'
            f'<a class="wx" href="#" title="Not this year" onclick="{_pycmd("wrappedx:" + str(int(year)))}">&times;</a></div>')
