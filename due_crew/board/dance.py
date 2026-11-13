"""The dance floor (song of the moment): the booth, the dancers, a song's card, the search.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import json as _json

from .. import closet as _closet
from .. import sev as _sev
from .. import songs as _songs

from .base import BOARD_FONT, DEFAULT_ACCENT, _by_theme, _pycmd, _token_block, accent_pair, initial, palette, button_reset
from .pip import my_look
from .windows import POP_JS, pop_named


# 3.9.6, song of the moment (Sam's sign-off on the mock's dance floor, with his
# notes: "make it less jumpy", one bubble at a time). The Decks screen's
# bottom-right corner: my Pip the DJ at its booth, my song on the decks; each
# mutual crewmate who picked a song dancing beside it as their Pip (their colour
# and look, as on their row), the song in a bubble over their head. A tap opens
# the song's card. render() draws it into a <template> in the board; dance_js
# puts it on the page outside the board, so a swap that changes nothing on the
# floor leaves it as it is (dancing, resting, a card open), and keeps it in step.
DANCE_W, DANCE_H = 392, 212  # px: the floor, the booth at its right
DANCE_NW, DANCE_NH = 252, 196  # px: folded (a narrow window): the booth, one dancer, a count
DANCE_NARROW = 900  # px: the window's width under which it folds
DANCE_BOARD = 1448  # px: under this the floor's corner reaches the board's (640 wide, centred): room after it
DANCE_MAX = 6  # dancers; past it five, and "+N" in the sixth's place (never on top of one)
DANCE_SLOT = 66  # px: a dancer's place, counted from the booth (Sam: start by the DJ, then toward the middle);
#   the back row sits half a place along, higher
DANCE_PIP, DANCE_PIP_BACK, DANCE_DJ = 80, 70, 96  # px: the drawings (slot()'s size): front row, back row, the DJ
DANCE_REST = 12  # s: dancing when the board draws, then resting (Pip's loops); pointing plays it on
DANCE_TICK = 0.4  # s: half a beat (Lively steps a move every two)
DANCE_SAY = 12  # ticks: each bubble's turn, about five seconds
DANCE_AREA = DANCE_W - 150 - 10  # px: the dancers' room, left of the booth


def _rgba(colour, a):
    """#rrggbb as rgba(), see-through by a (no color-mix in older webviews)."""
    h = str(colour).lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return f"rgba(0,0,0,{a})"
    return f"rgba({r},{g},{b},{a})"


def _dance_hue(text):
    """A colour for a song with no cover yet (and its decks' labels): from its words, the same each time."""
    return sum((i + 1) * ord(ch) for i, ch in enumerate(str(text or ""))) % 360


def _dance_tokens(cfg, sel):
    """The board's tokens on a part that sits outside it (the floor, the search), by Settings › Theme."""
    accent = cfg.get("accent", DEFAULT_ACCENT)
    lt, dk = palette("light", accent), palette("dark", accent)
    more = lambda p, ink, sh: f"--df-glow: {_rgba(p['accent'], .28)}; --df-check: {ink}; --df-sh: {sh};"  # noqa: E731
    return _by_theme(cfg, sel, _token_block(lt) + more(lt, "rgba(0,0,0,.06)", "0 3px 8px rgba(0,0,0,.14)"),
                     _token_block(dk) + more(dk, "rgba(255,255,255,.07)", "0 3px 10px rgba(0,0,0,.5)"))


DANCE_OFF_CSS = ("#dc-off { position: fixed; right: 12px; bottom: 10px; z-index: 6; background: var(--canvas-elevated, #fff); color: var(--fg, #333); "
                 "border: 1px solid var(--border, #e2e2da); border-radius: 999px; padding: 5px 12px; font: 12.5px/1.3 -apple-system, BlinkMacSystemFont, sans-serif; "
                 "box-shadow: 0 3px 8px rgba(0,0,0,.14); } #dc-off a { color: #2e7d32; font-weight: 700; text-decoration: none; margin-left: 8px; } "
                 ".night-mode #dc-off a, .nightMode #dc-off a { color: #7cc47f; }")

DANCE_CSS = """
#dc-dance { position: fixed; right: 12px; bottom: 6px; width: __W__px; height: __H__px; z-index: 6; pointer-events: none;
  font-family: __FONT__; font-size: 13px; line-height: 1.3; color: var(--dc-ink); text-align: left;
  --sv-line: var(--dc-line); --sv-amb: var(--dc-hours); --sv-mut: var(--dc-muted); --sv-a: var(--dc-accent); }
#dc-dance *, #dc-song * { box-sizing: border-box; }
#dc-dance [hidden], #dc-song [hidden] { display: none !important; }
/* Anki's Decks screen gives every button its look (and macOS its own): ours start from none */
__BUTTONS__
#dc-dance button { background: none; border: 0; padding: 0; cursor: pointer; text-align: inherit; }
#dc-dance button:focus-visible, #dc-dance a:focus-visible, #dc-song button:focus-visible, #dc-song a:focus-visible {
  outline: 2px solid var(--dc-accent) !important; outline-offset: 2px; }
#dc-dance .df-sc { position: absolute; inset: 0; }
#dc-dance .df-fl { position: absolute; left: var(--fl, -10px); right: 112px; bottom: 0; height: 104px; border-radius: 50%; pointer-events: none;
  background: radial-gradient(ellipse at 50% 45%, var(--df-glow), transparent 72%),
    repeating-conic-gradient(var(--df-check) 0 25%, transparent 0 50%) 0 0 / 20px 20px;
  -webkit-mask: radial-gradient(ellipse at center, #000 52%, transparent 71%); mask: radial-gradient(ellipse at center, #000 52%, transparent 71%); }
#dc-dance .df-dn { position: absolute; left: 0; bottom: 4px; width: __AREA__px; height: 176px; }
#dc-dance .dz { position: absolute; bottom: 0; right: calc(var(--x) * 1px); width: 60px; display: block; text-align: center;
  z-index: 2; color: var(--dc-ink); }
#dc-dance .dz .dzb { position: absolute; left: 0; top: 0; width: 100%; height: 100%; pointer-events: auto; border-radius: 12px; }
#dc-dance .dz.bk { bottom: 58px; z-index: 1; }
#dc-dance .dz.say, #dc-dance .dz:hover, #dc-dance .dz:focus-within { z-index: 4; }
#dc-dance .hp { display: block; }
#dc-dance .pp { display: block; width: -webkit-fit-content; width: fit-content; margin: 0 auto; pointer-events: none; transform-origin: 50% 100%; }
#dc-dance .pp .sv-slot { display: block; }
#dc-dance .pp .fc { display: grid; place-items: center; width: 42px; height: 42px; margin: 4px auto 2px; border-radius: 50%;
  border: 2px solid var(--sv-a); background: var(--dc-bg); font-size: 20px; font-weight: 800; color: var(--sv-a); }
#dc-dance .dz .nm { display: block; font-size: 10.5px; font-weight: 700; line-height: 1.2; margin-top: 2px; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; pointer-events: none; }
/* one bubble at a time (dance_js passes it along), and the one pointed at; it fades, never jumps */
#dc-dance .bub { position: absolute; left: 50%; bottom: calc(100% + 6px); transform: translateX(-50%); opacity: 0; pointer-events: none;
  background: var(--dc-bg); color: var(--dc-ink); border: 1px solid var(--dc-line); border-radius: 11px;
  padding: 3px 9px; box-shadow: var(--df-sh); z-index: 3; }
@media (prefers-reduced-motion: no-preference) { #dc-dance .bub { transition: opacity .45s ease; } }
#dc-dance .bub > span { display: block; max-width: 136px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  font-size: 11px; font-weight: 600; line-height: 1.35; }
#dc-dance .bub::after { content: ""; position: absolute; left: 50%; bottom: -5px; width: 8px; height: 8px; margin-left: -4px;
  background: var(--dc-bg); border-right: 1px solid var(--dc-line); border-bottom: 1px solid var(--dc-line); transform: rotate(45deg); }
#dc-dance .dz.say .bub, #dc-dance .dz:hover .bub, #dc-dance .dz:focus-within .bub, #dc-dance .bub.on { opacity: 1; }
#dc-dance .dz.say .bub, #dc-dance .dz:hover .bub, #dc-dance .dz:focus-within .bub { pointer-events: auto; cursor: pointer; }
#dc-dance .bub .st { color: #d99a00; }
#dc-dance .df-more, #dc-dance .df-ct { position: absolute; pointer-events: auto; border: 1px solid var(--dc-line); background: var(--dc-bg);
  color: var(--dc-ink); border-radius: 99px; font-size: 11.5px; font-weight: 700; line-height: 1.3; padding: 3px 10px; box-shadow: var(--df-sh); }
#dc-dance .df-more { right: calc(var(--x) * 1px + 6px); bottom: 80px; }
#dc-dance .df-ct { display: none; right: 66px; bottom: 26px; }
#dc-dance .df-em { position: absolute; right: 0; bottom: 34px; max-width: 220px; font-size: 12px; color: var(--dc-muted); pointer-events: none;
  background: var(--dc-bg); border: 1px solid var(--dc-line); border-radius: 10px; padding: 5px 10px; box-shadow: var(--df-sh); }
/* the booth: my Pip behind the desk, the decks, my song's name under it */
#dc-dance .df-bo { position: absolute; right: 0; bottom: 0; width: __BOOTH__px; height: 152px; pointer-events: auto; display: block; }
#dc-dance .df-bo .bsv { position: absolute; left: 0; bottom: 24px; width: 100%; height: auto; z-index: 1; pointer-events: none;
  filter: drop-shadow(0 5px 8px rgba(0,0,0,.22)); }
#dc-dance .df-bo .dj { position: absolute; left: 50%; bottom: 76px; transform: translateX(-50%); z-index: 0; pointer-events: none; }
#dc-dance .df-bo .dj .bub { bottom: calc(100% + 10px); }
#dc-dance .df-bo .tag { position: absolute; left: 50%; bottom: 0; transform: translateX(-50%); max-width: 100%; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; font-size: 11.5px; font-weight: 650; line-height: 1.3; padding: 2px 8px;
  border: 1.5px solid var(--dc-accent); border-radius: 8px; background: var(--dc-bg); color: var(--dc-ink); pointer-events: none; }
#dc-dance .df-bo .tag.no { border-color: var(--dc-line); color: var(--dc-muted); }
#dc-dance .eqb { fill: var(--dc-accent); transform-box: fill-box; transform-origin: 50% 100%; transform: scaleY(.55); }
#dc-dance .led { fill: var(--dc-accent); opacity: .5; }
#dc-dance.dm-lively.go .led { opacity: 1; }
#dc-dance .woof { transform-box: fill-box; transform-origin: 50% 50%; }
#dc-dance .spin { transform-box: view-box; transform-origin: 0 0; opacity: 0; }
#dc-dance.dm-lively.go .spin { opacity: 1; }
/* 3.9.12 (Sam: the × "closes it permanently which i don't think people realize"): the fold is the floor's one button */
#dc-dance .df-fd { position: absolute; right: 0; top: 42px; pointer-events: auto; width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center; color: var(--dc-muted); background: var(--dc-bg); border: 1px solid var(--dc-line);
  opacity: 0; transition: opacity .2s; }
#dc-dance .df-fd svg { width: 12px; height: 12px; display: block; }
#dc-dance:hover .df-fd, #dc-dance:focus-within .df-fd { opacity: 1; }
/* the song list's foot (and my card's): the one deliberate way to turn the floor off */
#dc-dance .df-off { border-top: 1px solid var(--dc-line); margin-top: 8px; padding-top: 7px; font-size: 12px; text-align: left; }
#dc-dance .df-off a { color: var(--dc-muted); text-decoration: underline; text-underline-offset: 2px; }
#dc-dance .df-off a:hover { color: var(--dc-ink); }
/* "Still this one?": over the booth on my song's last day */
#dc-dance .df-ask { position: absolute; right: 28px; bottom: 142px; pointer-events: auto; background: var(--dc-bg); color: var(--dc-ink);
  border: 1px solid var(--dc-line); border-radius: 12px; padding: 7px 26px 8px 11px; box-shadow: var(--df-sh); font-size: 12.5px;
  line-height: 1.35; white-space: nowrap; text-align: left; }
#dc-dance .df-ask b { display: block; font-weight: 700; }
#dc-dance .df-ask small { display: block; color: var(--dc-muted); font-size: 12px; max-width: 170px; overflow: hidden; text-overflow: ellipsis; }
#dc-dance .df-ask a, #dc-dance .df-ask button.lk { color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 12.5px; padding: 0;
  background: none; border: 0; cursor: pointer; }
#dc-dance .df-ask i { color: var(--dc-faded); font-style: normal; margin: 0 4px; }
#dc-dance .df-ask .ax { position: absolute; right: 6px; top: 4px; color: var(--dc-muted); font-weight: 400; font-size: 14px; line-height: 1; }
#dc-dance.fold .df-ask { display: none; }
/* folded: a chip in the corner, a record and how many songs (a star when one's new); a tap opens it again */
#dc-dance .df-chip { display: none; position: absolute; right: 0; bottom: 0; pointer-events: auto; align-items: center; gap: 6px;
  padding: 4px 11px 4px 5px; border-radius: 99px; border: 1px solid var(--dc-line); background: var(--dc-bg); color: var(--dc-ink);
  font-size: 12px; font-weight: 700; line-height: 1.2; box-shadow: var(--df-sh); white-space: nowrap; }
#dc-dance .df-chip svg { width: 22px; height: 22px; display: block; flex: none; }
#dc-dance .df-chip .st { color: #d99a00; }
#dc-dance.fold .df-sc, #dc-dance.fold .df-cards { display: none; }
#dc-dance.fold .df-chip { display: inline-flex; }
/* a song's card, over the floor */
#dc-dance .df-pop { position: absolute; right: 0; bottom: calc(100% + 6px); width: 340px; max-width: calc(100vw - 24px);
  max-height: calc(100vh - __H__px - 24px); overflow: auto; pointer-events: auto; z-index: 8; display: grid; gap: 8px;
  background: var(--dc-bg); color: var(--dc-ink); border: 1px solid var(--dc-line); border-radius: 12px; padding: 10px 12px 12px;
  box-shadow: 0 12px 32px rgba(0,0,0,.22); }
@media (max-height: 520px) { #dc-dance .df-pop { bottom: 0; max-height: calc(100vh - 16px); } }
#dc-dance .df-pop .ph { display: flex; justify-content: space-between; align-items: center; gap: 8px; font-size: 12px; color: var(--dc-muted); }
#dc-dance .df-pop .x { font-size: 19px; line-height: 1; color: var(--dc-muted); padding: 0 3px; border-radius: 6px; }
#dc-dance .sg { display: flex; gap: 12px; align-items: flex-start; }
#dc-dance .cov, #dc-song .cov { position: relative; flex: none; display: grid; place-items: center; overflow: hidden; border-radius: 8px;
  color: #fff; font-weight: 800; background: linear-gradient(135deg, hsl(var(--h) 55% 46%), hsl(calc(var(--h) + 50) 60% 30%)); }
#dc-dance .cov img, #dc-song .cov img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; background: #000; }
#dc-dance .tx, #dc-song .tx { display: grid; gap: 2px; min-width: 0; }
#dc-dance .tx b { font-size: 14px; overflow-wrap: anywhere; }
#dc-dance .tx .mt, #dc-song .tx .mt { font-size: 12px; color: var(--dc-muted); overflow-wrap: anywhere; }
#dc-dance .acts { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 6px; }
#dc-dance .bt { border: 1px solid var(--dc-line); background: var(--dc-bg); border-radius: 8px; padding: 5px 10px; font-size: 12.5px;
  font-weight: 600; line-height: 1.2; white-space: nowrap; }
#dc-dance .bt.pri { background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }
/* Apple's badge, as Apple serves it (never recoloured or redrawn); its words when it doesn't load */
#dc-dance .bdg, #dc-song .bdg { display: flex; align-items: center; gap: 8px; }
#dc-dance .bdg img, #dc-song .bdg img { display: block; height: 30px; width: auto; }
#dc-dance .bdg a, #dc-song .bdg a { text-decoration: none; line-height: 0; }
#dc-dance .bdg .bdt, #dc-song .bdg .bdt { line-height: 1.3; color: var(--dc-accent); font-size: 12px; font-weight: 700; }
/* a card's foot: Apple's credit and its badge, set apart from Listen */
#dc-dance .ft, #dc-song .ft { display: flex; align-items: center; justify-content: space-between; gap: 12px;
  border-top: 1px solid var(--dc-line); padding-top: 8px; }
/* the credit wraps; the badge keeps its place on the right (Sam) */
#dc-dance .ft .cr, #dc-song .ft .cr { flex: 1 1 auto; min-width: 0; font-size: 11px; line-height: 1.35; color: var(--dc-muted); }
#dc-dance .ft .bdg, #dc-song .ft .bdg { flex: none; margin-left: auto; }
/* till I've picked my music app: the apps themselves, a tap picks one and opens the song there */
#dc-dance .lsn { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
#dc-dance .lsn .lw { font-size: 12px; font-weight: 600; color: var(--dc-muted); margin-right: 2px; }
#dc-dance .lsn .bt { border-radius: 99px; }
#dc-dance .df-ls { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; max-height: 280px; overflow: auto; }
#dc-dance .df-ls button { width: 100%; display: flex; gap: 9px; align-items: center; text-align: left; border-radius: 8px; padding: 5px 6px; }
#dc-dance .df-ls button:hover { background: var(--dc-well); }
#dc-dance .df-ls .nt { flex: none; width: 22px; height: 22px; border-radius: 50%; display: grid; place-items: center; font-size: 12px;
  color: var(--dc-bg); background: var(--sv-a); }
#dc-dance .df-ls .tx b { font-size: 13px; }
#dc-dance .new { margin-left: auto; flex: none; font-size: 11px; font-weight: 700; color: var(--dc-accent); background: var(--dc-you-bg);
  border-radius: 99px; padding: 1px 7px; }
/* the search: a sheet over the board, as the board's questions are */
#dc-song { font-family: __FONT__; color: var(--dc-ink); text-align: left; }  /* its shade: dcPop (POP_JS) */
#dc-song .sw { width: 440px; max-width: 100%; border-radius: 14px; padding: 14px 16px; display: grid; gap: 10px; font-size: 13px; line-height: 1.35;
  background: var(--dc-bg); border: 1px solid var(--dc-line); box-shadow: 0 16px 60px rgba(0,0,0,.35); }
#dc-song .sh { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
#dc-song .sh b { font-size: 16px; }
#dc-song .x { background: none; border: 0; font-size: 20px; line-height: 1; color: var(--dc-muted); padding: 0 3px; cursor: pointer; border-radius: 6px; }
#dc-song .sq { width: 100%; height: 34px; border-radius: 8px; border: 1px solid var(--dc-line); background: var(--dc-well); color: var(--dc-ink);
  font-size: 13.5px; padding: 0 10px; }
#dc-song .sq:focus-visible { outline: 2px solid var(--dc-accent); outline-offset: 0; }
#dc-song .ss { font-size: 12px; color: var(--dc-muted); }
#dc-song .ss:empty { display: none; }
#dc-song .sr { list-style: none; margin: 0; padding: 0; display: grid; gap: 2px; max-height: 300px; overflow-y: auto; }
#dc-song .sr button { width: 100%; display: flex; gap: 10px; align-items: center; text-align: left; background: none; border: 1px solid transparent;
  border-radius: 10px; padding: 5px 6px; cursor: pointer; }
#dc-song .sr button:hover { background: var(--dc-well); }
#dc-song .sr button[aria-selected=true] { background: var(--dc-you-bg); border-color: var(--dc-accent); }
#dc-song .sr .tx b { font-size: 13px; overflow-wrap: anywhere; font-weight: 700; }
#dc-song .sn { font-size: 11.5px; color: var(--dc-muted); }
#dc-song .sf { display: flex; align-items: center; gap: 8px; }
#dc-song .sf .sp { flex: 1; }
#dc-song .go { background: var(--dc-accent); color: var(--dc-accent-ink); border: 1px solid transparent; border-radius: 8px; padding: 6px 16px;
  font-weight: 700; cursor: pointer; }
#dc-song .go:disabled { opacity: .45; cursor: default; }
#dc-song .no { background: none; border: 1px solid var(--dc-line); border-radius: 8px; padding: 6px 14px; cursor: pointer; }
/* folded, on a narrow window: the booth, one dancer, and how many songs (the list) */
@media (max-width: __NARROW__px) {
  #dc-dance { width: __NW__px; height: __NH__px; }
  #dc-dance .df-bo { width: 112px; height: 130px; }
  #dc-dance .df-bo .dj { bottom: 58px; transform: translateX(-50%) scale(.78); transform-origin: 50% 100%; }
  #dc-dance .df-fl { left: 20px; right: 80px; }
  #dc-dance .df-dn { width: 130px; }
  #dc-dance .dz:not(.d0), #dc-dance .df-more { display: none; }
  #dc-dance .df-ct { display: block; }
  #dc-dance .df-em { max-width: 124px; }
}
@media (prefers-reduced-motion: no-preference) {
  /* Gentle (the default): a slow sway, each in its own time, from still and back to still (dance_js lets each finish its sway) */
  #dc-dance.dm-gentle .dz.go .pp { animation: df-sway 2.8s ease-in-out calc(var(--i) * .35s) infinite; }
  @keyframes df-sway { 0%, 100% { transform: none; } 25% { transform: rotate(-4deg) translateY(-1px); } 75% { transform: rotate(4deg) translateY(-1px); } }
  #dc-dance.dm-gentle .dj.go .pp { animation: df-nod 1.6s ease-in-out infinite; }
  @keyframes df-nod { 0%, 100% { transform: none; } 50% { transform: translateY(2px) rotate(-2deg); } }
  /* Lively: a move on the beat (dance_js steps .b1 and .b3 in, with a rest between) */
  #dc-dance.dm-lively .pp, #dc-dance.dm-lively .pp .sv-armL, #dc-dance.dm-lively .pp .sv-armR { transition: transform .2s ease-out; }
  #dc-dance.dm-lively.b1 .dz.go.v0 .sv-armL, #dc-dance.dm-lively.b3 .dz.go.v2 .sv-armL { transform: rotate(118deg); }
  #dc-dance.dm-lively.b1 .dz.go.v0 .sv-armR, #dc-dance.dm-lively.b3 .dz.go.v2 .sv-armR { transform: rotate(-118deg); }
  #dc-dance.dm-lively.b1 .dz.go.v0 .pp { transform: translateY(-4px); }
  #dc-dance.dm-lively.b3 .dz.go.v0 .pp { transform: scale(1.06, .94); }
  #dc-dance.dm-lively.b1 .dz.go.v1 .sv-armR { transform: rotate(-120deg); }
  #dc-dance.dm-lively.b1 .dz.go.v1 .pp { transform: rotate(-6deg); }
  #dc-dance.dm-lively.b3 .dz.go.v1 .sv-armL { transform: rotate(120deg); }
  #dc-dance.dm-lively.b3 .dz.go.v1 .pp { transform: rotate(6deg); }
  #dc-dance.dm-lively.b1 .dz.go.v2 .pp { transform: translateY(-7px); }
  #dc-dance.dm-lively.b1 .dj.go .pp, #dc-dance.dm-lively.b3 .dj.go .pp { transform: translateY(3px); }
  /* Lively: the booth plays along (the equaliser, the speakers, a glint round the decks) */
  #dc-dance.dm-lively.go .eqb { animation: df-eq .4s ease-in-out var(--d) infinite alternate; }
  @keyframes df-eq { from { transform: scaleY(.3); } to { transform: scaleY(1); } }
  #dc-dance.dm-lively.go .woof { animation: df-woof .4s ease-in-out infinite alternate; }
  @keyframes df-woof { to { transform: scale(1.14); } }
  #dc-dance.dm-lively.go .spin { animation: df-rot 1.8s linear infinite; }
  @keyframes df-rot { to { transform: rotate(360deg); } }
  /* a song that's new to me: its dancer hops onto the floor from the booth, once */
  #dc-dance .dz.fresh .hp { animation: df-hop .9s cubic-bezier(.2, .8, .3, 1.2) .4s both; }
  @keyframes df-hop { from { transform: translate(48px, -26px); opacity: 0; } 55% { transform: translate(0, -12px); opacity: 1; } to { transform: none; } }
  #dc-dance:hover .sv { --sv-on: var(--sv-hover, infinite); }
}
""".replace("__BUTTONS__", button_reset("#dc-dance button, #dc-song button, #dc-song input", "font: inherit; color: inherit; border-radius: 0;")).replace("__W__", str(DANCE_W)).replace("__H__", str(DANCE_H)).replace("__NW__", str(DANCE_NW)).replace(
    "__NH__", str(DANCE_NH)).replace("__NARROW__", str(DANCE_NARROW - 1)).replace("__AREA__", str(DANCE_AREA)).replace(
    "__BOOTH__", "150").replace("__FONT__", BOARD_FONT)


# the folded floor's chip: a record, my colour on its label
DANCE_RECORD = ('<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="#151515"/>'
                '<circle cx="12" cy="12" r="8.4" fill="none" stroke="#2c2c2c" stroke-width=".8"/>'
                '<circle cx="12" cy="12" r="6.2" fill="none" stroke="#2c2c2c" stroke-width=".8"/>'
                '<path d="M5.2 8.6 A7.6 7.6 0 0 1 10.4 4.6" fill="none" stroke="rgba(255,255,255,.22)" stroke-width="1.4" stroke-linecap="round"/>'
                '<circle cx="12" cy="12" r="4" style="fill:var(--dc-accent)"/><circle cx="12" cy="12" r="1" fill="#e8e8e8"/></svg>')


def _dance_speaker(x):
    return (f'<g><rect x="{x}" y="40" width="18" height="54" rx="4.5" fill="#232622" stroke="#3a3e38" stroke-width=".8"/>'
            f'<circle cx="{x + 9}" cy="50" r="2.6" fill="#0f100f"/>'
            f'<circle class="woof" cx="{x + 9}" cy="72" r="7" fill="#0f100f" stroke="#3a3e38" stroke-width="1.2"/>'
            f'<circle cx="{x + 9}" cy="72" r="2.3" fill="#30342f"/></g>')


def _dance_deck(cx, label):
    """A deck seen from the front: the platter, my song's label, the arm; a glint that goes round when it's Lively."""
    return (f'<ellipse cx="{cx}" cy="31" rx="20" ry="5.8" fill="#141514" stroke="#343832" stroke-width=".8"/>'
            f'<ellipse cx="{cx}" cy="31" rx="13.5" ry="3.8" fill="none" stroke="#2b2e2a" stroke-width=".7"/>'
            f'<ellipse cx="{cx}" cy="31" rx="5.6" ry="1.7" fill="{label}"/>'
            f'<g transform="translate({cx} 31) scale(1 .28)"><g class="spin"><ellipse cx="15" cy="0" rx="1.2" ry="4.2" fill="#fff" opacity=".85"/></g></g>'
            f'<path d="M{cx + 18} 26 L{cx + 10} 30" stroke="#c9ccc4" stroke-width="1.3" stroke-linecap="round"/>')


def dance_booth_svg(song=None):
    """The DJ booth (the mock's, redrawn): a dark desk with two decks and a mixer, a speaker each side, and an
    equaliser in my colour that plays along when it's Lively. My song's colour on the decks' labels."""
    label = f"hsl({_dance_hue((song or {}).get('al') or (song or {}).get('t'))} 62% 56%)" if song else "#d9d2c3"
    hs = (10, 17, 23, 14, 25, 19, 12, 21, 9)
    bars = "".join(f'<rect class="eqb" style="--d:{-i * .17:.2f}s" x="{36 + i * 9.6:.1f}" y="{79 - h}" width="6" height="{h}" rx="2"/>'
                   for i, h in enumerate(hs))
    return ('<svg class="bsv" viewBox="0 0 150 96" aria-hidden="true">'
            + _dance_speaker(0) + _dance_speaker(132)
            + '<rect x="15" y="22" width="120" height="20" rx="7" fill="#4b5049"/>'
            '<rect x="19" y="38" width="112" height="56" rx="10" fill="#2c302b" stroke="#3d423b" stroke-width=".8"/>'
            '<rect x="19" y="38" width="112" height="3.5" fill="#363a34"/>'
            + _dance_deck(43, label) + _dance_deck(107, label)
            + '<rect x="64" y="26.5" width="22" height="8" rx="2.2" fill="#5d6359"/>'
            '<circle cx="68.5" cy="29.3" r="1.3" fill="#cfd3c9"/><circle cx="75" cy="29.3" r="1.3" fill="#cfd3c9"/>'
            '<circle cx="81.5" cy="29.3" r="1.3" fill="#cfd3c9"/><rect x="70" y="32" width="10" height="1.2" rx=".6" fill="#2b2e2a"/>'
            f'<rect x="30" y="48" width="90" height="35" rx="7" fill="#171916"/>{bars}'
            '<rect class="led" x="28" y="87.5" width="94" height="2.2" rx="1.1"/></svg>')


def _dance_line(song):
    """"Artist · Album · 2025": what's known, escaped."""
    return " &middot; ".join(_html.escape(str(x)) for x in (song.get("a"), song.get("al"), song.get("y")) if x)


def _dance_when(at, today=None):
    """When they picked it: "today", "yesterday", or "since 30 Oct"; "" when it's not known."""
    try:
        d = _dt.date.fromisoformat(str(at or ""))
    except ValueError:
        return ""
    n = ((today or _dt.date.today()) - d).days
    return "picked today" if n <= 0 else "picked yesterday" if n == 1 else f"since {d.day} {d.strftime('%b')}"


def _dance_cover(song, size=64):
    """The song's cover from Apple's catalog, unaltered; till it loads (or when there's none), a tile in its colour."""
    s = song or {}
    words = str(s.get("al") or s.get("t") or "?")
    ini = "".join(w[0] for w in words.split()[:2] if w).upper() or "?"
    img = (f'<img src="{_html.escape(s["art"])}" alt="" width="{size}" height="{size}" loading="lazy" '
           f'onerror="this.remove()">' if s.get("art") else "")
    return (f'<span class="cov" style="--h:{_dance_hue(words)};width:{size}px;height:{size}px;font-size:{round(size / 2.6)}px" '
            f'aria-hidden="true">{_html.escape(ini)}{img}</span>')


def _dance_badge(who):
    """Apple's "Listen on Apple Music" badge, as Apple serves it, opening the song on Apple Music
    (duecrew:songapple); when the image doesn't load, the same words as a link."""
    cmd = _pycmd(f"songapple:{who}")
    return (f'<span class="bdg"><a href="#" title="Listen on Apple Music" onclick="{cmd}">'
            f'<img src="{_html.escape(_songs.BADGE_URL)}" alt="Listen on Apple Music" height="{_songs.BADGE_H}" loading="lazy" '
            f'onerror="this.parentNode.hidden=true;this.parentNode.nextElementSibling.hidden=false"></a>'
            f'<a class="bdt" href="#" hidden onclick="{cmd}">Listen on Apple Music</a></span>')


def _dance_listen(who, view):
    """Listen in my music app, by its name ("Listen in Spotify"; another app: the title and artist, copied).
    Till I've said which app (Sam, after the click test: "I was never offered"), the card's own row of them:
    "Listen in" Apple Music · Spotify · YouTube Music · Other, a tap picking it for this computer and opening
    the song there (songlisten:<uid>:<app>). Settings changes it."""
    app = view.get("app") if view.get("app") in dict(_songs.APPS) else ""
    if app:
        word = "Copy title and artist" if app == "other" else f"Listen in {_html.escape(_songs.app_name(app))}"
        return f'<button type="button" class="bt pri" onclick="{_pycmd("songlisten:" + who)}">{word}</button>'
    short = {"other": "Other"}
    tip = {"other": "Copies the title and artist"}
    apps = "".join(f'<button type="button" class="bt" title="{tip.get(k, "Opens it in " + n)}" '
                   f'onclick="{_pycmd(f"songlisten:{who}:{k}")}">{short.get(k, n)}</button>' for k, n in _songs.APPS)
    return f'<div class="lsn" role="group" aria-label="Listen in"><span class="lw">Listen in</span>{apps}</div>'


def _dance_card(who, song, view, name=""):
    """A song's card: its cover, title, artist · album · year, Listen in my app (till I've picked one, the apps
    themselves, a row of their own), and at its foot Apple's credit and badge (songs.py: Apple's terms for a
    cover). Mine: Change… and Take it off instead of Listen."""
    e = _html.escape
    mine = who == "me"
    head = "&#9834; Your study soundtrack" if mine else f"&#9834; {e(name)}&rsquo;s study soundtrack"
    when = _dance_when(song.get("at"))
    if when and not mine:
        head += f" &middot; {when}"
    row = ""
    if mine:
        acts = ('<button type="button" class="bt pri" data-find>Change&hellip;</button>'
                f'<button type="button" class="bt" onclick="{_pycmd("songclear")}">Take it off</button>')
    else:
        listen = _dance_listen(who, view)
        acts, row = ("", listen) if listen.startswith('<div class="lsn"') else (listen, "")
    label = "Your song" if mine else f"{name}’s song"
    return (f'<div class="df-pop" data-card="{e(who)}" role="dialog" aria-label="{e(label)}" hidden>'
            f'<div class="ph"><span>{head}</span><button type="button" class="x" data-close aria-label="Close">&times;</button></div>'
            f'<div class="sg">{_dance_cover(song)}<div class="tx"><b>{e(song["t"])}</b><span class="mt">{_dance_line(song)}</span>'
            f'{f"<span class=acts>{acts}</span>" if acts else ""}</div></div>{row}'
            f'<div class="ft"><span class="cr">{e(_songs.CREDIT)}</span>{_dance_badge(who)}</div>'
            f'{_dance_off() if mine else ""}</div>')


def _dance_off():
    """3.9.12: "Turn off the dance floor", at the foot of the song list and of my own card."""
    return (f'<div class="df-off"><a href="#" title="Settings &rsaquo; Board brings it back" '
            f'onclick="{_pycmd("dancehide")}">Turn off the dance floor</a></div>')


def dance_off_js():
    """The line that stands in the floor's corner for a few seconds once it's turned off: Undo brings it back."""
    line = (f'Dance floor off<a href="#" onclick="{_pycmd("danceshow")}">Undo</a>')
    return ("(function(){var o=document.getElementById('dc-off');if(o){o.remove();}"
            "o=document.createElement('div');o.id='dc-off';o.setAttribute('role','status');o.innerHTML=" + _json.dumps(line) + ";"
            "var s=document.createElement('style');s.textContent=" + _json.dumps(DANCE_OFF_CSS) + ";o.appendChild(s);"
            "document.body.appendChild(o);setTimeout(function(){if(o.parentNode){o.remove();}},6000);})();")


def _dance_list(crew):
    """Everyone's songs (the "+N" and the folded floor's count open it): newest first, each opening its card."""
    e = _html.escape
    rows = "".join(
        f'<li><button type="button" data-open="{e(p["uid"])}" style="--fa-l:{accent_pair(p.get("accent"))[0]};'
        f'--fa-d:{accent_pair(p.get("accent"))[1]}"><span class="nt" aria-hidden="true">&#9834;</span>'
        f'<span class="tx"><b>{e(p["song"]["t"])}</b><span class="mt">{e(p["name"])} &middot; {e(p["song"]["a"])}</span></span>'
        f'{"<span class=new>new</span>" if p.get("fresh") else ""}</button></li>' for p in crew)
    return (f'<div class="df-pop" data-card="*" role="dialog" aria-label="Your crew&rsquo;s songs" hidden>'
            f'<div class="ph"><span>&#9834; Your crew&rsquo;s songs &middot; {len(crew)}</span>'
            f'<button type="button" class="x" data-close aria-label="Close">&times;</button></div>'
            f'<ul class="df-ls">{rows}</ul>{_dance_off()}</div>')


def _dance_dancer(i, p, view, place):
    """A crewmate on the floor: their Pip (their colour and look) or, Pip off, their initial in their colour;
    their name; the song in a bubble over their head (★ when it's new to me). The whole of it is the button;
    the drawing never takes a click."""
    e = _html.escape
    s = p["song"]
    back = i >= 3
    name = str(p.get("name") or "?")
    if view.get("pip", True):
        fig = _sev.slot(_sev.svg("idle", rest=True, look=p.get("look") or None, label=e(f"{name}’s Pip")),
                        DANCE_PIP_BACK if back else DANCE_PIP)
    else:
        fig = f'<span class="fc">{e(initial(name))}</span>'
    light, dark = accent_pair(p.get("accent"))
    mark = '<b class="st">&#9733;</b> ' if p.get("fresh") else "&#9834; "
    cls = f'dz d{i} v{i % 3}{" bk" if back else ""}{" fresh" if p.get("fresh") else ""}{" say" if i == place else ""}'
    x = (i - 3) * DANCE_SLOT + DANCE_SLOT // 2 if back else i * DANCE_SLOT
    said = f"{name}’s song: {s['t']} by {s['a']}"
    # the drawing, the name and the bubble spill out of the place (a hat, a long title); the button is laid over it
    # each Pip blinks on its own clock (Sam: "they're blinking at the same time"; sev.blink, as a room's seats)
    return (f'<span class="{cls}" style="--x:{x};--i:{i};--fa-l:{light};--fa-d:{dark};{_sev.blink_css(i)}">'
            f'<span class="bub" data-open="{e(p["uid"])}"><span>{mark}{e(s["t"])}</span></span>'
            f'<span class="hp"><span class="pp">{fig}</span><span class="nm">{e(name)}</span></span>'
            f'<button type="button" class="dzb" data-open="{e(p["uid"])}" aria-label="{e(said)}"></button></span>')


def _dance_dj(view, cfg):
    """My Pip behind the booth, headphones on (the closet's, over whatever's on its head); with no song of
    mine it waves, a bubble asking for one. Pip off: my colour's ♪ in its place."""
    me = view.get("me")
    if view.get("pip", True):
        look = my_look(cfg)
        if "headphones" not in _closet.shown(look):
            look = _closet.wear(look, "headphones")
        fig = _sev.slot(_sev.svg("idle" if me else "hello", rest=True, look=look, label="Your Pip, the DJ"), DANCE_DJ)
    else:
        fig = '<span class="fc">&#9834;</span>'
    ask = "" if me else '<span class="bub on"><span>Put on a song?</span></span>'
    return f'<span class="dj" style="{_sev.blink_css(DANCE_MAX)}"><span class="pp">{fig}</span>{ask}</span>'


def _dance_keys(view, cfg):
    """(scene, cards): what the floor is drawn from, and what its cards say besides. A swap that changes neither
    keeps the floor on the page as it is; one that changes the cards alone redraws just those. A new song's hop
    isn't in either: it plays when the floor is first drawn with it."""
    import hashlib
    crew = [[p.get("uid"), p.get("name"), p.get("accent"), p.get("look"), p.get("song")] for p in view.get("crew") or []]
    scene = _json.dumps([crew, view.get("me"), bool(view.get("ask")), bool(view.get("pip", True)), view.get("motion"), my_look(cfg),
                         cfg.get("theme", "auto"), cfg.get("accent", DEFAULT_ACCENT)], sort_keys=True, default=str)
    k = hashlib.sha1(scene.encode()).hexdigest()[:12]
    c = hashlib.sha1(_json.dumps([k, view.get("app")]).encode()).hexdigest()[:12]
    return k, c


def dance_html(view, cfg):
    """3.9.6, song of the moment: the dance floor for the Decks screen's corner, from song_flow.floor_view
    ({me, crew: [{uid, name, accent, look, song, fresh}], motion, app, pip, folded}); "" when it's None. A
    <template> in the board (and the room it needs after the board, while the two would meet), which dance_js
    puts on the page as #dc-dance. Up to DANCE_MAX dancers, newest first, the first beside the booth and the
    rest toward the middle (the checkered floor under just them), then "+N" (the whole list) in the last
    one's place; on a narrow window, the booth, one dancer and a count. No lights (Sam: distracting).
    Folded (Sam's "collapse": the view's folded, the page's own fold at once, dancefold), a chip in the
    corner: a record, how many songs, a star when one's new; turning it off is a line at the foot of the song list and of my card (dancehide, 3.9.12). Every word in it is theirs or Apple's: escaped here, and
    only cleaned songs (songs.clean) are drawn. Each click a keyed command, or a card's, the list's, the
    fold's or the search's opening (dance_js)."""
    if not view:
        return ""
    me = _songs.clean(view.get("me"))
    crew = []
    for p in view.get("crew") or []:
        s = _songs.clean((p or {}).get("song"))
        if s and p.get("uid"):
            crew.append(dict(p, uid=str(p["uid"]), name=str(p.get("name") or "?"), song=s))
    view = dict(view, me=me, crew=crew)
    motion = view.get("motion") if view.get("motion") in _songs.MOTIONS else "gentle"
    key, cards_key = _dance_keys(view, cfg)
    many = len(crew) > DANCE_MAX
    shown = crew[:DANCE_MAX - 1] if many else crew
    place = next((i for i, p in enumerate(shown) if p.get("fresh")), 0)  # the first bubble: a new song's, else the newest
    dancers = "".join(_dance_dancer(i, p, view, place) for i, p in enumerate(shown))
    if many:
        last = DANCE_MAX - 1
        x = (last - 3) * DANCE_SLOT + DANCE_SLOT // 2 if last >= 3 else last * DANCE_SLOT
        dancers += (f'<button type="button" class="df-more" data-open="*" style="--x:{x}" '
                    f'aria-label="All {len(crew)} of your crew&rsquo;s songs">+{len(crew) - len(shown)}</button>')
    if len(crew) > 1:
        dancers += (f'<button type="button" class="df-ct" data-open="*" aria-label="All {len(crew)} of your crew&rsquo;s songs">'
                    f'&#9834; {len(crew)}</button>')
    if not crew:
        dancers += '<span class="df-em">No one&rsquo;s picked a song yet.</span>'
    e = _html.escape
    said = f"Your song: {me['t']} by {me['a']}" if me else "Put on a song"
    booth = (f'<button type="button" class="df-bo" data-open="{"me" if me else "search"}" aria-label="{e(said)}">'
             f'{_dance_dj(view, cfg)}{dance_booth_svg(me)}'
             f'<span class="tag{"" if me else " no"}">{"&#9834; " + e(me["t"]) if me else "No song yet"}</span></button>')
    # 3.9.12: on my song's last day (songs.last_day), till answered: Keep (three more days), Change (the search), ×
    ask = ""
    if me and view.get("ask"):
        ask = (f'<div class="df-ask" role="group" aria-label="Still this one?"><b>Still this one?</b><small>{e(me["t"])}</small>'
               f'<a href="#" onclick="{_pycmd("songkeep")}">Keep</a><i>&middot;</i>'
               f'<button type="button" class="lk" data-open="search">Change</button>'
               f'<a class="ax" href="#" title="Not now" aria-label="Not now" onclick="{_pycmd("songaskoff")}">&times;</a></div>')
    cards = ("".join(_dance_card(p["uid"], p["song"], view, p["name"]) for p in crew)
             + (_dance_card("me", me, view) if me else "") + (_dance_list(crew) if crew else ""))
    # each crewmate in their colour, by day or by night as the board (one selector a call: _by_theme prefixes it)
    tones = "\n".join(_by_theme(cfg, sel, "--sv-a: var(--fa-l);", "--sv-a: var(--fa-d);")
                       for sel in ("#dc-dance .dz", "#dc-dance .df-ls button"))
    folded = bool(view.get("folded"))
    n = len(crew)
    chip = (f'<button type="button" class="df-chip" data-fold="0" title="Open the dance floor" '
            f'aria-label="Open the dance floor{f": {n} song" + ("" if n == 1 else "s") if n else ""}">{DANCE_RECORD}'
            f'<span>&#9834;{f" {n}" if n else ""}</span>'
            f'{"<b class=st>&#9733;</b>" if any(p.get("fresh") for p in crew) else ""}</button>')
    # the floor under the dancers there are: from the farthest one's left, less a little
    xs = [(i - 3) * DANCE_SLOT + DANCE_SLOT // 2 if i >= 3 else i * DANCE_SLOT for i in range(len(shown) + many)]
    fl = max(-10, DANCE_AREA - max(xs) - 60 - 24) if xs else -10
    floor = (f'<div id="dc-dance" class="dm-{motion}{" fold" if folded else ""}" data-k="{key}" data-c="{cards_key}" '
             f'data-me="{1 if me else 0}" data-badge="{e(_songs.BADGE_URL)}" '
             f'role="group" aria-label="Your crew&rsquo;s songs">'
             f'<style>{_dance_tokens(cfg, "#dc-dance")}\n{_dance_tokens(cfg, "#dc-song")}\n{tones}</style>'  # DANCE_CSS: dance_js's
             f'<div class="df-sc"><div class="df-fl" style="--fl:{fl}px"></div><div class="df-dn">{dancers}</div>{booth}'
             f'<button type="button" class="df-fd" data-fold="1" title="Fold it into the corner" aria-label="Fold the dance floor">'
             f'<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 4.5 L6 8 L9.5 4.5" fill="none" stroke="currentColor" '
             f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></button>{ask}</div>'
             f'<div class="df-cards">{cards}</div>{chip}</div>')
    room = (f'<style>#due-crew #dc-dance-room {{ height: 0; }} @media (max-width: {DANCE_BOARD}px) {{ #due-crew #dc-dance-room '
            f'{{ height: {DANCE_H + 8}px; }} #due-crew #dc-dance-room.fold {{ height: 40px; }} }} '
            f'@media (max-width: {DANCE_NARROW - 1}px) {{ #due-crew #dc-dance-room {{ height: {DANCE_NH + 8}px; }} '
            f'#due-crew #dc-dance-room.fold {{ height: 40px; }} }}</style>'
            f'<div id="dc-dance-room"{" class=fold" if folded else ""} aria-hidden="true"></div>')
    return f'<template id="dc-dance-src" data-k="{key}">{floor}</template>{room}'


# The floor on the page: built from the board's <template> when what it's drawn from changed, else left as it
# is (dancing or resting, a card open); its cards alone redrawn when only they changed. Dancing: DANCE_REST
# seconds when it's drawn, then rest; pointing at it plays it on; Still and Reduce
# motion, never. Gentle sways (CSS), each Pip finishing the sway it's in when the floor rests, so nothing
# jumps; Lively steps a move every beat (.b1, .b3), in place, never drawing a Pip again (a redraw on each
# beat swallowed clicks in the mock). One bubble at a time, its turn passed along. The search's songs come
# back as dcSong.results({q, songs, error}): words as
# text, a cover only from Apple's image host.
DANCE_JS = r"""
window.dcDance = window.dcDance || (function () {
    var REST = __REST__, TICK = __TICK__, SAY = __SAY__;
    function look() {  // the floor's look, once a page (a swap carries only the floor), when there's a floor to draw
        if (document.getElementById('dc-dance-css')) { return; }
        var css = document.createElement('style');
        css.id = 'dc-dance-css';
        css.textContent = __CSS__;
        (document.head || document.body).appendChild(css);
    }
    var ART = /^https:\/\/([a-z0-9-]+\.)*mzstatic\.com\/[^\s"'<>\\]*$/i;
    var S = { open: null, was: null, say: 0, restAt: 0, beat: 0, n: 0, hover: false, timer: null, every: 0, saidAt: 0, sheet: null, q: '', qt: null };
    function floor() { return document.getElementById('dc-dance'); }
    function reduce() { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
    function still(f) { return reduce() || f.classList.contains('dm-still'); }
    function send(cmd) { if (typeof pycmd !== 'undefined') { pycmd('duecrew:' + cmd + '|' + window.dcBK); } }
    function each(root, sel, fn) { Array.prototype.forEach.call(root.querySelectorAll(sel), fn); }
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) { e.className = cls; }
        if (text != null) { e.textContent = text; }
        return e;
    }
    function focus(x) { if (x && x.isConnected && x.focus) { try { x.focus({ preventScroll: true }); } catch (err) { /* gone */ } } }
    // the dancers on show (a narrow window folds the floor to one)
    function dancers(f) { return Array.prototype.filter.call(f.querySelectorAll('.dz'), function (d) { return d.offsetParent !== null; }); }
    function say(f, i) {
        var ds = dancers(f);
        each(f, '.dz.say', function (d) { d.classList.remove('say'); });
        if (!ds.length) { return; }
        S.say = ((i % ds.length) + ds.length) % ds.length;
        ds[S.say].classList.add('say');
    }
    function beat(f, b) { f.classList.remove('b1', 'b2', 'b3'); if (b > 0) { f.classList.add('b' + b); } }
    function wake(ms) { S.restAt = Math.max(S.restAt, Date.now() + (ms || REST)); pace(TICK); }
    // 3.9.7 (the energy review): the half-beat tick only while it dances; resting, one tick a bubble's turn
    function pace(ms) { if (S.every === ms && S.timer) { return; } clearInterval(S.timer); S.every = ms; S.timer = setInterval(tick, ms); }
    function resting() { return !!(window.dcRest && window.dcRest.resting()); }  // no move a while, or Anki not in front (sev.REST_JS)
    function away() { return document.hidden || (document.hasFocus && !document.hasFocus()); }
    function tick() {
        var f = floor();
        if (!f) { clearInterval(S.timer); S.timer = null; return; }
        S.n++;
        var on = !folded(f) && !still(f) && ((S.hover && !resting()) || Date.now() < S.restAt);
        if (on) {
            if (!f.classList.contains('go')) { f.classList.add('go'); each(f, '.dz, .dj', function (d) { d.classList.add('go'); }); }
            if (f.classList.contains('dm-lively') && S.n % 2 === 0) { S.beat = (S.beat + 1) % 4; beat(f, S.beat); }
        } else if (f.classList.contains('go')) {
            f.classList.remove('go');
            beat(f, 0);  // Lively's moves ease back to still
            // Gentle's sway goes back to still on its own: each Pip finishes the sway it's in (animationiteration)
            if (!f.classList.contains('dm-gentle') || still(f) || folded(f)) { each(f, '.go', function (d) { d.classList.remove('go'); }); }
        }
        var now = Date.now();
        if (now - S.saidAt >= TICK * SAY - TICK / 2 && !away() && !S.open && !folded(f)) { S.saidAt = now; say(f, S.say + 1); }
        if (!on && !f.classList.contains('go') && !f.querySelector('.go')) { pace(TICK * SAY); }
    }
    function folded(f) { return f.classList.contains('fold'); }
    function room(on) {  // the room after the board: the floor's, or the chip's while it's folded
        var r = document.getElementById('dc-dance-room');
        if (r) { r.classList.toggle('fold', on); }
    }
    // the fold (its chip, in the corner) and back: at once, on the page; the glue keeps it for the next draw (dancefold)
    function fold(on, tell) {
        var f = floor();
        if (!f || on === folded(f)) { return; }
        var had = !!(document.activeElement && f.contains(document.activeElement));
        close();
        if (tell) { S.userOpen = !on; f.removeAttribute('data-auto'); }  // a person's fold or open: fit leaves it be
        f.classList.toggle('fold', on);
        room(on);
        if (tell) { send('dancefold:' + (on ? 1 : 0)); }
        if (on) { tick(); } else { S.n = 0; wake(); tick(); say(f, S.say); }
        if (had) { focus(f.querySelector(on ? '.df-chip' : '.df-fd')); }
    }
    function setup(f) {
        S.open = null; S.was = null; S.n = 0; S.beat = 0; S.hover = false; S.restAt = 0;
        if (!folded(f)) { wake(); }
        var ds = dancers(f);
        say(f, Math.max(0, ds.indexOf(f.querySelector('.dz.say'))));
        f.addEventListener('click', click);
        f.addEventListener('pointerover', function () { S.hover = true; wake(); });
        f.addEventListener('pointerout', function (e) {
            if (!e.relatedTarget || !f.contains(e.relatedTarget)) { S.hover = false; wake(2400); }
        });
        f.addEventListener('focusin', function () { wake(); });
        f.addEventListener('animationiteration', function (e) {
            if (f.classList.contains('go') || (e.animationName !== 'df-sway' && e.animationName !== 'df-nod')) { return; }
            var d = e.target.closest('.dz, .dj');
            if (d) { d.classList.remove('go'); }
        });
        S.saidAt = Date.now();
        f.addEventListener('pointermove', function () { if (S.every !== TICK) { wake(); } });
        pace(TICK);
        tick();
    }
    // the floor open only where it fits beside the board; where it would cover the board, its chip
    // (data-auto: folded for room, not by a person, so it opens again when the window has room)
    function crowded(f) {
        var b = document.getElementById('due-crew');
        if (!b) { return false; }
        var was = folded(f);
        if (was) { f.classList.remove('fold'); }
        var r = f.getBoundingClientRect(), br = b.getBoundingClientRect();
        if (was) { f.classList.add('fold'); }
        return r.width > 0 && br.width > 0 && r.left < br.right + 8;
    }
    function fit() {
        var f = floor();
        if (!f || S.userOpen) { return; }
        if (!folded(f) && crowded(f)) {
            close();
            f.classList.add('fold');
            f.setAttribute('data-auto', '1');
            room(true);
            tick();
        } else if (folded(f) && f.hasAttribute('data-auto') && !crowded(f)) {
            f.classList.remove('fold');
            f.removeAttribute('data-auto');
            room(false);
            S.n = 0;
            wake();
            tick();
        }
    }
    function sync() {
        var t = document.getElementById('dc-dance-src'), cur = floor();
        var src = t && t.content ? t.content.querySelector('#dc-dance') : null;
        if (!src) {  // the board's off, or Settings, the closet or Wrapped in its place
            closeSearch();
            if (cur) { cur.remove(); }
            return;
        }
        if (cur && cur.getAttribute('data-k') === src.getAttribute('data-k')) {
            room(folded(cur));  // the page's fold, newer than the draw's
            if (cur.getAttribute('data-c') !== src.getAttribute('data-c')) {  // only the cards say something new
                var open = S.open, was = S.was, cards = cur.querySelector('.df-cards'), nu = src.querySelector('.df-cards');
                if (cards && nu) { cards.parentNode.replaceChild(document.importNode(nu, true), cards); }
                cur.setAttribute('data-c', src.getAttribute('data-c'));
                S.open = null;
                if (open) { show(open, true); S.was = was; }
            }
            return;
        }
        look();
        var f = document.importNode(src, true);
        if (cur) {
            f.classList.toggle('fold', folded(cur));
            if (cur.hasAttribute('data-auto')) { f.setAttribute('data-auto', '1'); }
            cur.parentNode.replaceChild(f, cur);
        } else { document.body.appendChild(f); }
        room(folded(f));
        setup(f);
        fit();
        if (!S.fits) {
            S.fits = true;
            var ft = 0;
            window.addEventListener('resize', function () { clearTimeout(ft); ft = setTimeout(fit, 150); });
        }
    }
    function click(e) {
        var f = floor(), t = e.target && e.target.closest ? e.target.closest('[data-open], [data-close], [data-fold], [data-find]') : null;
        if (!t || !f || !f.contains(t)) { return; }
        e.preventDefault();
        if (t.hasAttribute('data-close')) { close(); }
        else if (t.hasAttribute('data-fold')) { fold(t.getAttribute('data-fold') === '1', true); }
        else if (t.hasAttribute('data-find')) { close(); search(); }
        else if (t.getAttribute('data-open') === 'search') { search(); }
        else { show(t.getAttribute('data-open')); }
    }
    // a song's card (or the list of them): one at a time, over the floor
    function show(u, quiet) {
        var f = floor(), card = null;
        if (!f) { return; }
        each(f, '.df-pop', function (p) { var it = p.getAttribute('data-card') === u; p.hidden = !it; if (it) { card = p; } });
        if (!card) { S.open = null; return; }
        if (!S.open) { S.was = document.activeElement; }
        S.open = u;
        wake();
        if (!quiet) { focus(card.querySelector('[data-close]')); }
    }
    function close() {
        var f = floor(), was = S.was;
        if (f) { each(f, '.df-pop', function (p) { p.hidden = true; }); }
        S.open = null; S.was = null;
        focus(was);
    }
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && S.open && !S.sheet && !document.getElementById('dc-sheet')) { close(); }
    });
    document.addEventListener('pointerdown', function (e) {
        var f = floor();
        if (S.open && f && !f.contains(e.target) && !S.sheet && !document.getElementById('dc-sheet')) { close(); }
    }, true);
    // ---- my song: Apple's catalog, searched as I type ----
    function hue(w) { var h = 0; for (var i = 0; i < w.length; i++) { h = (h + (i + 1) * w.charCodeAt(i)) % 360; } return h; }
    function cover(song, size) {
        var w = String(song.al || song.t || '?'), c = el('span', 'cov');
        c.style.cssText = '--h:' + hue(w) + ';width:' + size + 'px;height:' + size + 'px;font-size:' + Math.round(size / 2.6) + 'px';
        c.setAttribute('aria-hidden', 'true');
        c.textContent = w.split(/\s+/).filter(Boolean).slice(0, 2).map(function (x) { return x.charAt(0); }).join('').toUpperCase() || '?';
        if (typeof song.art === 'string' && ART.test(song.art)) {
            var img = el('img');
            img.alt = '';
            img.width = img.height = size;
            img.addEventListener('error', function () { img.remove(); });
            img.src = song.art;
            c.appendChild(img);
        }
        return c;
    }
    function badge(src) {  // Apple's, as served; its words when it doesn't load
        var b = el('span', 'bdg'), img = el('img'), t = el('span', 'bdt', 'Listen on Apple Music');
        img.alt = 'Listen on Apple Music';
        img.height = __BADGE_H__;
        t.hidden = true;
        img.addEventListener('error', function () { img.hidden = true; t.hidden = false; });
        img.src = src;
        b.appendChild(img);
        b.appendChild(t);
        return b;
    }
    function search() {
        var f = floor();
        if (!f || S.sheet) { return; }
        close();
        var mine = f.getAttribute('data-me') === '1', src = f.getAttribute('data-badge') || '';
        var pop = window.dcPop.make({ id: 'dc-song', label: 'Your study soundtrack', z: 82, pad: '10vh 16px 16px' });
        var back = pop.back, card = el('div', 'sw'), head = el('div', 'sh'), x = el('button', 'x', '×');
        back.appendChild(card);
        head.appendChild(el('b', null, 'Your study soundtrack'));
        x.type = 'button';
        x.setAttribute('aria-label', 'Close');
        head.appendChild(x);
        card.appendChild(head);
        var inp = el('input', 'sq');
        inp.type = 'text';  // not 'search': its own clear button is the system's to draw
        inp.placeholder = 'Search for a song or artist';
        inp.setAttribute('aria-label', 'Search for a song or artist');
        inp.autocomplete = 'off';
        inp.spellcheck = false;
        inp.maxLength = 80;
        card.appendChild(inp);
        var st = el('div', 'ss'), ls = el('ul', 'sr');
        st.setAttribute('aria-live', 'polite');
        ls.setAttribute('role', 'listbox');
        ls.setAttribute('aria-label', 'Songs');
        card.appendChild(st);
        card.appendChild(ls);
        card.appendChild(el('div', 'sn', 'Your crew sees it. The search goes from this computer to Apple Music.'));
        if (src) {  // at the foot, Apple's credit and badge beside the covers: the picked song's page (or the first's)
            var bd = badge(src), apple = function () {
                var s2 = S.sheet, id = s2 && (s2.picked || (s2.rows[0] && s2.rows[0].getAttribute('data-id')));
                if (id && /^\d{1,16}$/.test(id)) { send('songapple:' + id); }
            };
            bd.setAttribute('role', 'link');
            bd.tabIndex = 0;
            bd.title = 'Listen on Apple Music';
            bd.style.cursor = 'pointer';
            bd.addEventListener('click', apple);
            bd.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); apple(); } });
            var cf = el('div', 'ft');
            cf.appendChild(el('span', 'cr', __CREDIT__));
            cf.appendChild(bd);
            card.appendChild(cf);
        }
        var ft = el('div', 'sf'), go = el('button', 'go', 'Use this'), off = mine ? el('button', 'no', 'Take it off') : null,
            no = el('button', 'no', 'Cancel');
        go.type = no.type = 'button';
        go.disabled = true;
        ft.appendChild(go);
        ft.appendChild(el('span', 'sp'));
        if (off) { off.type = 'button'; ft.appendChild(off); }
        ft.appendChild(no);
        card.appendChild(ft);
        var s = { pop: pop, inp: inp, st: st, ls: ls, go: go, rows: [], picked: '' };
        S.sheet = s;
        S.q = '';
        inp.addEventListener('input', function () {
            clearTimeout(S.qt);
            var q = inp.value.replace(/\s+/g, ' ').trim();
            if (q.length < 2) { S.q = ''; rows([]); st.textContent = ''; return; }
            st.textContent = 'Searching…';
            S.qt = setTimeout(function () { S.q = q; send('songsearch:' + encodeURIComponent(q)); }, 400);
        });
        inp.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown' && s.rows.length) { e.preventDefault(); pick(0); focus(s.rows[0]); }
            else if (e.key === 'Enter') { e.preventDefault(); if (s.picked) { use(); } else if (s.rows.length) { pick(0); } }
        });
        ls.addEventListener('keydown', function (e) {
            var at = s.rows.indexOf(document.activeElement);
            if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && at >= 0) {
                e.preventDefault();
                var to = Math.max(0, Math.min(s.rows.length - 1, at + (e.key === 'ArrowDown' ? 1 : -1)));
                pick(to);
                focus(s.rows[to]);
            }
        });
        go.addEventListener('click', use);
        if (off) { off.addEventListener('click', function () { closeSearch(); send('songclear'); }); }
        no.addEventListener('click', closeSearch);
        x.addEventListener('click', closeSearch);
        // Esc, or a click on the shade, puts it away; what's being searched goes with it
        pop.show(card, { esc: closeSearch, closing: function () { S.sheet = null; S.q = ''; clearTimeout(S.qt); } });
        inp.focus();
    }
    function pick(i) {
        var s = S.sheet;
        if (!s || !s.rows[i]) { return; }
        s.rows.forEach(function (b, j) { b.setAttribute('aria-selected', j === i ? 'true' : 'false'); });
        s.picked = s.rows[i].getAttribute('data-id');
        s.go.disabled = false;
    }
    function use() {
        var s = S.sheet;
        if (!s || !/^\d{1,16}$/.test(s.picked)) { return; }
        var id = s.picked;
        closeSearch();
        send('songuse:' + id);
    }
    function rows(songs) {
        var s = S.sheet;
        if (!s) { return; }
        while (s.ls.firstChild) { s.ls.removeChild(s.ls.firstChild); }
        s.rows = [];
        s.picked = '';
        s.go.disabled = true;
        songs.forEach(function (song) {
            var li = el('li'), b = el('button'), tx = el('span', 'tx'), i = s.rows.length;
            b.type = 'button';
            b.setAttribute('role', 'option');
            b.setAttribute('aria-selected', 'false');
            b.setAttribute('data-id', String(song.id));
            b.appendChild(cover(song, 40));
            tx.appendChild(el('b', null, song.t));
            tx.appendChild(el('span', 'mt', [song.a, song.al, song.y].filter(function (v) { return v; }).join(' · ')));
            b.appendChild(tx);
            b.addEventListener('click', function () { pick(i); });
            b.addEventListener('dblclick', function () { pick(i); use(); });
            li.appendChild(b);
            s.ls.appendChild(li);
            s.rows.push(b);
        });
    }
    function results(o) {
        var s = S.sheet;
        if (!s || !o || String(o.q || '') !== S.q || !S.q) { return; }  // only the latest search lands
        var got = (o.songs || []).filter(function (x) {
            return x && /^\d{1,16}$/.test(String(x.id)) && typeof x.t === 'string' && typeof x.a === 'string';
        });
        rows(o.error ? [] : got);
        s.st.textContent = o.error ? 'Couldn’t reach Apple Music just now. Try again in a moment.'
            : got.length ? '' : 'Nothing by that name. Try the artist.';
    }
    function closeSearch() {
        if (S.sheet) { S.sheet.pop.close(); }  // dcPop: the shade, the key back, the motion layer's way out
    }
    window.dcSong = { results: results };
    return { sync: sync, show: show, close: close, search: search, wake: wake, fold: fold, results: results };
})();
(function () {  // the board's draw calls the fridge (fridge_js): the floor is put in step with it, first
    var f = window.dcFridge;
    if (f && !f.dcDance) {
        window.dcFridge = function () { try { window.dcDance.sync(); } catch (e) { /* the fridge still goes up */ } return f.apply(this, arguments); };
        window.dcFridge.dcDance = true;
    }
})();
""".replace("__REST__", str(DANCE_REST * 1000)).replace("__TICK__", str(round(DANCE_TICK * 1000))).replace(
    "__SAY__", str(DANCE_SAY)).replace("__BADGE_H__", str(_songs.BADGE_H)).replace("__CREDIT__", _json.dumps(_songs.CREDIT_SEARCH)).replace(
    "__CSS__", _json.dumps(pop_named(DANCE_CSS, "dc-song")).replace("</", "<\\/"))


def dance_js(scripts=True):
    """3.9.6: after the board is drawn (and at every swap): the dance floor put on the page from the board's
    template, or left as it is when nothing it's drawn from changed, or taken off with none. scripts: the
    script itself (dcDance and dcSong, once a page) as well as its call, as fridge_js's."""
    return (POP_JS + DANCE_JS if scripts else "") + "\nif (window.dcDance) { window.dcDance.sync(); }\n"
