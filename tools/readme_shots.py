"""The README's other pictures (3.9.12): Magic search's window on a sample deck, written out as a
page for tools/readme_shots.js, which also crops Insights, Pip's closet, Pip Party and the dance
floor out of tools/preview.html (run tools/preview.py first). Renders of the add-on's own pages,
not mockups.

    python3 tools/preview.py && python3 tools/readme_shots.py && node tools/readme_shots.js
"""
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tests"))

import test_magic as T  # noqa: E402  (the suite's sample deck and its window)
from due_crew.magic_html import page_html  # noqa: E402

face, _ops, _closed = T.window()
face.on("type", {"text": "heart failure"})
html = page_html(face.view(), {"theme": "light", "accent": "blue"}, preview=True)  # a colour a picture: people pick their own
out = os.path.join(REPO, "tools", "readme_magic.html")
with open(out, "w", encoding="utf-8") as f:
    f.write("<!doctype html><meta charset=utf-8><body style='margin:0;background:#f5f5f5'>"
            "<div id=shot style='width:640px;margin:0 auto;background:#fff'>" + html + "</div></body>")
print(out)

# the squad's bingo card with a line, each stamp its person's Pip (the preview's card and week)
import json  # noqa: E402
import runpy  # noqa: E402

P = runpy.run_path(os.path.join(REPO, "tools", "preview.py"), run_name="readme")
board = P["board"]
PEOPLE = {"sam": {"you": True, "name": "Sammy"},
          "dre": {"name": "Dre", "accent": "blue", "look": ["dino"]},
          "maya": {"name": "Maya", "accent": "teal", "look": ["wizard"]},
          "theo": {"name": "Theo", "accent": "amber", "look": ["sprout", "shades"]},
          "noah": {"name": "Noah", "accent": "rose", "look": ["partyhat", "scarf"]}}
ME = {"theme": "light", "accent": "purple", "sev_look": ["headphones"], "sev_closet": {"headphones": "2026-01-01"}}
card = board.bingo_html(P["_bv"](P["_LINE"]), ME, people=PEOPLE)
out = os.path.join(REPO, "tools", "readme_bingo.html")
with open(out, "w", encoding="utf-8") as f:
    f.write("<!doctype html><meta charset=utf-8><body style='margin:0;background:#f5f5f5'><center>"
            "<div id=shot style='width:640px;margin:0 auto'>" + card + "</div></center></body>")
print(out)

# the accents' tokens, for the pictures cut from the preview (readme_shots.js sets them on the board)
tokens = {a: board._token_block(board.palette("light", a)) for a in board.ACCENTS}
with open(os.path.join(REPO, "tools", "readme_tokens.json"), "w", encoding="utf-8") as f:
    json.dump(tokens, f)
