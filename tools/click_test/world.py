"""The robot's world: the suite's FakeWorker (tests/fakes.py) in this
process, the robot signed in to it, and a crew of four with a week of
stats, a squad, two songs on and a cheer waiting, so the board has rows.
What a crewmate has goes up as their own client would send it (their
token, the API's own routes).

Nothing here reaches the network: the add-on's API client and its song
search are pointed at the fake."""

import datetime
import json
import os
import sys

ME, MY_NAME = "me", "Robin"
CREW = (("dre", "Dre", "\U0001F98A"), ("max", "Max", "\U0001F422"), ("ana", "Ana", "\U0001F33F"),
        ("kai", "Kai", "\U0001F680"))
SQUAD = "Night owls"
# one song a crewmate shares (as the song catalog gives it; its link host is the one the add-on takes); made-up words
SONGS = [{"trackId": 900000 + i, "trackName": f"Robot song {i}", "artistName": f"The Testers {i}",
          "collectionName": f"Album {i}", "releaseDate": "2024-05-01T00:00:00Z",
          "trackViewUrl": f"https://music.apple.com/us/song/{900000 + i}", "artworkUrl100": "",
          "kind": "song"} for i in range(1, 4)]


class World:
    def __init__(self, repo):
        sys.path.insert(0, os.path.join(repo, "tests"))
        import fakes
        self.fakes = fakes
        self.store = fakes.FakeWorker()
        real = sys.modules.get("requests")
        fakes.install_fake_requests(self.store)
        self.requests = sys.modules["requests"]  # the fake module
        if real is not None:
            sys.modules["requests"] = real  # Anki itself keeps the real one
        else:
            del sys.modules["requests"]
        self.store.add_user(ME, MY_NAME, email="robot@example.com")
        for uid, name, _emoji in CREW:
            self.store.add_user(uid, name)
            self.store.befriend(ME, uid)
            self.store.befriend(uid, ME)

    def call(self, uid, method, path, body=None):
        """A request as uid's own client sends it; (status, body)."""
        tok = self.store.session_for(uid)
        r = self.store.handle(method, "https://api.duecrew.com" + path,
                              headers={"Authorization": "Bearer " + tok}, json_body=body)
        return r.status_code, r.json()

    def seed(self, labels):
        """The crew's last few days, as their syncs send them. labels: my
        Anki days, today first (the board's own)."""
        for k, (uid, name, emoji) in enumerate(CREW):
            days = {}
            for i, lb in enumerate(labels[:7]):
                if (i + k) % 4 == 3:
                    continue  # a day off now and then
                n = 40 + 23 * k + 9 * i
                days[lb] = {"studied": True, "reviews": n, "studyTimeMs": n * 7000, "streak": 7 - i + k,
                            "newCards": 5 + k, "accuracy": 80 + k * 3}
            heat = {lb: 30 + 5 * i for i, lb in enumerate(labels[:7])}
            body = {"profile": {"name": name, "emoji": emoji, "clientVersion": "3.9.8"},
                    "week": {"days": days}, "heatmap": {"counts": heat}}
            st, _ = self.call(uid, "POST", "/sync", body)
            assert st == 200, (uid, st, _)
        # a squad: mine, with two of the crew in it
        st, sq = self.call(ME, "POST", "/squads", {"name": SQUAD})
        assert st == 200, sq
        for uid in ("dre", "max"):
            self.call(uid, "POST", f"/squads/{sq['id']}/join", {"code": sq["code"]})
            self.call(uid, "PUT", f"/squads/{sq['id']}/row",
                      {"name": uid.title(), "day": labels[0], "reviews": 55, "studyTimeMs": 400000,
                       "accuracy": 88, "streak": 6, "week": 5, "newCards": 9})
        self.squad = sq
        # two of the crew have a song on (the dance floor); a cheer from Dre waits for me
        now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for uid, s in (("dre", SONGS[0]), ("ana", SONGS[1])):
            song = {"t": s["trackName"], "a": s["artistName"], "al": s["collectionName"], "y": 2024,
                    "id": s["trackId"], "url": s["trackViewUrl"], "at": labels[0]}
            self.call(uid, "PUT", "/settings", {"v": 1, "at": now, "settings": {"song": song}})
        self.call("dre", "POST", f"/cheers/{ME}", {"emoji": "\U0001F389", "note": "Nice week"})

    def sign_in(self, dc):
        """Signs the add-on in as ME, its requests on the fake; at
        profile_did_open, before the add-on's own hook reads the session."""
        sys.modules["due_crew.backend.api"].requests = self.requests
        cl = dc.app.client()
        cl.http = self.requests.Session()
        cl.session.update(user_id=ME, token=self.store.session_for(ME), display_name=MY_NAME,
                          email="robot@example.com")
        cl._save_session()

    def songs_offline(self, dc):
        """Song search answers from SONGS, as the song catalog would."""
        import importlib
        song_flow = importlib.import_module("due_crew.song_flow")

        class Answer:
            status_code = 200

            def json(self):
                return {"resultCount": len(SONGS), "results": [dict(s) for s in SONGS]}

        song_flow._get = lambda url, stream=False: Answer()

    def plan_docs(self):
        return {pid: json.loads(p["doc"]) if isinstance(p.get("doc"), str) else p.get("doc")
                for pid, p in self.store.plans.items()}


def anki_days(col, n=8):
    """My Anki days, today first, labelled as the board labels them (the add-on's own StatsQueries)."""
    from due_crew.stats.queries import StatsQueries
    q = StatsQueries(col)
    return [q.day_label(i) for i in range(n)]
