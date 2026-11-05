"""Cheers: doodles, the Cheer window, a landing cheer's show (flurry_js), the finish line's (finish_js).

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import html as _html
import json as _json
import re as _re

from .. import emoji_drawer as _emoji_drawer
from .. import sev as _sev
from .. import shows as _shows
from ..backend.shapes import DOODLE_INKS, clean_doodle

from .base import BOARD_FONT, accent_pair
from .page import SHOW_JS
from .windows import POP_JS


# 3.9.1, doodle cheers: drawn on paper, the same in either theme, like the pad
DOODLE_PAPER, DOODLE_LINE, DOODLE_INK = "#fffdf7", "#e6dfcc", "#2b2d29"


def doodle_html(d, accent=None, label="A drawing"):
    """3.9.1: a doodle cheer's drawing, as an SVG of its strokes on the pad's
    300 x 170, or a sign's words; "" for anything clean_doodle drops. The
    caller sets the paper behind it. accent: the sender's colour (an accent
    name; its light shade, on paper in either theme). Numbers and escaped
    words only: a doodle never carries markup or a colour of its own."""
    return _doodle_art(clean_doodle(d), accent, label)


def _doodle_art(d, accent, label):
    """doodle_html's drawing of a doodle clean_doodle has already checked
    (or None)."""
    if not d:
        return ""
    if d["k"] == "sign":
        return f'<div class="dd-sign" style="font-family:{BOARD_FONT};font-weight:700">{_html.escape(d["t"])}</div>'
    colour = accent_pair(accent)[0]
    paths = []
    for st in d["s"]:
        pts = list(zip(st[1::2], st[2::2]))
        line = "M" + " L".join(f"{x} {y}" for x, y in pts) + (" l0.1 0" if len(pts) == 1 else "")
        c = st[0] >> 1  # 0 the sender's colour, 1 black, 2 on one of ours (DOODLE_INKS)
        ink = DOODLE_INK if c == 1 else accent_pair(DOODLE_INKS[c - 2])[0] if c >= 2 else colour
        paths.append(f'<path d="{line}" stroke="{ink}" stroke-width="{6 if st[0] & 1 else 3}"/>')
    return (f'<svg class="dd-draw" viewBox="0 0 300 170" role="img" aria-label="{_html.escape(label, quote=True)}" fill="none"'
            f' stroke-linecap="round" stroke-linejoin="round">{"".join(paths)}</svg>')


def doodle_landing(cheer, entries, cfg):
    """3.9.1: what a landing cheer's doodle needs (flurry_js): its markup,
    whether it's a sign, and, with Pip on, the sender's Pip with its arms
    up to hold it (their colour and look, as cheer_pips draws them). None
    when the cheer has none."""
    d = clean_doodle((cheer or {}).get("doodle"))
    if not d:
        return None
    e = next((x for x in entries or [] if x.get("user_id") == cheer.get("from") and not x.get("you")), {})
    name = str(cheer.get("name") or e.get("name") or "?")
    out = {"html": doodle_html(d, e.get("accent"), f"{name}’s drawing"), "sign": d["k"] == "sign",
           "a": list(accent_pair(e.get("accent"))), "pip": None,
           # its caption, as on the fridge: the note under it, and who it's from (text, never markup)
           "note": str(cheer.get("note") or "")[:80], "from": name.split(" ")[0][:40], "ni": int(cheer.get("ni", -1))}
    if cfg.get("sev", True):
        out["pip"] = _sev.svg("stretch", "idle", look=e.get("look"), label=_html.escape(f"{name}’s Pip", quote=True))
    return out


CHEER_WINDOW_JS = r"""
(function () {
    var V = __VIEW__;
    var T = window.dcPop.theme(), tok = T.tok;
    var bg = tok('bg', '#ffffff', '#1c1c1c'), ink = tok('ink', '#333333', '#dfe1dc'), line = tok('line', '#e2e2da', '#3d403b'),
        well = tok('well', '#f2f2ec', '#2b2d29'), muted = tok('muted', '#6f736b', '#9a9e94'),
        accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
        you = tok('you-bg', '#e9f2e9', '#2c372b');
    var font = T.font;
    var W = 300, H = 170, MAXP = 2000, MAXS = 200, SIGN = 24, NOTE = 80, INK = '__INK__';
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) { e.className = cls; }
        if (text != null) { e.textContent = text; }
        return e;
    }
    var pop = window.dcPop.make({ id: 'dc-cheer', label: 'Cheer ' + V.name, z: 80, pad: '9vh 16px 16px' }), back = pop.back;
    var css = el('style');
    css.textContent = pop.css(
        '#dc-cheer *{box-sizing:border-box;}' +
        '#dc-cheer .cw{width:440px;max-width:100%;border-radius:14px;padding:16px 18px 14px;text-align:left;display:grid;gap:12px;font-family:' + font + ';' +
          'box-shadow:0 16px 60px rgba(0,0,0,.35);background:' + bg + ';color:' + ink + ';border:1px solid ' + line + ';font-size:13px;}' +
        '#dc-cheer button,#dc-cheer input:where(:not([type=checkbox]):not([type=radio]):not([type=range])),#dc-cheer textarea{font-family:inherit;color:inherit;line-height:normal;font-weight:400;}#dc-cheer button{cursor:pointer;}' +
        '#dc-cheer .hd{display:flex;align-items:center;gap:10px;}' +
        '#dc-cheer .hd .pp{width:40px;height:40px;flex:none;display:grid;place-items:center;}' +
        '#dc-cheer .hd .pp svg{width:44px;height:44px;overflow:visible;}' +
        '#dc-cheer .hd b{display:block;font-size:16px;}' +
        '#dc-cheer .hd small{display:block;color:' + muted + ';font-size:11.5px;}' +
        '#dc-cheer .em{display:flex;flex-wrap:wrap;gap:6px;align-items:center;}' +
        '#dc-cheer .em button{width:40px;height:36px;padding:0;border-radius:10px;border:1px solid ' + line + ';background:' + bg + ';font-size:20px;line-height:1;}' +
        '#dc-cheer .em button[aria-pressed=true]{border:2px solid ' + accent + ';background:' + you + ';}' +
        '#dc-cheer .em .ot{width:auto;min-width:66px;padding:0 10px;font-size:12px;color:' + muted + ';}' +
        '#dc-cheer .em .ot.on{border:2px solid ' + accent + ';background:' + you + ';font-size:20px;color:' + ink + ';}' +
        '#dc-cheer .em .ot[aria-expanded=true]{border-color:' + accent + ';color:' + accent + ';}' +
        '#dc-cheer .em input.pk{width:74px;height:36px;border-radius:10px;border:2px solid ' + accent + ';background:' + you + ';color:' + ink + ';font-size:20px;padding:0 8px;text-align:center;}' +
        '#dc-cheer .em input.pk::placeholder{font-size:12px;color:' + muted + ';}' +
        '#dc-cheer .em input.pk:focus{outline:none;}' +
        '#dc-cheer .dr{border:1px solid ' + line + ';border-radius:12px;padding:8px;display:grid;gap:6px;background:' + well + ';}' +
        '#dc-cheer .gt{display:flex;flex-wrap:wrap;gap:2px;}' +
        '#dc-cheer .gt button{width:32px;height:28px;border:0;background:none;border-radius:8px;font-size:16px;line-height:1;padding:0;}' +
        '#dc-cheer .gt button:hover{background:' + bg + ';}' +
        '#dc-cheer .gr{position:relative;max-height:176px;overflow-y:auto;display:flex;flex-wrap:wrap;gap:2px;align-content:flex-start;}' +
        '#dc-cheer .gr .gl{flex-basis:100%;font-size:11px;font-weight:700;color:' + muted + ';padding:4px 2px 2px;}' +
        '#dc-cheer .gr button{width:34px;height:32px;border:0;background:none;border-radius:8px;font-size:20px;line-height:1;padding:0;}' +
        '#dc-cheer .gr button:hover{background:' + bg + ';}' +
        '#dc-cheer .gr .none{flex-basis:100%;color:' + muted + ';font-size:12px;padding:6px 2px;}' +
        '#dc-cheer .sgw{display:flex;align-items:center;gap:8px;}' +
        '#dc-cheer .sg{display:inline-flex;border:1px solid ' + line + ';border-radius:99px;padding:2px;gap:2px;width:max-content;}' +
        '#dc-cheer .sg button{border:0;background:none;border-radius:99px;padding:2px 14px;font-weight:700;font-size:12px;color:' + muted + ';}' +
        '#dc-cheer .sg button[aria-pressed=true]{background:' + accent + ';color:' + accentInk + ';}' +
        '#dc-cheer .pane{display:grid;gap:8px;}' +
        '#dc-cheer .paper{width:100%;aspect-ratio:300/170;background:#fffdf7;border:1px solid #e6dfcc;border-radius:10px;overflow:hidden;position:relative;color:#2b2d29;}' +
        '#dc-cheer canvas{display:block;width:100%;height:100%;touch-action:none;cursor:crosshair;}' +
        '#dc-cheer .tl{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}' +
        '#dc-cheer .sw{width:22px;height:22px;border-radius:50%;border:2px solid ' + bg + ';box-shadow:0 0 0 1px ' + line + ';padding:0;}' +
        '#dc-cheer .sw[aria-pressed=true]{box-shadow:0 0 0 2px ' + accent + ';}' +
        '#dc-cheer .pl{border:1px solid ' + line + ';background:none;border-radius:99px;padding:1px 10px;font-size:12px;}' +
        '#dc-cheer .pl[aria-pressed=true]{border-color:' + accent + ';color:' + accent + ';font-weight:700;}' +
        '#dc-cheer .lk{border:0;background:none;padding:1px 4px;font-size:12px;color:' + accent + ';font-weight:600;}' +
        '#dc-cheer .sp{flex:1;}' +
        '#dc-cheer .ct{font-size:11px;color:' + muted + ';font-variant-numeric:tabular-nums;}' +
        '#dc-cheer .words{position:absolute;inset:0;display:grid;place-items:center;padding:10px 16px;text-align:center;font-weight:700;font-size:26px;line-height:1.15;overflow-wrap:anywhere;}' +
        '#dc-cheer .words.ph{color:#b7b1a2;}' +
        '#dc-cheer .tx{width:100%;height:32px;border-radius:8px;border:1px solid ' + line + ';background:' + bg + ';color:' + ink + ';font-size:13px;padding:0 10px;}' +
        '#dc-cheer .tx:focus{outline:2px solid ' + accent + ';outline-offset:0;}' +
        '#dc-cheer .ft{display:flex;align-items:center;gap:8px;}' +
        '#dc-cheer .go{background:' + accent + ';color:' + accentInk + ';border:1px solid transparent;border-radius:8px;padding:6px 16px;font-weight:700;font-size:13px;}' +
        '#dc-cheer .no{background:none;border:1px solid ' + line + ';border-radius:8px;padding:6px 14px;font-size:13px;}' +
        '#dc-cheer button:focus-visible{outline:2px solid ' + accent + ' !important;outline-offset:2px;}' +
        '#dc-cheer .hint{font-size:11px;color:' + muted + ';}');
    back.appendChild(css);
    var card = el('div', 'cw');
    back.appendChild(card);

    // who it's for: their Pip (or emoji) and name
    var hd = el('div', 'hd');
    if (V.pip) { var pp = el('div', 'pp'); pp.innerHTML = V.pip; hd.appendChild(pp); }
    var ht = el('div');
    ht.appendChild(el('b', null, 'Cheer ' + V.name));
    ht.appendChild(el('small', null, 'Lands after their next sync.'));
    hd.appendChild(ht);
    card.appendChild(hd);

    // the emoji: the quick picks, or any other
    var emoji = V.emojis[0], em = el('div', 'em');
    em.setAttribute('role', 'group');
    em.setAttribute('aria-label', 'Emoji');
    var quick = [];
    V.emojis.forEach(function (x) {
        var b = el('button', null, x);
        b.type = 'button';
        b.setAttribute('aria-label', 'Send ' + x);
        b.addEventListener('click', function () { unpick(); choose(x, true); });  // 3.9.2's audit: Anki's box goes too
        quick.push([x, b]);
        em.appendChild(b);
    });
    // other: a drawer of emoji (emoji_drawer.py) in the window's own look, since a page can't open the
    // computer's picker (Sam: "doesn't pop up with the emoji drawer"); its search box takes a typed or pasted one too
    var other = el('button', 'ot', 'other');
    other.type = 'button';
    other.title = 'Any emoji';
    other.setAttribute('aria-label', 'Any other emoji');
    other.setAttribute('aria-expanded', 'false');
    other.addEventListener('click', function () {
        if (V.native) { native(); } else if (drawer.style.display === 'none') { openDrawer(); } else { shut(); }
    });
    em.appendChild(other);
    // on a Mac or Windows, other opens the computer's own picker (Sam: "want the other option to just open
    // the native drawer?"): a box takes other's place, focused, and what's picked there is picked;
    // if the computer can't (Linux, or asking failed), the drawer opens instead (dcCheerNoNative)
    var pickIn = el('input', 'ot pk');
    pickIn.style.display = 'none';
    pickIn.placeholder = 'pick one';
    pickIn.maxLength = 16;
    pickIn.setAttribute('aria-label', 'Your emoji');
    em.appendChild(pickIn);
    // 3.9.2 (Sam: "the custom picker doesn't accept the custom emoji choices"): the computer's picker can't
    // type into this page, so Anki lays its own box over this one (native_emoji.catch), and hands the pick here
    function native() {
        other.style.display = 'none'; pickIn.style.display = ''; pickIn.value = ''; pickIn.blur();
        window.dcCheerNoNative = function () { unpick(); openDrawer(); };
        window.dcCheerUnpick = function () { unpick(); other.focus(); };
        window.dcCheerPicked = function (t) { var e = oneEmoji(String(t || '').trim()); if (e) { unpick(); choose(e); } };
        var r = pickIn.getBoundingClientRect();
        // 3.9.2's audit: Anki's box sits where "pick one" was; a scroll or a resize moves the page under it,
        // so either puts it away (other again, to pick once more)
        window.addEventListener('resize', away);
        back.addEventListener('scroll', away, true);
        if (typeof pycmd !== 'undefined') {
            pycmd('duecrew:emojipicker:' + [r.left, r.top, r.width, r.height].map(function (v) { return Math.max(0, Math.round(v)); }).join(':') + '|' + window.dcBK);
        } else { window.dcCheerNoNative(); }
    }
    function unpick() {
        if (pickIn.style.display !== 'none' && typeof pycmd !== 'undefined') { pycmd('duecrew:emojipickeroff|' + window.dcBK); }
        pickIn.style.display = 'none'; other.style.display = '';
        window.removeEventListener('resize', away);
        back.removeEventListener('scroll', away, true);
    }
    // not `moved`: a var of that name once overwrote the open's motion flag (3.9.2's QoL pass)
    function away() { if (pickIn.style.display !== 'none') { unpick(); } }
    pickIn.addEventListener('input', function () {
        var t = oneEmoji(pickIn.value.trim());
        if (t) { unpick(); choose(t); } else if (pickIn.value.trim()) { pickIn.value = ''; }
    });
    card.appendChild(em);
    var drawer = el('div', 'dr'), find = el('input', 'tx'), gt = el('div', 'gt'), gr = el('div', 'gr'), none = el('div', 'none', 'Nothing by that name. Paste one in here instead.');
    drawer.style.display = 'none';
    find.placeholder = 'Find one: heart, coffee, owl…';
    find.setAttribute('aria-label', 'Find an emoji');
    drawer.appendChild(find);
    drawer.appendChild(gt);
    drawer.appendChild(gr);
    var cells = [], labels = [];
    V.drawer.forEach(function (g) {
        var lab = el('div', 'gl', g[0]);
        gr.appendChild(lab);
        labels.push([lab, []]);
        var tab = el('button', null, g[1][0][0]);
        tab.type = 'button';
        tab.title = g[0];
        tab.setAttribute('aria-label', g[0]);
        tab.addEventListener('click', function () { if (find.value) { find.value = ''; filter(); } gr.scrollTop = lab.offsetTop; });
        gt.appendChild(tab);
        g[1].forEach(function (x) {
            var b = el('button', null, x[0]);
            b.type = 'button';
            b.title = x[1];
            b.setAttribute('aria-label', x[0] + ' ' + x[1]);
            b.addEventListener('click', function () { choose(x[0]); });
            gr.appendChild(b);
            cells.push([b, (' ' + x[1]).toLowerCase(), lab]);
            labels[labels.length - 1][1].push(b);
        });
    });
    gr.appendChild(none);
    function oneEmoji(s) {
        var first = '';
        if (s && window.Intl && Intl.Segmenter) {
            var it = new Intl.Segmenter().segment(s)[Symbol.iterator]().next();
            first = it.done ? '' : it.value.segment;
        } else if (s) { first = Array.from(s)[0]; }
        var low = [0xA9, 0xAE, 0x203C, 0x2049, 0x2122, 0x2139];  // shapes.EMOJI_LOW (the suite checks): © ® ‼ ⁉ ™ ℹ
        // a letter or digit of any script (あ, 中, ①) isn't one either (3.9.2's QoL pass; shapes._first_grapheme the same)
        return first && !/[A-Za-z0-9\s]/.test(first) && !/^[\p{L}\p{N}]/u.test(first)
            && (first.charCodeAt(0) >= 0x2190 || low.indexOf(first.charCodeAt(0)) >= 0) ? first : '';
    }
    function filter() {
        var q = find.value.trim().toLowerCase(), shown = 0;
        cells.forEach(function (c) {
            var on = !q || c[1].indexOf(' ' + q) >= 0;
            c[0].style.display = on ? '' : 'none';
            if (on) { shown++; }
        });
        labels.forEach(function (l) { l[0].style.display = !q && l[1].length ? '' : 'none'; });
        none.style.display = shown ? 'none' : '';
    }
    find.addEventListener('input', function () {
        var typed = oneEmoji(find.value.trim());
        if (typed) { choose(typed); return; }
        filter();
    });
    filter();
    card.appendChild(drawer);
    function openDrawer() {
        drawer.style.display = '';
        other.setAttribute('aria-expanded', 'true');
        find.value = '';
        filter();
        gr.scrollTop = 0;
        find.focus();
    }
    function shut() {
        drawer.style.display = 'none';
        other.setAttribute('aria-expanded', 'false');
    }
    function choose(x, stay) {
        var q = V.emojis.indexOf(x) >= 0;
        other.textContent = q ? 'other' : x;
        other.className = q ? 'ot' : 'ot on';
        other.setAttribute('aria-label', q ? 'Any other emoji' : 'Send ' + x + ' (choose another)');
        pick(x);
        shut();
        if (!stay) { other.focus(); }  // a quick pick keeps the key on the emoji pressed (3.9.2's QoL pass)
    }
    function pick(x) {
        emoji = x;
        quick.forEach(function (q) { q[1].setAttribute('aria-pressed', q[0] === x ? 'true' : 'false'); });
    }
    pick(emoji);

    // Draw · Sign (3.9.1): a drawing, or words their Pip holds up; both optional, so both start shut and
    // the window is just the emoji and the note (Sam: "they don't always need to send a doodle / sign");
    // a press opens one, a second press on it shuts it, and only what's open is sent
    var mode = '', sgw = el('div', 'sgw'), sg = el('div', 'sg');
    sgw.appendChild(el('span', 'hint', 'Add'));
    sg.setAttribute('role', 'group');
    sg.setAttribute('aria-label', 'Add');
    var tabs = {};
    [['draw', 'Draw'], ['sign', 'Sign']].forEach(function (x) {
        var b = el('button', null, x[1]);
        b.type = 'button';
        b.addEventListener('click', function () { show(mode === x[0] ? '' : x[0]); });
        tabs[x[0]] = b;
        sg.appendChild(b);
    });
    sgw.appendChild(sg);
    card.appendChild(sgw);

    var draw = el('div', 'pane'), paper = el('div', 'paper'), cv = el('canvas');
    cv.width = W * 2;
    cv.height = H * 2;
    cv.setAttribute('aria-label', 'Draw here');
    paper.appendChild(cv);
    draw.appendChild(paper);
    // pen: bit 0 thick; pen >> 1 the colour: 0 the sender's, 1 black, 2 on one of ours (V.inks, DOODLE_INKS's order)
    var inks = V.inks.map(function (x, i) { return [i + 2, x[0], x[1]]; });
    if (V.mine >= 0 && inks[V.mine]) { var m = inks.splice(V.mine, 1)[0]; inks.unshift([m[0], m[1], 'My colour']); }
    inks.push([1, INK, 'Black']);
    var strokes = [], live = null, pen = (inks[0][0] << 1) | 1;
    function inkOf(p) { var c = p >> 1; return c === 1 ? INK : c >= 2 && V.inks[c - 2] ? V.inks[c - 2][0] : V.pen; }
    var cx = cv.getContext('2d');
    function points() { return strokes.reduce(function (a, s) { return a + s.p.length; }, 0); }
    function paint() {
        cx.setTransform(cv.width / W, 0, 0, cv.height / H, 0, 0);
        cx.clearRect(0, 0, W, H);
        cx.lineCap = 'round';
        cx.lineJoin = 'round';
        strokes.forEach(function (s) {
            cx.strokeStyle = inkOf(s.pen);
            cx.lineWidth = s.pen & 1 ? 6 : 3;
            cx.beginPath();
            s.p.forEach(function (q, i) { if (i) { cx.lineTo(q[0], q[1]); } else { cx.moveTo(q[0], q[1]); cx.lineTo(q[0] + 0.1, q[1]); } });
            cx.stroke();
        });
        var n = points();
        count.textContent = n > MAXP - 500 ? n.toLocaleString() + ' / ' + MAXP.toLocaleString() : '';
        caption();
    }
    function at(e) {
        var r = cv.getBoundingClientRect();
        return [Math.max(0, Math.min(W, Math.round((e.clientX - r.left) / r.width * W))),
                Math.max(0, Math.min(H, Math.round((e.clientY - r.top) / r.height * H)))];
    }
    cv.addEventListener('pointerdown', function (e) {
        if (strokes.length >= MAXS || points() >= MAXP) { return; }
        cv.setPointerCapture(e.pointerId);
        live = { pen: pen, p: [at(e)] };
        strokes.push(live);
        paint();
    });
    cv.addEventListener('pointermove', function (e) {
        if (!live || points() >= MAXP) { return; }
        var q = at(e), l = live.p[live.p.length - 1];
        if (Math.abs(q[0] - l[0]) + Math.abs(q[1] - l[1]) >= 2) { live.p.push(q); paint(); }
    });
    function lift() { live = null; }
    cv.addEventListener('pointerup', lift);
    cv.addEventListener('pointercancel', lift);

    var tl = el('div', 'tl'), swatches = [], widths = [];
    inks.forEach(function (x) {
        var b = el('button', 'sw');
        b.type = 'button';
        b.style.background = x[1];
        b.title = x[2];
        b.setAttribute('aria-label', x[2]);
        b.addEventListener('click', function () { pen = (pen & 1) | (x[0] << 1); tools(); });
        swatches.push([x[0], b]);
        tl.appendChild(b);
    });
    [['Thin', 0], ['Thick', 1]].forEach(function (x) {
        var b = el('button', 'pl', x[0]);
        b.type = 'button';
        b.addEventListener('click', function () { pen = (pen & ~1) | x[1]; tools(); });
        widths.push([x[1], b]);
        tl.appendChild(b);
    });
    tl.appendChild(el('span', 'sp'));
    var count = el('span', 'ct');
    tl.appendChild(count);
    var undo = el('button', 'lk', 'Undo'), clear = el('button', 'lk', 'Clear');
    undo.type = clear.type = 'button';
    undo.addEventListener('click', function () { strokes.pop(); paint(); });
    clear.addEventListener('click', function () { strokes = []; paint(); });
    tl.appendChild(undo);
    tl.appendChild(clear);
    draw.appendChild(tl);
    function tools() {
        swatches.forEach(function (s) { s[1].setAttribute('aria-pressed', (pen >> 1) === s[0] ? 'true' : 'false'); });
        widths.forEach(function (w) { w[1].setAttribute('aria-pressed', (pen & 1) === w[0] ? 'true' : 'false'); });
    }
    tools();
    card.appendChild(draw);

    var sign = el('div', 'pane'), signIn = el('input', 'tx'), sp = el('div', 'paper'), words = el('div', 'words ph', "you've got this");
    signIn.maxLength = SIGN;
    signIn.placeholder = "you've got this";
    signIn.setAttribute('aria-label', 'What your Pip holds up');
    signIn.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); send(); } });  // as the note's
    signIn.addEventListener('input', function () {
        var s = signIn.value.replace(/\s+/g, ' ').trim();
        words.textContent = s || "you've got this";
        words.className = s ? 'words' : 'words ph';
        caption();
    });
    sp.appendChild(words);
    sign.appendChild(signIn);
    sign.appendChild(sp);
    sign.appendChild(el('div', 'hint', 'A few words for your Pip to hold up when it lands. ' + SIGN + ' letters at most.'));
    card.appendChild(sign);
    function show(m) {
        mode = m;
        draw.style.display = m === 'draw' ? '' : 'none';
        sign.style.display = m === 'sign' ? '' : 'none';
        tabs.draw.setAttribute('aria-pressed', m === 'draw' ? 'true' : 'false');
        tabs.sign.setAttribute('aria-pressed', m === 'sign' ? 'true' : 'false');
        if (m === 'sign') { signIn.focus(); }
        caption();
    }
    // 3.9.1 (Sam): with a drawing or a sign, the note goes under it, "from" me, as a caption
    var note = null;
    function caption() {
        if (!note) { return; }
        var has = mode === 'sign' ? !!signIn.value.trim() : mode === 'draw' && strokes.length > 0;
        note.placeholder = has ? 'A caption under it (optional)' : 'Add a note (optional)';
    }
    show('');

    note = el('input', 'tx');
    note.maxLength = NOTE;
    note.placeholder = 'Add a note (optional)';
    note.setAttribute('aria-label', 'Note');
    note.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); send(); } });
    card.appendChild(note);

    var ft = el('div', 'ft'), go = el('button', 'go', '🎉 Send'), no = el('button', 'no', 'Cancel');
    go.type = no.type = 'button';
    ft.appendChild(go);
    ft.appendChild(el('span', 'sp'));
    ft.appendChild(no);
    card.appendChild(ft);
    paint();

    function doodle() {
        if (mode === 'sign') {
            var t = signIn.value.replace(/\s+/g, ' ').trim();
            return t ? { k: 'sign', t: t } : null;
        }
        if (mode !== 'draw' || !strokes.length) { return null; }  // shut: nothing goes, what's drawn stays for a reopen
        return { k: 'draw', s: strokes.map(function (s) {
            var out = [s.pen];
            s.p.forEach(function (q) { out.push(q[0], q[1]); });
            return out;
        }) };
    }
    var close = pop.close;
    function send() {
        var p = { to: V.uid, emoji: emoji, note: note.value.replace(/\s+/g, ' ').trim().slice(0, NOTE), doodle: doodle() };
        close();
        if (typeof pycmd !== 'undefined') { pycmd('duecrew:cheersend:' + encodeURIComponent(JSON.stringify(p)) + '|' + window.dcBK); }
    }
    go.addEventListener('click', send);
    no.addEventListener('click', close);
    // Esc puts away what's open in it first (Anki's box, then the drawer); the shade closes it
    pop.show(card, {
        esc: function () {
            if (pickIn.style.display !== 'none') { unpick(); other.focus(); }
            else if (drawer.style.display !== 'none') { shut(); other.focus(); } else { close(); }
        },
        shade: close,
        closing: unpick  // 3.9.2: other's box, if it's up, goes with the window
    });
    quick[0][1].focus();
})();
""".replace("__INK__", DOODLE_INK)


def cheer_overlay_js(view):
    """3.9.1 (Sam: "make the cheers and doodles modals in the design language
    of our add on"): the Cheer window, drawn on the Decks screen in the
    board's own look (its tokens, so Settings › Theme and Accent hold), in
    place of the Qt window. view: {uid, name, emojis (the quick picks), pip
    (card_sev's markup, or None with Pip off), pen (my accent's light shade,
    the drawing's colour, on paper in either theme)}. Send goes as one
    duecrew:cheersend command, its payload URI-encoded JSON; the glue checks
    every field again (cheer_allowed, clean_note, clean_doodle) and that the
    uid is a crewmate. The name and emoji go in as text, never markup.
    Also: "other"'s drawer (emoji_drawer), and every accent for the pad
    (Sam: "make all of our colors available in the doodles feature"), in
    DOODLE_INKS's order, mine first."""
    pen = view.get("pen") if _re.fullmatch(r"#[0-9a-fA-F]{6}", str(view.get("pen") or "")) else accent_pair(None)[0]
    inks = [[accent_pair(n)[0], n.capitalize()] for n in DOODLE_INKS]
    data = {"uid": str(view.get("uid") or ""), "name": str(view.get("name") or "?"),
            "emojis": [str(x) for x in view.get("emojis") or []][:8] or ["\U0001F389"],
            "pip": view.get("pip") or "", "pen": pen, "inks": inks,
            "mine": next((i for i, x in enumerate(inks) if x[0].lower() == pen.lower()), -1),
            "drawer": _emoji_drawer.view(), "native": bool(view.get("native"))}
    return POP_JS + CHEER_WINDOW_JS.replace("__VIEW__", _json.dumps(data).replace("</", "<\\/"))


CHEER_PIP = 92  # 3.8.22: a crewmate's Pip popping in with their cheer


def cheer_pips(cheers, entries, cfg, most=3):
    """3.8.22, cheers with Pips (Sam's pick, round three): who sent the
    cheers that just landed, as their Pips, each once, in the order they
    came, three at most: [{svg, a: [light, dark], emoji, name, note, poses}].
    A cheer lands only from someone I added: a mutual friend comes in their
    colour and look, anyone else plain. [] with Pip off. Our own markup; a
    name is only its label, escaped. 3.9.0: the poses a show needs (popping
    up, jumping, springing out of a present, still), and the name and
    note, which the show puts in as text."""
    if not cfg.get("sev", True):
        return []
    by = {e.get("user_id"): e for e in entries or [] if not e.get("you")}
    out, seen = [], set()
    for ch in cheers or []:
        u = ch.get("from")
        if not u or u in seen:
            continue
        seen.add(u)
        e = by.get(u) or {}
        name = str(ch.get("name") or e.get("name") or "?")
        label = _html.escape(f'{name}’s Pip', quote=True)
        look = e.get("look")
        note = next((str(c.get("note")) for c in cheers if c.get("from") == u and c.get("note")), "")
        out.append({"svg": _sev.svg("hello", "popup", look=look, label=label),
                    "a": list(accent_pair(e.get("accent"))), "emoji": str(ch.get("emoji") or ""),
                    "name": name.split(" ")[0][:40], "note": note[:140],
                    "poses": {"hello": _sev.svg("hello", "popup", look=look, label=label),
                              "jump": _sev.svg("hop", "jump", look=look, label=label),
                              "cheer": _sev.svg("cheer", "giftspin", look=look, label=label),
                              "idle": _sev.svg("idle", look=look, label=label)}})
        if len(out) >= most:
            break
    return out


def and_more(names, most=3):
    """"Dre", "Dre and Mo", "Dre, Mo and Ana", "Dre, Mo, Ana and 2 more"."""
    names = [str(n) for n in names]
    if len(names) > most:
        return ", ".join(names[:most]) + f" and {len(names) - most} more"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1] if names else ""


def finish_js(view):
    """3.9.6, the finish line (Sam's pick): a plan's last set's last card
    seen, its show over the whole Decks screen (show.js's DCShow.finish):
    the path fills as Pip hops along it, breaks the tape, a grad cap lands
    on it; seven seconds, its banner three more, a click or Esc ends it.
    Reduce motion: the banner alone, Pip still in its cap. view
    (plan_flow._finish_view): {pid, name, sets, cards, weeks, a, pip}; the
    colours are the board's tokens, read off the page. Injected by
    board_eval, never in the board's HTML; the plan's name goes in as text."""
    sets = int(view.get("sets") or 0)
    num = {"sets": sets, "cards": int(view.get("cards") or 0), "weeks": int(view.get("weeks") or 0)}
    bits = [f"{sets:,} set{'s' if sets != 1 else ''}", f"{num['cards']:,} card{'s' if num['cards'] != 1 else ''}"]
    if num["weeks"]:
        bits.append(f"{num['weeks']:,} week{'s' if num['weeks'] != 1 else ''}")
    pip = view.get("pip") or None
    data = {"name": str(view.get("name") or "the plan"), "sub": " · ".join(bits), "n": max(1, min(40, sets)),
            "share": "duecrew:planjoyshare:" + _re.sub(r"[^A-Za-z0-9_-]", "", str(view.get("pid") or "")) + ":fin",
            "a": list(view.get("a") or ["#2e7d32", "#7cc47f"]), "pip": pip, "ms": int(_shows.FINISH_SECONDS * 1000),
            "linger": int(_shows.BANNER_SECONDS * 1000)}
    return """
    (function () {
        var D = %s;
        var dc = document.getElementById('due-crew'), cs = dc ? getComputedStyle(dc) : null;
        var night = /night/i.test(document.body.className) || (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        function tok(name, light, dark) { var v = cs && cs.getPropertyValue('--dc-' + name).trim(); return v || (night ? dark : light); }
        D.bg = tok('bg', '#ffffff', '#1c1c1c'); D.ink = tok('ink', '#333333', '#dfe1dc'); D.line = tok('line', '#e2e2da', '#3d403b');
        D.accent = tok('accent', '#2e7d32', '#7cc47f'); D.accentInk = tok('accent-ink', '#ffffff', '#122912');
        D.amb = tok('hours', '#b26a00', '#dda45c'); D.mut = tok('muted', '#6f736b', '#9a9e94');
        var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(D.bg), n = m ? [m[1], m[2], m[3]].map(function (h) { return parseInt(h, 16); })
            : (/(\\d+)\\D+(\\d+)\\D+(\\d+)/.exec(D.bg) || [0, 255, 255, 255]).slice(1).map(Number);
        D.dark = n[0] * 0.299 + n[1] * 0.587 + n[2] * 0.114 < 128;
        D.rm = !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        D.sevcss = %s;
        %s
        (function go(n) {  // a cheer's show that landed with it plays first (twenty seconds at most)
            if (document.getElementById('dc-show') && n < 40) { setTimeout(function () { go(n + 1); }, 500); return; }
            if (window.DCShow && window.DCShow.finish) { window.DCShow.finish(D); }
        })(0);
    })();
    """ % (_json.dumps(data).replace("</", "<\\/"), _json.dumps(_sev.CSS).replace("</", "<\\/") if pip else "null", SHOW_JS)


def flurry_js(emojis, banner_text, back=None, notes=None, season=None, pips=None, show=None, doodle=None):
    """Injected via web.eval after render — never inline in board HTML.
    Banner takes its colors from the board's tokens (so Settings → Theme
    holds), the page's night classes only when the board is off. When `back` is
    (uid, emoji) — a single sender — the banner is clickable to return the
    cheer, and stays up a little longer. `notes`: sender-written lines shown
    under the title (textContent: never markup), which also buy time.
    pips (3.8.22, cheer_pips): the senders' Pips. Each pops up at the
    board's edge in turn, tosses its cheer onto my row and ducks back down,
    in place of the flurry; with Reduce motion they stand still in the
    banner. show (3.9.0, shows.next_show): with the Pips, a show over the
    whole Decks screen in place of the toss (show.js), the banner at the
    top; the toss if the show can't play. doodle (3.9.1, doodle_landing):
    a drawing or a sign came with it. The sender's Pip pops up at the
    board's corner holding it up, in place of the show and the toss, and
    ducks down as the banner goes; with Pip off or Reduce motion it sits in
    the banner, still, on its paper."""
    # 2.10: about one flake in three is the season's
    emoji_list = _json.dumps(list(emojis) * 2 + list(season or []) if season else list(emojis))
    # 3.9.7 (the security review): every fragment as its siblings, no </ to end a script it might one day sit in
    banner = _json.dumps(banner_text).replace("</", "<\\/")
    notes_json = _json.dumps([str(n) for n in (notes or [])][:3]).replace("</", "<\\/")
    back_cmd = _json.dumps(f"duecrew:cheerback:{back[0]}:{back[1]}" if back else None).replace("</", "<\\/")
    pips_json = _json.dumps([{"svg": p["svg"], "a": p["a"], "emoji": p.get("emoji") or ""} for p in (pips or [])][:3]).replace("</", "<\\/")
    show_json = _json.dumps(show if show in _shows.SHOWS and pips else None)
    senders_json = _json.dumps([dict(p.get("poses") or {}, name=p.get("name") or "", note=p.get("note") or "", emoji=p.get("emoji") or "\U0001F389", a=p["a"])
                                for p in (pips or [])][:3]).replace("</", "<\\/") if show else "[]"
    season_one = _json.dumps((list(season or []) or [""])[0])
    doodle_json = _json.dumps({k: doodle.get(k) for k in ("html", "sign", "a", "pip", "note", "from", "ni")}
                              if doodle and doodle.get("html") else None).replace("</", "<\\/")
    return """
    (function() {
        if (document.getElementById('dc-flurry')) { return; }
        var night = /night/i.test(document.body.className) ||
            (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
        // 2.9: colors come from the board, which already follows Settings ->
        // Theme and Accent; Anki's night class is only the fallback
        var dcBoard = document.getElementById('due-crew');
        var dcStyle = dcBoard ? getComputedStyle(dcBoard) : null;
        function tok(name, light, dark) {
            var v = dcStyle && dcStyle.getPropertyValue('--dc-' + name).trim();
            return v || (night ? dark : light);
        }
        var dcBg = tok('bg', '#ffffff', '#1c1c1c'), dcInk = tok('ink', '#333333', '#dfe1dc'),
            dcLine = tok('line', '#e2e2da', '#3d403b'), dcWell = tok('well', '#f2f2ec', '#2b2d29'),
            accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
            warn = tok('hours', '#b26a00', '#dda45c');
        var backCmd = %s;
        var banner = document.createElement('div');
        var title = document.createElement('div');
        title.textContent = %s;
        banner.appendChild(title);
        var notes = %s, noteEls = [];
        for (var n = 0; n < notes.length; n++) {
            var line = document.createElement('div');
            line.textContent = '\u201c' + notes[n] + '\u201d';
            line.style.cssText = 'font-size:13px;font-weight:400;margin-top:4px;opacity:0.9;max-width:60vw;';
            banner.appendChild(line);
            noteEls.push(line);
        }
        banner.style.cssText = 'position:fixed;top:18vh;left:50%%;transform:translateX(-50%%);' +
            'z-index:70;border-radius:12px;padding:10px 20px;font-weight:700;font-size:15px;' +
            'text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.3);transition:opacity 0.5s;' +
            'background:' + dcBg + ';color:' + dcInk + ';border:1px solid ' + accent + ';';
        var linger = 2600 + (notes.length ? 2500 : 0);
        if (backCmd && typeof pycmd !== 'undefined') {
            linger = 5000;
            banner.style.cursor = 'pointer';
            var sub = document.createElement('div');
            sub.textContent = 'click to send one back';
            sub.style.cssText = 'font-size:11px;font-weight:400;opacity:0.7;margin-top:2px;';
            banner.appendChild(sub);
            banner.addEventListener('click', function() {
                pycmd(backCmd + '|' + window.dcBK);
                // once: it fades as it goes, no second send
                banner.style.pointerEvents = 'none';
                banner.style.transition = 'opacity 0.25s';
                banner.style.opacity = '0';
                setTimeout(function() { banner.remove(); }, 300);
            });
        }
        var pips = %s, still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        // 3.9.1: a doodle buys time, on its paper (light in either theme, like the pad it was drawn on)
        var dd = %s, held = !!(dd && dd.pip && pips.length && !still && document.body.animate);
        function paper(w, h, caption) {
            var p = document.createElement('div');
            p.style.cssText = 'width:' + w + 'px;box-sizing:border-box;background:%s;border:1px solid %s;' +
                'border-radius:8px;overflow:hidden;color:%s;font-weight:400;text-align:left;';
            var art = document.createElement('div');
            art.style.cssText = 'height:' + h + 'px;display:grid;place-items:center;overflow:hidden;';
            art.innerHTML = dd.html;
            p.appendChild(art);
            var v = art.querySelector('svg');
            if (v) { v.style.cssText = 'width:100%%;height:100%%;display:block;'; }
            var words = art.querySelector('.dd-sign');
            if (words) { words.style.cssText += ';font-size:' + Math.round(h * 0.22) + 'px;line-height:1.15;text-align:center;padding:4px 10px;overflow-wrap:anywhere;'; }
            if (caption) {
                // 3.9.1 (Sam): the note it came with under it, and who it's from, as on the fridge
                var cap = document.createElement('div');
                cap.style.cssText = 'padding:0 8px 6px;font-size:11px;line-height:1.3;';
                if (dd.note) {
                    var q = document.createElement('div');
                    q.textContent = '\u201c' + dd.note + '\u201d';
                    q.style.cssText = 'display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;';
                    cap.appendChild(q);
                }
                var by = document.createElement('div');
                by.textContent = 'from ' + dd.from;
                by.style.cssText = 'font-weight:700;opacity:.75;margin-top:2px;';
                cap.appendChild(by);
                p.appendChild(cap);
            }
            return p;
        }
        if (dd) {
            linger += 2500;
            if (!held) { var mini = paper(150, 85, false); mini.style.margin = '8px auto 2px'; banner.insertBefore(mini, sub || null); }
            else if (dd.ni >= 0 && noteEls[dd.ni]) { noteEls[dd.ni].remove(); }  // its note goes under it, not in the banner too
        }
        // 3.8.22: the board's own theme decides a Pip's colour, light or dark
        function dark(c) {
            var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})/i.exec(c), n = m ? [m[1], m[2], m[3]].map(function(h) { return parseInt(h, 16); })
                : (/(\\d+)\\D+(\\d+)\\D+(\\d+)/.exec(c) || [0, 255, 255, 255]).slice(1).map(Number);
            return n[0] * 0.299 + n[1] * 0.587 + n[2] * 0.114 < 128;
        }
        var boardDark = dark(dcBg), muted = tok('muted', '#6f736b', '#9a9e94');
        function pipEl(p, size) {
            var w = document.createElement('span');
            w.style.cssText = 'display:inline-block;line-height:0;width:' + size + 'px;height:' + size + 'px;' +
                '--sv-a:' + (boardDark ? p.a[1] : p.a[0]) + ';--sv-line:' + dcLine + ';--sv-amb:' + warn + ';--sv-mut:' + muted + ';';
            w.innerHTML = p.svg;
            var v = w.querySelector('svg');
            if (v) { v.setAttribute('width', size); v.setAttribute('height', size); v.style.overflow = 'visible'; }
            return w;
        }
        if (pips.length && still) {
            // standing still beside who sent it, no flurry
            var who = document.createElement('div');
            who.style.cssText = 'display:flex;justify-content:center;gap:4px;margin:-4px 0 0;';
            pips.forEach(function(p) { var e = pipEl(p, 52); var v = e.querySelector('svg'); if (v) { v.classList.add('rest'); } who.appendChild(e); });
            banner.insertBefore(who, title);
        }
        document.body.appendChild(banner);
        // it comes in as it goes out, a fade (and a drop, with motion); never there in one frame
        if (banner.animate) {
            banner.animate([{ opacity: 0, transform: 'translateX(-50%%) translateY(' + (still ? 0 : -10) + 'px)' },
                            { opacity: 1, transform: 'translateX(-50%%)' }], { duration: 280, easing: 'ease-out' });
        }
        setTimeout(function() { banner.style.opacity = '0'; }, linger);
        setTimeout(function() { banner.remove(); }, linger + 600);
        if (still) { return; }
        if (held) {
            // 3.9.1: their Pip holds it up at the board's corner, then ducks down as the banner goes
            var hb = document.getElementById('due-crew'), hr = hb ? hb.getBoundingClientRect() : null;
            var hvh = window.innerHeight, base = Math.min(hvh, hr ? hr.bottom : hvh), HW = 190, HH = 236;  // room for its caption
            var right = Math.min(window.innerWidth - 8, hr ? hr.right : window.innerWidth - 8);
            var hbox = document.createElement('div');
            hbox.setAttribute('aria-hidden', 'true');
            hbox.style.cssText = 'position:fixed;z-index:71;pointer-events:none;overflow:hidden;left:' + Math.max(8, right - HW - 8) +
                'px;top:' + (base - HH) + 'px;width:' + HW + 'px;height:' + HH + 'px;';
            var lift = document.createElement('div');
            lift.style.cssText = 'display:flex;flex-direction:column;align-items:center;padding-top:6px;transform:translateY(' + HH + 'px);';
            var sign = paper(170, 96, true);
            sign.style.transform = 'rotate(-3deg)';
            sign.style.boxShadow = '0 6px 16px rgba(0,0,0,.18)';
            var sticks = document.createElement('div');
            sticks.style.cssText = 'display:flex;justify-content:space-between;width:56px;height:28px;margin-top:-2px;';  // long enough for a hat under it
            sticks.innerHTML = '<i style="width:3px;background:#b08a5a;border-radius:2px"></i><i style="width:3px;background:#b08a5a;border-radius:2px"></i>';
            var holder = pipEl({ svg: dd.pip, a: dd.a }, 92);
            holder.style.marginTop = '-40px';
            lift.appendChild(sign); lift.appendChild(sticks); lift.appendChild(holder);
            hbox.appendChild(lift);
            document.body.appendChild(hbox);
            lift.animate([{ transform: 'translateY(' + HH + 'px)' }, { transform: 'translateY(0px)' }],
                         { duration: 600, easing: 'cubic-bezier(.2,.9,.3,1.25)', fill: 'forwards' });
            setTimeout(function() {
                lift.animate([{ transform: 'translateY(0px)' }, { transform: 'translateY(' + HH + 'px)' }],
                             { duration: 380, easing: 'ease-in', fill: 'forwards' }).onfinish = function() { hbox.remove(); };
            }, linger);
            return;
        }
        var show = %s;
        if (show && pips.length && document.body.animate) {
            // 3.9.0: a show over the whole Decks screen, the banner at its top (show.js)
            %s
            var played = window.DCShow && window.DCShow.play(show, { senders: %s, dark: boardDark, line: dcLine, amb: warn, mut: muted,
                accent: accent, accentInk: accentInk, ink: dcInk, sevcss: %s });
            if (played) { banner.style.top = '12px'; return; }
        }
        if (pips.length && document.body.animate) {
            var dc = document.getElementById('due-crew'), vw = window.innerWidth, vh = window.innerHeight;
            var edge = dc ? dc.getBoundingClientRect().right : vw * 0.8, size = %d, season = %s;
            pips.forEach(function(p, i) { setTimeout(function() { toss(p, i); }, i * 1150); });
            function where() {
                // my row's name, if it's on screen; else under the banner
                var me = dc && dc.querySelector('tr.you td.nm'), r = me && me.getBoundingClientRect();
                if (r && r.top > 0 && r.bottom < vh) { return { x: r.left + Math.min(r.width * 0.4, 160), y: r.top + r.height / 2, row: me }; }
                var b = banner.getBoundingClientRect();
                return { x: b.left + b.width / 2, y: b.bottom + 24, row: null };
            }
            function fly(text, from, to, ms, px, then) {
                var f = document.createElement('span');
                f.textContent = text;
                f.setAttribute('aria-hidden', 'true');
                f.style.cssText = 'position:fixed;left:0;top:0;z-index:72;pointer-events:none;font-size:' + px + 'px;line-height:1;';
                document.body.appendChild(f);
                var mid = { x: (from.x + to.x) / 2, y: Math.min(from.y, to.y) - 80 };
                var a = f.animate([{ transform: 'translate(' + from.x + 'px,' + from.y + 'px) rotate(0) scale(.7)' },
                                   { transform: 'translate(' + mid.x + 'px,' + mid.y + 'px) rotate(180deg) scale(1.15)', offset: 0.5 },
                                   { transform: 'translate(' + to.x + 'px,' + to.y + 'px) rotate(360deg) scale(1)' }],
                                  { duration: ms, easing: 'ease-in-out', fill: 'forwards' });
                a.onfinish = function() { f.remove(); if (then) { then(); } };
            }
            function burst(text, at) {
                for (var k = 0; k < 9; k++) {
                    var s = document.createElement('span');
                    s.textContent = (k === 4 && season) ? season : text;
                    s.setAttribute('aria-hidden', 'true');
                    s.style.cssText = 'position:fixed;left:0;top:0;z-index:72;pointer-events:none;font-size:15px;line-height:1;';
                    document.body.appendChild(s);
                    var ang = k / 9 * Math.PI * 2, d = 34 + (k %% 3) * 14;
                    s.animate([{ transform: 'translate(' + at.x + 'px,' + at.y + 'px) scale(.4)', opacity: 1 },
                               { transform: 'translate(' + (at.x + Math.cos(ang) * d) + 'px,' + (at.y + Math.sin(ang) * d * 0.6 + 16) + 'px) scale(1)', opacity: 0 }],
                              { duration: 900, easing: 'ease-out', fill: 'forwards' }).onfinish = (function(x) { return function() { x.remove(); }; })(s);
                }
            }
            function toss(p, i) {
                // it rises from the board's bottom edge (the window's, if the board runs past it), in a box that hides it below
                var r = dc ? dc.getBoundingClientRect() : null, base = Math.min(vh, r ? r.bottom : vh);
                var x = Math.max(8, Math.min(vw - size - 8, edge - size - 16 - i * 64));
                var box = document.createElement('div'), w = pipEl(p, size);
                box.setAttribute('aria-hidden', 'true');
                box.style.cssText = 'position:fixed;z-index:71;pointer-events:none;overflow:hidden;left:' + x + 'px;top:' + (base - size) +
                    'px;width:' + size + 'px;height:' + size + 'px;';
                w.style.transform = 'translateY(' + size + 'px)';
                box.appendChild(w);
                document.body.appendChild(box);
                w.animate([{ transform: 'translateY(' + size + 'px)' }, { transform: 'translateY(4px)' }],
                          { duration: 380, easing: 'cubic-bezier(.3,1.4,.5,1)', fill: 'forwards' });
                setTimeout(function() {
                    var to = where();
                    fly(p.emoji || '🎉', { x: x + size * 0.72, y: base - size * 0.5 }, { x: to.x, y: to.y - 12 }, 760, 26, function() {
                        burst(p.emoji || '🎉', { x: to.x, y: to.y - 12 });
                        if (to.row) {
                            to.row.parentNode.animate([{ backgroundColor: 'transparent' }, { backgroundColor: accent + '33', offset: 0.2 }, { backgroundColor: 'transparent' }],
                                                     { duration: 1100 });
                        }
                    });
                }, 520);
                setTimeout(function() {
                    w.animate([{ transform: 'translateY(4px)' }, { transform: 'translateY(' + size + 'px)' }],
                              { duration: 340, easing: 'ease-in', fill: 'forwards' }).onfinish = function() { box.remove(); };
                }, 2200);
            }
            return;
        }
        var emojis = %s;
        var wrap = document.createElement('div');
        wrap.id = 'dc-flurry';
        wrap.style.cssText = 'position:fixed;left:0;top:0;right:0;bottom:0;pointer-events:none;z-index:69;overflow:hidden;';
        var style = document.createElement('style');
        style.textContent = '@keyframes dcfall { to { transform: translateY(108vh) rotate(300deg); } }';
        wrap.appendChild(style);
        for (var i = 0; i < 26; i++) {
            var s = document.createElement('span');
            s.textContent = emojis[i %% emojis.length];
            s.style.cssText = 'position:absolute;top:-40px;left:' + (Math.random() * 100) + 'vw;' +
                'font-size:' + (16 + Math.random() * 16) + 'px;' +
                'animation:dcfall ' + (1.6 + Math.random() * 1.4) + 's linear ' +
                (Math.random() * 0.7) + 's forwards;';
            wrap.appendChild(s);
        }
        document.body.appendChild(wrap);
        setTimeout(function() { wrap.remove(); }, 3800);
    })();
    """ % (back_cmd, banner, notes_json, pips_json, doodle_json, DOODLE_PAPER, DOODLE_LINE, DOODLE_INK, show_json, SHOW_JS if show_json != "null" else "",
           senders_json, _json.dumps(_sev.CSS).replace("</", "<\\/") if show_json != "null" else "null", CHEER_PIP, season_one, emoji_list)
