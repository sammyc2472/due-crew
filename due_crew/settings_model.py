"""3.4.1 Settings in the board: what a click there changes. Pure: a
command's parts and the config in, the keys it changes out (or None when
it's not a setting, or not a value the setting takes). The board's panel
sends one command per change; the glue saves what comes back.

The same keys and rules as the Qt dialog (ui/settings_dialog.py), which
stays for when the board isn't on screen."""

import datetime as _dt
from urllib.parse import unquote

TABS = ("you", "board", "privacy")
SWITCHES = ("show_leaderboard", "show_stale", "sync_notifications", "compact",
            "highlight_me", "share_reviews", "share_time", "share_retention",
            "share_streak", "share_heatmap")
CHOICES = {"theme": ("auto", "light", "dark"),
           "accent": ("green", "blue", "purple", "teal", "amber", "rose"),
           "room_chip_side": ("left", "right")}
HIDEABLE = ("week", "decks", "squads", "plans")
PRIVACY = ("numbers", "showup", "paused")
LABEL_MAX = 24
# what Reset board puts back: the Board tab, never anything on Privacy
BOARD_DEFAULTS = {"show_leaderboard": True, "show_stale": True, "sync_notifications": True,
                  "theme": "auto", "accent": "green", "compact": False, "highlight_me": True,
                  "crew_label": "Crew", "room_chip_side": "right", "hidden_tabs": []}


def _day(text):
    try:
        return _dt.date.fromisoformat(str(text)).isoformat()
    except (TypeError, ValueError):
        return None


def change(parts, cfg, today=None):
    """parts: the command split on ":" after "duecrew", e.g. ["set",
    "compact", "1"]. Returns {key: value} to save, or None."""
    today = today or _dt.date.today()
    cmd = parts[0] if parts else ""
    arg = parts[1] if len(parts) > 1 else ""
    val = parts[2] if len(parts) > 2 else ""
    if cmd == "set":
        if arg in SWITCHES and val in ("0", "1"):
            return {arg: val == "1"}
        if arg in CHOICES and val in CHOICES[arg]:
            return {arg: val}
        return None
    if cmd == "settabs" and arg in HIDEABLE and val in ("0", "1"):
        hidden = [k for k in (cfg.get("hidden_tabs") or []) if k in HIDEABLE and k != arg]
        if val == "0":
            hidden.append(arg)
        return {"hidden_tabs": [k for k in HIDEABLE if k in hidden]}
    if cmd == "setlabel":
        text = " ".join(unquote(":".join(parts[1:])).split())
        text = "".join(ch for ch in text if ch.isprintable())[:LABEL_MAX]
        return {"crew_label": text or "Crew"}
    if cmd == "setprivacy" and arg in PRIVACY:
        # the numbers keep their switches under the other two, for when
        # "My numbers" comes back
        return {"show_up": arg == "showup", "paused": arg == "paused"}
    if cmd == "setexam":
        if arg == "off":
            return {"exam_date": ""}
        day = _day(arg) or (_day(cfg.get("exam_date")) if arg == "on" else None)
        if arg == "on" and not day:
            day = (today + _dt.timedelta(days=7)).isoformat()
        return {"exam_date": day} if day else None
    if cmd == "setaway":
        if arg == "off":
            return {"away_from": "", "away_to": ""}
        if arg == "on":
            start = _day(cfg.get("away_from")) or (today + _dt.timedelta(days=1)).isoformat()
            end = _day(cfg.get("away_to")) or (today + _dt.timedelta(days=7)).isoformat()
        else:
            start, end = _day(arg), _day(val)
            if not start or not end:
                return None
        if end < start:
            start, end = end, start
        return {"away_from": start, "away_to": end}
    if cmd == "setreset":
        return {k: (list(v) if isinstance(v, list) else v) for k, v in BOARD_DEFAULTS.items()}
    return None
