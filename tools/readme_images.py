"""Render the README's board picture (docs/images/board.png) from the
add-on's own board: a sample crew in their colours and looks, your day
folded above it. CLAUDE.md: the README's images are renders of the board,
re-rendered when it changes.

    python3 tools/readme_images.py            # writes tools/readme_board.html
    node tools/readme_images.js               # screenshots it to docs/images/board.png

(The second step needs Playwright; the first is enough to look at it.)"""

import datetime
import os
import runpy

HERE = os.path.dirname(os.path.abspath(__file__))
P = runpy.run_path(os.path.join(HERE, "preview.py"), run_name="readme")  # its sample data, Due and plans
board, L, day, ago = P["board"], P["L"], P["day"], P["ago"]

TODAY = datetime.date.fromisoformat(L[0])
CREW = [
    {"user_id": "dre", "name": "Dre", "accent": "blue", "look": ["dino"],
     "days": {lb: day(700 + i * 30, 7440000, 93.1, 41 - i) for i, lb in enumerate(L)}},
    {"user_id": "marisa", "name": "Marisa K.", "accent": "teal", "look": ["wizard"],
     "exam_date": (TODAY + datetime.timedelta(days=3)).isoformat(),
     "days": {L[0]: dict(day(640, 5820000, 88.4, 17), status="Step 2 in 30 days, send help and also snacks")}},
    {"user_id": "sam", "name": "Sammy", "you": True, "accent": "green", "look": ["headphones"],
     "exam_date": (TODAY + datetime.timedelta(days=10)).isoformat(),
     "days": {L[0]: dict(day(512, 4320000, 91.6, 12), status="coffee, then 400 cards")}},
    {"user_id": "noah", "name": "Noah", "accent": "rose", "look": ["partyhat", "scarf"], "back": True,
     "days": {L[0]: day(118, 1320000, 88.0, 1)}},
    {"user_id": "priya", "name": "Priya", "accent": "amber", "look": ["sprout", "shades", "balloon"],
     "days": {L[0]: {"away": True, "awayTo": (TODAY + datetime.timedelta(days=4)).isoformat()}}},
    {"user_id": "theo", "name": "Theo", "paused": True, "days": {}},
]
for e in CREW:
    e.setdefault("you", False)
    e.setdefault("paused", False)
    e.setdefault("exam_date", "")
    e.setdefault("decks", [])
    e.setdefault("last_updated", ago(minutes=4))
DATA = {"entries": CREW, "labels": L, "tomorrow": P["TOMORROW"], "pending": []}

ME = {"period": "today", "accent": "green", "sev_look": ["headphones"], "sev_closet": {"headphones": L[-1]}}
html = board.render(DATA, ME, P["now_ts"] - 30,
                    due=dict(P["_DV"], folded=True), plans=P["PLANS"], you=P["_YOU"]("today", folded=True))
page = f"""<!doctype html><html><head><meta charset="utf-8"><title>README board</title>
<style>body {{ margin: 0; padding: 16px; background: #f5f5f5; font-family: -apple-system, sans-serif; }}
:root {{ --canvas-glass: rgba(255, 255, 255, 0.7); }} .fancy table {{ background: var(--canvas-glass); }}
#shot {{ width: 640px; }}</style></head>
<body class="fancy"><center><div id="shot">{html}</div></center></body></html>"""
out = os.path.join(HERE, "readme_board.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
print("wrote", out)
