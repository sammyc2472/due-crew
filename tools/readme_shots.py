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
html = page_html(face.view(), {"theme": "light", "accent": "green"}, preview=True)
out = os.path.join(REPO, "tools", "readme_magic.html")
with open(out, "w", encoding="utf-8") as f:
    f.write("<!doctype html><meta charset=utf-8><body style='margin:0;background:#f5f5f5'>"
            "<div id=shot style='width:640px;margin:0 auto;background:#fff'>" + html + "</div></body>")
print(out)
