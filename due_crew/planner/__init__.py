"""The plan windows (docs/planner.md): Your plans (a plan's weeks and dates,
written here by its authors), New plan from a calendar and Missed
questions, Python-native, for everyone since 3.9.3. Tools › Due Crew ›
Plans opens them, and the board: You › Plans' head row and each plan
card's Open, Insights' Missed questions line, Find a setting.

Labs is what stays behind this computer's "labs" switch (a key no window
sets; docs/planner.md says how): Claude's stand-in in New plan from a
calendar, and What Claude would get (claude.py: nothing is sent).

model.py, qids.py, edits.py and reading.py are pure; actions.py is the one
collection step it adds; remote.py its requests (routes the builder uses
already); flow.py the glue; window.py, picker.py, qid_window.py and
start_window.py the Qt windows; build.py the builder's rules, layout_tab.py
Lay it out, text.py and text_tab.py its Text, history_tab.py its Updates
and History, settings_tab.py its Progress and Settings, date_dialogs.py
the Dates tab's dialogs.
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
    for item in (("Your plans…", flow.open_plans), ("New plan from a calendar…", flow.open_start),
                 ("New plan from a deck…", plan_flow.open_make), ("Follow a plan…", plan_flow.open_follow), None,
                 ("Missed questions…", flow.open_qids), ("Export cards for my AI…", plan_flow.open_export)):
        if item is None:
            menu.addSeparator()
            continue
        label, fn = item
        menu.addAction(label).triggered.connect(lambda _=False, fn=fn: fn())
    return menu
