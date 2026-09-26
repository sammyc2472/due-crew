"""The real client (due_crew/backend/api.py) against the real Worker, run
locally by wrangler with a local D1. Where the suite's fake and the Worker's
own tests each prove one side, this proves they agree.

    cd worker && npx wrangler d1 migrations apply due-crew --local --env=""
    npx wrangler dev --env="" --local --port 8787 > ../wdev.log 2>&1 &
    cd .. && python3 tools/smoke_worker.py wdev.log

With no RESEND_API_KEY the Worker logs each sign-in code instead of sending
it; this reads them from wrangler's log. Needs `requests`. Exits non-zero
on any failure. CI runs it in the worker job.
"""
import datetime
import os
import re
import sys
import tempfile
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, ROOT)
import fakes  # noqa: E402
fakes.install_fake_aqt()  # enough of aqt for the package to import; the network is real
from due_crew.backend import api, shapes  # noqa: E402

BASE = os.environ.get("DUE_CREW_API", "http://127.0.0.1:8787")
LOG = sys.argv[1] if len(sys.argv) > 1 else "wdev.log"
ok_all = True
def check(name, cond, detail=""):
    global ok_all
    ok_all &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  [{detail}]"))

def code_for():
    for _ in range(50):
        m = re.findall(r"code: (\d{3}) (\d{3})\.", open(LOG).read())
        if m: return "".join(m[-1])
        time.sleep(0.1)

def person(email, name):
    cl = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"), base=BASE)
    cl.request_code(email)
    got = cl.verify_code(email, code_for(), "smoke")
    if got["new"]: cl.set_display_name(name)
    return cl, got

stamp = str(int(time.time()))
sam, g = person(f"sam{stamp}@example.com", "Sam")
check("sign-in: new account, a ULID, a name set", g["new"] and len(g["uid"]) == 26 and sam.display_name == "Sam")
dre, _ = person(f"dre{stamp}@example.com", "Dre")
code = sam.ensure_friend_code(None)
friend, err = dre.add_friend(f"Study with me on Due Crew · my code {code}")
check("code add: knocks the owner", err is None and friend["knocked"] is True, str((friend, err)))
check("knock arrives", [k[0] for k in sam.list_knocks()] == [dre.user_id])
check("add back: mutual", sam.add_back(dre.user_id)["mutual"] is True and sam.list_knocks() == [])

today = datetime.date.today()
labels = [(today - datetime.timedelta(days=i)).isoformat() for i in range(7)]
tomorrow = (today + datetime.timedelta(days=1)).isoformat()
stats = types.SimpleNamespace(reviews=205, time_ms=3600000, accuracy=91.5, streak=12, new_cards=20)
backfill = [{"label": labels[2], "reviews": 50, "time_ms": 1000, "accuracy": None, "streak": 10, "new_cards": 0}]
now = datetime.datetime.now(datetime.timezone.utc)
dre.session["tricky"] = [{"guid": "Ab3$kQ9+zX", "text": "The capital of Kentucky", "deck": "Geo", "at": labels[0]}]
dre.session["live_until"] = (now + datetime.timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
dre.session["room"] = {"host": dre.user_id, "start": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "rounds": 4, "round": 25, "brk": 5}
cfg = {"status": "coffee, then 400", "exam_date": (today + datetime.timedelta(days=9)).isoformat(),
       "away_from": (today + datetime.timedelta(days=2)).isoformat(), "away_to": (today + datetime.timedelta(days=4)).isoformat(),
       "emoji": "🐢"}
decks = [{"name": "AnKing", "sig": ["g1", "g2"], "total": 100, "seen": 40, "mature": 10, "open": 60, "today": 5, "day": labels[0], "ret": 90.1}]
ok, gone = dre.push(labels, cfg, stats=stats, backfill=backfill, shared_decks=decks, heatmap={labels[0]: 205, labels[2]: 50},
                    version="3.0.0", clock={"tz": -240, "rollover": 4})
check("sync: accepted", ok and gone == [], str((ok, gone)))
ok2, _ = dre.push(labels, cfg, stats=stats, version="3.0.0", clock={"tz": -240, "rollover": 4})
check("sync again: accepted", ok2)
data = sam.fetch_board(labels, tomorrow, with_decks=True)
d = next(e for e in data["entries"] if e["user_id"] == dre.user_id)
check("board: dre's today, with new cards and status", d["days"][labels[0]].get("reviews") == 205
      and d["days"][labels[0]].get("newCards") == 20 and d["days"][labels[0]].get("status") == "coffee, then 400", str(d["days"][labels[0]]))
check("board: backfilled day", d["days"][labels[2]].get("reviews") == 50)
check("board: away flags tomorrow+1..", (d["days"].get(tomorrow) or {}).get("away") is not True
      and d["exam_date"] == cfg["exam_date"] and d["emoji"] == "🐢")
check("board: flag without text; live; room", d["tricky"] == [{"guid": "Ab3$kQ9+zX", "deck": "Geo", "at": labels[0]}]
      and shapes.live_now(d["live_until"]) and d["room"]["rounds"] == 4, str(d["tricky"]))
check("board: decks", d["decks"][0]["name"] == "AnKing" and d["decks"][0]["ret"] == 90.1)
check("heatmap", sam.fetch_heatmap(dre.user_id) == {labels[0]: 205, labels[2]: 50})
check("cheer", dre.send_cheer(sam.user_id, "🍀", "Go get it", luck=True) is True)
c = sam.fetch_board(labels, tomorrow)["cheers"]
check("cheer arrives once, marked", len(c) == 1 and c[0]["luck"] and c[0]["name"] == "Dre"
      and sam.fetch_board(labels, tomorrow)["cheers"] == [], str(c))
sq = sam.create_squad("busm")
info, st = dre.peek_squad(sq["code"].lower())
check("squad: peek and join", info and info["id"] == sq["id"] and dre.join_squad(sq["id"]) == 200)
row = {"name": "Dre", "day": labels[0], "reviews": 205, "studyTimeMs": 3600000, "accuracy": 91.5, "streak": 12, "week": 5, "emoji": "🐢", "newCards": 20}
ok3, gone3 = dre.push(labels, cfg, squad_row=row, squads=[sq["id"], "f" * 24])
check("squad: row via sync; a squad I'm not in is gone", ok3 and gone3 == ["f" * 24], str((ok3, gone3)))
rows = sam.fetch_squad(sq["id"])["rows"]
r = next(x for x in rows if x["user_id"] == dre.user_id)
check("squad: rows read back", r["reviews"] == 205 and r["new_cards"] == 20 and r["retention"] == 91.5 and r["week"] == 5)
check("squad: block", sam.block_member(sq["id"], dre.user_id) and dre.join_squad(sq["id"]) == 403)
check("settings: put, get", sam.put_settings("2026-09-26T10:00:00Z", {"share_time": False})
      and sam.get_settings()[0]["settings"] == {"share_time": False})
check("version: current", sam.check_version(labels[0], "3.0.0") is False)
code_view, people, _k = dre.friends_view()
check("friends view", [p[0] for p in people] == [sam.user_id] and people[0][3] is True)
new_code, e2 = sam.new_friend_code(code)
check("new code; the old one is gone", e2 is None and new_code != code and dre.add_friend(code)[1] is not None)
# a 2.x account, imported and restored
kai = api.ApiClient(os.path.join(tempfile.mkdtemp(), "session.json"), base=BASE)
kai.request_code(f"kai{stamp}@example.com"); kg = kai.verify_code(f"kai{stamp}@example.com", code_for())
kai.set_display_name("Kai")
kai.session.update(needs_restore=True, friend_ids=[sam.user_id, "ghost"], friend_code="KAI" + stamp[-3:])
old_code = shapes.new_squad_code()  # a 2.x squad nobody has brought back yet
okk, _ = kai.push(labels, {"squads": [{"code": old_code, "name": "old squad", "founder": sam.user_id}]})
check("restore: done and synced", okk and "needs_restore" not in kai.session)
fv = kai.friends_view()
check("restore: code and crew back", fv[0] == "KAI" + stamp[-3:] and [p[0] for p in fv[1]] == [sam.user_id], str(fv))
check("restore: squad under its 2.x id", kai.fetch_squad(shapes.squad_id(old_code))["founder"] == sam.user_id)
kai.delete_account()
check("delete: signed out, and gone for everyone", not kai.signed_in
      and sam.profile(kg["uid"]) is None)
sam.sign_out(); time.sleep(0.5)
print("ALL OK" if ok_all else "SOMETHING FAILED")
sys.exit(0 if ok_all else 1)
