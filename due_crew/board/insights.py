"""You › Insights: the deck's map, How you study, Reviews ahead, leeches, my exam's scope.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import re as _re

from .. import views as _views
from ..words import later as _later, month as _month, t as _t, weekday as _weekday
from .base import _ahead_r, _day_after, _ins_dname, _ins_r, _pycmd, _short_day


def _tn(one, many, count, **names):
    """words.tn with the count's comma ("1,204 cards"): `one` for exactly one, `many` otherwise; {n} is
    the count unless it's given (a rounded one, one in bold)."""
    names.setdefault("n", f"{int(count):,}")
    return _t(one if int(count) == 1 else many, **names)


def _hm(m):
    m = int(m)
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m} min"  # the crew rows' "1h 13m"


def _ins_day(iso, today=""):
    try:
        d = _dt.date.fromisoformat(str(iso))
    except ValueError:
        return "", ""
    return (_t("Today") if str(iso) == today else _weekday(d.weekday())), str(d.day)


def _ins_letter(iso):
    """A day's letter under its bar, as the crew's week has them (M T W T F S S); "" for no day."""
    try:
        return _html.escape(_t("MTWTFSS")[_dt.date.fromisoformat(str(iso)).weekday()])
    except (ValueError, IndexError):
        return ""


def _ins_spark(days):
    """The header's 14 days of right, a line; a day with no reviews is a gap."""
    pts = [(i, v) for i, v in enumerate(days) if v is not None]
    if len(pts) < 2:
        return ""
    lo = min(v for _i, v in pts)
    lo = min(lo, 70)
    xy = [(2 + i * 92 / max(1, len(days) - 1), 22 - (v - lo) / max(1, 100 - lo) * 20) for i, v in pts]
    path = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    dots = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="hit"><title>{_t("{n} days ago &middot; {pct}% right", n=len(days) - 1 - i, pct=v)}</title></circle>'
                   for (x, y), (i, v) in zip(xy, pts))
    ex, ey = xy[-1]
    return (f'<svg class="ispark" viewBox="0 0 96 24" width="96" height="24" role="img" aria-label="{_t("Right, last 14 days")}">'
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
        return f'<div class="tq0">{_t("Insights fill in after a week of reviews.")}</div>'
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
    said = (_t("Exam {wd} {day} {month}", wd=_weekday(x.weekday()), day=x.day, month=_month(x.month)) if x
            else _t("Add exam date"))
    off = (f' <a class="q" href="#" title="{_t("Take your exam date off")}" aria-label="{_t("Take your exam date off")}" '
           f'onclick="{_pycmd("setexam:off")}">&times;</a>' if x else "")
    # 3.9.5 (Sam: "removing an exam date and then clicking add exam date makes anki quit"): the day is
    # picked in a Qt calendar (exampick), not the page's own date picker, which the board's redraw on its
    # change could pull out from under itself
    ctx = (f'<span class="iexam" title="{_t("Your exam date. Your crew sees it for the two weeks before.")}">'
           f'<a href="#" onclick="{_pycmd("exampick")}">{said}</a>{off}</span>')
    head = f'<div class="ihead">{pick}<span class="ictx">{ctx}</span></div>'
    # 3.9.5: How you study (all decks): its view in Insights' place, or its line atop Insights
    hv = ins.get("habits") if isinstance(ins.get("habits"), dict) else None
    if hv and hv.get("open"):
        return head + _habits_html(did, hv)
    view = ins.get("view") or {}
    if view.get("working") and len(view) == 1:
        # 3.9.9: the day's first look at a big deck is worked out a part at a time, Anki live meanwhile
        return head + f'<div class="tq0" role="status">{_t("Reading your reviews&hellip;")}</div>'
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
    return _t("{day} {month}", day=d.day, month=_month(d.month))


def _habits_line(did, h):
    """Atop Insights' main view: the way to How you study, and the week's win."""
    n = int((h.get("matured") or {}).get("n") or 0)
    return (f'<style>{HABITS_CSS}</style><div class="hs-in"><a href="#" onclick="{_pycmd(f"inshabits:{int(did)}:open")}">'
            f'{_t("How you study")} &rsaquo;</a><span>{_t("{n} matured this week", n=f"<b>{n:,}</b>")}</span></div>')


def _hs_matured_svg(m):
    """The win's bars: cards matured each of the last 8 weeks, this week solid."""
    vals = [max(0, int(x)) for x in (m.get("weeks") or [])][-8:]
    froms = list(m.get("from") or [])[-8:]
    if len(vals) < 2:
        return ""
    froms += [""] * (len(vals) - len(froms))
    top, w, gap, h0 = max(vals) or 1, 16, 4, 40
    s = f'<svg viewBox="0 0 160 52" role="img" aria-label="{_t("Cards matured, each of the last 8 weeks")}">'
    for i, v in enumerate(vals):
        hh = v / top * 34
        last = i == len(vals) - 1
        when = _t("This week") if last else _t("Week of {day}", day=_hs_day(froms[i]))
        s += (f'<rect class="{"t-on" if last else "t-tint"}" x="{2 + i * (w + gap)}" y="{h0 - hh:.1f}" width="{w}" '
              f'height="{hh:.1f}" rx="2"><title>{_t("{when}: {n} matured", when=when, n=f"{v:,}")}</title></rect>')
    return (s + f'<line class="t-base" x1="0" x2="160" y1="{h0}" y2="{h0}"/>'
            f'<text class="t-lab" x="2" y="51">{_t("8 weeks ago")}</text><text class="t-lab" x="158" y="51" text-anchor="end">{_t("now")}</text></svg>')


def _hs_two_svg(quick, slow, said):
    """Missed next time: the quicker right answers, then the slow ones (solid);
    said: the matched gap and its range, in each bar's tip."""
    vals, labs = (quick, slow), (_t("quick"), _t("slow"))
    names = (_later("Quicker right answers: {pct}% missed next time"), _later("Slow right answers: {pct}% missed next time"))
    top, h0 = max(max(vals), 1), 42
    s = f'<svg viewBox="0 0 160 56" role="img" aria-label="{_t("Missed next time: slow right answers against the rest")}">'
    for i, v in enumerate(vals):
        x, hh = 30 + i * 64, v / top * 30
        tip = _t(names[i], pct=v) + (f"\n{said}" if said else "")
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
    s = f'<svg viewBox="0 0 160 56" role="img" aria-label="{_t("Right, by minutes into a sitting")}">'
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
        said = _t("{band} min in: {pct}% right ({n} answers)", band=band, pct=round(v), n=f"{int(c[3]):,}")
        s += f'<circle class="t-dot" cx="{x(i)}" cy="{y(v):.1f}" r="3.5"><title>{said}</title></circle>'
    (i0, v0), (i1, v1) = pts[0][:2], pts[-1][:2]
    s += f'<text class="t-val" x="{x(i0)}" y="{y(v0) - 6:.1f}" text-anchor="start">{round(v0)}%</text>'
    s += f'<text class="t-val" x="{x(i1) + 4}" y="{y(v1) + 12:.1f}" text-anchor="end">{round(v1)}%</text>'
    return s + f'<text class="t-lab" x="2" y="54">{_t("start")}</text><text class="t-lab" x="158" y="54" text-anchor="end">90 min</text></svg>'


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
    r = ('<span class="r">' + _t("{time} a day &middot; {secs} a card", time=f"<b>{_hm(max(1, round(float(mins))))}</b>",
                                 secs=f"<b>{max(1, round(float(secs)))} s</b>") + '</span>'
         if mins is not None and secs is not None else "")
    head = (f'<div class="hv-h"><a href="#" onclick="{_pycmd(f"inshabits:{did}:shut")}">&lsaquo; {_t("Insights")}</a>'
            f'<b>{_t("How you study")}</b>{r}</div>')
    m = h.get("matured") or {}
    n = int(m.get("n") or 0)
    tiles = (f'<div><div class="big" title="{_t("Next review 3 weeks or more away")}">{n:,}<small>{_t("matured this week")}</small></div>'
             f'{_hs_matured_svg(m)}'
             + (f'<a href="#" class="go" onclick="{_pycmd(f"inshabits:{did}:see")}">{_t("See them")}</a>' if n else "") + "</div>")
    sp, sit = h.get("speed"), h.get("sit")
    if isinstance(sp, dict):
        slow, quick = _hs_pts(sp["slow"]), _hs_pts(sp["quick"])
        said = ""
        if sp.get("gap") is not None and sp.get("lo") is not None and sp.get("hi") is not None:
            said = _t("At the same intervals: {gap} points, could be {lo} to {hi}", gap=f"{_hs_pts(sp['gap']):+d}",
                      lo=_hs_pts(sp["lo"]), hi=_hs_pts(sp["hi"]))
        k = int(h.get("slow") or 0)
        go = f'<a href="#" class="go" onclick="{_pycmd(f"inshabits:{did}:slow")}">{_t("See them")}</a>' if k > 0 else ""
        # 3.9.5 (Sam, of "20% of slow right answers missed next time · 14% otherwise": "this doesn't make
        # much sense"): the number is this week's slow ones, the bars say why
        tiles += (f'<div><div class="big">{k:,}<small>{_t("right, but slow, this week")}</small></div>'
                  f'{_hs_two_svg(quick, slow, said)}<div class="hs-cap">{_t("missed next time")}</div>{go}</div>')
    if isinstance(sit, dict):
        sit_tip = _t("{a}% right in your first 15 minutes, {b}% at 45 to 60", a=round(float(sit["from"])), b=round(float(sit["to"])))
        tiles += (f'<div><div class="big" title="{sit_tip}">{SIT_AT} min<small>{_t("then you start missing more")}</small></div>'
                  f'{_hs_sit_svg(sit.get("curve") or [], SIT_AT)}<div class="hs-cap">{_t("right, by minutes in one go")}</div>'
                  f'<a href="#" class="go" title="{_t("Fifteen minutes, then one question")}" onclick="{_pycmd("room15")}">'
                  f'{_t("Start a Fifteen")}</a></div>')
    more = "" if isinstance(sp, dict) or isinstance(sit, dict) else f'<div class="hs-more">{_t("More as you study.")}</div>'
    return f'<style>{HABITS_CSS}</style><div class="dc-hv">{head}<div class="ht">{tiles}</div>{more}</div>'


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
        return " &middot; " + _t("about {time}", time=_hm(max(1, int(round(ans * secs / 60.0))))) if secs and ans else ""

    pk = max(range(1, 14), key=lambda j: cards[j])  # the tallest day ahead has its number
    ex = a.get("exam")
    for i, n in enumerate(past):
        x = i * slot
        _wd, dn = _ins_day(days[i])
        out += (f'<g><title>{_tn("{day}: {n} card", "{day}: {n} cards", int(n), day=_ins_dname(days[i]))}</title><rect class="hit" x="{x:.1f}" y="-20" width="{slot:.1f}" height="{Hh + 40:.0f}"/>'
                f'<rect class="ps" x="{x:.1f}" y="{y(n):.1f}" width="{bw:.1f}" height="{Hh - y(n):.1f}" rx="2"/>'
                f'{lab(x + bw / 2, Hh + 13, _ins_letter(days[i]))}{lab(x + bw / 2, Hh + 24, dn, "ax d")}</g>')
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
        tip = ((_t("Today: {done} done, about {n} to go", done=f"{done:,}", n=_ins_r(c)) if j == 0
                else _tn("{day}: about {n} card", "{day}: about {n} cards", _ahead_r(c), day=_ins_dname(days[7 + j]), n=_ins_r(c))
                + band(c, 0 if j < 7 else 1))
               + " &middot; " + _t("{started} you&rsquo;ve started, {new} from new cards", started=_ins_r(c - nw), new=_ins_r(nw))
               + mins(w["answers"][j]))
        num = ""
        if j == 0 or j == pk or j == ex:
            num = lab(x + bw / 2, ty - 5, _ins_r(tot), "ax b")
        mark = ""
        if j == ex:
            mark = (f'<line class="exl" x1="{x + bw / 2:.1f}" x2="{x + bw / 2:.1f}" y1="-14" y2="{ty - 16:.1f}"/>'
                    f'{lab(x + bw / 2, -17, _t("Exam"), "ax ev")}')
        _wd, dn = _ins_day(days[7 + j])
        out += (f'<g><title>{tip}</title><rect class="hit" x="{x:.1f}" y="-20" width="{slot:.1f}" height="{Hh + 40:.0f}"/>{bars}{num}{mark}'
                f'{lab(x + bw / 2, Hh + 13, _ins_letter(days[7 + j]), "ax b" if j == 0 else "ax")}'
                f'{lab(x + bw / 2, Hh + 24, dn, "ax b" if j == 0 else "ax d")}</g>')
    out += lab(7 * slot + bw / 2, Hh + 36, _t("today"), "ax d")
    x0 = 21.5 * slot
    out += lab(x0 + 1.5 * slot * 1.25 + bw / 2, -17, _t("by week"), "ax d")
    for k in range(4):
        x = x0 + k * slot * 1.25
        c, nw = wk_c[k], wk_n[k]
        h1, h2 = Hh * (c - nw) / top, Hh * nw / top
        first = days[7 + 14 + 7 * k]
        exam_here = ex is not None and 14 + 7 * k <= ex < 21 + 7 * k
        tip = (_t("Week of {day}: about {n} cards a day", day=_ins_dname(first, long=True), n=_ins_r(c)) + band(c, 2 + k)
               + mins(sum(w["answers"][14 + 7 * k:21 + 7 * k]) / 7.0) + (" &middot; " + _t("your exam") if exam_here else ""))
        try:
            fd = _dt.date.fromisoformat(first)
            l1, l2 = str(fd.day), _month(fd.month)
        except ValueError:
            l1 = l2 = ""
        out += (f'<g><title>{tip}</title><rect class="hit" x="{x:.1f}" y="-20" width="{slot * 1.2:.1f}" height="{Hh + 40:.0f}"/>'
                f'<rect class="pm" x="{x:.1f}" y="{Hh - h1:.1f}" width="{bw:.1f}" height="{h1:.1f}" rx="2"/>'
                + (f'<rect fill="url(#{pat})" x="{x:.1f}" y="{Hh - h1 - h2:.1f}" width="{bw:.1f}" height="{max(0.0, h2 - 1):.1f}" rx="2"/>' if h2 > 0.5 else "")
                + lab(x + bw / 2, Hh - h1 - h2 - 5, _ins_r(c), "ax b")
                + (lab(x + bw / 2, Hh - h1 - h2 - 17, _t("Exam"), "ax ev") if exam_here else "")
                + f'{lab(x + bw / 2, Hh + 13, l1)}{lab(x + bw / 2, Hh + 24, l2, "ax d")}</g>')
    out += f'<line class="base" x1="0" x2="{W:.0f}" y1="{Hh:.0f}" y2="{Hh:.0f}"/>'
    for sx in (6.86 * slot, 21.1 * slot):
        out += f'<line class="sep" x1="{sx:.1f}" x2="{sx:.1f}" y1="-6" y2="{Hh + 26:.0f}"/>'
    said = _t("Cards a day: the last 7 days, the next 14 by day, then 4 weeks by week")
    return f'<svg viewBox="-30 -30 676 174" role="img" aria-label="{said}">{out}</svg>'


def _ahead_weeks(xs):
    from ..ahead import weeks
    return weeks(xs)


def _ins_ahead(did, a, deck_name=""):
    """3.9.2 (Sam's picks: Your week becomes Reviews ahead): the chart of
    the next six weeks and its line. 3.9.10: nothing under it (the ways to
    pick from and Do it went); a stop of new cards that's already running
    keeps its chart, what it does, and Turn new cards back on.
    a: ahead_flow.deck_view."""
    e = _html.escape
    ways = [w for w in a.get("ways") or [] if isinstance(w, dict)]
    if not ways:
        return ""
    on = a.get("on") or "pace"
    pace = next((w for w in ways if w["key"] == "pace"), ways[0])
    days, ex = a["days"], a.get("exam")
    week = sum(a.get("past") or []) / 7.0
    uid = _re.sub(r"[^A-Za-z0-9]", "", str(did))[:20]
    name = e(str(deck_name or _t("this deck")))
    secs = a.get("secs")
    if ex is not None and 1 <= ex < 14:
        lo, hi, when = max(0, ex - 6), ex + 1, _later("Exam week") if ex >= 6 else _later("To your exam")
    elif ex is not None and 14 <= ex < 42:
        lo, hi, when = max(0, ex - 6), ex + 1, _later("Exam week")
    else:
        lo, hi, when = 7, 14, _later("In 2 weeks")
    exd = _ins_dname(_day_after(days[7], ex), long=True) if ex is not None and ex >= 0 else ""
    if exd and ex == 0:
        exd = _t("today")
    pz = a.get("pause") if isinstance(a.get("pause"), dict) else None

    def mean(xs):
        return sum(xs) / len(xs) if xs else 0

    def held(w):
        """3.9.2 (a real deck): what a stop holds back, and till when; a plan's dates in it said."""
        n, s = w.get("held") or 0, w.get("stop")
        if n < 1 or not s or 7 + int(s[1]) + 1 >= len(days):
            return ""
        ph = w.get("plan_held") or 0
        one = _ahead_r(n) == 1
        till = _ins_dname(days[7 + int(s[1]) + 1], long=True)
        if ph >= 1:
            return " " + _tn("{n} new card waits till {day}, {of} of them in your plan&rsquo;s sets.",
                             "{n} new cards wait till {day}, {of} of them in your plan&rsquo;s sets.",
                             1 if one else 2, n=_ins_r(n), day=till, of=_ins_r(ph))
        return " " + _tn("{n} new card waits till {day}.", "{n} new cards wait till {day}.", 1 if one else 2, n=_ins_r(n), day=till)

    # 3.9.10 (Sam: "just keep the graph and eliminate the call to action"): the one chart, the way it is now.
    # The ways to pick from and Do it went; a stop that's running keeps its line and its way back
    blocks, acts = "", ""
    for w in ways:
        k = w["key"]
        if k != on:
            continue
        if k == "pace":
            # 3.9.2 (a real deck: 44% of the week ahead was new cards at its pace, a guess, in one number):
            # the cards I've started first, what new ones add at my pace after it
            st, nw = mean((w.get("started") or w["cards"])[:14]), mean((w.get("new") or [0])[:14])
            says = {"n": f"<b>{_ins_r(st)}</b>", "more": f"<b>+{_ins_r(nw)}</b>",
                    "time": _hm(max(1, int(round(mean(w["answers"][:14]) * secs / 60.0)))) if secs else ""}
            if nw >= 0.5:
                line = (_t("Next 2 weeks: {n} a day from cards you&rsquo;ve started, {more} new at your pace, about {time} a day", **says)
                        if secs else _t("Next 2 weeks: {n} a day from cards you&rsquo;ve started, {more} new at your pace", **says))
            else:
                line = (_t("Next 2 weeks: {n} a day from cards you&rsquo;ve started, about {time} a day", **says)
                        if secs else _t("Next 2 weeks: {n} a day from cards you&rsquo;ve started", **says))
            line += " &middot; " + _t("this week {n}", n=_ins_r(week))
        else:
            a_, b_ = _ins_r(mean(w['cards'][lo:hi])), _ins_r(mean(pace['cards'][lo:hi]))
            line = ((_t("{when}: about {n} a day, not {other}", when=_t(when), n=f"<b>{a_}</b>", other=b_) if a_ != b_
                     else _t("{when}: about {n} a day", when=_t(when), n=f"<b>{a_}</b>"))
                    + (" &middot; " + _t("exam day about {n}", n=_ins_r(w["cards"][ex]))
                       if k != "unlocked" and ex is not None and 1 <= ex < 42 else ""))
        hid = "" if k == on else " hidden"
        blocks += (f'<div class="ahw" data-k="{k}"{hid}><div class="xline">{line}</div>'
                   f'<div class="iwk">{_ins_ahead_svg(did, a, w, uid)}</div></div>')
        # what pressing it does, said once, beside its button
        if k == on and k != "pace":
            to_exam = bool(pz and (pz.get("exam") or pz.get("kind") == "week") and exd)
            start = int((pz or {}).get("from") or 0)
            # 3.9.2's QoL pass: a start past the chart still named; before it starts, they aren't off yet
            frm = _ins_dname(_day_after(days[7], start), long=True) if start > 0 else ""
            if to_exam:
                off = (_t("No new cards in {name} from {start} till your exam, {day}.", name=name, start=frm, day=exd) if start > 0
                       else _t("No new cards in {name} till your exam, {day}.", name=name, day=exd))
            else:
                off = (_t("No new cards in {name} from {start} till you turn them back on.", name=name, start=frm) if start > 0
                       else _t("No new cards in {name} till you turn them back on.", name=name))
            act = f'<span>{off}{held(w)}</span>'  # (3.9.10: its way back is Settings › Study's, and a plan card's)
        else:
            act = ""
        if act:
            acts += f'<div class="xact" data-k="{k}"{hid}>{act}</div>'
    defs = (f'<svg class="ahdefs" width="0" height="0" aria-hidden="true"><defs><pattern id="ah{uid}" width="6" height="6" '
            f'patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" class="h1"/>'
            f'<rect width="3" height="6" class="h2"/></pattern></defs></svg>')
    return (f'<div class="isec dc-ahead">{defs}<div class="ik">{_t("Reviews ahead")}<span>&nbsp;&middot; {_t("cards a day")}</span>'
            f'<span class="ikey"><i class="sw ps"></i>{_t("done")} <i class="sw pm"></i>{_t("started")} '
            f'<i class="sw hx"></i>{_t("new cards")}</span></div>'
            f'{blocks}{acts}</div>')


def _ins_leech_row(did, c):
    """One card: its front (mine, from my copy), what it says (its topic,
    misses, when, slow, on my exam), one button and the rest behind ⋯."""
    e = _html.escape
    cid = int(c["cid"])
    bits = [e(str(c["topic"]))] if c.get("topic") else []
    bits.append(_tn("missed {n} time", "missed {n} times", int(c["lapses"]), n=int(c["lapses"])))
    if c.get("susp"):
        if c.get("day") or c.get("at"):  # my Anki day (its rollover), as every day on the board; a year ago or more, its year
            day = c.get("day") or _dt.datetime.fromtimestamp(int(c["at"]) / 1000).date().isoformat()
            try:
                old = (_dt.date.today() - _dt.date.fromisoformat(day)).days > 300
            except ValueError:
                old = False
            bits.append(_t("since {day}", day=e(_short_day(day)) + (f" {day[:4]}" if old else "")))
        if c.get("exam"):
            bits.append(f'<b class="ex">{_t("on your exam")}</b>')
    else:
        d = int(c.get("due") or 0)
        bits.append(_t("due today") if d <= 0 else _t("back tomorrow") if d == 1 else _t("back in {n} days", n=d))
    if int(c.get("secs") or 0) >= 30:
        bits.append(_t("slow: {n} s a try", n=int(c["secs"])))

    def act(a, label, cls="", title=""):
        tip_ = f' title="{title}"' if title else ""
        return f'<a class="{cls}" href="#"{tip_} onclick="{_pycmd(f"insleech:{did}:{a}:{cid}")}">{label}</a>'
    tip, knows = c.get("tip") or [], c.get("knows") or []
    # 3.9.10 (Sam: Insights is "a data only zone", nothing here adjusts a card): a crewmate's tip or
    # who has it down stay (they change no card); Bring back, Learn it fresh, Leave it out and Edit went
    if tip:
        main = act("tip", _t("{name}&rsquo;s tip", name=e(tip[0]["name"])), "sl-bt tip")
    elif knows:
        main = act("ask", _t("Ask {name}", name=e(knows[0])), "sl-bt tip",
                   _tn("{who} has it down", "{who} have it down", len(knows), who=e(", ".join(knows))))
    else:
        main = ""
    fr = e(str(c.get("front") or ""))
    return (f'<div class="sl-row"><span class="sl-q"><b title="{fr}">{fr or "&nbsp;"}</b>'
            f'<span>{" &middot; ".join(bits)}</span></span>'
            f'<span class="sl-act">{main}</span></div>')


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
    trail = (f'<div class="tmt"><a href="#" onclick="{_pycmd(f"insleech:{did}:shut:0")}">{_t("Insights")}</a> &rsaquo; '
             f'<b>{_t("Leeches")}</b>{" &middot; " + e(str(deck_name)) if deck_name else ""}</div>')
    n_out = int(L.get("out") or 0)
    # 3.9.2's audit: Leave it out's way back, on the same screen
    put = (f'<div class="tmt">{_t("{n} left out of this list", n=f"{n_out:,}")} &middot; <a href="#" '
           f'onclick="{_pycmd(f"insleech:{did}:unout:0")}">{_t("Put it back") if n_out == 1 else _t("Put them back")}</a></div>') if n_out else ""
    if not gone and not near and not kept:
        return f'<div class="dc-ins">{trail}<div class="tq0">{_t("No leeches here, and none a miss away.")}</div>{put}</div>'
    on_exam = sum(1 for c in gone if c.get("exam"))
    summ = " &middot; ".join(x for x in (
        _t("{n} Anki stopped showing you", n=f"<b>{ng:,}</b>") if ng else "",
        _t("{n} still in your reviews", n=f"<b>{nk:,}</b>") if nk else "",
        _t("{n} one miss away", n=f"<b>{nn:,}</b>") if nn else "",
        _t("{n} on your exam", n=f"{on_exam:,}") if on_exam else "") if x)
    heads = f'<a href="#" onclick="{_pycmd(f"insleech:{did}:browse:0")}">{_t("Browse")}</a>'
    out = f'{trail}<div class="sl-sum"><span>{summ}</span><span class="sl-hd">{heads}</span></div>'
    for rows, n, head, sub in ((gone, ng, _t("Anki stopped showing these"), f"{ng:,}"),
                               (near, nn, _t("One miss away"), _t("{n}, still in your reviews", n=f"{nn:,}")),
                               (kept, nk, _t("Leeches still in your reviews"), f"{nk:,}")):
        if rows:
            out += (f'<div class="isec"><div class="ik">{head}<span>&nbsp;&middot; {sub}</span></div>'
                    + "".join(_ins_leech_row(did, c) for c in rows[:LEECH_SHOW])
                    + (f'<div class="sl-plus">{_t("{n} more in Browse", n=f"{n - LEECH_SHOW:,}")}</div>' if n > LEECH_SHOW else "") + "</div>")
    out += put
    return f'<div class="dc-ins">{out}</div>'


def _ins_scope(aim):
    """3.9.2 (Sam's pick C1-A): what my exam covers, said once: since my
    last exam (the default, when it was in the last 10 weeks), since a day
    I picked, or the whole deck; Change picks a day (the date picker),
    and the other way back is a link."""
    since, why = str(aim.get("since") or ""), aim.get("since_why") or ""
    if since:
        day = _ins_dname(since, long=True)
        said = ((_t("Since {day}, the day after your last exam", day=day) if why == "last" else _t("Since {day}", day=day))
                + (" &middot; " + _tn("{n} card", "{n} cards", int(aim["since_n"])) if aim.get("since_n") is not None else ""))
        other = (f'<a class="q" href="#" onclick="{_pycmd("setscope:all")}">{_t("Whole deck")}</a>' if why == "last"
                 else f'<a class="q" href="#" title="{_t("Since your last exam, or the whole deck")}" '
                      f'onclick="{_pycmd("setscope:auto")}">{_t("As it was")}</a>')
    else:
        said = _t("Whole deck")
        other = (f'<a class="q" href="#" onclick="{_pycmd("setscope:auto")}">{_t("Since your last exam")}</a>'
                 if aim.get("since_pick") == "all" else "")
    pick = f'<span class="iexam"><a class="q" href="#" onclick="{_pycmd("scopepick")}">{_t("Change")}</a></span>'  # 3.9.5: a Qt calendar
    return f'<div class="isc">{said} &middot; {pick}{(" &middot; " + other) if other else ""}</div>'


def _insights_html(did, v):
    """3.7.9 (mock "Insights"): mine alone, worked out in my Anki. The
    header's right, the cards Anki won't show me before the next exam (a
    plan's event, or my own date: 3.8.0) that I'd be under my target on by
    then, what's not sticking yet, my week in time, Optimize FSRS when my
    newest cards fall short, and the deck's suspended leeches. 3.8.0: a
    deck's, plan or not (did, its id, in each command)."""
    _views.seen("insights", v)  # 3.9.12: its shape, checked as it's drawn
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
        was = (f'<span class="m">{_t("{pct}% the 2 weeks before", pct=round(100 * before[0] / before[1]))}</span>' if before[1] >= 50 else "")
        hd_tip = _t("This deck, first answer of each card each day: {n} of {of} right in 2 weeks", n=f"{now[0]:,}", of=f"{now[1]:,}")
        aims = " &middot; " + _t("Anki aims for {pct}%", pct=int(v.get("target") or 90)) if v.get("fsrs_on", True) else ""
        out += (f'<div class="ihd" title="{hd_tip}"><b>{pct}%</b><span>{_t("right")}{aims}'
                f'{" &middot; " + was if was else ""}</span>'
                f'{_ins_spark(r.get("days") or [])}</div>')
        from ..team import right_split
        sp = right_split(r)
        if sp:  # 3.9.2 (a real deck): a week of new cards reads as forgetting; said apart
            out += (f'<div class="tmt">{_t("{pct}% on the cards you started these 2 weeks ({n} reviews)", pct=sp[0], n=f"{sp[2]:,}")} '
                    f'&middot; {_t("{pct}% on the rest", pct=sp[1])}</div>')
    aim = v.get("aim") or {}
    hero = v.get("hero") or []
    if hero:
        k = int(aim.get("in") or 7)
        when, dn = _ins_day(aim.get("day"))
        days = _tn("{n} day", "{n} days", k, n=k)
        on = _t("{wd} {day}", wd=when, day=dn)
        # 3.7.9: named for the event only when its prep dates are what's counted; else by the day.
        # 3.8.0: my own exam date (Settings) is named too, over the whole deck
        scoped = bool(aim.get("scoped") and aim.get("name"))
        mine = aim.get("kind") == "exam"
        lab = (f'{e(str(aim["name"]))} &middot; {on} &middot; {days}' if scoped
               else f'{_t("Your exam")} &middot; {on} &middot; {days}' if mine
               else f'{_t("Before {day}", day=on)} &middot; {days}')
        target = int(v.get("target") or 90)
        whose = (_t("Started cards of the plan&rsquo;s prep sets for it that Anki won&rsquo;t show you before then, "
                    "under your {pct}% by then (FSRS)", pct=target) if scoped
                 else _t("Started cards of this deck that Anki won&rsquo;t show you before then, under your {pct}% by then (FSRS)", pct=target))
        cards = (f'<a class="tp" href="#" title="{_t("Browse them")}" onclick="{_pycmd(f"insbrowse:{did}:h")}">'
                 + _tn("{n} card", "{n} cards", len(hero)) + '</a>')
        out += (f'<div class="ihero"><div class="k">{lab}</div>'
                f'<div class="t" title="{whose}">'
                + _t("{cards} Anki won&rsquo;t show you before {day}", cards=cards, day=when) + '</div>'
                f'{_ins_scope(aim) if mine else ""}'
                # 3.9.5 (Sam's FSRS rule): Study only before a date, my exam or a plan's event
                + (f'<a class="bt" href="#" title="{_t("A filtered deck of them, the most missed first")}" '
                   f'onclick="{_pycmd(f"insstudy:{did}:h")}">{_t("Study {n} early", n=f"{len(hero):,}")}</a>'
                   if aim.get("name") else "") + '</div>')
    elif aim.get("kind") == "exam":
        # 3.9.2: my exam with nothing at risk still says what it covers, and keeps its Change; without
        # FSRS nothing was looked at (what's at risk is FSRS's), so it says only the day (the audit)
        ex_day = _ins_dname(aim.get("day"), long=True)
        ex_said = _t("Your exam, {day}: nothing at risk", day=ex_day) if aim.get("checked") else _t("Your exam, {day}", day=ex_day)
        out += f'<div class="iline">{ex_said} &middot; {_ins_scope(aim)}</div>'
    if int(v.get("behind") or 0) and v.get("pid"):
        out += '<div class="iline">' + _t("{n} new cards behind", n=f'{int(v["behind"]):,}') + '</div>'  # (3.9.10: said; You › Plans has what to do)
    rows = v.get("rows") or []
    dated = bool((v.get("aim") or {}).get("name"))  # 3.9.5 (Sam's FSRS rule): a Study only before a date
    if rows:
        # 3.9.2 (the students: "not right yet" and "forgot" read alike): Anki's own Stats' words
        out += (f'<div class="isec"><div class="ik">{_t("Not sticking yet")}<span>&nbsp;&middot; {_t("last 2 weeks")}</span>'
                f'<span class="ikey"><i class="sw st"></i>{_t("never passed")} <i class="sw fg"></i>{_t("lapsed")}</span></div>')
        for i, x in enumerate(rows):
            of, st, fg = max(1, int(x["of"])), int(x["stuck"]), int(x["forgot"])
            tip = _t("{name} · {n} cards reviewed in 2 weeks: {stuck} never passed a review yet, {forgot} lapsed after passing",
                     name=x["name"], n=of, stuck=st, forgot=fg)
            out += (f'<div class="irow" title="{e(tip)}"><span class="n"><b><a class="tp" href="#" title="{_t("Browse them")}" '
                    f'onclick="{_pycmd(f"insbrowse:{did}:{i}")}">{e(str(x["name"]))}</a></b>'
                    f'<span>{e(str(x.get("src") or ""))}</span></span>'
                    f'<span class="ib"><i class="st" style="width:{100 * st / of:.1f}%"></i>'
                    f'<i class="fg" style="left:{100 * st / of:.1f}%;width:{100 * fg / of:.1f}%"></i></span>'
                    f'<span class="c">{_t("{n} of {of}", n=f"<b>{st + fg}</b>", of=of)}</span>'
                    + (f'<a href="#" title="{_t("A filtered deck of them, the most missed first")}" '
                       f'onclick="{_pycmd(f"insstudy:{did}:{i}")}">{_t("Study {n}", n=st + fg)}</a>' if dated else "")
                    + '</div>')
        out += "</div>"
    out += _ins_map(did, v.get("map") or [], v.get("map_by"), v.get("map_at"), v.get("map_ways"))
    if v.get("ahead"):
        out += _ins_ahead(did, v["ahead"], v.get("deck_name"))
    f = v.get("fsrs")
    if f:
        f_tip = _t("Reviews of cards 1&ndash;3 days since their last review, 4 weeks: {pct}% right of {n}",
                   pct=int(f["right"]), n=f'{int(f["n"]):,}')
        f_said = _t("Newest cards {pct}% right, Anki aims for {target}%", pct=int(f["right"]), target=int(f["target"]))
        out += f'<div class="iline" title="{f_tip}">{f_said}</div>'
    h = v.get("hard")
    two = v.get("two")
    if h and two != "on":
        # 3.8.0: the Hard habit; with two buttons on there's no Hard to press. 3.9.10: said, nothing to press here
        # (Try two buttons is Settings › Study's)
        h_tip = _t("{n} reviews in 4 weeks", n=f'{int(h["n"]):,}')
        h_said = _t("You press Hard on {pct}% of reviews. Anki counts Hard as remembered.", pct=int(h["pct"]))
        out += f'<div class="iline" title="{h_tip}">{h_said}</div>'
    lee, near, kept = int(v.get("leeches") or 0), int(v.get("near") or 0), int(v.get("kept") or 0)
    lout = int(v.get("leech_out") or 0)
    if not (lee or near or kept) and lout:
        # 3.9.2's QoL pass: every one left out, the way back to them still here
        out += (f'<div class="iline">{_tn("{n} leech you left out", "{n} leeches you left out", lout, n=f"<b>{lout:,}</b>")} &middot; '
                f'<a href="#" onclick="{_pycmd(f"insleeches:{did}")}">{_t("See it") if lout == 1 else _t("See them")}</a></div>')
    elif lee or near or kept:
        # 3.8.0: from the plan card, a leech is the deck's; 3.9.2: and the ones a miss away, a view of their own,
        # and the ones Anki tagged and kept showing (Tag Only, its default since 23.10)
        b = lambda n: f"<b>{n:,}</b>"  # noqa: E731
        said = " &middot; ".join(x for x in (
            _tn("{n} leech Anki stopped showing you", "{n} leeches Anki stopped showing you", lee, n=b(lee)) if lee else "",
            (_t("{n} still in your reviews", n=b(kept)) if lee
             else _tn("{n} leech still in your reviews", "{n} leeches still in your reviews", kept, n=b(kept))) if kept else "",
            (_t("{n} one miss away", n=b(near)) if lee or kept  # alone, it says of what
             else _tn("{n} card one miss from a leech", "{n} cards one miss from a leech", near, n=b(near))) if near else "") if x)
        one = lee + near + kept == 1  # 3.9.3 (Sam): one card is "it"
        out += f'<div class="iline">{said} &middot; <a href="#" onclick="{_pycmd(f"insleeches:{did}")}">{_t("See it") if one else _t("See them")}</a></div>'
    if not out:
        return f'<div class="tq0">{_t("Insights fill in after a week of reviews.")}</div>'
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
    out, fresh, soon_any, bars = "", False, False, False
    for i, t in enumerate(cur):
        n, k, st = int(t["n"]), t.get("know"), int(t.get("started") or 0)
        soon = k is None and st > 0  # 3.9.2's audit: started, none reviewed yet: too soon to say
        fresh = fresh or (k is None and not soon)
        soon_any = soon_any or soon
        cards = _tn("{n} card", "{n} cards", n)
        said = (_t("{cards}, started, none reviewed yet: too soon to say", cards=cards) if soon
                else _t("{cards}, none started yet", cards=cards) if k is None
                else _t("{cards}, {n} started, {pct}% you’d remember now (FSRS)", cards=cards, n=f"{st:,}", pct=int(k)) if by == "fsrs"
                else _t("{cards}, {n} started, {pct}% right in their reviews these 4 weeks", cards=cards, n=f"{st:,}", pct=int(k)))
        tip = f'{t["name"]}: {said}. ' + (_t("Open it.") if t.get("kids") else _t("Browse them."))  # escaped where it's drawn
        more = '<i aria-hidden="true">&rsaquo;</i>' if t.get("kids") else ""
        bar = (f'<i class="tmb" style="width:{100 * st / n:.0f}%"></i>' if k is not None and 0 < st < n else "")
        bars = bars or bool(bar)
        out += (f'<a class="tm {"sn" if k is None else f"s{map_shade(int(k))}"}" href="#" '
                f'style="flex:{n} 1 {70 + int(150 * n / big)}px" title="{e(tip)}" '
                f'onclick="{_pycmd(f"insmap:{did}:{i}")}"><span>{e(str(t["name"]))}{more}</span>'
                f'<b>{_t("too soon") if soon else _t("new") if k is None else f"{int(k)}%"}<small> &middot; {n:,}</small></b>{bar}</a>')
    path = ""
    if trail:
        steps = [f'<a href="#" onclick="{_pycmd(f"insmapup:{did}:0")}">{_t("All")}</a>']
        steps += [f'<a href="#" onclick="{_pycmd(f"insmapup:{did}:{j}")}">{e(str(t["name"]))}</a>'
                  for j, t in enumerate(trail[:-1], 1)]
        last = trail[-1]
        steps.append(f'<b>{e(str(last["name"]))}</b>')
        lk = last.get("know")
        path = (f'<div class="tmt">{" &rsaquo; ".join(steps)} &middot; {_tn("{n} card", "{n} cards", int(last["n"]))}'
                f'{"" if lk is None else f", {int(lk)}%"} '
                f'&middot; <a href="#" onclick="{_pycmd(f"insmapall:{did}")}">{_t("Browse all")}</a></div>')
    # 3.9.2 (the students: what's the %, what's the bar?): said in the key; a tile's cards beside its %
    pct = _t("% you&rsquo;d recall now") if by == "fsrs" else _t("% right, 4 weeks")
    grey = ", ".join(w for w, on in ((_t("new"), fresh), (_t("too soon"), soon_any)) if on)
    # the key names what the map shows: the grey only with a grey tile, the bar only with a tile part started
    key = (f'{pct}: <i class="sw s0"></i>{_t("under 70")} <i class="sw s3"></i>90+' + (f' <i class="sw sn"></i>{grey}' if grey else "")
           + (f' &middot; <i class="sw bar"></i>{_t("started")}' if bars else ""))
    ways = [w for w in ways or () if isinstance(w, dict)]
    if len(ways) > 1:  # 3.8.0: another way to split it, this deck's, on this computer
        on = next((str(i) for i, w in enumerate(ways) if w.get("on")), "0")
        way = word_pick(f"insmapby:{int(did)}", _t("Split by"), [(str(i), str(w.get("name") or "?")) for i, w in enumerate(ways)], on)
        sub = f'<span>&nbsp;&middot; {_t("by {way}", way=way)}</span>'
    else:
        sub = f'<span>&nbsp;&middot; {_t("by topic, now")}</span>'
    share = (f' <a class="tmsh" href="#" title="{_t("A picture of it, or text")}" onclick="{_pycmd(f"insmapshare:{did}")}">'
             f'{_t("Share")} &rsaquo;</a>')
    # 3.8.1: by a plan's own tags, the ones no card in this deck carries (a gap in the plan's coverage)
    none = next((w.get("none") or [] for w in ways if w.get("on")), [])
    gap = ""
    if any(w.get("one") for w in ways) and not trail:
        gap = f'<div class="tmt">{_t("Everything you&rsquo;ve started is from one week, so this is by topic.")}</div>'
    if none and not trail:
        names = ", ".join(e(str(x)) for x in none[:6])
        if len(none) > 6:
            names = _t("{names} and {n} more", names=names, n=len(none) - 6)
        gap = f'<div class="tmt">{_t("No card in this deck carries {names}.", names=names)}</div>'
    return (f'<div class="isec"><div class="ik">{_t("What you know")}{sub}'
            f'<span class="ikey">{key}{share}</span></div>'
            f'{path}<div class="tmap">{out}</div>{gap}</div>')


def ahead_line(a):
    """3.9.2: the board's line when the next two weeks climb a quarter over
    this one (ahead.climb), in my most reviewed deck: the number and the
    day, what this week was, and Insights' chart. Never a warning colour."""
    did = int(a["did"])
    day = _ins_dname(a.get("day"), long=True)
    said = _t("Reviews in {deck} climb to about {n} a day by {day}", deck=f'<b>{_html.escape(str(a.get("name") or ""))}</b>',
              n=f'<b>{_ins_r(a["n"])}</b>', day=day)
    said += " &middot; " + _t("this week {n}", n=f'{int(a.get("week") or 0):,}')
    if a.get("cause"):
        said += " &middot; " + _t("you started {n} cards in 2 weeks", n=f'{int(a["cause"]):,}')
    return (f'<div class="dc-wrap ah-line"><span>&#128197;</span><span>{said}</span>'
            f'<a class="wc" href="#" onclick="{_pycmd(f"youins:{did}")}">{_t("See ahead")}</a>'
            f'<a class="wx" href="#" title="{_t("Not this week")}" onclick="{_pycmd(f"insaheadx:{did}")}">&times;</a></div>')
