"""3.9.2, Reviews ahead (Sam's picks, 18 Oct): what the next six weeks ask
of a deck, in cards a day as Anki counts them (each card once a day),
counted from my own review log, never a model. Mine alone: worked out in
my Anki, never sent.

Three parts, each read from what Anki already holds:
  1. the cards I've started: each one's next due day (the cards table),
     then what follows it by how my own reviews have gone at its interval
     (how often I miss, how far a pass pushes the next one, where a miss
     lands), counted from my last LOOK days;
  2. the cards I'll start: my own curve, how many times a card I started
     came back each day after (the cards I started 6 to 17 weeks ago), or
     a typical one (GENERIC) until I have COHORT of them;
  3. when I'll start them (starts): as I have been, the last four weeks,
     each weekday its own share (a lecture unlocked on Mondays arrives on
     Mondays: most people start new cards in batches, not 20 a day), never
     more than the deck's new cards left; a plan's dates when I follow
     one; with a stop (my choice, or the pause I asked for) none on its days.
On simulated learners it came within about 10% six weeks out, where the
due-only count (Anki's Future Due) misses half by week two; backtest()
checks it on my own past, and its error is the band each bar's tip gives.

Pure: rows in, numbers out. Days are offsets from today (0), as the Anki
day (the rollover) counts them. A log row is (day, cid, ease, ivl,
lastIvl, type), as Anki's revlog has them (ivl < 0: seconds, a step)."""

import heapq
from collections import defaultdict

H = 42          # six weeks: 14 days by day, then 4 weeks by week
BY_DAY = 14
LOOK = 120      # days of my answers the habits and the curve are counted from
COHORT = 60     # cards I started 6 to 17 weeks ago before the curve is mine
PACE_DAYS = 28  # the starts I've made lately, the pace a choice keeps
BACK = (42, 56, 70)  # the past days backtest() forecasts from
BUCKETS = (1, 3, 7, 15, 30, 60, 120, 10 ** 6)  # a card's last interval, up to
CLIMB = 1.25    # the board's line: the next two weeks a quarter over this one...
CLIMB_MIN = 20  # ...and this many cards a day more
STOP_BEFORE = 7  # "Stop new a week before the exam"
BACK_MIN = 100  # cards started before a past day for backtest() to forecast from it
CAUSE_MIN = 200  # the board's line names new cards as the climb's cause: this many in two weeks...
CAUSE_X = 2      # ...and this many times the two weeks before
# a typical new card's next six weeks (simulated learners on FSRS's
# defaults at 90%, smoothed): the share seen on each day after it starts,
# and the answers each took (its learning steps on day 0)
GENERIC = ((1.0, 0.336, 0.15, 0.338, 0.446, 0.27, 0.1, 0.062, 0.104, 0.173, 0.133, 0.066, 0.054, 0.058,
            0.058, 0.049, 0.046, 0.077, 0.174, 0.22, 0.134, 0.07, 0.065, 0.065, 0.083, 0.08, 0.049, 0.036,
            0.04, 0.044, 0.047, 0.045, 0.04, 0.039, 0.038, 0.033, 0.029, 0.029, 0.032, 0.032, 0.034, 0.037),
           (2.312, 0.404, 0.179, 0.383, 0.502, 0.305, 0.114, 0.071, 0.117, 0.194, 0.15, 0.074, 0.061, 0.067,
            0.066, 0.056, 0.051, 0.086, 0.195, 0.245, 0.15, 0.08, 0.074, 0.073, 0.093, 0.089, 0.055, 0.041,
            0.045, 0.05, 0.053, 0.051, 0.045, 0.044, 0.043, 0.038, 0.033, 0.033, 0.036, 0.036, 0.038, 0.043), 0)
_DEFAULT = (0.1, (1.8, 2.5, 3.4), 1)  # a bucket with nothing to go on: 10% missed, its push, a day


def _b(ivl):
    for i, top in enumerate(BUCKETS):
        if ivl <= top:
            return i
    return len(BUCKETS) - 1


def curve(log, first, T=0, h=H, lo=LOOK, need=COHORT):
    """(cards, answers, n): of the n cards I started between T-lo and T-h,
    the share seen k days after it started (k < h), and the answers each
    took; None with fewer than `need`. first: {cid: the day it started}."""
    cohort = {cid for cid, f in first.items() if T - lo <= f <= T - h}
    if len(cohort) < need:
        return None
    seen, ans = [set() for _ in range(h)], [0] * h
    for day, cid, ease, *_ in log:
        if ease > 0 and cid in cohort:
            k = day - first[cid]
            if 0 <= k < h:
                seen[k].add(cid)
                ans[k] += 1
    n = len(cohort)
    return [len(s) / n for s in seen], [a / n for a in ans], n


def _thirds(xs):
    """A pass's push as three equally likely values (each third's middle)."""
    if len(xs) < 30:
        return None
    xs = sorted(xs)
    return tuple(xs[int(len(xs) * q)] for q in (1 / 6, 1 / 2, 5 / 6))


def habits(log, T=0, lo=LOOK):
    """({bucket: (missed, a pass's push, where a miss lands)}, extra answers
    after a miss), from my review answers between T-lo and T. A bucket with
    too little to go on takes the one before it's."""
    miss, tot = defaultdict(int), defaultdict(int)
    grow, land = defaultdict(list), defaultdict(list)
    extra = []
    by_card = defaultdict(list)
    for row in log:
        if T - lo <= row[0] < T and row[2] > 0:
            by_card[row[1]].append(row)
    for rows in by_card.values():
        rows.sort()
        for i, (_day, _cid, ease, ivl, last, typ) in enumerate(rows):
            if typ != 1 or last <= 0:
                continue
            b = _b(last)
            tot[b] += 1
            if ease == 1:
                miss[b] += 1
                k = 0
                if ivl > 0:
                    land[b].append(ivl)  # no relearning steps
                else:
                    for nxt in rows[i + 1:]:
                        if nxt[5] != 2:
                            break
                        k += 1
                        if nxt[3] > 0:
                            land[b].append(nxt[3])
                            break
                extra.append(k)
            elif ivl > 0:
                grow[b].append(ivl / last)
    out, last = {}, _DEFAULT
    for b in range(len(BUCKETS)):
        p = miss[b] / tot[b] if tot[b] >= 20 else None
        g = _thirds(grow[b])
        ls = sorted(land[b])
        lnd = ls[len(ls) // 2] if ls else None
        last = (last[0] if p is None else p, last[1] if g is None else g, last[2] if lnd is None else lnd)
        out[b] = last
    return out, (sum(extra) / len(extra) if extra else 1.0)


def existing(state, hab, extra, h=H, cut=1e-3):
    """(cards, answers) a day, the next h days, from the cards I've started:
    state [(due day, interval)], an overdue one due today. Each day's cards
    go on by my habits at their interval: a pass to one of three pushes, a
    miss to where my misses land."""
    groups = defaultdict(float)
    for due, ivl in state:
        groups[(max(int(due), 0), max(1, int(ivl)))] += 1.0
    heap = list(groups)
    heapq.heapify(heap)
    cards, answers = [0.0] * h, [0.0] * h
    while heap:
        d, ivl = heapq.heappop(heap)
        w = groups.pop((d, ivl), 0.0)
        if w <= 0 or d >= h:
            continue
        p, g, lnd = hab[_b(ivl)]
        cards[d] += w
        answers[d] += w * (1 + p * extra)
        nexts = [(max(ivl + 1, int(round(ivl * gx))), w * (1 - p) / len(g)) for gx in g]
        nexts.append((max(1, int(lnd)), w * p))
        for ni, nw in nexts:
            nd = d + ni
            if nw > cut and nd < h:
                if (nd, ni) not in groups:
                    heapq.heappush(heap, (nd, ni))
                groups[(nd, ni)] += nw
    return cards, answers


def with_new(started, cv, starts, h=H):
    """{cards, answers, started, new}: a day's cards (each once) and answers
    the next h days: `started` (existing()'s (cards, answers)) and the
    cards I'll start (starts[d] on day d), each by the curve cv."""
    ex_c, ex_a = started
    c_cards, c_ans = cv[0], cv[1]
    new_c, new_a = [0.0] * h, [0.0] * h
    for s in range(h):
        k_ = starts[s] if s < len(starts) else 0
        if not k_:
            continue
        for k in range(h - s):
            new_c[s + k] += k_ * c_cards[k]
            new_a[s + k] += k_ * c_ans[k]
    return {"cards": [a + b for a, b in zip(ex_c, new_c)], "answers": [a + b for a, b in zip(ex_a, new_a)],
            "started": list(ex_c), "new": new_c}


def forecast(log, first, state, starts, T=0, h=H, generic=GENERIC):
    """with_new's, from the log (habits, my curve: `own` when it's mine,
    else GENERIC's), the cards I've started as of day T, and starts."""
    cv = curve(log, first, T, h)
    hab, extra = habits(log, T)
    return dict(with_new(existing(state, hab, extra, h), cv or generic, starts, h), own=cv is not None)


# ---- when I'll start new cards ----

def pace(first, wd0, days=PACE_DAYS):
    """New cards I start a day, by weekday ([7], Monday first), from what I
    started the last `days` days (fewer when the deck is newer, a week at
    least): a batch I unlock on Mondays lands on Mondays. wd0: today's
    weekday. Today's own starts aren't in it (the day isn't over)."""
    begun = min(first.values()) if first else 0
    span = max(7, min(days, -begun)) if first else days
    count, times = [0] * 7, [0] * 7
    for d in range(-span, 0):
        times[(wd0 + d) % 7] += 1
    for f in first.values():
        if -span <= f < 0:
            count[(wd0 + f) % 7] += 1
    return [count[i] / times[i] if times[i] else 0.0 for i in range(7)]


def starts(rate, wd0, left, h=H, stop=None, today_done=0, plan=None, pool=None):
    """New cards started each day, the next h days: rate[weekday] a day
    (pace), today less what I've started already, never more than `left`
    in all (the deck's new cards, unlocked or not). stop: (first, last) day
    with none. plan: {day: cards} a plan opens on its dates, started that
    day; then only the `pool` already unlocked goes at my pace. A plan's
    date inside a stop still opens: its cards join the pool, for after."""
    out, budget = [0.0] * h, float(max(0, left))
    drain = float(max(0, pool if plan is not None and pool is not None else left))
    for d in range(h):
        if stop and stop[0] <= d <= stop[1]:
            if plan is not None:  # its date still opens; the cards wait, unlocked, for after
                drain += float((plan or {}).get(d) or 0)
            continue
        n = rate[(wd0 + d) % 7] - (today_done if d == 0 else 0)
        n = max(0.0, min(n, drain))
        drain -= n
        if plan is not None:
            n += float((plan or {}).get(d) or 0)
        n = min(n, budget)
        budget -= n
        out[d] = n
    return out


def choices(exam_in, rate, unlocked, left, h=H):
    """The ways the next six weeks could go, as the section's pills show
    them: [(key, stop)]. Always "pace" (as I have been). With an exam in
    STOP_BEFORE+1..h-1 days, "week" (none its last STOP_BEFORE days);
    "now" (none from today, to the exam or for good). "unlocked" (only
    what's unlocked, no more batches) when there's no exam and the unlocked
    run out within two weeks at my pace."""
    out = [("pace", None)]
    weekly = sum(rate)
    # 3.9.2's audit: an exam today is no exam ahead (a stop "to the exam" would end tonight)
    if exam_in is not None and 1 <= exam_in < h:
        if exam_in > STOP_BEFORE:
            out.append(("week", (exam_in - STOP_BEFORE, exam_in)))
        out.append(("now", (0, exam_in)))
    else:
        if weekly and unlocked < weekly * 2 and unlocked < left:
            out.append(("unlocked", None))
        out.append(("now", (0, h)))
    return out


# ---- the past, against the forecast ----

def state_at(log, first, now, T, gone=()):
    """Each card I'd started by day T as (due day, interval) then, from the
    log: its last answer before T; else (nothing that early in the log) the
    first one after it says when it was due and at what interval; else the
    card as it is now (now: {cid: (due, ivl)}), untouched since. A card
    reset last (Forget) is new again; gone (suspended now, unanswered since
    T) is left out."""
    before, after = {}, {}
    for row in log:
        cid = row[1]
        if row[0] < T:
            if cid not in before or row[0] >= before[cid][0]:
                before[cid] = row
        elif cid not in after or row[0] < after[cid][0]:
            after[cid] = row
    out = []
    for cid, f in first.items():
        if f >= T or (cid in gone and cid not in after):
            continue
        r = before.get(cid)
        if r is not None:
            day, _c, ease, ivl, _l, typ = r
            if typ == 3 and ivl == 0:
                continue
            if ease == 0:
                if ivl > 0:
                    out.append((day + ivl - T, ivl))
                continue  # Forget: a new card again
            out.append(((day + ivl - T, ivl) if ivl > 0 else (day + 1 - T, 1)))
            continue
        r = after.get(cid)
        if r is not None:
            if r[5] == 1 and r[4] > 0:
                out.append((r[0] - T, r[4]))
            continue
        if cid in now:
            due, ivl = now[cid]
            out.append((due - T, ivl))
    return out


def backtest(log, first, now, gone=(), back=BACK, h=H):
    """[(what I did, what it said)] weekly, cards a day, from each past day
    T = -b in back: forecast with only what came before T (its starts what
    I really started), against what I really did: the forecast as it would
    have run then, the typical curve where mine wasn't old enough yet (3.9.2,
    Sam's deck: a deck under 12 weeks had no track record at all). A day
    with fewer than BACK_MIN cards started before it is left out. log
    reaches back to min(T) - LOOK at least."""
    out = []
    for b in back:
        T = -b
        if T + h > 0 or sum(1 for f in first.values() if f < T) < BACK_MIN:
            continue
        past = [r for r in log if r[0] < T]
        st = [0] * h
        for f in first.values():
            if T <= f < T + h:
                st[f - T] += 1
        f = forecast(past, first, state_at(log, first, now, T, gone), st, T, h)
        did = [set() for _ in range(h)]
        for day, cid, ease, *_ in log:
            if ease > 0 and T <= day < T + h:
                did[day - T].add(cid)
        wk = lambda xs: [sum(xs[i:i + 7]) / 7 for i in range(0, h, 7)]  # noqa: E731
        out.append((wk([len(s) for s in did]), wk(f["cards"])))
    return out


def trust(results):
    """(mean error, [error by week]) of a backtest, each week's |off| over
    what I did, averaged over its days; None with fewer than two."""
    if len(results) < 2:
        return None
    weeks = len(results[0][0])
    # 3.9.2's audit: a week I took off (after a block exam) is a whole miss, not 400% of one
    by = [sum(min(1.0, abs(f[w] - a[w]) / max(1.0, a[w])) for a, f in results) / len(results) for w in range(weeks)]
    return sum(by) / weeks, by


# ---- what Insights and the board say ----

def r(x):
    """A number as the chart says it: about, never more exact than it is."""
    x = float(x)
    if x < 30:
        return int(round(x))
    if x < 200:
        return int(round(x / 5.0) * 5)
    return int(round(x / 10.0) * 10)


def _mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def peak(cards, lo=1, hi=BY_DAY):
    """(day, cards a day) of the busiest three days running, lo..hi-1, by
    their middle day."""
    best = None
    for d in range(lo, min(hi, len(cards))):
        win = cards[max(lo, d - 1):min(hi, d + 2)]
        v = _mean(win)
        if best is None or v > best[1]:
            best = (d, v)
    return best


def climb(past, cards):
    """The board's line: (day, cards a day) when the next two weeks' busiest
    three days run CLIMB times this week's (past: the last seven days'
    cards) and CLIMB_MIN more; else None."""
    week = _mean(past)
    p = peak(cards)
    if not past or p is None:
        return None
    if p[1] >= week * CLIMB and p[1] - week >= CLIMB_MIN:
        return p
    return None


def cause(new14, before14):
    """The cards I started the last two weeks when they're the climb's
    likely cause (CAUSE_MIN at least, CAUSE_X times the two weeks before),
    else 0. 3.9.2, Sam's deck: 2,480 against 262."""
    new14, before14 = int(new14 or 0), int(before14 or 0)
    return new14 if new14 >= CAUSE_MIN and new14 >= CAUSE_X * before14 else 0


def weeks(xs, lo=BY_DAY, h=H):
    """The by-week part: each week's average day, days lo..h-1."""
    return [_mean(xs[i:i + 7]) for i in range(lo, h, 7)]


def stop_of(off, exam_in, today_iso, h=H):
    """The days a pause I asked for has no new cards, (first, last) from
    today, or None once it's over. off: {kind, at, exam} as Do it saved it:
    "now" from `at` (to the exam when it had one, else till I turn them
    back on), "week" the STOP_BEFORE days before the exam. Its exam is
    whichever date I have now: moved, the pause moves with it; gone or
    passed, it ends."""
    if not isinstance(off, dict):
        return None
    kind = off.get("kind")
    if off.get("exam") or kind == "week":
        if exam_in is None or exam_in < 0:
            return None
        if kind == "week":
            return (max(0, exam_in - STOP_BEFORE), exam_in)
        return (0, exam_in) if str(off.get("at") or "") <= today_iso else None
    return (0, h) if kind == "now" else None


def view(started, cv, rate, wd0, left, unlocked, past, exam_in=None, off=None,
         new_today=0, plan=None, pool=None, off_kind=None):
    """What Reviews ahead draws, worked out: {past, ways, on, climb}.
    started: existing()'s; cv: the curve (mine or GENERIC); rate: pace();
    left/unlocked: the deck's new cards, all / unlocked; past: the last
    seven days' cards; off: stop_of()'s (the pause in effect), else None.
    Each way {key, stop, cards, new, answers, starts; a stop's held, the new
    cards it holds back at my pace, and plan_held, a plan's dates' of them}; on: the one in
    effect (a pause's, else "pace"); climb: the board's line, on it. off_kind:
    the pause's own kind, so it's that way's pill (3.9.2's audit: a pause
    to an exam six weeks out made a second one). A stop that holds nothing
    back isn't offered (a finished deck)."""
    ways, paced = [], None
    for key, stop in choices(exam_in, rate, unlocked, left):
        st = starts(rate, wd0, unlocked if key == "unlocked" else left, stop=stop,
                    today_done=new_today, plan=plan, pool=pool)
        paced = st if key == "pace" else paced
        ways.append(dict(with_new(started, cv, st), key=key, stop=stop, starts=sum(st)))
    on = "pace"
    if off:
        # its own kind's way, unless it ends sooner than that way would (a stop to an exam that's today)
        hit = next((w for w in ways if w["stop"] and ((w["key"] == off_kind and off[1] >= w["stop"][1])
                                                     or tuple(w["stop"]) == tuple(off))), None)
        if hit is None:
            st = starts(rate, wd0, left, stop=off, today_done=new_today, plan=plan, pool=pool)
            hit = dict(with_new(started, cv, st), key="off", stop=off, starts=sum(st))
            ways.append(hit)
        on = hit["key"]
    for w in ways:  # 3.9.2 (Sam's deck): what a stop holds back, said beside its Do it
        if w.get("stop") and paced:
            a, b = int(w["stop"][0]), min(int(w["stop"][1]), len(paced) - 1)
            w["held"] = sum(paced[a:b + 1])
            w["plan_held"] = sum(float((plan or {}).get(d) or 0) for d in range(a, b + 1))
    ways = [w for w in ways if w["key"] in ("pace", on) or not w.get("stop") or w.get("held", 0) >= 1]
    cur = next(w for w in ways if w["key"] == on)
    return {"past": list(past), "ways": ways, "on": on, "climb": climb(past, cur["cards"])}
