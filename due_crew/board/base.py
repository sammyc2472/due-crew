"""The board's ground: its palettes and accents, tabs, words for days and times, a crew's rows (build_rows, the
app.js Board's twin), the page's key and its command helper.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import json as _json
import re as _re
import secrets as _secrets
from datetime import date as _date, datetime, timezone

from .. import room_model
from ..stats.decks import sig_match


LIGHT = {
    "bg": "#ffffff", "ink": "#333333", "muted": "#7a7a72", "line": "#e2e2da",
    "hours": "#b26a00", "faded": "#aaaaa2", "well": "#f2f2ec",
}
DARK = {
    "bg": "#1c1c1c", "ink": "#dfe1dc", "muted": "#989c92", "line": "#3d403b",
    "hours": "#dda45c", "faded": "#6d726a", "well": "#2b2d29",
}
# Accent choices: (accent, ink-on-accent, your-row fill) per theme. Every
# accent clears WCAG AA (4.5:1) as text on its card and as the pill fill
# behind its ink — tests/test_due_crew.py checks the arithmetic.
ACCENTS = {
    "green":  {"light": ("#2e7d32", "#ffffff", "#e9f2e9"), "dark": ("#7cc47f", "#122912", "#2c372b")},
    "blue":   {"light": ("#1e5fb4", "#ffffff", "#e8f0fb"), "dark": ("#7fb2f0", "#0b1f3a", "#263244")},
    "purple": {"light": ("#6b3fb5", "#ffffff", "#f0eafb"), "dark": ("#b89cf0", "#22143d", "#322a46")},
    "teal":   {"light": ("#0f766e", "#ffffff", "#e5f4f2"), "dark": ("#7dd3c8", "#0b2a28", "#22383a")},
    "amber":  {"light": ("#a35f00", "#ffffff", "#fbf1e2"), "dark": ("#e0a458", "#2d1d05", "#3d3323")},
    "rose":   {"light": ("#b03052", "#ffffff", "#fbe9ee"), "dark": ("#f08fa8", "#3a1220", "#3f2a31")},
}
DEFAULT_ACCENT = "green"


def accent_pair(name):
    """An accent's colour (light, dark); a name that isn't one of ours gets
    the default's. 3.8.1: a crewmate's Pip in a room wears theirs from here."""
    shades = ACCENTS.get(name if isinstance(name, str) else "", ACCENTS[DEFAULT_ACCENT])
    return shades["light"][0], shades["dark"][0]


def palette(theme, accent=DEFAULT_ACCENT):
    """Neutral tokens for the theme plus the chosen accent's trio."""
    base = dict(LIGHT if theme == "light" else DARK)
    a, ink, you = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])[theme]
    base.update({"accent": a, "accent-ink": ink, "you-bg": you, "fresh": a})
    # the logo's wordmark, a touch darker (lighter at night) than ink
    base["mark"] = "#e6e8e3" if theme == "dark" else "#242424"
    return base
NIGHT_SELECTORS = ("body.nightMode", "body.night_mode", "body.night-mode",
                   ":root.night-mode")

SORT_KEYS = ("reviews", "time", "retention", "streak", "week")  # week: squads only
# 3.8.0: the board is your people, Crew (Today, Week, Decks) and Squads;
# Plans and Insights are the You bubble's (YOU_MORE)
PERIODS = ("today", "week", "decks", "squads")
# 3.5.0: tabs a person can hide in Settings (per computer); Today always shows
# 3.8.0: Today and Week are always there; the rest can be hidden in Settings
HIDEABLE_TABS = (("decks", "Decks"), ("squads", "Squads"), ("plans", "Plans"), ("insights", "Insights"),
                 ("party", "Pip Party"))  # 3.9.5 (Sam: "make pip party something someone can unshow")
CREW_VIEWS = (("today", "Today"), ("week", "Week"), ("decks", "Decks"))
YOU_MORE = (("plans", "Plans"), ("insights", "Insights"))
PARTY_TAB = ("party", "Pip Party")  # 3.9.5's last round: after Insights, for those it's open to (gamenight_flow.shown)
BETA_TABS = ("party",)  # Sam's (3.9.5): Pip Party says Beta on its tab, the one way in, while it's new


def _tab_word(k, lb):
    """A You tab's name; a tab in BETA_TABS says Beta beside it."""
    return f'{lb}<span class="du-beta">Beta</span>' if k in BETA_TABS else lb


def hidden_tabs(cfg):
    return {k for k in (cfg.get("hidden_tabs") or []) if k in dict(HIDEABLE_TABS)}


def _head_label(icon, text):
    """The word; a narrow window shows the icon in its place (see _css)."""
    return f'<span class="hi">{icon}</span><span class="hl">{text}</span>'


HEADERS = (("reviews", _head_label("&#128218;", "Reviews")), ("time", _head_label("&#9201;", "Time")),
           ("retention", _head_label("&#127919;", "Retention")),
           ("streak", _head_label("&#128293;", "Streak")))
MEDALS = ("&#129351;", "&#129352;", "&#129353;")


def _token_block(palette):
    return "".join(f"--dc-{k}: {v}; " for k, v in palette.items())


def _by_theme(cfg, sel, light, dark):
    """`light` or `dark` (declarations) on `sel`, as Settings › Theme says;
    Match Anki follows its night mode (and the computer's)."""
    theme = cfg.get("theme", "auto")
    if theme == "light":
        return f"{sel} {{ {light} }}"
    if theme == "dark":
        return f"{sel} {{ {dark} }}"
    night = ", ".join(f"{n} {sel}" for n in NIGHT_SELECTORS)
    return (f"{sel} {{ {light} }}\n"
            f"    @media (prefers-color-scheme: dark) {{ {sel} {{ {dark} }} }}\n"
            f"    {night} {{ {dark} }}")


def _theme_css(cfg):
    accent = cfg.get("accent", DEFAULT_ACCENT)
    return _by_theme(cfg, "#due-crew", _token_block(palette("light", accent)), _token_block(palette("dark", accent)))


def _fmt_time(ms):
    m = int(ms) // 60000
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def _ago_secs(secs):
    if secs < 300:
        return "just now", "fresh"
    if secs < 3600:
        return f"{int(secs // 60)}m ago", "fresh"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago", "hours"
    return f"{int(secs // 86400)}d ago", "faded"


def _ago(ts_str):
    if not ts_str:
        return "", "faded"
    try:
        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
        secs = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
    except Exception:
        return "", "faded"
    return _ago_secs(secs)


QUIET_FOLD_DAYS = 90  # "The next round", Q3: the server's fold, the same number
# Q2: said where people read it (here, the Settings dialog, the site's Account, the README)
KEEP_LINE = "Unused for 12 months (24 when paused), an account is deleted with everything in it."


def _long_quiet(ts_str, now=None):
    """Q3: no sync in QUIET_FOLD_DAYS. An unknown time isn't long quiet."""
    if not ts_str:
        return False
    try:
        dt = datetime.fromisoformat(str(ts_str).replace("Z", "+00:00"))
    except Exception:
        return False
    return ((now or datetime.now(timezone.utc)) - dt).total_seconds() > QUIET_FOLD_DAYS * 86400


def _quiet_fold(rows):
    """Q3: the fold's line for long-quiet friends: how many, their names,
    and the month they were last here. Opened in the page, no command."""
    names = [_html.escape(str(r["name"])) for r in rows]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if len(names) <= 3 else f"{', '.join(names[:2])} and {len(names) - 2} more"
    newest = max((str(r.get("last_updated") or "") for r in rows), default="")
    try:
        since = datetime.fromisoformat(newest.replace("Z", "+00:00")).astimezone().strftime("%b")  # this computer's month
    except Exception:
        since = ""
    verb = "hasn't" if len(rows) == 1 else "haven't"
    return (f'<tr class="qfold"><td class="rk"></td><td class="nm" colspan="{len(HEADERS) + 1}">'
            f'<a href="#" onclick="this.closest(\'table\').classList.toggle(\'qopen\');return false;">'
            f'&#9656; {len(rows)} quiet</a> <span class="dc-note">&middot; {who} {verb} been here'
            f'{" since " + since if since else " in months"}</span></td></tr>')


def _day_metrics(doc):
    return {"reviews": doc.get("reviews"),
            "time_ms": doc.get("studyTimeMs"),
            "retention": doc.get("accuracy"),
            "streak": doc.get("streak"),
            "new": doc.get("newCards")}


def week_labels(labels):
    """The labels inside the calendar week (Monday to Sunday) of labels[0],
    newest first like `labels`. "Week" means this week, not a rolling seven
    days: it is what people mean by the word, it gives the crew one shared
    finish line, and it matches the "Last week" banner. Always a subset of
    the seven days already fetched, so it costs nothing."""
    if not labels:
        return []
    try:
        today = _date.fromisoformat(str(labels[0]))
    except ValueError:
        return list(labels)
    monday = (today - _dt.timedelta(days=today.weekday())).isoformat()
    return [lb for lb in labels if lb >= monday]


def _week_row(days, labels):
    found = [days.get(lb) for lb in labels if days.get(lb)]
    if not found:
        return None
    reviews = [d["reviews"] for d in found if "reviews" in d]
    times = [d["studyTimeMs"] for d in found if "studyTimeMs" in d]
    accs = [(d["accuracy"], d.get("reviews", 1)) for d in found if "accuracy" in d]
    streak = next((d["streak"] for d in found if "streak" in d), None)
    fresh = [d["newCards"] for d in found if "newCards" in d]
    acc = None
    if accs:
        weights = sum(max(r, 1) for _, r in accs)
        acc = sum(a * max(r, 1) for a, r in accs) / weights
    return {"reviews": sum(reviews) if reviews else None,
            "time_ms": sum(times) if times else None,
            "retention": acc, "streak": streak,
            "new": sum(fresh) if fresh else None}


def _showed(doc):
    """A day counts as showed-up. New docs say so outright (`studied`, the
    numbers-free field); docs from older versions fall back to whichever
    shared metric proves answers."""
    if not doc:
        return False
    if "studied" in doc:
        return bool(doc["studied"])
    return bool(doc.get("reviews") or doc.get("studyTimeMs") or "accuracy" in doc)


def _exam_text(iso, today_label):
    """"exam Fri" within the 14 days before the date; "" otherwise. The text
    is client-built from a parsed date — a friend's doc can never inject."""
    try:
        d = _date.fromisoformat(str(iso))
        t = _date.fromisoformat(str(today_label))
    except (TypeError, ValueError):
        return ""
    delta = (d - t).days
    if delta < 0 or delta > 14:
        return ""
    if delta == 0:
        return "exam today"
    if delta == 1:
        return "exam tomorrow"
    if delta < 7:
        return f"exam {d.strftime('%a')}"
    return f"exam {d.strftime('%b')} {d.day}"


def live_now(until, now=None):
    """Whether a "studying now" time (ISO, UTC) is still ahead (2.10)."""
    try:
        t = datetime.fromisoformat(str(until).replace("Z", "+00:00"))
    except ValueError:
        return False
    return t > (now or datetime.now(timezone.utc))


def plan_target(status):
    """A status that starts with a number is a plan (2.10): "200 cards,
    then bed" -> 200. None otherwise, or for numbers no one plans."""
    m = _re.match(r"\s*(\d{1,5})(?!\d)", str(status or ""))
    n = int(m.group(1)) if m else 0
    return n if 0 < n <= 20000 else None


def season_emoji(day):
    """A few emoji for the season, sprinkled into flurries (2.10)."""
    month = day.month
    if month == 10:
        return ["\U0001F383", "\U0001F342"]              # pumpkin, leaf
    if month in (9, 11):
        return ["\U0001F342", "\U0001F341"]              # leaves
    if month == 12:
        return ["\u2744\ufe0f", "\u26c4"]               # snowflake, snowman
    if month in (1, 2):
        return ["\u2744\ufe0f"]
    if month in (3, 4, 5):
        return ["\U0001F338", "\U0001F331"]              # blossom, sprout
    return ["\U0001F33B", "\u2600\ufe0f"]               # sunflower, sun


def sort_key(cfg):
    key = cfg.get("sort", "reviews")
    return key if key in SORT_KEYS else "reviews"


def _label(name, emoji=""):
    """Escaped name, with the person's emoji in front when they have one."""
    out = _html.escape(str(name))
    return f"{_html.escape(str(emoji))} {out}" if emoji else out


def _away_text(doc, today_lb):
    """Badge text for a day doc flagged away: when they're back, if known."""
    try:
        back = _dt.date.fromisoformat(str((doc or {}).get("awayTo"))) + _dt.timedelta(days=1)
        today = _dt.date.fromisoformat(str(today_lb))
    except (TypeError, ValueError):
        return "away"
    if back <= today:
        return "away"
    if back == today + _dt.timedelta(days=1):
        return "back tomorrow"
    return f"back {back:%b} {back.day}"


def _day_flags(doc, today_lb):
    """The Today-only extras a day doc carries: the status bubble and the
    away badge (v2.2). Both are shown only for the day being displayed."""
    return {"status": str(doc.get("status") or ""),
            "away": _away_text(doc, today_lb) if doc.get("away") else ""}


def build_rows(entries, labels, tomorrow, period, cfg):
    today_lb = labels[0] if labels else ""
    yest_lb = labels[1] if len(labels) > 1 else ""
    fresh, notyet, stale, quiet, paused = [], [], [], [], []
    for e in entries:
        row = {"user_id": e["user_id"], "name": e["name"], "you": e["you"],
               "emoji": e.get("emoji") or "",
               # 3.8.2: their Pip on the row, in their colour and look (mine come from the config)
               "accent": e.get("accent") or "", "look": e.get("look") or [],
               "paused": e["paused"], "last_updated": e["last_updated"],
               "reviews": None, "time_ms": None, "retention": None,
               "streak": None, "new": None, "stale": False, "quiet": False,
               "back": bool(e.get("back")) and not e["paused"],
               "live": live_now(e.get("live_until")) and not e["paused"],
               # 2.12: "in Dre's room" takes the place of "studying now"
               "room": (room_model.title(entries, e["room"]) if e.get("room")
                        and not e["paused"] else ""),
               "status": "", "away": "",
               # 3.2: their last plan week done, the day it's new
               "recap": (e.get("recap") or {}) if not e["paused"] and (e.get("recap") or {}).get("day") == today_lb else {},
               "exam": "" if e["paused"] else
                       _exam_text(e.get("exam_date"), today_lb)}
        if e["paused"]:
            paused.append(row)
            continue
        days = e.get("days") or {}
        # presence: how many of the seven days they showed up (the numbers-
        # free floor every doc carries), and whether that is all they share
        row["days7"] = sum(1 for lb in labels if _showed(days.get(lb)))
        row["days_wk"] = sum(1 for lb in week_labels(labels) if _showed(days.get(lb)))
        row["showup"] = False
        if period == "week":
            agg = _week_row(days, week_labels(labels))
            if agg is None:
                if e["you"] or row["days7"]:
                    row["showup"] = bool(row["days7"])
                    fresh.append(row)
                else:
                    row["quiet"] = True
                    quiet.append(row)
                continue
            if not row["days_wk"]:
                # this week's days are all zero so far: nothing to rank
                row["notyet"] = True
                notyet.append(row)
                continue
            row.update(agg)
            row["showup"] = bool(row["days7"]) and all(
                row[k] is None for k in ("reviews", "time_ms", "retention", "streak"))
            fresh.append(row)
        else:
            # a friend whose day rolled over ahead of mine writes my
            # "tomorrow" label — that's their live today
            today = days.get(tomorrow) or days.get(today_lb)
            yesterday = days.get(yest_lb)
            if today and not _showed(today):
                # synced, but nothing studied yet (or away): no numbers to
                # rank, so dashes and no rank, under everyone who studied;
                # their status still shows, and a cheer still lands
                row.update(_day_flags(today, today_lb))
                row["notyet"] = not row["away"]
                notyet.append(row)
            elif today:
                row.update(_day_metrics(today))
                row.update(_day_flags(today, today_lb))
                row["showup"] = _showed(today) and all(
                    row[k] is None for k in ("reviews", "time_ms", "retention", "streak"))
                row["studied_today"] = _showed(today)
                fresh.append(row)
            elif yesterday and cfg.get("show_stale", True) and not e["you"]:
                row.update(_day_metrics(yesterday))
                row.update(_day_flags(yesterday, today_lb))
                row["stale"] = True
                stale.append(row)
            elif e["you"]:
                fresh.append(row)
            else:
                # a quiet friend stays on the board — that's when a cheer lands
                row["quiet"] = True
                quiet.append(row)
    field = {"reviews": "reviews", "time": "time_ms", "retention": "retention",
             "streak": "streak", "week": "reviews"}[sort_key(cfg)]
    order = lambda r: r[field] if r[field] is not None else -1
    fresh.sort(key=order, reverse=True)
    stale.sort(key=order, reverse=True)
    quiet.sort(key=lambda r: r["last_updated"] or "", reverse=True)
    notyet.sort(key=lambda r: r["last_updated"] or "", reverse=True)
    return fresh, notyet + stale + quiet + paused  # dormant rows last


def build_deck_groups(entries):
    """Groups anchored on your shared decks; extras are crew decks that match
    none of yours. The Shared Decks dialog shows those against your own
    decks ("matches igk"); the board stopped repeating them in 2.7."""
    me = next((e for e in entries if e["you"]), None)
    others = [e for e in entries if not e["you"]]
    groups, matched = [], set()
    for d in (me.get("decks") or []) if me else []:
        rows = [(me["name"], True, d, me["user_id"])]
        for o in others:
            for od in o.get("decks") or []:
                if sig_match(d.get("sig"), od.get("sig")):
                    rows.append((o["name"], False, od, o["user_id"]))
                    matched.add((o["user_id"], od.get("name", "")))
                    break
        groups.append({"label": d.get("name", "?"), "rows": rows})
    extras = []
    for o in others:
        for od in o.get("decks") or []:
            if (o["user_id"], od.get("name", "")) not in matched:
                extras.append((o["name"], od.get("name", "?")))
    return groups, extras


def _cell(value, fmt=str):
    return "&mdash;" if value is None else fmt(value)


def today_text(reviews, new=None):
    """ "205 reviews (20 new)": the profile card's Today line (2.13)."""
    reviews = int(reviews or 0)
    out = f'{reviews:,} review{"" if reviews == 1 else "s"}'
    try:
        new = min(int(new), reviews)
    except (TypeError, ValueError):
        return out
    if new <= 0:
        return out
    return out + (" (all new)" if new == reviews else f" ({new:,} new)")


# where a row without the new-cards line would take one; _even_rows fills it
# when another row in the table has a line, so every row is the same height
_NW_ROOM = "<!--nw-->"


def _even_rows(body):
    if 'class="nw"' in body:
        # half a line above the number and half below: the row matches the
        # two-line ones, and the number stays level with the row's other cells
        return body.replace(_NW_ROOM, '<small class="nwh"></small>')
    return body.replace(_NW_ROOM, "")


def _reviews_cell(reviews, new):
    """The Reviews number, and under it how many were new cards (2.13): "all
    new" when every one was, nothing when none were or they didn't say."""
    if reviews is None:
        return _NW_ROOM + "&mdash;" + _NW_ROOM
    out = format(int(reviews), ",")
    try:
        new = int(new)
    except (TypeError, ValueError):
        return _NW_ROOM + out + _NW_ROOM
    if new <= 0 or reviews <= 0:
        return _NW_ROOM + out + _NW_ROOM
    new = min(new, int(reviews))
    line = "all new" if new == reviews else f"{new:,} new"
    return (f'<span title="{new:,} of {int(reviews):,} were new cards">{out}'
            f'<small class="nw">{line}</small></span>')


# 3.9.1 (the security review): the Decks page's own commands carry this, new
# each run and written only into that page. Anki calls a message the Decks
# screen's from the moment it switches to it, while the page before (a
# card's, or Overview's with a deck's description, scripts and all) is still
# up; without the key a message gets a card page's rules (__init__._on_js).
BOARD_KEY = _secrets.token_hex(8)


def key_js():
    """The key, where the page's own scripts add it (window.dcBK)."""
    return f"<script>window.dcBK={_json.dumps(BOARD_KEY)};</script>"


def _pycmd(cmd):
    """Only ids and keys ride in commands; anything else is dropped so a
    server-sourced id could never close the quote it sits in."""
    return f"pycmd('duecrew:{_re.sub(r'[^A-Za-z0-9:_.-]', '', str(cmd))}|{BOARD_KEY}'); return false;"


ROW_CAP = 10


def initial(name):
    """A person's first letter or digit, for the circle that stands in for
    an emoji they haven't picked ("?" when there's none)."""
    return next((ch.upper() for ch in str(name or "") if ch.isalnum()), "?")


def face(emoji, name, small=False):
    """Someone's emoji, or the first letter of their name in a circle.
    Escaped here: both are theirs."""
    if emoji:
        return _html.escape(str(emoji))
    return f'<span class="ini{" sm" if small else ""}">{_html.escape(initial(name))}</span>'


def _ins_r(x):
    from ..ahead import r
    return f"{r(x):,}"


def _ahead_r(x):
    from ..ahead import r
    return r(x)


def _day_after(iso, k):
    """The day k days after iso (a day), "" for anything else."""
    try:
        return (_dt.date.fromisoformat(str(iso)) + _dt.timedelta(days=int(k))).isoformat()
    except (TypeError, ValueError):
        return ""


def _ins_dname(iso, long=False):
    try:
        d = _dt.date.fromisoformat(str(iso))
    except ValueError:
        return ""
    return f"{d:%a} {d.day} {d:%b}" if long else f"{d:%a} {d.day}"


def _week_span(wk):
    try:
        monday = _dt.date.fromisocalendar(int(wk[:4]), int(wk[6:]), 1)
    except ValueError:
        return ""
    return f"week of {monday.day} {monday:%b}"


def _short_day(iso):
    """"14 Oct" from a day ("2026-10-14"), or from a moment (a cheer's
    "2026-10-15T01:30:00Z", which the server keeps in UTC) on this
    computer's clock; "" for anything else. 3.9.2: a moment was cut at its
    first ten characters, its UTC date, so a doodle sent on an American
    evening was dated the next day."""
    s = str(iso or "").strip()
    try:
        if "T" in s:
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
            d = (t.astimezone() if t.tzinfo else t).date()
        else:
            d = _dt.date.fromisoformat(s[:10])
    except ValueError:
        return ""
    return f"{d.day} {d.strftime('%b')}"
# the board's own font (Sam: "consistent with our normal fonts"): a sign is the board's words, bold
BOARD_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
