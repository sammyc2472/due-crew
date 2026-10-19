"""Labs, reading a block (docs/planner.md): the jobs that start a plan from a
block's calendar, done by plain rules wherever plain rules can. A calendar
read into sessions (each line that starts with a date, or a table's row
with a date in one cell; the lines under a session its objectives and the
resources it lists); each session matched to the deck's own tags by the
words of its title, what it lists and its objectives (tag names only: card
text is never read here); and what an exam covers ("weeks 1-3", "Oct 26 to
Nov 13", "lectures 1-12"). What plain rules leave (no session found, a
session nothing matched, words of a scope they can't place) is what
Claude's job would be: claude.py. Pure: the deck is a plans.DeckIndex.

The calendar's rules come from Course on a Mac (poc/course_mac/cal.py);
the word matching from its find.py, the way the builder's Suggest matches
a date's name: every word of a term in the tag's path, one in its last part.
"""

import csv
import datetime as dt
import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree

from . import model as M

# ---- the calendar ----

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_WD = r"(?:mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)[a-z]*\.?,?\s+"
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
DATE_RES = [
    ("iso", re.compile(r"^\s*(?:" + _WD + r")?(\d{4})-(\d{1,2})-(\d{1,2})\b", re.I)),
    ("num", re.compile(r"^\s*(?:" + _WD + r")?(\d{1,2})[/.](\d{1,2})(?:[/.](\d{2,4}))?\b", re.I)),
    ("md", re.compile(r"^\s*(?:" + _WD + r")?" + _MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.I)),
    ("dm", re.compile(r"^\s*(?:" + _WD + r")?(\d{1,2})(?:st|nd|rd|th)?\s+" + _MON + r"(?:,?\s+(\d{4}))?\b", re.I)),
]
KINDS = ("lecture", "quiz", "exam", "lab", "other")
EVENT_KINDS = ("quiz", "exam")  # a plan's events; the rest are its dates
_KIND_WORDS = [("exam", r"\b(exam|final|midterm|shelf|test)\b"), ("quiz", r"\b(quiz|ksa|irat|grat|assessment)\b"),
               ("lab", r"\b(lab|dissection|osce|clinical skills)\b")]
_SKIP = re.compile(r"\b(no class|holiday|break|vacation|day off)\b", re.I)
_OBJ = re.compile(r"^\s*(?:[-*•◦]\s*)?((?:SLG|LO|Obj(?:ective)?|Session objective)\s*[\w.-]*\d[\w.-]*|\d{1,2}[.)])"
                  r"\s*[:.)-]?\s+(.+)$", re.I)
_TIME = re.compile(r"^\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\s+", re.I)
_TAGGY = re.compile(r"^\s*(LEC|LECTURE|QUIZ|EXAM|LAB|SG|SMALL GROUP|CBL|TBL)\b[:.]?\s*", re.I)
# a resource the session lists: "Watch: heart failure 1-2", "Read pp. 290-295"
_LISTED = re.compile(r"^\s*(?:[-*•◦]\s*)?(watch|read|videos?|book|sketch(?:es)?|do|questions?)\b\s*[:.-]?\s*(.+)$", re.I)
_WEEK = re.compile(r"\bweek\s+(\d{1,2})\b", re.I)
_CELLS = re.compile(r"\s*(?:\||\t|\s{3,})\s*")
# a cell that says where or who, not what: "Room B2", "Dr. Lee", "B2"
_NOT_TITLE = re.compile(r"^(?:room|rm|bldg|hall|lab \d|dr\.?|prof\.?|zoom)\b|^[A-Z]?\d{1,4}[A-Z]?$", re.I)
TITLE_MAX = 120


def _year_for(month, day, today):
    """No year written: the year that puts the date nearest a little after
    today (a calendar is mostly about what's coming)."""
    best = None
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            d = dt.date(y, month, day)
        except ValueError:
            continue
        score = abs((d - (today + dt.timedelta(days=60))).days)
        if best is None or score < best[0]:
            best = (score, d)
    return best[1] if best else None


def parse_date(text, today, day_first=False):
    """(date, the rest of the line) for a line that starts with a date, else
    (None, text). "Mon 10/26", "10/26/2026", "Oct 26", "26 October 2026",
    "2026-10-26", "Monday, October 26th"."""
    s = str(text or "")
    for kind, rx in DATE_RES:
        m = rx.match(s)
        if not m:
            continue
        try:
            if kind == "iso":
                d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            elif kind == "num":
                a, b = int(m.group(1)), int(m.group(2))
                mo, da = (b, a) if day_first else (a, b)
                if m.group(3):
                    y = int(m.group(3))
                    d = dt.date(y + 2000 if y < 100 else y, mo, da)
                else:
                    d = _year_for(mo, da, today)
            elif kind == "md":
                mo, da = MONTHS[m.group(1).lower()[:3]], int(m.group(2))
                d = dt.date(int(m.group(3)), mo, da) if m.group(3) else _year_for(mo, da, today)
            else:
                da, mo = int(m.group(1)), MONTHS[m.group(2).lower()[:3]]
                d = dt.date(int(m.group(3)), mo, da) if m.group(3) else _year_for(mo, da, today)
        except (ValueError, KeyError):
            continue
        if d:
            return d, s[m.end():]
    return None, s


def kind_of(title, said=None):
    if said in KINDS and said != "other":
        return said
    t = str(title or "").lower()
    for k, rx in _KIND_WORDS:
        if re.search(rx, t):
            return k
    return said if said in KINDS else "lecture"


def clean_title(rest):
    t = _TIME.sub("", str(rest or ""))
    t = re.sub(r"^\s*[-–:|]\s*", "", t)
    word = _TAGGY.match(t)
    if word and (word.group(1).isupper() or re.match(r"\s*[:.–-]", t[word.end(1):])):
        t = t[word.end():]  # a kind column ("LEC", "Lecture:"); "Exam 1" and "Lab safety" are titles
    t = re.sub(r"\s*\((?:dr|prof)\.?[^)]*\)\s*$", "", t, flags=re.I)  # "(Dr. Lee)"
    t = re.sub(r"\s+(?:room|rm\.?|hall|bldg\.?|building)\s+\S+$", "", t, flags=re.I)  # "Room B2": a PDF's cells run together
    return re.sub(r"\s+", " ", t).strip(" -|:–")[:TITLE_MAX]


def split_objective(line):
    """("SLG 12", "Describe …") or ("", "…") for a line under a session."""
    m = _OBJ.match(line)
    if m:
        label = m.group(1).strip().rstrip(".):")
        if re.fullmatch(r"\d{1,2}", label):
            label = ""
        return re.sub(r"\s+", " ", label), m.group(2).strip()
    return "", re.sub(r"^\s*[-*•◦]\s*", "", line).strip()


def _said_kind(rest):
    tagged = _TAGGY.match(_TIME.sub("", str(rest or "").strip()))
    if not tagged:
        return None
    w = tagged.group(1).lower()
    return "quiz" if w == "quiz" else "exam" if w == "exam" else "lab" if w == "lab" else "lecture"


def _row(line, today, day_first):
    """A table's row ("Heart failure | Mon 10/26 | Dr. Lee", tab or wide
    spaces between cells): (date, title, said kind) when one cell is a date
    and another names something; None otherwise."""
    cells = [c for c in _CELLS.split(line.strip()) if c.strip()]
    if len(cells) < 2:
        return None
    for i, c in enumerate(cells):
        d, rest = parse_date(c, today, day_first)
        if not d or rest.strip(" ,.-"):
            continue
        names = [clean_title(x) for j, x in enumerate(cells) if j != i]
        names = [x for x in names if x and not _TIME.fullmatch(x + " ") and re.search(r"[A-Za-z]{3}", x)
                 and not _NOT_TITLE.search(x)]
        if names:
            said = next((_said_kind(x) for j, x in enumerate(cells) if j != i and _said_kind(x)), None)
            return d, names[0], said  # the first cell that names something (a table's title column comes first)
    return None


def session(date, title, kind="lecture", week=None):
    return {"date": date.isoformat() if isinstance(date, dt.date) else str(date), "kind": kind, "title": title,
            "objectives": [], "listed": [], "week": week}


def read_calendar(text, today, day_first=False):
    """A calendar pasted as lines or a table: each line that starts with a
    date, or a row with a date in a cell, is a session; the lines under it,
    its objectives and the resources it lists; a "Week 3" line numbers the
    sessions after it. [session], where a session is {date, kind, title,
    objectives: [{label, text}], listed: [{how, text}], week}. Breaks and
    holidays are left out."""
    out, week = [], None
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        d, said, row = None, None, None
        if _CELLS.search(line.strip()):
            row = _row(line, today, day_first)  # cells (a tab, a bar, wide spaces): a table's row, the date a cell
        if row:
            d, title, said = row
        else:
            d, rest = parse_date(line, today, day_first)
            if d:
                title, said = clean_title(rest), _said_kind(rest)
        if d:
            if not title or _SKIP.search(title):
                out.append(None)  # a date with nothing on it ends the last session's lines
                continue
            out.append(session(d, title, kind_of(title, said), week))
            continue
        wk = _WEEK.search(line)
        if wk and len(line.strip()) <= 40:
            week = int(wk.group(1))
            out.append(None)
            continue
        if out and out[-1] is not None:
            listed = _LISTED.match(line)
            if listed and len(listed.group(2).strip()) >= 3:
                how = listed.group(1).lower()
                how = "watch" if how.startswith("video") or how == "watch" else "read" if how in ("read", "book") else how
                out[-1]["listed"].append({"how": how[:12], "text": listed.group(2).strip()[:200]})
                continue
            label, words_ = split_objective(line)
            if len(words_) >= 8 and (label or raw[:1] in " \t" or re.match(r"^\s*[-*•◦\d]", raw)):
                out[-1]["objectives"].append({"label": label[:20], "text": words_[:300]})
    return merge([s for s in out if s])


def merge(sessions):
    """The same date and title is one session, its lines together; by date."""
    by, order = {}, []
    for s in sessions:
        k = (s["date"], s["title"].lower())
        if k not in by:
            by[k] = {**s, "objectives": list(s.get("objectives") or []), "listed": list(s.get("listed") or [])}
            order.append(k)
            continue
        have = {o["text"].lower() for o in by[k]["objectives"]}
        by[k]["objectives"] += [o for o in s.get("objectives") or [] if o["text"].lower() not in have]
        by[k]["listed"] += [x for x in s.get("listed") or [] if x not in by[k]["listed"]]
    return sorted((by[k] for k in order), key=lambda s: s["date"])


def dated(line, today):
    """True when a date is written anywhere in the line ("we meet on Oct 26")."""
    line = str(line or "")[:300]
    return any(not (k and line[k - 1].isalnum()) and parse_date(line[k:], today)[0] for k in range(len(line)))


def name_from(text, most=60):
    """A plan's name from its calendar's head: the first line before its
    first session that names something and holds no date
    ("BLOCK 2 · Cardiovascular"), else ""."""
    today = dt.date.today()
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if parse_date(line, today)[0] or _row(line, today, False):
            return ""  # the sessions start: a line under one is an objective, not a name
        if dated(line, today):
            continue
        name = re.sub(r"(?i)\s*[·|:-]?\s*\bweek\s+\d{1,2}\b.*$", "", line).strip(" ·|:-")
        if words(name) or re.search(r"(?i)\bblock\s+\d", name):
            return name[:most]
    return ""


def number_weeks(sessions):
    """Sessions the calendar didn't number by week get the week of the
    block they're in: week 1 holds the first session's Monday to Sunday."""
    if not sessions or all(s.get("week") for s in sessions):
        return sessions
    first = dt.date.fromisoformat(min(s["date"] for s in sessions))
    monday = first - dt.timedelta(days=first.weekday())
    for s in sessions:
        if not s.get("week"):
            s["week"] = (dt.date.fromisoformat(s["date"]) - monday).days // 7 + 1
    return sessions


# ---- a calendar's file, dropped on the box ----

FILE_MAX = 5 * 1024 * 1024    # a text calendar is never this big
BIG_MAX = 300 * 1024 * 1024   # a PDF, Word file or deck (their pictures weigh; only their words are read)
TEXT_MAX = 1_000_000          # a block's whole SLG document, as text
PAGES_MAX = 400               # a PDF's pages read, or a deck's slides
KINDS_READ = "a calendar export (.ics), a PDF, a Word file (.docx), slides (.pptx), a CSV or a text file"
BIG = ("pdf", "docx", "pptx")


def kind_of_file(name):
    return str(name or "").lower().rsplit(".", 1)[-1] if "." in str(name or "") else ""


def from_file(name, data):
    """A dropped file as text the box reads: (text, "") or ("", why not). A
    calendar export's events as dated lines, a Word file's paragraphs and
    table rows (cells by tabs), a deck's slides (pptx_text), a CSV's rows,
    text as it is. data: the bytes, or for a .docx or .pptx an open file
    (a deck's pictures are never read). A PDF is the window's (Qt reads
    it). Pure; nothing leaves the computer."""
    ext = kind_of_file(name)
    if isinstance(data, (bytes, bytearray)) and len(data) > (BIG_MAX if ext in BIG else FILE_MAX):
        return "", "That file is too big to be a calendar."
    try:
        if ext == "ics":
            text = _ics(_decode(data))
        elif ext == "docx":
            text = _docx(data)
        elif ext == "pptx":
            text = pptx_text(data)
        elif ext in ("ppt", "key", "odp"):
            return "", "Save the slides as PowerPoint (.pptx) or a PDF and drop that."
        elif ext in ("csv", "tsv"):
            text = _csv(_decode(data), "\t" if ext == "tsv" else None)
        elif ext in ("txt", "text", "md", ""):
            text = _decode(data)
        elif ext in ("xlsx", "xls", "numbers", "ods"):
            return "", "Save the sheet as CSV (File › Save as or Download) and drop that, or copy its cells in."
        elif ext in ("doc", "pages", "rtf", "odt"):
            return "", "Save it as a Word file (.docx) or a PDF and drop that, or copy its text in."
        else:
            return "", f"Due Crew reads {KINDS_READ}. Copy this one's text in instead."
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError, csv.Error, UnicodeError, ValueError):
        return "", "That file couldn't be read. Copy its text in instead."
    text = text.replace("\r\n", "\n").replace("\r", "\n")[:TEXT_MAX]
    return (text, "") if text.strip() else ("", "There's no text in that file.")


def _decode(data):
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return bytes(data or b"").decode(enc)
        except UnicodeDecodeError:
            continue
    return bytes(data or b"").decode("latin-1")


def _ics_unescape(v):
    return re.sub(r"\\([\\;,nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), v)


def _ics(text):
    """A calendar export's events as "2026-10-26  Heart failure" lines, by
    date, each description's lines under it; its name first."""
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]  # a folded line goes on the one before
        else:
            lines.append(raw)
    name, events, ev = "", [], None
    for line in lines:
        key, _, value = line.partition(":")
        prop = key.split(";", 1)[0].upper()
        if prop == "BEGIN" and value.strip().upper() == "VEVENT":
            ev = {}
        elif prop == "END" and value.strip().upper() == "VEVENT":
            if ev and ev.get("day") and ev.get("title"):
                events.append(ev)
            ev = None
        elif prop == "X-WR-CALNAME" and ev is None:
            name = _ics_unescape(value).strip()
        elif ev is not None and prop == "DTSTART":
            m = re.match(r"(\d{4})(\d{2})(\d{2})", value.strip())
            if m:
                ev["day"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        elif ev is not None and prop == "SUMMARY":
            ev["title"] = " ".join(_ics_unescape(value).split())
        elif ev is not None and prop == "DESCRIPTION":
            ev["notes"] = [x.strip() for x in _ics_unescape(value).split("\n") if x.strip()][:20]
    out = [name] if name else []
    for ev in sorted(events, key=lambda e: e["day"]):
        out.append(f"{ev['day']}  {ev['title']}")
        out += [f"    {x}" for x in ev.get("notes") or []]
    return "\n".join(out)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx_text(p):
    """A paragraph's words: its runs, a tab as a tab, a break as a space."""
    out = []
    for el in p.iter():
        if el.tag == _W + "t":
            out.append(el.text or "")
        elif el.tag == _W + "tab":
            out.append("\t")
        elif el.tag in (_W + "br", _W + "cr"):
            out.append(" ")
    return "".join(out)


def _zip(data):
    return zipfile.ZipFile(io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data)


def _part(z, name):
    """One XML part of a Word file or deck, refused when it's too big to be words."""
    info = z.getinfo(name)
    if info.file_size > 40 * 1024 * 1024:
        raise ValueError("too big")
    return ElementTree.fromstring(z.read(info))


def _docx(data):
    """A Word file's paragraphs as lines (a list item as "- …", so it reads as
    an objective) and its tables' rows with their cells by tabs."""
    z = _zip(data)
    body = _part(z, "word/document.xml").find(_W + "body")
    out = []

    def walk(el):
        for child in el:
            if child.tag == _W + "p":
                t = _docx_text(child)
                listed = child.find(f"{_W}pPr/{_W}numPr") is not None
                out.append(("    - " + t.strip()) if listed and t.strip() else t)
            elif child.tag == _W + "tbl":
                for tr in child.iter(_W + "tr"):
                    cells = [" ".join(_docx_text(p).strip() for p in tc.iter(_W + "p")).strip()
                             for tc in tr.findall(_W + "tc")]
                    if any(cells):
                        out.append("\t".join(cells))
            elif child.tag == _W + "sdt":
                content = child.find(_W + "sdtContent")
                if content is not None:
                    walk(content)
    walk(body if body is not None else [])
    return "\n".join(out)


_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _slide_lines(root):
    """A slide's (title, [lines]): its title placeholder's words, then each
    other paragraph (indented by its level) and each table row (cells by
    tabs), in the order the slide holds them."""
    title, lines = "", []
    for el in root.iter():
        if el.tag == _P + "sp":
            ph = el.find(f"{_P}nvSpPr/{_P}nvPr/{_P}ph")
            paras = ["".join(t.text or "" for t in p.iter(_A + "t")) for p in el.iter(_A + "p")]
            paras = [" ".join(x.split()) for x in paras if x.strip()]
            if ph is not None and ph.get("type") in ("title", "ctrTitle") and not title:
                title = " · ".join(paras)
                continue
            for p, text in zip([p for p in el.iter(_A + "p") if "".join(t.text or "" for t in p.iter(_A + "t")).strip()], paras):
                pr = p.find(_A + "pPr")
                lvl = int(pr.get("lvl") or 0) if pr is not None and str(pr.get("lvl") or "0").isdigit() else 0
                lines.append("    " * (lvl + 1) + text)
        elif el.tag == _A + "tr":
            cells = [" ".join("".join(t.text or "" for t in tc.iter(_A + "t")).split()) for tc in el.findall(_A + "tc")]
            if any(cells):
                lines.append("\t".join(cells))
    if not title:
        body = [x for x in lines if x.startswith("    ")]
        if body:
            title = body[0].strip()
            lines.remove(body[0])
    return title, lines


def pptx_slides(data, most=PAGES_MAX):
    """[(title, [lines])], a deck's slides in its own order (the deck's list
    of slides, not their file names); never its pictures or notes."""
    z = _zip(data)
    pres = _part(z, "ppt/presentation.xml")
    rels = _part(z, "ppt/_rels/presentation.xml.rels")
    target = {r.get("Id"): r.get("Target") for r in rels.iter(_REL + "Relationship")}
    out = []
    for sid in pres.iter(_P + "sldId"):
        t = target.get(sid.get(_R + "id"))
        if not t:
            continue
        name = "ppt/" + t.lstrip("/").replace("../", "") if not t.startswith("/ppt/") else t.lstrip("/")
        try:
            out.append(_slide_lines(_part(z, name)))
        except KeyError:
            continue
        if len(out) >= most:
            break
    return out


def pptx_text(data):
    """A deck as the box reads it: each slide's title on a line, its words
    under it (indented: a dated title's objectives), its tables' rows as
    rows (a schedule on a slide reads as a table)."""
    out = []
    for title, lines in pptx_slides(data):
        if title:
            out.append(title)
        out += lines
    return "\n".join(out)


_OBJ_HEAD = re.compile(r"(?i)\b(objectives?|learning (?:goals?|outcomes?)|slgs?|goals|outcomes|by the end)\b")
_NOT_A_TOPIC = re.compile(r"(?i)^(questions?|references?|outline|agenda|overview|summary|thank you|thanks|review|"
                          r"disclosures?|acknowledg\w*|cases?|quiz|break|contents|introduction|intro|any questions\??)$")


def from_slides(pages):
    """What a lecture's slides add to its session: {title, objectives
    [{label, text}], slides [title]}. pages: [(title, [lines])] (a deck's,
    or a PDF's pages, each page's first line its title). An objectives
    slide's lines, and any line labelled like one ("SLG 3 …"), are
    objectives; the other slides' titles name what it covers. Pure."""
    objectives, slides, seen = [], [], set()
    deck_title = ""
    for n, (title, lines) in enumerate(pages):
        title = " ".join(str(title or "").split())[:TITLE_MAX]
        if n == 0:
            deck_title = title
        head = bool(_OBJ_HEAD.search(title))
        for raw in lines:
            line = str(raw).strip()
            label, text = split_objective(line)
            if (head and len(text) >= 8) or (label and len(text) >= 8):
                key = text.lower()
                if key not in seen:
                    seen.add(key)
                    objectives.append({"label": label[:20], "text": text[:300]})
        if n and title and not head and not _NOT_A_TOPIC.match(title.strip(" ?!.:")) and re.search(r"[A-Za-z]{3}", title):
            if title.lower() not in {x.lower() for x in slides}:
                slides.append(title)
    return {"title": deck_title, "objectives": objectives[:60], "slides": slides[:80]}


def pdf_pages(texts):
    """A PDF's pages (Qt's text, a page each) as pages for from_slides:
    each page's first line its title (a deck saved as a PDF)."""
    out = []
    for page in texts or ():
        lines = [x.strip() for x in str(page or "").splitlines() if x.strip()]
        if lines:
            out.append((lines[0], lines[1:]))
    return out


def _csv(text, delimiter=None):
    """A sheet's rows, cells by tabs (a table the reader reads)."""
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    rows = csv.reader(io.StringIO(text), delimiter=delimiter)
    return "\n".join("\t".join(c.strip() for c in row) for row in rows if any(c.strip() for c in row))


def scrambled(text):
    """True when a PDF's text came out in pieces (most lines a letter or
    two), as some PDFs' do: better said than read."""
    lines = [x.strip() for x in str(text or "").splitlines() if x.strip()]
    return bool(lines) and sum(1 for x in lines if len(x) <= 3) > len(lines) / 2


def file_name(name):
    """A dropped file's name as a plan's ("MS2 Block 2 calendar.pdf" → "MS2
    Block 2 calendar"), for a calendar whose head names nothing."""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", str(name or "").replace("\\", "/").rsplit("/", 1)[-1])
    return " ".join(re.sub(r"[_]+", " ", stem).split())[:60]


# ---- words ----

STOP = {"and", "the", "for", "with", "part", "lecture", "lec", "week", "day", "read", "watch", "chapter", "unit",
        "video", "videos", "intro", "introduction", "review", "notes", "extra", "extras", "session", "class",
        "describe", "explain", "define", "list", "identify", "discuss", "compare", "contrast", "understand", "name",
        "outline", "apply", "relate", "recognize", "including", "between", "their", "they", "this", "that", "from",
        "into", "how", "why", "what", "which", "when", "only", "also", "make", "made", "role", "roles", "use", "used",
        "basic", "overview", "principles", "concepts", "objective", "objectives", "student", "students", "able",
        "will", "should", "each", "other", "these", "those", "its", "are", "was", "were", "has", "have", "can",
        "pages", "page", "book", "sketch", "sketches", "questions", "question", "small", "group", "case", "cases"}


def norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def words(s):
    """The words that name something: lowercase, no stop words, no numbers."""
    return [w for w in re.split(r"[^a-z0-9]+", norm(s)) if len(w) >= 3 and w not in STOP and not w.isdigit()]


def same(a, b):
    """"arrhythmia" and "arrhythmias", "cardiac" and "cardio": one word here
    (builder.js Suggest.same)."""
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if s == l or (len(s) >= 4 and l.startswith(s)):
        return True
    k = 0
    while k < len(s) and s[k] == l[k]:
        k += 1
    return k >= 5 and k >= 0.8 * len(s)


def _in(w, ws):
    return w in ws or any(same(w, x) for x in ws)


def hits(term, leaf, every):
    """A term names a tag: every word of it in the path, one in its last part."""
    return bool(term) and all(_in(w, every) for w in term) and any(_in(w, leaf) for w in term)


def terms_of(s, extra=()):
    """A session's terms, each a list of words: its title, what it lists, the
    abbreviations and long naming words of its objectives (BNP, natriuretic),
    and `extra` (the stand-in's own words, claude.py)."""
    out = []

    def put(t):
        w = words(t)
        if w and w not in out:
            out.append(w)
    lead = re.sub(r"[:(].*$", "", s.get("title") or "").strip()
    if len(words(lead)) <= 4:
        put(lead)
    else:
        ws = words(lead)
        for a, b in zip(ws, ws[1:]):
            put(f"{a} {b}")
    for x in s.get("listed") or []:
        put(re.sub(r"\b(?:pp?\.?|pages?)\s*[\d\s,–-]+", " ", x.get("text") or ""))
    slid = 0
    for t in s.get("slides") or []:  # a lecture's slides' titles (from_slides): what it covers
        ws = words(re.sub(r"[:(].*$", "", t))
        if not 1 <= len(ws) <= 4:
            continue
        before = len(out)
        put(" ".join(ws))
        if len(ws) >= 3:  # "acid base effects" names Acid_Base by its pair
            for a, b in zip(ws, ws[1:]):
                put(f"{a} {b}")
        slid += len(out) - before
        if slid >= 12:  # room left for the objectives' own words
            break
    text = " ".join(o.get("text") or "" for o in s.get("objectives") or [])
    for ab in re.findall(r"\b[A-Z][A-Za-z0-9]{1,5}\b", text):
        if len(ab) >= 3 and sum(c.isupper() for c in ab) >= 2:  # BNP, RAAS, HFrEF; not a capitalised word
            put(ab)
    own = set(words(s.get("title")))
    for w in sorted({w for w in words(text) if len(w) >= 7 and w not in own}):
        put(w)
    del out[24:]
    for t in extra:
        put(t)
    return out[:32]


# ---- the deck's tags ----

_TOKENS = ("#planner reading tokens",)  # kept with the index's searches
SKIP_ROOTS = ("duecrew", "leech", "marked")
NOTES_MAX = 600  # a tag holding more cards than this is too broad to be one session's


def tokens(idx):
    """([(path as written, leaf words, every word, depth)], {first four letters: {i}}):
    every tag path here (question numbers aside), read once a deck."""
    kept = idx._searches.get(_TOKENS)
    if kept is None:
        rows, by = [], {}
        for low, spelled, _w in M._paths(idx):
            if low.split(M.SEP)[0] in SKIP_ROOTS or low.startswith(SKIP_ROOTS):
                continue
            segs = spelled.split(M.SEP)
            leaf = words(M.label(segs[-1]))
            if not leaf:
                continue
            every = set(words(" ".join(M.label(x) for x in segs)))
            i = len(rows)
            rows.append((spelled, set(leaf), every, len(segs)))
            for w in leaf:
                by.setdefault(w[:4], set()).add(i)
        kept = (rows, by)
        idx._searches[_TOKENS] = kept
    return kept


def candidates(idx, s, extra=(), most=8):
    """The deck tags a session's words name, best first: [{tag, label, kind,
    group, score, title, cards, new}]. The title naming a tag counts most; a
    tag too broad to be one session's (NOTES_MAX), or holding the same cards
    as one already in, gives way; so does one inside one already in."""
    rows, by = tokens(idx)
    terms = terms_of(s, extra)
    title = words(re.sub(r"[:(].*$", "", s.get("title") or ""))
    maybe = set()
    for t in terms + [title]:
        for w in t:
            maybe |= by.get(w[:4], set())
    found = []
    for i in maybe:
        spelled, leaf, every, depth = rows[i]
        if depth < 2:
            continue
        got = [t for t in terms if hits(t, leaf, every)]
        th = hits(title, leaf, every) if len(title) <= 4 else False
        if not got and not th:
            continue
        cids = idx.tag_cards(spelled)
        if not cids or len(cids) > NOTES_MAX:
            continue
        found.append((2 * len(got) + (6 if th else 0), depth, spelled, th, cids))
    found.sort(key=lambda f: (-f[0], -f[1], len(f[4]), f[2].lower()))
    out = []
    for score, _depth, spelled, th, cids in found:
        if any(cids == o["_cids"] for o in out) or any(spelled.lower().startswith(o["tag"].lower() + M.SEP) for o in out):
            continue
        c = M.counts(idx, cids)
        group, _topic = M.split(spelled)
        out.append({"tag": spelled, "label": M.label(spelled), "kind": M.kind(spelled), "group": group,
                    "score": score, "title": th, "cards": c["cards"], "new": c["new"], "_cids": cids})
        if len(out) >= most:
            break
    return out


def nearby(idx, tags, most=120):
    """The tags beside these (the same parent: a block's other videos in
    Cardio when one is ticked), these left out; by path."""
    rows, _by = tokens(idx)
    have = {str(t).lower() for t in tags}
    parents = {t.rsplit(M.SEP, 1)[0] for t in have if M.SEP in t}
    out = [r[0] for r in rows if M.SEP in r[0] and r[0].lower().rsplit(M.SEP, 1)[0] in parents and r[0].lower() not in have]
    return sorted(out, key=str.lower)[:most]


def could_fit(idx, s, near=(), most=40):
    """The tags a job picking for this session would choose among
    (claude.py): its candidates, the tags whose last part starts as one of
    its words does ("antiarrhythmics" for "antiarrhythmic"), then `near`
    (nearby: beside what the block's other sessions have). [{tag, cards}]."""
    rows, by = tokens(idx)
    out = [c["tag"] for c in candidates(idx, s, most=most)]
    stems = {w[:5] for t in terms_of(s) for w in t if len(w) >= 5}
    for w in sorted(stems):
        for i in sorted(by.get(w[:4], ())):
            spelled, leaf, _every, depth = rows[i]
            if depth >= 2 and any(x.startswith(w) for x in leaf):
                out.append(spelled)
    out += list(near)
    seen, got = set(), []
    for t in out:
        if t.lower() in seen:
            continue
        cids = idx.tag_cards(t)
        if not cids or len(cids) > NOTES_MAX:
            continue
        seen.add(t.lower())
        got.append({"tag": t, "cards": len(cids)})
        if len(got) >= most:
            break
    return got


PICK_MIN = 6  # the title names it, or three of its terms do


def pick(cands, most=3):
    """Plain rules' pick: the tags the title names, or three of its terms do,
    at most one in each resource (the best), `most` in all. [index]."""
    out, groups = [], set()
    for i, c in enumerate(cands):
        if c["score"] < PICK_MIN or (c["group"], c["kind"]) in groups:
            continue
        out.append(i)
        groups.add((c["group"], c["kind"]))
        if len(out) >= most:
            break
    return out


# ---- what an exam covers ----

_RANGE = r"(\d{1,3})\s*(?:-|–|—|to|through|thru)\s*(\d{1,3})"
_WEEKS = re.compile(r"\bweeks?\s+" + _RANGE + r"|\bweeks?\s+(\d{1,2})\b", re.I)
_NUMBERED = re.compile(r"\b(?:lectures?|sessions?|lecs?)\s+" + _RANGE, re.I)
_DATES = re.compile(r"(" + _MON + r"\s+\d{1,2}|\d{1,2}/\d{1,2})\s*(?:-|–|—|to|through|thru)\s*(" + _MON + r"\s+\d{1,2}|\d{1,2}/\d{1,2})", re.I)
_UPTO = re.compile(r"\b(?:through|thru|up to|until)\s+(" + _MON + r"\s+\d{1,2}|\d{1,2}/\d{1,2})", re.I)


def scope(text, sessions, today, day_first=False):
    """What an exam covers, by plain rules: (the indexes of the sessions it
    covers, the parts of the text they couldn't place). Weeks ("weeks 1-3",
    "week 4"), numbered lectures ("lectures 1-12", the calendar's order),
    dates ("Oct 26 - Nov 13", "through Nov 13"). sessions: number_weeks'd."""
    text = str(text or "")
    lectures = [i for i, s in enumerate(sessions) if s["kind"] not in EVENT_KINDS]
    got, used = set(), []

    def mark(m):
        used.append((m.start(), m.end()))

    for m in _WEEKS.finditer(text):
        if _QUALIFIED.match(text, m.end()):
            continue  # "week 4's two pharm lectures": some of the week, not all of it (claude.py's job)
        a, b = (int(m.group(1)), int(m.group(2))) if m.group(1) else (int(m.group(3)), int(m.group(3)))
        got |= {i for i in lectures if a <= int(sessions[i].get("week") or 0) <= b}
        mark(m)
    for m in _NUMBERED.finditer(text):
        a, b = int(m.group(1)), int(m.group(2))
        got |= {i for n, i in enumerate(lectures, 1) if a <= n <= b}
        mark(m)
    for m in _DATES.finditer(text):
        a, b = parse_date(m.group(1), today, day_first)[0], parse_date(m.group(3), today, day_first)[0]
        if a and b:
            got |= {i for i in lectures if a.isoformat() <= sessions[i]["date"] <= b.isoformat()}
            mark(m)
    for m in _UPTO.finditer(text):
        if any(s <= m.start() < e for s, e in used):
            continue
        b = parse_date(m.group(1), today, day_first)[0]
        if b:
            got |= {i for i in lectures if sessions[i]["date"] <= b.isoformat()}
            mark(m)
    rest = text
    for s_, e in sorted(used, reverse=True):
        rest = rest[:s_] + " " + rest[e:]
    rest = _SAYS.sub(" ", rest)
    left = [" ".join(p.split()).strip(" .,;:") for p in re.split(r"\s*(?:,|;|\.\s|\band\b|\bplus\b)\s*", rest)]
    return sorted(got), [p for p in left if [w for w in words(p) if w not in _ALL]]


# "Exam 1 covers", "the quiz will be on": what an exam's line says before what it covers
_SAYS = re.compile(r"(?i)\b(?:(?:the\s+)?(?:exam|quiz|test|midterm|final|assessment)\s*\d*\s+)?"
                   r"(?:covers?|will\s+cover|is\s+on|will\s+be\s+on|includes?|material)\b")
# what an exam's line says of what it covers, not which: "everything through Nov 13"
_ALL = {"everything", "all", "material", "content", "covered", "topics", "lectures", "sessions", "classes", "stuff"}
# a week said with what of it: "week 4's two pharm lectures", "week 4 renal sessions"
_QUALIFIED = re.compile(r"(?i)(?:'s|’s)?\s+(?!and\b|or\b|plus\b|through\b|to\b)(?:[a-z0-9][\w-]*\s+){1,3}"
                        r"(?:lectures?|sessions?|classes|topics|talks)\b")
