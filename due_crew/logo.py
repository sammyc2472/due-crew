"""The logo ("Seven days", docs/logo) in the user's accent (2.10).

logo.svg and logo_line.svg are docs/logo/svg/due-crew-logo.svg and
due-crew-logo-line.svg byte for byte; the suite checks them. The stacked
one tops the sign-in and welcome screens; the one-line one is the board's
title, drawn by the webview itself with the board's colour tokens. Only the fills change: the studied days take the accent, in the shade
the board uses for Anki's theme, and the day off takes the board's line
colour. The artwork is final (docs/logo/README.md): never redraw it here.
GitHub shows the green original, since nobody's accent is known there."""

import os
import re


# the fills as drawn in logo.svg (light, green)
DRAWN_ON, DRAWN_OFF, DRAWN_INK = "#2e7d32", "#e2e2da", "#242424"
WORDMARK = {"light": "#242424", "dark": "#e6e8e3"}
ASPECT = 137 / 401  # height over width, from the viewBox

_source = None
_line = None


def _read(name):
    with open(os.path.join(os.path.dirname(__file__), name), encoding="utf-8") as f:
        return f.read()


def svg(theme="light", accent="green"):
    """The stacked logo for the dialogs, as SVG text in this accent and theme."""
    from .board import ACCENTS, DARK, DEFAULT_ACCENT, LIGHT  # board imports this module
    global _source
    if _source is None:
        _source = _read("logo.svg")
    shade = "dark" if theme == "dark" else "light"
    on = ACCENTS.get(accent, ACCENTS[DEFAULT_ACCENT])[shade][0]
    off = (DARK if shade == "dark" else LIGHT)["line"]
    return (_source.replace(f'fill="{DRAWN_ON}"', f'fill="{on}"')
            .replace(f'fill="{DRAWN_OFF}"', f'fill="{off}"')
            .replace(f'fill="{DRAWN_INK}"', f'fill="{WORDMARK[shade]}"'))


def board_mark():
    """The one-line logo as inline SVG for the board's top left, where the
    words "Due Crew" were. Fills come from classes the board's CSS points at
    its tokens (--dc-accent, --dc-line, --dc-mark), so the accent, the theme
    and a live accent change all just work. Its size is set in CSS."""
    global _line
    if _line is None:
        s = _read("logo_line.svg")
        s = re.sub(r' width="\d+" height="\d+"', "", s, count=1)
        s = s.replace('role="img"', 'class="dc-mark" role="img" aria-label="Due Crew"', 1)
        s = (s.replace(f'fill="{DRAWN_ON}"', 'class="on"')
             .replace(f'fill="{DRAWN_OFF}"', 'class="off"')
             .replace(f'fill="{DRAWN_INK}"', 'class="wm"'))
        _line = s.strip()
    return _line
