"""Magic search's page (3.9.7; ui/magic_window.py the shell): its style,
its script and the first view in it, in the board's tokens. Qt-free, so a
preview builds the same page."""

import json
import os

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "magicpage")


def colors(cfg):
    """The board's tokens (--dc-*) on the page, as Settings › Theme and the accent say."""
    from . import board
    accent = cfg.get("accent", board.DEFAULT_ACCENT)
    light, dark = board.palette("light", accent), board.palette("dark", accent)
    css = board._by_theme(cfg, ".dcm", board._token_block(light), board._token_block(dark))
    # 3.9.9 (Sam: "the bottom of it shows white in dark mode"): the tokens live on .dcm, so the page under
    # it had none and fell back to white wherever the window stood taller than its content
    lb, db = f"background: {light['bg']};", f"background: {dark['bg']};"
    theme = cfg.get("theme", "auto")
    if theme in ("light", "dark"):
        return css + f"\nbody {{ {lb if theme == 'light' else db} }}"
    night = ", ".join(n if n.startswith("body") else f"{n}, {n} body" for n in board.NIGHT_SELECTORS)
    return (css + f"\nbody {{ {lb} }}\n@media (prefers-color-scheme: dark) {{ body {{ {db} }} }}\n"
            f"{night} {{ {db} }}")


def page_html(view, cfg, preview=False):
    def read(name):
        with open(os.path.join(PAGE, name), encoding="utf-8") as f:
            return f.read()
    first = json.dumps(view, ensure_ascii=True).replace("<", "\\u003c")  # nothing in it reads as markup
    return (f"<style>{colors(cfg)}\n{read('magic.css')}</style>"
            f"<div id=\"dcm\" class=\"dcm\"></div>"
            f"<script>{read('magic.js')}</script>"
            f"<script>dcMagic.start({first}, {json.dumps(bool(preview))});</script>")
