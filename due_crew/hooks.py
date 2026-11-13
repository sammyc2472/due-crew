"""3.9.11, hooks (Sam's yes to the mock "Tips Become Hooks", step one): the
line that made a card click, written by me on a card I keep missing, shown
the next time I'm stuck on it. Mine alone in this step: `hooks.json` beside
wrap.json in this Anki profile's files, never sent (sharing one with my crew
is step two, and needs the server).

A hook is my own words on a note's guid, never the card's text. One a card,
a tip's length. What offers one:
  - the chip beside Edit, on the answer side of a card I've missed twice
    or more and again today ("Add a hook for next time"), and the
    reviewer's More menu on any card;
  - once a card, twice a day at most, when one I kept missing has stuck
    (TURNED_LAPSES lapses, its last TURNED_RIGHT answers right): "This one
    stuck. What made it click?"

Pure but for the file: the rules and the views here, the chip's place and
its clicks in cards.py.
"""

import json
import os

from .backend.shapes import clean_note

KEEP = 3000            # hooks kept (the oldest go first)
TURNED_LAPSES = 3      # a card I kept missing...
TURNED_RIGHT = 3       # ...whose last answers were all right
ASKS_A_DAY = 2         # "What made it click?" at most this often
ASKED_KEEP = 4000

_STORE = {"path": None, "data": None, "disk": None}


def _path():
    from . import wrap
    return os.path.join(wrap._profile_files(), "hooks.json")


def _data():
    path = _path()
    if _STORE["path"] != path or _STORE["data"] is None:
        _STORE.update(path=path, disk=None)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            got = json.loads(text)
            _STORE["data"] = got if isinstance(got, dict) else {}
            _STORE["disk"] = text
        except Exception:
            _STORE["data"] = {}
    d = _STORE["data"]
    if not isinstance(d.get("by"), dict):
        d["by"] = {}
    if not isinstance(d.get("asked"), dict):
        d["asked"] = {}
    return d


def _save():
    text = json.dumps(_STORE["data"])
    if _STORE.get("disk") == text:
        return
    tmp = _path() + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, _path())
        _STORE["disk"] = text
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def get(guid):
    """My hook on this card, or ""."""
    h = _data()["by"].get(str(guid))
    return clean_note(h.get("t")) if isinstance(h, dict) else ""


def put(guid, words, day):
    """Keep (or change) my hook on a card; no words takes it off. What it is now."""
    by = _data()["by"]
    text = clean_note(words)
    if text:
        by[str(guid)] = {"t": text, "at": str(day or "")}
        if len(by) > KEEP:
            for k in sorted(by, key=lambda g: str((by[g] or {}).get("at") or ""))[:len(by) - KEEP]:
                by.pop(k, None)
    else:
        by.pop(str(guid), None)
    _save()
    return text


def count():
    return len(_data()["by"])


def turned(lapses, last_eases):
    """A card I kept missing that has stuck: TURNED_LAPSES lapses or more,
    and its last TURNED_RIGHT answers (newest first) all right."""
    eases = [int(e or 0) for e in list(last_eases or [])[:TURNED_RIGHT]]
    return int(lapses or 0) >= TURNED_LAPSES and len(eases) == TURNED_RIGHT and all(e > 1 for e in eases)


def may_ask(guid, day):
    """Whether "What made it click?" may show on this card today: never asked of it, and under the day's few."""
    asked = _data()["asked"]
    return str(guid) not in asked and sum(1 for d in asked.values() if d == str(day)) < ASKS_A_DAY


def note_asked(guid, day):
    asked = _data()["asked"]
    asked[str(guid)] = str(day)
    if len(asked) > ASKED_KEEP:
        for k in sorted(asked, key=lambda g: asked[g])[:len(asked) - ASKED_KEEP]:
            asked.pop(k, None)
    _save()


def view(hook, stuck, offer, has_turned, can_ask):
    """What the chip says of my hook on the card up now, when nothing a
    crewmate left is there to say: (view or None, asked: whether this was
    the "what made it click" line). stuck: I'm stuck on it (my hook shows);
    offer: I've missed it twice or more and again today (the quiet way to
    add one, beside Edit in the bar, never over the card). Raw words: the
    chip draws them as text."""
    if hook:
        if not stuck:
            return None, False  # a card I have down doesn't need its hook read to me
        return {"kind": "hook", "text": f"Your hook: {hook}", "short": "Your hook", "title": hook,
                "cmd": "hookadd", "act": "Edit"}, False
    if has_turned and can_ask:
        return {"kind": "hookask", "text": "This one stuck. What made it click?", "short": "What made it click?",
                "cmd": "hookadd", "act": "Add a hook"}, True
    if offer:
        return {"kind": "hookadd", "text": "Add a hook for next time", "short": "+ Hook", "cmd": "hookadd", "bar": True}, False
    return None, False


def beside(view_, hook):
    """Who knows it keeps its place (Sam: "I really liked… these folks know
    this coming up on the right"); my hook is said after it, in the same bubble."""
    if not hook or not view_ or view_.get("kind") != "knows":
        return view_
    out = dict(view_, text=f'{view_["text"]} · Your hook: {hook}', title=hook)
    if isinstance(out.get("peek"), dict):
        out["peek"] = dict(out["peek"], head=f'{out["peek"]["head"]} · Your hook: {hook}')
    return out
