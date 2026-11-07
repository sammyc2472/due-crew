"""You › Pip Party: the three games, the map of what you know, the picks.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
import re as _re

from .. import sev as _sev
from ..gamenight import GAMES as _GAMES

from .base import _pycmd
from .insights import word_pick


_GAME_KIND = {"trivia": "Your cards, four shapes", "imposter": "One of you doesn't know", "links": "Two teams, one board"}
_GAME_UNIT = {"trivia": ("question", "questions"), "imposter": ("topic", "topics"), "links": ("word", "words")}
_PP_SHAPES = ('<path d="M12 3 L22 20 L2 20 Z"/>', '<path d="M12 2 L22 12 L12 22 L2 12 Z"/>', '<circle cx="12" cy="12" r="10"/>',
              '<rect x="3" y="3" width="18" height="18" rx="2"/>')
_PP_GRID = "gpgnngxpgnpggnpnpgngpnpgn"  # Links' key, a board of the two teams, nobody's and Code blue


def _party_art(gid):
    """A game's little picture: Trivia's four shapes and Pip thinking;
    Imposter's three Pips, the odd one in rose; Links' board. Still till
    pointed at (the tab's Pips are); then each plays: the shapes pop in
    turn and Pip thinks, the two Pips bob and the odd one looks about, its
    ? wobbling, a wave crosses the board. Picked, it plays once (.just)."""
    def pip(pose, accent, size):
        return _sev.still(pose, accent=accent).replace('width="80" height="80"', f'width="{size}" height="{size}"', 1)
    if gid == "trivia":
        shapes = "".join(f'<svg class="pp-sh s{i}" viewBox="0 0 24 24" aria-hidden="true">{d}</svg>' for i, d in enumerate(_PP_SHAPES))
        return f'<span class="pp-4">{shapes}</span><span class="pp-p">{pip("focus", "var(--dc-accent)", 30)}</span>'
    if gid == "imposter":
        return (f'<span class="pp-3"><span class="pp-p p1">{pip("hello", "var(--dc-accent)", 32)}</span>'
                f'<span class="pp-odd">{pip("peek", "#d0587f", 32)}<i>?</i></span><span class="pp-p p2">{pip("ready", "var(--dc-accent)", 32)}</span></span>')
    # Links' board, its squares in rows of five: a wave runs corner to corner (--d, a square's row and column)
    return '<span class="pp-25">' + "".join(f'<i class="{c}" style="--d:{k // 5 + k % 5}"></i>' for k, c in enumerate(_PP_GRID)) + "</span>"


def party_map_html(v):
    """The map's part of You › Pip Party (its trail, its tiles), drawn again
    alone while a find is typed (gamenight_flow._find_draw)."""
    e = _html.escape
    v = v or {}

    def tile(t, cmd, i, where=""):
        n, k, st = int(t.get("n") or 0), t.get("know"), int(t.get("started") or 0)
        shade = "sn" if k is None else f"s{3 if k >= 90 else 2 if k >= 80 else 1 if k >= 70 else 0}"
        mark = {"in": " pick", "out": " left"}.get(t.get("pick") or "", "")
        bar = f'<i class="tmb" style="width:{100 * st / n:.0f}%"></i>' if k is not None and n and 0 < st < n else ""
        say = f'{e(str(t["name"]))}{f"<i class=pp-wh>{e(where)}</i>" if where else ""}'
        tip = f'{t["name"]}: {n:,} card{"" if n == 1 else "s"}' + ({"in": ", picked", "out": ", left out"}.get(t.get("pick") or "", ""))
        op = (f'<a class="pp-op" href="#" aria-label="Open {e(str(t["name"]))}" onclick="{_pycmd(f"party:open:{i}")}">&rsaquo;</a>'
              if t.get("kids") and not where else "")
        big = max(1, int(v.get("_big") or n or 1))
        return (f'<span class="pp-tw" style="flex:{n} 1 {70 + int(150 * n / big)}px">'
                f'<a class="tm {shade}{mark}" href="#" role="button" aria-pressed="{"true" if mark else "false"}" title="{e(tip)}" '
                f'onclick="{_pycmd(f"{cmd}:{i}")}"><span>{say}</span>'
                f'<b>{"new" if k is None else f"{int(k)}%"}<small> &middot; {n:,}</small></b>{bar}'
                f'<i class="pp-ck">{"&minus;" if t.get("pick") == "out" else "&#10003;"}</i></a>{op}</span>')
    if v.get("find"):
        hits = v.get("hits") or []
        v = dict(v, _big=max([int(h.get("n") or 0) for h in hits] or [1]))
        body = "".join(tile(h, "party:hit", i, h.get("where") or "") for i, h in enumerate(hits)) or '<span class="pp-none">Nothing by that name.</span>'
        trail = (f'<div class="tmt">Matches for &ldquo;{e(v["find"])}&rdquo; &middot; '
                 f'<a href="#" onclick="dcParty.clear();return false;">Clear</a></div>')
        return f'<div id="pp-map">{trail}<div class="tmap{" picking" if any(h.get("pick") == "in" for h in hits) else ""}">{body}</div></div>'
    tiles = v.get("tiles") or []
    v = dict(v, _big=max([int(t.get("n") or 0) for t in tiles] + [int((v.get("ids") or {}).get("n") or 0), 1]))
    trail = ""
    if v.get("trail"):
        steps = [f'<a href="#" onclick="{_pycmd("party:up:0")}">All</a>']
        steps += [f'<a href="#" onclick="{_pycmd(f"party:up:{j}")}">{e(str(x))}</a>' for j, x in enumerate(v["trail"][:-1], 1)]
        steps.append(f'<b>{e(str(v["trail"][-1]))}</b>')
        trail = f'<div class="tmt">{" &rsaquo; ".join(steps)}</div>'
    body = "".join(tile(t, "party:pick", i) for i, t in enumerate(tiles))
    ids = v.get("ids")
    if ids:
        body += tile({"name": f'{int(ids["tags"]):,} question numbers', "n": ids["n"], "know": None, "pick": ids.get("pick")}, "party:ids", 0)
    if v.get("more"):
        body += (f'<span class="pp-tw" style="flex:1 1 120px"><a class="tm pp-more" href="#" onclick="dcParty.focus();return false;">'
                 f'<span>and {int(v["more"]):,} more</span><b>Find one &rsaquo;</b></a></span>')
    if not body and v.get("loading"):
        body = '<span class="pp-none" role="status">Reading your cards&hellip;</span>'
    if not body:
        body = ('<span class="pp-none">This deck doesn&rsquo;t split by system yet. Try Tags or Decks.</span>' if v.get("by") == "sys"
                else '<span class="pp-none">Nothing here yet.</span>')
    picking = any(t.get("pick") == "in" for t in tiles) or (ids or {}).get("pick") == "in"
    return f'<div id="pp-map">{trail}<div class="tmap{" picking" if picking else ""}">{body}</div></div>'


PARTY_JS = r"""
(function () {
  if (window.dcParty) { return; }
  var t = null;
  window.dcParty = {
    send: function (cmd, text) { pycmd('duecrew:party:' + cmd + ':' + encodeURIComponent(text || '') + '|' + window.dcBK); },
    find: function (inp, now) {
      clearTimeout(t);
      var v = inp.value.slice(0, 60);
      t = setTimeout(function () { dcParty.send('find', v); }, now ? 0 : 220);
    },
    clear: function () { var i = document.getElementById('pp-find'); if (i) { i.value = ''; dcParty.find(i, 1); i.focus(); } },
    focus: function () { var i = document.getElementById('pp-find'); if (i) { i.focus(); i.placeholder = 'Find one'; } },
    srch: function () { var r = document.getElementById('pp-srch'); if (r) { r.hidden = !r.hidden; if (!r.hidden) { r.querySelector('input').focus(); } } }
  };
})();
"""


def party_html(v):
    """3.9.5 round three, You › Pip Party (Sam's): the games up top, the one
    the TV opens on lit; what to play on, picked on the map (Insights' own
    tiles, the tag tree or the decks) or found by name; which of their
    cards; the picks at the foot; Host. Once the TV's open, its code and
    where phones join. v: gamenight_flow.tab_view. Names (tags, decks,
    kept picks) are mine, the code the server's: escaped."""
    e = _html.escape
    v = v or {}
    burst = " burst" if v.get("burst") else ""
    tv = v.get("open")
    if tv:
        fx = '<span class="pp-fx" aria-hidden="true">' + "".join(f'<i style="--r:{k * 36}deg"></i>' for k in range(10)) + "</span>" if burst else ""
        url = str(tv.get("url") or "")
        shown = _re.sub(r"^https?://", "", url)
        return (f'<div class="pp{burst}">{fx}<div class="pp-open"><b>On the TV &middot; {e(str(tv.get("code") or ""))}</b>'
                f'<span>Phones: <span class="pp-url">{e(shown)}</span> '
                f'<a href="#" onclick="{_pycmd("party:copy")}">Copy link</a></span></div></div>')
    first = v.get("first")
    boxes = ""
    for g in v.get("games") or []:
        gid, n, need = g["id"], g.get("n"), int(g.get("need") or 1)
        thin = n is not None and n < need
        one, many = _GAME_UNIT.get(gid, ("", ""))
        count = "&hellip;" if n is None else "Not enough cards" if thin else f"{n:,} {one if n == 1 else many}"
        on = " on" if g.get("first") else ""
        act = (f' href="#" onclick="{_pycmd("party:game:" + gid)}"' if not thin else ' aria-disabled="true"')
        boxes += (f'<a class="pp-gm g-{e(gid)}{on}{" thin" if thin else ""}{" just" if g.get("just") and on else ""}"{act} aria-pressed="{"true" if on else "false"}">'
                  f'<span class="pp-first">First up</span><span class="pp-art" aria-hidden="true">{_party_art(gid)}</span>'
                  f'<b>{e(g["label"])}</b><span class="pp-k">{e(_GAME_KIND.get(gid, ""))}</span><span class="pp-n">{count}</span></a>')
    kept = "".join(f'<a class="pp-kb" href="#" onclick="{_pycmd(f"party:kept:{i}")}">{e(k)}'
                   f'<i class="x" role="button" aria-label="Forget {e(k)}" onclick="event.stopPropagation();{_pycmd(f"party:forget:{i}")}">&times;</i></a>'
                   for i, k in enumerate(v.get("kept") or []))
    kept = f'<div class="pp-kept"><span>Kept:</span>{kept}</div>' if kept else ""
    by = v.get("by") or "sys"

    def picker(cmd, label, opts, on):
        return word_pick(f"party:{cmd}", label, opts, on)
    head = (f'<div class="pp-mh"><div class="ik">What you know <span class="pp-by">&middot; by '
            f'{picker("by", "Split by", (("sys", "Systems"), ("tag", "Tags"), ("deck", "Decks")), by)}</span></div>'
            f'<input id="pp-find" type="text" placeholder="Find a tag or deck" aria-label="Find a tag or deck" autocomplete="off" '
            f'value="{e(str(v.get("find") or ""))}" oninput="dcParty.find(this)" '
            f'onkeydown="if(event.key===\'Escape\'){{this.value=\'\';dcParty.find(this,1);}}"></div>')
    decks = ""
    if by == "sys" and len(v.get("decks") or []) > 1 and not v.get("find"):
        decks = '<div class="pp-dt">' + "".join(
            f'<a href="#" class="{"on" if int(d["did"]) == int(v.get("did") or 0) else ""}" onclick="{_pycmd("party:deck:" + str(int(d["did"])))}">'
            f'{e(str(d["name"]))}</a>' for d in v["decks"]) + "</div>"
    of = (f'<div class="pp-of">Of their cards: {picker("of", "Which of their cards", list(v.get("ofs") or []), v.get("of"))}'
          f'<a href="#" class="pp-as" onclick="dcParty.srch();return false;">As a search &rsaquo;</a></div>'
          f'<div id="pp-srch" class="pp-srch" hidden><input type="text" aria-label="As a search" value="{e(str(v.get("search") or ""))}" '
          f'onchange="dcParty.send(\'search\', this.value.slice(0,400))"></div>')
    chips = ""
    for j, p in enumerate(v.get("picks") or []):
        deck = f' &middot; {e(p["deck"])}' if p.get("kind") == "sys" and p.get("deck") else ""
        flip = "" if p.get("kind") == "search" else f' onclick="{_pycmd(f"party:out:{j}")}"'
        chips += (f'<span class="pp-pk{" out" if p.get("out") else ""}" role="button"{flip} '
                  f'title="{"Put it back in" if p.get("out") else "Leave these out"}">{"Not " if p.get("out") else ""}{e(p["name"])}{deck}'
                  f'<a class="x" href="#" aria-label="Drop {e(p["name"])}" onclick="event.stopPropagation();{_pycmd(f"party:drop:{j}")}">&times;</a></span>')
    n = int(v.get("n") or 0)
    count = f'{e(v["all"])} &middot; {n:,} card{"" if n == 1 else "s"}' if v.get("all") else f'{n:,} card{"" if n == 1 else "s"}'
    if v.get("loading"):
        count = "Reading your cards&hellip;"  # the map's reading follows the tab (gamenight_flow.tab_view)
    links = (f'<span class="pp-ln"><a href="#" onclick="{_pycmd("party:keep")}">Keep this pick</a>'
             f'<a href="#" onclick="{_pycmd("party:clear")}">Clear</a></span>') if v.get("picks") else ""
    said = str(v.get("said") or "")
    busy = bool(v.get("busy"))
    why = ("" if first or not n or v.get("loading") else "Too few cards for any game here.") if not said else said
    why = f'<span class="pp-said{"" if busy else " bad"}" role="status">{e(why)}</span>' if why else ""
    label = dict(_GAMES).get(first, "")
    host = (f'<a href="#" class="pp-host" onclick="{_pycmd("party:host")}">Host {e(label)}</a>' if first and n and not busy
            else f'<span class="pp-host off" aria-disabled="true">Host{" " + e(label) if label else ""}</span>')
    foot = (f'<div class="pp-foot"><div class="pp-say"><b>{count}</b>'
            f'{f"<div class=pp-picks>{chips}</div>" if chips else ""}{links}{why}</div>{host}</div>')
    return (f'<div class="pp{burst}"><div class="pp-gms">{boxes}</div>{kept}{head}{decks}'
            f'{party_map_html(v)}{of}{foot}</div>')
