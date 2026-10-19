"""Labs: the plan window, Python-native (docs/planner.md). Kept apart from
the rest of the add-on while it's built: nothing here runs unless this
computer's config says "labs": true (a key no window sets; docs/planner.md
says how), and the plan window opens only for the admin's account (the
server says which, remote.is_admin). Question IDs touch nothing but this
collection, so labs alone opens them.

model.py, qids.py and edits.py are pure; actions.py is the one collection
step it adds; remote.py its requests (routes the builder uses already);
flow.py the glue; window.py, picker.py and qid_window.py the Qt windows.
"""


def enabled(c=None):
    """This computer's labs switch: the config's "labs", true and nothing else."""
    if c is None:
        from ..app import cfg
        c = cfg()
    return c.get("labs") is True


_hooked = []  # the profile's close, hooked once: the windows close with it


def install(menu):
    """Tools › Due Crew's labs entries, once, when labs is on (at profile
    open; turning it on takes a restart)."""
    if not enabled() or getattr(menu, "_dc_labs", False):
        return False
    from aqt.qt import QAction
    from . import flow
    if not _hooked:
        try:
            from aqt import gui_hooks
            gui_hooks.profile_will_close.append(flow.close_all)
            _hooked.append(True)
        except (ImportError, AttributeError):
            pass
    menu._dc_labs = True
    menu.addSeparator()
    for label, fn in (("Plan window (labs)…", flow.open_plans), ("Question IDs (labs)…", flow.open_qids)):
        action = QAction(label, menu)
        action.triggered.connect(lambda _=False, fn=fn: fn())
        menu.addAction(action)
    return True
