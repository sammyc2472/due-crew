"""Due: the day's to-do in a box above the board.

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
    """The account's items, coerced: [{id, t, d, done, at, r}]. `d` a day or ""
    (Later), `done` the day I ticked it or "". 3.8.0: `r`, the weekdays a
    repeating one falls on (Monday "0"), from `d` on; its `done` is the
    last day I ticked it."""
    out, seen = [], set()
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        i = str(it.get("id") or "")[:16]
        t = " ".join(str(it.get("t") or "").split())[:MAX_TEXT]
        if not re.fullmatch(r"[a-z0-9]{4,16}", i) or not t or i in seen:
            continue
        seen.add(i)
        r = _rule(it.get("r"))
        out.append({"id": i, "t": t,
                    "d": it["d"] if _ok_day(it.get("d")) else "",
                    "done": it["done"] if _ok_day(it.get("done")) else "",
                    "at": it["at"] if _ok_day(it.get("at")) else ""})
        if r:
            out[-1]["r"] = r
    # every open one, and the newest ticked ones: the settings doc stays small
    done = sorted((it for it in out if not is_open(it)), key=lambda it: it["done"], reverse=True)[:MAX_OPEN]
    keep = {it["id"] for it in done}
    return [it for it in out if is_open(it) or it["id"] in keep][:MAX_OPEN * 2]


def _rule(r):
    """A repeat's weekdays, sorted, or "" (none, or not one)."""
    r = str(r or "")
    return "".join(sorted(set(r))) if re.fullmatch(r"[0-6]{1,7}", r) else ""


def is_open(it):
    """Not done: a repeating item always is (it comes again)."""
    return bool(it.get("r")) or not it["done"]


def on_day(it, day):
    """3.8.0: a repeating item falls on `day`: one of its weekdays, from its start."""
    return bool(it.get("r")) and str(d(day).weekday()) in it["r"] and (not it["d"] or day >= it["d"])


def done_on(it, day):
    """Ticked for `day`: a repeating item only on the day I ticked it."""
    return it["done"] == day if it.get("r") else bool(it["done"])


def clean_ticks(ticks):
    """{"pid:uid:n": day}: the author's lines I ticked by hand."""
    out = {}
    if isinstance(ticks, dict):
        for k, v in ticks.items():
            if isinstance(k, str) and len(k) <= 300 and k.count(":") == 2 and _ok_day(v):
                out[k] = v
    return dict(sorted(out.items(), key=lambda kv: kv[1])[-MAX_TICKS:])


def prune(items, today):
    """Ticked items go KEEP_DONE days after their tick; a repeating one stays."""
    cut = iso(d(today) - datetime.timedelta(days=KEEP_DONE))
    return [it for it in items if is_open(it) or it["done"] > cut]


def open_count(items):
    return sum(1 for it in items if is_open(it))


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
    it isn't one. Only this short list; no guessing. Digits are 0-9 only
    (Python's \\d takes any script's), as the preview's JS reads them."""
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
    m = re.fullmatch(r"([0-9]{1,2})(?:st|nd|rd|th)? ([a-z]{3,9}\.?)", w) or None
    if m and _month(m.group(2)):
        return _on_or_after(today, _month(m.group(2)), int(m.group(1)))
    m = re.fullmatch(r"([a-z]{3,9}\.?) ([0-9]{1,2})(?:st|nd|rd|th)?", w)
    if m and _month(m.group(1)):
        return _on_or_after(today, _month(m.group(1)), int(m.group(2)))
    return None


def repeat_word(phrase):
    """3.8.0: a repeat said in words: "daily", "every day", "weekdays",
    "every mon", "every mon and thu", "mondays". The weekdays (Monday "0"),
    or None when it isn't one. Only this short list; no guessing."""
    w = " ".join(str(phrase).lower().replace(",", " ").split())
    if w in ("daily", "every day", "each day"):
        return "0123456"
    if w in ("weekdays", "every weekday", "each weekday"):
        return "01234"
    if w.endswith("s") and w[:-1] in _LONG:
        return str(_LONG.index(w[:-1]))
    m = re.fullmatch(r"(?:every|each) ([a-z ]+)", w)
    if not m:
        return None
    days = set()
    for name in m.group(1).split():
        if name == "and":
            continue
        k = next((i for i, x in enumerate(_LONG) if len(name) >= 3 and x.startswith(name)), None)
        if k is None:
            return None
        days.add(str(k))
    return "".join(sorted(days)) or None


def parse_repeat(text):
    """(text, weekdays): a repeat said at the end of what I typed ("Practice
    block every mon"), or at the start before a colon ("every mon: practice
    block"), comes off it. weekdays is None when there's none, and the text
    is never left empty."""
    t = " ".join(str(text).split())
    m = re.fullmatch(r"([^:]{3,40}):\s*(.+)", t)
    if m:
        r = repeat_word(m.group(1))
        if r:
            return m.group(2), r
    words = t.split(" ")
    for n in range(min(6, len(words) - 1), 0, -1):
        r = repeat_word(" ".join(words[-n:]))
        if r:
            rest = " ".join(words[:-n]).rstrip(" ,-·:")
            if rest:
                return rest, r
    return t, None


def repeat_label(r):
    """"every day", "weekdays", "every Mon", "every Mon, Thu"."""
    if r == "0123456":
        return "every day"
    if r == "01234":
        return "weekdays"
    return "every " + ", ".join(_DAYS[int(k)].capitalize() for k in r)


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


def add(items, text, day, today, ident=None, rule=None):
    """(items, item) with a new item; (items, None) when it can't go in.
    3.8.0: `rule`, a repeat's weekdays: it starts today."""
    t = " ".join(str(text or "").split())[:MAX_TEXT]
    r = _rule(rule)
    if r:
        day = today
    if not t or not day_ok(day, today) or open_count(items) >= MAX_OPEN:
        return items, None
    it = {"id": ident or new_id(), "t": t, "d": day, "done": "", "at": today}
    if r:
        it["r"] = r
    return items + [it], it


def change(items, ident, today, **kw):
    """Tick (done=True/False), move (d=day or ""), or retext (t=...) one item.
    3.8.0: r="" stops a repeat (a one-off today, ticked if today's was)."""
    out = []
    for it in items:
        if it["id"] == ident:
            it = dict(it)
            if "r" in kw and not kw["r"] and it.get("r"):
                it.pop("r")
                it["d"], it["done"] = today, it["done"] if it["done"] == today else ""
            if "done" in kw:
                it["done"] = today if kw["done"] else ""
            if "d" in kw and day_ok(kw["d"], today) and not it.get("r"):
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
    """3.7.1's key: the line's place. Still read, so a tick from before
    3.7.2 holds; a new tick is keyed by the line itself (line_keys)."""
    return f"{pid}:{uid}:{n}"


def _fnv(text):
    """FNV-1a over code points, 8 hex digits (`dueLineHash` in app.js: change
    one, change both)."""
    h = 0x811C9DC5
    for ch in text:
        h = ((h ^ ord(ch)) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"


def line_keys(pid, uid, todo):
    """A tick's key per author's line, from what the line says (3.7.2), so
    an author who reorders a date's lines moves the ticks with them; a
    second identical line is told apart by its count."""
    out, count = [], {}
    for td in todo or []:
        h = _fnv(f"{td.get('k') or ''}\n{td.get('t') or ''}")
        count[h] = count.get(h, 0) + 1
        out.append(f"{pid}:{uid}:{h}" + (f".{count[h]}" if count[h] > 1 else ""))
    return out


def line_ticked(x, ticks):
    """Which of a date's author's lines are ticked: by the line's key, or by
    its place for a tick from before 3.7.2."""
    keys = line_keys(x["pid"], x["uid"], x.get("todo"))
    return [k in ticks or todo_key(x["pid"], x["uid"], n) in ticks for n, k in enumerate(keys)]


def sibling_line(n, buried):
    """A date done but for siblings Anki spaces out (they count as seen)."""
    n = int(n)
    return f"done \u00b7 {n:,} sibling{'s' if n != 1 else ''} {'tomorrow' if buried else 'later'}"


def date_state(x, ticks):
    """(done, part): a date is done when its cards are seen and its author's
    lines are ticked; part when anything of it is."""
    lines = x.get("todo") or []
    ticked = sum(line_ticked(x, ticks))
    total, seen = int(x.get("total") or 0), int(x.get("seen") or 0)
    cards_done = seen >= total if total else True
    if not total and not lines:
        # nothing of it here: done once its day came and the deck was read
        # (3.7.2), so Due can fold; never before it's been counted
        cards_done = bool(x.get("counted"))
    done = cards_done and ticked == len(lines) and (total or lines or x.get("counted"))
    return bool(done), bool(seen or ticked) and not done


def _date_row(x, ticks, today, short=False):
    done, part = date_state(x, ticks)
    lines = []
    if not short:
        for g, s, t in x.get("parts") or []:
            lines.append({"kind": "part", "label": g, "seen": int(s), "total": int(t),
                          "done": int(t) > 0 and int(s) >= int(t)})
        keys, on = line_keys(x["pid"], x["uid"], x.get("todo")), line_ticked(x, ticks)
        for n, td in enumerate(x.get("todo") or []):
            lines.append({"kind": "todo", "label": TODO_KINDS.get(td.get("k"), "Do"), "text": str(td.get("t") or ""),
                          "url": str(td.get("url") or ""), "key": keys[n], "done": on[n],
                          "can": x["opens"] <= today})
    total, seen = int(x.get("total") or 0), int(x.get("seen") or 0)
    if x["opens"] > today:
        n = f"{total:,} new" if total else ""
    elif total:
        n = "all seen" if seen >= total else f"{seen:,} / {total:,}"
        sib, buried = (x.get("sibs") or [0, 0])[:2]
        if sib and seen >= total:
            n = sibling_line(sib, buried)
    else:
        n = ""
    return {"kind": "plan", "pid": x["pid"], "uid": x["uid"], "plan": x.get("plan") or "",
            "name": x.get("name") or "?", "what": x.get("what") or "", "topics": x.get("topics") or [],
            "done": done, "part": part,
            "future": x["opens"] > today, "n": n, "seen": seen, "total": total, "lines": lines,
            "crew": x.get("crew"), "prep": x.get("prep"), "upd": int(x.get("upd") or 0)}


def _item_row(it, today, day=None):
    """One of my items, on `day` (a repeat's; today's when None)."""
    if it.get("r"):
        return {"kind": "mine", "id": it["id"], "text": it["t"], "day": day or today, "done": done_on(it, day or today),
                "tag": repeat_label(it["r"]), "rep": True, "ahead": bool(day and day > today)}
    return {"kind": "mine", "id": it["id"], "text": it["t"], "day": it["d"], "done": bool(it["done"]),
            "tag": (since(it["d"], today) if it["d"] and it["d"] < today else
                    fmt_day(it["d"], today) if it["d"] else "Later")}


def _once(items):
    """My items that don't repeat."""
    return [it for it in items if not it.get("r")]


def behind(dates, items, ticks, today):
    """What isn't done from earlier days: my own items one by one, and each
    plan's dates as one line (how many, how many cards left). A repeat is
    never behind: it comes again."""
    mine = [_item_row(it, today) for it in _once(items) if it["d"] and it["d"] < today and not it["done"]]
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
    """What board._due_html draws. `reviews`: {due, done, back, at} or None (not
    counted here); `suggestions`: [{key, text, go}]; `notes`: one-line
    notices (recovered leeches). Strings raw; the board escapes."""
    tab = tab if tab in TABS else "today"
    t = d(today)
    end = iso(t + datetime.timedelta(days=AHEAD))
    behind_plans, behind_mine = behind(dates, items, ticks, today)
    todays = [x for x in dates if x["opens"] == today]
    today_rows = [_date_row(x, ticks, today) for x in todays]
    today_rows += [_item_row(it, today) for it in items if (on_day(it, today) if it.get("r") else it["d"] == today)]
    if reviews is not None:
        # 3.8.0: learning cards back later today keep the row open
        due_r, back = int(reviews.get("due") or 0), int(reviews.get("back") or 0)
        today_rows.insert(0, {"kind": "reviews", "due": due_r, "back": back, "at": str(reviews.get("at") or ""),
                              "done": not due_r and not back and bool(reviews.get("done"))})
    counted = [r for r in today_rows if r["kind"] != "reviews" or r["due"] or r["back"] or r["done"]]
    done_n = sum(1 for r in counted if r["done"])
    # Upcoming: today in short, then each day ahead with something on it
    by_day = {}
    for x in dates:
        if today <= x["opens"] <= end:
            by_day.setdefault(x["opens"], []).append(_date_row(x, ticks, today, short=True))
    for it in _once(items):
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
    for it in items:
        if it.get("r"):  # 3.8.0: a repeat once: today's, or (that done) its next day
            for i in range(AHEAD + 1):
                day = iso(t + datetime.timedelta(days=i))
                if on_day(it, day):
                    by_day.setdefault(day, []).append(_item_row(it, today, day))
                    if day != today or not done_on(it, today):
                        break
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
    later = [_item_row(it, today) for it in _once(items) if not it["d"]]
    later.sort(key=lambda r: r["done"])
    nxt = [x for x in dates if x["opens"] > today]
    tomorrow = iso(t + datetime.timedelta(days=1))
    tom = [x.get("name") or "?" for x in dates if x["opens"] == tomorrow]
    tom += [it["t"] for it in items if (on_day(it, tomorrow) if it.get("r") else it["d"] == tomorrow and not it["done"])]
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
            # 3.8.0: Study today has something to walk: reviews due, or a plan's date not done
            "study": any((r["kind"] == "reviews" and r["due"]) or (r["kind"] == "plan" and not r["done"])
                         for r in today_rows),
            "suggestions": list(suggestions)[:2], "notes": list(notes),
            "full": open_count(items) >= MAX_OPEN}


def fmt_range(a, b):
    x, y = d(a), d(b)
    if a == b:
        return f"{x:%a} {x.day}"
    return f"{x:%a} {x.day} – {y:%a} {y.day}"


def done_for_today(v):
    """Everything today holds is ticked, and nothing waits behind: Due folds
    itself to its one line until tomorrow (unless I opened it by hand)."""
    return bool(v["total_n"]) and v["done_n"] >= v["total_n"] and not v["behind_n"]


def fold_state(choice, v, today):
    """Folded or open: my own Hide/Show today wins, else folded once the day's done.
    `choice` is the config's {"day", "folded"} (an older bool counts as no choice)."""
    if isinstance(choice, dict) and choice.get("day") == today:
        return bool(choice.get("folded"))
    return done_for_today(v)


def empty(v):
    """Nothing at all to show: no plan dates, items, reviews or suggestions."""
    return not (v["rows"] or v["behind_n"] or any(not x.get("quiet") and (x["rows"] or x["events"]) for x in v["days"])
                or v["later"] or v["suggestions"] or v["notes"])


# ---- 3.8.0: Study today, one button through the day ----

STUDY_STEPS = 30  # a walk never takes more steps than this


def study_next(plan_decks, due_now, misses, misses_done):
    """The walk's next step: ("deck", did) or ("misses", n) or None (done).
    plan_decks: the decks of the plans I follow, in plan order; due_now:
    {did: cards Anki would show now} for each of those and every top deck
    (a deck's count takes in its subdecks', within its limits); misses: how
    many I missed today. Plans' decks first, then the deck with the most
    due, then today's misses once."""
    for did in plan_decks:
        if int(due_now.get(did) or 0) > 0:
            return ("deck", did)
    rest = [(n, did) for did, n in due_now.items() if did not in plan_decks and int(n or 0) > 0]
    if rest:
        return ("deck", max(rest, key=lambda x: (x[0], -int(x[1])))[1])
    if misses and not misses_done:
        return ("misses", int(misses))
    return None
