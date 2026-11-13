"""The glue: Settings (the board's), its commands, the account's rename and delete."""

import datetime

from aqt import mw
from aqt.qt import QTimer
from aqt.utils import tooltip

from .. import ahead_flow
from .. import due_flow
from .. import errs_flow
from .. import plan_flow
from .. import rooms
from .. import sheets
from ..app import ADDON_VERSION
from ..app import _bg
from ..app import _state
from ..app import cfg
from ..app import client
from ..app import save_cfg
from ..errs import oops
from ..social import _edit_emoji
from ..social import _edit_status
from ..squads import open_squads

from .sync import _on_sync_done
from .render import _rerender
from .windows import _share_push, open_auth
from .commands import _swap


def _board_on_screen():
    c = cfg()
    return (mw.state == "deckBrowser" and c.get("show_leaderboard", True) and _state["board_shown"]
            and client().signed_in and not client().session_dead)


def _settings_view():
    """What the You tab shows. Main thread (deck names come from the collection)."""
    from ..board import _ago
    c, cl = cfg(), client()
    if cl.session_dead:
        state = "Sign-in expired"
    else:
        ago, _tone = _ago(cl.session.get("last_ok", ""))
        state = f"Synced {ago}" if ago else "Not synced yet"
    sync = " · ".join(x for x in (cl.email, state, f"v{ADDON_VERSION}" if ADDON_VERSION else "") if x)
    decks = []
    for did in c.get("shared_decks") or []:
        try:
            decks.append(mw.col.decks.name(int(did)))
        except Exception:
            continue
    crew = sum(1 for e in (_state["entries"] or []) if not e.get("you"))
    return {"tab": _state.get("settings_tab"), "signed_in": cl.signed_in, "name": cl.display_name,
            "emoji": c.get("emoji"), "status": c.get("status"), "sync": sync, "crew": crew,
            "squads": [s.get("name") for s in (c.get("squads") or []) if isinstance(s, dict) and s.get("name")],
            "decks": decks,
            "fsrs": _fsrs_on(),  # 3.9.1: two buttons' note, with FSRS off
            "leech_reach": _leech_reach(),  # 3.9.3: Recover leeches' line, by this profile's answer
            "new_stops": _new_stops()}  # 3.9.10: new cards stopped (Reviews ahead's, till then): Settings › Study turns them back on


def _new_stops():
    """[(deck id, its name)] for each deck whose new cards are stopped (plans.json's new_off)."""
    try:
        from .. import ahead_flow
        out = []
        for key in ahead_flow._off():
            name = str(mw.col.decks.name(int(key)) or "").split("::")[-1] if mw.col else ""
            if name:
                out.append((int(key), name))
        return out
    except Exception:
        oops()
        return []


def _leech_reach():
    """This profile's answer to Recover's one question ("deck", "eight"), or None."""
    try:
        return plan_flow._pcfg().get("leech_reach") if mw.col else None
    except Exception:
        return None


def _fsrs_on():
    """Whether FSRS is on in this collection; None when there's none open."""
    if not mw.col:
        return None
    try:
        return bool(mw.col.get_config("fsrs", False))
    except Exception:
        return None


def _settings_cmd(cmd, parts):
    """One click in the board's Settings. Changes apply at once."""
    from ..settings_model import TABS, change
    c = cfg()
    focus = ":".join([cmd] + parts)
    if cmd == "settab":
        if parts and parts[0] in TABS:
            _state["settings_tab"] = parts[0]
            _swap(c)
        return
    if cmd == "setclose":
        _state["settings_tab"] = None
        _swap(c)
        return
    if cmd == "setname":
        _rename()
    elif cmd == "setemoji":
        if _edit_emoji(mw) is not None:
            _swap(cfg(), focus)
    elif cmd == "setstatus":
        _edit_status(lambda _s: _swap(cfg(), focus))
    elif cmd == "setsquads":
        open_squads()
        _swap(cfg(), focus)
    elif cmd == "setsignin":
        _state["settings_tab"] = None
        open_auth()
    elif cmd == "setsignout":
        def out():
            _state["settings_tab"] = None
            client().sign_out()
            _on_signed_out()
        sheets.confirm("Sign out?", "Sign out on this device? Your account and stats stay.", "Sign out", out)
    elif cmd == "setdelete":
        _delete_account()
    elif cmd == "setfeedback":
        open_feedback()  # 3.6.5, P6
    else:
        changed = change([cmd] + parts, c)
        if changed:
            _apply_settings(changed, focus="label" if cmd == "setlabel" else focus)


def _pick_exam_day(cmd):
    """3.9.5 (Sam: "removing an exam date and then clicking add exam date
    makes anki quit"): Insights' Add exam date (exampick) and its scope's
    Change (scopepick) pick the day in a Qt calendar, then change it as
    Settings does (setexam, setscope)."""
    from ..settings_model import change
    from ..ui import pick_date
    c = cfg()
    today = datetime.date.today()
    try:
        today = datetime.date.fromisoformat(plan_flow._today() or "")
    except ValueError:
        pass
    if cmd == "exampick":
        try:
            now = datetime.date.fromisoformat(str(c.get("exam_date") or ""))
        except ValueError:
            now = today + datetime.timedelta(days=7)
        day = pick_date(mw, "Exam date", max(now, today), lo=today, hi=today + datetime.timedelta(days=730))
        changed = change(["setexam", day], c, today=today) if day else None
    else:
        try:
            now = datetime.date.fromisoformat(str(c.get("exam_since") or ""))
        except ValueError:
            now = today - datetime.timedelta(days=14)
        day = pick_date(mw, "Count the cards started since", min(now, today), hi=today)
        changed = change(["setscope", day], c, today=today) if day else None
    if changed:
        _apply_settings(changed)


def speak(c=None):
    """3.10.0 (words.py): the language from here on: Settings' pick, or Anki's own. At a profile's open and when
    the setting changes."""
    from .. import words
    try:
        import anki.lang
        anki_lang = getattr(anki.lang, "current_lang", "") or ""
    except Exception:
        anki_lang = ""
    return words.use(words.pick((c if c is not None else cfg()).get("lang"), anki_lang))


def _apply_settings(changed, focus=None):
    """Save what one change changed; the board redraws at once, and a
    sharing change goes out a moment later (one sync for a run of clicks)."""
    c = cfg()
    push = any(k in changed and changed[k] != c.get(k) for k in SHARE_KEYS)
    chip = any(k in changed and changed[k] != c.get(k, d) for k, d in
               (("room_chip_side", "right"), ("fifteen", True), ("sev", True), ("sev_break", "breathe")))  # 3.8.1
    leeches = changed.get("due_leeches") is True and not c.get("due_leeches")
    exam = "exam_date" in changed and str(changed["exam_date"] or "") != str(c.get("exam_date") or "")
    c.update(changed)
    save_cfg(c)
    if "lang" in changed:
        speak(c)  # 3.10.0: the redraw below is in the language just picked
    if exam:
        ahead_flow.exam_moved()  # 3.9.2's QoL pass: a pause to it follows now, not tomorrow
    if changed.get("show_leaderboard") is False:
        _state["settings_tab"] = None
        _rerender()
        tooltip("Due Crew is off the Decks screen. Tools › Due Crew › Show on the Decks screen brings it back.")
    else:
        # the focus names the command sent; after a toggle it's the opposite one
        _swap(c, focus=_flip(focus))
    if chip:
        rooms.refresh_widgets()
    if "shortcuts" in changed or "magic_search" in changed:
        _apply_keys()
    if "send_errs" in changed:
        errs_flow.switched(changed["send_errs"])  # 3.9.9: off, what's kept goes too
    if leeches:
        due_flow.recover_now()  # 3.8.0: now, and said, not at the next refresh
    if push:
        _share_push["n"] += 1
        n = _share_push["n"]
        QTimer.singleShot(2500, lambda: n == _share_push["n"] and _on_sync_done())


def _flip(focus):
    """set:compact:1 was clicked; the redrawn switch sends set:compact:0."""
    if not focus:
        return focus
    for a, b in ((":1", ":0"), (":0", ":1"), (":on", ":off"), (":off", ":on")):
        if focus.endswith(a) and not focus.startswith(("set:theme", "set:accent", "set:room")):
            return focus[:-len(a)] + b
    return focus


def _rename():
    cl = client()
    current = cl.display_name

    def go(name):
        name = name.strip()
        if not name or name == current:
            return

        def done(result):
            if not result:
                tooltip("Couldn't save the name. Try again.")
                return
            tooltip("Name changed.")
            _swap(cfg())
        _bg(lambda: cl.set_display_name(name), done)
    sheets.ask_text("Display name", "New name.", go, value=current or "", most=60)


def _delete_account():
    def go():
        cl = client()

        def done(result):
            if not result:
                tooltip("Couldn't delete. Check your connection and try again.")
                return
            _state["settings_tab"] = None
            _on_signed_out()
            tooltip("Account deleted.")
        _bg(lambda: cl.delete_account() or True, done)
    sheets.confirm("Delete account?", "This deletes your stats, your code, and your account for good. No undo.",
                   "Delete Account", go, danger=True)


def open_feedback():
    """3.6.5, P6: Send feedback (Tools › Due Crew, and Settings)."""
    if not client().signed_in:
        tooltip("Sign in to send feedback.")
        return
    from ..ui.feedback_dialog import FeedbackDialog
    FeedbackDialog(mw, client(), ADDON_VERSION, on_sent=lambda: tooltip("Sent. Thanks, every one is read.")).exec()


def open_settings(tab=None):
    """tab: "you", "board", "study" or "privacy" (your card's Privacy… opens that
    one). 3.8.0, one Settings: the board's, on the Decks screen, from
    anywhere (Tools › Due Crew › Settings…, the add-on's Config button);
    signed out or with the board turned off it shows too, since Settings
    is how the board comes back."""
    from ..settings_model import TABS
    _state["settings_tab"] = tab if tab in TABS else "you"
    _state["wrapped_open"] = None
    _close_addons_dialog()
    if mw.state != "deckBrowser":
        mw.moveToState("deckBrowser")  # its draw shows Settings
    elif _board_on_screen():
        _swap(cfg())
    else:
        _rerender()


def _browse_day(day):
    """3.8.0: a day on my own year (the profile card): the cards I answered
    that Anki day, in Browse."""
    try:
        d = datetime.date.fromisoformat(str(day))
        today = datetime.date.fromisoformat(due_flow._today())
    except (TypeError, ValueError):
        return
    ago = (today - d).days
    if ago < 0 or not mw.col:
        return
    end = (int(mw.col.sched.day_cutoff) - ago * 86400) * 1000
    cids = [int(x) for x in mw.col.db.list(
        "SELECT DISTINCT cid FROM revlog WHERE id >= ? AND id < ? AND ease > 0", end - 86400 * 1000, end)]
    plan_flow._browse(cids, empty="No reviews that day.")


def _close_addons_dialog():
    """The add-on's Config button opens Settings on the Decks screen: the
    Add-ons window in front of it closes."""
    try:
        import aqt
        inst = (getattr(aqt.dialogs, "_dialogs", {}).get("AddonsDialog") or [None, None])[1]
        if inst:
            inst.close()
    except Exception:
        pass


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("SHARE_KEYS", "_apply_keys", "_on_signed_out", "k")
SHARE_KEYS = _apply_keys = _on_signed_out = k = None
