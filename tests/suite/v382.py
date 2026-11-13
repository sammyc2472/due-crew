"""The suite: 3.8.2 to 3.9.1 (and 3.9.12's foundations): the closet, the fridge, sheets, the Qt look."""

from due_crew import board
import datetime
import fakes
import json
import os
import re
import sqlite3
import srcs
import sys
import tempfile
import types

from .base import KK, REPO, SUITE_FILE, TODAY, as_board, check, fetch_as, make_user_col, new_client, world
from .plans import _PlanGlue
from .v380 import _ahead_sample, _bingo_card, dc_mw
from .board import _day, _patched_due_crew, _plan_col
from .v381 import _v381_world


def test_room_widget_pips_v3821():
    """3.8.21 (Sam: "no pips here either!"): a crew room's people are their
    Pips in every widget that showed their initials: the top bar's chip (four,
    then +N), the margin card and the break (a crowd wraps, hats clear the line
    above), as on the room's card. Pip off: the initials, as before. The
    widgets run in node on a small fake page; skipped without node."""
    import shutil
    import subprocess
    from due_crew import room_model as rm, sev
    utc = datetime.timezone.utc
    now = datetime.datetime.now(utc)
    js_of = lambda kind: rm.widget_js(kind, rm.widget_data(rm.make_room("sam", now), [], ("#2e7d32", "#7cc47f")))
    check("every crew room widget draws its people one way (Pips, or the initials with Pip off), at the faces' size",
          "fc = people(c, 18, 4);" in js_of("chip") and "root.appendChild(people(c, 26, 0, true));" in js_of("gutter")
          and "box.appendChild(people(c, 32, 0, true));" in js_of("break") and "who.appendChild(people(c, 24));" in js_of("card")
          and "faces(c, " not in rm._RUNTIME.replace("return faces(c, size);", "").replace("function faces(c, size)", ""))
    node = shutil.which("node")
    if not node:
        print("SKIP room widget Pips: no node")
        return
    names = [("sam", "Sammy", True), ("lu", "Lu <b>", False), ("dre", "Dre", False),
             ("ana", "Ana", False), ("kai", "Kai", False), ("nia", "Nia", False)]

    def ents(room, n):
        return [{"user_id": u, "name": nm, "you": y, "accent": "blue", "look": ["cap"] if u == "lu" else [], "room": room}
                for u, nm, y in names[:n]]
    before = rm.make_room("sam", now + datetime.timedelta(minutes=20))
    fif = rm.make_fifteen("sam", now - datetime.timedelta(minutes=3))
    cases = [(kind, n, pip, before) for kind in ("chip", "gutter", "break", "card") for n, pip in ((2, True), (6, True), (2, False))]
    cases.append(("chip", 1, True, fif))
    progs = [rm.widget_js(kind, rm.widget_data(room, ents(room, n), board.accent_pair("green"), sev=pip))
             for kind, n, pip, room in cases]
    dom = r"""
class Sty { constructor() { this.cssText = ''; } setProperty(k, v) { this[k] = v; } }
class E {
  constructor(tag) { this.tag = tag; this.kids = []; this.style = new Sty(); this.textContent = ''; this.title = ''; }
  appendChild(k) { this.kids.push(k); k.parentNode = this; return k; }
  set innerHTML(h) { this.html = h; this.kids = []; const m = /^<([a-z]+)/.exec(h); if (m) { this.kids.push(new E(m[1])); } }
  get firstChild() { return this.kids[0] || null; }
  setAttribute(k, v) { this[k] = v; } querySelectorAll() { return []; } addEventListener() {} remove() {}
}
const body = new E('body'); body.className = '';
globalThis.window = globalThis; window.addEventListener = () => {};
globalThis.document = { body, head: new E('head'), createElement: (t) => new E(t), getElementById: () => null,
  querySelector: () => null, documentElement: { classList: { contains: () => false } } };
globalThis.setInterval = () => 0; globalThis.setTimeout = () => 0; globalThis.pycmd = () => {};
const walk = (e, out) => { out.push(e); e.kids.forEach((k) => walk(k, out)); return out; };
"""
    out = []
    for prog in progs:
        run = subprocess.run([node, "-e", dom + prog + r"""
const all = walk(body, []);
const pips = all.filter((e) => e.style['--sv-d'] !== undefined);
console.log(JSON.stringify({
  pips: pips.map((e) => e.title), slot: pips.length ? /width:(\d+)px/.exec(pips[0].style.cssText)[1] : null,
  initials: all.filter((e) => e.tag === 'i' && /border-radius:50%/.test(e.style.cssText)).map((e) => e.textContent),
  more: all.filter((e) => e.tag === 'small' && /^\+/.test(e.textContent)).map((e) => e.textContent),
  row: pips.length ? pips[0].parentNode.style.cssText : '' }));"""], capture_output=True, text=True, timeout=60)
        try:
            out.append(json.loads(run.stdout))
        except ValueError:
            out.append({"error": run.stdout[-300:] + run.stderr[-1500:]})
    got = {(kind, n, pip, room is fif): o for (kind, n, pip, room), o in zip(cases, out)}
    check("the widgets run in node", all("error" not in o for o in out), [o for o in out if "error" in o])
    six = ["You", "Ana", "Dre", "Kai", "Lu <b>", "Nia"]
    check("chip, Pip on: each person is their Pip, host first, a name only a label; four, then +2",
          got[("chip", 2, True, False)]["pips"] == ["You", "Lu <b>"] and got[("chip", 2, True, False)]["more"] == []
          and got[("chip", 6, True, False)]["pips"] == six[:4] and got[("chip", 6, True, False)]["more"] == ["+2"]
          and got[("chip", 2, True, False)]["initials"] == [], got)
    check("…each Pip's slot is the face it replaces (chip 18, margin card 26, break 32, room card 24)",
          [got[(k, 2, True, False)]["slot"] for k in ("chip", "gutter", "break", "card")] == ["18", "26", "32", "24"]
          and all(round(round(f / sev.SLOT[0]) * sev.SLOT[0]) == f for f in (18, 26, 32, 24)), got)
    check("margin card and break: everyone (no +N), wrapping, with room above for a hat",
          all(got[(k, 6, True, False)]["pips"] == six and got[(k, 6, True, False)]["more"] == []
              and "flex-wrap:wrap" in got[(k, 6, True, False)]["row"] and "padding-top:" in got[(k, 6, True, False)]["row"]
              for k in ("gutter", "break")), got)
    check("Pip off: the initials, as before, in every widget",
          all(got[(k, 2, False, False)]["pips"] == [] and got[(k, 2, False, False)]["initials"] == ["S", "L"]
              for k in ("chip", "gutter", "break", "card")), got)
    check("a fifteen's chip: its own Pip, no people", got[("chip", 1, True, True)]["pips"] == []
          and got[("chip", 1, True, True)]["initials"] == [], got)


def test_plan_card_squad_pips_v3822():
    """3.8.22 (Sam: "under squad we haven't switched to pips"): the plan
    card's squad line draws who showed up as their Pips, as the Squads tab
    does: mine in my look (it opens the closet), a crewmate's in their colour
    and look, anyone else plain. The board's summary names whose faces they
    are (who, uids, one for one); Pip off, or a server without who, the
    emojis as before. Still one request."""
    from due_crew import sev
    from due_crew.backend import shapes as S
    # the fake (the Worker's twin): who beside faces, one for one
    store = world({"sam": "Sammy", "dre": "Dre", "zed": "Zed"}, {"sam": ["dre"], "dre": ["sam"]})
    store.today = TODAY.isoformat()
    for u in ("sam", "dre", "zed"):
        store.team[("abcdefghij", u)] = {"joined": 1, "days": [store.today] if u != "zed" else [], "play": None}
    t = store._teams_for_board("zed")["abcdefghij"]
    check("server: the board's squad summary names whose faces they are, one for one",
          sorted(t["who"]) == ["dre", "sam"] and len(t["who"]) == len(t["faces"]) == t["shown"] == 2, t)
    # the client keeps who beside faces: junk is "", never dropped (they stay one for one)
    c = S.clean_teams({"abcdefghij": {"shown": 3, "of": 5, "faces": ["🐢", "", "🐸"], "who": ["dre", "<b>", 7]}})["abcdefghij"]
    check("client: who kept one for one with faces, junk as nothing",
          c["who"] == ["dre", "", ""] and c["faces"] == ["🐢", "", "🐸"], c)
    check("client: an older server's summary has no who", S.clean_teams({"abcdefghij": {"shown": 1, "faces": ["🐢"]}})["abcdefghij"]["who"] == [])

    people = {"sam": {"user_id": "sam", "name": "Sammy", "you": True},
              "dre": {"user_id": "dre", "name": "Dre", "accent": "blue", "look": ["dino"]}}
    cfg = {"accent": "amber", "sev_look": ["cap"], "sev_closet": {"cap": "2026-09-01"}}
    summ = {"shown": 3, "of": 11, "faces": ["🦊", "🐢", "🐸"], "who": ["sam", "dre", "zed"]}
    line = board._squad_line("p1", {"summary": summ, "unread": 0}, people, cfg)
    pips = line[line.index('class="pips"'):line.index("Squad:")]
    blue, amber, plain = board.accent_pair("blue"), board.accent_pair("amber"), board.accent_pair(None)
    check("line: who showed up are Pips, in order, and no emoji",
          pips.count("dc-rsev") == 3 and not any(x in line for x in ("🦊", "🐢", "🐸"))
          and "Squad: 3 of 11 showed up" in line and "duecrew:squadplan:p1" in line, line[:300])
    exact = [board.squad_pip(u, n, y, people, cfg, board.PCREW_PIP, k)
             for k, (u, n, y) in enumerate((("sam", "Sammy", True), ("dre", "Dre", False), ("zed", "A squadmate", False)))]
    check("…each the Squads tab's own Pip, look and all (mine and the crewmate's dressed, the stranger plain)",
          all(x and x in pips for x in exact) and len(exact[1]) > len(exact[2]) and "duecrew:closet" in exact[0]
          and f"--rs-l:{amber[0]}" in exact[0])
    check("…a crewmate's in their colour and look; anyone else plain, labelled as a squadmate",
          f"--rs-l:{blue[0]}" in pips and pips.count(f"--rs-l:{plain[0]}") == 1 and "A squadmate’s Pip" in pips
          and "Dre’s Pip" in pips, pips[:400])
    check("…in that order (me, the crewmate, the stranger)",
          pips.index(f"--rs-l:{amber[0]}") < pips.index(f"--rs-l:{blue[0]}") < pips.index(f"--rs-l:{plain[0]}"))
    check("…each blinking at its own moment, as a room's seats (3.9.0, Sam: on bingo they blinked as one)",
          all(sev.blink_css(k) in exact[k] for k in range(3)) and len({sev.blink(k) for k in range(3)}) == 3
          and "--sv-d" not in board.squad_pip("dre", "Dre", False, people, cfg), [x[:160] for x in exact])
    off = board._squad_line("p1", {"summary": summ, "unread": 0}, people, dict(cfg, sev=False))
    old = board._squad_line("p1", {"summary": dict(summ, who=[]), "unread": 0}, people, cfg)
    bare = board._squad_line("p1", {"summary": summ, "unread": 0})
    check("Pip off, a server without who, or no settings: the emojis, as before",
          all("🦊🐢🐸 Squad: 3 of 11" in x and "dc-rsev" not in x for x in (off, old, bare)), [off, old, bare])

    # the board end to end: You › Plans has the crew it needs
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    ents = [dict(x, accent="blue", look=["dino"]) if x["user_id"] == "dre" else x
            for x in new_client(store, "sam", "Sammy").fetch_board(labels)["entries"]]
    card = {"id": "p1", "title": "Plan", "tabs": {"unread": 0, "summary": summ}}
    plans = {"cards": [card]}
    html = board.render({"entries": ents, "labels": labels, "tomorrow": "", "pending": []}, dict(cfg, due_show=False), 0,
                        plans=plans, you={"tab": "plans", "plans": plans})
    sq = html[html.index('class="pcrew"'):]
    sq = sq[:sq.index("</div>")]
    check("board: the plan card's squad line, Pips from the board's own crew",
          sq.count("dc-rsev") == 3 and f"--rs-l:{blue[0]}" in sq and "#due-crew .pcrew .pips" in html, sq[:300])


def test_pips_where_emojis_were_v3822():
    """3.8.22 (Sam: "all the places where there are emojis we should reflect
    pips, including bottom bars, we can make the bingo stamps bigger.
    remove emojis from the friends dialog. invites and text shares can stay
    as is"): the review screen's chip, a squadmate's card, Settings › You,
    the bingo stamps, and on the site the account page, the exam rail and
    who added me back. Pip off: the emojis, as before. A Pip is our own
    markup; a name is only ever its label, escaped."""
    import shutil
    import subprocess
    from due_crew import cards as K, sev
    from due_crew.app import _state
    blue, plain = board.accent_pair("blue"), board.accent_pair(None)
    # ---- the review screen: who asked, or knows it, as their Pip ----
    saved = dict(_state)
    try:
        _state["entries"] = [{"user_id": "me", "name": "Sammy", "you": True},
                             {"user_id": "dre", "name": "Dre <b>Ng", "emoji": "🐢", "accent": "blue", "look": ["dino"]},
                             {"user_id": "mo", "name": "Mo", "emoji": ""},
                             {"user_id": "zz", "name": '"><img src=x onerror=alert(1)>', "look": ['"><b>x', "dino\"><i>"],
                              "accent": "red;}</style>"}]
        pips = K.pips_by_uid({})
        off = K.pips_by_uid({"sev": False})
    finally:
        _state.clear()
        _state.update(saved)
    hostile = pips.pop("zz")
    check("chip: a hostile name, look or accent never becomes markup in a Pip",
          not any(x in hostile["svg"] for x in ("<img", "<b>", "<i>", "</style>")) and hostile["a"] == list(plain)
          and "&lt;img" in hostile["svg"], hostile["svg"][:300])
    check("chip: each crewmate's Pip, in their colour, a name only its label (escaped); none of mine; Pip off, none",
          sorted(pips) == ["dre", "mo"] and pips["dre"]["a"] == list(blue) and pips["mo"]["a"] == list(plain)
          and "Dre &lt;b&gt;Ng’s Pip" in pips["dre"]["svg"] and "<b>" not in pips["dre"]["svg"]
          and len(pips["dre"]["svg"]) > len(pips["mo"]["svg"]) and off == {}, pips.get("dre", {}).get("svg", "")[:200])
    names = {"dre": ("Dre <b>Ng", "🐢"), "mo": ("Mo", "")}
    knows = K.chip_view({"knows": ["dre", "mo"], "tips": []}, [], names, pips=pips)
    asked = K.chip_view(None, [], names, asks=[("dre", 1, "why?")], pips=pips)
    old = K.chip_view({"knows": ["dre"], "tips": []}, [], names)
    check("chip: knows and asked lead with the Pip, no emoji in the words; without pips, the emoji as before",
          knows["text"] == "Dre and 1 more know this" and knows["pip"] == pips["dre"] and knows["sevcss"] == sev.CSS
          and asked["text"] == "Dre: “why?”" and asked["pip"] == pips["dre"]
          and old["text"] == "🐢 Dre knows this" and "pip" not in old, (knows, asked["text"], old["text"]))
    bar, card = K.chip_js(knows), K.float_js(dict(knows, accent=["#2e7d32", "#7cc47f"]))
    check("chip: the bar and the card both draw it (its own markup, the words still text)",
          all("p.innerHTML = D.pip.svg" in x and "pip(" in x and "t.textContent = folded ? D.fold : D.text" in bar for x in (bar, card))
          and "__PIP__" not in bar + card and "dc-sev-css-k" in bar)
    node = shutil.which("node")
    if node:
        ok = subprocess.run([node, "--check"], input=bar + "\n;" + card, capture_output=True, text=True, timeout=30)
        check("chip: its scripts parse", ok.returncode == 0, ok.stderr[-400:])

    # ---- a squadmate's card: a plain Pip ----
    fig = board.card_sev({"name": "igk"}, {})
    sq = board.stranger_card_js({"uid": "u1", "name": "igk <i>", "emoji": "🐢", "reviews": 1, "time_ms": 1, "retention": None,
                                 "streak": 1, "rank": 1, "squad": "orca", "today": True, "pending": False,
                                 "knocked_me": False, "founder_me": False, "sev": fig})
    check("squadmate card: a plain Pip, in the default colour, no emoji; the name escaped",
          json.dumps(fig)[1:40] in sq and f"--sv-a: {plain[0]}" in fig and "🐢" not in sq and "\\ud83d\\udc22" not in sq
          and "igk &lt;i&gt;" in sq, sq[:300])
    check("squadmate card: Pip off, no figure: the emoji, as before", board.card_sev({"name": "igk"}, {"sev": False}) is None)

    # ---- Settings › You: my Pip, opening the closet ----
    view = {"tab": "you", "signed_in": True, "name": "Sam", "emoji": "🦊", "status": "", "sync": "", "crew": 1,
            "squads": [], "decks": []}
    you = board.settings_html(view, {"accent": "blue", "sev_look": ["cap"], "sev_closet": {"cap": "2026-09-01"}})
    off = board.settings_html(view, {"sev": False})
    check("Settings › You: my Pip in my colour and look, opening the closet; Emoji… stays",
          'class="st-pip"' in you and "duecrew:closet" in you and "🦊" not in you and f"--sv-a: {blue[0]}" in you
          and 'aria-label="Your Pip"' in you and "setemoji" in you and sev.CSS in you)
    check("Settings › You: Pip off, my emoji as before", "🦊" in off and "st-pip" not in off)

    # ---- squad bingo: who stamped a square, as a bigger Pip ----
    from due_crew import bingo as B
    sqs = [{"id": f"q{i}", "fam": "often", "diff": "m", "icon": "x", "title": "T", "rule": "R", "detail": "D",
            "type": "days", "params": {"days": 1}} for i in range(8)]
    bcard = B.clean_card(_bingo_card(squares=sqs))
    rows = [{"user_id": u, "emoji": "🐢", "day": "2026-09-01", "joined": "2026-01-01",
             "play": {"wk": 202636, "s": 0b1}} for u in ("me", "dre", "zed")]
    ev = B.evaluate(bcard, rows)
    bv = {"card": bcard, "ev": ev, "names": {"me": ("Sammy", "🦊"), "dre": ("Dre", "🐢"), "zed": ("Zed", "🐸")}, "me": "me",
          "squad": "s", "squad_id": "s", "closest": B.closest(bcard, ev), "progress": [], "new": False, "withheld": [],
          "today": "2026-09-01"}
    people = {"me": {"user_id": "me", "you": True}, "dre": {"user_id": "dre", "accent": "blue", "look": ["dino"]}}
    cfg = {"accent": "amber"}
    full = board.bingo_html(bv, cfg, people=people)
    sq0 = full[full.rindex("<button", 0, full.index('data-i="0"')):]
    sq0 = sq0[:sq0.index("</button>")]
    amber = board.accent_pair("amber")
    check("bingo: who stamped are Pips (mine, a crewmate's dressed, a squadmate plain), a size up from the emoji, no emoji",
          sq0.count('class="st sp"') == 3 and f"--rs-l:{amber[0]}" in sq0 and f"--rs-l:{blue[0]}" in sq0
          and f"--rs-l:{plain[0]}" in sq0 and not any(x in sq0 for x in ("🦊", "🐢", "🐸")) and "stamped" in sq0
          and f"width:{round(board.STAMP_PIP * sev.SLOT[0])}px" in sq0 and board.STAMP_PIP * sev.SLOT[0] > 22, sq0[:400])
    check("bingo: a square's stamps each blink at their own moment when it's pointed at (3.9.0, Sam: \"they all blink at the same time\")",
          all(sev.blink_css(k) in sq0 for k in range(3)) and sq0.count("--sv-b:") == 3, sq0[:400])
    check("bingo: a square is a button, so no stamp is a link (mine doesn't open the closet from here)",
          "<a " not in sq0 and "duecrew:closet" not in sq0)
    plain_card = board.bingo_html(bv, {"sev": False}, people=people)
    p0 = plain_card[plain_card.index('data-i="0"'):]
    check("bingo: Pip off, the emojis as before", "🐢" in p0[:p0.index("</button>")] and "st sp" not in plain_card)

    # ---- the site: the account page, the exam rail, who added me back ----
    app_js = open(os.path.join(os.path.dirname(SUITE_FILE), "..", "site", "public", "app.js"), encoding="utf-8").read()
    check("site: one helper draws someone's Pip by uid, as squad_pip does; the account page, the exam rail and "
          "who added me back use it, the emoji only without sev.js",
          "function pipFor(uid, name, crew, look)" in app_js
          and "pipFor(me.uid, me.name, [], st?.settings?.sev_look) || face(me.emoji, me.name)" in app_js
          and "pipFor(f.uid, f.name, crew) || face(f.emoji, f.name)" in app_js
          and "const pip = pipFor(x.uid, x.name, crew); return pip ? [pip, x.name]" in app_js)


def test_closet_flow_v382():
    """3.8.2: the facts come from the revlog (the days and hours, read once
    a day, today's fresh), the cards, the board and a few tallies; what's new
    goes in the closet once, the account keeps it (merged thing by thing),
    and a mutual friend's look comes with the board."""
    from due_crew import closet_flow as cf, account
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    days = [TODAY - datetime.timedelta(days=i) for i in range(20)] + [datetime.date(2025, 10, 31), datetime.date(2025, 10, 30)]
    for d in days:
        for hour in (6, 22):
            fakes.add_review(conn, int(datetime.datetime.combine(d, datetime.time(hour)).timestamp() * 1000))
    for cid in range(12):
        fakes.add_card(conn, cid + 1, 1, ctype=2, queue=2, ivl=30, lapses=9 if cid < 3 else 0)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    files, saved_files = tempfile.mkdtemp(), cf._profile_files
    cf._profile_files = lambda: files
    cf._RF["key"] = None
    try:
        f = cf.revlog_facts(col)
        check("the revlog's facts: days, the longest run, mornings and evenings, Halloween, reviews, learned, leeches",
              f["days"] == 22 and f["run"] == 20 and f["mornings"] == 22 and f["evenings"] == 22 and f["halloween"] == 2
              and f["reviews"] == 44 and f["learned"] == 12 and f["leeches"] == 3 and f["back7"] == 1, f)
        fakes.add_review(conn, int(datetime.datetime.combine(TODAY, datetime.time(9)).timestamp() * 1000))
        check("the days before the last week are kept (3.9.1: closet_days.json); today's hours count each time",
              cf.revlog_facts(col)["reviews"] == 45 and cf._RF["key"] == os.path.join(files, cf.HISTORY))
    finally:
        cf._profile_files = saved_files
        cf._RF["key"] = None
    t = cf.clean_tallies({"fifteens": 3, "rooms": -1, "cheered": ["a", 5, "b"], "clear_last": "2026-09-01", "crew": True})
    check("the tallies, as this add-on writes them or less", t == {"fifteens": 3, "cheered": ["a", "b"], "clear_last": "2026-09-01"}, t)
    bf = cf.board_facts({"squads": [{"id": "s1", "founder": "me"}, {"id": "s2"}]}, [], "me",
                        [{"id": "p1", "doc": {"units": [{"id": "u1"}, {"id": "u2"}], "events": [{"day": "2026-08-01", "name": "Exam"}]}}],
                        {"p1": {"u1": [5, 5, 5], "u2": [3, 3, 3]}}, "2026-09-01", {"sprout": "2025-08-01"})
    check("the board's facts: squads (one I started), a plan followed, done, exam and all; a year with my Pip",
          bf == {"squads": 2, "founder": 1, "plans": 1, "plan_done": 1, "plan_exam": 1, "followed": 0, "sev_days": 396}, bf)
    from due_crew.wrap import _wrap_data
    w = _wrap_data()
    w["closet"] = {}
    saved = (cf._save,)
    cf._save = lambda: None
    try:
        cf.note_fifteens(4, datetime.datetime(2026, 9, 1, 7, tzinfo=datetime.timezone.utc).astimezone())
        cf.note_fifteens(1)
        cf.note_room(True)
        cf.note_room(False)
        for u in ("a", "b", "a"):
            cf.note_cheer(u, "2026-09-01")
        cf.note_cheer("c", "2026-09-02", big=True)
        cf.note_cheered()
        cf.note_bingo(1, False)
        crew = [{"you": True}, {"you": False, "days": {"2026-09-02": {"studied": True, "reviews": 3}}}]
        cf.note_day("2026-09-01", crew, True, 0)
        cf.note_day("2026-09-02", crew, True, 0)
        cf.note_day("2026-09-02", crew, True, 0)
        cf.note_day("2026-09-04", crew, True, 5)
        t = cf._tallies()
        check("Fifteens (how many, most in one go, the mornings'), rooms with the crew, cheers (whom, which days, a big streak), a cheer landing, a line",
              t["fifteens"] == 5 and t["fifteen_go"] == 4 and t["rooms"] == 1 and t["cheered"] == ["a", "b", "c"]
              and t["cheer_days"] == ["2026-09-01", "2026-09-02"] and t["big_cheer"] == 1 and t["cheered_by"] == 1
              and t["bingo_line"] == 1 and t["fifteen_am"] in (0, 4), t)
        check("a day with nothing left due, a run of them, once a day; a day the whole crew studied (a crewmate a day ahead too); the most crewmates",
              t["clear"] == 2 and t["clear_run"] == 2 and t["crew_day"] == 2 and t["crew"] == 1, t)
        cf.note_day("2026-08-30", crew, True, 5)  # their day two ahead isn't my today
        check("a crewmate's day two ahead isn't today", cf._tallies()["crew_day"] == 2)
    finally:
        cf._save = saved[0]
        w["closet"] = {}
    check("the account keeps the look and the closet, cleaned",
          account.clean({"sev_look": ["cap", "nope", "dino"], "sev_closet": {"cap": "2026-01-01", "x": "2026-01-01"}})
          == {"sev_look": ["cap", "dino"], "sev_closet": {"cap": "2026-01-01"}}
          and {"sev_look", "sev_closet"} <= set(account.ACCOUNT_KEYS))
    m = account.merge3({"sev_closet": {}}, {"sev_closet": {"cap": "2026-02-01"}, "sev_look": ["cap"]},
                       {"sev_closet": {"beanie": "2026-01-01"}, "sev_look": ["beanie"]})
    check("two computers earning at once: the closet merges thing by thing (nothing earned is lost); the look is mine",
          m["sev_closet"] == {"cap": "2026-02-01", "beanie": "2026-01-01"} and m["sev_look"] == ["cap"], m)
    store = world({"alice": "Alice", "bob": "Bob"}, {"alice": ["bob"], "bob": ["alice"]})
    store.settings["bob"] = {"v": 1, "at": "x", "settings": {"sev_look": ["dino", "headphones"], "accent": "teal"}, "rev": 1}
    cl = new_client(store, "alice")
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    got = cl.fetch_board(labels)
    bob = next(e for e in got["entries"] if e["user_id"] == "bob")
    me = next(e for e in got["entries"] if e["you"])
    check("a mutual friend's look comes with the board, as the closet wears it; mine is this computer's",
          bob["look"] == ["dino", "headphones"] and bob["accent"] == "teal" and me["look"] == [], bob)
    store.settings["bob"]["settings"]["sev_look"] = ["<script>"]
    check("a look that isn't names isn't sent",
          next(e for e in cl.fetch_board(labels)["entries"] if e["user_id"] == "bob")["look"] == [])


def _closet_whole(col):
    """3.8.2's read of the closet's revlog facts, the whole revlog by the
    hour (kept here to hold 3.9.1's kept history to it)."""
    from due_crew import closet as C
    cut = int(col.sched.day_cutoff)
    hours = {int(h): int(n) for h, n in col.db.all(
        "SELECT CAST((? - id / 1000) / 3600 AS INTEGER), COUNT(*) FROM revlog "
        "WHERE ease > 0 AND id >= 0 AND id < ? GROUP BY 1", cut - 1, cut * 1000)}
    end = datetime.date.fromtimestamp(cut)
    out = C.from_days({(end - datetime.timedelta(days=h // 24 + 1)).isoformat() for h in hours})
    out.update(C.from_hours([datetime.datetime.fromtimestamp(cut - (h + 1) * 3600) for h in hours]))
    out["reviews"] = sum(hours.values())
    return out


def test_closet_history_v391():
    """3.9.1: Pip's closet keeps the days before the last week in
    closet_days.json, per profile, where every launch read the whole revlog
    by the hour. The facts are the whole read's: the first time, again, in
    a new process, the next day (a day goes in), when a sync brings in a
    phone's last week or older answers, when the clock moves, and from a
    file that isn't one; a second profile the same day gets its own."""
    from due_crew import closet_flow as cf
    at = lambda d, h: int(datetime.datetime.combine(d, datetime.time(h)).timestamp() * 1000)

    def col_with(days, rollover=4):
        conn = sqlite3.connect(":memory:")
        fakes.make_collection(conn)
        for d, hour in days:
            fakes.add_review(conn, at(d, hour))
        fakes.add_review(conn, at(TODAY - datetime.timedelta(days=30), 12), ease=0, rtype=4)  # a set due date: no answer
        return fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY, rollover))

    D = datetime.date
    days = ([(TODAY - datetime.timedelta(days=i), h) for i in range(40) if i % 9 != 4 for h in (6, 22)]
            + [(TODAY - datetime.timedelta(days=i), 1) for i in (2, 11, 25)]
            + [(D(2025, 10, 24), 9), (D(2025, 10, 25), 9), (D(2025, 10, 31), 20), (D(2025, 12, 31), 23), (D(2026, 1, 1), 0),
               (D(2026, 3, 14), 12), (D(2024, 2, 29), 7), (D(2026, 6, 21), 5), (D(2025, 2, 13), 13)])
    col = col_with(days)
    files = tempfile.mkdtemp()
    reads = []
    saved = (cf._profile_files, cf._span, cf._zone)
    real_span = cf._span
    cf._profile_files = lambda: files
    cf._span = lambda c, cut, lo, hi: reads.append(lo) or real_span(c, cut, lo, hi)
    cf._RF.update(key=None, hist=None)

    def same(c, name, whole):
        f, want = cf.revlog_facts(c), _closet_whole(c)
        check(f"closet's history: {name}: the facts are the whole revlog's"
              + (", read whole" if whole else ", without reading it whole"),
              {k: f[k] for k in want} == want and reads.count(0) == whole, ({k: (f[k], want[k]) for k in want if f[k] != want[k]}, reads))
        reads.clear()

    try:
        same(col, "the first time", 1)
        kept = json.load(open(os.path.join(files, cf.HISTORY)))
        same(col, "again", 0)
        cf._RF.update(key=None, hist=None)
        same(col, "a new process, from the file", 0)
        col.sched.day_cutoff += 86400
        fakes.add_review(col.db.conn, at(TODAY + datetime.timedelta(days=1), 10))
        same(col, "the next day, a day added to the file", 0)
        check("closet's history: the file moves on by the day that settled, and only the last week is read fresh",
              json.load(open(os.path.join(files, cf.HISTORY)))["hi"] == kept["hi"] + 86400 * 1000
              and kept["hi"] == (fakes.day_cutoff_for(TODAY) - cf.SETTLED * 86400) * 1000 and kept["days"] == sorted(kept["days"]))
        fakes.add_review(col.db.conn, at(TODAY - datetime.timedelta(days=3), 13))
        same(col, "a phone's reviews from last week", 0)
        fakes.add_review(col.db.conn, at(TODAY - datetime.timedelta(days=33), 13))
        same(col, "a sync bringing in answers from a month ago", 1)
        col.sched.day_cutoff += 86400 + 3600
        same(col, "the clock moved an hour (DST)", 1)
        cf._zone = lambda: [1, 2, ["X", "Y"]]
        same(col, "another time zone", 1)
        cf._zone = saved[2]
        with open(os.path.join(files, cf.HISTORY), "w") as f:
            f.write('{"days": "2026-01-01"}')
        cf._RF.update(key=None, hist=None)
        same(col, "a file that isn't one", 1)
        midnight = col_with([(TODAY - datetime.timedelta(days=7), 22), (TODAY - datetime.timedelta(days=6), 1),
                             (TODAY - datetime.timedelta(days=20), 6)], rollover=0)
        cf._profile_files = lambda: os.path.join(files, "midnight")
        os.makedirs(os.path.join(files, "midnight"), exist_ok=True)
        same(midnight, "an evening over the kept edge (a day that rolls over at midnight)", 1)
        check("closet's history: that evening is one", cf.revlog_facts(midnight)["evenings"] == 1)
        reads.clear()
        one = col_with([(TODAY - datetime.timedelta(days=i), 12) for i in range(10, 30)])
        two = col_with([(TODAY - datetime.timedelta(days=i), 12) for i in range(10, 50, 2)])
        for name, c in (("one", one), ("two", two)):
            os.makedirs(os.path.join(files, name), exist_ok=True)
            cf._profile_files = lambda name=name: os.path.join(files, name)
            same(c, f"profile {name}", 1)
        check("closet's history: a second profile the same day (as many rows) gets its own, not the first's",
              cf.revlog_facts(two)["run"] == 1 and _closet_whole(one)["run"] == 20)
    finally:
        cf._profile_files, cf._span, cf._zone = saved
        cf._RF.update(key=None, hist=None)


def test_closet_site_rows_v382():
    """3.8.2, the twin on duecrew.com: the site's crew rows show each
    person's Pip in the emoji's place, as board.row_sev does. The site never
    draws Pip: site/public/sev.js holds sev.site_kit() (tools/gen_sev_js.py
    writes it; running it again changes nothing) and fills in its blanks
    following the closet's rules, restated in JS (run here in node against
    closet.clean, shown and the drawing itself). My own look comes on /board's
    me, as my crew sees it."""
    import importlib.util
    import random
    import shutil
    import subprocess
    from due_crew import closet as C, closet_art as CA, sev
    store = world({"alice": "Alice", "bob": "Bob"}, {"alice": ["bob"], "bob": ["alice"]})
    check("my look: none saved, none on me", "look" not in store._board("alice", False)["me"])
    store.settings["alice"] = {"v": 1, "at": "x", "settings": {"sev_look": ["cap", "glasses"], "accent": "rose"}, "rev": 1}
    me, bob_sees = store._board("alice", False)["me"], {f["uid"]: f for f in store._board("bob", False)["friends"]}["alice"]
    check("my look on /board's me (board.ts), as my crew sees it, and nothing else of my settings",
          me["look"] == ["cap", "glasses"] == bob_sees["look"] and "accent" not in me, me)
    store.settings["alice"]["settings"]["sev_look"] = ["<b>"]
    check("my look: names only, or nothing", "look" not in store._board("alice", False)["me"])

    kit = sev.site_kit()
    plain = sev.slot(sev.svg("idle", rest=True), sev.ROW_SIZE)
    filled = kit["row"].replace("%B%", "").replace("%F%", "").replace("%H%", "")
    check("the kit: the row's still Pip, a blank each for the back, the front and the hand; empty, it's the plain row Pip",
          all(kit["row"].count(b) == 1 for b in sev.BLANKS) and kit["held"].count("%H%") == 1 and filled == plain
          and "var(--sv-a,#2e7d32)" in plain and 'style="width:18px;height:18px"' in plain and 'class="sv m-idle"' in plain)
    check("the kit: every thing, its place and drawings the closet's; nothing in a drawing a blank could catch",
          list(kit["things"]) == [t["k"] for t in C.THINGS] and kit["slots"] == list(C.SLOTS) and kit["costume"] == C.COSTUME
          and all(v == [C.BY[k]["slot"], list(C.BY[k].get("also") or ()), *CA.ART[k]] for k, v in kit["things"].items())
          and not any("%" in a for v in kit["things"].values() for a in v[2:]))
    js_path = os.path.join(REPO, "site", "public", "sev.js")
    js = open(js_path, encoding="utf-8").read()
    spec = importlib.util.spec_from_file_location("gen_sev_js", os.path.join(REPO, "tools", "gen_sev_js.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    check("site/public/sev.js holds sev.site_kit() as tools/gen_sev_js.py writes it: running it again changes nothing",
          gen.render(js) == js and gen.kit_js() in js)
    site = os.path.join(REPO, "site", "public")
    app_js = open(os.path.join(site, "app.js"), encoding="utf-8").read()
    app_html = open(os.path.join(site, "app.html"), encoding="utf-8").read()
    check("the app page loads sev.js before app.js, from the site itself (the CSP's script-src 'self')",
          '<script src="/sev.js" defer></script>\n<script src="/app.js" defer></script>' in app_html
          and "script-src 'self'" in open(os.path.join(REPO, "site", "src", "index.ts"), encoding="utf-8").read())
    table, presence = app_js.split("  function nameCell(r, period) {")[1], app_js.split("  function presence(people, today, picker = null) {")[1]
    check("the site's crew rows (Today, Week and the days view) say who with Pip, no emoji; so do squads (3.8.21)",
          table.split("\n")[2].strip() == 'const cell = h("td", { class: "nm" }, who(p));'
          and 'h("td", { class: "nm" }, who(r.p), note(r))' in presence.split("  function decks(")[0]
          and "Sev.row(p.look, accentPair(p.accent)" in app_js and "you: true, accent: me?.accent || worn }" in app_js
          and 'squadPip(r, pips) || (r.emoji ? r.emoji + " " : ""), r.name)' in app_js)
    check("…its accent by day and night from board.py's, a name not ours the default's",
          all(f'{k}: [["{v["light"][0]}", ' in app_js and f'["{v["dark"][0]}", ' in app_js for k, v in board.ACCENTS.items())
          and "const accentPair = (name) => { const a = Object.prototype.hasOwnProperty.call(ACCENTS, name) ? ACCENTS[name] : ACCENTS.green; return [a[0][0], a[1][0]]; };" in app_js)

    node = shutil.which("node")
    if not node:
        print("SKIP the site's rows' Pip twin: no node")
        return
    ks = [t["k"] for t in C.THINGS]
    rnd = random.Random(382)
    looks = ([[], None, "beanie", 7, {"cap": 1}, ["cap"], ["<b>", "cap"], ["constructor", "__proto__", "toString", "cap"],
              ["beanie", "nope", 7, "cap", "cap", "dino", "ghost", "glasses"], ["headphones", "mug", "cape"],
              ["scarf", "headphones", "winter"], ["winter", "medal"], ["dino", "glasses"], ["glasses", "dino"], ks, ks[::-1]]
             + [[k] for k in ks] + [[k, "mug", "glasses"] for k in ks]
             + [rnd.sample(ks + ["nope", "x1"], rnd.randint(1, 16)) for _ in range(300)])
    prog = (js + "\nconst looks = JSON.parse(require('fs').readFileSync(0, 'utf8'));\n"
            "console.log(JSON.stringify(looks.map((l) => [Sev.clean(l), Sev.shown(l), Sev.markup(l)])));")
    run = subprocess.run([node, "-e", prog], input=json.dumps(looks), capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(run.stdout)
    except ValueError:
        got = None
    check("sev.js runs in node", got is not None and len(got) == len(looks), run.stderr[-2000:])
    if got is None:
        return
    bad = [(look, g) for look, g in zip(looks, got)
           if g != [C.clean(look), C.shown(look), sev.slot(sev.svg("idle", rest=True, look=look), sev.ROW_SIZE)]]
    check(f"sev.js is the closet's twin: clean, shown and the row's Pip to the byte, on {len(looks)} looks "
          "(each thing alone and with others, clashes, costumes, junk, every thing at once)", not bad, bad[:1])


def test_halloween_week_v3822():
    """3.8.22, Halloween week (Sam's pick, round three: "Line, bats and
    cobweb", shipped before the 24th): 24 to 31 Oct, a line under the
    board's head with this week's days and the five things, the next and
    when; three bats across it on the day's first board; a cobweb when every
    Pip on the crew's rows has a Halloween thing on. Nothing outside the
    week, with Pip off, or once hidden for the year."""
    from due_crew import closet as cl, closet_flow as cf
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    check("Halloween: nothing before the 24th or after the 31st",
          cl.halloween("2026-10-23", [], {}) is None and cl.halloween("2026-11-01", [], {}) is None
          and cl.halloween("nope", [], {}) is None)
    hw = cl.halloween("2026-10-24", ["2025-10-24", "2026-10-23"], {})
    check("the first day: last year's days and the day before don't count; the pumpkin, studying today",
          hw["days"] == 0 and hw["next"] == ("pumpkin", 1) and not hw["today"] and [k for k, _n, _g in hw["things"]] == list(cl.HALLOWEEN), hw)
    hw = cl.halloween("2026-10-26", ["2026-10-24", "2026-10-26"], {"pumpkin": "2026-10-24"})
    check("two days so far, today among them: the witch hat's earned (the days reach it), the bat wings next, a day more",
          hw["days"] == 2 and hw["today"] and [g for _k, _n, g in hw["things"]] == [True, True, False, False, False]
          and hw["next"] == ("batwings", 1), hw)
    hw = cl.halloween("2026-10-30", ["2026-10-30"], {})
    check("the 30th with one day: tomorrow reaches the witch hat, never the mummy",
          hw["next"] == ("witch", 1), hw)
    hw = cl.halloween("2026-10-31", [], {k: "2025-10-31" for k in cl.HALLOWEEN})
    check("all five already mine (a year before): nothing next", hw["next"] is None and all(g for _k, _n, g in hw["things"]), hw)
    check("the cobweb: every Pip in a Halloween thing (a costume shows; a plain Pip doesn't), two at least",
          cl.spooky([["pumpkin"], ["ghost", "glasses"], ["batwings", "cap"]]) and not cl.spooky([["pumpkin"], None])
          and not cl.spooky([["pumpkin"]]) and not cl.spooky([["pumpkin"], ["glasses"]]))
    base = cl.halloween("2026-10-26", ["2026-10-24", "2026-10-25"], {"pumpkin": "2026-10-24"})
    line = board.halloween_html(dict(base, spooky=0, bats=None), {})
    check("the line: its days, the five things as Pips (mine in colour), the next, the closet and a way to hide it",
          "2 days so far" in line and line.count("sv-slot") == 5 and line.count('class="hwk on"') == 2
          and "study today for the bat wings" in line and "duecrew:closet&#x27;" not in line
          and ("pycmd('duecrew:closet|" + KK + "')") in line and ("pycmd('duecrew:closethw|" + KK + "')") in line
          and "hwbat" not in line and "hwweb" not in line and "spooky" not in line, line[:600])
    flying = board.halloween_html(dict(base, spooky=6, bats=1.5), {})
    check("the day's first board: three bats, their flight's place kept across a redraw; the whole crew dressed: cobweb and line",
          flying.count('class="hwbat"') == 3 and "--ago:1.50s" in flying and "hwweb" in flying
          and "all 6 of you dressed up" in flying, flying[:400])
    check("Pip off, or not the week: no line", board.halloween_html(dict(base, bats=0), {"sev": False}) == ""
          and board.halloween_html(None, {}) == "")
    check("the bats never fly with Reduce motion, and never over the logo (only across the line)",
          "@media (prefers-reduced-motion: no-preference)" in board.HW_CSS
          and board.HW_CSS.index("dc-hwbat 4.2s") > board.HW_CSS.index("@media (prefers-reduced-motion: no-preference)")
          and ".dc-hw .hwbat" in board.HW_CSS and "dc-title" not in board.HW_CSS)
    data = {"entries": [{"user_id": "me", "name": "Me", "you": True, "paused": False, "last_updated": "", "exam_date": "",
                         "days": {}, "decks": []}], "pending": [],
            "labels": [(datetime.date(2026, 10, 26) - datetime.timedelta(days=i)).isoformat() for i in range(7)]}
    now = __import__("time").time()
    drawn = board.render(data, {"period": "today"}, now, halloween=dict(base, spooky=0, bats=None))
    check("the board: the line under its head, its sheet with it; without it, neither",
          drawn.count('class="dc-hw"') == 1 and drawn.index('class="dc-head"') < drawn.index('class="dc-hw"')
          and "dc-hwbat" in drawn and "dc-hw" not in board.render(data, {"period": "today"}, now))
    # the glue: my row's days, the crew's looks, the bats once, hidden till next year
    from due_crew.wrap import _wrap_data
    saved = (cf._save, cf.look, cf.have, dict(dc._state))
    cf._save = lambda: None
    cf.look = lambda c=None: ["pumpkin"]
    cf.have = lambda c=None: {"pumpkin": "2026-10-24"}
    w = _wrap_data()
    try:
        w.pop("hw_hidden", None)
        dc._state.pop("hw_bats", None)
        entries = [{"user_id": "me", "you": True, "days": {"2026-10-24": {"studied": True, "reviews": 30}, "2026-10-25": {"reviews": 0}}},
                   {"user_id": "dre", "look": ["ghost"], "days": {}}, {"user_id": "mo", "look": ["witch", "glasses"], "days": {}}]
        v = cf.halloween_view("2026-10-25", entries, {})
        check("the glue: my row's days (a day with no reviews isn't one), every row dressed: cobweb for 3; the bats out",
              v and v["days"] == 1 and v["spooky"] == 3 and v["bats"] is not None and v["bats"] < 1, v)
        dc._state["hw_bats"]["2026-10-25"] -= cf.BATS_SECONDS + 1
        v2 = cf.halloween_view("2026-10-25", entries[:2] + [{"user_id": "mo", "look": None}], {})
        check("a later board the same day: no bats; a plain Pip on a row: no cobweb", v2["bats"] is None and v2["spooky"] == 0, v2)
        check("Pip off: no line", cf.halloween_view("2026-10-25", entries, {"sev": False}) is None)
        swaps = []
        old = (dc._swap, dc._rerender, dc._board_on_screen)
        dc._swap, dc._rerender, dc._board_on_screen = (lambda c, focus=None: swaps.append(1)), (lambda: swaps.append(2)), (lambda: True)
        dc._state["labels"] = ["2026-10-25"]
        try:
            dc._on_js(False, as_board("duecrew:closethw"), DeckBrowser())
        finally:
            dc._swap, dc._rerender, dc._board_on_screen = old
        check("its ×, sent as the board sends it: hidden for 2026 (the board redraws), back next year",
              w.get("hw_hidden") == "2026" and swaps and cf.halloween_view("2026-10-25", entries, {}) is None
              and cf.halloween_view("2027-10-25", entries, {}) is not None, (w.get("hw_hidden"), swaps))
    finally:
        cf._save, cf.look, cf.have = saved[:3]
        dc._state.clear()
        dc._state.update(saved[3])
        w.pop("hw_hidden", None)


def test_year_counts_v3822():
    """3.8.22 (Sam: "Start the year counts in the next release: Yes"): the
    closet's tallies keep a year too, for Wrapped: Fifteens and the hours
    they began, rooms with the crew, cheers sent and got, crew days, each
    squad card's lines once, and the days each thing Pip has on was worn,
    once a day. Six years at most, cleaned like the rest; nothing sent."""
    from due_crew import closet_flow as cf
    from due_crew.wrap import _wrap_data
    from due_crew.app import _state
    w = _wrap_data()
    saved = (cf._save, cf.look, w.get("closet"), list(_state.get("labels") or []))
    cf._save = lambda: None
    cf.look = lambda c=None: ["dino"]
    w["closet"] = {}
    _state["labels"] = ["2026-10-25"]
    try:
        cf.note_fifteens(3, datetime.datetime(2026, 10, 25, 20, 5).astimezone())
        cf.note_fifteens(1)
        cf.note_room(True)
        cf.note_room(False)
        cf.note_cheer("dre", "2026-10-25")
        cf.note_cheer("mo", "2026-10-25")
        cf.note_cheered()
        for lines, wk in ((1, "202643:s1"), (2, "202643:s1"), (1, "202643:s1"), (1, "202644:s1")):
            cf.note_bingo(lines, False, wk)
        crew = [{"you": True}, {"you": False, "days": {"2026-10-25": {"studied": True, "reviews": 3}}}]
        cf.note_day("2026-10-25", crew, True, 0)
        cf.note_day("2026-10-25", crew, True, 0)
        cf.look = lambda c=None: ["pumpkin", "glasses"]
        cf.note_day("2026-10-26", crew, True, 0)
        y = cf.year_counts(2026)
        check("the year: Fifteens and their hour, rooms with the crew, cheers sent and got, a card's lines once (its most), crew days",
              y.get("fifteens") == 4 and y.get("hours") == {"20": 3} and y.get("rooms") == 1 and y.get("cheers_sent") == 2
              and y.get("cheered_by") == 1 and y.get("bingo") == {"202643:s1": 2, "202644:s1": 1} and y.get("crew_days") == 1, y)
        check("what Pip wore, a day each, once a day (a costume alone while it's on)",
              y.get("worn") == {"dino": 1, "pumpkin": 1, "glasses": 1} and y.get("worn_last") == "2026-10-26", y)
        _state["labels"] = ["2027-01-02"]
        cf.note_cheered()
        check("a new year starts its own counts", cf.year_counts(2027) == {"cheered_by": 1} and cf.year_counts(2026).get("cheered_by") == 1)
        t = cf.clean_tallies({"years": {"2019": {"rooms": 1}, "2020": {}, "2021": {}, "2022": {}, "2023": {}, "2024": {}, "2025": {},
                                        "x": {"rooms": 2}, "2026": {"rooms": -1, "fifteens": True, "hours": {"25": 1, "9": 2, "x": 1},
                                                                    "worn": {"nope": 3, "dino": 4}, "bingo": {"": 1, "w": "2"},
                                                                    "worn_last": "2026-10-26", "cheers_sent": 3}}})
        check("cleaned like the rest: six years at most, junk dropped",
              sorted(t["years"]) == ["2021", "2022", "2023", "2024", "2025", "2026"]
              and t["years"]["2026"] == {"cheers_sent": 3, "hours": {"9": 2}, "worn": {"dino": 4}, "worn_last": "2026-10-26"}, t)
    finally:
        cf._save, cf.look = saved[:2]
        w["closet"] = saved[2] or {}
        _state["labels"] = saved[3]


def test_cheers_with_pips_v3822():
    """3.8.22, cheers with Pips (Sam's pick, round three: "One by one, then
    and N more"): when cheers land, each sender's Pip rises from the board's
    bottom edge in turn, tosses the cheer onto my row and ducks back down,
    in place of the flurry; three at most, the rest "and N more"; with
    Reduce motion they stand still in the banner. A mutual friend comes in
    their colour and look, anyone else plain; Pip off, the flurry as before."""
    from due_crew import social
    from due_crew.app import _state, _pending_cheers
    entries = [{"user_id": "me", "you": True}, {"user_id": "dre", "name": "Dre", "accent": "blue", "look": ["dino"]},
               {"user_id": "mo", "name": "Mo"}, {"user_id": "zz", "name": "Z", "look": ['"><b>x'], "accent": "red;}"}]
    cheers = [{"from": "dre", "name": "Dre", "emoji": "🎉"}, {"from": "dre", "name": "Dre", "emoji": "🔥"},
              {"from": "mo", "name": "Mo", "emoji": "💪"}, {"from": "zz", "name": '"><img src=x>', "emoji": "👏"},
              {"from": "ann", "name": "Ann", "emoji": "🌟"}]
    pips = board.cheer_pips(cheers, entries, {})
    check("who sent them, as Pips: each once, in the order they came, three at most",
          [p["emoji"] for p in pips] == ["🎉", "💪", "👏"] and len(pips) == 3, pips)
    check("a mutual friend in their colour and look; anyone else plain, in the default colour",
          pips[0]["a"] == list(board.accent_pair("blue")) and "<path" in pips[0]["svg"]
          and pips[1]["a"] == list(board.accent_pair(None)) and pips[2]["a"] == list(board.accent_pair(None)))
    check("a name is only a label, escaped; a hostile look never becomes markup",
          "<img" not in pips[2]["svg"] and "&lt;img" in pips[2]["svg"] and "<b>" not in pips[2]["svg"], pips[2]["svg"][:300])
    check("Pip off: no Pips", board.cheer_pips(cheers, entries, {"sev": False}) == [])
    check("one, two, three names; then and N more",
          [board.and_more(x) for x in (["A"], ["A", "B"], ["A", "B", "C"], ["A", "B", "C", "D", "E"])]
          == ["A", "A and B", "A, B and C", "A, B, C and 2 more"])
    js = board.flurry_js(["🎉"], "Dre sent cheers", pips=pips, season=["🎃"])
    check("the toss: from the board's bottom edge onto my row, in place of the flurry; still Pips in the banner with Reduce motion",
          "tr.you td.nm" in js and "dc.getBoundingClientRect()" in js and "if (still) { return; }" in js
          and "banner.insertBefore(who, title)" in js and "classList.add('rest')" in js and "<\\/" in js.split("var pips = ")[1][:20000]
          and "</svg" not in js.split("var pips = ")[1].split(";")[0], js[:200])
    plain = board.flurry_js(["🎉"], "Dre sent cheers", season=["🎃"])
    check("no Pips: the flurry, as before", "var pips = []" in plain and "dcfall" in plain)
    import shutil
    import subprocess
    if shutil.which("node"):
        r = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True)
        check("the toss's script is valid JS", r.returncode == 0, r.stderr[:400])
    # sent as the board plays them: names in order, the Pips with them
    saved = (social.mw.state, getattr(social.mw, "web", None), list(_state.get("entries") or []), list(_state.get("labels") or []))
    said = []
    social.mw.state = "deckBrowser"
    social.mw.web = types.SimpleNamespace(eval=said.append)
    _state["entries"], _state["labels"] = entries, ["2026-10-25"]
    try:
        _pending_cheers.extend(cheers)
        social._play_cheers()
    finally:
        social.mw.state, social.mw.web = saved[:2]
        _state["entries"], _state["labels"] = saved[2], saved[3]
        _pending_cheers.clear()
    check("played: the banner names them in order (Dre, Mo, the rest and N more), the senders' Pips come along",
          said and "Dre, Mo, &quot;" not in said[0] and "Dre, Mo, " in said[0] and "and 1 more sent cheers" in said[0]
          and said[0].count("Pip") >= 3 and "dino" not in said[0].split("var pips")[0], said[0][:300] if said else said)


def test_cheer_shows_v390():
    """3.9.0, how a cheer lands (Sam's picks, "Cheers, everywhere"): a show
    over the whole Decks screen, a different one each time. The bag plays
    every one of the twelve before any repeats, never the same twice in a
    row; it's kept in this computer's config, never sent. flurry_js runs the
    show (show.js) in place of the toss, the banner at the top; Reduce
    motion and Pip off are as before. Sam's tweaks: the piñata says no
    "CRACK!", and the fireworks put no name in the middle."""
    import random as _r
    import shutil
    import subprocess
    from due_crew import shows, social
    from due_crew.app import _state, _pending_cheers
    check("the twelve Sam kept, in the mock's order",
          shows.SHOWS == ("cannon", "pinata", "fireworks", "gift", "bubbles", "wave", "balloons", "rocket", "stamp", "disco", "hat", "snow"))
    rng, bag, seen = _r.Random(7), None, []
    for _ in range(12 * 6):
        k, bag = shows.next_show(bag, rng)
        seen.append(k)
    check("every one plays before any repeats, bag after bag",
          all(sorted(seen[i:i + 12]) == sorted(shows.SHOWS) for i in range(0, len(seen), 12)), seen[:24])
    check("never the same twice in a row, even where one bag ends and the next begins",
          all(a != b for a, b in zip(seen, seen[1:])))
    k, b2 = shows.next_show(["gone", "fireworks", "snow"], rng)
    check("an older add-on's show in the bag is dropped; the last one played stays last",
          k == "fireworks" and b2 == ["fireworks"] and shows.next_show(None, rng)[0] in shows.SHOWS)
    for seed in range(40):  # a new bag never starts with the one just played
        k, _b = shows.next_show(["snow"], _r.Random(seed))
        check("a fresh bag doesn't open with the last show", k != "snow") if k == "snow" else None
    entries = [{"user_id": "me", "you": True}, {"user_id": "dre", "name": "Dre K.", "accent": "blue", "look": ["dino"]}, {"user_id": "mo", "name": "Mo"}]
    cheers = [{"from": "dre", "name": "Dre K.", "emoji": "🔥", "note": "go </script> " + "x" * 300}, {"from": "mo", "name": "Mo", "emoji": "💪"}]
    pips = board.cheer_pips(cheers, entries, {})
    check("each sender brings the poses a show needs, a first name and their note (cut short)",
          set(pips[0]["poses"]) == {"hello", "jump", "cheer", "idle"} and all("<svg" in v for v in pips[0]["poses"].values())
          and pips[0]["name"] == "Dre" and pips[0]["note"].startswith("go </script>") and len(pips[0]["note"]) == 140 and pips[1]["note"] == "", pips[0]["name"])
    js = board.flurry_js(["🔥", "💪"], "Dre and Mo sent cheers", pips=pips, show="pinata")
    check("with a show: show.js comes along and plays it in place of the toss, the banner at the top; Reduce motion still stands the Pips in the banner",
          'var show = "pinata"' in js and "window.DCShow.play(show" in js and "banner.style.top = '12px'" in js and board.SHOW_JS[:200] in js
          and js.index("if (still) { return; }") < js.index("window.DCShow.play(show") and "banner.insertBefore(who, title)" in js)
    check("what the show gets is escaped for the page: no </ in the senders it's handed",
          "</script>" not in js.split("senders: ")[1].split(", dark:")[0], js.split("senders: ")[1][:120])
    check("Pip off (no Pips) or a show it doesn't know: no show, the flurry or the toss as before",
          'var show = null' in board.flurry_js(["🎉"], "Dre sent cheers", show="pinata") and board.SHOW_JS[:200] not in board.flurry_js(["🎉"], "x", show="pinata")
          and 'var show = null' in board.flurry_js(["🎉"], "x", pips=pips, show="spotlight"))
    sj = board.SHOW_JS
    check("show.js draws all twelve, and only them",
          set(re.findall(r"SHOW\.(\w+) = function", sj)) == set(shows.SHOWS) and len(re.findall(r"SHOW\.(\w+) = function", sj)) == len(shows.SHOWS))
    check("Sam's tweaks: no \"CRACK!\" on the piñata, no name in the fireworks' middle",
          "CRACK" not in sj and "dcs-lbl" not in sj.split("SHOW.fireworks")[1].split("SHOW.gift")[0] and "THWACK!" in sj)
    check("a show never takes markup from the page: names, notes and emoji go in as text; Pips are sev.py's",
          ".innerHTML = s." not in sj and "innerHTML = svg" in sj and sj.count("textContent") >= 8)
    check("a click anywhere but a present or a bubble, or Esc, ends it; it ends on its own too",
          'e.key === "Escape"' in sj and 'closest(".dcs-click")' in sj and "function end(ms)" in sj)
    if shutil.which("node"):
        for name, code in (("show.js", sj), ("a landing with a show", js)):
            r = subprocess.run(["node", "--check", "-"], input=code, capture_output=True, text=True)
            check(f"{name} is valid JS", r.returncode == 0, r.stderr[:400])
    # as the board plays them: the next show from the bag, the bag kept in the config
    conf = {}
    saved = (social.mw.state, getattr(social.mw, "web", None), list(_state.get("entries") or []), list(_state.get("labels") or []), social.cfg, social.save_cfg)
    said = []
    social.mw.state, social.mw.web = "deckBrowser", types.SimpleNamespace(eval=said.append)
    social.cfg, social.save_cfg = (lambda: conf), (lambda c: (conf.clear(), conf.update(c)))
    _state["entries"], _state["labels"] = entries, ["2026-10-25"]
    try:
        played = []
        for _ in range(3):
            _pending_cheers.extend(cheers)
            social._play_cheers()
            played.append(re.search(r'var show = "(\w+)"', said[-1]).group(1))
        bag = list(conf.get(shows.BAG_KEY) or [])
        conf["sev"] = False
        _pending_cheers.extend(cheers)
        social._play_cheers()
        off = said[-1]
    finally:
        social.mw.state, social.mw.web = saved[:2]
        _state["entries"], _state["labels"] = saved[2], saved[3]
        social.cfg, social.save_cfg = saved[4], saved[5]
        _pending_cheers.clear()
    check("each landing plays the bag's next show, three different ones, the bag saved in this computer's config (not an account key)",
          len(set(played)) == 3 and bag[-1] == played[-1] and len(bag) == 10 and shows.BAG_KEY not in __import__("due_crew.account", fromlist=["x"]).ACCOUNT_KEYS, (played, bag))
    check("Pip off: the flurry as before, and the bag untouched", "var show = null" in off and conf.get(shows.BAG_KEY) == bag)


def _wr_year(seed, keep, until=datetime.date(2026, 11, 30), start=datetime.date(2026, 1, 1)):
    import random as _r
    r, out, d = _r.Random(seed), {}, start
    while d <= until:
        if keep(d, r):
            out[d.isoformat()] = (r.randint(60, 400), r.randint(0, 25), r.randint(600000, 4000000))
        d += datetime.timedelta(days=1)
    return out


def test_wrapped_story_v390():
    """3.9.0's Wrapped, since 3.9.10 the scrapbook's year page: the year's
    facts from my own reviews, and the board's line from 1 December to 15
    January, now the scrapbook's (the slide story is gone)."""
    from due_crew import wrapped as W
    full = W.facts(2026, "2026-12-01", _wr_year(9, lambda d, r: r.random() < (.97 if d.month == 3 else .85)),
                   {22: 5000, 23: 3000, 9: 1000}, "2023-02-01")
    none = W.facts(2026, "2026-03-03", {}, {}, None)
    check("the year's facts: days, reviews, the longest run, each day's count; none for no reviews",
          full["days"] > 200 and full["reviews"] > full["days"] and full["run"][0] >= 3 and len(full["per_day"]) == full["days"]
          and not none["days"], (full["days"], full["run"]))
    check("the board's line: 1 December to 15 January, for the year just ending; else none",
          W.banner_year("2026-12-01") == 2026 and W.banner_year("2027-01-15") == 2026 and W.banner_year("2027-01-16") is None
          and W.banner_year("2026-11-30") is None)
    check("the slide story is gone (3.9.10): no slides, no card read for it",
          not hasattr(W, "slides") and not hasattr(board, "wrapped_html") and not hasattr(board, "wrapped_js")
          and not hasattr(__import__("due_crew.wrapped_flow", fromlist=["x"]), "turned"))
    line = board.scrapbook_line(2026, True, ["dino"])
    check("the line: Your 2026 so far is in your scrapbook, Open, and its x for the year", "Your 2026 so far" in line
          and "scrapbook" in line and "duecrew:scrapbook:2026" in line
          and "duecrew:wrappedx:2026" in line and "&#127873;" in board.scrapbook_line(2026, False, [], pip=False))
    from due_crew import account
    check("the line's x is the account's (wrapped_seen), so it holds on every computer",
          "wrapped_seen" in account.ACCOUNT_KEYS and account.clean({"wrapped_seen": "2026xx"}) == {"wrapped_seen": "2026"})


def test_wrapped_flow_v390():
    """3.9.0: the year is read in one grouped query (an hour a row), new
    cards met as first answers, the first review ever, the years there are
    (3.9.10: for the scrapbook's year page; its commands have their own
    test, test_scrapbook_v3910)."""
    from due_crew import wrapped_flow as F
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    at = lambda d, h: int(datetime.datetime.combine(d, datetime.time(h)).timestamp() * 1000)
    for d, h in ((datetime.date(2026, 3, 2), 22), (datetime.date(2026, 3, 2), 23), (datetime.date(2026, 3, 3), 1), (datetime.date(2025, 12, 31), 10)):
        fakes.add_review(conn, at(d, h), rtype=1, time_ms=60000)
    fakes.add_review(conn, at(datetime.date(2026, 3, 2), 22), rtype=0, last_ivl=0, cid=7)   # a new card, first seen
    fakes.add_review(conn, at(datetime.date(2026, 3, 2), 22), rtype=0, last_ivl=-600, cid=7)  # its next learning step
    fakes.add_card(conn, 5, 1, ctype=2, queue=2, ivl=41, lapses=9)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(datetime.date(2026, 3, 10)))
    days, hours = F.year_rows(col, 2026)
    check("the year in one query: 1 am counts for the day before (the rollover); a new card met once; the hours",
          days.get("2026-03-02", (0,))[0] == 5 and days["2026-03-02"][1] == 1 and "2026-03-03" not in days
          and "2025-12-31" not in days and hours.get(22) == 3 and hours.get(1) == 1, (days, hours))
    check("the first review ever, and the years there are", F.first_day(col) == "2025-12-31" and F.years(col) == [2026, 2025])
    check("the board's line: in its fortnight-and-a-month, until its x for that year",
          F.banner("2026-12-03", {"sev": False})["year"] == 2026 and F.banner("2026-12-03", {"wrapped_seen": "2026"}) is None
          and F.banner("2027-01-10", {"sev": False}) == {"year": 2026, "so_far": False, "look": []} and F.banner("2026-10-03", {}) is None)
    from due_crew import sharecard as S
    d = S.year({"2026-03-02": (5, 60000)}, 2026, "2026-03-10", None, True)
    ops = S.draw("year", "story", d, {"time": True, "reviews": True, "streak": True, "best": True}, "light", lambda s, px, w: len(s) * px * 0.5)[2]
    js = open(os.path.join(REPO, "site", "public", "cards.js"), encoding="utf-8").read()
    check("the year card can carry Pip (Wrapped's picture), and cards.js draws it the same",
          any(o[0] == "sev" for o in ops) and not any(o[0] == "sev" for o in S.draw("year", "story", dict(d, sev=False), {}, "light", lambda s, px, w: 1)[2])
          and "if (d.sev) { const img = await sevImg(pal.g); if (img) c.drawImage(img, W - P - YEAR_SEV, 446 - YEAR_SEV * SEV_FEET, YEAR_SEV, YEAR_SEV); }" in js
          and "YEAR_SEV = 220" in js and S.YEAR_SEV == 220)


def test_crew_tabs_hold_still_v3910():
    """3.9.10 (Sam: "make sure the spacing on today / week are the same"):
    the picked view's word is bold, and bold is wider, so Week sat in a
    different place on Today than on Week. Each word keeps its bold room."""
    from due_crew.board import crew, style
    sw = crew._crew_picker("week")
    css = style._css({})
    check("crew's views: each word carries its own name for the room its bold takes, and the picked one adds no height",
          sw.count('data-t="') == 3 and 'data-t="Week"' in sw and "a[data-t]::after { content: attr(data-t);" in css
          and "a[data-t] { display: inline-block; padding-bottom: 2px; }" in css, sw[:200])


def test_hooks_v3911():
    """3.9.11, hooks (Sam: "build that whole implementation you've
    proposed"): my own line on a card I keep missing, folded till Show when
    I'm stuck on it (Sam: "especially for one by ones we don't want to spoil
    the correct answer"); offered quietly beside Edit on a second miss, and
    once when a card I kept missing has stuck. Shared (a tick on each), it's
    my tip on the card on the server: mutual friends stuck on it read it,
    nobody asking; "This helped" reaches me once. Who knows it keeps its
    bubble on a card I've no hook on; a crewmate's hook can be hidden."""
    from due_crew import hooks as H, cards as K, room_model as rm, scrapbook as S
    _patched_due_crew()
    H._STORE.update(path=None, data=None, disk=None)
    check("a tip is one line a card, cleaned as a note is; no words takes it off",
          H.put("g1", "  LOOP = thick <b>ascending</b> loop\n of Henle ", "2026-11-13") == H.get("g1") and "\n" not in H.get("g1")
          and "<b>" in H.get("g1") and H.count() == 1 and H.put("g1", "   ", "2026-11-13") == "" and H.get("g1") == "" and H.count() == 0)
    H._STORE.update(path=None, data=None, disk=None)
    os.path.exists(H._path()) and os.remove(H._path())
    H.put("g1", "think loops", "2026-11-13")
    disk = json.load(open(H._path()))
    check("kept in hooks.json beside wrap.json; shared by default, and waiting to be sent; none of it an account key",
          disk["by"]["g1"] == {"t": "think loops", "at": "2026-11-13", "s": True, "up": False} and H.waiting() == [("g1", "think loops")]
          and H.shared("g1") and "hook" not in open(os.path.join(REPO, "due_crew", "account.py")).read())
    H.sent("g1", "think loops")
    check("sent: nothing waits, and the tip knows it's up", H.waiting() == [] and json.load(open(H._path()))["by"]["g1"]["up"] is True)
    H.put("g1", "think loops", "2026-11-13", share=False)
    check("made private: it comes down from the server; the next one starts unticked (what I chose last)",
          H.waiting() == [("g1", "")] and not H.shared("g1") and not H.shared("never"))
    H.sent("g1", "")
    H.put("g2", "mine alone", "2026-11-13", share=False)
    check("a private tip is never sent, and taking one off that never went up sends nothing",
          H.waiting() == [] and H.put("g2", "", "2026-11-13") == "" and H.waiting() == [])
    H.put("g1", "think loops", "2026-11-13", share=True)
    H.put("g1", "think LOOPS", "2026-11-13", share=True)
    H.sent("g1", "think loops")  # an older send lands after a change: the newer words still wait
    check("a send that lands after a change leaves the newer words waiting; taken off after going up, it comes down",
          H.waiting() == [("g1", "think LOOPS")] and (H.sent("g1", "think LOOPS"), H.put("g1", "", "2026-11-13")) and H.waiting() == [("g1", "")])
    H.sent("g1", "")
    H.put("g1", "think loops", "2026-11-13")
    H.sent("g1", "think loops")
    check("a card has stuck: three lapses or more and its last three answers right, no fewer",
          H.turned(3, [3, 2, 4]) and not H.turned(2, [3, 3, 3]) and not H.turned(5, [3, 1, 3]) and not H.turned(5, [3, 3])
          and (H.TURNED_LAPSES, H.TURNED_RIGHT, H.ASKS_A_DAY) == (3, 3, 2))
    v, asked = H.view("think loops", True, False, False, False)
    check("stuck on a card with my tip: folded till Show (a one-by-one's answer isn't given away), Edit beside it; a card I have down says nothing",
          v["text"] == "Your tip: think loops" and v["fold"] == "You left a tip" and "think" not in v["fold"]
          and v["cmd"] == "hookadd" and v["act"] == "Edit" and not asked
          and H.view("think loops", False, False, True, True) == (None, False))
    add, _a = H.view("", True, True, False, False)
    ask, was = H.view("", False, False, True, True)
    check("no tip: a second miss offers one beside Edit (never over the card); a card that stuck asks what made it click, once",
          add["text"] == "Add a tip for next time" and add["bar"] is True and "act" not in add
          and ask["text"] == "This one stuck. What made it click?" and was and "bar" not in ask
          and H.view("", True, False, False, False) == (None, False) and H.view("", False, False, True, False) == (None, False))
    check("what made it click: never twice on a card, twice a day at most",
          H.may_ask("a", "2026-11-13") and (H.note_asked("a", "2026-11-13"), H.note_asked("b", "2026-11-13")) and not H.may_ask("a", "2026-11-14")
          and not H.may_ask("c", "2026-11-13") and H.may_ask("c", "2026-11-14"))
    knows = {"kind": "knows", "text": "Dre knows this", "cmd": "knowsask", "act": "Ask",
             "peek": {"uids": ["dre"], "head": "I know this one", "act": "Ask Dre"}}
    check("my tip takes the place of nothing, of who knows it, of a plan's note; an ask or a crewmate's tip stays",
          H.over(None) and H.over(knows) and H.over({"kind": "remark"}) and not H.over({"kind": "tip"}) and not H.over({"kind": "ask"}))
    check("hiding a crewmate's tip: theirs on that card alone, for good",
          not H.hidden("g3", "dre") and (H.hide("g3", "dre"), H.hidden("g3", "dre"))[1] and not H.hidden("g3", "mo") and not H.hidden("g4", "dre"))
    names = {"dre": ("Dre Ng", ""), "mo": ("Mo", "")}
    info = {"knows": [], "tips": [{"from": "dre", "text": "theirs", "helped": False}, {"from": "mo", "text": "mo's", "helped": False}]}
    check("a hidden tip is off the chip and its list; the next one takes its place; all hidden, who knows it is what's left",
          [t["from"] for t in K.tip_list(info, [], names, hidden=lambda u: u == "dre")] == ["mo"]
          and K.chip_view(info, [], names, hidden=lambda u: u == "dre")["actcmd"] == "knowshelped:mo"
          and K.chip_view(info, [{"from": "dre", "name": "Dre", "note": "kept here"}], names, hidden=lambda u: True) is None
          and "Hide this tip" in open(os.path.join(REPO, "due_crew", "cards.py")).read())
    lines = H.thanks_lines([("g1", "dre"), ("g1", "mo"), ("g1", "dre"), ("g5", "zed")], {"dre": "Dre", "mo": "Mo"},
                           lambda g: "Renal" if g == "g1" else "")
    check("thanks: a line a card, named by its deck part (never its words), the rest counted; someone I can't name is a crewmate",
          lines == ["Your tip on a Renal card helped Dre and 1 more.", "Your tip on a card helped a crewmate."] and "hook" in S.WHATS, lines)

    # on the card: the chip, and the click
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    col = fakes.FakeCol(conn, fakes.day_cutoff_for(TODAY))
    now_ms = (col.sched.day_cutoff - 3600) * 1000
    for i, ease in enumerate((3, 3, 3)):
        fakes.add_review(conn, now_ms - 86400000 * (i + 2), ease=ease, cid=7)
    fakes.add_review(conn, now_ms, ease=1, cid=8)
    mk = lambda cid, guid, lapses: types.SimpleNamespace(id=cid, lapses=lapses, ord=0, note=lambda: types.SimpleNamespace(guid=guid))  # noqa: E731
    saved = (K.mw.col, K.log_today)
    K.mw.col, K.log_today = col, (lambda c: "2026-11-15")
    try:
        stuck_view = K._with_hook(None, mk(8, "g1", 2), "g1")
        offer = K._with_hook(None, mk(8, "g8", 2), "g8")
        turned = K._with_hook(None, mk(7, "g7", 4), "g7")
        again = K._with_hook(None, mk(7, "g7", 4), "g7")
        quiet = K._with_hook(None, mk(9, "g9", 0), "g9")
        over_knows = K._with_hook(dict(knows), mk(8, "g1", 2), "g1")
        knows_stays = K._with_hook(dict(knows), mk(8, "g8", 2), "g8")
        tip_stays = K._with_hook({"kind": "tip", "text": "x"}, mk(8, "g1", 2), "g1")
    finally:
        K.mw.col, K.log_today = saved
    check("on the card: my tip when I'm stuck; the offer on a second miss today; what made it click once, then nothing; a fresh card, nothing",
          stuck_view["kind"] == "hook" and stuck_view["fold"] and offer["kind"] == "hookadd" and turned["kind"] == "hookask"
          and again is None and quiet is None, (stuck_view, offer, turned, again, quiet))
    check("who knows it comes up as ever on a card I've no tip on (an offer never takes its place); my tip goes in its place; a crewmate's tip stays",
          knows_stays["kind"] == "knows" and knows_stays["peek"]["head"] == "I know this one" and over_knows["kind"] == "hook"
          and tip_stays == {"kind": "tip", "text": "x"}, (knows_stays, over_knows))
    src = open(os.path.join(REPO, "due_crew", "cards.py")).read()
    check("its click is one of the card page's keyed commands (it opens a window, nothing more); the quiet offer stays in the bar; "
          "the More menu has it on any card",
          "hookadd" in rm.CARD_PAGE_CMDS and 'if view and page is not None and not view.get("bar"):' in src
          and 'elif cmd == "hookadd":\n        hook_edit()' in src
          and "Due Crew: add a tip…" in open(os.path.join(REPO, "due_crew", "together.py")).read())

    # the window's answer is kept, and a shared one goes to the server; a crewmate stuck on the card reads it; helped comes back once
    labels = [_day(-i) for i in range(8)]
    store = world({"sam": "Sam", "dre": "Dre", "zed": "Zed"}, {"sam": ["dre"], "dre": ["sam"], "zed": []})
    sam, dre, zed = new_client(store, "sam", "Sam"), new_client(store, "dre", "Dre"), new_client(store, "zed", "Zed")
    HD = types.ModuleType('due_crew.ui.hook_dialog')  # the suite has no Qt: the window itself is tools/dialogs.py's
    HD.HookDialog = None
    had_hd = sys.modules.get('due_crew.ui.hook_dialog')
    sys.modules['due_crew.ui.hook_dialog'] = HD
    opened, shown, said, answers = [], [], [], [("renal: think loops", True), ("renal: think loops", False), ("", False)]

    class FakeDialog:
        def __init__(self, parent, words="", shared=True, signed_in=True):
            opened.append((words, shared, signed_in))
            self.result_words, self.result_shared = answers[len(opened) - 1]

        def exec(self):
            return 1
    keep = (K._card, HD.HookDialog, K.on_answer, K.mw.col, K.log_today, K.tooltip, getattr(K.mw, "reviewer", None), K.client, K._bg, K.names_by_uid)
    card = mk(8, "g20", 2)
    K._card, K.on_answer, K.mw.col, K.log_today = (lambda: card), (lambda c, opened=False: shown.append(opened)), col, (lambda c: "2026-11-15")
    K.tooltip = lambda text, **k: said.append(text)
    K.mw.reviewer = types.SimpleNamespace(state="answer")
    HD.HookDialog, K.client, K._bg = FakeDialog, (lambda: sam), (lambda job, done=None: done(job()) if done else job())
    K.names_by_uid = lambda: {"dre": ("Dre Ng", "")}
    try:
        handled = K.on_message("hookadd", ["duecrew", "hookadd"], from_card_page=True)
        up = store.tips.get(("g20", "sam"))
        dre.push(labels, {}, stuck=["g20"])
        zed.push(labels, {}, stuck=["g20"])
        read = json.loads(json.dumps((dre.session.get("cards") or {}).get("g20"))), (zed.session.get("cards") or {}).get("g20")
        dre.tip_helped("g20", "sam")
        board = sam.fetch_board(labels)
        K.hook_thanks(board["thanks"])
        twice = sam.fetch_board(labels)["thanks"]
        K.on_message("hookadd", ["duecrew", "hookadd"], from_card_page=True)   # now private: it comes down
        down = ("g20", "sam") not in store.tips and H.get("g20") == "renal: think loops"
        K.on_message("hookadd", ["duecrew", "hookadd"], from_card_page=True)   # taken off
        # a send that doesn't get out waits, and goes with a later refresh's flush
        H.put("g21", "later", "2026-11-15")
        real = sam.put_hook
        sam.put_hook = lambda g, w: False
        K.flush_hooks()
        waited = H.waiting() == [("g21", "later")] and ("g21", "sam") not in store.tips
        sam.put_hook = real
        K.flush_hooks()
        H.put("g22", "no room", "2026-11-15")
        sam.put_hook = lambda g, w: None
        K.flush_hooks()
        refused = H.waiting() == [] and H.get("g22") == "no room" and not H.shared("g22")
        sam.put_hook = real
    finally:
        K._card, HD.HookDialog, K.on_answer, K.mw.col, K.log_today, K.tooltip = keep[:6]
        K.mw.reviewer, K.client, K._bg, K.names_by_uid = keep[6:]
        if had_hd is None:
            sys.modules.pop('due_crew.ui.hook_dialog', None)
        else:
            sys.modules['due_crew.ui.hook_dialog'] = had_hd
    check("the click: the window (the tip and tick it has, each time), kept, the chip drawn again opened",
          handled is True and opened == [("", True, True), ("renal: think loops", True, True), ("renal: think loops", False, True)]
          and shown == [True, True, True] and said[0] == "Tip saved, for you and your crew." and said[-1] == "Tip removed.", (opened, shown, said))
    check("shared: it's my tip on the card on the server; a mutual friend stuck on it reads it, a stranger doesn't",
          up and up["text"] == "renal: think loops" and read[0] == {"knows": [], "tips": [{"from": "sam", "text": "renal: think loops", "helped": False}]}
          and read[1] is None, (up, read))
    check("This helped reaches me with a refresh, once: said, and a keepsake; made private it comes down, and stays mine here",
          board["thanks"] == [("g20", "dre")] and twice == [] and "Your tip on a card helped Dre." in said and down and H.get("g20") == ""
          , (board["thanks"], twice, said))
    check("a send that didn't get out waits and goes with the next flush", waited and H.waiting() == [] and store.tips[("g21", "sam")]["text"] == "later")
    check("one the server refuses for good (no room) isn't sent again at every refresh: it stays, mine alone", refused)
    init = srcs.glue_src()
    check("a refresh's commit says the thanks and sends what waits (no request of its own when nothing does)",
          '_crew_cards.hook_thanks(data.get("thanks"))' in init and "_crew_cards.flush_hooks()" in init)
    H._STORE.update(path=None, data=None, disk=None)
    os.path.exists(H._path()) and os.remove(H._path())


def test_refill_with_nothing_to_take_back_v3912():
    """3.9.12 (Sam's report from a day's Study: "FilteredDeckError: No cards
    matched the provided search"): a Due Crew deck that lent its cards gets
    the rest back afterwards; when those are suspended now, or another
    add-on's deck holds them, Anki refuses a filtered deck that finds none.
    That isn't ours to report: the deck stays empty. Any other error is."""
    from due_crew import plan_flow as PF

    class FilteredDeckError(Exception):
        pass
    term = types.SimpleNamespace(search="", limit=0)
    deck = types.SimpleNamespace(config=types.SimpleNamespace(search_terms=[term]))
    calls = []

    def col(err):
        def update(d):
            calls.append((term.search, term.limit))
            if err is not None:
                raise err
        return types.SimpleNamespace(sched=types.SimpleNamespace(get_or_create_filtered_deck=lambda deck_id: deck, add_or_update_filtered_deck=update))
    PF._refill(col(None), 5, [11, 12])
    quiet = PF._refill(col(FilteredDeckError("No cards matched the provided search.")), 5, [11, 12])
    loud = None
    try:
        PF._refill(col(RuntimeError("something else")), 5, [11])
    except RuntimeError as e:
        loud = str(e)
    PF._refill(col(RuntimeError("never asked")), 5, [])
    check("refill: its cards back by id; none that Anki will take leaves it empty and says nothing; another error is still raised; no cards, no ask",
          calls == [("cid:11,12", 2), ("cid:11,12", 2), ("cid:11", 1)] and quiet is None and loud == "something else", (calls, loud))


def test_one_control_reset_v3912():
    """3.9.12, the foundations round, Stage A: every button of ours starts
    from one reset (board.button_reset), whichever part of the board it's
    on; a part adds only its own. A page of its own (Magic search, the
    plan window and its copy on duecrew.com) carries the same text for its
    scope. Five places restated it before, each a little differently."""
    from due_crew import board
    from due_crew.board import base, scrapbook as sb, settings as st, dance as dn
    core = base.BUTTON_CORE
    css = board._css({"accent": "green", "theme": "auto"}) if hasattr(board, "_css") else ""
    check("reset: the board's buttons, the scrapbook's, Settings' and the dance floor's all start from the one core, each with only its own after it",
          base.button_reset("#x", "color: red;") == "#x { " + core + " color: red; }"
          and ("#due-crew button { " + core + " color: inherit; font-weight: normal; }") in css
          and ("#due-crew.dc-sb button { " + core + " vertical-align: middle; font: inherit; cursor: pointer; }") in sb.SCRAP_CSS
          and ("#due-crew.dc-set button { " + core + " vertical-align: middle; }") in st.SETTINGS_CSS
          and ("#dc-dance button, #dc-song button, #dc-song input { " + core + " font: inherit; color: inherit; border-radius: 0; }") in dn.DANCE_CSS
          and "__BUTTONS__" not in sb.SCRAP_CSS + st.SETTINGS_CSS + dn.DANCE_CSS)
    src = {}
    for f in os.listdir(os.path.join(REPO, "due_crew", "board")):
        if f.endswith(".py") and f != "base.py":
            src[f] = open(os.path.join(REPO, "due_crew", "board", f), encoding="utf-8").read()
    own = sorted(f for f, text in src.items() if re.search(r"button[^{}\n]*\{[^{}]*appearance: none; margin: 0; box-shadow: none", text))
    check("reset: no part of the board restates it", own == [], own)
    pages = {os.path.join("due_crew", "magicpage", "magic.css"): ".dcm", os.path.join("due_crew", "planner", "page", "plan.css"): ".dcp",
             os.path.join("site", "public", "planpage", "plan.css"): ".dcp"}
    off = [f for f, scope in pages.items() if base.page_reset(scope) not in open(os.path.join(REPO, f), encoding="utf-8").read()]
    check("reset: a page of its own carries the same text for its scope (Magic search, the plan window, its copy on the site)", off == [], off)
    # Stage A's other half: duecrew.com's own pages. A page with a control carries the site's reset, itself or by its stylesheet
    pub = os.path.join(REPO, "site", "public")
    text = {f: open(os.path.join(pub, f), encoding="utf-8").read() for f in os.listdir(pub) if f.endswith((".html", ".css"))}
    js = {"app.html": "app.css", "table.html": "table.css"}  # pages whose controls their scripts draw: the sheet they load
    bare = []
    for f, t in text.items():
        if not f.endswith(".html"):
            continue
        has = re.search(r"<(button|select|textarea|input)\b", t) or f in js
        sheets = [t] + [text[c] for c in re.findall(r'href="/?([\w-]+\.css)', t) if c in text]
        if has and not any(" ".join(base.SITE_RESET.split()) in " ".join(x.split()) for x in sheets):
            bare.append(f)
    check("reset: every page of the site with a control carries the site's one reset (the landing page and For classes had none)",
          bare == [] and len(text) > 5, bare)


def test_view_shapes_v3912():
    """3.9.12, the foundations round: what a page is told to draw has a
    named shape (views.py), checked where it crosses from Python to the
    page. The review chip is the first: every view its makers build fits,
    a slip is counted (`view:chip`) and drawn anyway."""
    from due_crew import views as V, cards as K, hooks as H
    names = {"dre": ("Dre Ng", ""), "mo": ("Mo", "")}
    made = [K.chip_view({"knows": ["dre", "mo"], "tips": []}, [], names),
            K.chip_view({"knows": ["dre"], "tips": [{"from": "dre", "text": "loops", "helped": False}]}, [], names),
            K.chip_view({"knows": ["dre"]}, [], names, mine=True),
            K.chip_view(None, [], names, asks=[("dre", 1, "why axillary?")]),
            K.chip_view(None, [], names, asks=[("dre", 1)]),
            H.view("think loops", True, False, False, False)[0], H.view("", True, True, False, False)[0], H.view("", False, False, True, True)[0],
            None]
    bad = [(v.get("kind"), V.chip_wrong(v)) for v in made if V.chip_wrong(v)]
    check("shapes: every view the chip's makers build fits the chip's shape (who knows it, a tip, an ask, my tip, its offers)",
          bad == [] and all(v is None or v["kind"] in V.CHIP_KINDS for v in made), bad)
    check("shapes: a key the page doesn't know, a wrong type, an unknown kind and a peek's slip are each said",
          V.chip_wrong({"kind": "knows", "text": "x", "txet": "y"}) == ["txet: not in the shape"]
          and V.chip_wrong({"kind": "knows", "more": "2"}) == ["more: str"] and V.chip_wrong({"kind": "knows", "more": True}) == ["more: bool"]
          and V.chip_wrong({"kind": "nope"}) == ["kind: 'nope'"] and V.chip_wrong({"kind": "tip", "peek": {"uids": "dre"}}) == ["peek.uids: str"]
          and V.chip_wrong(None) == [] and V.chip_wrong("x") == ["not a dict"])
    js = open(os.path.join(REPO, "due_crew", "cards.py"), encoding="utf-8").read()
    read = set(re.findall(r"\bD\.([a-zA-Z_]+)", js))
    check("shapes: the chip's script reads only keys in its shape, and the glue counts a slip without dropping the view",
          read <= set(V.CHIP) and read >= {"kind", "text", "fold", "cmd", "act"} and 'errs.count("view:chip")' in js, sorted(read - set(V.CHIP)))
    # Stage D's first three: a plan's card, Insights, the dance floor, checked where each is drawn
    from due_crew import views as V
    had = list(V.SLIPS)
    try:
        del V.SLIPS[:]
        song = {"t": "Lantern Hours", "a": "Mira Vale", "al": "Lantern Hours", "y": 2025, "id": 1, "url": "https://music.apple.com/x", "at": "2026-11-02"}
        floor = {"me": song, "crew": [{"uid": "dre", "name": "Dre", "accent": None, "look": [], "song": song, "fresh": False}],
                 "motion": "gentle", "app": "", "ask": False, "pip": True, "folded": False, "_seen": {}}
        check("shapes: a dance floor as song_flow makes it fits; a None is always allowed",
              V.dance_wrong(floor) == [] and V.seen("dance", floor) and V.seen("dance", None) and V.SLIPS == [])
        check("shapes: a key the page doesn't know, a wrong type, in a dancer or a song: each said",
              V.dance_wrong(dict(floor, lights=True)) == ["lights: not in the shape"]
              and V.dance_wrong(dict(floor, folded="yes")) == ["folded: str"]
              and V.dance_wrong(dict(floor, crew=[{"uid": 7}])) == ["crew.uid: int"]
              and V.dance_wrong(dict(floor, me=dict(song, preview="x"))) == ["me.preview: not in the shape"])
        check("shapes: a slip is counted and kept for whoever looks, and the floor is drawn anyway",
              V.seen("dance", dict(floor, lights=True)) is False and V.SLIPS == [("dance", ["lights: not in the shape"])]
              and "dc-dance" in board.dance_html(dict(floor, lights=True), {}))
        check("shapes: a plan's card and Insights have theirs; a made-up surface is no one's problem",
              V.plan_wrong({"id": "p1", "name": "Block 1", "week": [], "paused": False}) == []
              and V.plan_wrong({"id": "p1", "weeks": []}) == ["weeks: not in the shape"]
              and V.insights_wrong({"did": 1, "map": [], "right": {}}) == [] and V.insights_wrong({"did": "1"}) == ["did: str"]
              and V.seen("nothing", {"a": 1}) is True)
        src = fakes.board_source()
        check("shapes: each is checked where it's drawn", all(x in src for x in ('_views.seen("plan", card)', '_views.seen("insights", v)',
                                                                                 '_views.seen("dance", view)')))
    finally:
        V.SLIPS[:] = had


def test_the_sites_constants_are_made_v3912():
    """3.9.12, the foundations round: constants the site restated by hand
    (what each party game needs, a plan's limits, a day's saves) are
    written from the add-on's by tools/gen_twins.py; running it again
    changes nothing."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen_twins", os.path.join(REPO, "tools", "gen_twins.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    check("the site's constants are their Python's (tools/gen_twins.py changes nothing)", gen.stale() == [], gen.stale())
    check("each made line says where it's from", all("made by tools/gen_twins.py from" in want for _f, _n, want in gen.lines()) and len(gen.lines()) == 3)


def test_the_fake_has_every_route_v3912():
    """3.9.12, the foundations round: the suite's server is the Worker
    restated, so a route the Worker gains has to be restated too, or the
    client's use of it is tested against nothing. Every route in
    worker/src/index.ts is asked of the fake; the ones it doesn't know
    are named here, and are only the site's."""
    ts = open(os.path.join(REPO, "worker", "src", "index.ts"), encoding="utf-8").read()
    store = world({"sam": "Sam"}, {})
    token = store.session_for("sam")

    def fill(g):
        t = g.group(0)
        return ("ABCD" if "A-Za-z]{4}" in t else "ABC123" if "A-Za-z0-9" in t else "7" if ("[0-9]{1," in t or "d{" in t)
                else "01ARZ3NDEKTSV4RRFFQ69G5FAV" if "{26}" in t else "x1")
    routes = re.findall(r'\b(?:authed|open)\("(GET|POST|PUT|PATCH|DELETE)", r\([`"]([^`"]+)[`"]\)', ts)
    unknown = []
    for m, raw in routes:
        path = re.sub(r"\([^)]*\)", fill, raw.replace("${ID}", "x1"))
        r = store.handle(m, "https://api.test" + path, {"Authorization": "Bearer " + token}, {} if m != "GET" else None)
        if r.status_code == 404 and (r.json() or {}).get("error") == "not_found":
            unknown.append((m, raw))
    SITE_ONLY = [("POST", "/auth/link/redeem"), ("POST", "/links/email")]  # the site's sign-in link and the landing page's "email it"
    check("the fake answers every route the Worker has but the site's own two; a new route is restated there or named here",
          len(routes) > 100 and sorted(unknown) == sorted(SITE_ONLY), (len(routes), unknown))


def test_copy_rules_v3912():
    """3.9.12, the foundations round: the words' rules, checked instead of
    remembered. Buttons, headings and menu items are sentence case; what a
    crewmate leaves on a card is a hook wherever it's read; nothing a
    person reads says rank, rival, compete or leaderboard."""
    files = {}
    for root, _dirs, names in os.walk(os.path.join(REPO, "due_crew")):
        for f in names:
            if f.endswith(".py"):
                files[os.path.relpath(os.path.join(root, f), os.path.join(REPO, "due_crew"))] = open(os.path.join(root, f), encoding="utf-8").read()
    # names that are names: the product, its parts, a person's own things
    names_ok = ("Due Crew", "Pip Party", "Your plans", "Magic search", "Big Step", "Your AI", "My plan", "Anki", "Apple Music", "Study Session", "Step 1", "Step 2")
    title = []
    for f, text in files.items():
        for m in re.finditer(r'(?:QPushButton|addButton|setWindowTitle|addAction|heading|QCheckBox|QRadioButton)\(\s*f?"([^"]{3,60})"', text):
            words = m.group(1)
            bare = words
            for n in names_ok:
                bare = bare.replace(n, "")
            if re.search(r"[a-z] [A-Z][a-z]", bare) and ": " not in bare and " \u00b7 " not in bare and " · " not in bare:
                title.append((f, words))
    check("copy: buttons, headings and menu items are sentence case (a name keeps its capitals)", title == [], title[:8])
    shown = [("board", "crew.py"), ("board", "insights.py"), ("board", "scrapbook.py"), ("together.py",), ("leech_flow.py",), ("scrapbook.py",),
             ("cards.py",), ("ui", "hook_dialog.py")]
    tips = []
    for parts in shown:
        text = files[os.path.join(*parts)]
        text = re.sub(r'''"""[\s\S]*?"""''', '""', text)       # a docstring or a comment may still say tip: the code does
        text = re.sub(r"(?m)(^\s*#.*$|\s{2}# .*$|^\s*//.*$)", "", text)
        for m in re.finditer(r"""(?:"|>|')([^"'<>\n]*?(?:\ba hook\b|s hook\b|\bhooks that\b|\bSend a hook\b|\bHooks from\b|>Hook<|\bour hook\b|\bHook (?:saved|removed)\b)[^"'<>\n]*)""", text):
            src = text.split("\n")[text[:m.start()].count("\n")]
            before = src[:src.find(m.group(1))] if m.group(1) in src else src
            if not ("#" in before or "//" in before or src.strip().startswith(("#", "//", "*"))):  # a comment may still say tip: the code does
                tips.append((os.path.join(*parts), m.group(1)[:60]))
    # 3.9.12, later the same day (SC: "let's call hooks tips again sorry"): a tip, never a hook
    check("copy: a line left on a card is a tip wherever a person reads it, never a hook", tips == [], tips[:6])
    banned = []
    pages = dict(files)
    for f in ("index.html", "classes.html", "privacy.html", "app.js", "table.js"):
        pages[os.path.join("site", f)] = open(os.path.join(REPO, "site", "public", f), encoding="utf-8").read()
    for f, text in pages.items():
        for m in re.finditer(r"""["'>][^"'<>\n]*\b(compete|competition|rivals?|leaderboard|ranking)\b[^"'<>\n]*""", text, re.I):
            line = text.split("\n")[text[:m.start()].count("\n")].strip()
            if not (line.startswith("#") or line.startswith("//") or line.startswith("*") or '"""' in line or "  # " in line):
                banned.append((f, m.group(0)[:70]))
    check("copy: friendship, never competition: nothing a person reads says rank, rival, compete or leaderboard", banned == [], banned[:6])
    # one way to say there was no answer: "Couldn't reach Due Crew." (never "the server", never "couldn't be reached")
    import glob as _glob
    odd = []
    for path in _glob.glob(os.path.join(REPO, "due_crew", "**", "*.py"), recursive=True):
        text = open(path, encoding="utf-8").read()
        for words in ("ouldn't reach the server", "Can't reach the server", "couldn't be reached. Try", "didn\\'t reach the server"):
            if words in text:
                odd.append((os.path.relpath(path, REPO), words))
    check("words: no answer from Due Crew is said one way", odd == [], odd)


def test_the_site_wears_the_boards_tokens_v3912():
    """3.9.12, the foundations round: the colours a person sees in Anki and
    on duecrew.com are one set. The add-on's pages all read board.palette;
    the site's stylesheets restate it by hand (its paper and ink are its
    own), so the tokens they share are checked against it here: the
    accent, its ink, your row's fill, the line, the well and the amber, in
    light and in dark."""
    from due_crew import board
    light, dark = board.palette("light", "green"), board.palette("dark", "green")
    want = {"accent": "accent", "accent-ink": "accent-ink", "you": "you-bg", "line": "line", "well": "well", "warn": "hours"}

    def tokens(text):
        """[{name: value}] for each block of custom properties, in order (the light block, then the dark)."""
        out = []
        for block in re.findall(r"\{[^{}]*--[a-z-]+:\s*#[^{}]*\}", text):
            out.append(dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})", block)))
        return out

    wrong = []
    for name, names in (("app.css", want), ("index.html", {k: v for k, v in want.items() if k in ("accent", "accent-ink", "line", "well")}),
                        ("table.css", {"acc": "accent", "line": "line", "w-well": "well", "w-acc-ink": "accent-ink", "w-you": "you-bg", "w-acc": "accent"})):
        blocks = tokens(open(os.path.join(REPO, "site", "public", name), encoding="utf-8").read())
        firsts = [b for b in blocks if any(k in b for k in names)][:2]
        if len(firsts) < 2:
            wrong.append((name, "no light and dark block"))
            continue
        for b, pal, theme in ((firsts[0], light, "light"), (firsts[1], dark, "dark")):
            for site_name, board_name in names.items():
                if site_name in b and b[site_name].lower() != pal[board_name].lower():
                    wrong.append((name, theme, site_name, b[site_name], pal[board_name]))
    check("tokens: the site's accent, its ink, your row, the line, the well and the amber are the board's, light and dark", wrong == [], wrong)
    pages = {"magic_html.py": "board.palette(", os.path.join("planner", "webpage.py"): "palette(", os.path.join("ui", "__init__.py"): "palette("}
    check("tokens: every page the add-on draws reads the board's palette (Magic search, the plan window, the Qt windows)",
          all(want_ in open(os.path.join(REPO, "due_crew", f), encoding="utf-8").read() for f, want_ in pages.items()))


def test_one_way_to_keep_a_file_v3912():
    """3.9.12, the foundations round: every file Due Crew keeps is written by
    store.py (whole to a .tmp, then swapped in; a failed write takes its
    .tmp with it and says so), where ten modules each wrote their own."""
    from due_crew import store
    d = tempfile.mkdtemp()
    p = os.path.join(d, "x.json")
    check("store: written whole and read back; a file that isn't a JSON object, or isn't there, reads as the default",
          store.write_json(p, {"a": 1}) and store.read_json(p) == ({"a": 1}, '{"a": 1}') and not os.path.exists(p + ".tmp")
          and store.write_text(p, "[1, 2]") and store.read_json(p, {}) == ({}, None) and store.read_json(os.path.join(d, "none.json")) == (None, None))
    check("store: a write that can't be made says so, leaves no .tmp and leaves the file as it was",
          store.write_json(p, {"a": 2}) and not store.write_json(os.path.join(d, "no", "such", "dir.json"), {"a": 3})
          and store.read_json(p)[0] == {"a": 2} and os.listdir(d) == ["x.json"])
    q = os.path.join(d, "mine.json")
    check("store: private is mine alone (a session token's file)", store.write_json(q, {"t": "x"}, private=True)
          and (os.name == "nt" or (os.stat(q).st_mode & 0o777) == 0o600))
    cache = {}
    data = store.load(cache, p)
    data["b"] = 1
    writes = []
    real = store.write_text
    store.write_text = lambda path, text, private=False: (writes.append(path), real(path, text, private))[1]
    try:
        first, again = store.save(cache), store.save(cache)
        other = store.load(cache, q, ok=lambda d: "by" in d, empty=lambda: {"by": {}})
    finally:
        store.write_text = real
    check("store: kept in memory till the path changes; saved only when it says something the file doesn't; a wrong shape is the empty one",
          first and again and writes == [p] and store.read_json(p)[0] == {"a": 2, "b": 1} and other == {"by": {}} and cache["path"] == q)
    src = {}
    for root, _dirs, files in os.walk(os.path.join(REPO, "due_crew")):
        for f in files:
            if f.endswith(".py"):
                src[os.path.relpath(os.path.join(root, f), REPO)] = open(os.path.join(root, f), encoding="utf-8").read()
    own = sorted(k for k, v in src.items() if '+ ".tmp"' in v and not k.endswith("store.py"))
    check("store: nothing else writes a .tmp of its own", own == [], own)


def test_scrapbook_v3910():
    """3.9.10, the scrapbook (Sam: "a combo wrapped and home for polaroids /
    notes, etc. that are ephemeral at the moment or deleted permanently
    when taken away from the screen"): a polaroid taken down, pushed out or
    signed out with goes there; good-luck lines once shown, a tip that
    helped, a cheer with words, what I did; by month under the year's page;
    Pin up, Delete, Empty; this computer's, per account, never sent."""
    import due_crew as dc
    from due_crew import scrapbook as S, scrap_flow as SF, closet_flow as cf, fridge as FR
    from aqt.deckbrowser import DeckBrowser
    _patched_due_crew()
    SF._BOOK.update(path=None, data=None, disk=None)
    draw = {"k": "draw", "s": [[0, 10, 10, 50, 50]]}
    # pure
    pz = {"k": "pz", "from": "dre", "name": "Dre", "at": "2026-11-03T10:00:00Z", "a": "blue", "n": "go <b>", "d": draw}
    its = S.add(S.add([], pz), pz)
    check("a keepsake is kept once, cleaned; one of no kind, no day or no words isn't",
          len(its) == 1 and its[0]["d"]["k"] == "draw" and S.clean_one({"k": "x", "at": "2026-11-03"}) is None
          and S.clean_one({"k": "luck", "at": "nope", "n": "hi"}) is None and S.clean_one({"k": "luck", "at": "2026-11-03", "n": ""}) is None
          and S.clean_one({"k": "mine", "at": "2026-11-03", "head": ""}) is None, its)
    more = S.add(its, {"k": "mine", "w": "plan", "head": "Finished Heme", "at": "2026-10-20"})
    more = S.add(more, {"k": "cheer", "from": "nia", "name": "Nia", "at": "2025-12-30T01:00:00Z", "n": "nice", "e": "🎉"})
    check("by year and month, newest first; this year always has a page",
          S.years(more, 2027) == [2027, 2026, 2025] and [m for m, _x in S.months(more, 2026)] == [11, 10]
          and S.counts(more, 2026) == {"pz": 1, "luck": 0, "tip": 0, "cheer": 0, "mine": 1})
    check("a month's line: what I did leads, else the days I showed up; its numbers only when there are some",
          S.month_line([{"head": "Finished Heme"}, {"head": "x"}], 9) == ("", "Finished Heme", ", and 1 more.")
          and S.month_line([], 1) == ("", "1 day", " you showed up.") and S.month_line([], 0) == ("", "", "")
          and S.month_sub(12, 3400, 1) == "12 study days · 3,400 reviews · cheered 1 time" and S.month_sub(0, 0, 0) == "")
    check("the year's line and numbers: kind, and only what there is",
          S.year_line(2026, 0, 0, True)[0] == "2026 so far: nothing studied yet."
          and S.year_line(2026, 200, 41000, False) == ("200 days you showed up, and ", "41,000 reviews", ".")
          and S.year_stats(31, 1, {"pz": 2}, 0, 0) == [("31", "days, your longest run"), ("1", "plan finished"), ("2", "drawings and signs")])
    check("a polaroid goes to the fridge's shape and back", S.to_fridge(S.from_fridge({"from": "dre", "name": "Dre", "at": "x", "a": "blue", "n": "n", "d": draw}))
          == {"from": "dre", "name": "Dre", "at": "x", "a": "blue", "n": "n", "d": draw})

    # the fridge feeds it
    ents = [{"user_id": "dre", "accent": "blue", "you": False}]
    cheers = [{"from": "dre", "name": "Dre", "at": f"2026-10-{d:02d}T10:00:00Z", "note": f"day {d}", "doodle": draw} for d in range(1, FR.KEEP + 3)]
    cf.keep_doodles(cheers, ents, "sam")
    pushed = [x["n"] for x in SF.items("sam")]
    check("a newer drawing pushing the oldest off the fridge sends it to the scrapbook (it was gone for good)",
          len(cf.fridge("sam")) == FR.KEEP and pushed == ["day 1", "day 2"], pushed)
    first = cf.fridge("sam")[0]
    cf.take_down(FR.key(first))
    down = [x["n"] for x in SF.items("sam")]
    cf.put_back(FR.key(first))
    check("× takes a drawing down into the scrapbook; Undo brings it back out", down == ["day 1", "day 2", first["n"]]
          and [x["n"] for x in SF.items("sam")] == ["day 1", "day 2"] and "In your scrapbook &middot;" in open(os.path.join(REPO, "due_crew", "board", "fridge.py")).read())
    kept = SF.find(S.key(SF.items("sam")[0]), "sam")
    up = cf.pin_up(S.to_fridge(kept), "sam")
    check("Pin up: back on the fridge, the oldest there making room in the scrapbook",
          up and any(x["n"] == "day 1" for x in cf.fridge("sam")) and len(cf.fridge("sam")) == FR.KEEP
          and first["n"] in [x["n"] for x in SF.items("sam")], [x["n"] for x in SF.items("sam")])
    saved = (dc._reset_runtime, dc._rerender)
    dc._reset_runtime, dc._rerender = (lambda **k: None), (lambda: None)
    try:
        dc._on_signed_out()
    finally:
        dc._reset_runtime, dc._rerender = saved
    n_out = len(SF.items("sam"))
    check("signing out: the fridge empties into that account's scrapbook, which stays, and another account sees none of it",
          cf.fridge("sam") == [] and n_out == FR.KEEP + 2 and SF.items("nia") == [], n_out)

    # what else is kept
    SF.cheers_in([{"from": "nia", "name": "Nia", "at": "2026-11-02T09:00:00Z", "note": "you got this", "emoji": "💪"},
                  {"from": "nia", "name": "Nia", "at": "2026-11-02T09:01:00Z", "note": "", "emoji": "🎉"},
                  {"from": "dre", "name": "Dre", "at": "2026-11-02T09:02:00Z", "note": "look", "doodle": draw}], "sam")
    SF.luck_shown([{"from": "nia", "name": "Nia", "note": "Breathe."}], "2026-11-05", "sam")
    SF.moment("plan", "Finished Heme", "Every set of it done.", "cheer", "2026-11-06", "sam")
    SF.moment("plan", "Finished Heme", "Every set of it done.", "cheer", "2026-11-06", "sam")
    nov = [x for x in SF.items("sam") if x["at"][:7] == "2026-11"]
    check("a cheer is counted in its month and kept only with words (a drawing is the fridge's); a good-luck line once shown; a moment once",
          sorted(x["k"] for x in nov) == ["cheer", "luck", "mine"] and SF._read("sam")["cheers"] == {"2026-11": 3}, nov)
    disk = json.load(open(SF._path()))
    check("its file is scrapbook.json beside wrap.json, by account; nothing of it is an account key or rides a request",
          set(disk["by"]) == {"sam"} and "scrap" not in open(os.path.join(REPO, "due_crew", "backend", "api.py")).read()
          and "scrap" not in open(os.path.join(REPO, "due_crew", "account.py")).read())

    # drawn
    view = {"year": 2026, "years": [2026, 2025], "so_far": True, "yline": S.year_line(2026, 200, 41000, True),
            "ystats": S.year_stats(31, 1, S.counts(SF.items("sam"), 2026), 3, 0), "n": len(SF.items("sam")), "any": True, "sev": True,
            "months": [{"m": m, "name": S.MONTHS[m - 1], "line": S.month_line([x for x in xs if x["k"] == "mine"], 9), "sub": S.month_sub(9, 900, 3),
                        "items": [dict(x, key=S.key(x)) for x in xs]} for m, xs in S.months(SF.items("sam") + [dict(pz)], 2026)]}
    h = board.scrapbook_html(view, {"accent": "green"}, {"dre": {"user_id": "dre", "accent": "purple", "look": []}}, [])
    check("drawn in the board's place: the year's page and Share my year, each year, a month a block, the way back, Empty, where it's kept",
          'class="sb-y"' in h and "duecrew:scrapshare:2026" in h and "duecrew:scrapyear:2025" in h and h.count('class="sb-m"') == 2
          and "duecrew:scrapclose" in h and "duecrew:scrapempty" in h and "Kept on this computer. Never sent." in h, h[:200])
    check("a polaroid has Pin up and Delete, anything else Delete alone; every word a sender wrote is escaped",
          h.count(">Pin up<") == h.count('class="sb-k sb-pz"') > 0 and h.count(">Delete<") == view["n"] + 1
          and "go &lt;b&gt;" in h and "go <b>" not in h)
    check("a sender's Pip and colour are theirs as they are now (purple, not the blue it came in)",
          f'style="--al:{board.accent_pair("purple")[0]};' in h and 'class="sv m-idle"' in h
          and 'class="sv ' not in board.scrapbook_html(dict(view, sev=False), {"sev": False}, {}, []).split('class="sb-m"')[1])
    empty = board.scrapbook_html({"year": 2026, "years": [2026], "so_far": True, "yline": S.year_line(2026, 0, 0, True), "months": [], "n": 0}, {})
    check("nothing kept yet: says what comes here; no Empty link", "Nothing kept yet this year" in empty and "scrapempty" not in empty)

    # the board's commands
    keep = (dc.open_scrapbook, dc._swap, dc.cfg, dc.save_cfg, dc._board_on_screen, dc._scrap_load, dict(dc._state), dc.client)
    import due_crew.shares as SH
    import due_crew.sheets as sheets
    saved_pic, saved_confirm = SH.picture, sheets.confirm
    opened, conf, swaps, pics, asked = [], {"accent": "green"}, [], [], []
    dc.open_scrapbook = lambda year=None: opened.append(year)
    dc._swap = lambda c, focus=None: swaps.append(1)
    dc.cfg = lambda: conf
    dc.save_cfg = lambda c, **k: conf.update(c)
    dc._board_on_screen = lambda: True
    dc._scrap_load = lambda year=None: True
    dc.client = lambda: types.SimpleNamespace(user_id="sam")
    SF.client = dc.client
    SH.picture = lambda kind, year=None: pics.append((kind, year))
    sheets.confirm = lambda title, text, yes, then, danger=False, **k: (asked.append((title, danger)), then())
    try:
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        send("scrapbook")
        send("scrapbook:2026")
        send("scrapyear:2025")
        send("scrapshare:2026")
        send("wrappedx:2026")
        dc._state["wrapped_open"] = {"year": 2026}
        a_pz = next(x for x in SF.items("sam") if x["k"] == "pz")
        a_luck = next(x for x in SF.items("sam") if x["k"] == "luck")
        before = len(SF.items("sam"))
        send("scrappin:" + S.key(a_pz))
        pinned = (len(SF.items("sam")), [x["n"] for x in cf.fridge("sam")])
        send("scrappin:" + S.key(a_luck))
        send("scrapdel:" + S.key(a_luck))
        after_del = len(SF.items("sam"))
        send("scrapdel:nonsense")
        send("scrapempty")
        send("scrapclose")
        check("the board's clicks reach it: open, a year, another, Share my year, the line's x for the year, back",
              opened == [None, 2026, 2025] and pics == [("pictureyear", 2026)] and conf.get("wrapped_seen") == "2026"
              and dc._state.get("wrapped_open") is None and swaps, (opened, pics, conf))
        check("Pin up puts a polaroid back on the Decks screen and out of the scrapbook (never a note); "
              "Delete and Empty ask first, in red, and only then go",
              pinned == (before - 1, [a_pz["n"]]) and after_del == before - 2 and SF.items("sam") == []
              and asked == [("Delete this?", True), ("Empty the scrapbook?", True)] and len(cf.fridge("sam")) == 1, (pinned, after_del, asked))
    finally:
        dc.open_scrapbook, dc._swap, dc.cfg, dc.save_cfg, dc._board_on_screen, dc._scrap_load = keep[:6]
        dc._state.clear()
        dc._state.update(keep[6])
        dc.client = keep[7]
        SF.client = keep[7]
        SH.picture, sheets.confirm = saved_pic, saved_confirm
        SF._BOOK.update(path=None, data=None, disk=None)
    src = srcs.glue_src()
    check("its ways in: the foot's Scrapbook, Tools › Due Crew › Scrapbook… (Your year… is gone), the December line",
          '("Scrapbook…", lambda: open_scrapbook())' in src and "Your year…" not in src)


def test_banner_actions_sit_together_v390():
    """A banner with two actions (the closet's Wear it and Closet) keeps
    them together at its right end: each .wc pushes itself right with an
    auto margin, so two of them split the free space and the first floated
    mid-banner (Sam, 16 Oct). They stay on one line, and the closet's words
    sit left when they wrap (the Decks screen's <center> reaches them)."""
    from due_crew import closet
    k = next(t["k"] for t in closet.THINGS if t["slot"] != closet.COSTUME)
    line = board.closet_line([k], [])
    css = board._css({})
    check("the closet's line: two actions, Wear it and Closet", line.count('class="wc"') == 2 and "Wear it" in line)
    check("a banner's second action sits beside the first, no auto margin splitting the space; actions on one line",
          ".dc-wrap .wc + .wc { margin-left: 4px; }" in css and re.search(r"\.dc-wrap \.wc \{[^}]*white-space: nowrap", css)
          and ".dc-wrap.cl-earn { text-align: left; }" in css)


def _keyframe_lists(src):
    """Each keyframe list a script hands animate() (or motion.js's anim()), as text."""
    out = []
    for m in re.finditer(r"\b(?:animate|anim)\(\s*[\w.]+\s*,\s*\[|\.animate\(\s*\[", src):
        i, depth, q = m.end() - 1, 0, None
        for j in range(i, min(len(src), i + 4000)):
            c = src[j]
            if q:
                if c == q and src[j - 1] != "\\":
                    q = None
            elif c in "'\"`":
                q = c
            elif c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if not depth:
                    out.append(src[i:j + 1])
                    break
    return out


def test_motion_ends_where_it_lands_v390():
    """3.9.0, the motion audit (Sam, 17 Oct: Crew to Squads "visibly flicks
    from rectangular to fit the pill"; "everything should be smooth!").
    tools/motion_audit.js plays every motion with its frames held and
    measures the last one against the page once it has cleaned up; these
    are the fixes it led to, so none comes undone: the pick's pill takes
    the new pick's shape (each corner as drawn) and its colours as it goes,
    a height move ends at the box's own height to the fraction of a pixel
    (its padding and border counted, offsetHeight never), a fold ends where
    taking the box out leaves the page (its border, a flex or grid gap),
    a glow ends on the box's own ground, a dimmed box keeps its dim, ↻
    finishes its turn, a cheer's banner and a show fade, the peek grows
    into its words. And no keyframe list anywhere goes backwards, which a
    browser refuses without a word."""
    js = open(os.path.join(REPO, "due_crew", "motion.js"), encoding="utf-8").read()
    check("audit: still one motion.js, the board's and the site's",
          js == open(os.path.join(REPO, "site", "public", "motion.js"), encoding="utf-8").read())
    slide = js[js.index("  function slide(g, from)"):js.index("  // 7: after a tab")]
    on_in = js[js.index("  function onIn(g)"):js.index("  function slide(g, from)")] if "  function onIn(g)" in js else js
    check("audit: the pick's pill: each corner as drawn (a radius past half the height draws as half), round at both ends on its way, the new pick's shape at the end",
          'Math.min(parseFloat(cs[k]) || 0, b.height / 2, b.width / 2) + "px"' in on_in
          and "borderRadius: from.pill ? from.r" in slide and "borderRadius: to.pill ? to.r" in slide
          and "kf = [k0, { borderRadius: Math.min(from.h, to.h) / 2 + \"px\", offset: 0.5 }, k1]" in slide, slide[:300])
    check("audit: the pick's colours are read before anything moves; the one left eases back, the new one's edge turns as the pill arrives",
          slide.index("var off = cw ?") < slide.index("var a = anim(ind, kf")
          and "anim(was, [Object.assign({ color: from.color }, edges(from.edge)), w1, { color: off.color, offset: 0.6 }, w2," in slide
          and "anim(on, [edges(off.edge), n1, n2, edges(to.edge)], { duration: BASE });" in slide
          and "w1.offset = 0.1; w2[wi] = from.edge; w2.offset = 0.9;" in slide and "n1[ni] = to.edge; n1.offset = 0.1; n2.offset = 0.9;" in slide)
    heights = re.findall(r"height: ([^,}\]]+)", js)
    loose = [h for h in heights if "inner(" not in h and h.strip() not in ('"0px"', 'h + "px"', '(from.pill ? from.h : 2) + "px"',
                                                                         '(to.pill ? to.h : 2) + "px"', 'r.height + "px"', 'z.h + "px"',
                                                                         'a.height + "px"', 'b.height + "px"')]  # the day ring: border-box
    check("audit: every height move goes to style.height's own measure (inner, from tall): no padding or border overshoot, no rounding",
          "function tall(el)" in js and "function inner(el, outer)" in js and not loose
          and not re.search(r"inner\([^)]*offsetHeight", js) and "h: tall(el)" in js and "snap.h = tall(root)" in js, loose)
    fold = js[js.index("  function fold(el"):js.index("  // 20: a")]
    check("audit: a fold ends where taking it out leaves the page: what's left of it (room), and in a grid the neighbour closes the gap",
          "function room(el, x)" in js and "function close(el, r, a, b, o)" in js and "room(el)" in fold and "close(el, r, 0, 1" in fold
          and 'borderTopStyle: "none"' in fold and "if (pull) pull.cancel();" in fold
          and "room(el), pull = close(el, r, 1, 0)" in js and "room(g, true)" in js)
    check("audit: a glow ends on the box's own ground (my row's tint never blinks off)",
          'var bg = getComputedStyle(el).backgroundColor || "transparent";' in js and '{ backgroundColor: bg }' in js)
    check("audit: opacity 1 is 'as it is': a dimmed day keeps its dim at a move's end",
          "k.opacity === 1 ? Object.assign({}, k, { opacity: op }) : k" in js)
    check("audit: ↻ finishes its turn: a redraw carries on from where it had got to, and the ten-second stop waits for a turn's end",
          "snap.spin = ((sa.currentTime || 0) % 800) / 800 * 360" in js and 'rotate(" + snap.spin + "deg)' in js
          and '"animationiteration"' in js)
    sj = board.SHOW_JS
    stop = sj[sj.index("  function stop()"):sj.index("  function end(ms)")]
    check("audit: a show ended by a click or Esc fades away, takes no more clicks, then goes",
          "o.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 260" in stop and "o.inert = true" in stop
          and "a.onfinish = a.oncancel = function () { o.remove(); };" in stop and '"#dc-show[aria-hidden=true] *{pointer-events:none!important}"' in sj)
    fl = board.flurry_js(["\U0001F389"], "Dre sent cheers", back=("dre", "\U0001F389"))
    check("audit: a cheer's banner fades in (and drops in, with motion), and a click fades it, once",
          "banner.animate([{ opacity: 0, transform: 'translateX(-50%) translateY(' + (still ? 0 : -10) + 'px)' }" in fl
          and "banner.style.pointerEvents = 'none';" in fl and "setTimeout(function() { banner.remove(); }, 300);" in fl)
    from due_crew import cards as K
    fj = K.float_js({"text": "x", "accent": ["#2e7d32", "#7cc47f"]})
    check("audit: the peek's Show grows the bubble into its words, which fade in once there's room; the bar's chip fades its words in",
          "grow.animate([{width: b0.width + 'px', height: b0.height + 'px'}" in fj and "{opacity: 0, offset: 0.4}" in fj
          and "{opacity: getComputedStyle(x).opacity}" in K.chip_js({"text": "x", "accent": "#2e7d32"}))
    bp = fakes.board_source()
    sthit = bp[bp.index("@keyframes sthit"):].split("\n")[0]
    check("audit: Settings' found row glows back to its own ground (from, and no to)", "{ from {" in sthit and "to {" not in sthit, sthit)
    srcs = {"motion.js": js, "show.js": sj, "board/": bp,
            "cards.py": open(os.path.join(REPO, "due_crew", "cards.py"), encoding="utf-8").read(),
            "room_model.py": open(os.path.join(REPO, "due_crew", "room_model.py"), encoding="utf-8").read()}
    for f in sorted(os.listdir(os.path.join(REPO, "site", "public"))):
        if f.endswith(".js"):
            srcs["site/" + f] = open(os.path.join(REPO, "site", "public", f), encoding="utf-8").read()
    bad, n = [], 0
    for name, src in srcs.items():
        for kf in _keyframe_lists(src):
            offs = [float(x) for x in re.findall(r"\boffset: ([0-9.]+)\b", kf)]
            n += 1
            if offs != sorted(offs) or any(o > 1 for o in offs):
                bad.append((name, kf[:120]))
    check("audit: no keyframe list anywhere goes backwards (a browser drops the whole move without a word)", n >= 60 and not bad, (n, bad))
    import shutil
    import subprocess
    if shutil.which("node"):
        r = subprocess.run(["node", "--check", os.path.join(REPO, "tools", "motion_audit.js")], capture_output=True, text=True)
        check("audit: tools/motion_audit.js is valid JS", r.returncode == 0, r.stderr[:300])


def test_doodle_cheers_v391():
    """3.9.1, doodle cheers (Sam: "create the doodles thing"): a cheer can
    carry a drawing (strokes on the 300 x 170 pad) or a sign their Pip holds
    up. Numbers and one line of words, both ways; it lands held up by the
    sender's Pip (in the banner with Pip off or Reduce motion), and stays on
    my fridge in Pip's closet, on this computer, till I take it down."""
    from due_crew.backend.shapes import clean_doodle
    from due_crew import fridge as FR
    draw = {"k": "draw", "s": [[0, 10, 20, 30, 40, 50, 60], [3, 299, 169]]}
    check("doodle shape: strokes of whole points on the pad, kept as they are; pens 0 to 15 (thin or thick in mine, black or any accent)",
          clean_doodle(draw) == draw and clean_doodle(dict(draw)) is not draw
          and clean_doodle({"k": "draw", "s": [[p, 1, 1] for p in range(16)]}) is not None)
    many = [n for i in range(2001) for n in (i % 300, i % 170)]
    bad = [{"k": "draw", "s": []}, {"k": "draw", "s": [[16, 1, 1]]}, {"k": "draw", "s": [[0, 1]]},
           {"k": "draw", "s": [[0, 301, 1]]}, {"k": "draw", "s": [[0, 1, 171]]}, {"k": "draw", "s": [[0, 1.5, 1]]},
           {"k": "draw", "s": [[0, True, 1]]}, {"k": "draw", "s": [[0, -1, 1]]}, {"k": "draw", "s": [[0] + many]},
           {"k": "draw", "s": [[0, 1, 1]] * 201}, {"k": "draw", "s": [[0, 1, 1]], "c": "#f00"},
           {"k": "sign", "t": "  "}, {"k": "sign", "t": 5}, {"k": "pic", "src": "https://x"}, "draw", None, []]
    check("doodle shape: anything the Worker turns away is None (no colour, no picture, no link, past the ceilings)",
          all(clean_doodle(b) is None for b in bad))
    check("doodle shape: 2,000 points is the ceiling, not past it",
          clean_doodle({"k": "draw", "s": [[2] + many[:4000]]}) is not None)
    party = "\U0001F389"
    check("a sign: one line, 24 at most as the Worker counts, an emoji never cut in half",
          clean_doodle({"k": "sign", "t": "  you've\ngot   this "}) == {"k": "sign", "t": "you've got this"}
          and clean_doodle({"k": "sign", "t": "x" * 40})["t"] == "x" * 24
          and clean_doodle({"k": "sign", "t": "x" * 23 + party})["t"] == "x" * 23)
    # both ways, through the fake Worker
    store = world({"sam": "Sammy", "dre": "Dre", "nia": "Nia"}, {"sam": ["dre", "nia"], "dre": ["sam"]})
    dre = new_client(store, "dre", "Dre")
    sent = dre.send_cheer("sam", party, "go", doodle=draw)
    check("sent: one request, the drawing as one more field of the cheer", sent is True
          and store.cheers[("sam", "dre")]["doodle"] == draw)
    dre.send_cheer("sam", "\U0001F340", "luck", luck=True, doodle=draw)
    lucky = store.cheers[("sam", "dre")]
    dre.send_cheer("sam", party, doodle={"k": "draw", "s": [[16, 1, 1]]})
    check("never on a good-luck line or a tip; a broken one isn't sent, the cheer still goes",
          lucky["doodle"] is None and lucky["luck"] and store.cheers[("sam", "dre")]["doodle"] is None)
    dre.send_cheer("sam", party, doodle={"k": "sign", "t": "you've got this"})
    sam = new_client(store, "sam", "Sammy")
    data, _labels, _t = fetch_as(store, sam, make_user_col([TODAY]))
    check("received: the sign comes with the cheer, read through the same gate",
          data["cheers"][0].get("doodle") == {"k": "sign", "t": "you've got this"}, data["cheers"])
    check("only to someone who added me, as every cheer (Nia hasn't added Dre)",
          dre.send_cheer("nia", party, doodle=draw) is False and ("nia", "dre") not in store.cheers)
    newer = store._cheer

    def older(me, to, body):  # a Worker from before 3.9.1: the field is one it doesn't know
        if "doodle" in body:
            raise fakes.Bad(400, "bad_cheer")
        return newer(me, to, body)
    store._cheer = older
    try:
        went = dre.send_cheer("sam", "\U0001F525", "still", doodle=draw)
    finally:
        store._cheer = newer
    check("a server from before doodles turns the field away: the cheer still goes, without it (and says so: no \"and a drawing\")",
          went == "plain" and store.cheers[("sam", "dre")]["note"] == "still" and store.cheers[("sam", "dre")].get("doodle") is None)
    # drawn: numbers and escaped words only
    art = board.doodle_html(draw, "blue")
    blue = board.accent_pair("blue")[0]
    check("drawn: a path a stroke, my colour or ink, thin or thick; nothing but numbers in it",
          art.count("<path") == 2 and f'stroke="{blue}" stroke-width="3"' in art and f'stroke="{board.DOODLE_INK}" stroke-width="6"' in art
          and "M299 169 l0.1 0" in art and 'viewBox="0 0 300 170"' in art)
    sign = board.doodle_html({"k": "sign", "t": "<b>hi</b>"})
    check("a sign's words are escaped; a broken doodle draws nothing",
          "&lt;b&gt;hi&lt;/b&gt;" in sign and "<b>" not in sign and board.doodle_html({"k": "draw", "s": [[16, 1, 1]]}) == "")
    from due_crew.backend.shapes import DOODLE_INKS, DOODLE_PEN_MAX
    inked = board.doodle_html({"k": "draw", "s": [[2 * (2 + i) + 1, 1, 1] for i in range(len(DOODLE_INKS))] + [[0, 1, 1]]}, "rose")
    check("every accent on the pad (Sam: \"all of our colors\"): pen >> 1 names one of ours by place, in the board's own shades; 0 is still the sender's",
          DOODLE_PEN_MAX == 15 and set(DOODLE_INKS) == set(board.ACCENTS) and len(DOODLE_INKS) == len(board.ACCENTS)
          and all(f'stroke="{board.accent_pair(n)[0]}" stroke-width="6"' in inked for n in DOODLE_INKS)
          and inked.endswith(f'<path d="M1 1 l0.1 0" stroke="{board.accent_pair("rose")[0]}" stroke-width="3"/></svg>'))
    ents = [{"user_id": "dre", "name": "Dre", "accent": "purple", "look": ["cap"], "you": False}]
    land = board.doodle_landing({"from": "dre", "name": "Dre", "doodle": draw}, ents, {"sev": True})
    still = board.doodle_landing({"from": "dre", "name": "Dre", "doodle": draw}, ents, {"sev": False})
    check("it lands held up by their Pip, arms up, in their colour and look; Pip off: no Pip; no doodle: nothing",
          land and "m-idle" in land["pip"] and land["a"] == list(board.accent_pair("purple"))
          and board.accent_pair("purple")[0] in land["html"] and still["pip"] is None
          and board.doodle_landing({"from": "dre"}, ents, {"sev": True}) is None)
    js = board.flurry_js([party], "🎉 Dre sent cheers", back=("dre", party), pips=[{"svg": "<svg></svg>", "a": ["#1", "#2"]}],
                         doodle=dict(land, html=board.doodle_html({"k": "sign", "t": "</script><b>"})))
    check("the landing: the doodle rides in as data (no '</' to end the script), buys time, and its Pip holds it up in the show's place",
          "</script><b>" not in js and "&lt;/script&gt;" in js and "linger += 2500" in js and "if (held)" in js
          and "var dd = null" in board.flurry_js([party], "x"))
    # the landing's caption (Sam: "put the included text ... under like a caption ... with their name")
    capt = board.doodle_landing({"from": "dre", "name": "Dre Smith", "note": "good luck", "doodle": draw, "ni": 0}, ents, {"sev": True})
    js = board.flurry_js([party], "🎉 Dre sent cheers", notes=["good luck"], pips=[{"svg": "<svg></svg>", "a": ["#1", "#2"]}], doodle=capt)
    dd = json.loads(re.search(r"var dd = (\{.*?\}), held", js).group(1).replace("<\\/", "</"))
    check("held up, the note it came with goes under it with who it's from, and leaves the banner; in the banner (Pip off, Reduce motion) it stays put",
          dd["note"] == "good luck" and dd["from"] == "Dre" and dd["ni"] == 0 and "paper(170, 96, true)" in js
          and "noteEls[dd.ni].remove()" in js and "paper(150, 85, false)" in js and "'from ' + dd.from" in js)
    # the fridge: mine, around the Decks screen, the last KEEP, on this computer
    cheers = [{"from": "dre", "name": "Dre", "at": f"2026-10-{d:02d}T10:00:00Z", "note": f"day {d}", "doodle": draw} for d in range(1, 30)]
    items = FR.add([], cheers + [{"from": "mo", "name": "Mo", "at": "x", "doodle": None}], {"dre": "purple"})
    again = FR.add(items, cheers[-2:], {})
    check("the fridge: the ones that carried a doodle, each once, with its note, the last 12, colour as it came",
          FR.KEEP == 12 and len(items) == 12 and items[-1]["at"].startswith("2026-10-29") and items[0]["at"].startswith("2026-10-18")
          and items[0]["a"] == "purple" and items[-1]["n"] == "day 29" and again == items)
    k = FR.key(items[-1])
    moved = FR.move(items, k, "l", -9000, 250)
    check("take one down by its key; where I dragged it is kept beside the board (side, px from its edge, px down; clamped); "
          "junk and an older spot (thousandths of the window) are dropped",
          len(FR.take_down(items, k)) == FR.KEEP - 1 and all(FR.key(x) != k for x in FR.take_down(items, k))
          and moved[-1]["p"] == ["l", -FR.REACH, 250] and "p" not in moved[0]
          and FR.move(items, k, "up", 5, 5)[-1].get("p") is None
          and FR.clean([dict(moved[-1], p=["r", 40, 120])])[0]["p"] == ["r", 40, 120]
          and FR.clean([{"d": {"k": "pic"}}, 5, {"from": "x", "d": draw, "p": [5, 200]}]) == [{"from": "x", "name": "?", "at": "", "a": "", "n": "", "d": draw}])
    people = {"dre": {"user_id": "dre", "name": "Dre", "look": ["cap"], "accent": "purple"}}
    fr = board.fridge_html(moved[-3:], people, {"sev": True})
    tape = board.accent_pair("purple")[1].lstrip("#")
    check("pinned around the Decks screen as Polaroids (Sam's pick): newest first, the note on the frame, their Pip and name "
          "(no \"from\", for room), taped up in their colour, a × to take it down, my place for the one I moved",
          fr.count('class="fz"') == 3 and fr.index("29 Oct") < fr.index("27 Oct") and "&ldquo;day 29&rdquo;" in fr
          and '<div class="fw"><span class="sv-slot"' in fr and ">from " not in fr and f"duecrew:fridgedown:{k}" in fr
          and f'data-s="l" data-x="{-FR.REACH}" data-y="250"' in fr
          and f"--fa:{board.accent_pair('purple')[0]}" in fr and board.fridge_html([], people, {}) == ""
          and f"--ft:rgba({int(tape[0:2], 16)},{int(tape[2:4], 16)},{int(tape[4:6], 16)},.6)" in fr
          and "background: var(--ft)" in board.FRIDGE_CSS and "color-mix" not in board.FRIDGE_CSS
          and '<div class="fw"><b>Dre</b>' in board.fridge_html(moved[-1:], people, {"sev": False})
          and "Fridge" not in board.closet_html({"tab": "Yours", "have": {}, "look": []}, {"accent": "green"}))
    fjs = board.fridge_js()
    check("its script places them (my spot, else the gutters beside the board, else a pile in the corner) and drags; a drop says where",
          "b[el.dataset.s] + Number(el.dataset.x)" in fjs and "room.l || room.r" in fjs and "duecrew:fridgemove:" in fjs
          and "setPointerCapture" in fjs and "resize" in fjs and "/ 1000" not in fjs)
    check("a spot the window's too small for waits on the pile and keeps its place for when the window grows",
          "x >= 4 && x + nw <= W - 4" in fjs and "if (x === null) {" in fjs and "!el.dataset.s && (room.l || room.r)" in fjs
          and "el.dataset.s = s" in fjs and "below any I left in the way" in fjs)
    import shutil
    import subprocess
    node = subprocess.run(["node", "--check", "-"], input=fjs, capture_output=True, text=True) if shutil.which("node") else None
    check("the fridge's script parses", node is None or node.returncode == 0, node and node.stderr[:300])
    # the clicks, as the board sends them
    import due_crew as dc
    from due_crew import closet_flow as cf
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    wrap = _patched_due_crew()
    swaps = []
    saved = (dc._swap, dc._board_on_screen)
    dc._swap = lambda c, focus=None: swaps.append(1)
    dc._board_on_screen = lambda: True
    try:
        cf.keep_doodles(cheers[-3:], ents)
        n0 = len(cf.fridge())
        k0 = FR.key(cf.fridge()[0])
        dc._on_js(False, as_board(f"duecrew:fridgemove:{k0}:l:-150:640"), DeckBrowser())
        placed, redrew = cf.fridge()[0].get("p"), len(swaps)
        dc._on_js(False, as_board("duecrew:fridgemove:nope:l:1:1"), DeckBrowser())
        dc._on_js(False, as_board(f"duecrew:fridgemove:{k0}:x:1:1"), DeckBrowser())
        dc._on_js(False, as_board(f"duecrew:fridgemove:{k0}:r:1"), DeckBrowser())
        dc._on_js(False, as_board(f"duecrew:fridgemove:{k0}:r:-:5"), DeckBrowser())
        dc._on_js(False, as_board(f"duecrew:fridgemove:{k0}:r:--5:5"), DeckBrowser())
        dc._on_js(False, as_board(f"duecrew:fridgemove:{k0}:r:²:5"), DeckBrowser())
        kept = cf.fridge()[0].get("p")
        dc._on_js(False, as_board("duecrew:fridgedown:" + k0), DeckBrowser())
        dc._on_js(False, as_board("duecrew:fridgedown:nope"), DeckBrowser())
        check("on the fridge as they land; a drag keeps its place without a redraw; × takes it down and the board redraws; through the board's own handler",
              n0 == 3 and placed == ["l", -150, 640] and kept == placed and redrew == 0 and len(cf.fridge()) == 2 and swaps
              and len(wrap._wrap_data()["fridge"]) == 2 and all(FR.key(x) != k0 for x in cf.fridge()))
    finally:
        dc._swap, dc._board_on_screen = saved


def test_fridge_pip_whole_v392():
    """3.9.2 (Sam: "pips get cutoff on the polaroids"): the line under a
    Polaroid never clips (only the name shortens with …), and Pip's slot
    leaves room above it for the head, hat and what it holds."""
    css = board.FRIDGE_CSS
    fw = css[css.index("#dc-fridge .fw {"):css.index("}", css.index("#dc-fridge .fw {"))]
    nm = css[css.index("#dc-fridge .fw b {"):css.index("}", css.index("#dc-fridge .fw b {"))]
    slot = css[css.index("#dc-fridge .fw .sv-slot {"):css.index("}", css.index("#dc-fridge .fw .sv-slot {"))]
    check("fridge: the caption line doesn't clip; the name does, with …; Pip's slot has its head's room",
          "overflow" not in fw and "overflow: hidden" in nm and "text-overflow: ellipsis" in nm and "min-width: 0" in nm
          and "margin: 9px" in slot, (fw, nm, slot))


def test_fridge_dates_local_v392():
    """3.9.2 (Sam: "some of the dates on polaroids are wrong"): a cheer's at
    comes from the server in UTC, and the Polaroid showed its first ten
    characters, the UTC date, so a doodle sent on an American evening was
    dated the next day. It's this computer's day now."""
    import time as _time
    check("a day stays that day; anything else is no date",
          board._short_day("2026-10-14") == "14 Oct" and board._short_day("") == "" and board._short_day("x") == ""
          and board._short_day(None) == "" and board._short_day("2026-13-40T99:00:00Z") == "")
    if not hasattr(_time, "tzset"):
        return
    old_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "America/New_York"
        _time.tzset()
        item = {"from": "dre", "name": "Dre", "at": "2026-10-15T01:30:00Z", "a": "", "n": "", "d": {"k": "sign", "t": "go"}}
        fr = board.fridge_html([item], {}, {"sev": False})
        check("9.30 pm in New York on the 14th is the 14th on its Polaroid, not the server's 15th",
              board._short_day("2026-10-15T01:30:00Z") == "14 Oct" and "14 Oct" in fr and "15 Oct" not in fr, fr)
        os.environ["TZ"] = "Asia/Tokyo"
        _time.tzset()
        check("and 10.30 am in Tokyo on the 15th is the 15th; a day with no clock is never moved",
              board._short_day("2026-10-15T01:30:00Z") == "15 Oct" and board._short_day("2026-10-14T23:30:00+00:00") == "15 Oct"
              and board._short_day("2026-10-14") == "14 Oct")
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        _time.tzset()


def test_fridge_dark_v392():
    """3.9.2 (Sam: "also need dark mode for polaroids"): at night a Polaroid's
    frame and photo go dark, a doodle's black ink reads light and each colour
    takes its night shade, Pip and Undo the sender's night accent; as
    Settings › Theme says (Match Anki: its night mode and the computer's)."""
    draw = {"k": "draw", "s": [[2, 10, 10, 50, 50], [0, 60, 60, 90, 90], [2 * (2 + board.DOODLE_INKS.index("rose")), 5, 5, 9, 9]]}
    item = {"from": "dre", "name": "Dre", "at": "2026-10-14T15:00:00Z", "a": "purple", "n": "", "d": draw}
    people = {"dre": {"user_id": "dre", "name": "Dre", "look": [], "accent": "purple"}}
    auto = board.fridge_html([item], people, {"sev": True})
    dark = board.fridge_html([item], people, {"sev": True, "theme": "dark"})
    light = board.fridge_html([item], people, {"sev": True, "theme": "light"})
    pl, pd = board.accent_pair("purple")
    rl, rd = board.accent_pair("rose")
    check("dark: the frame, photo and words on tokens; the night set by Settings › Theme, Match Anki by its night mode",
          "background: var(--fz-bg)" in board.FRIDGE_CSS and "background: var(--fz-photo)" in board.FRIDGE_CSS
          and "#fff" not in board.FRIDGE_CSS and "#2b2d29" not in board.FRIDGE_CSS
          and "--fz-bg: #33352f" in dark and "--fz-bg: #33352f" not in light and "--fz-bg: #fff" in light
          and "prefers-color-scheme: dark" in auto and "body.nightMode #dc-fridge .fz" in auto)
    check("dark: black ink reads light, each colour its night shade, Pip and Undo the sender's night accent",
          f'stroke="{board.DOODLE_INK}"' in dark and f'path[stroke="{board.DOODLE_INK}"] {{ stroke: var(--fz-2b2d29, {board.DOODLE_INK}); }}' in dark
          and "--fz-2b2d29: #e6e8e3;" in dark and f'stroke="{pl}"' in dark and f"--fz-{pl[1:]}: {pd};" in dark
          and f'stroke="{rl}"' in dark and f"--fz-{rl[1:]}: {rd};" in dark
          and f"--fa:{pl};--fd:{pd};" in dark and "--fz-acc: var(--fd)" in dark and "--sv-a: var(--fz-pip)" in board.FRIDGE_CSS
          and "--fz-pip: var(--pd, var(--fd))" in dark and "--fz-pip: var(--pa, var(--fa))" in light)
    check("a theme change draws it again (it's kept as last drawn)", dark != light != auto)
    # 3.9.10 (Sam: "everyone's polaroids are now showing their pip as green even if they use a different color"):
    # the Pip wears the colour its person has now; the tape and the drawing keep the one it came in
    bl, bd = board.accent_pair("blue")
    gl, gd = board.accent_pair("green")
    moved = board.fridge_html([item], {"dre": dict(people["dre"], accent="blue")}, {"sev": True, "theme": "light"})
    bare = board.fridge_html([dict(item, a="")], {"dre": dict(people["dre"], accent="blue")}, {"sev": True, "theme": "light"})
    gone = board.fridge_html([dict(item, a="")], {}, {"sev": True, "theme": "light"})
    check("a polaroid's Pip wears its person's colour as it is now; the tape keeps the one it came in",
          f"--fa:{pl};--fd:{pd};--pa:{bl};--pd:{bd};" in moved and moved != light)
    check("…one that came with no colour takes theirs, tape and Pip; nobody to ask: the default",
          f"--fa:{bl};--fd:{bd};--pa:{bl};--pd:{bd};" in bare and f"--fa:{gl};--fd:{gd};--pa:{gl};--pd:{gd};" in gone)


def test_fridge_account_and_undo_v391():
    """3.9.1, before release: the fridge is this Anki profile's file, and
    more than one account can sign in on a profile, so it keeps whose
    drawings it holds, shows them to that account alone and empties at
    sign-out. And × leaves "In your scrapbook · Undo" in the drawing's place for a
    few seconds; Undo puts it back where it was."""
    import due_crew as dc
    from due_crew import closet_flow as cf, fridge as FR
    from aqt.deckbrowser import DeckBrowser
    wrap = _patched_due_crew()
    draw = {"k": "draw", "s": [[0, 10, 10, 50, 50]]}
    cheers = [{"from": "dre", "name": "Dre", "at": f"2026-10-0{d}T10:00:00Z", "note": f"day {d}", "doodle": draw} for d in range(1, 4)]
    ents = [{"user_id": "dre", "accent": "blue", "you": False}]
    # an older fridge (before 3.9.1's owner): whoever's signed in
    wrap._wrap_data()["fridge"] = FR.add([], cheers[:1], {})
    legacy = (len(cf.fridge("sam")), len(cf.fridge("nia")))
    cf.keep_doodles(cheers[1:2], ents, "sam")
    adopted = (wrap._wrap_data().get("fridge_uid"), len(cf.fridge("sam")), cf.fridge("nia"))
    cf.keep_doodles(cheers[2:], ents, "nia")
    nias = (wrap._wrap_data().get("fridge_uid"), [x["n"] for x in cf.fridge("nia")], cf.fridge("sam"))
    check("fridge to account: an older one is whoever's signed in, then theirs; another account sees none of it, "
          "and its own first drawing starts a fridge of its own",
          legacy == (1, 1) and adopted == ("sam", 2, []) and nias == ("nia", ["day 3"], []), (legacy, adopted, nias))
    saved = (dc._reset_runtime, dc._rerender)
    dc._reset_runtime, dc._rerender = (lambda **k: None), (lambda: None)
    try:
        dc._on_signed_out()
    finally:
        dc._reset_runtime, dc._rerender = saved
    check("fridge to account: signing out empties it (the drawings were that account's)",
          "fridge" not in wrap._wrap_data() and "fridge_uid" not in wrap._wrap_data() and cf.fridge("nia") == [] and cf.gone() is None)
    src = srcs.glue_src()
    check("fridge to account: the board draws the signed-in account's, and keeps a landing one for it",
          "fridge=closet_flow.fridge(client().user_id)" in src and 'cf.keep_doodles(fresh, data["entries"], client().user_id)' in src)

    # Undo
    cf.keep_doodles(cheers, ents, "sam")
    first, mid = cf.fridge("sam")[0], cf.fridge("sam")[1]
    cf.move_fridge(FR.key(mid), "r", 40, 300)
    k = FR.key(mid)
    swaps = []
    saved = dc._swap
    dc._swap = lambda c, focus=None: swaps.append(1)
    try:
        dc._on_js(False, as_board("duecrew:fridgedown:" + k), DeckBrowser())
        g = cf.gone()
        html = board.fridge_html(cf.fridge("sam"), {}, {"sev": False}, g)
        dc._on_js(False, as_board("duecrew:fridgeback:nope"), DeckBrowser())
        wrong = [FR.key(x) for x in cf.fridge("sam")]
        dc._on_js(False, as_board("duecrew:fridgeback:" + k), DeckBrowser())
        back = cf.fridge("sam")
        again = cf.put_back(k)
    finally:
        dc._swap = saved
    pill = re.search(r'<div class="fz fgone"[^>]*>.*?</div>', html)
    order = re.findall(r'data-k="([0-9a-f]+)"', html)
    check("undo: × takes it down and leaves In your scrapbook · Undo where it was (its spot, its sender's colour), for the seconds it has",
          g and g["k"] == k and pill and f"duecrew:fridgeback:{k}" in pill.group(0) and 'data-s="r" data-x="40" data-y="300"' in pill.group(0)
          and f"--fa:{board.accent_pair('blue')[0]}" in pill.group(0) and 'role="status"' in pill.group(0)
          and re.search(r"--fg:-\d+\.\ds", pill.group(0)) and order == [FR.key(x) for x in reversed(back)]
          and len(swaps) >= 1, (g, html[-600:]))
    check("undo: Undo puts it back in its place with its spot, once; a key that isn't the one just taken down does nothing",
          [x["n"] for x in back] == ["day 1", "day 2", "day 3"] and back[1].get("p") == ["r", 40, 300]
          and k not in wrong and len(wrong) == 2 and again is False and back[0] == first, ([x["n"] for x in back], back[1].get("p")))
    cf.take_down(FR.key(first))
    cf._GONE["t"] -= cf.UNDO_SECS + 1
    check("undo: after its seconds the board leaves it out (its fade already hid it), and the cached fridge comes back",
          cf.gone() is None and 'class="fz fgone"' not in board.fridge_html(cf.fridge("sam"), {}, {"sev": False}, cf.gone())
          and board.FRIDGE_UNDO == cf.UNDO_SECS
          and "animation: dcfgone %ds linear forwards" % cf.UNDO_SECS in board.FRIDGE_CSS
          and "el.classList.contains('fgone')" in board.FRIDGE_JS and "el.isConnected" in board.FRIDGE_JS)


def test_native_emoji_picker_v391():
    """3.9.1 (Sam: "the emoji drawer is missing tons that are natively
    supported. want the other option to just open the native drawer?"): on a
    Mac or Windows the Cheer window's "other" opens the computer's own
    picker into a focused box; where there's none (Linux), or asking fails,
    the window's own drawer opens instead."""
    import ctypes
    import types as _types
    from due_crew import native_emoji as NE
    check("the computer's own picker: a Mac's and Windows', never Linux's; asking where there's none is a no",
          NE.available("darwin") and NE.available("win32") and not NE.available("linux")
          and NE.open_picker("linux") is False and NE.open_picker("darwin") in (True, False))
    presses = []
    had = getattr(ctypes, "windll", None)
    ctypes.windll = _types.SimpleNamespace(user32=_types.SimpleNamespace(keybd_event=lambda *a: presses.append(a)))
    try:
        ok = NE.open_picker("win32")
    finally:
        if had is None:
            del ctypes.windll
        else:
            ctypes.windll = had
    check("Windows: Win + . pressed and let go, in that order",
          ok is True and presses == [(0x5B, 0, 0, 0), (0xBE, 0, 0, 0), (0xBE, 0, 2, 0), (0x5B, 0, 2, 0)], presses)
    js = board.cheer_overlay_js({"uid": "dre", "name": "Dre", "emojis": ["🎉"], "native": True})
    plain = board.cheer_overlay_js({"uid": "dre", "name": "Dre", "emojis": ["🎉"]})
    check("the window: with a picker, other gives a focused box and asks for it; without, the drawer; the box's pick is picked; Esc puts other back",
          '"native": true' in js and '"native": false' in plain and "if (V.native) { native(); }" in js
          and "pycmd('duecrew:emojipicker:' + [r.left, r.top, r.width, r.height]" in js
          and "window.dcCheerNoNative = function () { unpick(); openDrawer(); };" in js
          and "if (t) { unpick(); choose(t); }" in js and "if (pickIn.style.display !== 'none') { unpick(); other.focus(); }" in js)
    check("3.9.2 (Sam: the custom picker didn't take the pick): our own box takes it over the page's, the page gets it; "
          "the window's close or Esc puts the box away",
          "window.dcCheerPicked = function (t) { var e = oneEmoji(String(t || '').trim()); if (e) { unpick(); choose(e); } };" in js
          and "pycmd('duecrew:emojipickeroff|' + window.dcBK)" in js and "closing: unpick  // 3.9.2: other's box" in js
          and "window.dcCheerUnpick = function () { unpick(); other.focus(); };" in js)
    check("3.9.2: what the box hands on: an emoji (a whole one, a skin tone and a job in it), never a letter or a digit",
          NE.first_emoji(" 👩🏽‍⚕️ ") == "👩🏽‍⚕️" and NE.first_emoji("x") == ""
          and NE.first_emoji("5") == "" and NE.first_emoji("") == ""
          and NE.picked_js("🎉'</script>") == 'window.dcCheerPicked && window.dcCheerPicked("\\ud83c\\udf89\'</script>");')
    import due_crew as dc
    from due_crew import app as appmod
    from aqt.deckbrowser import DeckBrowser
    evals, asked = [], []
    saved = (appmod.board_eval, NE.catch, NE.drop, NE.available)
    appmod.board_eval = lambda code: evals.append(code)
    try:
        NE.available = lambda platform=None: False  # 3.9.3: no picker, as on Linux, whatever this computer has
        dc._on_js(False, as_board("duecrew:emojipicker"), DeckBrowser())
        NE.catch = lambda x, y, w, h, then, gone: asked.append((x, y, w, h)) or then("🦋") or True
        dc._on_js(False, as_board("duecrew:emojipicker:412:230:72:44"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:emojipicker:1:2:3:9999999"), DeckBrowser())
        NE.drop = lambda: asked.append("off")
        dc._on_js(False, as_board("duecrew:emojipickeroff"), DeckBrowser())
    finally:
        appmod.board_eval, NE.catch, NE.drop, NE.available = saved
    check("emojipicker from the Decks screen: with no picker to open, the window is told to open its drawer",
          evals[0] == "window.dcCheerNoNative && window.dcCheerNoNative();", evals)
    check("3.9.2's audit: a quick pick, a scroll or a resize puts Anki's box away (it sat where 'pick one' was)",
          "b.addEventListener('click', function () { unpick(); choose(x, true); });" in js
          and "window.addEventListener('resize', away);" in js and "back.addEventListener('scroll', away, true);" in js
          and "window.removeEventListener('resize', away);" in js and "back.removeEventListener('scroll', away, true);" in js)
    downs = []
    NE.drop, keep_drop, keep_up = (lambda: downs.append(1)), NE.drop, appmod._decks[0]
    try:
        appmod.on_state_will_change("review", "deckBrowser")
        appmod.on_set_content(None, DeckBrowser())
        appmod.on_set_content(None, type("ReviewerBottomBar", (), {})())
    finally:
        NE.drop, appmod._decks[0] = keep_drop, keep_up
    check("3.9.2's audit: and it goes with the page it sat on (another screen, a redraw), not with a bar's page",
          len(downs) == 2, downs)
    check("3.9.2: with one, the box goes where the page's is, and the pick goes back to the page; a place it can't be is ignored",
          asked == [(412, 230, 72, 44), (0, 0, 64, 40), "off"] and evals[1] == NE.picked_js("🦋"), (asked, evals))


def test_more_emoji_v392():
    """3.9.2 (Sam's pick): the Cheer window's Other (and a status) takes the
    emoji a picker gives below U+2190 (© ® ‼ ⁉ ™ ℹ); keycaps start with a
    digit, which the Worker refuses, so they stay out; letters never pass.
    The page's oneEmoji keeps the same list (shapes.EMOJI_LOW)."""
    from due_crew.backend import shapes as S
    from due_crew import native_emoji as NE
    ok = ["©️", "®️", "‼️", "⁉️", "™️", "ℹ️"]
    check("© ® ‼ ⁉ ™ ℹ pass, as the cheer and the native box take them; keycaps, letters and digits never",
          all(S.clean_emoji(t) == t and NE.first_emoji(t) == t for t in ok)
          and all(S.clean_emoji(t) == "" and NE.first_emoji(t) == "" for t in ("1️⃣", "#️⃣", "a", "5", "i")),
          [(t, S.clean_emoji(t), NE.first_emoji(t)) for t in ok])
    js = board.cheer_overlay_js({"uid": "dre", "name": "Dre", "emojis": ["🎉"]})
    lst = re.search(r"var low = \[([^\]]*)\];", js).group(1)
    check("the page's oneEmoji takes the same list", sorted(int(x, 16) for x in lst.split(", ")) == sorted(S.EMOJI_LOW), lst)
    # 3.9.2's QoL pass: England's flag (tag characters) whole; a letter or digit of any script never
    eng, sco = "\U0001F3F4\U000E0067\U000E0062\U000E0065\U000E006E\U000E0067\U000E007F", "\U0001F3F4\U000E0067\U000E0062\U000E0073\U000E0063\U000E0074\U000E007F"
    other = ["あ", "中", "ａ", "①", "ありがとう"]
    check("England's and Scotland's flags whole; あ 中 ａ ① never pass (Python)",
          S.clean_emoji(eng) == eng and S.clean_emoji(sco) == sco and S.clean_emoji(eng + "x") == eng
          and all(S.clean_emoji(t) == "" for t in other), [(t, S.clean_emoji(t)) for t in other + [eng]])
    import shutil
    import subprocess
    node = shutil.which("node")
    if node:
        fn = js[js.index("function oneEmoji(s)"):js.index("function filter()")]
        cases = other + [eng, "🎉", "©️", "1️⃣", "👩‍⚕️"]
        out = subprocess.run([node, "-e", "var window = globalThis; " + fn + "; console.log(JSON.stringify("
                              + json.dumps(cases) + ".map(oneEmoji)))"], capture_output=True, text=True, timeout=30)
        got = json.loads(out.stdout or "null") or []
        check("the page's oneEmoji agrees with clean_emoji on each (the twins)",
              got == [S.clean_emoji(c) for c in cases], (got, [S.clean_emoji(c) for c in cases], out.stderr[-200:]))


def test_cheer_pill_and_window_v391():
    """3.9.1 (Sam: "Cheers, clearer: build 1", "get rid of the current cheers
    click to the right of the stats", "make the cheers and doodles modals in
    the design language of our add on"): a crewmate's row has a "🎉 Cheer"
    pill after the name (only while the pointer or a key is on the name:
    "not persistent all the time"), the 🎉 column is gone, and the
    Cheer window is drawn on the Decks screen in the board's look, its Send
    checked again in Python."""
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    day = {labels[0]: {"reviews": 40, "studyTimeMs": 600000, "retention": 90.0, "streak": 3}}
    base = {"days": day, "last_updated": "", "decks": [], "paused": False, "room": None}
    ents = [dict(base, user_id="me", name="Sammy", you=True), dict(base, user_id="dre", name="Dre <b>", you=False)]
    data = {"entries": ents, "labels": labels, "tomorrow": tomorrow, "pending": [], "decks": {}, "my_friends": []}
    page = board.render(data, {"period": "today"}, 0)
    rows = re.findall(r"<tr class=\"[^\"]*\">.*?</tr>", page, re.S)
    mine = next(r for r in rows if "Sammy" in r)
    dres = next(r for r in rows if "Dre" in r)
    nm = re.search(r'<td class="nm">(.*?)</td>', dres, re.S).group(1)
    head = re.search(r"<table[^>]*><tr>(.*?)</tr>", page, re.S).group(1)
    check("the 🎉 column is gone: no cheer cell, no empty head cell for it; a row has as many cells as the head",
          'class="chc"' not in page and "dc-cheer" not in page
          and dres.count("<td") == head.count("<th") + head.count('colspan="2"'), (dres.count("<td"), head.count("<th")))
    check("a crewmate's cheer is a pill after the name (escaped), opening the Cheer window; never on my own row",
          "duecrew:cheerpick:dre" in nm and "&#127881; Cheer" in nm and 'aria-label="Cheer Dre &lt;b&gt;"' in nm
          and nm.index("dc-pl") < nm.index("dc-cpill") and "dc-cpill" not in mine)
    check("the pill shows only while the pointer (or a key) is on the name, never on every row; a long name gives way so it's never cut off",
          "td.nm:hover a.dc-cpill" in page and "td.nm:focus-within a.dc-cpill" in page and "max-width: 56%" in page
          and "tr:hover a.dc-cpill" not in page and "dc-pills" not in page and not hasattr(board, "pills_always")
          and "dc-pills" not in board.render(data, {"period": "today", "cheer_pill_from": labels[6]}, 0))
    app_js = open(os.path.join(REPO, "site", "public", "app.js")).read()
    app_css = open(os.path.join(REPO, "site", "public", "app.css")).read()
    check("the site's twin: the pill after the name, only while the pointer's on the name; no 🎉 column, never on every row",
          '"linkish cpill"' in app_js and 'class: "chc"' not in app_js and "dc-pill-from" not in app_js and "cpills" not in app_js
          and "HEADS.length + 1" in app_js and ".brdt td.nm:hover .cpill, .brdt td.nm:focus-within .cpill" in app_css
          and "tr:hover .cpill" not in app_css and "hover: none" not in app_css and ".chc" not in app_css)
    import shutil
    import subprocess
    node = shutil.which("node")
    if node:
        # the bug hunt: the pill sat inside the line's if/else chain, so a crewmate's " · yesterday" and
        # " · 3 days this week" never showed (only mine did, and mine has no pill)
        body = app_js[app_js.index("  function nameCell(r, period) {"):app_js.index("  /** board._corner", app_js.index("  function nameCell(r, period) {"))]
        prog = ("function h(tag, attrs, ...kids) { const n = { tag, attrs, kids: [] }; n.append = (...k) => n.kids.push(...k);"
                " n.append(...kids.flat().filter((x) => x != null)); return n; }\n"
                "const text = (n) => typeof n === 'string' ? n : (n.kids || []).map(text).join('');\n"
                "const nameCell = new Function('h', 'who', 'ago', 'planTarget', 'cheerMenu', " + json.dumps(body + "\nreturn nameCell;")
                + ")(h, (p) => p.name, () => ['2h'], () => null, () => {});\n"
                "const base = { p: { name: 'Priya', uid: 'u1' }, you: false };\n"
                "console.log(JSON.stringify([nameCell({ ...base, stale: true }, 'today'), nameCell({ ...base, showup: true, daysWk: 3 }, 'today'),"
                " nameCell({ ...base, you: true, stale: true }, 'today')].map(text)));")
        run = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
        check("the site's row (the bug hunt): a crewmate's line still shows, then the pill; mine has the line and no pill",
              run.stdout.strip() == json.dumps(["Priya · yesterday🎉 Cheer", "Priya · 3 days this week🎉 Cheer", "Priya · yesterday"],
                                               separators=(",", ":"), ensure_ascii=False), run.stdout + run.stderr[-1500:])
    # the Cheer window, in the board's look
    js = board.cheer_overlay_js({"uid": "dre", "name": "Dre </script><b>", "emojis": ["🎉", "💪"], "pip": None,
                                 "pen": "red;background:url(x)"})
    view = json.loads(re.search(r"var V = (\{.*?\});\n", js).group(1).replace("<\\/", "</"))
    check("the window: its data as JSON (no '</' to end the script), the name as text, a pen that isn't a colour turned away",
          "</script>" not in js.split("var V = ")[1].split(";\n")[0] and view["name"] == "Dre </script><b>"
          and view["pen"] == board.accent_pair(None)[0] and view["emojis"] == ["🎉", "💪"] and view["pip"] == ""
          and "textContent" in js and "innerHTML = V.pip" in js and "duecrew:cheersend:" in js and "encodeURIComponent" in js)
    check("the window: the board's tokens, its own font, Draw and Sign, the pad's ceilings, Esc and the backdrop close it "
          "(3.9.8: through the shared overlay, board.POP_JS)",
          js.startswith(board.POP_JS) and "window.dcPop.theme()" in js and "var font = T.font;" in js and "'Draw'" in js and "'Sign'" in js
          and "MAXP = 2000" in js and "SIGN = 24" in js and "shade: close" in js and "esc: function ()" in js)
    from due_crew import emoji_drawer as ED
    from due_crew.backend.shapes import DOODLE_INKS, clean_emoji
    every = [e for _, items in ED.GROUPS for e, _ in items]
    from due_crew.backend.shapes import clean_note, clean_squad_name
    from due_crew import share as SH
    newer = ["\U0001FAE8", "\U0001FA77", "\U0001FAE9", "\U0001FAE1\U0001F3FD"]  # shaking face, pink heart (15.0), face with bags (16.0), a skin tone
    check("an emoji newer than this Python's Unicode (Anki on 3.9 has 13.0) still sends, and a note, a squad's name and a share keep it",
          all(clean_emoji(e) == e for e in newer) and clean_note("nice \U0001FAE8!") == "nice \U0001FAE8!"
          and clean_squad_name("Heme \U0001FA77") == "Heme \U0001FA77" and SH.clean_name("Dre \U0001FAE9") == "Dre \U0001FAE9"
          and clean_emoji("a") == "" and clean_emoji("\U0002FFFE") == "" and clean_note("x\U0002FFFE") == "x"
          and clean_note("a\u200bb\x07") == "ab",
          [(e, clean_emoji(e)) for e in newer])
    check("other opens a drawer of emoji, by group, each found by its words; every one can be sent (clean_emoji keeps it whole)",
          view["drawer"] == ED.view() and len(every) == len(set(every)) > 150
          and all(clean_emoji(e) == e for e in every) and all(w.strip() for _, items in ED.GROUPS for _, w in items)
          and "el('button', 'ot', 'other')" in js and "aria-expanded" in js and "function openDrawer()" in js
          and "Find one: heart, coffee, owl" in js and "oneEmoji(find.value.trim())" in js,
          [e for e in every if clean_emoji(e) != e])
    check("Draw and Sign start shut (a cheer is the emoji and the note); a second press shuts one, and only an open one is sent",
          "show('');" in js and "show('draw');" not in js and "show(mode === x[0] ? '' : x[0])" in js
          and "if (mode !== 'draw' || !strokes.length) { return null; }" in js and "mode === 'draw' && strokes.length > 0" in js)
    check("Esc shuts the drawer first, then the window",
          "if (drawer.style.display !== 'none') { shut(); other.focus(); } else { close(); }" in js)
    mine = board.cheer_overlay_js({"uid": "dre", "name": "Dre", "emojis": ["🎉"], "pen": board.accent_pair("teal")[0]})
    mv = json.loads(re.search(r"var V = (\{.*?\});\n", mine).group(1).replace("<\\/", "</"))
    check("the pad has every accent, mine first, then black; a stroke's colour goes as its place in DOODLE_INKS",
          [x[0] for x in mv["inks"]] == [board.accent_pair(n)[0] for n in DOODLE_INKS] and mv["mine"] == DOODLE_INKS.index("teal")
          and "'My colour'" in mine and "'Black'" in mine and "pen = (pen & 1) | (x[0] << 1)" in mine
          and "cx.strokeStyle = inkOf(s.pen)" in mine and f"INK = '{board.DOODLE_INK}'" in mine and "__INK__" not in mine)
    import shutil
    import subprocess
    node = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True) if shutil.which("node") else None
    check("the window's script parses", node is None or node.returncode == 0, node and node.stderr[:300])
    # Send, through the board's own handler, checked again
    import due_crew as dc
    from due_crew import social
    from aqt.deckbrowser import DeckBrowser
    store = world({"sam": "Sammy", "dre": "Dre"}, {"sam": ["dre"], "dre": ["sam"]})
    sam = new_client(store, "sam", "Sammy")
    saved = (social.client, social._bg, dc._state.get("entries"), social.mw.web.eval)
    evals = []
    social.client = lambda: sam
    social._bg = lambda job, done=None: done(job()) if done else job()
    social.mw.web.eval = evals.append
    dc._state["entries"] = [dict(ents[0], user_id="sam"), dict(ents[1], name="Dre", user_id="dre")]
    from urllib.parse import quote
    send = lambda p: dc._on_js(False, as_board("duecrew:cheersend:" + quote(json.dumps(p))), DeckBrowser())
    try:
        dc._on_js(False, as_board("duecrew:cheerpick:dre"), DeckBrowser())
        opened = evals[-1] if evals else ""
        send({"to": "dre", "emoji": "🔥", "note": "go  go", "doodle": {"k": "sign", "t": "you've got this"}})
        got = dict(store.cheers.get(("dre", "sam")) or {})
        store.cheers.clear()
        for bad in ({"to": "sam", "emoji": "🔥"}, {"to": "nia", "emoji": "🔥"}, {"to": "dre", "emoji": "lol"}, ["dre"]):
            send(bad)
        dc._on_js(False, as_board("duecrew:cheersend:%7Bnot json"), DeckBrowser())
        send({"to": "dre", "emoji": "🎉", "doodle": {"k": "draw", "s": [[16, 1, 1]]}, "extra": "<b>"})
        check("cheerpick opens the window on the Decks screen, for that crewmate",
              "dc-cheer" in opened and '"uid": "dre"' in opened)
        check("Send: one cheer with its note and sign; me, a stranger, a word for an emoji or a broken payload send nothing; a broken doodle goes without it",
              got.get("emoji") == "🔥" and got.get("note") == "go go" and got.get("doodle") == {"k": "sign", "t": "you've got this"}
              and list(store.cheers) == [("dre", "sam")] and store.cheers[("dre", "sam")]["doodle"] is None)
        said, tip = [], social.tooltip
        social.tooltip = said.append
        newer = store._cheer

        def older(me, to, body):  # a server from before 3.9.1
            if "doodle" in body:
                raise fakes.Bad(400, "bad_cheer")
            return newer(me, to, body)
        try:
            send({"to": "dre", "emoji": "🎉", "doodle": {"k": "sign", "t": "go"}})
            store._cheer = older
            send({"to": "dre", "emoji": "🎉", "doodle": {"k": "sign", "t": "go"}})
        finally:
            social.tooltip, store._cheer = tip, newer
        check("the toast says a sign went only when it did (the bug hunt: an older server sends the cheer without it)",
              said == ["Sent 🎉 and a sign to Dre.", "Sent 🎉 to Dre."], said)
    finally:
        social.client, social._bg, dc._state["entries"], social.mw.web.eval = saved


def test_two_buttons_v391():
    """3.9.1, two buttons (Sam's picks from the mock): Again and Good alone,
    every deck, 2, 3 and 4 count as Good, FSRS off allowed with a note; a
    switch in Settings › Board › Reviewing, and Try two buttons on Insights'
    Hard habit line, with its Undo there. Two of Anki's hooks; nothing sent."""
    from due_crew import two_buttons as TB, account, rooms, settings_model as SM, team_flow as TF
    from due_crew.app import _state
    four = ((1, "Again"), (2, "Hard"), (3, "Good"), (4, "Easy"))
    check("the bar: Again and Good with it on, in Anki's own words; off, or not Anki's four: as it came",
          TB.buttons(four, True) == ((1, "Again"), (3, "Good")) and TB.buttons(four, False) == four
          and TB.buttons(((1, "Again"), (2, "Good")), True) == ((1, "Again"), (2, "Good"))
          and TB.buttons((), True) == ())
    check("the keys: 2, 3 and 4 are Good; 1 stays Again; off, every ease as it was",
          [TB.ease((True, e), True) for e in (1, 2, 3, 4)] == [(True, 1), (True, 3), (True, 3), (True, 3)]
          and [TB.ease((True, e), False) for e in (1, 2, 3, 4)] == [(True, 1), (True, 2), (True, 3), (True, 4)])
    # the hooks, chained as Anki chains filters (the room's break first, as registered)
    conf = {"two_buttons": True}
    import due_crew.app as appmod
    saved_cfg = appmod.cfg
    appmod.cfg = lambda: conf
    try:
        def answer(e):
            out = (True, e)
            for f in (rooms.will_answer, TB.will_answer):
                out = f(out, None, None)
            return out
        _state["room_break"] = False
        on = [answer(e) for e in (1, 2, 3, 4)]
        _state["room_break"] = True
        held = answer(4)
        _state["room_break"] = False
        conf["two_buttons"] = False
        off = [answer(e) for e in (1, 2, 3, 4)]
        bar_off = TB.will_init_buttons(four, None, None)
        conf["two_buttons"] = True
        bar_on = TB.will_init_buttons(four, None, None)
    finally:
        appmod.cfg = saved_cfg
        _state["room_break"] = False
    check("the tips, called as Anki calls them: on, 2/3/4 land as Good and 1 as Again; off, nothing changes",
          on == [(True, 1), (True, 3), (True, 3), (True, 3)] and off == [(True, 1), (True, 2), (True, 3), (True, 4)]
          and bar_on == ((1, "Again"), (3, "Good")) and bar_off == four, (on, off))
    check("a room's break still holds the answer, whatever two buttons does with it", held == (False, 3), held)
    check("it's registered on both tips", "two_buttons.will_answer" in srcs.glue_src()
          and "reviewer_will_init_answer_buttons.append(two_buttons.will_init_buttons)" in srcs.glue_src())
    # the setting: a person's, so an account key; a switch on Settings; off by default; Reset board leaves it
    check("the setting: an account key, a bool, off unless set; Settings' switch sets it; Reset board leaves it",
          "two_buttons" in account.ACCOUNT_KEYS and account.clean({"two_buttons": True}) == {"two_buttons": True}
          and "two_buttons" not in account.clean({"two_buttons": "yes"}) and account.pick({"two_buttons": True})["two_buttons"] is True
          and SM.change(["set", "two_buttons", "1"], {}) == {"two_buttons": True}
          and SM.change(["set", "two_buttons", "0"], {}) == {"two_buttons": False}
          and "two_buttons" not in SM.BOARD_DEFAULTS and not TB.on({}))
    view = {"tab": "study", "signed_in": True}
    page = board.settings_html(dict(view, fsrs=True), {"two_buttons": True})
    page_off = board.settings_html(dict(view, fsrs=False), {})
    check("Settings › Study › Reviewing: Two buttons, on, with what it does and that phones keep four; FSRS off: its note",
          '<div class="st-h">Reviewing</div>' in page and "Two buttons" in page and "duecrew:set:two_buttons:0" in page
          and "2, 3 and 4 count as Good. Phones keep four." in page and "Works best with FSRS on." not in page
          and "duecrew:set:two_buttons:1" in page_off and "Works best with FSRS on." in page_off
          and "Works best with FSRS on." not in board.settings_html(view, {}))
    ix = board.settings_index(view, {})
    found = [x for x in ix if x["f"] == "set:two_buttons:"]
    check("Find a setting: hard, easy or buttons finds it", found and all(w in found[0]["k"] for w in ("hard", "easy", "buttons")), found)
    # Insights' Hard habit line
    hh = board._insights_html(10, {"hard": {"pct": 22, "n": 640}, "two": ""})
    tried = board._insights_html(10, {"hard": {"pct": 22, "n": 640}, "two": "tried"})
    check("the Hard habit line offers Try two buttons beside Not now; tried: it's on, with Undo; on: there's no Hard to press",
          "instwo" not in hh and "Try two buttons" not in hh and "You press Hard" in hh
          and "instwono" not in tried
          and "You press Hard" not in board._insights_html(10, {"hard": {"pct": 22, "n": 640}, "two": "on"}))
    # the clicks, as the board sends them
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    mine = {}
    saved = (TF.cfg, TF.save_cfg, appmod.swap)
    swaps = []
    TF.cfg = lambda: mine
    TF.save_cfg = lambda c, **k: mine.update(c)
    appmod.swap = lambda c, **k: swaps.append(1)
    try:
        dc._on_js(False, as_board("duecrew:instwo:10"), DeckBrowser())
        tried_on = (mine.get("two_buttons"), _state.get("two_tried"))
        dc._on_js(False, as_board("duecrew:instwono:10"), DeckBrowser())
        undone = (mine.get("two_buttons"), _state.get("two_tried"))
    finally:
        TF.cfg, TF.save_cfg, appmod.swap = saved
        _state["two_tried"] = False
    check("Try two buttons turns it on (saved as Settings saves it) and says so; Undo turns it off, back to the line",
          tried_on == (True, True) and undone == (False, False) and len(swaps) == 2, (tried_on, undone))


def test_efficiency_review_screen_v391():
    """3.9.1, the efficiency run (Sam: "I don't want our add on to impact anki
    performance"): the review screen's widgets go to a page once, and again
    only when they change or the page is new; taking one down is a few
    lines; the knows chip is taken down only when one's up; an answer draws
    only the Pips its chip could name; Pip's drawing and the config are kept."""
    from due_crew import rooms as R, room_model as rm, cards as K, sev, app as A
    from due_crew.app import _state
    sent = []

    class Web:
        def __init__(self, n):
            self.n = n

        def eval(self, js):
            sent.append((self.n, js))

        def evalWithCallback(self, js, cb):
            sent.append((self.n, js))
            cb(True)
    top, main, bottom = Web("top"), Web("main"), Web("bottom")
    conf, room = {}, {"v": None}
    now = datetime.datetime.now(datetime.timezone.utc)
    saved = (R._webs, R.client, R.cfg, R.my_room, R._where, dict(_state))
    try:
        R._webs = lambda: (top, main, bottom)
        R.client = lambda: types.SimpleNamespace(signed_in=True, session={})
        R.cfg = lambda: dict(conf)
        R.my_room = lambda: room["v"]
        R._where = lambda: "chip"
        _state["entries"] = [{"user_id": "me", "name": "Sam", "you": True}]
        R._DRAWN.clear()
        R.refresh_widgets()
        first = dict(sent)
        sent.clear()
        R.refresh_widgets()
        R.on_question(None)
        check("efficiency: each page's widgets go as one piece; the next card, the same widgets send nothing",
              sorted(first) == ["bottom", "main", "top"] and sent == [], [n for n, _ in sent])
        check("efficiency: the bottom bar alone gets what keeps Anki's buttons in its middle; taking a widget down is a few lines",
              rm.BAR_BALANCE in first["bottom"] and rm.BAR_BALANCE not in first["top"] + first["main"]
              and len(first["main"]) < 1000 and "var D =" not in first["main"] and "var D =" in first["top"])
        A.on_set_content(None, None)
        R.refresh_widgets()
        check("efficiency: a new page anywhere (webview_will_set_content), and they go again",
              sorted(n for n, _ in sent) == ["bottom", "main", "top"])
        sent.clear()
        conf["room_chip_side"] = "left"
        R.refresh_widgets()
        check("efficiency: a change goes only to the page it changes", [n for n, _ in sent] == ["top"])
        sent.clear()
        R._eval(main, "1;")
        sent.clear()
        R.refresh_widgets()
        check("efficiency: anything else drawn on a page, and that page gets them again", [n for n, _ in sent] == ["main"])
        sent.clear()
        R.on_theme()
        check("efficiency: night mode on or off, all drawn again (they pick their colours as they're drawn)", len(sent) == 3)
        room["v"] = rm.make_room("me", now - datetime.timedelta(minutes=3))
        _state["entries"][0]["room"] = room["v"]
        R.refresh_widgets()
        sent.clear()
        R.on_question(None)
        check("efficiency: and in a room, the next card sends nothing either", sent == [], [n for n, _ in sent])
    finally:
        R._webs, R.client, R.cfg, R.my_room, R._where = saved[:5]
        _state.clear()
        _state.update(saved[5])
        R._DRAWN.clear()
    runtime_ids = re.search(r"var ids = (\[[^\]]*\])", rm._RUNTIME).group(1)
    check("efficiency: the remover takes down the runtime's own widgets and stops their clocks, as its drop() does",
          runtime_ids in rm.REMOVE_JS and "clearInterval(window['dcRoomTick_' + k])" in rm.REMOVE_JS
          and "dcRoomTick_' + k]) { clearInterval(window['dcRoomTick_' + k])" in rm._RUNTIME
          and rm.widget_js("gutter", None).endswith('})("gutter");'))

    # the knows chip
    saved = (K._bottom, K._review_web, K.client)
    view = {"kind": "knows", "text": "Dre knows this", "accent": ["#0a0", "#7c7"], "pip": {"svg": "<svg/>", "a": ["#00f", "#99f"]},
            "sevcss": sev.CSS, "peek": {"head": "I know this one", "act": "Ask Dre", "pips": [{"svg": "<svg/>", "a": ["#00f", "#99f"]}]}}
    try:
        K._bottom, K._review_web = (lambda: bottom), (lambda: main)
        K._UP.update(bar=False, page=False)
        K._SHEET.clear()
        sent.clear()
        K.on_question(None)
        K._show(None)
        check("efficiency: a card with no chip sends nothing to the review screen, question or answer", sent == [])
        K._show(dict(view))
        once = list(sent)
        sent.clear()
        K.on_question(None)
        down = list(sent)
        sent.clear()
        K._show(dict(view))
        again = list(sent)
        sent.clear()
        A.on_set_content(None, None)
        K._show(dict(view))
        fresh = list(sent)
        sheet = json.dumps(sev.CSS)[1:200]
        check("efficiency: a chip that's up is taken down with a few lines (it still ducks away)",
              len(down) == 1 and down[0] == ("main", K.FLOAT_OFF) and "dcKnowsOff(true)" in K.FLOAT_OFF)
        check("efficiency: Pip's motion sheet goes to a page once, and again on a new page",
              sheet in once[0][1] and sheet not in again[0][1] and sheet in fresh[0][1], [len(x[0][1]) for x in (once, again, fresh)])
    finally:
        K._bottom, K._review_web, K.client = saved
        K._UP.update(bar=False, page=False)
    saved = dict(_state)
    try:
        _state["entries"] = [{"user_id": u, "name": u.title(), "accent": "blue"} for u in ("dre", "mo", "jo", "al")]
        names = K.names_by_uid()
        who = K.chip_people({"knows": ["dre", "mo", "jo", "al"], "tips": [{"from": "eve", "text": "x"}]}, [], names, [("mo", 0, "q")])
        check("efficiency: an answer draws only who its chip could name: who asked, who tipped, the first three who know it",
              who == {"dre", "mo", "jo", "eve"} and K.chip_people(None, [], names) == set()
              and set(K.pips_by_uid({}, only={"dre", "zed"})) == {"dre"} and K.pips_by_uid({}, only=set()) == {}
              and set(K.pips_by_uid({})) == {"dre", "mo", "jo", "al"})
    finally:
        _state.clear()
        _state.update(saved)
    looks = [None, [], ["headphones"], ("headphones", "scarf"), {"cap": 1}, "cap", [{"x": 1}]]
    check("efficiency: Pip's drawing is kept, the same as drawn afresh, a look from anywhere included",
          all(sev.svg(p, look=lk, label="L") == sev._svg(p, None, None, False, "L", None, None, lk, None)
              for p in ("idle", "peek", "nap") for lk in looks)
          and sev.svg("idle", look=["headphones"]) is sev.svg("idle", look=("headphones",)))
    am = A.mw.addonManager
    real = (am.getConfig, am.writeConfig)
    disk, reads = {"c": {"accent": "blue"}}, []
    try:
        am.getConfig = lambda n: (reads.append(1), dict(disk["c"]))[1]
        am.writeConfig = lambda n, c: disk.update(c=dict(c))
        A._CFG["text"] = None
        c1 = A.cfg()
        c1["accent"] = "rose"
        c2 = A.cfg()
        A.save_cfg(dict(c2, theme="dark"))
        c3 = A.cfg()
        check("efficiency: the config is read once, each caller its own copy, and read again after a save",
              len(reads) == 2 and c2 == {"accent": "blue"} and c3 == {"accent": "blue", "theme": "dark"})
    finally:
        am.getConfig, am.writeConfig = real
        A._CFG["text"] = None


def test_efficiency_plans_v391():
    """3.9.1, the efficiency run, plans and the deck tree: buried_today finds
    the notes started before today once a session_view, not once a date; a
    refresh_progress asked again with nothing it reads changed gives the
    last answer without reading the deck; Anki's deck tree is read once
    while it can't have changed, and Due, a plan's due and the bingo share it.
    Every answer the same as a fresh read."""
    import time as _t
    from due_crew import plans as P, plan_flow as F, due_flow as DF, app as A
    from due_crew.app import _state

    def old_buried(self, cids, first_seen):  # 3.9.0's, a pass over the deck each time
        before = {self.nid_of[c] for c, (_q, t) in self.cards.items() if t != 0 and first_seen.get(c) != 0}
        started, nid_of = self.started(), self.nid_of
        return sum(1 for c in cids if self.cards[c][1] == 0 and self.cards[c][0] in (-2, -3)
                   and nid_of.get(c) in started and nid_of.get(c) not in before)

    class Passes(dict):
        n = 0

        def items(self):
            Passes.n += 1
            return dict.items(self)
    col = _plan_col()
    conn = col.db.conn
    conn.execute("UPDATE cards SET queue = 2, type = 2 WHERE id = 5")
    conn.execute("UPDATE cards SET queue = -3, type = 0 WHERE id = 6")
    for o in (2, 3, 4):
        fakes.add_card(conn, 60 + o, did=10, queue=-3, nid=50, ord_=o)
    fakes.add_card(conn, 71, did=10, ctype=2, queue=2, nid=70, ord_=0)  # a second cloze, c1 seen
    fakes.add_card(conn, 72, did=10, queue=-2, nid=70, ord_=1)
    refs = [["guid000050", o] for o in range(5)] + [["guid000070", 0], ["guid000070", 1]]
    plan = {"id": "p", "sched": {"days": [1] * 7, "minutes": 60}, "doc": {"deck": "Step 1", "units": [
        {"id": f"u{i}", "name": f"Date {i}", "opens": _day(i - 4), "cards": refs[i:i + 3]} for i in range(5)]}}
    same, passes = [], []
    for seen in ({}, {5: 0}, {5: 1}, {5: 0, 71: 0}, {71: 2}):
        idx = P.DeckIndex(col, 10)
        idx.cards = Passes(idx.cards)
        idx.started()
        Passes.n = 0
        v = F.session_view(plan, {"deck_id": 10}, idx, seen, _day(0))
        passes.append(Passes.n)
        keep = P.DeckIndex.buried_today
        P.DeckIndex.buried_today = old_buried
        try:
            ref = F.session_view(plan, {"deck_id": 10}, P.DeckIndex(col, 10), seen, _day(0))
        finally:
            P.DeckIndex.buried_today = keep
        same.append(v == ref)
    check("buried today: a session_view's answer as before, five dates and the notes started before today found once",
          all(same) and passes == [1] * 5, (same, passes))
    idx = P.DeckIndex(col, 10)
    check("buried today: asked with another first_seen, it's found again",
          idx.buried_today({62, 63}, {5: 0}) == 2 and idx.buried_today({62, 63}, {5: 1}) == 0
          and idx.buried_today({62, 63}, {}) == 0 and idx.buried_today({72}, {71: 0}) == 1)

    # refresh_progress: what it reads, in one key
    store, pid, code, maya = _v381_world()
    col = _plan_col()
    col.mod = 1  # Anki's col.mod: every answer and op moves it (the fakes don't, so the test does)
    fakes.add_card(col.db.conn, 30, did=20, ctype=1, queue=1, due=0)  # a learning card, elsewhere: when it's back is set below
    builds, trees = [], []
    real_init, real_tree = P.DeckIndex.__init__, col.sched.deck_due_tree

    def counted(self, c, did):
        builds.append(did)
        real_init(self, c, did)
    clock = [float(col.sched.day_cutoff) - 6 * 3600]
    ahead = 1200  # Anki's learn-ahead (collapseTime) when the collection doesn't say
    saved = (DF.time, list(_state.get("labels") or []), _state.get("due_reviews"), _state.get("back_timer"))
    P.DeckIndex.__init__ = counted
    col.sched.deck_due_tree = lambda: trees.append(1) or real_tree()
    DF.time = types.SimpleNamespace(time=lambda: clock[0], localtime=_t.localtime)
    snap = lambda: {k: json.dumps(_state.get(k), sort_keys=True) for k in F._WRITES}  # noqa: E731

    def fresh():
        """The same refresh read again with nothing kept: what it must equal."""
        got, key = snap(), F._last["key"]
        F._last.update(key=None, got=None)
        DF._TREE.update(key=None)
        n, t = len(builds), len(trees)
        F.refresh_progress()
        del builds[n:], trees[t:]
        return got == snap() and F._last["key"] == key
    try:
        F._last.update(key=None, got=None)
        DF._TREE.update(key=None)
        with _PlanGlue({"A": maya}, {"A": col}) as g:
            got, _ = maya.follow_plan(code)
            F.on_followed(got, 10, None, "open")
            col.mod += 1  # what the open did
            col.db.conn.execute("UPDATE cards SET due = ? WHERE id = 30", (int(clock[0]) + ahead + 60,))
            col.sched.due = {10: (4, 0)}
            del builds[:], trees[:]
            first = F.refresh_progress()
            sess = dict(_state["plan_session"][pid])
            F.refresh_progress()
            n = len(builds)
            check("memo: asked again with nothing changed, the last answer: the deck read once, the deck tree once",
                  n == 1 and len(trees) == 1 and F.refresh_progress() == first and sess["due"] == 4 and fresh(),
                  (builds, len(trees), sess.get("due")))
            col.sched.unsuspend_cards([4])  # Extras, a date that opens in three days
            col.mod += 1
            F.refresh_progress()
            check("memo: an unsuspend (col.mod moved) reads the deck again, and what it opened counts",
                  len(builds) == n + 1 and _state["plan_progress"][pid]["ex"][0] == 1 and first[pid]["ex"][0] == 0 and fresh(),
                  (builds, _state["plan_progress"][pid]))
            col.sched.due = {10: (6, 0)}  # a learning card come inside the learn-ahead, in Anki's count: no change made
            F.refresh_progress()
            check("memo: Anki's due count holds till a learning card can come back", len(builds) == n + 1
                  and _state["plan_session"][pid]["due"] == 4)
            clock[0] += 61
            F.refresh_progress()
            check("memo: once one can, the deck tree is read again, and a new due is a new answer",
                  len(builds) == n + 2 and len(trees) == 3 and _state["plan_session"][pid]["due"] == 6 and fresh(),
                  (builds, len(trees), _state["plan_session"][pid].get("due")))
            n = len(builds)
            g.today["d"] = _day(1)
            F.refresh_progress()
            g.today["d"] = _day(0)
            F.refresh_progress()
            _state["labels"] = [_day(0), _day(-1)]
            F.refresh_progress()
            F._pcfg()["plans"][pid]["missed"] = {"mode": "spread", "day": _day(0)}  # the plan state, not yet saved
            F.refresh_progress()
            maya.session["plans"][0]["paused"] = True  # the plans as the session has them
            F.refresh_progress()
            check("memo: a paused plan has no session, at once", pid not in _state["plan_session"])
            maya.session["plans"][0]["paused"] = False
            A.generation += 1  # a profile or sign-in changed
            F.refresh_progress()
            check("memo: the day, Due's day, the plan state, the session's plans and a new profile each read again",
                  len(builds) == n + 6 and fresh(), builds[n:])
            n = len(builds)
            maya.session["plans"][0]["doc"]["units"][1]["search"] = ["is:due"]
            F.refresh_progress()
            F.refresh_progress()
            check("memo: a search about my own reviews is read again at every refresh, as before",
                  len(builds) == n + 2 and F._last["key"] is None, builds[n:])
            del maya.session["plans"][0]["doc"]["units"][1]["search"]
            F.refresh_progress()
            F.mw.col.mod = None  # an Anki that can't say: every refresh reads, as before
            F.refresh_progress()
            F.refresh_progress()
            check("memo: without col.mod nothing is kept", len(builds) == n + 5 and F._last["key"] is None)
            col.mod = 50

            # the deck tree: Due's reviews, a plan's due and the bingo's week, one read
            DF._TREE.update(key=None)
            del trees[:]
            _state["due_reviews"] = None
            r1 = DF._reviews()
            due = F._due_in(col, 10)
            DF.after_refresh()  # a refresh drops Due's count, not the tree
            r2 = DF._reviews()
            check("tree: Due's count twice and a plan's due, one read of Anki's deck tree, the same answers",
                  len(trees) == 1 and r1 == r2 and r1["due"] == 6 and due == 6, (len(trees), r1, due))
            DF._TREE.update(key=None)
            _state["due_reviews"] = None
            check("tree: the same as read fresh", DF._reviews() == r1 and len(trees) == 2)
            t0 = DF.deck_tree(col)
            col.mod += 1  # an answer
            t1 = DF.deck_tree(col)
            clock[0] = float(col.sched.day_cutoff) + 1  # the day turned
            t2 = DF.deck_tree(col)
            check("tree: read again after an answer and when the day turns", len(trees) == 4 and t0 is not t1 and t1 is not t2)
            clock[0] = float(col.sched.day_cutoff) - 6 * 3600
            col.db.conn.execute("UPDATE cards SET due = ? WHERE id = 30", (int(clock[0]) + ahead + 30,))
            col.mod += 1
            DF.deck_tree(col)
            clock[0] += 29
            DF.deck_tree(col)
            check("tree: kept till a learning card comes inside Anki's learn-ahead", len(trees) == 5)
            clock[0] += 2
            DF.deck_tree(col)
            clock[0] -= 10  # the clock put back: read again
            DF.deck_tree(col)
            check("tree: then read again; a clock put back reads again too", len(trees) == 7)
            col.conf["collapseTime"] = 0  # no learn-ahead: the card counts only once it's due
            col.mod += 1
            DF.deck_tree(col)
            clock[0] += 100
            DF.deck_tree(col)
            check("tree: Anki's own learn-ahead, from the collection", len(trees) == 8, len(trees))
    finally:
        P.DeckIndex.__init__ = real_init
        DF.time, _state["labels"], _state["due_reviews"], _state["back_timer"] = saved
        F._last.update(key=None, got=None)
        DF._TREE.update(key=None)


def test_efficiency_idle_v391():
    """3.9.1, the efficiency run, idle: a loop that never ends keeps Anki
    drawing 60 frames a second (about two-thirds of it on Anki's own
    thread). The ones nobody sees end: the bats' wings after their flight,
    Wrapped's frame loop; the room clocks tick only as often as they show."""
    from due_crew import room_model as rm
    import re as _re
    check("idle: the bats' wings flap for the flight and stop (no loop of ours that runs forever on Halloween's line)",
          "infinite" not in board.HW_CSS and "calc(var(--d) - var(--ago, 0s)) 20 alternate" in board.HW_CSS)
    rt = rm._RUNTIME
    check("idle: a room's widgets tick as often as they show (the break's mm:ss and the question each second, "
          "else at the minute's turn or the phase's end, ten seconds at most), and balance the bar only when their words change",
          "setInterval(tick" not in rt and "Math.min(10000, p.left > 0 ? p.left % 60000 + 50 : 10000)" in rt
          and "KIND === 'break' || KIND === 'ask') { return 1000; }" in rt and "root.textContent !== said" in rt)
    check("idle: the bar's watcher leaves the room's own changes to its tick, as the chip's",
          "room && room.contains(x.target)" in rm.BAR_BALANCE and "n === chip || n === room" in rm.BAR_BALANCE)
    from due_crew import sev as _sev
    forever = [x for x in _re.findall(r"[^{}\n]*\{[^{}]*\binfinite\b[^{}]*\}", _sev.CSS) if "--sv-on: var(--sv-hover, infinite)" not in x]
    check("Pip at rest (Sam's pick A): every loop of Pip's plays about twelve seconds, then rests; only the break's "
          "breathing and stretch go on (the exercise); pointing at Pip plays it on",
          forever and all("m-breathe" in x or "m-stretch" in x for x in forever)
          and ".sv:hover, .sv-slot:hover .sv { --sv-on: var(--sv-hover, infinite); }" in _sev.CSS and ".dc-rest { --sv-hover: 1; }" in _sev.CSS
          and _sev.CSS.count("var(--sv-on, ") >= 40, forever)
    src = fakes.board_source()
    check("Pip at rest (Sam's pick C): the fridge's Pips are still until pointed at; a plan card's and a bingo square's move while hovered; a crew row's never (3.9.10, Sam: only the Cheer pill shows)",
          "#dc-fridge .fz:not(:hover) .sv, #dc-fridge .fz:not(:hover) .sv * { animation: none !important; }" in board.FRIDGE_CSS
          and "#dc-fridge .fz:hover .sv { --sv-on: var(--sv-hover, infinite); }" in board.FRIDGE_CSS
          and all(f"#due-crew {k}:hover .dc-rsev .sv {{ --sv-on: var(--sv-hover, infinite); }}" in src for k in (".pcrew", ".bg-sq"))
          and "#due-crew tr .dc-rsev .sv, #due-crew tr .dc-rsev .sv * { animation: none !important; }" in src and "tr:hover .dc-rsev" not in src
          and "#due-crew .face:hover .dc-rsev .sv {{ --sv-on: var(--sv-hover, infinite); }}" in src)
    app_css = open(os.path.join(REPO, "site", "public", "app.css")).read()
    check("Pip at rest (the bug hunt): the break screen's Pip goes on all break, whichever of its stretch moves it does",
          "root.style.setProperty('--sv-on', 'infinite');" in rm._RUNTIME
          and rm._RUNTIME.index("root.style.setProperty('--sv-on', 'infinite');") > rm._RUNTIME.index("var bs = FIF && D.sev"))
    check("the studying-now dot (Sam's pick D): a few pulses, then lit, in Anki and on the site",
          "dcbreathe 2.4s ease-in-out 7 alternate" in fakes.board_source()
          and ".chip.live::before { animation: dcbreathe 2.4s ease-in-out 7 alternate; }" in app_css
          and "dcbreathe 2.4s ease-in-out infinite" not in app_css)
    loops = _re.findall(r"[^{}]*\{[^{}]*\binfinite\b[^{}]*\}", board.HW_CSS + board.FRIDGE_CSS if hasattr(board, "FRIDGE_CSS") else board.HW_CSS)
    check("idle: nothing new of ours loops forever on Halloween's line", not [x for x in loops if "hw" in x])
def test_efficiency_decks_v391():
    """3.9.1, the efficiency run, the Decks screen: the board's scripts go to
    a page once, and a swap sends only what they do after a draw; the
    fridge is checked and drawn once a change, the same as drawn afresh,
    and its script reads the page's layout once a placing; wrap.json is
    written only when it says something new, so a refresh that changes
    nothing writes nothing."""
    import shutil
    import subprocess
    import due_crew as dc
    from due_crew import app as A, closet_flow as CF, due_flow, fridge as FR, rooms, together
    from due_crew.app import _state
    mw = dc_mw()
    sent = []
    mine = '<div id="due-crew">board</div>'
    saved = (getattr(mw, "web", None), dc._board_html, dc._arrive_js, dc._play_cheers, together.show_luck_card,
             rooms.refresh_widgets, dict(_state))
    try:
        mw.web = types.SimpleNamespace(eval=sent.append)
        dc._board_html = lambda c: mine
        dc._arrive_js = lambda: ""
        dc._play_cheers = lambda: None
        together.show_luck_card = lambda: None
        rooms.refresh_widgets = lambda: None
        _state.update(entries=[], wrapped_open=False, plans_midday=False, plans_morning=None)
        A.on_set_content(None, None)
        dc._on_did_render(None)
        dc._swap({})
        dc._swap({})
        A.on_set_content(None, None)  # a page anew (stdHtml, here or in any of Anki's webviews)
        dc._swap({})
        dc._on_did_render(None)  # the board drawn: the page is new to it, whatever the count says
        drawn, swap, swap2, anew, again = sent
    finally:
        mw.web, dc._board_html, dc._arrive_js, dc._play_cheers, together.show_luck_card, rooms.refresh_widgets = saved[:6]
        _state.clear()
        _state.update(saved[6])
    scripts = (board.DUE_JS, board.MOTION_JS, board.FIND_JS, board.FRIDGE_JS)
    calls = swap[len(board.swap_js(mine)):]
    check("efficiency: a page drawn anew gets the board's scripts (Due's add line, motion.js, Find, the fridge's), as before",
          drawn == "window.dcBK=%s;" % json.dumps(KK) + board.keep_me_in_view_js() + board.fridge_js()
          and all(s in drawn for s in scripts)
          and anew == board.swap_js(mine) + board.keep_me_in_view_js() + board.fridge_js() and again == drawn)
    check("efficiency: a swap on that page sends only what they do after a draw, in their order, a few hundred bytes (it was 77 KB)",
          swap == swap2 and swap.startswith(board.swap_js(mine)) and not any(s in swap for s in scripts)
          and calls == board.keep_me_in_view_js(scripts=False) + board.fridge_js(scripts=False)
          and "'#due-crew .dc-scroll'" in calls and board.FIND_AFTER in calls and calls.endswith(board.MOTION_DRAWN
          + "\nif (window.dcFridge) { window.dcFridge(); }\n") and len(calls.encode()) < 1024, len(calls))
    check("efficiency: each script loads once a page (each checks it isn't there yet), so sent again it changes nothing",
          "if (window.dcDue) { return; }" in board.DUE_JS and "if (window.dcMotion) return;" in board.MOTION_JS
          and "if (!window.dcFind) {" in board.FIND_JS and "window.dcFridge = window.dcFridge || function () {" in board.FRIDGE_JS)
    # the scripts, then a swap's calls, in node on a page that has no board: each call reaches the script it calls,
    # nothing loads twice, and the calls alone on a page without them (another page) do nothing
    probe = r"""
    var none = function () { return null; };
    globalThis.window = globalThis;
    globalThis.document = {getElementById: none, querySelector: none, querySelectorAll: function () { return []; },
                           addEventListener: function () {}, body: {className: ''}};
    globalThis.sessionStorage = {getItem: none, setItem: function () {}};
    var out = {};
    try { (0, eval)(CALLS); out.bare = 'ok'; } catch (e) { out.bare = String(e); }
    (0, eval)(DRAWN);
    var due = window.dcDue, motion = window.dcMotion, find = window.dcFind, n = {after: 0, drawn: 0, fridge: 0};
    var a = find.after, d = motion.drawn, f = window.dcFridge;
    find.after = function () { n.after++; return a.apply(this, arguments); };
    motion.drawn = function () { n.drawn++; return d.apply(this, arguments); };
    window.dcFridge = function () { n.fridge++; return f.apply(this, arguments); };
    (0, eval)(CALLS);
    out.n = n;
    out.same = window.dcDue === due && window.dcMotion === motion && window.dcFind === find;
    console.log(JSON.stringify(out));
    """.replace("CALLS", json.dumps(calls)).replace("DRAWN", json.dumps(drawn))
    node = subprocess.run(["node", "-"], input=probe, capture_output=True, text=True) if shutil.which("node") else None
    got = json.loads(node.stdout) if node and node.returncode == 0 else None
    check("efficiency: in a page, a swap's calls reach the scripts the draw loaded, once each; on a page without them, nothing",
          node is None or got == {"bare": "ok", "n": {"after": 1, "drawn": 1, "fridge": 1}, "same": True},
          (got, node and node.stderr[:300]))
    place = board.FRIDGE_JS[board.FRIDGE_JS.index("function place()"):board.FRIDGE_JS.index("el.addEventListener('pointerdown'")]
    check("efficiency: the fridge's script tilts every doodle, then reads every height at once (a read after each write "
          "laid the page out again, twice a doodle), and places them by what it read",
          place.count("offsetHeight") == 1 and place.index("setProperty('--fr'") < place.index("offsetHeight")
          < place.index("style.left") and place.count("var h = hs[i]") == 2)

    # the fridge, checked and drawn once a change
    wrap = _patched_due_crew()
    raw = [{"from": u, "name": u.title(), "at": f"2026-10-0{i + 1}T09:00:00Z", "a": "blue", "n": f"day {i}",
            "d": {"k": "draw", "s": [[i * 3, 10 * i, 20, 30, 40 + i, 50, 60], [i * 3 + 1, 5, 5]] * 40}}
           for i, u in enumerate(("dre", "mo", "jo"))]
    raw.append({"from": "dre", "name": "Dre", "at": "2026-10-05T09:00:00Z", "a": "rose", "n": "", "d": {"k": "sign", "t": "go!"},
                "p": ["l", -150, 320]})
    people = {"dre": {"user_id": "dre", "look": ["cap"], "accent": "purple"}, "mo": {"user_id": "mo"}, "me": {"you": True}}
    afresh = lambda items, ppl, c: board._fridge_notes(FR._clean(items), ppl, c)  # noqa: E731  nothing kept
    checked = []
    real_check = FR.clean_doodle
    try:
        FR.clean_doodle = board.clean_doodle = lambda d: (checked.append(1), real_check(d))[1]
        FR._LAST.clear()
        board._FRIDGE_DRAWN.update(key=None, html="")
        wrap._wrap_data()["fridge"] = json.loads(json.dumps(raw))
        draws = [board.fridge_html(CF.fridge(), people, {"sev": True}) for _ in range(3)]
        once = len(checked)
        mine1 = CF.fridge()
        mine1[0]["name"] = "changed"
        mine1[0]["p"] = ["r", 1, 1]
        kept = CF.fridge()
        CF.move_fridge(FR.key(raw[0]), "r", 40, 120)
        checked.clear()
        moved = board.fridge_html(CF.fridge(), people, {"sev": True})
        n_moved = len(checked)
        checked.clear()
        dressed = board.fridge_html(CF.fridge(), dict(people, mo={"user_id": "mo", "look": ["dino"]}), {"sev": True})
        plain = board.fridge_html(CF.fridge(), people, {"sev": False})
        n_looks = len(checked)
        want = [afresh(raw, people, {"sev": True}), afresh(wrap._wrap_data()["fridge"], people, {"sev": True}),
                afresh(wrap._wrap_data()["fridge"], dict(people, mo={"user_id": "mo", "look": ["dino"]}), {"sev": True}),
                afresh(wrap._wrap_data()["fridge"], people, {"sev": False})]
    finally:
        FR.clean_doodle = board.clean_doodle = real_check
    check("efficiency: a fridge is checked once a change, each drawing once, however often the board draws (it was three times a draw)",
          once == len(raw) and n_moved == len(raw) and n_looks == 0, (once, n_moved, n_looks))
    check("efficiency: what's drawn from what's kept is what a draw afresh draws: as it was, moved, a look changed, Pip off",
          draws[0] == draws[1] == draws[2] == want[0] and moved == want[1] and dressed == want[2] and plain == want[3]
          and moved != want[0] and 'data-s="r" data-x="40" data-y="120"' in moved and dressed != moved and plain != moved
          and draws[0].count('class="fz"') == len(raw), [len(x) for x in want])
    check("efficiency: each caller gets a fridge of its own (a change to one is never kept)",
          kept[0]["name"] == "Dre" and "p" not in kept[0] and kept == FR.clean(raw))
    check("efficiency: a fridge's fingerprint is its contents: the same for a copy, never for anything that differs",
          FR.fingerprint(raw) == FR.fingerprint(json.loads(json.dumps(raw))) and FR.fingerprint([1]) != FR.fingerprint([True])
          and FR.fingerprint([1]) != FR.fingerprint([1.0]) and FR.fingerprint({"a": "1"}) != FR.fingerprint({"a": 1})
          and FR.fingerprint([object()]) is None)
    check("efficiency: an odd fridge (a name cut mid-word, a spot that's no longer one) is still drawn as afresh, and kept",
          board.fridge_html([dict(raw[0], name="x" * 59 + " yz", p=[5, 200])], people, {})
          == afresh([dict(raw[0], name="x" * 59 + " yz", p=[5, 200])], people, {}))

    # wrap.json, written only when it says something new
    wrap = _patched_due_crew()
    path = os.path.join(wrap._profile_files(), "wrap.json")
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()

    def refresh(more=0):
        day = lambda n: {"reviews": n, "studyTimeMs": 60000 * n, "accuracy": 90.0, "streak": 4}  # noqa: E731
        ents = [{"user_id": u, "name": u.title(), "you": u == "me", "paused": False, "decks": [],
                 "days": {lb: day(10 + k + (more if u == "dre" and not k else 0)) for k, lb in enumerate(labels)}}
                for u in ("me", "dre", "mo")]
        dc._commit({"entries": ents, "pending": [], "cheers": [], "my_code": "ABC", "my_friends": ["dre", "mo"]},
                   {}, labels, tomorrow)

    writes = []
    cl = types.SimpleNamespace(session={}, signed_in=True, user_id="me", _save_session=lambda: None)
    saved = (wrap.os, dc.client, together.client, dc._morning, dc._awaiting_phone, due_flow.after_refresh, due_flow._reviews,
             CF.check, dc.tooltip, dc._rerender, dc._swap, rooms.refresh_widgets, dc.account.saved_elsewhere, dict(_state))
    try:
        from due_crew import store  # 3.9.12: every file is written by store.py
        store.os = types.SimpleNamespace(path=os.path, remove=os.remove, open=os.open, fdopen=os.fdopen, chmod=os.chmod,
                                         replace=lambda a, b: (writes.append(b), os.replace(a, b)))
        dc.client = together.client = lambda: cl
        dc._morning = lambda *a, **k: None
        dc._awaiting_phone = lambda: False
        due_flow.after_refresh = lambda: None
        due_flow._reviews = lambda: {"done": 12, "due": 0}
        CF.check = lambda today: []
        dc.tooltip = lambda *a, **k: None
        dc._rerender = dc._swap = rooms.refresh_widgets = lambda *a, **k: None
        dc.account.saved_elsewhere = lambda at: None
        _state.update(board_shown=False, prev_label="", prev_counts={}, prev_streaks={}, days={}, decks={})
        wrap._wrap_data()["fridge"] = FR.clean(raw)
        refresh()
        first = len(writes)
        writes.clear()
        refresh()
        refresh()
        same = list(writes)
        refresh(more=40)
        changed = list(writes[len(same):])
        on_disk = json.load(open(path))
        wrap._wrap["profile"] = None  # the profile opened again: read from disk, and not written back
        wrap._wrap_data()
        wrap._save_wrap()
        reopened = writes[len(same) + len(changed):]
    finally:
        (wrap.os, dc.client, together.client, dc._morning, dc._awaiting_phone, due_flow.after_refresh, due_flow._reviews,
         CF.check, dc.tooltip, dc._rerender, dc._swap, rooms.refresh_widgets, dc.account.saved_elsewhere) = saved[:13]
        store.os = os
        _state.clear()
        _state.update(saved[13])
        wrap._wrap["profile"] = None
        wrap._wrap["data"] = {}
    check("efficiency: a refresh that changes nothing writes wrap.json not at all (it wrote it two or three times, fridge and all)",
          first >= 1 and same == [], (first, same))
    check("efficiency: one that changes something writes it once, whole, as it is; a profile opened again doesn't write it back",
          changed == [path] and on_disk["ledger"][labels[0]]["p"]["dre"] == 50 and len(on_disk["fridge"]) == len(raw)
          and reopened == [], (changed, reopened))


def test_decks_page_key_v391():
    """3.9.1 (the security review): Anki calls a message the Decks screen's
    from the moment it switches to it, while the page before (a card's, or
    Overview's with a deck's description, scripts and all) is still up. So
    the Decks page's own commands carry its key, new each run and written
    only into that page; without it, a message from "the Decks screen" gets
    a card page's rules. Nothing is drawn on the board until the Decks page
    is the one going in."""
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import app as A
    from due_crew.room_model import CMD_KEY
    sent = []
    hits = []
    real = dc._on_sync_done
    try:
        dc._on_sync_done = lambda *a, **k: hits.append("refresh")
        dc._on_js(False, "duecrew:refresh", DeckBrowser())
        dc._on_js(False, "duecrew:refresh|" + CMD_KEY, DeckBrowser())
        dc._on_js(False, "duecrew:refresh|0000", DeckBrowser())
        bare = list(hits)
        dc._on_js(False, "duecrew:refresh|" + board.BOARD_KEY, DeckBrowser())
        check("Decks key: a command from the Decks screen acts only with its page's key; bare, a widget's key or a wrong one, nothing",
              bare == [] and hits == ["refresh"], (bare, hits))
    finally:
        dc._on_sync_done = real
    check("Decks key: the board's commands carry it, as do the ones its scripts build; the page gets it once a draw",
          board._pycmd("refresh").endswith("|" + board.BOARD_KEY + "'); return false;")
          and board.key_js() == '<script>window.dcBK="' + board.BOARD_KEY + '";</script>'
          and len(board.BOARD_KEY) == 16 and board.BOARD_KEY != CMD_KEY
          and "'|' + window.dcBK" in board.cheer_overlay_js({"uid": "dre", "name": "Dre", "emojis": ["x"]})
          and "'|' + window.dcBK" in board.FRIDGE_JS)
    m = A.mw
    saved = (getattr(m, "state", None), m.web)
    try:
        m.web = types.SimpleNamespace(eval=sent.append)
        m.state = "deckBrowser"
        A.on_state_will_change("deckBrowser", "review")
        A.board_eval("x()")
        A.on_decks_render()
        A.board_eval("y()")
        A.on_state_will_change("review", "deckBrowser")
        m.state = "review"
        A.board_eval("z()")
        check("Decks key: nothing's drawn on the board on the way back to Decks till its page goes in, nor after it's left",
              sent == ["y()"], sent)
    finally:
        m.state, m.web = saved
        A._decks[0] = False
    src = srcs.glue_src()
    check("Decks key: the Decks page's render sets it down and says so; leaving it says so",
          "app.on_decks_render()\n    content.stats += board.key_js()" in src
          and "gui_hooks.state_will_change.append(app.on_state_will_change)" in src
          and all(f"app.board_eval(board.{f}" in open(os.path.join(REPO, "due_crew", mod)).read()
                  for mod, f in (("social.py", "flurry_js"), ("social.py", "cheer_overlay_js"), ("social.py", "profile_overlay_js"),
                                 ("squads.py", "stranger_card_js"), ("together.py", "luck_card_js"))))


def test_veil_v391():
    """3.9.1 (Sam: "when cheering, the full background doesn't grey out"):
    while a window is open over the board, the top and bottom bars (pages
    of their own) wear its backdrop too; a tap on them is Esc on the board.
    The board's page says when; leaving it, or a new page, takes it off."""
    import shutil
    import subprocess
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from due_crew import app as A
    from due_crew.room_model import CMD_KEY, trusted
    keep = board.keep_me_in_view_js()
    check("veil: the board's page watches for its windows once (with its scripts), never at every swap",
          board.VEIL_WATCH_JS in keep and board.VEIL_WATCH_JS not in board.keep_me_in_view_js(scripts=False)
          and "if (window.dcVeil || typeof MutationObserver === 'undefined') { return; }" in board.VEIL_WATCH_JS
          and all(f'"{i}"' in board.VEIL_WATCH_JS for i in ("dc-cheer", "dc-profile", "dc-sheet"))
          and "'|' + window.dcBK" in board.VEIL_WATCH_JS)
    top, bottom, main = [], [], []
    m = A.mw
    saved = (getattr(m, "toolbar", None), getattr(m, "bottomWeb", None), getattr(m, "state", None), m.web, A._decks[0])
    TopToolbar = type("TopToolbar", (), {})
    DeckBrowserBottomBar = type("DeckBrowserBottomBar", (), {})
    try:
        m.toolbar = types.SimpleNamespace(web=types.SimpleNamespace(eval=top.append))
        m.bottomWeb = types.SimpleNamespace(eval=bottom.append)
        m.web = types.SimpleNamespace(eval=main.append)
        m.state = "deckBrowser"
        A.on_decks_render()
        dc._on_js(False, "duecrew:veil:1|" + board.BOARD_KEY, DeckBrowser())
        on = (list(top), list(bottom), A._veiled[0])
        dc._on_js(False, "duecrew:veil:0|" + board.BOARD_KEY, DeckBrowser())
        off = (top[-1:], bottom[-1:], A._veiled[0])
        dc._on_js(False, "duecrew:veil:1", DeckBrowser())  # without the page's key: a card's page, nothing
        bare = A._veiled[0]
        check("veil: a window on the board dims both bars, its going undims them; only the board's page says so",
              len(on[0]) == len(on[1]) == 1 and "(true)" in on[0][0] and on[0] == on[1] and on[2] is True
              and "(false)" in off[0][0] and off[1] == off[0] and off[2] is False and bare is False, (on, off, bare))
        dc._on_js(False, "duecrew:veil:1|" + board.BOARD_KEY, DeckBrowser())
        A.on_set_content(None, TopToolbar())
        A.on_set_content(None, DeckBrowserBottomBar())
        bars = A._veiled[0]
        A.on_set_content(None, DeckBrowser())
        page = A._veiled[0]
        dc._on_js(False, "duecrew:veil:1|" + board.BOARD_KEY, DeckBrowser())
        A.on_state_will_change("review", "deckBrowser")
        m.state = "review"
        left = (A._veiled[0], "(false)" in top[-1])
        dc._on_js(False, "duecrew:veil:1|" + board.BOARD_KEY, DeckBrowser())
        late = A._veiled[0]
        check("veil: a bar's own new page keeps it; the main view's new page, leaving Decks or a late word from the page takes it off",
              bars is True and page is False and left == (False, True) and late is False, (bars, page, left, late))
        m.state = "deckBrowser"
        A.on_decks_render()
        del main[:]
        dc._on_js(False, "duecrew:veiltap|" + CMD_KEY, DeckBrowserBottomBar())
        dc._on_js(False, "duecrew:veiltap|" + CMD_KEY, TopToolbar())
        check("veil: a tap on a bar's shade is Esc on the board, from the Decks bottom bar (Anki's page: keyed) or the top bar",
              len(main) == 2 and all("key: 'Escape'" in x for x in main) and trusted("duecrew:veiltap|" + CMD_KEY, True)[1]
              and not trusted("duecrew:veil:1|" + CMD_KEY, True)[1] and f"duecrew:veiltap|{CMD_KEY}" in A.VEIL_JS % {"key": CMD_KEY, "on": "true"})
    finally:
        m.toolbar, m.bottomWeb, m.state, m.web, A._decks[0] = saved
        A._veiled[0] = False
    node = shutil.which("node")
    if not node:
        print("SKIP the veil's scripts in node: no node")
        return
    dom = r"""
    function El(tag) { this.tagName = tag; this.style = {}; this.kids = []; this.l = {}; this.attrs = {}; }
    El.prototype.appendChild = function (k) { this.kids.push(k); k.parent = this; if (typeof fire === 'function') fire('child'); return k; };
    El.prototype.addEventListener = function (t, f) { this.l[t] = f; };
    El.prototype.getBoundingClientRect = function () { return {}; };
    El.prototype.remove = function () { var p = this.parent; p.kids = p.kids.filter((x) => x !== this); fire('child'); };
    El.prototype.removeAttribute = function (a) { if (a === 'id') { this.id = ''; fire('attr'); } };
    var body = new El('body'), sent = [], obs = [];
    function find(n, id) { if (n.id === id) return n; for (var k of n.kids) { var f = find(k, id); if (f) return f; } return null; }
    var document = { body: body, createElement: (t) => new El(t), getElementById: (id) => find(body, id) };
    var window = { dcBK: 'KEY', matchMedia: () => ({ matches: false }) };
    function pycmd(c) { sent.push(c); }
    function MutationObserver(f) { this.f = f; }
    MutationObserver.prototype.observe = function (n, o) { obs.push([this.f, o]); };
    function fire(kind) { obs.forEach(([f, o]) => { if ((kind === 'child') === !!o.childList) f(); }); }
    """
    watch = dom + board.VEIL_WATCH_JS + r"""
    var a = new El('div'); a.id = 'dc-cheer'; body.appendChild(a);
    var b = new El('div'); b.id = 'dc-profile'; body.appendChild(b);
    b.remove();
    a.removeAttribute('id');
    a.remove();
    console.log(JSON.stringify(sent));
    """
    run = subprocess.run([node, "-e", watch], capture_output=True, text=True, timeout=60)
    check("veil: the page says once when a window comes and once when the last one starts to go",
          run.stdout.strip() == '["duecrew:veil:1|KEY","duecrew:veil:0|KEY"]', run.stdout + run.stderr[-1500:])
    bar = dom + "function fire() {}\n" + (A.VEIL_JS % {"key": "WK", "on": "true"}) + (A.VEIL_JS % {"key": "WK", "on": "true"}) + r"""
    var v = document.getElementById('dc-veil'), n = body.kids.length, up = [v.style.opacity, v.style.pointerEvents];
    v.l.click();
    """ + (A.VEIL_JS % {"key": "WK", "on": "false"}) + r"""
    console.log(JSON.stringify([n, up, [v.style.opacity, v.style.pointerEvents], sent, v.style.cssText]));
    """
    run = subprocess.run([node, "-e", bar], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(run.stdout)
    except ValueError:
        got = None
    check("veil: a bar gets one shade, the board's backdrop over everything; a tap sends the widget's keyed veiltap; off, it lets clicks through",
          got is not None and got[0] == 1 and got[1] == ["1", "auto"] and got[2] == ["0", "none"]
          and got[3] == ["duecrew:veiltap|WK"] and "rgba(0,0,0,.35)" in got[4] and "z-index:2147483647" in got[4],
          run.stdout + run.stderr[-1500:])


def test_sheets_v391():
    """3.9.1 (Sam: "make sure all modals are in our style"): a question, one
    line or one of a few, as a sheet on the Decks screen in the Cheer
    window's look; the Qt one off the board. Only a yes reaches then, and
    only an answer naming the open sheet's id, with the page's key."""
    import shutil
    import subprocess
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    from urllib.parse import quote
    from due_crew import app as A, sheets, ui
    js = board.sheet_js({"id": "abc", "title": "Status </script><b>", "text": "One line.\n\nTwo.", "yes": "Set",
                         "field": {"kind": "text", "value": "200 cards", "max": 99999}, "check": {"label": "Tags <i>too</i>", "on": 1}})
    view = json.loads(re.search(r"var V = (\{.*?\});\n", js).group(1).replace("<\\/", "</"))
    check("sheet: its words as JSON (no '</' to end the script), as text never markup; a box's ceiling kept sane",
          "</script>" not in js.split("var V = ")[1].split(";\n")[0] and view["title"] == "Status </script><b>"
          and view["field"] == {"kind": "text", "value": "200 cards", "max": 2000, "hint": ""} and view["check"] == {"label": "Tags <i>too</i>", "on": True}
          and "innerHTML" not in board.SHEET_JS and "textContent" in board.SHEET_JS and "white-space:pre-line" in board.SHEET_JS)
    pick = json.loads(re.search(r"var V = (\{.*?\});\n", board.sheet_js({"id": "x", "title": "t", "field": {"kind": "pick", "items": ["a", "b"], "at": 9}})).group(1))
    none = json.loads(re.search(r"var V = (\{.*?\});\n", board.sheet_js({"id": "x", "title": "t", "field": {"kind": "pick", "items": []}})).group(1))
    odd = json.loads(re.search(r"var V = (\{.*?\});\n", board.sheet_js({"id": "x", "title": "t", "field": {"kind": "html"}})).group(1))
    check("sheet: a pick's place kept in its list; no items or an unknown kind, no field",
          pick["field"]["at"] == 1 and none["field"] is None and odd["field"] is None)
    check("sheet: the board's tokens and font, the Cheer window's buttons, its answer one keyed command; Esc and the backdrop say no",
          js.startswith(board.POP_JS) and "window.dcPop.theme()" in board.SHEET_JS and "var font = T.font;" in board.SHEET_JS
          and "#dc-sheet .go{background:' + accent" in board.SHEET_JS and "#dc-sheet .no{background:none" in board.SHEET_JS
          and "pycmd('duecrew:sheet:' + V.id + ':' + encodeURIComponent(JSON.stringify(p)) + '|' + window.dcBK)" in board.SHEET_JS
          and "pop.show(card, { esc: function () { say({ ok: false }); } });" in board.SHEET_JS
          and "dc-sheet" in board.VEIL_IDS)

    # the glue: on the board, a sheet; its answer, once, with its id
    m = A.mw
    saved = (getattr(m, "state", None), m.web, A._decks[0], A.generation, dc._state.get("entries"))
    sent, got, nos = [], [], []
    try:
        m.web = types.SimpleNamespace(eval=sent.append)
        m.state = "deckBrowser"
        A.on_decks_render()
        sheets.confirm("Sign out?", "Sure?", "Sign out", lambda: got.append("yes"), no=lambda: nos.append("no"))
        sid = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        answer = lambda i, p, key=board.BOARD_KEY: dc._on_js(False, f"duecrew:sheet:{i}:{quote(json.dumps(p))}|{key}", DeckBrowser())
        answer("0" * 16, {"ok": True})
        answer(sid, {"ok": True}, key="")
        wrong = list(got)
        answer(sid, {"ok": True})
        answer(sid, {"ok": True})
        check("sheets: on the board a sheet, not Qt; only its own id with the page's key answers it, and once",
              len(sent) == 1 and "dc-sheet" in sent[0] and '"yes": "Sign out"' in sent[0] and wrong == [] and got == ["yes"], (wrong, got))
        sheets.confirm("Leave?", "", "Leave", lambda: got.append("left"), no=lambda: nos.append("no"))
        sid = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        answer(sid, {"ok": False})
        sheets.confirm("Leave?", "", "Leave", lambda: got.append("left"))
        sid = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        answer(sid, {"ok": False})
        check("sheets: Cancel, Esc or the backdrop: nothing, or the question's no() when it leads to another",
              got == ["yes"] and nos == ["no"], (got, nos))
        sheets.ask_text("Status", "One line.", got.append, value="x", most=5)
        first = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        sheets.ask_item("Change deck", "Run it on", ["A", "B"], got.append, at=1)
        sid = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        answer(first, {"ok": True, "text": "stale"})
        answer(sid, {"ok": True, "at": 7})
        sheets.ask_item("Change deck", "Run it on", ["A", "B"], got.append, at=1)
        sid = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        answer(sid, {"ok": True, "at": 1})
        sheets.ask_text("Status", "One line.", got.append, value="x", most=5)
        sid = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        answer(sid, {"ok": True, "text": "123456789"})
        check("sheets: one at a time (a new one drops the one before); a pick out of the list does nothing; a line keeps to its ceiling",
              got == ["yes", 1, "12345"], got)
        sheets.confirm("Sign out?", "Sure?", "Sign out", lambda: got.append("late"))
        sid = re.search(r'"id": "([0-9a-f]+)"', sent[-1]).group(1)
        n = len(sent)
        sheets.redraw()
        again = sent[n:]
        A.generation += 1
        answer(sid, {"ok": True})
        check("sheets: a Decks page drawn anew draws the open one again; an answer from before a profile change does nothing",
              len(again) == 1 and f'"id": "{sid}"' in again[0] and got == ["yes", 1, "12345"], (len(again), got))
        # off the board: Qt asks (the suite's Qt says yes, as askUser's fake did)
        A.on_state_will_change("review", "deckBrowser")
        n = len(sent)
        seen = []
        real = ui.confirm
        ui.confirm = lambda parent, title, text, yes: seen.append((title, text, yes)) or True
        try:
            sheets.confirm("Sign out?", "Sure?", "Sign out", lambda: got.append("qt"))
        finally:
            ui.confirm = real
        check("sheets: off the board, Qt's question, the same words; a yes reaches then",
              len(sent) == n and seen == [("Sign out?", "Sure?", "Sign out")] and got[-1] == "qt", (seen, got))
    finally:
        m.state, m.web, A._decks[0], A.generation, dc._state["entries"] = saved
        sheets._open.clear()
    src = {f: srcs.due_src(f) for f in ("__init__.py", "social.py", "due_flow.py", "team_flow.py",
                                                                      "together.py", "plan_flow.py", "squads.py", "cards.py")}
    check("sheets: what the board asks goes through them: status, name, sign out, delete, a to-do, the plan squad, "
          "a good-luck line, a tip, hold back, reset, change deck, stop following, the founder's tools",
          all(k in src[f] for f, k in (("social.py", 'sheets.ask_text("Status"'), ("__init__.py", 'sheets.ask_text("Display name"'),
                                       ("__init__.py", 'sheets.confirm("Sign out?"'), ("__init__.py", 'sheets.confirm("Delete account?"'),
                                       ("due_flow.py", 'sheets.ask_text("Edit to-do"'), ("team_flow.py", 'sheets.confirm("Join this plan'),
                                       ("team_flow.py", 'sheets.ask_text("Reply"'), ("team_flow.py", 'sheets.ask_text("Ask the squad"'),
                                       ("together.py", 'sheets.ask_text("Good-luck card"'), ("together.py", 'sheets.ask_text("Send a tip"'),
                                       ("plan_flow.py", "sheets.confirm(title, text, yes"), ("plan_flow.py", 'sheets.confirm("Reset to default?"'),
                                       ("plan_flow.py", 'sheets.ask_item("Change deck"'), ("plan_flow.py", "sheets.confirm_check(title, text, \"Stop\""),
                                       ("squads.py", 'sheets.confirm("Block?"'), ("squads.py", 'sheets.confirm("Remove?"')))
          and not any(x in t for t in src.values() for x in ("QInputDialog", "askUser", "getText(")))
    node = shutil.which("node")
    if not node:
        print("SKIP the sheet in node: no node")
        return
    dom = r"""
    function El(tag) { this.tagName = tag; this.style = {}; this.kids = []; this.l = {}; this.attrs = {}; this.value = '';
                       this.offsetTop = 0; this.offsetHeight = 10; this.scrollTop = 0; this.clientHeight = 100; }
    El.prototype.appendChild = function (k) { this.kids.push(k); k.parentNode = this; return k; };
    El.prototype.addEventListener = function (t, f) { this.l[t] = f; };
    El.prototype.setAttribute = function (a, v) { this.attrs[a] = String(v); };
    El.prototype.removeAttribute = function (a) { if (a === 'id') { this.id = ''; } delete this.attrs[a]; };
    El.prototype.focus = function () { focused = this; };
    El.prototype.select = function () {};
    El.prototype.remove = function () { removed.push(this); };
    var focused = null, removed = [], sent = [], doc = {};
    var body = new El('body');
    function find(n, id) { if (n.id === id) return n; for (var k of n.kids) { var f = find(k, id); if (f) return f; } return null; }
    function all(n, out) { out = out || []; out.push(n); n.kids.forEach((k) => all(k, out)); return out; }
    var document = { body: body, createElement: (t) => new El(t), getElementById: (id) => find(body, id),
                     addEventListener: (t, f) => { doc[t] = f; }, removeEventListener: (t) => { delete doc[t]; } };
    var window = { dcBK: 'KEY', matchMedia: () => ({ matches: true }) };
    function getComputedStyle() { return null; }
    function pycmd(c) { sent.push(decodeURIComponent(c)); }
    function btn(text) { return all(body).find((e) => e.tagName === 'button' && e.textContent === text); }
    """
    def run(view, then):
        prog = dom + board.sheet_js(view) + "\n" + then + "\nconsole.log(JSON.stringify(sent));"
        r = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
        try:
            return json.loads(r.stdout)
        except ValueError:
            return r.stdout + r.stderr[-1500:]
    typed = run({"id": "s1", "title": "Status", "field": {"kind": "text", "value": "old", "max": 80}},
                "var box = all(body).find((e) => e.tagName === 'input'); var wasFocused = focused === box; box.value = 'new line'; btn('OK').l.click();"
                "sent.push(String(wasFocused), String(box.maxLength));")
    cancelled = run({"id": "s2", "title": "Leave?", "yes": "Leave", "danger": True},
                    "var f = focused && focused.textContent; doc.keydown({ key: 'Escape', stopPropagation() {} }); btn('Leave').l.click(); sent.push(f);")
    picked = run({"id": "s3", "title": "Change deck", "field": {"kind": "pick", "items": ["A", "B", "C"], "at": 0}},
                 "btn('C').l.click(); btn('OK').l.click();")
    ticked = run({"id": "s4", "title": "Stop following?", "yes": "Stop", "check": {"label": "Tags too", "on": True}},
                 "all(body).find((e) => e.type === 'checkbox').checked = false; btn('Stop').l.click();")
    check("sheet in node: a line starts in its box, its ceiling set, and goes with its button; Esc says no once (a step that can't be "
          "taken back starts on Cancel); a pick and a tick go as asked",
          typed == ['duecrew:sheet:s1:{"ok":true,"text":"new line"}|KEY', "true", "80"]
          and cancelled == ['duecrew:sheet:s2:{"ok":false}|KEY', "Cancel"]
          and picked == ['duecrew:sheet:s3:{"ok":true,"at":2}|KEY']
          and ticked == ['duecrew:sheet:s4:{"ok":true,"check":false}|KEY'], (typed, cancelled, picked, ticked))


def test_qt_look_v391():
    """3.9.1 (Sam: "make sure all modals are in our style"): every Qt window
    wears the board's look (ui.styled, from attach_alive or its own call):
    its colours for its theme and accent, the main action in the accent; a
    label's own style sheet takes tone(), never palette(...), which a styled
    window doesn't pass down. tools/dialogs.py renders them all."""
    import glob
    from due_crew import board as B, ui
    ok, drawn = True, set()
    was = (ui._dark, ui._accent_name)
    try:
        for theme in ("light", "dark"):
            for name in B.ACCENTS:
                ui._dark, ui._accent_name = (lambda th=theme: th == "dark"), (lambda n=name: n)
                t = ui.tokens()
                try:
                    css = ui.qss(t)
                except (KeyError, IndexError, ValueError):
                    ok = False
                    continue
                ok = ok and all(t[k] in css for k in ("accent", "bg", "ink", "edge", "ink-2")) and "{{" not in css
                drawn.update(re.findall(r'url\("([^"]+)"\)', css))
    finally:
        ui._dark, ui._accent_name = was
    check("qt look: the stylesheet takes every theme and accent's tokens", ok)
    check("qt look: its arrows and ticks are drawings in the window's colours, written once beside the add-on",
          drawn and all(os.path.isfile(f) and open(f).read().startswith("<svg") and "\\" not in f for f in drawn)
          and len(drawn) == len(set(os.path.basename(f) for f in drawn)), sorted(drawn)[:3])
    check("qt look: the suite's Qt has none of it, and nothing raises; a tone is the board's colour",
          ui.styled(object()) is not None and ui.tone("muted") in (B.LIGHT["muted"], B.DARK["muted"]))
    src = {os.path.basename(p): open(p).read() for p in glob.glob(os.path.join(REPO, "due_crew", "ui", "*_dialog.py"))}
    init = open(os.path.join(REPO, "due_crew", "ui", "__init__.py")).read()
    unstyled = [f for f, t in src.items() if "(QDialog)" in t and t.count("(QDialog)") > t.count("attach_alive(self)") + t.count("styled(self)")]
    check("qt look: every dialog wears it (attach_alive styles it, the rest call styled)",
          "    styled(dialog)  # 3.9.1" in init and not unstyled, unstyled)
    check("qt look: no dialog's own style sheet reads palette(...) or a fixed grey",
          not [f for f, t in src.items() if re.search(r"palette\(|color: gray", t)])
    check("qt look: a question's yes is the accent (the red when it can't be taken back), Cancel focused; no icon",
          'go.setProperty("dc", "bad" if danger else "go")' in init and "box.setDefaultButton(cancel)" in init
          and "QMessageBox.Icon.NoIcon" in init and 'QPushButton[dc="go"]' in ui.QSS and 'QPushButton[dc="bad"]' in ui.QSS)


def test_qt_look_round_two_v391():
    """3.9.1, round two (Sam, of the Open a Study Room window on a Mac:
    "washed out. bad spacing. not engaging"): the Mac's own style drew a
    dressed box's arrow in a box and its list as a menu with ticks that cut
    its words off. Every Due Crew window now sits on Fusion (ui.base_style),
    with the board's look drawing every box, arrow, tick, radio dot and list
    itself, the same on a Mac, Windows and Linux, under Anki's style or the
    system's; a window's edges and rows have room; a window says what it is
    in a title (ui.heading), its frame says Due Crew; small print is one
    size and readable (role "note"); and a window grows to what its rows and
    words need (ui._fit: Qt capped one at two thirds of the screen, and
    Follow a plan's rows ran into each other). tools/dialogs.py renders every
    window and fails on a clipped button, a squeezed box, two controls on top
    of each other or a window shorter than its words."""
    import glob
    from due_crew import ui
    init = open(os.path.join(REPO, "due_crew", "ui", "__init__.py")).read()
    src = {os.path.basename(p): open(p).read() for p in glob.glob(os.path.join(REPO, "due_crew", "ui", "*_dialog.py"))}
    check("qt look 2: Fusion under every window, a little more room at its edges and between its rows",
          'QStyleFactory.create("Fusion")' in init and "PM_LayoutLeftMargin: 22" in init
          and "PM_LayoutVerticalSpacing: 8" in init and "dialog.setStyle(style)" in init)
    check("qt look 2: the sheet draws a box's arrow, a number box's buttons, ticks and radio dots, and a box's list as a list",
          all(x in ui.QSS for x in ("QComboBox::down-arrow", "QAbstractSpinBox::up-button", "QAbstractSpinBox::up-arrow",
                                    "QCheckBox::indicator:checked", "QRadioButton::indicator:checked",
                                    "QAbstractItemView::indicator", "combobox-popup: 0",
                                    "QComboBox QAbstractItemView::item", "QTreeView::branch:has-children:closed")))
    check("qt look 2: one type scale: 13px, 16px titles, 12px small print in a readable ink; no window sets its own",
          "* {{ font-size: 13px; }}" in ui.QSS and 'QLabel[dc="title"] {{ font-size: 16px' in ui.QSS
          and 'QLabel[dc="note"] {{ font-size: 12px; color: {ink-2}; }}' in ui.QSS
          and not [f for f, t in src.items() if re.search(r"font-size: 11(\.5)?px", t)], 
          [f for f, t in src.items() if re.search(r"font-size: 11(\.5)?px", t)])
    no_title = [f for f, t in src.items() if t.count("(QDialog)") > len(re.findall(r"\bheading\(self|\btitle\(", t))
                and f not in ("auth_dialog.py",)]  # the sign-in has the logo on top
    check("qt look 2: every window says what it is in its title; its frame says Due Crew",
          not no_title and 'dialog.setWindowTitle("Due Crew")' in init and 'box.setWindowTitle("Due Crew")' in init, no_title)
    check("qt look 2: a window's title and a heading are plain text (a plan's or a person's name)",
          "label.setTextFormat(Qt.TextFormat.PlainText)" in init.split("def title(")[1].split("def ")[0]
          and not [f for f, t in src.items() if re.search(r'QLabel\(f?"<b>', t)])
    check("qt look 2: a window grows to its rows and its words, never shrinks, never past its screen; tidied before it takes its size",
          "def _fit(window):" in init and "QEvent.Type.LayoutRequest" in init and "QEvent.Type.Polish" in init
          and "need_w >= w and need_h >= h" in init and "availableGeometry()" in init)
    dialogs = open(os.path.join(REPO, "tools", "dialogs.py")).read()
    check("qt look 2: the renderer fails on what a person would see as broken, and renders on a laptop's screen",
          "broken = fits(dlg)" in dialogs and '"width": 1440, "height": 900' in dialogs and "def kitchen():" in dialogs
          and "def questions():" in dialogs)


def test_room_sounds_gone_v398():
    """3.9.8 (Sam: "remove the whole room sounds feature"): no speaker on
    the chip, no player in the top bar, no recordings shipped, no setting,
    no command; a config that still says room_sound is simply ignored."""
    from due_crew import room_model as rm, settings_model as sm
    root = os.path.join(REPO, "due_crew")
    conf = json.load(open(os.path.join(root, "config.json")))
    fif = rm.make_fifteen("me", datetime.datetime(2026, 10, 17, 18, 0, tzinfo=datetime.timezone.utc))
    chip = rm.widget_js("chip", rm.widget_data(fif, [], ("#2e7d32", "#7cc47f")))
    glue = srcs.glue_src() + open(os.path.join(root, "rooms.py")).read()
    check("room sounds are gone: no files, no keys, no switch, no speaker, no player, no command",
          not os.path.exists(os.path.join(root, "sounds")) and not os.path.exists(os.path.join(root, "sounds.js"))
          and not {"room_sound", "room_sound_vol"} & set(conf) and "room_sounds" not in sm.BOARD_DEFAULTS
          and "room_sounds" not in sm.SWITCHES and "set:room_sounds:" not in board.FIND_WORDS
          and not any(hasattr(rm, n) for n in ("sound_pick", "sound_state", "sound_js", "sound_cmd", "sounds_on", "SOUNDS"))
          and "Room sound" not in chip and "roomsound" not in chip and "dcSounds" not in chip
          and "roomsound" not in glue and "setWebExports" not in glue and "dcRoomSound" not in glue
          and 'aria-label="Room sounds"' not in board._settings_board({})
          and "sounds/" not in open(os.path.join(REPO, "LICENSE")).read())
    from due_crew import rooms as R
    check("room sounds are gone: an old chip's click is just not ours (not a card page's command, no room handler takes it)",
          "roomsound" not in rm.CARD_PAGE_CMDS and R.on_message("roomsound", ["duecrew", "roomsound", "rain", "50"]) is False
          and rm.trusted("duecrew:roomsound:rain:50|" + rm.CMD_KEY, True)[1] is False)


def _sim_log(days=200, pace=30, seed=7, batch=False):
    """3.9.2: a simple learner, stdlib only: a pass pushes a card 2 to 3 times
    as far, a miss (20% under a week, 10% after) brings it back tomorrow.
    Rows as the add-on reads them: (day from today, cid, ease, ivl, lastIvl, type)."""
    import random
    rng = random.Random(seed)
    cards, log, nxt = {}, [], 0
    for t in range(days):
        for cid, (due, ivl) in sorted(cards.items()):
            if due > t:
                continue
            if rng.random() < (0.2 if ivl < 7 else 0.1):
                log += [(t, cid, 1, -600, ivl, 1), (t, cid, 3, 1, -600, 2)]
                cards[cid] = (t + 1, 1)
            else:
                n = max(ivl + 1, int(round(ivl * rng.uniform(2.0, 3.0))))
                log.append((t, cid, 3, n, ivl, 1))
                cards[cid] = (t + n, n)
        for _ in range((pace * 7 if t % 7 == 0 else 0) if batch else pace):
            log += [(t, nxt, 3, -600, 0, 0), (t, nxt, 3, 1, -600, 0)]
            cards[nxt] = (t + 1, 1)
            nxt += 1
    rows = [(d - days, c, e, i, li, ty) for d, c, e, i, li, ty in log]
    first = {}
    for d, c, e, *_ in rows:
        if e > 0 and (c not in first or d < first[c]):
            first[c] = d
    return rows, first, {c: (due - days, ivl) for c, (due, ivl) in cards.items()}


def test_reviews_ahead_392():
    """3.9.2 (Sam's picks, 18 Oct: Your week becomes Reviews ahead): the next
    six weeks of a deck in cards a day, counted from my own log (how my
    reviews go at each interval, my own new-card curve, when I start new
    cards: in batches, by weekday), its ways (my pace, stop new a week
    before the exam or now, only what's unlocked), the pause Do it asks
    for (Anki's today-only limit each morning, deck options untouched),
    the track record on my own past, and the board's line when reviews
    climb. Mine alone, never sent."""
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    from due_crew import ahead as A, ahead_flow as AF, plan_flow as F, team_flow as TF, board
    from due_crew.app import _state
    # ---- pure: habits, the curve, the pace ----
    log = []
    for i in range(40):  # 40 reviews at a 10-day interval: 10 missed, landing at 2 days after one step
        if i % 4 == 0:
            log += [(-50 + i, i, 1, -600, 10, 1), (-50 + i, i, 3, 2, -600, 2)]
        else:
            log.append((-50 + i, i, 3, 25, 10, 1))
    hab, extra = A.habits(log)
    p, g, land = hab[A._b(10)]
    check("ahead: habits by interval, counted: a quarter missed, a pass's push in thirds, a miss lands where mine did",
          abs(p - 0.25) < 1e-9 and g == (2.5, 2.5, 2.5) and land == 2 and extra == 1.0 and hab[A._b(400)][0] == 0.25, (hab, extra))
    check("ahead: nothing to go on, a plain default", A.habits([])[0][0] == A._DEFAULT)
    rows, first, now = _sim_log()
    cv = A.curve(rows, first)
    check("ahead: my own curve from the cards I started 6 to 17 weeks ago (each seen on its day, more answers that day)",
          cv is not None and cv[2] == 30 * 79 and cv[0][0] == 1.0 and cv[1][0] == 2.0 and cv[0][1] == 1.0
          and 0 < cv[0][5] < 1, cv and (cv[2], cv[0][:6], cv[1][:2]))
    check("ahead: under 60 of them, none (a typical curve stands in)", A.curve(rows, {c: d for c, d in first.items() if c < 50}) is None)
    batch, bfirst, _bn = _sim_log(days=120, pace=40, batch=True)
    rate = A.pace(bfirst, wd0=(120 % 7) % 7)
    check("ahead: my pace by weekday: a batch unlocked on one day a week lands on that day",
          sorted(round(x) for x in rate) == [0, 0, 0, 0, 0, 0, 280] and abs(sum(rate) - 280) < 1e-9, rate)
    check("ahead: a deck begun 3 days ago: a week's span at least",
          A.pace({1: -2, 2: -2, 3: -1}, 0) == [0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 1.0], A.pace({1: -2, 2: -2, 3: -1}, 0))
    # ---- starts and the ways ----
    st = A.starts([10.0] * 7, 0, left=25, today_done=4)
    check("ahead: starts: today less what's started, never more than the deck has left",
          st[:4] == [6.0, 10.0, 9.0, 0.0] and sum(st) == 25, st[:5])
    st = A.starts([10.0] * 7, 0, left=1000, stop=(2, 4))
    check("ahead: a stop has none on its days", st[:6] == [10.0, 10.0, 0.0, 0.0, 0.0, 10.0], st[:6])
    st = A.starts([10.0] * 7, 0, left=1000, plan={1: 50, 3: 40}, pool=15)
    check("ahead: a plan: its dates' cards on their day, the unlocked ones at my pace first",
          st[:5] == [10.0, 55.0, 0.0, 40.0, 0.0], st[:5])
    keys = lambda *a: [k for k, _s in A.choices(*a)]  # noqa: E731
    check("ahead: the ways: an exam 10 days out, a week before or now; 5 days out, now; none, now for good",
          keys(10, [40.0] * 7, 5000, 9000) == ["pace", "week", "now"] and A.choices(10, [40.0] * 7, 5000, 9000)[1][1] == (3, 10)
          and keys(5, [40.0] * 7, 5000, 9000) == ["pace", "now"] and A.choices(None, [40.0] * 7, 5000, 9000)[1] == ("now", (0, A.H)))
    check("ahead: only what's unlocked: a batch person (it runs out within two weeks) with more to unlock",
          keys(None, [40.0] * 7, 300, 9000) == ["pace", "unlocked", "now"] and keys(None, [40.0] * 7, 300, 300) == ["pace", "now"])
    check("ahead: a pause's days follow my exam date; it ends when the exam passes or goes",
          A.stop_of({"kind": "now", "at": "2026-09-01", "exam": True}, 9, "2026-09-02") == (0, 9)
          and A.stop_of({"kind": "week", "at": "2026-09-01", "exam": True}, 12, "2026-09-02") == (5, 12)
          and A.stop_of({"kind": "now", "at": "2026-09-01", "exam": True}, -1, "2026-09-02") is None
          and A.stop_of({"kind": "week", "exam": True}, None, "2026-09-02") is None
          and A.stop_of({"kind": "now", "at": "2026-09-01", "exam": False}, None, "2026-09-02") == (0, A.H)
          and A.stop_of(None, 3, "2026-09-02") is None)
    hab, extra = A.habits(rows)
    started = A.existing(list(now.values()), hab, extra)
    v = A.view(started, cv, [30.0] * 7, 0, 9000, 400, [300] * 7, exam_in=10)
    pace_w, stop_w = v["ways"][0], v["ways"][2]
    check("ahead: each way its own six weeks; stopping now lowers the exam week, not today's reviews",
          [w["key"] for w in v["ways"]] == ["pace", "week", "now"] and v["on"] == "pace"
          and stop_w["cards"][10] < pace_w["cards"][10] and abs(stop_w["started"][0] - pace_w["started"][0]) < 1e-9
          and stop_w["starts"] == 30 * (A.H - 11) and len(pace_w["cards"]) == A.H, [round(w["cards"][10]) for w in v["ways"]])
    off = A.view(started, cv, [30.0] * 7, 0, 9000, 400, [300] * 7, exam_in=10, off=(0, 10))
    check("ahead: the pause in effect is its way, on", off["on"] == "now", off["on"])
    odd = A.view(started, cv, [30.0] * 7, 0, 9000, 400, [300] * 7, exam_in=10, off=(2, 10))
    check("ahead: a pause no pill matches is a way of its own", odd["on"] == "off" and odd["ways"][-1]["stop"] == (2, 10))
    check("ahead: the board's line: the next two weeks' busiest three days a quarter over this week, and 20 more",
          A.climb([100] * 7, [0] + [100] * 5 + [140, 150, 145] + [100] * 33) == (7, 145)
          and A.climb([100] * 7, [0] + [120] * 41) is None and A.climb([10] * 7, [0] + [20] * 41) is None and A.climb([], [5] * 42) is None)
    held = A.starts([10.0] * 7, 0, 1000, h=14, stop=(0, 2), plan={1: 50}, pool=0)
    check("ahead: a plan's date inside a stop still opens; its cards start after, at my pace (a real deck)",
          held[:3] == [0.0, 0.0, 0.0] and held[3:8] == [10.0] * 5 and sum(held) == 50, held)
    check("ahead: numbers as the chart says them", [A.r(x) for x in (7.4, 42, 187, 1234)] == [7, 40, 185, 1230])
    # ---- the track record: forecast from past days, against what really happened ----
    res = A.backtest(rows, first, now)
    tr = A.trust(res)
    check("ahead: the track record from three past days, six weeks each; on a steady learner within 15% a week",
          len(res) == 3 and tr is not None and tr[0] < 0.15 and len(tr[1]) == 6, tr)
    yrows, yfirst, ynow = _sim_log(days=80, pace=20, seed=4)
    yres = A.backtest(yrows, yfirst, ynow)
    check("ahead: a deck under 12 weeks has a track record, the forecast as it would have run then (a real deck had none)",
          A.curve(yrows, yfirst, -42) is None and len(yres) == 3 and A.trust(yres) is not None and A.trust(yres)[0] < 0.25,
          A.trust(yres))
    check("ahead: a past day with under 100 cards started before it is left out",
          len(A.backtest(*_sim_log(days=75, pace=3, seed=4))) < 3)
    brows, bf2, bnow = _sim_log(days=200, pace=40, batch=True, seed=3)
    btr = A.trust(A.backtest(brows, bf2, bnow))
    check("ahead: and on one who unlocks a batch a week", btr is not None and btr[0] < 0.2, btr)
    due_only, by_day = [], {}
    for d, c, e, *_ in rows:
        if e > 0:
            by_day.setdefault(d, set()).add(c)
    for b in A.BACK:
        T0 = -b
        st0 = A.state_at(rows, first, now, T0)
        dd = [0] * A.H
        for due, _i in st0:
            if max(due, 0) < A.H:
                dd[max(due, 0)] += 1
        did = [len(by_day.get(T0 + k, ())) for k in range(A.H)]
        due_only.append(sum(abs(sum(dd[i:i + 7]) - sum(did[i:i + 7])) / max(1, sum(did[i:i + 7])) for i in range(0, A.H, 7)) / 6)
    sus = [(-30, 1, 3, 10, 4, 1), (-20, 1, 1, -600, 10, 1), (-30, 2, 3, 10, 4, 1)]
    st_s = A.state_at(sus, {1: -60, 2: -60}, {}, -25, gone={1, 2})
    check("ahead: a card suspended now is in the past it was answered in; one unanswered since, not",
          st_s == [(5, 10)], st_s)
    check("ahead: counted beats counting only what's due (Anki's Future Due) on the same past",
          tr[0] < min(due_only), (tr[0], due_only))
    # ---- the board ----
    s0 = _ahead_sample(exam_in=10)
    html = board._ins_ahead(10, s0, "<b>Spanish")
    check("board: Reviews ahead is its line and its chart (3.9.10: no ways to pick, no Do it, nothing under it)",
          html.count('class="ahw"') == 1 and " hidden>" not in html and 'data-k="pace">' in html
          and 'role="radiogroup"' not in html and "Your pace &middot;" not in html and "Stop new" not in html
          and "insaheadoff" not in html and "Counted from" not in html and "xact" not in html, html[:1500])
    check("board: data first: the cards I've started first, what new ones add at my pace, this week, the time; the exam week against my pace",
          "Next 2 weeks: <b>" in html and "a day from cards you&rsquo;ve started, <b>+" in html and "new at your pace" in html
          and " a day &middot; this week 100</div>" in html and "new at your pace, about " in html, html)
    check("board: a stop says what it holds back and when they start again (a real deck: the cost was unsaid)",
          "new cards wait till" not in html, html)  # (3.9.10: only a running stop says it: `paused`, below)
    hv = A.view(A.existing([(1, 10)] * 20, *A.habits([])), A.GENERIC, [20.0] * 7, 0, 900, 100, [50] * 7, exam_in=10,
                plan={2: 50, 20: 30}, pool=100)
    hw = {w["key"]: w for w in hv["ways"]}
    check("ahead: a stop's held cards, a plan's dates in it among them; the pace holds none",
          hw["now"]["held"] == 150 and hw["now"]["plan_held"] == 50 and hw["week"]["plan_held"] == 0
          and "held" not in hw["pace"], {k: (w.get("held"), w.get("plan_held")) for k, w in hw.items()})
    hh = board._ins_ahead(10, dict(_ahead_sample(exam_in=10), ways=hv["ways"]), "Step")
    check("board: a plan's share of what waits (the day with its month)",
          "insaheadoff" not in hh and "plan&rsquo;s sets" not in hh, hh)  # (3.9.10: no stop is offered to say it of)
    check("ahead: new cards named the climb's cause only when they're it (200 in two weeks, twice the two before)",
          A.cause(2480, 262) == 2480 and A.cause(150, 0) == 0 and A.cause(500, 300) == 0 and A.cause(None, None) == 0)
    ln = board.ahead_line({"did": 1, "name": "Step", "day": "2026-10-19", "n": 1030, "week": 780, "cause": 2480})
    check("board: the line says the cause", "this week 780 &middot; you started 2,480 cards in 2 weeks</span>" in ln
          and "you started" not in board.ahead_line({"did": 1, "name": "Step", "day": "2026-10-19", "n": 1030, "week": 780}), ln)
    check("board: Do it for each stop, said once; deck options untouched (its tip); the deck's name escaped",
          "duecrew:insaheadoff" not in html and ">Do it<" not in html and "<b>Spanish" not in html, html)
    check("board: the track record, and each bar's band from it", "within 9% a week" not in html and "&ndash;" in html)
    check("board: the exam on its day; the last 7 days, today, then by week", ">Exam<" in html and ">today<" in html
          and ">by week<" in html and "Week of " in html, html)
    paused = board._ins_ahead(10, _ahead_sample(exam_in=10, off=(0, 10)), "Spanish")
    check("board: paused: its way on, Turn new cards back on in Do it's place",
          'class="ahw" data-k="now"' in paused and paused.count('class="ahw"') == 1 and "new cards wait till" in paused
          and "insaheadon" not in paused
          and "duecrew:insaheadon:10" in board.settings_html({"tab": "study", "signed_in": True, "new_stops": [(10, "Sp<i>")]}, {})
          and "New cards stopped in Sp&lt;i&gt;" in board.settings_html({"tab": "study", "signed_in": True, "new_stops": [(10, "Sp<i>")]}, {})
          and "New cards stopped" not in board.settings_html({"tab": "study", "signed_in": True}, {})
          and "duecrew:insaheadoff:10:now" not in paused and "No new cards in Spanish till your exam" in paused, paused[-2500:])
    generic = board._ins_ahead(10, dict(_ahead_sample(), own=False, trust=None), "Spanish")
    check("board: no exam: stop for good; a typical curve said; no track record yet",
          "insaheadoff" not in generic and "typical curve" not in generic and "within" not in generic, generic[-1500:])
    rh = board.render({"entries": [], "labels": ["2026-09-01"], "tomorrow": "", "pending": []}, {}, 0, ahead={"did": 10, "name": "<i>Spanish", "day": "2026-09-08", "n": 330, "week": 250})
    check("board: the line when reviews climb, the deck escaped, to Insights, put away for a week",
          "Reviews in <b>&lt;i&gt;Spanish</b> climb to about <b>330</b> a day by Tue 8 Sep &middot; this week 250" in rh
          and "about <b>1,030</b> a day" in board.ahead_line({"did": 1, "name": "x", "day": "2026-10-19", "n": 1026.4, "week": 780})
          and "duecrew:youins:10" in rh and "duecrew:insaheadx:10" in rh, rh[:3000])
    # ---- the glue, on a collection ----
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    sday = 1000
    ts = lambda day: (cut + (day - 1) * 86400 + 3600) * 1000  # noqa: E731
    conn.executemany("INSERT INTO revlog (id, ease, time, type, cid, lastIvl, ivl) VALUES (?,?,?,?,?,?,?)",
                     [(ts(d) + n, e, 6000, ty, c, li, i) for n, (d, c, e, i, li, ty) in enumerate(rows)])  # its 200 days
    for c, (due, ivl) in now.items():
        fakes.add_card(conn, c, did=10, ctype=2, queue=2, ivl=ivl, due=sday + due)
    for k in range(400):
        fakes.add_card(conn, 90000 + k, did=11, queue=0)  # unlocked, waiting
    fd = next(c for c, (due, _i) in now.items() if due == 5)
    conn.execute("UPDATE cards SET odid = 10, did = 99, due = -100000, odue = ? WHERE id = ?", (sday + 5, fd))
    col = fakes.FakeCol(conn, cut)
    store = {10: {"id": 10, "name": "Spanish", "dyn": 0}, 11: {"id": 11, "name": "Spanish::Verbs", "dyn": 0}}

    class Decks(fakes.FakeDecks):
        def get(self, did, default=True):
            return store.get(did, False)

        def save(self, deck):
            store[deck["id"]] = deck
    col.decks = Decks({10: "Spanish", 11: "Spanish::Verbs"})
    pc, conf = {}, {"exam_date": _day(10)}
    saved = (F._today, F._pcfg, F._psave, F._after_change, F.apply_catch, mw.col, AF.cfg, AF.app.swap, AF.tooltip, AF._bg,
             _state.get("ahead_day"), _state.get("ahead_line"), _state.get("ahead_asked"))
    said, bg = [], []
    try:
        F._today = lambda: _day(0)
        F._pcfg = lambda: pc
        F._psave = lambda d: None
        F._after_change = lambda: None
        F.apply_catch = lambda: None
        mw.col = col
        AF.cfg = lambda: conf
        AF.app.swap = lambda c=None: None
        AF.tooltip = lambda m, **k: said.append(m)
        AF._bg = lambda job, done=None: bg.append((job, done))
        _state["ahead_day"], _state["ahead_line"], _state["ahead_asked"] = {}, None, set()
        v = AF.deck_view(col, 10, TF._deck_sql(col, 10), _day(10))
        check("glue: a deck's view: my curve, my pace, the deck's new cards, the exam in 10 days, today's count",
              v is not None and v["own"] and round(v["rate"]) == 210 and v["unlocked"] == 400 and v["left"] == 400
              and v["exam"] == 10 and [w["key"] for w in v["ways"]] == ["pace", "week", "now"] and len(v["days"]) == 7 + A.H
              and v["days"][7] == _day(0), v and (v["rate"], v["unlocked"], v["exam"]))
        st_now = AF._state_now(col, TF._deck_sql(col, 10), sday)
        check("glue: a card in a filtered deck is due on its own day (odue), not today (the 3.8 Your week bug)",
              (5, now[fd][1]) in st_now and len(st_now) == len(now), [x for x in st_now if x[0] < 0][:3])
        check("glue: the track record is worked out off the main thread, once a session a deck; none to show yet",
              len(bg) == 1 and v["trust"] is None)
        job, done = bg[0]
        done(job())
        tr = (pc.get("ahead_trust") or {}).get("10") or {}
        check("glue: and kept in plans.json for a week", tr.get("day") == _day(0) and len(tr.get("by") or []) == 6
              and tr["err"] < 0.15, tr)
        _state["ahead_day"] = {}
        v2 = AF.deck_view(col, 10, TF._deck_sql(col, 10), _day(10))
        check("glue: then the view has it", v2["trust"] and abs(v2["trust"][0] - tr["err"]) < 1e-9 and len(bg) == 1)
        col.v3_scheduler = lambda: False
        _state["ahead_day"] = {}
        old = AF.deck_view(col, 10, TF._deck_sql(col, 10), _day(10))
        AF.stop_new(10, "now")
        del col.v3_scheduler
        check("glue: on Anki's old v2 scheduler (no today-only limit) no stop is offered, and Do it does nothing",
              [w["key"] for w in old["ways"]] == ["pace"] and not pc.get("new_off"), [w["key"] for w in old["ways"]])
        # Do it: no new cards now, to the exam
        dc._on_js(False, as_board("duecrew:insaheadoff:10:now"), DeckBrowser())
        lim = lambda d: store[d].get("newLimitToday")  # noqa: E731
        check("glue: Do it: today's new cards 0 on the deck and its subdecks (Anki's today-only limit), said once",
              pc["new_off"] == {"10": {"kind": "now", "at": _day(0), "exam": True}}
              and lim(10) == {"limit": 0, "today": sday} and lim(11) == {"limit": 0, "today": sday}
              and said[-1].startswith("No new cards in Spanish till your exam"), (pc.get("new_off"), store))
        check("glue: the deck and its subdeck in one undo step (3.9.2's audit: a step a deck)",
              col.undo_steps[-1][0] == "Due Crew: new cards stopped", col.undo_steps[-3:])
        n_steps = len(col.undo_steps)
        AF.apply_morning()
        AF.on_state("overview", "deckBrowser")
        check("glue: set again with nothing to change: no step, and no empty one", len(col.undo_steps) == n_steps)
        check("glue: paused here and in the subdeck (a plan's Raise and Catch up, and Why, stand aside)",
              AF.paused(col, 11) == (10, pc["new_off"]["10"]) and AF.paused(col, 10)[0] == 10 and F._paused(col, 11) == 10)
        _state["ahead_day"] = {}
        v3 = AF.deck_view(col, 10, TF._deck_sql(col, 10), _day(10))
        check("glue: the view says it's on, and what the pause is (its own words)",
              v3["on"] == "now" and v3["off"] is True and v3["pause"] == {"kind": "now", "exam": True, "from": 0})
        col.sched.today = sday + 1
        store[10].pop("newLimitToday")
        store[11].pop("newLimitToday")
        check("glue: each morning sets it again while it runs", AF.apply_morning() and lim(10) == {"limit": 0, "today": sday + 1})
        store[10].pop("newLimitToday")
        store[11].pop("newLimitToday")
        AF.on_state("review", "overview")
        check("glue: and before I study, when the morning hasn't (not signed in, waiting for AnkiWeb)",
              lim(10) == {"limit": 0, "today": sday + 1} and lim(11) == {"limit": 0, "today": sday + 1})
        refreshed, caught, sv_rp = [], [], F.refresh_progress
        F.refresh_progress = lambda: refreshed.append(1)
        F.apply_catch = lambda: caught.append(1)
        try:
            dc._on_js(False, as_board("duecrew:insaheadon:10"), DeckBrowser())
            check("glue: Turn back on: the pause gone, today's 0 off", pc["new_off"] == {} and lim(10) is None and lim(11) is None, store)
            check("QoL pass: Turn back on says so, the catch-up's limit back in its one undo step, the plan card worked out again",
                  said[-1] == "New cards back on in Spanish." and caught and col.undo_steps[-1][0] == "Due Crew: new cards back on"
                  and refreshed, (said[-1:], caught, col.undo_steps[-1:], refreshed))
            # the exam cleared (or moved) while a stop to it ran: today's 0 comes off now, not at tomorrow's rollover
            dc._on_js(False, as_board("duecrew:insaheadoff:10:now"), DeckBrowser())
            caught.clear()
            keep_exam, conf["exam_date"] = conf["exam_date"], ""
            AF.exam_moved()
            check("QoL pass: the exam cleared under a stop to it: the stop's over and today's 0 off at once, the catch-up's back",
                  pc["new_off"] == {} and lim(10) is None and lim(11) is None and caught, (pc.get("new_off"), store))
            conf["exam_date"] = keep_exam
            moved, sv_em, sv = [], AF.exam_moved, (dc.save_cfg, dc._swap, dc.cfg)
            fake = {"exam_date": ""}
            AF.exam_moved = lambda: moved.append(1)
            dc.save_cfg, dc._swap, dc.cfg = (lambda c: None), (lambda c=None, **k: None), (lambda: fake)
            try:
                dc._apply_settings({"exam_date": "2030-01-02"})
                dc._apply_settings({"exam_date": "2030-01-02"})
                dc._apply_settings({"exam_date": ""})
            finally:
                AF.exam_moved = sv_em
                dc.save_cfg, dc._swap, dc.cfg = sv
            check("QoL pass: Settings tells the pause when my exam changes (not when it's set to what it was)", len(moved) == 2, moved)
        finally:
            F.refresh_progress, F.apply_catch = sv_rp, (lambda: None)
        dc._on_js(False, as_board("duecrew:insaheadoff:10:week"), DeckBrowser())
        check("glue: a week before: nothing today, the days kept", lim(10) is None and pc["new_off"]["10"]["kind"] == "week"
              and "from " in said[-1], said[-1])
        conf["exam_date"] = _day(-1)
        AF.apply_morning()
        check("glue: once the exam's past, the pause is forgotten", pc["new_off"] == {}, pc.get("new_off"))
        conf["exam_date"] = _day(10)
        dc._on_js(False, as_board("duecrew:insaheadoff:10:bogus"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:insaheadoff:x:now"), DeckBrowser())
        check("glue: a stop it doesn't know, or no deck, does nothing", pc["new_off"] == {})
        dc._on_js(False, as_board("duecrew:insaheadx:10"), DeckBrowser())
        check("glue: the line put away for this deck", pc["ahead_line_x"] == {"10": _day(0)})
        _state["ahead_line"] = {"day": _day(0), "line": {"did": 10, "name": "Spanish", "day": _day(5), "n": 330, "week": 250}}
        check("glue: put away, the line stays away a week", AF.board_line(conf) is None)
        pc["ahead_line_x"] = {"10": _day(-8)}
        check("glue: after a week it's back", (AF.board_line(conf) or {}).get("n") == 330)
    finally:
        (F._today, F._pcfg, F._psave, F._after_change, F.apply_catch, mw.col, AF.cfg, AF.app.swap, AF.tooltip, AF._bg,
         _state["ahead_day"], _state["ahead_line"], _state["ahead_asked"]) = saved


def test_ahead_audit_v392():
    """3.9.2's audit, before release: Stop new's words come from the pause I
    made (its kind, its exam), not from whether there's an exam date now;
    an exam today or passed is no exam ahead; one far off is named; a stop
    that holds nothing back isn't offered; the track record caps a week I
    took off; today's bar counts a card still in its steps once."""
    from due_crew import ahead as A, board
    keys = lambda e: [k for k, _s in A.choices(e, [20.0] * 7, 300, 500)]  # noqa: E731
    check("choices: an exam today or passed is none ahead: stop now till I turn them back on",
          keys(0) == ["pace", "now"] and dict(A.choices(0, [20.0] * 7, 300, 500))["now"] == (0, A.H)
          and keys(-3) == ["pace", "now"] and keys(10) == ["pace", "week", "now"] and keys(5) == ["pace", "now"])
    res = [([2.0] * 6, [300.0] * 6), ([100.0] * 6, [110.0] * 6)]
    tr = A.trust(res)
    check("track record: a week off is a whole miss, never 400% of one", tr and all(e <= 1.0 for e in tr[1]) and tr[0] <= 1.0, tr)
    sample = _ahead_sample
    exam_today = board._ins_ahead(10, sample(exam_in=0), "Spanish")
    passed = board._ins_ahead(10, sample(exam_in=-4), "Spanish")
    far = board._ins_ahead(10, sample(exam_in=60, off=(0, 60), pause={"kind": "now", "exam": True, "from": 0}), "Spanish")
    later = board._ins_ahead(10, sample(exam_in=10, off=(0, 10), pause={"kind": "now", "exam": False, "from": 0}), "Spanish")
    week = board._ins_ahead(10, sample(exam_in=10, off=(3, 10), pause={"kind": "week", "exam": True, "from": 3}), "Spanish")
    check("board: an exam today: Stop new now, till I turn them back on (never 'to the exam')",
          "to the exam" not in exam_today and "insaheadoff" not in exam_today, exam_today[-1800:])
    check("board: an exam passed: the same", "to the exam" not in passed and "till your exam" not in passed, passed[-1800:])
    check("board: paused to an exam six weeks off: its date named, one pill for it",
          "till your exam, Sat 31 Oct" in far and far.count('class="ahw"') == 1 and 'role="radio"' not in far, far[-1800:])
    check("board: a pause made with no exam, an exam added since: still till I turn them back on",
          "No new cards in Spanish till you turn them back on" in later, later[-1500:])
    check("board: the week before the exam, before it starts: from its first day",
          "No new cards in Spanish from Fri 4 Sep till your exam, Fri 11 Sep" in week, week[-1500:])
    fin = A.view(A.existing([(d, 10) for d in range(1, 14) for _ in range(20)], *A.habits([])), A.GENERIC, [0.0] * 7, 0, 0, 0,
                 [100] * 7, exam_in=20)
    check("a finished deck (no new cards left): no stop offered, it changes nothing", [w["key"] for w in fin["ways"]] == ["pace"],
          [w["key"] for w in fin["ways"]])
    one = sample(exam_in=10, off=(0, 10), pause={"kind": "now", "exam": True, "from": 0})
    check("words: one card, one new card", "1 new card waits" in board._ins_ahead(10, dict(one, ways=[
        dict(w, held=1) if w["key"] == one["on"] else w for w in one["ways"]]), "Spanish"))


def test_builder_audit_v392():
    """3.9.2's audit of the builder: Copy for next year copies the plan as
    saved, so it waits for a save and takes its first date from the saved
    plan as it is now (an unsaved earlier date made the shift 361 days and
    the weekdays slipped); a full account says so; the reviews line's
    busiest week is one its list shows, and a cut list says so."""
    js = open(os.path.join(os.path.dirname(os.path.abspath(SUITE_FILE)), "..", "site", "public", "builder.js"), encoding="utf-8").read()
    i = js.index("function nextYear()")
    ny = js[i:js.index("Copy for next year\");", i)]
    check("Copy for next year: a save first; the saved plan's first date, 364 days on; plans_full said",
          "if (dirty) {" in ny and "Save your changes first" in ny and 'await api("GET", `/plans/${plan.id}`)' in ny
          and "addDays(saved, 364)" in ny and '"plans_full"' in ny, ny[:600])
    import subprocess
    named = ny[ny.index("function named(n) {"):ny.index("\n    }", ny.index("function named(n) {")) + 6]
    long_ = "Pharm for second years with Dr. Lopez and the whole M2s team"
    out = subprocess.run(["node", "-e", named + "; console.log(JSON.stringify([named('Pharm block'), named('x'.repeat(70)), "
                          "named('Pharm block (next year)'), named('Cardio (copy)'), named(" + json.dumps(long_) + ")]))"],
                         capture_output=True, text=True, timeout=30)
    got = json.loads(out.stdout or "null") or []
    check("Copy for next year: named \"… (next year)\" within a name's 60; never twice, never \"(copy) (next year)\", cut at a word",
          got[:4] == ["Pharm block (next year)", "x" * 48 + " (next year)", "Pharm block (next year)", "Cardio (next year)"]
          and all(len(x) <= 60 for x in got) and got[4] == "Pharm for second years with Dr. Lopez and the (next year)"
          and "PUT\", `/plans/${mine.id}`" in ny and "name: named(got.name || plan.name)" in ny and "go(`/plans/${mine.id}`)" in ny
          and "The saved plan has no sets to copy." in ny and "That didn't copy: check your connection" in ny,
          (got, out.stderr[-300:]))
    rev = js[js.index("const Reviews = (() => {"):js.index("})();", js.index("const Reviews = (() => {")) + 5]
    wk = js[js.index("function weekly(ws) {"):js.index("\n  }", js.index("function weekly(ws) {")) + 4]
    out = subprocess.run(["node", "-e", "const addDays = (d) => d; " + rev + "\n" + wk + "\nconsole.log(JSON.stringify(weekly("
                          + json.dumps([{"n": x} for x in (26, 60, 3, 0.2, 0, 0, 0, 30, 0.4, 0)]) + ")))"],
                         capture_output=True, text=True, timeout=30)
    check("the reviews line: a break between a plan's parts says so, its tail's zeros go (3.9.2's QoL pass)",
          json.loads(out.stdout or "null") == ["26", "60", "3", "0 for 4 weeks", "30"], (out.stdout, out.stderr[-300:]))
    i = js.index("function reviewsNote()")
    rn = js[i:js.index("function sugRows", i)]
    check("the reviews line: its busiest week among the 16 it lists, a longer plan's list marked as cut",
          "const ws = all.slice(0, 16);" in rn and "Reviews.peak(ws)" in rn and '" · …"' in rn, rn)


def test_leeches_392():
    """3.9.2 (Sam's picks S1-A, S2-A): the cards Anki stopped showing me and
    the ones a miss from it, a view in Insights' place: one button a card
    (a crewmate's tip when one has it down, else Ask them, else Bring
    back), Learn it fresh, Edit and Leave it out behind ⋯, Bring all back
    and Browse on top, sorted by danger. Bring back keeps the schedule (the
    leech tag off); Learn it fresh is Anki's Reset; each one undo step."""
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    from due_crew import leech_flow as LF, plan_flow as F, team_flow as TF, board
    from due_crew.app import _state
    check("leech: one more miss makes a leech at 8, then every 4 after; not between",
          LF.next_is_leech(7, 8) and not LF.next_is_leech(8, 8) and LF.next_is_leech(11, 8) and not LF.next_is_leech(9, 8)
          and LF.next_is_leech(3, 4) and LF.next_is_leech(4, 4, 1))
    check("leech: a front as one line, a cloze's answer hidden, tags and sounds out",
          LF.front("<b>ojalá</b> que {{c1::tenga::tener}} [sound:x.mp3] &amp; más") == "ojalá que [tener] & más"
          and LF.front("{{c2::Warfarin}} inhibits VKOR") == "[…] inhibits VKOR" and len(LF.front("x" * 200)) == LF.FRONT_MAX)
    check("leech: its topic, the last part of its longest tag, never leech or marked",
          LF.topic(" leech Big::#Videos::Renal::Acid_base marked ") == "Acid base" and LF.topic("leech") == "")
    gone, near = LF.order([{"lapses": 8, "at": 5}, {"lapses": 12, "at": 1}, {"lapses": 8, "at": 9, "exam": True}],
                          [{"lapses": 7, "due": 3}, {"lapses": 11, "due": 1}])
    check("leech: danger first: on my exam, most missed, latest; near: due soonest",
          [(c["lapses"], c.get("exam", False)) for c in gone] == [(8, True), (12, False), (8, False)]
          and [c["due"] for c in near] == [1, 3])
    # ---- on a collection ----
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    at = lambda days: (cut - days * 86400 - 3600) * 1000  # noqa: E731
    rows = [(101, -1, 10, "estar listo vs ser listo", "Spanish::Ser_vs_estar leech", 3),
            (102, -1, 8, "La fiesta ____ en mi casa", "Spanish::Ser_vs_estar leech", 9),
            (103, -1, 9, "fui / fue / fuimos", "Spanish::Preterite leech", 20),
            (104, 2, 7, "ojalá que yo {{c1::tenga}}", "Spanish::Subjunctive", 1),
            (105, 2, 11, "quisiera = ?", "Spanish::Subjunctive leech", 4),
            (106, 2, 9, "hubiera vs hubiese", "Spanish::Subjunctive", 2)]
    for cid, queue, lapses, sf, tags, ago in rows:
        fakes.add_card(conn, cid, did=10, ctype=2, queue=queue, ivl=3, tags=tags, due=1000 + 3, lapses=lapses)
        conn.execute("UPDATE notes SET sfld = ? WHERE id = ?", (sf, cid))
        fakes.add_review(conn, at(40), ease=3, cid=cid, rtype=0, time_ms=44000 if cid == 103 else 8000)
        fakes.add_review(conn, at(ago), ease=1, cid=cid, time_ms=44000 if cid == 103 else 8000)
    # a real deck: Anki tags the note; a sibling the shared deck ships suspended, never answered, isn't a leech
    fakes.add_card(conn, 107, did=10, ctype=0, queue=-1, tags="Spanish::Ser_vs_estar leech", lapses=0)
    col = fakes.FakeCol(conn, cut)
    col.decks = fakes.FakeDecks({10: "Spanish"})
    col.get_card = lambda cid: types.SimpleNamespace(id=cid, odid=0, did=10, note=lambda: types.SimpleNamespace(
        guid=f"guid{cid:06d}", fields=[dict((r[0], r[3]) for r in rows)[cid]]))
    pc, said, shown, sheets_asked = {}, [], [], []
    saved = (F._pcfg, F._psave, F._after_change, F._browse, mw.col, LF.tooltip, LF.app.swap, LF.app.sync, _state.get("entries"),
             _state.get("leech_view"), _state.get("leech_open"), dict(LF.app.client().session.get("cards") or {}))
    from due_crew import sheets
    sv_sheet = (sheets.confirm, sheets.ask_text)
    try:
        F._pcfg = lambda: pc
        F._psave = lambda d: None
        F._after_change = lambda: None
        F._browse = lambda cids, q=None, empty="": shown.append(sorted(cids))
        mw.col = col
        LF.tooltip = lambda m, **k: said.append(m)
        LF.app.swap = lambda c=None: None
        LF.app.sync = lambda **k: None
        sheets.confirm = lambda title, text, yes, then, **k: sheets_asked.append((title, text, yes)) or then()
        sheets.ask_text = lambda title, text, then, **k: sheets_asked.append((title, text)) or then("why ser?")
        _state["entries"] = [{"user_id": "dre", "name": "Dre K", "you": False}, {"user_id": "maya", "name": "Maya", "you": False}]
        LF.app.client().session["cards"] = {"guid000102": {"tips": [{"from": "dre", "text": "fiesta takes ser: it's an event"}]},
                                            "guid000103": {"knows": ["maya"]}}
        _state["leech_view"], _state["leech_open"] = {}, {}
        deck = TF._deck_sql(col, 10)
        check("glue: counts for Insights' line: 3 suspended leeches, 2 a miss away (7 and 11 lapses, not 9)",
              LF.counts(col, deck) == (3, 2, 0), LF.counts(col, deck))
        dc._on_js(False, as_board("duecrew:insleeches:10"), DeckBrowser())
        v = LF.current(col, 10, deck)
        check("glue: See them opens the view in Insights' place", LF.is_open(10) and v["n_gone"] == 3 and v["n_near"] == 2)
        g = {c["cid"]: c for c in v["gone"]}
        check("glue: each card's front, topic, misses, slowness, the crew's tip or who has it down",
              g[102]["tip"] == [{"name": "Dre", "text": "fiesta takes ser: it's an event"}] and g[103]["knows"] == ["Maya"]
              and g[103]["secs"] == 44 and g[101]["topic"] == "Ser vs estar" and g[101]["front"] == "estar listo vs ser listo"
              and [c["cid"] for c in v["gone"]] == [101, 103, 102] and [c["cid"] for c in v["near"]] == [105, 104], v)
        html = board._insights_html(10, {"leech": v, "deck_name": "<i>Spanish"})
        check("board: the trail back, the counts, Bring all back and Browse; the deck's name escaped",
              "duecrew:insleech:10:shut:0" in html and "<b>3</b> Anki stopped showing you" in html and "<b>2</b> one miss away" in html
              and "Bring all" not in html and "insleech:10:back" not in html and "duecrew:insleech:10:browse:0" in html
              and "&lt;i&gt;Spanish" in html and "<i>Spanish" not in html, html[:1500])
        check("board: one button a card: the tip, else Ask who has it down, else Bring back; a near card's is a tip or nothing",
              "duecrew:insleech:10:tip:102" in html and "Dre&rsquo;s tip" in html and "Ask Maya" in html
              and "slow: 44 s a try" in html and "back in 3 days" in html, html)
        check("board: behind ⋯: Learn it fresh, Edit, Leave it out (and Bring back where the button's a tip)",
              not any(f"insleech:10:{a}:" in html for a in ("fresh", "edit", "out", "back")) and "hidden>" not in html
              and "Learn it fresh" not in html, html)  # 3.9.10: Insights is data only: nothing here adjusts a card
        evil = board._ins_leeches(10, {"gone": [dict(g[101], front="<img src=x onerror=1>", topic="<b>")], "near": [], "n_gone": 1, "n_near": 0})
        check("board: a card's own words escaped", "<img" not in evil and "&lt;img" in evil and "<b>&lt;b&gt;" not in evil, evil)
        dc._on_js(False, as_board("duecrew:insleech:10:tip:102"), DeckBrowser())
        q = lambda cid: conn.execute("SELECT queue, lapses, type FROM cards WHERE id = ?", (cid,)).fetchone()  # noqa: E731
        tags = lambda nid: conn.execute("SELECT tags FROM notes WHERE id = ?", (nid,)).fetchone()[0]  # noqa: E731
        was = q(102)
        check("glue: the tip in a sheet, its words alone (3.9.12: Insights is data only, nothing to bring back from here); the card as it was",
              sheets_asked[-1] == ("Dre's tip", "Dre: fiesta takes ser: it's an event", "OK") and q(102) == was and was[0] == -1, (sheets_asked[-1], was))
        LF.bring_back(10, [102])
        check("glue: bring back: unsuspended, schedule kept, the leech tag off, one undo step",
              q(102) == (2, 8, 2)
              and "leech" not in tags(102) and col.undo_steps[-1] == ("Due Crew: bring back", [102]) and said[-1] == "Back in your reviews.",
              (sheets_asked, q(102), col.undo_steps[-1:]))
        dc._on_js(False, as_board("duecrew:insleech:10:ask:103"), DeckBrowser())
        check("glue: Ask Maya: one line, as a card ask (Maya has it down)",
              sheets_asked[-1][0] == "Ask your crew about this card" and "Maya has it down" in sheets_asked[-1][1]
              and any(f["guid"] == "guid000103" for f in LF.app.client().session.get("tricky") or []), sheets_asked[-1])
        dc._on_js(False, as_board("duecrew:insleech:10:fresh:104"), DeckBrowser())
        check("glue: Learn it fresh: a new card, lapses from zero, one undo step", q(104) == (0, 0, 0)
              and col.undo_steps[-1][0] == "Due Crew: learn it fresh" and set(col.undo_steps[-1][1]) == {104}, q(104))
        dc._on_js(False, as_board("duecrew:insleech:10:out:101"), DeckBrowser())
        v2 = LF.current(col, 10, deck)
        check("glue: Leave it out: still suspended, out of the list and the count", q(101)[0] == -1 and pc["leech_out"] == [101]
              and [c["cid"] for c in v2["gone"]] == [103] and LF.counts(col, deck) == (1, 1, 0), v2)
        dc._on_js(False, as_board("duecrew:insleech:10:back:all"), DeckBrowser())
        check("glue: Bring all back: every one listed, one step", q(103)[0] == 2 and q(101)[0] == -1
              and col.undo_steps[-1] == ("Due Crew: bring back", [103]))
        dc._on_js(False, as_board("duecrew:insleech:10:edit:105"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:insleech:10:browse:0"), DeckBrowser())
        check("glue: Edit opens that card in Browse; Browse, all of them", shown[0] == [105] and shown[1] == [105], shown)
        n = len(col.undo_steps)
        for bad in ("insleech:10:back:999", "insleech:10:fresh:abc", "insleech:10:nope:105", "insleech:x:back:105"):
            dc._on_js(False, as_board("duecrew:" + bad), DeckBrowser())
        check("glue: a card not in the view, or a step it doesn't know, does nothing", len(col.undo_steps) == n)
        dc._on_js(False, as_board("duecrew:insleech:10:shut:0"), DeckBrowser())
        check("glue: Insights › takes the view away", not LF.is_open(10))
        line = board._insights_html(10, {"leeches": 3, "near": 2})
        check("board: Insights' line: suspended and one miss away, See them",
              "<b>3</b> leeches Anki stopped showing you &middot; <b>2</b> one miss away" in line and "duecrew:insleeches:10" in line, line)
    finally:
        (F._pcfg, F._psave, F._after_change, F._browse, mw.col, LF.tooltip, LF.app.swap, LF.app.sync, _state["entries"],
         _state["leech_view"], _state["leech_open"], sess) = saved
        LF.app.client().session["cards"] = sess
        LF.app.client().session["tricky"] = []
        sheets.confirm, sheets.ask_text = sv_sheet


def test_leeches_audit_v392():
    """3.9.2's audit, before release: Anki's half of the threshold is
    rounded up (at 5: 5, 8, 11); a note's other card still a leech keeps
    the note's tag when one comes back; the view is worked out again when
    the collection changed (a review, Browse, an undo); a card deleted since
    is no error; Leave it out has its way back on the same screen; a
    relearning card isn't a miss away (another miss adds no lapse)."""
    import due_crew as dc
    from aqt import mw
    from aqt.deckbrowser import DeckBrowser
    from due_crew import leech_flow as LF, plan_flow as F, team_flow as TF, board
    from due_crew.app import _state
    near_at = lambda fails: [n for n in range(0, 16) if LF.next_is_leech(n, fails)]  # noqa: E731
    check("leech: a miss away at Anki's own steps: 5 → 4, 7, 10, 13; 7 → 6, 10, 14; 3 → 2, 4, 6; 8 → 7, 11, 15; 1 → every one",
          near_at(5) == [4, 7, 10, 13] and near_at(7) == [6, 10, 14] and near_at(3)[:3] == [2, 4, 6]
          and near_at(8) == [7, 11, 15] and near_at(1) == list(range(16)), (near_at(5), near_at(7), near_at(3)))
    cut = int(datetime.datetime(2026, 10, 19, 4, 0).timestamp())  # rollover at 4: today's Anki day is 18 Oct
    ms = lambda d, h, m=0: int(datetime.datetime(2026, 10, d, h, m).timestamp() * 1000)  # noqa: E731
    check("leech: its last day is my Anki day: 1:30 after midnight is still the day before; 3:59 too; 4:00 a new one",
          (LF.anki_day(ms(19, 1, 30), cut), LF.anki_day(ms(18, 5), cut), LF.anki_day(ms(18, 3, 59), cut), LF.anki_day(ms(18, 4), cut))
          == ("2026-10-18", "2026-10-18", "2026-10-17", "2026-10-18") and LF.anki_day(0, cut) == "",
          (LF.anki_day(ms(19, 1, 30), cut), LF.anki_day(ms(18, 3, 59), cut)))
    conn = sqlite3.connect(":memory:")
    fakes.make_collection(conn)
    cut = fakes.day_cutoff_for(TODAY)
    fakes.add_card(conn, 201, did=10, ctype=2, queue=-1, ivl=3, tags="Bio::Cells leech", lapses=8)
    fakes.add_card(conn, 202, did=10, ctype=2, queue=-1, ivl=3, nid=201, ord_=1, lapses=9)  # its reversed card, a leech too
    fakes.add_card(conn, 203, did=10, ctype=2, queue=-1, ivl=3, tags="Bio::Krebs leech", lapses=8)
    fakes.add_card(conn, 204, did=10, ctype=3, queue=1, ivl=1, tags="Bio::Krebs", lapses=7)  # relearning: not a miss away
    for cid in (201, 202, 203, 204):
        fakes.add_review(conn, (cut - 3 * 86400) * 1000 + cid, ease=1, cid=cid)
    col = fakes.FakeCol(conn, cut)
    col.decks = fakes.FakeDecks({10: "Bio"})
    col.mod = 1
    deleted = set()

    def get_card(cid):
        if cid in deleted:
            raise KeyError(cid)
        return types.SimpleNamespace(id=cid, odid=0, did=10, note=lambda: types.SimpleNamespace(guid=f"guid{cid:06d}", fields=["x"]))
    col.get_card = get_card
    pc, said, asked = {}, [], []
    saved = (F._pcfg, F._psave, F._after_change, mw.col, LF.tooltip, LF.app.swap, _state.get("leech_view"), _state.get("leech_open"))
    from due_crew import sheets
    sv_ask = sheets.ask_text
    try:
        F._pcfg, F._psave, F._after_change = (lambda: pc), (lambda d: None), (lambda: None)
        mw.col = col
        LF.tooltip = lambda m, **k: said.append(m)
        LF.app.swap = lambda c=None: None
        sheets.ask_text = lambda *a, **k: asked.append(a)
        _state["leech_view"], _state["leech_open"] = {}, {}
        deck = TF._deck_sql(col, 10)
        tags = lambda nid: conn.execute("SELECT tags FROM notes WHERE id = ?", (nid,)).fetchone()[0]  # noqa: E731
        q = lambda cid: conn.execute("SELECT queue FROM cards WHERE id = ?", (cid,)).fetchone()[0]  # noqa: E731
        v = LF.current(col, 10, deck)
        check("leech: the reversed card is a leech of its own; a relearning card isn't a miss away",
              sorted(c["cid"] for c in v["gone"]) == [201, 202, 203] and v["near"] == [], v)
        dc._on_js(False, as_board("duecrew:insleech:10:back:201"), DeckBrowser())
        check("bring back one card of a note whose other card is still a leech: the note keeps its tag, the other stays listed",
              q(201) == 2 and q(202) == -1 and "leech" in tags(201)
              and [c["cid"] for c in LF.current(col, 10, deck)["gone"]] == [202, 203] or [c["cid"] for c in LF.current(col, 10, deck)["gone"]] == [203, 202],
              (tags(201), LF.current(col, 10, deck)))
        dc._on_js(False, as_board("duecrew:insleech:10:back:202"), DeckBrowser())
        check("…and when the last of them comes back, the tag comes off", q(202) == 2 and "leech" not in tags(201))
        # the collection changed under the view (a review suspended 204 as a leech): worked out again
        LF.current(col, 10, deck)
        conn.execute("UPDATE cards SET queue = -1, lapses = 8, type = 2 WHERE id = 204")
        conn.execute("UPDATE notes SET tags = ' Bio::Krebs leech ' WHERE id = 204")
        stale = [c["cid"] for c in LF.current(col, 10, deck)["gone"]]
        col.mod = 2
        fresh = [c["cid"] for c in LF.current(col, 10, deck)["gone"]]
        check("the view is worked out again when the collection changed (col.mod), not before",
              204 not in stale and 204 in fresh, (stale, fresh))
        # a card deleted since the view was drawn (Edit opened Browse): Ask, Bring back do nothing, no error
        deleted.add(203)
        conn.execute("DELETE FROM cards WHERE id = 203")
        n = len(col.undo_steps)
        dc._on_js(False, as_board("duecrew:insleech:10:ask:203"), DeckBrowser())
        LF.bring_back(10, [203])
        check("a card deleted since: Ask and Bring back do nothing, no error, no empty undo step",
              not asked and len(col.undo_steps) == n, col.undo_steps[n:])
        col.mod = 3
        dc._on_js(False, as_board("duecrew:insleech:10:out:204"), DeckBrowser())
        v = LF.current(col, 10, deck)
        html = board._ins_leeches(10, v)
        check("Leave it out: out of the list, and its way back at the foot of it",
              pc["leech_out"] == [204] and v["gone"] == [] and v["out"] == 1 and "1 left out of this list" in html
              and "duecrew:insleech:10:unout:0" in html and "Put it back" in html and "foot of this list" in said[-1], html)
        dc._on_js(False, as_board("duecrew:insleech:10:unout:0"), DeckBrowser())
        v = LF.current(col, 10, deck)
        check("Put it back: in the list again", pc["leech_out"] == [] and [c["cid"] for c in v["gone"]] == [204] and not v["out"])
    finally:
        F._pcfg, F._psave, F._after_change, mw.col, LF.tooltip, LF.app.swap, _state["leech_view"], _state["leech_open"] = saved
        sheets.ask_text = sv_ask


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("n", "t")
n = t = None
