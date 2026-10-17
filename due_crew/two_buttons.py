"""3.9.1, two buttons (Sam's picks from the mock "Two Buttons"): review with
Again and Good alone. Hard and Easy hide on the review screen, and the keys
2, 3 and 4 all count as Good (1 is Again; Space and Enter are Good already).
Every deck, FSRS on or off. It's a person's way of reviewing, so it's an
account key (account.ACCOUNT_KEYS) and follows them to another computer;
phones keep their four buttons (they don't run desktop add-ons).

Two of Anki's own hooks, nothing else: which buttons the bar draws
(reviewer_will_init_answer_buttons) and which ease an answer lands as
(reviewer_will_answer_card, a filter every answer passes through, keys and
clicks alike; a room's break shares it, and its no still holds). Nothing
is sent; past answers and Undo are untouched."""

KEY = "two_buttons"
AGAIN, GOOD = 1, 3


def buttons(shown, on):
    """The bar's buttons, ((ease, label), ...): with two buttons on, Again
    and Good from what Anki would draw (its own words, in its language); a
    list that isn't Anki's four (another add-on's, or none) as it came."""
    shown = tuple(shown or ())
    if not on or len(shown) != 4:
        return shown
    kept = tuple(b for b in shown if b and b[0] in (AGAIN, GOOD))
    return kept if len(kept) == 2 else shown


def ease(answer, on):
    """(proceed, ease) as reviewer_will_answer_card passes it: with two
    buttons on, 2, 3 and 4 are Good. A no from an earlier filter (a room's
    break) stays a no."""
    proceed, e = answer
    if on and e in (2, 4):
        return (proceed, GOOD)
    return (proceed, e)


def on(cfg):
    return bool((cfg or {}).get(KEY))


# ---- the hooks (glue: the config is read at the moment Anki asks) ----

def will_init_buttons(shown, reviewer, card):
    from .app import cfg
    try:
        return buttons(shown, on(cfg()))
    except Exception:
        return shown


def will_answer(answer, reviewer, card):
    from .app import cfg
    try:
        return ease(answer, on(cfg()))
    except Exception:
        return answer
