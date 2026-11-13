"""3.1 plans, the glue: what this computer remembers about the plans I
follow, the morning, progress for the sync, the Decks tab's plan card,
and the menus. Main-thread rules as in __init__: every collection read and
the one unsuspend step happen here, on the main thread; plan_flow makes a
request of its own only on a click (follow, pause, stop) and, for a plan
I write, at the day's first refresh (send_ids, send_trees: in the
background, only when what they send changed).

Per profile and computer, in user_files/<profile>/plans.json (deck ids
belong to one collection, so not in the add-on's config, which every
profile shares); never sent. Follow, share, pause, my days and my pace
live on the server; the board's plans are cached in the session
(api.fetch_board), so a light refresh and an offline morning have them.

plans.json, per profile:
  plans                  {plan id: the plan's state here, below}
  plans_day              the Anki day the morning last ran
  plans_opened           the last open's {day, label, per, units, spread, was, dates}: its undo line (3.8.1: by date)
  plan_offers_dismissed  squad offers waved off (the last 50)
  own_last               at my own pace, the last Open or Put back {pid, uid, name, kind, label, n, day, was}
  built                  filtered decks Due Crew built here (the last 200), for the morning's tidy
  authored_tags          plans I write, not follow: {plan id: {deck_id, tags, tags_sig, tags_day}}
  ids_sent               {plan id: hash of the note ids, counts and refs last sent} (send_ids)
  trees_sent             3.8.1: {deck name, lowercased: {h, day}}, its tree last sent, the day last read (send_trees)
  posts_seen             {plan id: the newest post read}
  aside_ok               {plan id: [leeches, missing]} as last OK'd
  fallback_ok            {plan id: true}: its renamed-tags note OK'd
  lesson_next            {plan id: true}: Today's lesson B, chosen before the plan runs here (the last 50)
  due, team_seen, map_snaps, ins_fsrs_hide, ins_hard_hide: due_flow's and team_flow's

plans[plan id], one plan on this computer:
  deck_id, swap          the deck it runs on here, and the tag swap ([theirs, mine]) or None
  applied                {unit id: sig | "skip:" + sig}: dates opened here, or skipped
  src                    {unit id: what it matched when applied}: a change opens only what it adds
  sig2                   1 once applied sigs carry C5's ids (3.7.2)
  seen_version, snapshot the plan as last seen, for the change note
  later                  {unit id: day}: put off (Not today) to that morning
  held                   cards the plan shut when I asked (Hold back, Put back): Stop opens them
  hold_yes               3.8.1: I said yes to Hold back; hold_new holds what authors add later
  catch                  G5's catch-up {until, extra}: Anki's today-only limit each morning
  missed                 3.8.1: the missed-days answer {mode, day} (3.2; was `catch` before)
  own_opened             at my own pace {unit id: the day I opened it, "" when opened elsewhere}
  checks                 checkpoints and review days built {key: {day, at, name, cids}}
  leeches, missing       {unit id: n}, {unit id: [missing, of]}: what a date left shut, when it opened
  tags, tags_sig, tags_day  the plan's own tags on my notes {tag id: path}, its sig, the day read
  tag_news               {day, names, more, missing}: tags that came today, said once
  away                   3.8.1, Welcome back's question {day, days, units, n}: dates from days I studied
                         nothing, kept back (in `later`) till it's answered; asked again each morning
  lesson_deck            Today's lesson: true, each open lesson a deck of its own (B); absent, in the deck (A)
  lesson_decks, lesson_held, lesson_folder  B: {unit id: its deck id}, {unit id: cards another add-on's
                         filtered deck holds}, the plan's folder of them ("Due Crew::Path Book")

3.8.1, read as today's (_upgrade, _hold_yes): an old `catch` {mode, day}
moves to `missed`; `held` without `hold_yes` was a yes on the plan's dates
and isn't one at my own pace (Put back put its cards there too).

The morning is once per Anki day (`plans_day`): after the day's AnkiWeb
sync, or at the first refresh when this profile doesn't sync; the day's
fresh plans get one more look. It never suspends anything on its own: a
unit removed, a date moved later, a plan stopped all leave open cards
open; only a yes to Hold back holds what authors add to later dates. A
unit the author changes opens only the cards the change adds, and a leech
never opens. Its other steps (tidy, tags, hold, catch-up, checkpoints)
come before what it opens, so the open is Anki's latest step and Not
today can undo it. 3.8.1: a plan whose morning would open dates from 3
or more days on which I studied nothing keeps them back and asks first
(Welcome back: Open them, Push my dates back, Not today).


3.9.12 (the foundations, Stage B): a package by part, one namespace as before (board/'s way).
Each part is a module of its own; the package holds every name of every part, so plan_flow.X and
`from .plan_flow import X` read as they did, and setting a name on plan_flow (a test's stand-in)
sets it in each part that has it. The parts load in the order below; a part reads an earlier one's
names at its top and a later one's at its foot.
"""

import importlib as _importlib
import types as _types

_ORDER = ("state", "cards", "morning", "lessons", "joys", "commands", "days", "pace", "schedule", "follower",
          "following", "browser")
PARTS = ()
_NAMES = {}
for _name in _ORDER:
    _part = _importlib.import_module("." + _name, __name__)
    PARTS += (_part,)
    _own = {k: v for k, v in vars(_part).items() if not k.startswith("__") and k not in getattr(_part, "_LATER", ())}
    _NAMES.update(_own)
    for _earlier in PARTS[:-1]:  # what an earlier part was waiting on from this one
        for _k in getattr(_earlier, "_LATER", ()):
            if _k in _own:
                setattr(_earlier, _k, _own[_k])
_NAMES.pop("_LATER", None)
for _name in _ORDER:  # a part's own module isn't one of the names (plan_flow.cards was never a module)
    globals().pop(_name, None)
globals().update(_NAMES)
del _part, _name, _own, _NAMES


class _OneNamespace(_types.ModuleType):
    def __setattr__(self, name, value):
        for part in PARTS:
            if name in vars(part):
                setattr(part, name, value)
        super().__setattr__(name, value)


__import__("sys").modules[__name__].__class__ = _OneNamespace
