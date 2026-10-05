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
        f"AND c.type = 2 AND c.queue != -1 AND c.ivl >= {KNOWN_IVL} "  # buried today is still known
        "AND c.id NOT IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)",
        clean_since)) if with_known else set()
    rows = col.db.all(
        f"SELECT n.guid, MAX(c.lapses) FROM cards c JOIN notes n ON n.id = c.nid WHERE {in_tree} "
        f"AND (c.lapses >= {STUCK_LAPSES} OR c.id IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)) "
        "GROUP BY n.guid ORDER BY MAX(c.lapses) DESC, n.guid LIMIT ?",
        today, STUCK_MAX)
    stuck = [str(g) for g, _l in rows]
    return {str(g) for g in known} - set(stuck), stuck


def log_today(col):
    from .stats.queries import StatsQueries
    return StatsQueries(col).day_label(0)


def _days_since(day, today):
    """Whole days from `day` to `today` (labels); 0 when unknown."""
    import datetime
    try:
        return max(0, (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(str(day))).days)
    except (TypeError, ValueError):
        return 0


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
        today = log_today(mw.col)
        if days == LOG_RECENT:
            # every day since the log last went up (two weeks on a phone
            # leave no hole), never more than the first window
            days = max(LOG_RECENT, min(LOG_FULL, _days_since(cl.session.get("log_sent_day"), today) + 1))
        cl.session["log_try_day"] = today
        log = log_days(mw.col, days)
        if log:
            out["log"] = log
        if days == LOG_FULL:
            out["log_window"] = "full"  # however few days it held
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
  if (Array.isArray(D.accent)) {
    var night = /night/i.test(document.body.className) || document.documentElement.classList.contains('night-mode');
    D.accent = D.accent[night ? 1 : 0];
  }
  var edit = document.querySelector('button[onclick*="edit"]');
  var cell = edit ? edit.parentNode : document.body;
  var s = document.createElement('span'); s.id = 'dc-knows';
  s.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding:2px 10px;border-radius:99px;' +
    'border:1px solid ' + D.accent + ';font:11.5px -apple-system,Segoe UI,sans-serif;white-space:nowrap;vertical-align:middle;cursor:pointer;';
  var t = document.createElement('span'); t.id = 'dc-knows-t'; t.textContent = D.text; s.appendChild(t);
  if (D.title) { s.title = D.title; t.style.cssText = 'display:inline-block;max-width:24vw;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom;'; }
  if (D.more) { var m = document.createElement('span'); m.textContent = '+' + D.more + ' more'; m.style.opacity = '0.7'; s.appendChild(m); }
  if (D.act) {
    var a = document.createElement('b'); a.textContent = D.act; a.style.color = D.accent; s.appendChild(a);
    if (D.actcmd) { a.onclick = function (e) { e.stopPropagation(); try { pycmd('duecrew:' + D.actcmd); } catch (x) {} }; }
  }
  s.onclick = function () { try { pycmd('duecrew:' + D.cmd); } catch (e) {} };
  cell.appendChild(s);
})();"""


def chip_js(data):
    from .room_model import BAR_BALANCE
    return _CHIP_JS.replace("__DATA__", json.dumps(data)) + BAR_BALANCE


# The chip as a small card above the bar, bottom right of the review
# screen (mock "Ask chip", B). It shows only while the card's own text and
# pictures leave that corner free (looked at again as pictures load, and on
# scroll and resize); otherwise, or the moment it isn't, the chip goes back
# beside Edit (`knowsbar`). Its clicks come from the review screen, where a
# card's script runs too, so they're keyed (room_model.CARD_PAGE_CMDS) and
# This helped from here asks first.
_FLOAT_JS = """(function () {
  var old = document.getElementById('dc-knows-card'); if (old) { old.remove(); }
  if (window.dcKnowsOff) { window.dcKnowsOff(); window.dcKnowsOff = null; }
  var D = __DATA__; if (!D) { return false; }
  var KEY = __KEY__, gone = false;
  function send(cmd) { try { pycmd('duecrew:' + cmd + '|' + KEY); } catch (e) {} }
  var night = /night/i.test(document.body.className) || document.documentElement.classList.contains('night-mode');
  var acc = night ? D.accent[1] : D.accent[0];
  var c = night ? {bg: '#2c2c2c', ink: '#e8e8e8', mut: '#9c9c9c', line: '#3d403b'} : {bg: '#ffffff', ink: '#222222', mut: '#777777', line: '#e2e2da'};
  function el(tag, css, text) { var e = document.createElement(tag); e.style.cssText = css; if (text != null) { e.textContent = text; } return e; }
  var box = el('div', 'position:fixed;right:12px;bottom:12px;max-width:260px;box-sizing:border-box;display:grid;gap:6px;padding:9px 12px;' +
    'border:1px solid ' + c.line + ';border-radius:12px;background:' + c.bg + ';color:' + c.ink + ';box-shadow:0 6px 18px rgba(0,0,0,.22);' +
    'font:12.5px/1.35 -apple-system,Segoe UI,sans-serif;text-align:left;z-index:60;');
  box.id = 'dc-knows-card';
  var head = el('div', 'font-weight:600;cursor:pointer;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;', D.text);
  if (D.title) { head.title = D.title; }
  head.onclick = function () { send(D.cmd); };
  var acts = el('div', 'display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;');
  function link(text, color, bold, fn) {
    var a = el('span', 'cursor:pointer;color:' + color + ';' + (bold ? 'font-weight:700;' : ''), text);
    a.onclick = function (e) { e.stopPropagation(); fn(); }; acts.appendChild(a); return a;
  }
  if (D.act) { link(D.act, acc, true, function () { send(D.actcmd || D.cmd); }); }
  if (D.more) { link('+' + D.more + ' more', c.mut, false, function () { send('knowstip'); }); }
  link('Not now', c.mut, false, function () { off(); });
  box.appendChild(head); box.appendChild(acts);
  document.body.appendChild(box);
  function hit(r, b) { return r.width > 0 && r.height > 0 && r.left < b.right + 8 && r.right > b.left - 8 && r.top < b.bottom + 8 && r.bottom > b.top - 8; }
  function free() {
    var b = box.getBoundingClientRect(), qa = document.getElementById('qa') || document.body;
    var w = document.createTreeWalker(qa, NodeFilter.SHOW_TEXT), n, g = document.createRange();
    while ((n = w.nextNode())) {
      if (!/\\S/.test(n.nodeValue) || box.contains(n)) { continue; }
      g.selectNodeContents(n);
      var rs = g.getClientRects();
      for (var i = 0; i < rs.length; i++) { if (hit(rs[i], b)) { return false; } }
    }
    var m = qa.querySelectorAll('img,table,canvas,svg,video,iframe,input,textarea,select,button');
    for (var j = 0; j < m.length; j++) { if (!box.contains(m[j]) && hit(m[j].getBoundingClientRect(), b)) { return false; } }
    return true;
  }
  function off() {
    if (gone) { return; }
    gone = true; box.remove();
    window.removeEventListener('scroll', check, true); window.removeEventListener('resize', check);
    document.removeEventListener('load', check, true);
    if (ro) { ro.disconnect(); }
    clearTimeout(later);
  }
  function check() { if (!gone && !free()) { off(); send('knowsbar'); } }
  window.addEventListener('scroll', check, true); window.addEventListener('resize', check);
  document.addEventListener('load', check, true);  // a picture that loads late
  // Anki puts the answer in a moment later (pictures preloaded, MathJax
  // typeset): look again when the card's area changes size, and once more
  var qa = document.getElementById('qa'), ro = null, later = setTimeout(check, 600);
  if (qa && window.ResizeObserver) { ro = new ResizeObserver(check); ro.observe(qa); }
  window.dcKnowsOff = off;
  if (!free()) { off(); return false; }
  return true;
})();"""


def float_js(data):
    from .room_model import CMD_KEY
    return _FLOAT_JS.replace("__KEY__", json.dumps(CMD_KEY)).replace("__DATA__", json.dumps(data))


_LAST = {"n": 0, "view": None}


def _review_web():
    rv = getattr(mw, "reviewer", None)
    return getattr(rv, "web", None) if mw.state == "review" else None


def _show(view):
    """The card above the bar when the corner's free, else the bar chip."""
    _LAST["n"] += 1
    n, _LAST["view"] = _LAST["n"], view
    bar, page = _bottom(), _review_web()

    def to_bar(shown):
        if n != _LAST["n"] or bar is None:
            return  # a newer card is up
        try:
            bar.eval(chip_js(None if shown else view))
        except Exception:
            pass
    if view and page is not None:
        try:
            page.evalWithCallback(float_js(view), to_bar)
            return
        except Exception:
            pass
    if not view and page is not None:
        try:
            page.eval(float_js(None))  # nothing to show now: the card above the bar goes too
        except Exception:
            pass
    to_bar(False)


def to_bar():
    """knowsbar: the corner stopped being free (a picture loaded, a scroll)."""
    bar = _bottom()
    if bar is not None and _LAST["view"]:
        try:
            bar.eval(chip_js(_LAST["view"]))
        except Exception:
            pass


def _bottom():
    rv = getattr(mw, "reviewer", None)
    return getattr(getattr(rv, "bottom", None), "web", None) if mw.state == "review" else None


def _accent():
    """[light, dark]: the bar chip wears the first, the card picks by night mode."""
    try:
        from .rooms import _accent_pair
        return list(_accent_pair())
    except Exception:
        return ["#2e7d32", "#7cc47f"]


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
    _show(view)


def on_question(card):
    _LAST["n"] += 1
    _LAST["view"] = None
    for web, js in ((_bottom(), chip_js(None)), (_review_web(), float_js(None))):
        if web is not None:
            try:
                web.eval(js)
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


def _tip_from(from_uid):
    card = _card()
    if card is None:
        return None
    return next((t for t in _tips_here(card.note().guid) if t["from"] == from_uid), None)


def helped_toggle(from_uid):
    """The bar's This helped (K1): on the tip it shows, for the card up now."""
    card = _card()
    if card is None:
        return
    guid = card.note().guid
    tip = next((t for t in _tips_here(guid) if t["from"] == from_uid), None)
    if tip is not None:
        helped(guid, from_uid, not tip["helped"])


def on_message(cmd, parts=(), from_card_page=False):
    if cmd == "knowsask":
        ask()
    elif cmd == "knowstip":
        show_tips()
    elif cmd == "knowsbar":
        to_bar()
    elif cmd == "knowshelped" and len(parts) > 2:
        if from_card_page:
            # the review screen runs the card's script too: a thanks is sent only on a yes
            from aqt.utils import askUser
            tip = _tip_from(parts[2])
            if tip is None or (not tip["helped"] and not askUser(f"Tell {tip['name'].split(' ')[0]} this tip helped?")):
                return True
        helped_toggle(parts[2])
    elif cmd == "knowsreply" and len(parts) > 3:
        # the ask on the card up now, found again by its guid: the index the
        # chip was drawn with moves once a tip takes a flag down
        card = _card()
        entry = next((e for e in _state["entries"] or [] if e["user_id"] == parts[2]), None)
        if card is None or entry is None:
            return True
        guid = card.note().guid
        idx = next((i for i, t in enumerate(entry.get("tricky") or []) if t.get("guid") == guid and t.get("q")), None)
        if idx is not None:
            from .together import send_tip
            send_tip(parts[2], idx)
    else:
        return False
    return True


# ---- the knower's side: asks on the board ----

_KNOW = {"key": None, "out": set()}


def i_know(col, guids):
    """The guids among these whose card I have down (as above)."""
    guids = sorted({str(g) for g in guids})
    if not guids:
        return set()
    cutoff = int(col.sched.day_cutoff)
    # no index on notes.guid: kept until the collection changes (a redraw
    # of the Decks tab asks again with nothing new)
    key = (id(col), getattr(col, "mod", None), cutoff, tuple(guids))
    if key[1] is not None and _KNOW["key"] == key:
        return set(_KNOW["out"])
    _KNOW["out"] = out = set(col.db.list(
        f"SELECT DISTINCT n.guid FROM cards c JOIN notes n ON n.id = c.nid WHERE n.guid IN ({','.join('?' * len(guids))}) "
        f"AND c.type = 2 AND c.ivl >= {KNOWN_IVL} AND c.id NOT IN (SELECT cid FROM revlog WHERE id >= ? AND ease = 1)",
        *guids, (cutoff - CLEAN_DAYS * 86400) * 1000))
    _KNOW["key"] = key
    return set(out)
