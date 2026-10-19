"""The builder's Text (site/public/builder.js: toText, fromText, and its
Text tab's preview, Add to the plan and Replace the plan's dates),
restated for Your plans' Text tab (3.9.3): pure, nothing of Anki's. A
twin of the builder's: change one, change both (CLAUDE.md's twins).

The plan as text, a line a date ("2026-10-05 | Heart failure |
tag:…, deck:… | due 2026-10-09 | even | for Heme quiz"), an event, one of
the plan's own tags ("tag | SLG 12 | notes:…"), a note for followers
("note | tag:… | words"). Add dates puts lines on (a line with a date's
own day and name adds to it); Edit the whole plan says what the plan is,
and what it leaves out goes. Names, tags, ids and the authors' words:
never a card's text."""

import copy
import json
import re

from .. import plans as P
from . import build as B
from . import edits as E

CARDS_TEXT = 500                     # builder.js CARDS_TEXT: past this, single cards are a count
UNITS_MAX, EVENTS_MAX, SOURCES_MAX, SEARCH_MAX = 200, 200, 50, 10
TAGS_MAX = 100
IDS_MAX = 5000
PERSONAL = re.compile(r"(?:^|[\s(\"-])(?:deck:current|is:(?:due|new|learn|review|suspended|buried|susp)|rated:|prop:|"
                      r"introduced:|added:|edited:|resched:|flag:|nid:|cid:)", re.I)
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_SPLIT = re.compile(r"\s*\|\s*|\s{2,}")
_SRC_SPLIT = re.compile(r"\s*[,;]\s*(?=(?:tag|deck):)", re.I)
_SAFE = 2 ** 53 - 1


def _name(path):
    """Tags.name: a path as it reads, "Cardio › Heart Failure"."""
    return " › ".join(P._word(x) for x in str(path).split("::"))


def _leaf(p):
    """leaf (app.js): a path's last part, _ as spaces."""
    return str(p).split("::")[-1].replace("_", " ") if p else ""


def root_of(doc, plan_name=""):
    """tagRootNow: the plan's own part of its tags."""
    return doc.get("tagroot") or P.tag_root(plan_name)


def ptag_path(doc, t, plan_name=""):
    return f"DueCrew::{root_of(doc, plan_name)}::{P.tag_part(t.get('name'))}"


def ptag_by_name(doc, name):
    want = P.tag_part(name).lower()
    return next((t for t in P.plan_tags(doc) if P.tag_part(t.get("name")).lower() == want), None)


def ptag_from(t):
    return ([f"tag:{x}" for x in t.get("tags") or []] + [f"deck:{x}" for x in t.get("decks") or []]
            + [f"search:{x}" for x in t.get("search") or []])


def has_ids(u):
    return bool(len(u.get("nids") or []) + len(u.get("cids") or []) + len(u.get("notes") or []))


def _picks_sig(x):
    return json.dumps([x.get("cards") or [], x.get("notes") or [], x.get("nids") or [], x.get("cids") or []])


def _events(doc):
    return [e for e in doc.get("events") or [] if isinstance(e, dict)]


def _remarks(doc):
    return [r for r in doc.get("remarks") or [] if isinstance(r, dict)]


def _cut_of(u, q):
    return next((c for c in u.get("cut") or [] if c.get("q") == q), None)


# ---- the plan as text (toText) ----

def tag_line(t):
    """tagLine: tag | SLG 12 | tag:…, deck:… | search:… | notes:… | cards:…"""
    first = ", ".join([f"tag:{x}" for x in t.get("tags") or []] + [f"deck:{x}" for x in t.get("decks") or []])
    parts = ["tag", t.get("name") or "", first, *[f"search:{x}" for x in t.get("search") or []],
             B.notes_text(t["notes"]) if t.get("notes") else "", B.cards_text(t["cards"]) if t.get("cards") else ""]
    return " | ".join(p for p in parts if p)


def pick_note(n):
    """A "# Pick in Anki for 2026-10-06: the iron cards" line as Read it
    shows it after "To pick in Anki:": its date and what, the words once
    (builder.js's pickNote)."""
    return re.sub(r"^:\s*", "", re.sub(r"^\s*pick in anki\b\s*(?:for\s+)?", "", str(n), flags=re.I)) or str(n)


def to_text(doc):
    """toText: the plan's tags, then its dates and events by day, then its notes for followers."""
    evs = [f"{e.get('day')} | event | {e.get('name')}" for e in _events(doc)]
    dates = [P._date_line(u, doc) for u in sorted(P.units(doc), key=lambda u: str(u.get("opens") or ""))]
    return "\n".join([tag_line(t) for t in P.plan_tags(doc)] + sorted(evs + dates) + [B.remark_line(r) for r in _remarks(doc)])


# ---- reading it (fromText) ----

class _Keys:
    """findKey: what a line might write for a tag, the exact path, any case, or its readable name."""

    def __init__(self, tree):
        self.tree = tree
        keys = list(tree.order) if tree is not None else []
        self.lower = {k.lower(): k for k in keys}
        self.byname = {f"{B.kind_of(k)}:{_name(B.path_of(k)).lower()}": k for k in keys}

    def find(self, kind, p):
        return self.lower.get(f"{kind}:{p.lower()}") or self.byname.get(f"{kind}:{p.lower()}") or f"{kind}:{p}"

    def has(self, k):
        return self.tree is not None and self.tree.has(k)

    def size(self):
        return len(self.tree.order) if self.tree is not None else 0


def _extras(tree):
    """extrasOf, worked out once a tree: each without-its-extras search, its tag."""
    got = getattr(tree, "_extras_map", None)
    if got is None:
        got = {}
        for key in tree.order:
            if B.kind_of(key) == "tag" and tree.extra_kids(key):
                got[B.without_q(B.path_of(key), [B.path_of(k) for k in tree.extra_kids(key)])] = B.path_of(key)
        tree._extras_map = got
    return got


def auto_name(doc, tree, u, placed):
    """autoName: a date named for what's on it (its first tag, + N more)."""
    ks = B.srcs(u)
    if not ks and u.get("cut"):
        c = u["cut"][0]
        t = next((x for x in P.plan_tags(doc) if x.get("id") == c.get("in")), None)
        nm = f"{P._word(str(c.get('tag')).split('::')[-1])}{' · ' + t['name'] if t else ''}"
        return f"{nm}{' + ' + str(len(u['cut']) - 1) + ' more' if len(u['cut']) > 1 else ''}"[:60]
    wo = next((p for p in (_extras(tree).get(q) for q in u.get("search") or []) if p), None) if tree is not None else None
    if not ks and wo:
        return B.label(tree, f"tag:{wo}", placed)[:60]
    if not ks:
        n_ids = len(u.get("nids") or []) + len(u.get("cids") or []) + len(u.get("notes") or [])
        n = len(u.get("cards") or [])
        return ("Search" if u.get("search") else f"{n_ids:,} added by ID" if n_ids
                else f"{n} single card{'s' if n != 1 else ''}" if n else "?")
    return f"{B.label(tree, ks[0], placed)}{f' + {len(ks) - 1} more' if len(ks) > 1 else ''}"[:60]


def from_text(doc, tree, text, whole=False, start="", plan_name="", new_id=None):
    """fromText: the text read against the plan as it is. {units, errors,
    missing, notes, events, warns, why, tags, renamed, remarks}: the dates it
    says (each with its id when it's a date the plan has: the same day and
    name, or in the whole plan the one with that name on another day, or
    with those cards under another name), its events, the plan's tags it
    says, its notes for followers; what it can't read (errors, a line
    each), what's cut short (warns), lines for picking in Anki (notes) and
    an AI's own notes (why), shown, never kept."""
    keys = _Keys(tree)
    placed_now = B.placed_keys(doc, tree) if tree is not None else set()
    taken = {u.get("id") for u in doc.get("units") or []} | {e.get("id") for e in _events(doc)} \
        | {t.get("id") for t in P.plan_tags(doc)} | {r.get("id") for r in _remarks(doc)}

    def uid8():
        if new_id is not None:
            while True:
                x = new_id()
                if x not in taken:
                    taken.add(x)
                    return x
        x = E.new_id({"units": [{"id": i} for i in taken]})
        taken.add(x)
        return x

    errors, units, tags_in, notes, evs, warns, why, lines, remarks_in, pending_cuts = [], [], [], [], [], [], [], [], [], []
    for_name = {}
    local_ids = 0
    auto = {u.get("id") for u in P.units(doc) if not u.get("name") or u.get("name") == auto_name(doc, tree, u, placed_now)}
    root = root_of(doc, plan_name)
    named = set()
    for raw in str(text).split("\n"):
        m = re.match(r"^\s*(?:[-*•]\s+)?`?tag\s*\|\s*([^|]+?)\s*(?:\||$)", raw, re.I)
        if m:
            named.add(P.tag_part(m.group(1)[:40]).lower())

    def plan_tag_key(raw_):
        if "::" in raw_:
            return None
        t = ptag_by_name(doc, raw_)
        if t:
            return f"tag:{ptag_path(doc, t, plan_name)}"
        return f"tag:DueCrew::{root}::{P.tag_part(raw_)}" if P.tag_part(raw_).lower() in named else None

    def srcs_of(part, tg, dk, cuts=None, i=0):
        for x in _SRC_SPLIT.split(part):
            kind = "deck" if x[:4].lower() == "deck" else "tag"
            r = x[x.index(":") + 1:].strip()
            cm = re.match(r"^(\S+)\s+in\s+(\S.*)$", r, re.I) if kind == "tag" and cuts is not None else None
            if cm:
                cuts.append({"tag": B.path_of(keys.find("tag", cm.group(1))), "inName": cm.group(2).strip(), "line": i + 1})
                continue
            key = (plan_tag_key(r) if kind == "tag" and cuts is not None else None) or keys.find(kind, r)
            (tg if kind == "tag" else dk).append(B.path_of(key))

    for i, raw in enumerate(str(text).split("\n")):
        line = re.sub(r"^[-*•]\s+", "", raw.strip())
        line = re.sub(r"^`([^`].*)`$", r"\1", line)
        if not line or raw.strip().startswith("```"):
            continue
        nl = re.match(r"^note(?:\s*\|\s*|\s{2,})(.*)$", line, re.I | re.S)
        if nl:
            r = B.remark_take(nl.group(1))
            if not r or r.get("bad"):
                errors.append(f"Line {i + 1}: a note is note | tag:PATH | your words, or note | card:ID:N | your words "
                              "(N the card's number from 1).")
                continue
            words = B.remark_clean(r["text"])
            if not words:
                errors.append(f"Line {i + 1}: the note has no words.")
                continue
            if len(words) > B.REMARK_TEXT:
                warns.append(f"Line {i + 1}: a note is cut to {B.REMARK_TEXT} characters.")
            x = {"card": r["card"]} if r.get("card") else {"tag": B.path_of(plan_tag_key(r["tag"]) or keys.find("tag", r["tag"]))}
            if "tag" in x and (not x["tag"] or len(x["tag"]) > 200):
                errors.append(f"Line {i + 1}: a note's tag is up to 200 characters.")
                continue
            x["text"] = words[:B.REMARK_TEXT]
            had = next((k for k, y in enumerate(remarks_in) if B.remark_same(x, y)), -1)
            if had >= 0:
                remarks_in[had] = x
            else:
                remarks_in.append(x)
            continue
        picks = None if line.startswith("#") else B.picks_take(line)
        if picks:
            line = picks["line"]
        line = line.replace("`", "")
        if line.startswith("#"):
            (notes if re.search(r"\bpick\b|\bsingle\b", line, re.I) else why).append(re.sub(r"^#+\s*", "", line))
            continue
        parts = [p for p in _SPLIT.split(line) if p]
        if len(parts) >= 2 and re.fullmatch(r"tag", parts[0], re.I):
            full = parts[1].strip()
            tname = full[:40].strip()
            if len(full) > 40:
                warns.append(f"Line {i + 1}: a tag's name is cut to 40 characters.")
            tg, dk, sq, bad = [], [], [], False
            for part in parts[2:]:
                if re.match(r"search:", part, re.I):
                    sq.append(part[7:].strip())
                elif re.match(r"(tag|deck):", part, re.I):
                    srcs_of(part, tg, dk)
                else:
                    errors.append(f"Line {i + 1}: a tag line is tag | its name | notes:…, tag:…, deck:… or search:…")
                    bad = True
                    break
            if bad:
                continue
            if picks and picks["bad"]:
                errors.append(f"Line {i + 1}: \"{picks['bad'][0][:30]}\" isn't a note's ID from Anki (cards: takes ID:N, "
                              "N the card's number from 1).")
                continue
            if any(PERSONAL.search(q) for q in sq):
                errors.append(f"Line {i + 1}: that search finds different cards in each person's Anki; use tags.")
                continue
            gs, cs = (picks["notes"], picks["cards"]) if picks else ([], [])
            if not tname or not (gs or cs or tg or dk or sq):
                errors.append(f"Line {i + 1}: a tag needs a name, and notes:, cards:, a tag:, a deck: or a search:.")
                continue
            if len(gs) > IDS_MAX or len(cs) > IDS_MAX:
                errors.append(f"Line {i + 1}: a tag holds up to 5,000 notes and 5,000 single cards.")
                continue
            want = P.tag_part(tname).lower()
            t = next((x for x in tags_in if P.tag_part(x["name"]).lower() == want), None)
            if t is None:
                was = ptag_by_name(doc, tname)
                t = {"id": was["id"] if was else uid8(), "name": tname}
                tags_in.append(t)
            for k, v in (("notes", gs), ("tags", tg), ("decks", dk), ("search", sq)):
                if v:
                    t[k] = list(dict.fromkeys(list(t.get(k) or []) + list(v)))
            if cs:
                have = {(g, o) for g, o in t.get("cards") or []}
                t["cards"] = list(t.get("cards") or []) + [[g, o] for g, o in cs if (g, o) not in have]
            continue
        if len(parts) >= 3 and _DAY.fullmatch(parts[0]) and re.fullmatch(r"event", parts[1], re.I):
            full = " ".join(parts[2:])
            name = full[:60]
            if len(full) > 60:
                warns.append(f"Line {i + 1}: the event's name is cut to 60 characters.")
            old = next((x for x in _events(doc) if str(x.get("name")).lower() == name.lower()), None)
            evs.append({"id": old["id"] if old else uid8(), "day": parts[0], "name": name})
            continue
        e = {"i": i, "opens": None, "due": None, "even": False, "name": "", "tags": [], "decks": [], "searches": [],
             "nids": [], "cids": [], "picks": picks or {"notes": [], "cards": [], "bad": []}, "keep_cards": False,
             "keep_n": 0, "cuts": [], "todo": [], "for": None}
        at = -1
        for k, part in enumerate(parts):
            name_part = not e["opens"] or k == at + 1
            m = None
            if not e["opens"] and _DAY.fullmatch(part):
                e["opens"], at = part, k
            elif not e["opens"] and (m := re.fullmatch(r"week\s+(\d+)", part, re.I)):
                e["opens"], at = E._later(start, (int(m.group(1)) - 1) * 7), k
            elif (m := re.fullmatch(r"due\s+(\d{4}-\d{2}-\d{2})", part, re.I)):
                e["due"] = m.group(1)
            elif not name_part and re.fullmatch(r"even(ly)?", part, re.I):
                e["even"] = True
            elif not name_part and (m := re.fullmatch(r"for\s+(.+)", part, re.I | re.S)):
                e["for"] = m.group(1).strip()
            elif not name_part and (m := re.fullmatch(r"(\d+) single cards?", part)):
                e["keep_cards"], e["keep_n"] = True, int(m.group(1))
            elif re.match(r"search:", part, re.I):
                e["searches"].append(part[7:].strip())
            elif not name_part and (m := re.fullmatch(r"(watch|read|do):\s*(.+)", part, re.I | re.S)):
                e["todo"].append(B.todo_parse(m.group(1), m.group(2)))
            elif (m := re.fullmatch(r"(nids|cids|ids):\s*([\d\s,;]+)", part, re.I)):
                to = "cids" if m.group(1).lower() == "cids" else "nids"
                e[to] += [int(x) for x in re.split(r"[\s,;]+", m.group(2)) if x and 0 < int(x) <= _SAFE]
            elif re.match(r"(tag|deck):", part, re.I):
                srcs_of(part, e["tags"], e["decks"], e["cuts"], i)
            else:
                e["name"] = f"{e['name']} {part}" if e["name"] else part
        pk = e["picks"]
        if not e["opens"]:
            errors.append(f"Line {i + 1}: starts with a date (2026-10-05) or \"week 3\".")
            continue
        if any(PERSONAL.search(q) for q in e["searches"]):
            errors.append(f"Line {i + 1}: that search finds different cards in each person's Anki; use tags.")
            continue
        if pk["bad"]:
            errors.append(f"Line {i + 1}: \"{pk['bad'][0][:30]}\" isn't a note's ID from Anki (cards: takes ID:N, "
                          "N the card's number from 1).")
            continue
        if not (e["tags"] or e["cuts"] or e["decks"] or e["searches"] or e["nids"] or e["cids"] or pk["notes"] or pk["cards"]
                or e["keep_cards"]):
            errors.append(f"Line {i + 1}: needs a tag:, a deck:, a search: or notes:.")
            continue
        if len(e["nids"]) > IDS_MAX or len(e["cids"]) > IDS_MAX or len(pk["notes"]) > IDS_MAX:
            errors.append(f"Line {i + 1}: a date takes up to 5,000 IDs.")
            continue
        if e["due"] and e["due"] < e["opens"]:
            errors.append(f"Line {i + 1}: due is before it opens.")
            continue
        if e["even"] and not (e["due"] and e["due"] > e["opens"]):
            errors.append(f"Line {i + 1}: \"even\" needs a due date after it opens.")
            continue
        if len(set(e["searches"])) + len(e["cuts"]) > SEARCH_MAX:
            errors.append(f"Line {i + 1}: a date holds up to {SEARCH_MAX} searches and cuts.")
            continue
        if len(set(e["tags"])) > SOURCES_MAX or len(set(e["decks"])) > SOURCES_MAX:
            errors.append(f"Line {i + 1}: a date holds up to {SOURCES_MAX} tags and {SOURCES_MAX} subdecks.")
            continue
        if len(e["name"]) > 60:
            warns.append(f"Line {i + 1}: the name is cut to 60 characters.")
        first = (e["tags"] or e["decks"] or [None])[0] or (e["cuts"][0]["tag"] if e["cuts"] else None)
        e["key"] = (e["name"] or _leaf(first) or "")[:60].strip()
        lines.append(e)

    renamed = []
    if whole:
        def srt(xs):
            return sorted({str(x) for x in xs or []})

        def tsig(t):
            return json.dumps([srt(t.get("notes")), srt(f"{g}:{o}" for g, o in t.get("cards") or []), srt(t.get("tags")),
                               srt(t.get("decks")), srt(t.get("search"))])
        had = {t.get("id") for t in P.plan_tags(doc)}
        fresh = [t for t in tags_in if t["id"] not in had]
        free = [t for t in P.plan_tags(doc) if not any(x["id"] == t.get("id") for x in tags_in)]
        for t in fresh:
            was = [x for x in free if tsig(x) == tsig(t)]
            if len(was) != 1 or len([y for y in fresh if tsig(y) == tsig(t)]) != 1:
                continue
            renamed.append({"id": was[0]["id"], "from": ptag_path(doc, was[0], plan_name), "was": was[0].get("name")})
            t["id"] = was[0]["id"]
            free.remove(was[0])

    claimed = set()
    for e in lines:
        e["old"] = next((u for u in P.units(doc) if u.get("opens") == e["opens"] and str(u.get("name") or "").strip() == e["key"]
                         and not (whole and u["id"] in claimed)), None)
        if e["old"] is not None and whole:
            claimed.add(e["old"]["id"])
    if whole:
        def srt2(xs):
            return sorted({str(x) for x in xs or []})

        def cards_sig(cs):
            return sorted(f"{g}:{o}" for g, o in cs)

        def sig_of(e):
            pk = e["picks"]
            return json.dumps([srt2(e["tags"]), srt2(e["decks"]), srt2(e["searches"]),
                               sorted(f"{c['tag']} in {P.tag_part(c['inName']).lower()}" for c in e["cuts"]),
                               srt2(e["nids"]), srt2(e["cids"]), srt2(pk["notes"]),
                               cards_sig(pk["cards"]) if pk["cards"] else f"#{e['keep_n']}" if e["keep_n"] else []])

        def in_name(c):
            return P.tag_part((next((t for t in P.plan_tags(doc) if t.get("id") == c.get("in")), None) or {}).get("name") or "?").lower()

        def old_sig(u):
            cards = u.get("cards") or []
            return json.dumps([srt2(u.get("tags")), srt2(u.get("decks")), srt2(q for q in u.get("search") or [] if not _cut_of(u, q)),
                               sorted(f"{c.get('tag')} in {in_name(c)}" for c in u.get("cut") or []),
                               srt2(u.get("nids")), srt2(u.get("cids")), srt2(u.get("notes")),
                               f"#{len(cards)}" if len(cards) > CARDS_TEXT else cards_sig(cards)])
        loose = [e for e in lines if e["old"] is None]
        for e in loose:
            free = [u for u in P.units(doc) if u["id"] not in claimed]
            moved = [u for u in free if str(u.get("name") or "").strip() == e["key"]]
            ren = [u for u in free if u.get("opens") == e["opens"] and old_sig(u) == sig_of(e)]
            if len(moved) == 1 and len([x for x in loose if x["key"] == e["key"]]) == 1:
                e["old"] = moved[0]
            elif len(ren) == 1 and len([x for x in loose if x["opens"] == e["opens"] and sig_of(x) == sig_of(e)]) == 1:
                e["old"] = ren[0]
            if e["old"] is not None:
                claimed.add(e["old"]["id"])

    for e in lines:
        old, pk = e["old"] or {}, e["picks"]
        had = [] if pk["cards"] and not e["keep_cards"] else list(old.get("cards") or [])
        seen = {(g, o) for g, o in had}
        cards = had + [[g, o] for g, o in pk["cards"] if (g, o) not in seen]
        if not (e["tags"] or e["cuts"] or e["decks"] or e["searches"] or e["nids"] or e["cids"] or pk["notes"] or cards):
            errors.append(f"Line {e['i'] + 1}: needs a tag:, a deck:, a search: or notes:.")
            continue
        u = {"id": old.get("id") or uid8(), "name": e["name"][:60], "opens": e["opens"],
             "tags": list(dict.fromkeys(e["tags"])), "decks": list(dict.fromkeys(e["decks"])), "cards": cards}
        if e["due"]:
            u["due"] = e["due"]
        for c in e["cuts"]:
            pending_cuts.append(dict(c, u=u))
        if e["even"]:
            u["even"] = True
        if e["searches"]:
            u["search"] = list(dict.fromkeys(e["searches"]))
            sn = {q: old["sn"][q] for q in u["search"] if (old.get("sn") or {}).get(q) is not None}
            if sn:
                u["sn"] = sn  # a search kept as it was keeps its count
        for k in ("nids", "cids"):
            if e[k]:
                u[k] = list(dict.fromkeys(e[k]))
        if pk["notes"]:
            u["notes"] = pk["notes"]
        if has_ids(u) and old and [old.get("nids"), old.get("cids"), old.get("notes")] == [u.get("nids"), u.get("cids"), u.get("notes")] \
                and old.get("idn") is not None:
            u["idn"] = old["idn"]
        if old.get("pl") and _picks_sig(old) == _picks_sig(u):
            u["pl"] = old["pl"]
        if (u.get("nids") or u.get("cids")) and not (old.get("idr") and [old.get("nids"), old.get("cids")] == [u.get("nids"), u.get("cids")]):
            local_ids += 1
        if len(e["todo"]) > B.TODO_MAX:
            warns.append(f"Line {e['i'] + 1}: a date keeps {B.TODO_MAX} lines to tick; the rest are left off.")
        if e["todo"]:
            u["todo"] = e["todo"][:B.TODO_MAX]
        if e["for"]:
            for_name[u["id"]] = e["for"]
        if not u["name"]:
            u["name"] = auto_name(doc, tree, u, placed_now)
            auto.add(u["id"])
        units.append(u)

    for c in pending_cuts:
        u, want = c["u"], P.tag_part(c["inName"]).lower()
        t = next((x for x in tags_in if P.tag_part(x["name"]).lower() == want), None) or ptag_by_name(doc, c["inName"])
        if not t:
            errors.append(f"Line {c['line']}: no tag of this plan is called {c['inName']}. Make it with a tag | {c['inName']} | … line.")
            continue
        if not any(x.get("tag") == c["tag"] and x.get("in") == t["id"] for x in u.get("cut") or []):
            u["cut"] = list(u.get("cut") or []) + [{"tag": c["tag"], "in": t["id"], "q": ""}]
        if u["id"] in auto and not B.srcs(u) and u["cut"][0]["tag"] == c["tag"]:
            more = f" + {len(u['cut']) - 1} more" if len(u["cut"]) > 1 else ""
            u["name"] = f"{P._word(c['tag'].split('::')[-1])} · {t['name']}{more}"[:60]
        elif u["id"] in auto and not B.srcs(u):
            u["name"] = re.sub(r"( \+ \d+ more)?$", f" + {len(u['cut']) - 1} more", u["name"], count=1)[:60]

    ours = f"tag:DueCrew::{root}::".lower()
    want_keys = [k for u in units for k in [f"tag:{t}" for t in u["tags"]] + [f"tag:{c['tag']}" for c in u.get("cut") or []]
                 + [f"deck:{d}" for d in u["decks"]]] + [f"tag:{x['tag']}" for x in remarks_in if x.get("tag")]
    missing = [k for k in dict.fromkeys(want_keys) if keys.size() and not keys.has(k) and not k.lower().startswith(ours)]
    for u in units:
        n = for_name.get(u["id"])
        if not n:
            continue
        ev = next((x for x in evs + _events(doc) if str(x.get("name")).lower() == n.lower()), None)
        if ev:
            u["for"] = ev["id"]
        else:
            errors.append(f"\"for {n}\": no event by that name. Add a line like 2026-10-15 | event | {n}")
    if local_ids:
        warns.append(f"{local_ids} date{' uses' if local_ids == 1 else 's use'} nids: or cids:, your Anki's own numbers. "
                     "Open Anki after you save, and they'll work in everyone's copy.")
    if len(tags_in) + len([t for t in P.plan_tags(doc) if not any(x["id"] == t.get("id") for x in tags_in)]) > TAGS_MAX:
        errors.append(f"A plan holds up to {TAGS_MAX} tags.")
    rm_n = len(remarks_in) if whole else len([y for y in _remarks(doc) if not any(B.remark_same(x, y) for x in remarks_in)]) + len(remarks_in)
    if rm_n > B.REMARKS_MAX:
        errors.append(f"A plan holds up to {B.REMARKS_MAX} notes on tags and cards; this would make {rm_n}.")
    ids_now = {u.get("id"): u for u in P.units(doc)}
    dates = len(units) if whole else len(ids_now) + len([u for u in units if u["id"] not in ids_now])
    if dates > UNITS_MAX:
        errors.append(f"A plan holds up to {UNITS_MAX} dates; this would make {dates}.")
    ev_n = len(evs) if whole else len([x for x in _events(doc) if not any(y["id"] == x.get("id") for y in evs)]) + len(evs)
    if ev_n > EVENTS_MAX:
        errors.append(f"A plan holds up to {EVENTS_MAX} events; this would make {ev_n}.")
    if not whole:
        for u in units:
            x = ids_now.get(u["id"])
            if x and len(set(x.get("search") or []) | set(u.get("search") or [])) + len(
                    [c for c in u.get("cut") or [] if not any(y.get("tag") == c["tag"] and y.get("in") == c["in"] for y in x.get("cut") or [])]) > SEARCH_MAX:
                errors.append(f"{P.fmt_day(x['opens'])}, {x.get('name')}: a date holds up to {SEARCH_MAX} searches and cuts.")
    return {"units": units, "errors": errors, "missing": missing, "notes": notes, "events": evs, "warns": warns,
            "why": [w for w in why if w][:60], "tags": tags_in, "renamed": renamed, "remarks": remarks_in}


# ---- what it would change (the Text tab's preview) ----

def _tag_re(path):
    return E._tag_re(path)


def gone(doc, r, whole):
    """What the whole plan's text leaves out: (dates, tags, notes) that go."""
    if not whole:
        return [], [], []
    return ([u for u in P.units(doc) if not any(x["id"] == u["id"] for x in r["units"])],
            [t for t in P.plan_tags(doc) if not any(x["id"] == t.get("id") for x in r["tags"])],
            [y for y in _remarks(doc) if not any(B.remark_same(x, y) for x in r["remarks"])])


def _uses(doc, u, ts, plan_name=""):
    return [t for t in ts if any(str(x).lower() == ptag_path(doc, t, plan_name).lower() for x in u.get("tags") or [])
            or any(c.get("in") == t.get("id") for c in u.get("cut") or [])
            or any(_tag_re(ptag_path(doc, t, plan_name)).search(q) for q in u.get("search") or [])]


def _bare(u):
    return not (B.srcs(u) or u.get("cards") or u.get("search") or u.get("cut") or has_ids(u))


def take_off(doc, u, ts, plan_name=""):
    """takeOff: the plan's tags off one date (a cut is its whole tag again, a search using one goes)."""
    for t in ts:
        path = ptag_path(doc, t, plan_name)
        u["tags"] = [x for x in u.get("tags") or [] if str(x).lower() != path.lower()]
        for c in [x for x in u.get("cut") or [] if x.get("in") == t.get("id")]:
            E._drop_search(u, c.get("q"))
            u["cut"] = [x for x in u["cut"] if x is not c]
            if not u["cut"]:
                del u["cut"]
            u["tags"] = list(dict.fromkeys(u["tags"] + [c["tag"]]))
        for q in list(u.get("search") or []):
            if _tag_re(path).search(q):
                E._drop_search(u, q)


def using(doc, r, whole, plan_name=""):
    """The dates in the text that still use a tag it takes off: [(unit, why)]."""
    _gu, gone_tags, _gr = gone(doc, r, whole)
    if not gone_tags:
        return []
    out = []
    for u in sorted(r["units"], key=lambda u: u["opens"]):
        ts = _uses(doc, u, gone_tags, plan_name)
        if not ts:
            continue
        only = [f"only what's in {t['name']}" for c in u.get("cut") or [] for t in ts if t.get("id") == c.get("in")]
        names = [t.get("name") for t in ts if not any(c.get("in") == t.get("id") for c in u.get("cut") or [])]
        left = copy.deepcopy(u)
        take_off(doc, left, ts, plan_name)
        out.append((u, ", ".join(names + only) + (", nothing else on it: it would find nothing" if _bare(left) else "")))
    return out


def take_all(doc, r, tree, plan_name=""):
    """Take them off those dates too: the tags the text takes off, off the
    dates in it that use them; a date left with nothing goes. The lines it
    says, date by date."""
    _gu, gone_tags, _gr = gone(doc, r, True)
    said = []
    placed = B.placed_keys(doc, tree) if tree is not None else set()
    for u, _why in using(doc, r, True, plan_name):
        ts = _uses(doc, u, gone_tags, plan_name)
        cuts = [c for c in u.get("cut") or [] if any(t.get("id") == c.get("in") for t in ts)]
        was, was_auto = u["name"], u["name"] == auto_name(doc, tree, u, placed)
        take_off(doc, u, ts, plan_name)
        if was_auto and not _bare(u):
            u["name"] = auto_name(doc, tree, u, placed)
        what = ("nothing left on it, so it goes" if _bare(u) else "; ".join(p for p in (
            ", ".join(f"{t['name']} off it" for t in ts if not any(c.get("in") == t.get("id") for c in cuts)),
            ", ".join(f"back to all of {P._word(c['tag'].split('::')[-1])}" for c in cuts)) if p))
        said.append(f"{P.fmt_day(u['opens'])} · {was}: {what}")
    r["units"] = [u for u in r["units"] if not _bare(u)]
    return said


def keep_tags(doc, text, r):
    """Keep the tags: the lines of the tags the text takes off, back in it."""
    _gu, gone_tags, _gr = gone(doc, r, True)
    return "\n".join([tag_line(t) for t in gone_tags] + [text]), [t.get("name") for t in gone_tags]


def heavy_after(doc, tree, r, whole, pace, start):
    """A day over the pace, as the plan would be after this: [{a, b, top}], cap."""
    if tree is None:
        return [], 0
    cap = ((B.end_daily(doc, tree, pace, set(pace.get("cover") or []), start) or int(pace.get("daily") or 0))
           if pace.get("mode") == "end" else int(pace.get("daily") or 0) if pace.get("mode") == "daily" else 0)
    if not cap:
        return [], 0
    placed = {k for u in r["units"] for k in B.srcs(u)}
    after = r["units"] if whole else [x for x in P.units(doc) if not any(u["id"] == x["id"] for u in r["units"])] + r["units"]
    work = B.work_map(dict(doc, units=after), lambda u: B.unit_total(tree, u, placed), pace.get("days") or [1] * 7)
    return B.over(work, cap), cap


# ---- Add to the plan, Replace the plan's dates (use) ----

def _merge(into, u):
    for c in u.get("cut") or []:
        if not any(x.get("tag") == c["tag"] and x.get("in") == c["in"] for x in into.get("cut") or []):
            into["cut"] = list(into.get("cut") or []) + [c]
    for k in ("tags", "decks", "search", "nids", "cids", "notes"):
        if not u.get(k):
            continue
        was = list(into.get(k) or [])
        into[k] = list(dict.fromkeys(was + list(u[k])))
        if into[k] != was and k in ("nids", "cids", "notes"):
            into.pop("idn", None)
    have = {(g, o) for g, o in into.get("cards") or []}
    into["cards"] = list(into.get("cards") or []) + [[g, o] for g, o in u.get("cards") or [] if (g, o) not in have]
    for k in ("due", "even", "for"):
        if u.get(k):
            into[k] = u[k]
    if u.get("todo"):
        had = {f"{x['k']}:{x['t'].lower()}" for x in into.get("todo") or []}
        into["todo"] = (list(into.get("todo") or []) + [x for x in u["todo"] if f"{x['k']}:{x['t'].lower()}" not in had])[:B.TODO_MAX]


def apply(doc, r, replace, plan_name="", new_id=None):
    """use(): the text's dates, events, tags and notes on the plan (Add), or
    the plan as the text says (Replace); a cut's search as its tags are now."""
    doc = copy.deepcopy(doc)
    r = copy.deepcopy(r)
    taken = {x.get("id") for x in _remarks(doc)}

    def uid8():
        x = new_id() if new_id is not None else E.new_id({"units": [{"id": i} for i in taken]})
        taken.add(x)
        return x
    if r["events"] or replace:
        keep = [] if replace else [x for x in _events(doc) if not any(y["id"] == x.get("id") for y in r["events"])]
        evs = sorted(keep + r["events"], key=lambda x: str(x["day"]))
        if evs:
            doc["events"] = evs
        else:
            doc.pop("events", None)
    if replace:
        doc["units"] = r["units"]
    else:
        units = doc.setdefault("units", [])
        for u in r["units"]:
            x = next((y for y in units if y.get("id") == u["id"]), None)
            if x is not None:
                _merge(x, u)
            else:
                units.append(u)

    def keep_id(x):
        old = next((y for y in _remarks(doc) if B.remark_same(x, y)), None)
        return dict({"id": old["id"] if old else uid8()}, **x)
    if replace:
        rs = [keep_id(x) for x in r["remarks"]]
    else:
        rs = [dict(y) for y in _remarks(doc)]
        for x in r["remarks"]:
            y = next((z for z in rs if B.remark_same(x, z)), None)
            if y is not None:
                y["text"] = x["text"]
            else:
                rs.append(keep_id(x))
    if rs:
        doc["remarks"] = rs
    else:
        doc.pop("remarks", None)

    def put_tags(lst):
        if lst:
            doc["tagroot"], doc["tags"] = root_of(doc, plan_name), lst
        else:
            doc.pop("tags", None)
    if replace:
        put_tags(r["tags"])
        for x in r["renamed"]:
            t = next((y for y in P.plan_tags(doc) if y.get("id") == x["id"]), None)
            if t is not None:
                E._retag(doc, x["from"], P.tag_path(doc, t))
    elif r["tags"]:
        lst = [copy.deepcopy(t) for t in P.plan_tags(doc)]
        for t in r["tags"]:
            x = next((y for y in lst if y.get("id") == t["id"]), None)
            if x is None:
                lst.append(t)
                continue
            for k in ("notes", "tags", "decks", "search"):
                if t.get(k):
                    x[k] = list(dict.fromkeys(list(x.get(k) or []) + list(t[k])))
            if t.get("cards"):
                have = {(g, o) for g, o in x.get("cards") or []}
                x["cards"] = list(x.get("cards") or []) + [[g, o] for g, o in t["cards"] if (g, o) not in have]
        put_tags(lst)
    E._sync_cuts(doc)
    if doc.get("reviews"):
        ids = {u.get("id") for u in doc.get("units") or []}
        doc["reviews"] = [x for x in doc["reviews"] if x.get("from") in ids and x.get("to") in ids]
        if not doc["reviews"]:
            del doc["reviews"]
    doc["units"] = sorted(doc.get("units") or [], key=lambda u: str(u.get("opens") or ""))
    return doc
