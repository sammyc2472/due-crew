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
import re as _re
import time
from datetime import date as _date, datetime, timezone

from .logo import board_mark
from . import room_model
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
PERIODS = ("today", "week", "decks", "squads", "plans")
# 3.5.0: tabs a person can hide in Settings (per computer); Today always shows
HIDEABLE_TABS = (("week", "Week"), ("decks", "Decks"), ("squads", "Squads"), ("plans", "Plans"))


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


def _theme_css(cfg):
    theme = cfg.get("theme", "auto")
    accent = cfg.get("accent", DEFAULT_ACCENT)
    light, dark = palette("light", accent), palette("dark", accent)
    if theme == "light":
        return f"#due-crew {{ {_token_block(light)} }}"
    if theme == "dark":
        return f"#due-crew {{ {_token_block(dark)} }}"
    night = ", ".join(f"{sel} #due-crew" for sel in NIGHT_SELECTORS)
    return (f"#due-crew {{ {_token_block(light)} }}\n"
            f"    @media (prefers-color-scheme: dark) {{ #due-crew {{ {_token_block(dark)} }} }}\n"
            f"    {night} {{ {_token_block(dark)} }}")


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
KEEP_LINE = ("Kept while you use it: after 12 months with no activity (24 when paused), "
             "your account is deleted with everything in it. Opening Anki counts.")


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
    return (f'<tr class="qfold"><td class="rk"></td><td class="nm" colspan="{len(HEADERS) + 2}">'
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


def _full_crew_days(entries, labels):
    """Days on which every non-paused member studied. 0 for solo boards."""
    active = [e for e in entries if not e.get("paused")]
    if len(active) < 2:
        return 0
    return sum(1 for lb in labels
               if all(_showed((e.get("days") or {}).get(lb)) for e in active))


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


def _exam_badge(iso, today_label):
    txt = _exam_text(iso, today_label)
    if not txt:
        return ""
    return f' <span class="exb">&#128214; {_html.escape(txt)}</span>'


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
    #due-crew th {{ padding: 2px 8px 6px; text-align: right; }}
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
    #due-crew td.chc {{ width: 22px; padding-left: 2px; padding-right: 2px; text-align: center; }}
    #due-crew a.dc-cheer {{ text-decoration: none; opacity: 0.3; font-size: 12px; }}
    #due-crew a.dc-cheer:hover {{ opacity: 1; }}
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
    #due-crew .dc-foot a.pb.warn {{ border-color: var(--dc-hours); color: var(--dc-hours); }}
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
      text-decoration: none; font-weight: 700; font-size: 10.5px; }}
    #due-crew .dc-wrap .wx {{ color: var(--dc-muted);
      text-decoration: none; font-weight: 700; }}
    #due-crew .dc-delta {{ font-size: 10px; font-weight: 700; color: var(--dc-accent);
      margin-left: 6px; }}
    #due-crew th .hi {{ display: none; }}
    #due-crew .chip {{ font-size: 10px; margin-left: 5px; white-space: nowrap; color: var(--dc-muted); }}
    #due-crew .chip.live {{ color: var(--dc-fresh); font-weight: 700; }}
    #due-crew .chip.exam {{ color: var(--dc-hours); font-weight: 700; }}
    #due-crew .exb {{ font-size: 10px; font-weight: 700; color: var(--dc-hours);
      margin-left: 5px; white-space: nowrap; }}
    #due-crew .bkb {{ font-size: 10px; font-weight: 700; color: var(--dc-accent);
      margin-left: 5px; white-space: nowrap; }}
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
    #due-crew .dr {{ display: flex; align-items: center; gap: 10px; padding: 3px 0; font-size: 12px; }}
    #due-crew .dr.me .dn {{ font-weight: 700; }}
    #due-crew .dn {{ width: 90px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; }}
    #due-crew .dtrack {{ position: relative; flex: 1; min-width: 70px; height: 12px; background: var(--dc-well);
      border: 1px solid var(--dc-line); border-radius: 2px; overflow: hidden; }}
    #due-crew .dtrack i {{ position: absolute; left: 0; top: 0; bottom: 0; display: block; }}
    #due-crew .dtrack .fo {{ opacity: 0.5; background: repeating-linear-gradient(
      135deg, var(--dc-accent) 0 1.5px, transparent 1.5px 5px); }}
    #due-crew .dtrack .fs {{ background: var(--dc-accent); opacity: 0.35; }}
    #due-crew .dtrack .fm {{ background: var(--dc-accent); }}
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
    #due-crew .dc-sw a.on {{ color: var(--dc-ink); font-weight: 700;
      border-bottom: 1px dotted currentColor; }}
    #due-crew .dc-sw a.add {{ color: var(--dc-accent); font-weight: 700; }}
    #due-crew .dc-card {{ padding: 16px; text-align: center;
      border-radius: 12px; background: var(--dc-bg); }}
    #due-crew .dc-card b {{ font-size: 15px; display: block; margin-bottom: 5px; }}
    #due-crew .dc-card span {{ font-size: 12px; color: var(--dc-muted); }}
    #due-crew .dc-card a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    /* 3.1: a plan I follow, on the Decks tab */
    #due-crew .dc-pc {{ margin-bottom: 14px; }}
    #due-crew .dc-pc .pk {{ display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin: 2px 0 6px; }}
    #due-crew .dc-pc .pk b {{ font-size: 12.5px; }}
    #due-crew .dc-pc .pk span {{ font-size: 11px; color: var(--dc-muted); }}
    #due-crew .dc-pc .pk .acts {{ margin-left: auto; display: flex; gap: 12px; }}
    #due-crew .dc-pc .pk .acts a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 11.5px; }}
    #due-crew .dc-pc .u3 {{ display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) 118px 58px;
      gap: 10px; align-items: center; font-size: 12px; padding: 3px 0; }}
    #due-crew .dc-pc .u3 .u {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .dc-pc .u3.hd {{ color: var(--dc-muted); font-size: 10.5px; font-weight: 700; }}
    #due-crew .dc-pc .u3.now .u {{ font-weight: 700; }}
    #due-crew .dc-pc .u3.later {{ color: var(--dc-faded); }}
    #due-crew .dc-pc .u3.skip {{ color: var(--dc-faded); }}
    #due-crew .dc-pc .u3.skip .u {{ text-decoration: line-through; }}
    #due-crew .dc-pc .bar {{ display: block; height: 8px; background: var(--dc-well); border-radius: 2px;
      overflow: hidden; position: relative; }}
    #due-crew .dc-pc .bar i {{ position: absolute; left: 0; top: 0; bottom: 0; background: var(--dc-accent); }}
    #due-crew .dc-pc .bar i.part {{ opacity: 0.35; }}
    #due-crew .dc-pc .miss {{ color: var(--dc-hours); font-size: 11px; }}
    #due-crew .dc-pc .n {{ color: var(--dc-muted); font-variant-numeric: tabular-nums; text-align: right;
      white-space: nowrap; font-size: 11px; }}
    #due-crew .dc-pc .pn {{ font-size: 12px; padding: 6px 8px; border-radius: 8px; background: var(--dc-well);
      display: flex; gap: 10px; flex-wrap: wrap; margin-top: 6px; }}
    #due-crew .dc-pc .pn.warn {{ color: var(--dc-hours); }}
    #due-crew .dc-pc .u3 a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 11px; text-align: right; }}
    #due-crew .dc-pc .pn a, #due-crew .dc-pc .pl a {{ margin-left: auto; color: var(--dc-accent); font-weight: 700;
      text-decoration: none; white-space: nowrap; }}
    #due-crew .dc-pc .pl {{ display: flex; gap: 10px; }}
    /* 3.2: today's session, the week's recap */
    #due-crew .dc-pc .ss {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin: 4px 0 6px; }}
    #due-crew .dc-pc .ss div {{ background: var(--dc-well); border-radius: 8px; padding: 6px 9px; display: grid; }}
    #due-crew .dc-pc .ss b {{ font-size: 16px; font-variant-numeric: tabular-nums; }}
    #due-crew .dc-pc .ss b small {{ font-size: 11px; color: var(--dc-muted); font-weight: 400; }}
    #due-crew .dc-pc .ss span {{ font-size: 10.5px; color: var(--dc-muted); }}
    #due-crew .dc-pc .pn .acts {{ margin-left: auto; display: flex; gap: 12px; flex-wrap: wrap; }}
    #due-crew .dc-pc .pn .acts a {{ margin-left: 0; }}
    /* 3.5.0: the Plans tab's Today box and week (Anki centres the Decks
       screen's text; the tab reads left to right) */
    #due-crew .dc-pc, #due-crew .dc-pways {{ text-align: left; }}
    #due-crew .ptoday {{ border: 1.5px solid var(--dc-accent); border-radius: 10px; padding: 9px 11px;
      display: grid; grid-template-columns: minmax(0, 1fr); gap: 6px; margin: 2px 0 10px; }}
    #due-crew .ptoday > * {{ min-width: 0; }}
    #due-crew .ptoday .h {{ font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-accent); }}
    #due-crew .ptoday.rest {{ border-color: var(--dc-line); }}
    #due-crew .ptoday.rest .h {{ color: var(--dc-muted); }}
    #due-crew .ptoday.behind {{ border-color: var(--dc-hours); }}
    #due-crew .ptoday.behind .h {{ color: var(--dc-hours); }}
    #due-crew .ptoday .what {{ font-size: 14px; }}
    #due-crew .ptoday .next {{ font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .ptoday .next b {{ color: var(--dc-ink); }}
    #due-crew .ptoday .next a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .ptoday .nums {{ display: flex; gap: 16px; flex-wrap: wrap; font-size: 11.5px; color: var(--dc-muted); }}
    #due-crew .ptoday .nums b {{ color: var(--dc-ink); font-size: 14px; font-variant-numeric: tabular-nums; }}
    #due-crew .ptoday .nums .ok {{ color: var(--dc-accent); font-weight: 700; }}
    #due-crew .wbar {{ display: block; height: 5px; background: var(--dc-well); border-radius: 3px; overflow: hidden; }}
    #due-crew .wbar i {{ display: block; height: 100%; background: var(--dc-accent); }}
    #due-crew .ptoday .wbar {{ max-width: 320px; }}
    #due-crew .ptoday .btns {{ display: flex; gap: 14px; align-items: center; flex-wrap: wrap; }}
    #due-crew .ptoday .btns a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 12px; }}
    #due-crew .ptoday .btns a.q {{ color: var(--dc-muted); font-weight: 500; }}
    #due-crew .ptoday .btns a.bt.on {{ background: var(--dc-accent); color: var(--dc-accent-ink); border-radius: 7px; padding: 4px 12px; }}
    #due-crew .pwh {{ display: flex; align-items: center; gap: 10px; font-size: 12px; margin: 2px 0 6px; }}
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
    #due-crew .pwk .tag {{ font-size: 9.5px; color: var(--dc-muted); font-weight: 600; }}
    #due-crew .pwk .wbar {{ margin-top: auto; height: 4px; }}
    #due-crew .pwk .pc.past .wbar {{ background: var(--dc-bg); }}
    #due-crew .pday {{ border: 1px solid var(--dc-line); border-radius: 10px; padding: 8px 10px; margin-top: 6px;
      display: grid; gap: 5px; font-size: 12px; }}
    #due-crew .pday[hidden] {{ display: none; }}
    #due-crew .pday .r {{ display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; }}
    #due-crew .pday .r .u {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .pday .r .acts, #due-crew .pday > .acts {{ display: flex; gap: 12px; justify-content: flex-end; }}
    #due-crew .pday a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .pday .wi {{ display: grid; gap: 2px; margin: 1px 0 5px; padding-left: 9px; border-left: 2px solid var(--dc-line);
                           font-size: 11.5px; color: var(--dc-muted); text-align: left; }}
    #due-crew .pday .wi b {{ color: var(--dc-ink); font-weight: 600; }}
    #due-crew .pday .wi .acts {{ display: flex; gap: 12px; }}
    #due-crew .ptoday .tw {{ display: block; font-size: 11.5px; font-weight: 400; color: var(--dc-muted);
                            white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 100%; }}
    #due-crew .pcrew {{ font-size: 11.5px; color: var(--dc-muted); margin-top: 8px; }}
    #due-crew .dc-pways {{ display: grid; gap: 10px; margin: 4px 0 8px; }}
    #due-crew .dc-pways .t {{ font-size: 14px; }}
    #due-crew .dc-pways .ways {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }}
    #due-crew .dc-pways .way {{ border: 1px solid var(--dc-line); border-radius: 10px; padding: 9px 10px; display: grid;
      gap: 6px; align-content: start; font-size: 12px; }}
    #due-crew .dc-pways .way b {{ font-size: 13px; }}
    #due-crew .dc-pways .way a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    #due-crew .dc-pways input {{ font: inherit; font-size: 12px; padding: 3px 7px; border: 1px solid var(--dc-line);
      border-radius: 6px; background: var(--dc-bg); color: var(--dc-ink); min-width: 0; }}
    @media (max-width: 560px) {{
      #due-crew .dc-pc .u3 {{ grid-template-columns: minmax(0, 1fr) 70px; }}
      #due-crew .dc-pc .u3 .n {{ grid-column: 1 / -1; text-align: left; }}
      /* the week as a list */
      #due-crew .pwk {{ grid-template-columns: 1fr; }}
      #due-crew .pwk .pc {{ min-height: 0; flex-direction: row; flex-wrap: wrap; align-items: center; gap: 6px; }}
      #due-crew .pwk .d {{ width: 100%; }}
      #due-crew .pwk .wbar {{ width: 100%; }}
      #due-crew .dc-pways .ways {{ grid-template-columns: 1fr; }}
      #due-crew .pwh .site {{ margin-left: 0; }}
      #due-crew .pwh {{ flex-wrap: wrap; }}
    }}
    </style>
    """


def _pycmd(cmd):
    """Only ids and keys ride in commands; anything else is dropped so a
    server-sourced id could never close the quote it sits in."""
    return f"pycmd('duecrew:{_re.sub(r'[^A-Za-z0-9:_-]', '', str(cmd))}'); return false;"


def _head(period, show_up=False, hidden=frozenset()):
    if show_up:
        # one crew view: today is the last square of the week
        keys = (("today", "Crew"), ("decks", "Decks"), ("squads", "Squads"), ("plans", "Plans"))
        on = "today" if period in ("today", "week") else period
    else:
        keys = (("today", "Today"), ("week", "Week"), ("decks", "Decks"), ("squads", "Squads"), ("plans", "Plans"))
        on = period
    keys = tuple((k, label) for k, label in keys if k not in hidden)
    pills = ""
    for key, label in keys:
        cls = "dc-pill on" if on == key else "dc-pill"
        pills += (f'<a class="{cls}" href="#" '
                  f'onclick="{_pycmd("period:" + key)}">{label}</a>')
    return (f'<div class="dc-head"><span class="dc-title">{board_mark()}</span>'
            f'<span>{pills}</span></div>')


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


def _row_html(row, rank, cfg, period="today"):
    name = _label(row["name"], row.get("emoji"))
    cls = "you" if row["you"] else ""
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
        cheer = '<td class="chc"></td>'
        name = (f'<a class="dc-pl" href="#" title="See what your crew sees" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{name}</a>')
    else:
        cheer = (f'<td class="chc"><a class="dc-cheer" href="#" title="Send a cheer" '
                 f'onclick="{_pycmd("cheerpick:" + str(row["user_id"]))}">&#127881;</a></td>')
        # 3.0.1: right-click for Mute cheers and Report…
        name = (f'<a class="dc-pl" href="#" title="Open profile" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}" '
                f'oncontextmenu="{_pycmd("rowmenu:" + str(row["user_id"]))}">{name}</a>')
    return (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
            f'<td class="nm">{name}{chip}{la}{extra}{status}</td>{cells}{cheer}</tr>')


def _table_html(data, cfg, period):
    sort = sort_key(cfg)
    fresh, dormant = build_rows(data["entries"], data["labels"],
                                data.get("tomorrow", ""), period, cfg)
    heads = "<th></th><th></th>"
    if sort == "week":
        sort = "reviews"
    for key, label in HEADERS:
        on = "on" if key == sort else ""
        arrow = " &#9662;" if key == sort else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{label}{arrow}</a></th>')
    heads += "<th></th>"
    if cfg.get("show_up"):
        fresh, dormant = build_rows(data["entries"], data["labels"],
                                    data.get("tomorrow", ""), "today", cfg)
        return _presence_html(fresh, dormant, data["labels"], data["entries"])
    body = ""
    n = 0  # show-up rows are counted, not ranked
    for row in fresh:
        if row.get("showup"):
            rank = "&#10003;"
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
    solo = ""
    if len(data["entries"]) == 1:
        # 3.4 review, C5: until a friend adds me back, the invite is the board
        code = str(data.get("my_code") or "")
        spaced = f"{code[:4]} {code[4:]}" if len(code) == 6 else code
        # 3.5.0: a friend's, a plan's or a squad's code, or a whole invite
        add = ("var v=(document.getElementById('dc-addcode').value||'').toUpperCase()"
               ".replace(/[^A-Z0-9 \\/]/g,' ').slice(0,200);"
               "pycmd('duecrew:addcode:'+v);return false;")
        pending = [str(x) for x in data.get("pending") or []]
        if not pending:
            wait = "They show up here once they add you back."
        elif len(pending) <= 2:
            wait = f"Waiting for {' and '.join(_html.escape(x) for x in pending)} to add you back."
        else:
            wait = f"Waiting for {len(pending)} people to add you back."
        solo = (f'<div class="dc-empty"><b>Bring your crew</b>'
                f'<span style="color: var(--dc-muted);">{wait}</span>'
                f'<div class="row">{f"<span class=dc-code>{_html.escape(spaced)}</span>" if code else ""}'
                f'<a class="bt on" href="#" onclick="{_pycmd("copyinvite")}">Copy invite</a></div>'
                f'<div class="row"><input id="dc-addcode" placeholder="A code, or paste an invite" '
                f'onkeydown="if(event.key===\'Enter\'){{{add}}}">'
                f'<a class="bt" href="#" onclick="{add}">Add</a></div></div>')
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
    """ + DUE_JS


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


def _presence_html(fresh, dormant, labels, entries):
    """The board in show-up mode: one view in place of Today and Week — a
    square per day, Monday to today, nothing to rank. Sorted by days showed
    up, then name; today is the last square, so who showed up today reads
    off the right-hand column."""
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
    heads = f'<th class="lt" colspan="2">{today_n} showed up today</th>{letters}'
    body = ""
    for row in fresh + dormant:
        name = _label(row["name"], row.get("emoji"))
        cls, note = ("you" if row["you"] else ""), ""
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
    return _scroll(f'<table><tr>{heads}</tr>{body}</table>', body.count('<tr class='))


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


def _decks_html(data, deltas=None, tricky=None, plans=None, mine=None):
    return _tricky_html(tricky, mine) + _decks_body(data, deltas)


def _plans_html(plans):
    """3.3: the Plans tab, a card each; 3.5.0: with none, the ways in."""
    cards = (plans or {}).get("cards") or []
    return "".join(_plan_card_html(card) for card in cards) if cards else _plans_empty_html()


def _segs(segments):
    """[(text, bold)] from plans.py, escaped."""
    return "".join(f"<b>{_html.escape(str(t))}</b>" if b else _html.escape(str(t)) for t, b in segments)


def _pbar(done, total, solid=True):
    pct = 0 if not total else max(0, min(100, round(100 * int(done) / int(total))))
    return f'<span class="bar"><i class="{"" if solid else "part"}" style="width:{pct}%"></i></span>'


def _plans_empty_html():
    """3.5.0: the Plans tab with no plan: three ways in."""
    add = ("var v=(document.getElementById('dc-plancode').value||'').toUpperCase()"
           ".replace(/[^A-Z0-9 \\/]/g,' ').slice(0,200);"
           "pycmd('duecrew:addcode:'+v);return false;")
    return (f'<div class="dc-pways"><b class="t">Follow a plan</b><div class="ways">'
            f'<div class="way"><b>Got a code?</b><input id="dc-plancode" placeholder="N4AP ULM2" '
            f'onkeydown="if(event.key===\'Enter\'){{{add}}}"><a href="#" onclick="{add}">Follow</a></div>'
            f'<div class="way"><b>Find one</b><a href="#" onclick="{_pycmd("planlibrary")}">Library on duecrew.com &#8599;</a></div>'
            f'<div class="way"><b>Make one</b><a href="#" onclick="{_pycmd("planmake")}">Pick a deck&hellip;</a></div>'
            f'</div></div>')


def _plan_card_html(card):
    """3.5.0, the Plans tab (mock "Plans Tab Review"): the plan, a Today
    box, this week as the site's calendar draws it (a list when narrow),
    one note at most, and the crew. Plan, date and event names are the
    author's: escaped here."""
    e = _html.escape
    pid = str(card.get("id", ""))
    out = (f'<div class="dc-pc"><div class="pk"><b>{e(str(card.get("title") or "Plan"))}</b>'
           f'<span>{e(str(card.get("sub") or ""))}</span>'
           f'<span class="acts"><a href="#" onclick="{_pycmd("planmenu:" + pid)}">Plan &#9662;</a></span></div>')
    if card.get("no_deck"):
        out += (f'<div class="dc-line">No deck here has this plan&rsquo;s cards yet. '
                f'<a href="#" onclick="{_pycmd("plandeck:" + pid)}">Pick a deck</a></div>')
    box, behind = _today_box(card, pid)
    out += box + _week_html(card, pid)
    notes = _plan_notes(card, pid, skip_waiting=behind)
    if notes:
        out += notes[0]
    crew = _crew_line(card)
    if crew:
        out += f'<div class="pcrew">{crew}</div>'
    return out + "</div>"


def _today_box(card, pid):
    """(html, behind): what today holds, in one of its states: paused, a
    rest day, done, behind, or a study day."""
    e = _html.escape
    s = card.get("session") or {}
    kind = s.get("kind")
    head = f'Today &middot; {e(str(card.get("today") or ""))}'
    names = [str(n) for n in card.get("today_names") or []]
    what = " &middot; ".join(f"<b>{e(n)}</b>" for n in names[:2]) + (f" and {len(names) - 2} more" if len(names) > 2 else "")
    # 3.6.5, P7: one line of what today's dates cover
    if card.get("today_what"):
        what += f'<span class="tw" title="{e(str(card["today_what"]))}">{e(str(card["today_what"]))}</span>'
    nxt = card.get("next")
    nxt_line = (f'<span class="next">Next: <b>{e(nxt["name"])}</b> &middot; {e(str(nxt["day"]))}'
                + (f' &middot; {int(nxt["n"]):,} new' if int(nxt.get("n") or 0) else "")
                + (f' &middot; <a href="#" onclick="{_pycmd("plannow:" + pid + ":" + str(nxt["uid"]))}">Open now</a>'
                   if nxt.get("uid") else "") + '</span>') if nxt else ""
    if card.get("paused"):
        what_ = str(card.get("sub") or "paused").split(" · ")[0]
        return (f'<div class="ptoday rest"><span class="h">{e(what_[:1].upper() + what_[1:])}</span>'
                f'<span class="what">No new cards until then</span>'
                f'<div class="btns"><a href="#" onclick="{_pycmd("planresume:" + pid)}">Resume now</a></div></div>'), False
    due = s.get("due")
    reviews = f'<span><b>{int(due):,}</b> reviews</span>' if due is not None else ""
    if kind in ("rest", "catchup", "taper"):
        word = {"rest": "rest day", "catchup": "catch-up week", "taper": "taper"}[kind]
        return (f'<div class="ptoday rest"><span class="h">{head} &middot; {word}</span>'
                f'<span class="what">{reviews or "Reviews"} &middot; no new</span>{nxt_line}'
                f'<div class="btns"><a class="bt on" href="#" onclick="{_pycmd("planstudy:" + pid)}">Study</a></div></div>'), False
    target, done = int(s.get("target") or 0), int(s.get("done") or 0)
    if s and target and done >= target and not int(due or 0):
        return (f'<div class="ptoday done"><span class="h">{head}</span>'
                f'<span class="what">&#10003; <b>Done</b> &middot; {target:,} new'
                + (f' &middot; {int(due):,} reviews' if due is not None else "") + f'</span>{nxt_line}</div>'), False
    behind = int(s.get("behind") or 0) or (0 if card.get("catch") else int(card.get("waiting") or 0))
    if s.get("ask"):
        behind = 0  # the missed-days question says it, with its own three ways
    bar = _wbar(min(done, target), target) if target else ""
    nums = []
    if due is not None:
        nums.append(f'<span><b>{int(due):,}</b> reviews</span>')
    if target:
        nums.append(f'<span><b>{min(done, target):,}</b> / {target:,} new</span>')
    op = card.get("opened")
    if op and int(card.get("early") or 0):
        early = int(card["early"])
        nums.append(f'<span>opened {early} day{"s" if early != 1 else ""} early</span>')
    something = bool(target) or bool(int(due or 0))
    if s and kind == "study" and not behind and not s.get("ask") and target:
        nums.append('<span class="ok">&#10003; on track</span>')
    btns = ""
    if s and kind == "study" and something:
        btns += f'<a class="bt on" href="#" onclick="{_pycmd("planstudy:" + pid)}">Study now</a>'
    if op and op.get("undo") and not behind:
        btns += f'<a href="#" class="q" onclick="{_pycmd("plannottoday")}">Put off to tomorrow</a>'
    if behind:
        btns += (f'<a href="#" onclick="{_pycmd("plancatch:" + pid)}">Catch up&hellip;</a>'
                 f'<a href="#" onclick="{_pycmd("planshift:" + pid)}">Move my days back&hellip;</a>')
    line = (f'<span class="what">{what}</span>' if what else
            '<span class="what">Nothing new opens today</span>' if not target else "")
    return (f'<div class="ptoday{" behind" if behind else ""}"><span class="h">{head}'
            + (f' &middot; {behind:,} new behind' if behind else "") + f'</span>{line}'
            + (f'<div class="nums">{"".join(nums)}</div>' if nums else "") + bar
            + ("" if what or target else nxt_line)
            + (f'<div class="btns">{btns}</div>' if btns else "") + '</div>'), bool(behind)


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
           f'<a class="site" href="#" title="Opens in your browser" onclick="{_pycmd("plansite:" + pid)}">Month on duecrew.com &#8599;</a></div>')
    cells, details = "", ""
    # the box marks the open day: today on this week, else the first day with plans
    has_any = [bool(d["units"] or d["events"]) for d in week]
    sel = next((i for i, d in enumerate(week) if d["today"]), None) if off == 0 else None
    if sel is None:
        sel = next((i for i, x in enumerate(has_any) if x), None)
    for i, d in enumerate(week):
        did = f"dc-pd-{_re.sub(r'[^A-Za-z0-9]', '', pid)}-{i}"
        new, seen = int(d.get("new") or 0), int(d.get("seen") or 0)
        if d["past"] or d["today"]:
            mark = ("&#10003;" if new and seen >= new else f"{new - seen:,} left" if new and d["past"] else
                    f"{new:,}" if new else "")
        else:
            mark = f"{new:,}" if new else ""
        cls = ("pc" + (" now" if d["today"] else " past" if d["past"] else "") + (" off" if d["rest"] else "")
               + (" sel" if i == sel else ""))
        chips = "".join(f'<span class="chip{" done" if u["state"] == "done" else " skip" if u["state"] == "skip" else ""}">'
                        f'{e(u["name"])}</span>' for u in d["units"])
        chips += "".join(f'<span class="chip ev">{e(n)}</span>' for n in d["events"])
        tag = "rest" if d["rest"] else "prep" if d["prep"] else ""
        bar = (_wbar(min(seen, new), new) if new and (d["past"] or d["today"]) else "")
        has = has_any[i]
        # a click moves the box here and shows the day's details; again closes both
        click = (f' onclick="var w=this.parentNode,o=this.classList.contains(\'sel\'),x=document.getElementById(\'{did}\');'
                 f'w.querySelectorAll(\'.pc\').forEach(function(c){{c.classList.remove(\'sel\');}});'
                 f'w.parentNode.querySelectorAll(\'.pday\').forEach(function(y){{y.hidden=true;}});'
                 f'if(!o){{this.classList.add(\'sel\');if(x)x.hidden=false;}}return false;"')
        num = (f'<b class="td"><span class="dow">{e(d["dow"])} </span>{int(d["num"])}</b>' if d["today"]
               else f'<b><span class="dow">{e(d["dow"])} </span>{int(d["num"])}</b>')
        cells += (f'<div class="{cls}"{click}><span class="d">{num}'
                  f'<span>{mark}</span></span>{chips}'
                  + (f'<span class="tag">{tag}</span>' if tag else "") + bar + '</div>')
        if has:
            rows = ""
            for u in d["units"]:
                uid = str(u["uid"])
                if u["state"] == "later":
                    acts = (f'<a href="#" onclick="{_pycmd(f"plannow:{pid}:{uid}")}">Open now</a>'
                            f'<a href="#" onclick="{_pycmd(f"planskip:{pid}:{uid}")}">Skip it</a>')
                    num = f'{int(u["total"]):,} new' if int(u["total"]) else ""
                elif u["state"] == "skip":
                    acts = f'<a href="#" onclick="{_pycmd(f"planunskip:{pid}:{uid}")}">Undo skip</a>'
                    num = "skipped"
                else:
                    acts = (f'<a href="#" onclick="{_pycmd(f"planstudydate:{pid}:{uid}")}">Study</a>' if int(u["seen"]) else "")
                    num = f'{int(u["seen"]):,} / {int(u["total"]):,}' if int(u["total"]) else ""
                rows += f'<div class="r"><span class="u">{e(u["name"])}</span><span class="n">{num}</span><span class="acts">{acts}</span></div>'
                # 3.6.5, P7: what's in it, as the site's print list groups it, and Browse
                what = "".join(f'<span class="g">{f"<b>{e(str(g))}</b> &middot; " if g else ""}{" &middot; ".join(e(str(x)) for x in xs)}</span>'
                               for g, xs in (u.get("what") or []))
                browse = (f'<a href="#" onclick="{_pycmd(f"planbrowse:{pid}:{uid}")}">Browse {int(u["total"]):,} card{"s" if int(u["total"]) != 1 else ""}</a>'
                          if int(u["total"]) and u["state"] != "skip" else "")
                if what or browse:
                    rows += f'<div class="wi">{what}{f"<span class=acts>{browse}</span>" if browse else ""}</div>'
            for n in d["events"]:
                rows += f'<div class="r"><span class="u"><b>{e(n)}</b></span><span class="n"></span><span></span></div>'
            later = (not d["past"] and not d["today"] and any(u["state"] == "later" for u in d["units"]))
            back = (f'<div class="acts"><a href="#" onclick="{_pycmd("planshift:" + pid)}">Move my days back&hellip;</a></div>'
                    if later else "")
            details += (f'<div class="pday" id="{did}"{"" if i == sel else " hidden"}><b>{e(d["dow"])} {int(d["num"])} {_mon(d["day"])}'
                        + (' &middot; today' if d["today"] else "") + '</b>'
                        f'{rows}{back}</div>')
    return out + f'<div class="pwk">{cells}</div>{details}'


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


def _plan_notes(card, pid, skip_waiting=False):
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
            a2 += f'<a href="#" onclick="{_pycmd("planpush:" + pid)}">Move my days back {n}</a>'
        a2 += f'<a href="#" onclick="{_pycmd("planleave:" + pid)}">Leave them</a>'
        out.append(f'<div class="pn warn"><span>Missed <b>{e(when)}</b>: {int(ask["waiting"]):,} new waiting</span>'
                   f'<span class="acts">{a2}</span></div>')
    if card.get("change"):
        out.append(f'<div class="pn"><span>{_segs(card["change"])}</span>'
                   f'<a href="#" onclick="{_pycmd("planok:" + pid)}">OK</a></div>')
    lim, want = s.get("limit"), int(s.get("target") or 0)
    if lim is not None and want > int(lim) and s.get("kind") == "study":
        out.append(f'<div class="pn warn"><span>Anki shows {int(lim):,} new a day in this deck; today has {want:,}.</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planlimit:" + pid)}">Raise to {want:,}</a></span></div>')
    fb = int(s.get("fell_back") or 0)
    if fb and not card.get("fallback_ok"):
        out.append(f'<div class="pn"><span>{fb} date{"s use tags" if fb != 1 else " uses a tag"} your deck names differently, '
                   f'matched by their cards.</span><span class="acts"><a href="#" onclick="{_pycmd("planidsok:" + pid)}">OK</a></span></div>')
    # 3.6.5: what the plan left shut here, said once (OK until it grows)
    lee, miss, of = (list(card.get("aside") or []) + [0, 0, 0])[:3]
    ok = (list(card.get("aside_ok") or []) + [0, 0])[:2]
    if (lee and int(lee) > int(ok[0])) or (miss and int(miss) > int(ok[1])):
        said = []
        if lee:
            said.append(f'{int(lee):,} leech{"es stay" if int(lee) != 1 else " stays"} suspended: Anki set '
                        f'{"them" if int(lee) != 1 else "it"} aside, and a plan never opens one.')
        if miss:
            said.append(f'{int(miss):,} of {int(of):,} exact cards aren\u2019t in your deck.')
        out.append(f'<div class="pn"><span>{" ".join(said)}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planasideok:" + pid)}">OK</a></span></div>')
    if card.get("catch"):
        c = card["catch"]
        out.append(f'<div class="pn"><span>Catching up: +{int(c.get("extra") or 0):,} new a day to {e(str(c.get("until") or ""))}</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plancatchstop:" + pid)}">Stop</a></span></div>')
    for kind, segments in card.get("lines") or []:
        if kind == "behind":
            out.append(f'<div class="pn warn"><span>{_segs(segments)}</span></div>')
    if int(card.get("waiting") or 0) and not card.get("catch") and not skip_waiting:
        w = int(card["waiting"])
        out.append(f'<div class="pn"><span><b>{w:,}</b> new from earlier days waiting</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("plancatch:" + pid)}">Catch up&hellip;</a></span></div>')
    if card.get("put_off"):
        names = [str(n) for n in card["put_off"]]
        what = " and ".join(f"<b>{e(n)}</b>" for n in names) if len(names) <= 2 else f"<b>{len(names)} dates</b>"
        out.append(f'<div class="pn"><span>{what} open{"s" if len(names) == 1 else ""} tomorrow morning</span>'
                   f'<span class="acts"><a href="#" onclick="{_pycmd("planputback:" + pid)}">Open now</a></span></div>')
    pf = card.get("prep")
    if pf:
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


def _decks_body(data, deltas=None):
    deltas = deltas or {}
    labels = data.get("labels") or []
    # a friend ahead of my timezone writes my "tomorrow" as their today
    today_labels = tuple(lb for lb in (labels[0] if labels else "", data.get("tomorrow")) if lb)
    groups, extras = build_deck_groups(data["entries"])
    if not groups and not extras:
        return ('<div class="dc-line">No shared decks yet. '
                f'<a href="#" onclick="{_pycmd("decks")}">Pick decks to share</a> '
                '&mdash; matching decks pair up on their own.</div>')
    html = ""
    for g in groups:
        label = _html.escape(str(g["label"]))
        rows = "".join(
            _bar(n, me, d, deltas.get((uid, d.get("name", ""))), today_labels)
            for n, me, d, uid in g["rows"])
        html += f'<div class="dg"><div class="dgh">{label}</div>{rows}</div>'
    html = _scroll(_even_bars(html), sum(len(g["rows"]) for g in groups))
    html += ('<div class="dc-line" style="padding-top: 2px;">'
             # named by texture, not by light/dark: in dark mode the mature fill
             # is the bright one, and "dark = mature" read backwards there
             'solid = mature &middot; faded = seen &middot; hatched = unlocked &middot; '
             '% of each person&rsquo;s own copy &middot; hover for numbers</div>')
    return html


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
        parts.append(f'<a{on} href="#" onclick="{_pycmd("squad:" + str(sq["id"]))}">'
                     f'{_html.escape(str(sq["name"]))}</a>')
    parts.append(f'<a class="add" href="#" onclick="{_pycmd("squadadd")}">'
                 f'+ join or create</a>')
    return '<div class="dc-sw">' + "".join(parts) + "</div>"


def _squads_html(view, cfg):
    """A squad board: everyone here holds the same invite. Plain ranks — no
    medals, no cheers; these aren't necessarily people you know. Add lives
    on the person's card (click a name), not on the row."""
    state = view.get("state")
    sw = _switcher(view)
    name = _html.escape(str(view.get("name") or "?"))
    if state == "none":
        return (sw + '<div class="dc-line">A private board '
                'for any group. Join with a code, or create one.</div>')
    if state == "loading":
        return sw + '<div class="dc-line">Fetching&hellip;</div>'
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
    # the squad head is rebuilt below when show-up mode is on
    heads = (f'<th style="text-align: left; font-weight: 400;" colspan="2">'
             f'<span style="color: var(--dc-muted); font-size: 11px;">{headline}</span></th>')
    for key, label in SQUAD_HEADERS:
        on = "on" if key == sort else ""
        arrow = " &#9662;" if key == sort else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{label}{arrow}</a></th>')
    show_up = bool(cfg.get("show_up"))
    numberless = lambda r: all(r.get(k) is None for k in ("reviews", "time_ms", "retention", "streak"))
    if show_up:
        live.sort(key=lambda r: (-(r.get("week") or 0), r["name"].lower()))
        heads = (f'<th style="text-align: left; font-weight: 400;" colspan="2">'
                 f'<span style="color: var(--dc-muted); font-size: 11px;">{people:,} in {name}'
                 + (" &middot; locked" if view.get("open") is False else "")
                 + (f" &middot; {len(live):,} showed up today" if live else "") + "</span></th>"
                 '<th><span style="color: var(--dc-muted); font-size: 11px; font-weight: 700;">&#128197; 7 days</span></th>')
    body = ""
    n = 0
    folded = False
    for r in live + waiting_today + rest:
        pname = _label(r["name"], r.get("emoji"))
        uid = str(r["user_id"])
        cls, note = "", ""
        if id(r) in long_ids:
            if not folded:
                body += _quiet_fold([{"name": x["name"], "last_updated": x.get("day")} for x in long_q]).replace(
                    f'colspan="{len(HEADERS) + 2}"', f'colspan="{2 + (1 if show_up else len(SQUAD_HEADERS))}"', 1)
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
    return sw + bingo + _scroll(f"<table><tr>{heads}</tr>{body}</table>", body.count('<tr class=')) + foot


# ---- 3.6: squad bingo (mock "Squad Bingo") ----

BINGO_CSS = """
    /* the whole card's frame is #due-crew.bg-full itself: its rules say so */
    #due-crew .bg-card, #due-crew.bg-full, #due-crew .bg-row, #due-crew .bg-bar, #due-crew .bg-info { text-align: left; }
    #due-crew [hidden] { display: none !important; }
    #due-crew .bg-card { border: 1.5px solid var(--dc-accent); border-radius: 10px; padding: 9px 12px; margin: 2px 0 10px;
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


def bingo_html(bv, cfg, loading=False):
    """The whole card, in the board's place (like Settings). Every string
    from the server is escaped here. A square's details show in the page
    when it's clicked: no request."""
    e = _html.escape
    head = (f'<div id="due-crew" class="dc-frame bg-full">{_css(cfg)}<style>{BINGO_CSS}</style>'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span></div>')
    back = f'<a class="bg-a" href="#" onclick="{_pycmd("bingoback")}">&lsaquo; Squads</a>'
    if not bv:
        said = "Fetching&hellip;" if loading else "No card this week yet. Refresh brings it."
        return head + f'<div class="bg-bar">{back}<b>Squad bingo</b></div><div class="bg-q">{said}</div></div>'
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
        who = st["who"]
        team = ""
        if st["need"] > 1 or sq.get("need") in ("half", "third", "quarter"):
            so_far = " &#10003;" if st["done"] else f' &middot; {len(who)}/{st["need"]}'
            team = (f'<span class="tm{" ok" if st["done"] else ""}">&#128101; {_bg_need(sq, st["need"])}'
                    f'{so_far}</span>')
        marks = "".join(
            f'<span class="st" style="right:{3 + k * 15}px;{"" if st["done"] else "opacity:.55"}" title="{e(names.get(u, ("?", ""))[0])}">'
            f'{e(names.get(u, ("?", ""))[1]) or "&#10003;"}</span>' for k, u in enumerate(who[:3]))
        dots, dname = diffs.get(sq.get("diff"), diffs["m"])
        rule = f'<span class="rl">{e(sq["rule"])}</span>' if known else ""
        squares += (f'<button class="bg-sq {"done" if st["done"] else ""} {cls}" data-i="{i}" onclick="{show}">'
                    f'<span class="fm">{fams.get(sq.get("fam"), "")}</span><span class="df" title="{dname}">{dots}</span>'
                    f'<span class="ic">{e(sq["icon"])}</span><span class="tt">{e(sq["title"]) if known else "Update to play"}</span>'
                    f'{rule}{team}{marks}</button>')
        whose = ", ".join(e(names.get(u, ("?", ""))[0]) for u in who)
        if st["need"] > 1 or sq.get("need") in ("half", "third", "quarter"):
            state = (f'A team square: {_bg_need(sq, st["need"])} have to pass the mark this week. '
                     + (f"Done by {whose}." if st["done"] else f"So far: {whose}." if who else "Nobody yet."))
        else:
            state = f"Stamped by {whose}." if who else "Not yet. Any one of you can stamp it."
        mine = ""
        if known and i < len(progress) and progress[i]:
            done, words = progress[i]
            if me in who or done:
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
    return (head
            + f'<div class="bg-bar">{back}<b>{e(bv.get("squad") or "Squad")} bingo</b>'
              f'<span class="bg-q">{e(_week_span(card["wk"]))} &middot; {stamps} of 9</span>'
              f'<a class="bg-a" href="#" title="The grid in emoji, never who stamped what" onclick="{_pycmd("bingocopy")}">Copy for the group chat</a></div>'
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


def crew_menu_items(period, show_up, squad_ok=False):
    """3.4 review, H5: the footer's Crew ▾, as [(label, command)] for the
    tab on screen. What the footer's links were, in one place."""
    items = [("Friends…", "friends")]
    if period == "today" and not show_up:
        items.append(("Share today", "sharetoday"))
        items.append(("Share today as a picture…", "picturetoday"))
    if period == "week" or (show_up and period == "today"):
        items.append(("Share the week", "sharecrewweek"))
        items.append(("Share the week as a picture…", "pictureweek"))
    if period == "squads" and not show_up and squad_ok:
        items.append(("Share the squad's day", "squadshare"))
    if period == "decks":
        items.append(("Shared decks…", "decks"))
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
           notice=None, asks=None, due=None):
    """due: Due's view (due_flow.view), above the board on every tab.
    live: I'm studying now (the footer offers to stop). tricky: flagged
    cards I share with a crewmate (Decks tab). milestones: [(uid, name,
    days)] for a crewmate's 100- or 365-day streak, with a one-tap cheer.
    room (2.12): {"mine": lobby or None, "invites": [...], "done": ...};
    see room_html. plans (3.1): {cards, offers} from plan_flow.board_view:
    the cards on the Decks tab, a squad's offers on Decks and Squads.
    notice (3.2.1): the admin's {id, text, link}, on top of every tab.
    asks (3.5.0): my own asks about cards (together.my_asks_view), Decks tab."""
    period = cfg.get("period", "today")
    hidden = hidden_tabs(cfg)  # 3.5.0: Plans shows by default, with a plan or without
    if period not in PERIODS or period in hidden:
        period = "today"
    show_up = bool(cfg.get("show_up"))
    body = (_decks_html(data, deltas, tricky, plans, asks) if period == "decks"
            else _plans_html(plans) if period == "plans"
            else _squads_html(squad_view or {"state": "none"}, cfg)
            if period == "squads"
            else _table_html(data, cfg, period))
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
        bans.append(f'<div class="dc-wrap"><span>{emoji}</span>'
                    f'<span><b>{_html.escape(str(who))}</b> just reached a {int(days)}-day streak.</span>'
                    f'<a class="wc" href="#" title="Send a cheer" '
                    f'onclick="{_pycmd("milestonecheer:" + str(uid))}">Send {emoji}</a>'
                    f'<a class="wx" href="#" title="Dismiss" '
                    f'onclick="{_pycmd("milestonex:" + str(uid))}">&times;</a></div>')
    lobby = ""
    if room and period in ("today", "week"):
        bans += [b for b in _split_wraps(room_html({"done": room.get("done"), "invites": room.get("invites")}))]
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
    if period in ("decks", "squads", "plans"):
        bans += _split_wraps(_offer_banners((plans or {}).get("offers")))
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
            left += (f'<a class="pb" href="#" title="Rounds and breaks with your crew" '
                     f'onclick="{_pycmd("roomopen")}">Open a room</a>')
    left += (f'<a href="#" title="Friends, sharing" '
             f'onclick="{_pycmd("crewmenu")}">Crew &#9662;</a>')
    n_pending = len(data.get("pending", []))
    if n_pending:
        left += (f'<a class="pb warn" href="#" title="You added them; you\'re crew when they add you back" '
                 f'onclick="{_pycmd("friends")}">{n_pending} waiting</a>')

    ago, _tone = _ago_secs(max(0.0, time.time() - fetched_at)) if fetched_at else ("just now", "")
    failed = ('<span class="warn" title="The last sync didn\'t reach the server. '
              'Your numbers are safe; Refresh tries again.">Couldn&rsquo;t sync</span>'
              ' &middot; ') if sync_error else ""
    foot = (f'<div class="dc-foot"><span class="fl">{left}</span><span class="sp"></span>'
            f'<span class="fr">{failed}Updated {ago}'
            f'<a class="ic" href="#" title="Refresh" onclick="{_pycmd("refresh")}">&#8635;</a>'
            f'<a class="ic" href="#" title="Settings" onclick="{_pycmd("settings")}">&#9881;&#xFE0E;</a></span></div>')

    return (f'<div id="due-crew" class="dc-frame">'
            f'{_css(cfg)}<style>{DUE_CSS}</style>{_due_html(due)}{_head(period, show_up, hidden)}{body}{foot}</div>')


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


def _settings_you(view):
    e = _html.escape
    if not view.get("signed_in"):
        return (f'<p>Not signed in.</p><div class="st-acts">'
                f'<a class="st-lk" href="#" {_st_click("setsignin")}>Start with your email</a></div>')
    emoji = e(str(view.get("emoji") or ""))
    status = str(view.get("status") or "")
    out = (f'<div class="st-who">{f"<span class=em>{emoji}</span>" if emoji else ""}'
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
            + _st_row("Feedback", f'<a class="st-lk" href="#" {_st_click("setfeedback")}>Send&hellip;</a>',
                      "Tell Sam what's working and what isn't")
            + '</div>')
    out += (f'<div class="st-foot"><a class="st-lk" href="#" {_st_click("setsignout")}>Sign out</a>'
            f'<a class="st-lk st-danger" href="#" {_st_click("setdelete")}>Delete account&hellip;</a></div>'
            f'<div class="st-foot"><span>{KEEP_LINE}</span></div>')
    return out


def _settings_board(cfg):
    hidden = hidden_tabs(cfg)
    pills = '<button class="st-pill on" disabled aria-pressed="true">Today</button>' + "".join(
        f'<button class="st-pill{"" if k in hidden else " on"}" aria-pressed="{"false" if k in hidden else "true"}" '
        f'{_st_click(f"settabs:{k}:{1 if k in hidden else 0}")}>{t}</button>' for k, t in HIDEABLE_TABS)
    accent = cfg.get("accent", DEFAULT_ACCENT)
    swatches = "".join(
        f'<button class="{"on" if k == accent else ""}" style="background:{v["light"][0]}" title="{k.title()}" '
        f'aria-label="{k.title()}" aria-pressed="{"true" if k == accent else "false"}" {_st_click(f"set:accent:{k}")}></button>'
        for k, v in ACCENTS.items())
    label = _html.escape(str(cfg.get("crew_label") or "Crew"))
    label_in = (f'<input class="st-in" data-f="label" maxlength="24" size="12" value="{label}" aria-label="Crew name in shares" '
                f'onchange="pycmd(\'duecrew:setlabel:\'+encodeURIComponent(this.value));">')
    g = lambda k, d: bool(cfg.get(k, d))  # noqa: E731
    return ('<div class="st-h">What it shows</div><div class="st-box">'
            + _st_row("Due Crew on the Decks screen", _st_switch("show_leaderboard", g("show_leaderboard", True), "Due Crew on the Decks screen"),
                      "Tools › Due Crew › Settings turns it back on")
            + _st_row("Yesterday for friends who haven't synced", _st_switch("show_stale", g("show_stale", True), "Yesterday for friends who haven't synced"))
            + _st_row("Tell me when my crew studies", _st_switch("sync_notifications", g("sync_notifications", True), "Tell me when my crew studies"))
            + _st_row("Tabs", f'<span class="st-pills">{pills}</span>')
            + '</div><div class="st-h">How it looks</div><div class="st-box">'
            + _st_row("Theme", _st_seg("theme", (("auto", "Match Anki"), ("light", "Light"), ("dark", "Dark")), cfg.get("theme", "auto"), "Theme"))
            + _st_row("Accent", f'<span class="st-sw" role="group" aria-label="Accent">{swatches}</span>')
            + _st_row("Compact rows", _st_switch("compact", g("compact", False), "Compact rows"))
            + _st_row("Highlight my row", _st_switch("highlight_me", g("highlight_me", True), "Highlight my row"))
            + _st_row("Room chip", _st_seg("room_chip_side", (("left", "Left"), ("right", "Right")), cfg.get("room_chip_side", "right"), "Room chip"),
                      "Its side of Anki's top bar")
            + _st_row("Crew name in shares", label_in)
            + '</div><div class="st-h">Due</div><div class="st-box">'
            + _st_row("Due above the board", _st_switch("due_show", g("due_show", True), "Due above the board"),
                      "Your plans' dates and your own to-dos")
            + _st_row("Suggestions", _st_switch("due_suggest", g("due_suggest", True), "Suggestions"),
                      "From your own Anki: today's misses, new leeches")
            + _st_row("Recover leeches", _st_switch("due_leeches", g("due_leeches", False), "Recover leeches"),
                      "Each morning on this computer: the leech tag off, and back as new cards. Edit › Undo puts them back.")
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
            + radio("paused", "Nothing for now", "Your crew sees &ldquo;on a break&rdquo;. Your streak keeps counting. "
                    "A paused account is kept 24 months without activity; opening Anki counts.")
            + '</div><div class="st-h">Dates your crew sees</div><div class="st-box">'
            + _st_row("&#128214; Exam", exam_ctl, "Shown for the two weeks before")
            + _st_row("&#9992;&#65039; Away", away_ctl)
            + '</div><div class="st-foot"><span>Turning a number off also takes it off this week.</span></div>')


def _st_toggle_cmd(cmd, on, label):
    return (f'<button class="st-tg{" on" if on else ""}" role="switch" aria-checked="{"true" if on else "false"}" '
            f'aria-label="{label}" {_st_click(cmd)}></button>')


def settings_html(view, cfg):
    """3.5.0: Settings in place of the board (mock "Settings in the Board").
    view: {tab, signed_in, name, emoji, status, sync, crew, squads, decks},
    from the glue; every string in it is escaped here."""
    tab = view.get("tab") if view.get("tab") in dict(SETTINGS_TABS) else "you"
    pills = "".join(f'<a class="dc-pill{" on" if k == tab else ""}" href="#" {_st_click("settab:" + k)}>{t}</a>'
                    for k, t in SETTINGS_TABS)
    body = (_settings_you(view) if tab == "you" else _settings_board(cfg) if tab == "board"
            else _settings_privacy(cfg))
    foot = ("Privacy, dates, status and accent are saved to your account. The rest stays on this computer."
            if view.get("signed_in") else "")
    return (f'<div id="due-crew" class="dc-frame dc-set">{_css(cfg)}<style>{SETTINGS_CSS}</style>'
            f'<div class="dc-head"><span class="dc-title">{board_mark()}</span><span>{pills}</span></div>'
            f'<div class="st-bar"><a class="st-back" href="#" {_st_click("setclose")}>&lsaquo; Board</a><b>Settings</b></div>'
            f'{body}'
            f'{f"<div class=st-note>{foot}</div>" if foot else ""}</div>')


def room_html(room):
    """2.12: the Decks screen's study rooms, from room_model.board_view.
    Every string in it may carry a friend's name: escaped here."""
    e = _html.escape
    out = ""
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
    if mine:
        bars = ""
        for i, f in enumerate(mine.get("bars") or []):
            if i:
                bars += f'<em style="flex:{int(mine.get("brk_min", 5)) or 1}"></em>'
            bars += f'<i style="flex:{int(mine.get("round", 25))}"><u style="width:{float(f) * 100:.1f}%"></u></i>'
        faces = "".join(f"<i>{e(str(x))}</i>" for x in (mine.get("initials") or [])[:6])
        out += (f'<div class="dc-room"><span class="rg{" brk" if mine.get("brk") else ""}" style="--p:{float(mine.get("frac", 0)):.3f}">'
                f'<b>{e(str(mine.get("label", "")))}</b></span>'
                f'<span class="rt"><b>{e(str(mine.get("title", "")))}</b><small>{e(str(mine.get("sub", "")))}</small>'
                f'<span class="rb">{bars}</span></span>'
                f'<span class="rw"><span class="fc" title="{e(str(mine.get("line", "")))}">{faces}</span>'
                f'<a class="go" href="#" onclick="{_pycmd("roomstudy")}">Study</a>'
                f'<a class="lv" href="#" onclick="{_pycmd("roomleave")}">Leave</a></span></div>')
    return out


def _card(cfg, title, body_html):
    head = board_mark() if title == "Due Crew" else f"<b>{title}</b>"
    return (f'<div id="due-crew">{_css(cfg)}<div class="dc-card">'
            f'{head}<span>{body_html}</span></div></div>')


def signed_out_card(cfg, expired=False, moved=False, gone=False):
    """moved: signed in on 2.x, which used passwords. 3.0 signs in with an
    emailed code, so everyone signs in once more, and nothing is lost.
    gone (Q4): the account was deleted after 12 months without activity."""
    if gone:
        return _card(cfg, "Welcome back",
                     f'Your Due Crew account was deleted after 12 months without activity, '
                     f'as the listing says. Your Anki and its cards are untouched. '
                     f'<a href="#" onclick="{_pycmd("setup")}">Start again with your email</a>; '
                     f'your crew can add you with your new code.')
    if moved:
        return _card(cfg, "Due Crew",
                     f'Due Crew now signs in with a code by email, no password. '
                     f'<a href="#" onclick="{_pycmd("setup")}">Sign in</a> once to carry on.')
    if expired:
        return _card(cfg, "Due Crew",
                     f'Your sign-in expired. '
                     f'<a href="#" onclick="{_pycmd("setup")}">Sign in again</a>')
    # 3.4 review, C4: one way in; the emailed code knows if the address is new
    return _card(cfg, "Due Crew",
                 f'Your friends&rsquo; studying next to yours. Nothing is shared '
                 f'until you start. <a href="#" onclick="{_pycmd("setup")}">Start with your email</a>')


def loading_card(cfg):
    return _card(cfg, "Due Crew", "Catching up with your crew&hellip;")


def flurry_js(emojis, banner_text, back=None, notes=None, season=None):
    """Injected via web.eval after render — never inline in board HTML.
    Banner takes its colors from the board's tokens (so Settings → Theme
    holds), the page's night classes only when the board is off. When `back` is
    (uid, emoji) — a single sender — the banner is clickable to return the
    cheer, and stays up a little longer. `notes`: sender-written lines shown
    under the title (textContent: never markup), which also buy time."""
    # 2.10: about one flake in three is the season's
    emoji_list = _json.dumps(list(emojis) * 2 + list(season or []) if season else list(emojis))
    banner = _json.dumps(banner_text)
    notes_json = _json.dumps([str(n) for n in (notes or [])][:3])
    back_cmd = _json.dumps(f"duecrew:cheerback:{back[0]}:{back[1]}" if back else None)
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
        var notes = %s;
        for (var n = 0; n < notes.length; n++) {
            var line = document.createElement('div');
            line.textContent = '\u201c' + notes[n] + '\u201d';
            line.style.cssText = 'font-size:13px;font-weight:400;margin-top:4px;opacity:0.9;max-width:60vw;';
            banner.appendChild(line);
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
                banner.remove();
            });
        }
        document.body.appendChild(banner);
        setTimeout(function() { banner.style.opacity = '0'; }, linger);
        setTimeout(function() { banner.remove(); }, linger + 600);
        if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) { return; }
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
    """ % (back_cmd, banner, notes_json, emoji_list)


def stranger_card_js(info):
    """Card for a squadmate who isn't crew. Deliberately spare — no heatmap,
    no cheer, no celebration: we don't necessarily know them. info: uid,
    name, reviews, time_ms, retention, streak, rank, squad, today (bool),
    pending, knocked_me, founder_me."""
    name = _label(info.get("name", "?"), info.get("emoji"))
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
    inner = _json.dumps(
        f'<div style="display: flex; align-items: baseline; gap: 8px;">'
        f'<span style="font-size: 15px; font-weight: 700;">{name}</span>'
        f'<span style="opacity: 0.6; font-size: 10.5px; text-transform: uppercase;'
        f' letter-spacing: 0.08em;">{where}</span></div>'
        f'<div style="font-size: 12px; opacity: 0.8; padding: 6px 0 2px;">{stat}</div>')
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
      None).
    For your own card ("you") the overlay shows exactly what the crew sees,
    and the cheer button becomes a Privacy shortcut. Everything user-sourced
    is escaped here; the JS only injects the built HTML and wires buttons."""
    you = bool(profile.get("you"))
    name = _label(profile.get("name", "?"), profile.get("emoji"))
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
    head = (kicker + '<div style="display: flex; align-items: baseline; gap: 8px;">'
            + "".join(bits) + "</div>")
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
        head += (f'<div style="font-size: 12px; opacity: 0.8; padding: 4px 0 0;">'
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
        cols = []
        week = [-1] * pad
        for n in cells:
            week.append(_heat_level(int(n)))
            if len(week) == 7:
                cols.append(week)
                week = []
        if week:
            cols.append(week + [-1] * (7 - len(week)))
        col_html = ""
        for col in cols[-26:]:
            cell_html = "".join(
                f'<i class="dchm h{lvl if lvl >= 0 else "x"}"></i>' for lvl in col)
            col_html += f'<div class="dchc">{cell_html}</div>'
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
    })();
    """ % (inner, act_label, act_primary, act_cmd)


# ---- Due (mock "My List"): the day's to-do, above the board ----

DUE_CSS = """
    #due-crew .du { text-align: left; border: 1.5px solid var(--dc-accent); border-radius: 11px;
      padding: 9px 12px 10px; margin: 0 0 14px; display: grid; gap: 6px; }
    #due-crew .du > * { min-width: 0; }
    #due-crew .du a { text-decoration: none; }
    #due-crew .du-h { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    #due-crew .du-h .sp { flex: 1; }
    #due-crew .du-n { color: var(--dc-muted); font-size: 11.5px; white-space: nowrap; }
    #due-crew .du-fold { color: var(--dc-muted); font-size: 11px; padding: 0 2px; }
    #due-crew .du-tabs { display: inline-flex; white-space: nowrap; }
    #due-crew .du-tabs a { font-size: 11px; font-weight: 700; padding: 1px 10px; border: 1px solid var(--dc-line);
      color: var(--dc-muted); }
    #due-crew .du-tabs a + a { border-left: 0; }
    #due-crew .du-tabs a:first-child { border-radius: 99px 0 0 99px; }
    #due-crew .du-tabs a:last-child { border-radius: 0 99px 99px 0; }
    #due-crew .du-tabs a.on { background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }
    #due-crew .du-r { display: grid; grid-template-columns: 16px minmax(0, 1fr) auto; gap: 2px 9px; align-items: start;
      padding: 5px 0 4px; border-top: 1px solid var(--dc-line); }
    #due-crew .du-r .t { display: grid; gap: 2px; min-width: 0; overflow-wrap: anywhere; }
    #due-crew .du-r .t small, #due-crew .du-m { color: var(--dc-muted); font-size: 11.5px; }
    #due-crew .du-r.done .t > b, #due-crew .du-r.done .t > span.x { color: var(--dc-muted); text-decoration: line-through; }
    #due-crew .du-r .end { display: flex; gap: 10px; align-items: baseline; white-space: nowrap; font-size: 11.5px; }
    #due-crew .du-r .end .n { color: var(--dc-muted); font-variant-numeric: tabular-nums; }
    #due-crew .du-go { color: var(--dc-accent); font-weight: 700; font-size: 11.5px; white-space: nowrap; }
    #due-crew .du-tag { color: var(--dc-muted); font-size: 11px; border: 1px solid var(--dc-line); border-radius: 6px;
      padding: 0 6px; white-space: nowrap; }
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
    #due-crew .du .wbar { margin-top: 3px; }
    #due-crew .du-sec { font-size: 10.5px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase;
      color: var(--dc-muted); padding-top: 4px; }
    #due-crew .du-sec.warn { color: #c77700; }
    #due-crew .du-bh { display: grid; gap: 0; }
    #due-crew .du-line { display: flex; justify-content: space-between; gap: 6px 12px; flex-wrap: wrap; font-size: 12px;
      border-radius: 8px; padding: 5px 9px; background: var(--dc-you-bg); }
    #due-crew .du-line.ev { color: #c77700; font-weight: 700; background: transparent; padding: 0; }
    #due-crew .du-line .acts { display: flex; gap: 12px; }
    #due-crew .du-line a, #due-crew .du-sg a { color: var(--dc-accent); font-weight: 700; }
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
    #due-crew .du-one { display: flex; align-items: center; gap: 6px 12px; padding: 7px 12px; white-space: nowrap; }
    #due-crew .du-one > * { flex: none; }
    #due-crew .du-one .wbar { flex: 0 1 90px; width: auto; min-width: 24px; margin: 0; }
    #due-crew .du-one .sp { flex: 1 1 0; }
    #due-crew .du-one .sp { flex: 1; }
    #due-crew .du-one > a:first-child b { color: var(--dc-accent); font-size: 12.5px; }
    #due-crew .du-one .du-go { flex: 0 1 auto; min-width: 0; max-width: 260px; overflow: hidden; text-overflow: ellipsis; }
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
    var m = w.match(/^(\d{1,2})(?:st|nd|rd|th)? ([a-z]{3,9}\.?)$/);
    if (m && month(m[2])) { return onOrAfter(today, month(m[2]), +m[1]); }
    m = w.match(/^([a-z]{3,9}\.?) (\d{1,2})(?:st|nd|rd|th)?$/);
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
      var p = parse(inp.value, box.getAttribute('data-today'));
      if (p.day === null || this.raw) { said.innerHTML = ''; return; }
      said.innerHTML = '&rarr; ' + label(p.day, box.getAttribute('data-today')) +
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
      pycmd('duecrew:dueadd:' + w + ':' + (this.raw ? 1 : 0) + ':' + encodeURIComponent(inp.value));
      this.raw = false;
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
    tag = f'<a href="#" class="du-tag" title="Move, edit or delete" onclick="{_pycmd("dueitem:" + r["id"])}">{e(r["tag"])} &#9662;</a>'
    if short:
        return (f'<div class="du-ln{" done" if r["done"] else ""}">{tick}<span>{e(r["text"])}</span>'
                f'<span class="n">{tag}</span></div>')
    do = (f'<a href="#" class="du-go" onclick="{_pycmd("duedo:" + r["id"])}">Do today</a>'
          if not r["day"] and not r["done"] else "")
    return (f'<div class="du-r{" done" if r["done"] else ""}">{tick}<span class="t"><span class="x">{e(r["text"])}</span></span>'
            f'<span class="end">{do}{tag}</span></div>')


def _due_plan(r):
    """A plan's date on Today, in full: its resources, the author's lines, its bar."""
    e = _html.escape
    box = _due_box("on" if r["done"] else "part" if r["part"] else "", auto=True)
    subs = ""
    for ln in r["lines"]:
        if ln["kind"] == "part":
            subs += (f'<span class="du-sub"><span class="du-bx auto{" on" if ln["done"] else ""}"></span>'
                     f'<span><b>{e(ln["label"])}</b></span><span class="n">{int(ln["seen"]):,} / {int(ln["total"]):,}</span></span>')
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
        extra.append(f'for {e(r["prep"])}')
    if r.get("crew") and int(r["crew"][1]) > 1:
        extra.append(f'crew {int(r["crew"][0]):,} of {int(r["crew"][1]):,} done')
    meta = " &middot; ".join([f'{e(r["plan"])}'] + extra)
    what = f'<small>{e(r["what"])}</small>' if r.get("what") else ""
    bar = _wbar(r["seen"], r["total"]) if r["total"] and not r["done"] else ""
    go = (f'<a href="#" class="du-go" onclick="{_pycmd("planstudy:" + r["pid"])}">Study &rsaquo;</a>'
          if not r["done"] and r["total"] and r["seen"] < r["total"] else "")
    n = f'<span class="n">{e(r["n"])}</span>' if r["n"] else ""
    return (f'<div class="du-r{" done" if r["done"] else ""}">{box}<span class="t"><b>{e(r["name"])}</b>'
            f'<small>{meta}</small>{what}{subs}{bar}</span><span class="end">{n}{go}</span></div>')


def _due_short(r):
    e = _html.escape
    if r["kind"] == "mine":
        return _due_mine(r, short=True)
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
        what = f'{int(p["dates"])} date{"s" if p["dates"] != 1 else ""}' + (f' &middot; {left:,} cards to see' if left else "")
        out += (f'<div class="du-r">{_due_box("", auto=True)}<span class="t"><b>{e(p["plan"])}</b><small>{what}</small></span>'
                f'<span class="end"><a href="#" class="du-go" onclick="{_pycmd("planstudy:" + p["pid"])}">Study &rsaquo;</a>'
                f'<a href="#" class="du-go" onclick="{_pycmd("plancatch:" + p["pid"])}">Catch up&hellip;</a></span></div>')
    out += "".join(_due_mine(r) for r in v["behind_mine"])
    if v["behind_more"]:
        out += f'<div class="du-q">and {int(v["behind_more"])} more</div>'
    return out + '<div class="du-sec">Today</div></div>' if v["tab"] == "today" else out + "</div>"


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


def _due_html(v):
    """Due, above the board on every tab (mock "My List"). v: due.view, from
    due_flow.view; every string in it is escaped here."""
    if not v:
        return ""
    e = _html.escape
    today = e(v["today"])
    done_n, total_n = int(v["done_n"]), int(v["total_n"])
    count = f"{done_n} of {total_n} done" if total_n else ""
    if v["folded"]:
        bar = _wbar(done_n, total_n) if total_n else ""
        st = v.get("start")
        go = (f'<a href="#" class="du-go" title="{e(st["name"])}" onclick="{_pycmd("planstudy:" + st["pid"])}">'
              f'Study &rsaquo; {e(st["name"])}</a>' if st else "")
        behind = f'<span class="du-n" style="color:#c77700">{int(v["behind_n"])} behind</span>' if v["behind_n"] else ""
        return (f'<div class="du du-one" data-today="{today}"><a href="#" onclick="{_pycmd("duefold")}" title="Open">'
                f'<b>{e(v["name"])}</b></a><span class="du-n">{count or "nothing today"}</span>{bar}{behind}'
                f'<span class="sp"></span>{go}<a href="#" class="du-fold" title="Open" onclick="{_pycmd("duefold")}">&#9662;</a></div>')
    tab = v["tab"]
    tabs = "".join(
        f'<a href="#" class="{"on" if k == tab else ""}" onclick="{_pycmd("duetab:" + k)}">{lb}</a>'
        for k, lb in (("today", "Today"), ("upcoming", "Upcoming"),
                      ("later", f'Later{" " + str(v["later_n"]) if v["later_n"] else ""}')))
    head = (f'<div class="du-h"><span class="du-tabs" role="tablist" aria-label="{e(v["name"])}">{tabs}</span>'
            f'<span class="sp"></span><span class="du-n">{count if tab != "later" else ""}</span>'
            f'<a href="#" class="du-fold" title="Fold to one line" onclick="{_pycmd("duefold")}">&#9652;</a></div>')
    toast = ""
    if v.get("toast"):
        toast = (f'<div class="du-line"><span>{e(v["toast"]["text"])}</span>'
                 f'<a href="#" onclick="{_pycmd("dueshow:" + v["toast"]["tab"])}">Show</a></div>')
    body = ""
    if tab == "today":
        body += _due_behind(v)
        for r in v["rows"]:
            if r["kind"] == "reviews":
                if not r["due"] and not r["done"]:
                    continue
                n = "all done" if r["done"] else f'{int(r["due"]):,} due'
                body += (f'<div class="du-r{" done" if r["done"] else ""}">{_due_box("on" if r["done"] else "")}'
                         f'<span class="t"><b>Reviews</b></span><span class="end"><span class="n">{n}</span></span></div>')
            elif r["kind"] == "plan":
                body += _due_plan(r)
            else:
                body += _due_mine(r)
        for sg in v["suggestions"] + v["notes"]:
            body += (f'<div class="du-sg"><span>&#10022;</span><span>{e(sg["text"])}</span><span>'
                     f'<a href="#" onclick="{_pycmd("duego:" + sg["key"])}">{e(sg["go"])}</a>'
                     f'<a href="#" class="x" title="Not today" onclick="{_pycmd("duex:" + sg["key"])}">&times;</a></span></div>')
        if not v["rows"] and not v["suggestions"] and not v["notes"]:
            body += '<div class="du-empty">Nothing due today.</div>'
        body += _due_add(v, "today")
        if v["event"]:
            ev = v["event"]
            body += f'<div class="du-line ev"><span>&#9733; {e(ev["name"])} {"today" if ev["when"] == "Today" else "on " + e(ev["when"])}</span></div>'
        nxt = ", ".join(e(x) for x in v["tomorrow"][:3]) + (f" and {len(v['tomorrow']) - 3} more" if len(v["tomorrow"]) > 3 else "")
        lead = "Done for today &middot; tomorrow" if total_n and done_n == total_n else "Tomorrow"
        if nxt:
            body += (f'<div class="du-line"><span><b>{lead}:</b> {nxt}</span>'
                     f'<a href="#" onclick="{_pycmd("duetab:upcoming")}">Upcoming &rsaquo;</a></div>')
        elif v["next"]:
            body += (f'<div class="du-line"><span><b>Next:</b> {", ".join(e(x) for x in v["next"]["names"][:2])} &middot; '
                     f'{e(v["next"]["day"])}</span><a href="#" onclick="{_pycmd("duetab:upcoming")}">Upcoming &rsaquo;</a></div>')
    elif tab == "upcoming":
        body += _due_behind(v)
        for dd in v["days"]:
            if dd.get("quiet"):
                body += f'<div class="du-q">{e(dd["label"])} &middot; nothing due</div>'
                continue
            what = "review day" if dd["review"] and not dd["n"] else (f'{dd["n"]} thing{"s" if dd["n"] != 1 else ""}' if dd["n"] else "")
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
            body += '<div class="du-empty">Nothing here. A to-do with no day waits here until you give it one.</div>'
        body += _due_add(v, "later")
    return f'<div class="du" data-today="{today}">{head}{toast}{body}</div>'
