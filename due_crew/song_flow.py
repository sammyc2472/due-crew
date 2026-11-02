"""Song of the moment's glue (3.9.6): the catalog search, my pick, a
song's preview, Listen in my music app, and the dance floor's view (the
board draws it: board.py, the Decks screen's bottom-right corner).

What's mine: my song is an account key ("song", account.ACCOUNT_KEYS): it
rides my settings and reaches my mutual friends on their /board, as my
Pip's look does. This computer's: the floor on or off ("dance_floor"), its
motion ("dance": gentle, lively, still), my music app ("music_app"), and
folded down to its chip or open ("dance_folded"), and which crewmates' songs
I've seen ("song_seen", so a new one hops in once).

Requests: the search goes from this computer straight to Apple's public
catalog (no account, no key), on typing that's paused; picking a song is
the account's one save. Nothing about what anyone is listening to is ever
read: the bubble is the song they chose. Main thread except the HTTP."""

import os
import tempfile
import traceback
import urllib.parse

from aqt import mw

from . import app, songs
from .app import cfg, save_cfg

TIMEOUT = 8
PREVIEW_MAX = 2_000_000  # bytes: a 30-second preview is about half a megabyte
SEEN_KEY = "song_seen"

_last = {"q": "", "songs": {}}  # the last search: what Use this picks from
_play = {"uid": "", "path": "", "want": "", "hooked": False}


# ---- what's what ----

def mine(c=None):
    return songs.clean((c if c is not None else cfg()).get("song"))


def motion(c=None):
    m = (c if c is not None else cfg()).get("dance")
    return m if m in songs.MOTIONS else "gentle"


def app_key(c=None):
    a = (c if c is not None else cfg()).get("music_app")
    return a if a in dict(songs.APPS) else ""


def _sig(song):
    return f'{song["id"]}@{song.get("at") or ""}' if song else ""


def _entries():
    return app._state.get("entries") or []


def song_of(uid):
    """My song ("me"), or a mutual crewmate's from this refresh."""
    if uid == "me":
        return mine()
    for e in _entries():
        if not e.get("you") and str(e.get("user_id") or "") == str(uid):
            return songs.clean(e.get("song"))
    return None


def floor_view(entries, c):
    """The dance floor's view, or None (off, or no board to draw it on):
    me (my song or None), crew (mutual crewmates with a song, newest
    first, each fresh when their song changed since I last saw the floor;
    the first look is history: nobody hops), motion, app, playing, pip."""
    if c.get("dance_floor") is False or entries is None:
        return None
    seen = c.get(SEEN_KEY) if isinstance(c.get(SEEN_KEY), dict) else None
    crew, sigs = [], {}
    for e in entries or []:
        if e.get("you"):
            continue
        uid = str(e.get("user_id") or "")
        s = songs.clean(e.get("song"))
        sigs[uid] = _sig(s)
        if s:
            crew.append({"uid": uid, "name": str(e.get("name") or "?"), "accent": e.get("accent") or "",
                         "look": list(e.get("look") or []), "song": s,
                         "fresh": seen is not None and uid in seen and seen[uid] != sigs[uid]})
    return {"me": mine(c), "crew": songs.newest_first(crew), "motion": motion(c), "app": app_key(c),
            "playing": _play["uid"], "pip": bool(c.get("sev", True)), "folded": bool(c.get("dance_folded")),
            "_seen": sigs}


def mark_seen(view):
    """After the floor is drawn: what it showed is seen (a fresh song hops once)."""
    if not view or not isinstance(view.get("_seen"), dict):
        return
    c = cfg()
    if c.get(SEEN_KEY) != view["_seen"]:
        c[SEEN_KEY] = dict(view["_seen"])
        save_cfg(c)


# ---- the commands the board sends ----

def on_message(cmd, parts):
    """The board's song and dance commands (songsearch, songuse, ..., dancemotion). True when handled."""
    arg = parts[2] if len(parts) > 2 else ""
    if cmd == "songsearch":
        search(urllib.parse.unquote(arg))
    elif cmd == "songuse" and arg.isdigit():
        use(int(arg))
    elif cmd == "songclear":
        clear()
    elif cmd == "songlisten" and arg:
        listen(arg)
    elif cmd == "songapp" and arg in dict(songs.APPS):
        set_app(arg)
    elif cmd == "songapp" and arg == "ask":
        set_app("")  # Settings' "Ask me the first time": the next Listen asks again
    elif cmd == "songprev" and arg:
        preview(arg)
    elif cmd == "songapple" and arg:
        apple(arg)
    elif cmd in ("dancehide", "danceshow"):
        _set("dance_floor", cmd == "danceshow")
    elif cmd == "dancefold" and arg in ("0", "1"):
        _set("dance_folded", arg == "1", redraw=False)  # the page folds it itself; kept for the next draw
    elif cmd == "dancemotion" and arg in songs.MOTIONS:
        _set("dance", arg)
    else:
        return False
    return True


def _set(key, value, redraw=True):
    c = cfg()
    if c.get(key) != value:
        c[key] = value
        save_cfg(c)
    if redraw:
        _redraw()


def _redraw():
    if mw.state == "deckBrowser":
        mw.deckBrowser.refresh()


def _today():
    from .account import _today as day
    return day()


# ---- the catalog ----

def _get(url, stream=False):
    import requests
    return requests.get(url, timeout=TIMEOUT, stream=stream, headers={"User-Agent": f"DueCrew/{app.ADDON_VERSION}"})


def search(q):
    """Ask Apple's catalog for q; the songs go to the page (dcSong.results).
    Only the latest search lands; one that failed says so. Not under two
    letters."""
    q = str(q or "")[:songs.QUERY_MAX]
    _last["q"] = q
    url = songs.search_url(q)
    if not url:
        _results(q, [], False)
        return
    gen = app.generation

    def job():
        try:
            r = _get(url)
            if r.status_code != 200:
                print(f"due crew: song search: {r.status_code}")
                return None
            return r.json()
        except Exception as e:  # offline, slow, or not JSON: one line, never Anki's error window
            print(f"due crew: song search: {type(e).__name__}")
            return None

    def done(data):
        if gen != app.generation or q != _last["q"]:
            return  # a newer search went out, or this profile closed
        if data is None:
            _results(q, [], True)
            return
        got = songs.parse(data)
        _last["songs"] = {s["id"]: s for s in got}
        _results(q, got, False)

    app._bg(job, done)


def _results(q, got, error):
    import json
    keep = ("id", "t", "a", "al", "y", "art")
    payload = {"q": q, "songs": [{k: s[k] for k in keep if k in s} for s in got], "error": bool(error)}
    app.board_eval("window.dcSong&&dcSong.results(" + json.dumps(payload) + ")")


# ---- my song ----

def use(track_id):
    """Put the last search's song on my card (the day I picked it), one save."""
    s = _last["songs"].get(track_id)
    if not s:
        return
    c = cfg()
    c["song"] = dict(songs.clean(s), at=_today())
    save_cfg(c)  # an account key: the account's save goes with it
    _redraw()


def clear():
    c = cfg()
    if "song" in c:
        c.pop("song")
        save_cfg(c)
    _redraw()


# ---- listening ----

def set_app(key):
    _set("music_app", key)


def listen(uid):
    """Open a song in my music app; the first time, ask which app that is."""
    s = song_of(uid)
    if not s:
        return
    a = app_key()
    if a:
        _open(s, a)
        return
    from . import sheets
    names = [n for _k, n in songs.APPS]

    def then(i):
        key = songs.APPS[i][0]
        c = cfg()
        c["music_app"] = key
        save_cfg(c)
        _open(s, key)
        _redraw()

    sheets.ask_item("Which music app do you use?", "Listen opens your crew's songs there. Settings can change it.",
                    names, then, yes="Listen")


def _open(s, key):
    from aqt.utils import openLink, tooltip
    url = songs.listen_url(s, key)
    if url:
        openLink(url)
        return
    try:
        from aqt.qt import QApplication
        QApplication.clipboard().setText(songs.words(s))
        tooltip(f"Copied: {songs.words(s)}")
    except Exception:
        traceback.print_exc()


def apple(uid):
    """Apple's badge beside a cover: the song's own page on Apple Music. A
    crewmate's or mine by uid; in the search, a result's by its track id."""
    s = _last["songs"].get(int(uid)) if uid.isdigit() and len(uid) <= 16 else song_of(uid)
    if s:
        from aqt.utils import openLink
        openLink(s["url"])


# ---- the preview: Apple's 30 seconds, through Anki's own player ----

def preview(uid):
    """Play a song's preview, or stop the one playing. Anki's web view can't
    play Apple's AAC, so it's fetched to a file and Anki's player plays it."""
    if _play["uid"] == uid:
        stop_preview()
        return
    s = song_of(uid)
    if not s or not s.get("prev"):
        from aqt.utils import tooltip
        tooltip("No preview for this one.")
        return
    stop_preview()
    _play["want"] = uid  # the latest ▶ wins: an earlier one still loading doesn't play
    gen = app.generation
    path = os.path.join(tempfile.gettempdir(), f"duecrew-preview-{s['id']}.m4a")

    def job():
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path
        try:
            r = _get(s["prev"], stream=True)
            if r.status_code != 200:
                return None
            got = b""
            for chunk in r.iter_content(65536):
                got += chunk
                if len(got) > PREVIEW_MAX:
                    return None
            with open(path, "wb") as f:
                f.write(got)
            return path
        except Exception as e:
            print(f"due crew: song preview: {type(e).__name__}")
            return None

    def done(p):
        if gen != app.generation or _play["want"] != uid:
            return
        _play["want"] = ""
        if not p:
            from aqt.utils import tooltip
            tooltip("The preview didn't load.")
            return
        _play.update(uid=uid, path=p)
        _hook()
        try:
            from aqt.sound import av_player
            av_player.play_file(p)
        except Exception:
            traceback.print_exc()
            _play.update(uid="", path="")
        _playing()

    app._bg(job, done)


def stop_preview():
    _play["want"] = ""
    if not _play["uid"]:
        return
    _play.update(uid="", path="")
    try:
        from aqt.sound import av_player
        av_player.stop_and_clear_queue()
    except Exception:
        traceback.print_exc()
    _playing()


def _playing():
    import json
    app.board_eval("window.dcSong&&dcSong.playing(" + json.dumps(_play["uid"]) + ")")


def _ended(*_args):
    if _play["uid"]:
        _play.update(uid="", path="")
        _playing()


def _hook():
    if _play["hooked"]:
        return
    try:
        from aqt import gui_hooks
        gui_hooks.av_player_did_end_playing.append(_ended)
        _play["hooked"] = True
    except Exception:
        traceback.print_exc()
