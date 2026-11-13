"""3.5.0 Settings in the board: what a click there changes. Pure: a
command's parts and the config in, the keys it changes out (or None when
it's not a setting, or not a value the setting takes). The board's panel
sends one command per change; the glue saves what comes back.

3.8.0: the only Settings; Tools › Due Crew › Settings… opens it too."""

import datetime as _dt
from urllib.parse import unquote

TABS = ("you", "board", "study", "privacy")  # board.SETTINGS_TABS (3.9.9: Study)
SWITCHES = ("show_leaderboard", "show_stale", "sync_notifications", "share_reviews", "share_time", "share_retention",
            "share_streak", "share_heatmap",
            "due_show", "due_suggest", "due_leeches",  # Due
            "fifteen", "sev",  # 3.8.1: ▶ Fifteen? and the nudge; Pip
            "two_buttons",  # 3.9.1: Again and Good alone (not the board's look: Reset board leaves it)
            "deck_counts",  # 3.9.12: Anki's deck list without the siblings it will bury (this computer's)
            "magic_search",  # 3.9.7: Magic search in the You box's head, and its key
            "calm",  # 3.9.9: the calm board (calm.py): parts appear when they have something to show
            "show_studying",  # 3.9.10: Privacy's Show when I'm studying (never Reset board's)
            "send_errs")  # 3.9.9: Privacy's Send Sam what went wrong (errs.py; never Reset board's)
CHOICES = {"theme": ("auto", "light", "dark"),
           "accent": ("green", "blue", "purple", "teal", "amber", "rose"),
           "room_chip_side": ("left", "right"),
           "sev_break": ("breathe", "stretch")}  # 3.8.1: a fifteen's break
HIDEABLE = ("decks", "squads", "plans", "insights", "party")  # board.HIDEABLE_TABS: Crew's Decks, Squads; Plans, Insights (3.8.0); Pip Party (3.9.5)
PRIVACY = ("numbers", "showup", "paused")
LABEL_MAX = 24
# what Reset Board and Study puts back: this computer's look and layout, the Fifteen, the keys; never
# anything on Privacy, nor an account's own switches (Today's lists, Magic search, two buttons)
BOARD_DEFAULTS = {"show_leaderboard": True, "show_stale": True, "sync_notifications": True,
                  "theme": "auto", "accent": "green", "compact": False, "highlight_me": True,
                  "crew_label": "Crew", "room_chip_side": "right", "hidden_tabs": [], "shortcuts": True,
                  "fifteen": True, "sev": True, "sev_break": "breathe",
                  "dance_floor": True, "dance": "gentle", "dance_folded": False,
                  "calm": False, "calm_news": [],
                  "deck_counts": False}  # 3.9.6: the dance floor


# 3.9.12 (SC agreed): switches that left Settings. Each is put back to what it was by default, once,
# so nobody is left in a look they can no longer change: compact rows, my row's highlight, the keys'
# switch. (The room chip's side was one for an hour: it's where a thing is, not a look, and its row is back.) (The crew's name in shares lost its row too; a name someone set is kept.)
RETIRED = {"compact": False, "highlight_me": True, "shortcuts": True}


def retire(cfg):
    """The retired switches back at their defaults: {key: value} to save ({}: nothing to do)."""
    return {k: v for k, v in RETIRED.items() if k in cfg and cfg[k] != v}


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
        out = {"hidden_tabs": [k for k in HIDEABLE if k in hidden]}
        if val == "1" and cfg.get("calm"):  # 3.9.9: shown by hand, the calm board lets it out for good
            out["calm_open"] = [k for k in HIDEABLE if k in set(cfg.get("calm_open") or []) | {arg}]
        return out
    if cmd == "setlabel":
        text = " ".join(unquote(":".join(parts[1:])).split())
        from .backend.shapes import printable
        text = "".join(ch for ch in text if printable(ch))[:LABEL_MAX]
        return {"crew_label": text or "Crew"}
    if cmd == "setprivacy" and arg in PRIVACY:
        # the numbers keep their switches under the other two, for when
        # "My numbers" comes back
        return {"show_up": arg == "showup", "paused": arg == "paused"}
    if cmd == "setexam":
        # 3.9.2 (Sam's pick C1-A): an exam that's passed is kept (exam_last) when another takes its
        # place, so the next one's scope can start after it; a new exam's scope starts from the default
        # (3.9.2's audit: set on the exam's own day, it's kept too; an upcoming exam moved keeps its scope)
        old = _day(cfg.get("exam_date"))
        passed = bool(old) and old <= today.isoformat()
        keep = {}
        if passed and old > (_day(cfg.get("exam_last")) or ""):
            keep["exam_last"] = old
        if cfg.get("exam_since") and (passed or not old or arg == "off"):
            keep["exam_since"] = ""
        if arg == "off":
            return {"exam_date": "", **keep}
        day = _day(arg) or (_day(cfg.get("exam_date")) if arg == "on" else None)
        if arg == "on" and not day:
            day = (today + _dt.timedelta(days=7)).isoformat()
        return {"exam_date": day, **(keep if day != old else {})} if day else None
    if cmd == "setscope":
        # 3.9.2: what my exam covers: the cards I started since a day, the whole deck ("all"), or the
        # default ("auto": since my last exam, when it was in the last 10 weeks)
        if arg in ("all", "auto"):
            return {"exam_since": "all" if arg == "all" else ""}
        day = _day(arg)
        return {"exam_since": day} if day and day <= today.isoformat() else None
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
