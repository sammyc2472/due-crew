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
from .app import _state, cfg, client, save_cfg
from .backend.shapes import LIVE_MINUTES, TRICKY_MAX, clean_note, clean_tricky
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
            toasts.append(f"{TIP_EMOJI} {html.escape(ch['name'])} left a tip on a card you flagged. "
                          "It shows when the card comes up.")
        horizon = (datetime.date.fromisoformat(today) - datetime.timedelta(days=TIP_DAYS)).isoformat()
        w["tips"] = {g: [t for t in ts if str(t.get("day", "")) >= horizon]
                     for g, ts in store.items()}
        w["tips"] = {g: ts for g, ts in w["tips"].items() if ts}
    if luck or tips:
        _save_wrap()
    return toasts


def tipped_guids(cheers):
    """The cards a crewmate tipped, from a fetch's cheers."""
    return {str(ch["guid"]) for ch in cheers or [] if ch.get("guid")}


def without_flags(flags, guids):
    return [f for f in flags or [] if f.get("guid") not in guids]


def forget_tipped(cheers):
    """Main thread. 3.0.1: the first tip on a flag takes it down for the
    whole crew. The server already took it off my week; this keeps my next
    sync from putting it back. Flagging the card again is mine to do."""
    guids = tipped_guids(cheers)
    cl = client()
    flags = cl.session.get("tricky") or []
    left = without_flags(flags, guids)
    if guids and len(left) != len(flags):
        cl.session["tricky"] = left
        cl._save_session()


def show_luck_card():
    """On my exam day, once: the card with every line my crew left."""
    w = _wrap_data()
    store = w.get("luck")
    if not isinstance(store, dict) or store.get("shown") or not store.get("lines"):
        return
    if store.get("exam") != _today() or mw.state != "deckBrowser":
        return
    name = (client().display_name or "").split(" ")[0]
    app.board_eval(board.luck_card_js(name, [(x["name"], x["note"]) for x in store["lines"]]))
    store["shown"] = True
    _save_wrap()
    from . import scrap_flow
    scrap_flow.luck_shown(store["lines"], _today())  # 3.9.10: shown, each line is kept (never raises)


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


def local_tips(guid):
    """The tips kept for this card, as they arrived: [{from, name, note, helped?}]."""
    return [dict(t) for t in (_wrap_data().get("tips") or {}).get(guid, []) if isinstance(t, dict)]


def mark_helped(guid, from_uid, on):
    """Main thread. This helped, remembered on the kept tip (3.5.0)."""
    w = _wrap_data()
    changed = False
    for t in (w.get("tips") or {}).get(guid, []):
        if isinstance(t, dict) and t.get("from") == from_uid and bool(t.get("helped")) != on:
            t["helped"] = on
            changed = True
            if on:
                from . import scrap_flow
                scrap_flow.tip_helped(guid, t)  # 3.9.10: a tip that helped is kept (its words, never the card)
    if changed:
        _save_wrap()


# ---- sending ----

def send_luck_line(uid):
    from . import sheets
    from .social import _send_cheer
    entry = next((e for e in _state["entries"] or [] if e["user_id"] == uid), None)
    if entry is None:
        return
    first = str(entry["name"]).split(" ")[0]

    def go(text):
        line = clean_note(text)
        if line:
            _send_cheer(uid, entry["name"], LUCK_EMOJI, line, luck=True)
    # plain text: the words hold a crewmate's name
    sheets.ask_text("Good-luck card", f"A line for {first}'s exam morning. They see it when they open Anki "
                    "that day, with everyone else's.", go, yes="Send")


def send_tip(uid, index):
    from .social import _send_cheer
    entry = next((e for e in _state["entries"] or [] if e["user_id"] == uid), None)
    try:
        flag = (entry or {}).get("tricky", [])[int(index)]
    except (ValueError, IndexError):
        return
    text = next((v["text"] for v in tricky_view()
                 if v["uid"] == uid and v["index"] == int(index)), "")
    first = str(entry['name']).split(' ')[0]
    q = f" {first} asks: “{flag['q']}”" if flag.get("q") else ""
    from . import sheets

    def go(words):
        tip = clean_note(words)
        if tip:
            _send_cheer(uid, entry["name"], TIP_EMOJI, tip, guid=flag["guid"],
                        then=lambda ok: ok and hide_tipped(uid, flag["guid"]))
    # plain text: the card's words are this computer's own, the ask a crewmate's
    sheets.ask_text("Send a tip", f"On “{text or 'this card'}”.{q}\n\nOne line; {first} sees it when the card comes up.",
                    go, yes="Send")


def hide_tipped(uid, guid):
    """Main thread. 3.0.1: a tip sent takes the flag down; my board stops
    showing it now, not at the next refresh. No request."""
    for e in _state["entries"] or []:
        if e["user_id"] == uid:
            e["tricky"] = without_flags(e.get("tricky"), {guid})
    app.swap(cfg())


def milestone_cheer(uid):
    from .social import _send_cheer, cheer_allowed
    m = next((m for m in _state["milestones"] if m[0] == uid), None)
    if m is None:
        return
    emoji = cheer_allowed("\U0001F4AF" if m[2] < 365 else "\U0001F389")
    if emoji:
        _send_cheer(uid, m[1], emoji, big=True)  # 3.8.2: the closet's balloon
    dismiss_milestone(uid)


def dismiss_milestone(uid):
    _state["milestones"] = [m for m in _state["milestones"] if m[0] != uid]
    app.swap(cfg())


# ---- studying now ----

def is_live():
    return board.live_now(client().session.get("live_until"))


LIVE_KEY = "show_studying"  # Privacy's Show when I'm studying (an account key, on unless turned off)
LIVE_TOLD = "live_told"     # the board's line about it, put away
LIVE_NOTE = "New: your crew sees a dot by your name while you\u2019re studying."


def live_on(c):
    """Whether my dot shows by itself: the switch on, and my numbers shared
    (never for someone paused or in just-show-up mode)."""
    return c.get(LIVE_KEY, True) is not False and not c.get("paused") and not c.get("show_up")


def live_note_due(c):
    """The board's line about the dot is still to be put away."""
    return bool(live_on(c) and not c.get(LIVE_TOLD))


def live_told():
    c = cfg()
    if not c.get(LIVE_TOLD):
        c[LIVE_TOLD] = True
        save_cfg(c)
        try:
            from . import account
            account.push(c)
        except Exception:
            pass


def auto_live(c, last_ms, day="", now=None):
    """3.9.10 (Sam: "get rid of I'm studying and just have it automatically
    pushed when someone has synced reviews within the last hour"): my dot for
    LIVE_MINUTES after my last review, set as a sync is made ready, so it
    rides my week as the button's hour did. It never shortens a room's or a
    fifteen's hour; switched off (or paused, or just showing up) the hour
    this set goes, and only that one. The first time in a day I'm studying
    while a crewmate is counts for the squad's square (lv). Main thread.
    True when the session changed."""
    cl = client()
    s = cl.session
    now = now or datetime.datetime.now(datetime.timezone.utc)
    want = ""
    if live_on(c) and last_ms:
        until = datetime.datetime.fromtimestamp(int(last_ms) / 1000, datetime.timezone.utc) + datetime.timedelta(minutes=LIVE_MINUTES)
        if until > now:
            want = until.strftime("%Y-%m-%dT%H:%M:%SZ")
    cur, mine, changed = str(s.get("live_until") or ""), str(s.get("live_auto") or ""), False
    if want:
        if want > cur:
            s["live_until"] = s["live_auto"] = want
            changed = True
        if day and s.get("live_lv") != day and any(
                not e.get("you") and board.live_now(e.get("live_until")) for e in _state["entries"] or []):
            s["live_lv"] = day
            changed = True
            from .bingo_flow import bump
            bump("lv")  # 3.6's square, by what it means now: studied while a crewmate was studying
    elif mine:
        if cur == mine:
            s.pop("live_until", None)
        s.pop("live_auto", None)
        changed = True
    if changed:
        cl._save_session()
    return changed


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


def unask(index):
    """3.5.0: Take back, on the Decks tab's own ask (by its place in my
    flags: a guid can't ride a board command). Main thread."""
    cl = client()
    flags = clean_tricky(cl.session.get("tricky"), _today())
    if not 0 <= index < len(flags):
        return
    del flags[index]
    cl.session["tricky"] = flags
    cl._save_session()
    app.swap(cfg())
    app.sync(light=True, fetch=False)
    tooltip("Taken back.")


def reviewer_menu(reviewer, menu):
    """gui_hooks.reviewer_will_show_context_menu: the More menu and a
    right-click on the card both get the flag."""
    card = getattr(reviewer, "card", None)
    if card is None or not client().signed_in:
        return
    flagged = any(f["guid"] == card.note().guid
                  for f in clean_tricky(client().session.get("tricky"), _today()))
    # 3.5.0, K2: one way to ask, on any card, a line optional
    if flagged:
        action = menu.addAction("Due Crew: take back my ask")
        action.triggered.connect(lambda: flag_card(card))
    else:
        from . import cards as crew_cards
        action = menu.addAction("Due Crew: ask my crew about this…")
        action.triggered.connect(lambda: crew_cards.ask(card))
    # 3.9.11: my own hook on this card (hooks.py), on any card
    from . import hooks
    hk = menu.addAction("Due Crew: your tip…" if hooks.get(card.note().guid) else "Due Crew: add a tip…")
    hk.triggered.connect(lambda: __import__("due_crew.cards", fromlist=["hook_edit"]).hook_edit(card))
    # 3.7.3: a card in a plan whose team I'm on can go to the team too
    from . import team_flow
    if team_flow.plan_for_card(card):
        team = menu.addAction("Due Crew: ask the squad about this…")
        team.triggered.connect(lambda: team_flow.ask_card(card))


_NOTES = {"key": None, "rows": {}}


def notes_by_guid(col, guids):
    """{guid: flds} for these guids. Anki has no index on notes.guid, so
    this is a scan of every note: kept until the collection changes, so a
    sort click or a redraw of the Decks tab doesn't scan again. Main thread."""
    guids = sorted({str(g) for g in guids})
    if not guids:
        return {}
    key = (id(col), getattr(col, "mod", None), tuple(guids))
    if key[1] is None or _NOTES["key"] != key:
        _NOTES["rows"] = dict(col.db.all(
            f"SELECT guid, flds FROM notes WHERE guid IN ({','.join('?' * len(guids))})", *guids))
        _NOTES["key"] = key
    return dict(_NOTES["rows"])


def tricky_view():
    """Flags from my crew on notes I also have: [{uid, name, index, text,
    deck}]. One local query over their guids; a flag on a card I don't
    have is someone else's deck, and stays out of view. Since 3.0 a flag
    carries no text: it's read here, from my own copy of the note."""
    flags = [(e, i, t) for e in _state["entries"] or [] if not e["you"]
             for i, t in enumerate(e.get("tricky") or [])]
    if not flags or not mw.col:
        return []
    guids = sorted({t["guid"] for _e, _i, t in flags})
    try:
        rows = notes_by_guid(mw.col, guids)
    except Exception:
        return []
    text = {g: _plain(str(flds).split("\x1f", 1)[0]) for g, flds in rows.items()}
    try:
        from .cards import i_know
        known = i_know(mw.col, [t["guid"] for _e, _i, t in flags if t.get("q")])  # 3.2: an ask
    except Exception:
        known = set()
    out = [{"uid": e["user_id"], "name": e["name"], "index": i,
            "text": text[t["guid"]], "deck": t["deck"], "q": t.get("q") or "",
            "known": t["guid"] in known}
           for e, i, t in flags if t["guid"] in text]
    out.sort(key=lambda v: not v["known"])  # asks about cards I know first
    return out


def my_asks_view():
    """3.5.0, K3: my asks, for the Decks tab: [{text, deck, state, who}].
    Open ones (still on my week) say who has the card down when I know
    it; answered ones (a tip kept in the last TIP_DAYS) say who answered.
    The text is my own copy's; nothing here makes a request."""
    cl = client()
    names = {e["user_id"]: str(e.get("name") or "?").split(" ")[0]
             for e in _state["entries"] or [] if not e.get("you")}
    info = cl.session.get("cards") or {}
    out = []
    for i, f in enumerate(clean_tricky(cl.session.get("tricky"), _today())):
        who = [names[u] for u in (info.get(f["guid"]) or {}).get("knows") or [] if u in names]
        out.append({"guid": f["guid"], "text": f.get("text") or "", "deck": f.get("deck") or "",
                    "state": "open", "who": who, "index": i})
    open_guids = {a["guid"] for a in out}
    tips = _wrap_data().get("tips") or {}
    answered = [(g, [t for t in ts if isinstance(t, dict)]) for g, ts in tips.items()
                if isinstance(ts, list) and ts and g not in open_guids][-50:]  # the newest; one bounded query
    if answered and mw.col:
        guids = [g for g, _ts in answered]
        try:
            rows = notes_by_guid(mw.col, guids)
        except Exception:
            rows = {}
        for g, ts in answered:
            if g in rows:
                out.append({"guid": g, "text": _plain(str(rows[g]).split("\x1f", 1)[0]), "deck": "",
                            "state": "answered", "who": [str(t.get("name") or "?").split(" ")[0] for t in ts]})
    return out[:8]
