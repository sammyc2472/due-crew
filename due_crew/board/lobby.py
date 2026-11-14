"""A study room's lobby on the Decks screen and its seats; the Fifteen's.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
import re as _re

from .. import room_model
from .. import sev as _sev
from ..words import t as _t, tn as _tn

from .base import _pycmd, accent_pair


def _cards(n):
    """ "1 card", "1,204 cards"."""
    return _t("{n} card", n=f"{n:,}") if n == 1 else _t("{n} cards", n=f"{n:,}")


def room_html(room):
    """2.12: the Decks screen's study rooms, from room_model.board_view.
    Every string in it may carry a friend's name: escaped here."""
    e = _html.escape
    out = ""
    fd = room.get("fifteen_done")
    if fd:
        # 3.8.1: a session of fifteens, ended: Pip stacks a square for each
        n = int(fd.get("n") or 0)
        mins = int(fd.get("minutes") or 0)
        cards = fd.get("cards")
        what = f'{_tn("{n} fifteen", "{n} fifteens", n)} &middot; {e(room_model.duration_text(mins))}'
        if isinstance(cards, int):
            what += f' &middot; {_cards(cards)}'
        if fd.get("sev"):
            up, down = _sev.stack_reach(n, 44)  # room for the squares drawn and the shadow, no more
            icon = f'<span class="dc-fig" style="padding:{up}px 0 {down}px">{_sev.slot(fd["sev"], 44)}</span>'
        else:
            icon = "<span>&#10003;</span>"
        out += (f'<div class="dc-wrap dc-sess">{icon}<span><b>{_t("Your session:")}</b> {what}.</span>'
                f'<a class="wx" href="#" title="{_t("Done")}" style="margin-left:auto" onclick="{_pycmd("room15x")}">&times;</a></div>')
    done = room.get("done")
    if done:
        rounds, took = int(done.get("rounds", 0)), e(room_model.duration_text(done.get("minutes", 0)))
        said = (_t("{rounds} rounds, {time} together with {who}.", rounds=rounds, time=took, who=e(str(done["with"]))) if done.get("with")
                else _t("{rounds} rounds, {time} together.", rounds=rounds, time=took))
        out += (f'<div class="dc-wrap"><span>&#10003;</span><span><b>{_t("Room done:")}</b> {said}</span>'
                f'<a class="wc" href="#" onclick="{_pycmd("roomshare")}">{_t("Share")}</a>'
                f'<a class="wc" href="#" style="margin-left:6px" onclick="{_pycmd("roomcheer")}">{_t("Cheer the room")}</a>'
                f'<a class="wx" href="#" title="{_t("Done")}" onclick="{_pycmd("roomdonex")}">&times;</a></div>')
    for inv in (room.get("invites") or [])[:2]:
        key = str(inv.get("key", ""))
        line = str(inv.get("line") or "")
        # one or several by the count the view brings (3.10.0: " and " is said in the language in use); the word, without one
        many = int(inv["n"]) > 1 if isinstance(inv.get("n"), int) else " and " in line
        here = (_t("{who} are in", who=e(line)) if many else _t("{who} is in", who=e(line))) if line else ""
        out += (f'<div class="dc-wrap"><span class="rdot"></span><span><b>{e(str(inv.get("title", "")))}</b>'
                f' &middot; {e(str(inv.get("sub", "")))}'
                f'{" &middot; " + here if here else ""}'
                f'</span><a class="wc" href="#" onclick="{_pycmd("roomjoin:" + key)}">{_t("Join")}</a>'
                f'<a class="wx" href="#" title="{_t("Not now")}" onclick="{_pycmd("roomx:" + key)}">&times;</a></div>')
    mine = room.get("mine")
    if mine and mine.get("fifteen"):
        return out + _fifteen_lobby(mine)
    if mine:
        bars = ""
        for i, f in enumerate(mine.get("bars") or []):
            if i:
                bars += f'<em style="flex:{int(mine.get("brk_min", 5)) or 1}"></em>'
            bars += f'<i style="flex:{int(mine.get("round", 25))}"><u style="width:{float(f) * 100:.1f}%"></u></i>'
        seats = [s for s in (mine.get("seats") or []) if isinstance(s, dict)][:6]
        faces = ("".join(_seat_html(s) for s in seats) if seats  # 3.8.1: Pip on, each member is their Pip
                 else "".join(f"<i>{e(str(x))}</i>" for x in (mine.get("initials") or [])[:6]))
        out += (f'<div class="dc-room"><span class="rg{" brk" if mine.get("brk") else ""}" style="--p:{float(mine.get("frac", 0)):.3f}">'
                f'<b>{e(str(mine.get("label", "")))}</b></span>'
                f'<span class="rt"><b>{e(str(mine.get("title", "")))}</b><small>{e(str(mine.get("sub", "")))}</small>'
                f'<span class="rb">{bars}</span></span>'
                f'<span class="rw"><span class="fc{" sv-seats" if seats else ""}" title="{e(str(mine.get("line", "")))}">{faces}</span>'
                f'<a class="go" href="#" onclick="{_pycmd("roomstudy")}">{_t("Study")}</a>'
                f'<a class="lv" href="#" onclick="{_pycmd("roomleave")}">{_t("Leave")}</a></span></div>')
    return out


_HEX = _re.compile(r"#[0-9a-fA-F]{6}")


def _seat_html(s):
    """3.8.1: a crew room's member as their Pip (room_model.seats), a 24 px
    seat like the initials' circles: their accent by day and by night (only
    a colour reaches the style; anything else, the default's), blinking at
    its own moment and doing its own small thing (a SEAT_MOVES one), their
    name its label (escaped)."""
    dflt, a = accent_pair(None), s.get("a")
    pair = a if isinstance(a, (list, tuple)) and len(a) == 2 else dflt
    light, dark = (x if isinstance(x, str) and _HEX.fullmatch(x) else d for x, d in zip(pair, dflt))
    try:
        delay = max(-60.0, min(0.0, float(s.get("d") or 0)))
    except (TypeError, ValueError):
        delay = 0.0
    try:  # 3.9.0: its own blink cycle (sev.blink)
        cycle = max(2.0, min(10.0, float(s.get("b") or _sev.BLINK)))
    except (TypeError, ValueError):
        cycle = _sev.BLINK
    name = _html.escape(str(s.get("n") or ""), quote=True)
    turn = s.get("m") if s.get("m") in _sev.SEAT_MOVES else "idle"  # its own small thing now and then
    look = s.get("l") if isinstance(s.get("l"), list) else None  # 3.8.2: what they have on (closet.clean rules it)
    return (f'<span class="seat" title="{name}" style="--sa-l:{light};--sa-d:{dark};--sv-b:{cycle:.2f}s;--sv-d:{delay:.2f}s">'
            f'{_sev.slot(_sev.svg("idle", turn, label=name, look=look), 40)}</span>')


def _fifteen_lobby(m):
    """3.8.1: my fifteen on the Decks screen: its ring with Pip beside it,
    and what can be said there (the question too, as the review screen asks it)."""
    e = _html.escape
    st = m.get("state")
    sub = str(m.get("sub", ""))
    if st == "ask" and isinstance(m.get("cards"), int):
        sub = (_t("{n} card.", n=f'{m["cards"]:,}') if m["cards"] == 1 else _t("{n} cards.", n=f'{m["cards"]:,}')) + " " + sub
    go = lambda cmd, text, cls="go": f'<a class="{cls}" href="#" onclick="{_pycmd(cmd)}">{text}</a>'  # noqa: E731
    if st == "ask":
        acts = ("" if m.get("cap") else go("room15five", _t("Take five, then another")) + go("room15now", _t("Another now"), "lv"))
        acts += go("room15stop", _t("Stop here"), "go" if m.get("cap") else "lv")
    elif st == "break":
        acts = go("room15now", _t("Start now")) + go("room15stop", _t("Stop here"), "lv")
    else:
        acts = go("duestudy", _t("Study")) + go("room15stop", _t("Stop here"), "lv")
    sv = _sev.slot(m["sev"], 46) if m.get("sev") else ""
    return (f'<div class="dc-room dc-fif"><span class="rgw">{sv}<span class="rg{" brk" if m.get("brk") else ""}" '
            f'style="--p:{float(m.get("frac", 0)):.3f}"><b>{e(str(m.get("label", "")))}</b></span></span>'
            f'<span class="rt"><b>{e(str(m.get("title", "")))}</b><small>{e(sub)}</small></span>'
            f'<span class="rw">{acts}</span></div>')
