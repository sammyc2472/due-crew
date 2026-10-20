"""3.8.0, "Board in Motion" (both rounds): each motion on the real board, to look at.
Draws a board, then swaps in the board after a change, as the add-on
does (board.swap_js), so motion.js moves what changed.

    python3 tools/motion_preview.py   # writes tools/motion_preview.html

Open it in a browser, pick one, Play. With the system's Reduce motion on,
nothing moves: that's the point of the check."""
import copy, html, json, os, sys, io, contextlib
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools")); sys.path.insert(0, os.path.join(REPO, "tests")); sys.path.insert(0, REPO)
with contextlib.redirect_stdout(io.StringIO()):
    import preview as PV
from due_crew import board, due as D

B = board
T, L, now = PV._T, PV.L, PV.now_ts
def R(data=None, cfg=None, ts=None, **kw):
    return B.render(data or PV.DATA, cfg or {"period": "today"}, ts or now - 60, **kw)

items_done = [dict(i, done=PV._T) if i["id"] == "i0002" else i for i in PV._ITEMS]
DV_TICK = D.view(T, PV._DATES, items_done, {}, events=[], reviews={"due": 214, "done": 120})
DV_BASE = D.view(T, PV._DATES, PV._ITEMS, {}, events=[], reviews={"due": 214, "done": 120})
one = [{"id": "z1", "t": "Practice questions", "d": T, "done": "", "at": T}]
DV_LAST = D.view(T, [], one, {}, reviews={"due": 0, "done": 120})
DV_FIN = D.view(T, [], [dict(one[0], done=T)], {}, reviews={"due": 0, "done": 120})
DV_BACK = D.view(T, [], one, {}, reviews={"due": 0, "done": 120, "back": 8, "at": "15:40"})
DV_NOW = D.view(T, [], one, {}, reviews={"due": 8, "done": 120, "back": 0})
you = PV._YOU

def bump(data, name, **kw):
    d = copy.deepcopy(data)
    for e in d["entries"]:
        if e["name"] == name:
            for k, v in kw.items():
                e["days"].setdefault(L[0], {})[k] = v
    return d

def studied(data, name, lb):
    d = copy.deepcopy(data)
    for e in d["entries"]:
        if e["name"] == name:
            e["days"][lb] = {"studied": True, "reviews": 40}
    return d

who = [e["name"] for e in PV.DATA["entries"]]
quiet = next(n for n in who if not any((PV.DATA["entries"][who.index(n)]["days"].get(lb) or {}).get("studied") or
                                       (PV.DATA["entries"][who.index(n)]["days"].get(lb) or {}).get("reviews") for lb in L[1:3]))
S = {
    "tick": (R(due=DV_BASE, you=you("today")), R(due=DV_TICK, you=you("today")), None),
    "done": (R(due=DV_LAST, you=you("today")), R(due=DV_FIN, you=you("today")), None),
    "learn": (R(due=DV_BACK, you=you("today")), R(due=DV_NOW, you=you("today")), None),
    "fold": (R(due=DV_BASE, you=you("today")), R(due=dict(DV_BASE, folded=True), you=you("today")), None),
    "unfold": (R(due=dict(DV_BASE, folded=True), you=you("today")), R(due=DV_BASE, you=you("today")), None),
    "duetabs": (R(due=DV_BASE, you=you("today")), R(due=dict(DV_BASE, tab="upcoming"), you=you("today")), None),
    "pills": (R(due=DV_BASE, you=you("today")), R({**PV.DATA}, {"period": "squads"}, due=DV_BASE, you=you("today"), squad_view=PV.SQUAD_VIEW), None),
    "views": (R(due=DV_BASE, you=you("today")), R(cfg={"period": "week", "crew_view": "week"}, due=DV_BASE, you=you("today")), None),
    "nums": (R(due=DV_BASE, you=you("today")), R(bump(PV.DATA, "Dre", reviews=742, studyTimeMs=131 * 60000), due=DV_BASE, you=you("today")), None),
    "nothing": (R(due=DV_BASE, you=you("today")), R(due=DV_BASE, you=you("today")), None),
    "squares": (R(PV.DATA_SHOWUP, {"period": "today", "show_up": True}),
                R(studied(PV.DATA_SHOWUP, quiet, L[1]), {"period": "today", "show_up": True}), None),
    "decks": (R(), R(cfg={"period": "decks", "crew_view": "decks"}), None),
    "upd": (R(ts=now - 600), R(ts=now - 2), None),
    "insights": (R(due=DV_BASE, you=you("today")), R(due=DV_BASE, plans=PV.PLANS, you=you("insights", insights=PV._PLAN_INS)), None),
    "map": (R(due=DV_BASE, plans=PV.PLANS, you=you("insights", insights=PV._PLAN_INS)),
            R(due=DV_BASE, plans=PV.PLANS, you=you("insights", insights=dict(PV._PLAN_INS, view=dict(PV._PLAN_INS["view"], map_at=["cardio · physiology"])))),
            "zoom"),
    "add": (R(due=DV_BASE, you=you("today")),
            R(due=D.view(T, PV._DATES, PV._ITEMS + [{"id": "i0099", "t": "Buy colored pens", "d": T, "done": "", "at": T}], {}, events=[], reviews={"due": 214, "done": 120}), you=you("today")),
            "add"),
    "addlater": (R(due=DV_BASE, you=you("today")),
                 R(due=D.view(T, PV._DATES, PV._ITEMS + [{"id": "i0099", "t": "Buy colored pens", "d": "", "done": "", "at": T}], {}, events=[], reviews={"due": 214, "done": 120}), you=you("today")),
                 "addlater"),
    "plans": (R(due=DV_BASE, plans=PV.PLANS, you=you("plans")), None, "day"),
}
# round five, pick A: the day's click again shuts its details; another day's slides them across
_wk = PV.PLAN_CARD["week"]
_on = lambda i: dict(PV.PLANS, cards=[dict(PV.PLAN_CARD, focus=_wk[i]["day"])])  # noqa: E731
S.update({"dayshut": (R(due=DV_BASE, plans=_on(4), you=you("plans", plans=_on(4))), None, "day"),
          "dayswitch": (R(due=DV_BASE, plans=_on(2), you=you("plans", plans=_on(2))), None, "day")})
# round two (each a swap; a profile, a bingo square and the logo are buttons)
from due_crew import room_model  # noqa: E402
ins = lambda **kw: R(due=DV_BASE, plans=PV.PLANS, you=you("insights", insights=dict(PV._PLAN_INS, view=dict(PV._PLAN_INS["view"], **kw))))  # noqa: E731
rows = PV._INS["rows"]
mp = copy.deepcopy(PV._MAP)
mp[1]["know"] = 84
less = dict(PV.DATA, entries=[e for i, e in enumerate(PV.DATA["entries"]) if i != 3])


def roomed(ix):
    ents = [dict(e, room=PV._room) if i in ix or e["you"] else e for i, e in enumerate(PV.DATA["entries"])]
    return R(dict(PV.DATA, entries=ents), room=room_model.board_view(PV._room, ents))


base = R(due=DV_BASE, you=you("today"))
toast = dict(DV_BASE, toast={"text": "Added for Thursday", "tab": "upcoming"})
SETTINGS = B.settings_html(dict(PV.SET_VIEW, tab="you"), PV.SET_CFG)
S.update({
    "settings": (base, SETTINGS, None), "setback": (SETTINGS, base, None),
    "sort": (R(cfg={"period": "today", "sort": "reviews"}), R(cfg={"period": "today", "sort": "time"}), None),
    "streak": (R(), R(bump(PV.DATA, "Dre", streak=42)), None),
    "arrive": (R(less), R(), "arrive:" + json.dumps([PV.DATA["entries"][3]["user_id"]])),
    "knockin": (R(), R(knocks=PV.KNOCKS), None), "knockout": (R(knocks=PV.KNOCKS), R(), None),
    "roomjoin": (roomed((1, 2)), roomed((1, 2, 3)), None), "roomleave": (roomed((1, 2, 3)), roomed((1, 2)), None),
    "planweek": (base, R(due=DV_BASE, plans=PV.PLANS, you=you("plans")), None),
    "sticking": (ins(), ins(rows=rows[1:]), None), "sticklast": (ins(rows=rows[:1]), ins(rows=[]), None),
    "shade": (ins(), ins(map=mp), None),
    "caught": (base, R(due=dict(DV_BASE, behind_n=0, behind_plans=[], behind_mine=[]), you=you("today")), None),
    "notein": (base, R(due=toast, you=you("today")), None), "noteout": (R(due=toast, you=you("today")), base, None),
    "studyto": (R(due=dict(DV_BASE, study_to="Pharm"), you=you("today")), R(due=dict(DV_BASE, study_to="Renal"), you=you("today")), None),
})
# 3.8.1: Pip by the logo for a moment (it goes by itself after sev.LOGO_SECONDS), and the session's line
from due_crew import sev as SV
# each of its moves (Sam: "variety!"): a different one each time it comes
S.update({f"sev{k}{'' if m == SV.moves(k)[0] else '.' + m}": (base, R(due=DV_BASE, you=you("today"), sev={"svg": SV.move(k, m), "ago": 0}), None)
          for k in ("hop", "cheer", "exam", "hello") for m in SV.moves(k)})
S.update({f"fifteendone{'' if m == 'stack' else '.' + m}": (base, R(due=DV_BASE, you=you("today"), room={
    "mine": None, "invites": [], "done": None, "fifteen_done": {"n": 3, "minutes": 45, "cards": 212, "walked": False,
                                                                "sev": SV.move("stack", m, stack=3)}}), None)
          for m in SV.moves("stack")})
S.update({f"streak.{m}": (base, R(due=DV_BASE, you=you("today"), milestones=[("dre", "Dre", 100)],
                                  milestone_sev={"dre": SV.move("hop", m, label="Pip: a big streak")}), None)
          for m in SV.moves("hop")})
# 3.9.1: the page has the board's scripts from its load (init_js), so a swap sends their calls alone, as the add-on's do
out = {k: {"a": a, "swap": ((B.swap_js(b) + B.keep_me_in_view_js(scripts=False)) if b else "")
           + (f"dcMotion.arrive({h.split(':', 1)[1]});" if h and h.startswith("arrive:") else ""), "hint": h} for k, (a, b, h) in S.items()}
NAMES = {"tick": "1 A tick you can see (and 2, the bar)", "done": "3 Done for today", "add": "4 A to-do lands (today)",
         "addlater": "4 A to-do lands (another day)", "learn": "5 Learning back, flagged", "fold": "6 Hide", "unfold": "6 Show",
         "duetabs": "7 Tabs: You", "pills": "7 Tabs: Crew to Squads", "views": "7 Tabs: Today to Week",
         "plans": "8 The plan week: a day", "dayshut": "8 The plan week: the day again shuts it",
         "dayswitch": "8 The plan week: another day", "map": "9 The map opens a tile", "nums": "10 Numbers that changed",
         "nothing": "A refresh with nothing new (nothing moves)", "squares": "11 A friend's day fills in",
         "decks": "12 Decks bars grow in", "upd": "14 Refreshing: Updated", "insights": "16 Insights' line draws in",
         "settings": "18 Settings slides in", "setback": "18 Back to the board", "sort": "19 The column you sort by",
         "streak": "20 A streak ticks up", "arrive": "22 A friend arrives", "knockin": "23 A knock slides in",
         "knockout": "23 A knock goes", "roomjoin": "24 Someone joins the room", "roomleave": "24 Someone leaves the room",
         "planweek": "25 A plan week's bars grow in", "sticking": "26 A topic starts sticking",
         "sticklast": "26 The last topic sticks", "shade": "27 A map tile changes shade", "caught": "29 Caught up",
         "notein": "30 A note slides in", "noteout": "30 A note goes", "studyto": "35 Study today names the next deck",
         "sevhop": "Pip: the day's done (a hop, the week's squares fly)", "sevcheer": "Pip: a cheer lands",
         "sevexam": "Pip: exam eve", "sevhello": "Pip: back from away", "fifteendone": "Pip: the session's line (a square a fifteen)",
         "sevhop.twirl": "Pip: the day's done, a twirl", "sevhop.shuffle": "Pip: the day's done, a little dance",
         "sevhop.jump": "Pip: the day's done, a big jump", "sevcheer.hug": "Pip: a cheer lands, hugs the gift",
         "sevcheer.giftspin": "Pip: a cheer lands, spins with it", "sevexam.pep": "Pip: exam eve, a pep fist",
         "sevhello.walkin": "Pip: back from away, walks in", "sevhello.popup": "Pip: back from away, up from below",
         "fifteendone.wobble": "Pip: the session's line, the tower wobbles",
         "fifteendone.catch": "Pip: the session's line, steps under them",
         **{f"streak.{m}": f"Pip: a crewmate's 100-day streak ({m})" for m in SV.moves("hop")}}
END, SAFE = "</", "<" + "\\" + "/"  # a script ends at </; inside one it is written <\\/
init_js = B.keep_me_in_view_js().replace(END, SAFE)
scen_js = json.dumps(out).replace(END, SAFE)
profile_js = json.dumps(PV.profile_js).replace(END, SAFE)
opts = "".join(f'<option value="{k}">{html.escape(NAMES.get(k, k))}</option>' for k in out)
doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Board in Motion, on the board</title>
<style>body{{margin:0;background:#ececE6;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
.bar{{position:sticky;top:0;z-index:99;display:flex;gap:8px;align-items:center;padding:10px 16px;background:#fff;border-bottom:1px solid #ddd}}
#stage{{max-width:900px;margin:16px auto;padding:0 16px}}</style></head><body>
<div class="bar"><select id="pick">{opts}</select><button id="play">Play</button>
<button id="cheer">13 Send Dre a cheer</button><button id="spin">14 Click ↻</button>
<button id="prof">21 + 28 Open Dre</button><button id="logo">The logo does the wave</button>
<span style="color:#777">15, 31 bingo and 17 studying now: see tools/preview.py and the board itself</span></div>
<div id="stage"></div>
<script>window.pycmd = function () {{}};</script>
<script>{init_js}</script>
<script>
var S = {scen_js};
function load(k) {{ document.getElementById('stage').innerHTML = '<center>' + S[k].a + '</center>'; }}
document.getElementById('play').onclick = function () {{
  var k = document.getElementById('pick').value, sc = S[k];
  load(k);
  setTimeout(function () {{
    if (sc.hint === 'zoom') {{ document.querySelector('.tmap .tm').dispatchEvent(new MouseEvent('click', {{bubbles: true}})); }}
    if (sc.hint === 'add' || sc.hint === 'addlater') {{
      var r = document.getElementById('du-in').getBoundingClientRect();
      dcMotion.say({{add: 'Buy colored pens', when: sc.hint === 'add' ? 'today' : 'later', from: {{x: r.left, y: r.top}}}});
    }}
    if (sc.hint === 'day') {{ document.querySelectorAll('.pwk .pc')[4].click(); return; }}
    (0, eval)(sc.swap);
  }}, 700);
}};
document.getElementById('cheer').onclick = function () {{ load('nothing'); setTimeout(function () {{ dcMotion.cheer('dre', '🎉'); }}, 300); }};
document.getElementById('spin').onclick = function () {{ load('nothing'); setTimeout(function () {{
  document.querySelector('.dc-foot a.ic[title="Refresh"]').click(); }}, 300); }};
document.getElementById('prof').onclick = function () {{ load('nothing'); setTimeout(function () {{
  document.querySelectorAll('#stage a.dc-pl')[1].dispatchEvent(new MouseEvent('click', {{bubbles: true}})); (0, eval)(PROFILE); }}, 300); }};
document.getElementById('logo').onclick = function () {{ dcMotion.logo(document.getElementById('stage')); }};
var PROFILE = {profile_js};
load(document.getElementById('pick').value);
</script></body></html>"""
path = os.path.join(REPO, "tools", "motion_preview.html")
open(path, "w", encoding="utf-8").write(doc)
print("wrote", path)
