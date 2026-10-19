"""A course: its lectures, each lecture's rows (a resource whole, a part
kept to the cards that fit, cards found by the words), what's ticked, the
checks, and the course as Due Crew plan text. Pure: the index is the
deck's (find.DeckIndex), the course a dict kept as JSON.

A lecture: {id, date, kind, title, objectives: [{label, text}], terms,
terms_set, state, how: {terms, pick, read}, rows, opened, secs}. A row:
{kind: "tag"|"found", tag, res, name, use: whole|part|no|later, later,
objs, fit: {nid: [objective, [clozes]]}, unread: [nid], on, n_notes}."""

import datetime as dt
import re
import uuid

EVENT_KINDS = ("quiz", "exam")
PLAN_NAME_MAX = 60


def new_course(name="", did=0, deck=""):
    return {"v": 1, "name": name or "My course", "did": int(did or 0), "deck": deck, "lectures": [], "auto_open": False}


def new_lecture(date, title, kind="lecture", objectives=()):
    return {"id": uuid.uuid4().hex[:8], "date": str(date), "kind": kind, "title": str(title)[:120],
            "objectives": [dict(o) for o in objectives], "terms": [], "terms_set": False,
            "state": "new", "how": {}, "rows": [], "opened": [], "secs": 0}


def lectures(course):
    """By date, then title."""
    return sorted(course.get("lectures") or [], key=lambda l: (l.get("date") or "", l.get("title") or ""))


def studied(lec):
    return lec.get("kind") not in EVENT_KINDS and lec.get("kind") != "lab"


def key_of(o, i):
    """An objective's short name: its label, else "Objective i"."""
    return (o.get("label") or "").strip() or f"Objective {i}"


# ---- rows and what they hold ----

def row_nids(row, idx):
    """The notes a row brings: a whole tag's notes, or the ones that fit."""
    if row["use"] == "whole" and row.get("tag"):
        return set(idx.under(row["tag"]))
    return {int(n) for n, (fits, *_r) in (row.get("fit") or {}).items() if fits}


def row_cids(row, idx):
    """The cards a row brings (a cloze kept to the clozes that fit)."""
    if row["use"] == "whole" and row.get("tag"):
        return idx.cids_of(idx.under(row["tag"]))
    keep = {int(n): (v[2] if len(v) > 2 else []) for n, v in (row.get("fit") or {}).items() if v[0]}
    return idx.cids_of(list(keep), {n: cl for n, cl in keep.items() if cl})


def default_on(row):
    """Ticked where the model (or the rules) and the cards agree: whole, or a
    part or a search with a card that fits."""
    if row["use"] == "whole":
        return True
    if row["use"] in ("part",) or row["kind"] == "found":
        return any(v[0] for v in (row.get("fit") or {}).values())
    return False


def lecture_cids(lec, idx, only_on=True):
    out = []
    seen = set()
    for r in lec.get("rows") or []:
        if only_on and not r.get("on"):
            continue
        for c in row_cids(r, idx):
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


def earlier_cids(course, lec, idx):
    """The cards lectures before this one already bring (ticked)."""
    got = set()
    for other in lectures(course):
        if other["id"] == lec["id"]:
            break
        if (other.get("date") or "") <= (lec.get("date") or ""):
            got |= set(lecture_cids(other, idx))
    return got


# ---- the checks ----

def next_event(course, lec):
    """(title, days ahead) of the first quiz or exam after the lecture."""
    try:
        d0 = dt.date.fromisoformat(lec["date"])
    except (KeyError, ValueError):
        return None
    for o in lectures(course):
        if o.get("kind") in EVENT_KINDS and (o.get("date") or "") >= lec["date"] and o["id"] != lec["id"]:
            try:
                return o["title"], (dt.date.fromisoformat(o["date"]) - d0).days
            except ValueError:
                continue
    return None


def summary(course, lec, idx):
    """What ticking does: {new, open_already, leeches, repeat, total,
    covered: [(key, how)], missing: [key], event}. New is what opening would
    unsuspend: suspended, not a leech, not on an earlier lecture."""
    cids = lecture_cids(lec, idx)
    before = earlier_cids(course, lec, idx)
    new = open_ = leech = rep = 0
    for c in cids:
        if c in before:
            rep += 1
            continue
        _nid, _o, q, _t = idx.card.get(c, (0, 0, 0, 0))
        if q != -1:
            open_ += 1
        elif idx.is_leech(c):
            leech += 1
        else:
            new += 1
    objs = lec.get("objectives") or []
    by = {i: [] for i in range(1, len(objs) + 1)}
    for r in lec.get("rows") or []:
        if not r.get("on"):
            continue
        if r["use"] == "whole":
            for o in r.get("objs") or []:
                if o in by:
                    by[o].append(f"{r['name']}, whole")
        fits = [v[1] for v in (r.get("fit") or {}).values() if v[0]]
        for o in set(fits):
            if o in by:
                by[o].append(f"{fits.count(o)} card{'s' if fits.count(o) != 1 else ''} from {r['name']}")
    covered = [(key_of(objs[i - 1], i), "; ".join(v)) for i, v in by.items() if v]
    missing = [key_of(objs[i - 1], i) for i, v in by.items() if not v]
    return {"new": new, "open_already": open_, "leeches": leech, "repeat": rep, "total": len(cids),
            "covered": covered, "missing": missing, "event": next_event(course, lec)}


def why_line(lec, idx):
    """The plan text's # line, from the counts: "VideosA's Heart Failure, all
    118; Diuretics kept to SLG 5, 11 of 64; left …"."""
    took, left = [], []
    for r in lec.get("rows") or []:
        n_all = len(idx.under(r["tag"])) if r.get("tag") else r.get("n_notes", 0)
        if r.get("on") and r["use"] == "whole":
            took.append(f"{r['res'] + ' ' if r.get('res') else ''}{r['name']}, all {n_all}")
        elif r.get("on"):
            n = len(row_nids(r, idx))
            took.append(f"{r['name']}, {n} of {n_all}" if r.get("tag") else f"{n} cards found by the words")
        elif r["use"] == "later" and r.get("later"):
            left.append(f"{r['name']} ({r['later']})")
        elif r["use"] != "no" and not r.get("on"):
            left.append(r["name"])
    s = "; ".join(took) or "nothing ticked"
    return s + (f". Left {', '.join(left[:4])}." if left else ".")


# ---- the course as Due Crew plan text ----

def _plan_tag_name(o, i, lec):
    """A plan tag's name (40 at most): the objective's label, else the
    lecture's title and the objective's number."""
    lab = (o.get("label") or "").strip()
    return (lab or f"{lec['title'][:30]} {i}")[:40]


def plan_text(course, idx):
    """The course as lines the builder's Text › Add dates reads: a plan tag
    per objective with cards that fit (notes:, and cards: for a cloze kept
    to some clozes), a line a lecture (whole tags, parts as cuts kept to an
    objective's tag, found cards by their objective's tag), an event a quiz
    or exam, and a # line a lecture: what it took and why."""
    tag_lines, dates, notes_lines = [], [], []
    seen_tag_names = {}
    for lec in lectures(course):
        if lec.get("kind") in EVENT_KINDS:
            dates.append(f"{lec['date']} | event | {lec['title'][:PLAN_NAME_MAX]}")
            continue
        if lec.get("kind") == "lab":
            dates.append(f"{lec['date']} | event | {lec['title'][:PLAN_NAME_MAX]}")
            continue
        objs = lec.get("objectives") or []
        # each objective's fitting notes, over every row
        fit_by = {}
        for r in lec.get("rows") or []:
            if not r.get("on") or r["use"] == "whole":
                continue
            for n, v in (r.get("fit") or {}).items():
                if v[0]:
                    o = v[1] if 1 <= v[1] <= len(objs) else 0
                    fit_by.setdefault(o, {})[int(n)] = v[2] if len(v) > 2 else []
        names = {}
        for o, notes in sorted(fit_by.items()):
            name = _plan_tag_name(objs[o - 1], o, lec) if o else f"{lec['title'][:30]} other"
            name = re.sub(r"[|\n]", " ", name).strip()
            if name.lower() in seen_tag_names and seen_tag_names[name.lower()] != lec["id"]:
                name = f"{name} ({lec['date'][5:]})"[:40]
            seen_tag_names[name.lower()] = lec["id"]
            names[o] = name
            whole_notes = [idx.guid.get(n) for n, cl in notes.items() if not cl and idx.guid.get(n)]
            some = [(idx.guid.get(n), cl) for n, cl in notes.items() if cl and idx.guid.get(n)]
            for i in range(0, len(whole_notes), 5000):
                tag_lines.append(f"tag | {name} | notes:{' '.join(whole_notes[i:i + 5000])}")
            if some:
                tag_lines.append(f"tag | {name} | cards:{' '.join(f'{g}:{c}' for g, cls in some for c in cls)}")
        parts = []
        for r in lec.get("rows") or []:
            if not r.get("on"):
                continue
            if r["use"] == "whole" and r.get("tag"):
                parts.append(f"tag:{r['tag']}")
            elif r.get("tag"):
                os_ = sorted({v[1] if 1 <= v[1] <= len(objs) else 0 for v in (r.get("fit") or {}).values() if v[0]})
                parts += [f"tag:{r['tag']} in {names[o]}" for o in os_ if o in names]
        found_objs = sorted({v[1] if 1 <= v[1] <= len(objs) else 0 for r in lec.get("rows") or []
                             if r.get("on") and r["kind"] == "found" for v in (r.get("fit") or {}).values() if v[0]})
        parts += [f"tag:{names[o]}" for o in found_objs if o in names]
        parts = list(dict.fromkeys(parts))
        if not parts:
            notes_lines.append(f"# {lec['date']} {lec['title'][:PLAN_NAME_MAX]}: nothing ticked, so no date.")
            continue
        line = f"{lec['date']} | {re.sub(r'[|]', '-', lec['title'])[:PLAN_NAME_MAX]} | {', '.join(parts)}"
        ev = next_event(course, lec)
        if ev:
            line += f" | for {ev[0][:PLAN_NAME_MAX]}"
        dates.append(line)
        notes_lines.append(f"# {lec['date']}: {why_line(lec, idx)}")
    return "\n".join(tag_lines + dates + notes_lines) + "\n"


# ---- measuring against an answer key ----

def score(predicted, answer):
    """Note-level: of the key's notes, how many it found (recall); of the
    ones it chose, how many the key has (precision)."""
    p, a = set(predicted), set(answer)
    both = len(p & a)
    return {"key": len(a), "chose": len(p), "both": both,
            "found": both / len(a) if a else 0.0, "right": both / len(p) if p else 0.0}


def key_tag(root, label):
    """Due Crew's plan tag for a label: DueCrew::<root>::SLG_12 (plans.tag_part)."""
    s = re.sub(r"\s+", "_", str(label or ""))
    s = re.sub(r'["*\\%]', "", s).replace(":", "-")
    s = re.sub(r"_+", "_", s).strip("_-") or "tag"
    return f"{root.rstrip(':')}::{s}"
