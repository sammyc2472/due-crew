"""3.7.3 a plan's team and its Insights, the pure parts (team_flow.py is the
glue). Insights: this plan's cards I missed in the last 14 days, by the
topic they share (a tag under its resource, read as words, as `plans.topics`
names it), with the 14 days before as the trend. Worked out in my Anki from
my own reviews; nothing about it leaves this computer."""

from . import plans as P

DAYS = 14          # the window; the trend compares it with the 14 before
MIN_CARDS = 5      # a topic shows with this many cards reviewed in the window
TREND_POINTS = 10  # this many points of share missed, either way, is a trend
ROWS = 6
NAME_MAX = 60


def topic_list(doc):
    """[(key, name, [resources], [plan tags], [unit ids])] for a plan's tags,
    one per topic: a tag's last part read as words, merged across resources
    ("Complement" from a video series and from a book is one topic)."""
    out = {}
    for u in P.units(doc):
        for t in u.get("tags") or []:
            segs = str(t).split(P._SEP)
            ri = next((i for i, x in enumerate(segs) if i > 0 and x[:1] in "#^"), -1)
            res = P._word(segs[ri]) if 0 <= ri < len(segs) - 1 else ""
            name = P._word(segs[-1])[:NAME_MAX]
            if not name:
                continue
            key = name.lower()
            k = out.setdefault(key, [key, name, [], [], []])
            if res and res not in k[2]:
                k[2].append(res)
            if t not in k[3]:
                k[3].append(t)
            if u["id"] not in k[4]:
                k[4].append(u["id"])
    return [tuple(v) for v in out.values()]


def card_windows(answers):
    """{cid: [reviewed, missed, reviewed before, missed before]} from
    [(cid, days_ago, ease)] review answers (learning steps left out by the
    caller). Cards, not presses: a card missed three times is one miss."""
    out = {}
    for cid, ago, ease in answers:
        ago = int(ago)
        if ago < 0 or ago >= 2 * DAYS:
            continue
        w = out.setdefault(int(cid), [0, 0, 0, 0])
        k = 0 if ago < DAYS else 2
        w[k] = 1
        if int(ease) == 1:
            w[k + 1] = 1
    return out


def insights(topics, cards_of, answers, todo_of=None):
    """The table, worst first: [{key, name, sub, missed, of, trend, cids,
    url}]. topics: topic_list; cards_of(tag) is the set of my cards under a
    plan tag; answers as card_windows takes them; todo_of(unit id) its
    author's lines, for Re-watch. trend: "worse", "better", "steady", or ""
    when either window is too thin to say."""
    win = card_windows(answers)
    rows = []
    for key, name, res, tags, uids in topics:
        cids = set()
        for t in tags:
            cids |= set(cards_of(t))
        a_rev = [c for c in cids if c in win and win[c][0]]
        if len(a_rev) < MIN_CARDS:
            continue
        missed = [c for c in a_rev if win[c][1]]
        if not missed:
            continue
        b_rev = [c for c in cids if c in win and win[c][2]]
        trend = ""
        if len(b_rev) >= MIN_CARDS:
            now = 100 * len(missed) / len(a_rev)
            before = 100 * sum(1 for c in b_rev if win[c][3]) / len(b_rev)
            trend = "worse" if now - before >= TREND_POINTS else "better" if before - now >= TREND_POINTS else "steady"
        url = ""
        for uid in reversed(uids):
            for line in (todo_of(uid) if todo_of else None) or []:
                if line.get("k") == "watch" and str(line.get("url") or "").startswith("https://"):
                    url = str(line["url"])
                    break
            if url:
                break
        rows.append({"key": key, "name": name, "sub": " · ".join(res), "missed": len(missed), "of": len(a_rev),
                     "trend": trend, "cids": sorted(missed), "url": url})
    rows.sort(key=lambda r: (-r["missed"] / r["of"], -r["missed"], r["name"].lower()))
    return rows[:ROWS]


# ---- the team ----

def unread(summary, seen):
    """How many of the team's threads moved since I last looked."""
    return sum(1 for a in (summary or {}).get("act") or [] if int(a) > int(seen or 0))


CELLS = (0, 1, 2, 3, 5, 6, 7, 8)
LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))


def bingo_line(ev):
    """"3 of 9 · one away from bingo", from the team card's counts."""
    def done(c):
        return ev["middle"]["done"] if c == 4 else ev["squares"][CELLS.index(c)]["done"]
    stamps = sum(1 for q in ev["squares"] if q["done"]) + (1 if ev["middle"]["done"] else 0)
    lines = int(ev.get("lines") or 0)
    if lines >= 8:
        state = "the whole card"
    elif lines:
        state = "BINGO" if lines == 1 else f"{lines} lines"
    else:
        left = min(sum(1 for c in line if not done(c)) for line in LINES)
        state = "one away from bingo" if left == 1 else f"{left} away from bingo"
    return f"{stamps} of 9 · {state}"


def closest(card, ev):
    """The names of the cells closest to a line (bingo.closest, on counts)."""
    def done(c):
        return ev["middle"]["done"] if c == 4 else ev["squares"][CELLS.index(c)]["done"]
    best = min(LINES, key=lambda line: sum(1 for c in line if not done(c)))
    return [card["middle"]["name"] if c == 4 else card["squares"][CELLS.index(c)]["title"] for c in best if not done(c)]
