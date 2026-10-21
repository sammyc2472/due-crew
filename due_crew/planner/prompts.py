"""The prompts for your own AI (round five, docs/planner.md): Plan the dates
and Tag by objective, the same words duecrew.com's Text gives (builder.js
Prompts, its twin: the suite runs both on the same cases). Copied from
Your plans into any AI chat with the syllabus; its answer comes back as
plan lines in the box under the plan, and waits to be sent like any change.

Names and counts only: the plan's dates, the deck's tag names with their
card counts, the plan's own tags. Never a card's text.

Pure."""

import re

from .. import plans as P
from . import build as B
from . import text as T

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_NUM = re.compile(r"^\d+$")
_HASH = re.compile(r"^[0-9a-f-]{12,}$", re.I)
_LONG = re.compile(r"^[A-Za-z0-9_-]{24,}$")


def _segs(k):
    return B.path_of(k).split("::")


def _unreadable(k):
    w = re.sub(r"^[#^$!]+", "", _segs(k)[-1])
    return bool(_NUM.match(w) or _HASH.match(w) or (_LONG.match(w) and re.search(r"\d", w)))


def _in_res(k):
    return any(x.startswith("#") for x in _segs(k)[1:])


def _rank(k):
    last = _segs(k)[-1]
    return 0 if last.startswith("#") else 1 if last.startswith("^") else 2


def _order(ks):
    return sorted(ks, key=_rank)  # stable, as the site's sort


def n_(v):
    return f"{int(v):,}"


def tag_lines(tree, cover=None):
    """tagLines: the deck's tags for the plan's prompt: what's ticked
    (cover, in the deck's order), whole; else the top levels, and resources
    five levels down; a branch of mostly numbered tags is one line; 600
    lines at most. (lines, more)."""
    keys, collapsed = [], {}

    def walk(k, depth):
        if len(keys) >= 600 or _unreadable(k):
            return
        keys.append(k)
        ks = tree.kids(k)
        odd = sum(1 for x in ks if _unreadable(x))
        if len(ks) >= 10 and odd >= len(ks) * 0.8:
            collapsed[k] = odd
            return
        if cover or depth < 2 or (_in_res(k) and depth < 5):
            for c in _order(ks):
                walk(c, depth + 1)
    for k in _order(cover if cover else tree.kids("root:tag") + tree.kids("root:deck")):
        walk(k, 0)
    lines = [f"{B.kind_of(k)}:{B.path_of(k)}  ({n_(tree.n(k))} cards) {B.tag_name(B.path_of(k))}"
             + (f" [{n_(collapsed[k])} numbered tags under it, not listed]" if k in collapsed else "") for k in keys]
    return lines, len(tree.order) - len(keys)


def plan(a):
    """Prompts.plan. a: {name, deck, start, end, days, mode, daily, phases,
    units, lines, more, cover, ptags: [{name, path, size}], planned, pn}."""
    day_names = ", ".join(d for i, d in enumerate(DAYS) if a["days"][i])
    ph = a.get("phases") or {}
    pace = (f"- About {a['daily']} new cards a study day." if a.get("mode") == "daily" and a.get("daily")
            else "- Finish everything by the end date, at an even pace." if a.get("mode") == "end" and a.get("end")
            else "- Each date's cards are for that date; nothing spreads over days unless its line says even.")
    units = a.get("units") or 0
    out = [
        f"I'm planning what to study in Anki, day by day, for \"{a['name']}\" on the deck \"{a['deck']}\". Due Crew opens each day's cards (unsuspends them) on the morning of that day, for me and everyone following the plan.",
        "",
        "The plan so far:",
        f"- Starts {a['start']}{', ends ' + a['end'] if a.get('end') else ', no end date yet'}.",
        f"- Study days: {day_names}.",
        pace,
        f"- Every {ph['catchup']}th week is a catch-up week: nothing new opens." if ph.get("catchup") else None,
        f"- The last {ph['taper']} days before the end open nothing new." if ph.get("taper") else None,
        f"- {units} dates are already planned (as text below the tags); keep or change them." if units else None,
        "",
        "Write the plan in exactly this format, one line per date, and nothing else (no table; anything you want to explain goes on a line starting with #):",
        "",
        "YYYY-MM-DD | a short name (60 characters at most) | tag:FULL::TAG::PATH, tag:ANOTHER::PATH | due YYYY-MM-DD | even | for EVENT NAME",
        "YYYY-MM-DD | a short name (60 characters at most) | notes:ID ID ID | cards:ID:2 ID:1",
        "",
        "The whole format: https://duecrew.com/plan-text",
        "",
        "Rules:",
        "- The first part is the date those cards open: YYYY-MM-DD, or \"week 3\" for the Monday of the plan's third week. The part after it is the date's name, as it reads (\"Read: Chapter 3\" is a name there).",
        "- A tag brings every card under it. A whole chapter is its tag; a smaller part is a deeper tag (a section, a lecture). Copy tags exactly from the list below, the part before the two spaces; never invent one.",
        "- A subdeck works the same way: deck:FULL::DECK::PATH.",
        "- This plan's own tags (my course's, like SLG 12) are listed below too; a date uses one by its name: tag:SLG 12. A resource kept to what one of them holds is the resource's tag, then in and the name: tag:#Videos::Pharm::Cephalosporins in SLG 12." if a.get("ptags") else None,
        "- When a lecture is only part of a tag (two tags at once, or one without another), use an Anki search instead: search:tag:A tag:B -tag:C.",
        "- Several tags can open the same day: separate them with commas on one line.",
        "- Exact notes: notes:ID ID ID brings every card of those notes (every cloze), the IDs separated by spaces. Exact cards: cards:ID:N ID:N brings card N of each note (1 is the first). These IDs can hold any character but a space; copy each exactly. For a plan others follow, use notes: and cards:; numeric nids: and cids: only work in my own Anki. Use only IDs I give you below; never invent, guess or round one. At most 5,000 on a line; split a longer list over dates.",
        "- An Anki search never uses deck:current, is:due, is:new, is:learn, is:review, is:suspended, is:buried, rated:, prop:, introduced:, added:, edited:, resched:, flag:, nid: or cid: (they find different cards for each person), and stays under 500 characters.",
        "- Events are named days with no cards (a lecture, a quiz, an exam): YYYY-MM-DD | event | Micro quiz, or YYYY-MM-DD | event | Unit 3 test. A date that preps for one ends with | for Micro quiz, the name exactly as on its event line. A date after its event can name it too: it reads \"after Micro quiz\", review after it.",
        "- A date can ask for things cards can't measure, ticked by hand (up to 8): | watch: Lecture 14, renal clearance | read: chapter 6 | do: practice block 3. A link may follow the words: | watch: Lecture 14 https://example.com/l14",
        "- A note for followers on a video's or a chapter's tag, or on one card, shows in their Anki when it comes up: note | tag:FULL::TAG::PATH | Skip the last two minutes, or note | card:ID:N | This one's on the quiz. One line in your own words, 280 characters at most, one a tag or a card; never card text.",
        "- A chapter too big for one day: put its deeper tags on different days, or give it a due date and the word even to spread it evenly from its date to its due date (\"| due 2026-10-09 | even\").",
        "- Without a due date, a date's cards are meant to be done before the next date opens.",
        "- If a day needs specific cards and I gave you no IDs for them, don't guess: add a line starting with # that says which (\"# Pick in Anki for 2026-10-06: the iron-study cards from Lecture 17\"); I'll pick them in Anki.",
        "- Leave out days off and catch-up weeks.",
        "",
        "Resources, and my cards if I attached them:",
        "- Many decks file cards under a resource: a video, a lecture, a book's chapter. If tags below look like that, a resource's tag brings every card filed under it. For each topic, pick the resource that best matches what my course needs, and keep its cards together on one date; a few extra cards from a good match are fine, and so is opening something a little before it's taught.",
        "- What my course needs to know decides what goes in, not which resource it's filed under: look beyond the chosen tags for other cards it needs.",
        "- If I attached a text file exported from Anki, it's my cards: one note per line, tab-separated. Its first lines say which column is which (#guid column:N is the note's ID, #tags column:N its tags). Use the card text to judge what each resource and tag actually covers; a tag doesn't prove every card under it is taught.",
        "- To add cards the chosen tags miss, use notes: with IDs from the #guid column, copied exactly (they can hold any character but a space). Never quote or copy card text into the plan.",
        "- If my course needs something no card covers, say so on a # line; don't invent cards.",
        "- After the plan, one # line per date at most: what you chose for it, and why.",
        "",
        "Before you answer, check the plan (yours and what's already planned):",
        "- Every topic or objective I gave is on a date, or named on a # Missing: line. Look through all the deck's tags before saying the deck doesn't have it.",
        "- No date mostly repeats an earlier one, and none brings many cards my course doesn't need. A good video's whole set can bring a few extra; keep it and say so.",
        "- A date that preps for an event opens before that event, with time to study it.",
        "- Name each problem on its own line: # Problem: (something that's wrong), # Tradeoff: (a choice I might make differently), # Question: (something you can't tell from what I gave). Name the date. Skip what's fine.",
        "- If I only ask you to check the plan, answer with # lines only.",
        "- Write only new dates, or what to add to a date already planned: a line with the same date and name as one below adds to it. Dates below stay as they are unless I ask to change them; then give the whole plan." if units else None,
        "- Keep every notes:, cards:, nids: and cids: in the plan below on its line, exactly as written, unless I ask to move or drop it. Keep its note lines too." if units else None,
        "",
        "Example:",
        "2026-10-05 | Microcytic anemias | tag:Heme::Red_cells::Microcytic",
        "2026-10-06 | Hemolysis | tag:Heme::Red_cells::Hemolytic | due 2026-10-08 | even | for Heme quiz",
        "2026-10-07 | Lecture 12 cards | notes:Ab3$kL9qZ1 p&x8Hk!eQ2 | for Heme quiz",
        "2026-10-09 | event | Heme quiz",
        "2026-10-12 | Chapter 4 | tag:Chemistry::Unit_3::Chapter_4 | read: Chapter 4, sections 1 to 3 | for Unit 3 test",
        "2026-10-16 | event | Unit 3 test",
        "note | tag:Heme::Red_cells::Hemolytic | Lecture 9's slides cover this better than the book.",
        "",
        "My syllabus, learning objectives and exam dates, or what I want (edit this part):",
        "",
        "",
        "Note IDs or card IDs I have, and what each list is for (in Anki's browser: select them, right-click, Due Crew: copy as plan selector; paste here, or leave this empty):",
        "",
        "",
    ]
    if a.get("ptags"):
        out += ["This plan's own tags (its name, its full tag in Anki, how big):",
                *[f"{t['name']}  tag:{t['path']}  ({t['size']})" for t in a["ptags"]], ""]
    more = a.get("more") or 0
    out.append(f"The deck's tags{' for what the plan covers' if a.get('cover') else ''} (tag or subdeck, card count, readable name)"
               + (f"; {n_(more)} more aren't listed, ask me for a branch" if more > 0 else "") + ":")
    out += list(a.get("lines") or [])
    if a.get("planned"):
        out += ["", "Already planned:", a["planned"]]
    if a.get("pn"):
        out += ["", "What each planned date opens, as my Anki counted it (new to that date, already on an earlier date, picked notes not in my deck):",
                *a["pn"]]
    return "\n".join(x for x in out if x is not None)


def standing(items):
    """Prompts.standing: [(line, its IDs, short line)] -> (lines, cut)."""
    lines, cut, ids = [], False, 0
    for line, m, short in items:
        if ids + m <= 2000:
            ids += m
            lines.append(line)
            continue
        cut = True
        lines.append(short)
    return lines, cut


def tag_list(tree):
    """Prompts.tagList: 300 of the deck's tags at most, in its order, never Due Crew's own."""
    keys = [k for k in tree.order if B.kind_of(k) == "tag" and not B.path_of(k).startswith("DueCrew::")]
    keys.sort(key=lambda k: tree.order.get(k, 0))
    return [f"tag:{B.path_of(k)}  ({n_(tree.n(k))} cards)" for k in keys[:300]]


def tags(a):
    """Prompts.tags. a: {name, deck, root, has, standing: (lines, cut), list}."""
    lines, cut = a.get("standing") or ([], False)
    out = [
        f"I'm tagging my Anki cards for \"{a['name']}\" on the deck \"{a['deck']}\" by my course's own objectives. Due Crew puts each tag on the cards of everyone following the plan, in their own Anki.",
        "",
        "For each objective I give, write one line, and nothing else (anything you want to explain goes on a line starting with #):",
        "",
        "tag | NAME | notes:ID ID ID",
        "tag | NAME | cards:ID:2 ID:1",
        "",
        f"In Anki each one becomes the tag DueCrew::{a['root']}::NAME (spaces as _).",
        "",
        "The whole format: https://duecrew.com/plan-text",
        "",
        "Rules:",
        "- NAME is the objective's short name as my course writes it (SLG 12, Week 3, Lecture 14), 40 characters at most.",
        "- The IDs are from the #guid column of the text file I attached (my cards, exported from Anki), copied exactly; they can hold any character but a space. Use only IDs from that file; never invent, guess or round one.",
        "- notes:ID brings every card of the note. When only some of a note's cards fit (one cloze of three), use cards:ID:N instead, N a card's number from the #cards column (1 is the first).",
        "- Read each card's text to judge whether it serves the objective. A card can be on more than one objective; leave out a card that only touches one in passing.",
        "- When every card under one of my deck's tags fits an objective, write the tag instead of the IDs: tag | NAME | tag:FULL::TAG::PATH, copied exactly from the list below or the #tags column.",
        "- At most 5,000 notes and 5,000 cards on a line; a bigger objective is two names (SLG 12a, SLG 12b).",
        "- Never quote or copy card text into your answer.",
        "- After each tag line, one # line: what you took, what you left out, and why.",
        "- If an objective has no cards in the file, say so on a # line; don't invent any.",
        "- This plan's tags as they stand are below. A line with the same name adds to that tag; to change one, say so on a # line." if a.get("has") else None,
        "- A note for followers on one of the tags, or on one card, shows in their Anki: note | tag:NAME | your words, or note | card:ID:N | your words. One line, 280 characters at most; never card text.",
        "",
        "Example:",
        "tag | SLG 12 | notes:Ab3$kL9qZ1 p&x8Hk!eQ2",
        "# SLG 12: the receptor-and-effect cards from the video and chapter 5; left out 9 on toxicity (SLG 15).",
        "tag | SLG 14 | tag:#Book::Pharm::Ch07",
        "# SLG 14: the whole chapter fits.",
        "tag | Unit 3 | tag:Chemistry::Unit_3",
        "# Unit 3: every card under the unit's tag fits.",
        "",
        "My objectives (edit this part):",
        "",
        "",
    ]
    if a.get("has"):
        out += ["This plan's tags now, as they stand (a line with the same name adds to one):", *lines,
                "A tag above with a count in brackets has more IDs than fit here; the whole lists are in Text › Edit the whole plan." if cut else None, ""]
    out.append("Tags in my deck, for whole-tag answers (tag, card count):")
    out += list(a.get("list") or [])
    return "\n".join(x for x in out if x is not None)


# ---- from a plan in Your plans ----

def ptag_size(doc, tree, t, plan_name=""):
    """ptagSize: how big one of the plan's own tags is: its cards in this
    Anki once it's here (the tree), else its notes and single cards."""
    k = f"tag:{P.tag_path(doc, t)}"
    m, c = len(t.get("notes") or []), len(t.get("cards") or [])
    have = tree is not None and tree.has(k)
    if have and not c:
        return f"{n_(tree.n(k))} cards"
    parts = [p for p in (f"{n_(m)} note{'' if m == 1 else 's'}" if m else "", f"{n_(c)} single card{'' if c == 1 else 's'}" if c else "") if p]
    return ", ".join(parts) if parts else f"{n_(tree.n(k))} cards" if have else "counted in your Anki soon"


def for_plan(doc, tree, name, start, cover=None):
    """The plan's prompt for this plan here (aiPrompt's arguments, as the
    builder gathers them)."""
    pace = dict({"mode": "placed" if doc.get("units") else "daily", "days": [1] * 7, "daily": 20}, **(doc.get("pace") or {}))
    if not doc.get("pace") and doc.get("end"):
        pace["mode"] = "end"
    lines, more = tag_lines(tree, cover) if tree is not None else ([], 0)
    units = P.units(doc)
    return plan({
        "name": name, "deck": doc.get("deck") or "", "start": start, "end": doc.get("end") or "", "days": pace["days"],
        "mode": pace["mode"], "daily": pace.get("daily"), "phases": doc.get("phases") or {}, "units": len(units),
        "lines": lines, "more": more, "cover": bool(cover),
        "ptags": [{"name": t.get("name"), "path": P.tag_path(doc, t), "size": ptag_size(doc, tree, t)} for t in P.plan_tags(doc)],
        "planned": T.to_text(doc) if units else "",
        "pn": [f"{u['opens']} {u.get('name')}: {u['pn'][0] + len(u.get('cards') or [])} new, {u['pn'][1]} repeat, {u['pn'][2]} not in my deck"
               for u in units if u.get("pn")],
    })


def for_tags(doc, tree, name):
    """Tag by objective's prompt for this plan here (tagPrompt's arguments)."""
    ptags = P.plan_tags(doc)
    items = []
    for t in ptags:
        first = ", ".join([f"tag:{x}" for x in t.get("tags") or []] + [f"deck:{x}" for x in t.get("decks") or []])
        srcs = [x for x in [first, *[f"search:{q}" for q in t.get("search") or []]] if x]
        items.append((T.tag_line(t), len(t.get("notes") or []) + len(t.get("cards") or []),
                      f"{' | '.join(['tag', t.get('name') or '', *srcs])} ({ptag_size(doc, tree, t)})"))
    return tags({"name": name, "deck": doc.get("deck") or "", "root": doc.get("tagroot") or P.tag_root(name), "has": bool(ptags),
                 "standing": standing(items), "list": tag_list(tree) if tree is not None else []})
