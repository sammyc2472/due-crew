"""Shared dialog plumbing.

attach_alive() must be called once per dialog: it sets dialog._alive and
clears it on the `finished` signal, which Qt emits for every way a dialog
ends (accept, reject, Esc, window close) — unlike closeEvent, which
accept()/reject() skip.

run_bg() runs a job off the main thread and delivers (result, error_code)
back on the main thread, only while the owner is still alive. error_code is
an AuthError code, "NETWORK" for transport failures, or None.
"""

import subprocess
import sys

from aqt import mw
from aqt.qt import QApplication

from ..backend.firebase import AuthError, TransportError


def copy_text(text):
    """Put text on the system clipboard, emoji and all.

    Qt's macOS pasteboard also offers a legacy "traditional Mac plain text"
    flavor, converted through Latin-1 with '?' for anything it can't encode
    — and some apps paste that one, turning every emoji and block glyph
    into '?' (and '·' into '∑'). pbcopy under a UTF-8 locale writes only
    the UTF-8 flavor, so it goes first on macOS; Qt with explicit UTF-8
    mime data is the fallback everywhere else."""
    text = str(text)
    if sys.platform == "darwin":
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True,
                           timeout=5, env={"LC_ALL": "en_US.UTF-8",
                                           "LANG": "en_US.UTF-8",
                                           "PATH": "/usr/bin:/bin"})
            return True
        except Exception:
            pass  # fall through to Qt
    clip = QApplication.clipboard()
    try:
        from aqt.qt import QMimeData
        mime = QMimeData()
        mime.setText(text)
        mime.setData("text/plain;charset=utf-8", text.encode("utf-8"))
        clip.setMimeData(mime)
    except Exception:
        clip.setText(text)
    return True


def _night():
    try:
        from aqt.theme import theme_manager
        return bool(theme_manager.night_mode)
    except Exception:
        return False


def accent():
    """Board green, readable on both of Anki's themes. Dialogs rebuild on
    every open, so a theme change is picked up next time."""
    return "#7cc47f" if _night() else "#2e7d32"


def danger():
    return "#ef8383" if _night() else "#d32f2f"


def attach_alive(dialog):
    dialog._alive = True
    dialog.finished.connect(lambda _=0: setattr(dialog, "_alive", False))


def run_bg(owner, job, done):
    def worker():
        try:
            result, err = job(), None
        except AuthError as e:
            result, err = None, e.code
        except TransportError:
            result, err = None, "NETWORK"
        except Exception:
            result, err = None, "NETWORK"
        mw.taskman.run_on_main(
            lambda: getattr(owner, "_alive", False) and done(result, err))
    mw.taskman.run_in_background(worker)
