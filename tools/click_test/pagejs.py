"""The robot's hands and eyes inside a page: installed once a page (again
after a reload), it keeps what the page sends through pycmd, lists the
controls that send a duecrew: command, and presses one with a DOM click
(focused first, as a pointer would). Read-only otherwise."""

import json

HELPER = r"""(function () {
  if (window.__ct && window.__ct.v === 3) { return 'have'; }
  var C = window.__ct = { v: 3, sent: [] };
  function wrap() {
    var orig = window.pycmd;
    if (typeof orig !== 'function' || orig.__ct) { return; }
    var w = function (m) { C.sent.push(String(m)); return orig.apply(this, arguments); };
    w.__ct = true;
    window.pycmd = w;
  }
  wrap();
  C.wrap = wrap;
  var ATTRS = ['onclick', 'onchange', 'oncontextmenu'];
  function attrOf(el) {
    for (var i = 0; i < ATTRS.length; i++) {
      var a = el.getAttribute(ATTRS[i]);
      if (a && a.indexOf('duecrew:') >= 0) { return [ATTRS[i], a]; }
    }
    return null;
  }
  function cmdOf(a) { var m = a.match(/duecrew:([A-Za-z0-9:_.\-]*)/); return m ? m[1] : ''; }
  function shown(el) {
    var r = el.getBoundingClientRect();
    if (!r.width || !r.height) { return false; }
    for (var e = el; e && e.nodeType === 1; e = e.parentElement) {
      var s = getComputedStyle(e);
      if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) { return false; }
    }
    return true;
  }
  function all(scope) {
    var root = scope ? document.querySelector(scope) : document, out = [], seen = {};
    if (!root) { return out; }
    root.querySelectorAll('[onclick*="duecrew:"],[onchange*="duecrew:"],[oncontextmenu*="duecrew:"]').forEach(function (el) {
      ATTRS.forEach(function (name) {  // one control can send two (a crewmate's name: click, and right-click)
        var code = el.getAttribute(name);
        if (!code || code.indexOf('duecrew:') < 0) { return; }
        var c = cmdOf(code), k = name + ' ' + c;
        var n = seen[k] = (seen[k] === undefined ? 0 : seen[k] + 1);
        out.push({ el: el, ev: name.slice(2), code: code, cmd: c, n: n });
      });
    });
    return out;
  }
  C.list = function (scope) {
    return JSON.stringify(all(scope).map(function (x) {
      var el = x.el;
      return { cmd: x.cmd, n: x.n, ev: x.ev, tag: el.tagName.toLowerCase(), type: el.type || '',
        text: ((el.innerText || el.value || el.getAttribute('aria-label') || el.title || '') + '').replace(/\s+/g, ' ').trim().slice(0, 50),
        shown: shown(el), off: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
        pop: !!el.closest('[data-pop]'), reads: /\.value|\bvalue\b/.test(x.code) };
    }));
  };
  function fill(el) {
    // a control that sends what's typed beside it: something in the box first
    var box = el.closest('form, .row, .ad, .du-add, div') || document;
    var inp = box.querySelector('input[type=text], input:not([type]), textarea');
    if (inp && !inp.value) {
      inp.value = 'ROBOTCODE1';
      inp.dispatchEvent(new Event('input', { bubbles: true }));
    }
    return !!inp;
  }
  C.press = function (ev, cmd, n, filled) {
    var x = all(null).filter(function (y) { return y.ev === ev && y.cmd === cmd; })[n];
    if (!x) { return JSON.stringify({ found: false }); }
    wrap();
    var el = x.el, did = 'click';
    C.sent = [];
    try { el.scrollIntoView({ block: 'center', inline: 'nearest' }); } catch (e) { /* not in the page's flow */ }
    var r = el.getBoundingClientRect(), cx = r.left + r.width / 2, cy = r.top + r.height / 2, over = '';
    var top = r.width && r.height ? document.elementFromPoint(cx, cy) : null;
    if (top && top !== el && !el.contains(top) && !top.contains(el)) {
      var cls = top.className && top.className.baseVal === undefined ? '.' + String(top.className).split(' ')[0] : '';
      over = top.id ? '#' + top.id : top.tagName.toLowerCase() + cls;
    }
    if (filled) { fill(el); }
    if (ev === 'change') {
      if (el.tagName === 'SELECT') {
        el.selectedIndex = el.options.length > 1 ? (el.selectedIndex + 1) % el.options.length : 0;
        did = 'choose ' + (el.value || '');
      } else if (el.type === 'date') {
        var d = new Date(Date.now() + 10 * 86400000);
        el.value = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
        did = 'date ' + el.value;
      } else {
        el.value = 'Robot';
        did = 'type Robot';
      }
      el.dispatchEvent(new Event('change', { bubbles: true }));
    } else if (ev === 'contextmenu') {
      el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: cx, clientY: cy }));
      did = 'right-click';
    } else {
      try { el.focus({ preventScroll: true }); } catch (e) { /* can't take focus */ }
      el.click();
    }
    return JSON.stringify({ found: true, sent: C.sent.slice(), over: over, did: did });
  };
  // controls a script made (an onclick of its own, no duecrew: in the markup): the bars' widgets
  function scripted(sel) {
    var out = [];
    document.querySelectorAll(sel).forEach(function (root) {
      [root].concat([].slice.call(root.querySelectorAll('*'))).forEach(function (el) {
        if (typeof el.onclick === 'function' && shown(el) && !el.disabled) { out.push(el); }
      });
    });
    return out;
  }
  C.scripted = function (sel) {
    return JSON.stringify(scripted(sel).map(function (el, i) {
      var r = el.closest('[id]');
      return { i: i, key: (r ? r.id : '') + ' ' + el.tagName.toLowerCase() + ' ' +
        ((el.innerText || el.getAttribute('aria-label') || el.title || '') + '').replace(/\s+/g, ' ').trim().slice(0, 30) };
    }));
  };
  C.pressScripted = function (sel, i) {
    var el = scripted(sel)[i];
    if (!el) { return JSON.stringify({ found: false }); }
    wrap();
    C.sent = [];
    try { el.focus({ preventScroll: true }); } catch (e) { /* fine */ }
    el.click();
    return JSON.stringify({ found: true, sent: C.sent.slice() });
  };
  // where a pointer rests to show a control that shows on hover (its nearest shown box), in CSS px
  C.spot = function (ev, cmd, n) {
    var x = all(null).filter(function (y) { return y.ev === ev && y.cmd === cmd; })[n];
    if (!x) { return null; }
    var e = x.el;
    while (e && e !== document.body && !shown(e)) { e = e.parentElement; }
    if (!e || e === document.body) { return null; }
    try { e.scrollIntoView({ block: 'center' }); } catch (err) { /* fine */ }
    var r = e.getBoundingClientRect();
    return JSON.stringify({ x: r.left + Math.min(r.width / 2, 40), y: r.top + r.height / 2 });
  };
  C.shown = function (ev, cmd, n) {
    var x = all(null).filter(function (y) { return y.ev === ev && y.cmd === cmd; })[n];
    return !!(x && shown(x.el));
  };
  // a window over the board (dcPop) that's open: its id, else ''
  C.pop = function () {
    var p = document.querySelector('[data-pop][id]');
    return p ? p.id : '';
  };
  C.esc = function () {
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    return C.pop();
  };
  C.focusDesc = function () {
    var a = document.activeElement;
    if (!a || a === document.body) { return 'nothing (the page itself)'; }
    var at = attrOf(a);
    return at ? at[0].slice(2) + ' ' + cmdOf(at[1]) : a.tagName.toLowerCase() + (a.id ? '#' + a.id : '') +
      (a.textContent ? ' "' + a.textContent.replace(/\s+/g, ' ').trim().slice(0, 30) + '"' : '');
  };
  return 'new';
})()"""


# two frames from now, the page says so (window.__ctPainted)
PAINT = ("window.__ctPainted = false; requestAnimationFrame(function () { requestAnimationFrame(function () "
         "{ window.__ctPainted = true; }); }); true")


def call(fn, *args):
    """A call into the helper, its JSON args written as JS."""
    return "window.__ct ? window.__ct.%s(%s) : null" % (fn, ", ".join(json.dumps(a) for a in args))


# a button anywhere in a page, by its words (the plan window's, Magic search's): pressed as a pointer would
PRESS_TEXT = r"""(function (sel, words, nth) {
  if (window.__ct) { window.__ct.wrap(); window.__ct.sent = []; }
  var hits = [].slice.call(document.querySelectorAll(sel)).filter(function (b) {
    return (b.textContent || '').replace(/\s+/g, ' ').trim().indexOf(words) === 0 && b.getClientRects().length;
  });
  var b = hits[nth || 0];
  if (!b) { return JSON.stringify({ found: false, n: hits.length }); }
  if (b.disabled) { return JSON.stringify({ found: true, off: true }); }
  try { b.scrollIntoView({ block: 'center' }); b.focus({ preventScroll: true }); } catch (e) { /* fine */ }
  b.click();
  return JSON.stringify({ found: true, sent: window.__ct ? window.__ct.sent.slice() : [] });
})(%s, %s, %s)"""


def press_text(sel, words, nth=0):
    return PRESS_TEXT % (json.dumps(sel), json.dumps(words), int(nth))


# typing into a field: its value, then the events a person's typing fires
TYPE = r"""(function (sel, value, nth) {
  var el = document.querySelectorAll(sel)[nth || 0];
  if (!el) { return false; }
  el.focus();
  el.value = value;
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return true;
})(%s, %s, %s)"""


def type_into(sel, value, nth=0):
    return TYPE % (json.dumps(sel), json.dumps(value), int(nth))
