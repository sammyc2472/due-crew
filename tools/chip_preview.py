"""3.9.1: the top bar's room chip with its speaker, as Anki draws it, light
and dark, closed and with the room-sound picker open; a fifteen and a crew
room; a narrow window. Writes tools/chip_preview.html (each case in its own
frame, since the chip sits fixed at the bar's end).

    python3 tools/chip_preview.py
"""

import datetime
import html
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fakes  # noqa: E402

fakes.install_fake_aqt()
sys.path.insert(0, ROOT)
from due_crew import board, room_model as rm  # noqa: E402

now = datetime.datetime.now(datetime.timezone.utc)
FIF = rm.make_fifteen("me", now - datetime.timedelta(minutes=4))
ROOM = rm.make_room("me", now - datetime.timedelta(minutes=10), 4, 25, 5)


def frame(title, room, sound, dark=False, open_=False, width=1000, compact=False):
    data = rm.widget_data(room, [], board.accent_pair("green"), compact=compact, sev=True, sound=sound)
    js = rm.widget_js("chip", data)
    player = rm.sound_js(rm.sound_state(room, *sound)) if open_ else ""
    click = ("setTimeout(function(){var s=document.querySelector('[aria-label=\"Room sound\"]');s&&s.click();},50);"
             if open_ else "")
    body_cls = "nightMode night_mode" if dark else ""
    bg = "#2c2c2c" if dark else "#f6f6f4"
    doc = (f'<!doctype html><html><head><meta charset="utf-8"></head>'
           f'<body class="{body_cls}" style="margin:0;height:34px;background:{bg};font:13px sans-serif;color:{"#ddd" if dark else "#333"}">'
           f'<div style="text-align:center;line-height:34px">Decks &nbsp; Add &nbsp; Browse &nbsp; Stats &nbsp; Sync</div>'
           f'<script>window.pycmd=function(m){{console.log(m)}};</script>'
           f'<script>{player}</script><script>{js}</script><script>{click}</script></body></html>')
    return (f'<h3>{html.escape(title)}</h3><iframe class="c" style="width:{width}px" srcdoc="{html.escape(doc, quote=True)}"></iframe>')


cases = [
    frame("A fifteen, no sound yet (light)", FIF, ("off", 60)),
    frame("A fifteen, rain on (light)", FIF, ("rain", 60)),
    frame("The picker open, rain picked (light)", FIF, ("rain", 60), open_=True),
    frame("The picker open, nothing picked (dark)", FIF, ("off", 60), dark=True, open_=True),
    frame("A study room, fire on (dark)", ROOM, ("fire", 40), dark=True),
    frame("A study room, the picker open (light)", ROOM, ("waves", 80), open_=True),
    frame("Compact chip, the picker open (light)", FIF, ("brown", 60), open_=True, compact=True),
    frame("A narrow window, the picker open (light)", FIF, ("rain", 60), open_=True, width=520),
]
page = ("<!doctype html><html><head><meta charset='utf-8'><title>Room chip, with its sound</title>"
        "<style>body{font:14px sans-serif;margin:20px;background:#fff}iframe.c{height:34px;border:1px solid #ccc;display:block;margin-bottom:14px}"
        "h3{font-size:13px;margin:8px 0 4px}</style></head><body>"
        + "".join(cases) + "</body></html>")
out = os.path.join(ROOT, "tools", "chip_preview.html")
with open(out, "w", encoding="utf-8") as f:
    f.write(page)
print(out, json.dumps({"cases": len(cases)}))
