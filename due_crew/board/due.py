"""Due: the day's to-do over the board (Today, Upcoming, Later), Magic search's way in.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import re as _re
import sys as _sys

from .. import due as _D

from .base import _pycmd, _tab_word
from .planweek import _remark_lines, _topic_a, _topic_go, _wbar, _why_shut
from .plancards import _opened_line


# ---- Due: the day's to-do, above the board ----

DUE_CSS = """
    #due-crew .du { text-align: left; border-radius: 12px; padding: 12px 18px; margin: 0 0 14px;
      display: grid; gap: 6px; align-content: start; }
    #due-crew .du > * { min-width: 0; }
    #due-crew .du a { text-decoration: none; }
    #due-crew .du-h { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    @media (max-width: 460px) { #due-crew .du-h > .du-n { display: none; } }  /* Hide stays on the tabs' line */
    #due-crew .du-h .sp { flex: 1; }
    /* 3.9.3 (Sam: "the QBank piece is a bit higher than everything else"): one line height for the head's words,
       or Hide's ▴ (a fallback font's taller line) and Due's bigger word sit a pixel under the rest */
    #due-crew .du-h > .du-n, #due-crew .du-h > .du-go, #due-crew .du-h > .du-fold,
    #due-crew .du-one > a, #due-crew .du-one > .du-n { line-height: 16px; }
    #due-crew .du-n { color: var(--dc-muted); font-size: 11.5px; white-space: nowrap; }
    #due-crew .du-fold { font-size: 11.5px; font-weight: 600; color: var(--dc-muted); white-space: nowrap; flex: none;
      margin-left: auto; }
    #due-crew .du-one .du-fold { color: var(--dc-accent); font-weight: 700; }
    #due-crew .du-tm { overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 0 1 auto; }
    /* 3.8.0: the box's tabs are words (the board's pills are the buttons): the
       one on screen in ink, underlined; Plans and Insights after a rule */
    #due-crew .du-tabs { display: inline-flex; gap: 14px; white-space: nowrap; }
    #due-crew .du-tabs a { font-size: 12px; font-weight: 700; color: var(--dc-muted); padding: 1px 0 3px; }
    #due-crew .du-tabs a:hover { color: var(--dc-ink); }
    #due-crew .du-tabs a.on { color: var(--dc-ink); box-shadow: inset 0 -2px var(--dc-accent); }
    #due-crew .du-tabs.du-more { padding-left: 14px; border-left: 1px solid var(--dc-line); }
    #due-crew .du-tabs .du-beta { margin-left: 5px; padding: 0 4px; border: 1px solid var(--dc-line); border-radius: 4px;
      font-size: 9px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--dc-muted);
      vertical-align: 1px; }
    #due-crew .du-r { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 2px 9px; align-items: start;
      padding: 5px 0 4px; border-top: 1px solid var(--dc-line); }
    #due-crew .du-r .t { display: grid; gap: 2px; min-width: 0; overflow-wrap: anywhere; }
    #due-crew .du-r .t small, #due-crew .du-m { color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .du-r.done .t > b, #due-crew .du-r.done .t > span.x { color: var(--dc-muted); text-decoration: line-through; }
    #due-crew .du-r .end { display: flex; gap: 10px; align-items: baseline; white-space: nowrap; font-size: 11.5px; }
    #due-crew .du-r .end .n { color: var(--dc-muted); font-variant-numeric: tabular-nums; }
    #due-crew .du-go { color: var(--dc-accent); font-weight: 700; font-size: 11.5px; white-space: nowrap; }
    #due-crew .du-go .nm { display: inline-block; max-width: 160px; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
    #due-crew .du-tag { color: var(--dc-muted); font-size: 11px; white-space: nowrap; }
    #due-crew .du-tag:hover { color: var(--dc-ink); }
    #due-crew .du-bx { box-sizing: border-box; width: 14px; height: 14px; border: 1.5px solid var(--dc-faded);
      border-radius: 4px; margin-top: 2px; display: block; position: relative; }
    #due-crew a.du-bx { cursor: pointer; }
    #due-crew .du-bx.auto { border-style: dashed; }
    #due-crew .du-bx.part { background: linear-gradient(90deg, var(--dc-you-bg) 50%, transparent 50%); border-color: var(--dc-accent); }
    #due-crew .du-bx.on { background: var(--dc-accent); border: 1.5px solid var(--dc-accent); }
    #due-crew .du-bx.on::after { content: ""; position: absolute; left: 3.5px; top: 0.5px; width: 3px; height: 7px;
      border: solid var(--dc-accent-ink); border-width: 0 2px 2px 0; transform: rotate(45deg); }
    #due-crew .du-sub { display: grid; grid-template-columns: 12px minmax(0, 1fr) auto; gap: 7px; align-items: center;
      font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .du-sub b { color: var(--dc-ink); font-weight: 600; }
    #due-crew .du-sub .du-bx { width: 11px; height: 11px; margin: 0; border-radius: 3px; }
    #due-crew .du-sub .du-bx.on::after { left: 2.5px; top: -0.5px; width: 2.5px; height: 6px; }
    #due-crew .du-sub .n { font-variant-numeric: tabular-nums; white-space: nowrap; }
    #due-crew .du-rm { display: block; color: var(--dc-muted); font-size: 11.5px; font-style: italic; text-align: left; }
    #due-crew .du .wbar { margin-top: 3px; }
    /* 3.9.3: a Today row's bar, under its words and numbers, the row's whole
       width (so the bars line up), in two tones: through for today solid,
       answered and back later today light */
    #due-crew .du-r > .wbar { grid-column: 2 / -1; }
    #due-crew .wbar.two { display: flex; }
    #due-crew .wbar.two i { flex: none; }
    #due-crew .wbar.two i.lt { opacity: .35; }
    #due-crew .du-sec { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-muted); padding-top: 4px; }
    #due-crew .du-sec.warn { color: #c77700; }
    #due-crew .du-bh { display: grid; gap: 0; padding-bottom: 8px; }
    #due-crew .du-line { display: flex; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap; font-size: 12px;
      padding: 5px 0 1px; border-top: 1px solid var(--dc-line); color: var(--dc-muted); }
    #due-crew .du-line b { color: var(--dc-ink); font-weight: 600; }
    #due-crew .du-line .acts { display: flex; gap: 12px; }
    #due-crew .du-line a, #due-crew .du-sg a { color: var(--dc-accent); font-weight: 700; }
    #due-crew .du-line a.tp { font-weight: inherit; }
    #due-crew .du-sg { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 9px; font-size: 12px;
      padding: 5px 0; border-top: 1px solid var(--dc-line); align-items: baseline; }
    #due-crew .du-sg .x { color: var(--dc-muted); font-weight: 400; margin-left: 10px; }
    /* 3.9.5: today's misses under a done Reviews row; a deck run out */
    #due-crew .du-rc { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 2px 9px; font-size: 12px;
      color: var(--dc-muted); padding: 0 0 6px; align-items: baseline; text-align: left; }
    #due-crew .du-rc b { color: var(--dc-ink); font-weight: 600; }
    #due-crew .du-rc .end { white-space: nowrap; }
    #due-crew .du-rc a { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .du-rc a.tp { font-weight: inherit; }
    /* 3.9.5: a plan topic on Today, its two ways (Study, Browse) beside its name */
    #due-crew a.dc-tpn.on { text-decoration: underline; text-underline-offset: 2px; }
    #due-crew .du-tpgo a { font-weight: 700; color: var(--dc-accent); text-decoration: none; margin-left: 7px; cursor: pointer;
      border-radius: 4px; padding: 0 3px; }
    #due-crew .du-tpgo a:hover, #due-crew .du-tpgo a:focus-visible { text-decoration: underline; text-underline-offset: 2px; }
    #due-crew .du-tpgo a:active, #due-crew .du-tpgo a.on { background: color-mix(in srgb, var(--dc-accent) 16%, transparent);
      text-decoration: underline; text-underline-offset: 2px; }
    #due-crew .du-add { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; padding-top: 3px; }
    #due-crew .du-add input[type=text] { flex: 1 1 160px; min-width: 0; font: inherit; font-size: 12.5px; color: var(--dc-ink);
      background: var(--dc-bg); border: 1px solid var(--dc-line); border-radius: 7px; padding: 4px 8px; }
    #due-crew .du-add select, #due-crew .du-add input[type=date] { font: inherit; font-size: 12px; color: var(--dc-ink);
      background: var(--dc-bg); border: 1px solid var(--dc-line); border-radius: 7px; padding: 3px 4px; color-scheme: light dark; }
    #due-crew .du-add select { padding-right: 20px; background-repeat: no-repeat; background-size: 4px 4px;
      background-image: linear-gradient(45deg, transparent 50%, var(--dc-muted) 50%), linear-gradient(135deg, var(--dc-muted) 50%, transparent 50%);
      background-position: calc(100% - 11px) 55%, calc(100% - 7px) 55%; }
    #due-crew .du-said { font-size: 11.5px; color: var(--dc-accent); font-weight: 700; white-space: nowrap; }
    #due-crew .du-said a { color: var(--dc-muted); font-weight: 400; margin-left: 4px; }
    #due-crew .du-dh { display: flex; justify-content: space-between; gap: 10px; font-size: 11.5px; font-weight: 700;
      padding-top: 6px; border-top: 1px solid var(--dc-line); }
    #due-crew .du-dh.today { color: var(--dc-accent); }
    #due-crew .du-dh small { color: var(--dc-muted); font-weight: 400; }
    #due-crew .du-dh .plus { color: var(--dc-accent); font-weight: 700; margin-left: 8px; }
    #due-crew .du-ln { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 9px; font-size: 12px;
      padding: 2px 0; align-items: start; }
    #due-crew .du-ln .n { color: var(--dc-muted); font-size: 11px; white-space: nowrap; }
    #due-crew .du-ln.done > span:nth-child(2) { color: var(--dc-muted); text-decoration: line-through; }
    #due-crew .du-q { color: var(--dc-faded); font-size: 11.5px; padding: 3px 0 3px 25px; }
    #due-crew .du-evl { color: #c77700; font-weight: 700; font-size: 12px; padding-left: 25px; }
    #due-crew .du-one { display: flex; align-items: baseline; gap: 6px 12px; padding: 10px 18px; white-space: nowrap; }
    #due-crew .du-one > * { flex: none; }
    #due-crew .du-one .wbar { flex: 0 1 90px; width: auto; min-width: 24px; margin: 0; align-self: center; }
    #due-crew .du-one .sp { flex: 1 1 0; }
    #due-crew .du-one .sp { flex: 1; }
    #due-crew .du-one > a:first-child b { color: var(--dc-accent); font-size: 12.5px; }
    #due-crew .du-one .du-go { flex: 0 1 auto; min-width: 0; max-width: 260px; display: inline-flex; }
    #due-crew .du-one .du-go .nm { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    /* what's next when the day's done: the one part that gives way (else it
       ran past the box and took Show with it) */
    #due-crew .du-one .du-tm { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
    /* narrow: the bar goes and "Study ›" keeps its words (it was squeezed to
       nothing and Show spilled out of the box) */
    @media (max-width: 480px) { #due-crew .du-one .du-go .nm { display: none; }
      #due-crew .du-one .wbar { display: none; } #due-crew .du-one .du-go { min-width: auto; } }
    /* narrower still, there's more than one line holds: it wraps */
    @media (max-width: 400px) { #due-crew .du-one { flex-wrap: wrap; } }
    #due-crew .du-sub a { color: var(--dc-accent); }
    #due-crew .du-empty { color: var(--dc-muted); font-size: 12px; padding: 4px 0; }
    /* round five: a plan's date opens its details under it, a click on its name */
    #due-crew a.du-nm { color: inherit; text-decoration: none; cursor: pointer; }
    #due-crew a.du-nm:hover b { text-decoration: underline; text-decoration-color: var(--dc-faded); }
    #due-crew .du-r.done .t > a.du-nm b { color: var(--dc-muted); text-decoration: line-through; }
    #due-crew .du-dd { display: grid; gap: 3px; margin: 0 0 6px 25px; padding: 2px 0 2px 9px; text-align: left;
      border-left: 2px solid var(--dc-line); font-size: 11.5px; color: var(--dc-muted); overflow-wrap: anywhere; }
    #due-crew .du-dd[hidden] { display: none; }
    #due-crew .du-dd b { color: var(--dc-ink); font-weight: 600; }
    #due-crew .du-dd .acts { display: flex; flex-wrap: wrap; gap: 3px 12px; }
    #due-crew .du-dd a { color: var(--dc-accent); font-weight: 700; }
    #due-crew .du-dd a.tp, #due-crew .du-dd .pwhy a.tp { font-weight: inherit; }
    /* 3.9.5 round three, You › Pip Party: the games up top, the map to pick from, the picks, Host */
    #due-crew .pp { display: grid; gap: 8px; text-align: left; position: relative; }
    #due-crew .pp-gms { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 7px; }
    #due-crew .pp-gm { display: grid; gap: 1px; padding: 9px 11px; border-radius: 13px; border: 1.5px solid transparent; text-decoration: none;
      color: var(--dc-ink); position: relative; overflow: hidden; min-width: 0; cursor: pointer; }
    #due-crew .pp-gm.g-trivia { background: color-mix(in srgb, #3a9a40 15%, var(--dc-bg)); --pp-g: #3a9a40; }
    #due-crew .pp-gm.g-imposter { background: color-mix(in srgb, #d0587f 15%, var(--dc-bg)); --pp-g: #d0587f; }
    #due-crew .pp-gm.g-links { background: color-mix(in srgb, #7b5cd6 15%, var(--dc-bg)); --pp-g: #7b5cd6; }
    #due-crew .pp-gm.on { border-color: var(--pp-g); }
    #due-crew .pp-gm.thin { opacity: .5; cursor: default; }
    #due-crew .pp-gm b { font-size: 14.5px; letter-spacing: -.01em; }
    #due-crew .pp-k { font-size: 11px; color: var(--dc-muted); }
    #due-crew .pp-n { font-size: 11.5px; font-weight: 700; font-variant-numeric: tabular-nums; margin-top: 1px; }
    #due-crew .pp-gm.thin .pp-n { color: var(--dc-hours); }
    #due-crew .pp-first { position: absolute; top: 7px; right: 8px; font-size: 9.5px; font-weight: 800; letter-spacing: .06em; text-transform: uppercase;
      padding: 1px 6px; border-radius: 99px; background: var(--dc-bg); color: var(--dc-ink); display: none; }
    #due-crew .pp-gm.on .pp-first { display: block; }
    #due-crew .pp-art { height: 40px; display: flex; align-items: center; gap: 4px; margin-bottom: 3px; }
    #due-crew .pp-art svg { display: block; }
    #due-crew .pp-4 { display: grid; grid-template-columns: 17px 17px; gap: 3px; }
    #due-crew .pp-sh { width: 17px; height: 17px; }
    #due-crew .pp-sh.s0 { fill: #3a9a40; } #due-crew .pp-sh.s1 { fill: #4f7fe0; } #due-crew .pp-sh.s2 { fill: #d08a1e; } #due-crew .pp-sh.s3 { fill: #d0587f; }
    #due-crew .pp-3 { display: flex; align-items: flex-end; }
    #due-crew .pp-3 > .pp-p, #due-crew .pp-odd { margin-right: -7px; }
    #due-crew .pp-p, #due-crew .pp-odd { display: inline-flex; transform-origin: 50% 100%; }
    #due-crew .pp-odd { position: relative; display: inline-flex; }
    #due-crew .pp-odd i { position: absolute; top: -3px; right: 3px; width: 14px; height: 14px; border-radius: 50%; display: grid; place-items: center;
      font-style: normal; font-size: 10px; font-weight: 900; background: var(--dc-bg); color: #d0587f; }
    #due-crew .pp-25 { display: grid; grid-template-columns: repeat(5, 7px); gap: 2px; }
    #due-crew .pp-25 i { width: 7px; height: 7px; border-radius: 2px; background: var(--dc-line); }
    #due-crew .pp-25 i.g { background: #3a9a40; } #due-crew .pp-25 i.p { background: #7b5cd6; } #due-crew .pp-25 i.x { background: #1f3f73; }
    @media (prefers-reduced-motion: no-preference) {
      /* round three (Sam: "add some animation"): pointed at, a game's picture plays; picked, it plays once */
      #due-crew .pp-gm:not(.thin):hover .pp-sh, #due-crew .pp-gm.just .pp-sh { animation: pp-pop 1.6s ease-in-out var(--k, 0s) var(--sv-hover, infinite); }
      #due-crew .pp-sh.s1 { --k: .18s; } #due-crew .pp-sh.s2 { --k: .36s; } #due-crew .pp-sh.s3 { --k: .54s; } #due-crew .pp-3 .pp-p.p2 { --k: .35s; }
      #due-crew .pp-gm:not(.thin):hover .pp-4 + .pp-p, #due-crew .pp-gm.just .pp-4 + .pp-p { animation: pp-think 2.4s ease-in-out var(--sv-hover, infinite); }
      #due-crew .pp-gm:not(.thin):hover .pp-3 .pp-p, #due-crew .pp-gm.just .pp-3 .pp-p { animation: pp-bob 1.1s ease-in-out var(--k, 0s) var(--sv-hover, infinite); }
      #due-crew .pp-gm:not(.thin):hover .pp-odd, #due-crew .pp-gm.just .pp-odd { animation: pp-look 2.2s ease-in-out var(--sv-hover, infinite); }
      #due-crew .pp-gm:not(.thin):hover .pp-odd i, #due-crew .pp-gm.just .pp-odd i { animation: pp-q 1.1s ease-in-out var(--sv-hover, infinite); }
      #due-crew .pp-gm:not(.thin):hover .pp-25 i, #due-crew .pp-gm.just .pp-25 i { animation: pp-wave 1.6s ease-in-out calc(var(--d) * 70ms) var(--sv-hover, infinite); }
      /* 3.9.7 (the energy review): picked, a picture plays once. This comes after the rules above and
         names each part as they do, or theirs (as specific, or more) kept it playing for good */
      #due-crew .pp-gm.just .pp-sh, #due-crew .pp-gm.just .pp-4 + .pp-p, #due-crew .pp-gm.just .pp-3 .pp-p, #due-crew .pp-gm.just .pp-odd,
      #due-crew .pp-gm.just .pp-odd i, #due-crew .pp-gm.just .pp-25 i { animation-iteration-count: 1; }
      #due-crew .pp-gm.just .pp-art { animation: pp-chosen .45s cubic-bezier(.34, 1.56, .64, 1) 1; }
      @keyframes pp-pop { 0%, 55%, 100% { transform: none; } 18% { transform: translateY(-3px) scale(1.18); } }
      @keyframes pp-think { 0%, 100% { transform: none; } 30% { transform: rotate(-7deg); } 65% { transform: rotate(5deg); } }
      @keyframes pp-bob { 0%, 100% { transform: none; } 45% { transform: translateY(-3px); } }
      @keyframes pp-look { 0%, 100% { transform: none; } 20% { transform: translateX(-2px) rotate(-6deg); } 50% { transform: translateX(2px) rotate(6deg); } 70% { transform: none; } }
      @keyframes pp-q { 0%, 100% { transform: none; } 25% { transform: rotate(-14deg) scale(1.15); } 50% { transform: rotate(10deg); } 75% { transform: rotate(-6deg); } }
      @keyframes pp-wave { 0%, 60%, 100% { transform: none; } 25% { transform: scale(1.35); } }
      @keyframes pp-chosen { 0% { transform: scale(.9); } 60% { transform: scale(1.06); } 100% { transform: none; } }
    }
    #due-crew .pp-kept { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .pp-kb { display: inline-flex; align-items: center; gap: 3px; font-weight: 700; color: var(--dc-ink); text-decoration: none;
      border: 1px solid var(--dc-line); border-radius: 99px; padding: 1px 4px 1px 9px; }
    #due-crew .pp-kb .x, #due-crew .pp-pk .x { font-style: normal; color: var(--dc-muted); padding: 0 3px; cursor: pointer; text-decoration: none; }
    #due-crew .pp-mh { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 2px; }
    #due-crew .pp-mh .ik { margin: 0; }
    #due-crew .pp-by { text-transform: none; letter-spacing: 0; }
    #due-crew #pp-find { margin-left: auto; flex: 0 1 200px; min-width: 0; box-sizing: border-box; font: inherit; font-size: 12px; padding: 4px 10px;
      border-radius: 99px; border: 1px solid var(--dc-line); background: var(--dc-well); color: var(--dc-ink); }
    #due-crew #pp-find:focus { outline: 2px solid var(--dc-accent); outline-offset: -1px; }
    #due-crew .pp-dt { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; font-weight: 700; }
    #due-crew .pp-dt a { color: var(--dc-muted); text-decoration: none; }
    #due-crew .pp-dt a.on { color: var(--dc-ink); box-shadow: inset 0 -2px 0 var(--dc-accent); }
    #due-crew .tmap > .pp-tw { display: flex; position: relative; min-width: 0; }
    #due-crew .pp-tw > .tm { flex: 1; min-width: 0; }
    #due-crew .pp-tw > .tm > span { padding-right: 14px; }
    #due-crew .pp-op { position: absolute; right: 3px; top: 3px; padding: 1px 6px; border-radius: 5px; font-size: 13px; line-height: 1.1; text-decoration: none;
      color: inherit; background: rgba(127, 127, 127, .18); }
    #due-crew .pp-op:hover { background: rgba(127, 127, 127, .34); }
    #due-crew .tm.s3 + .pp-op { color: var(--dc-accent-ink); }
    #due-crew .tm .pp-ck { position: absolute; right: 5px; bottom: 5px; width: 15px; height: 15px; border-radius: 50%; display: none; place-items: center;
      font-style: normal; font-size: 9.5px; font-weight: 900; background: var(--dc-ink); color: var(--dc-bg); }
    #due-crew .tm.pick { box-shadow: inset 0 0 0 2px var(--dc-ink), inset 0 0 0 4px var(--dc-bg); }
    #due-crew .tm.left { box-shadow: inset 0 0 0 2px var(--dc-hours); }
    #due-crew .tm.pick .pp-ck, #due-crew .tm.left .pp-ck { display: grid; }
    #due-crew .tm.left .pp-ck { background: var(--dc-hours); }
    #due-crew .tmap.picking .tm:not(.pick):not(.pp-more) { filter: saturate(.55) opacity(.7); }
    #due-crew .tm .pp-wh { display: block; font-style: italic; font-weight: 500; font-size: 10.5px; opacity: .85; }
    #due-crew .tm.pp-more { background: transparent; box-shadow: inset 0 0 0 1.5px var(--dc-line); color: var(--dc-muted); }
    #due-crew .pp-none { font-size: 12px; color: var(--dc-muted); padding: 6px 0; }
    #due-crew .pp-of { display: flex; gap: 6px; align-items: baseline; flex-wrap: wrap; font-size: 12px; color: var(--dc-muted); }
    #due-crew .pp-as { margin-left: auto; color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .pp-srch[hidden] { display: none; }
    #due-crew .pp-srch input { width: 100%; box-sizing: border-box; font-family: Menlo, Consolas, monospace; font-size: 11.5px; padding: 5px 8px;
      border-radius: 6px; border: 1px solid var(--dc-line); background: var(--dc-well); color: var(--dc-ink); }
    #due-crew .pp-foot { display: flex; gap: 10px 14px; align-items: center; flex-wrap: wrap; padding-top: 9px; border-top: 1px solid var(--dc-line); }
    #due-crew .pp-say { flex: 1; min-width: 190px; display: grid; gap: 4px; }
    #due-crew .pp-say > b { font-size: 13px; font-variant-numeric: tabular-nums; }
    #due-crew .pp-picks { display: flex; flex-wrap: wrap; gap: 4px; }
    #due-crew .pp-pk { display: inline-flex; align-items: center; gap: 2px; font-size: 11.5px; font-weight: 700; padding: 1px 3px 1px 9px; border-radius: 99px;
      background: var(--dc-you-bg); color: var(--dc-accent); border: 1px solid var(--dc-accent); cursor: pointer; }
    #due-crew .pp-pk.out { background: transparent; color: var(--dc-hours); border-color: var(--dc-hours); }
    #due-crew .pp-ln { display: flex; gap: 12px; font-size: 11.5px; }
    #due-crew .pp-ln a { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .pp-host { background: var(--dc-accent); color: var(--dc-accent-ink); font-weight: 700; font-size: 13px; padding: 7px 20px;
      border-radius: 99px; text-decoration: none; white-space: nowrap; }
    #due-crew .pp-host.off { opacity: .4; cursor: default; }
    #due-crew .pp-said { font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .pp-said.bad { color: var(--dc-hours); }
    #due-crew .pp-open { display: grid; gap: 3px; padding: 9px 12px; border-radius: 10px; background: var(--dc-you-bg); font-size: 12.5px; }
    #due-crew .pp-open b { font-size: 14px; letter-spacing: .02em; }
    #due-crew .pp-url { font-family: Menlo, Consolas, monospace; font-size: 12px; overflow-wrap: anywhere; }
    #due-crew .pp-open a { color: var(--dc-accent); font-weight: 700; margin-left: 6px; white-space: nowrap; }
    /* narrow: still three across, the picked one by its border (and Host's words) alone */
    @media (max-width: 520px) { #due-crew .pp-gm { padding: 8px 8px 7px; } #due-crew .pp-k, #due-crew .pp-gm.on .pp-first { display: none; }
      #due-crew .pp-art { height: 30px; transform: scale(.8); transform-origin: left center; } #due-crew .pp-gm.on { border-width: 2px; } }
    #due-crew .pp-fx { position: absolute; left: 32px; top: 20px; width: 0; height: 0; pointer-events: none; display: none; }
    @media (prefers-reduced-motion: no-preference) {
      #due-crew .pp.burst .pp-fx { display: block; }
      #due-crew .pp-fx i { position: absolute; left: -3px; top: -3px; width: 6px; height: 6px; border-radius: 2px;
        background: var(--dc-accent); animation: ppfx .9s ease-out forwards; }
      #due-crew .pp-fx i:nth-child(2n) { background: var(--dc-hours); border-radius: 50%; }
      #due-crew .pp-fx i:nth-child(3n) { background: var(--dc-muted); }
      @keyframes ppfx { 0% { opacity: 1; transform: rotate(var(--r)) translateY(-6px) scale(1); }
        100% { opacity: 0; transform: rotate(var(--r)) translateY(-36px) scale(.4); } }
    }
"""

DUE_JS = r"""
(function () {
  if (window.dcDue) { return; }
  var DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
  var LONG = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
  var MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december'];
  function day(iso) { var p = iso.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
  function iso(d) { return d.toISOString().slice(0, 10); }
  function plus(iso0, n) { var d = day(iso0); d.setUTCDate(d.getUTCDate() + n); return iso(d); }
  function month(w) {
    w = w.replace(/\.$/, '');
    for (var i = 0; i < 12; i++) { if (w.length >= 3 && MONTHS[i].indexOf(w) === 0) { return i + 1; } }
    return 0;
  }
  function onOrAfter(today, m, dd) {
    var y = +today.slice(0, 4);
    for (var k = 0; k < 2; k++) {
      var d = new Date(Date.UTC(y + k, m - 1, dd));
      if (d.getUTCMonth() !== m - 1) { return null; }
      if (iso(d) >= today) { return iso(d); }
    }
    return null;
  }
  // due.when_word, restated for the add line's preview: change one, change both
  function when(w, today) {
    w = w.toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
    if (w === 'today' || w === 'tonight') { return today; }
    if (w === 'tomorrow' || w === 'tmrw' || w === 'tmr') { return plus(today, 1); }
    if (w === 'later' || w === 'someday' || w === 'sometime') { return ''; }
    var wd = (day(today).getUTCDay() + 6) % 7;
    if (w === 'next week') { return plus(today, 7 - wd); }
    var pre = ['next ', 'on ', ''];
    for (var i = 0; i < pre.length; i++) {
      if (w.indexOf(pre[i]) === 0) {
        var name = w.slice(pre[i].length);
        for (var j = 0; j < 7; j++) {
          if (name.length >= 3 && LONG[j].indexOf(name) === 0) {
            var ahead = ((j + 6) % 7 - wd + 7) % 7 || 7;
            return plus(today, ahead);
          }
        }
      }
    }
    var m = w.match(/^([0-9]{1,2})(?:st|nd|rd|th)? ([a-z]{3,9}\.?)$/);
    if (m && month(m[2])) { return onOrAfter(today, month(m[2]), +m[1]); }
    m = w.match(/^([a-z]{3,9}\.?) ([0-9]{1,2})(?:st|nd|rd|th)?$/);
    if (m && month(m[1])) { return onOrAfter(today, month(m[1]), +m[2]); }
    return null;
  }
  function parse(text, today) {
    var words = text.replace(/\s+/g, ' ').trim().split(' ');
    for (var n = 3; n >= 1; n--) {
      if (words.length > n) {
        var d = when(words.slice(-n).join(' '), today);
        if (d !== null) {
          var rest = words.slice(0, -n).join(' ').replace(/[ ,\-·]+$/, '');
          if (rest) { return { text: rest, day: d }; }
        }
      }
    }
    return { text: words.join(' '), day: null };
  }
  // due.repeat_word and due.parse_repeat (3.8.0), restated: change one, change both
  var WEEK = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
  function repeatWord(w) {
    w = w.toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
    if (w === 'daily' || w === 'every day' || w === 'each day') { return '0123456'; }
    if (w === 'weekdays' || w === 'every weekday' || w === 'each weekday') { return '01234'; }
    if (w.slice(-1) === 's' && WEEK.indexOf(w.slice(0, -1)) >= 0) { return String(WEEK.indexOf(w.slice(0, -1))); }
    var m = w.match(/^(?:every|each) ([a-z ]+)$/);
    if (!m) { return null; }
    var on = {}, names = m[1].split(' ');
    for (var i = 0; i < names.length; i++) {
      if (names[i] === 'and') { continue; }
      var k = -1;
      for (var j = 0; j < 7; j++) { if (names[i].length >= 3 && WEEK[j].indexOf(names[i]) === 0) { k = j; break; } }
      if (k < 0) { return null; }
      on[k] = 1;
    }
    var out = '';
    for (var x = 0; x < 7; x++) { if (on[x]) { out += x; } }
    return out || null;
  }
  function parseRepeat(text) {
    var t = text.replace(/\s+/g, ' ').trim();
    var m = t.match(/^([^:]{3,40}):\s*(.+)$/);
    if (m) { var r0 = repeatWord(m[1]); if (r0) { return { text: m[2], rule: r0 }; } }
    var words = t.split(' ');
    for (var n = Math.min(6, words.length - 1); n >= 1; n--) {
      var r = repeatWord(words.slice(-n).join(' '));
      if (r) {
        var rest = words.slice(0, -n).join(' ').replace(/[ ,\-·:]+$/, '');
        if (rest) { return { text: rest, rule: r }; }
      }
    }
    return { text: t, rule: null };
  }
  function repeatLabel(r) {
    if (r === '0123456') { return 'every day'; }
    if (r === '01234') { return 'weekdays'; }
    var out = [];
    for (var i = 0; i < r.length; i++) { var n = WEEK[+r.charAt(i)]; out.push(n.charAt(0).toUpperCase() + n.slice(1, 3)); }
    return 'every ' + out.join(', ');
  }
  function label(d, today) {
    if (d === '') { return 'Later'; }
    if (d === today) { return 'Today'; }
    if (d === plus(today, 1)) { return 'Tomorrow'; }
    var x = day(d);
    return DAYS[x.getUTCDay()].charAt(0).toUpperCase() + DAYS[x.getUTCDay()].slice(1) + ' ' + x.getUTCDate() + ' ' +
      MONTHS[x.getUTCMonth()].charAt(0).toUpperCase() + MONTHS[x.getUTCMonth()].slice(1, 3);
  }
  function el(id) { return document.getElementById(id); }
  window.dcDue = {
    raw: false,
    preview: function () {
      var box = document.querySelector('#due-crew .du'), inp = el('du-in'), said = el('du-said');
      if (!box || !inp || !said) { return; }
      var rp = parseRepeat(inp.value);
      var p = rp.rule ? null : parse(inp.value, box.getAttribute('data-today'));
      if ((!rp.rule && p.day === null) || this.raw) { said.innerHTML = ''; return; }
      said.innerHTML = '&rarr; ' + (rp.rule ? repeatLabel(rp.rule) : label(p.day, box.getAttribute('data-today'))) +
        '<a href="#" title="Keep the words as text" onclick="dcDue.raw=true;dcDue.preview();return false;">&times;</a>';
    },
    pick: function () {
      var sel = el('du-when'), dt = el('du-date');
      if (sel && dt) { dt.style.display = sel.value === 'pick' ? '' : 'none'; if (sel.value === 'pick') { dt.focus(); } }
    },
    key: function (e) {
      if (e.key === 'Enter') { e.preventDefault(); this.send(); return; }
      if (e.key === 'Escape') { e.target.value = ''; this.raw = false; this.preview(); }
    },
    send: function () {
      var inp = el('du-in'), sel = el('du-when'), dt = el('du-date');
      if (!inp || !inp.value.trim()) { return; }
      var w = sel ? sel.value : 'today';
      if (w === 'pick') { w = (dt && dt.value) ? dt.value : 'today'; }
      if (window.dcMotion) {  // 3.8.0: the redraw shows where it went
        var r = inp.getBoundingClientRect();
        dcMotion.say({add: inp.value.trim().slice(0, 16), when: w, from: {x: r.left, y: r.top}});
      }
      pycmd('duecrew:dueadd:' + w + ':' + (this.raw ? 1 : 0) + ':' + encodeURIComponent(inp.value) + '|' + window.dcBK);
      this.raw = false;
      inp.value = '';  // sent: a redraw doesn't put it back (swap_js keeps a half-typed one)
    },
    plus: function (d) {
      var sel = el('du-when'), dt = el('du-date'), inp = el('du-in');
      if (!sel || !inp) { return; }
      var found = false;
      for (var i = 0; i < sel.options.length; i++) { if (sel.options[i].value === d) { found = true; } }
      if (found) { sel.value = d; if (dt) { dt.style.display = 'none'; } }
      else { sel.value = 'pick'; if (dt) { dt.value = d; dt.style.display = ''; } }
      inp.focus();
    }
  };
})();
"""


def _due_box(state, auto=True):
    cls = "du-bx" + (" auto" if auto else "") + (" on" if state == "on" else " part" if state == "part" else "")
    return f'<span class="{cls}"></span>'


def _due_tick(cmd, on, label):
    return (f'<a href="#" class="du-bx{" on" if on else ""}" role="checkbox" aria-checked="{"true" if on else "false"}" '
            f'title="{_html.escape(label)}" aria-label="{_html.escape(label)}" onclick="{_pycmd(cmd)}"></a>')


def _due_mine(r, short=False):
    e = _html.escape
    tick = _due_tick("duetick:" + r["id"], r["done"], "Done" if not r["done"] else "Not done")
    if r.get("ahead"):
        tick = '<span class="du-bx"></span>'  # 3.8.0: a repeat's next day ticks on that day
    tag = f'<a href="#" class="du-tag" title="Move, edit or delete" onclick="{_pycmd("dueitem:" + r["id"])}">{e(r["tag"])} &#9662;</a>'
    if short:
        return (f'<div class="du-ln{" done" if r["done"] else ""}">{tick}<span>{e(r["text"])}</span>'
                f'<span class="n">{tag}</span></div>')
    do = (f'<a href="#" class="du-go" onclick="{_pycmd("duedo:" + r["id"])}">Do today</a>'
          if not r["day"] and not r["done"] else "")
    return (f'<div class="du-r{" done" if r["done"] else ""}">{tick}<span class="t"><span class="x">{e(r["text"])}</span></span>'
            f'<span class="end">{do}{tag}</span></div>')


def _due_every(r, short=False):
    """3.8.0: a plan's weekly line ("Do · Practice questions", every Fri),
    ticked by hand for the day; a day ahead's ticks on that day."""
    e = _html.escape
    text = e(r["text"])
    if r.get("url", "").startswith("https://"):
        text = f'<a href="#" title="{e(r["url"])}" onclick="{_pycmd("duelink:" + r["key"])}">{text}</a>'
    tick = ('<span class="du-bx"></span>' if r.get("ahead")
            else _due_tick(f'duetodo:{r["key"]}', r["done"], "Done" if not r["done"] else "Not done"))
    if short:
        return (f'<div class="du-ln{" done" if r["done"] else ""}">{tick}<span><b>{e(r["label"])}</b> &middot; {text}'
                f' <span class="du-m">&middot; {e(r["plan"])}</span></span><span class="n">{e(r["tag"])}</span></div>')
    return (f'<div class="du-r{" done" if r["done"] else ""}">{tick}<span class="t"><span class="x"><b>{e(r["label"])}</b> '
            f'&middot; {text}</span><small>{e(r["plan"])} &middot; {e(r["tag"])}</small></span><span class="end"></span></div>')


def _date_more(r, topics=False):
    """Round five (Sam: "what happens when you click on a date? worried
    about overlap with the today page"): a plan's date on Today or Upcoming
    opens, a click on its name, what the Plans tab's week had for it: its
    cards in Browse and the ones left, Open now (ahead of its day, or shut
    again), Move…, Skip it, Put it back, and why it left cards shut;
    topics: its topics too (Upcoming's line has none). (the name's link,
    the details under the row), or the bare name and "" with nothing in
    them."""
    e = _html.escape
    pid, uid = str(r["pid"]), str(r["uid"])
    total, seen = int(r.get("total") or 0), int(r.get("seen") or 0)
    later, own = bool(r.get("future")), bool(r.get("own"))
    acts = []
    if total:
        acts.append(f'<a href="#" onclick="{_pycmd(f"planbrowse:{pid}:{uid}")}">Browse {total:,} card{"s" if total != 1 else ""}</a>')
    if not later and 0 < seen < total:
        acts.append(f'<a href="#" onclick="{_pycmd(f"planleft:{pid}:{uid}")}">{total - seen:,} left</a>')
    if later or r.get("shut"):
        acts.append(f'<a href="#" onclick="{_pycmd(f"plannow:{pid}:{uid}")}">Open now</a>')
    if not own and not r.get("done"):  # from today on, a date not done moves later on my copy
        acts.append(f'<a href="#" onclick="{_pycmd(f"planmove:{pid}:{uid}")}">Move&hellip;</a>')
    if later and not own:
        acts.append(f'<a href="#" onclick="{_pycmd(f"planskip:{pid}:{uid}")}">Skip it</a>')
    if r.get("moved"):
        acts.append(f'<a href="#" onclick="{_pycmd(f"planmoveback:{pid}:{uid}")}">Put it back</a>')
    what = ""
    if topics and r.get("topics"):
        what = "".join(f'<span>{f"<b>{e(str(g))}</b> &middot; " if g else ""}'
                       + ", ".join(_topic_a(pid, uid, x, i) for x, i in xs) + '</span>'
                       + _remark_lines(xs, r.get("rm"), "du-rm") for g, xs in r["topics"])
    body = what + (f'<span class="acts">{"".join(acts)}</span>' if acts else "") + _why_shut(pid, uid, r.get("why"))
    name = f'<b>{e(r["name"])}</b>'
    if not body:
        return name, ""
    did = f"dc-dd-{_re.sub(r'[^A-Za-z0-9]', '', pid)}-{_re.sub(r'[^A-Za-z0-9]', '', uid)}"
    link = (f'<a class="du-nm" href="#" title="Its cards, and what you can do with it" '
            f'onclick="var x=document.getElementById(\'{did}\');if(x)x.hidden=!x.hidden;return false;">{name}</a>')
    return link, f'<div class="du-dd" id="{did}" hidden>{body}</div>'


def _due_plan(r):
    """A plan's date on Today, in full: its resources (each with its topics,
    3.8.0), the author's lines, its bar; round five: its name opens its
    details (_date_more)."""
    e = _html.escape
    box = _due_box("on" if r["done"] else "part" if r["part"] else "", auto=True)
    groups, used = list(r.get("topics") or []), set()

    def topics_of(label):
        # a resource's topics on its own row (P.parts groups as P.topics does; no resource is "Other")
        for k, (g, xs) in enumerate(groups):
            if k not in used and (g == label or (label == "Other" and not g)):
                used.add(k)
                return (" &middot; " + ", ".join(_topic_go(r["pid"], r["uid"], x, i) for x, i in xs)
                        + _remark_lines(xs, r.get("rm"), "du-rm"))  # 3.8.1: the authors' notes under it
        return ""
    subs = ""
    for ln in r["lines"]:
        if ln["kind"] == "part":
            subs += (f'<span class="du-sub"><span class="du-bx auto{" on" if ln["done"] else ""}"></span>'
                     f'<span><b>{e(ln["label"])}</b>{topics_of(ln["label"])}</span>'
                     f'<span class="n">{int(ln["seen"]):,} / {int(ln["total"]):,}</span></span>')
        else:
            text = e(ln["text"])
            if ln.get("url", "").startswith("https://"):
                # opened by Anki in the browser, never inside the Decks screen
                text = f'<a href="#" title="{e(ln["url"])}" onclick="{_pycmd("duelink:" + ln["key"])}">{text}</a>'
            tick = (_due_tick(f'duetodo:{ln["key"]}', ln["done"], "Done") if ln["can"]
                    else '<span class="du-bx"></span>')
            subs += (f'<span class="du-sub">{tick}<span><b>{e(ln["label"])}</b> &middot; {text}</span>'
                     f'<span class="n">by hand</span></span>')
    extra = []
    if r.get("prep"):
        extra.append(f'{"after" if r.get("after") else "for"} {e(r["prep"])}')  # 3.8.1: after its event, reinforcement
    if r.get("crew") and int(r["crew"][1]) > 1:
        extra.append(f'crew {int(r["crew"][0]):,} of {int(r["crew"][1]):,} done')
    if r.get("upd"):
        # 3.7.3: an author's update adds to this date; it opens when I say
        said = f'+{int(r["upd"]):,} added' if int(r["upd"]) > 0 else "updated"
        extra.append(f'{said} &middot; <a href="#" onclick="{_pycmd("planupdopen:" + r["pid"])}">Open</a>')
    meta = " &middot; ".join([f'{e(r["plan"])}'] + extra)
    rest = [(g, xs) for k, (g, xs) in enumerate(groups) if k not in used]
    if rest:  # 3.8.0: each topic opens its cards in Browse; 3.9.5: studies them
        # as the Plans tab's day writes them: the group in bold, then its topics
        what = "<small>" + " &middot; ".join((f"<b>{e(str(g))}</b> &middot; " if g else "") + ", ".join(_topic_go(r["pid"], r["uid"], x, i) for x, i in xs)
                                              for g, xs in rest) + "</small>"
        what += "".join(_remark_lines(xs, r.get("rm"), "du-rm") for _g, xs in rest)  # 3.8.1
    elif groups:
        what = ""
    else:
        what = f'<small>{e(r["what"])}</small>' if r.get("what") else ""
    bar = _wbar2(r.get("through", r["seen"]), r.get("later", 0), r["total"]) if r["total"] and not r["done"] else ""
    go = ""  # 3.8.0: one Study, the box's Study today (its first step is this plan's deck)
    if r.get("study"):  # 3.8.1: but a plan's date with cards open has its own: a cram of just it
        cmd = _pycmd(f"planstudydate:{r['pid']}:{r['uid']}")
        go = (f'<a href="#" class="du-go" title="A filtered deck: its new cards and the ones due today" '
              f'onclick="{cmd}">Study</a>')
    n = f'<span class="n">{e(r["n"])}</span>' if r["n"] else ""
    name, more = _date_more(r)
    return (f'<div class="du-r{" done" if r["done"] else ""}">{box}<span class="t">{name}'
            f'<small>{meta}</small>{what}{subs}</span><span class="end">{n}{go}</span>{bar}</div>{more}')


def _wbar2(through, later, total):
    """3.9.3: a Today row's bar, in two tones: solid, the cards through for
    today (answered, next due tomorrow or later); light, answered and back
    later today; the well, still to do. The row's whole width, under its words."""
    total = int(total)
    a = 0 if not total else max(0, min(100, round(100 * int(through) / total)))
    b = 0 if not total else max(0, min(100 - a, round(100 * (int(through) + int(later)) / total) - a))
    return (f'<span class="wbar two" title="{int(through):,} through for today, {int(later):,} back later today, '
            f'of {total:,}"><i style="width:{a}%"></i><i class="lt" style="width:{b}%"></i></span>')


def _due_count(r, noun):
    """What a bar's row says at its end: "140 due" (or "40 new") before
    anything's answered, then "84 / 140", then "all done"."""
    if r["done"]:
        return "all done"
    if not r["through"] and not r["later"]:
        return f'{int(r["whole"]):,} {noun}'
    return f'{int(r["through"]):,} / {int(r["whole"]):,}'


def _due_reviews(r):
    """3.9.3: Reviews with its bar, and a line once I've started: the ones
    back later today (at the first one's time) and the ones due now."""
    e = _html.escape
    if not r["whole"]:
        return ""
    said = []
    if r["back"] and not r["done"]:
        said.append(f'{int(r["back"]):,} back{" at " + e(r["at"]) if r.get("at") else " later"}')
    if r["left"] and (r["through"] or r["later"]) and not r["done"]:
        said.append(f'{int(r["left"]):,} still due')
    small = f'<small>{" &middot; ".join(said)}</small>' if said else ""
    box = _due_box("on" if r["done"] else "part" if r["through"] or r["later"] else "")
    bar = "" if r["done"] else _wbar2(r["through"], r["later"], r["whole"])
    return (f'<div class="du-r{" done" if r["done"] else ""}">{box}<span class="t"><b>Reviews</b>{small}</span>'
            f'<span class="end"><span class="n">{_due_count(r, "due")}</span></span>{bar}</div>')


def _due_misses(m):
    """3.9.5: under a done Reviews row, today's misses, and where they were
    (each part opens Browse). A line, not a deck (Sam's FSRS rule). m:
    due_flow._misses, or None."""
    said = _D.misses_text(m)
    if not said:
        return ""
    e = _html.escape
    head, _sep, rest = said.partition(", ")
    text = f'{e(head)}, <b>{e(rest)}</b>' if rest else e(said)
    if m.get("topics"):
        parts = [f'<a class="tp" href="#" title="Browse them" onclick="{_pycmd(f"duego:miss{i}")}">'
                 f'{e(str(name))} {len(cids):,}</a>' for i, (name, cids) in enumerate(m["topics"])]
        if int(m.get("elsewhere") or 0):
            parts.append(f'{int(m["elsewhere"]):,} elsewhere')
        text += ": " + " &middot; ".join(parts)
    return f'<div class="du-rc"><span></span><span>{text}</span><span class="end"></span></div>'


def _due_new(r):
    """3.9.3: New cards (what Anki gives today: the ones I've started and what
    its limits still give, a line a deck when there's more than one), or Other
    new cards on a plan's day (the ones I started that none of its dates holds)."""
    e = _html.escape
    decks = r.get("decks") or []
    name = "Other new cards" if r.get("other") else "New cards"
    subs = small = ""
    if len(decks) > 5:  # a line a deck up to five; past that, how many
        small = f"{len(decks):,} decks"
    elif len(decks) > 1:
        subs = "".join(f'<span class="du-sub"><span class="du-bx auto{" on" if th >= tot else ""}"></span>'
                       f'<span><b>{e(d)}</b></span><span class="n">{th:,} / {tot:,}</span></span>'
                       for d, th, tot, _lt in decks)
    elif decks:
        small = e(decks[0][0])
    if r.get("other"):
        small = (small + " &middot; " if small else "") + "not on a plan"
    small = f"<small>{small}</small>" if small else ""
    box = _due_box("on" if r["done"] else "part" if r["part"] else "", auto=True)
    bar = "" if r["done"] else _wbar2(r["through"], r["later"], r["whole"])
    return (f'<div class="du-r{" done" if r["done"] else ""}">{box}<span class="t"><b>{name}</b>{small}{subs}</span>'
            f'<span class="end"><span class="n">{_due_count(r, "new")}</span></span>{bar}</div>')


def _due_short(r):
    e = _html.escape
    if r["kind"] == "mine":
        return _due_mine(r, short=True)
    if r["kind"] == "every":
        return _due_every(r, short=True)
    box = _due_box("on" if r["done"] else "part" if r["part"] else "", auto=True)
    name, more = _date_more(r, topics=True)  # round five: a click opens its details
    return (f'<div class="du-ln{" done" if r["done"] else ""}">{box}<span>{name}'
            f' <span class="du-m">&middot; {e(r["plan"])}</span></span><span class="n">{e(r["n"])}</span></div>{more}')


def _due_behind(v):
    e = _html.escape
    if not v["behind_n"]:
        return ""
    out = '<div class="du-bh"><div class="du-sec warn">Behind</div>'
    for p in v["behind_plans"]:
        left = int(p["left"])
        what = f'{int(p["dates"])} set{"s" if p["dates"] != 1 else ""}' + (
            f' &middot; <a class="tp" href="#" title="Browse them" onclick="{_pycmd("planleft:" + p["pid"])}">{left:,} cards to see</a>'
            if left else "")
        out += (f'<div class="du-r">{_due_box("", auto=True)}<span class="t"><b>{e(p["plan"])}</b><small>{what}</small></span>'
                f'<span class="end"><a href="#" class="du-go" onclick="{_pycmd("plancatch:" + p["pid"])}">Catch up&hellip;</a></span></div>')
    out += "".join(_due_mine(r) for r in v["behind_mine"])
    if v["behind_more"]:
        out += f'<div class="du-q">and {int(v["behind_more"])} more</div>'
    return out + "</div>"


def _due_add(v, default):
    """The add line: a day button beside it, a day said at the end shown before Enter."""
    today = v["today"]
    t = _dt.date.fromisoformat(today)
    opts = [("today", "Today"), ((t + _dt.timedelta(days=1)).isoformat(), "Tomorrow")]
    opts += [((t + _dt.timedelta(days=i)).isoformat(), f"{t + _dt.timedelta(days=i):%a}") for i in range(2, 7)]
    opts += [("later", "Later"), ("pick", "Pick a day…")]
    sel = "".join(f'<option value="{k}"{" selected" if k == default else ""}>{lb}</option>' for k, lb in opts)
    maxd = (t + _dt.timedelta(days=730)).isoformat()
    full = ' disabled placeholder="60 open: tick or delete some first"' if v.get("full") else ' placeholder="Add a to-do…"'
    return (f'<div class="du-add"><input type="text" id="du-in" maxlength="140" aria-label="Add a to-do"{full} '
            f'onkeydown="dcDue.key(event)" oninput="dcDue.preview()">'
            f'<span class="du-said" id="du-said"></span>'
            f'<select id="du-when" aria-label="Its day" onchange="dcDue.pick()">{sel}</select>'
            f'<input type="date" id="du-date" min="{today}" max="{maxd}" style="display:none" aria-label="Pick a day">'
            f'<a href="#" class="du-go" onclick="dcDue.send();return false;">Add</a></div>')


# 3.8.0: the two keys as this computer writes them (a Mac: Command for Study, Control for Ask, __init__.py)
STUDY_KBD, ASK_KBD = ("⌘⇧S", "⌃⇧Q") if _sys.platform == "darwin" else ("Ctrl+Shift+S", "Ctrl+Shift+Q")
MAGIC_KBD = "⌘⇧F" if _sys.platform == "darwin" else "Ctrl+Shift+F"  # 3.9.7: Magic search, from any screen
MAGIC_FIELD_ID = "dc-mgf"
MAGIC_EXAMPLES = ("cardio pharm due this week", "leeches in renal", "40 new from chapter 3", "paste question IDs",
                  "quiz Friday: spread it out")
_MAGIC_FIELD_ICON = ('<svg class="mag" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" '
                     'stroke-linecap="round" aria-hidden="true"><circle cx="10" cy="11" r="6.2"/><path d="M19.4 20.4l-4.7-4.7"/>'
                     '<path class="st" d="M19 1.6l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9z" stroke="none"/></svg>')
# the field's own sheet: it sits in Anki's part of the Decks page (under the deck list, over "Studied…"),
# outside #due-crew, so it carries the board's tokens itself
_MAGIC_FIELD_CSS = """
#dc-mgf { box-sizing: border-box; position: relative; display: flex; align-items: center; gap: 7px; width: 440px; max-width: 92%;
  height: 34px; margin: 14px auto 2px; padding: 0 9px 0 10px; border-radius: 10px; border: 1px solid transparent; text-align: left;
  font: 12.5px/1.2 Inter, -apple-system, "Segoe UI", sans-serif; color: var(--dc-ink);
  background: linear-gradient(var(--dc-bg), var(--dc-bg)) padding-box,
    conic-gradient(from var(--dc-ga), var(--dc-line) 0 62%, var(--dc-accent) 74%, var(--dc-hours) 82%, var(--dc-line) 92%) border-box; }
@property --dc-ga { syntax: "<angle>"; inherits: false; initial-value: 0deg; }
#dc-mgf.live, #dc-mgf:hover, #dc-mgf:focus-within { animation: dc-mgf-glint 4.5s linear infinite; }
#dc-mgf:focus-within { box-shadow: 0 0 0 2px var(--dc-you-bg); }
@keyframes dc-mgf-glint { to { --dc-ga: 360deg; } }
#dc-mgf button.go { appearance: none; -webkit-appearance: none; all: unset; display: inline-flex; flex: none; cursor: pointer; color: var(--dc-accent);
  margin: 0; padding: 2px; min-width: 0; box-shadow: none; border-radius: 6px; }
#dc-mgf button.go:focus-visible { outline: 2px solid var(--dc-accent) !important; outline-offset: 1px; }
#dc-mgf .mag { overflow: visible; display: block; }
#dc-mgf .mag .st { fill: var(--dc-hours); transform-box: fill-box; transform-origin: center; }
#dc-mgf.twk .mag .st { animation: dc-mgf-twk .6s ease-out; }
@keyframes dc-mgf-twk { 40% { transform: scale(1.7) rotate(45deg); } 100% { transform: none; } }
#dc-mgf input { appearance: none; -webkit-appearance: none; flex: 1; min-width: 0; height: 100%; margin: 0; padding: 0; border: 0; outline: none !important;
  background: transparent; box-shadow: none; font: inherit; color: var(--dc-ink); }
#dc-mgf input::placeholder { color: var(--dc-muted); opacity: 1; }
#dc-mgf kbd { flex: none; font: 10px Menlo, Consolas, monospace; color: var(--dc-muted); border: 1px solid var(--dc-line); border-radius: 4px;
  padding: 0 4px; background: var(--dc-well); }
#dc-mgf .s { position: absolute; left: 24px; top: 6px; width: 5px; height: 5px; background: var(--dc-hours); opacity: 0; pointer-events: none;
  clip-path: polygon(50% 0, 62% 38%, 100% 50%, 62% 62%, 50% 100%, 38% 62%, 0 50%, 38% 38%); }
#dc-mgf:hover .s, #dc-mgf.twk .s { animation: dc-mgf-spk .9s ease-out; }
#dc-mgf .s1 { --dx: -8px; } #dc-mgf .s2 { --dx: 9px; animation-delay: .12s !important; background: var(--dc-accent); }
#dc-mgf .s3 { --dx: 20px; animation-delay: .22s !important; }
@keyframes dc-mgf-spk { 0% { transform: translate(0, 0) scale(.2); opacity: 0; } 20% { opacity: 1; }
  100% { transform: translate(var(--dx, 10px), -22px) scale(1.2) rotate(90deg); opacity: 0; } }
@media (max-width: 460px) { #dc-mgf kbd { display: none; } }
@media (prefers-reduced-motion: reduce) { #dc-mgf, #dc-mgf * { animation: none !important; } }
"""
# its placeholder writes itself through a few examples, the star twinkling as each lands; then it rests (three
# examples, about twelve seconds, as the edge's glint does) till it's pointed at. Focused, it says what to type.
# Enter (or the magnifier) opens Magic search on what's typed. Nothing with Reduce motion.
_MAGIC_FIELD_JS = r"""
(function () {
    var f = document.getElementById('dc-mgf');
    if (!f || f.dcOn) { return; }
    f.dcOn = 1;
    var q = f.querySelector('input'), EX = __EX__, HINT = 'A topic, a filter, pasted question IDs…';
    var i = 0, n = 0, rounds = 0, timer = 0, typing = false;
    var still = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    function go() { f.querySelector('button.go').click(); }  // (the magnifier's own onclick sends: one place says the command)
    q.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') { e.preventDefault(); go(); }
        else if (e.key === 'Escape') { q.value = ''; q.blur(); }
    });
    function stop() { clearTimeout(timer); typing = false; }
    function type() {
        typing = true;
        q.placeholder = EX[i].slice(0, ++n);
        if (n < EX[i].length) { timer = setTimeout(type, 55 + Math.random() * 45); return; }
        typing = false;
        f.classList.remove('twk'); void f.offsetWidth; f.classList.add('twk');
        rounds++;
        if (rounds >= 3) { return; }
        timer = setTimeout(next, 2600);
    }
    function next() { n = 0; i = (i + 1) % EX.length; type(); }
    q.addEventListener('focus', function () { stop(); q.placeholder = HINT; });
    q.addEventListener('blur', function () { if (!q.value) { q.placeholder = EX[i]; } });
    if (still) { q.placeholder = EX[0]; return; }
    f.addEventListener('mouseenter', function () {
        if (!typing && rounds >= 3 && document.activeElement !== q) { rounds = 2; next(); }
    });
    f.classList.add('live');
    setTimeout(function () { f.classList.remove('live'); }, 12000);
    timer = setTimeout(type, 600);
})();
"""


def magic_field(cfg):
    """3.9.9 (Sam's pick G2, from eight places mocked and three styles):
    Magic search as a field under Anki's deck list, over its "Studied…"
    line, in the link's place in the You box's head. The board's input with
    the window's magnifier and star; a glint goes round its edge in the
    accent and the amber and its placeholder writes itself through a few
    examples, about twelve seconds, then both rest till it's pointed at.
    Type and Enter: the window opens on it. It's drawn with the Decks page
    (never by a swap), so it carries its own sheet, tokens and script."""
    from .base import BOARD_KEY, DEFAULT_ACCENT, _by_theme, _token_block, palette
    import json as _json
    accent = (cfg or {}).get("accent", DEFAULT_ACCENT)
    tokens = _by_theme(cfg or {}, "#" + MAGIC_FIELD_ID, _token_block(palette("light", accent)), _token_block(palette("dark", accent)))
    js = _MAGIC_FIELD_JS.replace("__EX__", _json.dumps(list(MAGIC_EXAMPLES)))
    return (f'<style>{tokens}{_MAGIC_FIELD_CSS}</style>'
            f'<div id="{MAGIC_FIELD_ID}" role="search">'
            f'<i class="s s1"></i><i class="s s2"></i><i class="s s3"></i>'
            # the board's command as the board sends it, with what's typed when there is any (a colon after its name)
            f'<button type="button" class="go" title="Magic search ({MAGIC_KBD})" aria-label="Open Magic search" '
            f'onclick="var q=this.parentNode.querySelector(\'input\').value.slice(0,400);'
            f'pycmd(\'duecrew:magic\'+(q?\':\'+encodeURIComponent(q):\'\')+\'|{BOARD_KEY}\');return false;">{_MAGIC_FIELD_ICON}</button>'
            f'<input type="text" aria-label="Magic search: a topic, a filter, pasted question IDs" placeholder="{_html.escape(MAGIC_EXAMPLES[0])}" '
            f'maxlength="400" autocomplete="off" autocapitalize="off" spellcheck="false">'
            f'<kbd>{MAGIC_KBD}</kbd></div><script>{js}</script>')


def _due_html(v, more=(), more_tab=None, more_body="", folded=None, magic=False):
    """The You bubble (3.8.0; Due above the board until then): Due's lists,
    Today, Upcoming and Later, when Due is on (v: due.view, from
    due_flow.view), then `more`, [(key, label)] (Plans, Insights), with
    `more_tab` picked and `more_body` drawn. Every string in v is escaped
    here; `more_body` comes drawn. folded: when there are no lists to say
    it (Due off)."""
    if not v and not more:
        return ""
    e = _html.escape
    mg = ""  # 3.9.9: Magic search is the field under the deck list now (magic_field); `magic` says only that it's on
    if not v:
        # Due's lists off: Plans and Insights only, folded or not; Magic search in its head too (3.9.5 to 3.9.6:
        # QBank QIDs, Magic search's since 3.9.7)
        ql = mg
        if folded:
            names = " &middot; ".join(lb for _k, lb in more)
            return (f'<div class="du du-one"><a href="#" onclick="{_pycmd("duefold")}" title="Show"><b>{names}</b></a>'
                    f'<span class="sp"></span>{ql}<a href="#" class="du-fold" title="Show" '
                    f'onclick="{_pycmd("duefold")}">Show &#9662;</a></div>')
        tab = more_tab if more_tab in dict(more) else more[0][0]
        tabs = "".join(f'<a href="#" role="tab" aria-selected="{"true" if k == tab else "false"}" class="{"on" if k == tab else ""}" onclick="{_pycmd("duetab:" + k)}">{_tab_word(k, lb)}</a>'
                       for k, lb in more)
        return (f'<div class="du"><div class="du-h"><span class="du-tabs" role="tablist" aria-label="You">{tabs}</span>'
                f'<span class="sp"></span>{ql}<a href="#" class="du-fold" title="Fold to one line" '
                f'onclick="{_pycmd("duefold")}">Hide &#9652;</a></div>{more_body}</div>')
    today = e(v["today"])
    # 3.9.3 (Sam's pick 1, in Study today's place): in the head on every tab and on the folded line ("missing
    # the QID chip on the top right"); QBank QIDs then, Magic search since 3.9.7 (its paste is QIDs' way)
    qids = mg
    done_n, total_n = int(v["done_n"]), int(v["total_n"])
    count = f"{done_n} of {total_n} done" if total_n else ""
    if v["folded"]:
        bar = _wbar(done_n, total_n) if total_n else ""
        go = ""  # 3.9.3: no Study today (Sam); Ctrl+Shift+S still walks the day
        behind = f'<span class="du-n" style="color:#c77700">{int(v["behind_n"])} behind</span>' if v["behind_n"] else ""
        if v.get("done"):
            # the day's done: what's next, in place of the bar
            nxt = v["tomorrow"][:2] or (v["next"]["names"][:2] if v.get("next") else [])
            count, bar, go = "&#10003; Done for today", "", (
                f'<span class="du-n du-tm" title="{", ".join(e(x) for x in nxt)}">'
                f'{"Tomorrow" if v["tomorrow"] else e(v["next"]["day"])}: '
                f'{", ".join(e(x) for x in nxt)}</span>' if nxt else "")
        return (f'<div class="du du-one" data-today="{today}"><a href="#" onclick="{_pycmd("duefold")}" title="Show">'
                f'<b>{e(v["name"])}</b></a><span class="du-n">{count or "nothing today"}</span>{bar}{behind}'
                f'<span class="sp"></span>{go}{qids}<a href="#" class="du-fold" title="Show the whole list" '
                f'onclick="{_pycmd("duefold")}">Show &#9662;</a></div>')
    tab = more_tab if more_tab in dict(more) else v["tab"]
    # 3.8.0: Later shows only when it holds something; adding one shows it
    lists = (("today", "Today"), ("upcoming", "Upcoming")) + (
        (("later", f'Later{" " + str(v["later_n"]) if v["later_n"] else ""}'),) if v["later"] else ())
    if tab not in dict(lists) and tab not in dict(more):
        tab = "today"
    tabs = "".join(
        f'<a href="#" role="tab" aria-selected="{"true" if k == tab else "false"}" class="{"on" if k == tab else ""}" onclick="{_pycmd("duetab:" + k)}">{lb}</a>'
        for k, lb in lists)
    if more:
        # 3.8.0: Plans and Insights, after a gap: what's mine beyond the day
        tabs += '</span><span class="du-tabs du-more" role="tablist" aria-label="Plans and Insights">' + "".join(
            f'<a href="#" role="tab" aria-selected="{"true" if k == tab else "false"}" class="{"on" if k == tab else ""}" onclick="{_pycmd("duetab:" + k)}">{_tab_word(k, lb)}</a>' for k, lb in more)
    if v.get("done") and tab == "today":
        count = "&#10003; Done for today"  # 3.8.0: as the folded line says it (and motion.js lights the box once)
    head = (f'<div class="du-h"><span class="du-tabs" role="tablist" aria-label="{e(v["name"])}">{tabs}</span>'
            f'<span class="sp"></span><span class="du-n">{count if tab in ("today", "upcoming") else ""}</span>{qids}'
            f'<a href="#" class="du-fold" title="Fold to one line" onclick="{_pycmd("duefold")}">Hide &#9652;</a></div>')
    if tab in dict(more):
        return f'<div class="du" data-today="{today}">{head}{more_body}</div>'

    toast = ""
    if v.get("toast"):
        toast = (f'<div class="du-line"><span>{e(v["toast"]["text"])}</span>'
                 f'<a href="#" onclick="{_pycmd("dueshow:" + v["toast"]["tab"])}">Show</a></div>')
    body = ""
    if tab == "today":
        if v.get("nudge"):
            # 3.8.1: once a day, past my usual start, nothing studied yet: Fifteen?
            peek = f'<span class="nz">{v["nudge_sev"]}</span>' if v.get("nudge_sev") else "<span>&#9654;</span>"
            body += (f'<div class="du-nudge">{peek}<span><b>Not started yet today.</b> Fifteen?</span>'
                     f'<span><a href="#" class="du-go" title="Fifteen minutes, then one question" onclick="{_pycmd("room15")}">Start</a>'
                     f'<a href="#" class="x" title="Not today" onclick="{_pycmd("duex:fifteen")}">&times;</a></span></div>')
        body += _due_behind(v)
        for r in v["rows"]:
            if r["kind"] == "reviews":
                if r.get("whole") is not None:
                    body += _due_reviews(r) + _due_misses(v.get("misses") if r.get("done") else None)
                    continue
                back = int(r.get("back") or 0)
                if not r["due"] and not r["done"] and not back:
                    continue
                n = ("all done" if r["done"] else f'{int(r["due"]):,} due' if r["due"]
                     else f'{back:,} back{" at " + e(r["at"]) if r.get("at") else " later"}')
                body += (f'<div class="du-r{" done" if r["done"] else ""}">{_due_box("on" if r["done"] else "")}'
                         f'<span class="t"><b>Reviews</b></span><span class="end"><span class="n">{n}</span></span></div>')
            elif r["kind"] == "new":
                body += _due_new(r)
            elif r["kind"] == "plan":
                body += _due_plan(r)
            elif r["kind"] == "every":
                body += _due_every(r)
            else:
                body += _due_mine(r)
        body += _opened_line(v.get("opened"))
        for sg in v["suggestions"] + v["notes"]:
            body += (f'<div class="du-sg"><span>&#10022;</span><span>{e(sg["text"])}</span><span>'
                     f'<a href="#" onclick="{_pycmd("duego:" + sg["key"])}">{e(sg["go"])}</a>'
                     f'<a href="#" class="x" title="Not today" onclick="{_pycmd("duex:" + sg["key"])}">&times;</a></span></div>')
        if not v["rows"] and not v["suggestions"] and not v["notes"]:
            body += '<div class="du-empty">Nothing due today.</div>'
        body += _due_add(v, "today")
    elif tab == "upcoming":
        for dd in v["days"]:  # 3.8.0: Behind is Today's alone
            if dd.get("quiet"):
                body += f'<div class="du-q">{e(dd["label"])} &middot; nothing due</div>'
                continue
            what = "review day" if dd["review"] and not dd["n"] else ""  # 3.8.0: its rows are the count
            plus = (f'<a href="#" class="plus" title="Add a to-do for this day" '
                    f'onclick="dcDue.plus(\'{e(dd["day"])}\');return false;">+</a>')
            body += (f'<div class="du-dh{" today" if dd["today"] else ""}"><span>{e(dd["head"])}</span>'
                     f'<small>{what}{plus}</small></div>')
            body += "".join(_due_short(r) for r in dd["rows"])
            body += "".join(f'<div class="du-evl">&#9733; {e(n)}</div>' for n in dd["events"])
        body += _due_add(v, "today")
    else:
        if v["later"]:
            body += "".join(_due_mine(r) for r in v["later"])
        else:
            body += '<div class="du-empty">Nothing here.</div>'
        body += _due_add(v, "later")
    return f'<div class="du" data-today="{today}">{head}{toast}{body}</div>'
