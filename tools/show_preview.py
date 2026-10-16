"""3.9.0: play each way a cheer lands (show.js) on a page like Anki's Decks
screen: the deck list, then the real board, and the real script a landing
cheer sends (board.flurry_js with a show). A button a show; "1" and "3" for
how many crewmates sent one. Writes tools/show_preview.html (not committed).

    python3 tools/show_preview.py && open tools/show_preview.html
"""

import contextlib
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
with contextlib.redirect_stdout(io.StringIO()):
    import preview as P  # the preview's sample crew (it writes tools/preview.html as it loads)
from due_crew import board, shows  # noqa: E402

ents = list(P.DRESSED)[:6]
cfg = dict(P._MINE, period="today", accent="green")
page = board.render(dict(P.DATA, entries=ents), cfg, P.now_ts - 60)
others = [e for e in ents if not e.get("you")]
SENDERS = [others[1], others[2], others[4]]
EMO = ["\U0001F525", "\U0001F389", "\U0001F4AA"]
NOTES = ["you've got this", "", "see you at the room tonight"]


def landing(kind, n):
    cheers = [{"from": e["user_id"], "name": e["name"], "emoji": EMO[i], "note": NOTES[i]} for i, e in enumerate(SENDERS[:n])]
    pips = board.cheer_pips(cheers, ents, cfg)
    names = [c["name"].split(" ")[0] for c in cheers]
    text = f"{' '.join(EMO[:n])} {board.and_more(names)} sent cheers"
    notes = [c["note"] if n == 1 else f"{c['name']}: {c['note']}" for c in cheers if c["note"]]
    back = (cheers[0]["from"], cheers[0]["emoji"]) if n == 1 else None
    return board.flurry_js([c["emoji"] for c in cheers], text, back=back, notes=notes, pips=pips, show=kind)


DECKS = [("&minus; Med school", 30, 12, 486, ""), ("Big Step 1", 20, 9, 412, "sub"), ("Pharm", 10, 3, 61, "sub"),
         ("Path", 0, 0, 13, "sub"), ("+ Spanish", 15, 0, 48, ""), ("Default", 0, 0, 0, "")]
rows = "".join(f'<tr class="deck"><td class="{c}">{n}</td><td class="n">{a}</td><td class="l">{b}</td><td class="d">{d}</td><td>&#9881;</td></tr>'
               for n, a, b, d, c in DECKS)
plays = {f"{k}:{n}": landing(k, n) for k in shows.SHOWS for n in (1, 3)}
buttons = "".join(f'<button onclick="go(\'{k}\', 1)">{k} 1</button><button onclick="go(\'{k}\', 3)">3</button> ' for k in shows.SHOWS)
out = f"""<!doctype html><html><head><meta charset="utf-8"><title>Cheer shows</title>
<style>
  body {{ margin: 0; padding: 0 12px 60px; background: #f5f5f5; font: 14px -apple-system, sans-serif; color: #202020; }}
  body.nightMode {{ background: #2c2c2c; color: #ddd; }}
  .bar {{ padding: 8px 0; display: flex; flex-wrap: wrap; gap: 4px; }}
  .bar button {{ font: inherit; font-size: 12px; padding: 2px 8px; }}
  table.dk {{ margin: 18px auto 0; border-collapse: collapse; min-width: 520px; }}
  table.dk td {{ padding: 6px 14px; text-align: right; border-bottom: 1px solid rgba(128,128,128,.2); }}
  table.dk td:first-child {{ text-align: left; }} table.dk td.sub {{ padding-left: 38px; }}
  .n {{ color: #1f6fd1; }} .l {{ color: #c62828; }} .d {{ color: #2e7d32; }}
</style></head><body>
<div class="bar"><button onclick="document.body.classList.toggle('nightMode')">theme</button> {buttons}</div>
<center><table class="dk">{rows}</table>{page}</center>
<script>
var PLAYS = {json.dumps(plays).replace("</", "<" + chr(92) + "/")};
function pycmd() {{ return false; }}
function go(k, n) {{ if (window.DCShow) DCShow.stop(); document.querySelectorAll('body > div[style*="18vh"], body > div[style*="12px"]').forEach(function (b) {{ if (b.style.position === 'fixed') b.remove(); }}); (0, eval)(PLAYS[k + ':' + n]); }}
</script></body></html>"""
path = os.path.join(HERE, "show_preview.html")
with open(path, "w", encoding="utf-8") as f:
    f.write(out)
print(path)
