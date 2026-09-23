"""Crew-only social surfaces: cheers (send, play, bookkeeping), the status
line, and the profile card. Squads have their own module; knocks live
there because they are a squad flow."""

import html

from aqt import mw
from aqt.utils import tooltip

from . import app, board
from .app import (CHEER_CLASSIC, CHEER_QUICK, HEATMAP_DAYS, _bg, _pending_cheers, _state,
                  cfg, client, save_cfg)
from .backend.firebase import clean_emoji, emoji_too_long
from .stats import duet_runs
from .stats.queries import StatsQueries

def _fresh_cheers(cheers, seen, old_ts=""):
    """(fresh, seen') — which cheers to play, and the per-sender marks to
    keep. Seen is per sender: one friend's clock (or a forged far-future
    `at`) can never hide everyone else's cheers behind one high-water mark.
    `seen` None = first run after v2.4: the old global mark folds in."""
    if seen is None:
        seen = {ch["from"]: ch["at"] for ch in cheers if ch["at"] <= old_ts}
    fresh = [ch for ch in cheers if seen.get(ch["from"]) != ch["at"]]
    present = {ch["from"] for ch in cheers}
    kept = {u: at for u, at in seen.items() if u in present}
    kept.update({ch["from"]: ch["at"] for ch in fresh})
    return fresh, kept


def _play_cheers():
    if not _pending_cheers or mw.state != "deckBrowser":
        return
    cheers = list(_pending_cheers)
    _pending_cheers.clear()
    names = sorted({ch["name"] for ch in cheers})
    emojis = [ch["emoji"] for ch in cheers]
    if len(names) == 1:
        text = f"{emojis[0]} {names[0]} sent cheers"
    else:
        text = f"{' '.join(dict.fromkeys(emojis))} {' and '.join(names)} sent cheers"
    back = (cheers[0]["from"], cheers[0]["emoji"]) if len(cheers) == 1 else None
    notes = [ch["note"] if len(cheers) == 1 else f"{ch['name']}: {ch['note']}"
             for ch in cheers if ch.get("note")]
    mw.web.eval(board.flurry_js(emojis, text, back=back, notes=notes))


def cheer_choices(stale):
    """(quick picks, any-emoji box?) for the picker. A server still on rules
    before v8 accepts only the classic three, so that is all the dialog
    offers then; the footer already says the server is behind."""
    return (CHEER_CLASSIC, False) if stale else (CHEER_QUICK, True)


def cheer_allowed(emoji, stale):
    """The one emoji to send, or ''. The same gate for the dialog and for
    a cheer-back click, whose emoji rides in from the page."""
    emoji = clean_emoji(emoji)
    if stale and emoji not in CHEER_CLASSIC:
        return ""
    return emoji


def _cheer_menu(to_uid):
    entry = next((e for e in (_state["entries"] or [])
                  if e["user_id"] == to_uid), None)
    if entry is None:
        return
    from .ui.cheer_dialog import CheerDialog
    stale = client().rules_stale
    quick, any_emoji = cheer_choices(stale)
    dlg = CheerDialog(mw, entry["name"], quick, any_emoji=any_emoji)
    if dlg.exec():
        emoji = cheer_allowed(dlg.emoji, stale)
        if emoji:
            _send_cheer(to_uid, entry["name"], emoji, dlg.note)


def _send_cheer(to_uid, to_name, emoji, note=""):
    cl = client()
    uid = cl.user_id
    my_name = cl.display_name or "A friend"

    def done(ok):
        if ok == "no-note":
            tooltip(f"Sent {html.escape(emoji)} to {html.escape(to_name)}. "
                    "The note needs a server update.")
        elif ok:
            tooltip(f"Sent {html.escape(emoji)} to {html.escape(to_name)}.")
        else:
            tooltip("Couldn't send. Check your connection.")

    _bg(lambda: cl.send_cheer(to_uid, uid, my_name, emoji, note or None), done)


def _edit_status():
    """Own card → "Set a status" / "edit". One line, crew-only, pushed
    right away (it rides today's stats doc). Empty clears it."""
    from aqt.qt import QInputDialog
    c = cfg()
    current = str(c.get("status") or "")
    text, ok = QInputDialog.getText(
        mw, "Status",
        "One line under your name, for your crew. Empty clears it.",
        text=current)
    if not ok:
        return
    text = " ".join(str(text).split())[:80]
    if text == current:
        return
    c["status"] = text
    save_cfg(c)
    lb = _state["labels"][0] if _state["labels"] else None
    for e in _state["entries"] or []:  # show it now; the upload confirms it
        if e["you"] and lb and e["days"].get(lb):
            doc = dict(e["days"][lb])
            if text:
                doc["status"] = text
            else:
                doc.pop("status", None)
            e["days"][lb] = doc
    app.rerender()
    app.sync()
    tooltip("Status set." if text else "Status cleared.")


def _edit_emoji():
    """Own card → "Pick an emoji" / "Change emoji". One glyph, in front of
    your name everywhere your crew sees it. Empty removes it."""
    from aqt.qt import QInputDialog
    c = cfg()
    current = str(c.get("emoji") or "")
    text, ok = QInputDialog.getText(
        mw, "Emoji", "One emoji, shown in front of your name. Empty removes it.",
        text=current)
    if not ok:
        return
    emoji = clean_emoji(text)
    if text.strip() and not emoji:
        tooltip("That one's too long. Try a simpler emoji." if emoji_too_long(text)
                else "That isn't an emoji.")
        return
    if emoji == current:
        return
    c["emoji"] = emoji
    save_cfg(c)
    for e in _state["entries"] or []:  # show it now; the upload confirms it
        if e["you"]:
            e["emoji"] = emoji
    app.rerender()
    app.sync()
    tooltip("Emoji set." if emoji else "Emoji removed.")


def _open_profile(uid):
    entry = next((e for e in (_state["entries"] or [])
                  if e["user_id"] == uid), None)
    if entry is None or not mw.col:
        return
    you = bool(entry.get("you"))
    q = StatsQueries(mw.col)
    my_labels = [q.day_label(i) for i in range(HEATMAP_DAYS)]
    my_days = set() if you else set(q.heatmap_counts(HEATMAP_DAYS))
    tomorrow = _state["tomorrow"]
    labels = _state["labels"]
    days = entry["days"]
    doc = (days.get(tomorrow) or (days.get(labels[0]) if labels else None)
           or next((days.get(lb) for lb in labels[1:] if days.get(lb)), None))
    streak_val = (doc or {}).get("streak")
    groups, _extras = board.build_deck_groups(_state["entries"])
    decks_line = ", ".join(g["label"] for g in groups
                           if any(u == uid for _n, _m, _d, u in g["rows"]))
    exam = board._exam_text(entry.get("exam_date", ""),
                            labels[0] if labels else "")
    exam = exam[:1].upper() + exam[1:] if exam else ""
    status = (str(cfg().get("status") or "") if you
              else str((doc or {}).get("status") or ""))
    today_doc = days.get(tomorrow) or (days.get(labels[0]) if labels else None)
    away = (board._away_text(today_doc, labels[0])
            if labels and today_doc and today_doc.get("away") else "")
    away = away[:1].upper() + away[1:] if away else ""
    cl = client()

    def show(counts):
        if True:
            if mw.state != "deckBrowser":
                return
            cells = same = duet = None
            if counts is not None:
                cells = [counts.get(lb, 0) for lb in reversed(my_labels)]
                if not you:
                    their_days = {lb for lb, n in counts.items() if n}
                    same = len(my_days & their_days)
                    run, best = duet_runs(my_days, their_days, my_labels[0])
                    mine_week = [lb in my_days for lb in reversed(labels)]
                    theirs_week = [
                        board._showed((days.get(tomorrow) or days.get(lb))
                                      if lb == labels[0] else days.get(lb))
                        for lb in reversed(labels)]
                    duet = {"run": run, "best": best,
                            "mine_week": mine_week, "theirs_week": theirs_week}
            mw.web.eval(board.profile_overlay_js({
                "name": entry["name"], "streak": streak_val,
                "last_active": entry["last_updated"], "cells": cells,
                "same_days": same, "decks_line": decks_line, "uid": uid,
                "you": you, "paused": bool(entry.get("paused")), "exam": exam,
                "duet": duet, "status": status, "away": away,
                "emoji": entry.get("emoji") or "",
            }))

    # your own card fetches your own heatmap doc: the honest, as-uploaded
    # state, not a local recomputation
    _bg(lambda: cl.fetch_heatmap(uid), show)
