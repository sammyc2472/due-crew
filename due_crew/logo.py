"""The logo ("Seven days", docs/logo) in the user's accent (2.10).

logo.svg is docs/logo/svg/due-crew-logo.svg byte for byte; the suite checks
it. Only the fills change: the studied days take the accent, in the shade
the board uses for Anki's theme, and the day off takes the board's line
colour. The artwork is final (docs/logo/README.md): never redraw it here.
GitHub shows the green original, since nobody's accent is known there."""

import os

from .board import ACCENTS, DARK, DEFAULT_ACCENT, LIGHT

# the fills as drawn in logo.svg (light, green)
DRAWN_ON, DRAWN_OFF, DRAWN_INK = "#2e7d32", "#e2e2da", "#242424"
WORDMARK = {"light": "#242424", "dark": "#e6e8e3"}
ASPECT = 137 / 401  # height over width, from the viewBox

_source = None


def svg(theme="light", accent=DEFAULT_ACCENT):
    global _source
    if _source is None:
        with open(os.path.join(os.path.dirname(__file__), "logo.svg"), encoding="utf-8") as f:
            _source = f.read()
    shade = "dark" if theme == "dark" else "light"
    on = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])[shade][0]
    off = (DARK if shade == "dark" else LIGHT)["line"]
    return (_source.replace(f'fill="{DRAWN_ON}"', f'fill="{on}"')
            .replace(f'fill="{DRAWN_OFF}"', f'fill="{off}"')
            .replace(f'fill="{DRAWN_INK}"', f'fill="{WORDMARK[shade]}"'))
