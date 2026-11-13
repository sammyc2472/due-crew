"""3.9.11, hooks (Sam's yes to the mock "Tips Become Hooks": "build that
whole implementation you've proposed"): the line that made a card click.

A hook is my own words on a note's guid, never the card's text: one a
card, a note's length. It shows, folded till Show (a one-by-one card's
answer isn't given away), the next time I'm stuck on that card. Shared
(the default, a tick on each one) it is also my tip on that card on the
server (PUT /hooks): every mutual friend stuck on the card reads it with
their sync, nobody having to ask. "This helped" on it reaches me once,
with a refresh (`thanks` on /board), and is a keepsake in the scrapbook.

What offers one:
  - the chip beside Edit, on the answer side of a card I've missed twice
    or more and again today ("Add a hook for next time"), and the
    reviewer's More menu on any card;
  - once a card, twice a day at most, when one I kept missing has stuck
    (TURNED_LAPSES lapses, its last TURNED_RIGHT answers right): "This one
    stuck. What made it click?"

`hooks.json` beside wrap.json, this Anki profile's: my hooks ({guid: {t,
at, s: shared, up: on the server}}), what still has to be sent (`out`:
{guid: words, or "" to take it down}; sent again with a later refresh
when a send didn't get out), the cards asked about, and the crew hooks I
hid (`hide`). Pure but for the file: the rules and the views here, the
chip's place, its clicks and the requests in cards.py.
"""

import os

from . import store
from .backend.shapes import clean_note

KEEP = 3000            # hooks kept (the oldest go first)
TURNED_LAPSES = 3      # a card I kept missing...
TURNED_RIGHT = 3       # ...whose last answers were all right
ASKS_A_DAY = 2         # "What made it click?" at most this often
ASKED_KEEP = 4000
HIDE_KEEP = 2000
SEND_AT_ONCE = 5       # waiting sends tried with one refresh

_STORE = {"path": None, "data": None, "disk": None}


def _path():
    from . import wrap
    return os.path.join(wrap._profile_files(), "hooks.json")


def _data():
    d = store.load(_STORE, _path())
    for k in ("by", "asked", "out", "hide"):
        if not isinstance(d.get(k), dict):
            d[k] = {}
    return d


def _save():
    store.save(_STORE)


def _one(guid):
    h = _data()["by"].get(str(guid))
    return h if isinstance(h, dict) else {}


def get(guid):
    """My hook on this card, or ""."""
    return clean_note(_one(guid).get("t"))


def shared(guid):
    """Whether my hook on this card is shared with my crew; with none there, what I chose last (shared, at first)."""
    h = _one(guid)
    return bool(h.get("s", True)) if h else bool(_data().get("share", True))


def put(guid, words, day, share=True):
    """Keep (or change) my hook on a card; no words takes it off. What it
    is now. What the server should have is noted in `out`: the words when
    it's shared, "" (take it down) when it was there and is now private or gone."""
    d = _data()
    by, g = d["by"], str(guid)
    was = _one(g)
    text = clean_note(words)
    if text:
        by[g] = {"t": text, "at": str(day or ""), "s": bool(share), "up": bool(was.get("up"))}
        d["share"] = bool(share)
        if share:
            d["out"][g] = text
        elif was.get("up") or d["out"].get(g):
            d["out"][g] = ""
        if len(by) > KEEP:
            for k in sorted(by, key=lambda x: str((by[x] or {}).get("at") or ""))[:len(by) - KEEP]:
                if (by.pop(k, None) or {}).get("up"):
                    d["out"][k] = ""
    else:
        by.pop(g, None)
        if was.get("up") or d["out"].get(g):
            d["out"][g] = ""
        else:
            d["out"].pop(g, None)
    _save()
    return text


def count():
    return len(_data()["by"])


def waiting():
    """What still has to reach the server: [(guid, words or "")], SEND_AT_ONCE at most."""
    return list(_data()["out"].items())[:SEND_AT_ONCE]


def sent(guid, words):
    """A send got there: no longer waiting (unless it changed since), and the hook knows it's up."""
    d, g = _data(), str(guid)
    if d["out"].get(g) == words:
        d["out"].pop(g, None)
    if g in d["by"] and isinstance(d["by"][g], dict):
        d["by"][g]["up"] = bool(words)
    _save()


def refused(guid, words):
    """The server won't take it (no room, or its shape): stop sending it; the hook stays, as mine alone."""
    d, g = _data(), str(guid)
    if d["out"].get(g) == words:
        d["out"].pop(g, None)
        if words and isinstance(d["by"].get(g), dict):
            d["by"][g]["s"] = False
    _save()


def hide(guid, uid):
    """A crewmate's hook on a card, hidden here for good."""
    h = _data()["hide"]
    h[f"{guid}|{uid}"] = 1
    if len(h) > HIDE_KEEP:
        for k in list(h)[:len(h) - HIDE_KEEP]:
            h.pop(k, None)
    _save()


def hidden(guid, uid):
    return f"{guid}|{uid}" in _data()["hide"]


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
    """What the chip says of my hook on the card up now: (view or None,
    asked: whether this was the "what made it click" line). stuck: I'm
    stuck on it (my hook shows, folded till Show: Sam, "especially for one
    by ones we don't want to spoil the correct answer"); offer: I've missed
    it twice or more and again today (the quiet way to add one, beside Edit
    in the bar, never over the card). Raw words: the chip draws them as text."""
    if hook:
        if not stuck:
            return None, False  # a card I have down doesn't need its hook read to me
        return {"kind": "hook", "text": f"Your tip: {hook}", "short": "Your tip", "title": hook,
                "fold": "You left a tip", "cmd": "hookadd", "act": "Edit"}, False
    if has_turned and can_ask:
        return {"kind": "hookask", "text": "This one stuck. What made it click?", "short": "What made it click?",
                "cmd": "hookadd", "act": "Add a tip"}, True
    if offer:
        return {"kind": "hookadd", "text": "Add a tip for next time", "short": "+ Tip", "cmd": "hookadd", "bar": True}, False
    return None, False


def over(view_):
    """Whether my hook goes in this view's place: nothing there, or who
    knows it, or a plan's note. An ask, or a crewmate's hook, stays (mine is
    a click away in More). Who knows it comes up as ever on a card I've no hook on."""
    return view_ is None or view_.get("kind") in ("knows", "remark")


def thanks_lines(thanks, names, part_of):
    """What I'm told when hooks of mine helped: one line a card. thanks:
    [(guid, uid)] as /board brings them; names: {uid: first name}; part_of:
    guid -> the deck part its card is in here ("" when I've no such card).
    "Your hook on a Renal card helped Maya and 2 more." Raw words."""
    by = {}
    for guid, uid in thanks or []:
        by.setdefault(str(guid), [])
        if uid not in by[str(guid)]:
            by[str(guid)].append(uid)
    out = []
    for guid, uids in by.items():
        who = [names[u] for u in uids if u in names]
        rest = len(uids) - 1
        first = who[0] if who else "a crewmate"
        said = first + (f" and {rest} more" if rest > 0 else "")
        part = str(part_of(guid) or "")
        on = f"on a {part} card" if part else "on a card"
        out.append(f"Your tip {on} helped {said}.")
    return out
