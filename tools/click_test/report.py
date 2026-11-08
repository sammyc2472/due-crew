"""The report: report.json (everything), summary.txt (what a person reads
first), and the exit code: 0 all passed, 1 something failed, 2 the robot
itself broke (it says where)."""

import json
import os

BAD = ("no handler", "dead", "lost", "raised", "stuck")


OUR_VIEWS = ("main webview", "top toolbar", "bottom toolbar")


def ours(view):
    """A web view the add-on draws in: Anki's main view and its bars, and its own windows ("due crew …")."""
    return view in OUR_VIEWS or str(view).startswith("due crew")


def failures(run, probe, result):
    out = []
    if result.get("crash"):
        out.append(("robot", result["crash"][-1500:]))
    for name, p in run.parts.items():
        if not p["ok"]:
            out.append((f"part {name}", "; ".join(p["notes"])[-1500:]))
    for c in run.checks:
        if not c["ok"] and not c.get("warn"):
            out.append((c["name"], c["detail"]))
    for p in run.presses:
        if p["verdict"] in BAD:
            out.append((f"press {p['view']}: {p['cmd']} ({p['text']!r})", f"{p['verdict']}: {p['why']}"))
    pressed = {e for p in run.presses for e in p.get("errors", [])}
    for e in probe.errors:
        if e["text"][-1500:] not in pressed:
            out.append((f"raised during {e['step']}", e["text"][-1500:]))
    for e in probe.js_errors:
        if ours(e.get("view", "")):
            out.append((f"a page's script failed ({e.get('view')}) during {e['step']}",
                        f"{e['src']}:{e['line']} {e['text']}"))
    for m in probe.plan_messages:
        if not m["handled"]:
            out.append((f"plan window: {m['name']} reached no handler", m.get("why") or m["msg"]))
    return out


def write(out, run, probe, world, result, secs):
    fails = failures(run, probe, result)
    verdicts = {}
    for p in run.presses:
        verdicts[p["verdict"]] = verdicts.get(p["verdict"], 0) + 1
    warnings = [{"what": c["name"], "detail": c["detail"]} for c in run.checks if not c["ok"] and c.get("warn")]
    data = {
        "ok": not fails,
        "warnings": warnings,
        "secs": round(secs, 1),
        "result": result,
        "failures": [{"what": a, "detail": b} for a, b in fails],
        "collection": run.built,
        "parts": run.parts,
        "views": run.views,
        "windows": run.windows,
        "checks": run.checks,
        "presses": run.presses,
        "verdicts": verdicts,
        "skipped": run.skipped,
        "timings": run.timings,
        "cpu": run.cpu,
        "messages": probe.messages,
        "plan_messages": probe.plan_messages,
        "errors": probe.errors,
        "js_errors": probe.js_errors,
        "windows_opened": probe.windows,
        "links_not_opened": probe.links,
        "network_refused": probe.network,
        "tooltips": probe.tooltips,
        "screens": probe.states,
        "print_exc_calls": probe.print_exc,
        "server": {"requests": len(world.store.log), "writes": world.store.writes},
        "shots": run.shots,
    }
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(data, f, indent=1, default=str, ensure_ascii=False)
    text = summary(data)
    with open(os.path.join(out, "summary.txt"), "w") as f:
        f.write(text)
    print(text, flush=True)
    if result.get("crash"):
        return 2
    return 1 if fails else 0


def summary(d):
    L = []
    L.append(f"Due Crew click test: {'PASSED' if d['ok'] else 'FAILED'} in {d['secs']:.0f} s")
    v = (d.get("collection") or {}).get("versions") or {}
    if v:
        L.append(f"Anki {v.get('anki')} · Qt {v.get('qt')} · PyQt {v.get('pyqt')} · Python {v.get('python')} · "
                 f"Due Crew {v.get('due_crew')}")
    L.append("")
    for name, p in d["parts"].items():
        L.append(f"  {'ok ' if p['ok'] else 'BAD'} {name:<8} {p['secs'] or 0:>6.1f} s" +
                 ("" if p["ok"] else "  " + p["notes"][0][:200].replace("\n", " ")))
    L.append("")
    views = d["views"]
    L.append(f"Views: {sum(1 for v in views if v.get('ok'))} of {len(views)} reached")
    for v in views:
        L.append(f"  {'ok ' if v.get('ok') else 'BAD'} {v['name']:<20} {v.get('controls', 0):>3} controls, "
                 f"{v.get('pressed', 0):>3} pressed")
    L.append("")
    pr = d["presses"]
    L.append(f"Presses: {len(pr)} ({', '.join(f'{k} {n}' for k, n in sorted(d['verdicts'].items()))})")
    for p in pr:
        mark = "ok " if p["verdict"] not in BAD else "BAD"
        extra = ""
        if p.get("windows"):
            extra += " -> " + ", ".join(p["windows"])[:80]
        if p.get("links"):
            extra += " -> link not opened"
        L.append(f"  {mark} {p['view'][:18]:<18} {p['cmd'][:34]:<34} {p['verdict']:<10} "
                 f"{(p.get('handlers') or [''])[0] or '':.40}{extra}")
    L.append("")
    if d["skipped"]:
        L.append("Not pressed:")
        for k, why in sorted(d["skipped"].items()):
            L.append(f"  {k:<30} {why}")
        L.append("")
    if d["windows"]:
        L.append("Windows over the board:")
        for w in d["windows"]:
            L.append(f"  {'ok ' if w['esc_closes'] and w['focus_back'] else 'BAD'} "
                     f"{w['window']:<34} "
                     f"Esc closes: {w['esc_closes']} ({w['how']}); key back: {w['focus_back']}")
        L.append("")
    L.append("Checks:")
    for c in d["checks"]:
        mark = "ok " if c["ok"] else "warn" if c.get("warn") else "BAD"
        L.append(f"  {mark} {c['name']}" + ("" if c["ok"] else f"  [{c['detail'][:300]}]"))
    L.append("")
    t = d["timings"]
    if t:
        L.append("Timings: " + ", ".join(f"{k} {v}" for k, v in t.items()))
    c = d["cpu"]
    if c:
        L.append(f"CPU on the Decks screen, no input: {c['at_rest']}% of one core at rest (from {c['rest_from_s']:g} s; "
                 f"limit {c['max_at_rest']}%), {c['whole']}% over the whole {c['secs']} s ({c['how']}, {c['cores']} cores)")
        L.append("  by 5 s: " + " ".join(f"{s['total']}" for s in c["slices"]))
        L.append(f"  the page before: {c['page_before']}  after: {c['page_after']}")
    if d["network_refused"]:
        L.append(f"Network refused: {sorted(set(x['host'] for x in d['network_refused']))}")
    L.append("")
    if d["warnings"]:
        L.append(f"Warnings, not failing the run ({len(d['warnings'])}):")
        for w in d["warnings"]:
            L.append(f"  - {w['what']}: {w['detail'][:300]}")
        L.append("")
    if d["failures"]:
        L.append(f"FAILURES ({len(d['failures'])}):")
        for f in d["failures"]:
            L.append(f"  - {f['what']}")
            for line in str(f["detail"]).strip().splitlines()[-8:]:
                L.append(f"      {line[:240]}")
    else:
        L.append("No failures.")
    return "\n".join(L) + "\n"
