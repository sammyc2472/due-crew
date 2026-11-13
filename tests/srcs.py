"""The add-on's source as text, for the checks that read it. A module that became a package
(plan_flow, 3.9.12) reads as it did when it was one file: its parts in the order they load."""
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def due_src(name):
    """due_crew/<name> as text; "plan_flow.py" (a package now) is its parts, one after another."""
    if name == "__init__.py":
        return glue_src()
    path = os.path.join(REPO, "due_crew", *name.split("/"))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return _package(path[:-3])


def _package(pkg):
    with open(os.path.join(pkg, "__init__.py"), encoding="utf-8") as f:
        init = f.read()
    parts = re.search(r"^_ORDER = \(([^)]*)\)", init, re.M).group(1)
    out = [init]
    for part in re.findall(r'"(\w+)"', parts):
        with open(os.path.join(pkg, part + ".py"), encoding="utf-8") as f:
            out.append(f.read())
    return "\n".join(out)


def flow_src():
    return due_src("plan_flow.py")


def glue_src():
    """The add-on's glue: due_crew/__init__.py and, since 3.9.12, glue/'s parts after it."""
    with open(os.path.join(REPO, "due_crew", "__init__.py"), encoding="utf-8") as f:
        return f.read() + "\n" + _package(os.path.join(REPO, "due_crew", "glue"))
