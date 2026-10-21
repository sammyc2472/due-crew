"""The plan windows (docs/planner.md): Your plans (a plan's weeks and
dates with the deck beside them, written here by its authors), New plan
and QBank QIDs, Python-native, for everyone since 3.9.3. Tools ›
Due Crew › Plans opens them, and the board: You › Plans' head row and
each plan card's Open, Today's head and Insights' line (QBank QIDs),
Find a setting.

Labs is what stays behind this computer's "labs" switch (a key no window
sets; docs/planner.md says how): Claude's stand-in, session by session
(start_window.py), and What Claude would get (claude.py: nothing is sent).

Round five: every change is an op (ops.py, pure), waiting under the plan
till it's sent when anyone follows it (draft.py, pure); view.py works out
what the Plan tab shows; prompts.py is builder.js's Prompts; ai.py the AI
hooks, mcp.py a local server an AI app on this computer may use (off by
default), mcp_host.py and mcp_dialog.py its glue. model.py, qids.py,
edits.py and reading.py are pure; actions.py is the one collection step
it adds; remote.py its requests (routes the builder uses already); flow.py
the glue; window.py (Plan · Sharing for authors, Plan · Mine for a
follower), plan_tab.py, date_panel.py, deck_panel.py, shape.py,
send.py, settings_tab.py (Sharing), mine_tab.py,
new_plan.py, text_tab.py, history_tab.py, day_notes.py, date_dialogs.py,
picker.py, qid_window.py and start_window.py the Qt windows; widgets.py
their small parts; build.py the builder's rules, text.py its Text.
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
                 ("QBank QIDs…", flow.open_qids), ("Export cards for my AI…", plan_flow.open_export)):
        if item is None:
            menu.addSeparator()
            continue
        label, fn = item
        menu.addAction(label).triggered.connect(lambda _=False, fn=fn: fn())
    return menu
