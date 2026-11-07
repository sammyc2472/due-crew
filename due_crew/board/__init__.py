"""Deck-screen board HTML. Pure rendering: no network, no collection access.

Theme is decided in CSS, inside the webview, not in Python: both palettes
ship as CSS custom properties, and the dark set applies under Anki's night
body classes (with a prefers-color-scheme fallback). The Settings override
forces a single palette. This holds on every Anki version regardless of what
theme_manager reports.

All server-sourced strings are escaped before they touch the webview.
Entries carry days as {label: doc}; data["labels"] fixes the order and
data["tomorrow"] is my next label, so a friend whose day already rolled over
ahead of mine still renders as fresh.

3.9.8 (the tidy-ups): a package by feature, one namespace as before.
Each part is a module of its own (its imports say what it leans on, in
the order below, no cycles); the package holds every name of every part,
so board.X and `from .board import X` read as they did. Setting a name on
the board (a test's stand-in) sets it in each part that has it, as it did
when the board was one file.
"""

import types as _types

from . import (base, style, pip, crew, planweek, insights, plancards, party, due, page, windows, cheers,  # noqa: F401
               dance, fridge, squads, settings, closet, wrapped, lobby, draw)

PARTS = (base, style, pip, crew, planweek, insights, plancards, party, due, page, windows, cheers,
         dance, fridge, squads, settings, closet, wrapped, lobby, draw)
_NAMES = {}
for _part in PARTS:
    for _name, _value in vars(_part).items():
        if not _name.startswith("__"):
            _NAMES[_name] = _value
globals().update(_NAMES)
del _part, _name, _value, _NAMES


class _Board(_types.ModuleType):
    def __setattr__(self, name, value):
        for part in PARTS:
            if name in vars(part):
                setattr(part, name, value)
        super().__setattr__(name, value)


__import__("sys").modules[__name__].__class__ = _Board
