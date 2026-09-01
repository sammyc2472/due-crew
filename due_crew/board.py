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

import html as _html
import json as _json
import time
from datetime import date as _date, datetime, timezone

from .stats.decks import sig_match

LIGHT = {
    "bg": "#ffffff", "ink": "#333333", "muted": "#7a7a72", "line": "#e2e2da",
    "accent": "#2e7d32", "accent-ink": "#ffffff", "you-bg": "#e9f2e9",
    "fresh": "#2e7d32", "hours": "#b26a00", "faded": "#aaaaa2",
    "well": "#f2f2ec",
}
DARK = {
    "bg": "#23271f", "ink": "#dfe1dc", "muted": "#989c92", "line": "#3d403b",
    "accent": "#7cc47f", "accent-ink": "#122912", "you-bg": "#2c372b",
    "fresh": "#7cc47f", "hours": "#dda45c", "faded": "#6d726a",
    "well": "#2b2d29",
}
NIGHT_SELECTORS = ("body.nightMode", "body.night_mode", "body.night-mode",
                   ":root.night-mode")

SORT_KEYS = ("reviews", "time", "retention", "streak")
PERIODS = ("today", "week", "days", "decks", "server")
HEADERS = (("reviews", "&#128218; Reviews"), ("time", "&#9201; Time"),
           ("retention", "&#127919; Retention"), ("streak", "&#128293; Streak"))
MEDALS = ("&#129351;", "&#129352;", "&#129353;")


def _token_block(palette):
    return "".join(f"--dc-{k}: {v}; " for k, v in palette.items())


def _theme_css(cfg):
    theme = cfg.get("theme", "auto")
    if theme == "light":
        return f"#due-crew {{ {_token_block(LIGHT)} }}"
    if theme == "dark":
        return f"#due-crew {{ {_token_block(DARK)} }}"
    night = ", ".join(f"{sel} #due-crew" for sel in NIGHT_SELECTORS)
    return (f"#due-crew {{ {_token_block(LIGHT)} }}\n"
            f"    @media (prefers-color-scheme: dark) {{ #due-crew {{ {_token_block(DARK)} }} }}\n"
            f"    {night} {{ {_token_block(DARK)} }}")


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
            "streak": doc.get("streak")}


def _week_row(days, labels):
    found = [days.get(lb) for lb in labels if days.get(lb)]
    if not found:
        return None
    reviews = [d["reviews"] for d in found if "reviews" in d]
    times = [d["studyTimeMs"] for d in found if "studyTimeMs" in d]
    accs = [(d["accuracy"], d.get("reviews", 1)) for d in found if "accuracy" in d]
    streak = next((d["streak"] for d in found if "streak" in d), None)
    acc = None
    if accs:
        weights = sum(max(r, 1) for _, r in accs)
        acc = sum(a * max(r, 1) for a, r in accs) / weights
    return {"reviews": sum(reviews) if reviews else None,
            "time_ms": sum(times) if times else None,
            "retention": acc, "streak": streak}


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


def sort_key(cfg):
    key = cfg.get("sort", "reviews")
    return key if key in SORT_KEYS else "reviews"


def build_rows(entries, labels, tomorrow, period, cfg):
    today_lb = labels[0] if labels else ""
    yest_lb = labels[1] if len(labels) > 1 else ""
    fresh, stale, quiet, paused = [], [], [], []
    for e in entries:
        row = {"user_id": e["user_id"], "name": e["name"], "you": e["you"],
               "paused": e["paused"], "last_updated": e["last_updated"],
               "reviews": None, "time_ms": None, "retention": None,
               "streak": None, "stale": False, "quiet": False,
               "back": bool(e.get("back")) and not e["paused"],
               "exam": "" if e["paused"] else
                       _exam_badge(e.get("exam_date"), today_lb)}
        if e["paused"]:
            paused.append(row)
            continue
        days = e.get("days") or {}
        if period == "week":
            agg = _week_row(days, labels)
            if agg is None:
                if e["you"]:
                    fresh.append(row)
                else:
                    row["quiet"] = True
                    quiet.append(row)
                continue
            row.update(agg)
            fresh.append(row)
        else:
            # a friend whose day rolled over ahead of mine writes my
            # "tomorrow" label — that's their live today
            today = days.get(tomorrow) or days.get(today_lb)
            yesterday = days.get(yest_lb)
            if today:
                row.update(_day_metrics(today))
                fresh.append(row)
            elif yesterday and cfg.get("show_stale", True) and not e["you"]:
                row.update(_day_metrics(yesterday))
                row["stale"] = True
                stale.append(row)
            elif e["you"]:
                fresh.append(row)
            else:
                # a quiet friend stays on the board — that's when a cheer lands
                row["quiet"] = True
                quiet.append(row)
    field = {"reviews": "reviews", "time": "time_ms",
             "retention": "retention", "streak": "streak"}[sort_key(cfg)]
    order = lambda r: r[field] if r[field] is not None else -1
    fresh.sort(key=order, reverse=True)
    stale.sort(key=order, reverse=True)
    quiet.sort(key=lambda r: r["last_updated"] or "", reverse=True)
    return fresh, stale + quiet + paused  # dormant rows last


def build_deck_groups(entries):
    """Groups anchored on your shared decks; extras are crew decks that match
    none of yours (a pointer to the Shared decks dialog)."""
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


def _css(cfg):
    pad = 3 if cfg.get("compact") else 6
    you_bg = "background: var(--dc-you-bg);" if cfg.get("highlight_me", True) else ""
    return f"""
    <style>
    {_theme_css(cfg)}
    #due-crew {{ margin: 18px auto 8px; max-width: 640px; color: var(--dc-ink);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; }}
    /* one radius language: board, cards, and overlays are 12px surfaces,
       inset banners 10px, buttons 6px, data bars 2px, pills full-round —
       controls are pills, data is rectangles */
    #due-crew.dc-frame {{ background: var(--dc-bg); border: 1px solid var(--dc-line);
      border-radius: 12px; padding: 16px 18px 10px;
      box-shadow: 0 10px 32px rgba(0,0,0,0.10); }}
    #due-crew .dc-head {{ display: flex; align-items: center; justify-content: space-between;
      gap: 10px; margin-bottom: 10px; }}
    #due-crew .dc-title {{ font-size: 15px; font-weight: 700; }}
    #due-crew .dc-pill {{ display: inline-block; font-size: 11px; font-weight: 700;
      padding: 1px 10px; border: 1px solid var(--dc-line); color: var(--dc-muted); text-decoration: none; }}
    #due-crew .dc-pill.on {{ background: var(--dc-accent); border-color: var(--dc-accent); color: var(--dc-accent-ink); }}
    #due-crew .dc-pill:first-child {{ border-radius: 99px 0 0 99px; }}
    #due-crew .dc-pill:last-child {{ border-radius: 0 99px 99px 0; }}
    #due-crew .dc-pill + .dc-pill {{ border-left: none; }}
    #due-crew .dc-scroll {{ overflow-x: auto; }}
    #due-crew table {{ width: 100%; border-collapse: collapse; }}
    #due-crew th {{ border-bottom: 1px solid var(--dc-line); padding: 2px 8px 5px; text-align: right; }}
    #due-crew th a {{ color: var(--dc-muted); font-size: 11px; font-weight: 700; text-decoration: none; white-space: nowrap; }}
    #due-crew th a.on {{ color: var(--dc-accent); }}
    #due-crew td {{ padding: {pad}px 8px; border-bottom: 1px solid var(--dc-line); white-space: nowrap; }}
    #due-crew tr:last-child td {{ border-bottom: none; }}
    #due-crew td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
    #due-crew td.rk {{ width: 30px; color: var(--dc-muted); }}
    #due-crew td.chc {{ width: 22px; padding-left: 2px; padding-right: 2px; text-align: center; }}
    #due-crew a.dc-cheer {{ text-decoration: none; opacity: 0.3; font-size: 12px; }}
    #due-crew a.dc-cheer:hover {{ opacity: 1; }}
    #due-crew tr.you td {{ {you_bg} }}
    #due-crew tr.you td:first-child {{ border-radius: 7px 0 0 7px; }}
    #due-crew tr.you td:last-child {{ border-radius: 0 7px 7px 0; }}
    #due-crew tr.you td.nm {{ font-weight: 700; }}
    #due-crew tr.dim td {{ color: var(--dc-faded); }}
    #due-crew .la {{ font-size: 10px; margin-left: 5px; }}
    #due-crew .la.fresh {{ color: var(--dc-fresh); }} #due-crew .la.hours {{ color: var(--dc-hours); }}
    #due-crew .la.faded {{ color: var(--dc-faded); }}
    #due-crew .dc-foot {{ display: flex; gap: 10px; font-size: 10.5px; color: var(--dc-muted); padding: 8px 4px 0; }}
    #due-crew .dc-foot .sp {{ flex: 1; }}
    #due-crew .dc-foot a {{ color: var(--dc-accent); text-decoration: none; font-weight: 700; }}
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
    #due-crew .exb {{ font-size: 10px; font-weight: 700; color: var(--dc-hours);
      margin-left: 5px; white-space: nowrap; }}
    #due-crew .bkb {{ font-size: 10px; font-weight: 700; color: var(--dc-accent);
      margin-left: 5px; white-space: nowrap; }}
    #due-crew .dc-wrap.eve {{ border-color: var(--dc-hours); }}
    #due-crew .dc-foot .warn {{ color: var(--dc-hours); }}
    #due-crew .surow {{ display: flex; align-items: center; gap: 12px;
      padding: {pad}px 0; font-size: 12.5px; }}
    #due-crew .surow.me .sun {{ font-weight: 700; }}
    #due-crew .surow.dim {{ color: var(--dc-faded); }}
    #due-crew .sun {{ width: 100px; flex-shrink: 0; overflow: hidden;
      text-overflow: ellipsis; white-space: nowrap; }}
    #due-crew .sudots {{ display: flex; gap: 7px; flex: 1; align-items: center; }}
    #due-crew .sudot {{ box-sizing: border-box; width: 11px; height: 11px;
      border-radius: 50%; background: var(--dc-accent);
      border: 1px solid transparent; flex-shrink: 0; }}
    #due-crew .sudot.off {{ background: var(--dc-well); border-color: var(--dc-line); }}
    #due-crew .sulet {{ width: 11px; text-align: center; font-size: 9px;
      font-weight: 700; color: var(--dc-muted); flex-shrink: 0; }}
    #due-crew .sulet.on {{ color: var(--dc-accent); }}
    #due-crew .sucount {{ width: 34px; flex-shrink: 0; text-align: right;
      font-variant-numeric: tabular-nums; font-size: 11px; color: var(--dc-muted); }}
    #due-crew .sunote {{ flex: 1; font-style: italic; font-size: 11.5px;
      color: var(--dc-faded); }}
    #due-crew .dg {{ margin-bottom: 12px; }}
    #due-crew .dgh {{ font-size: 12.5px; font-weight: 700; margin: 2px 0 5px; }}
    #due-crew .dr {{ display: flex; align-items: center; gap: 10px; padding: 3px 0; font-size: 12px; }}
    #due-crew .dr.me .dn {{ font-weight: 700; }}
    #due-crew .dn {{ width: 90px; flex-shrink: 0; overflow: hidden; text-overflow: ellipsis; }}
    #due-crew .dtrack {{ position: relative; flex: 1; height: 12px; background: var(--dc-well);
      border: 1px solid var(--dc-line); border-radius: 2px; overflow: hidden; }}
    #due-crew .dtrack i {{ position: absolute; left: 0; top: 0; bottom: 0; display: block; }}
    #due-crew .dtrack .fs {{ background: var(--dc-accent); opacity: 0.35; }}
    #due-crew .dtrack .fm {{ background: var(--dc-accent); }}
    #due-crew .dc-count {{ width: 118px; flex-shrink: 0; text-align: right;
      white-space: nowrap; font-variant-numeric: tabular-nums; font-size: 11px;
      color: var(--dc-muted); }}
    #due-crew .dc-line {{ font-size: 11.5px; color: var(--dc-muted); padding: 6px 0;
      border-top: 1px solid var(--dc-line); }}
    #due-crew .dc-card {{ padding: 16px; text-align: center; border: 1px solid var(--dc-line);
      border-radius: 12px; background: var(--dc-bg); }}
    #due-crew .dc-card b {{ font-size: 15px; display: block; margin-bottom: 5px; }}
    #due-crew .dc-card span {{ font-size: 12px; color: var(--dc-muted); }}
    #due-crew .dc-card a {{ color: var(--dc-accent); font-weight: 700; text-decoration: none; }}
    </style>
    """


def _pycmd(cmd):
    return f"pycmd('duecrew:{cmd}'); return false;"


def _head(period):
    pills = ""
    for key, label in (("today", "Today"), ("week", "Week"),
                       ("days", "Days"), ("decks", "Decks"),
                       ("server", "Server")):
        cls = "dc-pill on" if period == key else "dc-pill"
        pills += (f'<a class="{cls}" href="#" '
                  f'onclick="{_pycmd("period:" + key)}">{label}</a>')
    return (f'<div class="dc-head"><span class="dc-title">Due Crew</span>'
            f'<span>{pills}</span></div>')


def _row_html(row, rank, cfg):
    name = _html.escape(str(row["name"]))
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
        # the chip is a quiet row's whole story, so it ignores show_last_active
        txt, tone = _ago(row["last_updated"])
        if txt:
            la = f'<span class="la {tone}">({txt})</span>'
    else:
        if row["stale"]:
            cls += " dim"
            extra = ' <span class="la faded">&middot; yesterday</span>'
        cells = (f'<td class="n">{_cell(row["reviews"], lambda v: format(v, ","))}</td>'
                 f'<td class="n">{_cell(row["time_ms"], _fmt_time)}</td>'
                 f'<td class="n">{_cell(row["retention"], lambda v: f"{v:.1f}%")}</td>'
                 f'<td class="n">{_cell(row["streak"])}</td>')
        if cfg.get("show_last_active", True) and not row["stale"]:
            txt, tone = _ago(row["last_updated"])
            if txt:
                la = f'<span class="la {tone}">({txt})</span>'
    exam = row.get("exam") or ""
    if row.get("back") and not row["quiet"]:
        # the day a quiet friend returns, the board says so
        exam = ' <span class="bkb">&#128075; back</span>' + exam
    if row["you"]:
        cheer = '<td class="chc"></td>'
        name = (f'<a class="dc-pl" href="#" title="See what your crew sees" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{name}</a>')
    else:
        cheer = (f'<td class="chc"><a class="dc-cheer" href="#" title="Send a cheer" '
                 f'onclick="{_pycmd("cheerpick:" + str(row["user_id"]))}">&#127881;</a></td>')
        name = (f'<a class="dc-pl" href="#" title="Open profile" '
                f'onclick="{_pycmd("profile:" + str(row["user_id"]))}">{name}</a>')
    return (f'<tr class="{cls.strip()}"><td class="rk">{rank}</td>'
            f'<td class="nm">{name}{exam}{la}{extra}</td>{cells}{cheer}</tr>')


def _table_html(data, cfg, period):
    sort = sort_key(cfg)
    fresh, dormant = build_rows(data["entries"], data["labels"],
                                data.get("tomorrow", ""), period, cfg)
    heads = "<th></th><th></th>"
    for key, label in HEADERS:
        on = "on" if key == sort else ""
        arrow = " &#9662;" if key == sort else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{label}{arrow}</a></th>')
    heads += "<th></th>"
    body = ""
    for i, row in enumerate(fresh):
        rank = MEDALS[i] if i < 3 else f"#{i + 1}"
        body += _row_html(row, rank, cfg)
    for row in dormant:
        body += _row_html(row, "&mdash;", cfg)
    solo = ""
    if len(data["entries"]) == 1 and not data.get("pending"):
        solo = ('<div class="dc-line">Just you so far &mdash; share your code '
                'from the Friends screen.</div>')
    # narrow windows scroll the table inside the frame instead of bleeding
    # square content past the rounded border
    return f'<div class="dc-scroll"><table><tr>{heads}</tr>{body}</table></div>{solo}'


def _days_html(data, cfg):
    """The anti-leaderboard: who showed up, the last 7 days, no numbers.
    You first, then alphabetical — the order never moves with effort."""
    labels = data["labels"]
    tomorrow = data.get("tomorrow", "")
    cols = list(reversed(labels))  # oldest -> today, left to right
    entries = data["entries"]
    me = [e for e in entries if e["you"]]
    others = sorted((e for e in entries if not e["you"]),
                    key=lambda e: (bool(e["paused"]), str(e["name"]).lower()))
    letters = ""
    for lb in cols:
        try:
            letter = "MTWTFSS"[_date.fromisoformat(lb).weekday()]
        except (TypeError, ValueError):
            letter = "&middot;"
        on = " on" if lb == (labels[0] if labels else "") else ""
        letters += f'<span class="sulet{on}">{letter}</span>'
    html = (f'<div class="surow"><span class="sun"></span>'
            f'<div class="sudots">{letters}</div><span class="sucount"></span></div>')
    for e in me + others:
        name = _html.escape(str(e["name"]))
        if e["paused"]:
            html += (f'<div class="surow dim"><span class="sun">{name}</span>'
                     f'<span class="sunote">on a break</span>'
                     f'<span class="sucount"></span></div>')
            continue
        days = e.get("days") or {}
        dots = ""
        n = 0
        for lb in cols:
            doc = days.get(lb)
            if labels and lb == labels[0]:
                doc = days.get(tomorrow) or doc
            on = _showed(doc)
            n += 1 if on else 0
            dots += f'<span class="sudot{"" if on else " off"}"></span>'
        recent = (days.get(tomorrow) or (days.get(labels[0]) if labels else None)
                  or (days.get(labels[1]) if len(labels) > 1 else None))
        cls = "surow me" if e["you"] else ("surow" if recent else "surow dim")
        html += (f'<div class="{cls}"><span class="sun">{name}</span>'
                 f'<div class="sudots">{dots}</div>'
                 f'<span class="sucount">{n}/{len(cols)}</span></div>')
    html += ('<div class="dc-line" style="border-top: none;">'
             'a dot = a day with at least one answered card</div>')
    return html


def _bar(name, is_me, d, delta=None):
    total = max(int(d.get("total") or 0), 1)
    seen_pct = min(100, round(100 * int(d.get("seen") or 0) / total))
    mature_pct = min(100, round(100 * int(d.get("mature") or 0) / total))
    counts = f'{int(d.get("seen") or 0):,} / {int(d.get("total") or 0):,}'
    chip = f'<span class="dc-delta">+{delta:,} wk</span>' if delta else ""
    return (f'<div class="dr{" me" if is_me else ""}">'
            f'<span class="dn">{_html.escape(str(name))}</span>'
            f'<div class="dtrack"><i class="fs" style="width:{seen_pct}%;"></i>'
            f'<i class="fm" style="width:{mature_pct}%;"></i></div>'
            f'<span class="dc-count">{counts}{chip}</span></div>')


def _decks_html(data, deltas=None):
    deltas = deltas or {}
    groups, extras = build_deck_groups(data["entries"])
    if not groups and not extras:
        return ('<div class="dc-line" style="border-top: none;">No shared decks yet. '
                f'<a href="#" onclick="{_pycmd("decks")}">Pick decks to share</a> '
                '&mdash; decks you and your crew both study match automatically.</div>')
    html = ""
    for g in groups:
        label = _html.escape(str(g["label"]))
        rows = "".join(
            _bar(n, me, d, deltas.get((uid, d.get("name", ""))))
            for n, me, d, uid in g["rows"])
        html += f'<div class="dg"><div class="dgh">{label}</div>{rows}</div>'
    for who, deck in extras[:3]:
        html += (f'<div class="dc-line">{_html.escape(str(who))} shares '
                 f'&ldquo;{_html.escape(str(deck))}&rdquo; &mdash; '
                 f'<a href="#" onclick="{_pycmd("decks")}">open Shared decks</a> to join.</div>')
    html += ('<div class="dc-line" style="border-top: none; padding-top: 2px;">'
             'light = seen &middot; dark = mature &middot; % of each person&rsquo;s own copy</div>')
    return html


SERVER_SORTS = (("reviews", "&#128218; Reviews"), ("time", "&#9201; Time"),
                ("streak", "&#128293; Streak"))


def _server_html(view, cfg):
    """The server board: everyone here chose to be. Plain ranks — no medals,
    no cheers, no celebration surfaces; these aren't necessarily people you
    know. Add lives on the person's card (click a name), not on the row."""
    state = view.get("state")
    label = _html.escape(str(view.get("server") or "this server"))
    if state == "optin":
        return (f'<div class="dc-card"><b>The server board</b>'
                f'<span>Everyone on {label} who&rsquo;s sharing &mdash; and the '
                f'place to find new crew. Sharing goes both ways: turn it on in '
                f'<a href="#" onclick="{_pycmd("settings")}">Privacy</a> '
                f'to see the board and be on it.</span></div>')
    if state == "loading":
        return '<div class="dc-line" style="border-top: none;">Fetching the board&hellip;</div>'
    if state == "error":
        return ('<div class="dc-line" style="border-top: none;">Couldn&rsquo;t '
                'reach the board. Check your connection and Refresh.</div>')
    rows = view.get("rows") or []
    sort = sort_key(cfg)
    field = {"reviews": "reviews", "time": "time_ms",
             "streak": "streak"}.get(sort, "reviews")
    rows = sorted(rows, key=lambda r: r.get(field) or 0, reverse=True)
    heads = (f'<th style="text-align: left; font-weight: 400;" colspan="2">'
             f'<span style="color: var(--dc-muted); font-size: 11px;">{label} &middot; {len(rows)} today</span></th>')
    for key, htext in SERVER_SORTS:
        on = "on" if key == sort or (key == "reviews" and field == "reviews"
                                     and sort not in ("time", "streak")) else ""
        arrow = " &#9662;" if on else ""
        heads += (f'<th><a class="{on}" href="#" '
                  f'onclick="{_pycmd("sort:" + key)}">{htext}{arrow}</a></th>')
    body = ""
    for i, r in enumerate(rows):
        name = _html.escape(str(r["name"]))
        uid = str(r["user_id"])
        cls, note = "", ""
        if r.get("you"):
            cls = "you"
            link = (f'<a class="dc-pl" href="#" title="See what your crew sees" '
                    f'onclick="{_pycmd("profile:" + uid)}">{name}</a>')
        else:
            if r.get("crew"):
                note = ' <span class="la faded">&middot; crew</span>'
            elif r.get("pending"):
                note = ' <span class="la faded">&middot; knocked</span>'
            link = (f'<a class="dc-pl" href="#" title="Open card" '
                    f'onclick="{_pycmd("scard:" + uid)}">{name}</a>')
        body += (f'<tr class="{cls}"><td class="rk">#{i + 1}</td>'
                 f'<td class="nm">{link}{note}</td>'
                 f'<td class="n">{format(r["reviews"], ",")}</td>'
                 f'<td class="n">{_fmt_time(r["time_ms"])}</td>'
                 f'<td class="n">{r["streak"]}</td></tr>')
    if not body:
        return ('<div class="dc-line" style="border-top: none;">No one&rsquo;s '
                'on the board yet today.</div>')
    note = ('<div class="dc-line" style="border-top: none;">today only &middot; '
            'click a name to see their card &mdash; adding starts there</div>')
    return (f'<div class="dc-scroll"><table><tr>{heads}</tr>{body}</table></div>'
            f'{note}')


def render(data, cfg, fetched_at, wrap=None, deltas=None, exam_eve=None,
           rules_stale=False, server_view=None):
    period = cfg.get("period", "today")
    if period not in PERIODS:
        period = "today"
    body = (_decks_html(data, deltas) if period == "decks"
            else _days_html(data, cfg) if period == "days"
            else _server_html(server_view or {"state": "optin"}, cfg)
            if period == "server"
            else _table_html(data, cfg, period))
    if wrap:
        extra = ""
        if (wrap.get("full_days") or 0) >= 3:
            extra = f' &middot; everyone showed up {wrap["full_days"]} of 7 days'
        if wrap.get("best_name"):
            extra += (f' &middot; {_html.escape(str(wrap["best_name"]))}&rsquo;s '
                      f'best week yet')
        if wrap.get("milestone"):
            extra += (f' &middot; and the crew just passed '
                      f'<b>{_html.escape(str(wrap["milestone"]))} all-time</b>')
        body = (f'<div class="dc-wrap"><span>&#127881;</span>'
                f'<span><b>Last week, together:</b> '
                f'{wrap["reviews"]:,} reviews &middot; {_fmt_time(wrap["time_ms"])}{extra}</span>'
                f'<a class="wc" href="#" title="Copy for the group chat" '
                f'onclick="{_pycmd("wrapcopy")}">Copy</a>'
                f'<a class="wx" href="#" title="Dismiss" '
                f'onclick="{_pycmd("wrapdismiss")}">&times;</a></div>') + body
    if exam_eve and exam_eve.get("people"):
        links = [f'<a class="dc-pl" href="#" title="Send a cheer" '
                 f'onclick="{_pycmd("cheerpick:" + str(u))}">'
                 f'<b>{_html.escape(str(n))}</b></a>'
                 for u, n in exam_eve["people"]]
        if len(links) == 1:
            uid = exam_eve["people"][0][0]
            line = (f'{links[0]}&rsquo;s exam is tomorrow. '
                    f'A &#128170; tonight goes a long way.')
            act = (f'<a class="wc" href="#" title="Send a cheer" '
                   f'onclick="{_pycmd("cheerpick:" + str(uid))}">&#128170; Send one</a>')
        else:
            line = (" and ".join(links) + " have exams tomorrow. "
                    "A &#128170; tonight goes a long way.")
            act = ""
        body = (f'<div class="dc-wrap eve"><span>&#128214;</span>'
                f'<span>{line}</span>{act}'
                f'<a class="wx" href="#" title="Dismiss" '
                f'onclick="{_pycmd("evedismiss")}">&times;</a></div>') + body

    n_pending = len(data.get("pending", []))
    if n_pending:
        s = "s" if n_pending > 1 else ""
        left = (f'{n_pending} invite{s} pending &middot; '
                f'<a href="#" onclick="{_pycmd("friends")}">Friends</a>')
    else:
        left = f'<a href="#" onclick="{_pycmd("friends")}">Friends</a>'
    if rules_stale:
        left = (f'<span class="warn">&#9888;</span> <a href="#" '
                f'onclick="{_pycmd("rules")}">Server rules need an update</a>'
                f' &middot; ') + left
    if period == "decks":
        left += f' &middot; <a href="#" onclick="{_pycmd("decks")}">Shared decks</a>'

    ago, _tone = _ago_secs(max(0.0, time.time() - fetched_at)) if fetched_at else ("just now", "")
    foot = (f'<div class="dc-foot"><span>{left}</span><span class="sp"></span>'
            f'<span>Updated {ago} &middot; <a href="#" '
            f'onclick="{_pycmd("refresh")}">Refresh</a></span></div>')

    return (f'<div id="due-crew" class="dc-frame">'
            f'{_css(cfg)}{_head(period)}{body}{foot}</div>')


def _card(cfg, title, body_html):
    return (f'<div id="due-crew">{_css(cfg)}<div class="dc-card">'
            f'<b>{title}</b><span>{body_html}</span></div></div>')


def signed_out_card(cfg):
    return _card(cfg, "Due Crew",
                 f'Your studying, alongside your friends\'. '
                 f'<a href="#" onclick="{_pycmd("setup")}">Join your crew</a>')


def loading_card(cfg):
    return _card(cfg, "Due Crew", "Catching up with your crew&hellip;")


def flurry_js(emojis, banner_text, back=None):
    """Injected via web.eval after render — never inline in board HTML.
    Banner picks its colors from the page's night classes. When `back` is
    (uid, emoji) — a single sender — the banner is clickable to return the
    cheer, and stays up a little longer."""
    emoji_list = _json.dumps(emojis)
    banner = _json.dumps(banner_text)
    back_cmd = _json.dumps(f"duecrew:cheerback:{back[0]}:{back[1]}" if back else None)
    return """
    (function() {
        if (document.getElementById('dc-flurry')) { return; }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        var backCmd = %s;
        var banner = document.createElement('div');
        var title = document.createElement('div');
        title.textContent = %s;
        banner.appendChild(title);
        banner.style.cssText = 'position:fixed;top:18vh;left:50%%;transform:translateX(-50%%);' +
            'z-index:70;border-radius:12px;padding:10px 20px;font-weight:700;font-size:15px;' +
            'text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.3);transition:opacity 0.5s;' +
            (night ? 'background:#262b24;color:#dfe1dc;border:1px solid #7cc47f;'
                   : 'background:#ffffff;color:#23281f;border:1px solid #2e7d32;');
        var linger = 2600;
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
    """ % (back_cmd, banner, emoji_list)


def stranger_card_js(info):
    """Card for a server-board member who isn't crew. Deliberately spare —
    no heatmap, no cheer, no celebration: we don't necessarily know them.
    info: uid, name, reviews, time_ms, streak, pending (bool)."""
    name = _html.escape(str(info.get("name", "?")))
    stat = (f'{format(int(info.get("reviews") or 0), ",")} reviews today '
            f'&middot; {_fmt_time(int(info.get("time_ms") or 0))} '
            f'&middot; {int(info.get("streak") or 0)}-day streak')
    inner = _json.dumps(
        f'<div style="display: flex; align-items: baseline; gap: 8px;">'
        f'<span style="font-size: 15px; font-weight: 700;">{name}</span>'
        f'<span style="opacity: 0.6; font-size: 10.5px; text-transform: uppercase;'
        f' letter-spacing: 0.08em;">on the server board</span></div>'
        f'<div style="font-size: 12px; opacity: 0.8; padding: 6px 0 2px;">{stat}</div>'
        f'<div style="font-size: 11.5px; opacity: 0.65; padding: 2px 0 0;">'
        f'Crew see each other&rsquo;s weeks, days, decks, and heatmaps.</div>')
    if info.get("pending"):
        act_label = _json.dumps("\u23F3 Knocked — waiting for them")
        act_cmd, act_primary = _json.dumps(None), "false"
    else:
        act_label = _json.dumps("\U0001F91D Add to crew")
        act_cmd = _json.dumps(f"duecrew:knock:{info.get('uid', '')}")
        act_primary = "true"
    return """
    (function() {
        var old = document.getElementById('dc-profile');
        if (old) { old.remove(); }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        var accent = night ? '#7cc47f' : '#2e7d32';
        var back = document.createElement('div');
        back.id = 'dc-profile';
        back.style.cssText = 'position:fixed;inset:0;z-index:80;background:rgba(0,0,0,0.35);' +
            'display:flex;align-items:flex-start;justify-content:center;padding-top:16vh;';
        var card = document.createElement('div');
        card.style.cssText = 'min-width:300px;max-width:380px;border-radius:12px;padding:16px 20px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);' +
            (night ? 'background:#23271f;color:#dfe1dc;border:1px solid #3d403b;'
                   : 'background:#ffffff;color:#333333;border:1px solid #e2e2da;');
        var body = document.createElement('div');
        body.innerHTML = %s;
        card.appendChild(body);
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:8px;margin-top:12px;';
        var actCmd = %s;
        var act = document.createElement('button');
        act.textContent = %s;
        var primary = %s;
        act.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;' +
            (primary ? 'background:' + accent + ';color:' + (night ? '#122912' : '#ffffff') +
                       ';border:1px solid transparent;font-weight:600;cursor:pointer;'
                     : 'background:none;color:inherit;opacity:0.7;border:1px solid ' +
                       (night ? '#3d403b' : '#e2e2da') + ';cursor:default;');
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
            (night ? '#3d403b' : '#e2e2da') + ';';
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
    """ % (inner, act_cmd, act_label, act_primary)


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
      paused (bool), exam (str, client-built text or "").
    For your own card ("you") the overlay shows exactly what the crew sees,
    and the cheer button becomes a Privacy shortcut. Everything user-sourced
    is escaped here; the JS only injects the built HTML and wires buttons."""
    you = bool(profile.get("you"))
    name = _html.escape(str(profile.get("name", "?")))
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
    if profile.get("paused"):
        head += ('<div style="font-size: 12px; font-style: italic; '
                 'opacity: 0.7; padding: 4px 0 0;">on a break</div>')
    if profile.get("exam"):
        head += (f'<div class="dcex" style="font-size: 12px; font-weight: 700; '
                 f'padding: 4px 0 0;">&#128214; '
                 f'{_html.escape(str(profile["exam"]))}</div>')

    cells = profile.get("cells")
    if cells is None:
        private = "Your heatmap is private." if you else "Their heatmap is private."
        grid = (f'<div style="font-size: 12px; opacity: 0.7; margin: 12px 0;">'
                f'{private}</div>')
    else:
        cols = []
        week = []
        for n in cells:
            week.append(_heat_level(int(n)))
            if len(week) == 7:
                cols.append(week)
                week = []
        if week:
            cols.append(week + [0] * (7 - len(week)))
        col_html = ""
        for col in cols[-26:]:
            cell_html = "".join(
                f'<i class="dchm h{lvl}"></i>' for lvl in col)
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
        lines += (f'<div style="font-size: 12px; padding: 2px 0;">'
                  f'You&rsquo;ve studied on <b>{int(profile["same_days"])} of the '
                  f'same days</b> this half-year.</div>')
    if profile.get("decks_line"):
        prefix = "Shares with your crew: " if you else "Shares with you: "
        lines += (f'<div style="font-size: 12px; padding: 2px 0; opacity: 0.8;">'
                  f'{prefix}{_html.escape(str(profile["decks_line"]))}</div>')

    inner = _json.dumps(head + grid + lines)
    if you:
        act_label, act_primary = _json.dumps("Privacy…"), "false"
        act_cmd = _json.dumps("duecrew:settings")
    else:
        act_label, act_primary = _json.dumps("\U0001F389 Send a cheer"), "true"
        act_cmd = _json.dumps(f"duecrew:cheerpick:{profile.get('uid', '')}")
    return """
    (function() {
        var old = document.getElementById('dc-profile');
        if (old) { old.remove(); }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        var accent = night ? '#7cc47f' : '#2e7d32';
        var warn = night ? '#dda45c' : '#b26a00';
        var back = document.createElement('div');
        back.id = 'dc-profile';
        back.style.cssText = 'position:fixed;inset:0;z-index:80;background:rgba(0,0,0,0.35);' +
            'display:flex;align-items:flex-start;justify-content:center;padding-top:14vh;';
        var card = document.createElement('div');
        card.style.cssText = 'min-width:340px;max-width:420px;border-radius:12px;padding:16px 20px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);' +
            (night ? 'background:#23271f;color:#dfe1dc;border:1px solid #3d403b;'
                   : 'background:#ffffff;color:#333333;border:1px solid #e2e2da;');
        var style = document.createElement('style');
        style.textContent = '.dchg{display:flex;gap:2px;margin:12px 0 8px;}' +
            '.dchc{display:flex;flex-direction:column;gap:2px;}' +
            '.dchm{width:8px;height:8px;border-radius:1.5px;display:block;background:' +
            (night ? '#2b2d29' : '#f2f2ec') + ';}' +
            '.dchm.h1{background:' + accent + ';opacity:0.25;}' +
            '.dchm.h2{background:' + accent + ';opacity:0.45;}' +
            '.dchm.h3{background:' + accent + ';opacity:0.7;}' +
            '.dchm.h4{background:' + accent + ';}' +
            '.dcex{color:' + warn + ';}' +
            '.dcduet{display:flex;align-items:center;gap:8px;padding:1px 0;}' +
            '.dcdl{width:42px;flex-shrink:0;font-size:10px;opacity:0.65;' +
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
            '.dcd{width:9px;height:9px;border-radius:50%%;display:inline-block;' +
            'margin-right:6px;background:' + accent + ';}' +
            '.dcd.off{background:' + (night ? '#2b2d29' : '#f2f2ec') + ';}';
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
                (primary ? 'background:' + accent + ';color:' + (night ? '#122912' : '#ffffff') +
                           ';border:1px solid transparent;font-weight:600;'
                         : 'background:none;color:inherit;border:1px solid ' +
                           (night ? '#3d403b' : '#e2e2da') + ';');
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
