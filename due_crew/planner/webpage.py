"""The HTML plan window's page (web.py, webface.py): its style, its
script, the first view in it, and the board's tokens it wears. Qt-free,
so a preview (tools/plan_preview.py) builds the same page."""

import json
import os

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "page")
PREFIX = "dcplan:"


def page_html(state, colors_css, night=False, preview=False):
    """The page: its style, its script, and the first view in it."""
    def read(name):
        with open(os.path.join(PAGE, name), encoding="utf-8") as f:
            return f.read()
    first = json.dumps(state, ensure_ascii=True).replace("</", "<\\/")
    tabs = read("tabs.js") if os.path.exists(os.path.join(PAGE, "tabs.js")) else ""
    css = read("tabs.css") if os.path.exists(os.path.join(PAGE, "tabs.css")) else ""
    return (f"<style>{colors_css}\n{read('plan.css')}\n{css}</style>"
            f"<div id=\"dcp\" class=\"dcp{' night' if night else ''}\"></div>"
            f"<script>{read('plan.js')}\n{tabs}</script>"
            f"<script>dcPlan.start({first}, {json.dumps(bool(preview))});</script>")


def colors(cfg):
    """The board's tokens (--dc-*), as Settings › Theme and the accent say."""
    from .. import board
    accent = cfg.get("accent", board.DEFAULT_ACCENT)
    return board._by_theme(cfg, ".dcp", board._token_block(board.palette("light", accent)),
                           board._token_block(board.palette("dark", accent)))
