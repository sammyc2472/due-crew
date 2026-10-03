"""Due (mock "My List", L1-L15): the day's to-do in a box above the board.

Pure: no Anki, no network. The glue (due_flow) gathers what this computer
knows (the plans I follow, my own items, reviews due, today's misses) and
the board draws what `view` returns.

Three tabs: Today (the day in full), Upcoming (today in short, then the
next two weeks) and Later (my own items with no day). There's no going
back a day: whatever isn't done is Behind, at the top of Today and of
Upcoming. A plan's date ticks itself when its cards are seen and its
author's lines are ticked; my own items tick by hand.

My own items and my ticks on the author's lines are account settings
(`due_items`, `due_ticks`), so every computer and the site see them. Text
I typed, nothing else: never a card.
"""

import datetime
import re
import uuid

NAME = "Due"
TABS = ("today", "upcoming", "later")
AHEAD = 14  # Upcoming: today and the next two weeks
MAX_OPEN = 60  # my own items not yet done
MAX_TEXT = 140
KEEP_DONE = 7  # days a ticked item stays (crossed out on its day)
MAX_TICKS = 200
MAX_AHEAD_DAYS = 730  # a day further out than two years is a typo
TODO_KINDS = {"watch": "▶ Watch", "read": "Read", "do": "Do"}
SHOW_BEHIND = 6  # own items shown in Behind before "N more"


def d(iso):
    return datetime.date.fromisoformat(str(iso))


def iso(day):
    return day.isoformat()


def _ok_day(s):
    try:
        d(s)
        return isinstance(s, str) and len(s) == 10
    except (TypeError, ValueError):
        return False


# ---- my own items ----

def clean_items(items):
    """The account's items, coerced: [{id, t, d, done, at}]. `d` a day or ""
    (Later), `done` the day I ticked it or ""."""
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        i = str(it.get("id") or "")[:16]
        t = " ".join(str(it.get("t") or "").split())[:MAX_TEXT]
        if not re.fullmatch(r"[a-z0-9]{4,16}", i) or not t or i in seen:
            continue
        seen.add(i)
        out.append({"id": i, "t": t,
                    "d": it["d"] if _ok_day(it.get("d")) else "",
                    "done": it["done"] if _ok_day(it.get("done")) else "",
                    "at": it["at"] if _ok_day(it.get("at")) else ""})
    # every open one, and the newest ticked ones: the settings doc stays small
    done = sorted((it for it in out if it["done"]), key=lambda it: it["done"], reverse=True)[:MAX_OPEN]
    keep = {it["id"] for it in done}
    return [it for it in out if not it["done"] or it["id"] in keep][:MAX_OPEN * 2]


def clean_ticks(ticks):
    """{"pid:uid:n": day}: the author's lines I ticked by hand."""
    out = {}
    if isinstance(ticks, dict):
        for k, v in ticks.items():
            if isinstance(k, str) and len(k) <= 300 and k.count(":") == 2 and _ok_day(v):
                out[k] = v
    return dict(sorted(out.items(), key=lambda kv: kv[1])[-MAX_TICKS:])


def prune(items, today):
    """Ticked items go KEEP_DONE days after their tick."""
    cut = iso(d(today) - datetime.timedelta(days=KEEP_DONE))
    return [it for it in items if not it["done"] or it["done"] > cut]


def open_count(items):
    return sum(1 for it in items if not it["done"])


_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_LONG = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


_MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august",
                "september", "october", "november", "december")


def _month(w):
    w = w.lower().rstrip(".")
    return next((i + 1 for i, m in enumerate(_MONTH_NAMES) if len(w) >= 3 and m.startswith(w)), 0)


def _on_or_after(today, month, day):
    t = d(today)
    for y in (t.year, t.year + 1):
        try:
            x = datetime.date(y, month, day)
        except ValueError:
            return None
        if x >= t:
            return iso(x)
    return None


def when_word(phrase, today):
    """A day said in words: "today", "tomorrow", "fri", "next week",
    "12 oct", "oct 12", "later". Returns a day, "" for Later, or None when
    it isn't one. Only this short list; no guessing."""
    w = " ".join(str(phrase).lower().replace(",", " ").split())
    t = d(today)
    if w in ("today", "tonight"):
        return today
    if w in ("tomorrow", "tmrw", "tmr"):
        return iso(t + datetime.timedelta(days=1))
    if w in ("later", "someday", "sometime"):
        return ""
    if w == "next week":
        return iso(t + datetime.timedelta(days=7 - t.weekday()))
    for prefix in ("next ", "on ", ""):
        if w.startswith(prefix):
            name = w[len(prefix):]
            if len(name) >= 3 and any(x.startswith(name) for x in _LONG):
                wd = _DAYS.index(name[:3])
                ahead = (wd - t.weekday()) % 7 or 7  # "fri" on a Friday is next week's
                return iso(t + datetime.timedelta(days=ahead))
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)? ([a-z]{3,9}\.?)", w) or None
    if m and _month(m.group(2)):
        return _on_or_after(today, _month(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"([a-z]{3,9}\.?) (\d{1,2})(?:st|nd|rd|th)?", w)
    if m and _month(m.group(1)):
        return _on_or_after(today, _month(m.group(1)), int(m.group(2)))
    return None


def parse(text, today):
    """(text, day): a day said at the end of what I typed comes off it
    ("Book the room fri" -> ("Book the room", Friday)). day is None when
    nothing at the end is a day, and the text is never left empty."""
    words = " ".join(str(text).split()).split(" ")
    for n in (3, 2, 1):
        if len(words) > n:
            day = when_word(" ".join(words[-n:]), today)
            if day is not None:
                rest = " ".join(words[:-n]).rstrip(" ,-·")
                if rest:
                    return rest, day
    return " ".join(words), None


def day_ok(day, today):
    """A day I can put an item on: today or later, within two years, or ""."""
    if day == "":
        return True
    return _ok_day(day) and today <= day <= iso(d(today) + datetime.timedelta(days=MAX_AHEAD_DAYS))


def new_id():
    return uuid.uuid4().hex[:10]


def add(items, text, day, today, ident=None):
    """(items, item) with a new item; (items, None) when it can't go in."""
    t = " ".join(str(text or "").split())[:MAX_TEXT]
    if not t or not day_ok(day, today) or open_count(items) >= MAX_OPEN:
        return items, None
    it = {"id": ident or new_id(), "t": t, "d": day, "done": "", "at": today}
    return items + [it], it


def change(items, ident, today, **kw):
    """Tick (done=True/False), move (d=day or ""), or retext (t=...) one item."""
    out = []
    for it in items:
        if it["id"] == ident:
            it = dict(it)
            if "done" in kw:
                it["done"] = today if kw["done"] else ""
            if "d" in kw and day_ok(kw["d"], today):
                it["d"] = kw["d"]
            if "t" in kw:
                t = " ".join(str(kw["t"] or "").split())[:MAX_TEXT]
                if t:
                    it["t"] = t
        out.append(it)
    return out


def remove(items, ident):
    return [it for it in items if it["id"] != ident]


def fmt_day(day, today):
    """"Today", "Tomorrow", "Fri", "Fri 16 Oct": short, and the date once it's past a week."""
    if day == today:
        return "Today"
    x, t = d(day), d(today)
    n = (x - t).days
    if n == 1:
        return "Tomorrow"
    if n == -1:
        return "Yesterday"
    if 1 < n < 7:
        return f"{x:%a}"
    return f"{x:%a} {x.day} {x:%b}"


def long_day(day, today):
    """"Tomorrow", "Fri 9 Oct": for saying where an item went."""
    if day in (today, iso(d(today) + datetime.timedelta(days=1))):
        return fmt_day(day, today)
    x = d(day)
    return f"{x:%a} {x.day} {x:%b}"


def heading(day, today):
    x = d(day)
    if day == today:
        return f"Today · {x:%a} {x.day} {x:%b}"
    if (x - d(today)).days == 1:
        return f"Tomorrow · {x:%a} {x.day} {x:%b}"
    return f"{x:%a} {x.day} {x:%b}"


def since(day, today):
    """"since Thu" for an item left from an earlier day."""
    n = (d(today) - d(day)).days
    if n == 1:
        return "since yesterday"
    if n < 7:
        return f"since {d(day):%a}"
    return f"since {d(day).day} {d(day):%b}"


# ---- plan dates, as due_flow hands them over ----
#
# A date: {pid, uid, plan, name, opens, seen, total, parts: [[group, seen,
# total]], todo: [{k, t, url}], crew: [done, of], prep: "event name" | None}
# An event: {day, name, plan}; a review day: {day, plan}.

def todo_key(pid, uid, n):
    return f"{pid}:{uid}:{n}"


def date_state(x, ticks):
    """(done, part): a date is done when its cards are seen and its author's
    lines are ticked; part when anything of it is."""
    lines = x.get("todo") or []
    ticked = sum(1 for n in range(len(lines)) if todo_key(x["pid"], x["uid"], n) in ticks)
    total, seen = int(x.get("total") or 0), int(x.get("seen") or 0)
    cards_done = seen >= total if total else True
    if not total and not lines:
        cards_done = False  # nothing here to see: never ticks itself
    done = cards_done and ticked == len(lines) and (total or lines)
    return bool(done), bool(seen or ticked) and not done


def _date_row(x, ticks, today, short=False):
    done, part = date_state(x, ticks)
    lines = []
    if not short:
        for g, s, t in x.get("parts") or []:
            lines.append({"kind": "part", "label": g, "seen": int(s), "total": int(t),
                          "done": int(t) > 0 and int(s) >= int(t)})
        for n, td in enumerate(x.get("todo") or []):
            key = todo_key(x["pid"], x["uid"], n)
            lines.append({"kind": "todo", "label": TODO_KINDS.get(td.get("k"), "Do"), "text": str(td.get("t") or ""),
                          "url": str(td.get("url") or ""), "key": key, "done": key in ticks,
                          "can": x["opens"] <= today})
    total, seen = int(x.get("total") or 0), int(x.get("seen") or 0)
    if x["opens"] > today:
        n = f"{total:,} new" if total else ""
    elif total:
        n = "all seen" if seen >= total else f"{seen:,} / {total:,}"
    else:
        n = ""
    return {"kind": "plan", "pid": x["pid"], "uid": x["uid"], "plan": x.get("plan") or "",
            "name": x.get("name") or "?", "what": x.get("what") or "", "done": done, "part": part,
            "future": x["opens"] > today, "n": n, "seen": seen, "total": total, "lines": lines,
            "crew": x.get("crew"), "prep": x.get("prep")}


def _item_row(it, today):
    return {"kind": "mine", "id": it["id"], "text": it["t"], "day": it["d"], "done": bool(it["done"]),
            "tag": (since(it["d"], today) if it["d"] and it["d"] < today else
                    fmt_day(it["d"], today) if it["d"] else "Later")}


def behind(dates, items, ticks, today):
    """What isn't done from earlier days: my own items one by one, and each
    plan's dates as one line (how many, how many cards left)."""
    mine = [_item_row(it, today) for it in items if it["d"] and it["d"] < today and not it["done"]]
    mine.sort(key=lambda r: r["day"])
    plans = {}
    for x in dates:
        if x["opens"] < today and not date_state(x, ticks)[0]:
            p = plans.setdefault(x["pid"], {"kind": "behind", "pid": x["pid"], "plan": x.get("plan") or "",
                                            "dates": 0, "left": 0, "first": x["opens"], "uid": x["uid"]})
            p["dates"] += 1
            p["left"] += max(0, int(x.get("total") or 0) - int(x.get("seen") or 0))
            if x["opens"] < p["first"]:
                p["first"], p["uid"] = x["opens"], x["uid"]
    return list(plans.values()), mine


def view(today, dates, items, ticks, tab="today", events=(), review_days=(), reviews=None,
         suggestions=(), notes=(), folded=False):
    """What board._due_html draws. `reviews`: {due, done} or None (not
    counted here); `suggestions`: [{key, text, go}]; `notes`: one-line
    notices (recovered leeches). Strings raw; the board escapes."""
    tab = tab if tab in TABS else "today"
    t = d(today)
    end = iso(t + datetime.timedelta(days=AHEAD))
    behind_plans, behind_mine = behind(dates, items, ticks, today)
    todays = [x for x in dates if x["opens"] == today]
    today_rows = [_date_row(x, ticks, today) for x in todays]
    today_rows += [_item_row(it, today) for it in items if it["d"] == today]
    if reviews is not None:
        today_rows.insert(0, {"kind": "reviews", "due": int(reviews.get("due") or 0),
                              "done": not int(reviews.get("due") or 0) and bool(reviews.get("done"))})
    counted = [r for r in today_rows if r["kind"] != "reviews" or r["due"] or r["done"]]
    done_n = sum(1 for r in counted if r["done"])
    # Upcoming: today in short, then each day ahead with something on it
    by_day = {}
    for x in dates:
        if today <= x["opens"] <= end:
            by_day.setdefault(x["opens"], []).append(_date_row(x, ticks, today, short=True))
    for it in items:
        if it["d"] and today <= it["d"] <= end:
            by_day.setdefault(it["d"], []).append(_item_row(it, today))
    evs, revs = {}, {}
    for e in events:
        if today <= e["day"] <= end:
            evs.setdefault(e["day"], []).append(e.get("name") or "?")
    for r in review_days:
        if today <= r["day"] <= end:
            revs.setdefault(r["day"], []).append(r.get("plan") or "")
    days, quiet = [], []

    def flush():
        if quiet:
            days.append({"quiet": [quiet[0], quiet[-1]],
                         "label": fmt_range(quiet[0], quiet[-1])})
            quiet.clear()
    for i in range(AHEAD + 1):
        day = iso(t + datetime.timedelta(days=i))
        rows, ev, rv = by_day.get(day, []), evs.get(day, []), revs.get(day, [])
        if i and not rows and not ev and not rv:
            quiet.append(day)
            continue
        flush()
        days.append({"day": day, "head": heading(day, today), "today": i == 0, "rows": rows, "events": ev,
                     "review": bool(rv), "n": len(rows)})
    flush()
    later = [_item_row(it, today) for it in items if not it["d"]]
    later.sort(key=lambda r: r["done"])
    nxt = [x for x in dates if x["opens"] > today]
    tomorrow = iso(t + datetime.timedelta(days=1))
    tom = [x.get("name") or "?" for x in dates if x["opens"] == tomorrow]
    tom += [it["t"] for it in items if it["d"] == tomorrow and not it["done"]]
    next_up = None
    if not tom and nxt:
        first = min(x["opens"] for x in nxt)
        next_up = {"day": fmt_day(first, today), "names": [x.get("name") or "?" for x in nxt if x["opens"] == first]}
    ev_soon = sorted((e for e in events if today <= e["day"] <= end), key=lambda e: e["day"])
    start = next((r for r in today_rows if r["kind"] == "plan" and not r["done"]), None)
    return {"name": NAME, "today": today, "tab": tab, "folded": bool(folded),
            "head": heading(today, today), "rows": today_rows, "done_n": done_n, "total_n": len(counted),
            "behind_plans": behind_plans, "behind_mine": behind_mine[:SHOW_BEHIND],
            "behind_more": max(0, len(behind_mine) - SHOW_BEHIND),
            "behind_n": len(behind_mine) + sum(p["dates"] for p in behind_plans),
            "days": days, "later": later, "later_n": sum(1 for r in later if not r["done"]),
            "tomorrow": tom, "next": next_up,
            "event": ({"name": ev_soon[0].get("name") or "?", "when": fmt_day(ev_soon[0]["day"], today),
                       "plan": ev_soon[0].get("plan") or ""} if ev_soon else None),
            "start": ({"pid": start["pid"], "uid": start["uid"], "name": start["name"]} if start else None),
            "suggestions": list(suggestions)[:2], "notes": list(notes),
            "full": open_count(items) >= MAX_OPEN}


def fmt_range(a, b):
    x, y = d(a), d(b)
    if a == b:
        return f"{x:%a} {x.day}"
    return f"{x:%a} {x.day} – {y:%a} {y.day}"


def empty(v):
    """Nothing at all to show: no plan dates, items, reviews or suggestions."""
    return not (v["rows"] or v["behind_n"] or any(not x.get("quiet") and (x["rows"] or x["events"]) for x in v["days"])
                or v["later"] or v["suggestions"] or v["notes"])
