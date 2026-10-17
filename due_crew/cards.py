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

3.9.0 (Sam's pick, "Open calls" A): the day's first sync also sends the
cards due today in the decks I share (DUE_MAX of them, the most overdue
first), and the same reply says who knows each. That answer is kept for the
day, beside the stuck cards', so a card I miss for the first time shows the
chip the next time it comes up, without waiting for a sync; it still shows
only once I'm stuck on it (stuck_now).
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
DUE_MAX = 1000  # 3.9.0: the cards due today the day's first sync asks about
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



def due_today(col, dids, skip=()):
    """3.9.0: the guids of the cards due today in these decks and their
    subdecks (reviews due today or before, learning cards), the most
    overdue first, DUE_MAX at most, none of `skip` (the stuck ones, which
    go anyway). One query. A card in a filtered deck counts by its home
    deck's due day."""
    tree = _tree(col, dids)
    if not tree:
        return []
    ids = ",".join(str(d) for d in sorted(tree))
    today = int(col.sched.today)
    home = "CASE WHEN c.odid THEN c.odue ELSE c.due END"
    rows = col.db.all(
        f"SELECT n.guid, MIN(CASE WHEN c.queue = 1 THEN {today} ELSE {home} END) AS d FROM cards c JOIN notes n ON n.id = c.nid "
        f"WHERE (c.did IN ({ids}) OR c.odid IN ({ids})) AND (c.queue = 1 OR (c.queue IN (2, 3) AND {home} <= {today})) "
        "GROUP BY n.guid ORDER BY d, n.guid LIMIT ?", DUE_MAX + len(skip))
    skip = set(skip)
    return [str(g) for g, _d in rows if str(g) not in skip][:DUE_MAX]


def stuck_now(col, card, day_cutoff):
    """3.9.0: am I stuck on this card right now (what the stuck list means:
    lapsed twice or more, or Again on it today)? One indexed look at the
    review log."""
    try:
        if int(card.lapses or 0) >= STUCK_LAPSES:
            return True
        return bool(col.db.scalar("SELECT 1 FROM revlog WHERE cid = ? AND id >= ? AND ease = 1 LIMIT 1",
                                  int(card.id), (int(day_cutoff) - 86400) * 1000))
    except Exception:
        return False

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
    log (the first time 120 days, then the last 8). 3.9.0: the day's first
    sync, light or full, the cards due today as well. Main thread."""
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
        day = log_today(mw.col)
        if cl.session.get("due_day") != day:
            # 3.9.0: once a day, the cards due today too (who knows them comes back with the stuck ones')
            out["due"] = due_today(mw.col, dids, skip=stuck)
            out["due_day"] = day
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


CHIP_PIP = 24  # 3.8.22: a crewmate's Pip on the review screen's chip, its slot the chip's line
PEEK_PIP = 76  # 3.9.0: who knows it, peeking up from the bottom of the card
PEEK_MAX = 3  # 3.9.0 (Sam's "2D"): up to three who know it, side by side


def pips_by_uid(c=None):
    """3.8.22 (Sam: "all the places where there are emojis"): each
    crewmate's Pip for the review screen's chip, where their emoji was:
    {uid: {svg, a: [light, dark]}}, in their colour and look (a mutual
    friend's, which only the crew brings); {} with Pip off. Our own markup:
    a name is only its label, escaped."""
    if not (app.cfg() if c is None else c).get("sev", True):
        return {}
    import html
    from . import sev
    from .board import accent_pair
    return {e["user_id"]: {"svg": sev.slot(sev.svg("idle", rest=True, look=e.get("look"),
                                                   label=html.escape(f'{e.get("name") or "?"}’s Pip', quote=True)), CHIP_PIP),
                           "a": list(accent_pair(e.get("accent")))}
            for e in _state["entries"] or [] if not e.get("you") and e.get("user_id")}


def peek_pip(uid):
    """3.9.0: a crewmate's Pip waving as it peeks in (sev.py's own markup,
    their look; a name only in its label, escaped), or None."""
    import html
    from . import sev
    e = next((e for e in _state["entries"] or [] if e.get("user_id") == uid and not e.get("you")), None)
    if e is None:
        return None
    return sev.slot(sev.svg("peek", look=e.get("look"), label=html.escape(f'{e.get("name") or "?"}’s Pip', quote=True)), PEEK_PIP)

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


def chip_view(info, local_tips, names, asks=(), mine=False, pips=None):
    """What the chip says for one card, or None. info: the session's entry
    for the card; local_tips: the tips kept here for it (together.local_tips);
    asks: [(uid, index[, line])] crewmates asking about this card (on their
    week); mine: I've asked about it myself and no tip has come yet.
    3.5.0, K1: a tip shows its own words in the bar, with This helped.
    `short` is what the bar says when the words don't fit beside Edit.
    pips (3.8.22, pips_by_uid): who asked, or knows it, leads with their Pip
    in place of their emoji. 3.9.0 (Sam's pick, "Open calls" C): who knows
    it also has `peek`, what the corner says (Sam's "2D": no lightbulb, up to
    three Pips side by side): one knower's Pip speaks for them ("I know this
    one", Ask Dre), more say who ("Dre, Mo and Jo know this", "... and 2
    more"), Ask; `uids`, whose Pips (on_answer draws them). With Pip off the
    same bubble without them (Sam: "always this version, just without the
    pip")."""
    pips = pips or {}

    def who_of(uid):
        name, emoji = names[uid]
        return name.split(" ")[0] if uid in pips else f"{emoji + ' ' if emoji else ''}{name.split(' ')[0]}"

    def with_pip(view, uid):
        if uid in pips:
            from .sev import CSS
            view.update(pip=pips[uid], sevcss=CSS)
        return view
    asks = [a for a in asks if a[0] in names]
    if asks:
        who = who_of(asks[0][0])
        q = str(asks[0][2]) if len(asks[0]) > 2 and asks[0][2] else ""
        view = {"kind": "asked", "text": f"{who}: \u201c{q}\u201d" if q else f"{who} asked about this",
                "short": f"{who} asked", "ask": False, "cmd": f"knowsreply:{asks[0][0]}:{int(asks[0][1])}", "act": "Tip"}
        if q:
            view["title"] = q
        return with_pip(view, asks[0][0])
    knows = [u for u in (info or {}).get("knows") or [] if u in names]
    tips = tip_list(info, local_tips, names)
    if tips:
        first = tips[0]
        who = first["name"].split(" ")[0]
        view = {"kind": "tip", "text": f"\U0001F4A1 {who}: {first['text']}", "short": f"\U0001F4A1 {who}'s tip",
                "title": first["text"], "cmd": "knowstip"}
        if len(tips) > 1:
            view["more"] = len(tips) - 1
        if first["from"]:
            view["act"] = "\u2713 Helped" if first["helped"] else "This helped"
            view["actcmd"] = f"knowshelped:{first['from']}"
        return view
    if knows:
        who = who_of(knows[0])
        more = len(knows) - 1
        view = {"kind": "knows", "text": who + (f" and {more} more know this" if more > 0 else " knows this"),
                "short": who + (f" +{more}" if more > 0 else ""), "ask": True,
                "cmd": "knowsask", "act": "Asked" if mine else "Ask"}
        # one knower's Pip speaks for them; more, or no Pip, the words say who (Ask still reaches everyone with the card)
        speaks = knows[0] in pips and more <= 0
        firsts = [names[u][0].split(" ")[0] for u in knows[:PEEK_MAX]]
        rest = len(knows) - len(firsts)
        said = (firsts[0] if len(firsts) == 1 and not rest else ", ".join(firsts[:-1]) + " and " + firsts[-1] if not rest
                else ", ".join(firsts) + f" and {rest} more")
        view["peek"] = {"uids": [u for u in knows[:PEEK_MAX] if u in pips],
                        "head": "I know this one" if speaks else f"{said} know{'s' if len(knows) == 1 else ''} this",
                        "act": "Asked" if mine else (f"Ask {who}" if speaks else "Ask")}
        return with_pip(view, knows[0])
    return None


def remark_view(plans, guid, ord_):
    """3.8.1: what the chip says for an author's note on this card (guid and
    card number), in a plan I follow, or None. It rides the plan: no request.
    Drawn as text (textContent), never as markup; no click of its own."""
    from .plans import card_remarks
    got = card_remarks(plans, guid, ord_)
    if not got:
        return None
    name, text = got[0]
    return {"kind": "remark", "text": f"\U0001F4CC {name}: {text}", "short": f"\U0001F4CC {name}", "title": text}


# 3.8.22: who asked, or knows it, as their Pip (pips_by_uid): sev.py's own
# drawing, a name only in its label (escaped there), so it goes in as
# markup; its motion sheet comes along once
_PIP_JS = """function pip(into, D, night, css) {
    if (!D.pip || !D.pip.svg) { return; }
    if (D.sevcss && !document.getElementById('dc-sev-css-k')) {
      var st = document.createElement('style'); st.id = 'dc-sev-css-k'; st.textContent = D.sevcss;
      (document.head || document.body).appendChild(st);
    }
    var p = document.createElement('span'); p.innerHTML = D.pip.svg;
    p.style.cssText = 'display:inline-flex;flex:none;line-height:0;' + css + '--sv-a:' + D.pip.a[night ? 1 : 0] + ';' +
      (night ? '--sv-line:#3d403b;' : '');
    into.appendChild(p);
  }"""

_CHIP_JS = """(function () {
  var old = document.getElementById('dc-knows'); if (old) { old.remove(); }
  var D = __DATA__; if (!D) { return; }
  var night = /night/i.test(document.body.className) || document.documentElement.classList.contains('night-mode');
  if (Array.isArray(D.accent)) { D.accent = D.accent[night ? 1 : 0]; }
  var edit = document.querySelector('button[onclick*="edit"]');
  var cell = edit ? edit.parentNode : document.body;
  var s = document.createElement('span'); s.id = 'dc-knows';
  s.style.cssText = 'display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding:' + (D.pip ? '3px 10px 3px 6px' : '2px 10px') +
    ';border-radius:99px;border:1px solid ' + D.accent + ';font:11.5px -apple-system,Segoe UI,sans-serif;white-space:nowrap;vertical-align:middle;cursor:pointer;';
  pip(s, D, night, 'margin:8px 2px 0 1px;');  // 3.8.22: who it is, as their Pip (Sam, 16 Oct: room for all of it, head to feet)
  var t = document.createElement('span'); t.id = 'dc-knows-t'; t.textContent = D.text; s.appendChild(t);
  t.setAttribute('data-full', D.text); t.setAttribute('data-short', D.short || D.text);
  if (D.kind === 'tip') { t.setAttribute('data-tip', '1'); }
  s.title = D.title || D.text;
  t.style.cssText = 'display:inline-block;max-width:24vw;overflow:hidden;text-overflow:ellipsis;vertical-align:bottom;';
  if (D.more) { var m = document.createElement('span'); m.textContent = '+' + D.more + ' more'; m.style.opacity = '0.7'; s.appendChild(m); }
  if (D.act) {
    var a = document.createElement('b'); a.textContent = D.act; a.style.cssText = 'flex:none;color:' + D.accent; s.appendChild(a);
    if (D.actcmd) { a.onclick = function (e) { e.stopPropagation(); try { pycmd('duecrew:' + D.actcmd); } catch (x) {} }; }
  }
  if (D.cmd) { s.onclick = function () { try { pycmd('duecrew:' + D.cmd); } catch (e) {} }; } else { s.style.cursor = 'default'; }
  cell.appendChild(s);
  __PIP__
})();"""


def chip_js(data):
    from .room_model import BAR_BALANCE
    return _CHIP_JS.replace("__PIP__", _PIP_JS).replace("__DATA__", json.dumps(data)) + BAR_BALANCE


# The chip as a small card above the bar, bottom right of the review
# screen (mock "Ask chip", B). It shows only while the card's own text and
# pictures leave that corner free (looked at again as pictures load, and on
# scroll and resize); otherwise, or the moment it isn't, the chip goes back
# beside Edit (`knowsbar`). Its clicks come from the review screen, where a
# card's script runs too, so they're keyed (room_model.CARD_PAGE_CMDS) and
# This helped from here asks first.
_FLOAT_JS = """(function () {
  var D = __DATA__;
  var still = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  var old = document.getElementById('dc-knows-card'), oldPad = document.getElementById('dc-knows-pad');
  if (window.dcKnowsOff) { window.dcKnowsOff(!D); window.dcKnowsOff = null; } else if (old) { old.remove(); }
  if (oldPad) { oldPad.remove(); }
  if (!D) { return false; }
  var KEY = __KEY__, gone = false;
  function send(cmd) { try { pycmd('duecrew:' + cmd + '|' + KEY); } catch (e) {} }
  var night = /night/i.test(document.body.className) || document.documentElement.classList.contains('night-mode');
  var acc = night ? D.accent[1] : D.accent[0];
  var c = night ? {bg: '#2c2c2c', ink: '#e8e8e8', mut: '#9c9c9c', line: '#3d403b'} : {bg: '#ffffff', ink: '#222222', mut: '#777777', line: '#e2e2da'};
  function el(tag, css, text) { var e = document.createElement(tag); e.style.cssText = css; if (text != null) { e.textContent = text; } return e; }
  // 3.9.0 (Sam's picks, "Open calls" C, then "2D"): who knows it, their Pips peeking up from the bottom,
  // side by side (three at most), no light bulb drawn; with Pip off the same bubble in the same place, without them
  var peek = D.peek || null, withPip = !!(peek && peek.pips && peek.pips.length);
  var font = 'font:12.5px/1.35 -apple-system,Segoe UI,sans-serif;text-align:left;';
  var card = 'border:1px solid ' + c.line + ';background:' + c.bg + ';color:' + c.ink + ';box-shadow:0 6px 18px rgba(0,0,0,.22);';
  var box = peek ? el('div', 'position:fixed;right:16px;bottom:' + (withPip ? '0' : '14px') + ';display:flex;align-items:flex-end;gap:8px;z-index:60;' + font)
    : el('div', 'position:fixed;right:12px;bottom:12px;max-width:260px;box-sizing:border-box;display:grid;gap:6px;padding:9px 12px;' +
      'border-radius:12px;' + card + font + 'z-index:60;');
  box.id = 'dc-knows-card';
  var head = el('div', 'font-weight:600;cursor:pointer;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;',
    peek ? peek.head : D.text);
  if (D.title) { head.title = D.title; }
  if (D.cmd) { head.onclick = function () { send(D.cmd); }; } else { head.style.cursor = 'default'; }
  if (D.pip && !peek) {  // 3.8.22: who it is, as their Pip, before the words
    var hr = el('div', 'display:flex;gap:6px;align-items:center;');
    pip(hr, D, night, 'margin:-4px 0 -2px -2px;');
    hr.appendChild(head); head = hr;
  }
  var acts = el('div', 'display:flex;gap:12px;align-items:baseline;flex-wrap:wrap;');
  function link(text, color, bold, fn) {
    var a = el('span', 'cursor:pointer;color:' + color + ';' + (bold ? 'font-weight:700;' : ''), text);
    a.onclick = function (e) { e.stopPropagation(); fn(); }; acts.appendChild(a); return a;
  }
  if (D.act) { link(peek ? peek.act : D.act, acc, true, function () { send(D.actcmd || D.cmd); }); }
  if (D.more) { link('+' + D.more + ' more', c.mut, false, function () { send('knowstip'); }); }
  link('Not now', c.mut, false, function () { off(true); });
  var fig = null, bub = null;
  if (peek) {
    bub = el('div', 'margin-bottom:' + (withPip ? '26px' : '0') + ';max-width:220px;display:grid;gap:4px;padding:8px 11px;' +
      'border-radius:' + (withPip ? '12px 12px 4px 12px' : '12px') + ';transform-origin:100% 100%;' + card);
    bub.appendChild(head); bub.appendChild(acts);
    box.appendChild(bub);
  }
  if (withPip) {
    fig = el('span', 'position:relative;display:inline-flex;align-items:flex-end;gap:2px;line-height:0;');
    fig.setAttribute('data-fig', '1');
    for (var i = peek.pips.length - 1; i >= 0; i--) {  // the first who knows it nearest the corner
      pip(fig, {pip: peek.pips[i], sevcss: D.sevcss}, night, '');
    }
    box.appendChild(fig);
  } else if (!peek) {
    box.appendChild(head); box.appendChild(acts);
  }
  __PIP__
  document.body.appendChild(box);
  if (peek && !still && bub.animate) {  // up they pop, then the bubble; nothing with Reduce motion
    if (fig) { fig.animate([{transform: 'translateY(105%)'}, {transform: 'none'}], {duration: 700, easing: 'cubic-bezier(.2,.9,.3,1.25)'}); }
    bub.animate([{opacity: 0, transform: 'scale(.85)'}, {opacity: 1, transform: 'none'}], {duration: 350, delay: fig ? 550 : 0, easing: 'ease-out', fill: 'backwards'});
  }
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
  var pad = null, ro = null, later = null;
  function off(duck) {
    if (gone) { return; }
    gone = true;
    if (pad) { pad.remove(); }
    window.removeEventListener('scroll', check, true); window.removeEventListener('resize', check);
    document.removeEventListener('load', check, true);
    if (ro) { ro.disconnect(); }
    clearTimeout(later);
    if (window.dcKnowsOff === off) { window.dcKnowsOff = null; }
    box.removeAttribute('id');
    if (duck && bub && !still && bub.animate) {  // it ducks back down (or the bubble fades): the next card, or Not now
      box.style.pointerEvents = 'none';
      var fade = bub.animate([{opacity: 1}, {opacity: 0}], {duration: fig ? 150 : 200, fill: 'forwards'});
      if (fig) { fig.animate([{transform: 'none'}, {transform: 'translateY(105%)'}], {duration: 260, easing: 'ease-in', fill: 'forwards'}).onfinish = function () { box.remove(); }; }
      else { fade.onfinish = function () { box.remove(); }; }
    } else { box.remove(); }
  }
  function check() { if (!gone && !free()) { off(); send('knowsbar'); } }
  window.dcKnowsOff = off;
  if (peek) {
    // 3.9.0 (Sam, 16 Oct: the pill "is not the new version we agreed on"): the peek always shows, as in
    // the mock, never the bar's chip; room under the card so its last lines scroll clear of it
    pad = el('div', 'height:' + (box.offsetHeight + 12) + 'px;');
    pad.id = 'dc-knows-pad';
    document.body.appendChild(pad);
    return true;
  }
  window.addEventListener('scroll', check, true); window.addEventListener('resize', check);
  document.addEventListener('load', check, true);  // a picture that loads late
  // Anki puts the answer in a moment later (pictures preloaded, MathJax
  // typeset): look again when the card's area changes size, and once more
  var qa = document.getElementById('qa');
  later = setTimeout(check, 600);
  if (qa && window.ResizeObserver) { ro = new ResizeObserver(check); ro.observe(qa); }
  if (!free()) { off(); return false; }
  return true;
})();"""


def float_js(data):
    from .room_model import CMD_KEY
    return (_FLOAT_JS.replace("__PIP__", _PIP_JS).replace("__KEY__", json.dumps(CMD_KEY))
            .replace("__DATA__", json.dumps(data)))


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
    and someone knows it or left a tip. 3.9.0: the stuck cards' answer from
    the last sync, or, for a card I'm stuck on since, the morning's answer
    for the cards due today."""
    web = _bottom()
    if web is None or not client().signed_in:
        return
    try:
        guid = card.note().guid
        from .together import local_tips
        asks = [(e["user_id"], i, t["q"]) for e in _state["entries"] or [] if not e.get("you")
                for i, t in enumerate(e.get("tricky") or []) if t.get("guid") == guid and t.get("q")]
        from .together import _today
        mine = any(f["guid"] == guid for f in clean_tricky(client().session.get("tricky"), _today()))
        sess = client().session
        info = (sess.get("cards") or {}).get(guid)
        if info is None and guid in (sess.get("cards_due") or {}) and sess.get("due_day") == log_today(mw.col) \
                and stuck_now(mw.col, card, mw.col.sched.day_cutoff):
            info = sess["cards_due"][guid]  # 3.9.0: missed today for the first time, known since the morning
        pips = pips_by_uid()
        view = chip_view(info, local_tips(guid), names_by_uid(), asks, mine, pips)
        if view is None or view.get("kind") == "knows":
            view = remark_view(client().session.get("plans"), guid, card.ord) or view  # 3.8.1
        if view and view.get("peek"):
            peek = dict(view["peek"])
            # each Pip waving, in their look and colour; none (Pip off): the bubble alone
            drawn = [{"svg": peek_pip(u), "a": pips[u]["a"]} for u in peek.pop("uids", None) or [] if u in pips]
            peek["pips"] = [p for p in drawn if p["svg"]]
            view["peek"] = peek
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
    from .together import _today
    asked = next((f for f in clean_tricky(client().session.get("tricky"), _today()) if f["guid"] == guid), None)
    line, ok = ask_text(mw, "Ask your crew about this card",
                        lead + ("You've asked. Change your line, or leave it as it is."
                                if asked else "Your crew sees it on their copy of the card. One line, optional."),
                        (asked or {}).get("q") or "")
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
