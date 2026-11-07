"""The page's own: the stylesheet once a page (swap_js), Find a setting, the bars' shade, the motion layer's
scripts (motion.js, show.js), keep_me_in_view_js.

A part of the board (due_crew/board/, 3.9.8): see its __init__."""

import json as _json
import os as _os
import re as _re

from .. import sev as _sev

from .party import PARTY_JS
from .due import DUE_JS


_HERE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))  # due_crew/, where motion.js and show.js are

_LEAD_CSS = _re.compile(r'^(<div id="due-crew"[^>]*>)((?:\s*<style>.*?</style>)+)', _re.S)


def split_css(html_out):
    """3.9.7 (the energy review): (the board without its leading stylesheets,
    their text). They're most of a draw (113 KB of a realistic board's 138),
    and the same from one swap to the next."""
    m = _LEAD_CSS.match(html_out)
    if not m:
        return html_out, ""
    return m.group(1) + html_out[m.end():], "".join(_re.findall(r"<style>(.*?)</style>", m.group(2), _re.S))


def css_key(html_out):
    """The board's stylesheet, as a short key: what a page already holds."""
    import hashlib
    css = split_css(html_out)[1]
    return hashlib.sha1(css.encode("utf-8")).hexdigest()[:16] if css else ""


def swap_js(html_out, have_css=None):
    """3.8.0: the board redrawn in place, without the jumps. While the
    pointer is on Due Crew (a tab clicked, a row ticked), neither part (the
    You box, the board) gets shorter: each keeps its height until the
    pointer leaves (or the window resizes), then lets go at once. A part
    still fetching (.dc-wait) keeps
    its height either way; a box folded by Hide folds at once.
    3.9.7 (the energy review): the board's leading stylesheets go once into
    a page's #dc-css, just before the board, and again only when they
    change (have_css: the key of what this page holds, the glue's to keep);
    a swap carries the board alone. A page without them asks (css)."""
    body, css = split_css(html_out)
    key = css_key(html_out)
    send = css if css and key != have_css else None
    return """
    (function() {
        var el = document.getElementById('due-crew');
        if (!el) { return; }
        var H = %s, CSS = %s, st = document.getElementById('dc-css');
        if (H) {
            if (CSS !== null) {
                if (!st) { st = document.createElement('style'); st.id = 'dc-css'; }
                if (st.getAttribute('data-h') !== H) { st.textContent = CSS; st.setAttribute('data-h', H); }
            } else if (!st || st.getAttribute('data-h') !== H) {
                if (typeof pycmd !== 'undefined') { pycmd('duecrew:css|' + window.dcBK); }  // lost it: the glue sends it again
                return;
            }
            if (st.nextSibling !== el) { el.parentNode.insertBefore(st, el); }
        }
        var parts = [':scope > .du', '.dc-sheet'], was = {};
        var on = el.matches(':hover');
        parts.forEach(function (s) { var p = el.querySelector(s); if (p) { was[s] = p.getBoundingClientRect().height; } });
        // a to-do half typed when a redraw comes (a refresh, learning cards back): kept, with its day
        var din = document.getElementById('du-in'), keep = null;
        if (din && el.contains(din) && document.activeElement === din && din.value) {
            var w0 = document.getElementById('du-when'), d0 = document.getElementById('du-date');
            keep = {v: din.value, s: din.selectionStart, e: din.selectionEnd, w: w0 ? w0.value : null,
                    d: d0 ? d0.value : null, dd: d0 ? d0.style.display : null};
        }
        var tmp = document.createElement('div');
        tmp.innerHTML = %s;
        var nu = tmp.firstElementChild;
        var mo = null;  // 3.8.0: what changed moves (motion.js); the swap goes on whatever it does
        try { mo = window.dcMotion ? dcMotion.before(el) : null; } catch (e) { mo = null; }
        el.parentNode.replaceChild(nu, el);
        if (keep) {
            var n1 = document.getElementById('du-in');
            if (n1 && !n1.value) {
                n1.value = keep.v; n1.focus();
                try { n1.setSelectionRange(keep.s, keep.e); } catch (e) {}
                var w1 = document.getElementById('du-when'), d1 = document.getElementById('du-date');
                if (w1 && keep.w) { w1.value = keep.w; }
                if (d1 && keep.d !== null) { d1.value = keep.d; d1.style.display = keep.dd; }
                n1.dispatchEvent(new Event('input'));
            }
        }
        try { if (mo) { dcMotion.after(nu, mo); } } catch (e) {}
        var held = [];
        parts.forEach(function (s) {
            var p = nu.querySelector(s);
            if (!p || !was[s] || p.classList.contains('du-one')) { return; }
            if ((on || p.querySelector('.dc-wait')) && p.getBoundingClientRect().height < was[s] - 1) {
                p.style.boxSizing = 'border-box';
                p.style.minHeight = was[s] + 'px';
                held.push(p);
            }
        });
        if (held.length) {
            // let go at once when the pointer leaves, the window resizes or loses focus
            // (an eased release lagged behind a window being resized)
            var free = function () {
                held.forEach(function (p) { if (!p.querySelector('.dc-wait')) { p.style.minHeight = ''; } });
                window.removeEventListener('resize', free);
                window.removeEventListener('blur', free);
            };
            nu.addEventListener('mouseleave', free);
            window.addEventListener('resize', free);
            window.addEventListener('blur', free);
        }
    })();
    """ % (_json.dumps(key), _json.dumps(send).replace("</", "<\\/") if send is not None else "null", _json.dumps(body))


# 3.8.0, pick 28: Find a setting. The box's index (settings_index) is in its
# data-ix; a pick on another tab asks for that tab, and the next draw lands on it.
FIND_JS = r"""
(function () {
  if (!window.dcFind) {
    window.dcFind = {
      want: null,
      ix: function (inp) { try { return JSON.parse(inp.getAttribute('data-ix') || '[]'); } catch (e) { return []; } },
      type: function (inp) {
        var box = inp.nextElementSibling, q = inp.value.toLowerCase().match(/[a-z0-9]+/g) || [], self = this;
        while (box.firstChild) { box.removeChild(box.firstChild); }
        if (!q.length) { box.hidden = true; return; }
        var hits = this.ix(inp).filter(function (x) {
          var k = ' ' + x.k;
          return q.every(function (w) { return k.indexOf(' ' + w) >= 0; });
        }).slice(0, 7);
        if (!hits.length) {
          var n = document.createElement('span'); n.className = 'st-none'; n.textContent = 'Nothing by that name';
          box.appendChild(n);
        }
        hits.forEach(function (h, i) {
          var b = document.createElement('button'), l = document.createElement('b'), w = document.createElement('small');
          b.type = 'button'; b.setAttribute('role', 'option'); if (!i) { b.className = 'on'; }
          l.textContent = h.l; w.textContent = h.w; b.appendChild(l); b.appendChild(w);
          b.addEventListener('click', function () { box.hidden = true; inp.value = ''; self.go(h); });
          box.appendChild(b);
        });
        box.hidden = false;
      },
      key: function (e, inp) {
        var box = inp.nextElementSibling;
        if (e.key === 'Escape') { inp.value = ''; box.hidden = true; return; }
        if (e.key === 'Enter') { e.preventDefault(); var b = box.querySelector('button'); if (b) { b.click(); } }
      },
      go: function (h) {
        if (h.p) { pycmd('duecrew:' + h.p + '|' + window.dcBK); return; }  // 3.9.3: a plan window, not a setting
        var on = document.querySelector('#due-crew .dc-head .dc-pill.on');
        var tab = on ? (on.getAttribute('data-f') || '').split(':')[1] : '';
        if (tab === h.t) { this.land(h.f); return; }
        this.want = {f: h.f, at: Date.now()};
        pycmd('duecrew:settab:' + h.t + '|' + window.dcBK);
      },
      land: function (f) {
        var el = document.querySelector('#due-crew [data-f="' + f + '"]') || document.querySelector('#due-crew [data-f^="' + f + '"]');
        if (!el) { return; }
        var row = el.closest('.st-row, .st-radio, .st-acts, .st-foot') || el;
        var still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        row.scrollIntoView({block: 'center', behavior: still ? 'auto' : 'smooth'});
        row.classList.remove('st-hit'); void row.offsetWidth; row.classList.add('st-hit');
        setTimeout(function () { row.classList.remove('st-hit'); }, 2400);
        try { el.focus({preventScroll: true}); } catch (e) {}
      },
      after: function () {
        var w = this.want, self = this;
        this.want = null;
        if (w && Date.now() - w.at < 4000) { setTimeout(function () { self.land(w.f); }, 0); }  // after the swap's own focus
      }
    };
  }
  window.dcFind.after();
})();
"""

# 3.8.0: the board's motion, one file shared with duecrew.com (site/public/motion.js, byte for byte)
with open(_os.path.join(_HERE, "motion.js"), encoding="utf-8") as _f:
    MOTION_JS = _f.read()
# 3.9.0: how a cheer lands, a show over the whole Decks screen (shows.py picks which)
with open(_os.path.join(_HERE, "show.js"), encoding="utf-8") as _f:
    SHOW_JS = _f.read()


def keep_me_in_view_js(scripts=True):
    """Run after the board is drawn or swapped: a capped view starts with
    your own row in view, wherever it ranks. Nothing happens under the
    cap, or when you are already visible. scripts (3.9.1, the efficiency
    run): the board's own scripts with it (Due's add line, motion.js,
    Find), which a page keeps once it has them and which load only once
    (each checks it isn't there yet); without, only what each does after
    a draw (Find lands, the motion's memory), for a swap on a page that
    has them (the glue's _board_js). A part's own <script> never runs (a
    swap draws by innerHTML), so Pip Party's (PARTY_JS) rides here too."""
    return """
    (function() {
        var box = document.querySelector('#due-crew .dc-scroll');
        if (!box) { return; }
        var me = box.querySelector('tr.you') || box.querySelector('.dr.me');
        if (!me) { return; }
        var want = me.offsetTop - (box.clientHeight - me.offsetHeight) / 2;
        if (want > 0) { box.scrollTop = want; }
    })();
    """ + (DUE_JS + MOTION_JS + FIND_JS + VEIL_WATCH_JS + PARTY_JS + _sev.REST_JS if scripts else FIND_AFTER) + MOTION_DRAWN


# 3.9.1 (Sam: "when cheering, the full background doesn't grey out"): a
# window over the board dims the board's page; the glue dims the top and
# bottom bars to match (app.veil) while one is up. This tells it when: a
# window comes, or the last one goes (a closing one gives up its id as it
# starts to fade, motion.js, so the bars fade with it).
VEIL_IDS = ("dc-cheer", "dc-profile", "dc-sheet", "dc-song", "dc-magic")  # 3.9.6: the song search; 3.9.7: Magic search's how-to
VEIL_WATCH_JS = """
(function () {
    if (window.dcVeil || typeof MutationObserver === 'undefined') { return; }
    var on = false, IDS = %s;
    window.dcVeil = function () {
        var now = IDS.some(function (id) { return !!document.getElementById(id); });
        if (now === on) { return; }
        on = now;
        if (typeof pycmd !== 'undefined') { pycmd('duecrew:veil:' + (on ? 1 : 0) + '|' + window.dcBK); }
    };
    new MutationObserver(window.dcVeil).observe(document.body, { childList: true });
    new MutationObserver(window.dcVeil).observe(document.body, { attributes: true, attributeFilter: ['id'], subtree: true });
})();
""" % _json.dumps(list(VEIL_IDS))


# what FIND_JS does at every draw once it's on the page
FIND_AFTER = """
if (window.dcFind) { window.dcFind.after(); }
"""


# 3.8.0, round two: the board remembers what it said, so a draw anew (back
# from a review, no swap) moves what changed while I was away (motion.js)
MOTION_DRAWN = """
try { if (window.dcMotion) { dcMotion.drawn(document.getElementById('due-crew')); } } catch (e) {}
"""
