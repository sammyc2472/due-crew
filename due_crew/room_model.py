"""2.12 study rooms: the model. Pure: no aqt, no network.

A room is a shared clock: {host, start, rounds, round, brk} (start in UTC,
lengths in minutes). The host's week doc carries it; joining copies it to
mine. Every screen works out the round and the minutes left from `start`,
so nothing is fetched while anyone reviews. Who's in is whoever's week doc
carries the same room (host + start), as of the last refresh.

The widgets are JavaScript for four webviews: Anki's top bar (the chip, A),
the review screen's bottom bar (B), the review screen itself (the margin
card C, the break, and the room card), and the Decks screen. Everything
from a friend's doc goes in as textContent, never markup.
"""

import datetime
import json
import re
import secrets

ROUND_CHOICES = (15, 25, 30, 45, 50)
BREAK_CHOICES = (5, 10, 15)
MAX_ROUNDS = 8
HOST_MAX = 128
GUTTER_WIDTH = 150  # the margin card (C), px


def _parse(ts):
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)


def iso(dt):
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now(now):
    return now or datetime.datetime.now(datetime.timezone.utc)


def make_room(host, start, rounds=4, round_min=25, brk_min=5):
    return clean_room({"host": host, "start": iso(start), "rounds": rounds,
                       "round": round_min, "brk": brk_min})


def _bounded(value, low, high, default):
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, v))


def clean_room(value):
    """A room from a week doc, coerced, or None. Bounds keep a hostile doc
    from building a week-long room or a zero-minute round."""
    if not isinstance(value, dict):
        return None
    host = str(value.get("host") or "")[:HOST_MAX]
    start = _parse(value.get("start"))
    if not host or start is None:
        return None
    return {"host": host, "start": iso(start),
            "rounds": _bounded(value.get("rounds"), 1, MAX_ROUNDS, 4),
            "round": _bounded(value.get("round"), 5, 90, 25),
            "brk": _bounded(value.get("brk"), 0, 30, 5)}


def room_key(room):
    return f"{room['host']}@{room['start']}" if room else ""


def cmd_key(room):
    """The room's key as it survives a board command (board._pycmd keeps
    letters, digits, colon, dash and underscore): Join and × use this."""
    return re.sub(r"[^A-Za-z0-9:_-]", "", room_key(room))


def room_minutes(room):
    return room["rounds"] * room["round"] + (room["rounds"] - 1) * room["brk"]


def room_end(room):
    return _parse(room["start"]) + datetime.timedelta(minutes=room_minutes(room))


def phase(room, now=None):
    """Where the room is now: state before / round / break / done, the round
    (1-based; for a break, the round just finished), seconds left in this
    phase, and when it ends."""
    now = _now(now)
    t = _parse(room["start"])
    rnd, brk = datetime.timedelta(minutes=room["round"]), datetime.timedelta(minutes=room["brk"])
    out = {"rounds": room["rounds"], "end": room_end(room)}
    if now < t:
        return dict(out, state="before", round=0, left=(t - now).total_seconds(), until=t)
    for i in range(1, room["rounds"] + 1):
        if now < t + rnd:
            return dict(out, state="round", round=i, left=(t + rnd - now).total_seconds(),
                        until=t + rnd, total=rnd.total_seconds())
        t += rnd
        if i < room["rounds"] and brk:
            if now < t + brk:
                return dict(out, state="break", round=i, left=(t + brk - now).total_seconds(),
                            until=t + brk, total=brk.total_seconds())
            t += brk
    return dict(out, state="done", round=room["rounds"], left=0, until=t)


def is_over(room, now=None):
    return room is None or phase(room, now)["state"] == "done"


def members(entries, room):
    """[(uid, name, you)] of everyone whose room is this one, host first."""
    key = room_key(room)
    out = [(e["user_id"], str(e.get("name") or "?"), bool(e.get("you")))
           for e in entries or [] if key and room_key(e.get("room")) == key and not e.get("paused")]
    out.sort(key=lambda m: (m[0] != room["host"], m[1].lower()))
    return out


def host_name(entries, room):
    for e in entries or []:
        if e["user_id"] == room["host"]:
            return str(e.get("name") or "?")
    return ""


def title(entries, room):
    """ "Dre's room", or "A study room" when the host isn't in my crew."""
    name = host_name(entries, room)
    return f"{name.split(' ')[0]}’s room" if name else "A study room"


def invites(entries, my_room, dismissed=(), now=None):
    """Rooms my crew is in and I'm not: [(room, [(uid, name, you)])], the
    fullest first. Ended rooms and dismissed ones stay out."""
    rooms = {}
    mine = room_key(my_room)
    for e in entries or []:
        r = e.get("room")
        if e.get("you") or not r or e.get("paused"):
            continue
        k = room_key(r)
        if k == mine or cmd_key(r) in dismissed or is_over(r, now):
            continue
        rooms.setdefault(k, r)
    out = [(r, members(entries, r)) for r in rooms.values()]
    out.sort(key=lambda x: (-len(x[1]), x[0]["start"]))
    return out


def names_line(members_):
    """ "Dre, Ameya and you" """
    names = [n.split(" ")[0] for _u, n, you in members_ if not you]
    if any(you for _u, _n, you in members_):
        names.append("you")
    if not names:
        return ""
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def duration_text(minutes):
    h, m = divmod(int(minutes), 60)
    return f"{h} h {m:02d} m" if h else f"{m} m"


def done_share(done):
    """The chat line for a finished room."""
    return (f"Studied together on Due Crew: {done['rounds']} rounds, "
            f"{duration_text(done['minutes'])} with {done['with'] or 'my crew'}.\n"
            "— Due Crew · Anki add-on 2035408484")


# ---- the widgets ----

def widget_data(room, entries, accent_pair, compact=False, side="right"):
    """What every widget needs, all plain values. side: the chip's end of
    the top bar, "right" or "left"."""
    ms = members(entries, room)
    start = _parse(room["start"])
    return {"start": int(start.timestamp() * 1000), "rounds": room["rounds"],
            "round": room["round"] * 60000, "brk": room["brk"] * 60000,
            "title": title(entries, room),
            "names": [n.split(" ")[0] if not you else "you" for _u, n, you in ms],
            # faces show each person's own initial, mine included
            "initials": [(n.strip()[:1] or "?").upper() for _u, n, _you in ms],
            "line": names_line(ms),
            "accent": list(accent_pair), "compact": bool(compact), "side": chip_side(side)}


SQUARES = ('<svg viewBox="0 27.7 484 48.3" style="display:block;width:100%;height:auto" aria-hidden="true">'
           + "".join(f'<rect x="{x}" y="27.7" width="48.3" height="48.3" rx="8.69" class="{c}"/>'
                     for x, c in ((0, "on"), (72.45, "on"), (144.9, "on"), (217.35, "off"),
                                  (289.8, "on"), (362.25, "on"), (434.7, "on")))
           + "</svg>")

# Anki's bottom bar is a table of three cells: Edit's, the answer buttons',
# More's. Whatever widens one side cell (our chip or room, another add-on's
# button) pushes the buttons off centre, so they're slid back to the bar's
# middle (3.7.6: measured, never by setting widths), as far as the side
# cells' own buttons allow, at every card, on resize, and whenever the bar
# changes.
BAR_BALANCE = r"""
(function () {
  window.dcBarBalance = function () {
    var t = document.getElementById('innertable'), row = t && t.rows[0];
    if (!row || row.cells.length < 3) { return; }
    var l = row.cells[0], m = row.cells[1], r = row.cells[row.cells.length - 1];
    l.style.width = r.style.width = '';  // what 3.7.5 set, gone
    var t0 = document.getElementById('dc-knows-t');
    if (t0) {
      t0.style.maxWidth = '24vw'; t0.textContent = t0.getAttribute('data-full') || t0.textContent;
      [].forEach.call(t0.parentNode.querySelectorAll('span,b'), function (x) { x.style.display = ''; });
      t0.style.display = 'inline-block';
    }  // as drawn (cards._CHIP_JS); shrunk again below if need be
    // another add-on can draw its button over the bar (positioned, out of
    // the row), so ours would sit underneath it: step past anything that does
    function clear(el) {
      if (!el) { return; }
      el.style.marginLeft = '';
      var over = [].filter.call(document.body.getElementsByTagName('*'), function (o) {
        if (o === el || el.contains(o) || o.contains(el)) { return false; }
        var p = getComputedStyle(o).position;
        return p === 'absolute' || p === 'fixed';
      });
      for (var pass = 0; pass < 4; pass++) {
        var b = el.getBoundingClientRect(), push = 0;
        over.forEach(function (o) {
          var q = o.getBoundingClientRect();
          if (q.width > 0 && q.height > 0 && q.left < b.right && q.right > b.left && q.top < b.bottom && q.bottom > b.top) {
            push = Math.max(push, q.right - b.left + 8);
          }
        });
        if (!push) { return; }
        el.style.marginLeft = (parseFloat(getComputedStyle(el).marginLeft) || 0) + push + 'px';
      }
    }
    clear(document.getElementById('dc-knows'));
    clear(document.getElementById('dc-room-bottom'));
    // 3.7.6: no cell widths any more. Measure where the answer buttons are and
    // slide them (a transform, which moves nothing else) to the bar's middle,
    // as near as the side cells' own buttons allow: another add-on's button,
    // added whenever, can't throw the arithmetic off
    function span(c, skip) {   // where a cell's own buttons are, leaving `skip` out
      var a = Infinity, z = -Infinity;
      for (var k = 0; k < c.children.length; k++) {
        if (c.children[k] === skip) { continue; }
        var b = c.children[k].getBoundingClientRect();
        if (b.width > 0) { a = Math.min(a, b.left); z = Math.max(z, b.right); }
      }
      return z > a ? [a, z] : null;
    }
    [].forEach.call(m.children, function (x) { x.style.transform = ''; });
    var tb = t.getBoundingClientRect(), mid = tb.left + tb.width / 2, txt = document.getElementById('dc-knows-t');
    var chip = document.getElementById('dc-knows'), ms0 = span(m);
    if (!ms0) { return; }
    var half = (ms0[1] - ms0[0]) / 2, gap = 12;
    // the chip goes beside More (bottom right, where its card sits too), or
    // Edit's side when More's has no room beside a centred row of answer
    // buttons, and gives way there: its words shrink, then its short form
    function fits(side) {
      var cw = chip.getBoundingClientRect().width + 10;
      if (side === l) { var a = span(l, chip); return (a ? a[1] : tb.left) + cw + gap <= mid - half; }
      var b = span(r, chip); return (b ? b[0] : tb.right) - cw - gap >= mid + half;
    }
    function place(side) {
      if (chip.parentNode === side) { return; }
      if (side === r) { chip.style.marginLeft = '0'; chip.style.marginRight = '10px'; r.insertBefore(chip, r.firstChild); }
      else { chip.style.marginRight = ''; chip.style.marginLeft = '10px'; l.appendChild(chip); }
    }
    if (chip && txt) {
      var side = fits(r) ? r : fits(l) ? l : null;
      if (!side) {
        side = (span(l, chip) || [0, tb.left])[1] - tb.left < tb.right - (span(r, chip) || [tb.right])[0] ? l : r;
        place(side);
        for (var i = 0; !fits(side) && i < 4; i++) {
          var tw = txt.getBoundingClientRect().width;
          if (tw <= 120) { break; }
          txt.style.maxWidth = '120px';
        }
        if (!fits(side)) {
          txt.textContent = txt.getAttribute('data-short') || txt.textContent;
          txt.style.maxWidth = 'none';
          [].forEach.call(chip.children, function (x) {
            if (x !== txt && (x.tagName === 'SPAN' || txt.getAttribute('data-tip'))) { x.style.display = 'none'; }
          });
        }
      }
      place(side);
    }
    var ms = span(m), ls = span(l), rs = span(r);
    var dx = mid - (ms[0] + ms[1]) / 2;
    if (ls && ms[0] + dx < ls[1] + gap) { dx = ls[1] + gap - ms[0]; }        // never under a side's buttons
    if (rs && ms[1] + dx > rs[0] - gap) { dx = Math.min(dx, rs[0] - gap - ms[1]); }
    if (Math.abs(dx) >= 1) { [].forEach.call(m.children, function (x) { x.style.transform = 'translateX(' + Math.round(dx) + 'px)'; }); }
  };
  if (!window.dcBarResize) {
    window.dcBarResize = true;
    window.addEventListener('resize', function () { window.dcBarBalance(); });
    // anything added to the bar later (another add-on's button, Anki's answer
    // buttons for the next card) balances it again; our own style changes don't
    if (window.MutationObserver) {
      var pend = 0;
      new MutationObserver(function (recs) {
        var chip = document.getElementById('dc-knows');  // the chip's own moves and text swaps aren't news
        if (chip && recs.every(function (x) {
          var nodes = [].slice.call(x.addedNodes).concat([].slice.call(x.removedNodes));
          return chip.contains(x.target) || (nodes.length && nodes.every(function (n) { return n === chip; }));
        })) { return; }
        clearTimeout(pend);
        pend = setTimeout(function () { window.dcBarBalance(); }, 30);
      }).observe(document.body, { childList: true, subtree: true });
    }
  }
  window.dcBarBalance();
  clearTimeout(window.dcBarLater);
  window.dcBarLater = setTimeout(function () { window.dcBarBalance(); }, 400);
})();
"""


# The widget's commands carry this, so the reviewer page (where a card's own
# script runs too) is heard only through the widget's buttons. New each run,
# and only inside the widget's closure: never on the page for a card to read.
CMD_KEY = secrets.token_hex(8)

# One runtime per webview, shared by every kind. `kind`: chip (top bar),
# bottom (review bottom bar), gutter (margin card), break (between cards),
# card (the whole room, opened from the chip), off (remove all).
_RUNTIME = r"""
(function () {
  var D = __DATA__, KIND = __KIND__, SQ = __SQUARES__;
  var ids = ['chip', 'bottom', 'gutter', 'break', 'card'];
  function drop(k) {
    var el = document.getElementById('dc-room-' + k);
    if (el) { el.remove(); if (k === 'bottom' && window.dcBarBalance) { window.dcBarBalance(); } }
    if (window['dcRoomTick_' + k]) { clearInterval(window['dcRoomTick_' + k]); window['dcRoomTick_' + k] = null; }
  }
  if (KIND === 'off') { ids.forEach(drop); window.dcRoomFit = null; window.dcBarBalance && window.dcBarBalance(); return; }
  drop(KIND);
  if (!D) { return; }
  function night() {
    return /night/i.test(document.body.className) || document.documentElement.classList.contains('night-mode') ||
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches && !document.body.className);
  }
  function C() {
    var n = night();
    return {a: n ? D.accent[1] : D.accent[0], bg: n ? '#2c2c2c' : '#ffffff', ink: n ? '#e8e8e8' : '#222222',
            mut: n ? '#9c9c9c' : '#777777', line: n ? '#3d403b' : '#e2e2da', warm: n ? '#dda45c' : '#b26a00',
            face: n ? '#3a3148' : '#efe9f9'};
  }
  function phase(now) {
    var t = D.start;
    if (now < t) { return {state: 'before', round: 0, left: t - now, until: t, total: 1}; }
    for (var i = 1; i <= D.rounds; i++) {
      if (now < t + D.round) { return {state: 'round', round: i, left: t + D.round - now, until: t + D.round, total: D.round}; }
      t += D.round;
      if (i < D.rounds && D.brk) {
        if (now < t + D.brk) { return {state: 'break', round: i, left: t + D.brk - now, until: t + D.brk, total: D.brk}; }
        t += D.brk;
      }
    }
    return {state: 'done', round: D.rounds, left: 0, until: t, total: 1};
  }
  function hm(ms) { return new Date(ms).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }
  function mins(ms) { return Math.max(1, Math.ceil(ms / 60000)); }
  function mmss(ms) { var s = Math.max(0, Math.round(ms / 1000)); return Math.floor(s / 60) + ':' + ('0' + s % 60).slice(-2); }
  function el(tag, css, text) { var e = document.createElement(tag); if (css) { e.style.cssText = css; } if (text != null) { e.textContent = text; } return e; }
  function ring(size, c) {
    var r = el('span', 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;display:inline-grid;place-items:center;flex:none;');
    var inner = el('b', 'width:' + (size - Math.max(6, size * .12)) + 'px;height:' + (size - Math.max(6, size * .12)) +
      'px;border-radius:50%;display:grid;place-items:center;background:' + c.bg + ';color:' + c.ink + ';font:600 ' +
      Math.round(size * (size > 60 ? .22 : .4)) + 'px -apple-system,Segoe UI,sans-serif;');
    r.appendChild(inner);
    r.set = function (frac, label, warm) {
      var col = warm ? c.warm : c.a;
      r.style.background = 'conic-gradient(' + col + ' ' + (frac * 360) + 'deg,' + c.line + ' 0)';
      inner.textContent = label;
    };
    return r;
  }
  function squares(c, w) {
    var s = el('span', 'display:block;width:' + w + 'px;flex:none;');
    s.innerHTML = SQ;
    s.querySelectorAll('.on').forEach(function (q) { q.setAttribute('fill', c.a); });
    s.querySelectorAll('.off').forEach(function (q) { q.setAttribute('fill', c.line); });
    return s;
  }
  function faces(c, size) {
    var f = el('span', 'display:inline-flex;');
    (D.initials || D.names).forEach(function (n, i) {
      var x = el('i', 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;display:grid;place-items:center;font:700 ' +
        Math.round(size * .45) + 'px -apple-system,Segoe UI,sans-serif;font-style:normal;background:' + c.face + ';color:' + c.a +
        ';border:2px solid ' + c.bg + ';margin-left:' + (i ? -6 : 0) + 'px;', (n || '?').charAt(0).toUpperCase());
      f.appendChild(x);
    });
    return f;
  }
  function send(cmd) { try { pycmd('duecrew:' + cmd + '|' + __KEY__); } catch (e) {} }
  function sub(p) {
    if (p.state === 'before') { return 'starts ' + hm(D.start); }
    if (p.state === 'break') { return 'Break · round ' + (p.round + 1) + ' at ' + hm(p.until); }
    return 'Round ' + p.round + ' of ' + D.rounds + (p.round < D.rounds && D.brk ? ' · break ' + hm(p.until) : ' · ends ' + hm(p.until));
  }
  var c = C(), root, update;

  if (KIND === 'chip') {
    root = el('div', 'position:fixed;__SIDE__:10px;top:50%;transform:translateY(-50%);height:26px;display:flex;align-items:center;gap:7px;' +
      'padding:0 10px 0 5px;border:1px solid ' + c.a + ';border-radius:14px;background:' + c.bg + ';color:' + c.ink +
      ';font:12px -apple-system,Segoe UI,sans-serif;cursor:pointer;z-index:99;white-space:nowrap;');
    root.title = 'Your study room';
    var sq = squares(c, 34), rg = ring(20, c), tx = el('span', 'display:grid;line-height:1.1;'),
        t1 = el('b', 'font-size:11.5px;', D.title), t2 = el('small', 'font-size:10.5px;color:' + c.mut + ';'), fc = faces(c, 18);
    tx.appendChild(t1); tx.appendChild(t2);
    root.appendChild(sq); root.appendChild(rg); root.appendChild(tx); root.appendChild(fc);
    if (D.compact) { sq.style.display = tx.style.display = fc.style.display = 'none'; root.style.padding = '0 3px'; }
    root.onclick = function () { send('roomcard'); };
    update = function (p) {
      rg.set(p.state === 'before' ? 0 : 1 - p.left / p.total, p.state === 'before' ? '·' : String(mins(p.left)), p.state === 'break');
      t2.textContent = sub(p);
    };
  } else if (KIND === 'bottom') {
    var edit = document.querySelector('button[onclick*="edit"]');
    var cell = edit ? edit.parentNode : document.body;
    root = el('span', 'display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding-left:10px;border-left:1px solid ' + c.line +
      ';font:12px -apple-system,Segoe UI,sans-serif;color:' + c.mut + ';vertical-align:middle;cursor:pointer;white-space:nowrap;');
    var rg2 = ring(20, c), tx2 = el('span');
    root.appendChild(rg2); root.appendChild(tx2);
    root.onclick = function () { send('roomcard'); };
    cell.appendChild(root);
    update = function (p) {
      rg2.set(p.state === 'before' ? 0 : 1 - p.left / p.total, p.state === 'before' ? '·' : String(mins(p.left)), p.state === 'break');
      tx2.textContent = (p.state === 'break' ? 'break ' + mins(p.left) + ' min' : p.state === 'before' ? 'starts ' + hm(D.start) : mins(p.left) + ' min') +
        (D.line ? ' · ' + D.line : '');
    };
  } else if (KIND === 'gutter') {
    root = el('div', 'position:fixed;left:16px;top:16px;width:' + __GUTTER__ + 'px;box-sizing:border-box;display:grid;justify-items:center;gap:5px;' +
      'padding:12px 8px;border:1px solid ' + c.line + ';border-radius:14px;background:' + c.bg + ';color:' + c.ink +
      ';font:12px -apple-system,Segoe UI,sans-serif;text-align:center;box-shadow:0 4px 14px rgba(0,0,0,.08);z-index:50;cursor:pointer;');
    var rg3 = ring(40, c), g1 = el('b', 'font-size:12.5px;'), g2 = el('small', 'color:' + c.mut + ';font-size:11px;'),
        g3 = el('small', 'color:' + c.mut + ';font-size:11px;line-height:1.3;', D.line);
    root.appendChild(squares(c, 56)); root.appendChild(rg3); root.appendChild(g1); root.appendChild(g2); root.appendChild(faces(c, 26)); root.appendChild(g3);
    root.onclick = function () { send('roomcard'); };
    update = function (p) {
      rg3.set(p.state === 'before' ? 0 : 1 - p.left / p.total, p.state === 'before' ? '·' : String(mins(p.left)), p.state === 'break');
      g1.textContent = p.state === 'break' ? 'Break' : p.state === 'before' ? D.title : 'Round ' + p.round + ' of ' + D.rounds;
      g2.textContent = p.state === 'break' ? 'round ' + (p.round + 1) + ' at ' + hm(p.until) : p.state === 'before' ? 'starts ' + hm(D.start) :
        (p.round < D.rounds && D.brk ? 'break at ' + hm(p.until) : 'ends ' + hm(p.until));
    };
    // shown only while the card leaves the left margin free; A and B
    // don't need this, since they never sit over the card
    window.dcRoomFit = function () {
      var qa = document.getElementById('qa'), left = window.innerWidth;
      if (qa) {
        var r = document.createRange(); r.selectNodeContents(qa);
        var rects = r.getClientRects();
        for (var i = 0; i < rects.length; i++) { if (rects[i].width > 0 && rects[i].height > 0) { left = Math.min(left, rects[i].left); } }
        qa.querySelectorAll('img,table,canvas,svg,video,iframe').forEach(function (m) {
          var b = m.getBoundingClientRect(); if (b.width > 0) { left = Math.min(left, b.left); }
        });
      }
      root.style.display = left > 16 + __GUTTER__ + 24 ? 'grid' : 'none';
    };
    if (!window.dcRoomFitResize) {
      window.dcRoomFitResize = true;
      window.addEventListener('resize', function () { window.dcRoomFit && window.dcRoomFit(); });
    }
  } else if (KIND === 'break') {
    // a type-in answer box keeps no focus under the break
    try { if (document.activeElement && document.activeElement.blur) { document.activeElement.blur(); } } catch (e) {}
    root = el('div', 'position:fixed;inset:0;background:' + c.bg + ';color:' + c.ink + ';display:grid;place-items:center;z-index:9999;' +
      'font:16px -apple-system,Segoe UI,sans-serif;text-align:center;');
    var box = el('div', 'display:grid;justify-items:center;gap:14px;max-width:520px;padding:20px;');
    var logo = el('span', 'display:flex;align-items:center;gap:8px;');
    logo.appendChild(squares(c, 110));
    var rg4 = ring(150, c), h = el('div', 'font:600 28px -apple-system,Segoe UI,sans-serif;'), p1 = el('div', 'color:' + c.mut + ';max-width:40ch;');
    var btns = el('div', 'display:flex;gap:10px;flex-wrap:wrap;justify-content:center;');
    var cheer = el('button', 'background:' + c.a + ';color:' + c.bg + ';border:0;border-radius:8px;padding:8px 16px;font:600 14px -apple-system,Segoe UI,sans-serif;cursor:pointer;', 'Cheer the room 🎉');
    var skip = el('button', 'background:transparent;color:' + c.ink + ';border:1px solid ' + c.line + ';border-radius:8px;padding:8px 16px;font:14px -apple-system,Segoe UI,sans-serif;cursor:pointer;', 'Skip the break');
    cheer.onclick = function () { send('roomcheer'); cheer.textContent = 'Cheered ✓'; cheer.disabled = true; };
    skip.onclick = function () { send('roomskip'); };
    btns.appendChild(cheer); btns.appendChild(skip);
    box.appendChild(logo); box.appendChild(rg4); box.appendChild(h); box.appendChild(p1); box.appendChild(faces(c, 32)); box.appendChild(btns);
    box.appendChild(el('small', 'color:' + c.mut + ';font-size:12px;', 'The break waited for you to finish your card.'));
    root.appendChild(box);
    var ended = false;
    update = function (p) {
      if (p.state !== 'break') {
        if (!ended) { ended = true; send('roombreakend'); }
        return;
      }
      rg4.set(p.left / p.total, mmss(p.left), true);
      h.textContent = 'Round ' + p.round + ' done. Break.';
      var others = D.names.filter(function (n) { return n !== 'you'; });
      p1.textContent = (others.length ? others.join(' and ') + (others.length > 1 ? ' are' : ' is') + ' on the same break. ' : '') +
        'Round ' + (p.round + 1) + ' starts at ' + hm(p.until) + '.';
    };
  } else if (KIND === 'card') {
    root = el('div', 'position:fixed;right:12px;top:10px;width:330px;box-sizing:border-box;border:1px solid ' + c.line +
      ';border-radius:14px;background:' + c.bg + ';color:' + c.ink + ';box-shadow:0 12px 34px rgba(0,0,0,.2);padding:12px 14px;' +
      'display:grid;gap:10px;font:13px -apple-system,Segoe UI,sans-serif;z-index:10000;text-align:left;');
    var hd = el('div', 'display:flex;justify-content:space-between;align-items:center;'), x = el('span', 'cursor:pointer;color:' + c.mut + ';font-size:18px;', '×');
    hd.appendChild(squares(c, 70)); hd.appendChild(x);
    var row = el('div', 'display:flex;gap:10px;align-items:center;'), rg5 = ring(44, c), rt = el('div', 'display:grid;'),
        k1 = el('b', '', D.title), k2 = el('small', 'color:' + c.mut + ';font-size:12px;');
    rt.appendChild(k1); rt.appendChild(k2); row.appendChild(rg5); row.appendChild(rt);
    var bar = el('div', 'display:flex;gap:3px;align-items:center;'), segs = [];
    for (var i = 1; i <= D.rounds; i++) {
      var sg = el('i', 'flex:' + D.round + ';height:8px;border-radius:4px;background:' + c.line + ';position:relative;overflow:hidden;display:block;');
      var fill = el('i', 'position:absolute;left:0;top:0;bottom:0;width:0;background:' + c.a + ';display:block;');
      sg.appendChild(fill); bar.appendChild(sg); segs.push(fill);
      if (i < D.rounds && D.brk) { bar.appendChild(el('i', 'flex:' + D.brk + ';height:4px;border-radius:2px;background:' + c.warm + ';opacity:.45;display:block;')); }
    }
    var who = el('div', 'display:flex;align-items:center;gap:8px;color:' + c.mut + ';font-size:12px;');
    who.appendChild(faces(c, 24)); who.appendChild(el('span', '', D.line));
    var ft = el('div', 'display:flex;justify-content:space-between;font-size:12.5px;font-weight:600;color:' + c.a + ';border-top:1px solid ' + c.line + ';padding-top:8px;');
    var tuck = el('span', 'cursor:pointer;', D.compact ? 'Show the whole chip' : 'Tuck it away'), leave = el('span', 'cursor:pointer;', 'Leave room');
    ft.appendChild(tuck); ft.appendChild(leave);
    root.appendChild(hd); root.appendChild(row); root.appendChild(bar); root.appendChild(who); root.appendChild(ft);
    x.onclick = function () { drop('card'); };
    tuck.onclick = function () { drop('card'); send('roomtuck'); };
    leave.onclick = function () { drop('card'); send('roomleave'); };
    setTimeout(function () {
      document.addEventListener('mousedown', function out(ev) {
        // a card closed some other way (×, Tuck, Leave, redrawn) takes this with it
        if (!root.isConnected) { document.removeEventListener('mousedown', out); return; }
        if (!root.contains(ev.target)) { drop('card'); document.removeEventListener('mousedown', out); }
      });
    }, 0);
    update = function (p) {
      rg5.set(p.state === 'before' ? 0 : p.state === 'break' ? p.left / p.total : 1 - p.left / p.total,
              p.state === 'before' ? '·' : String(mins(p.left)), p.state === 'break');
      k2.textContent = p.state === 'before' ? 'Starts at ' + hm(D.start) + ' · ' + D.rounds + ' rounds' :
        p.state === 'break' ? 'Break · round ' + (p.round + 1) + ' at ' + hm(p.until) :
        'Round ' + p.round + ' of ' + D.rounds + ' · ' + mins(p.left) + ' min left';
      var now = Date.now(), t = D.start;
      segs.forEach(function (f) {
        f.style.width = Math.max(0, Math.min(1, (now - t) / D.round)) * 100 + '%';
        t += D.round + D.brk;
      });
    };
  }
  if (KIND !== 'bottom') { document.body.appendChild(root); }
  root.id = 'dc-room-' + KIND;
  function tick() {
    var p = phase(Date.now());
    if (p.state === 'done' && KIND !== 'break') { drop(KIND); return; }
    update(p);
    if (KIND === 'gutter' && window.dcRoomFit) { window.dcRoomFit(); }
    if (KIND === 'bottom' && window.dcBarBalance) { window.dcBarBalance(); }
  }
  tick();
  window['dcRoomTick_' + KIND] = setInterval(tick, KIND === 'break' ? 1000 : 10000);
})();
"""


def chip_side(value):
    """3.0.1: which end of the top bar the chip sits at (a per-computer
    setting: other add-ons put chips there too)."""
    return "left" if value == "left" else "right"


def widget_js(kind, data=None):
    """The JS that draws (or, with data None, removes) one widget. kind
    'off' removes them all from this webview."""
    # the data goes in last: a name or a tip holding "__KEY__" stays text
    return (_RUNTIME.replace("__KIND__", json.dumps(kind))
            .replace("__SQUARES__", json.dumps(SQUARES))
            .replace("__GUTTER__", str(GUTTER_WIDTH))
            .replace("__SIDE__", chip_side((data or {}).get("side")))
            .replace("__KEY__", json.dumps(CMD_KEY))
            .replace("__DATA__", json.dumps(data))
            + (BAR_BALANCE if kind in ("bottom", "off") else ""))


# what the widgets send from the reviewer's page (the margin card, the
# break, the room's card, the Ask card): nothing else is ever taken from there
CARD_PAGE_CMDS = ("roomcard", "roomtuck", "roomskip", "roombreakend", "roomcheer", "roomleave",
                  # the Ask card above the bar (cards.py): opening a dialog or a
                  # menu (Tip asks for its line), moving the chip to the bar, and This
                  # helped, which asks first
                  "knowsask", "knowstip", "knowsbar", "knowshelped", "knowsreply")


def trusted(message, from_card_page):
    """(message without its key, whether to act on it). From the reviewer's
    page only the widget's own commands count, and only with the key; a
    card's script could still wrap pycmd and learn it, so the list is what
    bounds it. Elsewhere the key is just dropped."""
    body, sep, key = message.rpartition("|")
    keyed = bool(sep) and key == CMD_KEY
    if keyed:
        message = body
    if not from_card_page:
        return message, True
    return message, keyed and message.split(":")[1:2] in [[c] for c in CARD_PAGE_CMDS]


def placement(top_hidden, bottom_hidden):
    """Where the room goes while reviewing: the top bar (A), else the
    bottom bar (B), else the margin (C, which shows itself only when the
    card leaves the margin free)."""
    if not top_hidden:
        return "chip"
    if not bottom_hidden:
        return "bottom"
    return "gutter"


def _clock(dt):
    """Local wall-clock time, as the board shows it."""
    return dt.astimezone().strftime("%H:%M")


def board_view(my_room, entries, dismissed=(), done=None, now=None):
    """What the Decks screen shows about rooms, as plain values (the board
    escapes every string): my room's lobby, invites to my crew's rooms, and
    the line for a room I finished."""
    now = _now(now)
    out = {"mine": None, "invites": [], "done": done}
    if my_room and not is_over(my_room, now):
        p = phase(my_room, now)
        ms = members(entries, my_room)
        if not any(you for _u, _n, you in ms):
            ms.append(("", "you", True))
        start = _parse(my_room["start"])
        bars, t = [], start
        for _i in range(my_room["rounds"]):
            span = datetime.timedelta(minutes=my_room["round"])
            bars.append(max(0.0, min(1.0, (now - t) / span)))
            t += span + datetime.timedelta(minutes=my_room["brk"])
        if p["state"] == "before":
            sub, label, frac = f"Starts at {_clock(start)} · {my_room['rounds']} rounds of {my_room['round']} min", "·", 0.0
        elif p["state"] == "break":
            sub = f"Break · round {p['round'] + 1} starts at {_clock(p['until'])}"
            label, frac = str(max(1, int(-(-p['left'] // 60)))), p["left"] / p["total"]
        else:
            nxt = (f", then a {my_room['brk']}-min break" if p["round"] < my_room["rounds"] and my_room["brk"] else "")
            sub = (f"Round {p['round']} of {my_room['rounds']} · {max(1, int(-(-p['left'] // 60)))} min left{nxt}"
                   f" · ends about {_clock(p['end'])}")
            label, frac = str(max(1, int(-(-p['left'] // 60)))), 1 - p["left"] / p["total"]
        out["mine"] = {"title": title(entries, my_room), "sub": sub, "label": label, "frac": round(frac, 3),
                       "brk": p["state"] == "break", "bars": [round(b, 3) for b in bars],
                       "round": my_room["round"], "brk_min": my_room["brk"],
                       "initials": [n[:1].upper() for _u, n, _y in ms], "line": names_line(ms)}
    for room, ms in invites(entries, my_room, dismissed, now):
        p = phase(room, now)
        when = (f"starts at {_clock(_parse(room['start']))}" if p["state"] == "before"
                else f"round {max(1, p['round'])} of {room['rounds']}")
        out["invites"].append({"key": cmd_key(room), "title": title(entries, room),
                               "sub": f"{room['rounds']} rounds of {room['round']} min · {when}",
                               "line": names_line(ms)})
    return out
