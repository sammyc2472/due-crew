"""Add to my calendar (3.9.6, Sam's pick): a plan's sets and its quizzes
and exams as a calendar file (.ics, RFC 5545) for Google, Apple or Outlook
calendars. Each set an all-day event on its days (a spread set from its
first day to its finish-by day), each quiz or exam an all-day event, each
review day one too. Names are the author's and the plan's; no card's text.
A follower's file has their own days (my shift, skips and moves). Pure."""

import datetime

PRODID = "-//Due Crew//Plans//EN"


def _esc(text):
    """A TEXT value: backslash, semicolon, comma and line breaks escaped."""
    t = str(text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return t.replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n")


def _fold(line):
    """Lines over 75 octets folded (a CRLF and a space), never inside a character."""
    out, cur = [], b""
    for ch in line:
        enc = ch.encode("utf-8")
        if len(cur) + len(enc) > (75 if not out else 74):
            out.append(cur)
            cur = b""
        cur += enc
    out.append(cur)
    return "\r\n ".join(x.decode("utf-8") for x in out)


def _day(iso):
    try:
        return datetime.date.fromisoformat(str(iso))
    except ValueError:
        return None


def _event(uid, stamp, first, last, summary, desc=""):
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
             f"DTSTART;VALUE=DATE:{first.strftime('%Y%m%d')}",
             f"DTEND;VALUE=DATE:{(last + datetime.timedelta(days=1)).strftime('%Y%m%d')}",
             f"SUMMARY:{_esc(summary)}", "TRANSP:TRANSPARENT"]
    if desc:
        lines.append(f"DESCRIPTION:{_esc(desc)}")
    lines.append("END:VEVENT")
    return lines


def calendar(pid, name, doc, counts=None, skipped=(), now=None):
    """The file's text. doc: the plan's (an author's) or mine (a follower's);
    counts: {set id: cards on it here}; skipped: the sets I skip (left out)."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    plan = " ".join(str(name or "Plan").split())
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{_esc(plan)}"]
    skip = set(skipped or ())
    for u in (doc or {}).get("units") or []:
        if not isinstance(u, dict) or u.get("id") in skip:
            continue
        first = _day(u.get("opens"))
        if first is None:
            continue
        last = _day(u.get("due")) if u.get("due") else first
        last = last if last and last >= first else first
        n = (counts or {}).get(u.get("id"))
        desc = f"{plan}" + (f" · {int(n):,} card{'s' if int(n) != 1 else ''}" if n else "")
        lines += _event(f"{pid}-{u.get('id')}@duecrew.com", stamp, first, last,
                        f"{u.get('name') or 'Set'} · {plan}", desc)
    for e in (doc or {}).get("events") or []:
        d = _day((e or {}).get("day"))
        if d is not None:
            lines += _event(f"{pid}-{e.get('id')}@duecrew.com", stamp, d, d, f"{e.get('name') or 'Exam'} · {plan}", plan)
    for r in (doc or {}).get("reviews") or []:
        d = _day((r or {}).get("day"))
        if d is not None:
            lines += _event(f"{pid}-r{d.strftime('%Y%m%d')}@duecrew.com", stamp, d, d, f"Review day · {plan}", plan)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in lines) + "\r\n"


def file_name(name):
    """A file name for the plan's calendar: its name, safe on every system."""
    safe = "".join(ch if ch.isalnum() or ch in " -_." else " " for ch in str(name or "Plan"))
    return (" ".join(safe.split())[:60] or "Plan") + ".ics"
