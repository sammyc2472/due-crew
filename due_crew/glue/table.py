"""The glue: the Decks screen's commands, one table (BOARD_CMDS): after every part it names."""

from urllib.parse import unquote as _unquote

from .. import app
from .. import board
from .. import due_flow
from .. import errs_flow
from .. import gamenight_flow
from .. import magic_flow
from .. import plan_flow
from .. import sheets
from .. import together
from ..app import _state
from ..app import cfg
from ..shares import _share
from ..shares import dismiss_review
from ..social import _cheer_menu
from ..social import _edit_emoji
from ..social import _edit_status
from ..social import _open_profile
from ..social import row_menu
from ..squads import _add_back
from ..squads import _block_member
from ..squads import _copy_invite
from ..squads import _dismiss_knock
from ..squads import _drop_squad
from ..squads import _kick_member
from ..squads import _leave_squad
from ..squads import _make_founder
from ..squads import _open_squad_card
from ..squads import _select_squad
from ..squads import _send_knock
from ..squads import _share_squad
from ..squads import _toggle_squad_lock
from ..squads import open_squads

from .render import _bingo_cmd, _calm_cmd, _closet
from .settings import _browse_day, _pick_exam_day, open_settings
from .windows import _closet_cmd, _scrap_cmd, _share_menu, open_auth, open_decks, open_friends
from .commands import _cmd_addcode, _cmd_cheer_back, _cmd_cheer_send, _cmd_css, _cmd_emoji_picker, _cmd_emoji_picker_off, _cmd_notice_open, _cmd_period, _cmd_privacy, _cmd_refresh, _cmd_sort, _cmd_wrap_copy, _fridge_spot, _settings_family, _song, _swap, _swapping, _team, _team_squad, _wrap_put
from .refresh import _copy_friend_invite
from .profile import open_magic


# Settings' own (`_settings_cmd`)
SETTINGS_CMDS = ("settab", "setclose", "set", "settabs", "setlabel", "setprivacy", "setexam", "setscope",
                 "setaway", "setreset", "setname", "setemoji", "setstatus", "setsquads",
                 "setsignout", "setdelete", "setsignin", "setfeedback")

# families: a command by its first letters, its module knowing the rest
_FAMILIES = (
    ("plan", lambda c, p: plan_flow.on_message(p[1], p)),  # 3.1
    ("due", lambda c, p: due_flow.on_message(p[1], p)),  # Due
    ("ins", lambda c, p: _team(p[1], p)),
    ("closet", lambda c, p: _closet_cmd(p[1], p[2:])),  # 3.8.2: Pip's closet
    ("wrapped", lambda c, p: _scrap_cmd(p[1], p[2:])),  # 3.9.0's line: its x (wrappedx)
    ("scrap", lambda c, p: _scrap_cmd(p[1], p[2:])),  # 3.9.10: the scrapbook
)

# a command: (how many values after its name, a check on them, what it does with (cfg, parts))
BOARD_CMDS = {
    "usetold": (0, None, lambda c, p: (errs_flow.told(), _swap(cfg()))),  # 3.9.9: the foot's note on what's counted, Got it
    "usesee": (0, None, lambda c, p: (errs_flow.told(), open_settings("privacy"))),  # and its way to the switch
    "calmall": (0, None, _calm_cmd), "calmx": (0, None, _calm_cmd),  # 3.9.9: the calm board (calm.py)
    "calmopen": (1, lambda p: p[2] in ("decks", "squads", "plans", "insights"), _calm_cmd),
    "party": (0, None, lambda c, p: gamenight_flow.on_message(p)),  # 3.9.5's last round: You › Pip Party
    # 3.9.7: Magic search (Find a setting); 3.9.9: from its field under the deck list, with what was typed
    "magic": (0, None, lambda c, p: open_magic(" ".join(_unquote(":".join(p[2:])).split())[:400] if len(p) > 2 else "")),
    "css": (0, None, _cmd_css),
    "magichow": (0, None, lambda c, p: magic_flow.howto_said(p)),  # 3.9.7, round 2: its how-to's buttons
    **{k: (0, None, _song) for k in ("songsearch", "songuse", "songclear", "songkeep", "songaskoff", "songlisten", "songapp", "songapple",
                                     "dancehide", "danceshow", "dancemotion", "dancefold")},
    "youins": (0, None, lambda c, p: _team(p[1], p)),
    "sort": (1, lambda p: p[2] in board.SORT_KEYS, _cmd_sort),
    **{k: (0, None, lambda c, p: _bingo_cmd(p[1])) for k in ("bingo", "bingoback", "bingocopy")},
    "period": (1, lambda p: p[2] in board.PERIODS, _cmd_period),
    "refresh": (0, None, _cmd_refresh),
    "friends": (0, None, lambda c, p: open_friends()),
    "livetold": (0, None, lambda c, p: (together.live_told(), _swap(cfg()))),  # 3.9.10: the foot's note on the dot, Got it
    "livesee": (0, None, lambda c, p: (together.live_told(), open_settings("privacy"))),  # and its way to the switch
    "luckline": (1, None, lambda c, p: together.send_luck_line(p[2])),
    "luckthanks": (0, None, lambda c, p: together.luck_thanks()),
    "tricktip": (2, None, lambda c, p: together.send_tip(p[2], p[3])),
    "milestonecheer": (1, None, lambda c, p: together.milestone_cheer(p[2])),
    "milestonex": (1, None, lambda c, p: together.dismiss_milestone(p[2])),
    "unask": (1, lambda p: p[2].isdigit(), lambda c, p: together.unask(int(p[2]))),  # 3.5.0: Take back
    "copyinvite": (0, None, lambda c, p: _copy_friend_invite()),
    "addcode": (0, None, _cmd_addcode),
    "privacypage": (0, None, _cmd_privacy),
    "errsee": (0, None, lambda c, p: errs_flow.see_what_went()),  # 3.9.9: Privacy's See what went
    "sharemenu": (0, None, lambda c, p: _share_menu(c)),  # 3.7.1, H3
    "decks": (0, None, lambda c, p: open_decks()),
    "setup": (0, None, lambda c, p: open_auth()),
    "cheerpick": (1, None, lambda c, p: _cheer_menu(p[2])),
    # 3.9.1: the fridge: a Polaroid moved (no redraw), taken down (an Undo in its place for a few seconds), put back
    "fridgemove": (4, _fridge_spot,
                   lambda c, p: _closet(lambda cf: cf.move_fridge(p[2], p[3], int(p[4][:6]), int(p[5][:5])))),
    "fridgedown": (1, None, _swapping(lambda c, p: _closet(lambda cf: cf.take_down(p[2])))),
    "fridgeback": (1, None, _swapping(lambda c, p: _closet(lambda cf: cf.put_back(p[2])))),
    "emojipicker": (0, None, _cmd_emoji_picker),
    "emojipickeroff": (0, None, _cmd_emoji_picker_off),
    "cheersend": (1, None, _cmd_cheer_send),
    "sheet": (2, None, lambda c, p: sheets.answer(p[2], ":".join(p[3:]))),  # 3.9.1: a sheet's answer
    # 3.9.1: a window over the board; the bars dim with it
    "veil": (1, None, lambda c, p: app.veil(p[2] == "1" and app.board_up())),
    "rowmenu": (1, None, lambda c, p: row_menu(p[2])),  # 3.0.1: right-click a crewmate: mute, report
    "status": (0, None, lambda c, p: _edit_status()),
    "emoji": (0, None, lambda c, p: _edit_emoji()),
    "profile": (1, None, lambda c, p: _open_profile(p[2])),
    "evedismiss": (0, None, lambda c, p: _wrap_put(c, "eve_dismissed",
                                                   lambda w: _state["labels"][0] if _state["labels"] else "")),
    # 3.2.1: the admin's notice, dismissed for good on this profile
    "noticex": (1, lambda p: p[2].isdigit(), lambda c, p: _wrap_put(
        c, "notices_dismissed", lambda w: (list(w.get("notices_dismissed") or []) + [int(p[2])])[-50:])),
    "noticeopen": (0, None, _cmd_notice_open),
    "wrapdismiss": (0, None, lambda c, p: _wrap_put(c, "dismissed", lambda w: w.get("week", ""))),
    **{k: (0, None, lambda c, p: _share(p[1])) for k in ("sharetoday", "shareweek", "sharecrewweek", "sharemonth",
                                                         "shareyear", "monthcopy", "yearcopy")},
    **{k: (0, None, _swapping(lambda c, p: dismiss_review(p[1][:-7]))) for k in ("monthdismiss", "yeardismiss")},
    "wrapcopy": (0, None, _cmd_wrap_copy),
    "settings": (0, None, lambda c, p: open_settings(tab=p[2] if len(p) > 2 else None)),
    "heatday": (1, None, lambda c, p: _browse_day(p[2])),
    **{k: (0, None, _settings_family) for k in SETTINGS_CMDS},
    # 3.9.5: Insights' exam date and its scope, in a Qt calendar
    **{k: (0, None, lambda c, p: _pick_exam_day(p[1])) for k in ("exampick", "scopepick")},
    "ecard": (1, None, lambda c, p: _open_squad_card(p[2])),
    "squad": (1, None, lambda c, p: _select_squad(p[2])),
    "squadplan": (1, None, lambda c, p: _team_squad(p[2])),
    "squadadd": (0, None, lambda c, p: open_squads()),
    "squadinvite": (0, None, lambda c, p: _copy_invite()),
    "squadlock": (0, None, lambda c, p: _toggle_squad_lock()),
    "squadleave": (0, None, lambda c, p: _leave_squad()),
    "squadkick": (1, None, lambda c, p: _kick_member(p[2])),
    "squadblock": (1, None, lambda c, p: _block_member(p[2])),
    "squadfounder": (1, None, lambda c, p: _make_founder(p[2])),
    "squadshare": (0, None, lambda c, p: _share_squad()),
    "squaddrop": (1, None, lambda c, p: _drop_squad(p[2])),
    "addback": (1, None, lambda c, p: _add_back(p[2])),
    "knockmute": (1, None, lambda c, p: _dismiss_knock(p[2])),
    "knock": (1, None, lambda c, p: _send_knock(p[2])),
    "cheerback": (2, None, _cmd_cheer_back),
}
