"""Settings, in the board: its tabs, rows and Find a setting.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
import json as _json
import re as _re

from .. import words as _words
from ..words import later as _later, t as _t
from ..errs import wanted as _sends_errs
from ..logo import board_mark
from .. import sev as _sev

from .base import ACCENTS, DEFAULT_ACCENT, HIDEABLE_TABS, KEEP_LINE, _by_theme, _pycmd, accent_pair, hidden_tabs, button_reset
from .style import _css
from .pip import SETTINGS_PIP, my_look
from .due import ASK_KBD, MAGIC_KBD, STUDY_KBD


# ---- 3.5.0: Settings, in the board ----

SETTINGS_CSS = """
    #due-crew.dc-set, #due-crew.dc-set .st-row, #due-crew.dc-set .st-l { text-align: left; }
    /* Anki styles every button on the Decks screen (a margin, a shadow,
       rounded corners); the panel's own controls start from nothing */
    __BUTTONS__
    #due-crew .st-radio { box-sizing: border-box; border-radius: 0; }
    #due-crew .st-box { overflow: hidden; }
    #due-crew .st-bar { display: flex; align-items: baseline; gap: 10px; margin: 2px 0 10px; }
    #due-crew .st-bar b { font-size: 15px; }
    #due-crew .st-back { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .st-h { font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-muted); margin: 12px 0 5px; }
    #due-crew .st-box { border: 1px solid var(--dc-line); border-radius: 9px; }
    #due-crew .st-row { display: flex; align-items: center; justify-content: space-between; gap: 6px 12px;
      padding: 7px 11px; flex-wrap: wrap; }
    #due-crew .st-row + .st-row { border-top: 1px solid var(--dc-line); }
    #due-crew .st-l { display: grid; gap: 1px; min-width: 0; }
    #due-crew .st-l small, #due-crew .st-note { color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .st-note { margin-top: 8px; }
    #due-crew .st-r { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    #due-crew .st-tg { width: 30px; height: 17px; border-radius: 99px; border: 0; padding: 0; cursor: pointer;
      background: var(--dc-line); position: relative; flex: none; }
    #due-crew .st-tg::after { content: ""; position: absolute; top: 2px; left: 2px; width: 13px; height: 13px;
      border-radius: 50%; background: var(--dc-bg); }
    #due-crew .st-tg.on { background: var(--dc-accent); }
    #due-crew .st-tg.on::after { left: 15px; }
    #due-crew .st-seg { display: inline-flex; }
    #due-crew .st-two { display: inline-flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px 14px; }
    #due-crew .st-two label { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--dc-muted); }
    #due-crew .st-seg button, #due-crew .st-pill { font: inherit; font-size: 11.5px; font-weight: 700; cursor: pointer;
      border: 1px solid var(--dc-line); background: transparent; color: var(--dc-muted); padding: 2px 10px; }
    #due-crew .st-seg button { border-radius: 0; }
    #due-crew .st-seg button:first-child { border-radius: 99px 0 0 99px; }
    #due-crew .st-seg button:last-child { border-radius: 0 99px 99px 0; }
    #due-crew .st-seg button + button { border-left: none; }
    #due-crew .st-seg button.on { background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }
    #due-crew .st-pills { display: flex; gap: 5px; flex-wrap: wrap; }
    #due-crew .st-pill { border-radius: 99px; }
    #due-crew .st-pill.on { border-color: var(--dc-accent); background: var(--dc-you-bg); color: var(--dc-ink); }
    #due-crew .st-pill.on::before { content: "\\2713  "; color: var(--dc-accent); }
    #due-crew .st-pill[disabled] { cursor: default; opacity: .6; }
    #due-crew .st-sw { display: flex; gap: 7px; }
    #due-crew .st-sw button { width: 18px; height: 18px; border-radius: 50%; border: 0; padding: 0; cursor: pointer;
      box-shadow: 0 0 0 2px var(--dc-bg); }
    #due-crew .st-sw button.on { box-shadow: 0 0 0 2px var(--dc-bg), 0 0 0 4px var(--dc-ink); }
    #due-crew .st-kbd { font: 11px Menlo, Consolas, monospace; border: 1px solid var(--dc-line); border-radius: 5px;
      padding: 1px 6px; color: var(--dc-ink); white-space: nowrap; }
    #due-crew .st-in { font: inherit; font-size: 12.5px; border: 1px solid var(--dc-line); border-radius: 6px;
      padding: 2px 7px; background: var(--dc-bg); color: var(--dc-ink); color-scheme: light dark; }
    #due-crew .st-in:disabled { color: var(--dc-faded); }
    #due-crew .st-lk { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .st-danger { color: #d64035; }
    #due-crew .st-who { display: flex; gap: 10px; align-items: center; }
    #due-crew .st-who .em { font-size: 26px; line-height: 1; }
    #due-crew .st-who b { font-size: 15px; }
    #due-crew .st-acts { display: flex; gap: 14px; flex-wrap: wrap; margin: 8px 0; }
    #due-crew .st-radio { display: grid; grid-template-columns: 16px 1fr; gap: 8px; padding: 8px 11px; cursor: pointer;
      width: 100%; text-align: left; font: inherit; color: inherit; background: transparent; border: 0; }
    #due-crew .st-radio + .st-radio, #due-crew .st-sub + .st-radio { border-top: 1px solid var(--dc-line); }
    #due-crew .st-radio i { box-sizing: border-box; width: 14px; height: 14px; border-radius: 50%;
      border: 1.5px solid var(--dc-faded); margin-top: 2px; }
    #due-crew .st-radio.on { background: var(--dc-you-bg); }
    #due-crew .st-radio.on i { border: 4px solid var(--dc-accent); }
    #due-crew .st-radio span { display: grid; gap: 2px; }
    #due-crew .st-radio small { color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .st-sub { padding: 0 11px 9px 35px; margin-top: -2px; background: var(--dc-you-bg); }
    #due-crew .st-foot { display: flex; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap;
      margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--dc-line); color: var(--dc-muted); font-size: 11.5px; }
    #due-crew button:focus-visible, #due-crew a:focus-visible, #due-crew input:focus-visible {
      outline: 2px solid var(--dc-accent); outline-offset: 2px; }
    /* 3.8.0, pick 28: Find a setting */
    #due-crew .st-find { margin-left: auto; position: relative; text-align: left; }
    #due-crew .st-find input { width: 150px; max-width: 42vw; }
    #due-crew .st-hits { position: absolute; right: 0; top: calc(100% + 4px); z-index: 20; min-width: 240px; max-width: 80vw;
      display: grid; background: var(--dc-bg); border: 1px solid var(--dc-line); border-radius: 10px; padding: 4px;
      box-shadow: 0 6px 22px rgba(0,0,0,.14); }
    #due-crew .st-hits[hidden] { display: none; }
    #due-crew .st-hits button { all: unset; display: grid; gap: 1px; padding: 6px 9px; border-radius: 7px; cursor: pointer; text-align: left; }
    #due-crew .st-hits button:hover, #due-crew .st-hits button.on { background: var(--dc-you-bg); }
    #due-crew .st-hits b { font-size: 12.5px; color: var(--dc-ink); }
    #due-crew .st-hits small { font-size: 11px; color: var(--dc-muted); }
    #due-crew .st-hits .st-none { padding: 6px 9px; font-size: 12px; color: var(--dc-muted); }
    @keyframes sthit { from { background-color: color-mix(in srgb, var(--dc-accent) 26%, transparent); } }  /* to its own ground, whatever that is */
    @media (prefers-reduced-motion: no-preference) { #due-crew .st-hit { animation: sthit 1.8s ease-out; } }
    @media (prefers-reduced-motion: reduce) { #due-crew .st-hit { outline: 2px solid var(--dc-accent); outline-offset: 1px; } }
""".replace("__BUTTONS__", button_reset("#due-crew.dc-set button", "vertical-align: middle;"))
# 3.9.9 (Sam: "reorganize settings to be intuitive and sensible"): four tabs by what a setting is about.
# You: who I am, my dates, my people. Board: what's on the Decks screen and how it looks. Study: what
# works while I study (Today, Magic search, reviewing, the Fifteen, keys). Privacy: what leaves this computer.
SETTINGS_TABS = (("you", _later("You")), ("board", _later("Board")), ("study", _later("Study")), ("privacy", _later("Privacy")))
RESET_WORDS = _later("Reset Board and Study")
# an accent's name, as its swatch says it (base.ACCENTS' keys; one without a name here says its key)
ACCENT_NAMES = {"green": _later("Green"), "blue": _later("Blue"), "purple": _later("Purple"), "teal": _later("Teal"),
                "amber": _later("Amber"), "rose": _later("Rose")}


def _st_row(label, control, sub=""):
    sub = f"<small>{sub}</small>" if sub else ""
    return f'<div class="st-row"><span class="st-l"><span>{label}</span>{sub}</span><span class="st-r">{control}</span></div>'


def _st_click(cmd):
    """onclick for a settings command; data-f names it, so focus comes back
    to it after the panel redraws."""
    return f'data-f="{_html.escape(_re.sub(r"[^A-Za-z0-9:_-]", "", cmd))}" onclick="{_pycmd(cmd)}"'


def _st_switch(key, on, label):
    return (f'<button class="st-tg{" on" if on else ""}" role="switch" aria-checked="{"true" if on else "false"}" '
            f'aria-label="{_html.escape(label)}" {_st_click(f"set:{key}:{0 if on else 1}")}></button>')


def _st_seg(key, options, current, label):
    btns = "".join(f'<button class="{"on" if v == current else ""}" aria-pressed="{"true" if v == current else "false"}" '
                   f'{_st_click(f"set:{key}:{v}")}>{t}</button>' for v, t in options)
    return f'<span class="st-seg" role="group" aria-label="{label}">{btns}</span>'


def _settings_you(view, cfg=None):
    """cfg (3.8.22): with Pip on, my Pip where my emoji was, opening the
    closet (Emoji… stays: it shows with Pip off and in text shares)."""
    e = _html.escape
    if not view.get("signed_in"):
        return (f'<p>{_t("Not signed in.")}</p><div class="st-acts">'
                f'<a class="st-lk" href="#" {_st_click("setsignin")}>{_t("Start with your email")}</a></div>')
    emoji = e(str(view.get("emoji") or ""))
    status = str(view.get("status") or "")
    fig = (f'<a class="st-pip" href="#" title="{_t("Pip&rsquo;s closet")}" onclick="{_pycmd("closet")}">'
           f'{_sev.slot(_sev.svg("idle", rest=True, look=my_look(cfg), label=_t("Your Pip")), SETTINGS_PIP)}</a>'
           if cfg is not None and cfg.get("sev", True) else f"<span class=em>{emoji}</span>" if emoji else "")
    out = (f'<div class="st-who">{fig}'
           f'<span style="display:grid"><b>{e(str(view.get("name") or "?"))}</b>'
           f'<span style="color:var(--dc-muted)">{"&ldquo;" + e(status) + "&rdquo;" if status else _t("No status")}</span></span></div>'
           f'<div class="st-acts"><a class="st-lk" href="#" {_st_click("setname")}>{_t("Name&hellip;")}</a>'
           f'<a class="st-lk" href="#" {_st_click("setemoji")}>{_t("Emoji&hellip;")}</a>'
           f'<a class="st-lk" href="#" {_st_click("setstatus")}>{_t("Status&hellip;")}</a></div>'
           f'<div class="st-note" style="margin:0 0 10px">{e(str(view.get("sync") or ""))}</div>')
    crew = int(view.get("crew") or 0)
    squads = [str(x) for x in view.get("squads") or []]
    decks = [str(x) for x in view.get("decks") or []]

    def names(xs, none):
        if not xs:
            return none
        shown = ", ".join(e(x) for x in xs[:2])
        return _t("{names} and {n} more", names=shown, n=len(xs) - 2) if len(xs) > 2 else shown
    if cfg is not None:  # 3.9.9: my dates are about me (they were under Privacy)
        out += f'<div class="st-h">{_t("Your dates")}</div><div class="st-box">' + _date_rows(cfg) + '</div>'
    out += (f'<div class="st-h">{_t("Your people")}</div><div class="st-box">'
            + _st_row(_t("Friends"), f'<a class="st-lk" href="#" {_st_click("friends")}>{_t("Open")}</a>',
                      _t("{n} in your crew", n=crew) if crew else _t("Your code, and who's in your crew"))
            + _st_row(_t("Squads"), f'<a class="st-lk" href="#" {_st_click("setsquads")}>{_t("Open")}</a>', names(squads, _t("None yet")))
            + _st_row(_t("Shared decks"), f'<a class="st-lk" href="#" {_st_click("decks")}>{_t("Open")}</a>', names(decks, _t("None yet")))
            + '</div>')
    # 3.6.5, P6: feedback, here as well as in Tools › Due Crew
    out += ('<div class="st-h">Due Crew</div><div class="st-box">'
            + _st_row(_t("Feedback"), f'<a class="st-lk" href="#" {_st_click("setfeedback")}>{_t("Send&hellip;")}</a>')
            + '</div>')
    out += (f'<div class="st-foot"><a class="st-lk" href="#" {_st_click("setsignout")}>{_t("Sign out")}</a>'
            f'<a class="st-lk st-danger" href="#" {_st_click("setdelete")}>{_t("Delete account&hellip;")}</a></div>'
            f'<div class="st-foot"><span>{_t(KEEP_LINE)}</span></div>')
    return out


def _accent_swatches(cfg):
    """The accent's swatches (Settings › Board and, 3.9.0, the closet):
    Pip's colour and the board's, the one your crew sees Pip in."""
    accent = cfg.get("accent", DEFAULT_ACCENT)
    return "".join(
        f'<button class="{"on" if k == accent else ""}" style="background:{v["light"][0]}" title="{_t(ACCENT_NAMES.get(k, k.title()))}" '
        f'aria-label="{_t(ACCENT_NAMES.get(k, k.title()))}" aria-pressed="{"true" if k == accent else "false"}" {_st_click(f"set:accent:{k}")}></button>'
        for k, v in ACCENTS.items())


def _settings_board(cfg):
    """What's on the Decks screen and how it looks (3.9.9: Today, Magic search, reviewing,
    the Fifteen and the keys went to Study)."""
    hidden = hidden_tabs(cfg)
    pills = f'<button class="st-pill on" disabled aria-pressed="true">{_t("Crew")}</button>' + "".join(
        f'<button class="st-pill{"" if k in hidden else " on"}" aria-pressed="{"false" if k in hidden else "true"}" '
        f'{_st_click(f"settabs:{k}:{1 if k in hidden else 0}")}>{_t(t)}</button>' for k, t in HIDEABLE_TABS)
    swatches = _accent_swatches(cfg)
    g = lambda k, d: bool(cfg.get(k, d))  # noqa: E731
    return (f'<div class="st-h">{_t("On the Decks screen")}</div><div class="st-box">'
            + _st_row(_t("Due Crew on the Decks screen"), _st_switch("show_leaderboard", g("show_leaderboard", True), _t("Due Crew on the Decks screen")),
                      _t("Tools › Due Crew › Show on the Decks screen brings it back"))
            + _st_row(_t("Tabs"), f'<span class="st-pills">{pills}</span>')
            + _st_row(_t("Calm board"), _st_switch("calm", g("calm", False), _t("Calm board")),
                      _t("A tab appears when it has something to show you"))
            + f'</div><div class="st-h">{_t("Look")}</div><div class="st-box">'
            + _st_row(_t("Theme"), _st_seg("theme", (("auto", _t("Match Anki")), ("light", _t("Light")), ("dark", _t("Dark"))),
                                           cfg.get("theme", "auto"), _t("Theme")))
            + _st_row(_t("Accent"), f'<span class="st-sw" role="group" aria-label="{_t("Accent")}">{swatches}</span>')
            # 3.10.0 (words.py): Anki's language unless picked here; each named as its speakers write it. The note says who
            # drafted them, and Suggest a wording is the feedback window, written in one's own language (SC, 13 Nov)
            + _st_row(_t("Language"), _st_seg("lang", ((_words.AUTO, _t("Match Anki")),) + tuple(_words.NAMES.items()),
                                              cfg.get("lang", _words.AUTO), _t("Language")),
                      f'{_t(_words.NOTE)} <a class="st-lk" href="#" {_st_click("setfeedback")}>{_t("Suggest a wording")}</a>')
            + f'</div><div class="st-h">{_t("Your crew")}</div><div class="st-box">'
            + _st_row(_t("Yesterday for friends who haven't synced"),
                      _st_switch("show_stale", g("show_stale", True), _t("Yesterday for friends who haven't synced")))
            + _st_row(_t("Tell me when my crew studies"),
                      _st_switch("sync_notifications", g("sync_notifications", True), _t("Tell me when my crew studies")))
            + '</div><div class="st-h">Pip</div><div class="st-box">'
            + _st_row("Pip", _st_switch("sev", g("sev", True), "Pip"), _t("The square from the logo, beside it and in your fifteens"))
            + _st_row(_t("Pip&rsquo;s closet"), f'<a class="st-lk" href="#" {_st_click("closet")}>{_t("Open")}</a>',
                      _t("What your Pip has on, and what it&rsquo;s earned"))
            + _settings_songs(cfg)  # 3.9.6: song of the moment, this computer's
            + '</div>'
            + f'<div class="st-foot"><span></span>'
              f'<a class="st-lk" href="#" {_st_click("setreset")}>{_t(RESET_WORDS)}</a></div>')


def _settings_study(cfg, fsrs=None, reach=None, stops=()):
    """3.9.9: what works while I study, a tab of its own (it was spread through Board).
    fsrs (3.9.1): whether FSRS is on in this collection (None: not known),
    for two buttons' one-line note; reach: Recover leeches' count."""
    g = lambda k, d: bool(cfg.get(k, d))  # noqa: E731
    # 3.9.10: new cards stopped from Reviews ahead (it could, till Insights became data only): the way back, while one runs
    stopped = "".join(
        _st_row(_t("New cards stopped in {deck}", deck=_html.escape(str(name))),
                f'<a class="st-lk" href="#" onclick="{_pycmd("insaheadon:" + str(int(did)))}">{_t("Turn back on")}</a>')
        for did, name in stops)
    # 3.9.3 (Sam's pick A): by each deck's leech count; 8 lapses after its question's Not these
    extras = (_t("Suggestions: today&rsquo;s misses, new leeches. Recover leeches: each morning, as new cards, at 8 lapses") if reach == "eight"
              else _t("Suggestions: today&rsquo;s misses, new leeches. Recover leeches: each morning, as new cards, at each deck's leech count"))
    return (f'<div class="st-h">{_t("Today")}</div><div class="st-box">' + stopped
            + _st_row(_t("Today, Upcoming, Later"), _st_switch("due_show", g("due_show", True), _t("Today, Upcoming, Later")))
            # 3.9.12 (SC agreed): Suggestions and Recover leeches are one row, each still its own switch
            + _st_row(_t("Today&rsquo;s extras"),
                      f'<span class="st-two"><label>{_t("Suggestions")} ' + _st_switch("due_suggest", g("due_suggest", True), _t("Suggestions"))
                      + f'</label><label>{_t("Recover leeches")} ' + _st_switch("due_leeches", g("due_leeches", False), _t("Recover leeches")) + '</label></span>',
                      extras)
            + f'</div><div class="st-h">{_t("Magic search")}</div><div class="st-box">'
            + _st_row(_t("Magic search"), _st_switch("magic_search", g("magic_search", True), _t("Magic search")),
                      _t("The field under your decks, and {keys} from any screen", keys=MAGIC_KBD))  # 3.9.7; 3.9.9: its field
            # 3.9.1, two buttons (Sam's picks): every deck; FSRS off, allowed with a note
            + f'</div><div class="st-h">{_t("Reviewing")}</div><div class="st-box">'
            + _st_row(_t("Two buttons"), _st_switch("two_buttons", g("two_buttons", False), _t("Two buttons")),
                      _t("Again and Good. Hard and Easy hide; 2, 3 and 4 count as Good. Phones keep four.")
                      + (" " + _t("Works best with FSRS on.") if fsrs is False else ""))
            # 3.9.12 (SC's pick A): Anki's deck list as what there is to do, where Anki buries siblings
            + _st_row(_t("Deck counts leave out buried siblings"),
                      _st_switch("deck_counts", g("deck_counts", False), _t("Deck counts leave out buried siblings")),
                      _t("Anki&rsquo;s deck list counts every card of a note, then buries the siblings as you study. On, it shows what you&rsquo;ll do."))
            + f'</div><div class="st-h">{_t("Fifteen and rooms")}</div><div class="st-box">'
            + _st_row(_t("Fifteen? in the top bar"), _st_switch("fifteen", g("fifteen", True), _t("Fifteen? in the top bar")),
                      _t("And the nudge, when you haven't started by your usual time"))
            + _st_row(_t("On a break"), _st_seg("sev_break", (("breathe", _t("Breathe")), ("stretch", _t("Stretch"))),
                                                cfg.get("sev_break", "breathe"), _t("On a break")),
                      _t("Breathe with Pip, four counts a side, or stretch"))
            + _st_row(_t("Room chip"), _st_seg("room_chip_side", (("left", _t("Left")), ("right", _t("Right"))),
                                               cfg.get("room_chip_side", "right"), _t("Room chip")),
                      _t("Its side of Anki&rsquo;s top bar"))  # back the day it left (SC's was on the left)
            + f'</div><div class="st-h">{_t("Shortcuts")}</div><div class="st-box">'
            + _st_row(_t("Study what&rsquo;s next"), f'<kbd class="st-kbd">{STUDY_KBD}</kbd>', _t("From any Anki screen"))
            + _st_row(_t("Ask the squad about this card"), f'<kbd class="st-kbd">{ASK_KBD}</kbd>', _t("While reviewing"))
            + _st_row(_t("Magic search"), f'<kbd class="st-kbd">{MAGIC_KBD}</kbd>', _t("From any Anki screen"))
            + '</div>'
            + f'<div class="st-foot"><span></span>'
              f'<a class="st-lk" href="#" {_st_click("setreset")}>{_t(RESET_WORDS)}</a></div>')


# 3.9.6: song of the moment, this computer's: the dance floor and how it dances, and the app Listen opens
DANCE_MOTIONS = (("gentle", _later("Gentle")), ("lively", _later("Lively")), ("still", _later("Still")))
MUSIC_APPS = (("ask", _later("Ask me the first time")), ("apple", "Apple Music"), ("spotify", "Spotify"),
              ("youtube", "YouTube Music"), ("other", _later("Another app")))  # songs.APPS, with "" as ask


def _settings_songs(cfg):
    """Settings › Board's song rows: the dance floor on or off (its × hides it; this brings it back), its
    motion, and my music app (Listen; a card's ▾ changes it too). Each one of song_flow's commands."""
    on = cfg.get("dance_floor", True) is not False
    app = cfg.get("music_app") if cfg.get("music_app") in dict(MUSIC_APPS) else "ask"
    apps = "".join(f'<button class="st-pill{" on" if k == app else ""}" aria-pressed="{"true" if k == app else "false"}" '
                   f'{_st_click("songapp:" + k)}>{_t(t)}</button>' for k, t in MUSIC_APPS)
    return (f'</div><div class="st-h">{_t("Study soundtrack")}</div><div class="st-box">'
            + _st_row(_t("Dance floor"), _st_toggle_cmd("dancehide" if on else "danceshow", on, _t("Dance floor")),
                      _t("Your crew&rsquo;s songs, in the Decks screen&rsquo;s corner"))
            + _st_row(_t("My music app"), f'<span class="st-pills" role="group" aria-label="{_t("My music app")}">{apps}</span>',
                      _t("Where Listen opens your crew&rsquo;s songs, on this computer")))


def _date_rows(cfg):
    """My exam and my days away (Settings › You since 3.9.9): each a date and its switch."""
    exam = str(cfg.get("exam_date") or "")
    a, b = str(cfg.get("away_from") or ""), str(cfg.get("away_to") or "")
    away_on = bool(a and b)
    esc = _html.escape
    exam_ctl = (f'<input class="st-in" type="date" data-f="exam" value="{esc(exam)}"{"" if exam else " disabled"} '
                f'aria-label="{_t("Exam date")}" onchange="if(this.value)pycmd(\'duecrew:setexam:\'+this.value+\'|\'+window.dcBK);">'
                + _st_toggle_cmd("setexam:" + ("off" if exam else "on"), bool(exam), _t("Exam")))
    send = "pycmd('duecrew:setaway:'+document.getElementById('st-af').value+':'+document.getElementById('st-at').value+'|'+window.dcBK);"
    away_ctl = (f'<input class="st-in" type="date" id="st-af" data-f="af" value="{esc(a)}"{"" if away_on else " disabled"} aria-label="{_t("Away from")}" '
                f'onchange="{send}"><span style="color:var(--dc-muted)">{_t("to")}</span>'
                f'<input class="st-in" type="date" id="st-at" data-f="at" value="{esc(b)}"{"" if away_on else " disabled"} aria-label="{_t("Away until")}" '
                f'onchange="{send}">' + _st_toggle_cmd("setaway:" + ("off" if away_on else "on"), away_on, _t("Away")))
    return (_st_row("&#128214; " + _t("Exam"), exam_ctl, _t("Your crew sees it for the two weeks before"))
            + _st_row("&#9992;&#65039; " + _t("Away"), away_ctl, _t("Your crew sees you&rsquo;re away")))


def _settings_privacy(cfg):
    choice = "paused" if cfg.get("paused") else "showup" if cfg.get("show_up") else "numbers"

    def radio(key, title, sub=""):
        on = key == choice
        return (f'<button class="st-radio{" on" if on else ""}" role="radio" aria-checked="{"true" if on else "false"}" '
                f'{_st_click(f"setprivacy:{key}")}><i></i><span><b>{title}</b>{f"<small>{sub}</small>" if sub else ""}</span></button>')
    nums = ""
    if choice == "numbers":
        nums = '<div class="st-sub"><span class="st-pills">' + "".join(
            f'<button class="st-pill{" on" if cfg.get(k, True) else ""}" aria-pressed="{"true" if cfg.get(k, True) else "false"}" '
            f'{_st_click(f"set:{k}:{0 if cfg.get(k, True) else 1}")}>{t}</button>'
            for k, t in (("share_reviews", _t("Reviews")), ("share_time", _t("Study time")), ("share_retention", _t("Retention")),
                         ("share_streak", _t("Streak")), ("share_heatmap", _t("Heatmap")))) + '</span></div>'
    return (f'<div class="st-h">{_t("What your crew and squads see")}</div><div class="st-box" role="radiogroup">'
            + radio("numbers", _t("My numbers")) + nums
            + radio("showup", _t("Just that I studied"), _t("Squares, no numbers. You see everyone the same way."))
            + radio("paused", _t("Nothing for now"), _t("Your crew sees &ldquo;on a break&rdquo;; your streak keeps counting. "
                                                        "Kept 24 months without activity."))
            # 3.9.10: the studying dot shows by itself; this is its switch (not for someone paused or just showing up)
            + f'</div><div class="st-h">{_t("While you study")}</div><div class="st-box">'
            + _st_row(_t("Show when I&rsquo;m studying"), _st_switch("show_studying", cfg.get("show_studying", True) is not False,
                                                                    _t("Show when I'm studying")),
                      _t("A dot by your name for an hour after your last review. Not shown while you&rsquo;re paused or just showing up.")
                      if not (cfg.get("paused") or cfg.get("show_up")) else
                      _t("Off while you&rsquo;re paused or just showing up."))
            # 3.9.9, Know when it breaks: the errors this computer met, by code, with the day's first sync
            + f'</div><div class="st-h">{_t("What Due Crew counts")}</div><div class="st-box">'
            + _st_row(_t("Send what went wrong, and what gets used"),
                      f'<a class="st-lk" href="#" {_st_click("errsee")}>{_t("See what went")}</a>'
                      + _st_switch("send_errs", _sends_errs(cfg), _t("Send what went wrong, and what gets used")),
                      _t("Error codes, and which parts you opened that day, as counts. Never your cards, plans or crew."))
            + f'</div><div class="st-foot"><span>{_t("Turning a number off also takes it off this week.")}</span>'
            # 3.7.1, D3: the page that says what's kept, for how long, and how it goes
            f'<a class="st-lk" href="#" {_st_click("privacypage")}>{_t("What Due Crew keeps")} &rsaquo;</a></div>')


def _st_toggle_cmd(cmd, on, label):
    return (f'<button class="st-tg{" on" if on else ""}" role="switch" aria-checked="{"true" if on else "false"}" '
            f'aria-label="{label}" {_st_click(cmd)}></button>')


# 3.8.0, pick 28 (Find a setting): words people use for a setting that its own label doesn't say
FIND_WORDS = {
    "set:theme:": "dark light night mode", "set:accent:": "colour color green purple blue", 
    "set:sync_notifications:": "notify notification alert", "set:show_leaderboard:": "hide off board decks screen",
    "settabs:": "tabs hide squads decks plans insights pip party games", "set:due_suggest:": "hard habit misses again",
    "set:calm:": "calm simple fewer tabs hide declutter", "set:due_leeches:": "leech suspended", "set:share_time:": "minutes hours privacy private",
    "set:share_reviews:": "cards numbers privacy private", "set:share_heatmap:": "year squares", "exam": "test date countdown",
    "af": "holiday vacation trip break", "setprivacy:paused": "pause break hide", "setprivacy:showup": "show up numbers squares",
    "setsignout": "log out", "setdelete": "remove erase", "setfeedback": "bug idea report", "label": "crew name group",
    "setreset": "default", "friends": "crew code invite", "decks": "share deck",
    # 3.8.1: the Fifteen and Pip
    "set:fifteen:": "timer pomodoro focus session nudge minutes", "set:sev:": "mascot character buddy animation",
    "set:sev_break:": "breathe stretch rest",
    # 3.9.1
    "set:two_buttons:": "hard easy again good pass fail answer buttons keys review",
    # 3.9.6: study soundtrack (song of the moment in code)
    "dance": "music song songs soundtrack dj party floor dancing pip motion animation corner",
    "songapp": "music app listen spotify apple youtube song",
    # 3.9.9: Know when it breaks
    "set:show_studying:": "studying now dot live online presence active green im i'm hour",
    "set:send_errs:": "errors error bugs bug crash broken report reports diagnostics problems wrong usage used counts analytics telemetry",
    "errsee": "errors error bugs report diagnostics what goes sent",
}


# 3.9.3: the plan windows aren't settings, but someone typing "calendar" or
# "plan" into Find a setting is looking for them: (command, label, words)
FIND_WINDOWS = (
    ("planyours", _later("Your plans"), "plan plans dates weeks schedule write edit author builder follow"),
    ("planstart", _later("New plan"), "new plan calendar syllabus block schedule file pdf word powerpoint slides import make deck"),
    # 3.9.7: Magic search, QBank QIDs' way since its round 2 (Sam: "this is replacing QBank QID search")
    ("magic", _later("Magic search"), "find search cards topic tag resource filtered deck study now put on a day quiz exam away filter "
                              "qbank qids missed questions question ids bank practice block wrong incorrect unsuspend"),
)


def _find_key(f):
    """A control's data-f, without the state at its end ("set:share_time:0"
    finds the switch whichever way it's set)."""
    bits = f.split(":")
    return ":".join(bits[:2]) + ":" if bits[0] in ("set", "settabs") and len(bits) > 2 else f


def _settings_tab(tab, view, cfg, pip=True):
    """A tab's rows. pip=False: the You tab with my emoji, not my Pip's drawing (Find a setting's index)."""
    if tab == "you":
        return _settings_you(view, cfg) if pip else _settings_you(view, dict(cfg, sev=False))
    if tab == "board":
        return _settings_board(cfg)
    if tab == "study":
        return _settings_study(cfg, view.get("fsrs"), view.get("leech_reach"), view.get("new_stops") or ())
    return _settings_privacy(cfg)


def settings_index(view, cfg):
    """3.8.0, pick 28: every setting a word can find, across Settings' four
    tabs: [{t: tab, f: the control's data-f (its start), l: its label,
    w: where ("Board › Look"), k: words to match}]. Read from the
    tabs as they're drawn, so a new row is findable as soon as it's there.
    Labels and headings are the add-on's own words; the people, squads and
    decks the You tab names stay out."""
    import html as H
    names = dict(SETTINGS_TABS)
    out, seen = [], set()

    def add(tab, f, label, where, extra=""):
        label = " ".join(_re.sub(r"<[^>]+>", "", H.unescape(label)).split())
        key = (tab, _find_key(f))
        if not label or key in seen:
            return
        seen.add(key)
        words = " ".join([label, where, extra] + [w for k, w in FIND_WORDS.items() if f.startswith(k)])
        out.append({"t": tab, "f": _find_key(f), "l": label, "w": where, "k": " ".join(_re.findall(r"[a-z0-9]+", words.lower()))})
    for tab, _name in SETTINGS_TABS:
        body = _settings_tab(tab, dict(view, name="", status="", emoji=""), cfg, pip=False)
        sections = _re.split(r'<div class="st-h">', body)
        for i, sec in enumerate(sections):
            head = H.unescape(sec.split("</div>", 1)[0]) if i else ""
            where = _t(names[tab]) + (f" › {head}" if head else "")
            rows = list(_re.finditer(r'<div class="st-row"><span class="st-l"><span>(.*?)</span>(?:<small>(.*?)</small>)?', sec))
            for j, m in enumerate(rows):
                end = rows[j + 1].start() if j + 1 < len(rows) else len(sec)
                # a row's switch, when it has one (3.9.9: Send Sam what went wrong's comes after See what went)
                f = _re.search(r'data-f="(set:[^"]+)"', sec[m.end():end]) or _re.search(r'data-f="([^"]+)"', sec[m.end():end])
                sub = H.unescape(m.group(2) or "") if tab != "you" else ""  # the You tab's lines name people and squads
                if f:
                    add(tab, f.group(1), m.group(1), where, sub)
                for pf, pt in _re.findall(r'<button class="st-pill[^"]*"[^>]*data-f="([^"]+)"[^>]*>(.*?)</button>', sec[m.end():end]):
                    add(tab, pf, pt, where + " › " + H.unescape(m.group(1)))
            for f, b, small in _re.findall(r'<button class="st-radio[^"]*"[^>]*data-f="([^"]+)"[^>]*><i></i><span><b>(.*?)</b>(?:<small>(.*?)</small>)?', sec):
                add(tab, f, b, where, H.unescape(small))
            for f, t in _re.findall(r'<button class="st-pill[^"]*"[^>]*data-f="([^"]+)"[^>]*>(.*?)</button>', sec):
                add(tab, f, t, where)
            for f, t in _re.findall(r'<a class="st-lk[^"]*" href="#" data-f="([^"]+)"[^>]*>(.*?)</a>', sec):
                if t.strip() not in (_t("Open"), _t("Send&hellip;")):
                    add(tab, f, t, where)
    for cmd, label, words in FIND_WINDOWS:  # 3.9.3: found last, after every setting a word names
        said = _t(label)  # found by its name in the language in use, and by its English as before
        out.append({"t": "", "p": cmd, "f": "", "l": said, "w": _t("Opens the window"),
                    "k": " ".join(_re.findall(r"[a-z0-9]+", f"{label} {words}{'' if said == label else ' ' + said}".lower()))})
    return out


def settings_html(view, cfg):
    """3.5.0: Settings in place of the board.
    view: {tab, signed_in, name, emoji, status, sync, crew, squads, decks},
    from the glue; every string in it is escaped here."""
    tab = view.get("tab") if view.get("tab") in dict(SETTINGS_TABS) else "you"
    pills = "".join(f'<a class="dc-pill{" on" if k == tab else ""}" href="#" {_st_click("settab:" + k)}>{_t(t)}</a>'
                    for k, t in SETTINGS_TABS)
    body = _settings_tab(tab, view, cfg)
    foot = _t("Privacy, dates, status and accent follow your account.") if view.get("signed_in") else ""
    none = _t("Nothing by that name")  # FIND_JS's word, sent only when it isn't the English the script has
    none = "" if none == "Nothing by that name" else f'data-none="{_html.escape(none, quote=True)}" '
    pip = ""
    if tab == "you" and cfg.get("sev", True):  # 3.8.22: my Pip in my colour, by day or night as the board
        light, dark = accent_pair(cfg.get("accent"))
        pip = (f'<style>{_sev.CSS}{_by_theme(cfg, "#due-crew .st-pip", f"--sv-a: {light};", f"--sv-a: {dark};")}'
               '\n#due-crew .st-pip { display: inline-flex; line-height: 0; margin: 6px 8px 0 0; text-decoration: none; border: 0; }</style>')
    return (f'<div id="due-crew" class="dc-frame dc-set">{_css(cfg)}<style>{SETTINGS_CSS}</style>{pip}'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span><span>{pills}</span></div>'
            f'<div class="st-bar"><a class="st-back" href="#" {_st_click("setclose")}>&lsaquo; {_t("Board")}</a><b>{_t("Settings")}</b>'
            # 3.8.0, pick 28: a word finds a setting on any tab (FIND_JS)
            f'<span class="st-find"><input type="search" class="st-in" placeholder="{_t("Find a setting")}" aria-label="{_t("Find a setting")}" '
            f'autocomplete="off" {none}data-ix="{_html.escape(_json.dumps(settings_index(view, cfg)), quote=True)}" '
            f'oninput="dcFind.type(this)" onkeydown="dcFind.key(event, this)">'
            f'<span class="st-hits" role="listbox" aria-label="{_t("Settings found")}" hidden></span></span></div>'
            f'{body}'
            f'{f"<div class=st-note>{foot}</div>" if foot else ""}</div>')
