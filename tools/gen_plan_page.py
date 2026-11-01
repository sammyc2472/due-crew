"""Your plans on duecrew.com is the add-on's plan page: this copies
due_crew/planner/page/*.js and *.css (plan, tabs, new) into
site/public/planpage/, byte for byte, for the site's plan pages
(site/public/planface.js draws its view with them). Run it after the
page changes; the suite checks that running it changes nothing.

    python3 tools/gen_plan_page.py           # writes the copies
    python3 tools/gen_plan_page.py --check   # exit 1 if a copy is behind the page

Never edit a copy by hand: change the page in due_crew/planner/page/.
"""

import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "due_crew", "planner", "page")
OUT = os.path.join(REPO, "site", "public", "planpage")


def names():
    """The page's files: its scripts and styles, in name order."""
    return sorted(n for n in os.listdir(SRC) if n.endswith((".js", ".css")))


def read(path):
    with open(path, "rb") as f:
        return f.read()


def stale():
    """What isn't the page's yet: [(name, why)]."""
    out = []
    want = names()
    for n in want:
        dst = os.path.join(OUT, n)
        if not os.path.exists(dst):
            out.append((n, "missing"))
        elif read(dst) != read(os.path.join(SRC, n)):
            out.append((n, "behind"))
    if os.path.isdir(OUT):
        out += [(n, "not the page's") for n in sorted(os.listdir(OUT)) if n not in want]
    return out


def main(argv):
    if "--check" in argv:
        bad = stale()
        for n, why in bad:
            print(f"site/public/planpage/{n}: {why}")
        print("the site's plan page is the add-on's" if not bad else "run tools/gen_plan_page.py")
        return 1 if bad else 0
    os.makedirs(OUT, exist_ok=True)
    want = names()
    for n in want:
        data = read(os.path.join(SRC, n))
        dst = os.path.join(OUT, n)
        if not os.path.exists(dst) or read(dst) != data:
            with open(dst, "wb") as f:
                f.write(data)
    for n in os.listdir(OUT):
        if n not in want:
            os.remove(os.path.join(OUT, n))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
