"""The board's windows: one overlay for all seven (POP_JS), a sheet, Magic search's how-to, a crewmate's,
a squadmate's and the good-luck card.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import datetime as _dt
import html as _html
import json as _json
import re as _re
from datetime import date as _date

from .. import songs as _songs

from .base import _ago, _fmt_time, _label, _pycmd, today_text
from .page import VEIL_IDS


# 3.9.8 (the tidy-ups): one overlay for the board's seven windows (the Cheer
# window, the song search, a sheet, Magic search's how-to, a crewmate's card, a
# squadmate's and the good-luck card). Each draws its own card in its own look;
# this is what's under and around it: the shade, its role and name, Esc, Tab
# kept inside, a click on the shade, the key back to what opened it, the bars'
# shade (its id goes as it closes, VEIL_WATCH_JS), the fade, and the motion
# layer's way in and out. Each window's script starts with it (once a page).
# A window's styles name it by its id or its data-pop (pop.css), so it keeps
# its look while it goes: once the id went first, a closing window lost its
# styles and showed bare at the page's foot for the length of its fade.
def pop_named(css, pid):
    """A window's styles, written by its id, as dcPop's css() writes them:
    by its id or its data-pop, so its look outlasts the id as it closes."""
    return _re.sub("#" + _re.escape(pid) + r"(?![\w-])", ':is(#%s,[data-pop="%s"])' % (pid, pid), css)


POP_JS = r"""
(function () {
    if (window.dcPop) { return; }
    var TABS = 'button, input, a[href], [tabindex="0"]';
    function still() { return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches); }
    function sel(id) { return ':is(#' + id + ',[data-pop="' + id + '"])'; }
    window.dcPop = {
        still: still,
        // the board's look: its tokens follow Settings › Theme and Accent; Anki's night class is only the fallback
        theme: function () {
            var night = /night/i.test(document.body.className) ||
                !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
            var dcBoard = document.getElementById('due-crew');
            var dcStyle = dcBoard ? getComputedStyle(dcBoard) : null;
            return { night: night, style: dcStyle,
                     font: (dcStyle && dcStyle.fontFamily) || '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
                     tok: function (name, light, dark) {
                         var v = dcStyle && dcStyle.getPropertyValue('--dc-' + name).trim();
                         return v || (night ? dark : light);
                     } };
        },
        // o: id, label, role (dialog), z, pad (the shade's padding). The window puts its styles (pop.css)
        // and its card in pop.back, then pop.show(card, {esc, shade, key, closing}): what Esc does (close),
        // what a click on the shade does (Esc's), a key it takes first (true: taken), what goes as it closes
        make: function (o) {
            var old = document.getElementById(o.id);
            if (old) { old.remove(); }
            var back = document.createElement('div'), was = document.activeElement, on = {}, moved = false, gone = false, down = false;
            var s = sel(o.id), base = document.createElement('style');
            back.id = o.id;
            back.setAttribute('data-pop', o.id);
            back.setAttribute('role', o.role || 'dialog');
            back.setAttribute('aria-modal', 'true');
            if (o.label) { back.setAttribute('aria-label', o.label); }
            // Anki's Decks screen gives every control its look (and macOS its own): the window's start from none
            base.textContent = s + '{position:fixed;inset:0;z-index:' + o.z + ';background:rgba(0,0,0,.35);display:flex;' +
                'align-items:flex-start;justify-content:center;padding:' + o.pad + ';overflow:auto;}' +
                s + ' button,' + s + ' input:where(:not([type=checkbox]):not([type=radio]):not([type=range])),' + s + ' textarea' +
                '{-webkit-appearance:none;appearance:none;margin:0;box-shadow:none;text-shadow:none;min-height:0;min-width:0;' +
                '-webkit-backdrop-filter:none;backdrop-filter:none;letter-spacing:normal;}';
            back.appendChild(base);
            // 3.9.2's QoL pass: Tab wraps inside the card, never onto the board under it
            function trap(e) {
                var f = Array.prototype.filter.call(on.card.querySelectorAll(TABS),
                    function (x) { return !x.disabled && x.offsetParent !== null; });
                if (!f.length) { return; }
                var at = f.indexOf(document.activeElement);
                if (at < 0 || (e.shiftKey && at === 0) || (!e.shiftKey && at === f.length - 1)) {
                    e.preventDefault();
                    (e.shiftKey ? f[f.length - 1] : f[0]).focus();
                }
            }
            function esc(e) {
                if (on.key && on.key(e)) { return; }
                if (e.key === 'Tab') { trap(e); return; }
                if (e.key !== 'Escape') { return; }
                e.stopPropagation();
                (on.esc || close)();
            }
            function close() {
                if (gone) { return; }
                gone = true;
                document.removeEventListener('keydown', esc, true);
                if (on.closing) { on.closing(); }
                back.removeAttribute('id');  // the bars' shade goes with it (VEIL_WATCH_JS); its look stays, by data-pop
                // what opened it gets the key back (3.9.2's QoL pass)
                if (was && was.isConnected && was.focus) { try { was.focus(); } catch (x) { /* gone with a redraw */ } }
                // 3.9.9 (the robot click-test): a crewmate's 🎉 pill shows only while its name cell has the pointer
                // or the key, so with the window up it's hidden and can't take the key back. Its cell's first
                // shown control takes it (the pill shows again, :focus-within), then the pill itself
                if (was && was.isConnected && document.activeElement !== was && was.closest) {
                    var cell = was.closest('td, li'), near = cell && [].slice.call(cell.querySelectorAll('a[href], button'))
                        .filter(function (x) { return x !== was && x.offsetParent !== null && x.tabIndex >= 0; })[0];
                    if (near) { try { near.focus(); was.focus(); } catch (x) { /* gone with a redraw */ } }
                }
                // moved: the motion layer opened it and takes it out its own way, back into what was clicked
                if (moved || still() || !back.animate) { back.remove(); return; }
                back.style.pointerEvents = 'none';
                back.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, easing: 'ease-in', fill: 'forwards' }).onfinish = function () { back.remove(); };
            }
            return {
                back: back,
                close: close,
                // the window's styles, written by its id: they name it by data-pop too, so its look outlasts the id
                css: function (text) { return String(text).replace(new RegExp('#' + o.id + '(?![\\w-])', 'g'), s); },
                show: function (card, opts) {
                    on = opts || {};
                    on.card = card;
                    // a press that starts on the shade and ends there closes it (a line drawn off a pad's edge never does)
                    back.addEventListener('pointerdown', function (e) { down = e.target === back; });
                    back.addEventListener('click', function (e) { if (e.target === back && down) { (on.shade || on.esc || close)(); } });
                    document.addEventListener('keydown', esc, true);
                    document.body.appendChild(back);
                    if (window.dcMotion && !still()) { try { dcMotion.open(back, card); moved = true; } catch (x) { /* it opens as it is */ } }
                }
            };
        }
    };
})();
"""


# 3.9.1 (Sam: "the modal for status update is still native, make sure all
# modals are in our style"): a question before a step, one line, or one of a
# few, on the Decks screen in the Cheer window's look (sheets.py asks; Qt
# answers off the board). view: {id, title, text (plain; its line breaks
# kept), yes, no, danger (a step that can't be taken back: the button in the
# board's red), field: {kind: "text", value, max, hint} or {kind: "pick",
# items, at}, check: {label, on}}. Every word goes in as text, never markup.
# The answer is one duecrew:sheet command: its id (new each time, so a page
# can't answer a question it wasn't asked) and URI-encoded JSON {ok, text,
# at, check}; Cancel, Esc and the backdrop send {ok: false}.
SHEET_JS = r"""
(function () {
    var V = __VIEW__;
    var T = window.dcPop.theme(), tok = T.tok, night = T.night, dcStyle = T.style;
    var bg = tok('bg', '#ffffff', '#1c1c1c'), ink = tok('ink', '#333333', '#dfe1dc'), line = tok('line', '#e2e2da', '#3d403b'),
        well = tok('well', '#f2f2ec', '#2b2d29'), muted = tok('muted', '#6f736b', '#9a9e94'),
        accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
        you = tok('you-bg', '#e9f2e9', '#2c372b');
    // the board's own theme, not the computer's: its background's lightness
    var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(bg);
    var dark = m ? (parseInt(m[1], 16) * 299 + parseInt(m[2], 16) * 587 + parseInt(m[3], 16) * 114) / 1000 < 128 : night;
    var bad = dark ? '#ef8383' : '#d32f2f', badInk = dark ? '#2a1212' : '#ffffff';
    var font = T.font;
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) { e.className = cls; }
        if (text != null) { e.textContent = text; }
        return e;
    }
    var pop = window.dcPop.make({ id: 'dc-sheet', label: V.title, role: V.field ? 'dialog' : 'alertdialog', z: 82, pad: '12vh 16px 16px' });
    var back = pop.back;
    var css = el('style');
    css.textContent = pop.css(
        '#dc-sheet *{box-sizing:border-box;}' +
        '#dc-sheet .cw{width:420px;max-width:100%;border-radius:14px;padding:16px 18px 14px;text-align:left;display:grid;gap:12px;font-family:' + font + ';' +
          'box-shadow:0 16px 60px rgba(0,0,0,.35);background:' + bg + ';color:' + ink + ';border:1px solid ' + line + ';font-size:13px;}' +
        '#dc-sheet button,#dc-sheet input:where(:not([type=checkbox]):not([type=radio]):not([type=range])),#dc-sheet textarea{font-family:inherit;color:inherit;line-height:normal;font-weight:400;}#dc-sheet button{cursor:pointer;}' +
        '#dc-sheet .hd{font-size:16px;font-weight:700;}' +
        '#dc-sheet .bd{white-space:pre-line;line-height:1.45;max-height:46vh;overflow-y:auto;overflow-wrap:anywhere;}' +
        '#dc-sheet .tx{width:100%;height:32px;border-radius:8px;border:1px solid ' + line + ';background:' + bg + ';color:' + ink + ';font-size:13px;padding:0 10px;}' +
        '#dc-sheet .tx:focus{outline:2px solid ' + accent + ';outline-offset:0;}' +
        '#dc-sheet .ct{font-size:11px;color:' + muted + ';font-variant-numeric:tabular-nums;text-align:right;margin-top:3px;}' +
        '#dc-sheet .ls{border:1px solid ' + line + ';border-radius:10px;background:' + well + ';padding:4px;max-height:230px;overflow-y:auto;display:grid;gap:2px;}' +
        '#dc-sheet .ls button{display:block;width:100%;text-align:left;border:1px solid transparent;background:none;border-radius:8px;padding:6px 10px;font-size:13px;overflow-wrap:anywhere;}' +
        '#dc-sheet .ls button:hover{background:' + bg + ';}' +
        '#dc-sheet .ls button[aria-selected=true]{border-color:' + accent + ';background:' + you + ';font-weight:600;}' +
        '#dc-sheet .ls .none{color:' + muted + ';padding:6px 10px;font-size:12px;}' +
        '#dc-sheet .ls.nts{max-height:none;gap:3px;}#dc-sheet .ls.nts button{padding:7px 10px;}' +
        '#dc-sheet .ls .nm{display:block;font-weight:600;}#dc-sheet .ls .nt{display:block;font-size:12px;font-weight:400;color:' + muted + ';margin-top:1px;line-height:1.35;}' +
        '#dc-sheet .ck{display:flex;align-items:flex-start;gap:8px;cursor:pointer;line-height:1.35;}' +
        // 3.9.6: the tick is the sheet's to draw, as the plan window's are (macOS draws any other its own way)
        '#dc-sheet .ck input{-webkit-appearance:none;appearance:none;width:15px;height:15px;min-height:0;margin:1px 0 0;flex:none;box-sizing:border-box;' +
          'display:inline-grid;place-content:center;border:1.5px solid ' + muted + ';border-radius:4px;background:' + bg + ';box-shadow:none;cursor:pointer;}' +
        '#dc-sheet .ck input:checked{background:' + accent + ';border-color:' + accent + ';}' +
        '#dc-sheet .ck input:checked::after{content:"";width:7px;height:3px;border-left:2px solid ' + accentInk + ';border-bottom:2px solid ' + accentInk + ';' +
          'transform:translateY(-1px) rotate(-45deg);}' +
        '#dc-sheet .ck input:focus-visible{outline:2px solid ' + accent + ';outline-offset:2px;}' +
        '#dc-sheet .ft{display:flex;align-items:center;gap:8px;}' +
        '#dc-sheet .sp{flex:1;}' +
        '#dc-sheet .go{background:' + accent + ';color:' + accentInk + ';border:1px solid transparent;border-radius:8px;padding:6px 16px;font-weight:700;font-size:13px;}' +
        '#dc-sheet .go.bad{background:' + bad + ';color:' + badInk + ';}' +
        '#dc-sheet .go:disabled{opacity:.45;cursor:default;}' +
        '#dc-sheet .no{background:none;border:1px solid ' + line + ';border-radius:8px;padding:6px 14px;font-size:13px;}' +
        '#dc-sheet button:focus-visible{outline:2px solid ' + accent + ' !important;outline-offset:2px;}');
    back.appendChild(css);
    var card = el('div', 'cw');
    back.appendChild(card);
    card.appendChild(el('div', 'hd', V.title));
    if (V.text) { card.appendChild(el('div', 'bd', V.text)); }

    var f = V.field || null, input = null, at = -1, rows = [];
    if (f && f.kind === 'text') {
        var wrap = el('div');
        input = el('input', 'tx');
        input.type = 'text';
        input.value = f.value || '';
        input.maxLength = f.max || 280;
        input.placeholder = f.hint || '';
        input.setAttribute('aria-label', V.title);
        input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); yes(); } });
        wrap.appendChild(input);
        // near the ceiling, how much room is left (the status's 80, a reply's 280)
        var ct = el('div', 'ct');
        function count() { var n = input.maxLength - input.value.length; ct.textContent = n <= 20 ? String(n) : ''; }
        input.addEventListener('input', count);
        count();
        wrap.appendChild(ct);
        card.appendChild(wrap);
    } else if (f && f.kind === 'pick') {
        // one of a few (a deck): a list in the board's look; a box to narrow it when it's long
        // plans, end to end (Behind…): a few ways out, each with a quiet line under its name
        var find = null, ls = el('div', f.notes ? 'ls nts' : 'ls');
        ls.setAttribute('role', 'listbox');
        ls.setAttribute('aria-label', V.title);
        at = Math.max(0, Math.min((f.items || []).length - 1, f.at || 0));
        (f.items || []).forEach(function (name, i) {
            var b = el('button', null, f.notes ? null : name);
            if (f.notes) { b.appendChild(el('span', 'nm', name)); if (f.notes[i]) { b.appendChild(el('span', 'nt', f.notes[i])); } }
            b.type = 'button';
            b.setAttribute('role', 'option');
            b.addEventListener('click', function () { pick(i); });
            b.addEventListener('dblclick', function () { pick(i); yes(); });
            rows.push(b);
            ls.appendChild(b);
        });
        var none = el('div', 'none', 'Nothing matches.');
        none.style.display = 'none';
        ls.appendChild(none);
        if (rows.length > 10) {
            find = el('input', 'tx');
            find.type = 'search';
            find.placeholder = 'Find';
            find.setAttribute('aria-label', 'Find');
            find.addEventListener('input', function () {
                var q = find.value.trim().toLowerCase(), first = -1;
                rows.forEach(function (b, i) {
                    var show = !q || b.textContent.toLowerCase().indexOf(q) >= 0;
                    b.style.display = show ? '' : 'none';
                    if (show && first < 0) { first = i; }
                });
                none.style.display = first < 0 ? '' : 'none';
                if (first >= 0 && rows[at].style.display === 'none') { pick(first); }
                go.disabled = first < 0;
            });
            find.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); if (!go.disabled) { yes(); } }
                else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); step(e.key === 'ArrowDown' ? 1 : -1); }
            });
            card.appendChild(find);
        }
        ls.addEventListener('keydown', function (e) {
            if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); step(e.key === 'ArrowDown' ? 1 : -1); rows[at].focus(); }
        });
        card.appendChild(ls);
    }
    function pick(i) {
        at = i;
        rows.forEach(function (b, j) { b.setAttribute('aria-selected', j === i ? 'true' : 'false'); });
        if (f && f.go && f.go[i] && go) { go.textContent = f.go[i]; }  // the button says what the pick does
        var r = rows[i], box = r.parentNode;
        if (r.offsetTop < box.scrollTop) { box.scrollTop = r.offsetTop - 4; }
        else if (r.offsetTop + r.offsetHeight > box.scrollTop + box.clientHeight) { box.scrollTop = r.offsetTop + r.offsetHeight - box.clientHeight + 4; }
    }
    function step(d) {
        for (var i = at + d; i >= 0 && i < rows.length; i += d) {
            if (rows[i].style.display !== 'none') { pick(i); return; }
        }
    }

    var tick = null;
    if (V.check) {
        var ck = el('label', 'ck');
        tick = el('input');
        tick.type = 'checkbox';
        tick.checked = !!V.check.on;
        ck.appendChild(tick);
        ck.appendChild(el('span', null, V.check.label));
        card.appendChild(ck);
    }

    var ft = el('div', 'ft'), go = el('button', 'go' + (V.danger ? ' bad' : ''), V.yes || 'OK'), no = el('button', 'no', V.no || 'Cancel');
    go.type = no.type = 'button';
    ft.appendChild(go);
    ft.appendChild(el('span', 'sp'));
    ft.appendChild(no);
    card.appendChild(ft);
    if (rows.length) { pick(at); }

    var said = false;
    function say(p) {
        if (said) { return; }
        said = true;
        close();
        if (typeof pycmd !== 'undefined') { pycmd('duecrew:sheet:' + V.id + ':' + encodeURIComponent(JSON.stringify(p)) + '|' + window.dcBK); }
    }
    function yes() {
        var p = { ok: true };
        if (input) { p.text = input.value; }
        if (rows.length) { p.at = at; }
        if (tick) { p.check = tick.checked; }
        say(p);
    }
    var close = pop.close;
    go.addEventListener('click', yes);
    no.addEventListener('click', function () { say({ ok: false }); });
    // Esc, or a click on the shade, says no
    pop.show(card, { esc: function () { say({ ok: false }); } });
    // a line to write starts in its box, its words selected; a step that can't be
    // taken back starts on Cancel, as the Qt question did
    if (input) { input.focus(); input.select(); }
    else if (rows.length) { (find || rows[at]).focus(); }
    else if (V.danger) { no.focus(); } else { go.focus(); }
})();
"""


def sheet_js(view):
    """SHEET_JS with its view (sheets.py builds it): the words as JSON, no
    '</' to end the script."""
    f = view.get("field") or None
    if f and f.get("kind") == "text":
        f = {"kind": "text", "value": str(f.get("value") or ""), "max": max(1, min(2000, int(f.get("max") or 280))),
             "hint": str(f.get("hint") or "")}
    elif f and f.get("kind") == "pick":
        items = [str(x) for x in f.get("items") or []]
        # plans, end to end (Behind…): a quiet line under each, and the button's word for each
        more = {k: ([str(x) for x in f[k]] + [""] * len(items))[:len(items)] for k in ("notes", "go") if f.get(k)}
        f = dict({"kind": "pick", "items": items, "at": max(0, min(len(items) - 1, int(f.get("at") or 0)))}, **more) if items else None
    else:
        f = None
    ck = view.get("check")
    data = {"id": str(view.get("id") or ""), "title": str(view.get("title") or ""), "text": str(view.get("text") or ""),
            "yes": str(view.get("yes") or "OK"), "no": str(view.get("no") or "Cancel"), "danger": bool(view.get("danger")),
            "field": f, "check": {"label": str(ck.get("label") or ""), "on": bool(ck.get("on"))} if ck else None}
    return POP_JS + SHEET_JS.replace("__VIEW__", _json.dumps(data).replace("</", "<\\/"))


# 3.9.7, round 2 (Sam: "the modal introducing for the first time should pop up
# on the main decks screen"): Magic search's how-to, once a person (the account's
# magic_seen), over the Decks screen in the sheets' look. Its words are
# magic.HOWTO's, the window's ? the same; a try opens the window with it.
# It waits for the board to be clear (no window, no show over it) and for the
# You box's head, where Magic search lives, to be on the page.
MAGIC_HOWTO_JS = r"""
(function () {
    var V = __VIEW__;
    if (document.getElementById('dc-magic')) { return; }
    var BUSY = __BUSY__;
    function clear() {
        return document.querySelector('.du-mg') && !BUSY.some(function (id) { return !!document.getElementById(id); });
    }
    function later(n) {
        if (clear()) { draw(); return; }
        if (n < 30) { setTimeout(function () { later(n + 1); }, 700); }
    }
    function draw() {
    var T = window.dcPop.theme(), tok = T.tok;
    var bg = tok('bg', '#ffffff', '#1c1c1c'), ink = tok('ink', '#333333', '#dfe1dc'), line = tok('line', '#e2e2da', '#3d403b'),
        well = tok('well', '#f2f2ec', '#2b2d29'), muted = tok('muted', '#6f736b', '#9a9e94'),
        accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
        you = tok('you-bg', '#e9f2e9', '#2c372b'), hours = tok('hours', '#f2b33d', '#f2c25c');
    var font = T.font;
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) { e.className = cls; }
        if (text != null) { e.textContent = text; }
        return e;
    }
    var pop = window.dcPop.make({ id: 'dc-magic', label: 'Magic search', z: 82, pad: '6vh 16px 16px' }), back = pop.back;
    var css = el('style');
    css.textContent = pop.css(
        '#dc-magic *{box-sizing:border-box;}' +
        '#dc-magic .cw{width:660px;max-width:100%;border-radius:16px;padding:18px 20px 16px;text-align:left;display:grid;gap:12px;font-family:' + font + ';' +
          'box-shadow:0 16px 60px rgba(0,0,0,.35);background:' + bg + ';color:' + ink + ';border:1px solid ' + line + ';font-size:13px;line-height:1.45;}' +
        '#dc-magic button{font-family:inherit;color:inherit;line-height:normal;font-weight:400;cursor:pointer;}' +
        '#dc-magic .t{display:flex;align-items:center;gap:10px;}#dc-magic .t b{font-size:19px;}' +
        '#dc-magic .new{font-size:11px;font-weight:700;border-radius:999px;padding:1px 8px;background:' + you + ';color:' + accent + ';}' +
        '#dc-magic p{margin:0;}' +
        '#dc-magic .how{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;}' +
        '#dc-magic .how>div{border:1px solid ' + line + ';border-radius:12px;padding:9px 11px;display:grid;gap:5px;align-content:start;}' +
        '#dc-magic h4{margin:0;font-size:13px;}#dc-magic .how p{font-size:12.5px;color:' + muted + ';}' +
        '#dc-magic code{font-size:11.5px;background:' + well + ';border-radius:5px;padding:1px 5px;overflow-wrap:anywhere;}' +
        '#dc-magic .try{display:flex;flex-wrap:wrap;gap:5px;}' +
        '#dc-magic .try button{border:1px solid ' + line + ';background:' + well + ';border-radius:999px;padding:3px 10px;font-size:12.5px;}' +
        '#dc-magic .try button:hover{border-color:' + accent + ';}' +
        '#dc-magic .then{border-radius:12px;background:' + you + ';padding:10px 12px;display:grid;gap:4px;font-size:12.5px;}' +
        '#dc-magic .then b{font-size:13px;}#dc-magic ul{margin:0;padding-left:18px;display:grid;gap:2px;}' +
        '#dc-magic .ft{display:flex;align-items:center;gap:8px;flex-wrap:wrap;}#dc-magic .ft .w{flex:1 1 220px;font-size:12px;color:' + muted + ';}' +
        '#dc-magic .go{background:' + accent + ';color:' + accentInk + ';border:1px solid transparent;border-radius:8px;padding:6px 16px;font-weight:700;font-size:13px;}' +
        '#dc-magic .no{background:none;border:1px solid ' + line + ';border-radius:8px;padding:6px 14px;font-size:13px;}' +
        '#dc-magic button:focus-visible{outline:2px solid ' + accent + ' !important;outline-offset:2px;}' +
        '@media (max-width:560px){#dc-magic .how{grid-template-columns:minmax(0,1fr);}}');
    back.appendChild(css);
    var card = el('div', 'cw');
    back.appendChild(card);
    var t = el('div', 't');
    t.innerHTML = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" aria-hidden="true">' +
        '<circle cx="10" cy="11" r="6.2"/><path d="M19.4 20.4l-4.7-4.7"/><path d="M19 1.6l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9z" fill="' + hours + '" stroke="none"/></svg>';
    t.appendChild(el('b', null, 'Magic search'));
    t.appendChild(el('span', 'new', 'New'));
    card.appendChild(t);
    card.appendChild(el('p', null, V.lede));
    var how = el('div', 'how');
    (V.parts || []).forEach(function (x) {
        var d = el('div');
        d.appendChild(el('h4', null, x.t));
        d.appendChild(el('p', null, x.w));
        if (x.code) { d.appendChild(el('code', null, x.code)); }
        var tries = x['try'] || [];
        if (tries.length) {
            var tr = el('div', 'try');
            tries.forEach(function (q, i) {
                var b = el('button', null, (x.label || [])[i] || q);
                b.type = 'button';
                b.title = 'Try it: ' + q;
                b.addEventListener('click', function () { say('try', q); });
                tr.appendChild(b);
            });
            d.appendChild(tr);
        }
        how.appendChild(d);
    });
    card.appendChild(how);
    var then = el('div', 'then');
    then.appendChild(el('b', null, 'Then, with what it finds'));
    var ul = el('ul');
    (V.then || []).forEach(function (x) { ul.appendChild(el('li', null, x)); });
    then.appendChild(ul);
    card.appendChild(then);
    var ft = el('div', 'ft'), go = el('button', 'go', 'Open Magic search'), no = el('button', 'no', 'Got it');
    go.type = no.type = 'button';
    ft.appendChild(el('span', 'w', V.foot));
    ft.appendChild(no);
    ft.appendChild(go);
    card.appendChild(ft);

    var said = false;
    function say(how, q) {
        if (said) { return; }
        said = true;
        pop.close();
        if (typeof pycmd !== 'undefined') { pycmd('duecrew:magichow:' + how + ':' + encodeURIComponent(q || '') + '|' + window.dcBK); }
    }
    go.addEventListener('click', function () { say('open'); });
    no.addEventListener('click', function () { say('seen'); });
    // Esc, or a click on the shade: seen
    pop.show(card, { esc: function () { say('seen'); } });
    try { go.focus({ preventScroll: true }); } catch (x) { go.focus(); }  // a short window opens on the card's top
    }
    later(0);
})();
"""


def magic_howto_js(view):
    """MAGIC_HOWTO_JS with its words (magic.howto): JSON, no '</' to end the script."""
    v = {"lede": str(view.get("lede") or ""), "foot": str(view.get("foot") or ""),
         "then": [str(x) for x in view.get("then") or []],
         "parts": [{"t": str(x.get("t") or ""), "w": str(x.get("w") or ""), "code": str(x.get("code") or ""),
                    "try": [str(q) for q in x.get("try") or []], "label": [str(q) for q in x.get("label") or []]}
                   for x in view.get("parts") or [] if isinstance(x, dict)]}
    busy = list(VEIL_IDS) + ["dc-show", "dc-flurry"]  # Wrapped, Settings and the closet take the You box with the board
    return POP_JS + (MAGIC_HOWTO_JS.replace("__BUSY__", _json.dumps(busy))
            .replace("__VIEW__", _json.dumps(v).replace("</", "<\\/")))


def stranger_card_js(info):
    """Card for a squadmate who isn't crew. Deliberately spare — no heatmap,
    no cheer, no celebration: we don't necessarily know them. info: uid,
    name, reviews, time_ms, retention, streak, rank, squad, today (bool),
    pending, knocked_me, founder_me; sev (3.8.22): card_sev's markup, a
    plain Pip in the emoji's place (all a squadmate shares is a name and an
    emoji, so no colour or look), or None."""
    sev_fig = info.get("sev")
    name = _html.escape(str(info.get("name", "?"))) if sev_fig else _label(info.get("name", "?"), info.get("emoji"))
    squad = _html.escape(str(info.get("squad") or "squad"))
    numberless = all(info.get(k) is None for k in ("reviews", "time_ms", "retention", "streak"))
    if info.get("show_up") or numberless:
        # show-up, theirs or mine: presence is the whole story, no rank
        where = f'in {squad}'
        bits = ["showed up today" if info.get("today") else "not today"]
        if info.get("week") is not None:
            bits.append(f'{int(info["week"])}/7 days this week')
    else:
        where = (f'#{int(info["rank"])} in {squad} today' if info.get("rank")
                 else f'in {squad}')
        when = "today" if info.get("today") else "last sync"
        bits = [f'{format(int(info.get("reviews") or 0), ",")} reviews {when}',
                _fmt_time(int(info.get("time_ms") or 0))]
        if info.get("retention") is not None:
            bits.append(f'{float(info["retention"]):.1f}% retention')
        bits.append(f'{int(info.get("streak") or 0)}-day streak')
    stat = " &middot; ".join(bits)
    head = (f'<div style="display: flex; align-items: baseline; gap: 8px; flex: 1; min-width: 0;">'
            f'<span style="font-size: 15px; font-weight: 700;">{name}</span>'
            f'<span style="opacity: 0.6; font-size: 10.5px; text-transform: uppercase;'
            f' letter-spacing: 0.08em;">{where}</span></div>')
    if sev_fig:  # 3.8.22: as on a crewmate's card, Pip beside the line, room above for a hat
        head = f'<div style="display: flex; align-items: center; gap: 10px; padding-top: 10px;">{sev_fig}{head}</div>'
    inner = _json.dumps(head + f'<div style="font-size: 12px; opacity: 0.8; padding: 6px 0 2px;">{stat}</div>')
    uid = str(info.get("uid", ""))
    if info.get("knocked_me"):
        act_label = _json.dumps("\U0001F91D Add back")
        act_cmd, act_primary = _json.dumps(f"duecrew:addback:{uid}"), "true"
    elif info.get("pending"):
        act_label = _json.dumps("\u23F3 Waiting")
        act_cmd, act_primary = _json.dumps(None), "false"
    else:
        act_label = _json.dumps("\U0001F91D Add")
        act_cmd, act_primary = _json.dumps(f"duecrew:knock:{uid}"), "true"
    extras = []
    if info.get("founder_me"):
        extras = [("Remove", f"duecrew:squadkick:{uid}"),
                  ("Block", f"duecrew:squadblock:{uid}"),
                  ("Make founder", f"duecrew:squadfounder:{uid}")]
    extras_json = _json.dumps(extras)
    return POP_JS + """
    (function() {
        // 2.9: colors come from the board, which already follows Settings ->
        // Theme and Accent; Anki's night class is only the fallback (dcPop.theme)
        var T = window.dcPop.theme(), tok = T.tok;
        var dcBg = tok('bg', '#ffffff', '#1c1c1c'), dcInk = tok('ink', '#333333', '#dfe1dc'),
            dcLine = tok('line', '#e2e2da', '#3d403b'), dcWell = tok('well', '#f2f2ec', '#2b2d29'),
            accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
            warn = tok('hours', '#b26a00', '#dda45c');
        var pop = window.dcPop.make({ id: 'dc-profile', label: %s, z: 80, pad: '16vh 0 0' }), back = pop.back;
        var reset = document.createElement('style');  // 3.9.6: Anki's button look (and macOS's own) off the card's; its focus ring back
        reset.textContent = pop.css('#dc-profile button{line-height:normal;font-weight:400;}' +
            '#dc-profile button:focus-visible{outline:2px solid ' + accent + ' !important;outline-offset:2px;}');
        back.appendChild(reset);
        var card = document.createElement('div');
        card.style.cssText = 'min-width:300px;max-width:380px;border-radius:12px;padding:16px 20px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);' +
            'background:' + dcBg + ';color:' + dcInk + ';border:1px solid ' + dcLine + ';';
        var body = document.createElement('div');
        body.innerHTML = %s;
        card.appendChild(body);
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;flex-wrap:wrap;gap:8px;margin-top:12px;';
        var actCmd = %s;
        var act = document.createElement('button');
        act.textContent = %s;
        var primary = %s;
        act.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;' +
            (primary ? 'background:' + accent + ';color:' + accentInk +
                       ';border:1px solid transparent;font-weight:600;cursor:pointer;'
                     : 'background:none;color:inherit;opacity:0.7;border:1px solid ' +
                       dcLine + ';cursor:default;');
        if (actCmd) {
            act.addEventListener('click', function() {
                pop.close();
                if (typeof pycmd !== 'undefined') { pycmd(actCmd + '|' + window.dcBK); }
            });
        }
        var close = document.createElement('button');
        close.textContent = 'Close';
        close.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
            'background:none;color:inherit;border:1px solid ' +
            dcLine + ';';
        close.addEventListener('click', function() { pop.close(); });
        row.appendChild(act);
        var spacer = document.createElement('div');
        spacer.style.flex = '1';
        row.appendChild(spacer);
        row.appendChild(close);
        card.appendChild(row);
        // the founder's tools get a row of their own; on the action row
        // they pushed Close onto a line by itself
        var extras = %s;
        if (extras.length) {
            var tools = document.createElement('div');
            tools.style.cssText = 'display:flex;flex-wrap:wrap;align-items:center;gap:6px;' +
                'margin-top:12px;padding-top:10px;border-top:1px solid ' + dcLine + ';';
            var toolsLabel = document.createElement('span');
            toolsLabel.textContent = 'Founder';
            toolsLabel.style.cssText = 'font-size:10.5px;opacity:0.6;margin-right:4px;' +
                'text-transform:uppercase;letter-spacing:0.08em;';
            tools.appendChild(toolsLabel);
            extras.forEach(function(pair) {
                var extra = document.createElement('button');
                extra.textContent = pair[0];
                extra.style.cssText = 'font-size:11.5px;padding:3px 10px;border-radius:6px;cursor:pointer;' +
                    'background:none;color:inherit;opacity:0.85;border:1px solid ' + dcLine + ';';
                extra.addEventListener('click', function() {
                    pop.close();
                    if (typeof pycmd !== 'undefined') { pycmd(pair[1] + '|' + window.dcBK); }
                });
                tools.appendChild(extra);
            });
            card.appendChild(tools);
        }
        back.appendChild(card);
        pop.show(card);  // Esc or the shade closes it; 3.8.0: out of the name and back into it (dcPop)
    })();
    """ % (_json.dumps(str(info.get("name") or "?")), inner, act_cmd, act_label, act_primary, extras_json)


def luck_card_js(name, lines):
    """2.10: the good-luck card, shown once on the morning of my exam.
    `lines`: [(sender name, note)]. Everything sender-written goes in as
    textContent, never markup. Thanks sends a 💚 back to each of them."""
    title = _json.dumps(f"\U0001F340 Good luck today, {str(name or 'you')}")
    items = _json.dumps([[str(n), str(t)] for n, t in (lines or [])][:12])
    return POP_JS + """
    (function() {
        // 2.9: colors come from the board, which already follows Settings ->
        // Theme and Accent; Anki's night class is only the fallback (dcPop.theme)
        var T = window.dcPop.theme(), tok = T.tok;
        var bg = tok('bg', '#ffffff', '#1c1c1c'), ink = tok('ink', '#333333', '#dfe1dc'),
            line = tok('line', '#e2e2da', '#3d403b'), accent = tok('accent', '#2e7d32', '#7cc47f'),
            accentInk = tok('accent-ink', '#ffffff', '#122912');
        var pop = window.dcPop.make({ id: 'dc-profile', label: %s, z: 80, pad: '14vh 0 0' }), back = pop.back;
        var reset = document.createElement('style');  // 3.9.6: Anki's button look (and macOS's own) off the card's; its focus ring back
        reset.textContent = pop.css('#dc-profile button{line-height:normal;font-weight:400;}' +
            '#dc-profile button:focus-visible{outline:2px solid ' + accent + ' !important;outline-offset:2px;}');
        back.appendChild(reset);
        var card = document.createElement('div');
        card.style.cssText = 'min-width:320px;max-width:420px;border-radius:12px;padding:18px 22px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);background:' + bg + ';color:' + ink +
            ';border:1px solid ' + line + ';';
        var h = document.createElement('div');
        h.textContent = %s;
        h.style.cssText = 'font-size:17px;font-weight:700;margin-bottom:10px;';
        card.appendChild(h);
        %s.forEach(function(pair) {
            var p = document.createElement('div');
            p.style.cssText = 'font-size:13.5px;padding:4px 0;';
            p.textContent = '\u201c' + pair[1] + '\u201d';
            var who = document.createElement('span');
            who.textContent = ' \u2014 ' + pair[0];
            who.style.cssText = 'opacity:0.6;font-size:12px;';
            p.appendChild(who);
            card.appendChild(p);
        });
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:8px;margin-top:14px;';
        var close = document.createElement('button');
        close.textContent = 'Close';
        close.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
            'background:none;color:inherit;border:1px solid ' + line + ';';
        close.addEventListener('click', function() { pop.close(); });
        var thanks = document.createElement('button');
        thanks.textContent = 'Thanks, crew';
        thanks.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
            'background:' + accent + ';color:' + accentInk + ';border:1px solid transparent;font-weight:600;';
        thanks.addEventListener('click', function() {
            pop.close();
            if (typeof pycmd !== 'undefined') { pycmd('duecrew:luckthanks|' + window.dcBK); }
        });
        var spacer = document.createElement('div');
        spacer.style.flex = '1';
        row.appendChild(close);
        row.appendChild(spacer);
        row.appendChild(thanks);
        card.appendChild(row);
        back.appendChild(card);
        pop.show(card);  // Esc or the shade closes it; 3.8.0: out of the name and back into it (dcPop)
    })();
    """ % (title, title, items)


HEAT_LEVELS = ((1, 1), (10, 2), (50, 3), (150, 4))


def _heat_level(n):
    level = 0
    for threshold, lvl in HEAT_LEVELS:
        if n >= threshold:
            level = lvl
    return level


def _profile_song(profile):
    """3.9.6: their song of the moment on their card, "♪ Title · Artist", with Listen (in my music app); on
    mine, Change, which opens the search. The song as songs.clean has it, escaped here; "" with none."""
    song = _songs.clean(profile.get("song"))
    if not song:
        return ""
    link = 'style="color: inherit; font-weight: 700; text-decoration: none; border-bottom: 1px dotted currentColor;"'
    shut = "document.getElementById('dc-profile').remove();"
    if profile.get("you"):
        act = (f'<a href="#" {link} onclick="{shut}if(window.dcDance){{dcDance.search();}}return false;">Change</a>')
    else:
        act = f'<a href="#" {link} onclick="{shut}{_pycmd("songlisten:" + str(profile.get("uid") or ""))}">Listen</a>'
    return (f'<div style="font-size: 12px; padding: 4px 0 0; display: flex; gap: 6px; align-items: baseline; min-width: 0;">'
            f'<span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;">&#9834; '
            f'<b>{_html.escape(song["t"])}</b> &middot; {_html.escape(song["a"])}</span>'
            f'<span style="flex: none;">{act}</span></div>')


def profile_overlay_js(profile):
    """Build the profile overlay. `profile`:
      name, streak (int|None), last_active (str ts), cells (list of daily
      counts oldest->newest, or None when the heatmap is private),
      same_days (int|None), decks_line (str), uid, you (bool),
      paused (bool), exam (str, client-built text or ""), away (str, text
      or ""), status (str or ""), today ((reviews, new cards or None) or
      None), sev (3.8.2: card_sev's markup, in the emoji's place, or None),
      song (3.9.6: their song of the moment, from their crew entry, or None).
    For your own card ("you") the overlay shows exactly what the crew sees,
    and the cheer button becomes a Privacy shortcut. Everything user-sourced
    is escaped here; the JS only injects the built HTML and wires buttons."""
    you = bool(profile.get("you"))
    sev_fig = profile.get("sev")  # 3.8.2: their Pip where the emoji was, as on their row
    name = _html.escape(str(profile.get("name", "?"))) if sev_fig else _label(profile.get("name", "?"), profile.get("emoji"))
    kicker = ""
    if you:
        kicker = ('<div style="font-size: 10px; font-weight: 700; '
                  'letter-spacing: 0.09em; text-transform: uppercase; '
                  'opacity: 0.6; margin-bottom: 6px;">As your crew sees it</div>')
    bits = [f'<span style="font-size: 15px; font-weight: 700;">{name}</span>']
    if profile.get("streak") is not None:
        bits.append(f'<span style="opacity: 0.7; font-size: 12px;">'
                    f'{int(profile["streak"])}-day streak</span>')
    ago_txt, _tone = _ago(profile.get("last_active", ""))
    if ago_txt:
        bits.append(f'<span style="opacity: 0.55; font-size: 11px; '
                    f'margin-left: auto;">({_html.escape(ago_txt)})</span>')
    head = '<div style="display: flex; align-items: baseline; gap: 8px; flex: 1; min-width: 0;">' + "".join(bits) + "</div>"
    if sev_fig:  # 3.8.2: Pip beside the line, centred on it, with room above for a hat or a balloon
        head = f'<div style="display: flex; align-items: center; gap: 10px; padding-top: 10px;">{sev_fig}{head}</div>'
    head = kicker + head
    today = profile.get("today")
    if today and not profile.get("paused"):
        head += (f'<div style="font-size: 12px; opacity: 0.8; padding: 4px 0 0;">'
                 f'Today: {today_text(*today)}</div>')
    if profile.get("paused"):
        head += ('<div style="font-size: 12px; font-style: italic; '
                 'opacity: 0.7; padding: 4px 0 0;">on a break</div>')
    if profile.get("exam"):
        head += (f'<div class="dcex" style="font-size: 12px; font-weight: 700; '
                 f'padding: 4px 0 0;">&#128214; '
                 f'{_html.escape(str(profile["exam"]))}</div>')
    if profile.get("away"):
        head += (f'<div class="dcex" style="font-size: 12px; font-weight: 700; '
                 f'padding: 4px 0 0;">&#9992;&#65039; '
                 f'{_html.escape(str(profile["away"]))}</div>')
    status = str(profile.get("status") or "")
    if status or you:
        edit = ""
        if you:
            link = ('style="color: inherit; text-decoration: none; '
                    'border-bottom: 1px dotted currentColor;"')
            edit = (f' <a href="#" {link} onclick="{_pycmd("status")}">'
                    f'{"edit" if status else "Set a status"}</a>')
        quoted = f'&ldquo;{_html.escape(status)}&rdquo;' if status else ""
        head += (f'<div style="font-size: 12px; opacity: 0.8; padding: 4px 0 0;">'
                 f'{quoted}{edit}</div>')
    song_line = _profile_song(profile)
    if song_line:
        head += song_line
    if you:
        link = ('style="color: inherit; text-decoration: none; '
                'border-bottom: 1px dotted currentColor;"')
        closet = ""
        if sev_fig:  # 3.8.2: dress your Pip; the emoji stays for squads, bingo and older add-ons
            closet = (f'<a href="#" {link} onclick="document.getElementById(\'dc-profile\').remove();{_pycmd("closet")}">'
                      f'Pip&rsquo;s closet</a> &middot; ')
        head += (f'<div style="font-size: 12px; opacity: 0.8; padding: 4px 0 0;">{closet}'
                 f'<a href="#" {link} onclick="{_pycmd("emoji")}">'
                 f'{"Change emoji" if profile.get("emoji") else "Pick an emoji"}</a></div>')

    cells = profile.get("cells")
    if cells is None:
        private = "Your heatmap is private." if you else "Their heatmap is private."
        grid = (f'<div style="font-size: 12px; opacity: 0.7; margin: 12px 0;">'
                f'{private}</div>')
    else:
        # rows are weekdays: the first column starts on a Monday, padded with
        # blanks, and the last is padded after today. Until 2.9 the grid
        # started wherever the six months did.
        try:
            pad = _date.fromisoformat(str(profile.get("start"))).weekday()
        except (TypeError, ValueError):
            pad = 0
        try:
            first = _date.fromisoformat(str(profile.get("start")))
        except (TypeError, ValueError):
            first = None
        cols = []
        week = [(-1, None, 0)] * pad
        for i, n in enumerate(cells):
            day = (first + _dt.timedelta(days=i)).isoformat() if first else None
            week.append((_heat_level(int(n)), day, int(n)))
            if len(week) == 7:
                cols.append(week)
                week = []
        if week:
            cols.append(week + [(-1, None, 0)] * (7 - len(week)))

        def cell(lvl, day, n):
            # 3.8.0: on my own card, a day I studied opens its cards in Browse
            if you and day and n > 0:
                d = _date.fromisoformat(day)
                return (f'<i class="dchm h{lvl}" title="{d:%a} {d.day} {d:%b} \u00b7 {n:,} review{"s" if n != 1 else ""}. '
                        f'Browse them" onclick="{_pycmd("heatday:" + day)}"></i>')
            return f'<i class="dchm h{lvl if lvl >= 0 else "x"}"></i>'
        col_html = ""
        for col in cols[-26:]:
            col_html += f'<div class="dchc">{"".join(cell(*c) for c in col)}</div>'
        grid = f'<div class="dchg">{col_html}</div>'

    lines = ""
    duet = profile.get("duet")
    if duet:
        short = _html.escape(str(profile.get("name", "?")).split(" ")[0][:10])

        def _drow(label, seq):
            dots = "".join(f'<i class="dcd{"" if on else " off"}"></i>'
                           for on in seq)
            return (f'<div class="dcduet"><span class="dcdl">{label}</span>'
                    f'<span>{dots}</span></div>')

        if duet.get("mine_week") and duet.get("theirs_week"):
            lines += (_drow("You", duet["mine_week"])
                      + _drow(short, duet["theirs_week"]))
        run, best = int(duet.get("run") or 0), int(duet.get("best") or 0)
        if run > 0:
            unit = "day" if run == 1 else "days"
            tail = f" &mdash; best run: {best}." if best > run else "."
            lines += (f'<div style="font-size: 12px; padding: 4px 0 2px;">'
                      f'You two have studied <b>{run} {unit} in a row '
                      f'together</b>{tail}</div>')
        elif best > 1:
            lines += (f'<div style="font-size: 12px; padding: 4px 0 2px;">'
                      f'Best run together: <b>{best} days</b>.</div>')
    if profile.get("same_days") is not None:
        # named by the month the heatmap above starts, so the two agree
        try:
            since = f' since {_date.fromisoformat(str(profile.get("start"))).strftime("%B")}'
        except (TypeError, ValueError):
            since = ""
        n = int(profile["same_days"])
        lines += (f'<div style="font-size: 12px; padding: 2px 0;">'
                  f'You&rsquo;ve both studied on <b>{n} day{"" if n == 1 else "s"}</b>{since}.</div>')
    if profile.get("decks_line"):
        prefix = "Shares with your crew: " if you else "Shares with you: "
        lines += (f'<div style="font-size: 12px; padding: 2px 0; opacity: 0.8;">'
                  f'{prefix}{_html.escape(str(profile["decks_line"]))}</div>')

    if you:
        link = ('style="color: inherit; font-weight: 700; text-decoration: none; '
                'border-bottom: 1px dotted currentColor;"')
        lines += (f'<div style="font-size: 12px; padding: 8px 0 0; opacity: 0.85;">'
                  f'Copy for the chat: <a href="#" {link} '
                  f'onclick="{_pycmd("sharetoday")}">today</a> &middot; '
                  f'<a href="#" {link} onclick="{_pycmd("shareweek")}">week</a> &middot; '
                  f'<a href="#" {link} onclick="{_pycmd("sharemonth")}">month</a> &middot; '
                  f'<a href="#" {link} onclick="{_pycmd("shareyear")}">year</a></div>')

    inner = _json.dumps(head + grid + lines)
    if you:
        act_label, act_primary = _json.dumps("Privacy…"), "false"
        act_cmd = _json.dumps("duecrew:settings:privacy")
    else:
        act_label, act_primary = _json.dumps("\U0001F389 Send a cheer"), "true"
        act_cmd = _json.dumps(f"duecrew:cheerpick:{profile.get('uid', '')}")
    return POP_JS + """
    (function() {
        // 2.9: colors come from the board, which already follows Settings ->
        // Theme and Accent; Anki's night class is only the fallback (dcPop.theme)
        var T = window.dcPop.theme(), tok = T.tok;
        var dcBg = tok('bg', '#ffffff', '#1c1c1c'), dcInk = tok('ink', '#333333', '#dfe1dc'),
            dcLine = tok('line', '#e2e2da', '#3d403b'), dcWell = tok('well', '#f2f2ec', '#2b2d29'),
            accent = tok('accent', '#2e7d32', '#7cc47f'), accentInk = tok('accent-ink', '#ffffff', '#122912'),
            warn = tok('hours', '#b26a00', '#dda45c');
        var pop = window.dcPop.make({ id: 'dc-profile', label: %s, z: 80, pad: '14vh 0 0' }), back = pop.back;
        var reset = document.createElement('style');  // 3.9.6: Anki's button look (and macOS's own) off the card's; its focus ring back
        reset.textContent = pop.css('#dc-profile button{line-height:normal;font-weight:400;}' +
            '#dc-profile button:focus-visible{outline:2px solid ' + accent + ' !important;outline-offset:2px;}');
        back.appendChild(reset);
        var card = document.createElement('div');
        card.style.cssText = 'min-width:340px;max-width:420px;border-radius:12px;padding:16px 20px;' +
            'box-shadow:0 16px 60px rgba(0,0,0,0.35);' +
            'background:' + dcBg + ';color:' + dcInk + ';border:1px solid ' + dcLine + ';';
        var style = document.createElement('style');
        style.textContent = '.dchg{display:flex;gap:2px;margin:12px 0 8px;}' +
            '.dchc{display:flex;flex-direction:column;gap:2px;}' +
            '.dchm[onclick]{cursor:pointer;}.dchm[onclick]:hover{outline:1px solid ' + accent + ';}' +
            '.dchm{width:8px;height:8px;border-radius:1.5px;display:block;background:' +
            dcWell + ';}' +
            '.dchm.h1{background:' + accent + ';opacity:0.25;}' +
            '.dchm.h2{background:' + accent + ';opacity:0.45;}' +
            '.dchm.h3{background:' + accent + ';opacity:0.7;}' +
            '.dchm.h4{background:' + accent + ';}' +
            '.dchm.hx{visibility:hidden;}' +
            '.dcex{color:' + warn + ';}' +
            '.dcduet{display:flex;align-items:center;gap:8px;padding:1px 0;}' +
            '.dcdl{width:42px;flex-shrink:0;font-size:10px;opacity:0.65;' +
            'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
            '.dcd{width:9px;height:9px;border-radius:50%%;display:inline-block;' +
            'margin-right:6px;background:' + accent + ';}' +
            '.dcd.off{background:' + dcWell + ';}';
        card.appendChild(style);
        var body = document.createElement('div');
        body.innerHTML = %s;
        card.appendChild(body);
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;gap:8px;margin-top:12px;';
        function btn(label, primary) {
            var b = document.createElement('button');
            b.textContent = label;
            b.style.cssText = 'font-size:12.5px;padding:5px 13px;border-radius:6px;cursor:pointer;' +
                (primary ? 'background:' + accent + ';color:' + accentInk +
                           ';border:1px solid transparent;font-weight:600;'
                         : 'background:none;color:inherit;border:1px solid ' +
                           dcLine + ';');
            return b;
        }
        var act = btn(%s, %s);
        act.addEventListener('click', function() {
            pop.close();
            if (typeof pycmd !== 'undefined') { pycmd(%s + '|' + window.dcBK); }
        });
        var close = btn('Close', false);
        close.addEventListener('click', function() { pop.close(); });
        row.appendChild(act);
        var spacer = document.createElement('div');
        spacer.style.flex = '1';
        row.appendChild(spacer);
        row.appendChild(close);
        card.appendChild(row);
        back.appendChild(card);
        pop.show(card);  // Esc or the shade closes it; 3.8.0: out of the name and back into it (dcPop)
    })();
    """ % (_json.dumps(str(profile.get("name") or "?")), inner, act_label, act_primary, act_cmd)
