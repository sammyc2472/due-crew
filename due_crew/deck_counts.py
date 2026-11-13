"""3.9.12 (SC: "i want to change the deck list number"; the mock's A): Anki's deck list without the
siblings it will bury.

With "bury siblings" on, Anki's deck list counts every card of a note: 12 for six notes with two cards
each. Study one and its sibling is put away for the day, so six is what there is to do; Anki's own
count says so only once a deck is being studied. Tried on Anki's engine (25.02): the list said 12,
studying said 6, and with a limit of 5 both said 5. So the number to show is the smaller of Anki's
count and the notes due (cards, in a deck that doesn't bury), added up over a deck and the decks under it.

Pure: the rows the glue reads in one query, each deck's settings and Anki's own page in; the page with
its numbers out. It changes what's shown, never a card; behind Settings › Study › Deck counts, off by
default. Learning cards are left as Anki counts them. A new card whose review sibling is due today is
still counted (Anki decides that as it builds the day): the number can be a little over, never under.
"""
import re

SWITCH = "deck_counts"
QUERY = ("SELECT did, "
         "SUM(queue = 0), COUNT(DISTINCT CASE WHEN queue = 0 THEN nid END), "
         "SUM(queue = 2), COUNT(DISTINCT CASE WHEN queue = 2 THEN nid END) "
         "FROM cards WHERE queue = 0 OR (queue = 2 AND due <= ?) GROUP BY did")


def to_do(rows, bury, names):
    """{deck id: (new, review)}: what there is to do in each deck and the decks under it.
    rows: QUERY's (did, new cards, new notes, review cards, review notes); bury: {did: (new, review)}, whether
    that deck buries each kind; names: {did: its full name}."""
    own = {}
    for did, new_cards, new_notes, rev_cards, rev_notes in rows:
        b_new, b_rev = bury.get(did, (False, False))
        own[did] = (int((new_notes if b_new else new_cards) or 0), int((rev_notes if b_rev else rev_cards) or 0))
    out = {}
    for did, name in names.items():
        under = name + "::"
        new = rev = 0
        for other, (n, r) in own.items():
            other_name = names.get(other)
            if other == did or (other_name and other_name.startswith(under)):
                new += n
                rev += r
        out[did] = (new, rev)
    return out


_ROW = re.compile(r"(<tr class='[^']*' id='(\d+)'.*?</tr>)", re.S)
_COUNT = re.compile(r'<span class="(new-count|review-count)">(\d+)</span>')


def rewrite(tree, counts):
    """Anki's deck list (the page's rows, as aqt/deckbrowser.py writes them) with each deck's New and Due as
    the smaller of Anki's count and counts[did]; a number that changed says Anki's own on a hover. A row it
    doesn't know, or a page that isn't shaped as expected, is left exactly as it was."""
    def row(m):
        text, did = m.group(1), int(m.group(2))
        if did not in counts:
            return text
        new, rev = counts[did]

        def count(c):
            kind, shown = c.group(1), int(c.group(2))
            real = min(shown, new if kind == "new-count" else rev)
            if real >= shown:
                return c.group(0)
            less = shown - real
            title = f"Anki counts {shown}. {less} {'is a sibling' if less == 1 else 'are siblings'} it will bury as you go."
            return f'<span class="{kind if real else "zero-count"}" title="{title}">{real}</span>'
        return _COUNT.sub(count, text)
    try:
        return _ROW.sub(row, tree)
    except Exception:
        return tree
