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
LOG_FULL = 120
LOG_RECENT = 8
LOG_BACK_STEP = 366  # 3.7.1: the history import, a year a sync
LOG_BACK_MAX = 15 * 366  # and no further back than the server keeps


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


def log_days(col, days, skip=0):
    """{day: [minutes, reviews, new, retention|None]} for the studied days
    among the last `days` (the `skip` newest left out): my log, which only
    I read (on the site)."""
    from .stats.queries import StatsQueries
    q = StatsQueries(col)
    totals = q.daily_totals(days, skip)
    fresh = q.new_cards_by_day(days, skip)
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
    log (the first time 120 days, then the last 8). Main thread."""
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
        days = LOG_RECENT if cl.session.get("log_full") == cl.user_id else LOG_FULL
        log = log_days(mw.col, days)
        if log:
            out["log"] = log
        back = history_part(mw.col, cl)
        if back:
            out["log_back"] = back
    return out


def history_part(col, cl):
    """3.7.1, the history import: once the first 120 days have gone, each
    full sync carries one more year of my log, oldest last, until it
    reaches my first review (or LOG_BACK_MAX days). Years with nothing in
    them are passed over here. Returns (days, skip after) or None when
    there's nothing left to bring in. Main thread."""
    if cl.session.get("log_full") != cl.user_id:
        return None
    st = cl.session.get("log_back") if isinstance(cl.session.get("log_back"), dict) else {}
    if st.get("uid") != cl.user_id:
        st = {"uid": cl.user_id, "skip": LOG_FULL}
    if st.get("done"):
        return None
    try:
        first = col.db.scalar("SELECT MIN(id) FROM revlog WHERE ease > 0")
    except Exception:
        return None
    from .stats.queries import StatsQueries
    oldest = 0 if not first else max(0, (StatsQueries(col)._cutoff_s() - int(first) // 1000) // 86400 + 1)
    skip = int(st.get("skip") or LOG_FULL)
    for _ in range(4):  # an empty year costs one query; a few at most per sync
        if skip >= min(oldest, LOG_BACK_MAX):
            cl.session["log_back"] = dict(st, skip=skip, done=True)
            cl._save_session()
            return None
        days = log_days(col, LOG_BACK_STEP, skip)
        skip += LOG_BACK_STEP
        if days:
            return days, skip
        cl.session["log_back"] = dict(st, skip=skip)
    cl._save_session()
    return None


# ---- the reviewer ----

def names_by_uid():
    return {e["user_id"]: (str(e.get("name") or "?"), str(e.get("emoji") or ""))
            for e in _state["entries"] or [] if not e.get("you")}


def tip_list(info, local_tips, names):
    """The tips on one card, each person once: [{from, name, text, helped}].
    The server's first (on a card I'm stuck on, from crewmates I can name),
    then the ones kept here as they arrived (2.10 tuples or 3.5.0 dicts)."""
    out, seen = [], set()
    for t in (info or {}).get("tips") or []:
        u = t.get("from")
        if u in names and u not in seen:
            seen.add(u)
            out.append({"from": u, "name": names[u][0], "text": str(t.get("text") or ""),
                        "helped": bool(t.get("helped"))})
    for t in local_tips or []:
        if isinstance(t, (tuple, list)):
            t = {"name": t[0], "note": t[1]}
        u = t.get("from") or ""
        if u and u in seen:
            continue
        seen.add(u)
        out.append({"from": u, "name": str(t.get("name") or "?"), "text": str(t.get("note") or ""),
                    "helped": bool(t.get("helped"))})
    return out


def chip_view(info, local_tips, names, asks=()):
    """What the chip says for one card, or None. info: the session's entry
    for the card; local_tips: the tips kept here for it (together.local_tips);
    asks: [(uid, index)] crewmates asking about this card (on their week).
    3.5.0, K1: a tip shows its own words in the bar, with This helped."""
    asks = [(u, i) for u, i in asks if u in names]
    if asks:
        name, emoji = names[asks[0][0]]
        return {"kind": "asked", "text": f"{emoji + ' ' if emoji else ''}{name.split(' ')[0]} asked about this",
                "ask": False, "cmd": f"knowsreply:{asks[0][0]}:{int(asks[0][1])}", "act": "Tip"}
    knows = [u for u in (info or {}).get("knows") or [] if u in names]
    tips = tip_list(info, local_tips, names)
    if tips:
        first = tips[0]
        view = {"kind": "tip", "text": f"\U0001F4A1 {first['name'].split(' ')[0]}: {first['text']}",
                "title": first["text"], "cmd": "knowstip"}
        if len(tips) > 1:
            view["more"] = len(tips) - 1
        if first["from"]:
            view["act"] = "\u2713 Helped" if first["helped"] else "This helped"
            view["actcmd"] = f"knowshelped:{first['from']}"
        return view
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
  if (D.title) { s.title = D.title; t.style.cssText = 'display:inline-block;max-width:38vw;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom;'; }
  if (D.more) { var m = document.createElement('span'); m.textContent = '+' + D.more + ' more'; m.style.opacity = '0.7'; s.appendChild(m); }
  if (D.act) {
    var a = document.createElement('b'); a.textContent = D.act; a.style.color = D.accent; s.appendChild(a);
    if (D.actcmd) { a.onclick = function (e) { e.stopPropagation(); try { pycmd('duecrew:' + D.actcmd); } catch (x) {} }; }
  }
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
        from .together import local_tips
        asks = [(e["user_id"], i) for e in _state["entries"] or [] if not e.get("you")
                for i, t in enumerate(e.get("tricky") or []) if t.get("guid") == guid and t.get("q")]
        view = chip_view((client().session.get("cards") or {}).get(guid), local_tips(guid), names_by_uid(), asks)
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


def ask(card=None):
    """3.5.0, K2: the one way to ask, from the chip or the reviewer's menu,
    on any card: a flag with my line (optional). It rides my week as the
    card's guid and the line; crewmates with the card read it from their
    own copy. The first tip takes it down."""
    card = card or _card()
    if card is None:
        return
    guid = card.note().guid
    names = names_by_uid()
    info = (client().session.get("cards") or {}).get(guid) or {}
    who = [names[u][0].split(" ")[0] for u in info.get("knows") or [] if u in names]
    from .ui import ask_text
    if who:
        listed = (", ".join(who[:-1]) + " and " + who[-1]) if 1 < len(who) <= 3 else \
            (", ".join(who[:3]) + f" and {len(who) - 3} more" if len(who) > 3 else who[0])
        lead = f"{listed} {'has' if len(who) == 1 else 'have'} it down. "
    else:
        lead = ""
    line, ok = ask_text(mw, "Ask your crew about this card",
                        lead + "Your crew sees it on their copy of the card. One line, optional.")
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
    from .bingo_flow import bump
    bump("aq")  # 3.6
    app.sync(light=True, fetch=False)
    tooltip("Asked. Tips show here when the card comes up.")


def _tips_here(guid):
    from .together import local_tips
    return tip_list((client().session.get("cards") or {}).get(guid), local_tips(guid), names_by_uid())


def show_tips():
    """The chip's tips, all of them, above the bar: each with This helped."""
    card = _card()
    if card is None:
        return
    guid = card.note().guid
    from aqt.qt import QCursor, QMenu
    menu = QMenu(mw)
    for t in _tips_here(guid):
        head = menu.addAction(f"{t['name'].split(' ')[0]}: {t['text']}")
        head.setEnabled(False)
        if t["from"]:
            act = menu.addAction("    \u2713 This helped" if t["helped"] else "    This helped")
            act.triggered.connect(lambda _c=False, t=t: helped(guid, t["from"], not t["helped"]))
    if not menu.actions():
        return
    menu.exec(QCursor.pos())


def helped(guid, from_uid, on=True):
    cl = client()

    def done(ok):
        if not ok:
            tooltip("Couldn't reach Due Crew. Check your connection.")
            return
        # remembered here too, so the bar says so at once and next time
        for t in ((cl.session.get("cards") or {}).get(guid) or {}).get("tips") or []:
            if t.get("from") == from_uid:
                t["helped"] = on
        from .together import mark_helped
        mark_helped(guid, from_uid, on)
        if on:
            tooltip("Thanks. The tips that help most show first.")
        card = _card()
        if card is not None and card.note().guid == guid and getattr(mw.reviewer, "state", "") == "answer":
            on_answer(card)
    _bg(lambda: cl.tip_helped(guid, from_uid, on), done)


def helped_toggle(from_uid):
    """The bar's This helped (K1): on the tip it shows, for the card up now."""
    card = _card()
    if card is None:
        return
    guid = card.note().guid
    tip = next((t for t in _tips_here(guid) if t["from"] == from_uid), None)
    if tip is not None:
        helped(guid, from_uid, not tip["helped"])


def on_message(cmd, parts=()):
    if cmd == "knowsask":
        ask()
    elif cmd == "knowstip":
        show_tips()
    elif cmd == "knowshelped" and len(parts) > 2:
        helped_toggle(parts[2])
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
