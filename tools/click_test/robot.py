"""The robot's driver: a scenario is a generator that yields what it waits
for, and this runs it on Qt timers, so Anki's event loop (and any modal
window's own loop) keeps running between steps. Nothing here sleeps: a
wait polls its condition and gives up at its timeout.

    def scenario(r):
        yield r.until(lambda: mw.state == "deckBrowser", 20, "the Decks screen")
        n = yield r.js(mw.web, "document.querySelectorAll('button').length")
        yield r.do(lambda: something_that_may_open_a_modal())

A wait that times out raises Timeout inside the scenario, where the step
that asked can catch it and record a failure."""

import time
import traceback

POLL_MS = 20


class Timeout(Exception):
    pass


class _Until:
    def __init__(self, pred, secs, what):
        self.pred, self.secs, self.what = pred, secs, what


class _Js:
    def __init__(self, web, code, secs, unless):
        self.web, self.code, self.secs, self.unless = web, code, secs, unless


BLOCKED = object()  # what a script's yield returns when `unless` came first


class _Do:
    def __init__(self, fn):
        self.fn = fn


class _Pause:
    def __init__(self, ms):
        self.ms = ms


class Robot:
    def __init__(self, timer_factory, on_done, on_crash):
        """timer_factory(ms, fn): a single-shot Qt timer. on_done(): the
        scenario finished. on_crash(text): the robot itself broke."""
        self._later = timer_factory
        self._done = on_done
        self._crash = on_crash
        self.gen = None
        self.t0 = time.perf_counter()

    # what a scenario yields
    def until(self, pred, secs=10.0, what="a condition"):
        """Wait until pred() is truthy; its value is what the yield returns."""
        return _Until(pred, secs, what)

    def js(self, web, code, secs=10.0, unless=None):
        """Run code in a web view's page; the yield returns its value. unless():
        a condition that ends the wait first (the yield returns BLOCKED): a
        modal window that a click in the page opened holds the page's answer
        back until it closes."""
        return _Js(web, code, secs, unless)

    def do(self, fn):
        """Run fn on its own timer, so a modal window it opens doesn't stop
        the robot: the scenario goes on while fn's window waits."""
        return _Do(fn)

    def pause(self, ms):
        """Only where there's no condition to wait for (a measured span)."""
        return _Pause(ms)

    # the loop
    def run(self, gen):
        self.gen = gen
        self._later(0, lambda: self._step(None))

    def _step(self, value, exc=None):
        try:
            req = self.gen.throw(exc) if exc is not None else self.gen.send(value)
        except StopIteration:
            self._done()
            return
        except Exception:
            self._crash(traceback.format_exc())
            return
        if isinstance(req, _Until):
            self._poll(req, time.perf_counter() + req.secs)
        elif isinstance(req, _Js):
            self._eval(req)
        elif isinstance(req, _Do):
            self._later(0, req.fn)
            self._later(0, lambda: self._step(None))
        elif isinstance(req, _Pause):
            self._later(req.ms, lambda: self._step(None))
        else:
            self._later(0, lambda: self._step(None, TypeError(f"the scenario yielded {req!r}")))

    def _poll(self, req, end):
        try:
            got = req.pred()
        except Exception as e:
            err = e
            self._later(0, lambda: self._step(None, err))
            return
        if got:
            self._later(0, lambda: self._step(got))
        elif time.perf_counter() > end:
            self._later(0, lambda: self._step(None, Timeout(f"waited {req.secs:g} s for {req.what}")))
        else:
            self._later(POLL_MS, lambda: self._poll(req, end))

    def _eval(self, req):
        box = {"done": False}

        def got(value):
            if not box["done"]:
                box["done"] = True
                self._later(0, lambda: self._step(value))

        def late():
            if not box["done"]:
                box["done"] = True
                self._step(None, Timeout(f"a script got no answer in {req.secs:g} s: {req.code[:80]}"))

        def blocked():
            if box["done"]:
                return
            try:
                hit = req.unless()
            except Exception:
                hit = False
            if hit:
                box["done"] = True
                self._step(BLOCKED)
            else:
                self._later(POLL_MS, blocked)
        try:
            req.web.evalWithCallback(req.code, got)
        except Exception as e:
            box["done"] = True
            err = e
            self._later(0, lambda: self._step(None, err))
            return
        self._later(int(req.secs * 1000), late)
        if req.unless is not None:
            self._later(POLL_MS, blocked)
