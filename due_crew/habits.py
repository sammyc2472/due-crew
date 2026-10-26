"""3.9.5, How you study (pure: no aqt; habits_flow is the glue). What my
own Anki log says about how I study, worked out on this computer and never
sent: no request, no account key, nothing on the server.

One read, the last WEEKS weeks of revlog over every deck, as rows
(id, cid, ease, ivl, lastIvl, time, type), oldest first. From it:

- My time (the view's head): minutes a studied day over the 28 days before
  today, and seconds a review answer, from revlog.time.
- Matured, the win: review answers that took a card from under 21 days to
  21 or more (Anki's own "mature"), this week and each of the eight.
- Slow but right: a right review answer that took 1.5 to 3 times the
  card's usual (the median of its right review answers, 3 or more; past 3
  it's left out: likely stepped away) against the quicker ones, by whether
  the card's next review answer was a miss. Held at the same intervals
  (bands by the answer's ivl, weighted as the slow ones fall), with a range
  from 300 resamples of cards (Random(7)). It shows only with 4 weeks of
  log, 1,500 right answers that have a next one, and the range's low end
  above zero. The headline is the raw miss rates, slow against the rest.
- Long sittings: a new sitting after a gap over 10 minutes. Right % of
  review answers by minutes in, each band re-weighted to the log's own
  interval mix (by the interval going in, lastIvl: a miss's new ivl would
  give it away); within sittings of an hour or more, 45 minutes in against
  the first 20, with a range from 300 resamples of sittings (Random(7)).
  It shows only with 20 such sittings, a drop of 3 points or more, and the
  range's high end below zero.
- The track record of Slow but right (studied: {card id: when it went into
  the deck, ms}): the ones studied (answered within LOOK_DAYS of going in),
  by their next review answer after that look, against the slow ones never
  studied. Said once 4 weeks have passed and 30 have had a next answer; if
  the studied ones aren't missed less, Study goes away.
"""

import datetime
import random
from collections import Counter

WEEKS = 8
DAY_MS = 86400000
MIN_MS = 60000
MATURE = 21                 # Anki's mature: next review 3 weeks or more away
BAND_EDGES = (7, 21, 61)    # interval bands: 1-6, 7-20, 21-60, 61+
QUICK_TO, SLOW_TO = 1.5, 3.0
USUAL_MIN = 3               # right review answers before a card has a usual
TIME_DAYS = 28              # the head's time, over the days before today
SLOW_DAYS = 7               # Slow but right: a right answer in the last 7 days
GAP_MS = 10 * MIN_MS        # a gap over this starts a new sitting
SIT_BINS = (15, 30, 45, 60, 90)  # minutes into a sitting: 0-15, 15-30, 30-45, 45-60, 60-90, 90+
BIN_MIN = 30                # answers before a bin of the curve is drawn
LONG_MIN, EARLY_MIN, LATE_MIN = 60, 20, 45
RESAMPLES, SEED, LO_AT, HI_AT = 300, 7, 7, 292
SPEED_DAYS, SPEED_N = 28, 1500
SIT_N, SIT_DROP = 20, 0.03
VIEW_DAYS = 14              # under two weeks of log, no How you study at all
SIT_AT = 35                 # the Fifteen at 35: minutes into a sitting
TRACK_DAYS, TRACK_N = 28, 30
LOOK_DAYS = 3               # a card studied: answered this soon after going into the deck
NEXT_UP_MIN = 10            # Today's Next up asks for this many slow ones
STUDY_MAX = 500             # cards a Slow but right deck takes, slowest first


def band(ivl):
    """0..3: an interval's band (1-6 days, 7-20, 21-60, 61+); under a day is the first."""
    ivl = int(ivl or 0)
    return sum(1 for e in BAND_EDGES if ivl >= e)


def days_ago(ms, cutoff):
    """The Anki day of a revlog time, as days before today (0: today), as
    leech_flow.anki_day counts it (the person's rollover, not midnight)."""
    return max(0, (int(cutoff) * 1000 - int(ms) - 1) // DAY_MS)


def today_of(cutoff):
    """Today's Anki day, as a date."""
    return datetime.date.fromtimestamp(int(cutoff)) - datetime.timedelta(days=1)


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    if not n:
        return 0
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _rate(miss, n):
    return miss / n if n else None


# ---- the ranges: resamples of whole cards, or whole sittings ----

def resample(vecs, stat, seed=SEED, times=RESAMPLES):
    """(low, high): `stat` of the summed cells over `times` resamples of the
    clusters (cards, or sittings) with replacement, sorted, at LO_AT and
    HI_AT (about 2.5% and 97.5%). vecs: each cluster's cells, sparse
    [(cell, value)]. None when a resample has nothing to say. Clusters
    alike are drawn as one kind, so it's quick on a big log."""
    if not vecs:
        return None
    kinds, ids = {}, []
    for v in vecs:
        ids.append(kinds.setdefault(tuple(v), len(kinds)))
    rows = list(kinds)
    width = 1 + max((c for v in rows for c, _x in v), default=0)
    rng = random.Random(seed)
    out = []
    m = len(ids)
    for _ in range(times):
        tot = [0] * width
        for k, mult in Counter(rng.choices(ids, k=m)).items():
            for c, x in rows[k]:
                tot[c] += mult * x
        g = stat(tot)
        if g is None:
            return None
        out.append(g)
    out.sort()
    return out[LO_AT], out[HI_AT]


def _sparse(cells):
    return [(i, x) for i, x in enumerate(cells) if x]


def matched_gap(tot):
    """Group 1's rate minus group 0's, band by band, weighted as group 1
    falls (bands with both only); None with no such band. tot: 16 cells,
    band b and group g at 4b+2g (how many) and 4b+2g+1 (how many of them
    count). Speed: group 1 the slow right answers, 0 the quicker; counted,
    a miss next time. Sittings: group 1 from 45 minutes in, 0 the first 20;
    counted, right."""
    use = [b for b in range(4) if len(tot) > 4 * b + 3 and tot[4 * b + 2] and tot[4 * b]]
    w = sum(tot[4 * b + 2] for b in use)
    if not w:
        return None
    return sum(tot[4 * b + 2] / w * (tot[4 * b + 3] / tot[4 * b + 2] - tot[4 * b + 1] / tot[4 * b]) for b in use)


# ---- the whole log, once a day ----

def work_out(rows, cutoff, studied=None):
    """Everything How you study says, from the log (rows oldest first) and
    the Slow but right decks built ({card id: ms}). Plain values only."""
    cutoff = int(cutoff)
    studied = {int(k): int(v) for k, v in (studied or {}).items()}
    now_ms = cutoff * 1000
    weeks = [set() for _ in range(WEEKS)]
    t_ms, t_days, r_ms, r_n = 0, set(), 0, 0
    first = None
    by_card = {}       # cid: [(id, ease, ivl, time)], its review answers
    every = {}         # a studied card's answers: [(id, ease, type)]
    sits, cur = [], None
    for row in rows:
        i, cid, ease, ivl, last, t, ty = (int(x or 0) for x in row[:7])
        if ease <= 0:
            continue  # a reschedule, not an answer
        d = days_ago(i, cutoff)
        if d >= WEEKS * 7:
            continue
        first = d if first is None else max(first, d)
        t = max(0, t)
        if 1 <= d <= TIME_DAYS:
            t_ms += t
            t_days.add(d)
            if ty == 1:
                r_ms += t
                r_n += 1
        if ty == 1:
            by_card.setdefault(cid, []).append((i, ease, ivl, t))
            if last < MATURE <= ivl:
                weeks[d // 7].add(cid)
        if cid in studied:
            every.setdefault(cid, []).append((i, ease, ty))
        # sittings: every answer, a gap over 10 minutes starts one
        if cur is None or i - cur["last"] > GAP_MS:
            cur = {"start": i - min(t, GAP_MS), "last": i, "rev": []}
            sits.append(cur)
        cur["last"] = i
        if ty == 1:
            cur["rev"].append(((i - cur["start"]) / MIN_MS, band(last), ease > 1))
    span = 0 if first is None else first + 1
    today = today_of(cutoff)
    out = {"day": cutoff, "span": span,
           "mins": t_ms / MIN_MS / len(t_days) if t_days else None,
           "secs": r_ms / 1000 / r_n if r_n else None,
           "matured": {"n": len(weeks[0]), "weeks": [len(w) for w in reversed(weeks)],
                       "from": [(today - datetime.timedelta(days=7 * k + 6)).isoformat() for k in reversed(range(WEEKS))],
                       "cids": sorted(weeks[0])}}
    out.update(_speed(by_card, cutoff, span, studied, every, now_ms))
    out["sit"] = _sittings(sits)
    return out


def _speed(by_card, cutoff, span, studied, every, now_ms):
    """The speed finding, Slow but right's cards, and its track record."""
    vecs, tot = [], [0] * 16
    rest_n = rest_miss = 0
    slow, slow_at = [], {}
    for cid, xs in by_card.items():
        rights = [t for _i, e, _v, t in xs if e > 1]
        if len(rights) < USUAL_MIN:
            continue
        usual = median(rights)
        if usual <= 0:
            continue
        cells = [0] * 16
        for k in range(len(xs) - 1):
            _i, e, ivl, t = xs[k]
            if e <= 1:
                continue
            ratio = t / usual
            if ratio >= SLOW_TO:
                continue  # likely stepped away
            c = 4 * band(ivl) + (2 if ratio >= QUICK_TO else 0)
            cells[c] += 1
            cells[c + 1] += xs[k + 1][1] == 1
        if any(cells):
            vecs.append(_sparse(cells))
            for j, x in enumerate(cells):
                tot[j] += x
            if cid not in studied:
                rest_n += sum(cells[4 * b + 2] for b in range(4))
                rest_miss += sum(cells[4 * b + 3] for b in range(4))
        # Slow but right: the card's latest review answer, in the last 7 days, right and slow
        i, e, _v, t = xs[-1]
        ratio = t / usual
        if e > 1 and days_ago(i, cutoff) < SLOW_DAYS and QUICK_TO <= ratio < SLOW_TO:
            slow.append((-ratio, cid))
            slow_at[cid] = i
    n_slow = sum(tot[4 * b + 2] for b in range(4))
    n_quick = sum(tot[4 * b] for b in range(4))
    out = {"slow": [c for _r, c in sorted(slow)], "slow_at": slow_at, "speed": None, "track": None}
    if n_slow and n_quick:
        gap = matched_gap(tot)
        rng = resample(vecs, matched_gap) if gap is not None else None
        out["speed"] = {
            "slow": sum(tot[4 * b + 3] for b in range(4)) / n_slow,
            "quick": sum(tot[4 * b + 1] for b in range(4)) / n_quick,
            "n_slow": n_slow, "n_quick": n_quick, "n": n_slow + n_quick, "gap": gap,
            "lo": rng[0] if rng else None, "hi": rng[1] if rng else None,
            "pass": bool(span >= SPEED_DAYS and n_slow + n_quick >= SPEED_N and rng and rng[0] > 0)}
    out["track"] = track(studied, every, by_card, rest_n, rest_miss, now_ms)
    return out


def track(studied, every, by_card, rest_n, rest_miss, now_ms):
    """Slow but right's track record: the cards studied (answered within
    LOOK_DAYS of going into the deck), each by its next review answer after
    that look, against the slow right answers of cards never studied. None
    before anything was studied."""
    if not studied:
        return None
    n = miss = 0
    for cid, at in studied.items():
        xs = every.get(cid) or []
        look = next((i for i, _e, _ty in xs if at <= i < at + LOOK_DAYS * DAY_MS), None)
        if look is None:
            continue
        nxt = next((e for i, e, _v, _t in by_card.get(cid) or [] if i > look), None)
        if nxt is None:
            continue
        n += 1
        miss += nxt == 1
    ready = bool(now_ms - min(studied.values()) >= TRACK_DAYS * DAY_MS and n >= TRACK_N and rest_n)
    mine, rest = _rate(miss, n), _rate(rest_miss, rest_n)
    return {"n": n, "studied": mine, "rest": rest, "rest_n": rest_n, "ready": ready,
            "against": bool(ready and mine is not None and rest is not None and mine >= rest)}


def _bin(minutes):
    return sum(1 for e in SIT_BINS if minutes >= e)


def _sittings(sits):
    """The curve (right % by minutes in, each bin weighted to the log's
    interval mix) and the long sittings' gap with its range."""
    n = [[0] * 4 for _ in range(len(SIT_BINS) + 1)]
    r = [[0] * 4 for _ in range(len(SIT_BINS) + 1)]
    vecs, longs = [], 0
    for s in sits:
        cells = [0] * 16
        long_ = (s["last"] - s["start"]) / MIN_MS >= LONG_MIN
        for m, b, ok in s["rev"]:
            k = _bin(m)
            n[k][b] += 1
            r[k][b] += ok
            if long_ and (m < EARLY_MIN or m >= LATE_MIN):
                c = 4 * b + (2 if m >= LATE_MIN else 0)
                cells[c] += 1
                cells[c + 1] += ok
        if long_:
            longs += 1
            vecs.append(_sparse(cells))
    total = sum(sum(x) for x in n)
    if not total:
        return None
    mix = [sum(n[k][b] for k in range(len(n))) / total for b in range(4)]
    curve = []
    edges = (0,) + SIT_BINS + (None,)
    for k in range(len(n)):
        nn = sum(n[k])
        val = None
        if nn >= BIN_MIN:
            w = sum(mix[b] for b in range(4) if n[k][b])
            val = 100 * sum(mix[b] / w * r[k][b] / n[k][b] for b in range(4) if n[k][b]) if w else None
        curve.append([edges[k], edges[k + 1], val, nn])
    tot = [0] * 16
    for v in vecs:
        for c, x in v:
            tot[c] += x
    gap = matched_gap(tot) if vecs else None
    rng = resample(vecs, matched_gap) if gap is not None else None
    ok = bool(longs >= SIT_N and gap is not None and gap <= -SIT_DROP + 1e-9 and rng and rng[1] < 0
              and curve[0][2] is not None and curve[2][2] is not None)
    return {"curve": curve, "gap": gap, "lo": rng[0] if rng else None, "hi": rng[1] if rng else None,
            "n": longs, "pass": ok}


# ---- what the board draws ----

def summary(res, study=0):
    """The view's shape (board._habits_html) from a worked-out log: a
    finding only when it passes. study: the Slow but right cards there are
    now (habits_flow, as the collection is); 0 when Study goes away."""
    sp, sit, tr = res.get("speed") or {}, res.get("sit") or {}, res.get("track") or {}
    out = {"mins": res.get("mins"), "secs": res.get("secs"), "span": int(res.get("span") or 0),
           "matured": {k: res["matured"][k] for k in ("n", "weeks", "from")}, "speed": None, "sit": None,
           "study": 0, "track": None}
    if sp.get("pass"):
        out["speed"] = {k: sp[k] for k in ("slow", "quick", "gap", "lo", "hi", "n_slow", "n_quick")}
        out["study"] = 0 if tr.get("against") else int(study or 0)
        if tr.get("ready"):
            out["track"] = {"studied": tr["studied"], "rest": tr["rest"], "n": tr["n"]}
    if sit.get("pass"):
        out["sit"] = {"curve": sit["curve"], "from": sit["curve"][0][2], "to": sit["curve"][2][2], "gap": sit["gap"],
                      "lo": sit["lo"], "hi": sit["hi"], "n": sit["n"]}
    return out


def fold_sitting(s, rows):
    """The sitting going on: [start, last answer] (ms) after these answers
    (id, time), oldest first; s, as it was (None: none yet). A gap over 10
    minutes starts a new one."""
    for i, t in rows:
        i, t = int(i), max(0, int(t or 0))
        if s is None or i - s[1] > GAP_MS:
            s = [i - min(t, GAP_MS), i]
        else:
            s = [s[0], max(s[1], i)]
    return s


def sit_due(s, now_ms, floor=0, dismissed=None):
    """Whether the Fifteen at 35 says so now: the sitting s ([start, last])
    still going (its last answer 10 minutes ago at most), past SIT_AT
    minutes since it began or since the last Fifteen or room (floor), and
    not waved off in this sitting."""
    if not s or now_ms - s[1] > GAP_MS or (dismissed is not None and dismissed == s[0]):
        return False
    return s[1] - max(s[0], int(floor or 0)) >= SIT_AT * MIN_MS
