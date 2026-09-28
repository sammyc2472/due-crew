"""3.2, who knows this one: the cards I have down and the ones I'm stuck
on (in the decks I share), the chip in the reviewer's bottom bar, Ask,
and tips that stay on their card. Main-thread rules as in __init__.

Nothing here adds a request on a normal day. The cards I know go out with
the sync as changes (known.json keeps what the server has); the cards I'm
stuck on go with each sync, and the answer (which mutual friends have each
down, and their tips) comes back in the same request and is kept in the
session. Cards are note guids; never their text. "This helped" is one
request, on a click.

A card is known when it's a review card at 21 days or more with no Again in
the last 30 days. I'm stuck on one I've lapsed on twice or more, or pressed
Again on today. The chip shows only on the answer side of a stuck card, and
only when someone knows it or left a tip; on every other card, nothing.
Nothing is drawn inside the card.
"""

import json

from aqt import mw
from aqt.utils import tooltip

from . import app
from .app import _bg, _state, client
from .backend.shapes import TRICKY_MAX, clean_note, clean_tricky

KNOWN_IVL = 21
CLEAN_DAYS = 30
STUCK_LAPSES = 2
STUCK_MAX = 300
LOG_FULL = 365  # 3.5: a year once (the site's log shows a year), then LOG_RECENT
LOG_RECENT = 8


def _tree(col, dids):
    out = set()
    for did in dids or []:
        try:
            if col.decks.get(int(did), default=False):
                out.update(int(d) for d in col.decks.deck_and_child_ids(int(did)))
        except Exception:
            continue
    return out


def known_and_stuck(col, dids, day_cutoff, with_known=True):
    """(known guids, stuck guids) in these decks and their subdecks. Two
    queries, each reading the review log's recent range once (not once a
    card); `day_cutoff` is Anki's next rollover, in seconds. with_known
    False (a light sync, which doesn't send them) skips the first."""
    tree = _tree(col, dids)
    if not tree:
        return set(), []
    ids = ",".join(str(d) for d in sorted(tree))
    in_tree = f"(c.did IN ({ids}) OR c.odid IN ({ids}))"
    clean_since = (day_cutoff - CLEAN_DAYS * 86400) * 1000
    today = (day_cutoff - 86400) * 1000
    known = set(col.db.list(
        f"SELECT DISTINCT n.guid FROM cards c JOIN notes n ON n.id = c.nid WHERE {in_tree} "
        f"AND c.type = 2 AND c.queue = 2 AND c.ivl >= {KNOWN_IVL} "
        "AND c.id NOT IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)",
        clean_since)) if with_known else set()
    rows = col.db.all(
        f"SELECT n.guid, MAX(c.lapses) FROM cards c JOIN notes n ON n.id = c.nid WHERE {in_tree} "
        f"AND (c.lapses >= {STUCK_LAPSES} OR c.id IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)) "
        "GROUP BY n.guid ORDER BY MAX(c.lapses) DESC, n.guid LIMIT ?",
        today, STUCK_MAX)
    stuck = [str(g) for g, _l in rows]
    return {str(g) for g in known} - set(stuck), stuck


def log_days(col, days):
    """{day: [minutes, reviews, new, retention|None]} for the studied days
    among the last `days`: my log, which only I read (on the site)."""
    from .stats.queries import StatsQueries
    q = StatsQueries(col)
    totals = q.daily_totals(days)
    fresh = q.new_cards_by_day(days)
    out = {}
    for label, (n, time_ms, correct, graded) in totals.items():
        if not n:
            continue
        out[label] = [min(1440, int(round(time_ms / 60000))), int(n), int(fresh.get(label, 0)),
                      round(correct / graded * 100, 1) if graded else None]
    return out


def for_sync(c, light=False):
    """What a sync carries for 3.2, as push()'s keyword arguments: the cards
    I'm stuck on (every sync), and on a full sync the cards I know and my
    log (the first time a year, then the last 8). Main thread."""
    cl = client()
    if not mw.col or not cl.signed_in:
        return None
    out = {}
    dids = c.get("shared_decks") or []
    if dids:
        known, stuck = known_and_stuck(mw.col, dids, int(mw.col.sched.day_cutoff), with_known=not light)
        out["stuck"] = stuck
        if not light:
            out["known"] = known
    if not light:
        days = LOG_RECENT if cl.session.get("log_year") == cl.user_id else LOG_FULL
        log = log_days(mw.col, days)
        if log:
            out["log"] = log
    return out


# ---- the reviewer ----

def names_by_uid():
    return {e["user_id"]: (str(e.get("name") or "?"), str(e.get("emoji") or ""))
            for e in _state["entries"] or [] if not e.get("you")}


def chip_view(info, local_tips, names, asks=()):
    """What the chip says for one card, or None. info: the session's entry
    for the card; local_tips: [(name, note)] kept from 2.10's flag tips;
    asks: [(uid, index)] crewmates asking about this card (on their week)."""
    asks = [(u, i) for u, i in asks if u in names]
    if asks:
        name, emoji = names[asks[0][0]]
        return {"kind": "asked", "text": f"{emoji + ' ' if emoji else ''}{name.split(' ')[0]} asked about this",
                "ask": False, "cmd": f"knowsreply:{asks[0][0]}:{int(asks[0][1])}", "act": "Tip"}
    knows = [u for u in (info or {}).get("knows") or [] if u in names]
    tips = [t for t in (info or {}).get("tips") or [] if t.get("from") in names]
    if tips or local_tips:
        first = names[tips[0]["from"]][0] if tips else local_tips[0][0]
        more = len(tips) + len(local_tips) - 1
        who = first.split(" ")[0]
        return {"kind": "tip", "text": f"\U0001F4A1 {who}’s tip" + (f" and {more} more" if more > 0 else ""),
                "cmd": "knowstip"}
    if knows:
        name, emoji = names[knows[0]]
        who = name.split(" ")[0]
        more = len(knows) - 1
        return {"kind": "knows", "text": f"{emoji + ' ' if emoji else ''}{who}"
                + (f" and {more} more know this" if more > 0 else " knows this"), "ask": True,
                "cmd": "knowsask", "act": "Ask"}
    return None


_CHIP_JS = """(function () {
  var old = document.getElementById('dc-knows'); if (old) { old.remove(); }
  var D = __DATA__; if (!D) { return; }
  var edit = document.querySelector('button[onclick*="edit"]');
  var cell = edit ? edit.parentNode : document.body;
  var s = document.createElement('span'); s.id = 'dc-knows';
  s.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding:2px 10px;border-radius:99px;' +
    'border:1px solid ' + D.accent + ';font:11.5px -apple-system,Segoe UI,sans-serif;white-space:nowrap;vertical-align:middle;cursor:pointer;';
  var t = document.createElement('span'); t.textContent = D.text; s.appendChild(t);
  if (D.act) { var a = document.createElement('b'); a.textContent = D.act; a.style.color = D.accent; s.appendChild(a); }
  s.onclick = function () { try { pycmd('duecrew:' + D.cmd); } catch (e) {} };
  cell.appendChild(s);
})();"""


def chip_js(data):
    return _CHIP_JS.replace("__DATA__", json.dumps(data))


def _bottom():
    rv = getattr(mw, "reviewer", None)
    return getattr(getattr(rv, "bottom", None), "web", None) if mw.state == "review" else None


def _accent():
    try:
        from .rooms import _accent_pair
        return _accent_pair()[0]
    except Exception:
        return "#2e7d32"


def on_answer(card):
    """reviewer_did_show_answer: the chip, when this card is one I'm stuck on
    and someone knows it or left a tip."""
    web = _bottom()
    if web is None or not client().signed_in:
        return
    try:
        guid = card.note().guid
        from .together import tips_for
        asks = [(e["user_id"], i) for e in _state["entries"] or [] if not e.get("you")
                for i, t in enumerate(e.get("tricky") or []) if t.get("guid") == guid and t.get("q")]
        view = chip_view((client().session.get("cards") or {}).get(guid), tips_for(guid), names_by_uid(), asks)
    except Exception:
        view = None
    if view:
        view["accent"] = _accent()
    try:
        web.eval(chip_js(view))
    except Exception:
        pass


def on_question(card):
    web = _bottom()
    if web is not None:
        try:
            web.eval(chip_js(None))
        except Exception:
            pass


def _card():
    return getattr(getattr(mw, "reviewer", None), "card", None) if mw.state == "review" else None


def ask():
    """Ask the crewmates who have this card down: a flag with my line. It
    rides my week as the card's guid and the line; they read the card from
    their own copy. The first tip takes it down."""
    card = _card()
    if card is None:
        return
    guid = card.note().guid
    names = names_by_uid()
    info = (client().session.get("cards") or {}).get(guid) or {}
    who = [names[u][0].split(" ")[0] for u in info.get("knows") or [] if u in names]
    from .ui import ask_text
    listed = ", ".join(who[:3]) + (f" and {len(who) - 3} more" if len(who) > 3 else "")
    line, ok = ask_text(mw, "Ask about this card",
                        f"Your crew sees it, and {listed or 'whoever knows it'} will know it's for them. "
                        "They see the card from their own deck. One line (optional).")
    if not ok:
        return
    flag(card, clean_note(line) or "")


def flag(card, q):
    from .together import _plain, _today
    cl = client()
    note = card.note()
    flags = [f for f in clean_tricky(cl.session.get("tricky"), _today()) if f["guid"] != note.guid]
    deck = mw.col.decks.name(card.odid or card.did).split("::")[-1]
    entry = {"guid": note.guid, "text": _plain(note.fields[0] if note.fields else ""),
             "deck": clean_note(deck, 40), "at": _today()}
    if q:
        entry["q"] = q
    flags.append(entry)
    cl.session["tricky"] = flags[-TRICKY_MAX:]
    cl._save_session()
    app.sync(light=True, fetch=False)
    tooltip("Asked. The first tip shows here when the card comes up.")


def show_tips():
    """The chip's tips, above the bar: each with This helped."""
    card = _card()
    if card is None:
        return
    guid = card.note().guid
    names = names_by_uid()
    info = (client().session.get("cards") or {}).get(guid) or {}
    from aqt.qt import QCursor, QMenu
    from .together import tips_for
    menu = QMenu(mw)
    for t in info.get("tips") or []:
        if t.get("from") not in names:
            continue
        who = names[t["from"]][0].split(" ")[0]
        head = menu.addAction(f"{who}: {t['text']}")
        head.setEnabled(False)
        label = "✓ This helped" if t.get("helped") else "This helped"
        act = menu.addAction(f"    {label}")
        act.triggered.connect(lambda _c=False, t=t: helped(guid, t["from"], not t.get("helped")))
    for name, note in tips_for(guid):
        a = menu.addAction(f"{name.split(' ')[0]}: {note}")
        a.setEnabled(False)
    if not menu.actions():
        return
    menu.exec(QCursor.pos())


def helped(guid, from_uid, on=True):
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
        elif on:
            tooltip("Thanks. The tips that help most show first.")
    _bg(lambda: cl.tip_helped(guid, from_uid, on), done)


def on_message(cmd, parts=()):
    if cmd == "knowsask":
        ask()
    elif cmd == "knowstip":
        show_tips()
    elif cmd == "knowsreply" and len(parts) > 3:
        from .together import send_tip
        send_tip(parts[2], parts[3])
    else:
        return False
    return True


# ---- the knower's side: asks on the board ----

def i_know(col, guids):
    """The guids among these whose card I have down (as above)."""
    guids = sorted({str(g) for g in guids})
    if not guids:
        return set()
    cutoff = int(col.sched.day_cutoff)
    return set(col.db.list(
        f"SELECT DISTINCT n.guid FROM cards c JOIN notes n ON n.id = c.nid WHERE n.guid IN ({','.join('?' * len(guids))}) "
        f"AND c.type = 2 AND c.ivl >= {KNOWN_IVL} AND c.id NOT IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)",
        *guids, (cutoff - CLEAN_DAYS * 86400) * 1000))
