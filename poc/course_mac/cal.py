"""A course calendar, read: dates in the ways schools write them, a plain
line reader for a calendar pasted as lines (no model needed), and the text
cut into pieces small enough for the Mac model's window. Pure."""

import datetime as dt
import re

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
_KIND_WORDS = [("exam", r"\b(exam|final|midterm|nbme|shelf|test)\b"), ("quiz", r"\b(quiz|ksa|irat|grat|assessment)\b"),
               ("lab", r"\b(lab|dissection|osce|clinical skills)\b")]
_SKIP = re.compile(r"\b(no class|holiday|break|vacation|day off)\b", re.I)
_OBJ = re.compile(r"^\s*(?:[-*•◦]\s*)?((?:SLG|LO|Obj(?:ective)?|Session objective)\s*[\w.-]*\d[\w.-]*|\d{1,2}[.)])\s*[:.)-]?\s+(.+)$", re.I)
_TIME = re.compile(r"^\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:[-–]\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?\s+", re.I)
_TAGGY = re.compile(r"^\s*(LEC|LECTURE|QUIZ|EXAM|LAB|SG|SMALL GROUP|CBL|TBL)\b[:.]?\s*", re.I)


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
                    y = y + 2000 if y < 100 else y
                    d = dt.date(y, mo, da)
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
    t = t[word.end():] if word else t
    t = re.sub(r"\s*\((?:dr|prof)\.?[^)]*\)\s*$", "", t, flags=re.I)  # "(Dr. Lee)"
    return re.sub(r"\s+", " ", t).strip(" -|:–")[:120]


def split_objective(line):
    """("SLG 12", "Describe …") or ("", "…") for a line under a session."""
    m = _OBJ.match(line)
    if m:
        label = m.group(1).strip().rstrip(".):")
        if re.fullmatch(r"\d{1,2}", label):
            label = ""
        return re.sub(r"\s+", " ", label), m.group(2).strip()
    s = re.sub(r"^\s*[-*•◦]\s*", "", line).strip()
    return "", s


def read_lines(text, today, day_first=False):
    """A calendar pasted as lines: each line that starts with a date is a
    session; the lines under it, its objectives. [session], where a session
    is {date, kind, title, objectives: [{label, text}]}. Breaks and holidays
    are left out."""
    out = []
    for raw in str(text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        d, rest = parse_date(line, today, day_first)
        if d:
            title = clean_title(rest)
            if not title or _SKIP.search(title):
                out.append(None)  # a date with nothing on it ends the last session's objectives
                continue
            tagged = _TAGGY.match(_TIME.sub("", rest.strip()))
            said = None
            if tagged:
                w = tagged.group(1).lower()
                said = "quiz" if w == "quiz" else "exam" if w == "exam" else "lab" if w == "lab" else "lecture"
            out.append({"date": d.isoformat(), "kind": kind_of(title, said), "title": title, "objectives": []})
            continue
        if out and out[-1] is not None:
            label, words = split_objective(line)
            if len(words) >= 8 and (label or raw[:1] in " \t" or re.match(r"^\s*[-*•◦\d]", raw)):
                out[-1]["objectives"].append({"label": label[:20], "text": words[:300]})
    return [s for s in out if s]


def chunks(text, size=1800):
    """The text in pieces of about `size` characters, each cut before a line
    that starts with a date where it can be, so a session and its objectives
    stay together."""
    lines = str(text or "").splitlines()
    out, cur, n = [], [], 0
    today = dt.date.today()
    for line in lines:
        starts = parse_date(line, today)[0] is not None
        if cur and n + len(line) > size and (starts or n > size * 1.5):
            out.append("\n".join(cur))
            cur, n = [], 0
        cur.append(line)
        n += len(line) + 1
    if cur and "".join(cur).strip():
        out.append("\n".join(cur))
    return out


def merge(sessions):
    """Sessions from several pieces, as one list by date: the same date and
    title is one session, its objectives together."""
    by, order = {}, []
    for s in sessions:
        k = (s["date"], s["title"].lower())
        if k not in by:
            by[k] = {**s, "objectives": list(s.get("objectives") or [])}
            order.append(k)
            continue
        have = {o["text"].lower() for o in by[k]["objectives"]}
        by[k]["objectives"] += [o for o in s.get("objectives") or [] if o["text"].lower() not in have]
    return sorted((by[k] for k in order), key=lambda s: s["date"])
