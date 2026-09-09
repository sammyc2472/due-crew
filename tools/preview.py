"""Render the real board.py output into a standalone page for visual audit.

Mimics Anki's deck browser context: same body font scale, a theme toggle
that flips the nightMode class, and buttons that run the real overlay JS.
"""

import html
import datetime
import json
import sys

import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tests"))  # the fake collection/aqt
import fakes  # noqa: E402

fakes.install_fake_requests(fakes.FakeFirestore())
fakes.install_fake_aqt()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from due_crew import board  # noqa: E402

TODAY = datetime.date(2026, 9, 1)
L = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
TOMORROW = (TODAY + datetime.timedelta(days=1)).isoformat()
NOW = datetime.datetime.now(datetime.timezone.utc)


def ago(**kw):
    return (NOW - datetime.timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


def day(reviews, ms, acc, streak):
    return {"reviews": reviews, "studyTimeMs": ms, "accuracy": acc,
            "streak": streak, "studied": reviews > 0}


SIG = ["g%02d" % i for i in range(20)]
SIG2 = ["j%02d" % i for i in range(20)]

ENTRIES = [
    {"user_id": "sam", "name": "Sammy", "you": True, "paused": False,
     "last_updated": ago(minutes=1), "exam_date": (TODAY + datetime.timedelta(days=10)).isoformat(),
     "days": {L[0]: day(512, 4320000, 91.6, 12), L[1]: day(430, 3900000, 90.2, 11),
              L[2]: day(388, 3300000, 88.9, 10), L[4]: day(510, 4000000, 92.0, 8),
              L[5]: day(220, 2000000, 85.5, 7), L[6]: day(240, 2100000, 86.5, 6)},
     "decks": [{"name": "AnKing Step 1", "sig": SIG, "total": 2100, "seen": 1218, "mature": 861},
               {"name": "Japanese Core 2k", "sig": SIG2, "total": 2000, "seen": 1820, "mature": 1540}]},
    {"user_id": "dre", "name": "Dre", "you": False, "paused": False,
     "last_updated": ago(minutes=12), "exam_date": "",
     "days": {lb: day(700 + i * 30, 7440000, 93.1, 41 - i) for i, lb in enumerate(L)},
     "decks": [{"name": "AnKing Step 1", "sig": SIG, "total": 2100, "seen": 1512, "mature": 1134}]},
    {"user_id": "marisa", "name": "Marisa K.", "you": False, "paused": False,
     "last_updated": ago(hours=1),
     "exam_date": (TODAY + datetime.timedelta(days=3)).isoformat(),
     "days": {L[0]: day(640, 5820000, 88.4, 17), L[2]: day(500, 4600000, 87.0, 15),
              L[3]: day(410, 3600000, 89.1, 14), L[5]: day(380, 3400000, 86.2, 12)},
     "decks": []},
    {"user_id": "long", "name": "Bartholomew Fitzgerald-Montgomery the Third of Pharmacology",
     "you": False, "paused": False, "last_updated": ago(minutes=3), "exam_date": "",
     "days": {L[0]: day(12345, 359940000, 100.0, 1234)}, "decks": []},
    {"user_id": "priya", "name": "Priya", "you": False, "paused": False,
     "last_updated": ago(hours=26), "exam_date": "",
     "days": {L[1]: day(233, 2400000, 86.0, 9), L[3]: day(310, 2900000, 84.4, 7)},
     "decks": [{"name": "Core 2k (JP)", "sig": SIG2, "total": 2000, "seen": 1281, "mature": 760}]},
    {"user_id": "noah", "name": "Noah", "you": False, "paused": False,
     "last_updated": ago(minutes=3), "exam_date": "", "back": True,
     "days": {L[0]: day(118, 1320000, 88.0, 1)}, "decks": []},
    {"user_id": "theo", "name": "Theo", "you": False, "paused": True,
     "last_updated": ago(days=2), "exam_date": "", "days": {}, "decks": []},
]

DATA = {"entries": ENTRIES, "labels": L, "tomorrow": TOMORROW, "pending": ["Jules"]}
WRAP = {"reviews": 21430, "time_ms": 148320000, "best_name": "Marisa K.", "full_days": 5}
DELTAS = {("sam", "AnKing Step 1"): 124}

now_ts = datetime.datetime.now().timestamp()
sections = []
EVE = {"people": [("marisa", "Marisa K.")]}
for period, wrap in (("today", WRAP), ("week", None), ("decks", None)):
    cfg = {"period": period}
    html_out = board.render(DATA, cfg, now_ts - 180, wrap=wrap, deltas=DELTAS,
                            exam_eve=EVE if period == "today" else None,
                            rules_stale=(period == "today"))
    sections.append(f'<h3>{period}</h3>{html_out}')
SROWS = [
    {"user_id": "u1", "name": "StepQueen", "day": L[0], "reviews": 1412,
     "time_ms": 10920000, "streak": 88},
    {"user_id": "dre", "name": "Dre", "day": L[0], "reviews": 812,
     "time_ms": 7440000, "streak": 41, "crew": True},
    {"user_id": "sam", "name": "Sammy", "day": L[0], "reviews": 512,
     "time_ms": 4320000, "streak": 12, "you": True},
    {"user_id": "u2", "name": "Maya R.", "day": L[0], "reviews": 488,
     "time_ms": 3900000, "streak": 31, "pending": True},
    {"user_id": "u3", "name": "Jordan", "day": L[0], "reviews": 302,
     "time_ms": 2400000, "streak": 9},
]
sections.append("<h3>everyone (sharing)</h3>" + board.render(
    DATA, {"period": "everyone"}, now_ts - 60,
    everyone_view={"state": "ok", "rows": SROWS, "totals": {"people": 2381, "reviews": 1204411, "above": 411}, "my_rank": 412}))
sections.append("<h3>everyone (not opted in)</h3>" + board.render(
    DATA, {"period": "everyone"}, now_ts - 60,
    everyone_view={"state": "optin"}))
# Each board styles `#due-crew`; on one page the last <style> would win for
# all of them, so every accent gets its own document via srcdoc.
def _framed(markup, dark):
    page = ("<body class='%s' style='margin:0;padding:12px;background:%s'>%s</body>"
            % ("night_mode" if dark else "", "#2a2a2a" if dark else "#ececec", markup))
    return ("<iframe class='dc-acc' data-theme='%s' style='width:470px;height:430px;border:0;margin:0 6px 6px 0' "
            "srcdoc=\"%s\"></iframe>" % ("dark" if dark else "light", html.escape(page, quote=True)))


for accent in board.ACCENTS:
    frames = "".join(
        _framed(board.render(DATA, {"period": "today", "accent": accent, "theme": theme},
                             now_ts - 60), theme == "dark")
        for theme in ("light", "dark"))
    sections.append(f"<h3>accent: {accent}</h3><div style='display:flex;flex-wrap:wrap'>{frames}</div>")
sections.append("<h3>signed-out card</h3>" + board.signed_out_card({}))

profile_js = board.profile_overlay_js({
    "name": "Dre", "streak": 41, "last_active": ago(minutes=12),
    "cells": [([0, 1, 3, 12, 30, 70, 160][i * 7 % 7] if (i % 9) else 0) for i in range(182)],
    "same_days": 118, "decks_line": "AnKing Step 1", "uid": "dre",
    "you": False, "paused": False, "exam": "",
    "duet": {"run": 5, "best": 23,
             "mine_week": [True, True, False, True, True, True, True],
             "theirs_week": [True, True, True, True, True, True, True]},
})
flurry = board.flurry_js(["\U0001F389"], "Dre sent cheers", back=("dre", "\U0001F389"))
stranger_js = board.stranger_card_js({"uid": "u2", "name": "Maya R.",
                                      "reviews": 488, "time_ms": 3900000,
                                      "streak": 31, "pending": False})

page = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Due Crew board preview</title>
<style>
  body {{ margin: 0; padding: 24px 12px 60px; background: #ffffff;
         font-family: -apple-system, sans-serif; }}
  body.nightMode {{ background: #2c2c2c; color: #d7d7d7; }}
  /* Anki 26.x deck screen: every table gets a translucent glass fill */
  :root {{ --canvas-glass: rgba(255, 255, 255, 0.7); }}
  body.nightMode {{ --canvas-glass: rgba(255, 255, 255, 0.10); }}
  .fancy table {{ background: var(--canvas-glass); }}
  h3 {{ max-width: 640px; margin: 26px auto 4px; font-size: 13px;
        font-family: monospace; opacity: 0.6; }}
  .bar {{ position: fixed; top: 8px; right: 12px; z-index: 99; display: flex; gap: 6px; }}
  .bar button {{ font-size: 12px; padding: 4px 10px; }}
</style></head><body class="fancy">
<div class="bar">
  <button onclick="document.body.classList.toggle('nightMode')">theme</button>
  <button onclick="eval(PROFILE_JS)">profile</button>
  <button onclick="eval(FLURRY_JS)">flurry</button>
  <button onclick="eval(STRANGER_JS)">stranger</button>
</div>
{''.join(sections)}
<script>
  function pycmd(cmd) {{ console.log('pycmd', cmd); return false; }}
  var PROFILE_JS = {json.dumps(profile_js)};
  var FLURRY_JS = {json.dumps(flurry)};
  var STRANGER_JS = {json.dumps(stranger_js)};
</script>
</body></html>"""

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preview.html")
with open(out, "w") as f:
    f.write(page)
print("wrote", out, len(page), "bytes")
