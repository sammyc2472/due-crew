"""The fridge: doodles pinned around the Decks screen.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html

from .. import fridge as _fridge
from .. import sev as _sev

from .base import ACCENTS, _by_theme, _pycmd, _short_day, accent_pair
from .windows import POP_JS
from .cheers import DOODLE_INK, _doodle_art
from .dance import DANCE_JS


# 3.9.1: the fridge, around the Decks screen (Sam: "could the fridge just be the
# periphery of the decks window, like dragged around the anki window?")
FRIDGE_W = 124  # px: a doodle on the window, on its paper
FRIDGE_PIP = 30  # px: the Pip by a sender's name on the fridge (a crew row's size; its body is 18)
FRIDGE_UNDO = 8  # s: "In your scrapbook · Undo" in a doodle's place (closet_flow.UNDO_SECS)


def _tape(colour):
    """A tape strip's colour: an accent's light shade (#rrggbb), see-through
    as tape is (rgba, since Anki's older webviews have no color-mix)."""
    h = str(colour).lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "rgba(0,0,0,.12)"
    return f"rgba({r},{g},{b},.6)"


FRIDGE_CSS = """
    #dc-fridge { position: fixed; left: 0; top: 0; right: 0; bottom: 0; pointer-events: none; z-index: 5; }
    #dc-fridge .fz { position: fixed; left: -9999px; top: 0; width: %dpx; box-sizing: border-box; pointer-events: auto;
      background: var(--fz-bg); border-radius: 2px; padding: 7px; color: var(--fz-ink);
      box-shadow: var(--fz-sh); text-align: left; font-size: 10.5px; line-height: 1.3; cursor: grab;
      touch-action: none; user-select: none; -webkit-user-select: none; transform: rotate(var(--fr, -2deg)); }
    #dc-fridge .fz::before { content: ""; position: absolute; top: -8px; left: 50%%; width: 54px; height: 16px; margin-left: -27px;
      background: var(--ft); transform: rotate(-4deg);
      clip-path: polygon(0 12%%, 5%% 0, 30%% 6%%, 60%% 0, 95%% 5%%, 100%% 0, 98%% 50%%, 100%% 100%%, 70%% 94%%, 40%% 100%%, 4%% 95%%, 0 100%%, 2%% 50%%); }
    #dc-fridge .fz.drag { cursor: grabbing; box-shadow: 0 14px 28px rgba(0,0,0,.25); z-index: 1; }
    #dc-fridge .fp { aspect-ratio: 300 / 170; display: grid; place-items: center; overflow: hidden; background: var(--fz-photo); }
    #dc-fridge .fp svg { width: 100%%; height: 100%%; display: block; }
    #dc-fridge .fp .dd-sign { font-size: 13px; line-height: 1.15; text-align: center; padding: 2px 4px; overflow-wrap: anywhere; }
    #dc-fridge .fq { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-top: 7px;
      text-align: center; font-size: 11px; }
    #dc-fridge .fw { display: flex; align-items: center; justify-content: center; gap: 3px; margin-top: 3px; color: var(--fz-muted);
      white-space: nowrap; min-width: 0; }
    #dc-fridge .fw b { color: var(--fz-ink); overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    /* 3.9.2 (Sam: "pips get cutoff on the polaroids"): Pip's head, hat and what it holds reach past its slot,
       so the line never clips (only the name does) and gives the head room under the photo */
    #dc-fridge .fw .sv-slot { --sv-a: var(--fz-pip); flex: none; margin: 9px 2px 0 4px; }
    #dc-fridge .fx { position: absolute; top: 0; right: 3px; display: block; opacity: 0; color: var(--fz-muted); text-decoration: none; font-size: 15px; line-height: 1; }
    /* 3.9.2's QoL pass: hidden by opacity, not display, so Tab reaches it (and shows it) */
    #dc-fridge .fz:hover .fx, #dc-fridge .fz:focus-within .fx, #dc-fridge .fx:focus { opacity: 1; }
    /* 3.9.1 (Sam's pick, "Pip at rest" C): still until pointed at, as crew rows */
    #dc-fridge .fz:not(:hover) .sv, #dc-fridge .fz:not(:hover) .sv * { animation: none !important; }
    /* 3.9.1: where one was just taken down, its Undo for a few seconds, then gone (--fg: how long it's been up) */
    #dc-fridge .fz.fgone { transform: none; cursor: default; text-align: center; font-size: 11.5px; padding: 8px 2px; white-space: nowrap;
      border-radius: 8px; animation: dcfgone %ds linear forwards; animation-delay: var(--fg, 0s); }
    #dc-fridge .fz.fgone::before { display: none; }
    #dc-fridge .fgone a { color: var(--fz-acc); font-weight: 700; text-decoration: none; }
    @keyframes dcfgone { 0%%, 85%% { opacity: 1; } 100%% { opacity: 0; visibility: hidden; } }
    #dc-fridge .fz:hover .sv { --sv-on: var(--sv-hover, infinite); }
""" % (FRIDGE_W, FRIDGE_UNDO)


# 3.9.2 (Sam: "also need dark mode for polaroids"): a Polaroid's colours as
# tokens on each one, light or dark as Settings › Theme says. At night the
# frame and the photo go dark, and a doodle's ink with them: black reads
# light, each colour its own night shade (the board's), and Pip and Undo
# take the sender's night accent (--fd beside --fa on each)
FRIDGE_LIGHT = ("--fz-bg: #fff; --fz-photo: #f4f3ee; --fz-ink: #2b2d29; --fz-muted: #6b665a; --fz-acc: var(--fa); --fz-pip: var(--pa, var(--fa)); "
                "--fz-sh: 0 3px 10px rgba(0,0,0,.16), 0 0 0 1px rgba(0,0,0,.05);")
FRIDGE_INKS = ((DOODLE_INK, "#e6e8e3"),) + tuple(
    (v["light"][0], v["dark"][0]) for _k, v in sorted(ACCENTS.items()))
FRIDGE_DARK = ("--fz-bg: #33352f; --fz-photo: #23241f; --fz-ink: #e6e8e3; --fz-muted: #a3a79c; --fz-acc: var(--fd); --fz-pip: var(--pd, var(--fd)); "
               "--fz-sh: 0 4px 14px rgba(0,0,0,.5), 0 0 0 1px rgba(255,255,255,.07); "
               + " ".join(f"--fz-{a[1:]}: {b};" for a, b in FRIDGE_INKS))
FRIDGE_INK_CSS = "".join(f'#dc-fridge .fp path[stroke="{a}"] {{ stroke: var(--fz-{a[1:]}, {a}); }}' for a, _b in FRIDGE_INKS)


def _fridge_theme(cfg):
    return FRIDGE_INK_CSS + _by_theme(cfg, "#dc-fridge .fz", FRIDGE_LIGHT, FRIDGE_DARK)


def fridge_html(items, people, cfg, gone=None):
    """3.9.1: the doodles my crew sent (fridge.clean's), pinned around the
    Decks screen, newest first: each a Polaroid (Sam's pick from "Pinned
    Doodles": the doodle in a white frame, taped up with a strip in their
    colour), the note it came with on the frame's wide bottom edge, then
    their Pip and name (no "from": Sam, "so there's more room for the
    Pip") and the day, and a × to take it down. Where I dragged one (its p:
    side of the board, px from its edge, px down) rides as data; fridge_js
    places the rest in the gutters beside the board, and lets me drag. ""
    when there's none. Kept as last drawn while what it's drawn from (the
    items, each person's look, Pip on or off) stays the same. gone
    (closet_flow.gone): the one just taken down; in its place "In your scrapbook ·
    Undo" (duecrew:fridgeback:<key>) for the seconds it has left."""
    crew = people or {}
    looks = [[u, 1, e.get("look"), e.get("accent")] if isinstance(e, dict) else [u, 0, e] for u, e in crew.items() if e]
    if gone:
        return _fridge_notes(_fridge.clean(items), crew, cfg, gone)  # a few seconds: drawn each time
    key = _fridge.fingerprint([items, looks, bool(cfg.get("sev", True)), str(cfg.get("theme", "auto"))])
    if key is None or key != _FRIDGE_DRAWN["key"]:
        _FRIDGE_DRAWN.update(key=key, html=_fridge_notes(_fridge.clean(items), crew, cfg))
    return _FRIDGE_DRAWN["html"]


# 3.9.1 (the efficiency run): the fridge as last drawn, kept on what it was
# drawn from, so a redraw doesn't draw its doodles again
_FRIDGE_DRAWN = {"key": None, "html": ""}


def _fridge_notes(items, people, cfg, gone=None):
    if not items and not gone:
        return ""
    notes = []
    for x in reversed(items):
        k = _fridge.key(x)
        e = people.get(x["from"]) or {}
        name = _html.escape(x["name"])
        pip = (_sev.slot(_sev.svg("idle", rest=True, look=e.get("look"), label=f"{name}’s Pip"), FRIDGE_PIP)
               if cfg.get("sev", True) and e else "")
        when = _short_day(x["at"])
        note = f'<div class="fq">&ldquo;{_html.escape(x["n"])}&rdquo;</div>' if x.get("n") else ""
        at = f' data-s="{x["p"][0]}" data-x="{x["p"][1]}" data-y="{x["p"][2]}"' if x.get("p") else ""
        art = _doodle_art(x["d"], x["a"], x["name"] + "’s drawing")  # fridge.clean checked it
        # 3.9.10 (Sam: "everyone's polaroids are now showing their pip as green even if they use a different
        # color"): the Pip is theirs as it is now, so it wears the colour they have now, as it wears what they
        # have on now; the drawing keeps the ink it was made in. One that came with no colour takes theirs
        now = e.get("accent") if isinstance(e, dict) and e.get("accent") in ACCENTS else ""
        fa, tape = accent_pair(x["a"] or now)
        pa, pd = accent_pair(now or x["a"])
        notes.append(f'<div class="fz" data-k="{k}"{at} style="--fa:{fa};--fd:{tape};--pa:{pa};--pd:{pd};--ft:{_tape(tape)}" title="Drag it anywhere">'
                     f'<div class="fp">{art}</div>{note}<div class="fw">{pip}<b>{name}</b>{f" · {when}" if when else ""}</div>'
                     f'<a class="fx" href="#" title="Take it down" aria-label="Take {name}’s down" '
                     f'onclick="{_pycmd("fridgedown:" + k)}">&times;</a></div>')
    if gone and gone.get("item"):
        g, k = gone["item"], str(gone.get("k") or "")
        at = f' data-s="{g["p"][0]}" data-x="{g["p"][1]}" data-y="{g["p"][2]}"' if g.get("p") else ""
        left = max(0.0, min(float(FRIDGE_UNDO), float(gone.get("ago") or 0)))
        notes.insert(max(0, min(len(notes), len(items) - int(gone.get("i") or 0))),
                     f'<div class="fz fgone" data-k="{_html.escape(k)}"{at} role="status" '
                     f'style="--fa:{accent_pair(g.get("a"))[0]};--fd:{accent_pair(g.get("a"))[1]};--fg:-{left:.1f}s">In your scrapbook &middot; '
                     f'<a href="#" onclick="{_pycmd("fridgeback:" + k)}">Undo</a></div>')
    return (f'<style>{FRIDGE_CSS}{_fridge_theme(cfg)}</style>'
            f'<div id="dc-fridge" role="group" aria-label="Your fridge">{"".join(notes)}</div>')


FRIDGE_JS = r"""
window.dcFridge = window.dcFridge || function () {
    var f = document.getElementById('dc-fridge');
    if (!f) { return; }
    var notes = Array.prototype.slice.call(f.querySelectorAll('.fz'));
    var tilt = [-2.5, 2, -1.5, 3, -3, 1.5], nw = __W__, gap = 18;
    // the board's edges in the window (its middle, with no board)
    function edges(box) {
        var dc = f.closest('#due-crew') || document.getElementById('due-crew'), r = dc ? dc.getBoundingClientRect() : null;
        return r ? { l: r.left - box.left, r: r.right - box.left } : { l: box.width / 2, r: box.width / 2 };
    }
    function place() {
        notes = notes.filter(function (el) { return el.isConnected; });  // an Undo whose time ran out has gone
        var box = f.getBoundingClientRect(), W = box.width, H = box.height, b = edges(box);
        var room = { l: b.l >= nw + 2 * gap, r: W - b.r >= nw + 2 * gap }, y = { l: 64, r: 64 }, n = 0, pile = 0, mine = [], at = [];
        // every tilt, then every height in one read (a write between two reads laid the page out again)
        notes.forEach(function (el, i) { el.style.setProperty('--fr', tilt[i % tilt.length] + 'deg'); });
        var hs = notes.map(function (el) { return el.offsetHeight || 140; });
        notes.forEach(function (el, i) {  // where I left each, beside the board's edge; it waits in the corner while the window's too small
            var h = hs[i], x = el.dataset.s ? b[el.dataset.s] + Number(el.dataset.x) : null;
            if (x !== null && x >= 4 && x + nw <= W - 4) {
                at[i] = [x, Math.min(Number(el.dataset.y), H - h - 4)];
                mine.push({ x: x, y: at[i][1], h: h });
            }
        });
        notes.forEach(function (el, i) {
            var h = hs[i], x = null, top;
            if (at[i]) {
                x = at[i][0]; top = at[i][1];
            } else if (!el.dataset.s && (room.l || room.r)) {  // the gutters beside the board, newest highest, left then right
                var side = room.l && room.r ? (n % 2 ? 'r' : 'l') : (room.l ? 'l' : 'r');
                x = side === 'l' ? (b.l - nw) / 2 : b.r + (W - b.r - nw) / 2;
                top = y[side];
                for (var k = 0, hit = true; hit && k < mine.length + 1; k++) {  // below any I left in the way
                    hit = false;
                    mine.forEach(function (m) {
                        if (m.x < x + nw + 6 && x < m.x + nw + 6 && m.y < top + h + gap && top < m.y + m.h + gap) { top = m.y + m.h + gap; hit = true; }
                    });
                }
                y[side] = top + h + gap; n++;
                if (top + h > H - 8) { top = H - h - 8 - (n % 3) * 10; }  // a pile at the bottom once a side is full
            }
            if (x === null) {  // no room: a little pile in the bottom right corner
                x = W - nw - 16 - (pile % 4) * 12; top = H - h - 16 - (pile % 4) * 10; pile++;
            }
            el.style.left = Math.max(4, Math.min(W - nw - 4, x)) + 'px';
            el.style.top = Math.max(4, Math.min(H - h - 4, top)) + 'px';
        });
    }
    notes.forEach(function (el) {  // 3.9.1: an Undo goes when its fade ends (the board's next draw leaves it out too)
        if (el.classList.contains('fgone')) { el.addEventListener('animationend', function () { el.remove(); }); }
    });
    notes.forEach(function (el) {
        el.addEventListener('pointerdown', function (e) {
            if (e.button !== 0 || e.target.closest('.fx') || el.classList.contains('fgone')) { return; }
            e.preventDefault();
            el.setPointerCapture(e.pointerId);
            var box = f.getBoundingClientRect(), sx = e.clientX, sy = e.clientY,
                ox = parseFloat(el.style.left) || 0, oy = parseFloat(el.style.top) || 0, moved = false;
            el.classList.add('drag');
            function move(ev) {
                var nx = Math.max(4, Math.min(box.width - el.offsetWidth - 4, ox + ev.clientX - sx)),
                    ny = Math.max(4, Math.min(box.height - el.offsetHeight - 4, oy + ev.clientY - sy));
                if (Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 3) { moved = true; }
                el.style.left = nx + 'px'; el.style.top = ny + 'px';
            }
            function up() {
                el.removeEventListener('pointermove', move);
                el.removeEventListener('pointerup', up);
                el.removeEventListener('pointercancel', up);
                el.classList.remove('drag');
                if (!moved) { return; }
                // kept by the nearer half of the board: px from that edge, px down
                var b = edges(box), x = parseFloat(el.style.left), s = x + nw / 2 < (b.l + b.r) / 2 ? 'l' : 'r';
                el.dataset.s = s; el.dataset.x = Math.round(x - b[s]); el.dataset.y = Math.round(parseFloat(el.style.top));
                if (typeof pycmd !== 'undefined') {
                    pycmd('duecrew:fridgemove:' + el.dataset.k + ':' + s + ':' + el.dataset.x + ':' + el.dataset.y + '|' + window.dcBK);
                }
            }
            el.addEventListener('pointermove', move);
            el.addEventListener('pointerup', up);
            el.addEventListener('pointercancel', up);
        });
    });
    place();
    window.dcFridgePlace = place;
    if (!window.dcFridgeResize) {
        window.dcFridgeResize = true;
        window.addEventListener('resize', function () { if (window.dcFridgePlace) { window.dcFridgePlace(); } });
    }
};
""".replace("__W__", str(FRIDGE_W))


def fridge_js(scripts=True):
    """3.9.1: after the board is drawn (and at every swap): the fridge's
    doodles placed (where I left each, else beside the board) and made
    draggable; a drop is duecrew:fridgemove:<key>:<side>:<dx>:<y>, beside
    the board's left or right edge (l, r), px from it, px down. A spot the
    window's too small for waits in the corner and comes back at the next
    resize. Nothing when there's no fridge on the page. scripts: the
    script itself (dcFridge, loaded once a page) as well as its call, as
    keep_me_in_view_js's. 3.9.6: the dance floor's script (DANCE_JS) comes
    with it, the other thing around the board, and the fridge's call puts the
    floor in step first (a swap's calls stay the few they were). 3.9.8: the
    board's one overlay (POP_JS) before it, for the song search."""
    return (FRIDGE_JS + POP_JS + DANCE_JS if scripts else "") + "\nif (window.dcFridge) { window.dcFridge(); }\n"
