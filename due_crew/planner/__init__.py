"""The plan windows (docs/planner.md): Your plans (a plan's weeks and
dates with the deck beside them, written here by its authors), New plan
Python-native, for everyone since 3.9.3 (QBank QIDs was one too, till
Magic search took it in 3.9.7). Tools › Due Crew › Plans opens them, and
the board: You › Plans' head row and each plan card's Open, Find a
setting.

Labs was what stayed behind this computer's "labs" switch: the calendar
window, session by session. It went in 3.9.9 (start_window.py, picker.py;
Sam: "don't think it works well enough"); the key opens nothing now.

Round five: every change is an op (ops.py, pure), waiting under the plan
till it's sent when anyone follows it (draft.py, pure); view.py works out
what the Plan tab shows; prompts.py is builder.js's Prompts; ai.py the AI
hooks, mcp.py a local server an AI app on this computer may use (off by
default), mcp_host.py and mcp_dialog.py its glue. model.py, qids.py,
edits.py and reading.py are pure; actions.py is the one collection step
it adds; remote.py its requests (routes the builder uses already); flow.py
the glue; web.py the plan window (a page: webface.py, webmodel.py,
webtabs.py, webnew.py, page/; the Qt one went in 3.9.9); text_tab.py,
and date_dialogs.py the Qt windows left;
widgets.py a window's first size; build.py the builder's rules, text.py
its Text.
"""


def enabled(c=None):
    """This computer's labs switch: the config's "labs", true and nothing else."""
    if c is None:
        from ..app import cfg
        c = cfg()
    return c.get("labs") is True


_hooked = []  # the profile's close, hooked once: the windows close with it


def plans_menu(parent):
    """Tools › Due Crew › Plans (3.9.3): everything about plans in one place,
    the three windows among them."""
    from aqt.qt import QMenu
    from .. import plan_flow
    from . import flow
    if not _hooked:
        try:
            from aqt import gui_hooks
            gui_hooks.profile_will_close.append(flow.close_all)
            _hooked.append(True)
        except (ImportError, AttributeError):
            pass
    menu = QMenu("Plans", parent)
    for item in (("Your plans…", flow.open_plans), ("New plan…", flow.open_new),
                 ("Follow a plan…", plan_flow.open_follow), None,
                 ("Export cards for my AI…", plan_flow.open_export)):
        if item is None:
            menu.addSeparator()
            continue
        label, fn = item
        menu.addAction(label).triggered.connect(lambda _=False, fn=fn: fn())
    return menu
