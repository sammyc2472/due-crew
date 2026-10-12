/* Due Crew's motion (3.8.0, "Board in Motion": Sam picked all seventeen,
   then round two's eighteen). One file in two places, byte for byte:
   due_crew/motion.js (the add-on's board, around board.swap_js) and
   site/public/motion.js (duecrew.com, around the board's draw). The suite
   checks they match.

   A redraw replaces the board whole. Before it, before() notes each thing
   the rules below know (a tick, a bar, a number, a tab, a tile, a stamp):
   what it said and where it sat. After it, after() moves only what
   changed, from what it was to what it is. A refresh that changes nothing
   moves nothing; nothing moves with the system's Reduce motion on; rows
   never slide past each other (never a race). A click that causes a
   redraw can leave a hint first (the tile it zoomed, the to-do it added).

   Round two: a thing that leaves (a banner, a note, a topic that's
   sticking now, Behind when I'm caught up) is put back for a moment where
   it was and folds away; Settings and the board slide past each other; a
   profile grows from its name. And a memory: the add-on's Decks screen is
   drawn anew after a review (no swap), so drawn() keeps what the board
   said in the page's session storage, and the next draw on the same Anki
   day moves what changed while I was away (counts, ticks, bars, shades,
   a topic that started sticking), never what's simply new on screen. */
(function () {
  "use strict";
  if (window.dcMotion) return;
  var EASE = "cubic-bezier(.2,.8,.2,1)", FAST = 140, BASE = 220, SLOW = 420;
  var M = window.dcMotion = { hint: null };

  M.ok = function () {
    try { return !window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch (e) { return true; }
  };
  function anim(el, kf, o) {
    if (!el || !el.animate || !M.ok()) return null;
    try { return el.animate(kf, Object.assign({ duration: BASE, easing: EASE }, o || {})); } catch (e) { return null; }
  }
  function done(a, f) { if (a) a.onfinish = a.oncancel = f; else f(); }
  M.anim = anim;

  // ---- who's who across a redraw ----
  function cmdOf(el) {
    var a = el && el.getAttribute && el.getAttribute("onclick");
    var m = a && a.match(/duecrew:([^'"]+)/);
    return m ? m[1] : "";
  }
  function words(el) { return el ? el.textContent.replace(/\s+/g, " ").trim().slice(0, 60) : ""; }
  function who(row) {
    if (!row) return "";
    if (row.dataset && row.dataset.uid) return row.dataset.uid;
    var a = row.querySelector('[onclick*="duecrew:profile:"]');
    var m = a && a.getAttribute("onclick").match(/profile:([^'"]+)/);
    return m ? m[1] : words(row.querySelector(".nm, .dn, td"));
  }
  function rowOf(el) { return el.closest(".du-r, .du-ln, .du-sub, .du-one, .du-h, .pc, .r, tr, .dr, .du"); }
  // which view a cell is in (Crew's Today or Week, a squad): their cells never pass for each other
  function view(el) {
    var t = el.closest("table"), part = el.closest(".dc-sheet, .dc-panel, .du") || document;
    var on = (t && t.querySelector(".dc-sw a.on")) || part.querySelector(".dc-sw a.on, .sqsw .on, .pills .on");
    return words(on) + "|" + (t ? t.rows[0].cells.length : "");
  }
  function place(el) { return el.closest(".du") ? "du" : "sheet"; }
  function nth(el) { return Array.prototype.indexOf.call(el.parentNode.children, el); }
  function cls(el) { return el.className && el.className.baseVal !== undefined ? el.className.baseVal : (el.className || ""); }
  // Insights' deck (each of its commands carries the deck id), the You box's tab, the board's
  function insDid(el) {
    var a = el && (el.matches && el.matches('[onclick*="duecrew:ins"]') ? el : el.querySelector('[onclick*="duecrew:ins"]'));
    var m = a && a.getAttribute("onclick").match(/duecrew:ins[a-z]*:(\d+)/);
    return m ? m[1] : "";
  }
  function dueTab(root) { return words(root.querySelector(".du-tabs a.on")) + (root.querySelector(".du-one") ? ":one" : ""); }
  function sheetTab(root) { return words(root.querySelector(".dc-head .on, .dc-tabs .on, .tabs .on")) + ":" + words(root.querySelector(".dc-sw a.on")); }
  // a table's columns, counting the corner's two
  function colOf(c) { var n = 0; for (var x = c.previousElementSibling; x; x = x.previousElementSibling) n += x.colSpan || 1; return n; }
  function cellAt(tr, col) {
    var n = 0;
    for (var i = 0; i < tr.cells.length; i++) { if (n === col) return tr.cells[i]; n += tr.cells[i].colSpan || 1; }
    return null;
  }
  function headOf(td) { var t = td.closest("table"); return t && t.rows[0] ? words(cellAt(t.rows[0], colOf(td))) : ""; }
  function num(s) { var d = String(s || "").replace(/[^\d]/g, ""); return d ? +d : NaN; }

  var RULES = [
    // 1 a tick; its row's words get their line
    { sel: ".du-bx", kind: "tick", key: function (el) { return "bx:" + (cmdOf(el) || words(rowOf(el))); },
      val: function (el) { return el.classList.contains("on") ? "1" : el.classList.contains("part") ? "p" : "0"; } },
    // 2 the day's bar, and a plan date's
    { sel: ".wbar > i", kind: "bar", key: function (el) { return "bar:" + words(rowOf(el)).replace(/\d[\d,]*/g, "#"); },
      val: function (el) { return el.style.width; } },
    { sel: ".du-n", kind: "text", key: function () { return "dun"; }, val: function (el) { return words(el); } },
    // 3 done for today, 6 Hide and Show
    { sel: ".du", kind: "due", key: function () { return "du"; },
      val: function (el) { return (el.classList.contains("du-one") ? "one" : "open") + (finished(el) ? ":done" : ""); } },
    // 5 learning back, flagged: a row's count says "back" then "due"
    { sel: ".du-r", kind: "row", key: function (el) { return "r:" + words(el.querySelector(".t > b, .t")); },
      val: function (el) { return words(el.querySelector(".end .n")); } },
    // 7 tabs, a line or a pill that follows the pick
    { sel: ".du-h, .dc-sw, .dc-head, .st-tabs, .pills, .sqsw", kind: "tabs",
      key: function (el) { return "tabs:" + cls(el).split(" ")[0] + ":" + place(el); },
      val: function (el) { var on = el.querySelector("a.on, button.on"); return on ? words(on) : ""; } },
    // 8 the plan week's ‹ ›
    { sel: ".pwk", kind: "week", key: function () { return "pwk"; }, val: function (el) { return words(el.querySelector(".pc .d")); } },
    // 9 the map, a level at a time
    { sel: ".tmap", kind: "map", key: function () { return "tmap"; },
      val: function (el) { return Array.prototype.map.call(el.querySelectorAll(".tm > span"), words).join("|"); } },
    // 10 numbers that changed (a cell by its person and column; rows keep their places)
    { sel: "td.n", kind: "num", key: function (el) { return "n:" + view(el) + ":" + who(el.closest("tr")) + ":" + el.cellIndex; },
      val: function (el) { return words(el); } },
    // 11 a friend's day fills in
    { sel: "td.sqc > i.sq", kind: "pop", key: function (el) { return "sq:" + view(el) + ":" + who(el.closest("tr")) + ":" + el.parentNode.cellIndex; },
      val: function (el) { return cls(el).indexOf("on") >= 0 ? "on" : ""; } },
    // 12 Decks bars grow in, when Decks opens
    { sel: ".dtrack", kind: "grow", key: function (el) { return "dt:" + who(el.closest(".dr, tr")); }, val: function () { return ""; } },
    // 14 refreshing: the foot's "Updated …"
    { sel: ".dc-foot .upd", kind: "text", key: function () { return "upd"; }, val: function (el) { return words(el); } },
    // 15 a bingo stamp, and a line
    { sel: ".bg-mini > i, .bgmini > i", kind: "stamp", key: function (el) { return "bm:" + nth(el); }, val: function (el) { return cls(el); } },
    { sel: ".bg-sq", kind: "stamp", key: function (el) { return "bq:" + el.dataset.i; },
      val: function (el) { return (el.classList.contains("done") ? "done " : "") + (el.classList.contains("line") ? "line" : ""); } },
    { sel: ".bg-t > span, .bgt > span", kind: "shout", key: function () { return "bs"; }, val: function (el) { return words(el); } },
    // 16 Insights' line draws in
    { sel: "svg.ispark", kind: "draw", key: function () { return "spark"; }, val: function () { return ""; } },
    // ---- round two ----
    // 19 the column you sort by
    { sel: "th > a.on", kind: "sort", key: function (el) { return "sort:" + place(el) + ":" + view(el); }, val: function (el) { return words(el); } },
    // 23 a banner: a knock, a notice, a room's invite (its "1 of 3 ›" isn't who it is)
    { sel: ".dc-wrap", kind: "wrap", key: function (el) { return "w:" + words(el).replace(/\d+ of \d+ ›/, ""); }, val: function () { return ""; },
      leave: { ctx: sheetTab } },
    // 30 a note under the box's tabs
    { sel: ".du-line", kind: "note", key: function (el) { return "ln:" + words(el); }, val: function () { return ""; },
      leave: { ctx: dueTab } },
    // 24 who's in the room
    { sel: ".dc-room .fc > i", kind: "face", key: function (el) { return "fc:" + words(el); }, val: function () { return ""; },
      leave: { ctx: function (root) { return words(root.querySelector(".dc-room .rt > b")); }, fx: "shrink" } },
    // 26 a topic starts sticking: its bars move; gone from the list, it says so on its way out
    { sel: ".irow", kind: "irow", key: function (el) { return "ir:" + insDid(el) + ":" + words(el.querySelector(".n b")); },
      val: function (el) { return words(el.querySelector(".c")); },
      extra: function (el) { return Array.prototype.map.call(el.querySelectorAll(".ib > i"), function (b) { return b.style.width; }).join(" "); },
      leave: { ctx: function (root) { return dueTab(root) + ":" + insDid(root.querySelector(".du")); }, up: ".isec", fx: "sticking", mem: true } },
    // 27 a map tile changes shade
    { sel: ".tmap .tm", kind: "shade", key: function (el) { return "tm:" + insDid(el) + ":" + words(el.querySelector("span")); },
      val: function (el) { return cls(el) + "|" + words(el.querySelector("b")); },
      extra: function (el) { return getComputedStyle(el).backgroundColor; } },
    // 29 caught up: Behind goes, saying so
    { sel: ".du-bh", kind: "behind", key: function () { return "bh"; }, val: function () { return ""; },
      leave: { ctx: dueTab, fx: "caught", mem: true } },
    // 35 Study today names the next deck
    { sel: ".du-go .nm", kind: "text", key: function () { return "go"; }, val: function (el) { return words(el); } }
  ];
  // what can move when the board comes back from a review (the memory): changes only, never a tab or a fold
  var MEMO = { tick: 1, bar: 1, text: 1, due: 1, row: 1, num: 1, pop: 1, stamp: 1, shout: 1, irow: 1, shade: 1 };

  function finished(du) {
    var n = du.querySelector(".du-n");
    var t = n ? n.textContent : "";
    var m = t.match(/(\d+) of (\d+) done/);
    return /Done for today/.test(t) || !!(m && +m[2] > 0 && m[1] === m[2]);
  }

  function each(root, f) {
    RULES.forEach(function (rule) {
      var seen = {};
      Array.prototype.forEach.call(root.querySelectorAll(rule.sel), function (el, i) {
        if (el.closest("[data-dc-ghost]")) return;  // one on its way out isn't there
        var k = rule.key(el, i);
        seen[k] = (seen[k] || 0) + 1;
        if (seen[k] > 1) k += "#" + seen[k];
        f(rule, el, k);
      });
    });
  }

  // where a thing sat: the child indexes from the board down to it, and its parent's class
  function pathOf(root, el) {
    var path = [];
    for (var x = el; x && x !== root; x = x.parentElement) path.unshift(nth(x));
    return x === root ? path : null;
  }
  function at(root, path) {
    var x = root;
    for (var i = 0; x && i < path.length; i++) x = x.children[path[i]];
    return x || null;
  }
  // a parent is the same one when its class and its heading are (two sections can share a class)
  function sig(p, sel) {
    var h = p && p.firstElementChild;
    return cls(p) + "|" + (h && !(sel && h.matches(sel)) ? words(h).slice(0, 24) : "");
  }
  // what a leaving thing needs to come back for a moment: its markup and its place
  function spot(root, rule, el) {
    if (!rule.leave || el.hidden || !el.offsetHeight) return null;
    var p = pathOf(root, el);
    if (!p) return null;
    var o = { html: el.outerHTML, path: p, pc: sig(el.parentElement, rule.sel), ctx: rule.leave.ctx(root) };
    var up = rule.leave.up && el.parentElement.closest(rule.leave.up);
    if (up && root.contains(up)) o.up = { html: up.outerHTML, path: pathOf(root, up), pc: sig(up.parentElement, rule.leave.up) };
    return o;
  }

  // the place of a group's picked item, inside the group (it moves as one when the page scrolls)
  function onIn(g) {
    var on = g.querySelector("a.on, button.on");
    if (!on) return null;
    var a = g.getBoundingClientRect(), b = on.getBoundingClientRect(), cs = getComputedStyle(on);
    var bg = cs.backgroundColor, pill = bg && bg !== "transparent" && !/rgba\(\d+, \d+, \d+, 0\)/.test(bg);
    return { x: b.left - a.left, y: b.top - a.top, w: b.width, h: b.height, pill: pill, bg: bg, r: cs.borderRadius };
  }

  // a click's hint is for the redraw it causes, not one minutes later
  function fresh(h) { return h && Date.now() - (h.at || 0) < 4000 ? h : null; }
  M.say = function (h) { h.at = Date.now(); M.hint = h; };

  function mode(root) { return root.classList.contains("dc-set") ? "set" : root.classList.contains("bg-full") ? "card" : "board"; }

  M.before = function (root) {
    var snap = { at: {}, hint: fresh(M.hint), parts: {}, rows: {} };
    M.hint = null;
    if (!root) return snap;
    snap.mode = mode(root);
    snap.h = root.offsetHeight;
    Array.prototype.forEach.call(root.querySelectorAll(".du-r, .du-ln"), function (r) { snap.rows[words(r)] = 1; });
    each(root, function (rule, el, k) {
      var r = el.getBoundingClientRect();
      snap.at[k] = { v: rule.val(el), w: el.style.width, t: words(el), h: el.offsetHeight, r: r,
                     on: rule.kind === "tabs" ? onIn(el) : null, x: rule.extra ? rule.extra(el) : null,
                     go: spot(root, rule, el), kind: rule.kind };
    });
    [".du", ".dc-sheet", ".dc-panel"].forEach(function (s) {
      var p = root.matches(s) ? root : root.querySelector(s);
      if (p) snap.parts[s] = p.offsetHeight;
    });
    return snap;
  };

  M.after = function (root, snap) {
    M.swapped = Date.now();
    if (!root || !snap || !M.ok()) return;
    // 18 Settings (or a bingo card) and the board: one slides in as the other goes
    if (snap.mode && snap.mode !== mode(root)) { turn(root, snap); return; }
    var cold = !Object.keys(snap.at).length, entered = [], tabbed = [], here = {};
    each(root, function (rule, el, k) {
      here[k] = 1;
      var was = snap.at[k], v = rule.val(el);
      if (!was) { if (!cold && !snap.mem) entered.push([rule.kind, el]); return; }
      if (was.v === v || (snap.mem && !MEMO[rule.kind])) return;
      var f = CHANGE[rule.kind];
      if (f) f(el, was, v, snap);
      if (rule.kind === "tabs") tabbed.push(el);
    });
    var n = 0;
    if (!snap.mem) {
      entered.forEach(function (x) {
        if (tabbed.length && (x[0] === "wrap" || x[0] === "note" || x[0] === "face")) return;  // a tab's own lines come in with it
        var f = ENTER[x[0]];
        if (f) f(x[1], n++, snap);
      });
      tabbed.forEach(function (g) { settle(g, snap); });
      added(root, snap, entered);
    }
    gone(root, snap, here, entered);
  };

  // ---- the memory: a board drawn anew (back from a review) moves what changed while I was away ----
  var MEM = "dcMotion";
  function day(root) { var d = root.querySelector(".du[data-today]"); return d ? d.getAttribute("data-today") : ""; }
  function me(root) { return who(root.querySelector("tr.you, .dr.me")); }  // whose board (another profile's isn't this one)
  M.drawn = function (root) {
    if (!root) return;
    var snap = null;
    if (Date.now() - (M.swapped || 0) > 1000) {
      try { snap = JSON.parse(sessionStorage.getItem(MEM) || "null"); } catch (e) { snap = null; }
      if (snap && snap.mode === mode(root) && snap.day === day(root) && snap.me === me(root) && Date.now() - snap.t < 3 * 3600 * 1000) {
        snap.mem = true;
        try { M.after(root, snap); } catch (e) { /* the board is drawn either way */ }
      }
    }
    // the logo waves with the board's first draw of the (Anki) day
    var today = day(root) || new Date().toDateString();
    try {
      if (sessionStorage.getItem(MEM + ":logo") !== today) { sessionStorage.setItem(MEM + ":logo", today); M.logo(root, 300); }
    } catch (e) { /* no storage: no wave */ }
    var keep = { t: Date.now(), mode: mode(root), day: day(root), me: me(root), at: {} };
    each(root, function (rule, el, k) {
      if (!MEMO[rule.kind] && !(rule.leave && rule.leave.mem)) return;
      var go = rule.leave && rule.leave.mem ? spot(root, rule, el) : null;
      keep.at[k] = { v: rule.val(el), w: el.style.width, t: words(el), x: rule.extra ? rule.extra(el) : null, go: go, kind: rule.kind };
    });
    try { sessionStorage.setItem(MEM, JSON.stringify(keep)); } catch (e) { /* no room: no memory */ }
  };

  // ---- small moves ----
  function pop(el, k, ms) {
    return anim(el, [{ transform: "scale(" + (k ? 0.4 : 1) + ")" }, { transform: "scale(1.18)", offset: 0.6 }, { transform: "scale(1)" }],
                { duration: ms || 320 });
  }
  function glow(el, ms) {
    return anim(el, [{ backgroundColor: "color-mix(in srgb, var(--dc-accent, #2e7d32) 22%, transparent)" },
                     { backgroundColor: "transparent" }], { duration: ms || 1400, easing: "ease-out" });
  }
  function rise(el, delay) {
    return anim(el, [{ opacity: 0, transform: "translateY(4px)" }, { opacity: 1, transform: "none" }],
                { duration: 180, delay: delay || 0, fill: "backwards" });
  }
  // a number from what it said to what it says: 1,234 or 2h 04m or 84%; anything else just glows
  function count(el, from, to, ms) {
    var fmt, a, b, tm = /^(?:(\d+)h )?(\d+)m$/, nm = /^\d[\d,]*$/, pc = /^(\d+)%$/;
    if (pc.test(from) && pc.test(to)) {
      a = +from.match(pc)[1]; b = +to.match(pc)[1];
      fmt = function (x) { return Math.round(x) + "%"; };
    } else if (nm.test(from) && nm.test(to)) {
      a = +from.replace(/,/g, ""); b = +to.replace(/,/g, "");
      fmt = function (x) { return Math.round(x).toLocaleString("en-US"); };
    } else if (tm.test(from) && tm.test(to)) {
      var p = from.match(tm), q = to.match(tm);
      a = (+(p[1] || 0)) * 60 + (+p[2]); b = (+(q[1] || 0)) * 60 + (+q[2]);
      fmt = function (x) { x = Math.round(x); return x >= 60 ? Math.floor(x / 60) + "h " + ("0" + (x % 60)).slice(-2) + "m" : x + "m"; };
    } else return;
    if (a === b || !M.ok()) return;
    var t0 = performance.now(), keep = el.textContent;
    (function step(t) {
      var k = Math.min(1, (t - t0) / (ms || SLOW)), e = 1 - Math.pow(1 - k, 3);
      if (!el.isConnected) return;
      el.textContent = k < 1 ? fmt(a + (b - a) * e) : keep;
      if (k < 1) requestAnimationFrame(step);
    })(t0);
  }

  var CHANGE = {
    tick: function (el, was, v) {
      if (v !== "1") return;
      pop(el, 0, BASE);
      try {
        el.animate([{ clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0 0)" }],
                   { duration: BASE, delay: 60, easing: EASE, fill: "backwards", pseudoElement: "::after" });
      } catch (e) { /* an older browser: the box fills, the check is there */ }
      var row = el.closest(".du-r, .du-ln");
      if (!row) return;
      Array.prototype.forEach.call(row.querySelectorAll(".t > b, .t > span.x, :scope > span:nth-child(2)"), function (t) {
        var c = getComputedStyle(t).textDecorationColor;
        anim(t, [{ textDecorationColor: "transparent" }, { textDecorationColor: c }], { duration: SLOW });
      });
    },
    bar: function (el, was) {
      if (was.w && el.style.width && was.w !== el.style.width) anim(el, [{ width: was.w }, { width: el.style.width }], { duration: SLOW });
    },
    text: function (el, was) { rise(el); count(el, was.t, words(el)); },
    due: function (el, was, v) {
      var fold = was.v.split(":")[0] !== v.split(":")[0];
      if (fold && was.h && el.offsetHeight !== was.h) {
        var h = el.offsetHeight;
        el.style.overflow = "hidden";
        done(anim(el, [{ height: was.h + "px" }, { height: h + "px" }], { duration: BASE }), function () { el.style.overflow = ""; });
        Array.prototype.forEach.call(el.children, function (c, i) { rise(c, 40 + i * 20); });
      }
      if (/:done$/.test(v) && !/:done$/.test(was.v)) { sweep(el); M.logo(el.closest("#due-crew, .brd") || document, 500); }
    },
    row: function (el, was, v) { if (/ back/.test(was.v) && / due/.test(v)) glow(el, 1200); },
    tabs: function (el, was) { slide(el, was.on); },
    week: function (el, was, v, snap) {
      var dir = (snap.hint && snap.hint.week) || 1;
      Array.prototype.forEach.call(el.querySelectorAll(".pc"), function (c, i) {
        anim(c, [{ opacity: 0, transform: "translateX(" + (24 * dir) + "px)" }, { opacity: 1, transform: "none" }],
             { duration: BASE, delay: i * 15, fill: "backwards" });
      });
    },
    map: function (el, was, v, snap) { zoom(el, snap.hint); },
    num: function (el, was, v) {
      count(el, was.t, v); glow(el);
      if (/Streak/.test(headOf(el)) && num(v) > num(was.t)) flame(el);  // 20 a streak ticks up
    },
    pop: function (el, was, v) { if (v === "on") pop(el, 1); },
    stamp: function (el, was, v) {
      var on = function (s) { return /(^| )(on|done)( |$)/.test(s); };
      if (on(v) && !on(was.v)) anim(el, [{ transform: "scale(1)" }, { transform: "scale(1.18)", offset: 0.35 },
                                         { transform: "scale(.94)", offset: 0.7 }, { transform: "scale(1)" }], { duration: 300 });
      if (/line/.test(v) && !/line/.test(was.v)) {
        var i = +(el.dataset.i || 0);
        anim(el, [{ boxShadow: "inset 0 0 0 0 transparent" }, { boxShadow: "inset 0 0 0 3px var(--dc-accent, #2e7d32)" },
                  { boxShadow: "inset 0 0 0 1px var(--dc-accent, #2e7d32)" }], { duration: 420, delay: 300 + (i % 3) * 90, fill: "backwards" });
      }
    },
    shout: function (el, was, v) {
      if (/BINGO|lines|whole card/.test(v) && !/BINGO|lines|whole card/.test(was.v)) {
        el.style.display = el.style.display || "inline-block";
        anim(el, [{ transform: "scale(.7)", opacity: 0 }, { transform: "scale(1.1)", opacity: 1, offset: 0.6 }, { transform: "scale(1)" }],
             { duration: 360, delay: 420, fill: "backwards" });
      } else rise(el);
    },
    // 19 the column you sorted by washes green once; the rows just change places
    sort: function (el) {
      var th = el.closest("th"), t = el.closest("table");
      if (!th || !t) return;
      var col = colOf(th);
      Array.prototype.forEach.call(t.rows, function (tr, i) {
        var c = i && cellAt(tr, col);
        if (c && c.tagName === "TD") glow(c, 900);
      });
    },
    // 26 a topic's bars move to what they are now, its count with them
    irow: function (el, was) {
      var ws = String(was.x || "").split(" ");
      Array.prototype.forEach.call(el.querySelectorAll(".ib > i"), function (b, i) {
        if (ws[i] && ws[i] !== b.style.width) anim(b, [{ width: ws[i] }, { width: b.style.width }], { duration: SLOW });
      });
      var c = el.querySelector(".c b");
      if (c) count(c, (was.v.match(/^\d[\d,]*/) || [""])[0], words(c));
    },
    // 27 a map tile eases into its new shade, its % counting there
    shade: function (el, was) {
      var bg = getComputedStyle(el).backgroundColor;
      if (was.x && was.x !== bg) anim(el, [{ backgroundColor: was.x }, { backgroundColor: bg }], { duration: 600, easing: "ease-in-out" });
      var b = el.querySelector("b");
      if (b) count(b, String(was.v).split("|")[1] || "", words(b), 600);
    }
  };

  var ENTER = {
    // 23, 30 a banner, a note: it opens into its place
    wrap: function (el) { unfold(el); },
    note: function (el) { unfold(el); },
    // 24 someone joins the room: in at the end
    face: function (el) {
      anim(el, [{ opacity: 0, transform: "translateX(8px) scale(.6)" }, { opacity: 1, transform: "none" }], { duration: BASE });
    },
    // 25 a plan's week, when Plans opens: each day's bar grows, left to right
    week: function (el) {
      Array.prototype.forEach.call(el.querySelectorAll(".wbar > i"), function (b, i) {
        b.style.transformOrigin = "left center";
        anim(b, [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], { duration: SLOW, delay: Math.min(i, 12) * 40, fill: "backwards" });
      });
    },
    grow: function (el, i) {
      Array.prototype.forEach.call(el.querySelectorAll("i"), function (b) {
        b.style.transformOrigin = "left center";
        anim(b, [{ transform: "scaleX(0)" }, { transform: "scaleX(1)" }], { duration: SLOW, delay: Math.min(i, 12) * 40, fill: "backwards" });
      });
    },
    draw: function (el) {
      Array.prototype.forEach.call(el.querySelectorAll("polyline, path"), function (p) {
        var len = p.getTotalLength ? p.getTotalLength() : 0;
        if (!len) return;
        p.style.strokeDasharray = len;
        done(anim(p, [{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { duration: 600, easing: "ease-in-out" }),
             function () { p.style.strokeDasharray = ""; });
      });
      Array.prototype.forEach.call(el.querySelectorAll("circle:not(.hit)"), function (c) {
        anim(c, [{ opacity: 0 }, { opacity: 1 }], { duration: FAST, delay: 560, fill: "backwards" });
      });
    }
  };

  // ---- the bigger moves ----
  // 23, 30: a line opens into its place, the rest moving down for it
  function unfold(el) {
    if (el.hidden || !el.offsetHeight) return;
    var h = el.offsetHeight, clip = el.style.overflow;
    el.style.overflow = "hidden";
    done(anim(el, [{ height: "0px", opacity: 0 }, { height: h + "px", opacity: 1 }], { duration: BASE }), function () { el.style.overflow = clip; });
  }
  // and folds away, the rest closing up; then it's gone
  function fold(el, delay, f) {
    var h = el.offsetHeight;
    el.style.overflow = "hidden";
    el.style.boxSizing = "border-box";
    done(anim(el, [{ height: h + "px", opacity: 1 }, { height: "0px", opacity: 0, paddingTop: "0px", paddingBottom: "0px", marginTop: "0px", marginBottom: "0px" }],
              { duration: BASE, delay: delay || 0, fill: "forwards" }), function () { el.remove(); if (f) f(); });
  }

  // 20: a 🔥 rises from a streak that just grew
  function flame(td) {
    if (!M.ok()) return;
    var r = td.getBoundingClientRect(), f = document.createElement("span");
    f.textContent = "🔥";
    f.setAttribute("aria-hidden", "true");
    f.style.cssText = "position:fixed;z-index:50;pointer-events:none;font-size:14px;left:" + (r.right - 12) + "px;top:" + (r.top - 2) + "px";
    document.body.appendChild(f);
    done(anim(f, [{ transform: "translateY(4px) scale(.6)", opacity: 0 }, { transform: "translateY(-6px) scale(1.15)", opacity: 1, offset: 0.35 },
                  { transform: "translateY(-22px) scale(.9)", opacity: 0 }], { duration: 900, delay: 200, fill: "backwards" }), function () { f.remove(); });
  }

  // 18: Settings comes in from the right as the board goes; Back slides the board home
  function turn(root, snap) {
    var dir = mode(root) === "board" ? -1 : 1;
    Array.prototype.forEach.call(root.children, function (c) {
      if (c.matches("style, script")) return;
      anim(c, [{ opacity: 0, transform: "translateX(" + (40 * dir) + "px)" }, { opacity: 1, transform: "none" }], { duration: BASE });
    });
    var h = root.offsetHeight;
    if (snap.h && Math.abs(h - snap.h) > 2) {
      var clip = root.style.overflow;
      root.style.overflow = "hidden";
      done(anim(root, [{ height: snap.h + "px" }, { height: h + "px" }], { duration: BASE }), function () { root.style.overflow = clip; });
    }
  }

  // 23, 24, 26, 29, 30: what's gone comes back for a moment where it sat, and goes
  function ghost(html) {
    var t = document.createElement("div");
    t.innerHTML = html;
    var g = t.firstElementChild;
    if (!g) return null;
    g.setAttribute("data-dc-ghost", "1");
    g.setAttribute("aria-hidden", "true");
    g.style.pointerEvents = "none";
    Array.prototype.forEach.call(g.querySelectorAll("[id]"), function (x) { x.removeAttribute("id"); });
    g.removeAttribute("id");
    return g;
  }
  function putBack(root, o, sel) {
    var p = at(root, o.path.slice(0, -1));
    if (!p || sig(p, sel) !== o.pc) return null;
    var g = ghost(o.html);
    if (g) p.insertBefore(g, p.children[o.path[o.path.length - 1]] || null);
    return g;
  }
  function gone(root, snap, here, entered) {
    var fresh = {}, ups = {};
    entered.forEach(function (x) { fresh[x[0]] = 1; });
    RULES.forEach(function (rule) {
      if (!rule.leave || (snap.mem && !rule.leave.mem)) return;
      var ctx = rule.leave.ctx(root);
      Object.keys(snap.at).forEach(function (k) {
        var was = snap.at[k], o = was.go;
        if (here[k] || !o || was.kind !== rule.kind || o.ctx !== ctx) return;
        // a topic pushed out by another isn't sticking now: only one that leaves with nothing in its place
        if (rule.leave.fx === "sticking" && fresh.irow) return;
        var g = putBack(root, o, rule.sel);
        if (g) return LEAVE[rule.leave.fx || "fold"](g);
        // the last of a section: the section comes back with it, once
        if (!o.up || ups[o.up.path.join(".")]) return;
        ups[o.up.path.join(".")] = 1;
        var sec = putBack(root, o.up, rule.leave.up);
        if (!sec) return;
        var rows = sec.querySelectorAll(rule.sel), left = rows.length;
        if (!left) return fold(sec);
        Array.prototype.forEach.call(rows, function (r) {
          LEAVE[rule.leave.fx || "fold"](r, function () { if (!--left) fold(sec); }, true);
        });
      });
    });
  }
  var LEAVE = {
    fold: function (g) { fold(g); },
    // 24 someone leaves the room: their face goes and the rest close up
    shrink: function (g) {
      var w = g.offsetWidth;
      g.style.overflow = "hidden";
      done(anim(g, [{ width: w + "px", opacity: 1 }, { width: "0px", opacity: 0, marginLeft: "0px", marginRight: "0px" }], { duration: BASE, fill: "forwards" }),
           function () { g.remove(); });
    },
    // 26 its bars shrink away, it says "sticking now ✓", and folds up
    sticking: function (g, f, keep) {
      Array.prototype.forEach.call(g.querySelectorAll(".ib > i"), function (b) {
        anim(b, [{ width: b.style.width }, { width: "0px" }], { duration: SLOW, fill: "forwards" });
      });
      setTimeout(function () {
        var c = g.querySelector(".c"), go = g.querySelector(":scope > a");
        if (c) {
          c.textContent = "sticking now ✓";
          c.style.color = "var(--dc-accent, #2e7d32)";
          c.style.fontWeight = "700";
          rise(c);
        }
        if (go) go.style.visibility = "hidden";
      }, SLOW);
      if (keep) setTimeout(function () { if (f) f(); }, SLOW + 1100);
      else setTimeout(function () { if (g.isConnected) fold(g, 0, f); }, SLOW + 1100);
    },
    // 29 Behind folds down to "Caught up ✓", and that goes too
    caught: function (g) {
      var h = g.offsetHeight;
      g.innerHTML = "";
      var say = document.createElement("div");
      say.textContent = "Caught up ✓";
      say.style.cssText = "color:var(--dc-accent,#2e7d32);font-weight:700;font-size:12px;padding:4px 0";
      g.appendChild(say);
      var h2 = g.offsetHeight;
      g.style.overflow = "hidden";
      anim(g, [{ height: h + "px" }, { height: h2 + "px" }], { duration: BASE });
      pop(say, 0, 320);
      setTimeout(function () { if (g.isConnected) fold(g); }, 1600);
    }
  };
  // 3: a soft green light passes once across the box
  function sweep(box) {
    var s = document.createElement("div");
    s.setAttribute("aria-hidden", "true");
    s.style.cssText = "position:absolute;inset:0;pointer-events:none;border-radius:inherit;transform:translateX(-100%);" +
      "background:linear-gradient(100deg,transparent 25%,color-mix(in srgb,var(--dc-accent,#2e7d32) 18%,transparent) 50%,transparent 75%)";
    var pos = getComputedStyle(box).position;
    if (pos === "static") box.style.position = "relative";
    var clip = box.style.overflow;
    box.style.overflow = "hidden";
    box.appendChild(s);
    done(anim(s, [{ transform: "translateX(-100%)" }, { transform: "translateX(100%)" }], { duration: 900, easing: "ease-in-out", delay: 200 }),
         function () { s.remove(); box.style.overflow = clip; if (pos === "static") box.style.position = ""; });
  }

  // 7: the line (or pill) goes from the old pick to the new, inside its group
  function slide(g, from) {
    var to = onIn(g), on = g.querySelector("a.on, button.on");
    if (!from || !to || !on || (Math.abs(from.x - to.x) < 1 && Math.abs(from.y - to.y) < 1)) return;
    var pos = getComputedStyle(g).position;
    if (pos === "static") g.style.position = "relative";
    var ind = document.createElement("i");
    ind.setAttribute("aria-hidden", "true");
    var accent = "var(--dc-accent, #2e7d32)";
    ind.style.cssText = "position:absolute;pointer-events:none;z-index:0;display:block;" +
      (from.pill ? "border-radius:" + from.r + ";background:" + from.bg + ";"
                 : "height:2px;border-radius:1px;background:" + accent + ";");
    var y0 = from.pill ? from.y : from.y + from.h - 2, y1 = to.pill ? to.y : to.y + to.h - 2;
    var items = g.querySelectorAll("a, button");
    Array.prototype.forEach.call(items, function (a) { a.style.position = a.style.position || "relative"; a.style.zIndex = "1"; });
    var keep = { bs: on.style.boxShadow, bg: on.style.backgroundColor };
    on.style.boxShadow = "none";
    if (from.pill) {
      // its words go from the others' colour to its own as the pill arrives under them
      on.style.backgroundColor = "transparent";
      var other = Array.prototype.filter.call(items, function (x) { return x !== on && !x.classList.contains("on"); })[0];
      if (other) anim(on, [{ color: getComputedStyle(other).color }, { color: getComputedStyle(on).color }], { duration: BASE });
    }
    g.insertBefore(ind, g.firstChild);
    var a = anim(ind, [{ left: from.x + "px", top: y0 + "px", width: from.w + "px", height: (from.pill ? from.h : 2) + "px" },
                       { left: to.x + "px", top: y1 + "px", width: to.w + "px", height: (to.pill ? to.h : 2) + "px" }],
                 { duration: BASE, fill: "forwards" });
    done(a, function () {
      ind.remove();
      on.style.boxShadow = keep.bs; on.style.backgroundColor = keep.bg;
      Array.prototype.forEach.call(items, function (x) { x.style.zIndex = ""; });
      if (pos === "static") g.style.position = "";
    });
  }

  // 7: after a tab, what's under it comes in, and its box eases to the new height
  function settle(g, snap) {
    var part = g.closest(".du, .dc-sheet, .dc-panel");
    if (!part) return;
    Array.prototype.forEach.call(part.children, function (c, i) {
      if (c.contains(g) || c.matches(".dc-foot, .dc-head, .foot, style, script")) return;
      rise(c, 40 + Math.min(i, 6) * 15);
    });
    var key = part.matches(".du") ? ".du" : part.matches(".dc-sheet") ? ".dc-sheet" : ".dc-panel";
    var h0 = snap.parts[key], h1 = part.offsetHeight;
    if (h0 && Math.abs(h1 - h0) > 2 && !part.style.minHeight) {
      var clip = part.style.overflow;
      part.style.overflow = "hidden";
      done(anim(part, [{ height: h0 + "px" }, { height: h1 + "px" }], { duration: BASE }), function () { part.style.overflow = clip; });
    }
  }

  // 9: the tile you picked grows to fill the map, then its parts come in
  function zoom(map, hint) {
    var tiles = map.querySelectorAll(".tm");
    var stagger = function (base) {
      Array.prototype.forEach.call(tiles, function (t, i) {
        anim(t, [{ opacity: 0, transform: "scale(" + (hint && hint.out ? 1.03 : 0.96) + ")" }, { opacity: 1, transform: "none" }],
             { duration: 180, delay: base + Math.min(i, 10) * 35, fill: "backwards" });
      });
    };
    if (!hint || !hint.zoom) { stagger(0); return; }
    var r = map.getBoundingClientRect(), z = hint.zoom, o = document.createElement("div");
    o.setAttribute("aria-hidden", "true");
    o.style.cssText = "position:fixed;pointer-events:none;z-index:50;border-radius:10px;background:" + z.bg + ";" +
      "left:" + z.x + "px;top:" + z.y + "px;width:" + z.w + "px;height:" + z.h + "px";
    document.body.appendChild(o);
    var a = anim(o, [{ left: z.x + "px", top: z.y + "px", width: z.w + "px", height: z.h + "px", opacity: 1 },
                     { left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px", opacity: 1, offset: 0.75 },
                     { left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px", opacity: 0 }],
                 { duration: 420, fill: "forwards" });
    done(a, function () { o.remove(); });
    stagger(260);
  }

  // 4: a to-do lands where it goes: opened into its place, or flown to its tab
  function added(root, snap, entered) {
    var h = snap.hint;
    if (!h || !h.add) return;
    var row = null;
    entered.forEach(function (x) {
      if (!row && x[0] === "row" && words(x[1]).indexOf(h.add.slice(0, 30)) >= 0) row = x[1];
    });
    Array.prototype.forEach.call(root.querySelectorAll(".du-ln, .du-r"), function (r) {
      if (!row && words(r).indexOf(h.add.slice(0, 30)) >= 0 && !snap.rows[words(r)]) row = r;
    });
    if (row) {
      var ht = row.offsetHeight;
      row.style.overflow = "hidden";
      done(anim(row, [{ height: "0px", opacity: 0 }, { height: ht + "px", opacity: 1 }], { duration: BASE }), function () {
        row.style.overflow = ""; glow(row, 1200);
      });
      return;
    }
    var tab = null;
    Array.prototype.forEach.call(root.querySelectorAll(".du-tabs a"), function (a) {
      var c = cmdOf(a);
      if ((h.when === "later" && /duetab:later/.test(c)) || (h.when !== "later" && h.when !== "today" && /duetab:upcoming/.test(c))) tab = a;
    });
    if (!tab || !h.from) return;
    var b = tab.getBoundingClientRect(), chip = document.createElement("span");
    chip.textContent = h.add.length > 24 ? h.add.slice(0, 23) + "…" : h.add;
    chip.setAttribute("aria-hidden", "true");
    chip.style.cssText = "position:fixed;z-index:50;pointer-events:none;padding:2px 9px;border-radius:99px;white-space:nowrap;" +
      "font:700 12px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;" +
      "background:var(--dc-accent,#2e7d32);color:var(--dc-accent-ink,#fff);left:" + (h.from.x + 6) + "px;top:" + (h.from.y + 4) + "px";
    document.body.appendChild(chip);
    var dx = b.left + b.width / 2 - (h.from.x + 6) - 20, dy = b.top - (h.from.y + 4);
    done(anim(chip, [{ transform: "translate(0,0) scale(1)", opacity: 1 }, { transform: "translate(" + dx + "px," + dy + "px) scale(.35)", opacity: 0.2 }],
              { duration: 380, easing: "cubic-bezier(.5,0,.3,1)" }), function () {
      chip.remove();
      tab.style.display = tab.style.display || "inline-block";
      anim(tab, [{ transform: "scale(1)" }, { transform: "scale(1.2)" }, { transform: "scale(1)" }], { duration: 320 });
    });
  }

  // 21: a profile's card grows out of the name you clicked, and goes back into it
  // (the card's script calls this; every way it closes goes through back.remove)
  M.open = function (back, card) {
    if (!back || !card || !M.ok()) return;
    var from = M.from && Date.now() - M.from.at < 8000 ? M.from : null;
    M.from = null;
    var shade = getComputedStyle(back).backgroundColor;
    var toName = function () {
      var r = card.getBoundingClientRect();
      if (!from || !r.width) return "translateY(8px) scale(.97)";
      return "translate(" + Math.round(from.x + from.w / 2 - r.left - r.width / 2) + "px," + Math.round(from.y + from.h / 2 - r.top - r.height / 2) + "px) " +
        "scale(" + Math.max(0.12, Math.min(1, from.w / r.width)).toFixed(3) + ")";
    };
    anim(back, [{ backgroundColor: "rgba(0,0,0,0)" }, { backgroundColor: shade }], { duration: BASE });
    anim(card, [{ transform: toName(), opacity: 0 }, { transform: "none", opacity: 1 }], { duration: 240 });
    var g = card.querySelector(".dchg");
    if (g) M.wave(g, 140);
    var rm = Element.prototype.remove.bind(back);
    back.remove = function () {
      if (back.getAttribute("data-closing")) return;
      back.setAttribute("data-closing", "1");
      back.removeAttribute("id");  // a new card can open while this one goes
      if (!M.ok() || !back.isConnected) return rm();
      back.style.pointerEvents = "none";
      anim(back, [{ backgroundColor: shade }, { backgroundColor: "rgba(0,0,0,0)" }], { duration: 160, fill: "forwards" });
      done(anim(card, [{ transform: "none", opacity: 1 }, { transform: toName(), opacity: 0 }],
                { duration: 160, fill: "forwards", easing: "cubic-bezier(.4,0,1,1)" }), rm);
    };
  };

  // 22: a friend arrives (the glue names them, once each on this computer): their row opens in, "new" for a moment
  M.arrive = function (uids) {
    var root = document.getElementById("due-crew") || document.querySelector(".brd");
    if (!root || !uids || !uids.length) return;
    Array.prototype.forEach.call(root.querySelectorAll("tr, .dr"), function (r) {
      if (uids.indexOf(who(r)) < 0) return;
      if (M.ok()) {
        anim(r, [{ opacity: 0, transform: "translateY(-4px)" }, { opacity: 1, transform: "none" }], { duration: BASE });
        Array.prototype.forEach.call(r.cells || [r], function (c) { glow(c, 1800); });
      }
      var a = r.querySelector(".dc-pl, .nm a, .nm, .dn");
      if (!a || r.querySelector(".dc-new")) return;
      var chip = document.createElement("span");
      chip.className = "dc-new";
      chip.textContent = "new";
      chip.style.cssText = "display:inline-block;margin-left:6px;padding:0 6px;border-radius:99px;font-size:10px;font-weight:700;" +
        "line-height:16px;vertical-align:1px;background:var(--dc-accent,#2e7d32);color:var(--dc-accent-ink,#fff)";
      if (a.tagName === "A") a.parentNode.insertBefore(chip, a.nextSibling); else a.appendChild(chip);
      setTimeout(function () {
        done(anim(chip, [{ opacity: 1 }, { opacity: 0 }], { duration: 600, fill: "forwards" }), function () { chip.remove(); });
      }, 4000);
    });
  };

  // 28: a year's squares fill in, a quick wave from its first week to today
  M.wave = function (grid, delay) {
    if (!grid || !M.ok()) return;
    var cells = Array.prototype.map.call(grid.querySelectorAll("i"), function (c) { return [c, c.getBoundingClientRect()]; });
    var xs = cells.map(function (x) { return x[1].left; }), ys = cells.map(function (x) { return x[1].top; });
    if (!cells.length) return;
    var x0 = Math.min.apply(null, xs), w = Math.max.apply(null, xs) - x0 || 1;
    var y0 = Math.min.apply(null, ys), h = Math.max.apply(null, ys) - y0 || 1;
    cells.forEach(function (x) {
      anim(x[0], [{ transform: "scale(0)" }, { transform: "scale(1)" }],
           { duration: 180, delay: (delay || 0) + Math.round(480 * (x[1].left - x0) / w + 50 * (x[1].top - y0) / h), fill: "backwards" });
    });
  };

  // 32: Copied ✓, on the button itself, then back (the glue says when the copy happened)
  M.copied = function (el, say) {
    if (!el) {
      var c = M.copying && Date.now() - M.copying.at < 10000 ? M.copying : null;
      M.copying = null;
      if (!c) return;
      el = c.el.isConnected ? c.el : document.querySelector('[onclick*="duecrew:' + c.cmd + '\'"]');
    }
    if (!el) return;
    var keep = el.getAttribute("data-was");
    if (keep === null) { keep = el.innerHTML; el.setAttribute("data-was", keep); }
    clearTimeout(el._dcCopied);
    el.textContent = say || "Copied ✓";
    if (M.ok()) {
      el.style.display = el.style.display || "inline-block";
      anim(el, [{ transform: "scale(.85)", opacity: 0.4 }, { transform: "scale(1.06)", opacity: 1, offset: 0.6 }, { transform: "none" }], { duration: BASE });
    }
    el._dcCopied = setTimeout(function () { el.innerHTML = el.getAttribute("data-was"); el.removeAttribute("data-was"); }, 1600);
  };

  // 34: things that moved to another cell between two draws settle into their new places (the plan
  // calendar's dates); the rest stay put, whatever else moved the grid
  M.places = function (sel, attr, cell) {
    var out = {}, seen = {};
    Array.prototype.forEach.call(document.querySelectorAll(sel), function (el) {
      var k = el.getAttribute(attr), c = cell && el.closest(cell);
      seen[k] = (seen[k] || 0) + 1;
      out[k + "#" + seen[k]] = { r: el.getBoundingClientRect(), c: c ? nth(c) : -1 };
    });
    return out;
  };
  M.moved = function (sel, attr, was, step, box, cell) {
    if (!was || !M.ok()) return;
    if (step) {
      var b = box && document.querySelector(box);
      if (b) anim(b, [{ opacity: 0, transform: "translateX(" + (32 * step) + "px)" }, { opacity: 1, transform: "none" }], { duration: BASE });
      return;
    }
    var seen = {};
    Array.prototype.forEach.call(document.querySelectorAll(sel), function (el) {
      var k = el.getAttribute(attr);
      seen[k] = (seen[k] || 0) + 1;
      var w = was[k + "#" + seen[k]], c = cell && el.closest(cell), r = el.getBoundingClientRect();
      if (!w || (c ? nth(c) : -1) === w.c) return;
      var a = w.r;
      anim(el, [{ transform: "translate(" + (a.left - r.left) + "px," + (a.top - r.top) + "px)" }, { transform: "none" }], { duration: BASE });
    });
  };

  // the logo: the crew does the wave. Its six studied days hop in turn, left to right, and the day off
  // sits it out (a day off is fine). Only a move, never a fill or a shape: it lands on the artwork, always.
  M.logo = function (where, delay) {
    var svg = where && (where.matches && where.matches("svg.dc-mark, svg.logo-inline") ? where : where.querySelector("svg.dc-mark, svg.logo-inline"));
    if (!svg || !M.ok() || svg.getAttribute("data-waving")) return;
    svg.setAttribute("data-waving", "1");
    var days = svg.querySelectorAll("rect"), i = 0;
    Array.prototype.forEach.call(days, function (d) {
      var off = /off/.test(cls(d)) || /--line|e2e2da/.test(d.getAttribute("style") + " " + d.getAttribute("fill"));
      if (!off) anim(d, [{ transform: "translateY(0)" }, { transform: "translateY(-15px)", offset: 0.4, easing: "cubic-bezier(.3,0,.5,1)" },
                        { transform: "translateY(0)", offset: 0.8 }, { transform: "translateY(0)" }],
                     { duration: 460, delay: (delay || 0) + i * 70, easing: "cubic-bezier(.5,0,.7,1)" });
      i++;
    });
    setTimeout(function () { svg.removeAttribute("data-waving"); }, (delay || 0) + days.length * 70 + 520);
  };
  document.addEventListener("pointerover", function (e) {
    var t = e.target && e.target.closest ? e.target.closest("svg.dc-mark, svg.logo-inline") : null;
    if (t) M.logo(t);
  }, true);

  // 13: a cheer you send (the glue calls this once it's sent)
  M.cheer = function (uid, emoji) {
    var root = document.getElementById("due-crew") || document;
    var row = null;
    Array.prototype.forEach.call(root.querySelectorAll("tr, .dr"), function (r) { if (!row && who(r) === uid) row = r; });
    var cell = row && (row.querySelector("td.chc") || row.querySelector(".nm") || row);
    if (!cell || !M.ok()) return;
    var r = cell.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
    var say = document.createElement("span");
    say.textContent = "Sent";
    say.setAttribute("aria-hidden", "true");
    say.style.cssText = "position:fixed;z-index:50;pointer-events:none;font:700 12px/1 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;" +
      "color:var(--dc-accent,#2e7d32);left:" + (r.left - 34) + "px;top:" + (y - 6) + "px";
    document.body.appendChild(say);
    done(anim(say, [{ opacity: 0 }, { opacity: 1, offset: 0.15 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: 1600 }),
         function () { say.remove(); });
    for (var i = 0; i < 5; i++) {
      (function (i) {
        var f = document.createElement("span");
        f.textContent = emoji || "🎉";
        f.setAttribute("aria-hidden", "true");
        f.style.cssText = "position:fixed;z-index:50;pointer-events:none;font-size:15px;left:" + (x - 8) + "px;top:" + (y - 10) + "px";
        document.body.appendChild(f);
        var dx = Math.random() * 36 - 18, dy = -(34 + Math.random() * 26);
        done(anim(f, [{ transform: "translate(0,0) scale(.6)", opacity: 1 }, { transform: "translate(" + dx + "px," + dy + "px) scale(.9)", opacity: 0 }],
                  { duration: 700 + Math.random() * 300, delay: i * 50, easing: "cubic-bezier(.2,.6,.3,1)", fill: "backwards" }),
             function () { f.remove(); });
      })(i);
    }
  };

  // ---- clicks that tell the next redraw what they did, or move at once ----
  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var tile = t.closest(".tmap .tm");
    if (tile) {
      var r = tile.getBoundingClientRect();
      M.say({ zoom: { x: r.left, y: r.top, w: r.width, h: r.height, bg: getComputedStyle(tile).backgroundColor } });
      return;
    }
    if (t.closest(".tmt a")) { M.say({ out: true }); return; }
    // 21: where the name was, for the card that grows out of it
    var nm = t.closest('a.dc-pl, [onclick*="duecrew:profile:"]');
    if (nm) { var q = nm.getBoundingClientRect(); M.from = { x: q.left, y: q.top, w: q.width, h: q.height, at: Date.now() }; }
    // 32: the copy link you clicked, for its Copied ✓
    var cp = t.closest('[onclick*="copy"]');
    if (cp && cmdOf(cp)) M.copying = { el: cp, cmd: cmdOf(cp), at: Date.now() };
    // 31: a bingo square's rule rises in under the card
    if (t.closest(".bg-sq") && M.ok()) {
      requestAnimationFrame(function () {
        var info = document.querySelector("#due-crew .bg-info > div:not([hidden])");
        if (info) rise(info);
      });
      return;
    }
    var nav = t.closest("a[onclick*='duecrew:planweek:']");
    if (nav) { M.say({ week: /:prev'/.test(nav.getAttribute("onclick")) ? -1 : 1 }); return; }
    var spin = t.closest('.dc-foot a.ic[title="Refresh"], .brd .foot button[title="Refresh"]');
    if (spin && M.ok()) { spin.classList.add("dc-spin"); setTimeout(function () { spin.classList.remove("dc-spin"); }, 10000); return; }
    // 8: the day you pick on a plan's week: the outline glides there, its card slides in
    var cell = t.closest(".pwk .pc");
    if (cell && M.ok()) {
      var wk = cell.parentNode, old = wk.querySelector(".pc.sel");
      var a = old && old !== cell ? old.getBoundingClientRect() : null, list = Array.prototype.slice.call(wk.children);
      var dir = old ? (list.indexOf(cell) > list.indexOf(old) ? 1 : -1) : 1;
      requestAnimationFrame(function () {
        if (!cell.classList.contains("sel")) return;
        var b = cell.getBoundingClientRect(), w = wk.getBoundingClientRect();
        if (a) {
          var ring = document.createElement("i");
          ring.setAttribute("aria-hidden", "true");
          ring.style.cssText = "position:absolute;pointer-events:none;display:block;border:2px solid var(--dc-accent,#2e7d32);border-radius:8px;box-sizing:border-box";
          var pos = getComputedStyle(wk).position;
          if (pos === "static") wk.style.position = "relative";
          wk.appendChild(ring);
          cell.style.borderColor = "transparent";
          done(anim(ring, [{ left: (a.left - w.left) + "px", top: (a.top - w.top) + "px", width: a.width + "px", height: a.height + "px" },
                           { left: (b.left - w.left) + "px", top: (b.top - w.top) + "px", width: b.width + "px", height: b.height + "px" }],
                     { duration: BASE, fill: "forwards" }), function () {
            ring.remove(); cell.style.borderColor = ""; if (pos === "static") wk.style.position = "";
          });
        }
        var box = wk.parentNode.querySelector(".pday:not([hidden])");
        if (box) anim(box, [{ opacity: 0, transform: "translateX(" + (12 * dir) + "px)" }, { opacity: 1, transform: "none" }], { duration: 180 });
      });
    }
  }, true);
})();
