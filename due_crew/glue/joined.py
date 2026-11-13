"""The glue: Anki's hooks, joined last, in the order they were."""

from aqt import gui_hooks

from .. import account
from .. import ahead_flow
from .. import app
from .. import cards as crew_cards
from .. import due_flow
from .. import plan_flow
from .. import rooms
from .. import together
from .. import two_buttons

from .settings import _apply_settings
from .profile import _mark_anki_synced, _on_profile_close, _on_profile_open
from .sync import _on_anki_sync, _on_sync_done
from .render import _on_did_render, _on_render, _rerender
from .commands import _on_js, _swap
from .refresh import refresh_board


gui_hooks.deck_browser_will_render_content.append(_on_render)


gui_hooks.deck_browser_did_render.append(_on_did_render)


# first: the upload that follows knows the phone's reviews are in
gui_hooks.sync_did_finish.append(_mark_anki_synced)


gui_hooks.sync_did_finish.append(_on_anki_sync)


gui_hooks.webview_did_receive_js_message.append(_on_js)


gui_hooks.profile_did_open.append(_on_profile_open)


gui_hooks.profile_will_close.append(_on_profile_close)


# 2.10: the flag on the reviewer's More menu. 3.2: a tip no longer goes
# under the answer; the chip beside Edit shows it, and who knows the card
# (nothing is drawn inside a card).
gui_hooks.reviewer_will_show_context_menu.append(together.reviewer_menu)
gui_hooks.reviewer_did_show_answer.append(crew_cards.on_answer)
gui_hooks.reviewer_did_show_question.append(crew_cards.on_question)


# 3.1: single cards onto a plan's date, from Anki's browser
gui_hooks.browser_will_show_context_menu.append(plan_flow.browser_menu)
if hasattr(gui_hooks, "browser_sidebar_will_show_context_menu"):  # 3.8.0: a tag's Due Crew: open its cards…
    gui_hooks.browser_sidebar_will_show_context_menu.append(plan_flow.sidebar_menu)
if hasattr(gui_hooks, "browser_did_fetch_row"):  # 3.9.5: Due says when a plan opens a suspended card
    gui_hooks.browser_did_fetch_row.append(plan_flow.browser_row)
if hasattr(gui_hooks, "browser_will_show"):
    gui_hooks.browser_will_show.append(lambda _browser: plan_flow.opens_reset())


# 2.12: study rooms. The room follows Anki from screen to screen; the break
# waits for the card on screen to be answered.
gui_hooks.reviewer_did_show_question.append(rooms.on_question)
gui_hooks.reviewer_did_show_answer.append(rooms.on_answer)
if hasattr(gui_hooks, "reviewer_will_answer_card"):
    gui_hooks.reviewer_will_answer_card.append(rooms.will_answer)  # none under a room's break
    gui_hooks.reviewer_will_answer_card.append(two_buttons.will_answer)  # 3.9.1: 2, 3 and 4 are Good
if hasattr(gui_hooks, "reviewer_will_init_answer_buttons"):
    gui_hooks.reviewer_will_init_answer_buttons.append(two_buttons.will_init_buttons)  # 3.9.1: Again and Good
gui_hooks.state_did_change.append(rooms.on_state)
gui_hooks.state_did_change.append(due_flow.on_state)  # 3.8.0: Study today's walk
gui_hooks.state_shortcuts_will_change.append(due_flow.walk_keys)  # and Escape stops it
if hasattr(gui_hooks, "top_toolbar_did_redraw"):  # Anki 2.1.54+
    gui_hooks.top_toolbar_did_redraw.append(rooms.on_toolbar)
# 3.9.1 (the efficiency run): a page sent once is sent again only on a new page
gui_hooks.webview_will_set_content.append(app.on_set_content)
gui_hooks.state_will_change.append(app.on_state_will_change)  # 3.9.1: the Decks page isn't up till it renders
gui_hooks.state_will_change.append(ahead_flow.on_state)  # 3.9.2's audit: Stop new is set before I study
if hasattr(gui_hooks, "theme_did_change"):
    gui_hooks.theme_did_change.append(rooms.on_theme)  # the widgets pick their colours as they're drawn

# the modules that need a redraw or a refresh reach it through app
app.swap = _swap
app.on_account_change = account.on_change
app.rerender = _rerender
app.refresh = refresh_board
app.sync = _on_sync_done
app.apply_settings = _apply_settings  # 3.9.7: Magic search's exam and away, as Settings saves them
