"""Plans, the glue: the plan's joys (3.9.6), one moment at a time."""

import re

from aqt import mw
from aqt.utils import tooltip

from .. import app
from .. import plans as P
from ..app import _state
from ..app import cfg
from ..errs import oops

from .state import _pcfg, _psave, followed
from .lessons import board_view


# ---- 3.9.6: the plan's joys (plans.joy_step; Sam's picks, the "Joy on the plan card" mock) ----
# A set done pops on the path and Pip hops to it; halfway, three-quarters and
# the last set are a line each with Share and ×; the finish line is a show
# over the Decks screen, then a line with Share; Behind cleared says Caught
# up for the rest of the day; the first morning says Day one, Pip's let's-go.
# What's played is plans.json's "joy" (this profile's, never sent): each
# moment is claimed the first time it's on screen (You › Plans, the Decks
# screen up) and plays from then, a redraw in its seconds going on from where
# it is. Nothing new is asked of the server.

JOY_KEY = "joy"


def _joy_states(c=None):
    j = (c if c is not None else _pcfg()).get(JOY_KEY)
    return j if isinstance(j, dict) else {}


def joy(card, today, shown=False, now=None):
    """card["joy"]: the card's joys as the board draws them (P.joy_step's
    view, with Pip's markup for its moments: Settings › Pip, in my look), or
    None. What changed goes back in plans.json; a plan just finished counts
    for the closet (closet_flow.note_plan_done). Main thread."""
    import time
    pid = str(card.get("id") or "")
    if not card.get("path") or not pid:
        card["joy"] = None
        return None
    pc = _pcfg()
    states = _joy_states(pc)
    st0 = states.get(pid)
    st, view = P.joy_step(st0, card["path"], card.get("behind"), today, time.time() if now is None else now,
                          shown=shown, name=str(card.get("name") or ""))
    if st != st0 and st is not None:
        states[pid] = st
        pc[JOY_KEY] = states
        _psave(pc)
        f = st.get("fin") if isinstance(st.get("fin"), dict) else {}
        if f.get("day") and not ((st0 or {}).get("fin") or {}).get("day"):
            try:
                from .. import closet_flow
                closet_flow.note_plan_done(pid)  # 3.9.6: three plans with every set done, the Finisher's ribbon
                from .. import scrap_flow
                scrap_flow.moment("plan", f"Finished {str(card.get('name') or 'a plan')}", "Every set of it done.", "cheer", today)  # 3.9.10
            except Exception:
                oops()
    card["joy"] = _joy_pips(view, pid) if view else None
    return card["joy"]


def _joy_pips(view, pid):
    """Pip for the moments that have one (a set done's hop, a move from the
    day done's mix, never the last one, the same one through its redraws;
    day one's let's-go), while they're out; none with Pip off."""
    from .. import rooms
    if not rooms.sev_on():
        return view
    from .. import sev
    look = rooms.my_look()
    pop, one = view.get("pop"), view.get("day1")
    if pop and pop.get("ago") is not None:
        moves = _state.setdefault("joy_moves", {})
        key = f"{pid}:{pop['uid']}"
        if key not in moves:
            moves[key] = rooms.pick("hop")
        pop["pip"] = re.sub(r'<rect class="cf"[^>]*/>', "", sev.move("hop", moves[key], rest=pop["ago"] > 1.5, look=look,
                                                                      label="Pip: a set done"))
    if one and one.get("ago") is not None:
        one["pip"] = sev.move("ready", "ready", rest=one["ago"] > 1.5, look=look, label="Pip: day one")
    return view


def joy_claim(cards, c=None):
    """You › Plans is drawn with the board up: the plan it shows claims what's
    waiting for it, which plays from now (once). Main thread."""
    if not cards or not app.board_up():
        return
    from .. import board
    card = board._picked_plan(cards, c if c is not None else cfg())
    today = _state["labels"][0] if _state["labels"] else ""
    if card and today:
        try:
            joy(card, today, shown=True)
        except Exception:
            oops()


def joy_show():
    """At a board draw on the Decks screen: a plan I follow just finished
    plays its show over it (board.finish_js, show.js), once a plan; the next
    one waits for the next draw. Main thread."""
    import time
    if not app.board_up() or not _state.get("board_shown"):
        return False
    pc = _pcfg()
    states = _joy_states(pc)
    mine = {p["id"]: p for p in followed()}
    for pid, st in states.items():
        f = (st or {}).get("fin") if isinstance(st, dict) else None
        if not isinstance(f, dict) or not f.get("day") or f.get("at") or pid not in mine:
            continue
        f["at"] = time.time()
        _psave(pc)
        from .. import board
        app.board_eval(board.finish_js(_finish_view(pid, mine[pid], f)))
        return True
    return False


def _finish_view(pid, plan, f):
    """What the finish show draws: the plan's name, its numbers, Pip (in my
    look, a hat or costume off for the grad cap that lands on it) and its
    accent; Pip off, no Pip."""
    from .. import board, rooms
    out = {"pid": pid, "name": str(f.get("name") or plan.get("name") or "the plan"),
           "sets": int(f.get("sets") or 0), "cards": int(f.get("cards") or 0), "weeks": int(f.get("weeks") or 0),
           "a": list(board.accent_pair(cfg().get("accent"))), "pip": None}
    if rooms.sev_on():
        from .. import closet, sev
        from ..closet_art import ART
        bare = [k for k in closet.clean(rooms.my_look())
                if closet.BY[k]["slot"] != closet.COSTUME and "head" not in closet.places(k)]
        cf = lambda s: re.sub(r'<rect class="cf"[^>]*/>', "", s)  # noqa: E731
        out["pip"] = {"hop": cf(sev.move("hop", "hop", rest=True, look=bare, label="Pip")),
                      "jump": cf(sev.move("hop", "jump", look=bare, label="Pip: finished")),
                      "still": sev.svg("hop", rest=True, look=bare + ["gradcap"], label="Pip in its grad cap"),
                      "cap": ART["gradcap"][0]}
    return out


def joy_x(pid, key):
    """× on a milestone's line: gone for today (it would be tomorrow either way)."""
    today = _state["labels"][0] if _state["labels"] else ""
    pc = _pcfg()
    states = _joy_states(pc)
    st = P.joy_dismiss(states.get(pid), key, today)
    if st is None:
        return
    states[pid] = st
    pc[JOY_KEY] = states
    _psave(pc)
    app.swap(cfg())


def _joy_menu(items):
    """The joy line's Share: a menu at the pointer, as the board's Share is."""
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    for label, fn in items:
        menu.addAction(label).triggered.connect(lambda _=False, f=fn: f())
    menu.exec(QCursor.pos())


def joy_share(pid, key):
    """Share on a joy's line (or the finish show's banner): as text, or as a
    picture (sharecard's plan card: the path, Pip with its hop trail). The
    card count starts as Privacy's Reviews switch says. Made here; nothing
    is posted. Main thread."""
    if key not in P.JOY_KEYS:
        return
    c = cfg()
    card = next((x for x in board_view(c).get("cards") or [] if str(x.get("id")) == str(pid)), None)
    j = (card or {}).get("joy") or {}
    line = j.get("line") if key != "fin" and (j.get("line") or {}).get("key") == key else None
    if (key == "fin" and not j.get("fin")) or (key != "fin" and line is None):
        return
    from .. import sharecard
    from ..ui import copy_text
    num = P.joy_numbers(card["path"])
    name = str(card.get("name") or "the plan")
    text = P.joy_text(key, name, num, line, cards=sharecard.privacy(c)["reviews"])

    def as_text():
        copy_text(text)
        tooltip("Copied.")
    _joy_menu([("As text", as_text), ("As a picture…", lambda: joy_picture(pid, key, card))])


def joy_picture(pid, key, card):
    """Share › As a picture… on a joy: the story card, made here (sharecard.plan)."""
    from .. import sharecard as SC
    from ..rooms import sev_on
    from ..ui.share_card_dialog import ShareCardDialog
    num = P.joy_numbers(card["path"])
    line = (card.get("joy") or {}).get("line") or {}
    brow = {"fin": "Finished", "half": "Halfway", "threeq": "Three-quarters", "last": "The last set"}[key]
    d = SC.plan(str(card.get("name") or "the plan"), num["sets"], num["sets"] if key == "fin" else num["done"],
                num["cards"] if key == "fin" else num["seen"], num["weeks"], brow=brow, sev=sev_on(), cap=key == "fin",
                last=str(line.get("name") or "") if key == "last" else "")
    pic = {"kind": "plan", "title": "Share this plan", "sizes": ("story",), "file": f"due-crew-plan-{pid}", "data": d}
    dlg = ShareCardDialog(mw, lambda _k: pic, priv=SC.privacy(cfg()), tooltip=tooltip)
    _state["share_card"] = dlg  # kept while it's open
    dlg.show()
