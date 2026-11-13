"""End-to-end tests for Due Crew against fake anki and a fake of the 3.0
Worker API (tests/fakes.py). worker/test proves the Worker itself.

Run: python3 tests/test_due_crew.py

3.9.12 (the foundations, Stage C): the tests themselves are tests/suite/, a package of parts in the
order they were written (base, board, plans, v380, v381, v382, v392, v399), one namespace as when
they were one file of 22,000 lines. This file runs them.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import suite  # noqa: E402

CHECKS, QUIET = suite.CHECKS, suite.QUIET


def tests():
    """Every test, in the order they're written: (name, function)."""
    return [(n, f) for part in suite.PARTS for n, f in vars(part).items()
            if n.startswith("test_") and callable(f) and getattr(f, "__module__", "") == part.__name__]


def main():
    """python3 tests/test_due_crew.py                 everything (what CI runs)
    python3 tests/test_due_crew.py hook magic      only the tests with one of these words in their name
    python3 tests/test_due_crew.py -q              only what failed is said
    python3 tests/test_due_crew.py --list          the tests' names
    A run by area leaves out the last check (every board click), which needs them all."""
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    QUIET[0] = "-q" in sys.argv[1:]
    every = tests()
    if "--list" in sys.argv[1:]:
        print("\n".join(n for n, _f in every))
        return
    picked = [(n, f) for n, f in every if not args or any(a.lower() in n.lower() for a in args)]
    for _n, f in picked:
        f()
    if not args:
        suite.check_every_board_click_is_taken()  # last: every control the suite drew on the board, pressed down its route
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed" + (f" ({len(picked)} of {len(every)} tests)" if args else ""))
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
