"""3.9.0: how a cheer lands (Sam's picks, "Cheers, everywhere"): a show over
the whole Decks screen, a different one each time. Pure: no aqt.

The bag: every show plays once before any plays again, and never the same
one twice in a row, even across two bags. It's kept on this computer (the
config's `cheer_bag`), as the board's look is: nothing here is sent.
show.js draws them; board.flurry_js starts one when cheers land.
"""

import random

# the twelve Sam kept, in the mock's order
SHOWS = ("cannon", "pinata", "fireworks", "gift", "bubbles", "wave",
         "balloons", "rocket", "stamp", "disco", "hat", "snow")
BAG_KEY = "cheer_bag"  # [the shows left in this bag, ..., the last one played]


def next_show(bag, rng=random):
    """(the show to play, the bag after it). bag: what the config keeps,
    the ones left to play then the last one played; anything else in it
    (an older add-on's show, a typo) is dropped. A new bag is the twelve
    shuffled, never starting with the one just played."""
    kept = [k for k in (bag or []) if k in SHOWS]
    last = kept[-1] if kept else None
    left = list(dict.fromkeys(kept[:-1]))
    if not left:
        left = list(SHOWS)
        rng.shuffle(left)
        if left[0] == last and len(left) > 1:
            left.append(left.pop(0))
    show = left.pop(0)
    return show, left + [show]
