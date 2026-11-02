"""Song of the moment (3.9.6): what a song is (songs.py), the catalog's
answer, Listen's links, the Worker's rule restated by the fake, the account
key, a mutual friend's song on my board's entries, and the glue
(song_flow.py): search, Use this, Take it off, Listen (asking the app the
first time), Apple's page, the preview through Anki's player, the floor's
view (fresh once, off, motion) and its settings. Standard library only:
python3 tests/test_songs.py."""

import copy
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fakes  # noqa: E402

STORE = fakes.FakeWorker()
fakes.install_fake_requests(STORE)
fakes.install_fake_aqt()

from due_crew import account, app, songs                      # noqa: E402
from due_crew import song_flow as SF                          # noqa: E402
from due_crew.backend import api                              # noqa: E402

CHECKS = []


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


SONG = {"t": "Lantern Hours", "a": "Mira Vale", "al": "Lantern Hours", "y": 2025, "id": 1700000001,
        "url": "https://music.apple.com/us/album/lantern-hours/1700000000?i=1700000001",
        "art": "https://is1-ssl.mzstatic.com/image/thumb/Music/x/300x300bb.jpg",
        "prev": "https://audio-ssl.itunes.apple.com/itunes-assets/AudioPreview/x/mzaf_1.plus.aac.p.m4a",
        "at": "2026-11-02"}

# the catalog's answer, as Apple's Search API documents it (made-up songs)
CATALOG = {"resultCount": 4, "results": [
    {"wrapperType": "track", "kind": "song", "trackId": 1700000001, "trackName": "Lantern Hours",
     "artistName": "Mira Vale", "collectionName": "Lantern Hours", "releaseDate": "2025-03-14T12:00:00Z",
     "trackViewUrl": SONG["url"], "previewUrl": SONG["prev"],
     "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/Music/x/100x100bb.jpg"},
    {"wrapperType": "track", "kind": "song", "trackId": 1700000001, "trackName": "Lantern Hours (again)",
     "artistName": "Mira Vale", "trackViewUrl": SONG["url"]},
    {"wrapperType": "track", "kind": "music-video", "trackId": 5, "trackName": "Not a song",
     "artistName": "X", "trackViewUrl": "https://music.apple.com/us/x"},
    {"wrapperType": "track", "kind": "song", "trackId": 1700000002, "trackName": "Second Wind <b>",
     "artistName": "Northbound", "trackViewUrl": "https://music.apple.com/us/album/second-wind/1?i=2",
     "artworkUrl100": "https://evil.example/100x100bb.jpg", "releaseDate": "soon"},
]}


def test_pure():
    c = songs.clean(SONG)
    check("a song: every field kept as given", c == SONG, c)
    for k in ("t", "a", "id", "url"):
        check(f"a song needs its {k}", songs.clean({x: v for x, v in SONG.items() if x != k}) is None)
    bad = [
        ("a link off Apple Music", dict(SONG, url="https://example.com/x")),
        ("http", dict(SONG, url="http://music.apple.com/us/x")),
        ("someone's name in the link", dict(SONG, url="https://u@music.apple.com/x")),
        ("another port", dict(SONG, url="https://music.apple.com:8443/x")),
        ("a long title", dict(SONG, t="x" * 121)),
        ("a control character", dict(SONG, a="Mira\nVale")),
        ("an id as text", dict(SONG, id="1700000001")),
        ("an id of true", dict(SONG, id=True)),
        ("a zero id", dict(SONG, id=0)),
        ("not a dict", [SONG]),
    ]
    for name, v in bad:
        check(f"no song: {name}", songs.clean(v) is None, songs.clean(v))
    loose = songs.clean(dict(SONG, art="https://evil.example/a.jpg", prev="javascript:alert(1)", al="a\x07b", y=3000, at="soon"))
    check("a cover, preview, album, year or day that doesn't hold is dropped, the rest kept",
          loose == {"t": SONG["t"], "a": SONG["a"], "id": SONG["id"], "url": SONG["url"]}, loose)
    check("titles trimmed", songs.clean(dict(SONG, t="  Lantern Hours ")) ["t"] == "Lantern Hours")
    got = songs.parse(CATALOG)
    check("the catalog's answer: songs only, one per id, cleaned (a bad cover dropped), the cover asked at 300 px",
          [s["id"] for s in got] == [1700000001, 1700000002] and got[0]["art"].endswith("/300x300bb.jpg")
          and got[0]["y"] == 2025 and "art" not in got[1] and "y" not in got[1] and got[1]["t"] == "Second Wind <b>", got)
    check("the catalog's answer: anything else, nothing", songs.parse({"results": "x"}) == [] and songs.parse(None) == [])
    check("search: two letters at least; songs only; the words as typed, encoded",
          songs.search_url("a") == "" and "entity=song" in songs.search_url("lantern hours")
          and "term=lantern+hours" in songs.search_url("  lantern   hours ") and "%3A" in songs.search_url("a:b|c"))
    check("search: a long query is cut", len(songs.search_url("x" * 500)) < 300)
    check("Listen in Apple Music: the song itself", songs.listen_url(SONG, "apple") == SONG["url"])
    check("Listen in Spotify: a search for title and artist (it comes first)",
          songs.listen_url(SONG, "spotify") == "https://open.spotify.com/search/Lantern%20Hours%20Mira%20Vale")
    check("Listen in YouTube Music: a search too",
          songs.listen_url(SONG, "youtube") == "https://music.youtube.com/search?q=Lantern+Hours+Mira+Vale")
    check("another app: nothing to open (the words to copy)", songs.listen_url(SONG, "other") is None
          and songs.words(SONG) == "Lantern Hours · Mira Vale")
    check("a song that doesn't hold: no link", songs.listen_url({"t": "x"}, "spotify") is None)
    people = [{"name": "jo", "song": dict(SONG, at="2026-10-01")}, {"name": "Ari", "song": dict(SONG, at="2026-11-02")},
              {"name": "bea", "song": dict(SONG, at="2026-11-02")}, {"name": "Cal", "song": dict(SONG)}]
    check("the floor's order: the newest pick first, then by name",
          [p["name"] for p in songs.newest_first(people)] == ["Ari", "bea", "Cal", "jo"],
          [p["name"] for p in songs.newest_first(people)])
    check("the apps, Apple first; the motions, gentle first", [k for k, _ in songs.APPS] == ["apple", "spotify", "youtube", "other"]
          and songs.MOTIONS[0] == "gentle" and songs.app_name("youtube") == "YouTube Music")
    check("Apple's badge: Apple's own, https", songs.BADGE_URL.startswith("https://tools.applemediaservices.com/"))


def test_worker_twin():
    """The fake's _song_of restates board.ts songOf; songs.clean is the add-on's
    side of the same rule: on every case here they agree."""
    cases = [SONG, dict(SONG, url="https://example.com/x"), dict(SONG, url="http://music.apple.com/x"),
             dict(SONG, url="https://u@music.apple.com/x"), dict(SONG, url="https://music.apple.com:443/x"),
             dict(SONG, url="https://MUSIC.apple.com/x"), dict(SONG, t="x" * 121), dict(SONG, a="a\tb"),
             dict(SONG, id="1"), dict(SONG, id=True), dict(SONG, id=-3), dict(SONG, art="https://a.mzstatic.com/x.jpg"),
             dict(SONG, art="https://mzstatic.com.evil.example/x"), dict(SONG, prev="https://itunes.apple.com/p.m4a"),
             dict(SONG, y=1899), dict(SONG, y=True), dict(SONG, at="2026-1-2"), dict(SONG, al=""), {"t": "x"}]
    w = fakes.FakeWorker()
    w.add_user("alice", "Alice")
    off = []
    for i, v in enumerate(cases):
        w.settings["alice"] = {"v": 1, "at": "x", "settings": {"song": copy.deepcopy(v)}, "rev": 1}
        if w._song_of("alice") != songs.clean(v):
            off.append((i, w._song_of("alice"), songs.clean(v)))
    check("the Worker's rule (as the fake restates it) and the add-on's agree", not off, off)


def test_board_entries_and_account():
    w = fakes.FakeWorker()
    for uid, nm in (("alice", "Alice"), ("dave", "Dave"), ("carol", "Carol")):
        w.add_user(uid, nm)
    w.befriend("alice", "dave")
    w.befriend("dave", "alice")
    w.befriend("carol", "alice")
    w.befriend("alice", "carol")  # alice added carol; carol added alice too: mutual
    w.settings["alice"] = {"v": 1, "at": "2026-11-02T00:00:00Z", "settings": {"song": dict(SONG, art="https://x.example/a")}, "rev": 1}
    sys.modules["requests"].Session = lambda: fakes.FakeSession(w)

    def board_of(uid):
        cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"))
        cl.session = {"user_id": uid, "token": w.session_for(uid), "email": f"{uid}@example.com", "display_name": uid}
        return cl.fetch_board(["2026-11-02"])["entries"]
    ents = {e["user_id"]: e for e in board_of("dave")}
    alice = ents.get("alice") or {}
    check("a mutual friend's song on my board's entries, cleaned (a cover off Apple's hosts dropped)",
          alice.get("song") == {k: v for k, v in SONG.items() if k != "art"}, alice.get("song"))
    me = next((e for e in ents.values() if e.get("you")), {})
    check("my own entry: no song from the board (mine is my account's)", me.get("song") is None)
    w.friends.discard(("alice", "dave"))
    lst = board_of("dave")
    check("someone who hasn't added me back: no song (nor a row of theirs in my entries)",
          not any(e.get("user_id") == "alice" and e.get("song") for e in lst))
    check("my song is an account key: it follows my account", "song" in account.ACCOUNT_KEYS)
    got = account.clean({"song": dict(SONG, prev="javascript:x")})
    check("the account's own copy is cleaned too", got.get("song") == {k: v for k, v in SONG.items() if k != "prev"}, got)
    check("one that doesn't hold doesn't come in", "song" not in account.clean({"song": {"t": "x"}}))
    check("pick: my song goes with my account's settings", account.pick({"song": SONG}).get("song") == SONG)


class Glue:
    """song_flow pointed at a config, the board's eval, a catalog, Anki's player."""

    def __enter__(self):
        self.c = {}
        self.evals, self.links, self.played, self.tips, self.asked, self.redraws, self.stopped = [], [], [], [], [], [], []
        self.answer = {"status": 200, "json": copy.deepcopy(CATALOG), "bytes": b"\x00" * 1000}
        self.saved = {k: getattr(SF, k) for k in ("cfg", "save_cfg", "_today", "_get")}
        self.saved_app = (app.board_eval, app._bg, app._state.get("entries"))
        SF.cfg = lambda: self.c
        SF.save_cfg = lambda c: None
        SF._today = lambda: "2026-11-02"
        g = self

        class Resp:
            def __init__(self, url):
                self.url = url
                self.status_code = g.answer["status"]

            def json(self):
                if isinstance(g.answer["json"], Exception):
                    raise g.answer["json"]
                return copy.deepcopy(g.answer["json"])

            def iter_content(self, n):
                b = g.answer["bytes"]
                for i in range(0, len(b), n):
                    yield b[i:i + n]
        self.asks = []
        SF._get = lambda url, stream=False: (self.asks.append(url), Resp(url))[1]
        app.board_eval = lambda js: self.evals.append(js)
        app._bg = lambda job, done=None: done(job()) if done else job()
        utils = sys.modules["aqt.utils"]
        utils.openLink = lambda u: self.links.append(u)
        utils.tooltip = lambda m, *a, **k: self.tips.append(m)
        sound = types.ModuleType("aqt.sound")
        sound.av_player = types.SimpleNamespace(play_file=lambda p: self.played.append(p),
                                                stop_and_clear_queue=lambda: self.stopped.append(1))
        sys.modules["aqt.sound"] = sound
        sys.modules["aqt.gui_hooks"].av_player_did_end_playing = types.SimpleNamespace(append=lambda f: self.__dict__.update(ended=f))
        from due_crew import sheets
        self.saved_ask = sheets.ask_item
        sheets.ask_item = lambda title, text, items, then, **k: self.asked.append((title, items, then))
        SF.mw.state = "deckBrowser"
        SF.mw.deckBrowser = types.SimpleNamespace(refresh=lambda: self.redraws.append(1))
        SF._play.update(uid="", path="", hooked=False)
        SF._last.update(q="", songs={})
        return self

    def __exit__(self, *a):
        for k, v in self.saved.items():
            setattr(SF, k, v)
        app.board_eval, app._bg, app._state["entries"] = self.saved_app
        from due_crew import sheets
        sheets.ask_item = self.saved_ask

    def say(self, msg):
        parts = msg.split(":")
        return SF.on_message(parts[1], parts)


def test_glue():
    with Glue() as g:
        g.say("duecrew:songsearch:" + "lantern%3A%20h%7Cours")
        check("search: the words decoded, Apple's catalog asked once", len(g.asks) == 1 and "term=lantern%3A+h%7Cours" in g.asks[0], g.asks)
        res = g.evals[-1]
        check("search: its songs to the page (dcSong.results), only what the rows show",
              res.startswith("window.dcSong&&dcSong.results(") and '"Lantern Hours"' in res and "Second Wind \\u003cb\\u003e" not in res
              and '"prev"' not in res and '"url"' not in res and '"error": false' in res, res[:300])
        check("search: a title with markup goes as data (the page escapes it)", '"Second Wind <b>"' in res)
        n = len(g.asks)
        g.say("duecrew:songsearch:a")
        check("search: one letter asks nothing, and says no songs", len(g.asks) == n and '"songs": []' in g.evals[-1])
        g.answer["status"] = 503
        g.say("duecrew:songsearch:lantern")
        check("search: the catalog down says so (error), never Anki's error window", '"error": true' in g.evals[-1])
        g.answer["status"] = 200
        g.answer["json"] = ValueError("not json")
        g.say("duecrew:songsearch:lantern")
        check("search: an answer that isn't JSON, the same", '"error": true' in g.evals[-1])
        g.answer["json"] = copy.deepcopy(CATALOG)
        g.say("duecrew:songsearch:lantern")
        g.say("duecrew:songuse:1700000001")
        check("Use this: the song on my card, the day I picked it; the board drawn again",
              g.c.get("song") == dict(SONG) and g.redraws, g.c.get("song"))
        g.say("duecrew:songuse:42")
        check("Use this: a song the last search didn't return does nothing", g.c["song"]["id"] == 1700000001)
        g.say("duecrew:songclear")
        check("Take it off: gone", "song" not in g.c)
        # Listen
        app._state["entries"] = [{"user_id": "me", "you": True},
                                 {"user_id": "dre", "you": False, "name": "Dre", "song": dict(SONG)}]
        g.say("duecrew:songlisten:dre")
        check("Listen, the first time: asks which app, every one offered, nothing opened yet",
              len(g.asked) == 1 and g.asked[0][1] == [n for _k, n in songs.APPS] and not g.links, g.asked)
        g.asked[0][2](1)
        check("…Spotify picked: kept on this computer, and the song opens there",
              g.c.get("music_app") == "spotify" and g.links[-1] == songs.listen_url(SONG, "spotify"))
        g.say("duecrew:songlisten:dre")
        check("Listen again: straight there, no question", len(g.asked) == 1 and len(g.links) == 2)
        g.say("duecrew:songapp:apple")
        g.say("duecrew:songlisten:dre")
        check("▾ Apple Music: the song itself from then on", g.c["music_app"] == "apple" and g.links[-1] == SONG["url"])
        g.say("duecrew:songapp:nope")
        check("an app that isn't one: nothing changes", g.c["music_app"] == "apple")
        g.say("duecrew:songapple:dre")
        check("Apple's badge: the song's page on Apple Music", g.links[-1] == SONG["url"])
        g.say("duecrew:songlisten:stranger")
        check("Listen to someone not in my crew's entries: nothing", g.links[-1] == SONG["url"] and len(g.asked) == 1)
        # the preview
        g.say("duecrew:songprev:dre")
        check("▶ 30 s: Apple's preview fetched to a file and played by Anki's player; the page told it's playing",
              g.played and g.played[-1].endswith(f"duecrew-preview-{SONG['id']}.m4a") and g.evals[-1].endswith('dcSong.playing("dre")'))
        g.say("duecrew:songprev:dre")
        check("■ Stop: Anki's player stopped, the page told", g.stopped and g.evals[-1].endswith('dcSong.playing("")'))
        g.say("duecrew:songprev:dre")
        g.ended()
        check("the preview ran out by itself: the page told", g.evals[-1].endswith('dcSong.playing("")') and SF._play["uid"] == "")
        g.say("duecrew:songprev:dre")  # stop
        slow = []
        app._bg = lambda job, done=None: slow.append((job, done))
        g.say("duecrew:songprev:dre")
        app._state["entries"].append({"user_id": "mo", "you": False, "name": "Mo", "song": dict(SONG, id=55)})
        g.say("duecrew:songprev:mo")
        n_played = len(g.played)
        for job, done in slow:
            done(job())
        app._bg = lambda job, done=None: done(job()) if done else job()
        check("▶ on one song, then on another before the first loaded: only the second plays",
              len(g.played) == n_played + 1 and g.played[-1].endswith("duecrew-preview-55.m4a") and SF._play["uid"] == "mo", g.played[-2:])
        g.say("duecrew:songprev:mo")
        app._state["entries"][1]["song"] = {k: v for k, v in SONG.items() if k != "prev"}
        g.say("duecrew:songprev:dre")
        check("a song without a preview says so", g.tips[-1] == "No preview for this one.")
        # the floor: on, off, motion
        g.say("duecrew:dancehide")
        check("× on the floor: off on this computer", g.c.get("dance_floor") is False and SF.floor_view([], g.c) is None)
        g.say("duecrew:danceshow")
        g.say("duecrew:dancemotion:lively")
        check("Settings: shown again; Lively", g.c.get("dance_floor") is True and SF.motion(g.c) == "lively")
        g.say("duecrew:dancemotion:wild")
        check("a motion that isn't one: nothing", SF.motion(g.c) == "lively")
        check("unknown: not ours", g.say("duecrew:songsomething:x") is False)


def test_floor_view():
    c = {}
    ents = [{"user_id": "me", "you": True, "name": "Me"},
            {"user_id": "dre", "you": False, "name": "Dre", "accent": "blue", "look": ["cap"], "song": dict(SONG, at="2026-10-01")},
            {"user_id": "mo", "you": False, "name": "Mo", "song": dict(SONG, id=9, at="2026-11-01")},
            {"user_id": "jo", "you": False, "name": "Jo"}]
    saved = (SF.cfg, SF.save_cfg)
    SF.cfg = lambda: c
    SF.save_cfg = lambda x: None
    try:
        v = SF.floor_view(ents, c)
        check("the floor: crewmates with a song, newest first, in their colour and look; the default motion gentle; no app yet",
              [p["uid"] for p in v["crew"]] == ["mo", "dre"] and v["crew"][1]["accent"] == "blue" and v["crew"][1]["look"] == ["cap"]
              and v["motion"] == "gentle" and v["app"] == "" and v["me"] is None and v["pip"] is True, v)
        check("the first look is history: nobody hops", not any(p["fresh"] for p in v["crew"]))
        SF.mark_seen(v)
        check("…and it's kept: each crewmate's song as seen", c.get(SF.SEEN_KEY) == {"dre": f"{SONG['id']}@2026-10-01", "mo": "9@2026-11-01", "jo": ""})
        ents[1]["song"] = dict(SONG, id=12, at="2026-11-02")
        ents[3]["song"] = dict(SONG, id=13, at="2026-11-02")
        v = SF.floor_view(ents, c)
        check("a new song, and a first one: they hop in; the one unchanged doesn't",
              {p["uid"]: p["fresh"] for p in v["crew"]} == {"dre": True, "jo": True, "mo": False}, v["crew"])
        SF.mark_seen(v)
        check("…once", not any(p["fresh"] for p in SF.floor_view(ents, c)["crew"]))
        ents.append({"user_id": "new", "you": False, "name": "Newbie", "song": dict(SONG)})
        check("someone new to my crew with a song: no hop (no song of theirs was seen before)",
              not next(p for p in SF.floor_view(ents, c)["crew"] if p["uid"] == "new")["fresh"])
        c["song"] = dict(SONG)
        c["sev"] = False
        v = SF.floor_view(ents, c)
        check("my song on the decks; Pip off says so", v["me"] == SONG and v["pip"] is False)
        check("no board (signed out): no floor", SF.floor_view(None, c) is None)
        c["dance_floor"] = False
        check("off: no floor", SF.floor_view(ents, c) is None)
    finally:
        SF.cfg, SF.save_cfg = saved


if __name__ == "__main__":
    test_pure()
    test_worker_twin()
    test_board_entries_and_account()
    test_glue()
    test_floor_view()
    failed = [n for n, ok in CHECKS if not ok]
    print(f"\n{len(CHECKS) - len(failed)}/{len(CHECKS)} checks passed")
    sys.exit(1 if failed else 0)
