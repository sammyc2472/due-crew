/* Your plans, as a page (web.py). The view comes whole from Python
   (dcPlan.show); what's clicked goes back as "dcplan:" + JSON through
   Anki's bridge. Every name is set as text, never as markup. What's
   only how it looks (List, Week or Month, a week folded, Find, the
   month shown) is kept here. */
var dcPlan = (function () {
  "use strict";
  var S = null, root = null, preview = false;
  var ui = { mode: "list", desc: false, find: "", look: false, opened: {}, closed: {}, all: null, month: null, week: null,
    paste: "", menu: null, sheet: null, deckFind: null, deckTimer: null };
  var DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  var MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  var MON3 = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function send(c, a) {
    var m = "dcplan:" + JSON.stringify({ c: c, a: a || {} });
    if (typeof window.pycmd === "function") { window.pycmd(m); } else if (window.console) { console.log(m); }
  }

  /* h("div.cls", {attrs}, [kids]): a node, its text set as text */
  function h(sel, attrs, kids) {
    var p = sel.split("."), el = document.createElement(p[0] || "div");
    if (p.length > 1) { el.className = p.slice(1).join(" "); }
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v === undefined || v === null || v === false) { return; }
      if (k === "text") { el.textContent = String(v); }
      else if (k.slice(0, 2) === "on") { el.addEventListener(k.slice(2), v); }
      else if (k === "cls") { el.className += (el.className ? " " : "") + v; }
      else if (k === "value") { el.value = v; }
      else if (k === "style") { el.setAttribute("style", v); }
      else { el.setAttribute(k, v === true ? "" : String(v)); }
    });
    (kids || []).forEach(function (c) {
      if (c === null || c === undefined || c === false) { return; }
      el.appendChild(typeof c === "string" || typeof c === "number" ? document.createTextNode(String(c)) : c);
    });
    return el;
  }
  function btn(label, fn, cls, attrs) {
    return h("button.b" + (cls ? "." + cls.split(" ").join(".") : ""), Object.assign({ type: "button", text: label, onclick: function (e) {
      e.stopPropagation(); if (!this.disabled) { fn(e, this); }
    } }, attrs || {}));
  }
  function author() { return S && S.head && S.head.author; }
  function busy() { return S && S.head && S.head.busy; }
  function keyStr(k) { return k ? k.join("\u0001") : ""; }
  function same(a, b) { return keyStr(a) === keyStr(b); }

  /* ---- dates ---- */
  function d(iso) { var p = String(iso).split("-"); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function iso(dt) { return dt.getFullYear() + "-" + String(dt.getMonth() + 1).padStart(2, "0") + "-" + String(dt.getDate()).padStart(2, "0"); }
  function addDays(s, n) { var x = d(s); x.setDate(x.getDate() + n); return iso(x); }
  function monday(s) { var x = d(s), k = (x.getDay() + 6) % 7; x.setDate(x.getDate() - k); return iso(x); }
  function short(s) { var x = d(s); return DAYS[(x.getDay() + 6) % 7] + " " + x.getDate() + " " + MON3[x.getMonth()]; }

  /* ---- menus ---- */
  function closeMenu() { if (ui.menu) { ui.menu.forEach(function (m) { m.remove(); }); ui.menu = null; } }
  function menu(items, anchor, level) {
    if (!level) { closeMenu(); ui.menu = []; }
    var r = anchor.getBoundingClientRect(), m = h("div.menu", { role: "menu" });
    items.forEach(function (it) {
      if (it.sep) { m.appendChild(h("hr")); return; }
      var mi = h("div.mi" + (it.off ? ".off" : "") + (it.bad ? ".bad" : "") + (it.sub ? ".sub" : ""), { role: "menuitem" },
        [it.on !== undefined ? h("span.tick", { text: it.on ? "✓" : "" }) : null, h("span", { text: it.label })]);
      mi.addEventListener("click", function (e) {
        e.stopPropagation();
        if (it.off) { return; }
        if (it.sub) { while (ui.menu.length > (level || 0) + 1) { ui.menu.pop().remove(); } menu(it.sub, mi, (level || 0) + 1); return; }
        closeMenu();
        if (it.fn) { it.fn(); } else if (it.cmd) { send(it.cmd, it.args || {}); }
      });
      m.appendChild(mi);
    });
    root.appendChild(m);
    ui.menu.push(m);
    var mr = m.getBoundingClientRect(), x = level ? r.right + 2 : r.left, y = level ? r.top - 6 : r.bottom + 4;
    if (x + mr.width > window.innerWidth - 8) { x = level ? r.left - mr.width - 2 : window.innerWidth - mr.width - 8; }
    if (y + mr.height > window.innerHeight - 8) { y = Math.max(8, (level ? r.bottom : r.top) - mr.height - 4); }
    m.style.left = Math.max(8, x) + "px";
    m.style.top = y + "px";
  }
  document.addEventListener("click", function () { closeMenu(); });

  /* ---- sheets: a question, a form, the changes to send, words to read ---- */
  function closeSheet() { ui.sheet = null; var v = root && root.querySelector(".veil"); if (v) { v.remove(); } }
  function sheet(sh) {
    closeMenu();
    closeSheet();
    ui.sheet = sh;
    var body = h("div.sheet" + (sh.kind === "send" || sh.kind === "read" ? ".wide" : ""), { role: "dialog", "aria-label": sh.title },
      [h("h4", { text: sh.title }), sh.words ? h("p.sub", { text: sh.words }) : null]);
    var fields = {}, go;
    function submit() {
      var args = Object.assign({}, sh.args || {});
      Object.keys(fields).forEach(function (k) { args[k] = fields[k].value; });
      if (sh.kind === "send") { args = { why: fields.why.value }; }
      closeSheet();
      if (sh.cmd) { send(sh.cmd, args); }
    }
    (sh.fields || []).forEach(function (f, i) {
      var input = f.type === "area" ? h("textarea.in", { rows: 4, maxlength: f.max || 280 }) :
        h("input.in", { type: f.type || "text", maxlength: f.max || 200, placeholder: f.hint || "" });
      input.value = f.value || "";
      input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && f.type !== "area") { e.preventDefault(); submit(); }
      });
      fields[f.name] = input;
      body.appendChild(h("div.fld", {}, [f.label ? h("label", { text: f.label }) : null, input]));
      if (i === 0) { setTimeout(function () { input.focus(); if (input.select) { input.select(); } }, 0); }
    });
    if (sh.kind === "send") {
      sh.rows.forEach(function (r) {
        body.appendChild(h("div.chg", {}, [h("span.muted", { text: r.verb }),
          h("span", {}, [h("b", { text: r.what }), r.detail ? h("span.d", { text: r.detail }) : null,
            r.who ? h("span.d" + (r.warn ? ".warn" : ""), { text: r.who }) : null,
            r.ai ? h("span.d", { text: "From your AI app" }) : null]),
          r.i !== null ? h("button.x", { type: "button", title: "Take this change out (it's never sent)", text: "✕",
            onclick: function () { closeSheet(); send("take_change", { i: r.i, again: true }); } }) : h("span")]));
      });
      var why = h("textarea.in", { rows: 3 });
      why.value = sh.why || "";
      var count = h("div.muted.sm", { style: "text-align:right" });
      function counted() { var n = why.value.split(/\s+/).join(" ").trim().length; count.textContent = n + " / " + sh.max; if (go) { go.disabled = n > sh.max; } }
      why.addEventListener("input", counted);
      fields.why = why;
      body.appendChild(h("div.fld", {}, [h("label", { text: "Tell them why" }), why, count]));
      setTimeout(counted, 0);
    }
    if (sh.kind === "read") { body.appendChild(h("pre", { text: sh.text })); }
    var own = dcPlan.sheets && dcPlan.sheets[sh.kind];  /* tabs.js's own kinds: Posts, History, a pick */
    if (own) { own(sh, body, { h: h, btn: btn, send: send, close: closeSheet }); }
    go = btn(sh.yes || "OK", submit, "pri" + (sh.danger ? " bad" : ""), { title: sh.tip || null });
    if (sh.danger) { go.style.background = "#c62828"; go.style.borderColor = "#c62828"; go.style.color = "#fff"; }
    body.appendChild(h("div.acts", {}, [btn(sh.no || (sh.kind === "send" ? "Back" : "Cancel"), closeSheet), sh.yes === null ? null : go]));
    var veil = h("div.veil", { onclick: function (e) { if (e.target === veil) { closeSheet(); } } }, [body]);
    root.appendChild(veil);
    if (!(sh.fields || []).length) { setTimeout(function () { go.focus(); }, 0); }
  }

  /* ---- the head ---- */
  function renderTop() {
    var hd = S.head, top = h("div.top");
    if (hd.plans.length) {
      var sel = h("select.in", { "aria-label": "Plan", onchange: function () { send("pick_plan", { pid: this.value }); }, disabled: busy() });
      hd.plans.forEach(function (p) { var o = h("option", { value: p.id, text: p.label }); if (p.id === hd.pid) { o.selected = true; } sel.appendChild(o); });
      top.appendChild(sel);
    } else { top.appendChild(h("div.grow")); }
    if (S.new) { return top; }
    if (hd.author) {
      top.appendChild(btn("Undo", function (e, b) { undoMenu(b); }, "ch", { id: "dcp-undo", title: "The last change not sent, your last save or send; History (Ctrl+Z)" }));
      top.appendChild(btn("Share…", function () { send("tab", { tab: "settings" }); }));
    }
    top.appendChild(btn("New plan…", function () { send("new_plan"); }, "", { disabled: busy() }));
    return top;
  }
  function undoMenu(anchor) {
    menu(S.head.undo.map(function (u) {
      return { label: u.label, off: !u.on, cmd: "undo", args: { what: u.what } };
    }), anchor);
  }
  function renderTabs() {
    var t = h("div.tabs", { role: "tablist" });
    [["plan", "Plan"], ["insights", "Insights"], ["settings", "Settings"]].forEach(function (x) {
      t.appendChild(h("button" + (S.tab === x[0] ? ".on" : ""), { type: "button", role: "tab", text: x[1],
        onclick: function () { send("tab", { tab: x[0] }); } }));
    });
    return t;
  }

  /* ---- the Plan tab ---- */
  function strips(p) {
    var out = [];
    if (p.now) {
      out.push(h("div.strip", {}, [h("span.h", { text: p.now.head }), h("span.grow", { text: p.now.words }),
        p.now.study ? btn("Study now", function () { send("study", { kind: "today", key: p.now.uid }); }, "pri") : null]));
    }
    if (p.behind) {
      out.push(h("div.strip.late", {}, [h("span.h", { text: "Behind" }), h("span.grow", { text: p.behind.words }),
        btn(p.behind.button, function () { send("study", { kind: "behind", key: p.behind.uids }); })]));
    }
    if (p.shape) {
      var sh = h("div.shape");
      p.shape.forEach(function (x) { sh.appendChild(h("span", { text: x[0] })); sh.appendChild(h("b", { text: x[1] })); });
      sh.appendChild(btn("Change…", function () { send("tab", { tab: "settings" }); }, "t"));
      out.push(sh);
    }
    if (p.cover && p.cover.cards) {
      var c = p.cover, tot = c.cards || 1;
      out.push(h("div.cover", {}, [
        h("div.br", { role: "img", "aria-label": c.seen + " seen, " + c.open + " open, " + c.shut + " still shut" }, [
          h("i.seen", { style: "width:" + (100 * c.seen / tot) + "%" }), h("i.open", { style: "width:" + (100 * c.open / tot) + "%" }),
          h("i.shut", { style: "width:" + (100 * c.shut / tot) + "%" })]),
        h("div.lg", {}, [h("span", {}, [h("i.seen"), c.seen.toLocaleString() + " seen"]), h("span", {}, [h("i.open"), c.open.toLocaleString() + " open"]),
          h("span", {}, [h("i.shut"), c.shut.toLocaleString() + " still shut"]),
          author() ? h("span", { text: "Not in a set: " + (c.outside || 0).toLocaleString() }) : null])]));
    }
    return out;
  }
  function toolbar(p) {
    var bar = h("div.row");
    var seg = h("div.seg", { role: "group", "aria-label": "View" });
    [["list", "List"], ["week", "Week"], ["month", "Month"]].forEach(function (m, i) {
      seg.appendChild(h("button" + (ui.mode === m[0] ? ".on" : ""), { type: "button", text: m[1], title: m[1] + " (Ctrl+" + (i + 1) + ")",
        onclick: function () { ui.mode = m[0]; render(); } }));
    });
    bar.appendChild(seg);
    if (ui.mode === "list") { bar.appendChild(btn(ui.desc ? "Latest first" : "Earliest first", function () { ui.desc = !ui.desc; render(); }, "t")); }
    var find = h("input.in", { placeholder: "Find a set or tag", "data-keep": "find", style: "width:200px", title: "Only the sets whose name or cards have these words; Enter picks the first (Ctrl+F)" });
    find.value = ui.find;
    find.addEventListener("input", function () { ui.find = this.value; if (ui.find.trim()) { ui.mode = "list"; } render(); });
    find.addEventListener("keydown", function (e) {
      if (e.key === "Enter") { var first = visibleKeys()[0]; if (first) { send("pick", { key: first }); } }
      if (e.key === "Escape") { if (this.value) { ui.find = ""; render(); } else { this.blur(); } }
    });
    bar.appendChild(find);
    bar.appendChild(btn("Today", goToday, "", { title: "The set open today, or the next one (Ctrl+T)" }));
    if (author() && (p.lookN || ui.look)) {
      bar.appendChild(btn("Needs a look (" + p.lookN + ")", function () { ui.look = !ui.look; render(); }, ui.look ? "pri" : "",
        { title: "Only the weeks with a set that has no cards here, or a day over the pace" }));
    }
    if (ui.mode === "list") { bar.appendChild(btn(allOpen(p) ? "Collapse all" : "Expand all", function () { ui.all = !allOpen(p); ui.opened = {}; ui.closed = {}; render(); })); }
    if (author()) {
      bar.appendChild(btn("Add", function (e, b) {
        menu([{ label: "A set…  Ctrl+N", cmd: "new_date_form" }, { label: "A quiz, exam or day…  Ctrl+E", cmd: "new_event_form" },
          { label: "A review day…", cmd: "new_review_form" }, { sep: true },
          { label: "Sets from the deck…", off: !p.hasDeck, cmd: "deck", args: {} }, { sep: true },
          { label: "Give everyone a day…", cmd: "breather" }], b);
      }, "ch", { disabled: busy() }));
    }
    return bar;
  }

  function isOpen(w) {
    if (ui.opened[w.start]) { return true; }
    if (ui.closed[w.start]) { return false; }
    if (ui.all !== null && !ui.look) { return ui.all; }
    if (ui.look) { return true; }
    return addDays(w.start, 6) >= S.plan.today;
  }
  function allOpen(p) { return p.weeks.every(isOpen); }
  function matches(it) {
    var words = ui.find.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) { return true; }
    if (it.kind !== "date" && it.kind !== "event") { return false; }
    return words.every(function (w) { return (it.hay || "").indexOf(w) >= 0; });
  }
  function itemRow(it) {
    if (it.kind === "taper") { return h("div.li.taper", {}, [h("span.s"), h("span.nm", { text: it.name }), h("span.r", { text: it.dayw })]); }
    var on = same(it.key, S.picked);
    var glyph = { done: "✓", now: "●", late: "!", ahead: "○", past: "·" }[it.state] || "";
    if (it.kind === "event") { glyph = "◆"; } else if (it.kind === "review") { glyph = "↺"; }
    var nm = h("span.nm", {}, [h("b", { text: it.name }), it.notSent ? h("span.ns", { text: "not sent" }) : null,
      h("span.u", { text: (it.span || it.dayw) + (it.under ? " · " : "") }, it.under ? [h("span" + (it.underTone === "warn" ? ".warn" : ""), { text: it.under })] : [])]);
    var row = h("div.li." + it.kind + (on ? ".on" : "") + (it.past ? ".past" : ""), {
      "data-key": keyStr(it.key), tabindex: "-1",
      onclick: function () { send("pick", { key: it.key }); },
      ondblclick: function () { if (author()) { send("pick", { key: it.key }); setTimeout(focusName, 50); } }
    }, [h("span.s." + (it.state || ""), { text: glyph }), nm, h("span.r" + (it.tone === "warn" ? ".warn" : ""), { text: it.right || "" })]);
    return row;
  }
  function listView(p) {
    var box = h("div"), today = p.today, any = false;
    var weeks = ui.desc ? p.weeks.slice().reverse() : p.weeks;
    weeks.forEach(function (w) {
      var items = w.items.filter(matches);
      if (ui.look && !w.look) { return; }
      if (ui.find.trim() && !items.length) { return; }
      any = true;
      var open = isOpen(w) || !!ui.find.trim();
      var words = w.words, warn = w.warn;
      if (w.past && !open) { words = w.folded; warn = false; }
      box.appendChild(h("div.wk" + (w.past ? ".past" : ""), { onclick: function () {
        if (isOpen(w)) { delete ui.opened[w.start]; ui.closed[w.start] = 1; } else { delete ui.closed[w.start]; ui.opened[w.start] = 1; }
        render();
      } }, [h("b", { text: (open ? "▾ " : "▸ ") + w.label }), h("span.w" + (warn ? ".warn" : ""), { text: words })]));
      if (!open) { return; }
      if (w.heavy) {
        var hv = w.heavy, acts = h("div.row", { style: "margin-top:6px" });
        if (hv.spread) { acts.appendChild(btn(hv.spread.label, function () { send("spread_heavy", { kind: hv.spread.kind, path: hv.spread.path, uid: hv.uid }); })); }
        if (hv.till) { acts.appendChild(btn(hv.till.label, function () { send("op", { op: { op: "set_due", date: hv.uid, due: hv.till.due } }); })); }
        box.appendChild(h("div.heavy", {}, [h("b", { text: "Over the pace " }), hv.words, acts]));
      }
      var ruled = w.start > today || addDays(w.start, 6) < today;
      var its = ui.desc ? items.slice().reverse() : items;
      its.forEach(function (it) {
        if (!ruled && (ui.desc ? String(it.day) <= today : String(it.day) >= today)) { box.appendChild(h("div.todayl", { text: "Today, " + p.todayw })); ruled = true; }
        box.appendChild(itemRow(it));
      });
      if (!ruled) { box.appendChild(h("div.todayl", { text: "Today, " + p.todayw })); }
    });
    if (!p.weeks.length) { box.appendChild(h("div.empty", { text: p.empty || "No sets yet." })); }
    else if (!any && ui.find.trim()) { box.appendChild(h("div.empty", { text: "No set or quiz has “" + ui.find.trim() + "” in its name or its cards." })); }
    return box;
  }
  function visibleKeys() {
    var out = [];
    (root.querySelectorAll(".pane [data-key]") || []).forEach(function (el) {
      var k = el.getAttribute("data-key"); if (k && out.indexOf(k) < 0) { out.push(k); }
    });
    return out.map(function (k) { return k.split("\u0001"); });
  }

  /* Week and Month: each lesson on its days (a spread one on each), each day's new cards */
  function calEntries(p) {
    var by = {};
    p.cal.forEach(function (e) {
      var day = e.day, last = e.last || e.day, first = true, guard = 0;
      while (day <= last && guard++ < 60) {
        (by[day] = by[day] || []).push({ e: e, cont: !first });
        first = false;
        day = addDays(day, 1);
      }
    });
    Object.keys(by).forEach(function (k) { by[k].sort(function (a, b) { return (a.e.kind === "event" ? 0 : 1) - (b.e.kind === "event" ? 0 : 1); }); });
    return by;
  }
  function dayCell(p, day, by, tall, inMonth) {
    var wd = (d(day).getDay() + 6) % 7, study = p.days[wd];
    var cls = "c" + (inMonth === false ? ".out" : "") + (!study ? ".rest" : "") + (day === p.today ? ".td" : "");
    var taper = p.taper && day >= p.taper[0] && day <= p.taper[1];
    var here = by[day] || [], n = p.load[day] || 0;
    var cell = h("div." + cls, { "data-day": day }, [h("span.dn", {}, [h("span", { text: tall ? short(day) : String(d(day).getDate()) }),
      taper ? h("span.nb", { text: "no new" }) : null])]);
    var cap = tall ? here.length : 2;
    here.slice(0, cap).forEach(function (x) {
      var e = x.e, on = same(e.key, S.picked);
      var ev = h("span.ev" + (e.kind === "event" ? ".q" : "") + (on ? ".on" : "") + (x.cont ? ".cont" : ""), {
        text: e.name, title: e.name, "data-key": keyStr(e.key), draggable: author() && !x.cont ? "true" : null,
        onclick: function (ev2) { ev2.stopPropagation(); send("pick", { key: e.key }); }
      });
      ev.addEventListener("dragstart", function (de) { de.dataTransfer.setData("text/plain", JSON.stringify(e.key)); });
      cell.appendChild(ev);
    });
    if (here.length > cap) {
      cell.appendChild(h("span.more", { text: "+" + (here.length - cap) + " more", title: here.slice(cap).map(function (x) { return x.e.name; }).join(", "),
        onclick: function (ev2) { ev2.stopPropagation(); ui.mode = "list"; send("pick", { key: here[cap].e.key }); } }));
    }
    if (n) {
      var over = p.cap && n > p.cap * 1.25;
      cell.appendChild(h("span.ld" + (over ? ".hv" : ""), { title: n + " new" + (over ? ", over your " + p.cap : "") },
        [h("i", { style: "width:" + Math.min(100, 100 * n / Math.max(p.cap * 1.5 || 1, n)) + "%" })]));
    }
    if (author()) {
      cell.addEventListener("dragover", function (de) { de.preventDefault(); cell.classList.add("drop"); });
      cell.addEventListener("dragleave", function () { cell.classList.remove("drop"); });
      cell.addEventListener("drop", function (de) {
        de.preventDefault(); cell.classList.remove("drop");
        var key; try { key = JSON.parse(de.dataTransfer.getData("text/plain")); } catch (err) { return; }
        if (key[0] === "date") { send("move", { uid: key[1], to: day }); } else if (key[0] === "event") { send("move_event", { eid: key[1], to: day }); }
      });
    }
    return cell;
  }
  function anchorDay(p) {
    var k = S.picked, e = k && p.cal.filter(function (x) { return same(x.key, k); })[0];
    return e ? e.day : p.today;
  }
  function weekView(p) {
    if (!ui.week) { ui.week = monday(anchorDay(p)); }
    var by = calEntries(p), grid = h("div.cal.wkv");
    DAYS.forEach(function (x) { grid.appendChild(h("div.hd", { text: x })); });
    for (var i = 0; i < 7; i++) { grid.appendChild(dayCell(p, addDays(ui.week, i), by, true)); }
    return h("div", {}, [h("div.calnav", {}, [btn("‹", function () { ui.week = addDays(ui.week, -7); render(); }),
      h("b", { text: "Week of " + short(ui.week) }), btn("›", function () { ui.week = addDays(ui.week, 7); render(); })]), grid]);
  }
  function monthView(p) {
    if (!ui.month) { ui.month = anchorDay(p).slice(0, 7) + "-01"; }
    var first = d(ui.month), by = calEntries(p), grid = h("div.cal");
    DAYS.forEach(function (x) { grid.appendChild(h("div.hd", { text: x })); });
    var start = monday(ui.month);
    for (var k = 0; k < 42; k++) {
      var day = addDays(start, k), dd = d(day);
      if (k >= 35 && dd.getMonth() !== first.getMonth()) { break; }
      grid.appendChild(dayCell(p, day, by, false, dd.getMonth() === first.getMonth()));
    }
    function step(n) { var x = d(ui.month); x.setMonth(x.getMonth() + n); ui.month = iso(x); render(); }
    return h("div", {}, [h("div.calnav", {}, [btn("‹", function () { step(-1); }),
      h("b", { text: MONTHS[first.getMonth()] + " " + first.getFullYear() }), btn("›", function () { step(1); })]), grid]);
  }
  function goToday() {
    var p = S.plan; if (!p) { return; }
    ui.week = monday(p.today); ui.month = p.today.slice(0, 7) + "-01";
    var t = p.today, best = null;
    p.cal.forEach(function (e) { if (e.kind === "date" && e.day <= t && (e.last || e.day) >= t) { best = e; } });
    if (!best) { p.cal.forEach(function (e) { if (!best && e.kind === "date" && e.day > t) { best = e; } }); }
    if (best) { ui.opened[monday(best.day)] = 1; delete ui.closed[monday(best.day)]; send("pick", { key: best.key }); } else { render(); }
  }

  /* the picked one, beside the plan */
  function focusName() { var n = root.querySelector("[data-keep=name]"); if (n) { n.focus(); n.select(); } }
  function dateInput(value, onchange, keep) {
    var i = h("input.in", { type: "date", "data-keep": keep });
    i.value = value || "";
    i.addEventListener("change", function () { onchange(this.value); });
    return i;
  }
  function menuItems(list) {
    return (list || []).map(function (x) {
      if (x.sep) { return { sep: true }; }
      return { label: x.label, on: x.on, off: x.off, bad: x.bad, cmd: x.cmd, args: x.args, sub: x.sub ? menuItems(x.sub) : null };
    });
  }
  function notesBlock(nt) {
    var box = h("div", {}, [h("div.sh", { text: "Notes on its day" })]);
    if (!nt) { return box; }
    if (nt.loading) { box.appendChild(h("div.muted.sm", { text: "Reading its notes…" })); return box; }
    nt.rows.forEach(function (x) {
      box.appendChild(h("div.note", {}, [h("b", { text: x.who }), h("span", { text: x.text }),
        x.remove ? h("button.x", { type: "button", text: "Take it off", onclick: function () { send("note_off", { nid: x.id }); } }) : h("span")]));
    });
    if (!nt.rows.length && !nt.writes) { box.appendChild(h("div.muted.sm", { text: "No notes on " + nt.dayw + "." })); }
    if (nt.writes) {
      var box2 = h("input.in.grow", { maxlength: 280, placeholder: "A note on " + nt.dayw + ", for everyone on it", "data-keep": "note" });
      function add() { var t = box2.value.trim(); if (t) { send("note_add", { day: nt.day, text: t }); box2.value = ""; } }
      box2.addEventListener("keydown", function (e) { if (e.key === "Enter") { add(); } });
      box.appendChild(h("div.row", {}, [box2, btn("Add the note", add)]));
    }
    return box;
  }
  function datePanel(pn) {
    var box = h("div"), a = pn.author;
    if (a) {
      var name = h("input.in.grow", { maxlength: 60, "data-keep": "name", "aria-label": "Its name" });
      name.value = pn.name;
      function rename() { if (name.value.trim() && name.value.trim() !== pn.name) { send("rename", { uid: pn.uid, name: name.value }); } }
      name.addEventListener("change", rename);
      name.addEventListener("keydown", function (e) { if (e.key === "Enter") { name.blur(); } if (e.key === "Escape") { name.value = pn.name; name.blur(); } });
      box.appendChild(h("div.row", {}, [name, btn("⋯", function (e, b) { menu(menuItems(pn.more), b); }, "", { title: "More for this set" })]));
      var ev = h("select.in", { onchange: function () { send("set_for", { uid: pn.uid, eid: this.value }); } });
      ev.appendChild(h("option", { value: "", text: "Nothing" }));
      pn.events.forEach(function (e) { var o = h("option", { value: e.id, text: e.label }); if (e.id === pn.for) { o.selected = true; } ev.appendChild(o); });
      ev.appendChild(h("option", { value: "new", text: "A new quiz, exam or day…" }));
      var due = dateInput(pn.due, function (v) { send("set_due", { uid: pn.uid, due: v }); }, "due");
      box.appendChild(h("div", { style: "margin-top:10px" }, [
        h("div.fl", {}, [h("span", { text: "Cards open" }), dateInput(pn.opens, function (v) { send("move", { uid: pn.uid, to: v }); }, "opens")]),
        h("div.fl", {}, [h("span", { text: "Finish by" }), h("div.row", {}, [due, pn.due ? btn("No day", function () { send("set_due", { uid: pn.uid, due: "" }); }, "t") : null])]),
        h("div.fl", {}, [h("span", { text: "Leads up to" }), ev])]));
    } else {
      box.appendChild(h("h3", { text: pn.label }));
      box.appendChild(h("div.muted.sm", { text: pn.meta }));
    }
    box.appendChild(h("div.sh", { text: pn.n !== null && pn.n !== undefined ? "Its cards (" + pn.n.toLocaleString() + ")" : "Its cards" }));
    if (pn.said) { box.appendChild(h("div.muted.sm", { text: pn.said, style: "margin:-2px 0 6px" })); }
    pn.sources.forEach(function (s) {
      var items = [];
      if (s.n) { items.push({ label: "Show these " + s.n.toLocaleString() + " in Browse", cmd: "browse", args: { key: S.picked, i: s.i } }); }
      if (s.menu) { items.push({ sep: true }); items = items.concat(menuItems(s.menu)); }
      box.appendChild(h("div.src", { title: s.raw, onclick: function (e) { if (items.length) { e.stopPropagation(); menu(items, this); } } }, [
        h("span", { text: s.name }), h("span.n", { text: s.n !== null && s.n !== undefined ? s.n.toLocaleString() : "" }),
        a && s.key ? h("button.x", { type: "button", title: "Take it off this set", text: "✕", onclick: function (e) {
          e.stopPropagation(); send("op", { op: { op: "take_cards", date: pn.uid, key: s.key } });
        } }) : h("span")]));
    });
    var acts = h("div.row", { style: "margin-top:6px" });
    if (a) {
      acts.appendChild(btn("Add from the deck", function () { send("deck", { uid: pn.uid }); }, "", { title: "Tick the deck's tags for this set (Ctrl+D)" }));
      acts.appendChild(btn("Add a search or IDs…", function () { send("add_search"); }));
    }
    if (pn.n) { acts.appendChild(btn("Show the " + pn.n.toLocaleString() + " in Browse", function () { send("browse", { key: S.picked }); })); }
    box.appendChild(acts);
    if (a || pn.todo.length || pn.every.length) {
      box.appendChild(h("div.sh", { text: "To do" }));
      pn.todo.forEach(function (t, i) {
        box.appendChild(h("div.line", {}, [h("span", { text: t }), a ? h("button.x", { type: "button", text: "✕", title: "Take this line off",
          onclick: function () { send("todo_off", { i: i }); } }) : null]));
      });
      pn.every.forEach(function (t) { box.appendChild(h("div.line.muted", { text: t })); });
      if (a) { box.appendChild(h("div.row", { style: "margin-top:4px" }, [btn(pn.todo.length ? "Change its to-dos…" : "Add a to-do…", function () { send("todo"); })])); }
    }
    box.appendChild(notesBlock(pn.notes));
    return box;
  }
  function eventPanel(pn) {
    var box = h("div");
    if (pn.author) {
      var name = h("input.in.grow", { maxlength: 60, "data-keep": "name" });
      name.value = pn.name;
      name.addEventListener("change", function () { send("rename_event", { eid: pn.eid, name: name.value }); });
      name.addEventListener("keydown", function (e) { if (e.key === "Enter") { name.blur(); } });
      box.appendChild(h("div.row", {}, [name]));
      box.appendChild(h("div.fl", { style: "margin-top:10px" }, [h("span", { text: "On" }), dateInput(pn.day, function (v) { send("move_event", { eid: pn.eid, to: v }); }, "evday")]));
    } else { box.appendChild(h("h3", { text: pn.title })); }
    box.appendChild(h("div.muted.sm", { text: pn.said, style: "margin:6px 0" }));
    pn.items.forEach(function (x) { box.appendChild(h("div.line", {}, [h("span.link", { text: x.label, onclick: function () { send("pick", { key: x.key }); } })])); });
    if (pn.author) { box.appendChild(h("div.row", { style: "margin-top:10px" }, [btn("Take it off…", function () { send("delete"); }, "bad")])); }
    return box;
  }
  function reviewPanel(pn) {
    return h("div", {}, [h("h3", { text: pn.title }), h("div.muted.sm", { text: pn.said, style: "margin:6px 0" }),
      pn.author ? h("div.row", {}, [btn("Change its sets…", function () { send("review_day", { day: pn.day }); }),
        btn("No review day", function () { send("delete"); }, "bad")]) : null]);
  }

  /* the deck beside the plan */
  function deckPanel(dk) {
    var box = h("div");
    if (dk.none) { box.appendChild(h("div.muted", { text: dk.none })); return box; }
    box.appendChild(h("div.row.sp", {}, [
      dk.target ? h("span", {}, [h("span.muted", { text: "Ticks add to " }), h("b", { text: dk.targetLabel })]) : h("b", { text: "Tick what the plan covers" }),
      btn("Done", function () { send("deck_done"); })]));
    var seg = h("div.seg", { style: "margin:10px 0 8px" });
    dk.views.forEach(function (v) { seg.appendChild(h("button" + (dk.view === v.key ? ".on" : ""), { type: "button", text: v.label, onclick: function () { send("deck_view", { view: v.key }); } })); });
    if (dk.more.length) {
      var inMore = dk.more.filter(function (v) { return v.key === dk.view; })[0];
      seg.appendChild(h("button" + (inMore ? ".on" : ""), { type: "button", text: inMore ? inMore.label : "More ▾",
        onclick: function (e) { e.stopPropagation(); menu(dk.more.map(function (v) { return { label: v.label, on: v.key === dk.view, cmd: "deck_view", args: { view: v.key } }; }), this); } }));
    }
    box.appendChild(seg);
    var find = h("input.in", { placeholder: "Find a tag or subdeck", "data-keep": "deckfind", style: "width:100%" });
    find.value = ui.deckFind !== null ? ui.deckFind : (dk.find || "");
    find.addEventListener("input", function () {
      ui.deckFind = this.value; var v = this.value;
      clearTimeout(ui.deckTimer); ui.deckTimer = setTimeout(function () { send("deck_find", { text: v }); }, 220);
    });
    box.appendChild(find);
    var tree = h("div.tree", { style: "margin-top:8px" });
    function node(n, depth) {
      var tw = n.kids ? h("span.tw", { text: n.open ? "▾" : "▸", onclick: function () { send("deck_open", { key: n.key, on: !n.open }); } }) : h("span.tw");
      var cb = h("span.cb" + (n.check === 1 ? ".on" : n.check === 2 ? ".part" : ""), { role: "checkbox", "aria-checked": n.check === 1 ? "true" : n.check === 2 ? "mixed" : "false",
        onclick: function (e) { e.stopPropagation(); if (!n.off && !busy()) { send("deck_tick", { key: n.key, on: n.check !== 1 }); } } });
      var row = h("div.tn2" + (n.placed ? ".placed" : "") + (n.off ? ".dis" : ""), { style: "padding-left:" + (4 + depth * 16) + "px", title: n.path,
        oncontextmenu: function (e) { e.preventDefault(); rowMenu(n, this); } },
        [tw, (dk.view !== "plan" || dk.target) ? cb : null, h("span.nm", { text: n.name }), h("span.wh", { text: n.where }), h("span.c", { text: (n.n || 0).toLocaleString() }),
          h("button.x", { type: "button", text: "⋯", title: "More for this tag", onclick: function (e) { e.stopPropagation(); rowMenu(n, this); } })]);
      tree.appendChild(row);
      (n.children || []).forEach(function (c) { node(c, depth + 1); });
    }
    function rowMenu(n, anchor) {
      if (!author()) { return; }
      var items = [];
      if (n.uid) { items.push({ label: "Go to its set (" + n.where.replace("on ", "") + ")", cmd: "pick", args: { key: ["date", n.uid] } }); }
      if (String(n.key).indexOf("tag:") === 0) { items.push({ label: "A note for followers on it…", cmd: "remark", args: { path: n.path } }); }
      if (/^(tag|deck):/.test(String(n.key)) && !n.ptag && !n.off) {
        items.push({ label: "A set of its own, next free day", cmd: "lesson_from", args: { key: n.key, day: "next" } },
          { label: "A set of its own on a day…", cmd: "lesson_from", args: { key: n.key, day: null } });
      }
      if (n.ptag) { items.push({ sep: true }, { label: "Rename the tag…", cmd: "ptag_rename", args: { ptag: n.ptag } }, { label: "Delete the tag…", cmd: "ptag_delete", args: { ptag: n.ptag } }); }
      if (items.length) { menu(items, anchor); }
    }
    dk.nodes.forEach(function (n) { node(n, 0); });
    dk.lines.forEach(function (l) {
      tree.appendChild(h("div" + (l.view ? ".link" : ".muted"), { text: l.words, style: "padding:4px", onclick: l.view ? function () { send("deck_view", { view: l.view }); } : null }));
    });
    box.appendChild(tree);
    if (dk.fill) {
      var f = dk.fill, fb = h("div.fillbar" + (f.bad ? ".bad" : ""), {}, [f.head ? h("b", { text: f.head + " " }) : null, f.words]);
      var acts = h("div.row", { style: "margin-top:8px" });
      if (f.go) { acts.appendChild(btn(f.go.label, function () { send("deck_lay", { how: f.go.how }); }, "pri", { disabled: busy() })); }
      if (f.alt) { acts.appendChild(btn(f.alt.label, function () { send("deck_lay", { how: f.alt.how }); })); }
      if (f.upto && f.upto.length) {
        acts.appendChild(btn("Before a quiz or exam", function (e, b) {
          menu(f.upto.map(function (x) { return { label: x.label, cmd: "deck_lay", args: { how: ["end", false, null], upto: x.eid } }; }), b);
        }, "ch", { disabled: busy() }));
      }
      if (f.week) { acts.appendChild(btn("Next week only", function () { send("deck_week"); }, "", { title: "Lay out only what fits next week" })); }
      if (f.keep) { acts.appendChild(btn("Save the ticks only", function () { send("deck_keep"); }, "", { title: "Saves the ticks as what the plan covers, without laying them out" })); }
      fb.appendChild(acts);
      box.appendChild(fb);
    }
    if (dk.cardNotes && dk.cardNotes.length) {
      box.appendChild(h("div.row", { style: "margin-top:8px" }, [btn("Notes on cards…", function (e, b) {
        menu(dk.cardNotes.map(function (x) { return { label: x.label, sub: [{ label: "Take it off", cmd: "card_note_off", args: { rid: x.id } }] }; }), b);
      })]));
    }
    return box;
  }

  function foot(p) {
    var out = [];
    if (p.sending) {
      var s = p.sending, w = h("span.w", {}, [h("b", { text: s.n + " change" + (s.n !== 1 ? "s" : "") + " not sent: " })]);
      s.items.forEach(function (x, i) {
        if (i) { w.appendChild(document.createTextNode(", ")); }
        w.appendChild(x.key ? h("span.k", { text: x.words, onclick: function () { send("pick", { key: x.key }); } }) : h("span", { text: x.words }));
      });
      if (s.more > 0) { w.appendChild(document.createTextNode(", and " + s.more + " more")); }
      out.push(h("div.waiting", {}, [w, btn("Discard", function () { send("discard"); }, "t", { title: "Take every change not sent back; nobody saw them" }),
        btn("Review and send", function () { send("review_send"); }, "pri", { disabled: busy(), title: "Every change waiting, and a line for followers (Ctrl+Enter)" })]));
    }
    if (author()) {
      var ta = h("textarea.in" + (ui.paste.indexOf("\n") >= 0 ? ".tall" : ""), { placeholder: "Paste plan lines", "data-keep": "paste", "aria-label": "Paste plan lines" });
      ta.value = ui.paste;
      ta.addEventListener("input", function () { var was = ui.paste.indexOf("\n") >= 0; ui.paste = this.value; if (was !== (ui.paste.indexOf("\n") >= 0)) { this.classList.toggle("tall"); } });
      out.push(h("div.paste", {}, [ta, btn("Show the changes", function () { if (ui.paste.trim()) { send("paste", { text: ui.paste }); } }, "", { disabled: busy() }),
        btn("The plan as text", function () { send("text"); }, "", { title: "Every set, quiz and tag as plan lines, to read or edit" }),
        btn("AI prompt", function (e, b) {
          menu([{ label: "Copy: Plan the sets", cmd: "prompt", args: { which: "plan" } }, { label: "Copy: Tag by objective", cmd: "prompt", args: { which: "tags" } },
            { sep: true }, { label: "See the prompt", sub: [{ label: "Plan the sets", cmd: "see_prompt", args: { which: "plan" } },
              { label: "Tag by objective", cmd: "see_prompt", args: { which: "tags" } }] }], b);
        }, "ch", { title: "Copied for you to paste in your own AI; it gets tag names and counts, never a card" })]));
    }
    out.push(h("div.row.calrow", {}, [h("span.grow"), btn("Add to my calendar…", function () { send("calendar"); }, "t",
      { title: "The sets, quizzes and review days as a calendar file, for Google, Apple or Outlook" })]));
    return out;
  }

  function planTab() {
    var p = S.plan, body = h("div.body");
    strips(p).forEach(function (x) { body.appendChild(x); });
    body.appendChild(toolbar(p));
    var left = h("div.pane", { "data-scroll": "left" }, [ui.mode === "week" ? weekView(p) : ui.mode === "month" ? monthView(p) : listView(p)]);
    var side = h("div.side", { "data-scroll": "side" }, [S.side === "deck" && S.deck ? deckPanel(S.deck) :
      S.panel.kind === "date" ? datePanel(S.panel) : S.panel.kind === "event" ? eventPanel(S.panel) :
      S.panel.kind === "review" ? reviewPanel(S.panel) : h("div.muted", { text: S.panel.words })]);
    body.appendChild(h("div.cols", {}, [left, side]));
    foot(p).forEach(function (x) { body.appendChild(x); });
    return body;
  }
  function otherTab(name) {
    var data = S[name], draw = dcPlan.tabs && dcPlan.tabs[name];
    if (!data || data.todo || !draw) { return h("div.body", {}, [h("div.empty", { text: "Loading…" })]); }
    return h("div.body", { "data-scroll": name }, [draw(data, kit())]);
  }
  function kit() { return { h: h, btn: btn, send: send, menu: menu, sheet: sheet, S: S, ui: ui, dateInput: dateInput }; }
  function welcome() {
    return h("div.welcome", {}, [h("h2", { text: "No plans yet" }),
      h("p.muted", { text: "A plan puts a deck's cards in sets on days, and opens each set's cards in Anki as its day comes." }),
      h("div.row", {}, [btn("New plan…", function () { send("new_plan"); }, "pri"), btn("Follow a plan…", function () { send("follow_plan"); })])]);
  }

  /* ---- drawn ---- */
  function keepState() {
    var a = document.activeElement, st = { scroll: {} };
    if (a && a.getAttribute && a.getAttribute("data-keep")) {
      st.focus = a.getAttribute("data-keep");
      try { st.sel = [a.selectionStart, a.selectionEnd]; } catch (e) { st.sel = null; }
      if (st.focus !== "name") { st.value = a.value; }
    }
    root.querySelectorAll("[data-scroll]").forEach(function (el) { st.scroll[el.getAttribute("data-scroll")] = el.scrollTop; });
    return st;
  }
  function restore(st) {
    Object.keys(st.scroll).forEach(function (k) { var el = root.querySelector("[data-scroll=" + k + "]"); if (el) { el.scrollTop = st.scroll[k]; } });
    if (st.focus) {
      var el = root.querySelector("[data-keep=" + st.focus + "]");
      if (el) {
        if (st.value !== undefined && st.focus !== "name") { el.value = st.value; }
        el.focus();
        try { if (st.sel) { el.setSelectionRange(st.sel[0], st.sel[1]); } } catch (e) { /* a date box */ }
      }
    }
  }
  function render() {
    if (!S) { return; }
    var st = keepState(), sh = ui.sheet;
    closeMenu();
    root.textContent = "";
    root.appendChild(renderTop());
    if (S.new && dcPlan.newPlan) {  /* New plan, in the tabs' place */
      root.appendChild(h("div.body", { "data-scroll": "new" }, [dcPlan.newPlan(S.new, kit())]));
    } else {
      if (S.plan) { root.appendChild(renderTabs()); }
      if (S.welcome) { root.appendChild(welcome()); }
      else if (!S.plan) { root.appendChild(h("div.body", {}, [h("div.empty", { text: S.head.plans.length ? "Loading the plan…" : "" })])); }
      else if (S.tab === "plan") { root.appendChild(planTab()); }
      else { root.appendChild(otherTab(S.tab)); }
    }
    root.appendChild(h("div.foot", {}, [h("span.status", { text: S.status || "", role: "status" }), btn("Close", function () { send("close"); }, "t")]));
    restore(st);
    if (sh) { sheet(sh); }
    var on = root.querySelector(".pane .on");
    if (on && S._scrollPick) { on.scrollIntoView({ block: "nearest" }); }
  }

  /* ---- keys ---- */
  document.addEventListener("keydown", function (e) {
    if (!S) { return; }
    if (ui.sheet) { if (e.key === "Escape") { closeSheet(); } return; }
    if (e.key === "Escape") { closeMenu(); }
    var typing = /^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement || {}).tagName || "");
    var mod = e.ctrlKey || e.metaKey, k = e.key.toLowerCase();
    if (mod && k === "n" && author()) { e.preventDefault(); send("new_date_form"); return; }
    if (mod && k === "e" && author()) { e.preventDefault(); send("new_event_form"); return; }
    if (mod && k === "f") { e.preventDefault(); var f = root.querySelector("[data-keep=find]"); if (f) { f.focus(); f.select(); } return; }
    if (mod && k === "t") { e.preventDefault(); goToday(); return; }
    if (mod && (k === "1" || k === "2" || k === "3")) { e.preventDefault(); ui.mode = ["list", "week", "month"][+k - 1]; render(); return; }
    if (mod && k === "d" && author()) { e.preventDefault(); send("deck", { uid: S.picked && S.picked[0] === "date" ? S.picked[1] : null }); return; }
    if (mod && e.key === "Enter" && S.plan && S.plan.sending) { e.preventDefault(); send("review_send"); return; }
    if (mod && k === "z" && !typing) { e.preventDefault(); send("undo_key"); return; }
    if (typing || !S.plan || S.tab !== "plan") { return; }
    if (e.altKey && (e.key === "ArrowLeft" || e.key === "ArrowRight")) { e.preventDefault(); send("nudge", { k: e.key === "ArrowLeft" ? -1 : 1 }); return; }
    if (e.key === "ArrowUp" || e.key === "ArrowDown") {
      var ks = visibleKeys(), cur = S.picked ? keyStr(S.picked) : "", i = ks.map(keyStr).indexOf(cur);
      i = Math.max(0, Math.min(ks.length - 1, i + (e.key === "ArrowUp" ? -1 : 1)));
      if (ks[i]) { e.preventDefault(); S._scrollPick = true; send("pick", { key: ks[i] }); }
      return;
    }
    if ((e.key === "Enter" || e.key === "F2") && author()) { e.preventDefault(); focusName(); return; }
    if ((e.key === "Delete" || e.key === "Backspace") && author() && S.picked) { e.preventDefault(); send("delete"); }
  });

  return {
    start: function (state, isPreview) {
      preview = !!isPreview;
      root = document.getElementById("dcp");
      S = state;
      render();
      if (!preview) { send("ready"); }
    },
    show: function (state) {
      var scroll = S && S._scrollPick;
      if (S && state.picked && !same(state.picked, S.picked)) { scroll = true; }
      if (S && S.head && state.head && S.head.pid !== state.head.pid) { ui.week = ui.month = null; ui.find = ""; ui.opened = {}; ui.closed = {}; ui.all = null; ui.deckFind = null; }
      if (state.side !== "deck") { ui.deckFind = null; }
      S = state;
      S._scrollPick = scroll;
      render();
      S._scrollPick = false;
    },
    status: function (st) { if (!S) { return; } S.status = st.status; var el = root.querySelector(".status"); if (el) { el.textContent = st.status || ""; } },
    sheet: sheet,
    openUndo: function () { var b = document.getElementById("dcp-undo"); if (b) { undoMenu(b); } },
    pasted: function () { ui.paste = ""; render(); },
    set: function (patch) { Object.assign(ui, patch || {}); render(); },
    tabs: {}
  };
})();
