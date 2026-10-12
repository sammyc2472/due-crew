/* Due Crew's motion (3.8.0, "Board in Motion": Sam picked all seventeen).
   One file in two places, byte for byte: due_crew/motion.js (the add-on's
   board, around board.swap_js) and site/public/motion.js (duecrew.com,
   around the board's draw). The suite checks they match.

   A redraw replaces the board whole. Before it, before() notes each thing
   the rules below know (a tick, a bar, a number, a tab, a tile, a stamp):
   what it said and where it sat. After it, after() moves only what
   changed, from what it was to what it is. A refresh that changes nothing
   moves nothing; nothing moves with the system's Reduce motion on; rows
   never slide past each other (never a race). A click that causes a
   redraw can leave a hint first (the tile it zoomed, the to-do it added). */
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
    { sel: "svg.ispark", kind: "draw", key: function () { return "spark"; }, val: function () { return ""; } }
  ];

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
        var k = rule.key(el, i);
        seen[k] = (seen[k] || 0) + 1;
        if (seen[k] > 1) k += "#" + seen[k];
        f(rule, el, k);
      });
    });
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

  M.before = function (root) {
    var snap = { at: {}, hint: fresh(M.hint), parts: {}, rows: {} };
    M.hint = null;
    if (!root) return snap;
    Array.prototype.forEach.call(root.querySelectorAll(".du-r, .du-ln"), function (r) { snap.rows[words(r)] = 1; });
    each(root, function (rule, el, k) {
      var r = el.getBoundingClientRect();
      snap.at[k] = { v: rule.val(el), w: el.style.width, t: words(el), h: el.offsetHeight, r: r,
                     on: rule.kind === "tabs" ? onIn(el) : null };
    });
    [".du", ".dc-sheet", ".dc-panel"].forEach(function (s) {
      var p = root.matches(s) ? root : root.querySelector(s);
      if (p) snap.parts[s] = p.offsetHeight;
    });
    return snap;
  };

  M.after = function (root, snap) {
    if (!root || !snap || !M.ok()) return;
    var cold = !Object.keys(snap.at).length, entered = [], tabbed = [];
    each(root, function (rule, el, k) {
      var was = snap.at[k], v = rule.val(el);
      if (!was) { if (!cold) entered.push([rule.kind, el]); return; }
      if (was.v === v) return;
      var f = CHANGE[rule.kind];
      if (f) f(el, was, v, snap);
      if (rule.kind === "tabs") tabbed.push(el);
    });
    var n = 0;
    entered.forEach(function (x) { var f = ENTER[x[0]]; if (f) f(x[1], n++, snap); });
    tabbed.forEach(function (g) { settle(g, snap); });
    added(root, snap, entered);
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
  // a number from what it said to what it says: 1,234 or 2h 04m; anything else just glows
  function count(el, from, to) {
    var fmt, a, b, tm = /^(?:(\d+)h )?(\d+)m$/, nm = /^\d[\d,]*$/;
    if (nm.test(from) && nm.test(to)) {
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
      var k = Math.min(1, (t - t0) / SLOW), e = 1 - Math.pow(1 - k, 3);
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
      if (/:done$/.test(v) && !/:done$/.test(was.v)) sweep(el);
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
    num: function (el, was, v) { count(el, was.t, v); glow(el); },
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
    }
  };

  var ENTER = {
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
