"""Deck-screen board HTML. Pure rendering: no network, no collection access.

Theme is decided in CSS, inside the webview, not in Python: both palettes
ship as CSS custom properties, and the dark set applies under Anki's night
body classes (with a prefers-color-scheme fallback). The Settings override
forces a single palette. This holds on every Anki version regardless of what
theme_manager reports.

All server-sourced strings are escaped before they touch the webview.
Entries carry days as {label: doc}; data["labels"] fixes the order and
data["tomorrow"] is my next label, so a friend whose day already rolled over
ahead of mine still renders as fresh.
"""

import datetime as _dt
import html as _html
import json as _json
import os as _os
import re as _re
import sys as _sys
import time
from datetime import date as _date, datetime, timezone

from .logo import board_mark
from . import room_model
from . import closet as _closet, emoji_drawer as _emoji_drawer, fridge as _fridge, sev as _sev, shows as _shows
from .backend.shapes import DOODLE_INKS, clean_doodle
from .stats.decks import sig_match

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
HIDEABLE_TABS = (("decks", "Decks"), ("squads", "Squads"), ("plans", "Plans"), ("insights", "Insights"))
CREW_VIEWS = (("today", "Today"), ("week", "Week"), ("decks", "Decks"))
YOU_MORE = (("plans", "Plans"), ("insights", "Insights"))


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
        since = datetime.fromisoformat(newest.replace("Z", "+00:00")).strftime("%b")
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


def _css(cfg):
    pad = 3 if cfg.get("compact") else 6
    you_bg = "background: var(--dc-you-bg);" if cfg.get("highlight_me", True) else ""
    return f"""
    <style>
    {_theme_css(cfg)}
    #due-crew {{ margin: 18px auto 8px; max-width: 640px; color: var(--dc-ink);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; }}
    /* 3.5.0: Anki's Decks screen sits in a <center> (the board's older parts
       have always been centred by it; a new part says text-align: left
       itself) and gives every button a margin, a shadow and rounded
       corners, which the board's buttons start without */
    #due-crew button {{ -webkit-appearance: none; appearance: none; margin: 0; box-shadow: none;
      min-width: 0; min-height: 0; text-shadow: none; background-image: none; }}
    /* the board is one rounded card — white by day, near-black by night —
       and inside it there are no rules and no fills: rows separate by
       spacing and the you-row highlight alone */
    #due-crew.dc-frame {{ background: var(--dc-bg); border-radius: 12px;
      padding: 16px 18px 10px; }}
    /* 3.8.0: two of them, apart: the You bubble (Due, Plans, Insights) on
       top, and under it the board, your people (Crew, Squads) */
    #due-crew.dc-frame.dc-split {{ background: transparent; padding: 0; border-radius: 0; }}
    #due-crew.dc-split > .du {{ background: var(--dc-bg); margin: 0 0 12px; }}
    #due-crew .dc-sheet {{ background: var(--dc-bg); border-radius: 12px; padding: 16px 18px 10px; }}
    /* the deck screen is shared with Anki's own styles (26.x paints
       `.fancy table` with a glass fill) and other add-ons' CSS. None of
       them may redecorate this board: no borders, shadows, radii, or fills
       on the table — every rule below is scoped to #due-crew, and nothing
       here touches the page. The table never needs to scroll or be
       clipped: the name column absorbs the slack and ellipsizes. */
    #due-crew, #due-crew table, #due-crew tr, #due-crew th, #due-crew td {{
      border: 0 !important; box-shadow: none !important; outline: 0 !important; }}
    #due-crew table, #due-crew tr, #due-crew th, #due-crew td {{
      border-radius: 0 !important; background: transparent !important; }}
    /* the one fill inside the card: your row (re-asserted after the reset) */
    #due-crew tr.you td {{ {you_bg.replace(";", " !important;") if you_bg else ""} }}
    #due-crew .dc-head {{ display: flex; align-items: center; justify-content: space-between;
      flex-wrap: wrap; gap: 8px 10px; margin-bottom: 10px; }}
    /* the pills stay one row; a narrow window puts them under the logo */
    #due-crew .dc-head > span:last-child {{ white-space: nowrap; }}
    #due-crew .dc-title {{ font-size: 15px; font-weight: 700; line-height: 0; }}
    /* 2.10: the logo is the title. Its squares are the board's: the accent,
       and the line colour for the day off. */
    #due-crew .dc-mark {{ display: inline-block; height: 17px; width: auto; vertical-align: middle; }}
    #due-crew .dc-mark .on {{ fill: var(--dc-accent); }}
    #due-crew .dc-mark .off {{ fill: var(--dc-line); }}
    #due-crew .dc-mark .wm {{ fill: var(--dc-mark); }}
    #due-crew .dc-card .dc-mark {{ display: block; height: 17px; margin: 0 auto 8px; }}
    #due-crew .dc-pill {{ display: inline-block; font-size: 11px; font-weight: 700;
      padding: 1px 10px; border: 1px solid var(--dc-line); color: var(--dc-muted); text-decoration: none; }}
    #due-crew .dc-pill.on {{ background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .dc-pill:first-child {{ border-radius: 99px 0 0 99px; }}
    #due-crew .dc-pill:last-child {{ border-radius: 0 99px 99px 0; }}
    #due-crew .dc-pill + .dc-pill {{ border-left: none; }}
    /* the row cap: ten rows, then the view scrolls inside the card. A row
       is the 13px line box (17px in Chromium) plus its padding, the header
       25px — measured in the preview, not assumed. The half row past the
       cap is the cue that there is more. The header stays put and needs a
       fill of its own, since rows slide under it. */
    #due-crew .dc-scroll {{ max-height: {25 + ROW_CAP * (17 + 2 * pad) + (17 + 2 * pad) // 2}px;
      overflow-y: auto; position: relative; }}
    #due-crew .dc-scroll th {{ position: sticky; top: 0; z-index: 1;
      background: var(--dc-bg) !important; }}
    #due-crew table {{ width: 100%; border-collapse: collapse; }}
    #due-crew th {{ padding: 2px 8px 6px; text-align: right; white-space: nowrap; }}
    #due-crew th a {{ color: var(--dc-muted); font-size: 11px; font-weight: 700; text-decoration: none; white-space: nowrap; }}
    #due-crew th a.on {{ color: var(--dc-accent); }}
    #due-crew td {{ padding: {pad}px 8px; white-space: nowrap; }}
    #due-crew td.nm {{ width: 100%; max-width: 0; overflow: hidden !important;
      text-overflow: ellipsis; }}
    #due-crew td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
    #due-crew td.rk {{ width: 30px; color: var(--dc-muted); }}
    #due-crew th.lt {{ text-align: left; font-weight: 400; }}
    #due-crew th.lt, #due-crew th.sqh {{ color: var(--dc-muted); font-size: 11px; }}
    #due-crew th.sqh {{ text-align: center; padding: 2px 3px 6px; font-weight: 700; }}
    #due-crew th.sqh.on {{ color: var(--dc-accent); }}
    #due-crew td.sqc {{ text-align: center; padding-left: 3px; padding-right: 3px; width: 18px; }}
    #due-crew .sq {{ display: inline-block; width: 12px; height: 12px; border-radius: 2px;
      background: var(--dc-well); vertical-align: middle; }}
    #due-crew .sq.on {{ background: var(--dc-accent); }}
    #due-crew .sq.away {{ background: var(--dc-well); box-shadow: inset 0 0 0 2px var(--dc-accent); opacity: 0.5; }}
    /* 3.9.1 (Sam's pick, "Cheers, clearer"): a cheer is a pill after the name, in place of the faint 🎉
       column at the end; it shows only while the pointer's on the name (or a key's on it), never always
       (Sam: "only show up when scrolling on a name, not persistent all the time") */
    #due-crew a.dc-cpill {{ display: none; margin-left: 6px; padding: 0 8px; border: 1px solid var(--dc-accent); border-radius: 99px;
      color: var(--dc-accent); font-size: 10.5px; font-weight: 700; line-height: 16px; text-decoration: none; white-space: nowrap;
      vertical-align: 1px; }}
    #due-crew td.nm:hover a.dc-cpill, #due-crew td.nm:focus-within a.dc-cpill {{ display: inline-block; }}
    /* a long name gives way so its pill is never cut off: it ends a little sooner while the pill shows */
    #due-crew td.nm:hover a.dc-pl, #due-crew td.nm:focus-within a.dc-pl {{
      display: inline-block; max-width: 56%; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }}
    #due-crew tr.you a.dc-pl {{ max-width: none; }}
    #due-crew a.dc-cpill:hover, #due-crew a.dc-cpill:focus-visible {{ background: var(--dc-accent); color: var(--dc-accent-ink); outline: none; }}
    #due-crew tr.you td {{ {you_bg} }}
    #due-crew tr.you td.nm {{ font-weight: 700; }}
    #due-crew tr.dim td {{ color: var(--dc-faded); }}
    /* Q3: long-quiet friends, folded into one line until it's clicked */
    #due-crew tr.qh {{ display: none; }}
    #due-crew table.qopen tr.qh {{ display: table-row; }}
    #due-crew tr.qfold td {{ text-align: left; }}
    #due-crew tr.qfold a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .la {{ font-size: 10px; margin-left: 5px; }}
    #due-crew small.nwh {{ display: block; height: 5.5px; }}
    #due-crew small.nw {{ display: block; font-size: 10px; line-height: 1.1;
                          color: var(--dc-muted); font-weight: 400; }}
    #due-crew .la.fresh {{ color: var(--dc-fresh); }} #due-crew .la.hours {{ color: var(--dc-hours); }}
    #due-crew .la.faded {{ color: var(--dc-faded); }}
    #due-crew .dc-foot {{ display: flex; gap: 10px; font-size: 10.5px; color: var(--dc-muted); padding: 8px 4px 0; }}
    #due-crew .dc-foot .sp {{ flex: 1; }}
    #due-crew .dc-foot .fl, #due-crew .dc-foot .fr {{ display: inline-flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }}
    #due-crew .dc-foot a.pb {{ border: 1px solid var(--dc-accent); border-radius: 99px; padding: 1px 9px; }}
    #due-crew .dc-foot a.pb.on {{ background: var(--dc-accent); color: var(--dc-bg); }}
    #due-crew .dc-foot a.warn {{ color: var(--dc-hours); }}
    #due-crew .dc-foot a.ic {{ color: var(--dc-muted); font-weight: 400; font-size: 13px; }}
    #due-crew .dc-wrap[hidden] {{ display: none; }}
    #due-crew .dc-wrap a.wn {{ color: var(--dc-muted); text-decoration: none; font-size: 11px; white-space: nowrap; margin-left: 8px; }}
    #due-crew .dc-empty {{ border: 1px dashed var(--dc-accent); border-radius: 10px; padding: 12px 14px; margin: 8px 0 2px;
      display: grid; gap: 8px; font-size: 12px; }}
    #due-crew .dc-empty .row {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
    #due-crew .dc-empty .dc-code {{ font-size: 18px; letter-spacing: 3px; }}
    #due-crew .dc-empty input {{ flex: 1 1 160px; font: inherit; padding: 4px 8px; border: 1px solid var(--dc-line);
      border-radius: 6px; background: var(--dc-bg); color: var(--dc-ink); }}
    #due-crew .dc-empty a.bt {{ border: 1px solid var(--dc-accent); border-radius: 6px; padding: 3px 12px; font-weight: 700;
      color: var(--dc-accent); text-decoration: none; }}
    #due-crew .dc-empty a.bt.on {{ background: var(--dc-accent); color: var(--dc-bg); }}
    #due-crew .dc-foot a {{ color: var(--dc-accent); text-decoration: none; font-weight: 700;
      white-space: nowrap; }}
    #due-crew .dc-note {{ font-style: italic; font-size: 11px; }}
    #due-crew a.dc-pl {{ color: inherit; text-decoration: none;
      border-bottom: 1px dotted var(--dc-line); }}
    #due-crew a.dc-pl:hover {{ color: var(--dc-accent); border-bottom-color: var(--dc-accent); }}
    #due-crew .dc-wrap {{ display: flex; align-items: center; gap: 10px;
      border: 1px solid var(--dc-accent); border-radius: 10px; padding: 8px 12px;
      font-size: 12px; margin-bottom: 10px; }}
    #due-crew .dc-wrap .wc {{ margin-left: auto; color: var(--dc-accent);
      text-decoration: none; font-weight: 700; font-size: 10.5px; white-space: nowrap; }}
    /* a banner's second action sits beside the first: two auto margins would split the free space between them */
    #due-crew .dc-wrap .wc + .wc {{ margin-left: 4px; }}
    #due-crew .dc-wrap.cl-earn {{ text-align: left; }}
    #due-crew .dc-wrap .wx {{ color: var(--dc-muted);
      text-decoration: none; font-weight: 700; }}
    #due-crew .dc-wrap.inv {{ text-align: left; }}
    #due-crew .dc-wrap .yn {{ margin-left: auto; display: flex; gap: 12px; white-space: nowrap; }}
    #due-crew .dc-wrap .yn .wc {{ margin-left: 0; font-size: 12px; }}
    #due-crew .dc-delta {{ font-size: 10px; font-weight: 700; color: var(--dc-accent);
      margin-left: 6px; }}
    #due-crew th .hi {{ display: none; }}
    #due-crew .chip {{ font-size: 10px; margin-left: 5px; white-space: nowrap; color: var(--dc-muted); }}
    #due-crew .chip.live {{ color: var(--dc-fresh); font-weight: 700; }}
    #due-crew .chip.exam {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .awb {{ font-size: 10px; font-weight: 700; color: var(--dc-hours);
      margin-left: 5px; white-space: nowrap; }}
    #due-crew .dc-stw {{ position: relative; display: block; max-width: 100%;
      margin: 2px 0 1px; padding-top: 4px; overflow: hidden; line-height: 0; }}
    #due-crew .dc-stw::before {{ content: ""; position: absolute; top: 0; left: 9px;
      border: 4px solid transparent; border-top: 0; border-bottom-color: var(--dc-well); }}
    #due-crew .dc-st {{ display: inline-block; max-width: 100%; box-sizing: border-box;
      padding: 2px 8px; border-radius: 10px; background: var(--dc-well);
      color: var(--dc-muted); font-size: 11px; font-weight: 400; line-height: 1.4;
      white-space: nowrap; overflow: hidden; text-overflow: ellipsis; vertical-align: top; }}
    #due-crew tr.you .dc-stw::before {{ border-bottom-color: var(--dc-bg); }}
    #due-crew tr.you .dc-st {{ background: var(--dc-bg); font-weight: 400; }}
    #due-crew .dc-wrap.eve {{ border-color: var(--dc-hours); }}
    /* 2.12: study rooms */
    #due-crew .dc-room {{ display: grid; grid-template-columns: auto 1fr auto; gap: 12px; align-items: center;
      border: 1px solid var(--dc-accent); border-radius: 12px; padding: 10px 12px; margin-bottom: 10px; }}
    #due-crew .dc-room .rg {{ width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center;
      background: conic-gradient(var(--dc-accent) calc(var(--p) * 360deg), var(--dc-line) 0); }}
    #due-crew .dc-room .rg.brk {{ background: conic-gradient(var(--dc-hours) calc(var(--p) * 360deg), var(--dc-line) 0); }}
    #due-crew .dc-room .rg b {{ width: 31px; height: 31px; border-radius: 50%; background: var(--dc-bg);
      display: grid; place-items: center; font-size: 12px; }}
    #due-crew .dc-room .rt {{ display: grid; gap: 4px; min-width: 0; font-size: 12.5px; }}
    #due-crew .dc-room .rt small {{ color: var(--dc-muted); font-size: 11.5px; }}
    #due-crew .dc-room .rb {{ display: flex; gap: 3px; align-items: center; }}
    #due-crew .dc-room .rb i {{ height: 6px; border-radius: 3px; background: var(--dc-line); display: block; position: relative; overflow: hidden; }}
    #due-crew .dc-room .rb i u {{ position: absolute; left: 0; top: 0; bottom: 0; background: var(--dc-accent); display: block; }}
    #due-crew .dc-room .rb em {{ height: 3px; border-radius: 2px; background: var(--dc-hours); opacity: .45; display: block; }}
    #due-crew .dc-room .rw {{ display: flex; gap: 8px; align-items: center; }}
    #due-crew .dc-room .fc {{ display: inline-flex; }}
    #due-crew .dc-room .fc i {{ width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center;
      font-style: normal; font-size: 11px; font-weight: 700; color: var(--dc-accent); border: 2px solid var(--dc-bg);
      background: var(--dc-you-bg); margin-left: -6px; }}
    #due-crew .dc-room .fc i:first-child {{ margin-left: 0; }}
    #due-crew .dc-room .go {{ background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px;
      padding: 4px 12px; font-weight: 700; text-decoration: none; font-size: 12px; }}
    #due-crew .dc-room .lv {{ color: var(--dc-muted); text-decoration: none; font-size: 12px; }}
    #due-crew .dc-wrap .rdot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--dc-accent); flex: none; }}
    #due-crew .dc-foot .warn {{ color: var(--dc-hours); }}
    #due-crew .dg {{ margin-bottom: 12px; }}
    #due-crew .dgh {{ font-size: 12.5px; font-weight: 700; margin: 2px 0 5px; }}
    #due-crew .dgh .dsk {{ font-size: 11px; color: var(--dc-accent); text-decoration: none; margin-left: 8px; }}
    #due-crew .ihead {{ display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 12px; margin: 0 0 8px; }}
    #due-crew .ihead .dc-sw {{ padding: 0; }}
    #due-crew .ictx {{ text-align: left; font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .ihead .dc-sw + .ictx {{ margin-left: auto; }}
    #due-crew .ictx b {{ color: var(--dc-ink); }}
    #due-crew .ictx a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    /* 3.8.0, the topic map */
    #due-crew .tmap {{ display: flex; flex-wrap: wrap; gap: 3px; margin-top: 2px; }}
    #due-crew .tmap .tm {{ display: flex; flex-direction: column; justify-content: space-between; min-height: 44px; min-width: 0;
      border-radius: 6px; padding: 5px 7px; text-decoration: none; font-size: 11.5px; font-weight: 600; white-space: normal;
      color: var(--dc-ink); overflow: hidden; }}
    #due-crew .tmap .tm span {{ overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2;
      -webkit-box-orient: vertical; overflow-wrap: anywhere; }}
    #due-crew .tmap .tm b {{ font-size: 12px; font-variant-numeric: tabular-nums; }}
    #due-crew .tmap .tm {{ position: relative; }}
    #due-crew .tmap .tm .tmb {{ position: absolute; left: 0; bottom: 0; height: 3px; background: currentColor; opacity: .45; }}
    #due-crew .tm.sn, #due-crew .sw.sn {{ background: var(--dc-well); color: var(--dc-muted); }}
    #due-crew .ik select.tmby {{ -webkit-appearance: none; appearance: none; font: inherit; font-weight: 700;
      color: var(--dc-accent); background: transparent; border: 0; padding: 0 0 0 2px; margin: 0; cursor: pointer;
      text-transform: none; letter-spacing: 0; color-scheme: light dark; }}
    #due-crew .ik .tmsh {{ margin-left: 8px; color: var(--dc-accent); font-weight: 700; text-decoration: none;
      text-transform: none; letter-spacing: 0; white-space: nowrap; }}
    #due-crew .ik .tmbv {{ font-style: normal; font-size: 9px; color: var(--dc-accent); margin-left: 2px; pointer-events: none; }}
    #due-crew .tmap .tm span i {{ font-style: normal; margin-left: 3px; opacity: .7; }}
    #due-crew .tmt {{ font-size: 11.5px; color: var(--dc-muted); margin: 1px 0 4px; text-align: left; }}
    #due-crew .tmt b {{ color: var(--dc-ink); }}
    #due-crew .tmt a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .tmap .tm:hover {{ filter: brightness(.94); }}
    #due-crew .tm.s3, #due-crew .sw.s3 {{ background: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .tm.s2 {{ background: color-mix(in srgb, var(--dc-accent) 55%, var(--dc-bg)); }}
    #due-crew .tm.s1 {{ background: color-mix(in srgb, var(--dc-accent) 25%, var(--dc-bg)); }}
    #due-crew .tm.s0, #due-crew .sw.s0 {{ background: var(--dc-hours); color: var(--dc-bg); }}
    #due-crew .iexam {{ position: relative; display: inline-flex; align-items: baseline; gap: 2px; }}
    #due-crew .iexam .q {{ color: var(--dc-muted); font-weight: 400; padding: 0 2px; }}
    #due-crew .iexam input.ixd {{ position: absolute; left: 0; bottom: 0; width: 1px; height: 1px; opacity: 0; border: 0; padding: 0;
      pointer-events: none; }}
    #due-crew .ideck {{ font-size: 13px; color: var(--dc-ink); }}
    #due-crew .ideck + .ictx {{ margin-left: auto; }}
    #due-crew .iexam input {{ font: inherit; color: var(--dc-ink); background: var(--dc-bg); border: 1px solid var(--dc-line);
      border-radius: 6px; padding: 1px 4px; margin: 0; color-scheme: light dark; }}
    #due-crew .dr {{ display: flex; align-items: center; gap: 10px; padding: 3px 0; font-size: 12px; }}
    #due-crew .dr.me .dn {{ font-weight: 700; }}
    #due-crew .dn {{ width: 90px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; }}
    #due-crew .dtrack {{ position: relative; flex: 1; min-width: 70px; height: 12px; background: var(--dc-well);
      border: 1px solid var(--dc-line); border-radius: 2px; overflow: hidden; }}
    #due-crew .dtrack i {{ position: absolute; left: 0; top: 0; bottom: 0; display: block; }}
    #due-crew .dtrack .fo, #due-crew .dkey .fo {{ opacity: 0.5; background: repeating-linear-gradient(
      135deg, var(--dc-accent) 0 1.5px, transparent 1.5px 5px); }}
    #due-crew .dtrack .fs, #due-crew .dkey .fs {{ background: var(--dc-accent); opacity: 0.35; }}
    #due-crew .dtrack .fm, #due-crew .dkey .fm {{ background: var(--dc-accent); }}
    #due-crew .dkey i {{ display: inline-block; width: 12px; height: 8px; border-radius: 2px; margin: 0 4px 0 10px; vertical-align: 0; }}
    #due-crew .dkey i:first-child {{ margin-left: 0; }}
    #due-crew .dc-count {{ min-width: 118px; flex-shrink: 0; display: flex;
      flex-direction: column; align-items: flex-end; line-height: 1.25;
      white-space: nowrap; font-variant-numeric: tabular-nums; font-size: 11px;
      color: var(--dc-muted); }}
    #due-crew .dc-count .dc-delta {{ margin-left: 0; }}
    #due-crew .dc-line {{ font-size: 11.5px; color: var(--dc-muted); padding: 6px 0; }}
    #due-crew .dc-line a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .dc-live {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%;
      background: var(--dc-accent); box-shadow: 0 0 0 2px var(--dc-you-bg); margin: 0 3px 0 6px;
      vertical-align: 1px; }}
    /* 3.8.0: studying now breathes, slowly; ↻ turns while the board fetches (motion.js) */
    @keyframes dcbreathe {{ from {{ opacity: .4; transform: scale(.85); }} to {{ opacity: 1; transform: scale(1); }} }}
    @keyframes dcspin {{ to {{ transform: rotate(360deg); }} }}
    @media (prefers-reduced-motion: no-preference) {{
      #due-crew .dc-live {{ animation: dcbreathe 2.4s ease-in-out infinite alternate; }}
      #due-crew .dc-foot a.ic.dc-spin {{ display: inline-block; animation: dcspin .8s linear infinite; }}
    }}
    #due-crew .dc-plan {{ display: inline-block; width: 36px; height: 4px; border-radius: 2px;
      background: var(--dc-line); overflow: hidden; vertical-align: middle; margin: 0 4px 0 1px; }}
    #due-crew .dc-plan i {{ display: block; height: 100%; background: var(--dc-accent); }}
    #due-crew .dc-flag {{ font-size: 12px; padding: 6px 10px; margin-bottom: 10px; border-radius: 8px;
      background: var(--dc-well); display: flex; flex-wrap: wrap; gap: 4px 10px; }}
    #due-crew .dc-flag a {{ margin-left: auto; color: var(--dc-accent); font-weight: 700;
      text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-flag, #due-crew .dc-flag-h {{ text-align: left; }}
    #due-crew .dc-flag {{ align-items: center; }}
    #due-crew .dc-flag small {{ display: block; color: var(--dc-muted); font-size: 11px; }}
    #due-crew .dc-flag-h {{ font-size: 10.5px; font-weight: 700; letter-spacing: .05em;
      text-transform: uppercase; color: var(--dc-muted); margin: 2px 0 4px; }}
    #due-crew .dc-ask-st + a {{ margin-left: 0; }}
    #due-crew .dc-ask-st {{ margin-left: auto; align-self: center; font-size: 10.5px; font-weight: 700;
      border-radius: 5px; padding: 1px 6px; background: var(--dc-line); white-space: nowrap; }}
    #due-crew .dc-ask-st.on {{ color: var(--dc-accent); }}
    #due-crew .dc-code {{ font-family: Menlo, Consolas, monospace; font-weight: 700;
      letter-spacing: 1.5px; color: var(--dc-ink); }}
    /* a narrow window: headers keep their icons, the last-active chips go
       (a quiet row keeps its: that chip is the whole story), and the name
       gets the room. Until 2.9 every name shrank to three letters. */
    @media (max-width: 560px) {{
      #due-crew th .hl {{ display: none; }} #due-crew th .hi {{ display: inline; }}
      #due-crew td, #due-crew th {{ padding-left: 4px; padding-right: 4px; }}
      #due-crew tr:not(.dim) .la {{ display: none; }}
      #due-crew .dc-head .dc-mark {{ height: 14px; }}
      #due-crew .dc-room {{ grid-template-columns: auto 1fr; }}
      #due-crew .dc-room .rw {{ grid-column: 1 / -1; justify-content: flex-end; }}
    }}
    #due-crew .dc-sw {{ font-size: 11.5px; padding: 2px 0 8px; }}
    #due-crew .dc-sw a {{ color: var(--dc-muted); text-decoration: none; margin-right: 12px; }}
    #due-crew .dc-sw a.on {{ color: var(--dc-ink); font-weight: 700; box-shadow: inset 0 -2px var(--dc-accent);
      padding-bottom: 2px; }}
    #due-crew .dc-sw a.add {{ color: var(--dc-accent); font-weight: 700; }}
    #due-crew .dc-sw a i {{ font-style: normal; font-size: 10px; font-weight: 700; color: var(--dc-accent-ink);
      background: var(--dc-accent); border-radius: 99px; padding: 0 5px; margin-left: 4px; }}
    /* 3.8.0, head row B (Sam's pick): Crew's views, and a squad's names, in
       the table's top-left corner; what was there goes under the table.
       Decks has no table: its picker has a line of its own, with the key */
    #due-crew th.dc-corner {{ text-align: left; white-space: normal; }}
    #due-crew th.dc-corner .dc-sw {{ padding: 0; position: relative; top: 2px; }}
    #due-crew th.dc-corner .dc-sw a {{ display: inline-block; font-size: 11.5px; font-weight: 400; color: var(--dc-muted);
      max-width: 8em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: bottom; }}
    #due-crew th.dc-corner .dc-sw a.on {{ color: var(--dc-ink); font-weight: 700; }}
    #due-crew th.dc-corner .dc-sw a.add {{ color: var(--dc-accent); font-weight: 700; }}
    #due-crew .dc-pline {{ display: flex; align-items: baseline; flex-wrap: wrap; gap: 0 10px; text-align: left; padding: 0 8px; }}
    #due-crew .dc-sheet > .dc-sw {{ text-align: left; padding-left: 8px; }}  /* a squad with no table yet */
    @media (max-width: 560px) {{ #due-crew .dc-pline {{ padding: 0 4px; }} #due-crew .dc-sheet > .dc-sw {{ padding-left: 4px; }} }}
    #due-crew .dc-pline .dc-sw {{ padding-bottom: 6px; }}
    #due-crew .dc-pline .dkey {{ margin-left: auto; font-size: 11px; color: var(--dc-muted); }}
    #due-crew .dc-sum {{ text-align: left; padding: 6px 8px 0; }}
    #due-crew .dc-card {{ padding: 16px; text-align: center;
      border-radius: 12px; background: var(--dc-bg); }}
    #due-crew .dc-card b {{ font-size: 15px; display: block; margin-bottom: 5px; }}
    #due-crew .dc-card span {{ font-size: 12px; color: var(--dc-muted); }}
    #due-crew .dc-card a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    /* 3.1: a plan I follow (You › Plans since 3.8.0) */
    #due-crew .dc-pc {{ margin-bottom: 14px; }}
    #due-crew .dc-pc .pk {{ display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin: 2px 0 6px; }}
    #due-crew .dc-pc .pk b {{ font-size: 12.5px; }}
    #due-crew .dc-pc .pk span {{ font-size: 11px; color: var(--dc-muted); }}
    #due-crew .dc-pc .pk .acts {{ margin-left: auto; display: flex; gap: 12px; }}
    #due-crew .dc-pc .pk .acts a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 11.5px; }}
    #due-crew .dc-pc .miss {{ color: var(--dc-hours); font-size: 11px; }}
    #due-crew .dc-pc .n {{ color: var(--dc-muted); font-variant-numeric: tabular-nums; text-align: right;
      white-space: nowrap; font-size: 11px; }}
    #due-crew .dc-pc .pn {{ font-size: 12px; padding: 6px 0 0; border-top: 1px solid var(--dc-line);
      display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }}
    #due-crew .dc-pc .pn.warn {{ color: var(--dc-hours); }}
    #due-crew .dc-pc .pn a {{ margin-left: auto; color: var(--dc-accent); font-weight: 700;
      text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-pc .pn .acts {{ margin-left: auto; display: flex; gap: 12px; flex-wrap: wrap; }}
    #due-crew .dc-pc .pn .acts a {{ margin-left: 0; }}
    /* 3.8.0: at my own pace, Up next */
    #due-crew .dc-pc .pnx {{ text-align: left; margin-top: 4px; }}
    #due-crew .dc-pc .nx {{ display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; justify-content: space-between;
      padding: 7px 10px; border: 1px solid var(--dc-accent); border-radius: 8px; background: var(--dc-you-bg); }}
    #due-crew .dc-pc .nx .nx1 {{ font-size: 12.5px; min-width: 0; overflow-wrap: anywhere; }}
    #due-crew .dc-pc .nx .nx1 small {{ color: var(--dc-muted); font-size: 11.5px; }}
    #due-crew .dc-pc .nx .lbl {{ font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--dc-accent); margin-right: 4px; }}
    #due-crew .dc-pc .nx .nx2 {{ display: flex; gap: 6px; }}
    #due-crew .dc-pc .nx a.bt, #due-crew .dc-pc .nx a.bt2 {{ font-size: 12px; font-weight: 700; text-decoration: none; border-radius: 7px;
      padding: 4px 12px; white-space: nowrap; border: 1px solid var(--dc-accent); }}
    #due-crew .dc-pc .nx a.bt {{ background: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .dc-pc .nx a.bt2 {{ color: var(--dc-accent); background: transparent; }}
    #due-crew .dc-pc .pq, #due-crew .dc-pc .pnl {{ font-size: 11.5px; color: var(--dc-muted); margin: 6px 2px 0; }}
    #due-crew .dc-pc .pnl {{ color: var(--dc-ink); }}
    #due-crew .dc-pc .pq a, #due-crew .dc-pc .pnl a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .dc-pc .pq a.nx3 {{ font-weight: 600; }}  /* 3.8.1: Then's dates, each opens now */
    /* 3.5.0: a plan's week (Anki centres the Decks screen's text; the plan reads left to right) */
    #due-crew .dc-pc, #due-crew .dc-pways {{ text-align: left; }}
    #due-crew .wbar {{ display: block; height: 5px; background: var(--dc-well); border-radius: 3px; overflow: hidden; }}
    #due-crew .wbar i {{ display: block; height: 100%; background: var(--dc-accent); }}
    #due-crew .pwh {{ display: flex; align-items: center; gap: 10px; font-size: 12px; margin: 8px 0 6px; }}
    #due-crew .pwh .nav {{ display: flex; align-items: center; gap: 8px; }}
    #due-crew .pwh .nav a {{ font-size: 15px; line-height: 20px; }}
    #due-crew .pwh a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .pwh .site {{ margin-left: auto; font-weight: 600; }}
    #due-crew .pwk {{ display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 4px; }}
    #due-crew .pwk .pc {{ border: 1px solid var(--dc-line); border-radius: 8px; padding: 4px 5px 5px; min-height: 64px;
      display: flex; flex-direction: column; gap: 3px; cursor: default; min-width: 0; text-align: left; }}
    #due-crew .pwk .pc[onclick] {{ cursor: pointer; }}
    #due-crew .pwh .nav .tb {{ padding: 0 2px; font-size: 12px; font-weight: 700; }}
    #due-crew .pwh .nav .tb.here {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .pwk .d b.td {{ background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 99px; padding: 0 6px; white-space: nowrap; }}
    #due-crew .pwk .d b.td .dow {{ color: inherit; }}
    #due-crew .pwk .pc.past {{ background: var(--dc-well); }}
    #due-crew .pwk .pc.sel {{ border: 2px solid var(--dc-accent); padding: 3px 4px 4px; }}
    #due-crew .pwk .pc.off {{ opacity: .6; }}
    #due-crew .pwk .d {{ display: flex; justify-content: space-between; gap: 4px; font-size: 10.5px; color: var(--dc-muted); }}
    #due-crew .pwk .d b {{ color: var(--dc-ink); }}
    #due-crew .pwk .d .dow {{ font-weight: 500; color: var(--dc-muted); }}
    #due-crew .pwk .chip {{ background: var(--dc-well); border-radius: 5px; padding: 1px 4px; font-size: 10.5px; font-weight: 600;
      white-space: normal; text-align: left;
      line-height: 1.25; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
      overflow-wrap: anywhere; }}
    #due-crew .pwk .pc.past .chip {{ background: var(--dc-bg); }}
    #due-crew .pwk .chip.done {{ background: none; color: var(--dc-muted); font-weight: 500; }}
    #due-crew .pwk .chip.skip {{ background: none; color: var(--dc-faded); text-decoration: line-through; font-weight: 500; }}
    #due-crew .pwk .chip.ev {{ background: none; border: 1.3px solid var(--dc-ink); }}
    #due-crew .pwk .chip.mv {{ background: none; border: 1px dashed var(--dc-accent); }}
    #due-crew .pwk .tag {{ font-size: 9.5px; color: var(--dc-muted); font-weight: 600; }}
    #due-crew .pwk .wbar {{ margin-top: auto; height: 4px; }}
    #due-crew .abar {{ display: block; height: 5px; border-radius: 3px; background: var(--dc-you-bg); box-shadow: inset 0 0 0 1px var(--dc-line); overflow: hidden; }}
    #due-crew .pwk .lm {{ font-size: 10.5px; color: var(--dc-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
    #due-crew .pwk .lm .late {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .abar i {{ display: block; height: 100%; background: var(--dc-accent); border-radius: 3px; }}
    #due-crew .abar.late i {{ background: var(--dc-hours); }}
    #due-crew .pwk .d .late {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .pkey {{ display: flex; gap: 12px; flex-wrap: wrap; font-size: 10.5px; color: var(--dc-muted); margin: 4px 0 2px; text-align: left; }}
    #due-crew .pkey i {{ display: inline-block; width: 14px; height: 5px; border-radius: 3px; margin-right: 4px; vertical-align: middle; }}
    #due-crew .pkey .kn {{ background: var(--dc-accent); }} #due-crew .pkey .kc {{ background: var(--dc-you-bg); }}
    #due-crew .pday .abar {{ width: 140px; max-width: 40%; }}
    #due-crew .pwk .pc.past .wbar {{ background: var(--dc-bg); }}
    #due-crew .pday {{ border: 1px solid var(--dc-line); border-radius: 10px; padding: 8px 10px; margin-top: 6px;
      display: grid; gap: 5px; font-size: 12px; }}
    #due-crew .pday[hidden] {{ display: none; }}
    #due-crew .pday .r {{ display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; }}
    #due-crew .pday .r .u {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .pday .r .acts, #due-crew .pday > .acts {{ display: flex; gap: 12px; justify-content: flex-end; }}
    #due-crew .pday .r .mv {{ color: var(--dc-muted); font-size: 12px; }}
    #due-crew .pday a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .pday .wi {{ display: grid; gap: 2px; margin: 1px 0 5px; padding-left: 9px; border-left: 2px solid var(--dc-line);
                           font-size: 11.5px; color: var(--dc-muted); text-align: left; }}
    #due-crew .pday .wi b {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .pday .wi .rm {{ font-style: italic; overflow-wrap: anywhere; }}
    #due-crew .pday .wi .acts {{ display: flex; gap: 12px; }}
    /* 3.8.1: a day's line (the plan's, then mine), and why a date left cards shut */
    #due-crew .pday .pdl {{ font-size: 11.5px; color: var(--dc-muted); margin-top: -3px; text-align: left; }}
    #due-crew .pday .pwhy {{ font-size: 11.5px; color: var(--dc-muted); margin: -2px 0 4px; padding-left: 11px; text-align: left; }}
    #due-crew .pday .pwhy a.tp {{ font-weight: inherit; }}
    /* 3.8.0: a set of cards that opens in Browse (a topic, "16 left"): one look
       everywhere, the board's green, as Today's (Sam: "pick one style and stick with it") */
    #due-crew a.tp {{ color: var(--dc-accent); font-weight: inherit; text-decoration: none; }}
    #due-crew a.tp:hover {{ text-decoration: underline; text-underline-offset: 2px; }}
    #due-crew .pcrew {{ font-size: 11.5px; color: var(--dc-muted); margin-top: 8px; }}
    #due-crew .pcrew a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    /* 3.7.3: a plan's squad (3.8.0: on the Squads tab) */
    #due-crew .tg {{ font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-muted); margin: 12px 0 4px; text-align: left; }}
    #due-crew .tg:first-child {{ margin-top: 2px; }}
    #due-crew .faces {{ display: flex; flex-wrap: wrap; gap: 8px 14px; text-align: left; }}
    #due-crew .face {{ display: grid; justify-items: center; gap: 1px; font-size: 11px; color: var(--dc-muted); min-width: 44px; }}
    #due-crew .face .e {{ font-size: 20px; line-height: 24px; }}
    #due-crew .face .e .dc-rsev {{ margin: 4px 0 0; }}
    #due-crew .face:not(:hover) .dc-rsev .sv, #due-crew .face:not(:hover) .dc-rsev .sv * {{ animation: none !important; }}
    #due-crew .ini {{ display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; background: var(--dc-you-bg); color: var(--dc-accent); font-size: 12px; font-weight: 700; line-height: 1; vertical-align: middle; }}
    #due-crew .ini.sm {{ width: 17px; height: 17px; font-size: 10px; }}
    #due-crew .face.away {{ opacity: .38; }}
    #due-crew .face b {{ color: var(--dc-ink); font-weight: 600; font-size: 11.5px; max-width: 64px;
      overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .face.more b {{ color: var(--dc-muted); }}
    #due-crew .tqa {{ display: flex; gap: 6px; align-items: center; margin: 2px 0 6px; }}
    #due-crew .tqa input {{ flex: 1; min-width: 0; font: inherit; font-size: 12.5px; color: var(--dc-ink); background: var(--dc-bg);
      border: 1px solid var(--dc-line); border-radius: 7px; padding: 5px 8px; }}
    #due-crew .tqa a, #due-crew .tq a, #due-crew .tjoin a, #due-crew .wk2 a {{
      color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 11.5px; white-space: nowrap; }}
    #due-crew .tq {{ border-top: 1px solid var(--dc-line); padding: 7px 0; margin-top: 0;  /* 3.8.0: rows, not boxes */
      display: grid; gap: 3px; text-align: left; font-size: 12px; overflow-wrap: anywhere; }}
    #due-crew .tq .t {{ display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }}
    #due-crew .tq .t .m {{ margin-left: auto; color: var(--dc-muted); font-size: 11px; white-space: nowrap; }}
    #due-crew .tq .t .acts {{ display: flex; gap: 10px; }}
    #due-crew .tq .t .acts a.q {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .tq .card {{ font-size: 11px; color: var(--dc-muted); }}
    #due-crew .tq .rep {{ border-left: 2px solid var(--dc-line); padding-left: 8px; font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .tq .rep b {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .tq .rep .ok {{ color: var(--dc-accent); font-weight: 700; }}
    #due-crew .tq .rep a {{ margin-left: 8px; font-size: 11px; }}
    #due-crew .tq .rep a.q {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .tjoin {{ border: 1px solid var(--dc-line); border-radius: 10px; padding: 10px 12px; display: grid; gap: 6px;
      text-align: left; font-size: 12px; }}
    #due-crew .tjoin a.bt {{ justify-self: start; background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px; padding: 4px 12px; }}
    #due-crew .tjoin .k, #due-crew .tq0 {{ color: var(--dc-muted); font-size: 11.5px; text-align: left; }}
    #due-crew .dc-ins {{ display: grid; gap: 14px; text-align: left; font-size: 12px; }}
    #due-crew .dc-ins a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-ins a.q {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .dc-ins a.tp {{ font-weight: inherit; white-space: normal; }}
    #due-crew .ihd {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; text-align: left; }}
    #due-crew .ihd b {{ font-size: 18px; font-variant-numeric: tabular-nums; }}
    #due-crew .ihd > span {{ font-size: 12px; }}
    #due-crew .ihd .m {{ color: var(--dc-muted); }}
    #due-crew .ispark path {{ fill: none; stroke: var(--dc-accent); stroke-width: 2; stroke-linejoin: round; }}
    #due-crew .ispark .end {{ fill: var(--dc-accent); stroke: var(--dc-bg); stroke-width: 2; }}
    #due-crew .ispark .hit, #due-crew .iwk .hit {{ fill: transparent; }}
    #due-crew .ihero {{ background: var(--dc-you-bg); border-radius: 10px; padding: 11px 13px; display: grid; gap: 4px; justify-items: start; }}
    #due-crew .ihero .k {{ font-size: 10.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--dc-accent); }}
    #due-crew .ihero .t {{ font-size: 14px; font-weight: 650; color: var(--dc-ink); }}
    #due-crew .dc-ins a.bt {{ margin-top: 4px; background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px; padding: 5px 13px; font-size: 12px; }}
    #due-crew .isec {{ display: grid; gap: 2px; border-top: 1px solid var(--dc-line); padding-top: 10px; }}
    #due-crew .ik {{ display: flex; flex-wrap: wrap; gap: 4px 0; align-items: baseline; font-size: 10.5px; font-weight: 700;
      letter-spacing: .06em; text-transform: uppercase; color: var(--dc-muted); margin-bottom: 4px; }}
    #due-crew .ik > span {{ text-transform: none; letter-spacing: 0; color: var(--dc-ink); font-weight: 600; }}
    #due-crew .ik .ikey {{ margin-left: auto; padding-left: 12px; color: var(--dc-muted); font-weight: 500; display: inline-flex; gap: 5px; align-items: center; }}
    #due-crew .sw {{ display: inline-block; width: 12px; height: 7px; border-radius: 2px; margin-left: 6px; }}
    #due-crew .sw.st {{ background: var(--dc-hours); }}
    #due-crew .sw.fg {{ background: color-mix(in srgb, var(--dc-hours) 40%, var(--dc-bg)); }}
    #due-crew .sw.pm {{ background: color-mix(in srgb, var(--dc-accent) 35%, var(--dc-bg)); }}
    #due-crew .sw.hx {{ background: repeating-linear-gradient(135deg, color-mix(in srgb, var(--dc-accent) 55%, var(--dc-bg)) 0 2px, color-mix(in srgb, var(--dc-accent) 18%, var(--dc-bg)) 2px 4px); }}
    #due-crew .irow {{ display: grid; grid-template-columns: minmax(0, 1fr) 120px 56px 64px; gap: 10px; align-items: center;
      padding: 5px 0; border-bottom: 1px solid var(--dc-line); }}
    #due-crew .irow:last-child {{ border-bottom: 0; }}
    #due-crew .irow .n {{ display: grid; min-width: 0; text-align: left; }}
    #due-crew .irow .n b {{ font-weight: 500; color: var(--dc-ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
      padding-bottom: 2px; }}  /* 3.8.0: room for the name's underline */
    #due-crew .irow .n span {{ font-size: 10.5px; color: var(--dc-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .irow .ib {{ position: relative; height: 9px; border-radius: 5px; background: var(--dc-well); overflow: hidden; }}
    #due-crew .irow .ib i {{ position: absolute; top: 0; bottom: 0; }}
    #due-crew .irow .ib .st {{ left: 0; background: var(--dc-hours); }}
    #due-crew .irow .ib .fg {{ background: color-mix(in srgb, var(--dc-hours) 40%, var(--dc-bg)); }}
    #due-crew .irow .c {{ text-align: right; color: var(--dc-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}
    #due-crew .irow .c b {{ color: var(--dc-ink); }}
    #due-crew .irow > a {{ text-align: right; }}
    #due-crew .iwk {{ overflow-x: auto; }}
    #due-crew .iwk svg {{ width: 100%; min-width: 460px; height: auto; display: block; overflow: visible; }}
    #due-crew .iwk .pm {{ fill: color-mix(in srgb, var(--dc-accent) 35%, var(--dc-bg)); }}
    #due-crew .iwk .h1 {{ fill: color-mix(in srgb, var(--dc-accent) 18%, var(--dc-bg)); }}
    #due-crew .iwk .h2 {{ fill: color-mix(in srgb, var(--dc-accent) 55%, var(--dc-bg)); }}
    #due-crew .iwk .g {{ stroke: var(--dc-line); stroke-dasharray: 2 3; }}
    #due-crew .iwk .base {{ stroke: var(--dc-line); }}
    #due-crew .iwk text {{ fill: var(--dc-muted); font-size: 10px; text-anchor: middle; }}
    #due-crew .iwk .yl {{ text-anchor: end; font-size: 9px; }}
    #due-crew .iwk .ax.b {{ fill: var(--dc-ink); font-weight: 700; }}
    #due-crew .iwk .ax.d {{ font-size: 9px; opacity: .8; }}
    #due-crew .iwk .ev {{ font-weight: 700; letter-spacing: .04em; }}
    #due-crew .iline {{ border-top: 1px solid var(--dc-line); padding-top: 10px; color: var(--dc-ink); }}
    @media (max-width: 560px) {{ #due-crew .irow {{ grid-template-columns: minmax(0, 1fr) auto auto; row-gap: 4px; }}
      #due-crew .irow .ib {{ grid-column: 1 / -1; grid-row: 2; }} }}
    #due-crew .wk2 {{ display: grid; grid-template-columns: minmax(0, 1fr) 64px 76px 150px; gap: 12px; align-items: center;
      font-size: 12px; padding: 5px 0; border-bottom: 1px solid var(--dc-line); text-align: left; }}
    #due-crew .wk2:last-child {{ border-bottom: 0; }}
    #due-crew .wk2 .sub {{ display: block; font-size: 11px; color: var(--dc-muted); }}
    #due-crew .wk2 .n {{ text-align: right; color: var(--dc-muted); font-variant-numeric: tabular-nums; }}
    #due-crew .wk2 .tr {{ font-size: 11px; }}
    #due-crew .wk2 .tr.up {{ color: var(--dc-hours); }}
    #due-crew .wk2 .tr.dn {{ color: var(--dc-accent); }}
    #due-crew .wk2 .acts {{ display: flex; gap: 10px; }}
    #due-crew .wk2.hd {{ font-size: 10.5px; color: var(--dc-muted); font-weight: 700; padding-bottom: 3px; }}
    #due-crew .dc-pways {{ display: grid; gap: 10px; margin: 4px 0 8px; }}
    #due-crew .dc-pways .t {{ font-size: 14px; }}
    #due-crew .dc-pways .ways {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }}
    #due-crew .dc-pways .way {{ display: grid; gap: 6px; align-content: start; font-size: 12px; }}
    #due-crew .dc-pways .way b {{ font-size: 13px; }}
    #due-crew .dc-pways .way a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .dc-pways input {{ font: inherit; font-size: 12px; padding: 3px 7px; border: 1px solid var(--dc-line);
      border-radius: 6px; background: var(--dc-bg); color: var(--dc-ink); min-width: 0; }}
    @media (max-width: 560px) {{
      #due-crew .wk2 {{ grid-template-columns: minmax(0, 1fr) auto auto; gap: 3px 10px; }}
      #due-crew .wk2 .acts {{ grid-column: 1 / -1; }}
      #due-crew .wk2.hd span:last-child {{ display: none; }}
      /* the week as a list */
      #due-crew .pwk {{ grid-template-columns: 1fr; }}
      #due-crew .pwk .pc {{ min-height: 0; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 6px; }}
      #due-crew .pwk .d {{ width: 100%; }}
      #due-crew .pwk .wbar {{ width: 100%; }}
      #due-crew .dc-pways .ways {{ grid-template-columns: 1fr; }}
      #due-crew .pwh {{ flex-wrap: wrap; }}
    }}
    </style>
    """


def _pycmd(cmd):
    """Only ids and keys ride in commands; anything else is dropped so a
    server-sourced id could never close the quote it sits in."""
    return f"pycmd('duecrew:{_re.sub(r'[^A-Za-z0-9:_.-]', '', str(cmd))}'); return false;"


def crew_views(show_up=False, hidden=frozenset()):
    """3.8.0: Crew's views, picked under the pills: Today, Week, Decks; in
    show-up mode This week (one view for both) and Decks. Decks can hide."""
    first = (("today", "This week"),) if show_up else CREW_VIEWS[:2]
    return first + (CREW_VIEWS[2:] if "decks" not in hidden else ())


def _crew_on(period, show_up=False):
    """The Crew view a period draws as: show-up mode draws Week as This week."""
    return "today" if show_up and period == "week" else period


def _head(period, show_up=False, hidden=frozenset(), crew="today", sev=None):
    """3.8.0: the board is your people: Crew and Squads. Crew's views are
    picked under the pills (_crew_picker), and the Crew pill goes back to
    the one last picked."""
    views = dict(crew_views(show_up, hidden))
    crew = _crew_on(crew, show_up)
    crew = crew if crew in views else "today"
    keys = (("crew", "Crew"), ("squads", "Squads"))
    on = "squads" if period == "squads" else "crew"
    keys = tuple((k, label) for k, label in keys if k not in hidden)
    pills = ""
    for key, label in keys:
        cls = "dc-pill on" if on == key else "dc-pill"
        pills += (f'<a class="{cls}" href="#" '
                  f'onclick="{_pycmd("period:" + (crew if key == "crew" else key))}">{label}</a>')
    # 3.8.1: Pip beside the logo, never on it (the logo itself never changes),
    # and only for a moment: it pops in, plays it, and goes (Sam)
    beside = (f'<a class="dc-sev once" href="#" title="Pip&rsquo;s closet" onclick="{_pycmd("closet")}" '
              f'style="--ago:{float(sev.get("ago") or 0):.2f}s">{_sev.slot(sev["svg"], 36)}</a>'
              if sev and sev.get("svg") else "")  # 3.8.2: Pip's closet is a click away
    return (f'<div class="dc-head"><span class="dc-title">{board_mark()}{beside}</span>'
            f'<span>{pills}</span></div>')


def _crew_picker(period, show_up=False, hidden=frozenset()):
    """3.8.0: Crew's views, picked as a squad is (the Squads tab's .dc-sw).
    Nothing when there's only one."""
    views = crew_views(show_up, hidden)
    if len(views) < 2:
        return ""
    period = _crew_on(period, show_up)
    on = ' class="on"'
    return ('<div class="dc-sw">' + "".join(
        f'<a{on if period == k else ""} href="#" onclick="{_pycmd("period:" + k)}">{t}</a>'
        for k, t in views) + "</div>")


def _corner(inner):
    """3.8.0, head row B (Sam's pick): a picker in the table's top-left
    corner, over the rank and the name, where the header was empty."""
    return f'<th class="lt dc-corner" colspan="2">{inner}</th>'


def _chip(row):
    """3.4 review, T1: the one thing beside a name, the most time-bound:
    a room or studying now, an exam within two weeks, back today, away,
    a plan week done. The rest is on the person's card. T2: green only
    for studying now, amber only for an exam; the others grey."""
    if row["quiet"]:
        return ""
    if row.get("room"):
        # the room's title is a friend's name: escaped
        return f' <span class="dc-live"></span><span class="chip live">in {_html.escape(str(row["room"]))}</span>'
    if row.get("live"):
        return ' <span class="dc-live"></span><span class="chip live">studying now</span>'
    if row.get("exam"):
        return f' <span class="chip exam">{_html.escape(str(row["exam"]))}</span>'
    if row.get("back"):
        return ' <span class="chip">back today</span>'
    if row.get("away"):
        away = str(row["away"])
        return f' <span class="chip">{_html.escape(away if away == "away" else "away · " + away)}</span>'
    r = row.get("recap")
    if r:
        return (f' <span class="chip" title="{_html.escape(str(r.get("name") or ""))}">'
                f'week {int(r.get("n") or 0)} done</span>')
    return ""


def _who(row, cfg):
    """3.8.2: a crew row's name, with their Pip in the emoji's place (Pip
    on), or their emoji (Pip off), as before."""
    fig = row_sev(row, cfg)
    return (fig, _html.escape(str(row["name"]))) if fig else ("", _label(row["name"], row.get("emoji")))


def _row_html(row, rank, cfg, period="today"):
    fig, name = _who(row, cfg)
    cls = ("you" if row["you"] else "") + (" sv" if fig else "")
    extra = ""
    la = ""
    if row["paused"]:
        cls += " dim"
        extra = ' <span class="dc-note">&middot; on a break</span>'
        cells = f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3
    elif row.get("notyet"):
        cls += " dim"
        # a phone's reviews reach us only once their computer's Anki syncs,
        # so say when we last heard, not that they haven't studied
        txt, _tone = _ago(row["last_updated"])
        when = f" as of {txt}" if txt and txt != "just now" else ""
        extra = (' <span class="la faded">&middot; nothing '
                 f'{"this week" if period == "week" else "yet"}{when}</span>')
        cells = f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3
    elif row["quiet"]:
        cls += " dim"
        cells = f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3
        # T2: when they last synced is a quiet row's whole story; the others
        # show it on their card
        txt, _tone = _ago(row["last_updated"])
        if txt:
            la = f'<span class="la faded">({txt})</span>'
    else:
        if row["stale"]:
            cls += " dim"
            extra = ' <span class="la faded">&middot; yesterday</span>'
        elif row.get("showup") and row.get("days_wk"):
            n = row["days_wk"]
            extra = f' <span class="la faded">&middot; {n} day{"s" if n != 1 else ""} this week</span>'
        # T5: how many were new shows on the Week tab, where it's the story
        cells = (f'<td class="n">{_reviews_cell(row["reviews"], row.get("new") if period == "week" else None)}</td>'
                 f'<td class="n">{_cell(row["time_ms"], _fmt_time)}</td>'
                 f'<td class="n">{_cell(row["retention"], lambda v: f"{v:.1f}%")}</td>'
                 f'<td class="n">{_cell(row["streak"])}</td>')
    chip = _chip(row)
    status = ""
    if row.get("status"):
        st = _html.escape(str(row["status"]))
        # 2.10: a status that starts with a number is a plan, ticked by the
        # day's reviews; without shared reviews it stays a plain status
        target = plan_target(row["status"])
        done = row.get("reviews")
        lead = ""
        if target and isinstance(done, int) and not row.get("stale"):
            if done >= target:
                lead = "&#10003; "
            else:
                pct = min(100, round(100 * done / target))
                lead = (f'&#128221; <span class="dc-plan"><i style="width:{pct}%"></i></span>'
                        f'{done:,} &middot; ')
        status = f'<div class="dc-stw"><span class="dc-st" title="{st}">{lead}{st}</span></div>'
    if row["you"]:
        cheer = ""
        name = (f'{fig}<a class="dc-pl" href="#" title="See what your crew sees" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{name}</a>')
    else:
        # 3.9.1: the cheer is a pill after the name (and its chip), where the eye already is
        cheer = (f'<a class="dc-cpill" href="#" title="Send a cheer" aria-label="Cheer {_html.escape(str(row["name"]), quote=True)}" '
                 f'onclick="{_pycmd("cheerpick:" + str(row["user_id"]))}">&#127881; Cheer</a>')
        # 3.0.1: right-click for Mute cheers and Report…
        # 3.8.2: their Pip opens the profile too, outside the name's underline
        sev_link = (f'<a class="dc-rsevl" href="#" tabindex="-1" aria-hidden="true" '
                    f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{fig}</a>') if fig else ""
        name = (sev_link + f'<a class="dc-pl" href="#" title="Open profile" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}" '
                f'oncontextmenu="{_pycmd("rowmenu:" + str(row["user_id"]))}">{name}</a>')
    return (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
            f'<td class="nm">{name}{chip}{la}{extra}{cheer}{status}</td>{cells}</tr>')


def _solo_html(data):
    """3.4 review, C5: until a friend adds me back, the invite is the board
    (in show-up mode too, 3.8.0)."""
    if len(data["entries"]) != 1:
        return ""
    code = str(data.get("my_code") or "")
    spaced = f"{code[:4]} {code[4:]}" if len(code) == 6 else code
    # 3.5.0: a friend's, a plan's or a squad's code, or a whole invite
    add = ("var v=(document.getElementById('dc-addcode').value||'').toUpperCase()"
           ".replace(/[^A-Z0-9 \\/]/g,' ').slice(0,200);"
           "pycmd('duecrew:addcode:'+v);return false;")
    pending = [str(x) for x in data.get("pending") or []]
    if not pending:
        wait = "Send a friend your invite. Once you’ve added each other, they’re here."
    elif len(pending) <= 2:
        wait = f"Waiting for {' and '.join(_html.escape(x) for x in pending)} to add you back."
    else:
        wait = f"Waiting for {len(pending)} people to add you back."
    return (f'<div class="dc-empty"><b>Bring your crew</b>'
            f'<span style="color: var(--dc-muted);">{wait}</span>'
            f'<div class="row">{f"<span class=dc-code>{_html.escape(spaced)}</span>" if code else ""}'
            f'<a class="bt on" href="#" onclick="{_pycmd("copyinvite")}">Copy invite</a></div>'
            f'<div class="row"><input id="dc-addcode" placeholder="A code, or paste an invite" '
            f'onkeydown="if(event.key===\'Enter\'){{{add}}}">'
            f'<a class="bt" href="#" onclick="{add}">Add</a></div></div>')


def _table_html(data, cfg, period, pick=""):
    """pick: Crew's views (_crew_picker), in the header's corner."""
    sort = sort_key(cfg)
    fresh, dormant = build_rows(data["entries"], data["labels"],
                                data.get("tomorrow", ""), period, cfg)
    heads = _corner(pick) if pick else "<th></th><th></th>"
    if sort == "week":
        sort = "reviews"
    for key, label in HEADERS:
        on = "on" if key == sort else ""
        arrow = " &#9662;" if key == sort else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{label}{arrow}</a></th>')
    if cfg.get("show_up"):
        fresh, dormant = build_rows(data["entries"], data["labels"],
                                    data.get("tomorrow", ""), "today", cfg)
        return _presence_html(fresh, dormant, data["labels"], data["entries"], pick, cfg) + _solo_html(data)
    body = ""
    n = 0  # show-up rows are counted, not ranked
    for row in fresh:
        if row.get("showup"):
            rank = "&#10003;"
        elif all(row.get(k) is None for k in ("reviews", "time_ms", "retention", "streak")):
            rank = "&mdash;"  # 3.8.0: nothing to rank (me alone, the day I joined), no medal
        else:
            n += 1
            rank = MEDALS[n - 1] if n <= 3 else f"#{n}"
        body += _row_html(row, rank, cfg, period)
    # Q3: friends quiet for 90+ days fold into one line under everyone
    long_q = [r for r in dormant if r["quiet"] and not r["you"] and _long_quiet(r["last_updated"])]
    for row in dormant:
        if row not in long_q:
            body += _row_html(row, "&mdash;", cfg, period)
    if long_q:
        body += _quiet_fold(long_q)
        for row in long_q:
            body += _row_html(row, "&mdash;", cfg, period).replace('<tr class="', '<tr class="qh ', 1)
    body = _even_rows(body)
    solo = _solo_html(data)
    # the name column ellipsizes, so the table can never outgrow the card;
    # past the row cap it scrolls inside it
    return _scroll(f'<table><tr>{heads}</tr>{body}</table>', body.count('<tr class=')) + solo


ROW_CAP = 10


def _scroll(html, rows):
    """Past ROW_CAP rows a view scrolls inside the card instead of growing
    the page: the header stays put and, after a render, the you-row is
    scrolled into view (keep_me_in_view_js). Under the cap nothing wraps,
    so small crews are untouched."""
    return f'<div class="dc-scroll">{html}</div>' if rows > ROW_CAP else html


def swap_js(html_out):
    """3.8.0: the board redrawn in place, without the jumps. While the
    pointer is on Due Crew (a tab clicked, a row ticked), neither part (the
    You box, the board) gets shorter: each keeps its height until the
    pointer leaves (or the window resizes), then lets go at once. A part
    still fetching (.dc-wait) keeps
    its height either way; a box folded by Hide folds at once."""
    return """
    (function() {
        var el = document.getElementById('due-crew');
        if (!el) { return; }
        var parts = [':scope > .du', '.dc-sheet'], was = {};
        var on = el.matches(':hover');
        parts.forEach(function (s) { var p = el.querySelector(s); if (p) { was[s] = p.getBoundingClientRect().height; } });
        // a to-do half typed when a redraw comes (a refresh, learning cards back): kept, with its day
        var din = document.getElementById('du-in'), keep = null;
        if (din && el.contains(din) && document.activeElement === din && din.value) {
            var w0 = document.getElementById('du-when'), d0 = document.getElementById('du-date');
            keep = {v: din.value, s: din.selectionStart, e: din.selectionEnd, w: w0 ? w0.value : null,
                    d: d0 ? d0.value : null, dd: d0 ? d0.style.display : null};
        }
        var tmp = document.createElement('div');
        tmp.innerHTML = %s;
        var nu = tmp.firstElementChild;
        var mo = null;  // 3.8.0: what changed moves (motion.js); the swap goes on whatever it does
        try { mo = window.dcMotion ? dcMotion.before(el) : null; } catch (e) { mo = null; }
        el.parentNode.replaceChild(nu, el);
        if (keep) {
            var n1 = document.getElementById('du-in');
            if (n1 && !n1.value) {
                n1.value = keep.v; n1.focus();
                try { n1.setSelectionRange(keep.s, keep.e); } catch (e) {}
                var w1 = document.getElementById('du-when'), d1 = document.getElementById('du-date');
                if (w1 && keep.w) { w1.value = keep.w; }
                if (d1 && keep.d !== null) { d1.value = keep.d; d1.style.display = keep.dd; }
                n1.dispatchEvent(new Event('input'));
            }
        }
        try { if (mo) { dcMotion.after(nu, mo); } } catch (e) {}
        var held = [];
        parts.forEach(function (s) {
            var p = nu.querySelector(s);
            if (!p || !was[s] || p.classList.contains('du-one')) { return; }
            if ((on || p.querySelector('.dc-wait')) && p.getBoundingClientRect().height < was[s] - 1) {
                p.style.boxSizing = 'border-box';
                p.style.minHeight = was[s] + 'px';
                held.push(p);
            }
        });
        if (held.length) {
            // let go at once when the pointer leaves, the window resizes or loses focus
            // (an eased release lagged behind a window being resized)
            var free = function () {
                held.forEach(function (p) { if (!p.querySelector('.dc-wait')) { p.style.minHeight = ''; } });
                window.removeEventListener('resize', free);
                window.removeEventListener('blur', free);
            };
            nu.addEventListener('mouseleave', free);
            window.addEventListener('resize', free);
            window.addEventListener('blur', free);
        }
    })();
    """ % _json.dumps(html_out)


# 3.8.0, pick 28: Find a setting. The box's index (settings_index) is in its
# data-ix; a pick on another tab asks for that tab, and the next draw lands on it.
FIND_JS = r"""
(function () {
  if (!window.dcFind) {
    window.dcFind = {
      want: null,
      ix: function (inp) { try { return JSON.parse(inp.getAttribute('data-ix') || '[]'); } catch (e) { return []; } },
      type: function (inp) {
        var box = inp.nextElementSibling, q = inp.value.toLowerCase().match(/[a-z0-9]+/g) || [], self = this;
        while (box.firstChild) { box.removeChild(box.firstChild); }
        if (!q.length) { box.hidden = true; return; }
        var hits = this.ix(inp).filter(function (x) {
          var k = ' ' + x.k;
          return q.every(function (w) { return k.indexOf(' ' + w) >= 0; });
        }).slice(0, 7);
        if (!hits.length) {
          var n = document.createElement('span'); n.className = 'st-none'; n.textContent = 'Nothing by that name';
          box.appendChild(n);
        }
        hits.forEach(function (h, i) {
          var b = document.createElement('button'), l = document.createElement('b'), w = document.createElement('small');
          b.type = 'button'; b.setAttribute('role', 'option'); if (!i) { b.className = 'on'; }
          l.textContent = h.l; w.textContent = h.w; b.appendChild(l); b.appendChild(w);
          b.addEventListener('click', function () { box.hidden = true; inp.value = ''; self.go(h); });
          box.appendChild(b);
        });
        box.hidden = false;
      },
      key: function (e, inp) {
        var box = inp.nextElementSibling;
        if (e.key === 'Escape') { inp.value = ''; box.hidden = true; return; }
        if (e.key === 'Enter') { e.preventDefault(); var b = box.querySelector('button'); if (b) { b.click(); } }
      },
      go: function (h) {
        var on = document.querySelector('#due-crew .dc-head .dc-pill.on');
        var tab = on ? (on.getAttribute('data-f') || '').split(':')[1] : '';
        if (tab === h.t) { this.land(h.f); return; }
        this.want = {f: h.f, at: Date.now()};
        pycmd('duecrew:settab:' + h.t);
      },
      land: function (f) {
        var el = document.querySelector('#due-crew [data-f="' + f + '"]') || document.querySelector('#due-crew [data-f^="' + f + '"]');
        if (!el) { return; }
        var row = el.closest('.st-row, .st-radio, .st-acts, .st-foot') || el;
        var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        row.scrollIntoView({block: 'center', behavior: still ? 'auto' : 'smooth'});
        row.classList.remove('st-hit'); void row.offsetWidth; row.classList.add('st-hit');
        setTimeout(function () { row.classList.remove('st-hit'); }, 2400);
        try { el.focus({preventScroll: true}); } catch (e) {}
      },
      after: function () {
        var w = this.want, self = this;
        this.want = null;
        if (w && Date.now() - w.at < 4000) { setTimeout(function () { self.land(w.f); }, 0); }  // after the swap's own focus
      }
    };
  }
  window.dcFind.after();
})();
"""

# 3.8.0: the board's motion, one file shared with duecrew.com (site/public/motion.js, byte for byte)
with open(_os.path.join(_os.path.dirname(__file__), "motion.js"), encoding="utf-8") as _f:
    MOTION_JS = _f.read()
# 3.9.0: how a cheer lands, a show over the whole Decks screen (shows.py picks which)
with open(_os.path.join(_os.path.dirname(__file__), "show.js"), encoding="utf-8") as _f:
    SHOW_JS = _f.read()


def keep_me_in_view_js():
    """Run after the board is drawn or swapped: a capped view starts with
    your own row in view, wherever it ranks. Nothing happens under the
    cap, or when you are already visible."""
    return """
    (function() {
        var box = document.querySelector('#due-crew .dc-scroll');
        if (!box) { return; }
        var me = box.querySelector('tr.you') || box.querySelector('.dr.me');
        if (!me) { return; }
        var want = me.offsetTop - (box.clientHeight - me.offsetHeight) / 2;
        if (want > 0) { box.scrollTop = want; }
    })();
    """ + DUE_JS + MOTION_JS + FIND_JS + MOTION_DRAWN


# 3.8.0, round two: the board remembers what it said, so a draw anew (back
# from a review, no swap) moves what changed while I was away (motion.js)
MOTION_DRAWN = """
try { if (window.dcMotion) { dcMotion.drawn(document.getElementById('due-crew')); } } catch (e) {}
"""


# a deck row without a "+N today" line holds its place, filled when another
# row has one, so the rows stay evenly spaced (_even_rows, for the bars)
_DD_ROOM = "<!--dd-->"


def _even_bars(html):
    if 'class="dc-delta"' in html:
        return html.replace(_DD_ROOM, '<span class="dc-delta">&nbsp;</span>')
    return html.replace(_DD_ROOM, "")


def _bar(name, is_me, d, delta=None, today_labels=()):
    """One person's progress through one shared deck. Three fills on one
    track: mature (solid), seen (faded), then unlocked-but-unseen (hatched) —
    so a deck worked through by unsuspending it a topic at a time shows how
    much is in play, not just a sliver of the whole. Everything is a percent
    of the person's own copy. The row's tooltip carries the exact numbers."""
    total = max(int(d.get("total") or 0), 1)
    seen, mature = int(d.get("seen") or 0), int(d.get("mature") or 0)
    pct = lambda n: min(100, round(100 * n / total))
    opened = d.get("open")
    open_html = ""
    if opened is not None:
        # the hatch starts where "seen" ends rather than lying under it: the
        # seen fill is translucent, and a hatch beneath it shows through
        # (caught by eye in the preview; the string tests couldn't see it)
        start = pct(seen)
        span = max(pct(int(opened)) - start, 0)
        open_html = f'<i class="fo" style="left:{start}%;width:{span}%;"></i>'
    counts = f'{seen:,} / {int(d.get("total") or 0):,}'
    ret = d.get("ret")
    if ret is not None:
        counts += f' &middot; {float(ret):.0f}%'
    chips = []
    # "today" is only true on the day it was written
    if d.get("today") and d.get("day") in today_labels:
        chips.append(f'+{int(d["today"]):,} today')
    if delta:
        chips.append(f'+{delta:,} wk')
    chip_html = (f'<span class="dc-delta">{" &middot; ".join(chips)}</span>' if chips else _DD_ROOM)
    tip = [f'{seen:,} seen', f'{mature:,} mature']
    if opened is not None:
        tip.append(f'{int(opened):,} unlocked')
    tip.append(f'{int(d.get("total") or 0):,} total')
    if delta:
        tip.append(f'+{delta:,} this week')
    if ret is not None:
        tip.append(f'{float(ret):.1f}% retention, last 7 days')
    return (f'<div class="dr{" me" if is_me else ""}" title="{_html.escape(" · ".join(tip))}">'
            f'<span class="dn">{_html.escape(str(name))}</span>'
            f'<div class="dtrack">{open_html}<i class="fs" style="width:{pct(seen)}%;"></i>'
            f'<i class="fm" style="width:{pct(mature)}%;"></i></div>'
            f'<span class="dc-count"><span>{counts}</span>{chip_html}</span></div>')


def _presence_html(fresh, dormant, labels, entries, pick="", cfg=None):
    """The board in show-up mode: one view in place of Today and Week — a
    square per day, Monday to today, nothing to rank. Sorted by days showed
    up, then name; today is the last square, so who showed up today reads
    off the right-hand column. pick: Crew's views, in the header's corner
    (3.8.0), and "N showed up today" goes under the table."""
    days_of = {e["user_id"]: e.get("days") or {} for e in entries}
    week = list(reversed(week_labels(labels)))  # Monday first
    # sorted by what is on screen: squares lit this week, then name
    lit = lambda r: sum(1 for lb in week if _showed(days_of.get(r["user_id"], {}).get(lb)))
    fresh = sorted(fresh, key=lambda r: (-lit(r), r["name"].lower()))
    today_n = sum(1 for r in fresh if r.get("studied_today"))
    letters = ""
    for lb in week:
        cls = "sqh on" if lb == labels[0] else "sqh"
        letters += f'<th class="{cls}">{"MTWTFSS"[datetime.fromisoformat(lb).weekday()]}</th>'
    said = f"{today_n} showed up today"
    heads = (_corner(pick) if pick else f'<th class="lt" colspan="2">{said}</th>') + letters
    body = ""
    for row in fresh + dormant:
        fig, name = _who(row, cfg or {"sev": False})
        name = fig + name
        cls, note = ("you" if row["you"] else "") + (" sv" if fig else ""), ""
        if row["paused"]:
            cls += " dim"
            note = ' <span class="dc-note">&middot; on a break</span>'
        elif row["quiet"]:
            cls += " dim"
            txt, tone = _ago(row["last_updated"])
            note = f' <span class="la {tone}">({txt})</span>' if txt else ""
        elif row["stale"]:
            cls += " dim"
            note = ' <span class="la faded">&middot; yesterday</span>'
        elif row.get("away"):
            note = f' <span class="la faded">&#9992;&#65039; {_html.escape(str(row["away"]))}</span>'
        docs = days_of.get(row["user_id"], {})
        cells = "".join(
            '<td class="sqc"><i class="sq %s"></i></td>' % (
                "on" if _showed(docs.get(lb)) else "away" if (docs.get(lb) or {}).get("away") else "")
            for lb in week)
        body += (f'<tr class="{cls.strip()}"><td class="rk"></td>'
                 f'<td class="nm">{name}{note}</td>{cells}</tr>')
    return (_scroll(f'<table><tr>{heads}</tr>{body}</table>', body.count('<tr class='))
            + (f'<div class="dc-line dc-sum">{said}</div>' if pick else ""))


def _tricky_html(tricky, mine=None):
    """2.10: cards a crewmate flagged, listed only when I have the same note.
    3.5.0, K3: under their own headings, "Asked of you" (asks about cards
    I have down first) and "Your asks", each with where it stands. Their
    text is theirs, and a card's text is my own copy's: escaped."""
    out = ""
    asked = (tricky or [])[:6]
    if asked:
        out += '<div class="dc-flag-h">Asked of you</div>'
    for t in asked:
        who = _html.escape(str(t.get("name", "?")))
        text = _html.escape(str(t.get("text") or "a card"))
        deck = _html.escape(str(t.get("deck") or ""))
        cmd = f'tricktip:{t.get("uid", "")}:{int(t.get("index", 0))}'
        q = _html.escape(str(t.get("q") or ""))
        where = f'&ldquo;{text}&rdquo;{" &middot; " + deck if deck else ""}' + (" &middot; you have this down" if t.get("known") else "")
        say = (f'&#129504; <b>{who}</b>: &ldquo;{q}&rdquo;' if q
               else f'&#129513; <b>{who}</b> finds this one tricky') + f'<small>{where}</small>'
        out += (f'<div class="dc-flag"><span>{say}</span>'
                f'<a href="#" title="One line; it shows when the card comes up for them" '
                f'onclick="{_pycmd(cmd)}">Tip</a></div>')
    mine = (mine or [])[:6]
    if mine:
        out += '<div class="dc-flag-h">Your asks</div>'
    for a in mine:
        text = _html.escape(str(a.get("text") or "a card"))
        who = [_html.escape(str(w)) for w in a.get("who") or []]
        if a.get("state") == "answered":
            said = f'{who[0] if who else "A crewmate"} answered'
            tag = f'<span class="dc-ask-st on">{len(who) or 1} tip{"" if len(who) <= 1 else "s"}</span>'
        else:
            said = (f'{", ".join(who[:2])}{" and more" if len(who) > 2 else ""} '
                    f'{"knows" if len(who) == 1 else "know"} this') if who else "Nobody's answered yet"
            tag = ('<span class="dc-ask-st">waiting</span>'
                   + (f'<a href="#" title="Your crew stops seeing it" '
                      f'onclick="{_pycmd("unask:" + str(int(a["index"])))}">Take back</a>'
                      if isinstance(a.get("index"), int) else ""))
        out += f'<div class="dc-flag"><span>&ldquo;{text}&rdquo;<small>{said}</small></span>{tag}</div>'
    return out


def _decks_html(data, deltas=None, tricky=None, plans=None, mine=None, sticking=None, pick=""):
    return _decks_body(data, deltas, sticking, pick, _tricky_html(tricky, mine))


def _plans_html(plans, people=None, cfg=None):
    """3.3: the plans, a card each; 3.5.0: with none, the ways in."""
    cards = (plans or {}).get("cards") or []
    return "".join(_plan_card_html(card, people, cfg) for card in cards) if cards else _plans_empty_html()


def _you_plans(plans, opened=None, people=None, cfg=None):
    """3.8.0, You › Plans: a plan offered to one of my squads, then each plan
    I follow; following none, the ways in. opened: this morning's line, here
    only when Due is off (it's under Today otherwise)."""
    if opened and not opened.get("dates") and (plans or {}).get("opened_dates"):
        opened = dict(opened, dates=plans["opened_dates"])  # 3.8.1: its dates, as Due's Today has them
    return (_opened_line(opened) + _invite_lines((plans or {}).get("invites"))
            + _offer_banners((plans or {}).get("offers")) + _plans_html(plans, people, cfg))


def _invite_lines(invites):
    """3.8.1: an invite to co-write a plan, or to keep one, a line each above
    the plans, with Yes and No. Names are the server's: escaped."""
    e = _html.escape
    out = ""
    for x in invites or []:
        pid, who, name = str(x.get("id", "")), e(str((x.get("by") or {}).get("name") or "?")), e(str(x.get("name") or "Plan"))
        said = (f"<b>{who}</b> offered you <b>{name}</b> to keep." if x.get("kind") == "owner"
                else f"<b>{who}</b> asked you to co-write <b>{name}</b>. Its tags would go on your notes in Anki.")
        out += (f'<div class="dc-wrap inv"><span>&#128221;</span><span>{said}</span><span class="yn">'
                f'<a class="wc" href="#" onclick="{_pycmd(f"planinvite:{pid}:yes")}">Yes</a>'
                f'<a class="wc" href="#" onclick="{_pycmd(f"planinvite:{pid}:no")}">No</a></span></div>')
    return out


def _opened_dates(dates):
    """3.8.1: what the morning opened, by date: "Renal physiology 80 ·
    Antiarrhythmics 40", each name opening Browse on that date's new cards;
    four or more: the first two "and 2 more". Names are the author's:
    escaped here."""
    dates = [d for d in dates or [] if isinstance(d, (list, tuple)) and len(d) >= 4]
    if not dates:
        return ""
    shown = dates if len(dates) <= 3 else dates[:2]
    out = " &middot; ".join(
        f'<a class="tp" href="#" title="Browse its new cards" onclick="{_pycmd(f"planopened:{d[0]}:{d[1]}")}">'
        f'{_html.escape(str(d[2]))}</a> {int(d[3]):,}' for d in shown)
    return ": " + out + (f" and {len(dates) - len(shown)} more" if len(dates) > len(shown) else "")


def _opened_line(op):
    """3.8.0, from the plan's old Today box: what this morning opened, with
    Not today (its undo; 3.8.1, the name the update line's has) while that's
    still Anki's latest step. 3.8.1: by date, each a way to its new cards."""
    n = int((op or {}).get("n") or 0)
    if not n:
        return ""
    # 3.8.0: Sync now while AnkiWeb hasn't had them (a phone gets them from there)
    sync = (f'<a href="#" title="Anki&rsquo;s sync, so your phone has them" onclick="{_pycmd("plansync")}">Sync now</a>'
            if op.get("sync") else "")
    by = _opened_dates(op.get("dates"))
    return (f'<div class="du-line"><span>This morning opened {n:,} new card{"s" if n != 1 else ""}{by or "."}</span>'
            f'<span class="acts">{sync}<a href="#" title="They open tomorrow morning" onclick="{_pycmd("plannottoday")}">'
            f'Not today</a></span></div>')


def _segs(segments):
    """[(text, bold)] from plans.py, escaped."""
    return "".join(f"<b>{_html.escape(str(t))}</b>" if b else _html.escape(str(t)) for t, b in segments)


def _plans_empty_html():
    """3.5.0: the Plans tab with no plan: three ways in."""
    add = ("var v=(document.getElementById('dc-plancode').value||'').toUpperCase()"
           ".replace(/[^A-Z0-9 \\/]/g,' ').slice(0,200);"
           "pycmd('duecrew:addcode:'+v);return false;")
    return (f'<div class="dc-pways"><b class="t">Follow a plan</b><div class="ways">'
            f'<div class="way"><b>Got a code?</b><input id="dc-plancode" placeholder="N4AP ULM2" '
            f'onkeydown="if(event.key===\'Enter\'){{{add}}}"><a href="#" onclick="{add}">Follow</a></div>'
            f'<div class="way"><b>Find one</b><a href="#" onclick="{_pycmd("planlibrary")}">The library &#8599;</a></div>'
            f'<div class="way"><b>Make one</b><a href="#" onclick="{_pycmd("planmake")}">Pick a deck&hellip;</a></div>'
            f'</div></div>')


def _plan_card_html(card, people=None, cfg=None):
    """3.5.0, a plan I follow (You › Plans since 3.8.0): the plan, what it
    says about now (_plan_now), this week as the site's calendar draws it
    (a list when narrow), one note at most, and the crew. Today is the tab
    beside it, so there's no Today box. Plan, date and event names are the
    author's: escaped here."""
    e = _html.escape
    pid = str(card.get("id", ""))
    out = (f'<div class="dc-pc"><div class="pk"><b>{e(str(card.get("title") or "Plan"))}</b>'
           f'<span>{e(str(card.get("sub") or ""))}</span>'
           f'<span class="acts"><a href="#" onclick="{_pycmd("planmenu:" + pid)}">Plan &#9662;</a></span></div>')
    tabs = card.get("tabs") or {}
    if card.get("no_deck"):
        out += (f'<div class="dc-line">No deck here has this plan&rsquo;s cards yet. '
                f'<a href="#" onclick="{_pycmd("plandeck:" + pid)}">Pick a deck</a></div>')
    out += _plan_now(card, pid) + _week_html(card, pid)
    notes = _plan_notes(card, pid)
    if notes:
        out += notes[0]
    crew = _squad_line(pid, tabs, people, cfg)
    if not crew:
        # 3.8.0: not in its squad: the crew who follow it, and the way in
        crew = _crew_line(card)
        if not card.get("team_ask"):
            join = f'<a href="#" onclick="{_pycmd(f"planteamjoin:{pid}:ask")}">Join its squad</a>'
            crew = f"{crew} &middot; {join}" if crew else join
    if crew:
        out += f'<div class="pcrew">{crew}</div>'
    return out + "</div>"


def _plan_now(card, pid):
    """3.8.0: what the plan's Today box said that Today, the tab beside it,
    doesn't: that it's paused, a day with no new cards, and the next
    exam's cards at risk (card["ins"], from Insights), with Study."""
    e = _html.escape
    if card.get("paused"):
        return (f'<div class="pn"><span>No new cards while it&rsquo;s paused.</span>'
                f'<span class="acts"><a href="#" onclick="{_pycmd("planresume:" + pid)}">Resume now</a></span></div>')
    out = _own_html(card.get("own"), pid) if card.get("own") else ""
    out += _quiz_line(card, pid)
    kind = (card.get("session") or {}).get("kind")
    if kind in ("rest", "catchup", "taper"):
        word = {"rest": "a rest day", "catchup": "in its catch-up week", "taper": "in its taper"}[kind]
        out += f'<div class="pn"><span>Today is {word}: reviews, and no new cards.</span></div>'
    ins = card.get("ins") or {}
    n = int(ins.get("n") or 0)
    if n and ins.get("did"):
        did = int(ins["did"])
        wd, dn = _ins_day(ins.get("day"))
        when = (f'<b>{e(str(ins["name"]))}</b> on {wd} {dn}' if ins.get("name") else f"{wd} {dn}")
        out += (f'<div class="pn"><span><a class="tp" href="#" title="Browse them" onclick="{_pycmd(f"insbrowse:{did}:h")}">'
                f'{n:,} card{"s" if n != 1 else ""}</a> Anki won&rsquo;t show you before {when}</span>'
                f'<span class="acts"><a href="#" onclick="{_pycmd(f"insstudy:{did}:h")}">Study {n:,}</a>'
                f'<a href="#" onclick="{_pycmd(f"youins:{did}")}">Insights &rsaquo;</a></span></div>')
    return out


def _quiz_line(card, pid):
    """3.8.1 (plans, rethought), Study for a quiz: from three days out, the
    event, its prep days left, the cards its dates opened here, and Study for
    it (one deck of them, the shakiest first). The event's name is the
    author's: escaped here."""
    qz = card.get("quiz")
    if not qz:
        return ""
    e = _html.escape
    pf = card.get("prep") or {}
    left = int(pf.get("left") or 0) if pf.get("day") == qz.get("day") and pf.get("name") == qz.get("name") else 0
    n = int(qz.get("open") or 0)
    when = "today" if qz.get("today") else f'on {e(str(qz.get("when") or ""))}'
    return (f'<div class="pn"><span>For <b>{e(str(qz.get("name") or "?"))}</b> {when}'
            + (f' &middot; {left} more day{"s" if left != 1 else ""} of prep' if left else "")
            + f' &middot; {n:,} card{"s" if n != 1 else ""} open from its dates</span>'
            f'<span class="acts"><a href="#" title="Its dates&rsquo; open cards in one deck, the shakiest first" '
            f'onclick="{_pycmd(f"planquiz:{pid}:" + str(qz.get("id") or ""))}">Study for it</a></span></div>')


def _own_html(ow, pid):
    """3.8.0, at my own pace: Up next with Open and Open and study, what
    follows, the last step's Undo (or Put back), and quiet lines: where the
    plan's dates are, my pace, the exam. No Behind. Names are the author's:
    escaped here."""
    e = _html.escape
    out = '<div class="pnx">'
    nx = ow.get("next")
    if nx:
        n = int(nx.get("n") or 0)
        out += (f'<div class="nx"><span class="nx1"><span class="lbl">Up next</span> <b>{e(str(nx.get("name") or "?"))}</b>'
                + (f' <small>{n:,} new</small>' if n else "") + '</span>'
                f'<span class="nx2"><a class="bt" href="#" onclick="{_pycmd("planpaceopen:" + pid)}">Open</a>'
                f'<a class="bt2" href="#" onclick="{_pycmd("planpacestudy:" + pid)}">Open and study</a></span></div>')
        then, more = ow.get("then") or [], int(ow.get("more") or 0)
        items = ow.get("then_items") or []
        if items:
            # 3.8.1: any date after Then opens now, ahead of the rest (and says so, with its Undo)
            then = []
            for x in items:
                go = _pycmd(f"planpaceopen:{pid}:{x.get('uid') or ''}")
                then.append(f'<a class="nx3" href="#" title="Open it now, ahead of the rest" onclick="{go}">'
                            f'{e(str(x.get("name") or "?"))}</a> {int(x.get("n") or 0):,}')
        else:
            then = [e(str(x)) for x in then]
        if then:
            out += f'<div class="pq">Then {" &middot; ".join(then)}{f" &middot; {more:,} more" if more else ""}</div>'
    else:
        out += '<div class="pq">Every date of it is open.</div>'
    if ow.get("last"):
        out += (f'<div class="pnl">{e(str(ow["last"]))} '
                f'<a href="#" onclick="{_pycmd("planpaceundo:" + pid)}">Undo</a></div>')
    elif ow.get("back"):
        b = ow["back"]
        out += (f'<div class="pq"><a href="#" onclick="{_pycmd("planpaceback:" + pid)}">Put back {e(str(b.get("name") or "?"))}</a>'
                f' &middot; {int(b.get("n") or 0):,} not seen yet</div>')
    said = " ".join(e(str(ow[k])) for k in ("at", "pace") if ow.get(k))
    if said:
        out += f'<div class="pq">{said}</div>'
    if ow.get("finish"):
        out += f'<div class="pq">{e(str(ow["finish"]))}</div>'
    return out + "</div>"


def _squad_line(pid, tabs, people=None, cfg=None):
    """3.8.0, the Plan tab's line about the plan's squad: faces, how many
    showed up, and the way there (the newest question from someone else
    when there is one). "" when I'm not in it. 3.8.22 (Sam: "under squad we
    haven't switched to pips"): who showed up are their Pips, as on the
    Squads tab (squad_pip: mine and a crewmate's in colour and look, anyone
    else plain), from the uids beside their emojis (who); Pip off, or a
    server without them, the emojis. people: {uid: crew entry}, mine too."""
    e = _html.escape
    s = tabs.get("summary")
    if not s:
        return ""
    emojis, who, people = s.get("faces") or [], s.get("who") or [], people or {}
    pips = [squad_pip(u, (people.get(u) or {}).get("name") or "A squadmate", (people.get(u) or {}).get("you"),
                      people, cfg, PCREW_PIP, k)
            for k, u in enumerate(who[:len(emojis)])] if cfg is not None and len(who) >= len(emojis) else []
    faces = (f'<span class="pips">{"".join(pips)}</span>' if pips and all(pips)
             else "".join(e(str(x)) for x in emojis))
    n, of = int(s.get("shown") or 0), int(s.get("of") or 0)
    out = f'{faces} Squad: {n} of {of} showed up' if n else f'Squad: {of} in it'
    last, unread = s.get("last"), int(tabs.get("unread") or 0)
    go = (f'{e(str(last.get("name") or "?"))} asked' if last and unread
          else f'{unread} new' if unread else "Open")
    return out.strip() + f' &middot; <a href="#" onclick="{_pycmd(f"squadplan:{pid}")}">{go} &rsaquo;</a>'


def _team_ago(at, now=None):
    import time as _time
    d = max(0, int((now or _time.time()) - int(at or 0)))
    if d < 60:
        return "now"
    if d < 3600:
        return f"{d // 60}m"
    if d < 86400:
        return f"{d // 3600}h"
    return "yesterday" if d < 2 * 86400 else f"{d // 86400}d"


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


def _plan_squad_html(pid, tabs, people=None, cfg=None):
    """3.8.0, a plan's squad on the Squads tab (the plan's Team tab until
    then): who showed up today, its bingo, Ask the squad and its threads,
    and the way out. Names, words and topics are other people's: escaped here."""
    e = _html.escape
    st, v = tabs.get("team_state"), tabs.get("team")
    if v is None:
        if st == "failed":
            return (f'<div class="tq0">Couldn&rsquo;t reach Due Crew. '
                    f'<a href="#" onclick="{_pycmd(f"planteamretry:{pid}")}">Try again</a></div>')
        return '<div class="tq0 dc-wait">Fetching&hellip;</div>'
    if not v.get("on"):
        n = int(v.get("count") or 0)
        return (f'<div class="tjoin"><b>{f"{n} in its squad" if n else "No one in its squad yet"}</b>'
                '<span class="k">The squad sees that you showed up today, and your questions and answers; '
                'your progress counts for the plan&rsquo;s authors. Never your numbers.</span>'
                f'<a class="bt" href="#" onclick="{_pycmd(f"planteamjoin:{pid}")}">Join its squad</a></div>')
    me = tabs.get("me")

    def who_face(x, size=None, small=False):  # 3.8.21: their Pip, as on the squad's table; Pip off, the emoji
        pip = squad_pip(x.get("uid"), x.get("name"), x.get("uid") == me, people, cfg, size) if cfg is not None else None
        return pip or face(x.get("emoji"), x.get("name"), small=small)
    faces = ""
    for f in v.get("faces") or []:
        name = "You" if f.get("uid") == me else str(f.get("name") or "?")
        faces += (f'<div class="face{"" if f.get("shown") else " away"}"><span class="e">{who_face(f, 40)}</span>'
                  f'<b>{e(name)}</b></div>')
    if int(v.get("more") or 0):
        more = int(v["more"])
        faces += f'<div class="face more"><span class="e">+</span><b>{more:,} more</b></div>'
    head = f'Showed up today &middot; {int(v.get("shown") or 0)} of {int(v.get("count") or 0)}'
    if int(v.get("streak") or 0) > 1:
        head += f' &middot; {int(v["streak"])} days running'
    out = f'<div class="tg">{head}</div><div class="faces">{faces}</div>'
    b = v.get("bingo")
    if b:
        from .team import bingo_line
        ev = b["ev"]
        cells = "".join(f'<i class="{"on" if (ev["middle"]["done"] if c == 4 else ev["squares"][CELLS_BINGO.index(c)]["done"]) else ""}"></i>'
                        for c in range(9))
        out += (f'<style>{BINGO_CSS}</style><div class="bg-card" style="margin-top:8px"><span class="bg-mini">{cells}</span>'
                f'<span class="bg-t"><b>Squad bingo</b><span>{e(bingo_line(ev))}</span></span>'
                f'<a href="#" onclick="{_pycmd(f"planteambingo:{pid}")}">Open</a></div>')
    draft = e(str(tabs.get("draft") or ""), quote=True)
    send = (f"var v=document.getElementById('dc-tqa-{_re.sub(r'[^A-Za-z0-9]', '', pid)}').value;"
            f"if(v.trim())pycmd('duecrew:planteamask:{pid}:'+encodeURIComponent(v.slice(0,280)));return false;")
    iid = f"dc-tqa-{_re.sub(r'[^A-Za-z0-9]', '', pid)}"
    out += (f'<div class="tg">Ask the squad</div><div class="tqa"><input id="{iid}" maxlength="280" '
            f'placeholder="Ask anything&hellip;" value="{draft}" onkeydown="if(event.key===\'Enter\'){{{send}}}">'
            f'<a href="#" onclick="{send}">Ask</a></div>')
    known = tabs.get("known") or {}
    down, have = set(known.get("down") or []), set(known.get("have") or [])
    for a in v.get("asks") or []:
        aid = int(a["id"])
        who = "You" if a.get("mine") else f'{who_face(a, small=True)} <b>{e(str(a.get("name") or "?"))}</b>'
        if a.get("guid"):
            on = " on a card you have down" if a["guid"] in down else " on a card"
            head = f'<span>{who}{on}</span>'
            body = f'<div>&ldquo;{e(str(a.get("text") or ""))}&rdquo;</div>'
        else:
            head = f'<span>{who}: {e(str(a.get("text") or ""))}</span>'
            body = ""
        reps = ""
        for r in a.get("replies") or []:
            rid = int(r["id"])
            rn = "You" if r.get("mine") else e(str(r.get("name") or "?"))
            extra = ""
            if a.get("mine") and not r.get("mine"):
                extra = f'<a href="#" onclick="{_pycmd(f"planteamhelped:{pid}:{rid}")}">{"Helped &#10003;" if r.get("helped") else "That helped"}</a>'
            elif r.get("helped"):
                extra = '<span class="ok"> &#10003; helped</span>'
            if r.get("remove"):
                extra += f'<a href="#" onclick="{_pycmd(f"planteamremove:{pid}:{rid}")}">Remove</a>'
            elif not r.get("mine"):
                extra += f'<a class="q" href="#" onclick="{_pycmd(f"planteamreport:{pid}:{rid}")}">Report</a>'
            reps += (f'<div class="rep"><b>{rn}</b>{" (author)" if r.get("author") else ""}: '
                     f'{e(str(r.get("text") or ""))}{extra}</div>')
        n_rep = len(a.get("replies") or [])
        bits = [x for x in (str(a.get("topic") or ""),
                            f'{n_rep} repl{"ies" if n_rep != 1 else "y"}' if n_rep else "") if x]
        acts = f'<a href="#" onclick="{_pycmd(f"planteamreply:{pid}:{aid}")}">{"Answer" if a.get("guid") else "Reply"}</a>'
        if a.get("guid") and a["guid"] in have:
            acts += f'<a href="#" onclick="{_pycmd(f"planteamcard:{pid}:{aid}")}">See the card</a>'
        if a.get("remove"):
            acts += f'<a class="q" href="#" onclick="{_pycmd(f"planteamremove:{pid}:{aid}")}">Remove</a>'
        elif not a.get("mine"):
            acts += f'<a class="q" href="#" onclick="{_pycmd(f"planteamreport:{pid}:{aid}")}">Report</a>'
        out += (f'<div class="tq"><div class="t">{head}<span class="m">{_team_ago(a.get("act") or a.get("at"))}</span></div>'
                f'{body}{reps}<div class="t"><span class="card">{e(" · ".join(bits))}</span>'
                f'<span class="acts">{acts}</span></div></div>')
    if not v.get("asks"):
        out += '<div class="tq0">No questions yet.</div>'
    return out + (f'<div class="dc-line"><a href="#" onclick="{_pycmd("duetab:plans")}">Open the plan</a> &middot; '
                  f'<a href="#" onclick="{_pycmd(f"planteamleave:{pid}")}">Leave</a></div>')


def _hm(m):
    m = int(m)
    return f"{m // 60} h {m % 60:02d}" if m >= 60 else f"{m} min"


def _ins_day(iso, today=""):
    try:
        d = _dt.date.fromisoformat(str(iso))
    except ValueError:
        return "", ""
    return ("Today" if str(iso) == today else f"{d:%a}"), str(d.day)


def _ins_spark(days):
    """The header's 14 days of right, a line; a day with no reviews is a gap."""
    pts = [(i, v) for i, v in enumerate(days) if v is not None]
    if len(pts) < 2:
        return ""
    lo = min(v for _i, v in pts)
    lo = min(lo, 70)
    xy = [(2 + i * 92 / max(1, len(days) - 1), 22 - (v - lo) / max(1, 100 - lo) * 20) for i, v in pts]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="hit"><title>{len(days) - 1 - i} days ago &middot; {v}% right</title></circle>'
                   for (x, y), (i, v) in zip(xy, pts))
    ex, ey = xy[-1]
    return (f'<svg class="ispark" viewBox="0 0 96 24" width="96" height="24" role="img" aria-label="Right, last 14 days">'
            f'<path d="{path}"/><circle class="end" cx="{ex:.1f}" cy="{ey:.1f}" r="3"/>{dots}</svg>')


def _you_insights(ins):
    """3.8.0, You › Insights: for everyone, a deck at a time, picked as a
    squad is. ins: team_flow.you_view: {decks: [{did, name, full}], did,
    exam: my exam date or "", view: the deck's Insights}. It's the deck's,
    plan or not: a plan I follow on it only sharpens it (its events
    aim the exam box, its dates name the topics, its behind line). Names are
    mine (decks) or authors' (plan events, topics): escaped."""
    e = _html.escape
    ins = ins or {}
    decks = ins.get("decks") or []
    if not decks:
        return '<div class="tq0">Insights fill in after a week of reviews.</div>'
    did = int(ins.get("did") or decks[0]["did"])
    on = ' class="on"'
    cur = next((d for d in decks if int(d["did"]) == did), decks[0])
    # 3.8.0 (Sam): the deck's name always shows: one deck, its name; more, the picker
    pick = (f'<b class="ideck" title="{e(str(cur.get("full") or cur["name"]))}">{e(str(cur["name"]))}</b>'
            if len(decks) < 2 else '<div class="dc-sw">' + "".join(
                f'<a{on if int(d["did"]) == did else ""} href="#" title="{e(str(d.get("full") or d["name"]))}" '
                f'onclick="{_pycmd("insdeck:" + str(int(d["did"])))}">{e(str(d["name"]))}</a>' for d in decks) + "</div>")
    # 3.8.0: my exam date, set right here (Settings has the same one): a link, Add exam
    # date, that opens the date picker; once set, the day itself, with × to take it off
    ex = str(ins.get("exam") or "")
    ex = ex if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", ex) else ""
    try:
        x = _dt.date.fromisoformat(ex) if ex else None
    except ValueError:
        x, ex = None, ""
    said = f"Exam {x:%a} {x.day} {x:%b}" if x else "Add exam date"
    off = (f' <a class="q" href="#" title="Take your exam date off" aria-label="Take your exam date off" '
           f'onclick="{_pycmd("setexam:off")}">&times;</a>' if x else "")
    ctx = (f'<span class="iexam" title="Your exam date. Your crew sees it for the two weeks before.">'
           f'<a href="#" onclick="var i=this.nextElementSibling;try{{i.showPicker();}}catch(x){{i.classList.remove(\'ixd\');i.focus();}}return false;">{said}</a>'
           f'<input class="ixd" type="date" value="{e(ex)}" aria-label="Exam date" '
           f'onchange="pycmd(\'duecrew:setexam:\'+(this.value||\'off\'));">{off}</span>')
    head = f'<div class="ihead">{pick}<span class="ictx">{ctx}</span></div>'
    return head + _insights_html(did, ins.get("view") or {})


def _ins_week(did, w, aim, today):
    """Your week in time: the last 7 days as studied, today (done, and what's
    left), and the next days at my own pace: what the plan asks, or (3.8.0,
    no plan) what Anki has due."""
    past, ahead = w.get("past") or [], w.get("ahead") or []
    cols = [("p", m, d, f"{_hm(m)} in this deck") for d, m in past]
    done = int(w.get("today_done") or 0)
    for i, (d, m, n, r) in enumerate(ahead):
        tip = f"about {_hm(m)}: {n:,} new and {r:,} reviews, at your pace"
        if i == 0:
            cols.append(("t", max(m, done), d, f"{_hm(done)} so far &middot; " + tip))
        else:
            cols.append(("f", m, d, tip))
    top = max([c[1] for c in cols] + [60])
    W, H, gap = 640, 90, 6
    bw = (W - gap * (len(cols) - 1)) / max(1, len(cols))
    hid = "hx" + _re.sub(r"[^A-Za-z0-9]", "", str(did))[:20]
    grid = "".join(f'<line class="g" x1="0" x2="{W}" y1="{H - H * h * 60 / top:.1f}" y2="{H - H * h * 60 / top:.1f}"/>'
                   f'<text class="yl" x="-5" y="{H - H * h * 60 / top + 3:.1f}">{h} h</text>'
                   for h in range(1, int(top // 60) + 1))
    bars = ""
    for i, (k, m, d, tip) in enumerate(cols):
        x, hgt = i * (bw + gap), H * m / top
        wd, dn = _ins_day(d, today)
        lab = _html.escape(f"{wd} {dn}")
        bars += f'<g><title>{lab} &middot; {tip}</title><rect class="hit" x="{x:.1f}" y="0" width="{bw:.1f}" height="120"/>'
        if k == "p":
            bars += f'<rect class="pm" x="{x:.1f}" y="{H - max(hgt, 1.5):.1f}" width="{bw:.1f}" height="{max(hgt, 1.5):.1f}" rx="3"/>'
        elif k == "t":
            hd = H * done / top
            bars += f'<rect class="pm" x="{x:.1f}" y="{H - hd:.1f}" width="{bw:.1f}" height="{hd:.1f}" rx="3"/>'
            if hgt - hd > 2:
                bars += f'<rect fill="url(#{hid})" x="{x:.1f}" y="{H - hgt:.1f}" width="{bw:.1f}" height="{hgt - hd - 2:.1f}" rx="3"/>'
        else:
            bars += f'<rect fill="url(#{hid})" x="{x:.1f}" y="{H - hgt:.1f}" width="{bw:.1f}" height="{hgt:.1f}" rx="3"/>'
        if aim.get("name") and d == aim.get("day"):
            last = i == len(cols) - 1
            anchor = ' style="text-anchor:end"' if last else ""
            bars += (f'<text class="ev" x="{x + (bw if last else bw / 2):.1f}" y="{H - hgt - 6:.1f}"{anchor}>'
                     f'{_html.escape(str(aim["name"])[:12])}</text>')
        bars += (f'<text class="ax{" b" if k == "t" else ""}" x="{x + bw / 2:.1f}" y="{H + 14}">{_html.escape(wd)}</text>'
                 f'<text class="ax d" x="{x + bw / 2:.1f}" y="{H + 25}">{dn}</text></g>')
    defs = (f'<defs><pattern id="{hid}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
            f'<rect width="6" height="6" class="h1"/><rect width="3" height="6" class="h2"/></pattern></defs>')
    to = (f" to {_ins_day(aim['day'])[0]}" if aim.get("name") and int(aim.get("in") or 99) <= 6 else " this week")
    return (f'<div class="isec"><div class="ik">Your week<span>&nbsp;&middot; about {_hm(w["avg"])} a day{to}'
            f' &middot; the last 7 days: {_hm(w.get("was") or 0)}</span>'
            f'<span class="ikey"><i class="sw pm"></i>your days <i class="sw hx"></i>{"what the plan asks" if w.get("src") != "anki" else "what Anki has due"}</span></div>'
            f'<div class="iwk"><svg viewBox="-24 0 664 120" role="img" aria-label="Minutes a day in this deck">{defs}{grid}'
            f'<line class="base" x1="0" x2="{W}" y1="{H}" y2="{H}"/>{bars}</svg></div></div>')


def _insights_html(did, v):
    """3.7.9 (mock "Insights"): mine alone, worked out in my Anki. The
    header's right, the cards Anki won't show me before the next exam (a
    plan's event, or my own date: 3.8.0) that I'd be under my target on by
    then, what's not sticking yet, my week in time, Optimize FSRS when my
    newest cards fall short, and the deck's suspended leeches. 3.8.0: a
    deck's, plan or not (did, its id, in each command)."""
    e = _html.escape
    v = v if isinstance(v, dict) else {}
    out = ""
    r = v.get("right") or {}
    now, before = r.get("now") or [0, 0], r.get("before") or [0, 0]
    if now[1] >= 50:
        pct = round(100 * now[0] / now[1])
        was = (f'<span class="m">{round(100 * before[0] / before[1])}% the 2 weeks before</span>' if before[1] >= 50 else "")
        out += (f'<div class="ihd" title="This deck, first answer of each card each day: '
                f'{now[0]:,} of {now[1]:,} right in 2 weeks"><b>{pct}%</b><span>right on reviews{" &middot; " + was if was else ""}</span>'
                f'{_ins_spark(r.get("days") or [])}</div>')
    aim = v.get("aim") or {}
    today = ""
    w = v.get("week")
    if w and w.get("ahead"):
        today = w["ahead"][0][0]
    hero = v.get("hero") or []
    if hero:
        k = int(aim.get("in") or 7)
        when, dn = _ins_day(aim.get("day"))
        days = f'{k} day{"s" if k != 1 else ""}'
        # 3.7.9: named for the event only when its prep dates are what's counted; else by the day.
        # 3.8.0: my own exam date (Settings) is named too, over the whole deck
        scoped = bool(aim.get("scoped") and aim.get("name"))
        mine = aim.get("kind") == "exam"
        lab = (f'{e(str(aim["name"]))} &middot; {when} {dn} &middot; {days}' if scoped
               else f'Your exam &middot; {when} {dn} &middot; {days}' if mine
               else f'Before {when} {dn} &middot; {days}')
        whose = "the plan&rsquo;s prep dates for it" if scoped else "this deck"
        out += (f'<div class="ihero"><div class="k">{lab}</div>'
                f'<div class="t" title="Started cards of {whose} that Anki won&rsquo;t show you before then, under your {int(v.get("target") or 90)}% by then (FSRS)">'
                f'<a class="tp" href="#" title="Browse them" onclick="{_pycmd(f"insbrowse:{did}:h")}">'
                f'{len(hero):,} card{"s" if len(hero) != 1 else ""}</a> Anki won&rsquo;t show you before {when}</div>'
                f'<a class="bt" href="#" onclick="{_pycmd(f"insstudy:{did}:h")}">Study {len(hero):,}</a></div>')
    if int(v.get("behind") or 0) and v.get("pid"):
        out += (f'<div class="iline">{int(v["behind"]):,} new cards behind &middot; '
                f'<a href="#" onclick="{_pycmd("plancatch:" + str(v["pid"]))}">Catch up&hellip;</a></div>')
    rows = v.get("rows") or []
    if rows:
        out += ('<div class="isec"><div class="ik">Not sticking yet<span>&nbsp;&middot; last 2 weeks</span>'
                '<span class="ikey"><i class="sw st"></i>not right yet <i class="sw fg"></i>forgot</span></div>')
        for i, x in enumerate(rows):
            of, st, fg = max(1, int(x["of"])), int(x["stuck"]), int(x["forgot"])
            tip = f'{x["name"]} · {of} cards reviewed in 2 weeks: {st} not right yet, {fg} forgotten after being right'
            out += (f'<div class="irow" title="{e(tip)}"><span class="n"><b><a class="tp" href="#" title="Browse them" '
                    f'onclick="{_pycmd(f"insbrowse:{did}:{i}")}">{e(str(x["name"]))}</a></b>'
                    f'<span>{e(str(x.get("src") or ""))}</span></span>'
                    f'<span class="ib"><i class="st" style="width:{100 * st / of:.1f}%"></i>'
                    f'<i class="fg" style="left:{100 * st / of:.1f}%;width:{100 * fg / of:.1f}%"></i></span>'
                    f'<span class="c"><b>{st + fg}</b> of {of}</span>'
                    f'<a href="#" onclick="{_pycmd(f"insstudy:{did}:{i}")}">Study {st + fg}</a></div>')
        out += "</div>"
    out += _ins_map(did, v.get("map") or [], v.get("map_by"), v.get("map_at"), v.get("map_ways"))
    if w:
        out += _ins_week(did, w, aim, today)
    f = v.get("fsrs")
    if f:
        out += (f'<div class="iline" title="Reviews of cards 1&ndash;3 days since their last review, 4 weeks: '
                f'{int(f["right"])}% right of {int(f["n"]):,}">Newest cards {int(f["right"])}% right, '
                f'Anki aims for {int(f["target"])}% &middot; '
                f'<a href="#" onclick="{_pycmd(f"insfsrs:{did}")}">Optimize FSRS</a> '
                f'<a class="q" href="#" onclick="{_pycmd(f"insfsrsno:{did}")}">Not now</a></div>')
    h = v.get("hard")
    two = v.get("two")
    if two == "tried":
        # 3.9.1: just turned on from here: said, with its way back
        out += (f'<div class="iline">Two buttons are on: Again and Good. 2, 3 and 4 count as Good. '
                f'<a class="q" href="#" onclick="{_pycmd(f"instwono:{did}")}">Undo</a></div>')
    elif h and two != "on":
        # 3.8.0: the Hard habit, said once a month at most; 3.9.1: with two buttons on there's no Hard to press
        out += (f'<div class="iline" title="{int(h["n"]):,} reviews in 4 weeks">You press Hard on {int(h["pct"])}% of reviews. '
                f'Anki counts Hard as remembered. '
                f'<a href="#" onclick="{_pycmd(f"instwo:{did}")}">Try two buttons</a> '
                f'<a class="q" href="#" onclick="{_pycmd(f"inshardno:{did}")}">Not now</a></div>')
    lee = int(v.get("leeches") or 0)
    if lee:
        # 3.8.0: from the plan card; a leech is the deck's
        out += (f'<div class="iline">{lee:,} suspended leech{"es" if lee != 1 else ""} &middot; '
                f'<a href="#" onclick="{_pycmd(f"insleeches:{did}")}">See them</a></div>')
    if not out:
        return '<div class="tq0">Insights fill in after a week of reviews.</div>'
    return f'<div class="dc-ins">{out}</div>'


def _ins_map(did, tiles, by, at=(), ways=()):
    """3.8.0, the topic map: each subject a tile, sized by its cards in play,
    shaded by how much I know now of the ones I've started (a bar along its
    foot: how many I've started; none yet, "new"). A tile that splits again
    opens into its smaller ones (at: the keys opened), the trail above them
    goes back, and Browse all opens the open one's cards; a tile that
    doesn't, its cards. ways: how else it can split (Systems, a resource,
    Subdecks), a pick in its heading ("by Systems ▾"). Mine alone, from my
    own Anki. Two tiles at least, or it says nothing."""
    if len(tiles) < 2:
        return ""
    e = _html.escape
    from .team import map_level, map_shade
    trail, cur = map_level(tiles, at)
    big = max(int(t["n"]) for t in cur) or 1
    how = "you’d remember now (FSRS)" if by == "fsrs" else "right on their last review"  # escaped with the tip
    out, fresh = "", False
    for i, t in enumerate(cur):
        n, k, st = int(t["n"]), t.get("know"), int(t.get("started") or 0)
        fresh = fresh or k is None
        said = (f"{n:,} cards, none started yet" if k is None
                else f"{n:,} cards, {st:,} started, {int(k)}% {how}")
        tip = f'{t["name"]}: {said}. ' + ("Open it." if t.get("kids") else "Browse them.")
        more = '<i aria-hidden="true">&rsaquo;</i>' if t.get("kids") else ""
        bar = (f'<i class="tmb" style="width:{100 * st / n:.0f}%"></i>' if k is not None and 0 < st < n else "")
        out += (f'<a class="tm {"sn" if k is None else f"s{map_shade(int(k))}"}" href="#" '
                f'style="flex:{n} 1 {70 + int(150 * n / big)}px" title="{e(tip)}" '
                f'onclick="{_pycmd(f"insmap:{did}:{i}")}"><span>{e(str(t["name"]))}{more}</span>'
                f'<b>{"new" if k is None else f"{int(k)}%"}</b>{bar}</a>')
    path = ""
    if trail:
        steps = [f'<a href="#" onclick="{_pycmd(f"insmapup:{did}:0")}">All</a>']
        steps += [f'<a href="#" onclick="{_pycmd(f"insmapup:{did}:{j}")}">{e(str(t["name"]))}</a>'
                  for j, t in enumerate(trail[:-1], 1)]
        last = trail[-1]
        steps.append(f'<b>{e(str(last["name"]))}</b>')
        lk = last.get("know")
        path = (f'<div class="tmt">{" &rsaquo; ".join(steps)} &middot; {int(last["n"]):,} cards'
                f'{"" if lk is None else f", {int(lk)}%"} '
                f'&middot; <a href="#" onclick="{_pycmd(f"insmapall:{did}")}">Browse all</a></div>')
    key = '<i class="sw s0"></i>under 70% <i class="sw s3"></i>90%+' + (' <i class="sw sn"></i>new' if fresh else "")
    ways = [w for w in ways or () if isinstance(w, dict)]
    if len(ways) > 1:  # 3.8.0: another way to split it, this deck's, on this computer
        opts = "".join(f'<option value="{i}"{" selected" if w.get("on") else ""}>{e(str(w.get("name") or "?"))}</option>'
                       for i, w in enumerate(ways))
        sub = (f'<span>&nbsp;&middot; by <select class="tmby" aria-label="Split by" '
               f'onchange="pycmd(\'duecrew:insmapby:{int(did)}:\'+this.value);">{opts}</select>'
               f'<i class="tmbv" aria-hidden="true">&#9662;</i></span>')
    else:
        sub = "<span>&nbsp;&middot; by topic, now</span>"
    share = f' <a class="tmsh" href="#" title="A picture of it, or text" onclick="{_pycmd(f"insmapshare:{did}")}">Share &rsaquo;</a>'
    # 3.8.1: by a plan's own tags, the ones no card in this deck carries (a gap in the plan's coverage)
    none = next((w.get("none") or [] for w in ways if w.get("on")), [])
    gap = ""
    if none and not trail:
        names = ", ".join(e(str(x)) for x in none[:6]) + (f" and {len(none) - 6} more" if len(none) > 6 else "")
        gap = f'<div class="tmt">No card in this deck carries {names}.</div>'
    return (f'<div class="isec"><div class="ik">What you know{sub}'
            f'<span class="ikey">{key}{share}</span></div>'
            f'{path}<div class="tmap">{out}</div>{gap}</div>')


def _week_html(card, pid):
    """This week (or the one ‹ › moved to), in the site calendar's look; a
    day's cell opens its details under the week."""
    e = _html.escape
    week = card.get("week") or []
    if not week:
        return ""
    off = int(card.get("week_offset") or 0)
    first = week[0]
    title = "This week" if off == 0 else f'Week of {int(first["num"])} {_mon(first["day"])}'
    # 3.6.5: Today sits between the arrows, always; greyed on this week
    nav = (f'<span class="nav"><a href="#" title="Last week" onclick="{_pycmd(f"planweek:{pid}:prev")}">&lsaquo;</a>'
           f'<a href="#" class="tb{"" if off else " here"}" onclick="{_pycmd(f"planweek:{pid}:0")}">Today</a>'
           f'<a href="#" title="Next week" onclick="{_pycmd(f"planweek:{pid}:next")}">&rsaquo;</a></span>')
    out = (f'<div class="pwh"><b>{title}</b>{nav}'
           f'<a class="site" href="#" title="The month on duecrew.com, in your browser" '
           f'onclick="{_pycmd("plansite:" + pid)}">Month &#8599;</a></div>')
    cells, details = "", ""
    # 3.8.0: a day's details open on a click (today's are the box's Today), or
    # on the day Browse › Show on my plan asked for
    focus = card.get("focus")
    sel = next((i for i, d in enumerate(week) if d["day"] == focus), None) if focus else None
    has_any = [bool(d["units"] or d["events"]) for d in week]
    # 3.7.81: plan load: a day's bar is its size (to the week's biggest) filled with what it asks
    loaded = any(d.get("size") is not None for d in week)
    of = max([int(d.get("size") or 0) for d in week] + [1])
    for i, d in enumerate(week):
        did = f"dc-pd-{_re.sub(r'[^A-Za-z0-9]', '', pid)}-{i}"
        new, seen = int(d.get("new") or 0), int(d.get("seen") or 0)
        size, ask = (int(d["size"]), int(d.get("ask") or 0)) if d.get("size") is not None else (None, 0)
        uids = "-".join(str(u["uid"]) for u in d["units"] if u["state"] != "skip")
        if size is not None:
            mark = (("&#10003;" if not ask else f'<span class="late">{_left_a(pid, uids, f"{ask:,} behind")}</span>') if d["past"] and size
                    else ("&#10003;" if not ask else _left_a(pid, uids, f"{ask:,} to go")) if d["today"] and size
                    else (f"{ask:,} new" if ask else "nothing new") if size else "")
        elif d["past"] or d["today"]:
            mark = ("&#10003;" if new and seen >= new else _left_a(pid, uids, f"{new - seen:,} left") if new and d["past"] else
                    f"{new:,}" if new else "")
        else:
            mark = f"{new:,}" if new else ""
        cls = ("pc" + (" now" if d["today"] else " past" if d["past"] else "") + (" off" if d["rest"] else "")
               + (" sel" if i == sel else ""))
        chips = "".join(f'<span class="chip{" done" if u["state"] == "done" else " skip" if u["state"] == "skip" else " mv" if u.get("moved") else ""}">'
                        f'{e(u["name"])}</span>' for u in d["units"])
        chips += "".join(f'<span class="chip ev">{e(n)}</span>' for n in d["events"])
        tag = "rest" if d["rest"] else "prep" if d["prep"] else ""
        bar = ("" if size is not None else _wbar(min(seen, new), new) if new and (d["past"] or d["today"]) else "")
        top = _abar(size, ask, of, d["past"], f'{d["dow"]} {int(d["num"])}') if size else ""
        has = has_any[i]
        # a click moves the box here and shows the day's details; again closes both
        click = (f' onclick="var w=this.parentNode,o=this.classList.contains(\'sel\'),x=document.getElementById(\'{did}\');'
                 f'w.querySelectorAll(\'.pc\').forEach(function(c){{c.classList.remove(\'sel\');}});'
                 f'w.parentNode.querySelectorAll(\'.pday\').forEach(function(y){{y.hidden=true;}});'
                 f'if(!o){{this.classList.add(\'sel\');if(x)x.hidden=false;}}return false;"')
        num = (f'<b class="td"><span class="dow">{e(d["dow"])} </span>{int(d["num"])}</b>' if d["today"]
               else f'<b><span class="dow">{e(d["dow"])} </span>{int(d["num"])}</b>')
        # 3.7.81: with the load, the day's number gets its own line, then its bar
        head = (f'<span class="d">{num}<span></span></span><span class="lm">{mark}</span>' if size is not None
                else f'<span class="d">{num}<span>{mark}</span></span>')
        cells += (f'<div class="{cls}"{click}>{head}{top}{chips}'
                  + (f'<span class="tag">{tag}</span>' if tag else "") + bar + '</div>')
        if has:
            rows = ""
            for u in d["units"]:
                uid = str(u["uid"])
                # 3.7.6: from today on, a date not done moves later on my copy; a moved one goes back
                move = (f'<a href="#" onclick="{_pycmd(f"planmove:{pid}:{uid}")}">Move&hellip;</a>'
                        if not d["past"] and u["state"] in ("later", "open") else "")
                back_ = (f'<a href="#" onclick="{_pycmd(f"planmoveback:{pid}:{uid}")}">Put it back</a>'
                         if u.get("moved") else "")
                if u["state"] == "later":
                    acts = (f'<a href="#" onclick="{_pycmd(f"plannow:{pid}:{uid}")}">Open now</a>{move}'
                            f'<a href="#" onclick="{_pycmd(f"planskip:{pid}:{uid}")}">Skip it</a>{back_}')
                    num = f'{int(u["total"]):,} new' if int(u["total"]) else ""
                elif u["state"] == "skip":
                    acts = f'<a href="#" onclick="{_pycmd(f"planunskip:{pid}:{uid}")}">Undo skip</a>'
                    num = "skipped"
                else:
                    # 3.8.1: a date whose cards are all shut again (Edit › Undo), or at my
                    # own pace not opened yet, opens from here as one on its day does
                    acts = (f'<a href="#" onclick="{_pycmd(f"plannow:{pid}:{uid}")}">Open now</a>' if u.get("shut") else "")
                    # 3.8.1: Study, a Due Crew deck of its open cards (a cram before a quiz)
                    acts += (f'<a href="#" title="A Due Crew deck of its open cards, new and review, in random order" '
                             f'onclick="{_pycmd(f"planstudydate:{pid}:{uid}")}">Study</a>'
                             if int(u["seen"]) or u.get("study") else "")
                    acts += move + back_
                    num = f'{int(u["seen"]):,} / {int(u["total"]):,}' if int(u["total"]) else ""
                if u.get("ld") and u["state"] != "skip":
                    num = _load_words(u["ld"], d["past"] or d["today"])
                tag = ' <span class="mv">&middot; moved</span>' if u.get("moved") else ""
                if u.get("ev"):  # 3.8.1: "for Heme quiz", or "after Heme quiz" (reinforcement)
                    tag += f' <span class="mv">&middot; {e(str(u["ev"]))}</span>'
                rows += f'<div class="r"><span class="u">{e(u["name"])}{tag}</span><span class="n">{num}</span><span class="acts">{acts}</span></div>'
                # 3.6.5, P7: what's in it, as the site's print list groups it, and Browse
                # 3.8.0: each topic opens its cards in Browse
                what = "".join(f'<span class="g">{f"<b>{e(str(g))}</b> &middot; " if g else ""}'
                               + " &middot; ".join(_topic_a(pid, uid, x, i) for x, i in xs) + '</span>'
                               + _remark_lines(xs, u.get("rm"), "rm")  # 3.8.1: the authors' notes under it
                               for g, xs in (u.get("what") or []))
                browse = (f'<a href="#" onclick="{_pycmd(f"planbrowse:{pid}:{uid}")}">Browse {int(u["total"]):,} card{"s" if int(u["total"]) != 1 else ""}</a>'
                          if int(u["total"]) and u["state"] != "skip" else "")
                if browse and u["state"] == "open" and 0 < int(u["seen"]) < int(u["total"]):
                    browse += (f'<a href="#" onclick="{_pycmd(f"planleft:{pid}:{uid}")}">'
                               f'{int(u["total"]) - int(u["seen"]):,} left</a>')  # 3.8.0
                if what or browse:
                    rows += f'<div class="wi">{what}{f"<span class=acts>{browse}</span>" if browse else ""}</div>'
                rows += _why_shut(pid, uid, u.get("why"))  # 3.8.1
            for n in d["events"]:
                rows += f'<div class="r"><span class="u"><b>{e(n)}</b></span><span class="n"></span><span></span></div>'
            later = (not d["past"] and not d["today"] and any(u["state"] == "later" for u in d["units"]))
            back = (f'<div class="acts"><a href="#" onclick="{_pycmd("planshift:" + pid)}">Push my dates back&hellip;</a></div>'
                    if later else "")
            details += (f'<div class="pday" id="{did}"{"" if i == sel else " hidden"}><b>{e(d["dow"])} {int(d["num"])} {_mon(d["day"])}'
                        + (' &middot; today' if d["today"] else "") + '</b>'
                        f'{_day_line(d)}{rows}{back}</div>')
    key = ('<div class="pkey"><span><i class="kn"></i>new to you</span><span><i class="kc"></i>seen or in your Anki by then</span>'
           '</div>') if loaded else ""
    return out + f'<div class="pwk">{cells}</div>{key}{details}'


def _why_shut(pid, uid, why):
    """3.8.1, why didn't it open: under a date in the week, a quiet line when
    it left cards shut: its leeches (Browse) and picks this copy doesn't have."""
    lee, miss = int((why or {}).get("lee") or 0), int((why or {}).get("miss") or 0)
    bits = []
    if lee:
        bits.append(f'<a class="tp" href="#" title="Browse them" onclick="{_pycmd(f"planleech:{pid}:{uid}")}">'
                    f'{lee:,} leech{"es" if lee != 1 else ""}</a> stay{"s" if lee == 1 else ""} shut')
    if miss:
        bits.append(f'{miss:,} pick{"s aren" if miss != 1 else " isn"}&rsquo;t in your copy')
    return f'<div class="pwhy">{" &middot; ".join(bits)}</div>' if bits else ""


def _day_line(d):
    """3.8.1, shared and mine: a day's details say what the plan opens that
    day apart from my own load ("opens 120 cards · you: 300 reviews due");
    today and ahead only."""
    if d.get("past"):
        return ""
    new, mine = int(d.get("new") or 0), int(d.get("mine") or 0)
    bits = ([f"opens {new:,} card{'s' if new != 1 else ''}"] if new else []) + (  # every card its dates match, not only new ones
        [f"you: {mine:,} review{'s' if mine != 1 else ''} due"] if mine else [])
    return f'<span class="pdl">{" &middot; ".join(bits)}</span>' if bits else ""


def _left_a(pid, uids, text):
    """3.8.0: a day's "16 left" in its cell, opening those cards in Browse;
    the cell's own click (its details) doesn't fire with it."""
    if not uids:
        return text
    return (f'<a class="tp" href="#" title="Browse them" onclick="event.stopPropagation();'
            f'{_pycmd(f"planleft:{pid}:{uids}")}">{text}</a>')


def _remark_lines(xs, rm, cls):
    """3.8.1: the authors' notes on a tag ([[i, text]], plans.topic_remarks)
    under the topic row that names it: xs, that row's [[name, i]]. Each note
    once; the authors' words, escaped."""
    at = {int(i) for _x, i in xs or []}
    texts = []
    for i, text in rm or []:
        if int(i) in at and str(text) not in texts:
            texts.append(str(text))
    return "".join(f'<span class="{cls}">&#9432; {_html.escape(t)}</span>' for t in texts)


def _topic_a(pid, uids, name, i):
    """3.8.0: a plan's topic as a link to its cards in Anki's browser."""
    return (f'<a class="tp" href="#" title="Browse its cards" '
            f'onclick="{_pycmd(f"plantopic:{pid}:{uids}:{int(i)}")}">{_html.escape(str(name))}</a>')


def _abar(size, ask, of, late, label):
    """3.7.81: a day's bar: its size against the week's biggest, filled
    with what it asks (behind in the warm colour)."""
    w = max(4, round(100 * int(size) / max(1, int(of))))
    f = 0 if not size else round(100 * int(ask) / int(size))
    what = "behind" if late else "to go or new"
    return (f'<span class="abar{" late" if late and ask else ""}" style="width:{w}%" '
            f'title="{_html.escape(label)} &middot; {int(size):,} cards &middot; {int(ask):,} {what}"><i style="width:{f}%"></i></span>')


def _load_words(ld, now):
    """A date in its details: today and before, seen of its cards; ahead,
    what will be new that day and what I'll have seen before it."""
    s_, o_, l_ = (int(x) for x in ld)
    tot = s_ + o_ + l_
    if now:
        return f"{s_:,} of {tot:,} seen"
    return f"{l_:,} of {tot:,} new" + (f" &middot; {s_ + o_:,} already seen or in your Anki" if s_ + o_ else "")


def _wbar(done, total):
    """The Plans tab's bars: their own class, so nothing else's .bar reaches them."""
    pct = 0 if not total else max(0, min(100, round(100 * int(done) / int(total))))
    return f'<span class="wbar" title="{int(done):,} of {int(total):,}"><i style="width:{pct}%"></i></span>'


def _mon(iso):
    try:
        return f"{_dt.date.fromisoformat(str(iso)):%b}"
    except ValueError:
        return ""


def _crew_line(card):
    """"Crew: 5 done with Chapter 1", for the latest open date anyone in my
    crew finished."""
    e = _html.escape
    for r in reversed(card.get("rows") or []):
        crew = r.get("crew") or [0, 0]
        if r.get("state") in ("open", "now") and int(crew[0] or 0):
            return f'Crew: {int(crew[0]):,} done with {e(str(r.get("name") or "?"))}'
    return ""


def _plan_notes(card, pid):
    """Everything the plan has to say beyond today and the week, most
    pressing first; the tab shows the first. Each carries its own action."""
    e = _html.escape
    s = card.get("session") or {}
    out = []
    ask = s.get("ask")
    if ask:
        days = [str(d) for d in ask.get("days") or []]
        when = " and ".join(_short(d) for d in days[-2:]) if len(days) <= 2 else f"{len(days)} study days"
        a2 = (f'<a href="#" onclick="{_pycmd("planspread:" + pid)}">Spread them (+{int(ask["spread"]):,} a day)</a>')
        if ask.get("push"):
            n = int(ask["push"])
            a2 += f'<a href="#" onclick="{_pycmd("planpush:" + pid)}">Push my dates back {n} day{"s" if n != 1 else ""}</a>'
        a2 += f'<a href="#" onclick="{_pycmd("planleave:" + pid)}">Leave them</a>'
        out.append(f'<div class="pn warn"><span>Missed <b>{e(when)}</b>: {int(ask["waiting"]):,} new waiting</span>'
                   f'<span class="acts">{a2}</span></div>')
    upd = card.get("update")
    if upd and int(upd.get("n") or 0):
        # 3.7.3: an author's update adds to today or earlier: nothing opens until I say
        n = int(upd["n"])
        names = [str(x) for x in upd.get("names") or []]
        what = " and ".join(f"<b>{e(x)}</b>" for x in names) if len(names) <= 2 else f"<b>{len(names)} dates</b>"
        who = e(str(card.get("owner_name") or "The plan"))
        lim = s.get("limit")
        over = (f' Anki shows {int(lim):,} new a day in this deck.'
                if lim is not None and int(s.get("target") or 0) + n > int(lim) else "")
        out.append(f'<div class="pn"><span>{who} added {n:,} card{"s" if n != 1 else ""} to {what}.{over}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planupdopen:" + pid)}">Open {n:,}</a>'
                   f'<a href="#" title="They open tomorrow morning" onclick="{_pycmd("planupdlater:" + pid)}">Not today</a></span></div>')
    if card.get("team_ask"):
        # 3.7.6: shared progress before the team and sharing were one choice: asked once
        out.append('<div class="pn"><span>Join this plan&rsquo;s squad? The others in it see your name and the days you '
                   'show up, and your progress counts for its authors.</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planteamjoin:" + pid)}">Join</a>'
                   f'<a href="#" onclick="{_pycmd("planteamno:" + pid)}">No thanks</a></span></div>')
    for post in (card.get("posts") or [])[:1]:
        # 3.7.3: the authors' words to followers, the newest unread
        out.append(f'<div class="pn post"><span><b>{e(str(post.get("name") or "?"))}</b>: {e(str(post.get("text") or ""))}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planpostok:" + pid)}">OK</a></span></div>')
    if card.get("change"):
        out.append(f'<div class="pn"><span>{_segs(card["change"])}</span>'
                   f'<a href="#" onclick="{_pycmd("planok:" + pid)}">OK</a></div>')
    tn = card.get("tag_news")
    if tn and tn.get("names"):
        # 3.8.0: the plan's own tags, on my notes since today
        more = int(tn.get("more") or 0)
        miss = int(tn.get("missing") or 0)
        names = ", ".join(e(str(x)) for x in tn["names"])
        out.append(f'<div class="pn"><span>New tags: <b>{names}</b>{f" and {more} more" if more else ""}.'
                   f'{f" {miss:,} of their notes aren&rsquo;t in your deck." if miss else ""}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plantags:" + pid)}">Browse them</a>'
                   f'<a href="#" onclick="{_pycmd("plantagsok:" + pid)}">OK</a></span></div>')
    lim, want = s.get("limit"), int(s.get("target") or 0)
    if lim is not None and want > int(lim) and s.get("kind") == "study":
        out.append(f'<div class="pn warn"><span>Anki shows {int(lim):,} new a day in this deck; today has {want:,}.</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planlimit:" + pid)}">Raise to {want:,}</a></span></div>')
    fb = int(s.get("fell_back") or 0)
    if fb and not card.get("fallback_ok"):
        out.append(f'<div class="pn"><span>{fb} date{"s use tags" if fb != 1 else " uses a tag"} your deck names differently, '
                   f'matched by their cards.</span><span class="acts"><a href="#" onclick="{_pycmd("planidsok:" + pid)}">OK</a></span></div>')
    # 3.6.5: what the plan left shut here, said once (OK until it grows).
    # 3.8.0: the leeches are the deck's, so they're on Insights
    _lee, miss, of = (list(card.get("aside") or []) + [0, 0, 0])[:3]
    ok = (list(card.get("aside_ok") or []) + [0, 0])[:2]
    if miss and int(miss) > int(ok[1]):
        out.append(f'<div class="pn"><span>{int(miss):,} of {int(of):,} exact cards aren\u2019t in your deck.</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planasideok:" + pid)}">OK</a></span></div>')
    if card.get("catch"):
        c = card["catch"]
        out.append(f'<div class="pn"><span>Catching up: +{int(c.get("extra") or 0):,} new a day to {e(str(c.get("until") or ""))}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plancatchstop:" + pid)}">Stop</a></span></div>')
    for kind, segments in card.get("lines") or []:
        if kind == "behind" and not card.get("catch"):
            # 3.8.0: Catch up (and Push my dates back, in its menu), from the old Today box
            out.append(f'<div class="pn warn"><span>{_segs(segments)}</span>'
                       f'<span class="acts"><a href="#" onclick="{_pycmd("plancatch:" + pid)}">Catch up&hellip;</a></span></div>')
    if int(card.get("waiting") or 0) and not card.get("catch"):
        w = int(card["waiting"])
        out.append(f'<div class="pn"><span><b>{w:,}</b> new from earlier days waiting</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plancatch:" + pid)}">Catch up&hellip;</a></span></div>')
    if card.get("put_off"):
        names = [str(n) for n in card["put_off"]]
        what = " and ".join(f"<b>{e(n)}</b>" for n in names) if len(names) <= 2 else f"<b>{len(names)} dates</b>"
        # 3.8.1: put off by Welcome back's Not today, they wait: tomorrow morning asks again
        when = (f'wait{"s" if len(names) == 1 else ""} for tomorrow morning' if card.get("put_off_ask")
                else f'open{"s" if len(names) == 1 else ""} tomorrow morning')
        out.append(f'<div class="pn"><span>{what} {when}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planputback:" + pid)}">Open now</a></span></div>')
    pf, qz = card.get("prep"), card.get("quiz")
    # 3.8.1: Study for a quiz says this, in what the plan says about now (_plan_now)
    if pf and not (qz and qz.get("day") == pf.get("day") and qz.get("name") == pf.get("name")):
        left = int(pf.get("left") or 0)
        what = (f'<b>{e(str(pf.get("name") or "?"))}</b> is today' if pf.get("today")
                else f'For <b>{e(str(pf.get("name") or "?"))}</b> on {e(str(pf.get("when") or ""))}'
                + (f' &middot; {left} more day{"s" if left != 1 else ""} of prep' if left else ""))
        out.append(f'<div class="pn"><span>{what}</span></div>')
    for kind, segments in card.get("lines") or []:
        if kind != "behind":
            out.append(f'<div class="pn"><span>{_segs(segments)}</span></div>')
    r = s.get("recap")
    if r:
        a, b = r.get("sessions") or [0, 0]
        out.append(f'<div class="pn"><span><b>Week {int(r["n"])} done</b>: {int(a)} of {int(b)} sessions, '
                   f'{int(r.get("new") or 0):,} new cards{", on track" if r.get("on_track") else ""}.</span></div>')
    for c in s.get("checks") or []:
        n, got = int(c.get("n") or 0), int(c.get("answered") or 0)
        if got >= n and n:
            out.append(f'<div class="pn"><span>Checkpoint <b>{e(str(c.get("name") or ""))}</b> done: '
                       f'<b>{int(c.get("right") or 0):,} of {n:,}</b> right first time.</span></div>')
        elif n:
            out.append(f'<div class="pn"><span>&#10003; Built <b>Checkpoint &middot; {e(str(c.get("name") or ""))}</b>: '
                       f'{n:,} cards you&rsquo;ve missed most. {got:,} done.</span></div>')
    return out


def _short(iso):
    try:
        d = _dt.date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    return f"{d:%a}"


def notice_html(notice):
    """3.2.1: the admin's notice, one line on top of the board: the text,
    More when it has a link, and a dismiss. Escaped; the link never goes in
    the page (Python opens it)."""
    nid = int(notice.get("id") or 0)
    more = (f'<a class="wc" href="#" title="Opens in your browser" onclick="{_pycmd("noticeopen")}">More</a>'
            if notice.get("link") else "")
    return (f'<div class="dc-wrap notice"><span>&#128227;</span>'
            f'<span>{_html.escape(str(notice.get("text") or ""))}</span>{more}'
            f'<a class="wx" href="#" title="Dismiss" onclick="{_pycmd(f"noticex:{nid}")}">&times;</a></div>')


def _offer_banners(offers):
    """3.1: a plan offered to one of my squads. Names escaped."""
    e = _html.escape
    out = ""
    for o in offers or []:
        oid = str(o.get("id", ""))
        out += (f'<div class="dc-wrap"><span>&#128197;</span>'
                f'<span><b>{e(str(o.get("owner") or "?"))}</b> offered {e(str(o.get("squad") or ""))} '
                f'a plan: {e(str(o.get("name") or ""))}</span>'
                f'<a class="wc" href="#" onclick="{_pycmd("planlook:" + oid)}">Look</a>'
                f'<a class="wx" href="#" title="Not now" onclick="{_pycmd("planofferx:" + oid)}">&times;</a></div>')
    return out


# 3.7.1, I6: a key drawn like the bars, no words about hovering
_DKEY = '<span class="dkey"><i class="fm"></i>mature<i class="fs"></i>seen<i class="fo"></i>unlocked</span>'


def _decks_body(data, deltas=None, sticking=None, pick="", asks=""):
    """Crew › Decks: pick (Crew's views) on a line of its own, the key at its
    right when the bars come next (3.8.0, head row B); asks, the cards asked
    about, between them and the bars, with the key under the bars."""
    deltas = deltas or {}
    labels = data.get("labels") or []
    # a friend ahead of my timezone writes my "tomorrow" as their today
    today_labels = tuple(lb for lb in (labels[0] if labels else "", data.get("tomorrow")) if lb)
    groups, extras = build_deck_groups(data["entries"])
    up = bool(pick) and not asks and bool(groups)
    top = f'<div class="dc-pline">{pick}{_DKEY if up else ""}</div>' if pick else ""
    if not groups:  # a friend's alone isn't drawn (extras, since 2.7): the way in
        return (top + asks + '<div class="dc-line">No shared decks yet. '
                f'<a href="#" onclick="{_pycmd("decks")}">Pick decks to share</a></div>')
    html = ""
    for g in groups:
        label = _html.escape(str(g["label"]))
        did = (sticking or {}).get(str(g["label"]))
        if did:
            # 3.8.0: my own deck, to how it's sticking (You › Insights)
            label += (f'<a class="dsk" href="#" title="How it&rsquo;s sticking, in Insights" '
                      f'onclick="{_pycmd("youins:" + str(int(did)))}">How it&rsquo;s sticking &rsaquo;</a>')
        rows = "".join(
            _bar(n, me, d, deltas.get((uid, d.get("name", ""))), today_labels)
            for n, me, d, uid in g["rows"])
        html += f'<div class="dg"><div class="dgh">{label}</div>{rows}</div>'
    html = _scroll(_even_bars(html), sum(len(g["rows"]) for g in groups))
    if groups and not up:
        html += f'<div class="dc-line" style="padding-top: 2px;">{_DKEY}</div>'
    return top + asks + html


SQUAD_FIELDS = {"reviews": "reviews", "time": "time_ms",
                "retention": "retention", "streak": "streak", "week": "week"}
# squads stay Today-only, so this column is a rolling count ("studied 5 of
# the last 7 days"), one int per member. Labelled for what it is: the crew's
# Week view is the calendar week, and the two must not share a word.
SQUAD_HEADERS = HEADERS + (("week", _head_label("&#128197;", "7 days")),)


def _switcher(view):
    parts = []
    for sq in view.get("squads") or []:
        on = ' class="on"' if sq["id"] == view.get("current") else ""
        nm = _html.escape(str(sq["name"]))
        parts.append(f'<a{on} href="#" title="{nm}" onclick="{_pycmd("squad:" + str(sq["id"]))}">{nm}</a>')
    for sq in view.get("plan_squads") or []:
        # 3.8.0: a plan's squad, named for the plan; the badge is its threads that moved
        on = sq["id"] == view.get("current")
        n = int(sq.get("unread") or 0)
        cls = ' class="on"' if on else ""
        badge = f"<i>{n}</i>" if n and not on else ""
        nm = _html.escape(str(sq["name"]))
        parts.append(f'<a{cls} href="#" title="{nm}" onclick="{_pycmd("squadplan:" + str(sq["pid"]))}">{nm}{badge}</a>')
    parts.append(f'<a class="add" href="#" onclick="{_pycmd("squadadd")}">'
                 f'+ join or create</a>')
    return '<div class="dc-sw">' + "".join(parts) + "</div>"


def squad_week(rows, day):
    """3.8.0: a squad's last 7 days together, totals only (nobody ahead of
    anybody): (study days between us, how many of us studied). A row's week
    is its 7 days to its own last sync, so a sync `age` days ago counts at
    most 7 - age of them, and one a week old or more none (a day ahead is
    today, a timezone ahead). Its twin is squadWeek in app.js."""
    try:
        today = datetime.fromisoformat(str(day)).date()
    except ValueError:
        return 0, 0
    days = []
    for r in rows or []:
        w = r.get("week")
        if not isinstance(w, (int, float)) or isinstance(w, bool) or w != w or abs(w) == float("inf"):
            continue
        try:
            age = (today - datetime.fromisoformat(str(r.get("day"))).date()).days
        except ValueError:
            continue
        if -1 <= age < 7:  # a day ahead: a friend ahead of my timezone, synced on their today
            days.append(min(7 - max(age, 0), max(0, int(w))))
    return sum(days), sum(1 for d in days if d)


def _squad_week_line(rows, day):
    days, people = squad_week(rows, day)
    if people < 2:
        return ""
    return f'<div class="dc-line dc-sum sqwk">Last 7 days: <b>{days:,}</b> study days between {people:,} of you</div>'


def _squads_html(view, cfg, crew_by=None):
    """A squad board: everyone here holds the same invite. Plain ranks — no
    medals, no cheers; these aren't necessarily people you know. Add lives
    on the person's card (click a name), not on the row. crew_by (3.8.21): my
    crew by uid, so a crewmate's Pip wears their colour and look."""
    state = view.get("state")
    sw = _switcher(view)
    if view.get("kind") == "plan":
        return sw + _plan_squad_html(str(view.get("pid") or ""), view, crew_by, cfg)
    name = _html.escape(str(view.get("name") or "?"))
    if state == "none":
        return sw + '<div class="dc-line">No squads yet.</div>'  # the way in is right above it
    if state == "loading":
        return sw + '<div class="dc-line dc-wait">Fetching&hellip;</div>'
    if state == "error":
        return (sw + '<div class="dc-line">Couldn&rsquo;t '
                'load. Check your connection and Refresh.</div>')
    if state == "gone":
        return (sw + f'<div class="dc-line">You&rsquo;re no '
                f'longer in {name}. <a href="#" '
                f'onclick="{_pycmd("squaddrop:" + str(view.get("current", "")))}">Remove</a></div>')
    rows = view.get("rows") or []
    day, yesterday = view.get("day", ""), view.get("yesterday", "")
    sort = sort_key(cfg)  # the crew table's sort, same headers, same links
    field = SQUAD_FIELDS[sort]
    # synced today with nothing studied yet: no numbers to rank, so these
    # sit under the ranked rows with dashes (as on Today)
    zero = lambda r: r.get("reviews") == 0 and not r.get("time_ms")
    live = sorted([r for r in rows if r.get("day") == day and not zero(r)],
                  key=lambda r: r.get(field) if r.get(field) is not None else -1,
                  reverse=True)
    waiting_today = [r for r in rows if r.get("day") == day and zero(r)]
    rest = sorted([r for r in rows if r.get("day") != day],
                  key=lambda r: r.get("day") or "", reverse=True)
    # Q3: members with no sync in 90+ days fold into one line, as on Today
    try:
        cut = (datetime.fromisoformat(day) - _dt.timedelta(days=QUIET_FOLD_DAYS)).date().isoformat()
    except Exception:
        cut = ""
    long_q = [r for r in rest if cut and not r.get("you") and str(r.get("day") or "") < cut]
    rest = [r for r in rest if r not in long_q] + long_q
    long_ids = {id(r) for r in long_q}
    people = int(view.get("people") or len(rows))
    headline = f'{people:,} in {name}'
    if view.get("open") is False:
        headline += " &middot; locked"
    if live:
        headline += (f' &middot; {len(live):,} studying today &middot; '
                     f'{int(view.get("reviews") or 0):,} reviews together')
    # 3.8.0, head row B: the squads' names in the table's corner, the
    # headline under it (rebuilt below when show-up mode is on)
    heads = _corner(sw)
    for key, label in SQUAD_HEADERS:
        on = "on" if key == sort else ""
        arrow = " &#9662;" if key == sort else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{label}{arrow}</a></th>')
    show_up = bool(cfg.get("show_up"))
    numberless = lambda r: all(r.get(k) is None for k in ("reviews", "time_ms", "retention", "streak"))
    if show_up:
        live.sort(key=lambda r: (-(r.get("week") or 0), r["name"].lower()))
        headline = (f'{people:,} in {name}' + (" &middot; locked" if view.get("open") is False else "")
                    + (f" &middot; {len(live):,} showed up today" if live else ""))
        heads = (_corner(sw) + '<th><span style="color: var(--dc-muted); font-size: 11px; '
                 'font-weight: 700;">&#128197; 7 days</span></th>')
    body = ""
    n = 0
    folded = False
    for r in live + waiting_today + rest:
        uid = str(r["user_id"])
        pip = squad_pip(uid, r["name"], r.get("you"), crew_by, cfg)  # 3.8.21: Pip where the emoji was
        pname = _html.escape(str(r["name"])) if pip else _label(r["name"], r.get("emoji"))
        cls, note = "", ""
        if id(r) in long_ids:
            if not folded:
                body += _quiet_fold([{"name": x["name"], "last_updated": x.get("day")} for x in long_q]).replace(
                    f'colspan="{len(HEADERS) + 1}"', f'colspan="{2 + (1 if show_up else len(SQUAD_HEADERS))}"', 1)
                folded = True
            cls = "qh"
        if r.get("you"):
            cls = "you"
            link = (f'<a class="dc-pl" href="#" title="See what your crew sees" '
                    f'onclick="{_pycmd("profile:" + uid)}">{pname}</a>')
        else:
            if r.get("crew"):
                note = ' <span class="la faded">&middot; crew</span>'
            elif r.get("knocked_me"):
                note = ' <span class="la fresh">&middot; added you</span>'
            elif r.get("pending"):
                note = ' <span class="la faded">&middot; waiting</span>'
            link = (f'<a class="dc-pl" href="#" title="Open card" '
                    f'onclick="{_pycmd("ecard:" + uid)}">{pname}</a>')
        if pip:  # beside the name, outside its underline, as on Crew; room above for a hat (tr.sv)
            link, cls = pip + link, cls + " sv"
        if r.get("day") != day:
            cls += " dim"
            when = "yesterday" if r.get("day") == yesterday else "quiet"
            note += f' <span class="la faded">&middot; {when}</span>'
            rank = ""
        elif zero(r):
            cls += " dim"
            note += ' <span class="la faded">&middot; nothing yet today</span>'
            rank = "&mdash;"
        elif show_up or numberless(r):
            rank = "&#10003;"  # showed up: counted, not ranked
        else:
            n += 1
            rank = f"#{n}"
        if show_up:
            body += (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
                     f'<td class="nm">{link}{note}</td>'
                     f'<td class="n">{_cell(r.get("week"), lambda v: f"{v}/7")}</td></tr>')
            continue
        if r.get("day") == day and zero(r):
            body += (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
                     f'<td class="nm">{link}{note}</td>'
                     f'<td class="n">{_NW_ROOM}&mdash;{_NW_ROOM}</td>' + '<td class="n">&mdash;</td>' * 3 +
                     f'<td class="n">{_cell(r.get("week"), lambda v: f"{v}/7")}</td></tr>')
            continue
        body += (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
                 f'<td class="nm">{link}{note}</td>'
                 f'<td class="n">{_reviews_cell(r.get("reviews"), r.get("new_cards"))}</td>'
                 f'<td class="n">{_cell(r.get("time_ms"), _fmt_time)}</td>'
                 f'<td class="n">{_cell(r.get("retention"), lambda v: f"{v:.1f}%")}</td>'
                 f'<td class="n">{_cell(r.get("streak"))}</td>'
                 f'<td class="n">{_cell(r.get("week"), lambda v: f"{v}/7")}</td></tr>')
    body = _even_rows(body)
    # the squad's own line; Share today sits in the footer, as on Today
    acts = [f'<a href="#" onclick="{_pycmd("squadinvite")}">Copy invite</a>']
    if view.get("founder_me"):
        acts.append(f'<a href="#" onclick="{_pycmd("squadlock")}">'
                    f'{"Open" if view.get("open") is False else "Lock"}</a>')
    acts.append(f'<a href="#" onclick="{_pycmd("squadleave")}">Leave</a>')
    foot = ('<div class="dc-line">'
            + " &middot; ".join(acts) + "</div>")
    bingo = (f"<style>{BINGO_CSS}</style>" + bingo_card_html(view["bingo"])) if view.get("bingo") else ""  # 3.6
    if not body:
        return (sw + bingo + '<div class="dc-line">No one&rsquo;s '
                'synced yet.</div>' + foot)
    # the bingo card under the table, the names it's for being in its corner
    return (_scroll(f"<table><tr>{heads}</tr>{body}</table>", body.count('<tr class='))
            + f'<div class="dc-line dc-sum">{headline}</div>' + _squad_week_line(rows, day) + bingo + foot)


# ---- 3.6: squad bingo ----

BINGO_CSS = """
    /* the whole card's frame is #due-crew.bg-full itself: its rules say so */
    #due-crew .bg-card, #due-crew.bg-full, #due-crew .bg-row, #due-crew .bg-bar, #due-crew .bg-info { text-align: left; }
    #due-crew [hidden] { display: none !important; }
    #due-crew .bg-card { border-top: 1px solid var(--dc-line); border-bottom: 1px solid var(--dc-line); padding: 9px 0;
      margin: 2px 0 10px;  /* 3.8.0: a row between rules, no box */
      display: flex; align-items: center; gap: 12px; flex-wrap: wrap; font-size: 12px; }
    #due-crew .bg-card .bg-t { display: grid; gap: 1px; flex: 1 1 180px; min-width: 0; }
    #due-crew .bg-card .bg-t span, #due-crew .bg-q { color: var(--dc-muted); }
    #due-crew .bg-card a, #due-crew a.bg-a { color: var(--dc-accent); font-weight: 700; text-decoration: none; white-space: nowrap; }
    #due-crew .bg-mini { display: grid; grid-template-columns: repeat(3, 9px); gap: 2px; flex: none; }
    #due-crew .bg-mini i { width: 9px; height: 9px; border-radius: 2px; background: var(--dc-line); }
    #due-crew .bg-mini i.on { background: var(--dc-accent); }
    #due-crew .bg-mini i.m { background: var(--dc-hours); }
    #due-crew .bg-bar { display: flex; align-items: baseline; gap: 4px 10px; flex-wrap: wrap; margin: 2px 0 10px; }
    #due-crew .bg-bar b { font-size: 15px; }
    #due-crew .bg-bar .bg-a:last-child { margin-left: auto; }
    #due-crew .bg-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 6px; }
    #due-crew .bg-sq { position: relative; min-height: 118px; padding: 17px 5px 22px; border: 1px solid var(--dc-line) !important;
      border-radius: 9px; background: var(--dc-bg); color: var(--dc-ink); font: inherit; cursor: pointer;
      display: grid; align-content: start; justify-items: center; gap: 2px; text-align: center; }
    #due-crew .bg-sq .ic { font-size: 22px; line-height: 1.1; }
    #due-crew .bg-sq .tt { font-size: 12px; font-weight: 700; line-height: 1.2; }
    #due-crew .bg-sq .rl { font-size: 10.5px; line-height: 1.25; color: var(--dc-muted); }
    #due-crew .bg-sq .fm { position: absolute; top: 4px; left: 6px; font-size: 8px; font-weight: 700; letter-spacing: .05em;
      text-transform: uppercase; color: var(--dc-muted); }
    #due-crew .bg-sq .df { position: absolute; top: 4px; right: 6px; font-size: 7px; letter-spacing: 1px; color: var(--dc-muted); }
    #due-crew .bg-sq .tm { font-size: 9.5px; font-weight: 700; color: var(--dc-hours); background: var(--dc-amber-bg, rgba(178,106,0,.1));
      border-radius: 99px; padding: 0 6px; }
    #due-crew .bg-sq .tm.ok { color: var(--dc-accent); background: var(--dc-you-bg); }
    #due-crew .bg-sq .st { position: absolute; bottom: 3px; width: 22px; height: 22px; border-radius: 50%; display: grid;
      place-items: center; font-size: 13px; background: var(--dc-you-bg); box-shadow: inset 0 0 0 1.5px var(--dc-accent); }
    #due-crew .bg-sq.done { background: var(--dc-you-bg); }
    #due-crew .bg-sq.line { border-color: var(--dc-accent) !important; box-shadow: inset 0 0 0 1px var(--dc-accent) !important; }
    #due-crew .bg-sq.mid { border-color: var(--dc-hours) !important; }
    #due-crew .bg-sq.mid.done { border-color: var(--dc-accent) !important; }
    #due-crew .bg-sq.sel { outline: 2px solid var(--dc-ink) !important; outline-offset: -2px; }
    #due-crew .bg-sq .pb { width: 80%; height: 4px; border-radius: 2px; background: var(--dc-line); overflow: hidden; }
    #due-crew .bg-sq .pb i { display: block; height: 100%; background: var(--dc-hours); }
    #due-crew .bg-sq.done .pb i { background: var(--dc-accent); }
    #due-crew .bg-sq .pp { font-size: 9.5px; font-weight: 700; color: var(--dc-hours); }
    #due-crew .bg-row { display: flex; gap: 6px 10px; align-items: center; flex-wrap: wrap; margin-top: 10px; font-size: 12px; }
    #due-crew .bg-shout { font-weight: 800; font-size: 15px; color: var(--dc-accent); letter-spacing: .03em; }
    #due-crew .bg-info { border-top: 1px solid var(--dc-line); margin-top: 10px; padding-top: 8px; font-size: 12px; }
    #due-crew .bg-info > div { display: grid; gap: 3px; }
    #due-crew .bg-info .k { color: var(--dc-muted); font-size: 11px; }
    #due-crew .bg-info .me { font-weight: 700; }
    @media (max-width: 460px) {
      #due-crew .bg-sq { min-height: 126px; padding: 15px 2px 20px; }
      #due-crew .bg-sq .tt { font-size: 11px; }
      #due-crew .bg-sq .rl { font-size: 9.5px; }
      #due-crew .bg-sq .fm { font-size: 7px; left: 4px; }
      #due-crew .bg-sq .st { width: 18px; height: 18px; font-size: 10px; }
    }
"""


def _bg_need(sq, need):
    # the number, never the share: "a third of you" said nothing in a small squad
    return f"{need} of you"


def bingo_card_html(bv):
    """The Squads tab's card, above the squad's table: the grid small, the
    middle's progress, what's closest to a line. Never who's ahead."""
    if not bv:
        return ""
    e = _html.escape
    card, ev = bv["card"], bv["ev"]
    cells = ""
    for c in range(9):
        if c == 4:
            cells += f'<i class="{"on" if ev["middle"]["done"] else "m"}"></i>'
        else:
            cells += f'<i class="{"on" if ev["squares"][CELLS_BINGO.index(c)]["done"] else ""}"></i>'
    m, mid = card["middle"], ev["middle"]
    if bv.get("new"):
        line = (f'&#129376; A new card. This week&rsquo;s middle: {e(m["icon"])} '
                f'<b>{e(m["name"])}</b>, {e(m["rule"][:1].lower() + m["rule"][1:])}.')
    else:
        stamps = sum(1 for q in ev["squares"] if q["done"]) + (1 if mid["done"] else 0)
        if ev["lines"] >= 8:
            state = "the whole card"
        elif ev["lines"]:
            state = "BINGO" if ev["lines"] == 1 else f'{ev["lines"]} lines'
        else:
            left = len(bv.get("closest") or [])
            state = "one away from bingo" if left == 1 else f"{left} away from bingo"
        line = f"{stamps} of 9 &middot; {state}"
    return (f'<div class="bg-card"><span class="bg-mini">{cells}</span>'
            f'<span class="bg-t"><b>Squad bingo</b><span>{line}</span></span>'
            f'<a href="#" onclick="{_pycmd("bingo")}">Open the card</a></div>')


CELLS_BINGO = (0, 1, 2, 3, 5, 6, 7, 8)


def bingo_html(bv, cfg, loading=False, team=False, people=None):
    """The whole card, in the board's place (like Settings). Every string
    from the server is escaped here. A square's details show in the page
    when it's clicked: no request. people (3.8.22): {uid: crew entry}, mine
    too, so who stamped a square shows as their Pip (stamp_pip)."""
    e = _html.escape
    pips = cfg.get("sev", True)
    sheet = (f'<style>{_sev.CSS}{BINGO_PIP_CSS}{_by_theme(cfg, "#due-crew .dc-rsev", "--sv-a: var(--rs-l);", "--sv-a: var(--rs-d);")}</style>'
             if pips else "")
    head = (f'<div id="due-crew" class="dc-frame bg-full">{_css(cfg)}<style>{BINGO_CSS}</style>{sheet}'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span></div>')
    team_card = bool(bv and bv.get("team")) or team  # 3.7.3: a plan team's card: counts, never who
    back = (f'<a class="bg-a" href="#" onclick="{_pycmd("planteambingoback")}">&lsaquo; Squads</a>' if team_card
            else f'<a class="bg-a" href="#" onclick="{_pycmd("bingoback")}">&lsaquo; Squads</a>')
    if not bv:
        said = "Fetching&hellip;" if loading else "No card this week yet. Refresh brings it."
        return head + (f'<div class="bg-bar">{back}<b>Squad bingo</b></div>'
                       f'<div class="bg-q{" dc-wait" if loading else ""}">{said}</div></div>')
    card, ev = bv["card"], bv["ev"]
    names, me = bv.get("names") or {}, bv.get("me")
    progress = bv.get("progress") or []
    lined = set(ev.get("cells") or [])
    squares, infos = "", ""
    fams = {"early": "Early", "spread": "Spread out", "focus": "Focus", "volume": "Bigger day", "fresh": "New cards",
            "often": "Showing up", "clean": "Keeping up", "wild": "Wildcard"}
    diffs = {"e": ("&#9679;", "easy"), "m": ("&#9679;&#9679;", "medium"), "h": ("&#9679;&#9679;&#9679;", "hard")}
    show = "var i=this.dataset.i;document.querySelectorAll('#due-crew .bg-info>div').forEach(function(x){x.hidden=x.dataset.i!==i});" \
           "document.querySelectorAll('#due-crew .bg-sq').forEach(function(x){x.classList.toggle('sel',x.dataset.i===i)});return false;"
    for c in range(9):
        cls = "line" if c in lined else ""
        if c == 4:
            m, mid = card["middle"], ev["middle"]
            pct = 100 if mid["done"] else int(100 * mid["have"] / max(1, mid["goal"]))
            free = m.get("type") == "free"
            said = "Unlocked" if mid["done"] else f'{mid["have"]} of {mid["goal"]} {e(m.get("unit") or "")}'.strip()
            prog = "" if free else (f'<span class="pb"><i style="width:{pct}%"></i></span>'
                                    f'<span class="pp">{said}</span>')
            squares += (f'<button class="bg-sq mid {"done" if mid["done"] else ""} {cls}" data-i="m" onclick="{show}">'
                        f'<span class="ic">{e(m["icon"]) if mid["done"] else "&#128274;"}</span>'
                        f'<span class="tt">{e(m["name"])}</span><span class="rl">{e(m["rule"])}</span>{prog}</button>')
            state = ("Unlocked. It counts toward all four lines through the middle." if mid["done"]
                     else f'{mid["have"]} of {mid["goal"]} so far. The squad unlocks it together.')
            infos += (f'<div data-i="m" hidden><b>{e(m["icon"])} {e(m["name"])}: {e(m["rule"])}</b>'
                      f'<span>{e(m["detail"])}</span><span class="k">{"This week the middle is free." if free else state}</span></div>')
            continue
        i = CELLS_BINGO.index(c)
        sq, st = card["squares"][i], ev["squares"][i]
        known = sq.get("type") in _BINGO_TYPES
        who = st.get("who") or []
        n_who = int(st.get("n", len(who)))
        team = ""
        if st["need"] > 1 or sq.get("need") in ("half", "third", "quarter"):
            so_far = " &#10003;" if st["done"] else f' &middot; {n_who}/{st["need"]}'
            team = (f'<span class="tm{" ok" if st["done"] else ""}">&#128101; {_bg_need(sq, st["need"])}'
                    f'{so_far}</span>')
        marks = "".join(
            f'<span class="st sp" style="right:{8 + k * 27}px;{"" if st["done"] else "opacity:.55"}" title="{e(names.get(u, ("?", ""))[0])}">'
            f'{stamp_pip(u, names.get(u, ("?", ""))[0], people, cfg, k)}</span>' if pips else
            f'<span class="st" style="right:{3 + k * 15}px;{"" if st["done"] else "opacity:.55"}" title="{e(names.get(u, ("?", ""))[0])}">'
            f'{e(names.get(u, ("?", ""))[1]) or "&#10003;"}</span>' for k, u in enumerate(who[:3]))
        dots, dname = diffs.get(sq.get("diff"), diffs["m"])
        rule = f'<span class="rl">{e(sq["rule"])}</span>' if known else ""
        squares += (f'<button class="bg-sq {"done" if st["done"] else ""} {cls}{" stamped" if pips and who else ""}" data-i="{i}" onclick="{show}">'
                    f'<span class="fm">{fams.get(sq.get("fam"), "")}</span><span class="df" title="{dname}">{dots}</span>'
                    f'<span class="ic">{e(sq["icon"])}</span><span class="tt">{e(sq["title"]) if known else "Update to play"}</span>'
                    f'{rule}{team}{marks}</button>')
        whose = ", ".join(e(names.get(u, ("?", ""))[0]) for u in who) if who else (f"{n_who} of you" if n_who else "")
        if st["need"] > 1 or sq.get("need") in ("half", "third", "quarter"):
            state = (f'A team square: {_bg_need(sq, st["need"])} have to pass the mark this week. '
                     + (f"Done by {whose}." if st["done"] else f"So far: {whose}." if whose else "Nobody yet."))
        else:
            state = f"Stamped by {whose}." if whose else "Not yet. Any one of you can stamp it."
        mine = ""
        if known and i < len(progress) and progress[i]:
            done, words = progress[i]
            if me in who or done:  # a team card has no who: my own progress says
                mine = '<span class="me">You: done.</span>'
            elif sq.get("type") in (bv.get("withheld") or ()):
                mine = (f'<span class="me">You: {e(words)}</span>'
                        '<span class="k">Your Privacy switches keep yours on this computer: it would say when or how much.</span>')
            else:
                mine = f'<span class="me">You: {e(words)}</span>'
        elif not known:
            mine = '<span class="k">New this week. Update Due Crew to play it; your squad can still stamp it.</span>'
        infos += (f'<div data-i="{i}" hidden><b>{e(sq["icon"])} {e(sq["title"])}</b>'
                  f'<span class="k">{fams.get(sq.get("fam"), "")} &middot; {dname}</span>'
                  f'<span>{e(sq["detail"])}</span>{mine}<span class="k">{state}</span></div>')
    stamps = sum(1 for q in ev["squares"] if q["done"]) + (1 if ev["middle"]["done"] else 0)
    if ev["lines"] >= 8:
        foot = '<span class="bg-shout">THE WHOLE CARD</span><span>All nine, together.</span>'
    elif ev["lines"]:
        foot = (f'<span class="bg-shout">BINGO!</span>'
                f'<span>{"A line" if ev["lines"] == 1 else str(ev["lines"]) + " lines"} this week.</span>')
    else:
        foot = f'<span class="bg-q">Closest: {e(", ".join(bv.get("closest") or []))}</span>'
    older = ""
    if ev.get("older"):
        n = ev["older"]
        older = f'<div class="bg-row bg-q">{n} of you need{"s" if n == 1 else ""} to update Due Crew to play.</div>'
    copy = ("" if team_card else
            f'<a class="bg-a" href="#" title="The grid in emoji, never who stamped what" onclick="{_pycmd("bingocopy")}">Copy for the group chat</a>')
    title = f'{e(bv.get("squad") or "Squad")} bingo'
    return (head
            + f'<div class="bg-bar">{back}<b>{title}</b>'
              f'<span class="bg-q">{e(_week_span(card["wk"]))} &middot; {stamps} of 9</span>{copy}</div>'
            + f'<div class="bg-grid">{squares}</div>'
            + f'<div class="bg-row">{foot}</div>' + older
            + f'<div class="bg-info"><div data-i=""></div>{infos}</div>'
            + "</div>")


_BINGO_TYPES = ("window", "minute", "sittings", "parts", "focus", "beat", "rel", "best",
                "newdays", "newdone", "days", "zero", "samehour")


def _week_span(wk):
    try:
        monday = _dt.date.fromisocalendar(int(wk[:4]), int(wk[6:]), 1)
    except ValueError:
        return ""
    return f"week of {monday.day} {monday:%b}"


def _review_banner(kind, info):
    """Personal month or year review, above the board. Local numbers only."""
    r = info["review"]
    if kind == "month":
        icon, title = "&#128197;", f'Your {_html.escape(str(info["name"]))}:'
        cmd_copy, cmd_x = "monthcopy", "monthdismiss"
    else:
        icon, title = "&#127881;", f'Your {_html.escape(str(info["key"]))}:'
        cmd_copy, cmd_x = "yearcopy", "yeardismiss"
    bits = [f'{int(r["reviews"]):,} reviews', _fmt_time(int(r["time_ms"] or 0)),
            f'{int(r["days"])} of {int(r["span"])} days']
    if kind == "month" and r.get("best_day"):
        bits.append(f'best day {int(r["best_day"][1]):,}')
    if kind == "year" and int(r.get("longest_run") or 0) > 1:
        bits.append(f'&#128293; {int(r["longest_run"])}-day run')
    return (f'<div class="dc-wrap"><span>{icon}</span>'
            f'<span><b>{title}</b> {" &middot; ".join(bits)}</span>'
            f'<a class="wc" href="#" title="Copy for the chat" '
            f'onclick="{_pycmd(cmd_copy)}">Copy</a>'
            f'<a class="wx" href="#" title="Dismiss" '
            f'onclick="{_pycmd(cmd_x)}">&times;</a></div>')


def crew_menu_items():
    """The footer's Crew menu (3.4 review, H5; 3.7.1, H3): people only, the
    same on every tab. What you post went to Share."""
    return [("Friends…", "friends"), ("Copy invite", "copyinvite"),
            ("Shared decks…", "decks")]


def share_menu_items(show_up, squad_ok=False):
    """The footer's Share menu (3.7.1, H3), as [(label, command)], a label of
    None being a heading: as text first, then as a picture, the same on
    every tab. Today's numbers aren't offered in just-show-up mode."""
    items = [(None, "As text")]
    if not show_up:
        items.append(("My day", "sharetoday"))
    items.append(("Our week", "sharecrewweek"))
    if squad_ok and not show_up:
        items.append(("The squad's day", "squadshare"))
    items.append((None, "As a picture"))
    if not show_up:
        items.append(("My day…", "picturetoday"))
    items += [("My week…", "pictureweek"), ("My year…", "pictureyear"),
              ("All time…", "picturealltime")]
    return items


def _split_wraps(html):
    """The banners in a run of them, one string each."""
    out, i = [], 0
    while True:
        j = html.find('<div class="dc-wrap', i)
        if j < 0:
            return out
        k = html.find('<div class="dc-wrap', j + 1)
        out.append(html[j:k if k >= 0 else len(html)])
        if k < 0:
            return out
        i = k


def _one_at_a_time(bans):
    """3.4 review, H6: the first banner shows; "1 of N ›" steps to the next
    (in the page, no request). Dismissing one still goes through Python."""
    bans = [b for b in bans if b]
    if len(bans) < 2:
        return "".join(bans)
    out = []
    step = ("var w=this.closest('.dc-wrap'),n=w.nextElementSibling||w.parentNode.firstElementChild;"
            "w.hidden=true;n.hidden=false;return false;")
    for i, b in enumerate(bans):
        more = f'<a class="wn" href="#" title="The next one" onclick="{step}">{i + 1} of {len(bans)} &rsaquo;</a>'
        cut = b.rfind('<a class="wx"')
        if cut < 0:
            cut = b.rfind("</div>")
        b = b[:cut] + more + b[cut:]
        if i:
            b = b.replace('<div class="dc-wrap', '<div hidden class="dc-wrap', 1)
        out.append(b)
    return f'<div class="dc-bans">{"".join(out)}</div>'


def render(data, cfg, fetched_at, wrap=None, deltas=None, exam_eve=None,
           rules_stale=False, squad_view=None, knocks=None, reviews=None,
           sync_error=False, live=False, tricky=None, milestones=None, room=None, plans=None,
           notice=None, asks=None, due=None, you=None, sticking=None, sev=None, milestone_sev=None, closet=None,
           halloween=None, wrapped=None, fridge=None):
    """3.8.0: two parts, apart. On top the You bubble (you_html): due,
    Due's view (due_flow.view, None when Due is off), and you, its Plans and
    Insights ({tab, folded, plans, insights}; None draws Due alone). Under it
    the board, your people: Crew (Today, Week, Decks) and Squads.
    sticking: {deck name: deck id} of my decks Insights has, for Decks' links.
    live: I'm studying now (the footer offers to stop). tricky: flagged
    cards I share with a crewmate (Crew › Decks). milestones: [(uid, name,
    days)] for a crewmate's 100- or 365-day streak, with a one-tap cheer.
    room (2.12): {"mine": lobby or None, "invites": [...], "done": ...};
    see room_html. plans (3.1): {cards, offers} from plan_flow.board_view
    (the cards are You › Plans'; a squad's offers show on Squads too).
    notice (3.2.1): the admin's {id, text, link}, on top of every tab.
    asks (3.5.0): my own asks about cards (together.my_asks_view), Crew › Decks.
    sev (3.8.1): Pip beside the logo for a moment, {svg, ago} (rooms.board_sev), or None.
    milestone_sev (3.8.1): {uid: Pip's markup} for a streak banner, Pip in its emoji's place.
    closet (3.8.2): {keys, first}: what just came for Pip, for its line (closet_line).
    halloween (3.8.22): Halloween week's line, its bats and cobweb (halloween_html), or None.
    wrapped (3.9.0): {year, so_far, look} for the line that your year is ready (1 Dec to 15 Jan), or None.
    fridge (3.9.1): the doodles my crew sent (fridge.clean's), pinned around the Decks screen (fridge_html)."""
    period = cfg.get("period", "today")
    hidden = hidden_tabs(cfg)
    if period not in PERIODS or period in hidden:
        period = "today"  # a saved Plans (before 3.8.0) or a hidden view: Crew's Today
    show_up = bool(cfg.get("show_up"))
    pick = "" if period == "squads" else _crew_picker(period, show_up, hidden)
    body = (_decks_html(data, deltas, tricky, None, asks, sticking, pick) if period == "decks"
            else _squads_html(squad_view or {"state": "none"}, cfg,
                              {e.get("user_id"): e for e in data.get("entries") or [] if not e.get("you")})
            if period == "squads"
            else _table_html(data, cfg, period, pick))
    # 3.4 review, H6: one banner at a time, the most time-bound first; the
    # rest wait behind "1 of N ›". The admin's notice and my own room stay.
    bans = []
    if exam_eve and exam_eve.get("people"):
        # 2.10: a line for their exam-morning card, rather than a cheer now
        links = [f'<a class="dc-pl" href="#" title="Add a line to their good-luck card" '
                 f'onclick="{_pycmd("luckline:" + str(u))}">'
                 f'<b>{_html.escape(str(n))}</b></a>'
                 for u, n in exam_eve["people"]]
        if len(links) == 1:
            uid = exam_eve["people"][0][0]
            line = f'{links[0]}&rsquo;s exam is tomorrow.'
            act = (f'<a class="wc" href="#" title="They see it when they open Anki that morning" '
                   f'onclick="{_pycmd("luckline:" + str(uid))}">&#127808; Add a line to their card</a>')
        else:
            line = " and ".join(links) + " have exams tomorrow."
            act = ""
        bans.append(f'<div class="dc-wrap eve"><span>&#128214;</span>'
                    f'<span>{line}</span>{act}'
                    f'<a class="wx" href="#" title="Dismiss" '
                    f'onclick="{_pycmd("evedismiss")}">&times;</a></div>')
    for k in (knocks or [])[:3]:
        # someone in a squad added me: my add makes it mutual
        who = _html.escape(str(k.get("name", "?")))
        # a squadmate's add names the squad; an add by code (2.9) says so
        where = (f' from {_html.escape(str(k["squad"]))}' if k.get("squad")
                 else " your code" if k.get("via_code") else "")
        uid = str(k.get("uid", ""))
        bans.append(f'<div class="dc-wrap knock"><span>&#128075;</span>'
                    f'<span><b>{who}</b> added{"" if k.get("via_code") and not k.get("squad") else " you"}{where}</span>'
                    f'<a class="wc" href="#" title="Add back" '
                    f'onclick="{_pycmd("addback:" + uid)}">Add back</a>'
                    f'<a class="wx" href="#" title="Not now" '
                    f'onclick="{_pycmd("knockmute:" + uid)}">&times;</a></div>')
    for uid, who, days in (milestones or [])[:2]:
        emoji = "&#128175;" if int(days) < 365 else "&#127881;"
        fig = (milestone_sev or {}).get(uid)  # 3.8.1 (Sam's pick): Pip hops in the emoji's place
        icon = f'<span class="dc-fig">{_sev.slot(fig, 40)}</span>' if fig else f"<span>{emoji}</span>"
        bans.append(f'<div class="dc-wrap">{icon}'
                    f'<span><b>{_html.escape(str(who))}</b> just reached a {int(days)}-day streak.</span>'
                    f'<a class="wc" href="#" title="Send a cheer" '
                    f'onclick="{_pycmd("milestonecheer:" + str(uid))}">Send {emoji}</a>'
                    f'<a class="wx" href="#" title="Dismiss" '
                    f'onclick="{_pycmd("milestonex:" + str(uid))}">&times;</a></div>')
    if wrapped and wrapped.get("year"):
        bans.append(wrapped_line(wrapped["year"], wrapped.get("so_far"), wrapped.get("look") or [], cfg.get("sev", True)))
    if closet and closet.get("keys") and cfg.get("sev", True):
        line = closet_line(closet["keys"], my_look(cfg), bool(closet.get("first")))
        if line:
            bans.append(line)
    lobby = ""
    if room and period in ("today", "week"):
        bans += [b for b in _split_wraps(room_html({"done": room.get("done"), "invites": room.get("invites"),
                                                     "fifteen_done": room.get("fifteen_done")}))]
        lobby = room_html({"mine": room.get("mine")})
    if wrap and not show_up:  # the week's totals are numbers
        extra = ""
        if (wrap.get("full_days") or 0) >= 3:
            extra = f' &middot; everyone showed up {wrap["full_days"]} of 7 days'
        if wrap.get("best_name"):
            extra += (f' &middot; {_html.escape(str(wrap["best_name"]))}&rsquo;s '
                      f'best week yet')
        if 0 < int(wrap.get("days_known") or 7) < 7:
            extra += f' &middot; from {int(wrap["days_known"])} of its 7 days'
        if wrap.get("milestone"):
            extra += (f' &middot; and the crew just passed '
                      f'<b>{_html.escape(str(wrap["milestone"]))} all-time</b>')
        bans.append(f'<div class="dc-wrap"><span>&#127881;</span>'
                    f'<span><b>Last week, together:</b> '
                    f'{wrap["reviews"]:,} reviews &middot; {_fmt_time(wrap["time_ms"])}{extra}</span>'
                    f'<a class="wc" href="#" title="Copy for the group chat" '
                    f'onclick="{_pycmd("wrapcopy")}">Copy</a>'
                    f'<a class="wx" href="#" title="Dismiss" '
                    f'onclick="{_pycmd("wrapdismiss")}">&times;</a></div>')
    for kind in ("month", "year"):
        if reviews and reviews.get(kind):
            bans.append(_review_banner(kind, reviews[kind]))
    if period == "squads":
        bans += _split_wraps(_offer_banners((plans or {}).get("offers")))  # and on You's Plans
    body = (notice_html(notice) if notice else "") + _one_at_a_time(bans) + lobby + body

    # 3.4 review, H5: the day's two social actions as buttons, the rest in
    # one Crew menu, and Refresh and Settings as quiet icons
    left = ""
    if rules_stale:
        left += ('<span class="warn" title="The server is behind this version; '
                 'some sharing is paused until it catches up.">'
                 '&#9888; server catching up</span>')
    if period in ("today", "week") and not cfg.get("paused"):
        # 2.10: a dot by your name for an hour, so friends can join you
        left += (f'<a class="pb on" href="#" title="Stop showing that you\'re studying" '
                 f'onclick="{_pycmd("live")}">Stop studying</a>' if live else
                 f'<a class="pb on" href="#" title="A dot by your name for the next hour" '
                 f'onclick="{_pycmd("live")}">I&rsquo;m studying</a>')
        if not (room or {}).get("mine"):
            # 2.12: a study room for the crew
            left += (f'<a href="#" title="Rounds and breaks with your crew" '
                     f'onclick="{_pycmd("roomopen")}">Open a room</a>')  # 3.8.0: one pill in the footer
    left += (f'<a href="#" title="Friends" '
             f'onclick="{_pycmd("crewmenu")}">Crew</a>'  # 3.8.0 (Sam): no caret
             f'<a href="#" title="As text or a picture" '
             f'onclick="{_pycmd("sharemenu")}">Share</a>')
    n_pending = len(data.get("pending", []))
    if n_pending:
        left += (f'<a class="warn" href="#" title="You added them; you\'re crew when they add you back" '
                 f'onclick="{_pycmd("friends")}">{n_pending} waiting</a>')

    ago, _tone = _ago_secs(max(0.0, time.time() - fetched_at)) if fetched_at else ("just now", "")
    failed = ('<span class="warn" title="The last sync didn\'t reach the server. '
              'Your numbers are safe; Refresh tries again.">Couldn&rsquo;t sync</span>'
              ' &middot; ') if sync_error else ""
    foot = (f'<div class="dc-foot"><span class="fl">{left}</span><span class="sp"></span>'
            f'<span class="fr">{failed}<span class="upd">Updated {ago}</span>'
            f'<a class="ic" href="#" title="Refresh" onclick="{_pycmd("refresh")}">&#8635;</a>'
            f'<a class="ic" href="#" title="Settings" onclick="{_pycmd("settings")}">&#9881;&#xFE0E;</a></span></div>')

    # 3.8.1: Pip's moments; a crew room's Pips each wear their person's accent, by day or by night as the board
    seat = _by_theme(cfg, "#due-crew .dc-room .seat", "--sv-a: var(--sa-l);", "--sv-a: var(--sa-d);")
    # 3.8.2: and each crew row's Pip wears its person's colour, as the seats do
    seat += _by_theme(cfg, "#due-crew .dc-rsev", "--sv-a: var(--rs-l);", "--sv-a: var(--rs-d);")
    # the name's cell clips what spills out of it: room above the line for a Pip's hat, the whole
    # row's (tr.sv) so the name and the numbers stay on one line
    seat += f"\n    #due-crew tr.sv > td {{ padding-top: {(3 if cfg.get('compact') else 6) + 6}px; }}"
    sheet = f'<style>{SEV_CSS}{CLOSET_CSS}{HW_CSS if halloween else ""}{seat}{_sev.CSS}</style>' if cfg.get("sev", True) else ""
    people = {x.get("user_id"): x for x in data.get("entries") or []}  # 3.8.22: a plan's squad line, mine too
    return (f'<div id="due-crew" class="dc-frame dc-split">{_css(cfg)}<style>{DUE_CSS}</style>{sheet}'
            f'{you_html(cfg, due, you, people)}<div class="dc-sheet">'
            f'{_head(period, show_up, hidden, cfg.get("crew_view") or period, sev)}{halloween_html(halloween, cfg)}{body}{foot}</div>'
            f'{fridge_html(fridge, people, cfg)}</div>')  # 3.9.1: the doodles, pinned around the Decks screen


def you_html(cfg, due=None, you=None, people=None):
    """3.8.0, the You bubble: Today, Upcoming and Later (Due's lists, when
    Due is on), then Plans and Insights unless hidden in Settings. due:
    due.view or None; you: {tab, folded, plans, insights, opened}, from the glue
    (None: Due's lists alone, as before). "" when there's nothing to show.
    people (3.8.22): {uid: crew entry}, mine too, for a plan's squad line."""
    if you is None:
        return _due_html(due)
    hidden = hidden_tabs(cfg)
    more = tuple(t for t in YOU_MORE if t[0] not in hidden)
    keys = (["today", "upcoming", "later"] if due else []) + [k for k, _l in more]
    if not keys:
        return ""
    tab = you.get("tab") if you.get("tab") in keys else keys[0]
    body = (_you_plans(you.get("plans"), None if due else you.get("opened"), people, cfg) if tab == "plans"
            else _you_insights(you.get("insights")) if tab == "insights" else "")
    return _due_html(due, more, tab if tab in dict(more) else None, body, folded=bool(you.get("folded")))



# ---- 3.5.0: Settings, in the board ----

SETTINGS_CSS = """
    #due-crew.dc-set, #due-crew.dc-set .st-row, #due-crew.dc-set .st-l { text-align: left; }
    /* Anki styles every button on the Decks screen (a margin, a shadow,
       rounded corners); the panel's own controls start from nothing */
    #due-crew.dc-set button { -webkit-appearance: none; appearance: none; margin: 0; box-shadow: none;
      min-width: 0; min-height: 0; text-shadow: none; background-image: none; vertical-align: middle; }
    #due-crew .st-radio { box-sizing: border-box; border-radius: 0; }
    #due-crew .st-box { overflow: hidden; }
    #due-crew .st-bar { display: flex; align-items: baseline; gap: 10px; margin: 2px 0 10px; }
    #due-crew .st-bar b { font-size: 15px; }
    #due-crew .st-back { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .st-h { font-size: 11px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-muted); margin: 12px 0 5px; }
    #due-crew .st-box { border: 1px solid var(--dc-line); border-radius: 9px; }
    #due-crew .st-row { display: flex; align-items: center; justify-content: space-between; gap: 6px 12px;
      padding: 7px 11px; flex-wrap: wrap; }
    #due-crew .st-row + .st-row { border-top: 1px solid var(--dc-line); }
    #due-crew .st-l { display: grid; gap: 1px; min-width: 0; }
    #due-crew .st-l small, #due-crew .st-note { color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .st-note { margin-top: 8px; }
    #due-crew .st-r { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    #due-crew .st-tg { width: 30px; height: 17px; border-radius: 99px; border: 0; padding: 0; cursor: pointer;
      background: var(--dc-line); position: relative; flex: none; }
    #due-crew .st-tg::after { content: ""; position: absolute; top: 2px; left: 2px; width: 13px; height: 13px;
      border-radius: 50%; background: var(--dc-bg); }
    #due-crew .st-tg.on { background: var(--dc-accent); }
    #due-crew .st-tg.on::after { left: 15px; }
    #due-crew .st-seg { display: inline-flex; }
    #due-crew .st-seg button, #due-crew .st-pill { font: inherit; font-size: 11.5px; font-weight: 700; cursor: pointer;
      border: 1px solid var(--dc-line); background: transparent; color: var(--dc-muted); padding: 2px 10px; }
    #due-crew .st-seg button { border-radius: 0; }
    #due-crew .st-seg button:first-child { border-radius: 99px 0 0 99px; }
    #due-crew .st-seg button:last-child { border-radius: 0 99px 99px 0; }
    #due-crew .st-seg button + button { border-left: none; }
    #due-crew .st-seg button.on { background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }
    #due-crew .st-pills { display: flex; gap: 5px; flex-wrap: wrap; }
    #due-crew .st-pill { border-radius: 99px; }
    #due-crew .st-pill.on { border-color: var(--dc-accent); background: var(--dc-you-bg); color: var(--dc-ink); }
    #due-crew .st-pill.on::before { content: "\\2713  "; color: var(--dc-accent); }
    #due-crew .st-pill[disabled] { cursor: default; opacity: .6; }
    #due-crew .st-sw { display: flex; gap: 7px; }
    #due-crew .st-sw button { width: 18px; height: 18px; border-radius: 50%; border: 0; padding: 0; cursor: pointer;
      box-shadow: 0 0 0 2px var(--dc-bg); }
    #due-crew .st-sw button.on { box-shadow: 0 0 0 2px var(--dc-bg), 0 0 0 4px var(--dc-ink); }
    #due-crew .st-kbd { font: 11px Menlo, Consolas, monospace; border: 1px solid var(--dc-line); border-radius: 5px;
      padding: 1px 6px; color: var(--dc-ink); white-space: nowrap; }
    #due-crew .st-in { font: inherit; font-size: 12.5px; border: 1px solid var(--dc-line); border-radius: 6px;
      padding: 2px 7px; background: var(--dc-bg); color: var(--dc-ink); color-scheme: light dark; }
    #due-crew .st-in:disabled { color: var(--dc-faded); }
    #due-crew .st-lk { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .st-danger { color: #d64035; }
    #due-crew .st-who { display: flex; gap: 10px; align-items: center; }
    #due-crew .st-who .em { font-size: 26px; line-height: 1; }
    #due-crew .st-who b { font-size: 15px; }
    #due-crew .st-acts { display: flex; gap: 14px; flex-wrap: wrap; margin: 8px 0; }
    #due-crew .st-radio { display: grid; grid-template-columns: 16px 1fr; gap: 8px; padding: 8px 11px; cursor: pointer;
      width: 100%; text-align: left; font: inherit; color: inherit; background: transparent; border: 0; }
    #due-crew .st-radio + .st-radio, #due-crew .st-sub + .st-radio { border-top: 1px solid var(--dc-line); }
    #due-crew .st-radio i { box-sizing: border-box; width: 14px; height: 14px; border-radius: 50%;
      border: 1.5px solid var(--dc-faded); margin-top: 2px; }
    #due-crew .st-radio.on { background: var(--dc-you-bg); }
    #due-crew .st-radio.on i { border: 4px solid var(--dc-accent); }
    #due-crew .st-radio span { display: grid; gap: 2px; }
    #due-crew .st-radio small { color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .st-sub { padding: 0 11px 9px 35px; margin-top: -2px; background: var(--dc-you-bg); }
    #due-crew .st-foot { display: flex; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap;
      margin-top: 10px; padding-top: 8px; border-top: 1px solid var(--dc-line); color: var(--dc-muted); font-size: 11.5px; }
    #due-crew button:focus-visible, #due-crew a:focus-visible, #due-crew input:focus-visible {
      outline: 2px solid var(--dc-accent); outline-offset: 2px; }
    /* 3.8.0, pick 28: Find a setting */
    #due-crew .st-find { margin-left: auto; position: relative; text-align: left; }
    #due-crew .st-find input { width: 150px; max-width: 42vw; }
    #due-crew .st-hits { position: absolute; right: 0; top: calc(100% + 4px); z-index: 20; min-width: 240px; max-width: 80vw;
      display: grid; background: var(--dc-bg); border: 1px solid var(--dc-line); border-radius: 10px; padding: 4px;
      box-shadow: 0 6px 22px rgba(0,0,0,.14); }
    #due-crew .st-hits[hidden] { display: none; }
    #due-crew .st-hits button { all: unset; display: grid; gap: 1px; padding: 6px 9px; border-radius: 7px; cursor: pointer; text-align: left; }
    #due-crew .st-hits button:hover, #due-crew .st-hits button.on { background: var(--dc-you-bg); }
    #due-crew .st-hits b { font-size: 12.5px; color: var(--dc-ink); }
    #due-crew .st-hits small { font-size: 11px; color: var(--dc-muted); }
    #due-crew .st-hits .st-none { padding: 6px 9px; font-size: 12px; color: var(--dc-muted); }
    @keyframes sthit { from { background-color: color-mix(in srgb, var(--dc-accent) 26%, transparent); } }  /* to its own ground, whatever that is */
    @media (prefers-reduced-motion: no-preference) { #due-crew .st-hit { animation: sthit 1.8s ease-out; } }
    @media (prefers-reduced-motion: reduce) { #due-crew .st-hit { outline: 2px solid var(--dc-accent); outline-offset: 1px; } }
"""
SETTINGS_TABS = (("you", "You"), ("board", "Board"), ("privacy", "Privacy"))


def _st_row(label, control, sub=""):
    sub = f"<small>{sub}</small>" if sub else ""
    return f'<div class="st-row"><span class="st-l"><span>{label}</span>{sub}</span><span class="st-r">{control}</span></div>'


def _st_click(cmd):
    """onclick for a settings command; data-f names it, so focus comes back
    to it after the panel redraws."""
    return f'data-f="{_html.escape(_re.sub(r"[^A-Za-z0-9:_-]", "", cmd))}" onclick="{_pycmd(cmd)}"'


def _st_switch(key, on, label):
    return (f'<button class="st-tg{" on" if on else ""}" role="switch" aria-checked="{"true" if on else "false"}" '
            f'aria-label="{_html.escape(label)}" {_st_click(f"set:{key}:{0 if on else 1}")}></button>')


def _st_seg(key, options, current, label):
    btns = "".join(f'<button class="{"on" if v == current else ""}" aria-pressed="{"true" if v == current else "false"}" '
                   f'{_st_click(f"set:{key}:{v}")}>{t}</button>' for v, t in options)
    return f'<span class="st-seg" role="group" aria-label="{label}">{btns}</span>'


def _settings_you(view, cfg=None):
    """cfg (3.8.22): with Pip on, my Pip where my emoji was, opening the
    closet (Emoji… stays: it shows with Pip off and in text shares)."""
    e = _html.escape
    if not view.get("signed_in"):
        return (f'<p>Not signed in.</p><div class="st-acts">'
                f'<a class="st-lk" href="#" {_st_click("setsignin")}>Start with your email</a></div>')
    emoji = e(str(view.get("emoji") or ""))
    status = str(view.get("status") or "")
    fig = (f'<a class="st-pip" href="#" title="Pip&rsquo;s closet" onclick="{_pycmd("closet")}">'
           f'{_sev.slot(_sev.svg("idle", rest=True, look=my_look(cfg), label="Your Pip"), SETTINGS_PIP)}</a>'
           if cfg is not None and cfg.get("sev", True) else f"<span class=em>{emoji}</span>" if emoji else "")
    out = (f'<div class="st-who">{fig}'
           f'<span style="display:grid"><b>{e(str(view.get("name") or "?"))}</b>'
           f'<span style="color:var(--dc-muted)">{"&ldquo;" + e(status) + "&rdquo;" if status else "No status"}</span></span></div>'
           f'<div class="st-acts"><a class="st-lk" href="#" {_st_click("setname")}>Name&hellip;</a>'
           f'<a class="st-lk" href="#" {_st_click("setemoji")}>Emoji&hellip;</a>'
           f'<a class="st-lk" href="#" {_st_click("setstatus")}>Status&hellip;</a></div>'
           f'<div class="st-note" style="margin:0 0 10px">{e(str(view.get("sync") or ""))}</div>')
    crew = int(view.get("crew") or 0)
    squads = [str(x) for x in view.get("squads") or []]
    decks = [str(x) for x in view.get("decks") or []]

    def names(xs, none):
        if not xs:
            return none
        shown = ", ".join(e(x) for x in xs[:2])
        return shown + (f" and {len(xs) - 2} more" if len(xs) > 2 else "")
    out += ('<div class="st-box">'
            + _st_row("Friends", f'<a class="st-lk" href="#" {_st_click("friends")}>Open</a>',
                      f"{crew} in your crew" if crew else "Your code, and who's in your crew")
            + _st_row("Squads", f'<a class="st-lk" href="#" {_st_click("setsquads")}>Open</a>', names(squads, "None yet"))
            + _st_row("Shared decks", f'<a class="st-lk" href="#" {_st_click("decks")}>Open</a>', names(decks, "None yet"))
            + '</div>')
    # 3.6.5, P6: feedback, here as well as in Tools › Due Crew
    out += ('<div class="st-box">'
            + _st_row("Feedback", f'<a class="st-lk" href="#" {_st_click("setfeedback")}>Send&hellip;</a>')
            + '</div>')
    out += (f'<div class="st-foot"><a class="st-lk" href="#" {_st_click("setsignout")}>Sign out</a>'
            f'<a class="st-lk st-danger" href="#" {_st_click("setdelete")}>Delete account&hellip;</a></div>'
            f'<div class="st-foot"><span>{KEEP_LINE}</span></div>')
    return out


def _accent_swatches(cfg):
    """The accent's swatches (Settings › Board and, 3.9.0, the closet):
    Pip's colour and the board's, the one your crew sees Pip in."""
    accent = cfg.get("accent", DEFAULT_ACCENT)
    return "".join(
        f'<button class="{"on" if k == accent else ""}" style="background:{v["light"][0]}" title="{k.title()}" '
        f'aria-label="{k.title()}" aria-pressed="{"true" if k == accent else "false"}" {_st_click(f"set:accent:{k}")}></button>'
        for k, v in ACCENTS.items())


def _settings_board(cfg, fsrs=None):
    """fsrs (3.9.1): whether FSRS is on in this collection (None: not known),
    for two buttons' one-line note."""
    hidden = hidden_tabs(cfg)
    pills = '<button class="st-pill on" disabled aria-pressed="true">Crew</button>' + "".join(
        f'<button class="st-pill{"" if k in hidden else " on"}" aria-pressed="{"false" if k in hidden else "true"}" '
        f'{_st_click(f"settabs:{k}:{1 if k in hidden else 0}")}>{t}</button>' for k, t in HIDEABLE_TABS)
    swatches = _accent_swatches(cfg)
    label = _html.escape(str(cfg.get("crew_label") or "Crew"))
    label_in = (f'<input class="st-in" data-f="label" maxlength="24" size="12" value="{label}" aria-label="Crew name in shares" '
                f'onchange="pycmd(\'duecrew:setlabel:\'+encodeURIComponent(this.value));">')
    g = lambda k, d: bool(cfg.get(k, d))  # noqa: E731
    return ('<div class="st-h">What it shows</div><div class="st-box">'
            + _st_row("Due Crew on the Decks screen", _st_switch("show_leaderboard", g("show_leaderboard", True), "Due Crew on the Decks screen"),
                      "Tools › Due Crew › Show on the Decks screen brings it back")
            + _st_row("Yesterday for friends who haven't synced", _st_switch("show_stale", g("show_stale", True), "Yesterday for friends who haven't synced"))
            + _st_row("Tell me when my crew studies", _st_switch("sync_notifications", g("sync_notifications", True), "Tell me when my crew studies"))
            + _st_row("Shows", f'<span class="st-pills">{pills}</span>')
            + '</div><div class="st-h">How it looks</div><div class="st-box">'
            + _st_row("Theme", _st_seg("theme", (("auto", "Match Anki"), ("light", "Light"), ("dark", "Dark")), cfg.get("theme", "auto"), "Theme"))
            + _st_row("Accent", f'<span class="st-sw" role="group" aria-label="Accent">{swatches}</span>')
            + _st_row("Compact rows", _st_switch("compact", g("compact", False), "Compact rows"))
            + _st_row("Highlight my row", _st_switch("highlight_me", g("highlight_me", True), "Highlight my row"))
            + _st_row("Room chip", _st_seg("room_chip_side", (("left", "Left"), ("right", "Right")), cfg.get("room_chip_side", "right"), "Room chip"),
                      "Its side of Anki's top bar")
            + _st_row("Crew name in shares", label_in)
            + '</div><div class="st-h">Fifteen and Pip</div><div class="st-box">'
            + _st_row("Fifteen? in the top bar", _st_switch("fifteen", g("fifteen", True), "Fifteen? in the top bar"),
                      "And the nudge, when you haven't started by your usual time")
            + _st_row("Room sounds", _st_switch("room_sounds", g("room_sounds", True), "Room sounds"),
                      "Brown noise, rain, fire or waves while you study, from the chip")
            + _st_row("Pip", _st_switch("sev", g("sev", True), "Pip"), "The square from the logo, beside it and in your fifteens")
            + _st_row("Pip&rsquo;s closet", f'<a class="st-lk" href="#" {_st_click("closet")}>Open</a>',
                      "What your Pip has on, and what it&rsquo;s earned")
            + _st_row("On a break", _st_seg("sev_break", (("breathe", "Breathe"), ("stretch", "Stretch")),
                                            cfg.get("sev_break", "breathe"), "On a break"),
                      "Breathe with Pip, four counts a side, or stretch")
            + '</div><div class="st-h">Due</div><div class="st-box">'
            + _st_row("Today, Upcoming, Later", _st_switch("due_show", g("due_show", True), "Today, Upcoming, Later"))
            + _st_row("Suggestions", _st_switch("due_suggest", g("due_suggest", True), "Suggestions"),
                      "Today's misses, new leeches")
            + _st_row("Recover leeches", _st_switch("due_leeches", g("due_leeches", False), "Recover leeches"),
                      "Each morning, as new cards")
            # 3.9.1, two buttons (Sam's picks): every deck; FSRS off, allowed with a note
            + '</div><div class="st-h">Reviewing</div><div class="st-box">'
            + _st_row("Two buttons", _st_switch("two_buttons", g("two_buttons", False), "Two buttons"),
                      "Again and Good. Hard and Easy hide; 2, 3 and 4 count as Good. Phones keep four."
                      + (" Works best with FSRS on." if fsrs is False else ""))
            + '</div><div class="st-h">Shortcuts</div><div class="st-box">'
            + _st_row("Study what&rsquo;s next", f'<kbd class="st-kbd">{STUDY_KBD}</kbd>', "From any Anki screen")
            + _st_row("Ask the squad about this card", f'<kbd class="st-kbd">{ASK_KBD}</kbd>', "While reviewing")
            + _st_row("Shortcuts on", _st_switch("shortcuts", g("shortcuts", True), "Shortcuts on"),
                      "Off if another add-on uses these keys")
            + '</div>'
            + f'<div class="st-foot"><span></span>'
              f'<a class="st-lk" href="#" {_st_click("setreset")}>Reset board</a></div>')


def _settings_privacy(cfg):
    choice = "paused" if cfg.get("paused") else "showup" if cfg.get("show_up") else "numbers"

    def radio(key, title, sub=""):
        on = key == choice
        return (f'<button class="st-radio{" on" if on else ""}" role="radio" aria-checked="{"true" if on else "false"}" '
                f'{_st_click(f"setprivacy:{key}")}><i></i><span><b>{title}</b>{f"<small>{sub}</small>" if sub else ""}</span></button>')
    nums = ""
    if choice == "numbers":
        nums = '<div class="st-sub"><span class="st-pills">' + "".join(
            f'<button class="st-pill{" on" if cfg.get(k, True) else ""}" aria-pressed="{"true" if cfg.get(k, True) else "false"}" '
            f'{_st_click(f"set:{k}:{0 if cfg.get(k, True) else 1}")}>{t}</button>'
            for k, t in (("share_reviews", "Reviews"), ("share_time", "Study time"), ("share_retention", "Retention"),
                         ("share_streak", "Streak"), ("share_heatmap", "Heatmap"))) + '</span></div>'
    exam = str(cfg.get("exam_date") or "")
    a, b = str(cfg.get("away_from") or ""), str(cfg.get("away_to") or "")
    away_on = bool(a and b)
    esc = _html.escape
    exam_ctl = (f'<input class="st-in" type="date" data-f="exam" value="{esc(exam)}"{"" if exam else " disabled"} '
                f'aria-label="Exam date" onchange="if(this.value)pycmd(\'duecrew:setexam:\'+this.value);">'
                + _st_toggle_cmd("setexam:" + ("off" if exam else "on"), bool(exam), "Exam"))
    send = "pycmd('duecrew:setaway:'+document.getElementById('st-af').value+':'+document.getElementById('st-at').value);"
    away_ctl = (f'<input class="st-in" type="date" id="st-af" data-f="af" value="{esc(a)}"{"" if away_on else " disabled"} aria-label="Away from" '
                f'onchange="{send}"><span style="color:var(--dc-muted)">to</span>'
                f'<input class="st-in" type="date" id="st-at" data-f="at" value="{esc(b)}"{"" if away_on else " disabled"} aria-label="Away until" '
                f'onchange="{send}">' + _st_toggle_cmd("setaway:" + ("off" if away_on else "on"), away_on, "Away"))
    return ('<div class="st-h">What your crew and squads see</div><div class="st-box" role="radiogroup">'
            + radio("numbers", "My numbers") + nums
            + radio("showup", "Just that I studied", "Squares, no numbers. You see everyone the same way.")
            + radio("paused", "Nothing for now", "Your crew sees &ldquo;on a break&rdquo;; your streak keeps counting. "
                    "Kept 24 months without activity.")
            + '</div><div class="st-h">Dates your crew sees</div><div class="st-box">'
            + _st_row("&#128214; Exam", exam_ctl, "Shown for the two weeks before")
            + _st_row("&#9992;&#65039; Away", away_ctl)
            + '</div><div class="st-foot"><span>Turning a number off also takes it off this week.</span>'
            # 3.7.1, D3: the page that says what's kept, for how long, and how it goes
            f'<a class="st-lk" href="#" {_st_click("privacypage")}>What Due Crew keeps &rsaquo;</a></div>')


def _st_toggle_cmd(cmd, on, label):
    return (f'<button class="st-tg{" on" if on else ""}" role="switch" aria-checked="{"true" if on else "false"}" '
            f'aria-label="{label}" {_st_click(cmd)}></button>')


# 3.8.0, pick 28 (Find a setting): words people use for a setting that its own label doesn't say
FIND_WORDS = {
    "set:theme:": "dark light night mode", "set:accent:": "colour color green purple blue", "set:compact:": "dense small",
    "set:sync_notifications:": "notify notification alert", "set:show_leaderboard:": "hide off board decks screen",
    "settabs:": "tabs hide squads decks plans insights", "set:due_suggest:": "hard habit misses again",
    "set:due_leeches:": "leech suspended", "set:shortcuts:": "keys keyboard", "set:share_time:": "minutes hours privacy private",
    "set:share_reviews:": "cards numbers privacy private", "set:share_heatmap:": "year squares", "exam": "test date countdown",
    "af": "holiday vacation trip break", "setprivacy:paused": "pause break hide", "setprivacy:showup": "show up numbers squares",
    "setsignout": "log out", "setdelete": "remove erase", "setfeedback": "bug idea report", "label": "crew name group",
    "setreset": "default", "friends": "crew code invite", "decks": "share deck",
    # 3.8.1: the Fifteen and Pip
    "set:fifteen:": "timer pomodoro focus session nudge minutes", "set:sev:": "mascot character buddy animation",
    "set:room_sounds:": "sound noise audio ambient music speaker volume brown rain fire waves",
    "set:sev_break:": "breathe stretch rest",
    # 3.9.1
    "set:two_buttons:": "hard easy again good pass fail answer buttons keys review",
}


def _find_key(f):
    """A control's data-f, without the state at its end ("set:share_time:0"
    finds the switch whichever way it's set)."""
    bits = f.split(":")
    return ":".join(bits[:2]) + ":" if bits[0] in ("set", "settabs") and len(bits) > 2 else f


def settings_index(view, cfg):
    """3.8.0, pick 28: every setting a word can find, across Settings' three
    tabs: [{t: tab, f: the control's data-f (its start), l: its label,
    w: where ("Board › How it looks"), k: words to match}]. Read from the
    tabs as they're drawn, so a new row is findable as soon as it's there.
    Labels and headings are the add-on's own words; the people, squads and
    decks the You tab names stay out."""
    import html as H
    names = dict(SETTINGS_TABS)
    out, seen = [], set()

    def add(tab, f, label, where, extra=""):
        label = " ".join(_re.sub(r"<[^>]+>", "", H.unescape(label)).split())
        key = (tab, _find_key(f))
        if not label or key in seen:
            return
        seen.add(key)
        words = " ".join([label, where, extra] + [w for k, w in FIND_WORDS.items() if f.startswith(k)])
        out.append({"t": tab, "f": _find_key(f), "l": label, "w": where, "k": " ".join(_re.findall(r"[a-z0-9]+", words.lower()))})
    for tab in ("you", "board", "privacy"):
        body = (_settings_you(dict(view, name="", status="", emoji="")) if tab == "you"
                else _settings_board(cfg, view.get("fsrs")) if tab == "board" else _settings_privacy(cfg))
        sections = _re.split(r'<div class="st-h">', body)
        for i, sec in enumerate(sections):
            head = H.unescape(sec.split("</div>", 1)[0]) if i else ""
            where = names[tab] + (f" › {head}" if head else "")
            rows = list(_re.finditer(r'<div class="st-row"><span class="st-l"><span>(.*?)</span>(?:<small>(.*?)</small>)?', sec))
            for j, m in enumerate(rows):
                end = rows[j + 1].start() if j + 1 < len(rows) else len(sec)
                f = _re.search(r'data-f="([^"]+)"', sec[m.end():end])
                sub = H.unescape(m.group(2) or "") if tab != "you" else ""  # the You tab's lines name people and squads
                if f:
                    add(tab, f.group(1), m.group(1), where, sub)
                for pf, pt in _re.findall(r'<button class="st-pill[^"]*"[^>]*data-f="([^"]+)"[^>]*>(.*?)</button>', sec[m.end():end]):
                    add(tab, pf, pt, where + " › " + H.unescape(m.group(1)))
            for f, b, small in _re.findall(r'<button class="st-radio[^"]*"[^>]*data-f="([^"]+)"[^>]*><i></i><span><b>(.*?)</b>(?:<small>(.*?)</small>)?', sec):
                add(tab, f, b, where, H.unescape(small))
            for f, t in _re.findall(r'<button class="st-pill[^"]*"[^>]*data-f="([^"]+)"[^>]*>(.*?)</button>', sec):
                add(tab, f, t, where)
            for f, t in _re.findall(r'<a class="st-lk[^"]*" href="#" data-f="([^"]+)"[^>]*>(.*?)</a>', sec):
                if t.strip() not in ("Open", "Send&hellip;"):
                    add(tab, f, t, where)
    return out


def settings_html(view, cfg):
    """3.5.0: Settings in place of the board.
    view: {tab, signed_in, name, emoji, status, sync, crew, squads, decks},
    from the glue; every string in it is escaped here."""
    tab = view.get("tab") if view.get("tab") in dict(SETTINGS_TABS) else "you"
    pills = "".join(f'<a class="dc-pill{" on" if k == tab else ""}" href="#" {_st_click("settab:" + k)}>{t}</a>'
                    for k, t in SETTINGS_TABS)
    body = (_settings_you(view, cfg) if tab == "you" else _settings_board(cfg, view.get("fsrs")) if tab == "board"
            else _settings_privacy(cfg))
    foot = "Privacy, dates, status and accent follow your account." if view.get("signed_in") else ""
    pip = ""
    if tab == "you" and cfg.get("sev", True):  # 3.8.22: my Pip in my colour, by day or night as the board
        light, dark = accent_pair(cfg.get("accent"))
        pip = (f'<style>{_sev.CSS}{_by_theme(cfg, "#due-crew .st-pip", f"--sv-a: {light};", f"--sv-a: {dark};")}'
               '\n#due-crew .st-pip { display: inline-flex; line-height: 0; margin: 6px 8px 0 0; text-decoration: none; border: 0; }</style>')
    return (f'<div id="due-crew" class="dc-frame dc-set">{_css(cfg)}<style>{SETTINGS_CSS}</style>{pip}'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span><span>{pills}</span></div>'
            f'<div class="st-bar"><a class="st-back" href="#" {_st_click("setclose")}>&lsaquo; Board</a><b>Settings</b>'
            # 3.8.0, pick 28: a word finds a setting on any tab (FIND_JS)
            f'<span class="st-find"><input type="search" class="st-in" placeholder="Find a setting" aria-label="Find a setting" '
            f'autocomplete="off" data-ix="{_html.escape(_json.dumps(settings_index(view, cfg)), quote=True)}" '
            f'oninput="dcFind.type(this)" onkeydown="dcFind.key(event, this)">'
            f'<span class="st-hits" role="listbox" aria-label="Settings found" hidden></span></span></div>'
            f'{body}'
            f'{f"<div class=st-note>{foot}</div>" if foot else ""}</div>')


# ---- 3.8.2: Pip's closet ----

CLOSET_TABS = ("Yours", "To earn")
# the places on Pip, top to bottom, as the closet lists them; a costume over them all
CLOSET_PLACES = ("head", "face", "body", "hand", "back")
PLACE_NAMES = {"head": "Head", "face": "Face", "body": "Body", "hand": "Hand", "back": "Back", _closet.COSTUME: "Costume"}

CLOSET_CSS = """
    #due-crew.dc-closet { text-align: left; }
    #due-crew .cl-wrap { display: grid; grid-template-columns: 176px minmax(0, 1fr); gap: 16px; align-items: start; }
    @media (max-width: 560px) { #due-crew .cl-wrap { grid-template-columns: minmax(0, 1fr); } }
    #due-crew .cl-me { display: grid; gap: 8px; position: sticky; top: 6px; }
    #due-crew .cl-fig { width: 100%; display: grid; place-items: end center; padding: 20px 0 6px; border-radius: 12px;
      background: var(--dc-you-bg); }
    #due-crew .cl-fig svg.sv { width: 124px; height: 124px; }
    /* what's on, place by place: the one list of it */
    #due-crew .cl-ons { display: grid; gap: 1px; font-size: 12px; }
    #due-crew .cl-o { display: grid; grid-template-columns: 62px minmax(0, 1fr); align-items: baseline; gap: 4px;
      padding: 3px 6px; border-radius: 7px; min-height: 18px; }
    #due-crew .cl-o > span:first-child { font-size: 10px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
      color: var(--dc-muted); }
    #due-crew .cl-o button { font: inherit; font-weight: 700; color: var(--dc-ink); background: none; border: 0; padding: 0;
      margin: 0; box-shadow: none; cursor: pointer; text-align: left; border-radius: 0; }
    #due-crew .cl-o button::after { content: " \\00d7"; color: var(--dc-muted); font-weight: 400; }
    #due-crew .cl-o button:hover { color: var(--dc-accent); }
    #due-crew .cl-o i { font-style: normal; color: var(--dc-faded); }
    #due-crew .cl-o.cos { background: var(--dc-you-bg); }
    #due-crew .cl-ons.covered .cl-o:not(.cos) { opacity: .5; }
    #due-crew .cl-col { display: grid; gap: 5px; font-size: 12px; font-weight: 600; padding-bottom: 6px; border-bottom: 1px solid var(--dc-line); }
    #due-crew .cl-col small { font-weight: 400; color: var(--dc-muted); margin-left: 4px; }
    #due-crew .cl-col .st-sw { flex-wrap: wrap; padding: 2px 3px; }
    #due-crew .cl-msg { font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .cl-msg:empty { display: none; }
    #due-crew .cl-msg b { color: var(--dc-ink); }
    #due-crew .cl-n { font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .cl-main { display: grid; gap: 14px; min-width: 0; }
    #due-crew .cl-sec { display: grid; gap: 6px; }
    #due-crew .cl-sec h4 { margin: 0; font-size: 10.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
      color: var(--dc-muted); display: flex; gap: 6px; align-items: baseline; }
    #due-crew .cl-sec h4 small { font-weight: 400; letter-spacing: 0; text-transform: none; }
    #due-crew .cl-next { font-size: 11.5px; color: var(--dc-muted); padding: 2px 0 4px; }
    #due-crew .cl-near { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 6px; }
    #due-crew .cl-nr { display: flex; gap: 6px; align-items: center; border: 1px solid var(--dc-line); border-radius: 9px;
      padding: 3px 8px 3px 2px; font-size: 11.5px; min-width: 0; }
    #due-crew .cl-nr > span:last-child { display: grid; gap: 2px; min-width: 0; flex: 1; }
    #due-crew .cl-nr small { color: var(--dc-muted); font-size: 10.5px; }
    #due-crew .cl-bar { display: block; height: 4px; border-radius: 99px; background: var(--dc-line); overflow: hidden; }
    #due-crew .cl-bar i { display: block; height: 100%; background: var(--dc-accent); border-radius: 99px; }
    #due-crew .cl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(86px, 1fr)); gap: 6px; }
    #due-crew .cl-grid.lk { grid-template-columns: repeat(auto-fill, minmax(96px, 1fr)); }
    /* a thing of mine: plain until it's on; on is the accent, filled, and says so */
    #due-crew .cl-t { display: grid; justify-items: center; align-content: start; gap: 1px; padding: 8px 3px 7px; border-radius: 10px;
      border: 1px solid var(--dc-line); background: var(--dc-bg); color: var(--dc-ink); font: inherit; cursor: pointer;
      position: relative; text-align: center; margin: 0; box-shadow: none; }
    #due-crew button.cl-t:hover { border-color: var(--dc-accent); }
    #due-crew .cl-t b { font-size: 11.5px; line-height: 1.2; }
    #due-crew .cl-t small { font-size: 10px; color: var(--dc-muted); line-height: 1.25; }
    #due-crew .cl-t small.w { color: var(--dc-hours); font-weight: 700; }
    #due-crew .cl-t .cl-f { height: 40px; display: grid; place-items: end center; margin-bottom: 3px; }
    #due-crew .cl-t.on { border: 2px solid var(--dc-accent); padding: 7px 2px 6px; background: var(--dc-you-bg); }
    #due-crew .cl-t.on b { color: var(--dc-accent); }
    #due-crew .cl-t.under { border: 1px dashed var(--dc-accent); }
    #due-crew .cl-badge { position: absolute; top: 4px; right: 4px; font-size: 9px; font-weight: 800; line-height: 1;
      padding: 3px 5px; border-radius: 99px; background: var(--dc-accent); color: var(--dc-accent-ink); letter-spacing: .02em; }
    #due-crew .cl-badge.u { background: var(--dc-well); color: var(--dc-muted); }
    #due-crew .cl-badge.n { right: auto; left: 4px; background: var(--dc-hours); color: var(--dc-bg); }
    /* one still to earn: no click, greyed, what it needs */
    #due-crew .cl-t.lk { cursor: default; background: var(--dc-well); border-color: transparent; }
    #due-crew .cl-t.lk .cl-f { filter: grayscale(1); opacity: .38; }
    #due-crew .cl-t.lk b { color: var(--dc-muted); }
    #due-crew .cl-t .cl-q { width: 34px; height: 34px; border-radius: 50%; border: 2px dashed var(--dc-faded);
      display: grid; place-items: center; color: var(--dc-muted); font-weight: 800; font-size: 17px; margin-bottom: 4px; }
    #due-crew .cl-t .cl-bar { width: 70%; margin: 3px 0 1px; }
    #due-crew .cl-t .sv *, #due-crew .cl-nr .sv * { animation: none !important; }
    #due-crew .cl-pills { display: flex; flex-wrap: wrap; gap: 4px; }
    #due-crew .cl-pills .st-pill.on::before { content: none; }
    #due-crew .cl-pills .st-pill.on { background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }
    #due-crew .cl-earn .dc-fig { display: inline-flex; flex: none; }
    /* crew rows (3.8.2): each person's Pip in their colour and look, in the emoji's place; still until pointed at */
    /* Pip's arms and what it holds reach past its slot (sev.SLOT): room beside it so they never touch the name,
       and above it for a hat, so the row is a touch taller than an emoji's */
    #due-crew .dc-rsev { display: inline-block; vertical-align: middle; margin: -3px 8px -6px 2px; line-height: 0; }
    #due-crew a.dc-rsev, #due-crew a.dc-rsevl { text-decoration: none; border: 0; }
    #due-crew tr:not(:hover) .dc-rsev .sv, #due-crew tr:not(:hover) .dc-rsev .sv * { animation: none !important; }
    /* 3.8.22: a plan card's squad line: who showed up, side by side, still until it's pointed at */
    #due-crew .pcrew .pips { display: inline-flex; gap: 4px; vertical-align: middle; margin: 8px 5px 0 0; }  /* a hat clear of the line above */
    #due-crew .pcrew .pips .dc-rsev { margin: 0; }
    #due-crew .pcrew:not(:hover) .dc-rsev .sv, #due-crew .pcrew:not(:hover) .dc-rsev .sv * { animation: none !important; }
    @media (max-width: 380px) { #due-crew .dc-rsev { display: none; } }
"""


def my_look(cfg):
    """3.8.2: what my Pip has on: things I have, as the closet draws them."""
    have = _closet.clean_closet(cfg.get("sev_closet"))
    return [k for k in _closet.clean(cfg.get("sev_look")) if k in have]


def _closet_day(day):
    """'3 Oct', or '3 Oct 2025' when it isn't this year's."""
    try:
        d = _date.fromisoformat(str(day))
    except ValueError:
        return ""
    return f"{d.day} {d:%b}" + ("" if d.year == _date.today().year else f" {d.year}")


def _wear_tile(t, have, look, shown, new):
    """A thing of mine: a button that puts it on, or takes it off. On says
    so (the accent, filled, a tick); one a costume covers says Under."""
    e = _html.escape
    k = t["k"]
    on, under = k in look and k in shown, k in look and k not in shown
    cls = "cl-t" + (" on" if on else " under" if under else "") + (" new" if k in new else "")
    badge = ('<span class="cl-badge">&#10003; On</span>' if on else '<span class="cl-badge u">Under</span>' if under else "")
    badge += '<span class="cl-badge n">New</span>' if k in new and not on else ""
    since = _closet_day(have.get(k))
    tip = e(f'Yours since {since}' if since else t.get("tip") or "")
    fig = f'<span class="cl-f">{_sev.slot(_sev.svg("idle", rest=True, look=[k], label=e(t["name"])), 52)}</span>'
    also = "".join(f'<small>and {PLACE_NAMES[p].lower()}</small>' for p in t.get("also") or ())
    also += f'<small>{e(t["rule"])}</small>'  # what earned it
    state = "on" if on else "under the costume" if under else "not on"
    return (f'<button class="{cls}" title="{tip}" aria-label="{e(t["name"])}, {state}" aria-pressed="{"true" if k in look else "false"}" '
            f'{_st_click("closetwear:" + k)}>{badge}{fig}<b>{e(t["name"])}</b>{also}</button>')


def _earn_tile(t, progress):
    """One still to earn: shown, never worn. What it needs, how far along;
    a secret, only that it is one."""
    e = _html.escape
    if t["group"] == "Secret":
        return ('<div class="cl-t lk" role="group" aria-label="A secret, not yet" title="You&rsquo;ll know it when it happens">'
                '<span class="cl-q" aria-hidden="true">?</span><b>A secret</b></div>')
    fig = f'<span class="cl-f">{_sev.slot(_sev.svg("idle", rest=True, look=[t["k"]], label=e(t["name"])), 52)}</span>'
    when = f'<small class="w">{e(t["when"])}</small>' if t.get("when") else ""
    bar = ""
    got, need = progress.get(t["k"]) or (0, 0)
    if got > 0:
        bar = (f'<span class="cl-bar" aria-hidden="true"><i style="width:{min(100, round(100 * got / need))}%"></i></span>'
               f'<small>{got:,} of {need:,}</small>')
    return (f'<div class="cl-t lk" role="group" aria-label="{e(t["name"])}, not yet" title="{e(t.get("tip") or "")}">'
            f'{fig}<b>{e(t["name"])}</b><small>{e(t["rule"])}</small>{when}{bar}</div>')


def _closet_ons(look):
    """What's on, place by place, each a button that takes it off; a
    costume over them, the rest waiting under it."""
    e = _html.escape
    cos = _closet.costume(look)
    rows = []
    if cos:
        rows.append(f'<div class="cl-o cos"><span>Costume</span><button title="Take it off" '
                    f'{_st_click("closetwear:" + cos)}>{e(_closet.BY[cos]["name"])}</button></div>')
    for p in CLOSET_PLACES:
        k = next((x for x in look if _closet.BY[x]["slot"] != _closet.COSTUME and p in _closet.places(x)), None)
        if k is None:
            what = "<i>&ndash;</i>"
        elif _closet.BY[k]["slot"] != p:  # the earmuffs' scarf
            what = f'<i>with the {e(_closet.BY[k]["name"].split(" and ")[0].lower())}</i>'
        else:
            what = f'<button title="Take it off" {_st_click("closetwear:" + k)}>{e(_closet.BY[k]["name"])}</button>'
        rows.append(f'<div class="cl-o"><span>{PLACE_NAMES[p]}</span>{what}</div>')
    return (f'<div class="cl-ons{" covered" if cos else ""}" aria-label="What your Pip has on">' + "".join(rows) + "</div>")


def _short_day(iso):
    """"14 Oct" from a cheer's ISO time; "" for anything else."""
    try:
        d = _dt.date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    return f"{d.day} {d.strftime('%b')}"


def closet_html(view, cfg):
    """3.8.2: Pip's closet, in place of the board (as Settings is).
    view: {tab, have: {thing: day}, look, near: [(k, got, need, unit)],
    progress: {k: (got, need)}, new: [k], msg, rest}, from the glue
    (closet_flow). On the left your Pip in what it has on, and what's on,
    place by place (each takes it off). Yours: your things by place, one at
    a time in each, the costumes over them; what's on is the accent with a
    tick. To earn: what you're close to, then the rest by how it's earned,
    greyed, never worn before it's earned; secrets a question mark."""
    e = _html.escape
    have = _closet.clean_closet(view.get("have"))
    look = [k for k in _closet.clean(view.get("look")) if k in have]
    shown = _closet.shown(look)
    tab = view.get("tab") if view.get("tab") in CLOSET_TABS else CLOSET_TABS[0]
    new = [k for k in view.get("new") or [] if k in have]
    progress = {k: v for k, v in (view.get("progress") or {}).items() if k in _closet.BY and k not in have}
    fig = _sev.svg("hello" if new else "idle", rest=bool(view.get("rest")), look=look, label="Your Pip")
    colour = (f'<div class="cl-col"><span>Colour <small>Pip and your board</small></span>'
              f'<span class="st-sw" role="group" aria-label="Colour">{_accent_swatches(cfg)}</span></div>')  # 3.9.0 (Sam)
    me = (f'<div class="cl-me"><div class="cl-fig">{fig}</div>{colour}{_closet_ons(look)}'
          f'<div class="cl-msg" aria-live="polite">{str(view.get("msg") or "")}</div>'
          + (f'<a class="st-lk" href="#" {_st_click("closetoff")}>Take it all off</a>' if look else "")
          + '</div>')
    left = len(_closet.THINGS) - len(have)
    counts = (len(have), left)
    pills = "".join(f'<button class="st-pill{" on" if t == tab else ""}" aria-pressed="{"true" if t == tab else "false"}" '
                    f'{_st_click(f"closettab:{i}")}>{e(t)} <small>{counts[i]}</small></button>' for i, t in enumerate(CLOSET_TABS))
    if tab == CLOSET_TABS[0]:
        secs = []
        for p in CLOSET_PLACES + (_closet.COSTUME,):
            mine = [t for t in _closet.THINGS if t["slot"] == p and t["k"] in have]
            if mine:
                body = '<div class="cl-grid">' + "".join(_wear_tile(t, have, look, shown, new) for t in mine) + "</div>"
            else:  # nothing here yet: the next one, and how far along
                todo = [t for t in _closet.THINGS if t["slot"] == p and t["group"] != "Secret"]
                nxt = max(todo, key=lambda t: (progress.get(t["k"], (0, 1))[0] / progress.get(t["k"], (0, 1))[1], -todo.index(t)))
                got = progress.get(nxt["k"], (0, 0))[0]
                body = (f'<div class="cl-next">Next: <b>{e(nxt["name"])}</b>, {e(nxt["rule"][:1].lower() + nxt["rule"][1:])}'
                        f'{f" ({got:,} so far)" if got else ""}</div>')
            secs.append(f'<section class="cl-sec"><h4>{"Costumes" if p == _closet.COSTUME else PLACE_NAMES[p]}'
                        f'{f" <small>{len(mine)}</small>" if mine else ""}</h4>{body}</section>')
        main = "".join(secs)
    else:
        near_html = ""
        if view.get("near"):
            near_html = ('<section class="cl-sec"><h4>Almost there</h4><div class="cl-near">' + "".join(
                f'<div class="cl-nr"><span>{_sev.slot(_sev.svg("idle", rest=True, look=[k], label=e(_closet.BY[k]["name"])), 34)}</span>'
                f'<span><b>{e(_closet.BY[k]["name"])}</b><span class="cl-bar"><i style="width:{min(100, round(100 * got / need))}%"></i></span>'
                f'<small>{got:,} of {need:,} {e(unit)}</small></span></div>'
                for k, got, need, unit in view.get("near")) + "</div></section>")
        secs = []
        for g in _closet.GROUPS:
            todo = [t for t in _closet.THINGS if t["group"] == g and t["k"] not in have]
            if todo:
                secs.append(f'<section class="cl-sec"><h4>{e(g)} <small>{len(todo)} to go</small></h4><div class="cl-grid lk">'
                            + "".join(_earn_tile(t, progress) for t in todo) + "</div></section>")
        main = near_html + ("".join(secs) or f'<div class="cl-next">All {len(_closet.THINGS)} earned.</div>')
    off = "" if cfg.get("sev", True) else '<div class="st-note">Pip is off in Settings, so nobody sees it for now.</div>'
    return (f'<div id="due-crew" class="dc-frame dc-set dc-closet">{_css(cfg)}<style>{SETTINGS_CSS}{SEV_CSS}{CLOSET_CSS}{_sev.CSS}</style>'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span></div>'
            f'<div class="st-bar"><a class="st-back" href="#" {_st_click("closetclose")}>&lsaquo; Board</a><b>Pip&rsquo;s closet</b>'
            f'<span class="cl-n">{len(have)} of {len(_closet.THINGS)}</span></div>'
            f'<div class="cl-wrap">{me}<div class="cl-main"><div class="cl-pills" role="group" aria-label="Show">{pills}</div>'
            f'{main}</div></div>{off}</div>')


WRAPPED_CSS = """
    #due-crew.dc-wr { text-align: left; }
    #due-crew .wr-wrap { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 22px; align-items: start; }
    @media (max-width: 600px) { #due-crew .wr-wrap { grid-template-columns: minmax(0, 1fr); justify-items: center; } }
    #due-crew .wr-phone { position: relative; width: 300px; max-width: 100%; height: 560px; border-radius: 26px; overflow: hidden;
      background: #000; box-shadow: 0 10px 30px rgba(0,0,0,.18); outline: none; }
    #due-crew .wr-phone:focus-visible { box-shadow: 0 0 0 3px var(--dc-accent), 0 10px 30px rgba(0,0,0,.18); }
    #due-crew .wr-bars { position: absolute; top: 10px; left: 12px; right: 12px; display: flex; gap: 4px; z-index: 3; }
    #due-crew .wr-bars i { flex: 1; height: 3px; border-radius: 2px; background: rgba(255,255,255,.3); overflow: hidden; display: block; }
    #due-crew .wr-bars b { display: block; height: 100%; width: 0; background: #fff; }
    #due-crew .wr-phone.lt .wr-bars i { background: rgba(0,0,0,.14); } #due-crew .wr-phone.lt .wr-bars b { background: #222; }
    #due-crew .wr-s { position: absolute; inset: 0; background: var(--bg); color: #fff; padding: 36px 20px 18px; display: none;
      flex-direction: column; gap: 8px; }
    #due-crew .wr-s.on { display: flex; }
    #due-crew .wr-s.lt { color: #222; }
    #due-crew .wr-tap { position: absolute; top: 0; bottom: 0; width: 34%; background: transparent; border: 0; box-shadow: none;
      border-radius: 0; margin: 0; padding: 0; z-index: 2; cursor: pointer; }
    #due-crew .wr-tap.l { left: 0; } #due-crew .wr-tap.r { right: 0; width: 66%; }
    #due-crew .wk { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; opacity: .78; }
    #due-crew .wb { font-size: 40px; font-weight: 800; line-height: 1.04; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
    #due-crew .wb.long { font-size: 32px; }
    #due-crew .wl { font-size: 15px; line-height: 1.35; opacity: .92; }
    #due-crew .wsm { font-size: 13px; line-height: 1.35; opacity: .8; }
    #due-crew .wno { font-size: 13px; opacity: .8; margin-top: auto; }
    #due-crew .wtag { align-self: flex-start; font-size: 10.5px; font-weight: 700; padding: 2px 8px; border-radius: 99px;
      background: rgba(255,255,255,.16); }
    #due-crew .wr-s.lt .wtag { background: rgba(0,0,0,.08); }
    #due-crew .wp { align-self: center; margin-top: auto; line-height: 0; --sv-line: rgba(255,255,255,.18); }
    #due-crew .wp svg.sv { width: 128px; height: 128px; overflow: visible; }
    #due-crew .wp.xl svg.sv { width: 176px; height: 176px; }
    #due-crew .wh { display: grid; grid-template-rows: repeat(7, 1fr); grid-auto-flow: column; grid-auto-columns: 1fr; gap: 1.3px; margin: 6px 0 2px; }
    #due-crew .wh i { display: block; aspect-ratio: 1; border-radius: 1.2px; background: rgba(255,255,255,.1); }
    #due-crew .wh i.x { background: transparent; } #due-crew .wh i.f { background: rgba(255,255,255,.05); }
    #due-crew .wh i.l1 { background: color-mix(in srgb, var(--wa) 45%, transparent); } #due-crew .wh i.l2 { background: color-mix(in srgb, var(--wa) 65%, transparent); }
    #due-crew .wh i.l3 { background: color-mix(in srgb, var(--wa) 85%, transparent); } #due-crew .wh i.l4 { background: var(--wa); }
    #due-crew .wh i.r { background: #e0a458; }
    #due-crew .wg { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px 10px; margin-top: 8px; font-size: 12.5px; opacity: .95; }
    #due-crew .wg b { display: block; font-size: 28px; line-height: 1.05; font-weight: 800; letter-spacing: -.02em; font-variant-numeric: tabular-nums; }
    #due-crew .wq { background: #fbf8f1; color: #2b2d29; border-radius: 12px; padding: 18px 14px; font-size: 16px; font-weight: 600;
      line-height: 1.35; margin: 6px 0 4px; box-shadow: 0 4px 14px rgba(0,0,0,.25); overflow-wrap: anywhere; }
    #due-crew .wt { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); justify-items: center; gap: 2px; margin-top: 6px; }
    #due-crew .wt .sv { width: 54px; height: 54px; overflow: visible; }
    #due-crew .wt .sv, #due-crew .wt .sv * { animation: none !important; }
    #due-crew .wpic { background: #fff; color: #222; border-radius: 16px; padding: 16px 12px 6px; display: grid; gap: 8px;
      box-shadow: 0 6px 18px rgba(0,0,0,.08); margin-top: 6px; }
    #due-crew .wpic .wk { text-align: center; opacity: .7; }
    #due-crew .wpic .wg { grid-template-columns: repeat(3, minmax(0, 1fr)); text-align: center; color: #6b6f67; margin: 0; }
    #due-crew .wpic .wg b { color: #222; font-size: 24px; }
    #due-crew .wpic .wp { margin: 0; --sv-line: #e2e2da; } #due-crew .wpic .wp svg.sv { width: 92px; height: 92px; }
    #due-crew .wpic .dc-mark { height: 14px; width: auto; justify-self: center; }
    #due-crew .wgo { position: relative; z-index: 4; align-self: center; margin-top: 10px; font: inherit; font-size: 13px; font-weight: 700;
      padding: 7px 14px; border-radius: 9px; border: 0; background: #2e7d32; color: #fff; cursor: pointer; }
    #due-crew .wr-side { display: grid; gap: 10px; align-content: start; font-size: 13px; max-width: 360px; }
    #due-crew .wr-side h3 { margin: 0; font-family: inherit; font-size: 17px; font-weight: 700; letter-spacing: normal; }
    #due-crew .wr-side p { margin: 0; color: var(--dc-muted); line-height: 1.45; }
    #due-crew .wr-years { display: flex; flex-wrap: wrap; gap: 6px; }
    #due-crew .wr-years a { padding: 3px 10px; border-radius: 99px; border: 1px solid var(--dc-line); color: var(--dc-ink); text-decoration: none; }
    #due-crew .wr-years a.on { background: var(--dc-accent); color: var(--dc-accent-ink); border-color: transparent; }
    #due-crew .wr-list { margin: 16px 0 0; padding: 12px 14px 12px 34px; border: 1px solid var(--dc-line); border-radius: 12px;
      display: grid; gap: 6px; font-size: 13px; line-height: 1.45; max-width: 640px; }
    #due-crew .wr-list[hidden] { display: none; }
    #due-crew .wr-btn { font: inherit; font-size: 12.5px; font-weight: 700; padding: 5px 12px; border-radius: 8px; border: 1px solid var(--dc-line);
      background: var(--dc-bg); color: var(--dc-ink); cursor: pointer; margin: 0; box-shadow: none; justify-self: start; }
"""


def _wr_heat(cells, accent, run=None):
    lo, hi = (run or ("", ""))
    out = []
    for c in cells:
        if c is None:
            out.append('<i class="x"></i>')
        elif c == "":
            out.append('<i class="f"></i>')
        else:
            day, lv = c
            out.append('<i class="r"></i>' if run and lo <= day <= hi else f'<i class="l{int(lv)}"></i>' if lv else "<i></i>")
    return f'<div class="wh" style="--wa:{accent}" aria-hidden="true">' + "".join(out) + "</div>"


def _wr_slide(i, total, sl, view, cfg):
    e = _html.escape
    look = view.get("look") or []
    kind = sl.get("kind")
    lt = kind == "picture"
    accent = accent_pair(cfg.get("accent", DEFAULT_ACCENT))
    pip_a = accent[0] if lt else accent[1]

    def pip(pose, size_cls="", lk=None):
        if not cfg.get("sev", True):
            return ""  # Pip off: the story without it
        return (f'<span class="wp {size_cls}" style="--sv-a:{pip_a}">'
                f'{_sev.svg(pose, look=look if lk is None else lk, label="Your Pip")}</span>')
    parts = []
    if kind != "picture":
        parts.append(f'<div class="wk">{e(sl.get("kicker") or "")}</div>')
    if sl.get("tag"):
        parts.append(f'<span class="wtag">{e(sl["tag"])}</span>')
    if sl.get("lead"):
        parts.append(f'<div class="wl">{e(sl["lead"])}</div>')
    if sl.get("big"):
        parts.append(f'<div class="wb{" long" if len(str(sl["big"])) > 12 else ""}">{e(sl["big"])}</div>')
    if sl.get("line") and kind != "crew":
        parts.append(f'<div class="wl">{e(sl["line"])}</div>')
    if kind == "days":
        parts.append(_wr_heat(view.get("heat") or [], accent[1]))
    if kind == "run":
        parts.append(_wr_heat(view.get("heat") or [], accent[1], sl.get("run")))
    if kind == "turned":
        parts.insert(2, f'<div class="wq">{e(sl.get("front") or "")}</div>')
    if kind == "things":
        parts.append('<div class="wt">' + "".join(
            _sev.svg("idle", rest=True, look=[k], label=e(_closet.BY[k]["name"])).replace('<svg ', f'<svg style="--sv-a:{pip_a}" ', 1)
            for k in sl.get("things") or [] if k in _closet.BY) + "</div>")
    if sl.get("grid") and kind != "picture":
        parts.append('<div class="wg">' + "".join(f"<div><b>{e(a)}</b>{e(b)}</div>" for a, b in sl["grid"]) + "</div>")
    if kind == "crew" and sl.get("line"):
        parts.append(f'<div class="wl">{e(sl["line"])}</div>')
    if sl.get("small") and kind != "picture":
        parts.append(f'<div class="wsm">{e(sl["small"])}</div>')
    if kind == "picture":
        nums = "".join(f"<div><b>{e(a)}</b>{e(b)}</div>" for a, b in sl.get("grid") or [])
        parts.append(f'<div class="wpic">{board_mark()}<div class="wk">{e(sl.get("kicker") or "")}</div>'
                     f'<div class="wg">{nums}</div>{pip("hop")}</div>'
                     f'<button class="wgo" onclick="{_pycmd("wrappedpic:" + str(int(view.get("year") or 0)))}">Make the picture</button>'
                     + (f'<div class="wno">{e(sl["small"])}</div>' if sl.get("small") else ""))
    elif sl.get("pose") and kind not in ("turned", "things", "days"):
        parts.append(pip(sl["pose"], "xl" if kind == "cover" else ""))
    if sl.get("note"):
        parts.append(f'<div class="wno">{e(sl["note"])}</div>')
    return (f'<section class="wr-s{" on" if i == 0 else ""}{" lt" if lt else ""}" style="--bg:{e(sl.get("bg") or "#12301a")}" '
            f'aria-roledescription="slide" aria-label="{i + 1} of {total}">{"".join(parts)}</section>')


def wrapped_html(view, cfg):
    """3.9.0, your Wrapped (Sam's pick, round three), in place of the board
    (as the closet is): the year's story on a phone-shaped card, slide by
    slide (wrapped.slides), Pip in your look; tap or the arrow keys move it,
    and it moves on by itself (wrapped_js; not with Reduce motion). Beside
    it the years Anki's history has, All on one page (every slide as
    text), and the way back. view: {year, years, slides, heat, look}."""
    from . import wrapped as _w
    e = _html.escape
    sl = [s for s in view.get("slides") or [] if cfg.get("sev", True) or s.get("kind") != "things"]
    year = int(view.get("year") or 0)
    if sl:
        phone = (f'<div class="wr-phone" tabindex="0" aria-label="Your {year}, a story: the arrow keys or the sides move it">'
                 f'<div class="wr-bars">{"".join("<i><b></b></i>" for _ in sl)}</div>'
                 + "".join(_wr_slide(i, len(sl), s, view, cfg) for i, s in enumerate(sl))
                 + '<button class="wr-tap l" aria-label="Back"></button><button class="wr-tap r" aria-label="Next"></button></div>')
        lines = "".join(f"<li>{e(_w.words(s))}</li>" for s in sl)
        listing = f'<ol class="wr-list" id="wr-list" hidden>{lines}</ol>'
    else:
        phone = f'<div class="st-note">No reviews in {year} yet.</div>'
        listing = ""
    years = "".join(f'<a href="#" class="{"on" if y == year else ""}" onclick="{_pycmd("wrappedyear:" + str(int(y)))}">{int(y)}</a>'
                    for y in view.get("years") or [] if str(y).isdigit())
    side = (f'<div class="wr-side"><h3>Your {year}</h3>'
            '<p>Made on this computer from your own reviews. Nothing is sent, and only you see it unless you make the picture.</p>'
            + (f'<div class="wr-years" aria-label="Another year">{years}</div>' if years else "")
            + ('<button class="wr-btn" onclick="var l=document.getElementById(\'wr-list\');if(l){l.hidden=!l.hidden;}return false;">'
               'All on one page</button>' if sl else "")
            + (f'<a class="st-lk" href="#" {_st_click("wrappedcard")}>'
               f'{"Leave out the card you turned around" if view.get("card_on") else "Show the card you turned around"}</a>'
               if view.get("card") else "")
            + '</div>')
    sheet = f"{SEV_CSS}{WRAPPED_CSS}{_sev.CSS}" if cfg.get("sev", True) else WRAPPED_CSS
    return (f'<div id="due-crew" class="dc-frame dc-set dc-wr">{_css(cfg)}<style>{SETTINGS_CSS}{sheet}</style>'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span></div>'
            f'<div class="st-bar"><a class="st-back" href="#" {_st_click("wrappedclose")}>&lsaquo; Board</a><b>Your {year}</b></div>'
            f'<div class="wr-wrap">{phone}{side}</div>{listing}</div>')


def wrapped_js():
    """3.9.0: Wrapped's player, said to the page after the board draws it:
    the sides and the arrow keys move it, it moves on by itself and waits
    while the pointer is on it, each slide's Pip plays its moment as it
    comes; with Reduce motion it never moves on by itself. Once a card."""
    return """
    (function() {
        var ph = document.querySelector('#due-crew .wr-phone');
        if (!ph || ph.getAttribute('data-on')) { return; }
        ph.setAttribute('data-on', '1');
        var sl = [].slice.call(ph.querySelectorAll('.wr-s')), bars = [].slice.call(ph.querySelectorAll('.wr-bars b'));
        var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        var st = { i: 0, t: 0, held: false, last: 0 }, PER = 6500;
        function show(i) {
            st.i = Math.max(0, Math.min(sl.length - 1, i)); st.t = 0;
            sl.forEach(function(s, j) { s.classList.toggle('on', j === st.i); });
            bars.forEach(function(b, j) { b.style.width = j < st.i ? '100%' : (j === st.i && still ? '100%' : '0'); });
            ph.classList.toggle('lt', sl[st.i].classList.contains('lt'));
            if (!still) {
                sl[st.i].querySelectorAll('.wp svg.sv').forEach(function(v) { var c = v.cloneNode(true); v.parentNode.replaceChild(c, v); });
            }
        }
        function tick(now) {
            if (!document.body.contains(ph)) { return; }
            var dt = st.last ? now - st.last : 0; st.last = now;
            if (!st.held && !document.hidden && st.i < sl.length - 1) {
                st.t += dt;
                bars[st.i].style.width = Math.min(100, st.t / PER * 100) + '%';
                if (st.t >= PER) { show(st.i + 1); }
            } else if (st.i === sl.length - 1) { bars[st.i].style.width = '100%'; }
            requestAnimationFrame(tick);
        }
        ph.querySelector('.wr-tap.l').addEventListener('click', function(ev) { ev.preventDefault(); show(st.i - 1); });
        ph.querySelector('.wr-tap.r').addEventListener('click', function(ev) { ev.preventDefault(); show(st.i + 1); });
        ph.addEventListener('keydown', function(ev) {
            if (ev.key === 'ArrowRight' || ev.key === ' ') { show(st.i + 1); ev.preventDefault(); }
            else if (ev.key === 'ArrowLeft') { show(st.i - 1); ev.preventDefault(); }
        });
        ph.addEventListener('mouseenter', function() { st.held = true; });
        ph.addEventListener('mouseleave', function() { st.held = false; });
        show(0);
        try { ph.focus({ preventScroll: true }); } catch (e) {}
        if (!still) { requestAnimationFrame(tick); }
    })();
    """


def wrapped_line(year, so_far, look, pip=True):
    """3.9.0: the board's line, 1 December to 15 January: your year is
    ready. Open plays it in the board's place; the x is for the year, on
    every computer (the account's wrapped_seen). Pip off: a gift."""
    fig = (f'<span class="dc-fig">{_sev.slot(_sev.svg("hop", rest=True, look=look, label="Your Pip"), 40)}</span>'
           if pip else "<span>&#127873;</span>")
    return (f'<div class="dc-wrap wr-line">{fig}'
            f'<span><b>Your {int(year)}{" so far" if so_far else ""}</b> is ready: your year in Anki{", as Pip saw it" if pip else ""}.</span>'
            f'<a class="wc" href="#" onclick="{_pycmd("wrappedopen:" + str(int(year)))}">Open &#9654;</a>'
            f'<a class="wx" href="#" title="Not this year" onclick="{_pycmd("wrappedx:" + str(int(year)))}">&times;</a></div>')


def closet_line(news, look, first=False):
    """3.8.2: the board's line when something new is in the closet: Pip
    in it, its name and what earned it, Wear it (or Be one, a costume) and
    the closet. The day the closet comes it's one line for all of them."""
    e = _html.escape
    news = [k for k in news if k in _closet.BY]
    if not news:
        return ""
    k = news[-1]
    t = _closet.BY[k]
    fig = _sev.svg("hop", rest=True, look=_closet.wear(look, k) if k not in look else look, label="Your Pip")
    if first and len(news) > 1:
        words = f'<b>Pip&rsquo;s closet is open.</b> Your days so far earned it {len(news)} things.'
        acts = f'<a class="wc" href="#" onclick="{_pycmd("closet")}">See them</a>'
    elif len(news) > 1:
        names = ", ".join(e(_closet.BY[x]["name"]) for x in news[:-1]) + " and " + e(t["name"])
        words = f'<b>New for your Pip:</b> {names}.'
        acts = f'<a class="wc" href="#" onclick="{_pycmd("closet")}">See them</a>'
    else:
        words = f'<b>New for your Pip: {e(t["name"])}.</b> {e(t["rule"])}.'
        acts = (f'<a class="wc" href="#" onclick="{_pycmd("closetwear:" + k)}">{"Be one" if t["slot"] == _closet.COSTUME else "Wear it"}</a>'
                f'<a class="wc" href="#" onclick="{_pycmd("closet")}">Closet</a>')
    return (f'<div class="dc-wrap cl-earn"><span class="dc-fig">{_sev.slot(fig, 40)}</span><span>{words}</span>{acts}'
            f'<a class="wx" href="#" title="Later" onclick="{_pycmd("closetnew")}">&times;</a></div>')


HW_PIP = 34  # 3.8.22: a Halloween thing on the week's line
HW_BAT = ('<svg class="hwbat" style="--d:{d}s" viewBox="0 0 40 20" aria-hidden="true"><g class="w">'
          '<path d="M20 9 C17 4 12 3 6 5 C9 7 9 10 7 12 C11 11 14 12 16 15 C17 13 18 12 20 12 C22 12 23 13 24 15 '
          'C26 12 29 11 33 12 C31 10 31 7 34 5 C28 3 23 4 20 9 Z"/></g>'
          '<circle class="e" cx="18.6" cy="9.5" r=".9"/><circle class="e" cx="21.4" cy="9.5" r=".9"/></svg>')
HW_WEB = ('<svg class="hwweb" viewBox="0 0 60 60" aria-hidden="true"><path d="M60 0 L0 0 M60 0 L60 60 M60 0 L8 30 M60 0 '
          'L30 52 M60 0 L2 14 M60 0 L46 58 M46 0 Q48 6 60 14 M32 0 Q36 12 60 28 M18 0 Q24 18 60 42"/></svg>')
HW_CSS = """
    #due-crew .dc-hw { position: relative; overflow: hidden; display: flex; flex-wrap: wrap; align-items: center; gap: 2px 8px;
      text-align: left; margin: 0 0 8px; padding: 3px 30px 3px 10px; border-radius: 10px; background: var(--dc-well); font-size: 12.5px; }
    #due-crew .dc-hw .hwl { color: var(--dc-hours); font-weight: 700; text-decoration: none; }
    #due-crew .dc-hw .hwd, #due-crew .dc-hw .hwn { color: var(--dc-muted); }
    #due-crew .dc-hw .hws { color: var(--dc-hours); font-weight: 600; }
    #due-crew .dc-hw .hwt { display: inline-flex; align-items: flex-end; gap: 3px; padding-top: 6px; }
    #due-crew .dc-hw .hwk { display: inline-flex; line-height: 0; }
    #due-crew .dc-hw .hwk.off { opacity: .32; filter: grayscale(1); }
    #due-crew .dc-hw .hwk .sv, #due-crew .dc-hw .hwk .sv * { animation: none !important; }
    #due-crew .dc-hw .wx { position: absolute; right: 9px; top: 50%; transform: translateY(-50%); z-index: 2;
      color: var(--dc-muted); text-decoration: none; font-size: 16px; line-height: 1; }
    #due-crew .dc-hw .wx:hover { color: var(--dc-ink); }
    #due-crew .dc-hw .hwweb { position: absolute; right: -1px; top: -1px; width: 30px; height: 30px; pointer-events: none;
      fill: none; stroke: var(--dc-muted); stroke-width: 1; opacity: .5; }
    #due-crew .dc-hw .hwbat { position: absolute; left: -30px; top: 3px; width: 26px; height: 13px; opacity: 0; pointer-events: none; z-index: 3; }
    #due-crew .dc-hw .hwbat path { fill: var(--dc-ink); opacity: .85; }
    #due-crew .dc-hw .hwbat .e { fill: var(--dc-hours); }
    @media (prefers-reduced-motion: no-preference) {
      /* three bats across the line, once a day: past the logo's line, never over it (Sam) */
      #due-crew .dc-hw .hwbat { animation: dc-hwbat 4.2s linear calc(var(--d) - var(--ago, 0s)) both; }
      #due-crew .dc-hw .hwbat .w { transform-box: fill-box; transform-origin: 50% 50%; animation: dc-hwflap .22s ease-in-out infinite alternate; }
      @keyframes dc-hwbat { 0% { opacity: 1; left: -30px; transform: translateY(2px); } 25% { transform: translateY(-2px); }
        50% { transform: translateY(3px); } 75% { transform: translateY(-1px); } 100% { opacity: 1; left: calc(100% + 10px); transform: translateY(1px); } }
      @keyframes dc-hwflap { from { transform: scaleY(1); } to { transform: scaleY(.45); } }
    }
"""


def halloween_html(hw, cfg):
    """3.8.22, Halloween week (24 to 31 Oct; Sam's pick, round three): a line
    under the board's head with this week's days, the five things in
    order (mine in colour), the next and when; three bats across it once a
    day (hw["bats"]: how long they've been out, as Pip by the logo; None
    after); and when every Pip on the crew's rows has a Halloween thing on
    (hw["spooky"]: how many), a cobweb in its corner and a line about it.
    Nothing with Pip off. hw: closet.halloween's, from closet_flow."""
    if not hw or not cfg.get("sev", True):
        return ""
    e = _html.escape
    days = int(hw.get("days") or 0)
    said = "a thing a day for five days" if not days else f'{days} day{"" if days == 1 else "s"} so far'
    things = "".join(
        f'<span class="hwk {"on" if got else "off"}" title="{e(_closet.BY[k]["name"])}: '
        f'{"a day" if n == 1 else str(n) + " days"} of Halloween week">'
        f'{_sev.slot(_sev.svg("idle", rest=True, look=[k], label=_closet.BY[k]["name"]), HW_PIP)}</span>'
        for k, n, got in hw.get("things") or [] if k in _closet.BY)
    nxt = hw.get("next")
    if nxt:
        name = e(_closet.BY[nxt[0]]["name"].lower())
        more = int(nxt[1])
        when = ((f"tomorrow: the {name}" if hw.get("today") else f"study today for the {name}") if more == 1
                else f"the {name} in {more} more days")
    elif all(got for _k, _n, got in hw.get("things") or []):
        when = "all five: Pip&rsquo;s ready"
    else:
        when = "the rest next year"
    n = int(hw.get("spooky") or 0)
    spooky = f'<span class="hws">A spooky crew: all {n} of you dressed up.</span>' if n else ""
    ago = hw.get("bats")
    bats = "".join(HW_BAT.format(d=d) for d in (0, .5, 1.1)) if ago is not None else ""
    return (f'<div class="dc-hw" style="--ago:{float(ago or 0):.2f}s">{bats}{HW_WEB if n else ""}'
            f'<a class="hwl" href="#" title="Pip&rsquo;s closet" onclick="{_pycmd("closet")}">Halloween week</a>'
            f'<span class="hwd">{said}</span><span class="hwt">{things}</span><span class="hwn">{when}</span>{spooky}'
            f'<a class="wx" href="#" title="Hide until next year" onclick="{_pycmd("closethw")}">&times;</a></div>')


def row_sev(row, cfg, size=None, nth=None):
    """3.8.2: someone's Pip on a crew row, in the emoji's place: their colour
    and their look (mine: this computer's), still until the row is pointed
    at. My own opens the closet. None with Pip off. nth (3.9.0): its place
    among Pips that move together (a bingo square's stamps, a plan card's
    squad line), so each blinks on its own clock (sev.blink), as a room's
    seats do."""
    if not cfg.get("sev", True):
        return None
    light, dark = accent_pair(cfg.get("accent") if row.get("you") else row.get("accent"))
    look = my_look(cfg) if row.get("you") else row.get("look")
    label = "Your Pip" if row.get("you") else _html.escape(f'{row.get("name") or "?"}’s Pip', quote=True)
    fig = _sev.slot(_sev.svg("idle", rest=True, look=look, label=label), size or _sev.ROW_SIZE)  # the site's rows too (sev.site_kit)
    style = f'--rs-l:{light};--rs-d:{dark}' + (f';{_sev.blink_css(nth)}' if nth is not None else "")
    if row.get("you"):
        return (f'<a class="dc-rsev" href="#" title="Pip&rsquo;s closet" style="{style}" '
                f'onclick="{_pycmd("closet")}">{fig}</a>')
    return f'<span class="dc-rsev" style="{style}">{fig}</span>'


PCREW_PIP = 26  # 3.8.22: a Pip on a plan card's squad line, its slot a line of its small text
SETTINGS_PIP = 44  # 3.8.22: mine in Settings › You, beside my name and status


def squad_pip(uid, name, you, people, cfg, size=None, nth=None):
    """3.8.21: someone's Pip on the Squads tab, in the emoji's place (Sam: "the
    squads page still has the old emojis"): mine as on my row; a crewmate's
    in their colour and look (a mutual friend's, which only the crew brings);
    anyone else plain, in the default colour, since all a squadmate shares is
    a name and an emoji. people: {uid: crew entry}. None with Pip off."""
    p = (people or {}).get(uid) or {}
    return row_sev({"you": bool(you), "name": name, "accent": p.get("accent"), "look": p.get("look")}, cfg, size, nth)


STAMP_PIP = 40  # 3.8.22: who stamped a bingo square, bigger than the emoji was (Sam: "make the bingo stamps bigger")
BINGO_PIP_CSS = """
    #due-crew .bg-sq.stamped { padding-bottom: 34px; }
    #due-crew .bg-sq .st.sp { width: auto; height: auto; background: none; box-shadow: none; border-radius: 0; bottom: 4px; }
    #due-crew .bg-sq .st.sp .dc-rsev { display: inline-block; line-height: 0; margin: 0; }
    #due-crew .bg-sq:not(:hover) .dc-rsev .sv, #due-crew .bg-sq:not(:hover) .dc-rsev .sv * { animation: none !important; }
"""


def stamp_pip(uid, name, people, cfg, nth=None):
    """3.8.22: who stamped a bingo square, as their Pip: mine and a
    crewmate's in colour and look, a squadmate's plain (all they share is a
    name and an emoji). The square is a button, so never a link: mine
    doesn't open the closet from here."""
    p = (people or {}).get(uid) or {}
    you = bool(p.get("you"))
    return row_sev({"name": name, "accent": cfg.get("accent") if you else p.get("accent"),
                    "look": my_look(cfg) if you else p.get("look")}, cfg, STAMP_PIP, nth) or ""


def card_sev(row, cfg, size=44):
    """3.8.2: someone's Pip on their profile card, in the emoji's place, as
    on their row: their colour, their look (mine: this computer's), waving
    once as the card opens. The card sits outside the board, so the colours
    come with it. None with Pip off."""
    if not cfg.get("sev", True):
        return None
    light, dark = accent_pair(cfg.get("accent") if row.get("you") else row.get("accent"))
    look = my_look(cfg) if row.get("you") else row.get("look")
    label = "Your Pip" if row.get("you") else _html.escape(f'{row.get("name") or "?"}’s Pip', quote=True)

    def colours(theme, a):
        p = palette(theme, cfg.get("accent", DEFAULT_ACCENT))
        return f"--sv-a: {a}; --sv-line: {p['line']}; --sv-amb: {p['hours']}; --sv-mut: {p['muted']};"
    css = _by_theme(cfg, "#dc-profile .dc-psev", colours("light", light), colours("dark", dark))
    fig = _sev.slot(_sev.svg("hello", look=look, label=label), size)
    return (f'<style>{css}\n#dc-profile .dc-psev {{ display: inline-block; flex: none; line-height: 0; margin: 0 2px; }}</style>'
            f'<span class="dc-psev">{fig}</span>')


def room_html(room):
    """2.12: the Decks screen's study rooms, from room_model.board_view.
    Every string in it may carry a friend's name: escaped here."""
    e = _html.escape
    out = ""
    fd = room.get("fifteen_done")
    if fd:
        # 3.8.1: a session of fifteens, ended: Pip stacks a square for each
        n = int(fd.get("n") or 0)
        mins = int(fd.get("minutes") or 0)
        cards = fd.get("cards")
        what = f'{n} fifteen{"" if n == 1 else "s"} &middot; {e(room_model.duration_text(mins))}'
        if isinstance(cards, int):
            what += f' &middot; {cards:,} card{"" if cards == 1 else "s"}'
        if fd.get("sev"):
            up, down = _sev.stack_reach(n, 44)  # room for the squares drawn and the shadow, no more
            icon = f'<span class="dc-fig" style="padding:{up}px 0 {down}px">{_sev.slot(fd["sev"], 44)}</span>'
        else:
            icon = "<span>&#10003;</span>"
        out += (f'<div class="dc-wrap dc-sess">{icon}<span><b>Your session:</b> {what}.</span>'
                f'<a class="wx" href="#" title="Done" style="margin-left:auto" onclick="{_pycmd("room15x")}">&times;</a></div>')
    done = room.get("done")
    if done:
        out += (f'<div class="dc-wrap"><span>&#10003;</span><span><b>Room done:</b> '
                f'{int(done.get("rounds", 0))} rounds, {e(room_model.duration_text(done.get("minutes", 0)))} together'
                f'{" with " + e(str(done["with"])) if done.get("with") else ""}.</span>'
                f'<a class="wc" href="#" onclick="{_pycmd("roomshare")}">Share</a>'
                f'<a class="wc" href="#" style="margin-left:6px" onclick="{_pycmd("roomcheer")}">Cheer the room</a>'
                f'<a class="wx" href="#" title="Done" onclick="{_pycmd("roomdonex")}">&times;</a></div>')
    for inv in (room.get("invites") or [])[:2]:
        key = str(inv.get("key", ""))
        out += (f'<div class="dc-wrap"><span class="rdot"></span><span><b>{e(str(inv.get("title", "")))}</b>'
                f' &middot; {e(str(inv.get("sub", "")))}'
                f'{" &middot; " + e(str(inv["line"])) + (" is" if " and " not in str(inv["line"]) else " are") + " in" if inv.get("line") else ""}'
                f'</span><a class="wc" href="#" onclick="{_pycmd("roomjoin:" + key)}">Join</a>'
                f'<a class="wx" href="#" title="Not now" onclick="{_pycmd("roomx:" + key)}">&times;</a></div>')
    mine = room.get("mine")
    if mine and mine.get("fifteen"):
        return out + _fifteen_lobby(mine)
    if mine:
        bars = ""
        for i, f in enumerate(mine.get("bars") or []):
            if i:
                bars += f'<em style="flex:{int(mine.get("brk_min", 5)) or 1}"></em>'
            bars += f'<i style="flex:{int(mine.get("round", 25))}"><u style="width:{float(f) * 100:.1f}%"></u></i>'
        seats = [s for s in (mine.get("seats") or []) if isinstance(s, dict)][:6]
        faces = ("".join(_seat_html(s) for s in seats) if seats  # 3.8.1: Pip on, each member is their Pip
                 else "".join(f"<i>{e(str(x))}</i>" for x in (mine.get("initials") or [])[:6]))
        out += (f'<div class="dc-room"><span class="rg{" brk" if mine.get("brk") else ""}" style="--p:{float(mine.get("frac", 0)):.3f}">'
                f'<b>{e(str(mine.get("label", "")))}</b></span>'
                f'<span class="rt"><b>{e(str(mine.get("title", "")))}</b><small>{e(str(mine.get("sub", "")))}</small>'
                f'<span class="rb">{bars}</span></span>'
                f'<span class="rw"><span class="fc{" sv-seats" if seats else ""}" title="{e(str(mine.get("line", "")))}">{faces}</span>'
                f'<a class="go" href="#" onclick="{_pycmd("roomstudy")}">Study</a>'
                f'<a class="lv" href="#" onclick="{_pycmd("roomleave")}">Leave</a></span></div>')
    return out


_HEX = _re.compile(r"#[0-9a-fA-F]{6}")


def _seat_html(s):
    """3.8.1: a crew room's member as their Pip (room_model.seats), a 24 px
    seat like the initials' circles: their accent by day and by night (only
    a colour reaches the style; anything else, the default's), blinking at
    its own moment and doing its own small thing (a SEAT_MOVES one), their
    name its label (escaped)."""
    dflt, a = accent_pair(None), s.get("a")
    pair = a if isinstance(a, (list, tuple)) and len(a) == 2 else dflt
    light, dark = (x if isinstance(x, str) and _HEX.fullmatch(x) else d for x, d in zip(pair, dflt))
    try:
        delay = max(-60.0, min(0.0, float(s.get("d") or 0)))
    except (TypeError, ValueError):
        delay = 0.0
    try:  # 3.9.0: its own blink cycle (sev.blink)
        cycle = max(2.0, min(10.0, float(s.get("b") or _sev.BLINK)))
    except (TypeError, ValueError):
        cycle = _sev.BLINK
    name = _html.escape(str(s.get("n") or ""), quote=True)
    turn = s.get("m") if s.get("m") in _sev.SEAT_MOVES else "idle"  # its own small thing now and then
    look = s.get("l") if isinstance(s.get("l"), list) else None  # 3.8.2: what they have on (closet.clean rules it)
    return (f'<span class="seat" title="{name}" style="--sa-l:{light};--sa-d:{dark};--sv-b:{cycle:.2f}s;--sv-d:{delay:.2f}s">'
            f'{_sev.slot(_sev.svg("idle", turn, label=name, look=look), 40)}</span>')


def _fifteen_lobby(m):
    """3.8.1: my fifteen on the Decks screen: its ring with Pip beside it,
    and what can be said there (the question too, as the review screen asks it)."""
    e = _html.escape
    st = m.get("state")
    sub = str(m.get("sub", ""))
    if st == "ask" and isinstance(m.get("cards"), int):
        sub = f'{m["cards"]:,} card{"" if m["cards"] == 1 else "s"}. ' + sub
    go = lambda cmd, text, cls="go": f'<a class="{cls}" href="#" onclick="{_pycmd(cmd)}">{text}</a>'  # noqa: E731
    if st == "ask":
        acts = ("" if m.get("cap") else go("room15five", "Take five, then another") + go("room15now", "Another now", "lv"))
        acts += go("room15stop", "Stop here", "go" if m.get("cap") else "lv")
    elif st == "break":
        acts = go("room15now", "Start now") + go("room15stop", "Stop here", "lv")
    else:
        acts = go("duestudy", "Study") + go("room15stop", "Stop here", "lv")
    sv = _sev.slot(m["sev"], 46) if m.get("sev") else ""
    return (f'<div class="dc-room dc-fif"><span class="rgw">{sv}<span class="rg{" brk" if m.get("brk") else ""}" '
            f'style="--p:{float(m.get("frac", 0)):.3f}"><b>{e(str(m.get("label", "")))}</b></span></span>'
            f'<span class="rt"><b>{e(str(m.get("title", "")))}</b><small>{e(sub)}</small></span>'
            f'<span class="rw">{acts}</span></div>')


# 3.8.1: Pip on the board wears the board's colours; its size is its body's
SEV_CSS = """
    #due-crew { --sv-a: var(--dc-accent); --sv-line: var(--dc-line); --sv-amb: var(--dc-hours); --sv-mut: var(--dc-muted); }
    /* its feet on the logo's line, a little shorter than the wordmark is tall */
    #due-crew .dc-sev { display: inline-block; margin-left: 8px; vertical-align: middle; line-height: normal;
      position: relative; top: -1px; }
    /* by the logo it's a moment: out for a few seconds, then gone (still, it just goes) */
    #due-crew .dc-sev.once { animation: dc-sev-go 0s linear calc(5s - var(--ago, 0s)) forwards; }
    @keyframes dc-sev-go { to { visibility: hidden; } }
    @media (prefers-reduced-motion: no-preference) {
      #due-crew .dc-sev.once { transform-origin: 50% 100%;
        animation: dc-sev-pop 5s linear calc(0s - var(--ago, 0s)) forwards; }
      @keyframes dc-sev-pop { 0% { transform: scale(0); } 7% { transform: scale(1.12); } 11%, 90% { transform: scale(1); }
        100% { transform: scale(0); visibility: hidden; } }
    }
    /* a crew room's members as their Pips: side by side, not overlapping as the circles do */
    #due-crew .dc-room .fc.sv-seats { gap: 3px; align-items: center; }
    #due-crew .dc-room .fc .seat { display: inline-flex; }
    #due-crew .dc-fif .rgw { display: inline-flex; align-items: center; gap: 8px; }
    #due-crew .dc-fif .rt { text-align: left; }
    /* the session's line: Pip and its stack, the box's own padding around them (stack_reach) */
    #due-crew .dc-wrap .dc-fig { display: inline-flex; flex: none; }
    /* signed out: Pip waves beside the words, until you start */
    #due-crew .dc-card .dc-so { display: inline-flex; align-items: center; gap: 8px; text-align: left; max-width: 100%; }
    #due-crew .dc-card .dc-hi { flex: none; line-height: 0; }
    #due-crew .dc-sess { text-align: left; }
    #due-crew .dc-fif .rw { flex-wrap: wrap; justify-content: flex-end; }
    #due-crew .du-nudge { display: grid; grid-template-columns: 34px minmax(0, 1fr) auto; gap: 9px; align-items: center;
      font-size: 12.5px; padding: 6px 2px 8px; text-align: left; }
    #due-crew .du-nudge .nz { position: relative; width: 34px; height: 28px; overflow: hidden; }
    #due-crew .du-nudge .nz svg { position: absolute; left: -7px; top: -19px; width: 48px; height: 48px; }
    #due-crew .du-nudge .du-go { margin: 0; }
    #due-crew .du-nudge .x { color: var(--dc-muted); font-weight: 400; margin-left: 10px; text-decoration: none; }
"""


def _card(cfg, title, body_html, sheet=""):
    head = board_mark() if title == "Due Crew" else f"<b>{title}</b>"
    return (f'<div id="due-crew">{_css(cfg)}{sheet}<div class="dc-card">'
            f'{head}<span>{body_html}</span></div></div>')


def signed_out_card(cfg, expired=False, gone=False, sev=None):
    """gone (Q4): the account was deleted after 12 months without activity.
    sev (3.8.1, Sam's pick): Pip's markup, waving beside the words until
    you start (rooms.signed_out_sev), or None."""
    if gone:
        return _card(cfg, "Welcome back",
                     f'Your Due Crew account was deleted after 12 months without activity, '
                     f'as the listing says. Your Anki and its cards are untouched. '
                     f'<a href="#" onclick="{_pycmd("setup")}">Start again with your email</a>; '
                     f'your crew can add you with your new code.')
    if expired:
        return _card(cfg, "Due Crew",
                     f'Your sign-in expired. '
                     f'<a href="#" onclick="{_pycmd("setup")}">Sign in again</a>')
    # 3.4 review, C4: one way in; the emailed code knows if the address is new
    words = (f'Your friends&rsquo; studying next to yours. Nothing is shared '
             f'until you start. <a href="#" onclick="{_pycmd("setup")}">Start with your email</a>')
    if not sev:
        return _card(cfg, "Due Crew", words)
    return _card(cfg, "Due Crew", f'<span class="dc-so"><span class="dc-hi">{_sev.slot(sev, 44)}</span><span>{words}</span></span>',
                 f'<style>{SEV_CSS}{_sev.CSS}</style>')


def loading_card(cfg):
    return _card(cfg, "Due Crew", "Catching up with your crew&hellip;")


# 3.9.1, doodle cheers: drawn on paper, the same in either theme, like the pad
DOODLE_PAPER, DOODLE_LINE, DOODLE_INK = "#fffdf7", "#e6dfcc", "#2b2d29"
# the board's own font (Sam: "consistent with our normal fonts"): a sign is the board's words, bold
BOARD_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"


def doodle_html(d, accent=None, label="A drawing"):
    """3.9.1: a doodle cheer's drawing, as an SVG of its strokes on the pad's
    300 x 170, or a sign's words; "" for anything clean_doodle drops. The
    caller sets the paper behind it. accent: the sender's colour (an accent
    name; its light shade, on paper in either theme). Numbers and escaped
    words only: a doodle never carries markup or a colour of its own."""
    d = clean_doodle(d)
    if not d:
        return ""
    if d["k"] == "sign":
        return f'<div class="dd-sign" style="font-family:{BOARD_FONT};font-weight:700">{_html.escape(d["t"])}</div>'
    colour = accent_pair(accent)[0]
    paths = []
    for st in d["s"]:
        pts = list(zip(st[1::2], st[2::2]))
        line = "M" + " L".join(f"{x} {y}" for x, y in pts) + (" l0.1 0" if len(pts) == 1 else "")
        c = st[0] >> 1  # 0 the sender's colour, 1 black, 2 on one of ours (DOODLE_INKS)
        ink = DOODLE_INK if c == 1 else accent_pair(DOODLE_INKS[c - 2])[0] if c >= 2 else colour
        paths.append(f'<path d="{line}" stroke="{ink}" stroke-width="{6 if st[0] & 1 else 3}"/>')
    return (f'<svg class="dd-draw" viewBox="0 0 300 170" role="img" aria-label="{_html.escape(label, quote=True)}" fill="none"'
            f' stroke-linecap="round" stroke-linejoin="round">{"".join(paths)}</svg>')


def doodle_landing(cheer, entries, cfg):
    """3.9.1: what a landing cheer's doodle needs (flurry_js): its markup,
    whether it's a sign, and, with Pip on, the sender's Pip with its arms
    up to hold it (their colour and look, as cheer_pips draws them). None
    when the cheer has none."""
    d = clean_doodle((cheer or {}).get("doodle"))
    if not d:
        return None
    e = next((x for x in entries or [] if x.get("user_id") == cheer.get("from") and not x.get("you")), {})
    name = str(cheer.get("name") or e.get("name") or "?")
    out = {"html": doodle_html(d, e.get("accent"), f"{name}’s drawing"), "sign": d["k"] == "sign",
           "a": list(accent_pair(e.get("accent"))), "pip": None,
           # its caption, as on the fridge: the note under it, and who it's from (text, never markup)
           "note": str(cheer.get("note") or "")[:80], "from": name.split(" ")[0][:40], "ni": int(cheer.get("ni", -1))}
    if cfg.get("sev", True):
        out["pip"] = _sev.svg("stretch", "idle", look=e.get("look"), label=_html.escape(f"{name}’s Pip", quote=True))
    return out


CHEER_WINDOW_JS = r"""
(function () {
    var V = __VIEW__;
    var old = document.getElementById('dc-cheer');
    if (old) { old.remove(); }
    var night = /night/i.test(document.body.className) ||
        (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    var dcBoard = document.getElementById('due-crew');
    var dcStyle = dcBoard ? getComputedStyle(dcBoard) : null;
    function tok(name, light, dark) {
        var v = dcStyle && dcStyle.getPropertyValue('--dc-' + name).trim();
        return v || (night ? dark : light);
    }
    var bg = tok('bg', '#ffffff', '#1c1c1c'), ink = tok('ink', '#333333', '#dfe1dc'), line = tok('line', '#e2e2da', '#3d403b'),
        well = tok('well', '#f2f2ec', '#2b2d29'), muted = tok('muted', '#6f736b', '#9a9e94'),
        accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
        you = tok('you-bg', '#e9f2e9', '#2c372b');
    var font = (dcStyle && dcStyle.fontFamily) || '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    var W = 300, H = 170, MAXP = 2000, MAXS = 200, SIGN = 24, NOTE = 80, INK = '__INK__';
    var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) { e.className = cls; }
        if (text != null) { e.textContent = text; }
        return e;
    }
    var back = el('div');
    back.id = 'dc-cheer';
    back.setAttribute('role', 'dialog');
    back.setAttribute('aria-modal', 'true');
    back.setAttribute('aria-label', 'Cheer ' + V.name);
    var css = el('style');
    css.textContent =
        '#dc-cheer{position:fixed;inset:0;z-index:80;background:rgba(0,0,0,.35);display:flex;align-items:flex-start;justify-content:center;padding:9vh 16px 16px;overflow:auto;}' +
        '#dc-cheer *{box-sizing:border-box;}' +
        '#dc-cheer .cw{width:440px;max-width:100%;border-radius:14px;padding:16px 18px 14px;text-align:left;display:grid;gap:12px;font-family:' + font + ';' +
          'box-shadow:0 16px 60px rgba(0,0,0,.35);background:' + bg + ';color:' + ink + ';border:1px solid ' + line + ';font-size:13px;}' +
        '#dc-cheer button,#dc-cheer input{margin:0;box-shadow:none;font-family:inherit;color:inherit;}#dc-cheer button{cursor:pointer;}' +
        '#dc-cheer .hd{display:flex;align-items:center;gap:10px;}' +
        '#dc-cheer .hd .pp{width:40px;height:40px;flex:none;display:grid;place-items:center;}' +
        '#dc-cheer .hd .pp svg{width:44px;height:44px;overflow:visible;}' +
        '#dc-cheer .hd b{display:block;font-size:16px;}' +
        '#dc-cheer .hd small{display:block;color:' + muted + ';font-size:11.5px;}' +
        '#dc-cheer .em{display:flex;flex-wrap:wrap;gap:6px;align-items:center;}' +
        '#dc-cheer .em button{width:40px;height:36px;padding:0;border-radius:10px;border:1px solid ' + line + ';background:' + bg + ';font-size:20px;line-height:1;}' +
        '#dc-cheer .em button[aria-pressed=true]{border:2px solid ' + accent + ';background:' + you + ';}' +
        '#dc-cheer .em .ot{width:auto;min-width:66px;padding:0 10px;font-size:12px;color:' + muted + ';}' +
        '#dc-cheer .em .ot.on{border:2px solid ' + accent + ';background:' + you + ';font-size:20px;color:' + ink + ';}' +
        '#dc-cheer .em .ot[aria-expanded=true]{border-color:' + accent + ';color:' + accent + ';}' +
        '#dc-cheer .em input.pk{width:74px;height:36px;border-radius:10px;border:2px solid ' + accent + ';background:' + you + ';color:' + ink + ';font-size:20px;padding:0 8px;text-align:center;}' +
        '#dc-cheer .em input.pk::placeholder{font-size:12px;color:' + muted + ';}' +
        '#dc-cheer .em input.pk:focus{outline:none;}' +
        '#dc-cheer .dr{border:1px solid ' + line + ';border-radius:12px;padding:8px;display:grid;gap:6px;background:' + well + ';}' +
        '#dc-cheer .gt{display:flex;flex-wrap:wrap;gap:2px;}' +
        '#dc-cheer .gt button{width:32px;height:28px;border:0;background:none;border-radius:8px;font-size:16px;line-height:1;padding:0;}' +
        '#dc-cheer .gt button:hover{background:' + bg + ';}' +
        '#dc-cheer .gr{position:relative;max-height:176px;overflow-y:auto;display:flex;flex-wrap:wrap;gap:2px;align-content:flex-start;}' +
        '#dc-cheer .gr .gl{flex-basis:100%;font-size:11px;font-weight:700;color:' + muted + ';padding:4px 2px 2px;}' +
        '#dc-cheer .gr button{width:34px;height:32px;border:0;background:none;border-radius:8px;font-size:20px;line-height:1;padding:0;}' +
        '#dc-cheer .gr button:hover{background:' + bg + ';}' +
        '#dc-cheer .gr .none{flex-basis:100%;color:' + muted + ';font-size:12px;padding:6px 2px;}' +
        '#dc-cheer .sgw{display:flex;align-items:center;gap:8px;}' +
        '#dc-cheer .sg{display:inline-flex;border:1px solid ' + line + ';border-radius:99px;padding:2px;gap:2px;width:max-content;}' +
        '#dc-cheer .sg button{border:0;background:none;border-radius:99px;padding:2px 14px;font-weight:700;font-size:12px;color:' + muted + ';}' +
        '#dc-cheer .sg button[aria-pressed=true]{background:' + accent + ';color:' + accentInk + ';}' +
        '#dc-cheer .pane{display:grid;gap:8px;}' +
        '#dc-cheer .paper{width:100%;aspect-ratio:300/170;background:#fffdf7;border:1px solid #e6dfcc;border-radius:10px;overflow:hidden;position:relative;color:#2b2d29;}' +
        '#dc-cheer canvas{display:block;width:100%;height:100%;touch-action:none;cursor:crosshair;}' +
        '#dc-cheer .tl{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}' +
        '#dc-cheer .sw{width:22px;height:22px;border-radius:50%;border:2px solid ' + bg + ';box-shadow:0 0 0 1px ' + line + ';padding:0;}' +
        '#dc-cheer .sw[aria-pressed=true]{box-shadow:0 0 0 2px ' + accent + ';}' +
        '#dc-cheer .pl{border:1px solid ' + line + ';background:none;border-radius:99px;padding:1px 10px;font-size:12px;}' +
        '#dc-cheer .pl[aria-pressed=true]{border-color:' + accent + ';color:' + accent + ';font-weight:700;}' +
        '#dc-cheer .lk{border:0;background:none;padding:1px 4px;font-size:12px;color:' + accent + ';font-weight:600;}' +
        '#dc-cheer .sp{flex:1;}' +
        '#dc-cheer .ct{font-size:11px;color:' + muted + ';font-variant-numeric:tabular-nums;}' +
        '#dc-cheer .words{position:absolute;inset:0;display:grid;place-items:center;padding:10px 16px;text-align:center;font-weight:700;font-size:26px;line-height:1.15;overflow-wrap:anywhere;}' +
        '#dc-cheer .words.ph{color:#b7b1a2;}' +
        '#dc-cheer .tx{width:100%;height:32px;border-radius:8px;border:1px solid ' + line + ';background:' + bg + ';color:' + ink + ';font-size:13px;padding:0 10px;}' +
        '#dc-cheer .tx:focus{outline:2px solid ' + accent + ';outline-offset:0;}' +
        '#dc-cheer .ft{display:flex;align-items:center;gap:8px;}' +
        '#dc-cheer .go{background:' + accent + ';color:' + accentInk + ';border:1px solid transparent;border-radius:8px;padding:6px 16px;font-weight:700;font-size:13px;}' +
        '#dc-cheer .no{background:none;border:1px solid ' + line + ';border-radius:8px;padding:6px 14px;font-size:13px;}' +
        '#dc-cheer button:focus-visible{outline:2px solid ' + accent + ';outline-offset:2px;}' +
        '#dc-cheer .hint{font-size:11px;color:' + muted + ';}';
    back.appendChild(css);
    var card = el('div', 'cw');
    back.appendChild(card);

    // who it's for: their Pip (or emoji) and name
    var hd = el('div', 'hd');
    if (V.pip) { var pp = el('div', 'pp'); pp.innerHTML = V.pip; hd.appendChild(pp); }
    var ht = el('div');
    ht.appendChild(el('b', null, 'Cheer ' + V.name));
    ht.appendChild(el('small', null, 'Lands after their next sync.'));
    hd.appendChild(ht);
    card.appendChild(hd);

    // the emoji: the quick picks, or any other
    var emoji = V.emojis[0], em = el('div', 'em');
    em.setAttribute('role', 'group');
    em.setAttribute('aria-label', 'Emoji');
    var quick = [];
    V.emojis.forEach(function (x) {
        var b = el('button', null, x);
        b.type = 'button';
        b.setAttribute('aria-label', 'Send ' + x);
        b.addEventListener('click', function () { choose(x); });
        quick.push([x, b]);
        em.appendChild(b);
    });
    // other: a drawer of emoji (emoji_drawer.py) in the window's own look, since a page can't open the
    // computer's picker (Sam: "doesn't pop up with the emoji drawer"); its search box takes a typed or pasted one too
    var other = el('button', 'ot', 'other');
    other.type = 'button';
    other.title = 'Any emoji';
    other.setAttribute('aria-label', 'Any other emoji');
    other.setAttribute('aria-expanded', 'false');
    other.addEventListener('click', function () {
        if (V.native) { native(); } else if (drawer.style.display === 'none') { openDrawer(); } else { shut(); }
    });
    em.appendChild(other);
    // on a Mac or Windows, other opens the computer's own picker (Sam: "want the other option to just open
    // the native drawer?"): a box takes other's place, focused, and what's picked there is picked;
    // if the computer can't (Linux, or asking failed), the drawer opens instead (dcCheerNoNative)
    var pickIn = el('input', 'ot pk');
    pickIn.style.display = 'none';
    pickIn.placeholder = 'pick one';
    pickIn.maxLength = 16;
    pickIn.setAttribute('aria-label', 'Your emoji');
    em.appendChild(pickIn);
    function native() {
        other.style.display = 'none'; pickIn.style.display = ''; pickIn.value = ''; pickIn.focus();
        window.dcCheerNoNative = function () { unpick(); openDrawer(); };
        if (typeof pycmd !== 'undefined') { pycmd('duecrew:emojipicker'); } else { window.dcCheerNoNative(); }
    }
    function unpick() { pickIn.style.display = 'none'; other.style.display = ''; }
    pickIn.addEventListener('input', function () {
        var t = oneEmoji(pickIn.value.trim());
        if (t) { unpick(); choose(t); } else if (pickIn.value.trim()) { pickIn.value = ''; }
    });
    card.appendChild(em);
    var drawer = el('div', 'dr'), find = el('input', 'tx'), gt = el('div', 'gt'), gr = el('div', 'gr'), none = el('div', 'none', 'Nothing by that name. Paste one in here instead.');
    drawer.style.display = 'none';
    find.placeholder = 'Find one: heart, coffee, owl…';
    find.setAttribute('aria-label', 'Find an emoji');
    drawer.appendChild(find);
    drawer.appendChild(gt);
    drawer.appendChild(gr);
    var cells = [], labels = [];
    V.drawer.forEach(function (g) {
        var lab = el('div', 'gl', g[0]);
        gr.appendChild(lab);
        labels.push([lab, []]);
        var tab = el('button', null, g[1][0][0]);
        tab.type = 'button';
        tab.title = g[0];
        tab.setAttribute('aria-label', g[0]);
        tab.addEventListener('click', function () { if (find.value) { find.value = ''; filter(); } gr.scrollTop = lab.offsetTop; });
        gt.appendChild(tab);
        g[1].forEach(function (x) {
            var b = el('button', null, x[0]);
            b.type = 'button';
            b.title = x[1];
            b.setAttribute('aria-label', x[0] + ' ' + x[1]);
            b.addEventListener('click', function () { choose(x[0]); });
            gr.appendChild(b);
            cells.push([b, (' ' + x[1]).toLowerCase(), lab]);
            labels[labels.length - 1][1].push(b);
        });
    });
    gr.appendChild(none);
    function oneEmoji(s) {
        var first = '';
        if (s && window.Intl && Intl.Segmenter) {
            var it = new Intl.Segmenter().segment(s)[Symbol.iterator]().next();
            first = it.done ? '' : it.value.segment;
        } else if (s) { first = Array.from(s)[0]; }
        return first && !/[A-Za-z0-9\s]/.test(first) && first.charCodeAt(0) >= 0x2190 ? first : '';
    }
    function filter() {
        var q = find.value.trim().toLowerCase(), shown = 0;
        cells.forEach(function (c) {
            var on = !q || c[1].indexOf(' ' + q) >= 0;
            c[0].style.display = on ? '' : 'none';
            if (on) { shown++; }
        });
        labels.forEach(function (l) { l[0].style.display = !q && l[1].length ? '' : 'none'; });
        none.style.display = shown ? 'none' : '';
    }
    find.addEventListener('input', function () {
        var typed = oneEmoji(find.value.trim());
        if (typed) { choose(typed); return; }
        filter();
    });
    filter();
    card.appendChild(drawer);
    function openDrawer() {
        drawer.style.display = '';
        other.setAttribute('aria-expanded', 'true');
        find.value = '';
        filter();
        gr.scrollTop = 0;
        find.focus();
    }
    function shut() {
        drawer.style.display = 'none';
        other.setAttribute('aria-expanded', 'false');
    }
    function choose(x) {
        var q = V.emojis.indexOf(x) >= 0;
        other.textContent = q ? 'other' : x;
        other.className = q ? 'ot' : 'ot on';
        other.setAttribute('aria-label', q ? 'Any other emoji' : 'Send ' + x + ' (choose another)');
        pick(x);
        shut();
        other.focus();
    }
    function pick(x) {
        emoji = x;
        quick.forEach(function (q) { q[1].setAttribute('aria-pressed', q[0] === x ? 'true' : 'false'); });
    }
    pick(emoji);

    // Draw · Sign (3.9.1): a drawing, or words their Pip holds up; both optional, so both start shut and
    // the window is just the emoji and the note (Sam: "they don't always need to send a doodle / sign");
    // a press opens one, a second press on it shuts it, and only what's open is sent
    var mode = '', sgw = el('div', 'sgw'), sg = el('div', 'sg');
    sgw.appendChild(el('span', 'hint', 'Add'));
    sg.setAttribute('role', 'group');
    sg.setAttribute('aria-label', 'Add');
    var tabs = {};
    [['draw', 'Draw'], ['sign', 'Sign']].forEach(function (x) {
        var b = el('button', null, x[1]);
        b.type = 'button';
        b.addEventListener('click', function () { show(mode === x[0] ? '' : x[0]); });
        tabs[x[0]] = b;
        sg.appendChild(b);
    });
    sgw.appendChild(sg);
    card.appendChild(sgw);

    var draw = el('div', 'pane'), paper = el('div', 'paper'), cv = el('canvas');
    cv.width = W * 2;
    cv.height = H * 2;
    cv.setAttribute('aria-label', 'Draw here');
    paper.appendChild(cv);
    draw.appendChild(paper);
    // pen: bit 0 thick; pen >> 1 the colour: 0 the sender's, 1 black, 2 on one of ours (V.inks, DOODLE_INKS's order)
    var inks = V.inks.map(function (x, i) { return [i + 2, x[0], x[1]]; });
    if (V.mine >= 0 && inks[V.mine]) { var m = inks.splice(V.mine, 1)[0]; inks.unshift([m[0], m[1], 'My colour']); }
    inks.push([1, INK, 'Black']);
    var strokes = [], live = null, pen = (inks[0][0] << 1) | 1;
    function inkOf(p) { var c = p >> 1; return c === 1 ? INK : c >= 2 && V.inks[c - 2] ? V.inks[c - 2][0] : V.pen; }
    var cx = cv.getContext('2d');
    function points() { return strokes.reduce(function (a, s) { return a + s.p.length; }, 0); }
    function paint() {
        cx.setTransform(cv.width / W, 0, 0, cv.height / H, 0, 0);
        cx.clearRect(0, 0, W, H);
        cx.lineCap = 'round';
        cx.lineJoin = 'round';
        strokes.forEach(function (s) {
            cx.strokeStyle = inkOf(s.pen);
            cx.lineWidth = s.pen & 1 ? 6 : 3;
            cx.beginPath();
            s.p.forEach(function (q, i) { if (i) { cx.lineTo(q[0], q[1]); } else { cx.moveTo(q[0], q[1]); cx.lineTo(q[0] + 0.1, q[1]); } });
            cx.stroke();
        });
        var n = points();
        count.textContent = n > MAXP - 500 ? n.toLocaleString() + ' / ' + MAXP.toLocaleString() : '';
        caption();
    }
    function at(e) {
        var r = cv.getBoundingClientRect();
        return [Math.max(0, Math.min(W, Math.round((e.clientX - r.left) / r.width * W))),
                Math.max(0, Math.min(H, Math.round((e.clientY - r.top) / r.height * H)))];
    }
    cv.addEventListener('pointerdown', function (e) {
        if (strokes.length >= MAXS || points() >= MAXP) { return; }
        cv.setPointerCapture(e.pointerId);
        live = { pen: pen, p: [at(e)] };
        strokes.push(live);
        paint();
    });
    cv.addEventListener('pointermove', function (e) {
        if (!live || points() >= MAXP) { return; }
        var q = at(e), l = live.p[live.p.length - 1];
        if (Math.abs(q[0] - l[0]) + Math.abs(q[1] - l[1]) >= 2) { live.p.push(q); paint(); }
    });
    function lift() { live = null; }
    cv.addEventListener('pointerup', lift);
    cv.addEventListener('pointercancel', lift);

    var tl = el('div', 'tl'), swatches = [], widths = [];
    inks.forEach(function (x) {
        var b = el('button', 'sw');
        b.type = 'button';
        b.style.background = x[1];
        b.title = x[2];
        b.setAttribute('aria-label', x[2]);
        b.addEventListener('click', function () { pen = (pen & 1) | (x[0] << 1); tools(); });
        swatches.push([x[0], b]);
        tl.appendChild(b);
    });
    [['Thin', 0], ['Thick', 1]].forEach(function (x) {
        var b = el('button', 'pl', x[0]);
        b.type = 'button';
        b.addEventListener('click', function () { pen = (pen & ~1) | x[1]; tools(); });
        widths.push([x[1], b]);
        tl.appendChild(b);
    });
    tl.appendChild(el('span', 'sp'));
    var count = el('span', 'ct');
    tl.appendChild(count);
    var undo = el('button', 'lk', 'Undo'), clear = el('button', 'lk', 'Clear');
    undo.type = clear.type = 'button';
    undo.addEventListener('click', function () { strokes.pop(); paint(); });
    clear.addEventListener('click', function () { strokes = []; paint(); });
    tl.appendChild(undo);
    tl.appendChild(clear);
    draw.appendChild(tl);
    function tools() {
        swatches.forEach(function (s) { s[1].setAttribute('aria-pressed', (pen >> 1) === s[0] ? 'true' : 'false'); });
        widths.forEach(function (w) { w[1].setAttribute('aria-pressed', (pen & 1) === w[0] ? 'true' : 'false'); });
    }
    tools();
    card.appendChild(draw);

    var sign = el('div', 'pane'), signIn = el('input', 'tx'), sp = el('div', 'paper'), words = el('div', 'words ph', "you've got this");
    signIn.maxLength = SIGN;
    signIn.placeholder = "you've got this";
    signIn.setAttribute('aria-label', 'What your Pip holds up');
    signIn.addEventListener('input', function () {
        var s = signIn.value.replace(/\s+/g, ' ').trim();
        words.textContent = s || "you've got this";
        words.className = s ? 'words' : 'words ph';
        caption();
    });
    sp.appendChild(words);
    sign.appendChild(signIn);
    sign.appendChild(sp);
    sign.appendChild(el('div', 'hint', 'A few words for your Pip to hold up when it lands. ' + SIGN + ' letters at most.'));
    card.appendChild(sign);
    function show(m) {
        mode = m;
        draw.style.display = m === 'draw' ? '' : 'none';
        sign.style.display = m === 'sign' ? '' : 'none';
        tabs.draw.setAttribute('aria-pressed', m === 'draw' ? 'true' : 'false');
        tabs.sign.setAttribute('aria-pressed', m === 'sign' ? 'true' : 'false');
        if (m === 'sign') { signIn.focus(); }
        caption();
    }
    // 3.9.1 (Sam): with a drawing or a sign, the note goes under it, "from" me, as a caption
    var note = null;
    function caption() {
        if (!note) { return; }
        var has = mode === 'sign' ? !!signIn.value.trim() : mode === 'draw' && strokes.length > 0;
        note.placeholder = has ? 'A caption under it (optional)' : 'Add a note (optional)';
    }
    show('');

    note = el('input', 'tx');
    note.maxLength = NOTE;
    note.placeholder = 'Add a note (optional)';
    note.setAttribute('aria-label', 'Note');
    note.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); send(); } });
    card.appendChild(note);

    var ft = el('div', 'ft'), go = el('button', 'go', '🎉 Send'), no = el('button', 'no', 'Cancel');
    go.type = no.type = 'button';
    ft.appendChild(go);
    ft.appendChild(el('span', 'sp'));
    ft.appendChild(no);
    card.appendChild(ft);
    paint();

    function doodle() {
        if (mode === 'sign') {
            var t = signIn.value.replace(/\s+/g, ' ').trim();
            return t ? { k: 'sign', t: t } : null;
        }
        if (mode !== 'draw' || !strokes.length) { return null; }  // shut: nothing goes, what's drawn stays for a reopen
        return { k: 'draw', s: strokes.map(function (s) {
            var out = [s.pen];
            s.p.forEach(function (q) { out.push(q[0], q[1]); });
            return out;
        }) };
    }
    function close() {
        document.removeEventListener('keydown', esc, true);
        if (still || !back.animate) { back.remove(); return; }
        back.style.pointerEvents = 'none';
        back.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-in' }).onfinish = function () { back.remove(); };
    }
    function send() {
        var p = { to: V.uid, emoji: emoji, note: note.value.replace(/\s+/g, ' ').trim().slice(0, NOTE), doodle: doodle() };
        close();
        if (typeof pycmd !== 'undefined') { pycmd('duecrew:cheersend:' + encodeURIComponent(JSON.stringify(p))); }
    }
    go.addEventListener('click', send);
    no.addEventListener('click', close);
    // a press that starts on the backdrop and ends there closes it (a line drawn off the pad's edge never does)
    var downOnBack = false;
    back.addEventListener('pointerdown', function (e) { downOnBack = e.target === back; });
    back.addEventListener('click', function (e) { if (e.target === back && downOnBack) { close(); } });
    function esc(e) {
        if (e.key !== 'Escape') { return; }
        e.stopPropagation();
        if (pickIn.style.display !== 'none') { unpick(); other.focus(); }
        else if (drawer.style.display !== 'none') { shut(); other.focus(); } else { close(); }
    }
    document.addEventListener('keydown', esc, true);
    document.body.appendChild(back);
    if (window.dcMotion && !still) { dcMotion.open(back, card); }
    quick[0][1].focus();
})();
""".replace("__INK__", DOODLE_INK)


# 3.9.1: the fridge, around the Decks screen (Sam: "could the fridge just be the
# periphery of the decks window, like dragged around the anki window?")
FRIDGE_W = 124  # px: a doodle on the window, on its paper
FRIDGE_PIP = 30  # px: the Pip by a sender's name on the fridge (a crew row's size; its body is 18)


def _tape(colour):
    """A tape strip's colour: an accent's light shade (#rrggbb), see-through
    as tape is (rgba, since Anki's older webviews have no color-mix)."""
    h = str(colour).lstrip("#")
    try:
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return "rgba(0,0,0,.12)"
    return f"rgba({r},{g},{b},.6)"


FRIDGE_CSS = """
    #dc-fridge { position: fixed; left: 0; top: 0; right: 0; bottom: 0; pointer-events: none; z-index: 5; }
    #dc-fridge .fz { position: fixed; left: -9999px; top: 0; width: %dpx; box-sizing: border-box; pointer-events: auto;
      background: #fff; border-radius: 2px; padding: 7px; color: #2b2d29;
      box-shadow: 0 3px 10px rgba(0,0,0,.16), 0 0 0 1px rgba(0,0,0,.05); text-align: left; font-size: 10.5px; line-height: 1.3; cursor: grab;
      touch-action: none; user-select: none; -webkit-user-select: none; transform: rotate(var(--fr, -2deg)); }
    #dc-fridge .fz::before { content: ""; position: absolute; top: -8px; left: 50%%; width: 54px; height: 16px; margin-left: -27px;
      background: var(--ft); transform: rotate(-4deg);
      clip-path: polygon(0 12%%, 5%% 0, 30%% 6%%, 60%% 0, 95%% 5%%, 100%% 0, 98%% 50%%, 100%% 100%%, 70%% 94%%, 40%% 100%%, 4%% 95%%, 0 100%%, 2%% 50%%); }
    #dc-fridge .fz.drag { cursor: grabbing; box-shadow: 0 14px 28px rgba(0,0,0,.25); z-index: 1; }
    #dc-fridge .fp { aspect-ratio: 300 / 170; display: grid; place-items: center; overflow: hidden; background: #f4f3ee; }
    #dc-fridge .fp svg { width: 100%%; height: 100%%; display: block; }
    #dc-fridge .fp .dd-sign { font-size: 13px; line-height: 1.15; text-align: center; padding: 2px 4px; overflow-wrap: anywhere; }
    #dc-fridge .fq { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; margin-top: 7px;
      text-align: center; font-size: 11px; }
    #dc-fridge .fw { display: flex; align-items: center; justify-content: center; gap: 3px; margin-top: 3px; color: #6b665a;
      white-space: nowrap; overflow: hidden; }
    #dc-fridge .fw b { color: #2b2d29; overflow: hidden; text-overflow: ellipsis; }
    #dc-fridge .fw .sv-slot { --sv-a: var(--fa); flex: none; }
    #dc-fridge .fx { position: absolute; top: 0; right: 3px; display: none; color: #6b665a; text-decoration: none; font-size: 15px; line-height: 1; }
    #dc-fridge .fz:hover .fx, #dc-fridge .fz:focus-within .fx { display: block; }
""" % FRIDGE_W


def fridge_html(items, people, cfg):
    """3.9.1: the doodles my crew sent (fridge.clean's), pinned around the
    Decks screen, newest first: each a Polaroid (Sam's pick from "Pinned
    Doodles": the doodle in a white frame, taped up with a strip in their
    colour), the note it came with on the frame's wide bottom edge, then
    their Pip and name (no "from": Sam, "so there's more room for the
    Pip") and the day, and a × to take it down. Where I dragged one (its p:
    side of the board, px from its edge, px down) rides as data; fridge_js
    places the rest in the gutters beside the board, and lets me drag. ""
    when there's none."""
    items = _fridge.clean(items)
    if not items:
        return ""
    notes = []
    for x in reversed(items):
        k = _fridge.key(x)
        e = (people or {}).get(x["from"]) or {}
        name = _html.escape(x["name"])
        pip = (_sev.slot(_sev.svg("idle", rest=True, look=e.get("look"), label=f"{name}’s Pip"), FRIDGE_PIP)
               if cfg.get("sev", True) and e else "")
        when = _short_day(x["at"])
        note = f'<div class="fq">&ldquo;{_html.escape(x["n"])}&rdquo;</div>' if x.get("n") else ""
        at = f' data-s="{x["p"][0]}" data-x="{x["p"][1]}" data-y="{x["p"][2]}"' if x.get("p") else ""
        art = doodle_html(x["d"], x["a"], x["name"] + "’s drawing")
        fa, tape = accent_pair(x["a"])
        notes.append(f'<div class="fz" data-k="{k}"{at} style="--fa:{fa};--ft:{_tape(tape)}" title="Drag it anywhere">'
                     f'<div class="fp">{art}</div>{note}<div class="fw">{pip}<b>{name}</b>{f" · {when}" if when else ""}</div>'
                     f'<a class="fx" href="#" title="Take it down" aria-label="Take {name}’s down" '
                     f'onclick="{_pycmd("fridgedown:" + k)}">&times;</a></div>')
    return f'<style>{FRIDGE_CSS}</style><div id="dc-fridge" role="group" aria-label="Your fridge">{"".join(notes)}</div>'


FRIDGE_JS = r"""
(function () {
    var f = document.getElementById('dc-fridge');
    if (!f) { return; }
    var notes = Array.prototype.slice.call(f.querySelectorAll('.fz'));
    var tilt = [-2.5, 2, -1.5, 3, -3, 1.5], nw = __W__, gap = 18;
    // the board's edges in the window (its middle, with no board)
    function edges(box) {
        var dc = f.closest('#due-crew') || document.getElementById('due-crew'), r = dc ? dc.getBoundingClientRect() : null;
        return r ? { l: r.left - box.left, r: r.right - box.left } : { l: box.width / 2, r: box.width / 2 };
    }
    function place() {
        var box = f.getBoundingClientRect(), W = box.width, H = box.height, b = edges(box);
        var room = { l: b.l >= nw + 2 * gap, r: W - b.r >= nw + 2 * gap }, y = { l: 64, r: 64 }, n = 0, pile = 0, mine = [], at = [];
        notes.forEach(function (el, i) {  // where I left each, beside the board's edge; it waits in the corner while the window's too small
            el.style.setProperty('--fr', tilt[i % tilt.length] + 'deg');
            var h = el.offsetHeight || 140, x = el.dataset.s ? b[el.dataset.s] + Number(el.dataset.x) : null;
            if (x !== null && x >= 4 && x + nw <= W - 4) {
                at[i] = [x, Math.min(Number(el.dataset.y), H - h - 4)];
                mine.push({ x: x, y: at[i][1], h: h });
            }
        });
        notes.forEach(function (el, i) {
            var h = el.offsetHeight || 140, x = null, top;
            if (at[i]) {
                x = at[i][0]; top = at[i][1];
            } else if (!el.dataset.s && (room.l || room.r)) {  // the gutters beside the board, newest highest, left then right
                var side = room.l && room.r ? (n % 2 ? 'r' : 'l') : (room.l ? 'l' : 'r');
                x = side === 'l' ? (b.l - nw) / 2 : b.r + (W - b.r - nw) / 2;
                top = y[side];
                for (var k = 0, hit = true; hit && k < mine.length + 1; k++) {  // below any I left in the way
                    hit = false;
                    mine.forEach(function (m) {
                        if (m.x < x + nw + 6 && x < m.x + nw + 6 && m.y < top + h + gap && top < m.y + m.h + gap) { top = m.y + m.h + gap; hit = true; }
                    });
                }
                y[side] = top + h + gap; n++;
                if (top + h > H - 8) { top = H - h - 8 - (n % 3) * 10; }  // a pile at the bottom once a side is full
            }
            if (x === null) {  // no room: a little pile in the bottom right corner
                x = W - nw - 16 - (pile % 4) * 12; top = H - h - 16 - (pile % 4) * 10; pile++;
            }
            el.style.left = Math.max(4, Math.min(W - nw - 4, x)) + 'px';
            el.style.top = Math.max(4, Math.min(H - h - 4, top)) + 'px';
        });
    }
    notes.forEach(function (el) {
        el.addEventListener('pointerdown', function (e) {
            if (e.button !== 0 || e.target.closest('.fx')) { return; }
            e.preventDefault();
            el.setPointerCapture(e.pointerId);
            var box = f.getBoundingClientRect(), sx = e.clientX, sy = e.clientY,
                ox = parseFloat(el.style.left) || 0, oy = parseFloat(el.style.top) || 0, moved = false;
            el.classList.add('drag');
            function move(ev) {
                var nx = Math.max(4, Math.min(box.width - el.offsetWidth - 4, ox + ev.clientX - sx)),
                    ny = Math.max(4, Math.min(box.height - el.offsetHeight - 4, oy + ev.clientY - sy));
                if (Math.abs(ev.clientX - sx) + Math.abs(ev.clientY - sy) > 3) { moved = true; }
                el.style.left = nx + 'px'; el.style.top = ny + 'px';
            }
            function up() {
                el.removeEventListener('pointermove', move);
                el.removeEventListener('pointerup', up);
                el.removeEventListener('pointercancel', up);
                el.classList.remove('drag');
                if (!moved) { return; }
                // kept by the nearer half of the board: px from that edge, px down
                var b = edges(box), x = parseFloat(el.style.left), s = x + nw / 2 < (b.l + b.r) / 2 ? 'l' : 'r';
                el.dataset.s = s; el.dataset.x = Math.round(x - b[s]); el.dataset.y = Math.round(parseFloat(el.style.top));
                if (typeof pycmd !== 'undefined') {
                    pycmd('duecrew:fridgemove:' + el.dataset.k + ':' + s + ':' + el.dataset.x + ':' + el.dataset.y);
                }
            }
            el.addEventListener('pointermove', move);
            el.addEventListener('pointerup', up);
            el.addEventListener('pointercancel', up);
        });
    });
    place();
    window.dcFridgePlace = place;
    if (!window.dcFridgeResize) {
        window.dcFridgeResize = true;
        window.addEventListener('resize', function () { if (window.dcFridgePlace) { window.dcFridgePlace(); } });
    }
})();
""".replace("__W__", str(FRIDGE_W))


def fridge_js():
    """3.9.1: after the board is drawn (and at every swap): the fridge's
    doodles placed (where I left each, else beside the board) and made
    draggable; a drop is duecrew:fridgemove:<key>:<side>:<dx>:<y>, beside
    the board's left or right edge (l, r), px from it, px down. A spot the
    window's too small for waits in the corner and comes back at the next
    resize. Nothing when there's no fridge on the page."""
    return FRIDGE_JS


def cheer_overlay_js(view):
    """3.9.1 (Sam: "make the cheers and doodles modals in the design language
    of our add on"): the Cheer window, drawn on the Decks screen in the
    board's own look (its tokens, so Settings › Theme and Accent hold), in
    place of the Qt window. view: {uid, name, emojis (the quick picks), pip
    (card_sev's markup, or None with Pip off), pen (my accent's light shade,
    the drawing's colour, on paper in either theme)}. Send goes as one
    duecrew:cheersend command, its payload URI-encoded JSON; the glue checks
    every field again (cheer_allowed, clean_note, clean_doodle) and that the
    uid is a crewmate. The name and emoji go in as text, never markup.
    Also: "other"'s drawer (emoji_drawer), and every accent for the pad
    (Sam: "make all of our colors available in the doodles feature"), in
    DOODLE_INKS's order, mine first."""
    pen = view.get("pen") if _re.fullmatch(r"#[0-9a-fA-F]{6}", str(view.get("pen") or "")) else accent_pair(None)[0]
    inks = [[accent_pair(n)[0], n.capitalize()] for n in DOODLE_INKS]
    data = {"uid": str(view.get("uid") or ""), "name": str(view.get("name") or "?"),
            "emojis": [str(x) for x in view.get("emojis") or []][:8] or ["\U0001F389"],
            "pip": view.get("pip") or "", "pen": pen, "inks": inks,
            "mine": next((i for i, x in enumerate(inks) if x[0].lower() == pen.lower()), -1),
            "drawer": _emoji_drawer.view(), "native": bool(view.get("native"))}
    return CHEER_WINDOW_JS.replace("__VIEW__", _json.dumps(data).replace("</", "<\\/"))


CHEER_PIP = 92  # 3.8.22: a crewmate's Pip popping in with their cheer


def cheer_pips(cheers, entries, cfg, most=3):
    """3.8.22, cheers with Pips (Sam's pick, round three): who sent the
    cheers that just landed, as their Pips, each once, in the order they
    came, three at most: [{svg, a: [light, dark], emoji, name, note, poses}].
    A cheer lands only from someone I added: a mutual friend comes in their
    colour and look, anyone else plain. [] with Pip off. Our own markup; a
    name is only its label, escaped. 3.9.0: the poses a show needs (popping
    up, jumping, springing out of a present, still), and the name and
    note, which the show puts in as text."""
    if not cfg.get("sev", True):
        return []
    by = {e.get("user_id"): e for e in entries or [] if not e.get("you")}
    out, seen = [], set()
    for ch in cheers or []:
        u = ch.get("from")
        if not u or u in seen:
            continue
        seen.add(u)
        e = by.get(u) or {}
        name = str(ch.get("name") or e.get("name") or "?")
        label = _html.escape(f'{name}’s Pip', quote=True)
        look = e.get("look")
        note = next((str(c.get("note")) for c in cheers if c.get("from") == u and c.get("note")), "")
        out.append({"svg": _sev.svg("hello", "popup", look=look, label=label),
                    "a": list(accent_pair(e.get("accent"))), "emoji": str(ch.get("emoji") or ""),
                    "name": name.split(" ")[0][:40], "note": note[:140],
                    "poses": {"hello": _sev.svg("hello", "popup", look=look, label=label),
                              "jump": _sev.svg("hop", "jump", look=look, label=label),
                              "cheer": _sev.svg("cheer", "giftspin", look=look, label=label),
                              "idle": _sev.svg("idle", look=look, label=label)}})
        if len(out) >= most:
            break
    return out


def and_more(names, most=3):
    """"Dre", "Dre and Mo", "Dre, Mo and Ana", "Dre, Mo, Ana and 2 more"."""
    names = [str(n) for n in names]
    if len(names) > most:
        return ", ".join(names[:most]) + f" and {len(names) - most} more"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def flurry_js(emojis, banner_text, back=None, notes=None, season=None, pips=None, show=None, doodle=None):
    """Injected via web.eval after render — never inline in board HTML.
    Banner takes its colors from the board's tokens (so Settings → Theme
    holds), the page's night classes only when the board is off. When `back` is
    (uid, emoji) — a single sender — the banner is clickable to return the
    cheer, and stays up a little longer. `notes`: sender-written lines shown
    under the title (textContent: never markup), which also buy time.
    pips (3.8.22, cheer_pips): the senders' Pips. Each pops up at the
    board's edge in turn, tosses its cheer onto my row and ducks back down,
    in place of the flurry; with Reduce motion they stand still in the
    banner. show (3.9.0, shows.next_show): with the Pips, a show over the
    whole Decks screen in place of the toss (show.js), the banner at the
    top; the toss if the show can't play. doodle (3.9.1, doodle_landing):
    a drawing or a sign came with it. The sender's Pip pops up at the
    board's corner holding it up, in place of the show and the toss, and
    ducks down as the banner goes; with Pip off or Reduce motion it sits in
    the banner, still, on its paper."""
    # 2.10: about one flake in three is the season's
    emoji_list = _json.dumps(list(emojis) * 2 + list(season or []) if season else list(emojis))
    banner = _json.dumps(banner_text)
    notes_json = _json.dumps([str(n) for n in (notes or [])][:3])
    back_cmd = _json.dumps(f"duecrew:cheerback:{back[0]}:{back[1]}" if back else None)
    pips_json = _json.dumps([{"svg": p["svg"], "a": p["a"], "emoji": p.get("emoji") or ""} for p in (pips or [])][:3]).replace("</", "<\\/")
    show_json = _json.dumps(show if show in _shows.SHOWS and pips else None)
    senders_json = _json.dumps([dict(p.get("poses") or {}, name=p.get("name") or "", note=p.get("note") or "", emoji=p.get("emoji") or "\U0001F389", a=p["a"])
                                for p in (pips or [])][:3]).replace("</", "<\\/") if show else "[]"
    season_one = _json.dumps((list(season or []) or [""])[0])
    doodle_json = _json.dumps({k: doodle.get(k) for k in ("html", "sign", "a", "pip", "note", "from", "ni")}
                              if doodle and doodle.get("html") else None).replace("</", "<\\/")
    return """
    (function() {
        if (document.getElementById('dc-flurry')) { return; }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        // 2.9: colors come from the board, which already follows Settings ->
        // Theme and Accent; Anki's night class is only the fallback
        var dcBoard = document.getElementById('due-crew');
        var dcStyle = dcBoard ? getComputedStyle(dcBoard) : null;
        function tok(name, light, dark) {
            var v = dcStyle && dcStyle.getPropertyValue('--dc-' + name).trim();
            return v || (night ? dark : light);
        }
        var dcBg = tok('bg', '#ffffff', '#1c1c1c'), dcInk = tok('ink', '#333333', '#dfe1dc'),
            dcLine = tok('line', '#e2e2da', '#3d403b'), dcWell = tok('well', '#f2f2ec', '#2b2d29'),
            accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
            warn = tok('hours', '#b26a00', '#dda45c');
        var backCmd = %s;
        var banner = document.createElement('div');
        var title = document.createElement('div');
        title.textContent = %s;
        banner.appendChild(title);
        var notes = %s, noteEls = [];
        for (var n = 0; n < notes.length; n++) {
            var line = document.createElement('div');
            line.textContent = '\u201c' + notes[n] + '\u201d';
            line.style.cssText = 'font-size:13px;font-weight:400;margin-top:4px;opacity:0.9;max-width:60vw;';
            banner.appendChild(line);
            noteEls.push(line);
        }
        banner.style.cssText = 'position:fixed;top:18vh;left:50%%;transform:translateX(-50%%);' +
            'z-index:70;border-radius:12px;padding:10px 20px;font-weight:700;font-size:15px;' +
            'text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.3);transition:opacity 0.5s;' +
            'background:' + dcBg + ';color:' + dcInk + ';border:1px solid ' + accent + ';';
        var linger = 2600 + (notes.length ? 2500 : 0);
        if (backCmd && typeof pycmd !== 'undefined') {
            linger = 5000;
            banner.style.cursor = 'pointer';
            var sub = document.createElement('div');
            sub.textContent = 'click to send one back';
            sub.style.cssText = 'font-size:11px;font-weight:400;opacity:0.7;margin-top:2px;';
            banner.appendChild(sub);
            banner.addEventListener('click', function() {
                pycmd(backCmd);
                // once: it fades as it goes, no second send
                banner.style.pointerEvents = 'none';
                banner.style.transition = 'opacity 0.25s';
                banner.style.opacity = '0';
                setTimeout(function() { banner.remove(); }, 300);
            });
        }
        var pips = %s, still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        // 3.9.1: a doodle buys time, on its paper (light in either theme, like the pad it was drawn on)
        var dd = %s, held = !!(dd && dd.pip && pips.length && !still && document.body.animate);
        function paper(w, h, caption) {
            var p = document.createElement('div');
            p.style.cssText = 'width:' + w + 'px;box-sizing:border-box;background:%s;border:1px solid %s;' +
                'border-radius:8px;overflow:hidden;color:%s;font-weight:400;text-align:left;';
            var art = document.createElement('div');
            art.style.cssText = 'height:' + h + 'px;display:grid;place-items:center;overflow:hidden;';
            art.innerHTML = dd.html;
            p.appendChild(art);
            var v = art.querySelector('svg');
            if (v) { v.style.cssText = 'width:100%%;height:100%%;display:block;'; }
            var words = art.querySelector('.dd-sign');
            if (words) { words.style.cssText += ';font-size:' + Math.round(h * 0.22) + 'px;line-height:1.15;text-align:center;padding:4px 10px;overflow-wrap:anywhere;'; }
            if (caption) {
                // 3.9.1 (Sam): the note it came with under it, and who it's from, as on the fridge
                var cap = document.createElement('div');
                cap.style.cssText = 'padding:0 8px 6px;font-size:11px;line-height:1.3;';
                if (dd.note) {
                    var q = document.createElement('div');
                    q.textContent = '\u201c' + dd.note + '\u201d';
                    q.style.cssText = 'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;';
                    cap.appendChild(q);
                }
                var by = document.createElement('div');
                by.textContent = 'from ' + dd.from;
                by.style.cssText = 'font-weight:700;opacity:.75;margin-top:2px;';
                cap.appendChild(by);
                p.appendChild(cap);
            }
            return p;
        }
        if (dd) {
            linger += 2500;
            if (!held) { var mini = paper(150, 85, false); mini.style.margin = '8px auto 2px'; banner.insertBefore(mini, sub || null); }
            else if (dd.ni >= 0 && noteEls[dd.ni]) { noteEls[dd.ni].remove(); }  // its note goes under it, not in the banner too
        }
        // 3.8.22: the board's own theme decides a Pip's colour, light or dark
        function dark(c) {
            var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(c), n = m ? [m[1], m[2], m[3]].map(function(h) { return parseInt(h, 16); })
                : (/(\\d+)\\D+(\\d+)\\D+(\\d+)/.exec(c) || [0, 255, 255, 255]).slice(1).map(Number);
            return n[0] * 0.299 + n[1] * 0.587 + n[2] * 0.114 < 128;
        }
        var boardDark = dark(dcBg), muted = tok('muted', '#6f736b', '#9a9e94');
        function pipEl(p, size) {
            var w = document.createElement('span');
            w.style.cssText = 'display:inline-block;line-height:0;width:' + size + 'px;height:' + size + 'px;' +
                '--sv-a:' + (boardDark ? p.a[1] : p.a[0]) + ';--sv-line:' + dcLine + ';--sv-amb:' + warn + ';--sv-mut:' + muted + ';';
            w.innerHTML = p.svg;
            var v = w.querySelector('svg');
            if (v) { v.setAttribute('width', size); v.setAttribute('height', size); v.style.overflow = 'visible'; }
            return w;
        }
        if (pips.length && still) {
            // standing still beside who sent it, no flurry
            var who = document.createElement('div');
            who.style.cssText = 'display:flex;justify-content:center;gap:4px;margin:-4px 0 0;';
            pips.forEach(function(p) { var e = pipEl(p, 52); var v = e.querySelector('svg'); if (v) { v.classList.add('rest'); } who.appendChild(e); });
            banner.insertBefore(who, title);
        }
        document.body.appendChild(banner);
        // it comes in as it goes out, a fade (and a drop, with motion); never there in one frame
        if (banner.animate) {
            banner.animate([{ opacity: 0, transform: 'translateX(-50%%) translateY(' + (still ? 0 : -10) + 'px)' },
                            { opacity: 1, transform: 'translateX(-50%%)' }], { duration: 280, easing: 'ease-out' });
        }
        setTimeout(function() { banner.style.opacity = '0'; }, linger);
        setTimeout(function() { banner.remove(); }, linger + 600);
        if (still) { return; }
        if (held) {
            // 3.9.1: their Pip holds it up at the board's corner, then ducks down as the banner goes
            var hb = document.getElementById('due-crew'), hr = hb ? hb.getBoundingClientRect() : null;
            var hvh = window.innerHeight, base = Math.min(hvh, hr ? hr.bottom : hvh), HW = 190, HH = 236;  // room for its caption
            var right = Math.min(window.innerWidth - 8, hr ? hr.right : window.innerWidth - 8);
            var hbox = document.createElement('div');
            hbox.setAttribute('aria-hidden', 'true');
            hbox.style.cssText = 'position:fixed;z-index:71;pointer-events:none;overflow:hidden;left:' + Math.max(8, right - HW - 8) +
                'px;top:' + (base - HH) + 'px;width:' + HW + 'px;height:' + HH + 'px;';
            var lift = document.createElement('div');
            lift.style.cssText = 'display:flex;flex-direction:column;align-items:center;padding-top:6px;transform:translateY(' + HH + 'px);';
            var sign = paper(170, 96, true);
            sign.style.transform = 'rotate(-3deg)';
            sign.style.boxShadow = '0 6px 16px rgba(0,0,0,.18)';
            var sticks = document.createElement('div');
            sticks.style.cssText = 'display:flex;justify-content:space-between;width:56px;height:28px;margin-top:-2px;';  // long enough for a hat under it
            sticks.innerHTML = '<i style="width:3px;background:#b08a5a;border-radius:2px"></i><i style="width:3px;background:#b08a5a;border-radius:2px"></i>';
            var holder = pipEl({ svg: dd.pip, a: dd.a }, 92);
            holder.style.marginTop = '-40px';
            lift.appendChild(sign); lift.appendChild(sticks); lift.appendChild(holder);
            hbox.appendChild(lift);
            document.body.appendChild(hbox);
            lift.animate([{ transform: 'translateY(' + HH + 'px)' }, { transform: 'translateY(0px)' }],
                         { duration: 600, easing: 'cubic-bezier(.2,.9,.3,1.25)', fill: 'forwards' });
            setTimeout(function() {
                lift.animate([{ transform: 'translateY(0px)' }, { transform: 'translateY(' + HH + 'px)' }],
                             { duration: 380, easing: 'ease-in', fill: 'forwards' }).onfinish = function() { hbox.remove(); };
            }, linger);
            return;
        }
        var show = %s;
        if (show && pips.length && document.body.animate) {
            // 3.9.0: a show over the whole Decks screen, the banner at its top (show.js)
            %s
            var played = window.DCShow && window.DCShow.play(show, { senders: %s, dark: boardDark, line: dcLine, amb: warn, mut: muted,
                accent: accent, accentInk: accentInk, ink: dcInk, sevcss: %s });
            if (played) { banner.style.top = '12px'; return; }
        }
        if (pips.length && document.body.animate) {
            var dc = document.getElementById('due-crew'), vw = window.innerWidth, vh = window.innerHeight;
            var edge = dc ? dc.getBoundingClientRect().right : vw * 0.8, size = %d, season = %s;
            pips.forEach(function(p, i) { setTimeout(function() { toss(p, i); }, i * 1150); });
            function where() {
                // my row's name, if it's on screen; else under the banner
                var me = dc && dc.querySelector('tr.you td.nm'), r = me && me.getBoundingClientRect();
                if (r && r.top > 0 && r.bottom < vh) { return { x: r.left + Math.min(r.width * 0.4, 160), y: r.top + r.height / 2, row: me }; }
                var b = banner.getBoundingClientRect();
                return { x: b.left + b.width / 2, y: b.bottom + 24, row: null };
            }
            function fly(text, from, to, ms, px, then) {
                var f = document.createElement('span');
                f.textContent = text;
                f.setAttribute('aria-hidden', 'true');
                f.style.cssText = 'position:fixed;left:0;top:0;z-index:72;pointer-events:none;font-size:' + px + 'px;line-height:1;';
                document.body.appendChild(f);
                var mid = { x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - 80 };
                var a = f.animate([{ transform: 'translate(' + from.x + 'px,' + from.y + 'px) rotate(0) scale(.7)' },
                                   { transform: 'translate(' + mid.x + 'px,' + mid.y + 'px) rotate(180deg) scale(1.15)', offset: 0.5 },
                                   { transform: 'translate(' + to.x + 'px,' + to.y + 'px) rotate(360deg) scale(1)' }],
                                  { duration: ms, easing: 'ease-in-out', fill: 'forwards' });
                a.onfinish = function() { f.remove(); if (then) { then(); } };
            }
            function burst(text, at) {
                for (var k = 0; k < 9; k++) {
                    var s = document.createElement('span');
                    s.textContent = (k === 4 && season) ? season : text;
                    s.setAttribute('aria-hidden', 'true');
                    s.style.cssText = 'position:fixed;left:0;top:0;z-index:72;pointer-events:none;font-size:15px;line-height:1;';
                    document.body.appendChild(s);
                    var ang = k / 9 * Math.PI * 2, d = 34 + (k %% 3) * 14;
                    s.animate([{ transform: 'translate(' + at.x + 'px,' + at.y + 'px) scale(.4)', opacity: 1 },
                               { transform: 'translate(' + (at.x + Math.cos(ang) * d) + 'px,' + (at.y + Math.sin(ang) * d * 0.6 + 16) + 'px) scale(1)', opacity: 0 }],
                              { duration: 900, easing: 'ease-out', fill: 'forwards' }).onfinish = (function(x) { return function() { x.remove(); }; })(s);
                }
            }
            function toss(p, i) {
                // it rises from the board's bottom edge (the window's, if the board runs past it), in a box that hides it below
                var r = dc ? dc.getBoundingClientRect() : null, base = Math.min(vh, r ? r.bottom : vh);
                var x = Math.max(8, Math.min(vw - size - 8, edge - size - 16 - i * 64));
                var box = document.createElement('div'), w = pipEl(p, size);
                box.setAttribute('aria-hidden', 'true');
                box.style.cssText = 'position:fixed;z-index:71;pointer-events:none;overflow:hidden;left:' + x + 'px;top:' + (base - size) +
                    'px;width:' + size + 'px;height:' + size + 'px;';
                w.style.transform = 'translateY(' + size + 'px)';
                box.appendChild(w);
                document.body.appendChild(box);
                w.animate([{ transform: 'translateY(' + size + 'px)' }, { transform: 'translateY(4px)' }],
                          { duration: 380, easing: 'cubic-bezier(.3,1.4,.5,1)', fill: 'forwards' });
                setTimeout(function() {
                    var to = where();
                    fly(p.emoji || '🎉', { x: x + size * 0.72, y: base - size * 0.5 }, { x: to.x, y: to.y - 12 }, 760, 26, function() {
                        burst(p.emoji || '🎉', { x: to.x, y: to.y - 12 });
                        if (to.row) {
                            to.row.parentNode.animate([{ backgroundColor: 'transparent' }, { backgroundColor: accent + '33', offset: 0.2 }, { backgroundColor: 'transparent' }],
                                                     { duration: 1100 });
                        }
                    });
                }, 520);
                setTimeout(function() {
                    w.animate([{ transform: 'translateY(4px)' }, { transform: 'translateY(' + size + 'px)' }],
                              { duration: 340, easing: 'ease-in', fill: 'forwards' }).onfinish = function() { box.remove(); };
                }, 2200);
            }
            return;
        }
        var emojis = %s;
        var wrap = document.createElement('div');
        wrap.id = 'dc-flurry';
        wrap.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:69;overflow:hidden;';
        var style = document.createElement('style');
        style.textContent = '@keyframes dcfall { to { transform: translateY(108vh) rotate(300deg); } }';
        wrap.appendChild(style);
        for (var i = 0; i < 26; i++) {
            var s = document.createElement('span');
            s.textContent = emojis[i %% emojis.length];
            s.style.cssText = 'position:absolute;top:-40px;left:' + (Math.random() * 100) + 'vw;' +
                'font-size:' + (16 + Math.random() * 16) + 'px;' +
                'animation:dcfall ' + (1.6 + Math.random() * 1.4) + 's linear ' +
                (Math.random() * 0.7) + 's forwards;';
            wrap.appendChild(s);
        }
        document.body.appendChild(wrap);
        setTimeout(function() { wrap.remove(); }, 3800);
    })();
    """ % (back_cmd, banner, notes_json, pips_json, doodle_json, DOODLE_PAPER, DOODLE_LINE, DOODLE_INK, show_json, SHOW_JS if show_json != "null" else "",
           senders_json, _json.dumps(_sev.CSS).replace("</", "<\\/") if show_json != "null" else "null", CHEER_PIP, season_one, emoji_list)


def stranger_card_js(info):
    """Card for a squadmate who isn't crew. Deliberately spare — no heatmap,
    no cheer, no celebration: we don't necessarily know them. info: uid,
    name, reviews, time_ms, retention, streak, rank, squad, today (bool),
    pending, knocked_me, founder_me; sev (3.8.22): card_sev's markup, a
    plain Pip in the emoji's place (all a squadmate shares is a name and an
    emoji, so no colour or look), or None."""
    sev_fig = info.get("sev")
    name = _html.escape(str(info.get("name", "?"))) if sev_fig else _label(info.get("name", "?"), info.get("emoji"))
    squad = _html.escape(str(info.get("squad") or "squad"))
    numberless = all(info.get(k) is None for k in ("reviews", "time_ms", "retention", "streak"))
    if info.get("show_up") or numberless:
        # show-up, theirs or mine: presence is the whole story, no rank
        where = f'in {squad}'
        bits = ["showed up today" if info.get("today") else "not today"]
        if info.get("week") is not None:
            bits.append(f'{int(info["week"])}/7 days this week')
    else:
        where = (f'#{int(info["rank"])} in {squad} today' if info.get("rank")
                 else f'in {squad}')
        when = "today" if info.get("today") else "last sync"
        bits = [f'{format(int(info.get("reviews") or 0), ",")} reviews {when}',
                _fmt_time(int(info.get("time_ms") or 0))]
        if info.get("retention") is not None:
            bits.append(f'{float(info["retention"]):.1f}% retention')
        bits.append(f'{int(info.get("streak") or 0)}-day streak')
    stat = " &middot; ".join(bits)
    head = (f'<div style="display: flex; align-items: baseline; gap: 8px; flex: 1; min-width: 0;">'
            f'<span style="font-size: 15px; font-weight: 700;">{name}</span>'
            f'<span style="opacity: 0.6; font-size: 10.5px; text-transform: uppercase;'
            f' letter-spacing: 0.08em;">{where}</span></div>')
    if sev_fig:  # 3.8.22: as on a crewmate's card, Pip beside the line, room above for a hat
        head = f'<div style="display: flex; align-items: center; gap: 10px; padding-top: 10px;">{sev_fig}{head}</div>'
    inner = _json.dumps(head + f'<div style="font-size: 12px; opacity: 0.8; padding: 6px 0 2px;">{stat}</div>')
    uid = str(info.get("uid", ""))
    if info.get("knocked_me"):
        act_label = _json.dumps("\U0001F91D Add back")
        act_cmd, act_primary = _json.dumps(f"duecrew:addback:{uid}"), "true"
    elif info.get("pending"):
        act_label = _json.dumps("\u23F3 Waiting")
        act_cmd, act_primary = _json.dumps(None), "false"
    else:
        act_label = _json.dumps("\U0001F91D Add")
        act_cmd, act_primary = _json.dumps(f"duecrew:knock:{uid}"), "true"
    extras = []
    if info.get("founder_me"):
        extras = [("Remove", f"duecrew:squadkick:{uid}"),
                  ("Block", f"duecrew:squadblock:{uid}"),
                  ("Make founder", f"duecrew:squadfounder:{uid}")]
    extras_json = _json.dumps(extras)
    return """
    (function() {
        var old = document.getElementById('dc-profile');
        if (old) { old.remove(); }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        // 2.9: colors come from the board, which already follows Settings ->
        // Theme and Accent; Anki's night class is only the fallback
        var dcBoard = document.getElementById('due-crew');
        var dcStyle = dcBoard ? getComputedStyle(dcBoard) : null;
        function tok(name, light, dark) {
            var v = dcStyle && dcStyle.getPropertyValue('--dc-' + name).trim();
            return v || (night ? dark : light);
        }
        var dcBg = tok('bg', '#ffffff', '#1c1c1c'), dcInk = tok('ink', '#333333', '#dfe1dc'),
            dcLine = tok('line', '#e2e2da', '#3d403b'), dcWell = tok('well', '#f2f2ec', '#2b2d29'),
            accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
            warn = tok('hours', '#b26a00', '#dda45c');
        var back = document.createElement('div');
        back.id = 'dc-profile';
        back.style.cssText = 'position:fixed;inset:0;z-index:80;background:rgba(0,0,0,0.35);' +
            'display:flex;align-items:flex-start;justify-content:center;padding-top:16vh;';
        var card = document.createElement('div');
        card.style.cssText = 'min-width:300px;max-width:380px;border-radius:12px;padding:16px 20px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);' +
            'background:' + dcBg + ';color:' + dcInk + ';border:1px solid ' + dcLine + ';';
        var body = document.createElement('div');
        body.innerHTML = %s;
        card.appendChild(body);
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;';
        var actCmd = %s;
        var act = document.createElement('button');
        act.textContent = %s;
        var primary = %s;
        act.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;' +
            (primary ? 'background:' + accent + ';color:' + accentInk +
                       ';border:1px solid transparent;font-weight:600;cursor:pointer;'
                     : 'background:none;color:inherit;opacity:0.7;border:1px solid ' +
                       dcLine + ';cursor:default;');
        if (actCmd) {
            act.addEventListener('click', function() {
                back.remove();
                if (typeof pycmd !== 'undefined') { pycmd(actCmd); }
            });
        }
        var close = document.createElement('button');
        close.textContent = 'Close';
        close.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
            'background:none;color:inherit;border:1px solid ' +
            dcLine + ';';
        close.addEventListener('click', function() { back.remove(); });
        row.appendChild(act);
        var spacer = document.createElement('div');
        spacer.style.flex = '1';
        row.appendChild(spacer);
        row.appendChild(close);
        card.appendChild(row);
        // the founder's tools get a row of their own; on the action row
        // they pushed Close onto a line by itself
        var extras = %s;
        if (extras.length) {
            var tools = document.createElement('div');
            tools.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:6px;' +
                'margin-top:12px;padding-top:10px;border-top:1px solid ' + dcLine + ';';
            var toolsLabel = document.createElement('span');
            toolsLabel.textContent = 'Founder';
            toolsLabel.style.cssText = 'font-size:10.5px;opacity:0.6;margin-right:4px;' +
                'text-transform:uppercase;letter-spacing:0.08em;';
            tools.appendChild(toolsLabel);
            extras.forEach(function(pair) {
                var extra = document.createElement('button');
                extra.textContent = pair[0];
                extra.style.cssText = 'font-size:11.5px;padding:3px 10px;border-radius:6px;cursor:pointer;' +
                    'background:none;color:inherit;opacity:0.85;border:1px solid ' + dcLine + ';';
                extra.addEventListener('click', function() {
                    back.remove();
                    if (typeof pycmd !== 'undefined') { pycmd(pair[1]); }
                });
                tools.appendChild(extra);
            });
            card.appendChild(tools);
        }
        back.appendChild(card);
        back.addEventListener('click', function(e) {
            if (e.target === back) { back.remove(); }
        });
        document.addEventListener('keydown', function esc(e) {
            if (e.key === 'Escape') { back.remove(); document.removeEventListener('keydown', esc); }
        });
        document.body.appendChild(back);
        if (window.dcMotion) { dcMotion.open(back, card); }  // 3.8.0: from the name, back into it
    })();
    """ % (inner, act_cmd, act_label, act_primary, extras_json)


def luck_card_js(name, lines):
    """2.10: the good-luck card, shown once on the morning of my exam.
    `lines`: [(sender name, note)]. Everything sender-written goes in as
    textContent, never markup. Thanks sends a 💚 back to each of them."""
    title = _json.dumps(f"\U0001F340 Good luck today, {str(name or 'you')}")
    items = _json.dumps([[str(n), str(t)] for n, t in (lines or [])][:12])
    return """
    (function() {
        var old = document.getElementById('dc-profile');
        if (old) { old.remove(); }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        var dcBoard = document.getElementById('due-crew');
        var dcStyle = dcBoard ? getComputedStyle(dcBoard) : null;
        function tok(name, light, dark) {
            var v = dcStyle && dcStyle.getPropertyValue('--dc-' + name).trim();
            return v || (night ? dark : light);
        }
        var bg = tok('bg', '#ffffff', '#1c1c1c'), ink = tok('ink', '#333333', '#dfe1dc'),
            line = tok('line', '#e2e2da', '#3d403b'), accent = tok('accent', '#2e7d32', '#7cc47f'),
            accentInk = tok('accent-ink', '#ffffff', '#122912');
        var back = document.createElement('div');
        back.id = 'dc-profile';
        back.style.cssText = 'position:fixed;inset:0;z-index:80;background:rgba(0,0,0,0.35);' +
            'display:flex;align-items:flex-start;justify-content:center;padding-top:14vh;';
        var card = document.createElement('div');
        card.style.cssText = 'min-width:320px;max-width:420px;border-radius:12px;padding:18px 22px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);background:' + bg + ';color:' + ink +
            ';border:1px solid ' + line + ';';
        var h = document.createElement('div');
        h.textContent = %s;
        h.style.cssText = 'font-size:17px;font-weight:700;margin-bottom:10px;';
        card.appendChild(h);
        %s.forEach(function(pair) {
            var p = document.createElement('div');
            p.style.cssText = 'font-size:13.5px;padding:4px 0;';
            p.textContent = '\u201c' + pair[1] + '\u201d';
            var who = document.createElement('span');
            who.textContent = ' \u2014 ' + pair[0];
            who.style.cssText = 'opacity:0.6;font-size:12px;';
            p.appendChild(who);
            card.appendChild(p);
        });
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:8px;margin-top:14px;';
        var close = document.createElement('button');
        close.textContent = 'Close';
        close.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
            'background:none;color:inherit;border:1px solid ' + line + ';';
        close.addEventListener('click', function() { back.remove(); });
        var thanks = document.createElement('button');
        thanks.textContent = 'Thanks, crew';
        thanks.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
            'background:' + accent + ';color:' + accentInk + ';border:1px solid transparent;font-weight:600;';
        thanks.addEventListener('click', function() {
            back.remove();
            if (typeof pycmd !== 'undefined') { pycmd('duecrew:luckthanks'); }
        });
        var spacer = document.createElement('div');
        spacer.style.flex = '1';
        row.appendChild(close);
        row.appendChild(spacer);
        row.appendChild(thanks);
        card.appendChild(row);
        back.appendChild(card);
        back.addEventListener('click', function(e) { if (e.target === back) { back.remove(); } });
        document.body.appendChild(back);
        if (window.dcMotion) { dcMotion.open(back, card); }  // 3.8.0: from the name, back into it
    })();
    """ % (title, items)


HEAT_LEVELS = ((1, 1), (10, 2), (50, 3), (150, 4))


def _heat_level(n):
    level = 0
    for threshold, lvl in HEAT_LEVELS:
        if n >= threshold:
            level = lvl
    return level


def profile_overlay_js(profile):
    """Build the profile overlay. `profile`:
      name, streak (int|None), last_active (str ts), cells (list of daily
      counts oldest->newest, or None when the heatmap is private),
      same_days (int|None), decks_line (str), uid, you (bool),
      paused (bool), exam (str, client-built text or ""), away (str, text
      or ""), status (str or ""), today ((reviews, new cards or None) or
      None), sev (3.8.2: card_sev's markup, in the emoji's place, or None).
    For your own card ("you") the overlay shows exactly what the crew sees,
    and the cheer button becomes a Privacy shortcut. Everything user-sourced
    is escaped here; the JS only injects the built HTML and wires buttons."""
    you = bool(profile.get("you"))
    sev_fig = profile.get("sev")  # 3.8.2: their Pip where the emoji was, as on their row
    name = _html.escape(str(profile.get("name", "?"))) if sev_fig else _label(profile.get("name", "?"), profile.get("emoji"))
    kicker = ""
    if you:
        kicker = ('<div style="font-size: 10px; font-weight: 700; '
                  'letter-spacing: 0.09em; text-transform: uppercase; '
                  'opacity: 0.6; margin-bottom: 6px;">As your crew sees it</div>')
    bits = [f'<span style="font-size: 15px; font-weight: 700;">{name}</span>']
    if profile.get("streak") is not None:
        bits.append(f'<span style="opacity: 0.7; font-size: 12px;">'
                    f'{int(profile["streak"])}-day streak</span>')
    ago_txt, _tone = _ago(profile.get("last_active", ""))
    if ago_txt:
        bits.append(f'<span style="opacity: 0.55; font-size: 11px; '
                    f'margin-left: auto;">({_html.escape(ago_txt)})</span>')
    head = '<div style="display: flex; align-items: baseline; gap: 8px; flex: 1; min-width: 0;">' + "".join(bits) + "</div>"
    if sev_fig:  # 3.8.2: Pip beside the line, centred on it, with room above for a hat or a balloon
        head = f'<div style="display: flex; align-items: center; gap: 10px; padding-top: 10px;">{sev_fig}{head}</div>'
    head = kicker + head
    today = profile.get("today")
    if today and not profile.get("paused"):
        head += (f'<div style="font-size: 12px; opacity: 0.8; padding: 4px 0 0;">'
                 f'Today: {today_text(*today)}</div>')
    if profile.get("paused"):
        head += ('<div style="font-size: 12px; font-style: italic; '
                 'opacity: 0.7; padding: 4px 0 0;">on a break</div>')
    if profile.get("exam"):
        head += (f'<div class="dcex" style="font-size: 12px; font-weight: 700; '
                 f'padding: 4px 0 0;">&#128214; '
                 f'{_html.escape(str(profile["exam"]))}</div>')
    if profile.get("away"):
        head += (f'<div class="dcex" style="font-size: 12px; font-weight: 700; '
                 f'padding: 4px 0 0;">&#9992;&#65039; '
                 f'{_html.escape(str(profile["away"]))}</div>')
    status = str(profile.get("status") or "")
    if status or you:
        edit = ""
        if you:
            link = ('style="color: inherit; text-decoration: none; '
                    'border-bottom: 1px dotted currentColor;"')
            edit = (f' <a href="#" {link} onclick="{_pycmd("status")}">'
                    f'{"edit" if status else "Set a status"}</a>')
        quoted = f'&ldquo;{_html.escape(status)}&rdquo;' if status else ""
        head += (f'<div style="font-size: 12px; opacity: 0.8; padding: 4px 0 0;">'
                 f'{quoted}{edit}</div>')
    if you:
        link = ('style="color: inherit; text-decoration: none; '
                'border-bottom: 1px dotted currentColor;"')
        closet = ""
        if sev_fig:  # 3.8.2: dress your Pip; the emoji stays for squads, bingo and older add-ons
            closet = (f'<a href="#" {link} onclick="document.getElementById(\'dc-profile\').remove();{_pycmd("closet")}">'
                      f'Pip&rsquo;s closet</a> &middot; ')
        head += (f'<div style="font-size: 12px; opacity: 0.8; padding: 4px 0 0;">{closet}'
                 f'<a href="#" {link} onclick="{_pycmd("emoji")}">'
                 f'{"Change emoji" if profile.get("emoji") else "Pick an emoji"}</a></div>')

    cells = profile.get("cells")
    if cells is None:
        private = "Your heatmap is private." if you else "Their heatmap is private."
        grid = (f'<div style="font-size: 12px; opacity: 0.7; margin: 12px 0;">'
                f'{private}</div>')
    else:
        # rows are weekdays: the first column starts on a Monday, padded with
        # blanks, and the last is padded after today. Until 2.9 the grid
        # started wherever the six months did.
        try:
            pad = _date.fromisoformat(str(profile.get("start"))).weekday()
        except (TypeError, ValueError):
            pad = 0
        try:
            first = _date.fromisoformat(str(profile.get("start")))
        except (TypeError, ValueError):
            first = None
        cols = []
        week = [(-1, None, 0)] * pad
        for i, n in enumerate(cells):
            day = (first + _dt.timedelta(days=i)).isoformat() if first else None
            week.append((_heat_level(int(n)), day, int(n)))
            if len(week) == 7:
                cols.append(week)
                week = []
        if week:
            cols.append(week + [(-1, None, 0)] * (7 - len(week)))

        def cell(lvl, day, n):
            # 3.8.0: on my own card, a day I studied opens its cards in Browse
            if you and day and n > 0:
                d = _date.fromisoformat(day)
                return (f'<i class="dchm h{lvl}" title="{d:%a} {d.day} {d:%b} \u00b7 {n:,} review{"s" if n != 1 else ""}. '
                        f'Browse them" onclick="{_pycmd("heatday:" + day)}"></i>')
            return f'<i class="dchm h{lvl if lvl >= 0 else "x"}"></i>'
        col_html = ""
        for col in cols[-26:]:
            col_html += f'<div class="dchc">{"".join(cell(*c) for c in col)}</div>'
        grid = f'<div class="dchg">{col_html}</div>'

    lines = ""
    duet = profile.get("duet")
    if duet:
        short = _html.escape(str(profile.get("name", "?")).split(" ")[0][:10])

        def _drow(label, seq):
            dots = "".join(f'<i class="dcd{"" if on else " off"}"></i>'
                           for on in seq)
            return (f'<div class="dcduet"><span class="dcdl">{label}</span>'
                    f'<span>{dots}</span></div>')

        if duet.get("mine_week") and duet.get("theirs_week"):
            lines += (_drow("You", duet["mine_week"])
                      + _drow(short, duet["theirs_week"]))
        run, best = int(duet.get("run") or 0), int(duet.get("best") or 0)
        if run > 0:
            unit = "day" if run == 1 else "days"
            tail = f" &mdash; best run: {best}." if best > run else "."
            lines += (f'<div style="font-size: 12px; padding: 4px 0 2px;">'
                      f'You two have studied <b>{run} {unit} in a row '
                      f'together</b>{tail}</div>')
        elif best > 1:
            lines += (f'<div style="font-size: 12px; padding: 4px 0 2px;">'
                      f'Best run together: <b>{best} days</b>.</div>')
    if profile.get("same_days") is not None:
        # named by the month the heatmap above starts, so the two agree
        try:
            since = f' since {_date.fromisoformat(str(profile.get("start"))).strftime("%B")}'
        except (TypeError, ValueError):
            since = ""
        n = int(profile["same_days"])
        lines += (f'<div style="font-size: 12px; padding: 2px 0;">'
                  f'You&rsquo;ve both studied on <b>{n} day{"" if n == 1 else "s"}</b>{since}.</div>')
    if profile.get("decks_line"):
        prefix = "Shares with your crew: " if you else "Shares with you: "
        lines += (f'<div style="font-size: 12px; padding: 2px 0; opacity: 0.8;">'
                  f'{prefix}{_html.escape(str(profile["decks_line"]))}</div>')

    if you:
        link = ('style="color: inherit; font-weight: 700; text-decoration: none; '
                'border-bottom: 1px dotted currentColor;"')
        lines += (f'<div style="font-size: 12px; padding: 8px 0 0; opacity: 0.85;">'
                  f'Copy for the chat: <a href="#" {link} '
                  f'onclick="{_pycmd("sharetoday")}">today</a> &middot; '
                  f'<a href="#" {link} onclick="{_pycmd("shareweek")}">week</a> &middot; '
                  f'<a href="#" {link} onclick="{_pycmd("sharemonth")}">month</a> &middot; '
                  f'<a href="#" {link} onclick="{_pycmd("shareyear")}">year</a></div>')

    inner = _json.dumps(head + grid + lines)
    if you:
        act_label, act_primary = _json.dumps("Privacy…"), "false"
        act_cmd = _json.dumps("duecrew:settings:privacy")
    else:
        act_label, act_primary = _json.dumps("\U0001F389 Send a cheer"), "true"
        act_cmd = _json.dumps(f"duecrew:cheerpick:{profile.get('uid', '')}")
    return """
    (function() {
        var old = document.getElementById('dc-profile');
        if (old) { old.remove(); }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        // 2.9: colors come from the board, which already follows Settings ->
        // Theme and Accent; Anki's night class is only the fallback
        var dcBoard = document.getElementById('due-crew');
        var dcStyle = dcBoard ? getComputedStyle(dcBoard) : null;
        function tok(name, light, dark) {
            var v = dcStyle && dcStyle.getPropertyValue('--dc-' + name).trim();
            return v || (night ? dark : light);
        }
        var dcBg = tok('bg', '#ffffff', '#1c1c1c'), dcInk = tok('ink', '#333333', '#dfe1dc'),
            dcLine = tok('line', '#e2e2da', '#3d403b'), dcWell = tok('well', '#f2f2ec', '#2b2d29'),
            accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
            warn = tok('hours', '#b26a00', '#dda45c');
        var back = document.createElement('div');
        back.id = 'dc-profile';
        back.style.cssText = 'position:fixed;inset:0;z-index:80;background:rgba(0,0,0,0.35);' +
            'display:flex;align-items:flex-start;justify-content:center;padding-top:14vh;';
        var card = document.createElement('div');
        card.style.cssText = 'min-width:340px;max-width:420px;border-radius:12px;padding:16px 20px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);' +
            'background:' + dcBg + ';color:' + dcInk + ';border:1px solid ' + dcLine + ';';
        var style = document.createElement('style');
        style.textContent = '.dchg{display:flex;gap:2px;margin:12px 0 8px;}' +
            '.dchc{display:flex;flex-direction:column;gap:2px;}' +
            '.dchm[onclick]{cursor:pointer;}.dchm[onclick]:hover{outline:1px solid ' + accent + ';}' +
            '.dchm{width:8px;height:8px;border-radius:1.5px;display:block;background:' +
            dcWell + ';}' +
            '.dchm.h1{background:' + accent + ';opacity:0.25;}' +
            '.dchm.h2{background:' + accent + ';opacity:0.45;}' +
            '.dchm.h3{background:' + accent + ';opacity:0.7;}' +
            '.dchm.h4{background:' + accent + ';}' +
            '.dchm.hx{visibility:hidden;}' +
            '.dcex{color:' + warn + ';}' +
            '.dcduet{display:flex;align-items:center;gap:8px;padding:1px 0;}' +
            '.dcdl{width:42px;flex-shrink:0;font-size:10px;opacity:0.65;' +
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
            '.dcd{width:9px;height:9px;border-radius:50%%;display:inline-block;' +
            'margin-right:6px;background:' + accent + ';}' +
            '.dcd.off{background:' + dcWell + ';}';
        card.appendChild(style);
        var body = document.createElement('div');
        body.innerHTML = %s;
        card.appendChild(body);
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:8px;margin-top:12px;';
        function btn(label, primary) {
            var b = document.createElement('button');
            b.textContent = label;
            b.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
                (primary ? 'background:' + accent + ';color:' + accentInk +
                           ';border:1px solid transparent;font-weight:600;'
                         : 'background:none;color:inherit;border:1px solid ' +
                           dcLine + ';');
            return b;
        }
        var act = btn(%s, %s);
        act.addEventListener('click', function() {
            back.remove();
            if (typeof pycmd !== 'undefined') { pycmd(%s); }
        });
        var close = btn('Close', false);
        close.addEventListener('click', function() { back.remove(); });
        row.appendChild(act);
        var spacer = document.createElement('div');
        spacer.style.flex = '1';
        row.appendChild(spacer);
        row.appendChild(close);
        card.appendChild(row);
        back.appendChild(card);
        back.addEventListener('click', function(e) {
            if (e.target === back) { back.remove(); }
        });
        document.addEventListener('keydown', function esc(e) {
            if (e.key === 'Escape') { back.remove(); document.removeEventListener('keydown', esc); }
        });
        document.body.appendChild(back);
        if (window.dcMotion) { dcMotion.open(back, card); }  // 3.8.0: from the name, back into it
    })();
    """ % (inner, act_label, act_primary, act_cmd)


# ---- Due: the day's to-do, above the board ----

DUE_CSS = """
    #due-crew .du { text-align: left; border-radius: 12px; padding: 12px 18px; margin: 0 0 14px;
      display: grid; gap: 6px; align-content: start; }
    #due-crew .du > * { min-width: 0; }
    #due-crew .du a { text-decoration: none; }
    #due-crew .du-h { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    @media (max-width: 460px) { #due-crew .du-h > .du-n { display: none; } }  /* Hide stays on the tabs' line */
    #due-crew .du-h .sp { flex: 1; }
    #due-crew .du-n { color: var(--dc-muted); font-size: 11.5px; white-space: nowrap; }
    #due-crew .du-fold { font-size: 11.5px; font-weight: 600; color: var(--dc-muted); white-space: nowrap; flex: none;
      margin-left: auto; }
    #due-crew .du-one .du-fold { color: var(--dc-accent); font-weight: 700; }
    #due-crew .du-tm { overflow: hidden; text-overflow: ellipsis; min-width: 0; flex: 0 1 auto; }
    /* 3.8.0: the box's tabs are words (the board's pills are the buttons): the
       one on screen in ink, underlined; Plans and Insights after a rule */
    #due-crew .du-tabs { display: inline-flex; gap: 14px; white-space: nowrap; }
    #due-crew .du-tabs a { font-size: 12px; font-weight: 700; color: var(--dc-muted); padding: 1px 0 3px; }
    #due-crew .du-tabs a:hover { color: var(--dc-ink); }
    #due-crew .du-tabs a.on { color: var(--dc-ink); box-shadow: inset 0 -2px var(--dc-accent); }
    #due-crew .du-tabs.du-more { padding-left: 14px; border-left: 1px solid var(--dc-line); }
    #due-crew .du-r { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 2px 9px; align-items: start;
      padding: 5px 0 4px; border-top: 1px solid var(--dc-line); }
    #due-crew .du-r .t { display: grid; gap: 2px; min-width: 0; overflow-wrap: anywhere; }
    #due-crew .du-r .t small, #due-crew .du-m { color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .du-r.done .t > b, #due-crew .du-r.done .t > span.x { color: var(--dc-muted); text-decoration: line-through; }
    #due-crew .du-r .end { display: flex; gap: 10px; align-items: baseline; white-space: nowrap; font-size: 11.5px; }
    #due-crew .du-r .end .n { color: var(--dc-muted); font-variant-numeric: tabular-nums; }
    #due-crew .du-go { color: var(--dc-accent); font-weight: 700; font-size: 11.5px; white-space: nowrap; }
    #due-crew .du-go .nm { display: inline-block; max-width: 160px; overflow: hidden; text-overflow: ellipsis; vertical-align: bottom; }
    #due-crew .du-tag { color: var(--dc-muted); font-size: 11px; white-space: nowrap; }
    #due-crew .du-tag:hover { color: var(--dc-ink); }
    #due-crew .du-bx { box-sizing: border-box; width: 14px; height: 14px; border: 1.5px solid var(--dc-faded);
      border-radius: 4px; margin-top: 2px; display: block; position: relative; }
    #due-crew a.du-bx { cursor: pointer; }
    #due-crew .du-bx.auto { border-style: dashed; }
    #due-crew .du-bx.part { background: linear-gradient(90deg, var(--dc-you-bg) 50%, transparent 50%); border-color: var(--dc-accent); }
    #due-crew .du-bx.on { background: var(--dc-accent); border: 1.5px solid var(--dc-accent); }
    #due-crew .du-bx.on::after { content: ""; position: absolute; left: 3.5px; top: 0.5px; width: 3px; height: 7px;
      border: solid var(--dc-accent-ink); border-width: 0 2px 2px 0; transform: rotate(45deg); }
    #due-crew .du-sub { display: grid; grid-template-columns: 12px minmax(0, 1fr) auto; gap: 7px; align-items: center;
      font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .du-sub b { color: var(--dc-ink); font-weight: 600; }
    #due-crew .du-sub .du-bx { width: 11px; height: 11px; margin: 0; border-radius: 3px; }
    #due-crew .du-sub .du-bx.on::after { left: 2.5px; top: -0.5px; width: 2.5px; height: 6px; }
    #due-crew .du-sub .n { font-variant-numeric: tabular-nums; white-space: nowrap; }
    #due-crew .du-rm { display: block; color: var(--dc-muted); font-size: 11.5px; font-style: italic; text-align: left; }
    #due-crew .du .wbar { margin-top: 3px; }
    #due-crew .du-sec { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-muted); padding-top: 4px; }
    #due-crew .du-sec.warn { color: #c77700; }
    #due-crew .du-bh { display: grid; gap: 0; padding-bottom: 8px; }
    #due-crew .du-line { display: flex; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap; font-size: 12px;
      padding: 5px 0 1px; border-top: 1px solid var(--dc-line); color: var(--dc-muted); }
    #due-crew .du-line b { color: var(--dc-ink); font-weight: 600; }
    #due-crew .du-line .acts { display: flex; gap: 12px; }
    #due-crew .du-line a, #due-crew .du-sg a { color: var(--dc-accent); font-weight: 700; }
    #due-crew .du-line a.tp { font-weight: inherit; }
    #due-crew .du-sg { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 9px; font-size: 12px;
      padding: 5px 0; border-top: 1px solid var(--dc-line); align-items: baseline; }
    #due-crew .du-sg .x { color: var(--dc-muted); font-weight: 400; margin-left: 10px; }
    #due-crew .du-add { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; padding-top: 3px; }
    #due-crew .du-add input[type=text] { flex: 1 1 160px; min-width: 0; font: inherit; font-size: 12.5px; color: var(--dc-ink);
      background: var(--dc-bg); border: 1px solid var(--dc-line); border-radius: 7px; padding: 4px 8px; }
    #due-crew .du-add select, #due-crew .du-add input[type=date] { font: inherit; font-size: 12px; color: var(--dc-ink);
      background: var(--dc-bg); border: 1px solid var(--dc-line); border-radius: 7px; padding: 3px 4px; color-scheme: light dark; }
    #due-crew .du-said { font-size: 11.5px; color: var(--dc-accent); font-weight: 700; white-space: nowrap; }
    #due-crew .du-said a { color: var(--dc-muted); font-weight: 400; margin-left: 4px; }
    #due-crew .du-dh { display: flex; justify-content: space-between; gap: 10px; font-size: 11.5px; font-weight: 700;
      padding-top: 6px; border-top: 1px solid var(--dc-line); }
    #due-crew .du-dh.today { color: var(--dc-accent); }
    #due-crew .du-dh small { color: var(--dc-muted); font-weight: 400; }
    #due-crew .du-dh .plus { color: var(--dc-accent); font-weight: 700; margin-left: 8px; }
    #due-crew .du-ln { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 9px; font-size: 12px;
      padding: 2px 0; align-items: start; }
    #due-crew .du-ln .n { color: var(--dc-muted); font-size: 11px; white-space: nowrap; }
    #due-crew .du-ln.done > span:nth-child(2) { color: var(--dc-muted); text-decoration: line-through; }
    #due-crew .du-q { color: var(--dc-faded); font-size: 11.5px; padding: 3px 0 3px 25px; }
    #due-crew .du-evl { color: #c77700; font-weight: 700; font-size: 12px; padding-left: 25px; }
    #due-crew .du-one { display: flex; align-items: center; gap: 6px 12px; padding: 10px 18px; white-space: nowrap; }
    #due-crew .du-one > * { flex: none; }
    #due-crew .du-one .wbar { flex: 0 1 90px; width: auto; min-width: 24px; margin: 0; }
    #due-crew .du-one .sp { flex: 1 1 0; }
    #due-crew .du-one .sp { flex: 1; }
    #due-crew .du-one > a:first-child b { color: var(--dc-accent); font-size: 12.5px; }
    #due-crew .du-one .du-go { flex: 0 1 auto; min-width: 0; max-width: 260px; display: inline-flex; }
    #due-crew .du-one .du-go .nm { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
    /* what's next when the day's done: the one part that gives way (else it
       ran past the box and took Show with it) */
    #due-crew .du-one .du-tm { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
    /* narrow: the bar goes and "Study ›" keeps its words (it was squeezed to
       nothing and Show spilled out of the box) */
    @media (max-width: 480px) { #due-crew .du-one .du-go .nm { display: none; }
      #due-crew .du-one .wbar { display: none; } #due-crew .du-one .du-go { min-width: auto; } }
    /* narrower still, there's more than one line holds: it wraps */
    @media (max-width: 400px) { #due-crew .du-one { flex-wrap: wrap; } }
    #due-crew .du-sub a { color: var(--dc-accent); }
    #due-crew .du-empty { color: var(--dc-muted); font-size: 12px; padding: 4px 0; }
"""

DUE_JS = r"""
(function () {
  if (window.dcDue) { return; }
  var DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
  var LONG = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];
  var MONTHS = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august',
    'september', 'october', 'november', 'december'];
  function day(iso) { var p = iso.split('-'); return new Date(Date.UTC(+p[0], +p[1] - 1, +p[2])); }
  function iso(d) { return d.toISOString().slice(0, 10); }
  function plus(iso0, n) { var d = day(iso0); d.setUTCDate(d.getUTCDate() + n); return iso(d); }
  function month(w) {
    w = w.replace(/\.$/, '');
    for (var i = 0; i < 12; i++) { if (w.length >= 3 && MONTHS[i].indexOf(w) === 0) { return i + 1; } }
    return 0;
  }
  function onOrAfter(today, m, dd) {
    var y = +today.slice(0, 4);
    for (var k = 0; k < 2; k++) {
      var d = new Date(Date.UTC(y + k, m - 1, dd));
      if (d.getUTCMonth() !== m - 1) { return null; }
      if (iso(d) >= today) { return iso(d); }
    }
    return null;
  }
  // due.when_word, restated for the add line's preview: change one, change both
  function when(w, today) {
    w = w.toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
    if (w === 'today' || w === 'tonight') { return today; }
    if (w === 'tomorrow' || w === 'tmrw' || w === 'tmr') { return plus(today, 1); }
    if (w === 'later' || w === 'someday' || w === 'sometime') { return ''; }
    var wd = (day(today).getUTCDay() + 6) % 7;
    if (w === 'next week') { return plus(today, 7 - wd); }
    var pre = ['next ', 'on ', ''];
    for (var i = 0; i < pre.length; i++) {
      if (w.indexOf(pre[i]) === 0) {
        var name = w.slice(pre[i].length);
        for (var j = 0; j < 7; j++) {
          if (name.length >= 3 && LONG[j].indexOf(name) === 0) {
            var ahead = ((j + 6) % 7 - wd + 7) % 7 || 7;
            return plus(today, ahead);
          }
        }
      }
    }
    var m = w.match(/^([0-9]{1,2})(?:st|nd|rd|th)? ([a-z]{3,9}\.?)$/);
    if (m && month(m[2])) { return onOrAfter(today, month(m[2]), +m[1]); }
    m = w.match(/^([a-z]{3,9}\.?) ([0-9]{1,2})(?:st|nd|rd|th)?$/);
    if (m && month(m[1])) { return onOrAfter(today, month(m[1]), +m[2]); }
    return null;
  }
  function parse(text, today) {
    var words = text.replace(/\s+/g, ' ').trim().split(' ');
    for (var n = 3; n >= 1; n--) {
      if (words.length > n) {
        var d = when(words.slice(-n).join(' '), today);
        if (d !== null) {
          var rest = words.slice(0, -n).join(' ').replace(/[ ,\-·]+$/, '');
          if (rest) { return { text: rest, day: d }; }
        }
      }
    }
    return { text: words.join(' '), day: null };
  }
  // due.repeat_word and due.parse_repeat (3.8.0), restated: change one, change both
  var WEEK = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];
  function repeatWord(w) {
    w = w.toLowerCase().replace(/,/g, ' ').replace(/\s+/g, ' ').trim();
    if (w === 'daily' || w === 'every day' || w === 'each day') { return '0123456'; }
    if (w === 'weekdays' || w === 'every weekday' || w === 'each weekday') { return '01234'; }
    if (w.slice(-1) === 's' && WEEK.indexOf(w.slice(0, -1)) >= 0) { return String(WEEK.indexOf(w.slice(0, -1))); }
    var m = w.match(/^(?:every|each) ([a-z ]+)$/);
    if (!m) { return null; }
    var on = {}, names = m[1].split(' ');
    for (var i = 0; i < names.length; i++) {
      if (names[i] === 'and') { continue; }
      var k = -1;
      for (var j = 0; j < 7; j++) { if (names[i].length >= 3 && WEEK[j].indexOf(names[i]) === 0) { k = j; break; } }
      if (k < 0) { return null; }
      on[k] = 1;
    }
    var out = '';
    for (var x = 0; x < 7; x++) { if (on[x]) { out += x; } }
    return out || null;
  }
  function parseRepeat(text) {
    var t = text.replace(/\s+/g, ' ').trim();
    var m = t.match(/^([^:]{3,40}):\s*(.+)$/);
    if (m) { var r0 = repeatWord(m[1]); if (r0) { return { text: m[2], rule: r0 }; } }
    var words = t.split(' ');
    for (var n = Math.min(6, words.length - 1); n >= 1; n--) {
      var r = repeatWord(words.slice(-n).join(' '));
      if (r) {
        var rest = words.slice(0, -n).join(' ').replace(/[ ,\-·:]+$/, '');
        if (rest) { return { text: rest, rule: r }; }
      }
    }
    return { text: t, rule: null };
  }
  function repeatLabel(r) {
    if (r === '0123456') { return 'every day'; }
    if (r === '01234') { return 'weekdays'; }
    var out = [];
    for (var i = 0; i < r.length; i++) { var n = WEEK[+r.charAt(i)]; out.push(n.charAt(0).toUpperCase() + n.slice(1, 3)); }
    return 'every ' + out.join(', ');
  }
  function label(d, today) {
    if (d === '') { return 'Later'; }
    if (d === today) { return 'Today'; }
    if (d === plus(today, 1)) { return 'Tomorrow'; }
    var x = day(d);
    return DAYS[x.getUTCDay()].charAt(0).toUpperCase() + DAYS[x.getUTCDay()].slice(1) + ' ' + x.getUTCDate() + ' ' +
      MONTHS[x.getUTCMonth()].charAt(0).toUpperCase() + MONTHS[x.getUTCMonth()].slice(1, 3);
  }
  function el(id) { return document.getElementById(id); }
  window.dcDue = {
    raw: false,
    preview: function () {
      var box = document.querySelector('#due-crew .du'), inp = el('du-in'), said = el('du-said');
      if (!box || !inp || !said) { return; }
      var rp = parseRepeat(inp.value);
      var p = rp.rule ? null : parse(inp.value, box.getAttribute('data-today'));
      if ((!rp.rule && p.day === null) || this.raw) { said.innerHTML = ''; return; }
      said.innerHTML = '&rarr; ' + (rp.rule ? repeatLabel(rp.rule) : label(p.day, box.getAttribute('data-today'))) +
        '<a href="#" title="Keep the words as text" onclick="dcDue.raw=true;dcDue.preview();return false;">&times;</a>';
    },
    pick: function () {
      var sel = el('du-when'), dt = el('du-date');
      if (sel && dt) { dt.style.display = sel.value === 'pick' ? '' : 'none'; if (sel.value === 'pick') { dt.focus(); } }
    },
    key: function (e) {
      if (e.key === 'Enter') { e.preventDefault(); this.send(); return; }
      if (e.key === 'Escape') { e.target.value = ''; this.raw = false; this.preview(); }
    },
    send: function () {
      var inp = el('du-in'), sel = el('du-when'), dt = el('du-date');
      if (!inp || !inp.value.trim()) { return; }
      var w = sel ? sel.value : 'today';
      if (w === 'pick') { w = (dt && dt.value) ? dt.value : 'today'; }
      if (window.dcMotion) {  // 3.8.0: the redraw shows where it went
        var r = inp.getBoundingClientRect();
        dcMotion.say({add: inp.value.trim().slice(0, 16), when: w, from: {x: r.left, y: r.top}});
      }
      pycmd('duecrew:dueadd:' + w + ':' + (this.raw ? 1 : 0) + ':' + encodeURIComponent(inp.value));
      this.raw = false;
      inp.value = '';  // sent: a redraw doesn't put it back (swap_js keeps a half-typed one)
    },
    plus: function (d) {
      var sel = el('du-when'), dt = el('du-date'), inp = el('du-in');
      if (!sel || !inp) { return; }
      var found = false;
      for (var i = 0; i < sel.options.length; i++) { if (sel.options[i].value === d) { found = true; } }
      if (found) { sel.value = d; if (dt) { dt.style.display = 'none'; } }
      else { sel.value = 'pick'; if (dt) { dt.value = d; dt.style.display = ''; } }
      inp.focus();
    }
  };
})();
"""


def _due_box(state, auto=True):
    cls = "du-bx" + (" auto" if auto else "") + (" on" if state == "on" else " part" if state == "part" else "")
    return f'<span class="{cls}"></span>'


def _due_tick(cmd, on, label):
    return (f'<a href="#" class="du-bx{" on" if on else ""}" role="checkbox" aria-checked="{"true" if on else "false"}" '
            f'title="{_html.escape(label)}" aria-label="{_html.escape(label)}" onclick="{_pycmd(cmd)}"></a>')


def _due_mine(r, short=False):
    e = _html.escape
    tick = _due_tick("duetick:" + r["id"], r["done"], "Done" if not r["done"] else "Not done")
    if r.get("ahead"):
        tick = '<span class="du-bx"></span>'  # 3.8.0: a repeat's next day ticks on that day
    tag = f'<a href="#" class="du-tag" title="Move, edit or delete" onclick="{_pycmd("dueitem:" + r["id"])}">{e(r["tag"])} &#9662;</a>'
    if short:
        return (f'<div class="du-ln{" done" if r["done"] else ""}">{tick}<span>{e(r["text"])}</span>'
                f'<span class="n">{tag}</span></div>')
    do = (f'<a href="#" class="du-go" onclick="{_pycmd("duedo:" + r["id"])}">Do today</a>'
          if not r["day"] and not r["done"] else "")
    return (f'<div class="du-r{" done" if r["done"] else ""}">{tick}<span class="t"><span class="x">{e(r["text"])}</span></span>'
            f'<span class="end">{do}{tag}</span></div>')


def _due_every(r, short=False):
    """3.8.0: a plan's weekly line ("Do · Practice questions", every Fri),
    ticked by hand for the day; a day ahead's ticks on that day."""
    e = _html.escape
    text = e(r["text"])
    if r.get("url", "").startswith("https://"):
        text = f'<a href="#" title="{e(r["url"])}" onclick="{_pycmd("duelink:" + r["key"])}">{text}</a>'
    tick = ('<span class="du-bx"></span>' if r.get("ahead")
            else _due_tick(f'duetodo:{r["key"]}', r["done"], "Done" if not r["done"] else "Not done"))
    if short:
        return (f'<div class="du-ln{" done" if r["done"] else ""}">{tick}<span><b>{e(r["label"])}</b> &middot; {text}'
                f' <span class="du-m">&middot; {e(r["plan"])}</span></span><span class="n">{e(r["tag"])}</span></div>')
    return (f'<div class="du-r{" done" if r["done"] else ""}">{tick}<span class="t"><span class="x"><b>{e(r["label"])}</b> '
            f'&middot; {text}</span><small>{e(r["plan"])} &middot; {e(r["tag"])}</small></span><span class="end"></span></div>')


def _due_plan(r):
    """A plan's date on Today, in full: its resources (each with its topics,
    3.8.0), the author's lines, its bar."""
    e = _html.escape
    box = _due_box("on" if r["done"] else "part" if r["part"] else "", auto=True)
    groups, used = list(r.get("topics") or []), set()

    def topics_of(label):
        # a resource's topics on its own row (P.parts groups as P.topics does; no resource is "Other")
        for k, (g, xs) in enumerate(groups):
            if k not in used and (g == label or (label == "Other" and not g)):
                used.add(k)
                return (" &middot; " + ", ".join(_topic_a(r["pid"], r["uid"], x, i) for x, i in xs)
                        + _remark_lines(xs, r.get("rm"), "du-rm"))  # 3.8.1: the authors' notes under it
        return ""
    subs = ""
    for ln in r["lines"]:
        if ln["kind"] == "part":
            subs += (f'<span class="du-sub"><span class="du-bx auto{" on" if ln["done"] else ""}"></span>'
                     f'<span><b>{e(ln["label"])}</b>{topics_of(ln["label"])}</span>'
                     f'<span class="n">{int(ln["seen"]):,} / {int(ln["total"]):,}</span></span>')
        else:
            text = e(ln["text"])
            if ln.get("url", "").startswith("https://"):
                # opened by Anki in the browser, never inside the Decks screen
                text = f'<a href="#" title="{e(ln["url"])}" onclick="{_pycmd("duelink:" + ln["key"])}">{text}</a>'
            tick = (_due_tick(f'duetodo:{ln["key"]}', ln["done"], "Done") if ln["can"]
                    else '<span class="du-bx"></span>')
            subs += (f'<span class="du-sub">{tick}<span><b>{e(ln["label"])}</b> &middot; {text}</span>'
                     f'<span class="n">by hand</span></span>')
    extra = []
    if r.get("prep"):
        extra.append(f'{"after" if r.get("after") else "for"} {e(r["prep"])}')  # 3.8.1: after its event, reinforcement
    if r.get("crew") and int(r["crew"][1]) > 1:
        extra.append(f'crew {int(r["crew"][0]):,} of {int(r["crew"][1]):,} done')
    if r.get("upd"):
        # 3.7.3: an author's update adds to this date; it opens when I say
        said = f'+{int(r["upd"]):,} added' if int(r["upd"]) > 0 else "updated"
        extra.append(f'{said} &middot; <a href="#" onclick="{_pycmd("planupdopen:" + r["pid"])}">Open</a>')
    meta = " &middot; ".join([f'{e(r["plan"])}'] + extra)
    rest = [(g, xs) for k, (g, xs) in enumerate(groups) if k not in used]
    if rest:  # 3.8.0: each topic opens its cards in Browse
        # as the Plans tab's day writes them: the group in bold, then its topics
        what = "<small>" + " &middot; ".join((f"<b>{e(str(g))}</b> &middot; " if g else "") + ", ".join(_topic_a(r["pid"], r["uid"], x, i) for x, i in xs)
                                              for g, xs in rest) + "</small>"
        what += "".join(_remark_lines(xs, r.get("rm"), "du-rm") for _g, xs in rest)  # 3.8.1
    elif groups:
        what = ""
    else:
        what = f'<small>{e(r["what"])}</small>' if r.get("what") else ""
    bar = _wbar(r["seen"], r["total"]) if r["total"] and not r["done"] else ""
    go = ""  # 3.8.0: one Study, the box's Study today (its first step is this plan's deck)
    if r.get("study"):  # 3.8.1: but a plan's date with cards open has its own: a cram of just it
        cmd = _pycmd(f"planstudydate:{r['pid']}:{r['uid']}")
        go = (f'<a href="#" class="du-go" title="A Due Crew deck of its open cards, new and review, in random order" '
              f'onclick="{cmd}">Study</a>')
    n = f'<span class="n">{e(r["n"])}</span>' if r["n"] else ""
    return (f'<div class="du-r{" done" if r["done"] else ""}">{box}<span class="t"><b>{e(r["name"])}</b>'
            f'<small>{meta}</small>{what}{subs}{bar}</span><span class="end">{n}{go}</span></div>')


def _due_short(r):
    e = _html.escape
    if r["kind"] == "mine":
        return _due_mine(r, short=True)
    if r["kind"] == "every":
        return _due_every(r, short=True)
    box = _due_box("on" if r["done"] else "part" if r["part"] else "", auto=True)
    return (f'<div class="du-ln{" done" if r["done"] else ""}">{box}<span><b>{e(r["name"])}</b>'
            f' <span class="du-m">&middot; {e(r["plan"])}</span></span><span class="n">{e(r["n"])}</span></div>')


def _due_behind(v):
    e = _html.escape
    if not v["behind_n"]:
        return ""
    out = '<div class="du-bh"><div class="du-sec warn">Behind</div>'
    for p in v["behind_plans"]:
        left = int(p["left"])
        what = f'{int(p["dates"])} date{"s" if p["dates"] != 1 else ""}' + (
            f' &middot; <a class="tp" href="#" title="Browse them" onclick="{_pycmd("planleft:" + p["pid"])}">{left:,} cards to see</a>'
            if left else "")
        out += (f'<div class="du-r">{_due_box("", auto=True)}<span class="t"><b>{e(p["plan"])}</b><small>{what}</small></span>'
                f'<span class="end"><a href="#" class="du-go" onclick="{_pycmd("plancatch:" + p["pid"])}">Catch up&hellip;</a></span></div>')
    out += "".join(_due_mine(r) for r in v["behind_mine"])
    if v["behind_more"]:
        out += f'<div class="du-q">and {int(v["behind_more"])} more</div>'
    return out + "</div>"


def _due_add(v, default):
    """The add line: a day button beside it, a day said at the end shown before Enter."""
    today = v["today"]
    t = _dt.date.fromisoformat(today)
    opts = [("today", "Today"), ((t + _dt.timedelta(days=1)).isoformat(), "Tomorrow")]
    opts += [((t + _dt.timedelta(days=i)).isoformat(), f"{t + _dt.timedelta(days=i):%a}") for i in range(2, 7)]
    opts += [("later", "Later"), ("pick", "Pick a day…")]
    sel = "".join(f'<option value="{k}"{" selected" if k == default else ""}>{lb}</option>' for k, lb in opts)
    maxd = (t + _dt.timedelta(days=730)).isoformat()
    full = ' disabled placeholder="60 open: tick or delete some first"' if v.get("full") else ' placeholder="Add a to-do…"'
    return (f'<div class="du-add"><input type="text" id="du-in" maxlength="140" aria-label="Add a to-do"{full} '
            f'onkeydown="dcDue.key(event)" oninput="dcDue.preview()">'
            f'<span class="du-said" id="du-said"></span>'
            f'<select id="du-when" aria-label="Its day" onchange="dcDue.pick()">{sel}</select>'
            f'<input type="date" id="du-date" min="{today}" max="{maxd}" style="display:none" aria-label="Pick a day">'
            f'<a href="#" class="du-go" onclick="dcDue.send();return false;">Add</a></div>')


# 3.8.0: the two keys as this computer writes them (a Mac: Command for Study, Control for Ask, __init__.py)
STUDY_KBD, ASK_KBD = ("⌘⇧S", "⌃⇧Q") if _sys.platform == "darwin" else ("Ctrl+Shift+S", "Ctrl+Shift+Q")
def _study_to(v):
    """3.8.0 (Board in Motion, 35): the deck Study today opens first, named
    on the button (due_flow works it out from Anki's deck tree)."""
    to = v.get("study_to")
    return f' <span class="nm">{_html.escape(str(to))}</span>' if to else ""


STUDY_TIP = f"Each deck with cards due, your plans&rsquo; first ({STUDY_KBD})"


def _due_html(v, more=(), more_tab=None, more_body="", folded=None):
    """The You bubble (3.8.0; Due above the board until then): Due's lists,
    Today, Upcoming and Later, when Due is on (v: due.view, from
    due_flow.view), then `more`, [(key, label)] (Plans, Insights), with
    `more_tab` picked and `more_body` drawn. Every string in v is escaped
    here; `more_body` comes drawn. folded: when there are no lists to say
    it (Due off)."""
    if not v and not more:
        return ""
    e = _html.escape
    if not v:
        # Due's lists off: Plans and Insights only, folded or not
        if folded:
            names = " &middot; ".join(lb for _k, lb in more)
            return (f'<div class="du du-one"><a href="#" onclick="{_pycmd("duefold")}" title="Show"><b>{names}</b></a>'
                    f'<span class="sp"></span><a href="#" class="du-fold" title="Show" '
                    f'onclick="{_pycmd("duefold")}">Show &#9662;</a></div>')
        tab = more_tab if more_tab in dict(more) else more[0][0]
        tabs = "".join(f'<a href="#" role="tab" aria-selected="{"true" if k == tab else "false"}" class="{"on" if k == tab else ""}" onclick="{_pycmd("duetab:" + k)}">{lb}</a>'
                       for k, lb in more)
        return (f'<div class="du"><div class="du-h"><span class="du-tabs" role="tablist" aria-label="You">{tabs}</span>'
                f'<span class="sp"></span><a href="#" class="du-fold" title="Fold to one line" '
                f'onclick="{_pycmd("duefold")}">Hide &#9652;</a></div>{more_body}</div>')
    today = e(v["today"])
    done_n, total_n = int(v["done_n"]), int(v["total_n"])
    count = f"{done_n} of {total_n} done" if total_n else ""
    if v["folded"]:
        bar = _wbar(done_n, total_n) if total_n else ""
        # 3.8.0: Study today walks the day (the plans' decks first), as the box's
        go = (f'<a href="#" class="du-go" title="{STUDY_TIP}" onclick="{_pycmd("duestudy")}">'
              f'Study today &rsaquo;{_study_to(v)}</a>' if v.get("study") else "")
        behind = f'<span class="du-n" style="color:#c77700">{int(v["behind_n"])} behind</span>' if v["behind_n"] else ""
        if v.get("done"):
            # the day's done: what's next, in place of the bar
            nxt = v["tomorrow"][:2] or (v["next"]["names"][:2] if v.get("next") else [])
            count, bar, go = "&#10003; Done for today", "", (
                f'<span class="du-n du-tm" title="{", ".join(e(x) for x in nxt)}">'
                f'{"Tomorrow" if v["tomorrow"] else e(v["next"]["day"])}: '
                f'{", ".join(e(x) for x in nxt)}</span>' if nxt else "")
        return (f'<div class="du du-one" data-today="{today}"><a href="#" onclick="{_pycmd("duefold")}" title="Show">'
                f'<b>{e(v["name"])}</b></a><span class="du-n">{count or "nothing today"}</span>{bar}{behind}'
                f'<span class="sp"></span>{go}<a href="#" class="du-fold" title="Show the whole list" '
                f'onclick="{_pycmd("duefold")}">Show &#9662;</a></div>')
    tab = more_tab if more_tab in dict(more) else v["tab"]
    # 3.8.0: Later shows only when it holds something; adding one shows it
    lists = (("today", "Today"), ("upcoming", "Upcoming")) + (
        (("later", f'Later{" " + str(v["later_n"]) if v["later_n"] else ""}'),) if v["later"] else ())
    if tab not in dict(lists) and tab not in dict(more):
        tab = "today"
    tabs = "".join(
        f'<a href="#" role="tab" aria-selected="{"true" if k == tab else "false"}" class="{"on" if k == tab else ""}" onclick="{_pycmd("duetab:" + k)}">{lb}</a>'
        for k, lb in lists)
    if more:
        # 3.8.0: Plans and Insights, after a gap: what's mine beyond the day
        tabs += '</span><span class="du-tabs du-more" role="tablist" aria-label="Plans and Insights">' + "".join(
            f'<a href="#" role="tab" aria-selected="{"true" if k == tab else "false"}" class="{"on" if k == tab else ""}" onclick="{_pycmd("duetab:" + k)}">{lb}</a>' for k, lb in more)
    study = (f'<a href="#" class="du-go" title="{STUDY_TIP}" onclick="{_pycmd("duestudy")}">Study today &rsaquo;{_study_to(v)}</a>'
             if tab == "today" and v.get("study") else "")
    if v.get("done") and tab == "today":
        count = "&#10003; Done for today"  # 3.8.0: as the folded line says it (and motion.js lights the box once)
    head = (f'<div class="du-h"><span class="du-tabs" role="tablist" aria-label="{e(v["name"])}">{tabs}</span>'
            f'<span class="sp"></span><span class="du-n">{count if tab in ("today", "upcoming") else ""}</span>{study}'
            f'<a href="#" class="du-fold" title="Fold to one line" onclick="{_pycmd("duefold")}">Hide &#9652;</a></div>')
    if tab in dict(more):
        return f'<div class="du" data-today="{today}">{head}{more_body}</div>'

    toast = ""
    if v.get("toast"):
        toast = (f'<div class="du-line"><span>{e(v["toast"]["text"])}</span>'
                 f'<a href="#" onclick="{_pycmd("dueshow:" + v["toast"]["tab"])}">Show</a></div>')
    body = ""
    if tab == "today":
        if v.get("nudge"):
            # 3.8.1: once a day, past my usual start, nothing studied yet: Fifteen?
            peek = f'<span class="nz">{v["nudge_sev"]}</span>' if v.get("nudge_sev") else "<span>&#9654;</span>"
            body += (f'<div class="du-nudge">{peek}<span><b>Not started yet today.</b> Fifteen?</span>'
                     f'<span><a href="#" class="du-go" title="Fifteen minutes, then one question" onclick="{_pycmd("room15")}">Start</a>'
                     f'<a href="#" class="x" title="Not today" onclick="{_pycmd("duex:fifteen")}">&times;</a></span></div>')
        body += _due_behind(v)
        for r in v["rows"]:
            if r["kind"] == "reviews":
                back = int(r.get("back") or 0)
                if not r["due"] and not r["done"] and not back:
                    continue
                n = ("all done" if r["done"] else f'{int(r["due"]):,} due' if r["due"]
                     else f'{back:,} back{" at " + e(r["at"]) if r.get("at") else " later"}')
                body += (f'<div class="du-r{" done" if r["done"] else ""}">{_due_box("on" if r["done"] else "")}'
                         f'<span class="t"><b>Reviews</b></span><span class="end"><span class="n">{n}</span></span></div>')
            elif r["kind"] == "plan":
                body += _due_plan(r)
            elif r["kind"] == "every":
                body += _due_every(r)
            else:
                body += _due_mine(r)
        body += _opened_line(v.get("opened"))
        for sg in v["suggestions"] + v["notes"]:
            body += (f'<div class="du-sg"><span>&#10022;</span><span>{e(sg["text"])}</span><span>'
                     f'<a href="#" onclick="{_pycmd("duego:" + sg["key"])}">{e(sg["go"])}</a>'
                     f'<a href="#" class="x" title="Not today" onclick="{_pycmd("duex:" + sg["key"])}">&times;</a></span></div>')
        if not v["rows"] and not v["suggestions"] and not v["notes"]:
            body += '<div class="du-empty">Nothing due today.</div>'
        body += _due_add(v, "today")
    elif tab == "upcoming":
        for dd in v["days"]:  # 3.8.0: Behind is Today's alone
            if dd.get("quiet"):
                body += f'<div class="du-q">{e(dd["label"])} &middot; nothing due</div>'
                continue
            what = "review day" if dd["review"] and not dd["n"] else ""  # 3.8.0: its rows are the count
            plus = (f'<a href="#" class="plus" title="Add a to-do for this day" '
                    f'onclick="dcDue.plus(\'{e(dd["day"])}\');return false;">+</a>')
            body += (f'<div class="du-dh{" today" if dd["today"] else ""}"><span>{e(dd["head"])}</span>'
                     f'<small>{what}{plus}</small></div>')
            body += "".join(_due_short(r) for r in dd["rows"])
            body += "".join(f'<div class="du-evl">&#9733; {e(n)}</div>' for n in dd["events"])
        body += _due_add(v, "today")
    else:
        if v["later"]:
            body += "".join(_due_mine(r) for r in v["later"])
        else:
            body += '<div class="du-empty">Nothing here.</div>'
        body += _due_add(v, "later")
    return f'<div class="du" data-today="{today}">{head}{toast}{body}</div>'
