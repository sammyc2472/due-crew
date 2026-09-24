"""2.10, studying together: "studying now", cards a friend is stuck on and
tips for them, the good-luck card for an exam morning, and the 100-day
cheer. Main-thread rules as in __init__. Nothing here adds a read: live and
flagged cards ride my week doc, lines and tips ride cheers, and what
arrives is kept locally in wrap.json."""

import datetime
import html
import re

from aqt import mw
from aqt.utils import tooltip

from . import app, board
from .app import _state, cfg, client
from .backend.firebase import LIVE_MINUTES, TRICKY_MAX, clean_note, clean_tricky
from .wrap import _save_wrap, _wrap_data

LUCK_EMOJI = "\U0001F340"   # four-leaf clover
TIP_EMOJI = "\U0001F4A1"    # light bulb
THANKS_EMOJI = "\U0001F49A"  # green heart
TIP_DAYS = 14


def _today():
    return _state["labels"][0] if _state["labels"] else datetime.date.today().isoformat()


# ---- routing what arrives ----

def route_cheers(cheers, my_exam, today):
    """(play, luck, tips) from a fetch's cheers. A line marked for luck is
    held for my exam morning, if I have an exam today or ahead; without one
    it plays as a cheer. A tip on a card is kept for that card. The rest
    play as flurries, as always."""
    play, luck, tips = [], [], []
    for ch in cheers:
        if ch.get("luck") and ch.get("note") and my_exam and my_exam >= today:
            luck.append(ch)
        elif ch.get("guid") and ch.get("note"):
            tips.append(ch)
        else:
            play.append(ch)
    return play, luck, tips


def keep(luck, tips, my_exam, today):
    """Main thread. Hold lines for the exam card and tips for their cards
    in wrap.json; returns toast lines."""
    w = _wrap_data()
    toasts = []
    if luck:
        store = w.get("luck") if isinstance(w.get("luck"), dict) else {}
        if store.get("exam") != my_exam:
            store = {"exam": my_exam, "lines": [], "shown": False}
        for ch in luck:
            store["lines"] = [x for x in store["lines"] if x.get("from") != ch["from"]]
            store["lines"].append({"from": ch["from"], "name": ch["name"], "note": ch["note"]})
            toasts.append(f"{LUCK_EMOJI} {html.escape(ch['name'])} left you a line for exam morning.")
        w["luck"] = store
    if tips:
        store = w.get("tips") if isinstance(w.get("tips"), dict) else {}
        for ch in tips:
            got = [t for t in store.get(ch["guid"], []) if t.get("from") != ch["from"]]
            got.append({"from": ch["from"], "name": ch["name"], "note": ch["note"], "day": today})
            store[ch["guid"]] = got[-3:]
            toasts.append(f"{TIP_EMOJI} {html.escape(ch['name'])} sent a tip on a card you flagged. "
                          "It shows when the card comes up.")
        horizon = (datetime.date.fromisoformat(today) - datetime.timedelta(days=TIP_DAYS)).isoformat()
        w["tips"] = {g: [t for t in ts if str(t.get("day", "")) >= horizon]
                     for g, ts in store.items()}
        w["tips"] = {g: ts for g, ts in w["tips"].items() if ts}
    if luck or tips:
        _save_wrap()
    return toasts


def show_luck_card():
    """On my exam day, once: the card with every line my crew left."""
    w = _wrap_data()
    store = w.get("luck")
    if not isinstance(store, dict) or store.get("shown") or not store.get("lines"):
        return
    if store.get("exam") != _today() or mw.state != "deckBrowser":
        return
    name = (client().display_name or "").split(" ")[0]
    mw.web.eval(board.luck_card_js(name, [(x["name"], x["note"]) for x in store["lines"]]))
    store["shown"] = True
    _save_wrap()


def luck_thanks():
    from .social import _send_cheer
    store = _wrap_data().get("luck") or {}
    crew = {e["user_id"] for e in _state["entries"] or []}
    sent = set()
    for x in store.get("lines") or []:
        if x.get("from") in crew and x["from"] not in sent:
            sent.add(x["from"])
            _send_cheer(x["from"], x["name"], THANKS_EMOJI)


def tips_for(guid):
    """[(name, note)] kept for this card."""
    return [(t["name"], t["note"]) for t in (_wrap_data().get("tips") or {}).get(guid, [])]


def card_will_show(text, card, kind):
    """gui_hooks.card_will_show: a crewmate's tip under the answer of the
    card it was sent for. Never on the question: a tip can give it away."""
    try:
        if not kind.endswith("Answer"):
            return text
        tips = tips_for(card.note().guid)
        return text + board.tip_html(tips) if tips else text
    except Exception:
        return text


# ---- sending ----

def _ask_line(title, prompt):
    from aqt.qt import QInputDialog
    text, ok = QInputDialog.getText(mw, title, prompt)
    return clean_note(text) if ok else ""


def send_luck_line(uid):
    from .social import _send_cheer
    entry = next((e for e in _state["entries"] or [] if e["user_id"] == uid), None)
    if entry is None:
        return
    first = str(entry["name"]).split(" ")[0]
    line = _ask_line("Good-luck card",
                     f"A line for {first}'s exam morning. They see it when they open Anki "
                     "that day, with everyone else's.")
    if line:
        _send_cheer(uid, entry["name"], LUCK_EMOJI, line, luck=True)


def send_tip(uid, index):
    from .social import _send_cheer
    entry = next((e for e in _state["entries"] or [] if e["user_id"] == uid), None)
    try:
        flag = (entry or {}).get("tricky", [])[int(index)]
    except (ValueError, IndexError):
        return
    tip = _ask_line("Send a tip",
                    f"On “{flag['text'] or 'this card'}”. One line; "
                    f"{str(entry['name']).split(' ')[0]} sees it when the card comes up.")
    if tip:
        _send_cheer(uid, entry["name"], TIP_EMOJI, tip, guid=flag["guid"])


def milestone_cheer(uid):
    from .social import _send_cheer, cheer_allowed
    m = next((m for m in _state["milestones"] if m[0] == uid), None)
    if m is None:
        return
    emoji = cheer_allowed("\U0001F4AF" if m[2] < 365 else "\U0001F389", client().rules_stale)
    if emoji:
        _send_cheer(uid, m[1], emoji)
    dismiss_milestone(uid)


def dismiss_milestone(uid):
    _state["milestones"] = [m for m in _state["milestones"] if m[0] != uid]
    app.swap(cfg())


# ---- studying now ----

def is_live():
    return board.live_now(client().session.get("live_until"))


def toggle_live():
    """The footer's "I'm studying": a dot by my name for LIVE_MINUTES, or
    off again. It rides my week doc; friends see it on their next refresh."""
    cl = client()
    if is_live():
        cl.session.pop("live_until", None)
        msg = "Stopped."
    else:
        until = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=LIVE_MINUTES)
        cl.session["live_until"] = until.strftime("%Y-%m-%dT%H:%M:%SZ")
        msg = "Your crew sees you're studying, for the next hour."
    cl._save_session()
    for e in _state["entries"] or []:
        if e["you"]:
            e["live_until"] = str(cl.session.get("live_until") or "")
    app.swap(cfg())
    app.sync(light=True, fetch=False)
    tooltip(msg)


# ---- cards that are getting me ----

def _plain(field):
    text = re.sub(r"<[^>]+>|&nbsp;", " ", str(field or ""))
    # a cloze shows as [...]: the friends who see this have the card too,
    # and the flag mustn't give them its answer
    text = html.unescape(re.sub(r"\{\{c\d+::.*?\}\}", "[\u2026]", text))
    return clean_note(text, 60)


def flag_card(card):
    """Reviewer → More / right-click: "This one's getting me". The card's
    note guid, the start of its first field, and its deck ride my week doc
    for a week, for crewmates who have the same note. Again unflags."""
    cl = client()
    note = card.note()
    flags = clean_tricky(cl.session.get("tricky"), _today())
    if any(f["guid"] == note.guid for f in flags):
        flags = [f for f in flags if f["guid"] != note.guid]
        msg = "Unflagged."
    else:
        deck = mw.col.decks.name(card.odid or card.did).split("::")[-1]
        flags.append({"guid": note.guid, "text": _plain(note.fields[0] if note.fields else ""),
                      "deck": clean_note(deck, 40), "at": _today()})
        flags = flags[-TRICKY_MAX:]
        msg = "Flagged for your crew. Anyone with this card can send you a tip."
    cl.session["tricky"] = flags
    cl._save_session()
    app.sync(light=True, fetch=False)
    tooltip(msg)


def reviewer_menu(reviewer, menu):
    """gui_hooks.reviewer_will_show_context_menu: the More menu and a
    right-click on the card both get the flag."""
    card = getattr(reviewer, "card", None)
    if card is None or not client().signed_in:
        return
    flagged = any(f["guid"] == card.note().guid
                  for f in clean_tricky(client().session.get("tricky"), _today()))
    action = menu.addAction("Due Crew: unflag this card" if flagged
                            else "Due Crew: this one's getting me")
    action.triggered.connect(lambda: flag_card(card))


def tricky_view():
    """Flags from my crew on notes I also have: [{uid, name, index, text,
    deck}]. One local query over their guids; a flag on a card I don't
    have is someone else's deck, and stays out of view."""
    flags = [(e, i, t) for e in _state["entries"] or [] if not e["you"]
             for i, t in enumerate(e.get("tricky") or [])]
    if not flags or not mw.col:
        return []
    guids = sorted({t["guid"] for _e, _i, t in flags})
    try:
        have = set(mw.col.db.list(
            f"SELECT guid FROM notes WHERE guid IN ({','.join('?' * len(guids))})", *guids))
    except Exception:
        return []
    return [{"uid": e["user_id"], "name": e["name"], "index": i,
             "text": t["text"], "deck": t["deck"]}
            for e, i, t in flags if t["guid"] in have]
