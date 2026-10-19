"""Course on a Mac (PoC): a block's calendar in, each lecture's cards found
in your deck by the Mac's own model (or plain rules), ticked, and opened as
you watch. A proof of concept beside Due Crew, not part of it: it never
talks to Due Crew's server, and Due Crew never reads it. Its one bridge is
Copy as plan text, for the builder's Text › Add dates."""

try:
    from aqt import mw as _mw
except ImportError:  # the tests import the pure parts without Anki's window
    _mw = None

if _mw is not None:
    from . import glue
    __all__ = ["glue"]
