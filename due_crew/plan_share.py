"""3.10.2, a plan's deck is shared with my crew (SC, 17 Nov 2026). Pure.

Who knows a card, friends' tips and Crew › Decks all read the decks I share,
and almost nobody had shared one: a plan on a deck didn't count. Now running a
plan on a deck shares that deck, as Share a deck would, with all my crew
(mutual friends, as ever): said in the Follow window and, once, at the board's
foot for a plan already running; turned off by unticking it in Crew › Decks.
Stopping the plan asks once whether to keep sharing it.

A plan's state says how its deck stands (`share`): nothing yet; ON, shared by
this; MINE, shared by me already (never asked about, never taken off); OFF,
taken off at a stop. Unticking the deck myself leaves ON behind, which only
means "don't add it again"."""

ON, MINE, OFF = "on", "mine", "off"


def due(states, shared, alive):
    """What a look at my plans changes: ([(pid, did)] to share, [(pid, MINE)] to mark). states: {pid: st};
    shared: the deck ids I share; alive(did): whether it's a deck here. A plan looked at once is never looked at
    again: unticking its deck in Crew › Decks is the way off, and stays off."""
    have = {int(d) for d in shared or [] if isinstance(d, int) or str(d).lstrip("-").isdigit()}
    add, mark = [], []
    for pid, st in (states or {}).items():
        if not isinstance(st, dict) or st.get("share") is not None:
            continue
        try:
            did = int(st.get("deck_id") or 0)
        except (TypeError, ValueError):
            continue
        if not did or not alive(did):
            continue
        if did in have:
            mark.append((pid, MINE))
        else:
            add.append((pid, did))
            have.add(did)
    return add, mark


def asks(st, shared):
    """Whether stopping this plan asks to keep sharing its deck: this shared it, and it's still shared."""
    try:
        did = int((st or {}).get("deck_id") or 0)
    except (TypeError, ValueError):
        return False
    return bool(did) and (st or {}).get("share") == ON and did in {int(d) for d in shared or [] if str(d).lstrip("-").isdigit()}


def without(shared, did):
    return [d for d in shared or [] if str(d) != str(did)]
