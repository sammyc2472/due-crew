"""Shared dialog plumbing.

attach_alive() must be called once per dialog: it sets dialog._alive and
clears it on the `finished` signal, which Qt emits for every way a dialog
ends (accept, reject, Esc, window close) — unlike closeEvent, which
accept()/reject() skip.

run_bg() runs a job off the main thread and delivers (result, error_code)
back on the main thread, only while the owner is still alive. error_code is
an AuthError code, "NETWORK" for transport failures, or None.
"""

from aqt import mw

from ..backend.firebase import AuthError, TransportError


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
