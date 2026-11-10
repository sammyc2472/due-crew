"""You › Insights: the deck's map, How you study, Reviews ahead, leeches, my exam's scope.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import re as _re

from .base import _ahead_r, _day_after, _ins_dname, _ins_r, _pycmd, _short_day


def _hm(m):
    m = int(m)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m} min"  # the crew rows' "1h 13m"


def _ins_day(iso, today=""):
    try:
        d = _dt.date.fromisoformat(str(iso))
    except ValueError:
        return "", ""
    return ("Today" if str(iso) == today else f"{d:%a}"), str(d.day)


def _ins_spark(days):
    """The header's 14 days of right, a line; a day with no reviews is a gap."""
    pts = [(i, v) for i, v in enumerate(days) if v is not None]
    if len(pts) < 2:
        return ""
    lo = min(v for _i, v in pts)
    lo = min(lo, 70)
    xy = [(2 + i * 92 / max(1, len(days) - 1), 22 - (v - lo) / max(1, 100 - lo) * 20) for i, v in pts]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="hit"><title>{len(days) - 1 - i} days ago &middot; {v}% right</title></circle>'
                   for (x, y), (i, v) in zip(xy, pts))
    ex, ey = xy[-1]
    return (f'<svg class="ispark" viewBox="0 0 96 24" width="96" height="24" role="img" aria-label="Right, last 14 days">'
            f'<path d="{path}"/><circle class="end" cx="{ex:.1f}" cy="{ey:.1f}" r="3"/>{dots}</svg>')


def _you_insights(ins):
    """3.8.0, You › Insights: for everyone, a deck at a time, picked as a
    squad is. ins: team_flow.you_view: {decks: [{did, name, full}], did,
    exam: my exam date or "", view: the deck's Insights}. It's the deck's,
    plan or not: a plan I follow on it only sharpens it (its events
    aim the exam box, its dates name the topics, its behind line). Names are
    mine (decks) or authors' (plan events, topics): escaped."""
    e = _html.escape
    ins = ins or {}
    decks = ins.get("decks") or []
    if not decks:
        return '<div class="tq0">Insights fill in after a week of reviews.</div>'
    did = int(ins.get("did") or decks[0]["did"])
    on = ' class="on"'
    cur = next((d for d in decks if int(d["did"]) == did), decks[0])
    # 3.8.0 (Sam): the deck's name always shows: one deck, its name; more, the picker
    pick = (f'<b class="ideck" title="{e(str(cur.get("full") or cur["name"]))}">{e(str(cur["name"]))}</b>'
            if len(decks) < 2 else '<div class="dc-sw">' + "".join(
                f'<a{on if int(d["did"]) == did else ""} href="#" title="{e(str(d.get("full") or d["name"]))}" '
                f'onclick="{_pycmd("insdeck:" + str(int(d["did"])))}">{e(str(d["name"]))}</a>' for d in decks) + "</div>")
    # 3.8.0: my exam date, set right here (Settings has the same one): a link, Add exam
    # date, that opens the date picker; once set, the day itself, with × to take it off
    ex = str(ins.get("exam") or "")
    ex = ex if _re.fullmatch(r"\d{4}-\d{2}-\d{2}", ex) else ""
    try:
        x = _dt.date.fromisoformat(ex) if ex else None
    except ValueError:
        x, ex = None, ""
    said = f"Exam {x:%a} {x.day} {x:%b}" if x else "Add exam date"
    off = (f' <a class="q" href="#" title="Take your exam date off" aria-label="Take your exam date off" '
           f'onclick="{_pycmd("setexam:off")}">&times;</a>' if x else "")
    # 3.9.5 (Sam: "removing an exam date and then clicking add exam date makes anki quit"): the day is
    # picked in a Qt calendar (exampick), not the page's own date picker, which the board's redraw on its
    # change could pull out from under itself
    ctx = (f'<span class="iexam" title="Your exam date. Your crew sees it for the two weeks before.">'
           f'<a href="#" onclick="{_pycmd("exampick")}">{said}</a>{off}</span>')
    head = f'<div class="ihead">{pick}<span class="ictx">{ctx}</span></div>'
    # 3.9.5: How you study (all decks): its view in Insights' place, or its line atop Insights
    hv = ins.get("habits") if isinstance(ins.get("habits"), dict) else None
    if hv and hv.get("open"):
        return head + _habits_html(did, hv)
    view = ins.get("view") or {}
    if view.get("working") and len(view) == 1:
        # 3.9.9: the day's first look at a big deck is worked out a part at a time, Anki live meanwhile
        return head + '<div class="tq0" role="status">Reading your reviews&hellip;</div>'
    line = _habits_line(did, hv) if hv and not isinstance(view.get("leech"), dict) else ""
    return head + line + _insights_html(did, view)


# ---- 3.9.5: How you study (habits.py, habits_flow.py): mine alone, never sent ----

HABITS_CSS = """
    #due-crew .hs-in { display: flex; gap: 4px 10px; flex-wrap: wrap; align-items: baseline; text-align: left; font-size: 12px;
      color: var(--dc-muted); padding: 2px 0 10px; }
    #due-crew .hs-in a { color: var(--dc-accent); font-weight: 700; text-decoration: none; }
    #due-crew .hs-in b { color: var(--dc-ink); }
    #due-crew .dc-hv { text-align: left; }
    #due-crew .hv-h { display: flex; flex-wrap: wrap; gap: 2px 12px; align-items: baseline; text-align: left; margin: 0 0 8px; }
    #due-crew .hv-h a { color: var(--dc-accent); font-weight: 700; text-decoration: none; font-size: 12px; }
    #due-crew .hv-h b { font-size: 13.5px; color: var(--dc-ink); }
    #due-crew .hv-h .r { margin-left: auto; font-size: 11.5px; color: var(--dc-muted); }
    #due-crew .hv-h .r b { font-size: 11.5px; }
    #due-crew .ht { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 8px; text-align: left; margin: 2px 0 6px; }
    #due-crew .ht > div { background: var(--dc-well); border-radius: 10px; padding: 10px 12px 9px; display: grid; gap: 7px;
      align-content: start; min-width: 0; }
    #due-crew .ht > div:only-child { max-width: 300px; }
    #due-crew .ht .big { font-size: 24px; font-weight: 700; line-height: 1.05; font-variant-numeric: tabular-nums; color: var(--dc-ink); }
    #due-crew .ht .big small { display: block; font-size: 12px; font-weight: 600; color: var(--dc-muted); margin-top: 3px; line-height: 1.25; }
    #due-crew .ht a.go { justify-self: start; color: var(--dc-accent); font-weight: 700; font-size: 12px; text-decoration: none; }
    #due-crew .ht .hs-cap { font-size: 11px; color: var(--dc-muted); margin-top: -4px; }
    #due-crew .ht svg { width: 100%; max-width: 210px; height: auto; display: block; overflow: visible; }
    #due-crew .ht .t-tint { fill: color-mix(in srgb, var(--dc-accent) 34%, var(--dc-well)); }
    #due-crew .ht .t-on { fill: var(--dc-accent); }
    #due-crew .ht .t-lab { fill: var(--dc-muted); font-size: 9px; }
    #due-crew .ht .t-val { fill: var(--dc-ink); font-size: 9.5px; font-weight: 700; font-variant-numeric: tabular-nums; }
    #due-crew .ht .t-base { stroke: var(--dc-faded); stroke-width: 1; }
    #due-crew .ht .t-grid { stroke: var(--dc-line); stroke-width: 1; }
    #due-crew .ht .t-mark { stroke: var(--dc-muted); stroke-width: 1; stroke-dasharray: 2 2; }
    #due-crew .ht .t-line { stroke: var(--dc-accent); stroke-width: 2; fill: none; stroke-linejoin: round; stroke-linecap: round; }
    #due-crew .ht .t-dot { fill: var(--dc-accent); stroke: var(--dc-well); stroke-width: 2; }
    #due-crew .hs-more { font-size: 11.5px; color: var(--dc-muted); text-align: left; }
"""


def _hs_pts(x):
    return int(round(100 * float(x)))


def _hs_day(iso):
    try:
        d = _dt.date.fromisoformat(str(iso))
    except ValueError:
        return ""
    return f"{d.day} {d:%b}"


def _habits_line(did, h):
    """Atop Insights' main view: the way to How you study, and the week's win."""
    n = int((h.get("matured") or {}).get("n") or 0)
    return (f'<style>{HABITS_CSS}</style><div class="hs-in"><a href="#" onclick="{_pycmd(f"inshabits:{int(did)}:open")}">'
            f'How you study &rsaquo;</a><span><b>{n:,}</b> matured this week</span></div>')


def _hs_matured_svg(m):
    """The win's bars: cards matured each of the last 8 weeks, this week solid."""
    vals = [max(0, int(x)) for x in (m.get("weeks") or [])][-8:]
    froms = list(m.get("from") or [])[-8:]
    if len(vals) < 2:
        return ""
    froms += [""] * (len(vals) - len(froms))
    top, w, gap, h0 = max(vals) or 1, 16, 4, 40
    s = '<svg viewBox="0 0 160 52" role="img" aria-label="Cards matured, each of the last 8 weeks">'
    for i, v in enumerate(vals):
        hh = v / top * 34
        last = i == len(vals) - 1
        when = "This week" if last else f"Week of {_hs_day(froms[i])}"
        s += (f'<rect class="{"t-on" if last else "t-tint"}" x="{2 + i * (w + gap)}" y="{h0 - hh:.1f}" width="{w}" '
              f'height="{hh:.1f}" rx="2"><title>{when}: {v:,} matured</title></rect>')
    return (s + f'<line class="t-base" x1="0" x2="160" y1="{h0}" y2="{h0}"/>'
            '<text class="t-lab" x="2" y="51">8 weeks ago</text><text class="t-lab" x="158" y="51" text-anchor="end">now</text></svg>')


def _hs_two_svg(quick, slow, said):
    """Missed next time: the quicker right answers, then the slow ones (solid);
    said: the matched gap and its range, in each bar's tip."""
    vals, labs = (quick, slow), ("quick", "slow")
    names = ("Quicker right answers", "Slow right answers")
    top, h0 = max(max(vals), 1), 42
    s = '<svg viewBox="0 0 160 56" role="img" aria-label="Missed next time: slow right answers against the rest">'
    for i, v in enumerate(vals):
        x, hh = 30 + i * 64, v / top * 30
        tip = f"{names[i]}: {v}% missed next time" + (f"\n{said}" if said else "")
        s += (f'<rect class="{"t-on" if i else "t-tint"}" x="{x}" y="{h0 - hh:.1f}" width="36" height="{hh:.1f}" rx="3">'
              f'<title>{tip}</title></rect>'
              f'<text class="t-val" x="{x + 18}" y="{h0 - hh - 3:.1f}" text-anchor="middle">{v}%</text>'
              f'<text class="t-lab" x="{x + 18}" y="53" text-anchor="middle">{labs[i]}</text>')
    return s + f'<line class="t-base" x1="14" x2="146" y1="{h0}" y2="{h0}"/></svg>'


def _hs_sit_svg(curve, at):
    """Right % by minutes into a sitting, a point a band (0-15 … 90+), the
    `at` minutes marked; the axis from just under the lowest to just over."""
    import math
    pts = []
    for i, c in enumerate(curve[:6]):
        if c[2] is not None:
            pts.append((i, float(c[2]), c))
    if len(pts) < 2:
        return ""
    vs = [v for _i, v, _c in pts]
    lo, hi = math.floor(min(vs) - 2), math.ceil(max(vs) + 2)
    if hi - lo < 10:
        mid = (hi + lo) / 2
        lo, hi = math.floor(mid - 5), math.ceil(mid + 5)

    def x(i):
        return 8 + 28 * i

    def y(v):
        return 6 + (hi - v) / (hi - lo) * 34
    s = '<svg viewBox="0 0 160 56" role="img" aria-label="Right, by minutes into a sitting">'
    g = 5 * round((lo + hi) / 10)
    if lo < g < hi:
        s += f'<line class="t-grid" x1="0" x2="160" y1="{y(g):.1f}" y2="{y(g):.1f}"/>'
    edges = [int(c[0]) for c in curve[:6]]
    k = max(j for j, e in enumerate(edges) if e <= at)
    span = (int(curve[k][1]) - edges[k]) if curve[k][1] is not None else 15
    mx = 8 + 28 * (k - 0.5) + (at - edges[k]) / max(1, span) * 28
    s += (f'<line class="t-mark" x1="{mx:.1f}" x2="{mx:.1f}" y1="2" y2="44"/>'
          f'<text class="t-lab" x="{mx + 3:.1f}" y="9">{int(at)}</text>')
    s += '<polyline class="t-line" points="' + " ".join(f"{x(i)},{y(v):.1f}" for i, v, _c in pts) + '"/>'
    for i, v, c in pts:
        band = f"{int(c[0])}&ndash;{int(c[1])}" if c[1] is not None else f"{int(c[0])}+"
        s += (f'<circle class="t-dot" cx="{x(i)}" cy="{y(v):.1f}" r="3.5"><title>{band} min in: {round(v)}% right '
              f'({int(c[3]):,} answers)</title></circle>')
    (i0, v0), (i1, v1) = pts[0][:2], pts[-1][:2]
    s += f'<text class="t-val" x="{x(i0)}" y="{y(v0) - 6:.1f}" text-anchor="start">{round(v0)}%</text>'
    s += f'<text class="t-val" x="{x(i1) + 4}" y="{y(v1) + 12:.1f}" text-anchor="end">{round(v1)}%</text>'
    return s + '<text class="t-lab" x="2" y="54">start</text><text class="t-lab" x="158" y="54" text-anchor="end">90 min</text></svg>'


def _habits_html(did, h):
    """3.9.5, How you study, in Insights' place (‹ Insights goes back): my
    time in its head; the win, cards matured, always; Slow but right only
    when its finding passes, with See them (a finding, not a deck, since
    3.9.5's FSRS rule: with an exam set they join the exam box's Study); long
    sittings only when theirs passes, with Start a Fifteen.
    Nothing passed: the win and one line. All decks, worked out from my
    own log (habits_flow.board_view). Numbers only: nothing to escape but
    what's built here."""
    from ..habits import SIT_AT
    did = int(did)
    mins, secs = h.get("mins"), h.get("secs")
    r = (f'<span class="r"><b>{_hm(max(1, round(float(mins))))}</b> a day &middot; <b>{max(1, round(float(secs)))} s</b> a card</span>'
         if mins is not None and secs is not None else "")
    head = (f'<div class="hv-h"><a href="#" onclick="{_pycmd(f"inshabits:{did}:shut")}">&lsaquo; Insights</a>'
            f'<b>How you study</b>{r}</div>')
    m = h.get("matured") or {}
    n = int(m.get("n") or 0)
    tiles = (f'<div><div class="big" title="Next review 3 weeks or more away">{n:,}<small>matured this week</small></div>'
             f'{_hs_matured_svg(m)}'
             + (f'<a href="#" class="go" onclick="{_pycmd(f"inshabits:{did}:see")}">See them</a>' if n else "") + "</div>")
    sp, sit = h.get("speed"), h.get("sit")
    if isinstance(sp, dict):
        slow, quick = _hs_pts(sp["slow"]), _hs_pts(sp["quick"])
        said = ""
        if sp.get("gap") is not None and sp.get("lo") is not None and sp.get("hi") is not None:
            said = (f"At the same intervals: {_hs_pts(sp['gap']):+d} points, "
                    f"could be {_hs_pts(sp['lo'])} to {_hs_pts(sp['hi'])}")
        k = int(h.get("slow") or 0)
        go = f'<a href="#" class="go" onclick="{_pycmd(f"inshabits:{did}:slow")}">See them</a>' if k > 0 else ""
        # 3.9.5 (Sam, of "20% of slow right answers missed next time · 14% otherwise": "this doesn't make
        # much sense"): the number is this week's slow ones, the bars say why
        tiles += (f'<div><div class="big">{k:,}<small>right, but slow, this week</small></div>'
                  f'{_hs_two_svg(quick, slow, said)}<div class="hs-cap">missed next time</div>{go}</div>')
    if isinstance(sit, dict):
        tiles += (f'<div><div class="big" title="{round(float(sit["from"]))}% right in your first 15 minutes, '
                  f'{round(float(sit["to"]))}% at 45 to 60">{SIT_AT} min<small>then you start missing more</small></div>'
                  f'{_hs_sit_svg(sit.get("curve") or [], SIT_AT)}<div class="hs-cap">right, by minutes in one go</div>'
                  f'<a href="#" class="go" title="Fifteen minutes, then one question" onclick="{_pycmd("room15")}">'
                  f'Start a Fifteen</a></div>')
    more = "" if isinstance(sp, dict) or isinstance(sit, dict) else '<div class="hs-more">More as you study.</div>'
    return f'<style>{HABITS_CSS}</style><div class="dc-hv">{head}<div class="ht">{tiles}</div>{more}</div>'


AHEAD_PILL = {"pace": "Your pace", "week": "Stop new a week before the exam", "unlocked": "",
              "now": "Stop new now", "off": "Paused"}


def _ins_ahead_svg(did, a, w, uid):
    """3.9.2: one chart, cards a day as Anki counts them: the last 7 days
    as studied, today (done, and what's still due), the next 13 by day
    (the cards I've started, solid; what new cards bring, striped), then
    4 weeks by week (a week's average day). The exam marked on its day.
    Each bar's tip: its numbers, a band from the track record, the time."""
    days, past, cards, new = a["days"], a["past"], w["cards"], w["new"]
    trust = a.get("trust")
    by = (trust[1] if trust else None) or []
    secs = a.get("secs")
    wk_c, wk_n = _ahead_weeks(cards), _ahead_weeks(new)
    done = int(a.get("done") or 0)
    tall = max([1] + list(past) + [done + cards[0]] + list(cards[1:14]) + wk_c)
    step = next((s_ for s_ in (5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000) if tall / s_ <= 4), 10000)
    top = step * (int(tall // step) + 1)
    Hh, W = 104.0, 640.0
    slot = W / 26.5
    bw = slot * 0.72
    y = lambda v: Hh - Hh * v / top  # noqa: E731
    lab = lambda x, yy, t, cls="ax": f'<text class="{cls}" x="{x:.1f}" y="{yy:.1f}">{t}</text>'  # noqa: E731
    pat = f"ah{uid}"  # defined once, outside the ways' blocks (a pattern in a hidden one doesn't draw)
    out = ""
    for k in range(1, int(top // step) + 1):
        v = k * step
        out += f'<line class="g" x1="0" x2="{W:.0f}" y1="{y(v):.1f}" y2="{y(v):.1f}"/><text class="yl" x="-5" y="{y(v) + 3:.1f}">{v:,}</text>'

    def band(v, wk):
        e = by[min(wk, len(by) - 1)] if by else None
        return f" ({_ins_r(max(0.0, v * (1 - e)))}&ndash;{_ins_r(v * (1 + e))})" if e and v >= 10 else ""

    def mins(ans):
        return f" &middot; about {_hm(max(1, int(round(ans * secs / 60.0))))}" if secs and ans else ""

    pk = max(range(1, 14), key=lambda j: cards[j])  # the tallest day ahead has its number
    ex = a.get("exam")
    for i, n in enumerate(past):
        x = i * slot
        wd, dn = _ins_day(days[i])
        out += (f'<g><title>{_ins_dname(days[i])}: {int(n):,} card{"" if int(n) == 1 else "s"}</title><rect class="hit" x="{x:.1f}" y="-20" width="{slot:.1f}" height="{Hh + 40:.0f}"/>'
                f'<rect class="ps" x="{x:.1f}" y="{y(n):.1f}" width="{bw:.1f}" height="{Hh - y(n):.1f}" rx="2"/>'
                f'{lab(x + bw / 2, Hh + 13, _html.escape(wd[:1]))}{lab(x + bw / 2, Hh + 24, dn, "ax d")}</g>')
    for j in range(14):
        x = (7 + j) * slot
        c, nw = cards[j], new[j]
        base = Hh
        bars = ""
        if j == 0 and done:
            bars += f'<rect class="ps" x="{x:.1f}" y="{y(done):.1f}" width="{bw:.1f}" height="{Hh - y(done):.1f}" rx="2"/>'
            base = y(done)
        h1 = Hh * (c - nw) / top
        h2 = Hh * nw / top
        bars += f'<rect class="pm" x="{x:.1f}" y="{base - h1:.1f}" width="{bw:.1f}" height="{h1:.1f}" rx="2"/>'
        if h2 > 0.5:
            bars += f'<rect fill="url(#{pat})" x="{x:.1f}" y="{base - h1 - h2:.1f}" width="{bw:.1f}" height="{max(0.0, h2 - 1):.1f}" rx="2"/>'
        tot = c + (done if j == 0 else 0)
        ty = base - h1 - h2
        tip = (f"{'Today' if j == 0 else _ins_dname(days[7 + j])}: "
               + (f"{done:,} done, about {_ins_r(c)} to go" if j == 0 else f"about {_ins_r(c)} card{'' if _ahead_r(c) == 1 else 's'}{band(c, 0 if j < 7 else 1)}")
               + f" &middot; {_ins_r(c - nw)} you&rsquo;ve started, {_ins_r(nw)} from new cards{mins(w['answers'][j])}")
        num = ""
        if j == 0 or j == pk or j == ex:
            num = lab(x + bw / 2, ty - 5, _ins_r(tot), "ax b")
        mark = ""
        if j == ex:
            mark = (f'<line class="exl" x1="{x + bw / 2:.1f}" x2="{x + bw / 2:.1f}" y1="-14" y2="{ty - 16:.1f}"/>'
                    f'{lab(x + bw / 2, -17, "Exam", "ax ev")}')
        wd, dn = _ins_day(days[7 + j])
        out += (f'<g><title>{tip}</title><rect class="hit" x="{x:.1f}" y="-20" width="{slot:.1f}" height="{Hh + 40:.0f}"/>{bars}{num}{mark}'
                f'{lab(x + bw / 2, Hh + 13, _html.escape(wd[:1]), "ax b" if j == 0 else "ax")}'
                f'{lab(x + bw / 2, Hh + 24, dn, "ax b" if j == 0 else "ax d")}</g>')
    out += lab(7 * slot + bw / 2, Hh + 36, "today", "ax d")
    x0 = 21.5 * slot
    out += lab(x0 + 1.5 * slot * 1.25 + bw / 2, -17, "by week", "ax d")
    for k in range(4):
        x = x0 + k * slot * 1.25
        c, nw = wk_c[k], wk_n[k]
        h1, h2 = Hh * (c - nw) / top, Hh * nw / top
        first = days[7 + 14 + 7 * k]
        exam_here = ex is not None and 14 + 7 * k <= ex < 21 + 7 * k
        tip = (f"Week of {_ins_dname(first, long=True)}: about {_ins_r(c)} cards a day{band(c, 2 + k)}"
               f"{mins(sum(w['answers'][14 + 7 * k:21 + 7 * k]) / 7.0)}{' &middot; your exam' if exam_here else ''}")
        try:
            fd = _dt.date.fromisoformat(first)
            l1, l2 = str(fd.day), f"{fd:%b}"
        except ValueError:
            l1 = l2 = ""
        out += (f'<g><title>{tip}</title><rect class="hit" x="{x:.1f}" y="-20" width="{slot * 1.2:.1f}" height="{Hh + 40:.0f}"/>'
                f'<rect class="pm" x="{x:.1f}" y="{Hh - h1:.1f}" width="{bw:.1f}" height="{h1:.1f}" rx="2"/>'
                + (f'<rect fill="url(#{pat})" x="{x:.1f}" y="{Hh - h1 - h2:.1f}" width="{bw:.1f}" height="{max(0.0, h2 - 1):.1f}" rx="2"/>' if h2 > 0.5 else "")
                + lab(x + bw / 2, Hh - h1 - h2 - 5, _ins_r(c), "ax b")
                + (lab(x + bw / 2, Hh - h1 - h2 - 17, "Exam", "ax ev") if exam_here else "")
                + f'{lab(x + bw / 2, Hh + 13, l1)}{lab(x + bw / 2, Hh + 24, l2, "ax d")}</g>')
    out += f'<line class="base" x1="0" x2="{W:.0f}" y1="{Hh:.0f}" y2="{Hh:.0f}"/>'
    for sx in (6.86 * slot, 21.1 * slot):
        out += f'<line class="sep" x1="{sx:.1f}" x2="{sx:.1f}" y1="-6" y2="{Hh + 26:.0f}"/>'
    return (f'<svg viewBox="-30 -30 676 174" role="img" aria-label="Cards a day: the last 7 days, the next 14 by day, '
            f'then 4 weeks by week">{out}</svg>')


def _ahead_weeks(xs):
    from ..ahead import weeks
    return weeks(xs)


def _ins_ahead(did, a, deck_name=""):
    """3.9.2 (Sam's picks: Your week becomes Reviews ahead): the chart, the
    ways the next six weeks could go (each its own chart and line, picked
    on the page), and for a stop, Do it: no new cards in this deck, set
    each morning as Anki's today-only limit (deck options untouched), with
    Turn back on in its place once it runs. a: ahead_flow.deck_view."""
    e = _html.escape
    ways = [w for w in a.get("ways") or [] if isinstance(w, dict)]
    if not ways:
        return ""
    on = a.get("on") or "pace"
    pace = next((w for w in ways if w["key"] == "pace"), ways[0])
    days, ex = a["days"], a.get("exam")
    week = sum(a.get("past") or []) / 7.0
    uid = _re.sub(r"[^A-Za-z0-9]", "", str(did))[:20]
    name = e(str(deck_name or "this deck"))
    secs = a.get("secs")
    if ex is not None and 1 <= ex < 14:
        lo, hi, when = max(0, ex - 6), ex + 1, "Exam week" if ex >= 6 else "To your exam"
    elif ex is not None and 14 <= ex < 42:
        lo, hi, when = max(0, ex - 6), ex + 1, "Exam week"
    else:
        lo, hi, when = 7, 14, "In 2 weeks"
    # 3.9.2's audit: "to the exam" only for an exam ahead (today's, or one passed, isn't), named at any distance;
    # a pause I made says what it does from its own kind and exam, not from whether there's an exam now
    ahead_ex = ex is not None and ex >= 1
    exd = _ins_dname(_day_after(days[7], ex), long=True) if ex is not None and ex >= 0 else ""
    if exd and ex == 0:
        exd = "today"
    pz = a.get("pause") if isinstance(a.get("pause"), dict) else None
    rate, unlocked = int(round(a.get("rate") or 0)), int(a.get("unlocked") or 0)

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0

    def held(w):
        """3.9.2 (a real deck): what a stop holds back, and till when; a plan's dates in it said."""
        n, s = w.get("held") or 0, w.get("stop")
        if n < 1 or not s or 7 + int(s[1]) + 1 >= len(days):
            return ""
        ph = w.get("plan_held") or 0
        one = _ahead_r(n) == 1
        return (f" {_ins_r(n)} new card{'' if one else 's'} wait{'s' if one else ''} "
                f"till {_ins_dname(days[7 + int(s[1]) + 1], long=True)}"
                + (f", {_ins_r(ph)} of them in your plan&rsquo;s sets" if ph >= 1 else "") + ".")

    blocks, pills, acts = "", "", ""
    for w in ways:
        k = w["key"]
        if k == "pace":
            # 3.9.2 (a real deck: 44% of the week ahead was new cards at its pace, a guess, in one number):
            # the cards I've started first, what new ones add at my pace after it
            mins = (f", about {_hm(max(1, int(round(mean(w['answers'][:14]) * secs / 60.0))))} a day" if secs else "")
            st, nw = mean((w.get("started") or w["cards"])[:14]), mean((w.get("new") or [0])[:14])
            line = (f"Next 2 weeks: <b>{_ins_r(st)}</b> a day from cards you&rsquo;ve started"
                    + (f", <b>+{_ins_r(nw)}</b> new at your pace" if nw >= 0.5 else "")
                    + f"{mins} &middot; this week {_ins_r(week)}")
            label = f"Your pace &middot; {rate:,} new a week"
        else:
            a_, b_ = _ins_r(mean(w['cards'][lo:hi])), _ins_r(mean(pace['cards'][lo:hi]))
            line = (f"{when}: about <b>{a_}</b> a day" + (f", not {b_}" if a_ != b_ else "")
                    + (f" &middot; exam day about {_ins_r(w['cards'][ex])}" if k != "unlocked" and ex is not None and 1 <= ex < 42 else ""))
            # 3.9.2's QoL pass: a pause no longer among the choices (its exam moved) keeps its own kind's name
            kk = str((pz or {}).get("kind") or "now") if k == "off" else k
            label = (f"Only the {unlocked:,} unlocked" if kk == "unlocked"
                     else "Stop new now" + (", to the exam" if (bool(pz.get("exam")) if pz and k == on else ahead_ex) else "")
                     if kk == "now"
                     else AHEAD_PILL.get(kk) or kk)
        hid = "" if k == on else " hidden"
        blocks += (f'<div class="ahw" data-k="{k}"{hid}><div class="xline">{line}</div>'
                   f'<div class="iwk">{_ins_ahead_svg(did, a, w, uid)}</div></div>')
        pills += (f'<span class="xc{" on" if k == on else ""}" data-k="{k}" role="radio" tabindex="0" '
                  f'aria-checked="{"true" if k == on else "false"}">{label}</span>')
        # what pressing it does, said once, beside its button
        if k == on and k != "pace":
            to_exam = bool(pz and (pz.get("exam") or pz.get("kind") == "week") and exd)
            start = int((pz or {}).get("from") or 0)
            # 3.9.2's QoL pass: a start past the chart still named; before it starts, they aren't off yet
            act = (f'<span>No new cards in {name} '
                   + (f"from {_ins_dname(_day_after(days[7], start), long=True)} " if start > 0 else "")
                   + (f"till your exam, {exd}" if to_exam else "till you turn them back on")
                   + f'.{held(w)}</span><a class="bt" href="#" onclick="{_pycmd(f"insaheadon:{did}")}">'
                   + ("Keep them on" if start > 0 else "Turn new cards back on") + '</a>')
        elif k == "pace" and on != "pace":
            later = int((pz or {}).get("from") or 0) > 0  # the stop hasn't begun: they're on today
            act = (f'<span>{"New cards stay on, at your pace." if later else "From today, new cards at your pace."}</span>'
                   f'<a class="bt" href="#" onclick="{_pycmd(f"insaheadon:{did}")}">{"Keep them on" if later else "Turn new cards back on"}</a>')
        elif k == "pace":
            act = ""
        elif k == "unlocked":
            act = "<span>If you unlock no more: what that leaves.</span>"
        elif k in ("week", "now") and on == "pace":
            first = "today" if k == "now" else _ins_dname(days[7 + w["stop"][0]], long=True)
            till = f"till your exam, {exd}" if ahead_ex else "till you turn them back on"
            act = (f'<span>From {first}, no new cards in {name} {till}.{held(w)}</span>'
                   f'<a class="bt" href="#" title="Anki&rsquo;s today-only limit, each morning. Your deck options stay as they are." '
                   f'onclick="{_pycmd(f"insaheadoff:{did}:{k}")}">Do it</a>')
        else:
            act = ""
        if act:
            acts += f'<div class="xact" data-k="{k}"{hid}>{act}</div>'
    tr = a.get("trust")
    said = ("Counted from your last 120 days"
            + (f" &middot; on your own past, within {max(1, int(round(100 * tr[0])))}% a week" if tr else "")
            + ("" if a.get("own") else " &middot; new cards by a typical curve till yours has 6 weeks"))
    pick = ("var r=this.closest('.dc-ahead'),k=(event.target.closest('.xc')||{}).dataset;"
            "if(!k||!k.k)return;k=k.k;r.querySelectorAll('[data-k]').forEach(function(x){"
            "var m=x.dataset.k===k;if(x.classList.contains('xc')){x.classList.toggle('on',m);x.setAttribute('aria-checked',m);}else x.hidden=!m;});")
    keys = ("if(event.key==='Enter'||event.key===' '){event.preventDefault();event.target.click();}")
    defs = (f'<svg class="ahdefs" width="0" height="0" aria-hidden="true"><defs><pattern id="ah{uid}" width="6" height="6" '
            f'patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" class="h1"/>'
            f'<rect width="3" height="6" class="h2"/></pattern></defs></svg>')
    return (f'<div class="isec dc-ahead">{defs}<div class="ik">Reviews ahead<span>&nbsp;&middot; cards a day</span>'
            f'<span class="ikey"><i class="sw ps"></i>done <i class="sw pm"></i>started <i class="sw hx"></i>new cards</span></div>'
            f'{blocks}'
            + (f'<div class="xwhat" role="radiogroup" aria-label="New cards" onclick="{pick}" onkeydown="{keys}">{pills}</div>'
               if len(ways) > 1 else "")
            + f'{acts}<div class="tmt">{said}.</div></div>')


def _ins_leech_row(did, c):
    """One card: its front (mine, from my copy), what it says (its topic,
    misses, when, slow, on my exam), one button and the rest behind ⋯."""
    e = _html.escape
    cid = int(c["cid"])
    bits = [e(str(c["topic"]))] if c.get("topic") else []
    bits.append(f'missed {int(c["lapses"])} time{"" if int(c["lapses"]) == 1 else "s"}')
    if c.get("susp"):
        if c.get("day") or c.get("at"):  # my Anki day (its rollover), as every day on the board; a year ago or more, its year
            day = c.get("day") or _dt.datetime.fromtimestamp(int(c["at"]) / 1000).date().isoformat()
            try:
                old = (_dt.date.today() - _dt.date.fromisoformat(day)).days > 300
            except ValueError:
                old = False
            bits.append("since " + e(_short_day(day)) + (f" {day[:4]}" if old else ""))
        if c.get("exam"):
            bits.append('<b class="ex">on your exam</b>')
    else:
        d = int(c.get("due") or 0)
        bits.append("due today" if d <= 0 else "back tomorrow" if d == 1 else f"back in {d} days")
    if int(c.get("secs") or 0) >= 30:
        bits.append(f'slow: {int(c["secs"])} s a try')

    def act(a, label, cls="", title=""):
        tip_ = f' title="{title}"' if title else ""
        return f'<a class="{cls}" href="#"{tip_} onclick="{_pycmd(f"insleech:{did}:{a}:{cid}")}">{label}</a>'
    tip, knows = c.get("tip") or [], c.get("knows") or []
    back = act("back", "Bring back", "sl-bt", "Due again, schedule kept")
    if tip:
        main = act("tip", f'{e(tip[0]["name"])}&rsquo;s tip', "sl-bt tip")
    elif knows:
        main = act("ask", f"Ask {e(knows[0])}", "sl-bt tip",
                   f'{e(", ".join(knows))} {"has" if len(knows) == 1 else "have"} it down')
    elif c.get("susp"):
        main = back
    else:
        main = ""
    more = [act("fresh", "Learn it fresh", "q", "A new card again (Anki&rsquo;s Reset)"), act("edit", "Edit", "q")]
    if c.get("susp"):
        more.append(act("out", "Leave it out", "q", "Stays suspended, out of this list"))
        if main != back:
            more.insert(0, act("back", "Bring back", "q", "Due again, schedule kept"))
    elif c.get("kept"):
        more.append(act("out", "Leave it out", "q", "Stays in your reviews, out of this list"))
    toggle = "var m=this.nextElementSibling;m.hidden=!m.hidden;this.setAttribute('aria-expanded',!m.hidden);return false;"
    fr = e(str(c.get("front") or ""))
    return (f'<div class="sl-row"><span class="sl-q"><b title="{fr}">{fr or "&nbsp;"}</b>'
            f'<span>{" &middot; ".join(bits)}</span></span>'
            f'<span class="sl-act">{main}<span class="sl-more"><a class="q" href="#" aria-expanded="false" aria-label="More" '
            f'title="More" onclick="{toggle}">&middot;&middot;&middot;</a><span class="sl-more" hidden>{" ".join(more)}</span></span></span></div>')


LEECH_SHOW = 12  # cards a group lists; the rest are in Browse


def _ins_leeches(did, L, deck_name=""):
    """3.9.2 (Sam's picks: leeches, one button per card, sorted by danger):
    in Insights' place, Insights › Leeches with the way back; the counts,
    Bring all back and Browse; the cards Anki stopped showing, then the
    ones a miss from it, then the ones Anki tagged and kept showing (Tag
    Only). L: leech_flow.view."""
    e = _html.escape
    gone, near, kept = L.get("gone") or [], L.get("near") or [], L.get("kept") or []
    ng, nn, nk = int(L.get("n_gone") or 0), int(L.get("n_near") or 0), int(L.get("n_kept") or 0)
    trail = (f'<div class="tmt"><a href="#" onclick="{_pycmd(f"insleech:{did}:shut:0")}">Insights</a> &rsaquo; '
             f'<b>Leeches</b>{" &middot; " + e(str(deck_name)) if deck_name else ""}</div>')
    n_out = int(L.get("out") or 0)
    # 3.9.2's audit: Leave it out's way back, on the same screen
    put = (f'<div class="tmt">{n_out:,} left out of this list &middot; <a href="#" '
           f'onclick="{_pycmd(f"insleech:{did}:unout:0")}">Put {"it" if n_out == 1 else "them"} back</a></div>') if n_out else ""
    if not gone and not near and not kept:
        return f'<div class="dc-ins">{trail}<div class="tq0">No leeches here, and none a miss away.</div>{put}</div>'
    on_exam = sum(1 for c in gone if c.get("exam"))
    summ = " &middot; ".join(x for x in (
        f"<b>{ng:,}</b> Anki stopped showing you" if ng else "",
        f"<b>{nk:,}</b> still in your reviews" if nk else "",
        f"<b>{nn:,}</b> one miss away" if nn else "",
        f"{on_exam:,} on your exam" if on_exam else "") if x)
    heads = ""
    if ng:
        heads += (f'<a class="sl-bt" href="#" title="Due again, schedule kept" '
                  f'onclick="{_pycmd(f"insleech:{did}:back:all")}">{"Bring it back" if ng == 1 else f"Bring all {ng:,} back"}</a>')
    heads += f'<a href="#" onclick="{_pycmd(f"insleech:{did}:browse:0")}">Browse</a>'
    out = f'{trail}<div class="sl-sum"><span>{summ}</span><span class="sl-hd">{heads}</span></div>'
    for rows, n, head, sub in ((gone, ng, "Anki stopped showing these", f"{ng:,}"),
                               (near, nn, "One miss away", f"{nn:,}, still in your reviews"),
                               (kept, nk, "Leeches still in your reviews", f"{nk:,}")):
        if rows:
            out += (f'<div class="isec"><div class="ik">{head}<span>&nbsp;&middot; {sub}</span></div>'
                    + "".join(_ins_leech_row(did, c) for c in rows[:LEECH_SHOW])
                    + (f'<div class="sl-plus">{n - LEECH_SHOW:,} more in Browse</div>' if n > LEECH_SHOW else "") + "</div>")
    out += ('<div class="tmt">' + ("Bring back: due again, schedule kept. " if ng else "")
            + "Learn it fresh: a new card again. Edit &rsaquo; Undo takes " + ("either" if ng else "it") + " back.</div>") + put
    return f'<div class="dc-ins">{out}</div>'


def _ins_scope(aim):
    """3.9.2 (Sam's pick C1-A): what my exam covers, said once: since my
    last exam (the default, when it was in the last 10 weeks), since a day
    I picked, or the whole deck; Change picks a day (the date picker),
    and the other way back is a link."""
    since, why = str(aim.get("since") or ""), aim.get("since_why") or ""
    if since:
        said = (f'Since {_ins_dname(since, long=True)}'
                + (", the day after your last exam" if why == "last" else "")
                + (f' &middot; {int(aim["since_n"]):,} card{"" if int(aim["since_n"]) == 1 else "s"}' if aim.get("since_n") is not None else ""))
        other = (f'<a class="q" href="#" onclick="{_pycmd("setscope:all")}">Whole deck</a>' if why == "last"
                 else f'<a class="q" href="#" title="Since your last exam, or the whole deck" onclick="{_pycmd("setscope:auto")}">As it was</a>')
    else:
        said = "Whole deck"
        other = (f'<a class="q" href="#" onclick="{_pycmd("setscope:auto")}">Since your last exam</a>'
                 if aim.get("since_pick") == "all" else "")
    pick = f'<span class="iexam"><a class="q" href="#" onclick="{_pycmd("scopepick")}">Change</a></span>'  # 3.9.5: a Qt calendar
    return f'<div class="isc">{said} &middot; {pick}{(" &middot; " + other) if other else ""}</div>'


def _insights_html(did, v):
    """3.7.9 (mock "Insights"): mine alone, worked out in my Anki. The
    header's right, the cards Anki won't show me before the next exam (a
    plan's event, or my own date: 3.8.0) that I'd be under my target on by
    then, what's not sticking yet, my week in time, Optimize FSRS when my
    newest cards fall short, and the deck's suspended leeches. 3.8.0: a
    deck's, plan or not (did, its id, in each command)."""
    e = _html.escape
    v = v if isinstance(v, dict) else {}
    if isinstance(v.get("leech"), dict):
        return _ins_leeches(did, v["leech"], v.get("deck_name"))  # 3.9.2: the leeches view, in Insights' place
    out = ""
    # 3.9.5 (Sam: "this line is extra because QIDs is in the header"): no QBank QIDs line here; the head has it
    r = v.get("right") or {}
    now, before = r.get("now") or [0, 0], r.get("before") or [0, 0]
    if now[1] >= 50:
        pct = round(100 * now[0] / now[1])
        was = (f'<span class="m">{round(100 * before[0] / before[1])}% the 2 weeks before</span>' if before[1] >= 50 else "")
        out += (f'<div class="ihd" title="This deck, first answer of each card each day: '
                f'{now[0]:,} of {now[1]:,} right in 2 weeks"><b>{pct}%</b><span>right{" &middot; Anki aims for " + str(int(v.get("target") or 90)) + "%" if v.get("fsrs_on", True) else ""}'
                f'{" &middot; " + was if was else ""}</span>'
                f'{_ins_spark(r.get("days") or [])}</div>')
        from ..team import right_split
        sp = right_split(r)
        if sp:  # 3.9.2 (a real deck): a week of new cards reads as forgetting; said apart
            out += (f'<div class="tmt">{sp[0]}% on the cards you started these 2 weeks ({sp[2]:,} reviews) '
                    f'&middot; {sp[1]}% on the rest</div>')
    aim = v.get("aim") or {}
    hero = v.get("hero") or []
    if hero:
        k = int(aim.get("in") or 7)
        when, dn = _ins_day(aim.get("day"))
        days = f'{k} day{"s" if k != 1 else ""}'
        # 3.7.9: named for the event only when its prep dates are what's counted; else by the day.
        # 3.8.0: my own exam date (Settings) is named too, over the whole deck
        scoped = bool(aim.get("scoped") and aim.get("name"))
        mine = aim.get("kind") == "exam"
        lab = (f'{e(str(aim["name"]))} &middot; {when} {dn} &middot; {days}' if scoped
               else f'Your exam &middot; {when} {dn} &middot; {days}' if mine
               else f'Before {when} {dn} &middot; {days}')
        whose = "the plan&rsquo;s prep sets for it" if scoped else "this deck"
        out += (f'<div class="ihero"><div class="k">{lab}</div>'
                f'<div class="t" title="Started cards of {whose} that Anki won&rsquo;t show you before then, under your {int(v.get("target") or 90)}% by then (FSRS)">'
                f'<a class="tp" href="#" title="Browse them" onclick="{_pycmd(f"insbrowse:{did}:h")}">'
                f'{len(hero):,} card{"s" if len(hero) != 1 else ""}</a> Anki won&rsquo;t show you before {when}</div>'
                f'{_ins_scope(aim) if mine else ""}'
                # 3.9.5 (Sam's FSRS rule): Study only before a date, my exam or a plan's event
                + (f'<a class="bt" href="#" title="A filtered deck of them, the most missed first" onclick="{_pycmd(f"insstudy:{did}:h")}">Study {len(hero):,} early</a>'
                   if aim.get("name") else "") + '</div>')
    elif aim.get("kind") == "exam":
        # 3.9.2: my exam with nothing at risk still says what it covers, and keeps its Change; without
        # FSRS nothing was looked at (what's at risk is FSRS's), so it says only the day (the audit)
        risk = ": nothing at risk" if aim.get("checked") else ""
        out += f'<div class="iline">Your exam, {_ins_dname(aim.get("day"), long=True)}{risk} &middot; {_ins_scope(aim)}</div>'
    if int(v.get("behind") or 0) and v.get("pid"):
        out += (f'<div class="iline">{int(v["behind"]):,} new cards behind &middot; '
                f'<a href="#" onclick="{_pycmd("plancatch:" + str(v["pid"]))}">Catch up&hellip;</a></div>')
    rows = v.get("rows") or []
    dated = bool((v.get("aim") or {}).get("name"))  # 3.9.5 (Sam's FSRS rule): a Study only before a date
    if rows:
        # 3.9.2 (the students: "not right yet" and "forgot" read alike): Anki's own Stats' words
        out += ('<div class="isec"><div class="ik">Not sticking yet<span>&nbsp;&middot; last 2 weeks</span>'
                '<span class="ikey"><i class="sw st"></i>never passed <i class="sw fg"></i>lapsed</span></div>')
        for i, x in enumerate(rows):
            of, st, fg = max(1, int(x["of"])), int(x["stuck"]), int(x["forgot"])
            tip = f'{x["name"]} · {of} cards reviewed in 2 weeks: {st} never passed a review yet, {fg} lapsed after passing'
            out += (f'<div class="irow" title="{e(tip)}"><span class="n"><b><a class="tp" href="#" title="Browse them" '
                    f'onclick="{_pycmd(f"insbrowse:{did}:{i}")}">{e(str(x["name"]))}</a></b>'
                    f'<span>{e(str(x.get("src") or ""))}</span></span>'
                    f'<span class="ib"><i class="st" style="width:{100 * st / of:.1f}%"></i>'
                    f'<i class="fg" style="left:{100 * st / of:.1f}%;width:{100 * fg / of:.1f}%"></i></span>'
                    f'<span class="c"><b>{st + fg}</b> of {of}</span>'
                    + (f'<a href="#" title="A filtered deck of them, the most missed first" onclick="{_pycmd(f"insstudy:{did}:{i}")}">Study {st + fg}</a>' if dated else "")
                    + '</div>')
        out += "</div>"
    out += _ins_map(did, v.get("map") or [], v.get("map_by"), v.get("map_at"), v.get("map_ways"))
    if v.get("ahead"):
        out += _ins_ahead(did, v["ahead"], v.get("deck_name"))
    f = v.get("fsrs")
    if f:
        out += (f'<div class="iline" title="Reviews of cards 1&ndash;3 days since their last review, 4 weeks: '
                f'{int(f["right"])}% right of {int(f["n"]):,}">Newest cards {int(f["right"])}% right, '
                f'Anki aims for {int(f["target"])}% &middot; '
                f'<a href="#" onclick="{_pycmd(f"insfsrs:{did}")}">Optimize FSRS</a> '
                f'<a class="q" href="#" onclick="{_pycmd(f"insfsrsno:{did}")}">Not now</a></div>')
    h = v.get("hard")
    two = v.get("two")
    if two == "tried":
        # 3.9.1: just turned on from here: said, with its way back
        out += (f'<div class="iline">Two buttons are on: Again and Good. 2, 3 and 4 count as Good. '
                f'<a class="q" href="#" onclick="{_pycmd(f"instwono:{did}")}">Undo</a></div>')
    elif h and two != "on":
        # 3.8.0: the Hard habit, said once a month at most; 3.9.1: with two buttons on there's no Hard to press
        out += (f'<div class="iline" title="{int(h["n"]):,} reviews in 4 weeks">You press Hard on {int(h["pct"])}% of reviews. '
                f'Anki counts Hard as remembered. '
                f'<a href="#" onclick="{_pycmd(f"instwo:{did}")}">Try two buttons</a> '
                f'<a class="q" href="#" onclick="{_pycmd(f"inshardno:{did}")}">Not now</a></div>')
    lee, near, kept = int(v.get("leeches") or 0), int(v.get("near") or 0), int(v.get("kept") or 0)
    lout = int(v.get("leech_out") or 0)
    if not (lee or near or kept) and lout:
        # 3.9.2's QoL pass: every one left out, the way back to them still here
        out += (f'<div class="iline"><b>{lout:,}</b> leech{"es" if lout != 1 else ""} you left out &middot; '
                f'<a href="#" onclick="{_pycmd(f"insleeches:{did}")}">{"See it" if lout == 1 else "See them"}</a></div>')
    elif lee or near or kept:
        # 3.8.0: from the plan card, a leech is the deck's; 3.9.2: and the ones a miss away, a view of their own,
        # and the ones Anki tagged and kept showing (Tag Only, its default since 23.10)
        les = lambda n: f"leech{'es' if n != 1 else ''} "  # noqa: E731
        said = " &middot; ".join(x for x in (f"<b>{lee:,}</b> {les(lee)}Anki stopped showing you" if lee else "",
                                              f"<b>{kept:,}</b> {'' if lee else les(kept)}still in your reviews" if kept else "",
                                              (f"<b>{near:,}</b> one miss away" if lee or kept  # alone, it says of what
                                               else f"<b>{near:,}</b> card{'' if near == 1 else 's'} one miss from a leech")
                                              if near else "") if x)
        one = lee + near + kept == 1  # 3.9.3 (Sam): one card is "it"
        out += f'<div class="iline">{said} &middot; <a href="#" onclick="{_pycmd(f"insleeches:{did}")}">{"See it" if one else "See them"}</a></div>'
    if not out:
        return '<div class="tq0">Insights fill in after a week of reviews.</div>'
    return f'<div class="dc-ins">{out}</div>'


def word_pick(cmd, label, opts, on):
    """A pick in a line of words ("by Systems ▾"): the word picked and its ▾,
    the select laid over them, so the ▾ sits by the word (a select is as
    wide as its longest option). opts: [(value, words)]; a change sends
    duecrew:<cmd>:<value>. The words are escaped here."""
    e = _html.escape
    word = next((w for k, w in opts if k == on), opts[0][1] if opts else "")
    ops = "".join(f'<option value="{e(str(k))}"{" selected" if k == on else ""}>{e(str(w))}</option>' for k, w in opts)
    return (f'<span class="dc-wp"><b>{e(str(word))}</b><i aria-hidden="true">&#9662;</i><select aria-label="{e(label)}" '
            f'onchange="pycmd(\'duecrew:{cmd}:\'+this.value+\'|\'+window.dcBK);">{ops}</select></span>')


def _ins_map(did, tiles, by, at=(), ways=()):
    """3.8.0, the topic map: each subject a tile, sized by its cards in play,
    shaded by how much I know now of the ones I've started (a bar along its
    foot: how many I've started; none yet, "new"). A tile that splits again
    opens into its smaller ones (at: the keys opened), the trail above them
    goes back, and Browse all opens the open one's cards; a tile that
    doesn't, its cards. ways: how else it can split (Systems, a resource,
    Subdecks), a pick in its heading ("by Systems ▾"). Mine alone, from my
    own Anki. Two tiles at least, or it says nothing."""
    if len(tiles) < 2:
        return ""
    e = _html.escape
    from ..team import map_level, map_shade
    trail, cur = map_level(tiles, at)
    big = max(int(t["n"]) for t in cur) or 1
    how = "you’d remember now (FSRS)" if by == "fsrs" else "right in their reviews these 4 weeks"  # escaped with the tip
    out, fresh, soon_any, bars = "", False, False, False
    for i, t in enumerate(cur):
        n, k, st = int(t["n"]), t.get("know"), int(t.get("started") or 0)
        soon = k is None and st > 0  # 3.9.2's audit: started, none reviewed yet: too soon to say
        fresh = fresh or (k is None and not soon)
        soon_any = soon_any or soon
        cards = f'{n:,} card{"" if n == 1 else "s"}'
        said = (f"{cards}, started, none reviewed yet: too soon to say" if soon
                else f"{cards}, none started yet" if k is None
                else f"{cards}, {st:,} started, {int(k)}% {how}")
        tip = f'{t["name"]}: {said}. ' + ("Open it." if t.get("kids") else "Browse them.")
        more = '<i aria-hidden="true">&rsaquo;</i>' if t.get("kids") else ""
        bar = (f'<i class="tmb" style="width:{100 * st / n:.0f}%"></i>' if k is not None and 0 < st < n else "")
        bars = bars or bool(bar)
        out += (f'<a class="tm {"sn" if k is None else f"s{map_shade(int(k))}"}" href="#" '
                f'style="flex:{n} 1 {70 + int(150 * n / big)}px" title="{e(tip)}" '
                f'onclick="{_pycmd(f"insmap:{did}:{i}")}"><span>{e(str(t["name"]))}{more}</span>'
                f'<b>{"too soon" if soon else "new" if k is None else f"{int(k)}%"}<small> &middot; {n:,}</small></b>{bar}</a>')
    path = ""
    if trail:
        steps = [f'<a href="#" onclick="{_pycmd(f"insmapup:{did}:0")}">All</a>']
        steps += [f'<a href="#" onclick="{_pycmd(f"insmapup:{did}:{j}")}">{e(str(t["name"]))}</a>'
                  for j, t in enumerate(trail[:-1], 1)]
        last = trail[-1]
        steps.append(f'<b>{e(str(last["name"]))}</b>')
        lk = last.get("know")
        path = (f'<div class="tmt">{" &rsaquo; ".join(steps)} &middot; {int(last["n"]):,} card{"" if int(last["n"]) == 1 else "s"}'
                f'{"" if lk is None else f", {int(lk)}%"} '
                f'&middot; <a href="#" onclick="{_pycmd(f"insmapall:{did}")}">Browse all</a></div>')
    # 3.9.2 (the students: what's the %, what's the bar?): said in the key; a tile's cards beside its %
    pct = "% you&rsquo;d recall now" if by == "fsrs" else "% right, 4 weeks"
    grey = ", ".join(w for w, on in (("new", fresh), ("too soon", soon_any)) if on)
    # the key names what the map shows: the grey only with a grey tile, the bar only with a tile part started
    key = (f'{pct}: <i class="sw s0"></i>under 70 <i class="sw s3"></i>90+' + (f' <i class="sw sn"></i>{grey}' if grey else "")
           + (' &middot; <i class="sw bar"></i>started' if bars else ""))
    ways = [w for w in ways or () if isinstance(w, dict)]
    if len(ways) > 1:  # 3.8.0: another way to split it, this deck's, on this computer
        on = next((str(i) for i, w in enumerate(ways) if w.get("on")), "0")
        sub = (f'<span>&nbsp;&middot; by {word_pick(f"insmapby:{int(did)}", "Split by", [(str(i), str(w.get("name") or "?")) for i, w in enumerate(ways)], on)}'
               '</span>')
    else:
        sub = "<span>&nbsp;&middot; by topic, now</span>"
    share = f' <a class="tmsh" href="#" title="A picture of it, or text" onclick="{_pycmd(f"insmapshare:{did}")}">Share &rsaquo;</a>'
    # 3.8.1: by a plan's own tags, the ones no card in this deck carries (a gap in the plan's coverage)
    none = next((w.get("none") or [] for w in ways if w.get("on")), [])
    gap = ""
    if any(w.get("one") for w in ways) and not trail:
        gap = '<div class="tmt">Everything you&rsquo;ve started is from one week, so this is by topic.</div>'
    if none and not trail:
        names = ", ".join(e(str(x)) for x in none[:6]) + (f" and {len(none) - 6} more" if len(none) > 6 else "")
        gap = f'<div class="tmt">No card in this deck carries {names}.</div>'
    return (f'<div class="isec"><div class="ik">What you know{sub}'
            f'<span class="ikey">{key}{share}</span></div>'
            f'{path}<div class="tmap">{out}</div>{gap}</div>')


def ahead_line(a):
    """3.9.2: the board's line when the next two weeks climb a quarter over
    this one (ahead.climb), in my most reviewed deck: the number and the
    day, what this week was, and Insights' chart. Never a warning colour."""
    did = int(a["did"])
    day = _ins_dname(a.get("day"), long=True)
    return (f'<div class="dc-wrap ah-line"><span>&#128197;</span>'
            f'<span>Reviews in <b>{_html.escape(str(a.get("name") or ""))}</b> climb to about <b>{_ins_r(a["n"])}</b> a day by {day}'
            f' &middot; this week {int(a.get("week") or 0):,}'
            + (f' &middot; you started {int(a["cause"]):,} cards in 2 weeks' if a.get("cause") else "") + '</span>'
            f'<a class="wc" href="#" onclick="{_pycmd(f"youins:{did}")}">See ahead</a>'
            f'<a class="wx" href="#" title="Not this week" onclick="{_pycmd(f"insaheadx:{did}")}">&times;</a></div>')
