"""The suite: 3.9.9 on: calm offline, what gets used, Magic search's field."""

from due_crew import board
import datetime
import json
import os
import re
import sys
import tempfile
import types

from .base import REPO, TODAY, as_board, check, make_user_col, new_client, world
from .board import _day, _plan_units


def test_calm_offline_v399():
    """3.9.9 (Off the Board, 11, Sam's pick): when Due Crew can't be reached
    the board says so in a line on top of every tab (the foot's "Couldn't
    sync" was the only word), with when a refresh last got through and Try
    now; a cheer sent then waits, marked on its crewmate's row, and goes
    with the next refresh that gets an answer. Only no answer at all, or the
    server away, holds a cheer: a refusal, a sign-in gone or a ceiling
    would only be refused again."""
    import inspect
    import time as _time
    import due_crew as dc
    from due_crew import app as A, social as S
    from due_crew.backend.shapes import TransportError
    from due_crew.board import draw as D
    from due_crew.app import _state
    labels = [(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7)]
    tomorrow = (TODAY + datetime.timedelta(days=1)).isoformat()
    day = {labels[0]: {"reviews": 40, "studyTimeMs": 600000, "retention": 90.0, "streak": 3}}
    base = {"days": day, "last_updated": "", "decks": [], "paused": False, "room": None}
    ents = [dict(base, user_id="me", name="Sammy", you=True), dict(base, user_id="dre", name="Dre", you=False),
            dict(base, user_id="kai", name="Kai", you=False)]
    data = {"entries": ents, "labels": labels, "tomorrow": tomorrow, "pending": [], "decks": {}, "my_friends": []}
    now = _time.mktime((2026, 11, 8, 18, 0, 0, 0, 0, -1))
    at = _time.mktime((2026, 11, 8, 15, 10, 0, 0, 0, -1))
    check("offline: when a refresh last got through, as a person says it (today, this week, before)",
          D._clock(at, now) == "3:10 PM" and D._clock(at - 2 * 86400, now) == "Fri 3:10 PM"
          and D._clock(at - 9 * 86400, now) == "30 Oct" and D._clock(0, now) == "", D._clock(at, now))
    line = D.offline_html(at, now)
    check("offline: the line says it plainly, when, and Try now refreshes (the board's own command)",
          "Can&rsquo;t reach Due Crew. Your studying still counts and sends when it&rsquo;s back. Last refresh 3:10 PM."
          in line and "duecrew:refresh|" in line and "Try now" in line and 'role="status"' in line)
    page = board.render(data, {"period": "today"}, at, offline=True, notice={"id": 1, "text": "Hi"})
    calm = board.render(data, {"period": "today"}, at)
    check("offline: on top of the board, above even the admin's notice; nothing when a refresh got through",
          "dc-wrap off" in page and page.index("dc-wrap off") < page.index("dc-wrap notice")
          and "dc-wrap off" not in calm and "#due-crew .dc-wrap.off" in page)
    held = board.render(dict(data, held={"dre"}), {"period": "today"}, at)
    rows = {u: next(r for r in re.findall(r"<tr class=\"[^\"]*\">.*?</tr>", held, re.S) if n in r)
            for u, n in (("dre", "Dre"), ("kai", "Kai"))}
    check("offline: a held cheer's crewmate shows Waiting to send, without the pointer; the others the usual Cheer",
          "&#127881; Waiting<span class=\"ts\"> to send</span>" in rows["dre"] and 'class="dc-cpill held"' in rows["dre"]
          and "waiting to send" in rows["dre"] and "a.dc-cpill.held .ts { display: none; }" in held
          and rows["dre"].startswith('<tr class="') and " ch" in rows["dre"].split('"')[1]
          and "&#127881; Cheer</a>" in rows["kai"] and "Waiting to send" not in rows["kai"]
          and "#due-crew tr.ch a.dc-cpill.held" in held)

    # holding: what's held, what isn't, and sending them when a refresh gets through
    sent, tips, answers = [], [], []
    cl = types.SimpleNamespace(session={}, user_id="me", _save_session=lambda: None)

    def send_cheer(to, emoji, note=None, luck=False, guid=None, doodle=None):
        sent.append((to, emoji, note, luck, guid))
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    cl.send_cheer = send_cheer
    saved = (S.client, S._bg, S.tooltip, A.swap, dict(_state))
    try:
        S.client = lambda: cl
        S._bg = lambda job, done=None: done(job()) if done else job()
        S.tooltip = lambda t, **k: tips.append(t)
        A.swap = lambda c: None
        _state["labels"] = labels
        answers[:] = [TransportError("no network")]
        S._send_cheer("dre", "Dre", "\U0001F389", "go")
        after_net = (S.held_uids(), tips[-1])
        answers[:] = [TransportError("server busy", 503)]
        S._send_cheer("kai", "Kai", "\U0001F525")
        after_5xx = S.held_uids()
        for err in (TransportError("slow down", 429), TransportError("signed out", 401)):
            answers[:] = [err]
            S._send_cheer("max", "Max", "\U0001F389")
        refused = S.held_uids()
        answers[:] = [TransportError("no network")]
        S._send_cheer("dre", "Dre", "\U0001F340", "newer")  # a second to the same crewmate replaces the first
        one_each = [(h["to"], h["emoji"], h["note"]) for h in S.held_cheers()]
        sent.clear()
        answers[:] = [True, TransportError("no network")]  # in the order held: Kai's goes; Dre's gets no answer again
        n = S.send_held(labels[0])
        resend = (n, [s[0] for s in sent], S.held_uids())
        cl.session["cheers_held"]["list"][0]["day"] = (TODAY - datetime.timedelta(days=4)).isoformat()
        sent.clear()
        stale = (S.send_held(labels[0]), sent[:], S.held_uids())
        cl.session["cheers_held"] = {"uid": "someone-else", "list": [{"to": "dre", "emoji": "x", "day": labels[0]}]}
        other = (S.held_uids(), S.send_held(labels[0]))
    finally:
        S.client, S._bg, S.tooltip, A.swap = saved[:4]
        _state.clear()
        _state.update(saved[4])
    check("offline: no answer holds a cheer, and says so with who it's for",
          after_net[0] == {"dre"} and "sends when Due Crew is back" in after_net[1] and "Dre" in after_net[1], after_net)
    check("offline: the server away (5xx) holds one too; a ceiling (429) or a sign-in gone (401) doesn't",
          after_5xx == {"dre", "kai"} and refused == {"dre", "kai"}, (after_5xx, refused))
    check("offline: one held a crewmate, the newest (the server keeps one a pair as well)",
          sorted(one_each) == [("dre", "\U0001F340", "newer"), ("kai", "\U0001F525", "")], one_each)
    check("offline: a refresh that gets through sends each held cheer as it was; one with no answer again waits again",
          resend[0] == 2 and resend[1] == ["kai", "dre"] and resend[2] == {"dre"}, resend)
    check("offline: a cheer held more than three days goes unsent; another sign-in's are never sent",
          stale[0] == 0 and stale[1] == [] and stale[2] == set() and other == (set(), 0), (stale, other))
    src = inspect.getsource(dc._sync_failed) + inspect.getsource(dc._commit) + inspect.getsource(dc._after_push)
    check("offline: a refresh with no answer sets the line (not when the sign-in's gone); any answer clears it and "
          "sends what's held",
          '_state["offline"] = not client().session_dead' in inspect.getsource(dc._sync_failed)
          and "offline=False" in inspect.getsource(dc._commit) and src.count("send_held(labels[0])") == 2
          and 'offline=bool(_state.get("offline"))' in inspect.getsource(dc._board_html))
def test_know_when_it_breaks_v399():
    """3.9.9, Know when it breaks (Sam's sign-off): each install counts its
    own failures by code, never by content (errs.py); the first sync after a
    day ends sends that day's counts once, behind Privacy's switch, and only
    to a Worker that has said it takes them (errs_flow.py, api.push). The
    Worker's side is restated in tests/fakes.py and proved in
    worker/test/field.test.ts."""
    import contextlib
    import io
    import time as _time
    from urllib.parse import quote
    import due_crew as dc
    from due_crew import app as appmod, errs, errs_flow, sheets, team_flow
    from due_crew.backend.shapes import TransportError
    from due_crew.planner import remote
    from aqt.deckbrowser import DeckBrowser
    CARD = "The external iliac artery <b>becomes</b> the femoral · Sam's /Users/sam/Anki"
    WORDS = ("iliac", "femoral", "Sam's", "Users", "becomes", "secret", "ZZCODE", "<b>", "artery")
    was = dict(errs._now)
    tmp = tempfile.mkdtemp()
    t = errs.Tally(os.path.join(tmp, "errs.json"))
    errs.use(t, on=True)
    errs.after(None)
    seen = []  # every code counted here, for the last check
    add = t.add
    t.add = lambda code, day, n=1: (seen.append(code), add(code, day, n))[1]
    col_was, state_was = dc.mw.col, dc.mw.state
    dc.mw.col, dc.mw.state = None, "deckBrowser"  # the day as errs.set_day says it, no collection to read

    real = (datetime.datetime.now() - datetime.timedelta(hours=4)).date()
    D, Y, Y2 = real.isoformat(), (real - datetime.timedelta(days=1)).isoformat(), (real - datetime.timedelta(days=2)).isoformat()
    errs.set_day(_time.time() + 3600, D)  # today is D for an hour (mw.col is none here)
    try:
        # ---- codes: the alphabet, and built from our own names ----
        check("errs: a code is [a-z0-9_.:-], 80 at most; anything else is none",
              errs.clean_code("save:bad_plan") == "save:bad_plan" and errs.clean_code("x" * 80) == "x" * 80
              and not any(errs.clean_code(c) for c in ("x" * 81, "Save:x", "req:/plans", "a b", "", "py:é", None, 7)))
        check("errs: req codes name the route as the Worker does, never an id, a code or a query",
              errs.req_code("/plans/p123secret/notes/77", 400) == "req:plans.:id.notes.:n:400"
              and errs.req_code("/plans/trees", 500) == "req:plans.trees:500"
              and errs.req_code("/plans/mine", 404) == "req:plans.mine:404"
              and errs.req_code("/board?decks=1&wk=2026-W45&got=9&pv=abc", "offline") == "req:board:offline"
              and errs.req_code("/codes/ZZCODE99/add", 404) == "req:codes.:code.add:404"
              and errs.req_code("/squads/s1/members/u2", 403) == "req:squads.:id.members.:id:403"
              and errs.req_code("/nope/zz", 404) == "req:other:404" and errs.req_code("/sync", 999) == "req:sync:other"
              and errs.req_code("/sync", "timeout") == "req:sync:timeout")
        # the routes are the Worker's: every one of index.ts is one of ROUTES, and none more
        ts = open(os.path.join(REPO, "worker", "src", "index.ts"), encoding="utf-8").read()
        found = set()
        for raw in re.findall(r'(?:authed|open)\("[A-Z]+", r\([`"]([^`"]+)[`"]\)', ts):
            def name(m):
                g = m.group(0)
                return ":code" if ("{1,12}" in g and "A-Za-z0-9" in g) or "A-Za-z]{4}" in g else ":n" if "d{" in g or "[0-9]{1," in g else ":id"
            found.add(re.sub(r"\([^)]*\)", name, raw.replace("${ID}", ":id")))
        check("errs: ROUTES is the Worker's routes (worker/src/index.ts), both ways",
              len(found) > 100 and found == set(errs.ROUTES), sorted(found ^ set(errs.ROUTES)))

        # an exception the add-on caught and printed: where it was and its type, never its message.
        # A sheet's answer whose step raises (sheets.answer catches it), sent as the board sends it
        def boom():
            raise ValueError(CARD)
        board_was = appmod._decks[0]
        appmod._decks[0] = True
        err = io.StringIO()
        try:
            sheets.confirm("Sure?", "x", "Yes", boom)
            sid = next(iter(sheets._open))
            with contextlib.redirect_stderr(err):
                dc._on_js(False, as_board(f"duecrew:sheet:{sid}:" + quote(json.dumps({"ok": True}), safe="")), DeckBrowser())
        finally:
            appmod._decks[0] = board_was
            sheets._open.clear()
        check("errs: a caught exception prints as before (its words on this computer only) and counts by place and type",
              "Traceback" in err.getvalue() and "iliac" in err.getvalue() and t.of(D).get("py:sheets:lambda:valueerror") == 1,
              (t.of(D), err.getvalue()[-200:]))
        ns = {}
        exec(compile("def plan_step():\n    raise KeyError('" + CARD.replace("'", "") + "')\n",
                     os.path.join(errs.ROOT, "planner", "flow.py"), "exec"), ns)
        try:
            ns["plan_step"]()
        except KeyError:
            kind, _e, tb = sys.exc_info()
            deep = errs.py_code(kind, tb)
        try:
            raise TransportError(CARD)
        except TransportError:
            kind, _e, tb = sys.exc_info()
            outside = errs.py_code(kind, tb)
        check("errs: the deepest frame in the add-on's folder, a subfolder's file named with it; none in it is other",
              deep == "py:planner.flow:plan_step:keyerror" and outside == "py:other:other:transporterror", (deep, outside))

        # board commands: a name of the table's with values that don't pass, or one bucket for any other
        dc._on_js(False, as_board("duecrew:iliacsecret:" + quote(CARD, safe="")), DeckBrowser())
        dc._on_js(False, as_board("duecrew:femoralsecret"), DeckBrowser())
        dc._on_js(False, as_board("duecrew:sort:nonsense"), DeckBrowser())
        Previewer = type("Previewer", (), {})
        dc._on_js(False, "duecrew:arterysecret:x", Previewer())  # a card's page: refused before the table, not counted
        check("errs: cmd:<name>:bad for the table's own name, cmd:unknown for any other (it could be a card's), "
              "and a card page's message is no board command",
              t.of(D).get("cmd:unknown") == 2 and t.of(D).get("cmd:sort:bad") == 1, t.of(D))

        # requests that failed, through the client against the fake Worker
        store = world({"sam": "Sammy", "dre": "Dre"})
        store.today = D
        cl = new_client(store, "sam", "Sammy")
        labels = [D, Y]
        store.fail_status = 503
        try:
            cl.plan("psecret123")
        except TransportError:
            pass
        store.fail_status = None
        for down in (True, "connect"):
            store.down = down
            try:
                cl.fetch_board(labels)
            except TransportError:
                pass
        store.down = False
        cl.add_friend("ZZCODE99")
        check("errs: a request that failed, by route and status, offline or timeout; once each, not once a try",
              t.of(D).get("req:plans.:id:503") == 1 and t.of(D).get("req:board:offline") == 1
              and t.of(D).get("req:board:timeout") == 1 and t.of(D).get("req:codes.:code.add:404") == 1, t.of(D))

        # a plan save the server refused: its error when the window has words for it, else save:other
        pid, _c = store.add_plan("sam", "Heme", "Big Step 1", _plan_units())
        said = remote.save(new_client(store, "dre", "Dre"), pid, 1, {"deck": "Big Step 1", "units": []}, "x")
        remote._refused({"error": "<b>" + CARD})
        remote._view(400, {"error": "not_owner"})
        refused = [c for c in t.of(D) if c.startswith("save:")]
        check("errs: a refused save is save:<its error>, a word of the window's; any other error is save:other",
              said[0] == "refused" and "save:other" in refused and "save:not_owner" in refused
              and all(c[5:] in remote.SAVE_CODES or c == "save:other" for c in refused) and len(refused) == 3, refused)

        # ---- the tally: caps, days, the file ----
        cap = errs.Tally()
        for i in range(60):
            cap.add(f"c{i}", Y)
        cap.add("c0", Y, 20000)
        cap.add("Not A Code", Y)
        day = cap.of(Y)
        check("errs: 50 codes a day at most (the 50th holds the rest), each count at most 9,999, no code that isn't one",
              len(day) == 50 and day["errs:more"] == 11 and day["c0"] == 9999 and "c55" not in day, (len(day), day.get("errs:more")))
        held = errs.Tally()
        for n in range(11):
            held.add("a", (real - datetime.timedelta(days=n)).isoformat())
        ready = held.ready(D)
        check("errs: today and the 7 days before are held; a sync sends the 7 that are over, older ones go unsent",
              len(held.days) == 8 and sorted(ready) == [(real - datetime.timedelta(days=n)).isoformat() for n in range(7, 0, -1)]
              and D not in ready, sorted(held.days))
        path = os.path.join(tmp, "bad.json")
        with open(path, "w") as f:
            json.dump({"v": 1, "days": {Y: {"ok:a": 2, "Bad Code": 1, "z": 0, "y": "3", "w": True}, "nope": {"a": 1}}}, f)
        with open(os.path.join(tmp, "junk.json"), "w") as f:
            f.write("{not json")
        t.save()
        check("errs: kept in a small file, read back as written; a file not ours, or bad parts of one, read as nothing",
              errs.Tally(t.path).days == t.days and errs.Tally(path).days == {Y: {"ok:a": 2}}
              and errs.Tally(os.path.join(tmp, "junk.json")).days == {})

        # ---- the day: Anki's, from any thread ----
        errs.set_day(1_800_000_000, "2026-11-07")
        rolled = (errs.today(1_800_000_000 - 1), errs.today(1_800_000_000), errs.today(1_800_000_000 + 2 * 86400 + 5))
        errs.set_day(_time.time() - 1, Y)  # the rollover just passed, and nobody read the collection since
        errs.count("rollover:test")
        errs.set_day(_time.time() + 3600, D)
        check("errs: a count lands on Anki's day: the cutoff last read, a day on for each day past it",
              rolled == ("2026-11-07", "2026-11-08", "2026-11-10") and t.of(D).get("rollover:test") == 1
              and "rollover:test" not in t.of(Y), rolled)

        # ---- sending: once, finished days only, only to a Worker that takes them ----
        conf = {}
        V = errs.clean_version(appmod.ADDON_VERSION)
        glue = (appmod.client, appmod.cfg, sheets.confirm)
        shown = []
        appmod.client, appmod.cfg = (lambda: cl), (lambda: conf)
        sheets.confirm = lambda title, text, yes, then, **k: shown.append((title, text))
        try:
            t.clear()
            t.add("save:bad_plan", Y, 2)
            t.add("req:plans.:id:400", Y, 2)
            t.add("py:plan_flow:maybe_morning:keyerror", Y2)
            t.add("cmd:unknown", D)
            cl.session.pop("errs_ok", None)
            gate = errs_flow.for_sync(conf)
            errs_flow.see_what_went()
            check("errs: before /board says the Worker takes them, none go, and See what went says why",
                  gate == {} and "server doesn't take them yet" in shown[-1][1], shown[-1])
            cl.fetch_board(labels)
            check("errs: /board's errs: true is kept in the session", cl.session.get("errs_ok") is True)
            dc._on_js(False, as_board("duecrew:errsee"), DeckBrowser())  # Settings › Privacy's See what went
            title, text = shown[-1]
            sending = errs_flow.for_sync(conf)
            n = len(store.log)
            ok, _gone = cl.push(labels, conf, stats=types.SimpleNamespace(reviews=3, time_ms=60000, accuracy=90.0, streak=2,
                                                                         new_cards=0), version="3.9.9", **sending)
            body = store.bodies[-1][2]
            listed, at = {}, None
            for line in text.split("\n"):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", line):
                    at = line
                elif " × " in line and at:
                    code, count = line.rsplit(" × ", 1)
                    listed.setdefault(at, {})[code] = int(count.replace(",", ""))
            check("errs: the day's first sync carries the days that are over, in one request; today's wait",
                  ok and len(store.log) - n == 1 and store.log[-1][:2] == ("POST", "/sync")
                  and body["errs"]["days"] == {Y: {"save:bad_plan": 2, "req:plans.:id:400": 2},
                                               Y2: {"py:plan_flow:maybe_morning:keyerror": 1}}
                  and body["errs"]["v"] == V, body.get("errs"))
            check("errs: See what went lists exactly what that sync sent",
                  title == errs.SHEET_TITLE and listed == body["errs"]["days"] and f"Due Crew {body['errs']['v']}" in text,
                  (listed, text))
            check("errs: the Worker (the fake) keeps them added up, a person once, no uid",
                  store.field[(Y, V, "save:bad_plan")] == [2, 1]
                  and all("sam" not in k for key in store.field for k in key))
            check("errs: once sent they're gone; today's are still kept", sorted(t.days) == [D], sorted(t.days))
            cl.push(labels, conf, version="3.9.9", **errs_flow.for_sync(conf))
            check("errs: the day's next sync carries none", "errs" not in store.bodies[-1][2])
            errs.set_day(_time.time() + 3600, (real + datetime.timedelta(days=1)).isoformat())
            store.today = (real + datetime.timedelta(days=1)).isoformat()
            cl.push(labels, conf, version="3.9.9", **errs_flow.for_sync(conf))
            check("errs: the next day's first sync carries the day before",
                  store.bodies[-1][2].get("errs", {}).get("days") == {D: {"cmd:unknown": 1}} and t.days == {})
            nxt = (real + datetime.timedelta(days=1)).isoformat()

            # a lost reply: it landed, so it never goes again (a person's day counts once); never got out, it goes later
            t.add("lost:reply", D)
            sending = errs_flow.for_sync(conf)
            store.lose_replies, n = 1, len(store.log)
            ok, _gone = cl.push(labels, conf, version="3.9.9", **sending)
            check("errs: an answer that never came: the counts are taken as sent, the rest goes once more",
                  ok and len(store.log) - n == 2 and "errs" not in store.bodies[-1][2] and D not in t.days
                  and store.field[(D, V, "lost:reply")] == [1, 1], (store.log[-2:], t.days))
            t.add("never:out", D)
            store.down = "connect"
            try:
                cl.push(labels, conf, version="3.9.9", **errs_flow.for_sync(conf))
            except TransportError:
                pass
            store.down = False
            errs_flow._flying.clear()  # the next sync is more than a push's while later
            cl.push(labels, conf, version="3.9.9", **errs_flow.for_sync(conf))
            check("errs: a sync that never got out keeps them, and the next one sends them",
                  store.field.get((D, V, "never:out")) == [1, 1] and D not in t.days, t.days)
            t.add("two:syncs", D)
            first, second = errs_flow.for_sync(conf), errs_flow.for_sync(conf)
            check("errs: two syncs at once don't both send a day", bool(first) and second == {})
            first["errs_sent"]()

            # a Worker put back to one from before: its sync turns errs away; the rest goes, and none till it says so
            store.takes_errs = False
            t.add("old:worker", D)
            sending = errs_flow.for_sync(conf)
            n = len(store.log)
            ok, _gone = cl.push(labels, conf, version="3.9.9", **sending)
            check("errs: an older Worker refuses a sync with errs: sent again without them, the flag off, the counts kept",
                  ok and len(store.log) - n == 2 and cl.session.get("errs_ok") is False and "errs" not in store.bodies[-1][2]
                  and t.of(D).get("old:worker") == 1, store.log[-2:])
            cl.fetch_board(labels)
            errs_flow._flying.clear()
            n = len(store.log)
            ok, _gone = cl.push(labels, conf, version="3.9.9", errs={"days": {D: {"old:worker": 1}}, "v": "3.9.9"})
            check("errs: without the flag nothing goes, whatever's handed to the push: one request, no errs",
                  ok and len(store.log) - n == 1 and "errs" not in store.bodies[-1][2] and errs_flow.for_sync(conf) == {})
            store.takes_errs = True
            cl.fetch_board(labels)
            dropped = []
            n = len(store.log)
            ok, _gone = cl.push(labels, conf, version="3.9.9", errs={"days": {"nope": {"a": 1}}, "v": "3.9.9"},
                                errs_sent=lambda: dropped.append(1))
            check("errs: counts the Worker won't take (bad_errs) go no further; the sync goes without them",
                  ok and dropped == [1] and len(store.log) - n == 2 and "errs" not in store.bodies[-1][2])
            t.clear()

            # Privacy's switch: off, nothing is counted, kept or sent
            t.add("before:off", Y)
            saved = (dc._swap, dc.cfg, dc.save_cfg)
            dc._swap, dc.cfg, dc.save_cfg = (lambda c, focus=None: None), (lambda: conf), (lambda c, **k: None)
            try:
                dc._on_js(False, as_board("duecrew:set:send_errs:0"), DeckBrowser())
            finally:
                dc._swap, dc.cfg, dc.save_cfg = saved
            errs.count("while:off")
            cl.push(labels, conf, version="3.9.9", **errs_flow.for_sync(conf))
            errs_flow.see_what_went()
            check("errs: Send what went wrong off (its switch, through the board): nothing kept, counted or sent",
                  conf.get("send_errs") is False and t.days == {} and "errs" not in store.bodies[-1][2]
                  and "is off" in shown[-1][1], (conf, t.days, shown[-1]))
            conf["send_errs"] = True
            errs.switch(True)
            errs.count("back:on")
            check("errs: on again, it counts from then", t.days == {nxt: {"back:on": 1}}, t.days)
            t.clear()
        finally:
            appmod.client, appmod.cfg, sheets.confirm = glue

        # the glue: _on_sync_done hands the push what for_sync gives
        pushes = []
        names = ("client", "cfg", "_profile_files", "_awaiting_phone", "refresh_board", "_pushed", "_closing", "_last_attempt")
        saved = {k: getattr(dc, k) for k in names}
        saved_mods = (dc.mw.col, dc.account.ready, dc.plan_flow.for_sync, dc.plan_flow.maybe_morning, dc.crew_cards.for_sync,
                      dc.bingo_flow.for_row, team_flow.for_sync, errs_flow.for_sync)
        dc.mw.col, dc.client, dc.cfg, dc._profile_files = make_user_col([TODAY]), (lambda: cl), (lambda: {}), (lambda: tmp)
        dc._awaiting_phone = lambda: False
        dc.account.ready = lambda: True
        dc.refresh_board = lambda **kw: pushes.append(kw)
        dc.plan_flow.for_sync = lambda: None
        dc.plan_flow.maybe_morning = lambda *a, **k: None
        dc.crew_cards.for_sync = lambda c, light=False: {"stuck": ["g1"]}
        dc.bingo_flow.for_row = lambda c: None
        team_flow.for_sync = lambda c: None
        marker = object()
        errs_flow.for_sync = lambda c: {"errs": {"days": {Y: {"a": 1}}, "v": "3.9.9"}, "errs_sent": marker}
        try:
            dc._on_sync_done(light=True)
            errs_flow.for_sync = lambda c: {}
            dc._on_sync_done(light=True)
        finally:
            for k, v in saved.items():
                setattr(dc, k, v)
            (dc.mw.col, dc.account.ready, dc.plan_flow.for_sync, dc.plan_flow.maybe_morning, dc.crew_cards.for_sync,
             dc.bingo_flow.for_row, team_flow.for_sync, errs_flow.for_sync) = saved_mods
        check("errs: a sync's extras carry for_sync's errs beside the rest, and nothing when it has none",
              len(pushes) == 2 and pushes[0]["extras"]["errs_sent"] is marker and pushes[0]["extras"]["stuck"] == ["g1"]
              and "errs" not in pushes[1]["extras"], [p.get("extras") for p in pushes])

        # the Privacy row and its default
        from due_crew import account, settings_model
        on_html = board.settings_html({"tab": "privacy", "signed_in": True}, {})
        off_html = board.settings_html({"tab": "privacy", "signed_in": True}, {"send_errs": False})
        check("errs: Privacy's row: Send what went wrong, its line, See what went, the switch as set (on by default)",
              "Send what went wrong, and what gets used" in on_html and "Never your cards, plans or crew." in on_html
              and "duecrew:errsee" in on_html and "duecrew:set:send_errs:0" in on_html and "duecrew:set:send_errs:1" in off_html
              and errs.wanted({}) is errs.SEND_DEFAULT and errs.SEND_DEFAULT is True)
        check("errs: the switch is the account's (every computer), a Settings switch, never Reset board's",
              "send_errs" in account.ACCOUNT_KEYS and account.clean({"send_errs": False}) == {"send_errs": False}
              and settings_model.change(["set", "send_errs", "0"], {}) == {"send_errs": False}
              and "send_errs" not in settings_model.change(["setreset"], {}))
        idx = board.settings_index({"signed_in": True}, {})
        check("errs: Find a setting finds it", any(x["l"] == "Send what went wrong, and what gets used" and "errors" in x["k"] for x in idx)
              and any(x["l"] == "See what went" for x in idx))

        # nothing a card or a request said is in any code made here, or in what went
        made = set(seen) | {k[2] for k in store.field}
        sent = json.dumps([b for m, p, b in store.bodies if p == "/sync" and b and "errs" in b])
        check("errs: no code carries a message, a card's words, a command a card sent, an id or a friend code",
              made and all(errs.clean_code(c) for c in made)
              and not any(w.lower() in (c + sent).lower() for c in made for w in WORDS), sorted(made))
    finally:
        errs._now.clear()
        errs._now.update(was)
        errs_flow._flying.clear()
        dc.mw.col, dc.mw.state = col_was, state_was


def test_in_the_field_panel_v399():
    """3.9.9: the admin Inbox's In the field, yesterday (fieldPanel in
    site/public/app.js), run in node on a small DOM: a code a row with its
    counts and versions, the line of codes new since the day before, and
    what the server sends set as text, never as HTML. Needs node."""
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        print("SKIP In the field panel: no node")
        return
    js = open(os.path.join(REPO, "site", "public", "app.js"), encoding="utf-8").read()
    src = (js[js.index("function h(tag, attrs, ...kids) {"):js.index("function page(")]
           + js[js.index("const MONTHS ="):js.index("\n", js.index("const DAYS ="))] + "\n"
           + js[js.index("function fieldPanel() {"):js.index("/** 3.8.1 (the audit): reports, kept for the admin")])
    dom = r"""
class Node { constructor() { this.kids = []; }
  append(...k) { for (const x of k) this.kids.push(x instanceof Node ? x : new Text(String(x))); }
  replaceChildren(...k) { this.kids = []; this.append(...k); }
  get textContent() { return this.kids.map((c) => c.textContent).join(""); } }
class Text extends Node { constructor(t) { super(); this.t = t; } get textContent() { return this.t; } }
class El extends Node { constructor(tag) { super(); this.tag = tag; this.className = ""; this.attrs = {}; }
  setAttribute(k, v) { this.attrs[k] = v; } addEventListener() {} }
globalThis.Node = Node;
globalThis.document = { createElement: (t) => new El(t) };
const tags = (n) => (n instanceof El ? [n.tag, ...n.kids.flatMap(tags)] : []);
const text = (n) => n.textContent;
"""
    days = {"day": "2026-11-07", "before": "2026-11-06", "beforeCodes": 2,
            "rows": [{"code": "save:bad_plan", "n": 345, "people": 3, "versions": ["3.9.10", "3.9.9"]},
                     {"code": "<img src=x onerror=alert(1)>", "n": 1, "people": 1, "versions": ["3.9.9"]}],
            "new": ["<img src=x onerror=alert(1)>"]}
    cases = [days, dict(days, beforeCodes=0, new=[r["code"] for r in days["rows"]]),
             {"day": "2026-11-07", "before": "2026-11-06", "beforeCodes": 0, "rows": [], "new": []},
             dict(days, new=[])]
    prog = (dom + src + "\nconst cases = " + json.dumps(cases) + ";\n(async () => { const out = [];"
            " for (const c of cases) { globalThis.api = async () => c; const box = fieldPanel();"
            " await new Promise((r) => setTimeout(r, 0)); out.push({ text: text(box), tags: tags(box) }); }"
            " console.log(JSON.stringify(out)); })();")
    run = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    try:
        got = json.loads(run.stdout)
    except ValueError:
        got = None
    ok = isinstance(got, list) and len(got) == 4
    full, fresh, empty, same = got if ok else ({}, {}, {}, {})
    check("in the field: yesterday's codes, a row each, most first, with times, people and versions",
          ok and "In the field, yesterday" in full["text"] and "Sat 7 Nov · 2 codes" in full["text"]
          and "save:bad_plan34533.9.10, 3.9.9" in full["text"], (got, run.stderr[-400:]))
    check("in the field: a line for the codes new since the day before; none to compare with, it says so; none new, it says so",
          ok and "New since Fri 6 Nov: <img src=x onerror=alert(1)>" in full["text"]
          and "Nothing came in for Fri 6 Nov, so nothing to compare with." in fresh["text"] and "New since" not in fresh["text"]
          and "Nothing new since Fri 6 Nov." in same["text"], got)
    check("in the field: an empty day says so, with no stray null",
          ok and "Nothing went wrong, or nothing has come in yet." in empty["text"] and "null" not in empty["text"]
          and "undefined" not in "".join(g["text"] for g in got), got)
    check("in the field: what the server sends is text, never HTML (no element made from it); the Inbox opens with it",
          ok and "img" not in sum((g["tags"] for g in got), []) and full["tags"].count("code") == 2
          and "fieldPanel()" in js[js.index("inbox: ["):js.index("\n", js.index("inbox: ["))], got)


def test_plan_exam_asked_once_v399():
    """3.9.9 (Sam: "when a plan sets an exam date … it should show for the
    folks following it"; his pick B, "Exams and Limits"): an author marks
    an event the exam; a follower's plan card asks, once, "Heme–Onc block
    exam is Fri 12 Dec. Make it your exam?" Make it mine sets my exam to it
    (the crew's countdown, the good-luck card) and remembers the plan; Not
    now only remembers it asked. My own exam ahead wins and nothing is
    asked, but one that came from the plan is asked about again when the
    plan's exam moves."""
    from due_crew import plans as P, plan_flow as F, account, app as A
    from due_crew.app import _state
    today = TODAY.isoformat()
    d = lambda n: (TODAY + datetime.timedelta(days=n)).isoformat()  # noqa: E731
    plan = lambda pid, name, evs: {"id": pid, "name": name, "doc": {"deck": "d", "units": [], "events": evs}}  # noqa: E731
    heme = plan("p1", "Heme-Onc", [{"id": "q", "day": d(10), "name": "Heme quiz"},
                                   {"id": "x", "day": d(33), "name": "Heme-Onc block exam", "kind": "exam"}])
    renal = plan("p2", "Renal", [{"id": "y", "day": d(60), "name": "Renal exam", "kind": "exam"}])
    old = plan("p3", "Cardio", [{"id": "z", "day": d(-2), "name": "Cardio exam", "kind": "exam"}])
    o = P.exam_offer([renal, heme, old], "", today)
    check("exam: the soonest exam ahead across the plans I follow is asked about; a quiz, or one passed, never",
          o == {"pid": "p1", "name": "Heme-Onc", "day": d(33), "ename": "Heme-Onc block exam", "was": ""}, o)
    check("exam: once asked about at that day, the next plan's comes up; asked about both, nothing",
          P.exam_offer([renal, heme], "", today, {"p1": d(33)})["pid"] == "p2"
          and P.exam_offer([renal, heme], "", today, {"p1": d(33), "p2": d(60)}) is None)
    check("exam: my own exam ahead wins: nothing is asked; one passed doesn't count",
          P.exam_offer([heme], d(20), today) is None and P.exam_offer([heme], d(-1), today)["pid"] == "p1")
    check("exam: it's my exam already: nothing", P.exam_offer([heme], d(33), today) is None)
    moved = plan("p1", "Heme-Onc", [{"id": "x", "day": d(36), "name": "Heme-Onc block exam", "kind": "exam"}])
    mv = P.exam_offer([moved], d(33), today, {"p1": d(33)}, {"pid": "p1", "day": d(33)})
    check("exam: made mine, then moved by its author: asked again, with my day", mv and mv["day"] == d(36) and mv["was"] == d(33), mv)
    check("exam: …not when I'd set my own day since (it didn't come from the plan any more)",
          P.exam_offer([moved], d(40), today, {"p1": d(33)}, {"pid": "p1", "day": d(33)}) is None)
    check("exam: …and asked about at the new day, not again",
          P.exam_offer([moved], d(33), today, {"p1": d(36)}, {"pid": "p1", "day": d(33)}) is None)
    check("exam: the two settings keys clean to their shapes and ride the account",
          P.clean_exam_from({"pid": "p1", "day": d(3), "x": 1}) == {"pid": "p1", "day": d(3)} and P.clean_exam_from({"pid": "", "day": d(3)}) is None
          and P.clean_exam_asked({"p1": d(3), "p2": "soon", 5: d(1)}) == {"p1": d(3)}
          and len(P.clean_exam_asked({f"p{i}": d(1) for i in range(90)})) == P.EXAM_ASKED_MAX
          and {"exam_from", "exam_asked"} <= set(account.ACCOUNT_KEYS)
          and account.clean({"exam_from": {"pid": "p1", "day": d(3)}, "exam_asked": {"p1": d(3)}})
          == {"exam_from": {"pid": "p1", "day": d(3)}, "exam_asked": {"p1": d(3)}})
    card = {"id": "p1", "title": "Heme-Onc", "exam_ask": dict(o, ename="<b>Block</b> exam")}
    html_ = board._exam_ask(card, "p1")
    check("exam: the card's line asks it, the exam's name escaped, both ways answered by the board's own commands",
          "&lt;b&gt;Block&lt;/b&gt; exam is <b>" in html_ and "Make it your exam?" in html_ and "Make it mine" in html_
          and "Not now" in html_ and "duecrew:planexam:yes:p1|" in html_ and "duecrew:planexam:no:p1|" in html_, html_)
    mv_html = board._exam_ask({"exam_ask": dict(mv, ename="Heme-Onc block exam")}, "p1")
    check("exam: moved: Move mine, or keep my day", "moved to <b>" in mv_html and "Move mine" in mv_html and "Keep " in mv_html, mv_html)
    check("exam: no question, no line", board._exam_ask({"id": "p1"}, "p1") == "")

    # answering it, through the board's command
    cfgs, tips = [{"exam_date": ""}], []
    saved = (F.followed, F.cfg, F.save_cfg, F.tooltip, A.swap, dict(_state))
    try:
        F.followed = lambda: [heme, renal]
        F.cfg = lambda: dict(cfgs[-1])
        F.save_cfg = lambda c: cfgs.append(dict(c))
        F.tooltip = lambda t, **k: tips.append(t)
        A.swap = lambda c: None
        _state["labels"] = [today]
        F.on_message("planexam", ["duecrew", "planexam", "no", "p1"])
        after_no = dict(cfgs[-1])
        F.on_message("planexam", ["duecrew", "planexam", "yes", "p2"])
        after_yes = dict(cfgs[-1])
        n = len(cfgs)
        F.on_message("planexam", ["duecrew", "planexam", "yes", "p2"])
        again = len(cfgs) == n
    finally:
        F.followed, F.cfg, F.save_cfg, F.tooltip, A.swap = saved[:5]
        _state.clear()
        _state.update(saved[5])
    check("exam: Not now remembers it was asked, and sets nothing",
          after_no.get("exam_asked") == {"p1": d(33)} and not after_no.get("exam_date") and not after_no.get("exam_from"), after_no)
    check("exam: Make it mine sets my exam to it (Settings' own setexam), remembers the plan, says so; asked again: nothing",
          after_yes.get("exam_date") == d(60) and after_yes.get("exam_from") == {"pid": "p2", "day": d(60)}
          and after_yes.get("exam_asked") == {"p1": d(33), "p2": d(60)} and tips and "Your exam:" in tips[-1] and again, after_yes)
    store = world({"priya": "Priya"})
    cl = new_client(store, "priya", "Priya")
    pid = cl._call("POST", "/plans", {"name": "Heme-Onc", "deck": "d"})[1]["id"]
    ok = cl._call("PUT", f"/plans/{pid}", {"version": 1, "doc": {"deck": "d", "units": [], "events": [
        {"id": "x", "day": d(33), "name": "Block exam", "kind": "exam"}]}})[0]
    bad = []
    for ev in ({"id": "x", "day": d(33), "name": "Block exam", "kind": "quiz"}, {"id": "x", "day": d(33), "name": "E", "big": 1}):
        try:
            bad.append(cl._call("PUT", f"/plans/{pid}", {"version": 2, "doc": {"deck": "d", "units": [], "events": [ev]}})[0])
        except Exception as e:
            bad.append(getattr(e, "status", "raised"))
    check("exam: the fake server keeps the mark, and takes no other kind or field (worker/test/exam.test.ts's twin)",
          ok == 200 and store.plans[pid]["doc"]["events"][0].get("kind") == "exam" and bad == [400, 400], (ok, bad))


def test_insights_only_when_something_changed_v399():
    """3.9.9's review: Insights took seconds of the log on a big deck, again
    every ten minutes. Past its ten minutes it is worked out again only when
    the collection changed (its stamp); and the three slow reads of the log
    give what the old ones gave."""
    import sqlite3
    from due_crew import team_flow as TF
    from due_crew.app import _state
    import due_crew as dc
    stamp, calls = [(1, 2, 3, 4, 5)], []
    db = types.SimpleNamespace(first=lambda sql: stamp[0])
    saved = (TF.cfg, TF._work_out, dc.mw.col, _state.get("insights"))
    try:
        TF.cfg = lambda: {}
        TF._work_out = lambda did, pid=None, exam="": calls.append(did) or {"n": len(calls)}
        dc.mw.col = types.SimpleNamespace(db=db, sched=types.SimpleNamespace(day_cutoff=100))
        _state["insights"] = {}
        a = TF.insights(7)
        _state["insights"][7]["at"] -= TF.INSIGHTS_FRESH + 1
        b = TF.insights(7)
        _state["insights"][7]["at"] -= TF.INSIGHTS_FRESH + 1
        stamp[0] = (1, 9, 3, 4, 5)  # an answer since
        c = TF.insights(7)
        db.first = lambda sql: 1 / 0  # a stamp that can't be read: worked out, as before
        _state["insights"][7]["at"] -= TF.INSIGHTS_FRESH + 1
        d = TF.insights(7)
        check("insights: kept past ten minutes while nothing changed; again after an answer, or when the stamp can't be read",
              (a, b, c, d) == ({"n": 1}, {"n": 1}, {"n": 2}, {"n": 3}), (a, b, c, d))
        # Pip Party's tab asks the same thing before it shows (a loading screen or not), and keeps its own
        # reading of every card's tags by the same stamp
        import time
        from due_crew import gamenight_flow as GF, app as A
        db.first = lambda sql: stamp[0]
        _state["insights"] = {}
        TF.insights(7)
        _state["insights"][7]["at"] -= TF.INSIGHTS_FRESH + 1
        same = TF.insights_ready(7)
        stamp[0] = (1, 10, 3, 4, 5)
        moved = TF.insights_ready(7)
        was = GF.TAB.get("corpus")
        try:
            old = time.time() - GF.CORPUS_FOR - 5
            GF.TAB["corpus"] = (A.generation, old, {"rows": []}, TF._stamp())
            kept_ = GF._kept(GF.TAB["corpus"]) and GF.TAB["corpus"][1] > old
            GF.TAB["corpus"] = (A.generation, old, {"rows": []}, (0,))
            changed = GF._kept(GF.TAB["corpus"])
            other = GF._kept((A.generation - 1, time.time(), {"rows": []}, TF._stamp()))
        finally:
            GF.TAB["corpus"] = was
        check("pip party: past ten minutes its map is at hand while nothing changed (no loading screen, no second read of the tags); "
              "read again after a change, and never another profile's",
              (same, moved, kept_, changed, other) == (True, False, True, False, False), (same, moved, kept_, changed, other))
    finally:
        TF.cfg, TF._work_out, dc.mw.col, _state["insights"] = saved
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE revlog (id INTEGER PRIMARY KEY, cid INTEGER, ease INTEGER, type INTEGER)")
    conn.execute("CREATE INDEX ix_revlog_cid ON revlog (cid)")
    conn.execute("CREATE TABLE cards (id INTEGER PRIMARY KEY)")
    rows = [(10, 1, 3, 0), (60, 1, 1, 1), (70, 1, 3, 1),      # card 1: started before, missed, then right
            (55, 2, 2, 0), (65, 2, 1, 1),                       # card 2: started since, never right in a review
            (20, 3, 0, 4), (58, 3, 3, 1), (80, 3, 4, 1),        # card 3: a manual entry before (ease 0), first answer since
            (30, 4, 3, 1)]                                      # card 4: nothing since
    conn.executemany("INSERT INTO revlog VALUES (?, ?, ?, ?)", rows)
    conn.executemany("INSERT INTO cards VALUES (?)", [(i,) for i in range(1, 6)])
    col = types.SimpleNamespace(db=types.SimpleNamespace(
        list=lambda q, *a: [r[0] for r in conn.execute(q, a)], all=lambda q, *a: conn.execute(q, a).fetchall()))
    old = [r[0] for r in conn.execute("SELECT cid FROM revlog WHERE ease > 0 AND cid IN (1,2,3,4,5) GROUP BY cid HAVING min(id) >= ?", (50,))]
    new = TF._first_since(col, "1,2,3,4,5", 50)
    check("insights: the cards first answered since a day, read from that day on, are the ones the whole log gave",
          sorted(new) == sorted(old) == [2, 3], (new, old))
    old_first = dict(conn.execute("SELECT cid, min(id) FROM revlog WHERE type = 1 AND ease > 1 AND cid IN (1,2,3,4,5) GROUP BY cid"))
    new_first = {c: r for c, r in conn.execute(
        "SELECT c.id, (SELECT r.id FROM revlog r WHERE r.cid = c.id AND r.type = 1 AND r.ease > 1 ORDER BY r.id LIMIT 1) "
        "FROM cards c WHERE c.id IN (1,2,3,4,5)") if r is not None}
    old_last = dict(conn.execute("SELECT cid, max(id) FROM revlog WHERE type = 1 AND ease > 0 AND cid IN (1,2,3,4,5) GROUP BY cid"))
    new_last = {c: r for c, r in conn.execute(
        "SELECT c.id, (SELECT r.id FROM revlog r WHERE r.cid = c.id AND r.type = 1 AND r.ease > 0 ORDER BY r.id DESC LIMIT 1) "
        "FROM cards c WHERE c.id IN (1,2,3,4,5)") if r is not None}
    check("insights: a card's first right review and its last review, read from its own log's ends, are the same",
          new_first == old_first == {1: 70, 3: 58, 4: 30} and new_last == old_last == {1: 70, 2: 65, 3: 80, 4: 30},
          (new_first, old_first, new_last, old_last))


def test_what_gets_used_v399():
    """3.9.9: which parts were opened today, on the error counts' own path:
    "use:<part>" once a day however often, "use:any" beside it; nothing
    before the person has been told, nothing with the switch off, and no
    name on the switch."""
    from due_crew import errs, errs_flow
    saved = dict(errs._now)
    try:
        t = errs.Tally()
        errs.use(t, on=True)
        errs.use_ok(False)
        errs.used("insights")
        untold = dict(t.days)
        errs.use_ok(True)
        for _ in range(3):
            errs.used("insights")
        errs.used(errs.use_of("planopen"))
        errs.used(errs.use_of("cheersend"))
        errs.used("not a part")
        errs.used(None)
        day = errs.today()
        check("used: nothing before being told; then a part once a day however often, use:any once, only parts on the list",
              untold == {} and t.days[day] == {"use:any": 1, "use:insights": 1, "use:plans": 1, "use:cheers": 1}, (untold, t.days))
        check("used: a command's part by its first letters, the longest first; none for a command with no part",
              [errs.use_of(c) for c in ("planteamask", "plan", "duetab", "youins", "insmap", "squadkick", "songuse", "refresh", "css", "")]
              == ["plansquad", "plans", "due", "insights", "insights", "squads", "songs", None, None, None])
        check("used: every code passes the server's rule, and a day's parts fit a day's codes",
              all(errs.clean_code("use:" + p) for p in errs.USE_PARTS) and len(errs.USE_PARTS) < errs.CODES_MAX - 10, errs.USE_PARTS)
        errs.switch(False)
        errs.used("magic")
        check("used: the switch off, nothing counted and what was is gone", t.days == {}, t.days)
        from due_crew import board
        import due_crew as dc
        from aqt.deckbrowser import DeckBrowser
        c = {"send_errs": True}
        line = board.draw._use_line(c)
        words = line + errs.sheet_text({"v": "3.9.9", "days": {"2026-11-09": {"use:any": 1}}})
        check("used: said once in a line at the board's foot (no window): what's new, Privacy and Got it; nobody named",
              "Sam" not in words and "counts which of its parts get opened" in line and "usesee" in line and "usetold" in line
              and "use:any × 1" in words and board.draw._use_line({"send_errs": False}) == ""
              and board.draw._use_line({"send_errs": True, "use_told": True}) == "", line)
        was = (dc.cfg, dc.save_cfg, dc._swap, dc.open_settings, errs_flow.app.cfg, errs_flow.app.save_cfg)
        went = []
        try:
            dc.cfg = errs_flow.app.cfg = lambda: c
            dc.save_cfg = errs_flow.app.save_cfg = lambda x, **k: None
            dc._swap = lambda *a, **k: went.append("swap")
            dc.open_settings = lambda tab=None: went.append(tab)
            errs.switch(True)
            errs.use_ok(False)
            dc._on_js(False, as_board("duecrew:usetold"), DeckBrowser())
            got_it = (c.get("use_told"), errs._now.get("use_ok"), list(went))
            c.pop("use_told")
            dc._on_js(False, as_board("duecrew:usesee"), DeckBrowser())
            check("used: Got it puts the line away and counting starts; Privacy does too, and opens the switch's tab",
                  got_it == (True, True, ["swap"]) and c.get("use_told") is True and went == ["swap", "privacy"], (got_it, went))
        finally:
            dc.cfg, dc.save_cfg, dc._swap, dc.open_settings, errs_flow.app.cfg, errs_flow.app.save_cfg = was
    finally:
        errs._now.clear()
        errs._now.update(saved)


def test_calm_board_v399():
    """3.9.9, the calm board: a new person sees Crew and Today; a part
    stays folded until it has something to show, then says so in one line;
    Show all, Settings and any link to a part let it out for good. Off for
    everyone who had the board before."""
    from due_crew import calm, board, settings_model as SM
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    old = {"hidden_tabs": ["party"]}
    check("calm: off unless asked: the board as it was", board.hidden_tabs(old) == {"party"} and board.draw._calm_line(old) == "")
    c = {"calm": True, "calm_open": [], "calm_news": [], "hidden_tabs": []}
    check("calm: a new person's board: every part but Crew and Today folded, and the way out said",
          board.hidden_tabs(c) == set(calm.PARTS) and "Show all" in board.draw._calm_line(c) and "calmall" in board.draw._calm_line(c))
    check("calm: what's ready: a friend, a squad, a plan, two weeks of reviews; Pip Party never by itself",
          calm.ready({"friends": 0, "squads": 0, "plans": 0, "days": 13}) == []
          and calm.ready({"friends": 2, "squads": 1, "plans": 1, "days": 14}) == ["decks", "squads", "plans", "insights"]
          and calm.ready({"days": None}) == [])
    changed = calm.release(c, calm.ready({"friends": 1, "days": 20}), news=True)
    line = board.draw._calm_line(c)
    check("calm: a part lets itself out once, with its line: its words, Open and its way off",
          changed and board.hidden_tabs(c) == {"squads", "plans", "party"} and "Decks is ready" in line
          and "calmopen:decks" in line and "calmx" in line and not calm.release(c, ["decks"], news=True), line)
    saved = (dc.cfg, dc.save_cfg, dc._swap, dc._cmd_period, dc.due_flow.on_message)
    went = []
    try:
        dc.cfg = lambda: c
        dc.save_cfg = lambda x, **k: None
        dc._swap = lambda *a, **k: went.append("swap")
        dc._cmd_period = lambda cc, p: went.append(("period", p[2]))
        dc.due_flow.on_message = lambda cmd, p: went.append((cmd, p[2]))
        send = lambda m: dc._on_js(False, as_board("duecrew:" + m), DeckBrowser())
        send("calmopen:decks")
        send("calmx")
        after_x = list(c["calm_news"])
        send("calmopen:insights")
        send("calmopen:nonsense")
        check("calm: Open goes to the part and its line goes; x puts the next away; a made-up part is no command",
              went == [("period", "decks"), "swap", ("duetab", "insights")] and after_x == [] and c["calm_news"] == [], (went, c))
        c["calm_news"] = ["insights"]
        send("calmall")
        check("calm: Show all: every tab, the switch off, nothing left to say",
              c["calm"] is False and board.hidden_tabs(c) == set() and board.draw._calm_line(c) == "" and c["calm_news"] == [], c)
    finally:
        dc.cfg, dc.save_cfg, dc._swap, dc._cmd_period, dc.due_flow.on_message = saved
    c2 = {"calm": True, "calm_open": [], "hidden_tabs": []}
    got = SM.change(["settabs", "squads", "1"], c2)
    check("calm: a tab shown by hand in Settings is out for good; the switch is Settings › Board's",
          got.get("calm_open") == ["squads"] and "calm" in SM.SWITCHES and SM.change(["set", "calm", "1"], {}) == {"calm": True}, got)


def test_magic_field_on_the_decks_page_v399():
    """3.9.9 (Sam's pick G2): the Decks page gets Magic search's field after
    Anki's deck list and over its "Studied…" line (the start of
    content.stats), the board after that line; not with Magic search off, not signed out."""
    import due_crew as dc
    from due_crew.app import _state
    store = world({"sam": "Sam"})
    cl = new_client(store, "sam", "Sam")
    conf = {"show_leaderboard": True}
    saved = (dc.cfg, dc.client, dc._board_html, dc._push_if_stale, _state.get("entries"), _state.get("settings_tab"),
             _state.get("closet_open"), _state.get("wrapped_open"), dc.magic_flow.cfg)
    try:
        dc.cfg = dc.magic_flow.cfg = lambda: conf
        dc.client = lambda: cl
        dc._board_html = lambda c: "<div id=\"due-crew\">BOARD</div>"
        dc._push_if_stale = lambda: None
        _state.update(entries=[], settings_tab=None, closet_open=False, wrapped_open=False)
        page = types.SimpleNamespace(tree="<table>DECKS</table>", stats="Studied 9 cards")
        dc._on_render(None, page)
        # (Sam's screenshot: content.tree is inside Anki's <table>, where a div is lifted to above the list)
        st = page.stats
        check("decks page: the field under the deck list (outside Anki's table), over its own line, the board after",
              page.tree == "<table>DECKS</table>" and st.startswith("<style>#dc-mgf") and 'id="dc-mgf"' in st
              and st.index('id="dc-mgf"') < st.index("Studied 9 cards") < st.index("BOARD") and st.endswith("BOARD</div>"), st[:120])
        ph = lambda h: re.search(r'<input type="text"[^>]*placeholder="([^"]*)"', h).group(1)
        page2 = types.SimpleNamespace(tree="", stats="")
        dc._on_render(None, page2)
        check("decks page: one question in the field, the same every time (3.9.10: no sample searches), never cycled",
              ph(st) == dc.board.MAGIC_PROMPT == ph(page2.stats) == "What do you want to study?" and not hasattr(dc.board, "MAGIC_EXAMPLES")
              and "setTimeout(type" not in st and "__EX__" not in st, (ph(st), ph(page2.stats)))
        conf["magic_search"] = False
        page = types.SimpleNamespace(tree="T", stats="S")
        dc._on_render(None, page)
        check("decks page: Magic search off: no field, the board as ever", page.tree == "T" and "BOARD" in page.stats)
        conf["magic_search"] = True
        dc.client = lambda: types.SimpleNamespace(signed_in=False, session_dead=False, deleted_quiet=False)
        page = types.SimpleNamespace(tree="T", stats="S")
        dc._on_render(None, page)
        check("decks page: signed out: no field", page.tree == "T")
    finally:
        (dc.cfg, dc.client, dc._board_html, dc._push_if_stale) = saved[:4]
        dc.magic_flow.cfg = saved[8]
        _state.update(entries=saved[4], settings_tab=saved[5], closet_open=saved[6], wrapped_open=saved[7])


def test_load_across_plans_v399():
    """3.9.9 (plans, what was missing: 2): You › Plans adds up the next
    seven days across plans, reviews and each plan's new cards at my own
    pace; a day half again over my usual is heavy, and its smallest set not
    yet open moves, in one press, to the nearest later day that stays
    under heavy, before its event. My follow only."""
    from due_crew import plans as P, board
    pace = {"new_s": 60, "rev_s": 6, "day_min": 60, "known": True}
    t = _day(0)
    sets = [{"pid": "a", "plan": "Heme", "uid": "h1", "name": "Anemias", "day": t, "ask": 20, "moved": 0, "cap": ""},
            {"pid": "a", "plan": "Heme", "uid": "h2", "name": "Coag", "day": _day(1), "ask": 70, "moved": 0, "cap": ""},
            {"pid": "b", "plan": "Pharm <b>", "uid": "p6", "name": "Pharm 6", "day": _day(1), "ask": 30, "moved": 1, "cap": _day(4)},
            {"pid": "b", "plan": "Pharm <b>", "uid": "p7", "name": "Pharm 7", "day": _day(9), "ask": 30, "moved": 0, "cap": ""}]
    rev = {t: 300, _day(1): 200, _day(2): 500, _day(3): 100, _day(4): 0, _day(20): 900}
    v = P.load_week(sets, rev, t, pace)
    d = v["days"]
    check("load: seven days from today, reviews and each plan's new cards, minutes at my pace",
          len(d) == 7 and d[0]["today"] and [p["pid"] for p in v["plans"]] == ["a", "b"]
          and d[0]["parts"] == [20, 0] and d[0]["rev"] == 300 and d[0]["min"] == 50
          and d[1]["parts"] == [70, 30] and d[1]["min"] == 120 and d[6]["min"] == 0, d[:2])
    check("load: heavy is half again over my usual day, and only with new cards in it",
          [x["heavy"] for x in d] == [False, True, False, False, False, False, False] and v["top"] == 120)
    check("load: a day's shares add up, reviews first", abs(sum(d[1]["share"]) - 1) < 1e-9 and abs(d[1]["share"][0] - 20 / 120) < 1e-9)
    mv = v["hint"]["move"]
    check("load: the hint names the day's cards; the move is its smallest set, to the nearest later day with room before its event, "
          "on top of the days it already runs later",
          v["hint"]["day"] == _day(1) and v["hint"]["new"] == 100 and v["hint"]["plans"] == 2 and v["hint"]["rev"] == 200
          and mv == {"pid": "b", "uid": "p6", "name": "Pharm 6", "to": _day(2), "n": 2}, v["hint"])
    tight = P.load_week([dict(x, cap=_day(2)) if x["uid"] == "p6" else x for x in sets], rev, t, pace)
    check("load: no day before its event stays under heavy with it: the bigger set moves instead",
          tight["hint"]["move"]["uid"] == "h2" and tight["hint"]["move"]["to"] == _day(3), tight["hint"])
    none = P.load_week(sets, {_day(i): 2000 for i in range(7)}, t, pace)
    check("load: nowhere lighter: the line, no move", none["hint"] and none["hint"]["move"] is None)
    today_heavy = P.load_week([dict(x, day=t) if x["uid"] in ("h2", "p6") else x for x in sets], rev, t, pace)
    check("load: today's sets are open already: heavy said, nothing moved", today_heavy["hint"]["day"] == t and today_heavy["hint"]["move"] is None)
    check("load: before my usual day is known nothing is heavy", P.load_week(sets, rev, t, dict(pace, known=False))["hint"] is None)
    check("load: one plan in the week: no view (its own week says it)", P.load_week(sets[:2], rev, t, pace) is None
          and P.load_week([], rev, t, pace) is None)
    back = P.load_week([dict(x, day=_day(3), moved=3) if x["uid"] == "p6" else x for x in sets], rev, t, pace, back=("b", "p6"))
    check("load: after a move, the set and where it went, for Put it back",
          back["back"] == {"pid": "b", "uid": "p6", "name": "Pharm 6", "day": _day(3)} and not back["days"][1]["heavy"], back["back"])
    check("load: a set put back is no longer named", P.load_week(sets, rev, t, pace, back=("b", "p7"))["back"] is None)
    check("load: time words", [P.load_time(x) for x in (0, 45, 60, 130)] == ["0 min", "45 min", "1 h 00", "2 h 10"])
    h = board.plancards._load_html(v)
    check("load: drawn: the key, a row a day, the heavy day's time marked, the move as a command, names escaped",
          h.count('class="lwd') == 7 and 'class="n hv">2 h 00' in h and "planmoveto:b:p6:2" in h and "Pharm &lt;b&gt;" in h
          and "<b>Tomorrow" not in h and "is heavy:</b> 100 new across 2 plans on top of 200 reviews." in h
          and "Move Pharm 6 to " in h and "your own pace" in h, h[-700:])
    hb = board.plancards._load_html(back)
    check("load: drawn after a move: Put it back, on the same screen", "planmoveback:b:p6" in hb and "Pharm 6 moved to " in hb)
    check("load: nothing to show, nothing drawn; a typical pace says so",
          board.plancards._load_html(None) == "" and "typical pace" in board.plancards._load_html(P.load_week(sets, rev, t, dict(pace, known=False))))


def test_insights_a_part_at_a_time_v399():
    """3.9.9 (the performance review): the board's Insights is worked out a
    part at a time, Anki live between parts, and drawn again when done; until
    then the last view (marked working) or a line saying so. Off outside
    Anki's own run (the suite, the tools), where it's worked out whole."""
    from due_crew import team_flow as TF, app as A, board
    from due_crew.app import _state
    import due_crew as dc

    def steps(did, pid=None, exam=""):
        seen.append("a")
        yield
        seen.append("b")
        yield
        return {"n": len(seen)}
    seen, later, swaps = [], [], []
    saved = (TF.cfg, TF._work_steps, TF._later, TF.ASYNC, dc.mw.col, _state.get("insights"), _state.get("ins_job"), A.swap, TF._stamp)
    try:
        TF.cfg = lambda: {}
        TF._work_steps = steps
        TF._later = lambda fn, ms=0: later.append(fn)
        TF._stamp = lambda: (1,)
        A.swap = lambda *a, **k: swaps.append(1)
        dc.mw.col = types.SimpleNamespace()
        _state["insights"], _state["ins_job"] = {}, None
        check("soon: off (the suite, the tools): worked out whole, at once", TF._work_out(7) == {"n": 2} and TF.insights_soon(7) == {"n": 4})
        TF.ASYNC, seen[:] = True, []
        check("soon: the suite's stand-in for Anki says whole", os.environ.get(TF.WHOLE) == "1" and TF.insights_soon(8) == {"n": 2})
        os.environ.pop(TF.WHOLE)
        seen[:] = []
        _state["insights"] = {}
        first = TF.insights_soon(7)
        again = TF.insights_soon(7)
        check("soon: not at hand: a line saying so, one job however often the board draws, nothing worked out yet",
              first == {"working": True} == again and len(later) == 1 and seen == [], (first, later, seen))
        while later:
            later.pop(0)()
        check("soon: a part a turn, then the view kept and the board drawn again",
              seen == ["a", "b"] and swaps == [1] and _state["ins_job"] is None and TF.insights_soon(7) == {"n": 2}, (seen, swaps))
        _state["insights"][7]["at"] -= TF.INSIGHTS_FRESH + 1
        TF._stamp = lambda: (2,)
        stale = TF.insights_soon(7)
        check("soon: changed since: the last view stays up, marked working, while the next is worked out",
              stale == {"n": 2, "working": True} and len(later) == 1, stale)
        A.generation += 1
        later.pop(0)()
        check("soon: the profile changed meanwhile: the job lets go, nothing kept or drawn", _state["ins_job"] is None and swaps == [1])
        A.generation -= 1
        html = board.insights._you_insights({"decks": [{"did": 7, "name": "Deck"}], "did": 7, "view": {"working": True}})
        check("soon: the board's line while it works", "Reading your reviews" in html, html[-120:])
        # warming ahead: quietly, standing back from a card on screen, no redraw at its end
        had = (TF.you_decks, board.hidden_tabs, getattr(dc.mw, "state", None))
        try:
            TF.you_decks = lambda: [{"did": 9, "name": "Deck", "pid": None}]
            board.hidden_tabs = lambda c=None: {"insights"}
            _state["insights"], seen[:], later[:], swaps[:] = {}, [], [], []
            TF.warm()
            check("warm: Insights hidden (Settings, or the calm board): nothing worked out", later == [] and _state["ins_job"] is None)
            board.hidden_tabs = lambda c=None: set()
            TF.warm()
            dc.mw.state = "review"
            later.pop(0)()
            check("warm: a card on screen: it waits, nothing worked out", seen == [] and len(later) == 1)
            dc.mw.state = "deckBrowser"
            while later:
                later.pop(0)()
            check("warm: worked out ahead a part a turn, kept, the board not redrawn; the tab then opens on it at once",
                  seen == ["a", "b"] and swaps == [] and TF.insights_ready(9) and TF.insights_soon(9) == {"n": 2} and later == [])
            TF.warm()
            check("warm: at hand already: nothing started", later == [] and _state["ins_job"] is None)
            _state["insights"], seen[:] = {}, []
            TF.warm()
            got = TF.insights_soon(9)
            while later:
                later.pop(0)()
            check("warm: asked for while warming: the same job, and now the board is drawn again at its end",
                  got == {"working": True} and seen == ["a", "b"] and swaps == [1])
            os.environ[TF.WHOLE] = "1"
            _state["insights"] = {}
            TF.warm()
            check("warm: off outside Anki's own run", later == [])
            os.environ.pop(TF.WHOLE)
        finally:
            TF.you_decks, board.hidden_tabs = had[0], had[1]
            dc.mw.state = had[2]
    finally:
        (TF.cfg, TF._work_steps, TF._later, TF.ASYNC, dc.mw.col, _state["insights"], _state["ins_job"], A.swap, TF._stamp) = saved
        os.environ[TF.WHOLE] = "1"
