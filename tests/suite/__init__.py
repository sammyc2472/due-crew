"""The suite (3.9.12, Stage C): what was tests/test_due_crew.py, a package of parts in the order the tests
were written, one namespace as before. tests/test_due_crew.py runs it."""

import importlib as _importlib
import types as _types

_ORDER = ("base", "board", "plans", "v380", "v381", "v382", "v392", "v399")
PARTS = ()
_NAMES = {}
for _name in _ORDER:
    _part = _importlib.import_module("." + _name, __name__)
    PARTS += (_part,)
    _own = {k: v for k, v in vars(_part).items() if not k.startswith("__") and k not in getattr(_part, "_LATER", ())}
    _NAMES.update(_own)
    for _earlier in PARTS[:-1]:  # what an earlier part was waiting on from this one
        for _k in getattr(_earlier, "_LATER", ()):
            if _k in _own:
                setattr(_earlier, _k, _own[_k])
_NAMES.pop("_LATER", None)
for _name in _ORDER:  # a part's own module isn't one of the names (plan_flow.cards was never a module)
    globals().pop(_name, None)
globals().update(_NAMES)
del _part, _name, _own, _NAMES


class _OneNamespace(_types.ModuleType):
    def __setattr__(self, name, value):
        for part in PARTS:
            if name in vars(part):
                setattr(part, name, value)
        super().__setattr__(name, value)


__import__("sys").modules[__name__].__class__ = _OneNamespace
