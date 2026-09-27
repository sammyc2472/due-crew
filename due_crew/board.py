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
PERIODS = ("today", "week", "decks", "squads", "plans")  # plans: only while I follow one (3.3)
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
    fresh, stale, quiet, paused = [], [], [], []
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
            row.update(agg)
            row["showup"] = bool(row["days7"]) and all(
                row[k] is None for k in ("reviews", "time_ms", "retention", "streak"))
            fresh.append(row)
        else:
            # a friend whose day rolled over ahead of mine writes my
            # "tomorrow" label — that's their live today
            today = days.get(tomorrow) or days.get(today_lb)
            yesterday = days.get(yest_lb)
            if today:
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
    return fresh, stale + quiet + paused  # dormant rows last


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


def _reviews_cell(reviews, new):
    """The Reviews number, and under it how many were new cards (2.13): "all
    new" when every one was, nothing when none were or they didn't say."""
    if reviews is None:
        return "&mdash;"
    out = format(int(reviews), ",")
    try:
        new = int(new)
    except (TypeError, ValueError):
        return out
    if new <= 0 or reviews <= 0:
        return out
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
    #due-crew .la {{ font-size: 10px; margin-left: 5px; }}
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
    #due-crew .dc-pc .u3 {{ display: grid; grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) 118px 36px;
      gap: 10px; align-items: center; font-size: 12px; padding: 3px 0; }}
    #due-crew .dc-pc .u3 .u {{ overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .dc-pc .u3.hd {{ color: var(--dc-muted); font-size: 10.5px; font-weight: 700; }}
    #due-crew .dc-pc .u3.now .u {{ font-weight: 700; }}
    #due-crew .dc-pc .u3.later {{ color: var(--dc-faded); }}
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
    @media (max-width: 560px) {{
      #due-crew .dc-pc .u3 {{ grid-template-columns: minmax(0, 1fr) 70px; }}
      #due-crew .dc-pc .u3 .n {{ grid-column: 1 / -1; text-align: left; }}
    }}
    </style>
    """


def _pycmd(cmd):
    """Only ids and keys ride in commands; anything else is dropped so a
    server-sourced id could never close the quote it sits in."""
    return f"pycmd('duecrew:{_re.sub(r'[^A-Za-z0-9:_-]', '', str(cmd))}'); return false;"


def _head(period, show_up=False, has_plans=False):
    if show_up:
        # one crew view: today is the last square of the week
        keys = (("today", "Crew"), ("decks", "Decks"), ("squads", "Squads"))
        on = "today" if period in ("today", "week") else period
    else:
        keys = (("today", "Today"), ("week", "Week"), ("decks", "Decks"), ("squads", "Squads"))
        on = period
    if has_plans:
        keys += (("plans", "Plans"),)
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
        cells = '<td class="n">&mdash;</td>' * 4
    elif row["quiet"]:
        cls += " dim"
        cells = '<td class="n">&mdash;</td>' * 4
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
    for row in dormant:
        body += _row_html(row, "&mdash;", cfg, period)
    solo = ""
    if len(data["entries"]) == 1:
        # 3.4 review, C5: until a friend adds me back, the invite is the board
        code = str(data.get("my_code") or "")
        spaced = f"{code[:4]} {code[4:]}" if len(code) == 6 else code
        add = ("var v=(document.getElementById('dc-addcode').value||'').toUpperCase(),"
               "m=v.match(/(^|[^A-Z0-9])([A-Z0-9]{6})([^A-Z0-9]|$)/);"
               "pycmd('duecrew:addcode:'+(m?m[2]:''));return false;")
        waiting = len(data.get("pending") or [])
        solo = (f'<div class="dc-empty"><b>Bring your crew</b>'
                f'<span style="color: var(--dc-muted);">'
                f'{"They show up here once they add you back." if not waiting else f"Waiting for {waiting} to add you back."}</span>'
                f'<div class="row">{f"<span class=dc-code>{_html.escape(spaced)}</span>" if code else ""}'
                f'<a class="bt on" href="#" onclick="{_pycmd("copyinvite")}">Copy invite</a></div>'
                f'<div class="row"><input id="dc-addcode" placeholder="Their code, or paste their invite" '
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
    """


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
    chip_html = (f'<span class="dc-delta">{" &middot; ".join(chips)}</span>' if chips else "")
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


def _tricky_html(tricky):
    """2.10: cards a crewmate flagged "this one's getting me", listed only
    when I have the same note. Their text is theirs: escaped."""
    out = ""
    for t in (tricky or [])[:6]:
        who = _html.escape(str(t.get("name", "?")))
        text = _html.escape(str(t.get("text") or "a card"))
        deck = _html.escape(str(t.get("deck") or ""))
        cmd = f'tricktip:{t.get("uid", "")}:{int(t.get("index", 0))}'
        q = _html.escape(str(t.get("q") or ""))
        if q and t.get("known"):
            # 3.2: an ask, on a card I have down
            say = (f'&#129504; <b>{who}</b> asks about a card you know: &ldquo;{q}&rdquo;'
                   f'<br><small>&ldquo;{text}&rdquo;{" &middot; " + deck if deck else ""}</small>')
        else:
            say = (f'&#129513; <b>{who}</b> finds &ldquo;{text}&rdquo; tricky{" &middot; " + deck if deck else ""}'
                   + (f': &ldquo;{q}&rdquo;' if q else ""))
        out += (f'<div class="dc-flag"><span>{say}</span>'
                f'<a href="#" title="One line; it shows when the card comes up for them" '
                f'onclick="{_pycmd(cmd)}">{"Tip" if q and t.get("known") else "Send a tip"}</a></div>')
    return out


def _decks_html(data, deltas=None, tricky=None, plans=None):
    return _tricky_html(tricky) + _decks_body(data, deltas)


def _plans_html(plans):
    """3.3: the Plans tab, there while I follow a plan: a card each."""
    return "".join(_plan_card_html(card) for card in (plans or {}).get("cards") or [])


def _segs(segments):
    """[(text, bold)] from plans.py, escaped."""
    return "".join(f"<b>{_html.escape(str(t))}</b>" if b else _html.escape(str(t)) for t, b in segments)


def _pbar(done, total, solid=True):
    pct = 0 if not total else max(0, min(100, round(100 * int(done) / int(total))))
    return f'<span class="bar"><i class="{"" if solid else "part"}" style="width:{pct}%"></i></span>'


def _plan_card_html(card):
    """3.1: a plan I follow, on the Decks tab (plan_flow.card_view). Plan
    and date names are the author's: escaped here. 3.3: one line of
    status, one bar a date, no legend."""
    e = _html.escape
    pid = str(card.get("id", ""))
    out = (f'<div class="dc-pc"><div class="pk"><b>{e(str(card.get("title") or "Plan"))}</b>'
           f'<span>{e(str(card.get("sub") or ""))}</span>'
           f'<span class="acts"><a href="#" onclick="{_pycmd("planmenu:" + pid)}">Plan &#9662;</a></span></div>')
    if card.get("no_deck"):
        out += (f'<div class="dc-line">No deck here has this plan&rsquo;s cards yet. '
                f'<a href="#" onclick="{_pycmd("plandeck:" + pid)}">Pick a deck</a></div>')
    out += _session_html(card, pid)
    rows = ""
    for r in card.get("rows") or []:
        name = f'<span class="u">{e(str(r.get("name") or "?"))}</span>'
        if r.get("state") == "later":
            rows += f'<div class="u3 later">{name}<span></span><span class="n">{e(str(r.get("n") or ""))}</span><span></span></div>'
            continue
        s_, t = r.get("seen") or [0, 0]
        mine = ('<span class="miss">not in your copy</span>' if r.get("missing")
                else f'<span title="{int(s_):,} of {int(t):,} seen">{_pbar(s_, t, solid=int(s_) >= int(t))}</span>')
        cls = "u3 now" if r.get("state") == "now" else "u3"
        cmd = "planstudydate:" + pid + ":" + str(r.get("uid") or "")
        study = (f'<a href="#" title="A filtered deck of this date&rsquo;s cards you&rsquo;ve seen" '
                 f'onclick="{_pycmd(cmd)}">Study</a>'
                 if r.get("uid") and not r.get("missing") and int(s_) else '<span></span>')
        rows += f'<div class="{cls}">{name}{mine}<span class="n">{e(str(r.get("n") or ""))}</span>{study}</div>'
    if rows:
        n_rows = len(card.get("rows") or [])
        out += f'<div class="dc-scroll">{rows}</div>' if n_rows > ROW_CAP else rows
    for kind, segments in card.get("lines") or []:
        out += f'<div class="pn{" warn" if kind == "behind" else ""}"><span>{_segs(segments)}</span></div>'
    if card.get("change"):
        out += (f'<div class="pn"><span>{_segs(card["change"])}</span>'
                f'<a href="#" onclick="{_pycmd("planok:" + pid)}">OK</a></div>')
    return out + "</div>"


def _session_html(card, pid):
    """3.2: today's session on my schedule, then one status line: on track
    or behind, what opened this morning (Undo), Study now; the missed-days
    question, the week's recap, checkpoints. Numbers only (the plan's
    names are escaped)."""
    e = _html.escape
    s = card.get("session")
    out = ""
    kind = (s or {}).get("kind")
    if s:
        target, done = int(s.get("target") or 0), int(s.get("done") or 0)
        due = s.get("due")
        if kind == "study" or (target and kind not in ("catchup", "taper")):
            new = f'<b>{min(done, target):,}<small> / {target:,}</small></b><span>new today</span>'
        else:
            word = {"rest": "rest day", "catchup": "catch-up week", "taper": "taper"}.get(kind, "")
            new = f'<b>&mdash;</b><span>{e(word)}: no new</span>'
        rev = f'<b>{int(due):,}</b><span>reviews due</span>' if due is not None else '<b>&mdash;</b><span>reviews</span>'
        mins = int(s.get("minutes") or 0)
        left = f'<b>~{mins:,} min</b><span>left today</span>' if mins else '<b>&#10003;</b><span>done for today</span>'
        out += f'<div class="ss"><div>{new}</div><div>{rev}</div><div>{left}</div></div>'
    ask = (s or {}).get("ask")
    bits, acts = [], []
    if s and kind == "study" and not ask:
        behind = int(s.get("behind") or 0)
        bits.append(f'<b>{behind:,} behind</b>' if behind else "On track")
    op = card.get("opened")
    if op:
        names = [str(n) for n in op.get("names") or []]
        what = (" and ".join(f"<b>{e(n)}</b>" for n in names) if len(names) <= 2
                else f"<b>{len(names)} dates</b>")
        n = int(op.get("n") or 0)
        early = int(card.get("early") or 0)
        bits.append(f'opened {what} this morning ({n:,} card{"s" if n != 1 else ""}'
                    + (f', {early} day{"s" if early != 1 else ""} early)' if early else ")"))
        if op.get("undo"):
            acts.append(f'<a href="#" title="Anki&rsquo;s Edit › Undo" onclick="{_pycmd("planundo")}">Undo</a>')
    if s and kind == "study" and not ask:
        acts.append(f'<a href="#" onclick="{_pycmd("planstudy:" + pid)}">Study now</a>')
    if bits:
        line = " &middot; ".join(bits)
        line = line[0].upper() + line[1:] if line[:1].islower() else line
        out += (f'<div class="pn{" warn" if "behind</b>" in line else ""}"><span>{"&#10003; " if op else ""}{line}</span>'
                f'<span class="acts">{"".join(acts)}</span></div>')
    if not s:
        return out
    lim, want = s.get("limit"), int(s.get("target") or 0)
    if lim is not None and want > int(lim) and kind == "study":
        # 3.3, C1: Anki would quietly show fewer than the plan has today
        out += (f'<div class="pn warn"><span>Anki shows {int(lim):,} new a day in this deck; today has {want:,}.</span>'
                f'<span class="acts"><a href="#" onclick="{_pycmd("planlimit:" + pid)}">Raise to {want:,}</a></span></div>')
    fb = int(s.get("fell_back") or 0)
    if fb and not card.get("fallback_ok"):
        # 3.3, C5: a newer AnKing names some of the plan's tags differently
        out += (f'<div class="pn"><span>{fb} date{"s use tags" if fb != 1 else " uses a tag"} your deck names differently. '
                f'Matched by their cards: nothing changes for you.</span>'
                f'<span class="acts"><a href="#" onclick="{_pycmd("planidsok:" + pid)}">OK</a></span></div>')
    if ask:
        days = [str(d) for d in ask.get("days") or []]
        when = " and ".join(_short(d) for d in days[-2:]) if len(days) <= 2 else f"{len(days)} study days"
        a2 = (f'<a href="#" onclick="{_pycmd("planspread:" + pid)}">Spread them (+{int(ask["spread"]):,} a day)</a>')
        if ask.get("push"):
            n = int(ask["push"])
            a2 += f'<a href="#" onclick="{_pycmd("planpush:" + pid)}">Push my dates back {n} day{"s" if n != 1 else ""}</a>'
        a2 += f'<a href="#" onclick="{_pycmd("planleave:" + pid)}">Leave them open</a>'
        out += (f'<div class="pn warn"><span>You missed <b>{e(when)}</b>: {int(ask["waiting"]):,} new '
                f'card{"s" if int(ask["waiting"]) != 1 else ""} waiting.</span><span class="acts">{a2}</span></div>')
    r = s.get("recap")
    if r:
        a, b = r.get("sessions") or [0, 0]
        out += (f'<div class="pn"><span><b>Week {int(r["n"])} done</b>: {int(a)} of {int(b)} sessions, '
                f'{int(r.get("new") or 0):,} new cards{", on track" if r.get("on_track") else ""}.</span></div>')
    for c in s.get("checks") or []:
        n, got = int(c.get("n") or 0), int(c.get("answered") or 0)
        if got >= n and n:
            out += (f'<div class="pn"><span>Checkpoint <b>{e(str(c.get("name") or ""))}</b> done: '
                    f'<b>{int(c.get("right") or 0):,} of {n:,}</b> right first time.</span></div>')
        elif n:
            out += (f'<div class="pn"><span>&#10003; Built <b>Checkpoint &middot; {e(str(c.get("name") or ""))}</b>: '
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
    html = _scroll(html, sum(len(g["rows"]) for g in groups))
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
    live = sorted([r for r in rows if r.get("day") == day],
                  key=lambda r: r.get(field) if r.get(field) is not None else -1,
                  reverse=True)
    rest = sorted([r for r in rows if r.get("day") != day],
                  key=lambda r: r.get("day") or "", reverse=True)
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
    for r in live + rest:
        pname = _label(r["name"], r.get("emoji"))
        uid = str(r["user_id"])
        cls, note = "", ""
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
        body += (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
                 f'<td class="nm">{link}{note}</td>'
                 f'<td class="n">{_reviews_cell(r.get("reviews"), r.get("new_cards"))}</td>'
                 f'<td class="n">{_cell(r.get("time_ms"), _fmt_time)}</td>'
                 f'<td class="n">{_cell(r.get("retention"), lambda v: f"{v:.1f}%")}</td>'
                 f'<td class="n">{_cell(r.get("streak"))}</td>'
                 f'<td class="n">{_cell(r.get("week"), lambda v: f"{v}/7")}</td></tr>')
    # the squad's own line; Share today sits in the footer, as on Today
    acts = [f'<a href="#" onclick="{_pycmd("squadinvite")}">Copy invite</a>']
    if view.get("founder_me"):
        acts.append(f'<a href="#" onclick="{_pycmd("squadlock")}">'
                    f'{"Open" if view.get("open") is False else "Lock"}</a>')
    acts.append(f'<a href="#" onclick="{_pycmd("squadleave")}">Leave</a>')
    foot = ('<div class="dc-line">'
            + " &middot; ".join(acts) + "</div>")
    if not body:
        return (sw + '<div class="dc-line">No one&rsquo;s '
                'synced yet.</div>' + foot)
    return sw + _scroll(f"<table><tr>{heads}</tr>{body}</table>", body.count('<tr class=')) + foot


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
    if period == "week" or (show_up and period == "today"):
        items.append(("Share the week", "sharecrewweek"))
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
           notice=None):
    """live: I'm studying now (the footer offers to stop). tricky: flagged
    cards I share with a crewmate (Decks tab). milestones: [(uid, name,
    days)] for a crewmate's 100- or 365-day streak, with a one-tap cheer.
    room (2.12): {"mine": lobby or None, "invites": [...], "done": ...};
    see room_html. plans (3.1): {cards, offers} from plan_flow.board_view:
    the cards on the Decks tab, a squad's offers on Decks and Squads.
    notice (3.2.1): the admin's {id, text, link}, on top of every tab."""
    period = cfg.get("period", "today")
    has_plans = bool((plans or {}).get("cards"))
    if period not in PERIODS or (period == "plans" and not has_plans):
        period = "today"
    show_up = bool(cfg.get("show_up"))
    body = (_decks_html(data, deltas, tricky, plans) if period == "decks"
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
            f'{_css(cfg)}{_head(period, show_up, has_plans)}{body}{foot}</div>')


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


def signed_out_card(cfg, expired=False, moved=False):
    """moved: signed in on 2.x, which used passwords. 3.0 signs in with an
    emailed code, so everyone signs in once more, and nothing is lost."""
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
