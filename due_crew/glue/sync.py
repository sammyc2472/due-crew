"""The glue: after Anki's sync and after ours."""

import time

from aqt import mw

from .. import account
from .. import bingo_flow
from .. import cards as crew_cards
from .. import errs_flow
from .. import plan_flow
from ..app import HEATMAP_DAYS
from ..app import _profile_files
from ..app import _state
from ..app import cfg
from ..app import client
from ..backend.shapes import clean_emoji
from ..backend.shapes import shared_numbers
from ..errs import oops
from ..stats import gather_stats
from ..stats import gather_week
from ..stats import heatmap as cached_heatmap
from ..stats import held_streak
from ..stats import week_days
from ..stats.decks import gather_shared_decks
from ..stats.queries import StatsQueries

from .render import _last_studied
from .refresh import _morning, _run, refresh_board


def _on_sync_done(full=False, light=False, fetch=None):
    """Upload everything that changed, then fetch. Anki's sync hook and the
    board's Refresh both land here, so Refresh never leaves your own row
    behind; Refresh asks for the full week. light: the automatic pushes
    (on open, on a stale board) send today's numbers only — decks, heatmap,
    and backfill move slowly and cost main-thread SQL, so they wait for a
    real sync or a Refresh."""
    if not mw.col or not client().signed_in:
        return
    if not account.ready():
        # 2.13: my settings first, so a new computer never uploads defaults
        # over the account's (its shared decks, its privacy switches)
        account.ensure(lambda: _on_sync_done(full=full, light=light, fetch=fetch))
        return
    _run.last_attempt = time.time()
    # 3.1: the morning waits for the day's AnkiWeb sync; this may be it
    _morning(_awaiting_phone())
    c = cfg()
    # independent try blocks: one gatherer failing must not silently stop
    # the others from uploading (that failure mode is invisible in the UI)
    stats = week = decks = heat = None
    try:
        stats = gather_stats(mw.col, _profile_files())
        if _awaiting_phone():
            stats.streak = held_streak(stats.streak, client().sent_days(),
                                       StatsQueries(mw.col).day_label(0))
    except Exception:
        oops()
    if not light:
        try:
            week = gather_week(mw.col, _profile_files())
        except Exception:
            oops()
        try:
            # an install that has never had a deck list (and couldn't pull
            # one) doesn't upload an empty one over the account's
            if c.get("shared_decks") or c.get("shared_decks_set"):
                decks = gather_shared_decks(mw.col, c)
        except Exception:
            oops()
        try:
            heat = (cached_heatmap(StatsQueries(mw.col), _profile_files(), HEATMAP_DAYS)
                    if c.get("share_heatmap", True) else "off")
            if isinstance(heat, dict) and c.get("show_up"):
                heat = {lb: 1 for lb, n in heat.items() if n}  # just show up: which days, no counts
        except Exception:
            oops()
    row = None
    if stats is not None:
        row = {"name": client().display_name or "Me"}
        if c.get("show_up"):
            # just show up: no numbers, and the row is dated by the last day I
            # studied, so "today" on a squad board means I studied today
            row["day"] = _last_studied(StatsQueries(mw.col), stats)
        else:
            # the Privacy switches, as on the day docs: until 2.9 a squad got
            # all four numbers whatever the switches said
            row.update(shared_numbers({
                "reviews": int(stats.reviews), "studyTimeMs": int(stats.time_ms),
                "streak": int(stats.streak),
                "accuracy": None if stats.accuracy is None else float(stats.accuracy)}, c))
            if "reviews" in row:
                row["newCards"] = int(stats.new_cards)  # 2.13: under Reviews, never alone
        try:
            row["week"] = week_days(StatsQueries(mw.col))
        except Exception:
            oops()
        emoji = clean_emoji(c.get("emoji"))
        if emoji:
            row["emoji"] = emoji
        play = bingo_flow.for_row(c)  # 3.6: squad bingo, my week's facts
        if play:
            row["play"] = play
    plan_prog = None
    try:
        plan_prog = plan_flow.for_sync()
    except Exception:
        oops()
    extras = None
    try:
        extras = crew_cards.for_sync(c, light=light)  # 3.2: cards I know and I'm stuck on, my log
    except Exception:
        oops()
    try:
        from .. import team_flow
        team = team_flow.for_sync(c)  # 3.7.3: showed up today, and my squares, per plan team
        if team:
            extras = dict(extras or {}, team=team)
    except Exception:
        oops()
    try:
        sending = errs_flow.for_sync(c)  # 3.9.9: the days that are over, what went wrong, by code (Privacy's switch)
        if sending:
            extras = dict(extras or {}, **sending)
    except Exception:
        oops()
    _run.pushed = _push_key() if stats is not None else None
    refresh_board(upload_stats=stats, backfill=week, shared_decks=decks,
                  heatmap=heat, squad_row=row, full=full, fetch=fetch, plans=plan_prog, extras=extras)


def _push_key():
    """What a push's numbers come from: the collection (Anki moves its mod
    with every change, a sync's too), my day and my config."""
    try:
        return (mw.col.mod, StatsQueries(mw.col).day_label(0), cfg())
    except Exception:
        return None


def _on_anki_sync(*_args):
    """Anki's own sync finished: everything that changed goes up
    (_on_sync_done). 3.9.1: the one Anki runs as it closes (after
    profile_will_close) sends today's numbers only, as the pushes on open
    do, and nothing when the collection, my day and my config are as the
    last push that went had them: Anki waits on this before it can quit,
    and the upload's thread may not outlive it. Leaving a room still goes
    (rooms.on_close pushes it itself)."""
    if not _run.closing:
        _on_sync_done()
    elif _run.pushed is None or _run.pushed != _push_key() or _state.get("sync_error"):
        _on_sync_done(light=True)


# Names of the parts after this one. The package sets them as each of those parts loads
# (an import here would load a later part before the ones between).
_LATER = ("_awaiting_phone",)
_awaiting_phone = None
