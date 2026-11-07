"""Card Probe: a diagnostic add-on, installed beside Due Crew for a while, then
removed. It finds what holds a card up after a deck is opened.

It notes, in its own user_files/probe.txt:
- each card that takes longer than a second to show, from the deck's click
  (or the last answer) to its text on screen;
- what Anki's main thread was running whenever it was stuck for half a
  second or more (a few samples of its Python stack while it stays stuck);
- for a slow card, how long the top bar, the card's page and the bottom bar
  took to answer, and their long tasks;
- the Anki, Qt and platform versions and the add-ons that are on.

Tools › Card probe: copy the report puts it on the clipboard. It sends
nothing anywhere, and keeps no card text: only times, names of code and
counts."""

import os
import platform
import sys
import threading
import time
import traceback

from aqt import gui_hooks, mw
from aqt.qt import QAction, QApplication, QTimer

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "user_files", "probe.txt")
STUCK = 0.5          # s the main thread is stuck before its stack is noted
SAMPLES = (0.5, 2.0, 5.0, 10.0)
SLOW_CARD = 1.0      # s from the click (or answer) to the card's text

_lines = []
_lock = threading.Lock()
_beat = [time.monotonic()]
_main = threading.main_thread().ident
_card = {"t0": None, "why": "", "polls": 0, "seen": False}


def note(text):
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        _lines.append(f"{stamp} {text}")
        del _lines[:-400]
        try:
            os.makedirs(os.path.dirname(OUT), exist_ok=True)
            with open(OUT, "w", encoding="utf-8") as f:
                f.write(_head() + "\n".join(_lines) + "\n")
        except OSError:
            pass


def _head():
    try:
        from anki.buildinfo import version
    except Exception:
        version = "?"
    try:
        from aqt.qt import qVersion
        qt = qVersion()
    except Exception:
        qt = "?"
    on = []
    try:
        for m in mw.addonManager.all_addon_meta():
            if m.enabled:
                on.append(f"{m.human_name()} ({m.dir_name})")
    except Exception:
        pass
    return (f"Card probe report\nAnki {version} · Qt {qt} · {platform.platform()} · Python {sys.version.split()[0]}\n"
            f"Add-ons on: {', '.join(on) or '?'}\n\n")


# ---- the main thread: stuck, and what it was running ----

def _tick():
    _beat[0] = time.monotonic()


def _stack():
    frame = sys._current_frames().get(_main)
    if frame is None:
        return "  (no stack)"
    rows = traceback.extract_stack(frame)[-14:]
    return "\n".join(f"  {os.path.basename(os.path.dirname(r.filename))}/{os.path.basename(r.filename)}:{r.lineno} {r.name}"
                     for r in rows)


def _watch():
    seen = None
    taken = set()
    while True:
        time.sleep(0.1)
        since = _beat[0]
        gap = time.monotonic() - since
        if gap < STUCK:
            continue
        if seen != since:
            seen, taken = since, set()
        for at in SAMPLES:
            if gap >= at and at not in taken:
                taken.add(at)
                note(f"main thread stuck {gap:.1f} s, running:\n{_stack()}")


# ---- a card: from the click (or the answer) to its text on screen ----

def _start(why):
    _card.update(t0=time.monotonic(), why=why, polls=0, seen=False)


def _on_state(new, old):
    if new == "overview" and old == "deckBrowser":
        _start("deck clicked")
    elif new == "review":
        if _card["t0"] is None or time.monotonic() - _card["t0"] > 30:
            _start("Study Now")


def _on_answer(*_a):
    _start("next card")


def _on_question(card):
    if _card["t0"] is None:
        _start("card")
    QTimer.singleShot(0, _poll)


_POLL = """(function(){var q=document.getElementById('qa');if(!q){return null;}
return [q.style.opacity, q.innerHTML.length];})()"""


def _poll():
    if _card["t0"] is None or _card["seen"]:
        return
    asked = time.monotonic()
    _card["polls"] += 1

    def got(res):
        now = time.monotonic()
        took = now - _card["t0"]
        if isinstance(res, list) and res[1] and res[0] in ("1", ""):
            _card["seen"] = True
            if took >= SLOW_CARD:
                note(f"slow card: {took:.1f} s from '{_card['why']}' to its text "
                     f"(the card's page answered the last check in {now - asked:.2f} s)")
                _pages(took)
            _card["t0"] = None
            return
        if took > 60:
            note(f"card not shown after 60 s ('{_card['why']}'); the page says {res!r}")
            _pages(took)
            _card["t0"] = None
            return
        QTimer.singleShot(50, _poll)
    try:
        mw.web.evalWithCallback(_POLL, got)
    except Exception:
        traceback.print_exc()


_LONG = """(function(){var a=window.__probeLong||[],now=performance.now();
var r=a.filter(function(e){return now-e[0]<%d;});
return [r.length, Math.round(r.reduce(function(t,e){return t+e[1];},0)), document.querySelectorAll('*').length];})()"""


def _pages(took):
    """For a slow card: how long each page takes to answer now, and its long tasks lately."""
    span = int((took + 3) * 1000)
    webs = (("top bar", getattr(getattr(mw, "toolbar", None), "web", None)), ("card", mw.web),
            ("bottom bar", getattr(getattr(mw, "reviewer", None), "bottom", None) and mw.reviewer.bottom.web))
    for name, web in webs:
        if web is None:
            continue
        asked = time.monotonic()

        def got(res, name=name, asked=asked):
            note(f"  {name}: answered in {time.monotonic() - asked:.2f} s; long tasks lately (count, ms), elements: {res!r}")
        try:
            web.evalWithCallback(_LONG % span, got)
        except Exception:
            traceback.print_exc()


# a page's long tasks (50 ms or more of its scripts and drawing at once) go only to a
# listener set up as it loads: this one keeps the last 200 for _LONG
_KEEP = ("<script>try{window.__probeLong=[];new PerformanceObserver(function(l){var a=window.__probeLong;"
         "l.getEntries().forEach(function(e){a.push([e.startTime,e.duration]);});if(a.length>200){a.splice(0,a.length-200);}})"
         ".observe({type:'longtask',buffered:true});}catch(e){}</script>")


def _on_content(content, context):
    try:
        content.head += _KEEP
    except Exception:
        pass


def _copy():
    with _lock:
        text = _head() + "\n".join(_lines)
    QApplication.clipboard().setText(text)
    from aqt.utils import tooltip
    tooltip("Card probe report copied.")


def _menu():
    a = QAction("Card probe: copy the report", mw)
    a.triggered.connect(_copy)
    mw.form.menuTools.addAction(a)


def _begin():
    t = QTimer(mw)
    t.timeout.connect(_tick)
    t.start(100)
    mw._card_probe_timer = t
    threading.Thread(target=_watch, daemon=True, name="card-probe").start()
    _menu()
    note("probe on")


gui_hooks.main_window_did_init.append(_begin)
gui_hooks.state_did_change.append(_on_state)
gui_hooks.reviewer_did_answer_card.append(_on_answer)
gui_hooks.reviewer_did_show_question.append(_on_question)
gui_hooks.webview_will_set_content.append(_on_content)
