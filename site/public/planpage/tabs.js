/* Insights and Settings in Your plans: webtabs.py works out what they say,
   plan.js draws the window and calls dcPlan.tabs[name](data, ctx). Every
   name and number is set as text. A click goes back as tabcmd {name, args}
   (webtabs.c_<name>). What's only being typed (a name, a line, a link) is
   kept here till it's saved; Posts, History and a pick are sheets
   (dcPlan.sheets, drawn inside plan.js's). */
(function () {
  "use strict";
  var P = window.dcPlan;
  if (!P || !P.tabs) { return; }
  var DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

  function run(send, name, args) { send("tabcmd", { name: name, args: args || {} }); }
  function item(name, label, args, more) {
    return Object.assign({ label: label, cmd: "tabcmd", args: { name: name, args: args || {} } }, more || {});
  }
  function norm(s) { return String(s || "").split(/\s+/).join(" ").trim(); }
  function monday(s) {
    var p = String(s).split("-"), x = new Date(+p[0], +p[1] - 1, +p[2]);
    x.setDate(x.getDate() - (x.getDay() + 6) % 7);
    return x.getFullYear() + "-" + String(x.getMonth() + 1).padStart(2, "0") + "-" + String(x.getDate()).padStart(2, "0");
  }

  /* ---- pieces ---- */
  function sec(h, title, kids, cls) {
    return h("section.tsec" + (cls ? "." + cls : ""), {}, [title ? h("h3.th", { text: title }) : null].concat(kids));
  }
  function fr(h, label, kids, attrs) {
    return h("div.fr", attrs || {}, [h("span.lb", { text: label }), h("div.ctl", {}, kids)]);
  }
  /* a bar: parts end to end on one scale ([{v: %, k: fill|soft|over, has}]), a track under them (%) */
  function bar(h, parts, o) {
    o = o || {};
    var b = h("div.tbar", { title: o.tip || null, role: o.tip ? "img" : null, "aria-label": o.tip || null });
    if (o.track !== undefined && o.track !== null) { b.appendChild(h("i.trk", { style: "width:" + o.track + "%" })); }
    var f = h("span.tfl");
    parts.forEach(function (x) { if (x.has || x.v > 0) { f.appendChild(h("i." + x.k, { style: "width:" + x.v + "%" })); } });
    b.appendChild(f);
    return b;
  }
  function input(h, keep, max, value, attrs) {
    var i = h("input.in", Object.assign({ "data-keep": keep, maxlength: max }, attrs || {}));
    i.value = value;
    return i;
  }
  /* what's typed in a box, kept till it's saved: a reload shows the plan's
     words unless something else was typed here (settings_tab's rule) */
  function kept(ui, pid, key, server) {
    var s = ui.tb || (ui.tb = {}), k = pid + "\u0001" + key, x = s[k];
    if (!x || x.typed === x.put) { x = s[k] = { put: server, typed: server }; } else { x.put = server; }
    return x;
  }
  function seg(h, items, attrs) {
    var s = h("div.seg", Object.assign({ role: "group" }, attrs || {}));
    items.forEach(function (it) {
      s.appendChild(h("button" + (it.on ? ".on" : ""), { type: "button", text: it.label, title: it.title || null, disabled: it.off,
        "aria-pressed": it.on ? "true" : "false", onclick: function (e) { e.stopPropagation(); if (!it.on || it.again) { it.fn(); } } }));
    });
    return s;
  }
  function select(h, opts, value, onchange, attrs) {
    var s = h("select.in", Object.assign({ onchange: function () { onchange(this.value); } }, attrs || {}));
    opts.forEach(function (o) {
      var op = h("option", { value: String(o.v === null || o.v === undefined ? "" : o.v), text: o.label });
      if (String(o.v) === String(value)) { op.selected = true; }
      s.appendChild(op);
    });
    return s;
  }

  /* ---- Insights ---- */
  function workload(d, c) {
    var h = c.h, kids = [];
    if (d.empty) { return sec(h, "Workload", [h("p.tp.muted", { text: d.empty })], "twork"); }
    kids.push(h("p.tp", { text: d.words }));
    if (d.over) { kids.push(h("p.tp.warn", { text: d.over })); }
    /* a week a row: its name, new a study day (the pace a line down the column), reviews a day */
    var g = h("div.wl");
    g.appendChild(h("span"));
    g.appendChild(h("span.wlh", { text: d.newHead }));
    g.appendChild(h("span.wlh", { text: d.rvHead }));  /* each spans its count and its bar */
    d.rows.forEach(function (r) {
      g.appendChild(h("div.wln" + (r.now ? ".now" : "") + (r.past ? ".past" : ""), { title: r.tip }, [
        h("span", {}, [h("b", { text: r.week }), " ", h("span.muted", { text: r.span })]),
        r.events ? h("span.evs", { text: r.events }) : null]));
      /* each count just before its own bar, so it reads with that bar (3.9.6, after the last check) */
      var nb = h("div.wlb.wnew", { title: r.tip }, [bar(h, [{ v: r.new, k: r.over ? "over" : "fill", has: r.has }])]);
      if (d.line !== null && d.line !== undefined) { nb.appendChild(h("i.pl", { style: "left:" + d.line + "%" })); }
      g.appendChild(h("span.wlw" + (r.over ? ".warn" : ""), { text: r.newWords }));
      g.appendChild(nb);
      g.appendChild(h("span.wlw", { text: r.rvWords }));
      g.appendChild(h("div.wlb", { title: r.tip }, [bar(h, [{ v: r.rv, k: "fill", has: r.hasRv }])]));
    });
    kids.push(g);
    return sec(h, "Workload", kids, "twork");
  }
  function parts(h, p) {
    var g = h("div.tparts");
    p.rows.forEach(function (r) {
      g.appendChild(h("span.tpn", { text: r.name, title: r.name }));
      g.appendChild(h("div.tpb", { title: r.name + ": " + r.words }, [bar(h, [{ v: r.fill, k: "fill", has: r.fill > 0 }], { track: r.track })]));
      g.appendChild(h("span.wlw", { text: r.words }));
    });
    return [g, p.more ? h("p.tp.muted", { text: p.more }) : null, p.none ? h("p.tp.muted", { text: p.none }) : null];
  }
  function deck(d, c) {
    var h = c.h, kids = [h("p.tp", { text: d.words }), h("div.meter", {}, [bar(h, d.bar, { track: 100, tip: d.tip })])];
    if (d.key) {
      kids.push(h("div.tkey", {}, [h("span.muted", { text: d.key }), h("i.sw.fill"), h("span.muted", { text: "Seen" }),
        h("i.sw.soft"), h("span.muted", { text: "To go" })]));
    }
    if (d.ways && d.ways.length) {
      kids.push(h("div.row.tby", {}, [c.btn(d.by, function (e, b) {
        c.menu(d.ways.map(function (x) { return item("map_by", x.name, { key: x.key }, { on: x.on }); }), b);
      }, "ch", { title: "How the deck is split: the same as its topic map on the board" })]));
    } else if (d.by) { kids.push(h("div.tsub", { text: d.by })); }
    if (d.parts) { kids = kids.concat(parts(h, d.parts)); }
    if (d.inside) { kids.push(h("div.tsub", { text: d.inside.head })); kids = kids.concat(parts(h, d.inside)); }
    return sec(h, "How much of the deck", kids);
  }
  function goRow(c, x, ev) {
    var h = c.h;
    return h("div.trow" + (ev ? ".ev" : ""), { tabindex: "0", title: "Show it on the Plan tab", onclick: function () {
      var ui = c.ui, m = monday(x.day);
      ui.opened[m] = 1; delete ui.closed[m]; ui.find = ""; ui.look = false; ui.week = null; ui.month = null;
      run(c.send, "go", { key: x.key });
    }, onkeydown: function (e) { if (e.key === "Enter") { this.click(); } } },
    [h("span.muted", { text: x.dayw }), h("span.nm", { text: x.name }), h("span.wlw", { text: x.words })]);
  }
  function contents(d, c) {
    var h = c.h, kids = [];
    if (d.exams.length) { kids.push(h("div.tsub", { text: "Quizzes and exams" })); d.exams.forEach(function (x) { kids.push(goRow(c, x, true)); }); }
    if (d.big.length) { kids.push(h("div.tsub", { text: "Its biggest sets" })); d.big.forEach(function (x) { kids.push(goRow(c, x, false)); }); }
    d.lines.forEach(function (t) { kids.push(h("p.tp.muted", { text: t })); });
    return sec(h, "What's in it", kids);
  }
  P.tabs.insights = function (d, c) {
    var h = c.h, box = h("div.tb" + (d.none !== undefined ? "" : ".tins"));
    if (d.none !== undefined) { box.appendChild(h("div.empty", { text: d.none })); return box; }
    box.appendChild(workload(d.work, c));
    box.appendChild(deck(d.deck, c));
    box.appendChild(contents(d.has, c));
    return box;
  };

  /* ---- Settings, an author's ---- */
  function savedBox(c, d, key, server, max, attrs, cmd) {
    /* a box, and its Save once what's in it isn't the plan's */
    var h = c.h, k = kept(c.ui, d.pid, key, server), box = input(h, "tb-" + key, max, k.typed, attrs);
    var save = c.btn("Save", function () { cmd(box.value); }, "pri", { disabled: d.busy });
    function shown() { save.style.display = norm(box.value) !== norm(server) ? "" : "none"; }
    box.addEventListener("input", function () { k.typed = this.value; shown(); });
    box.addEventListener("keydown", function (e) { if (e.key === "Enter" && save.style.display !== "none" && !save.disabled) { save.click(); } });
    shown();
    return { box: box, save: save };
  }
  function shape(c, d) {
    var h = c.h, s = d.shape, busy = d.busy, rows = [];
    function put(key, value) { run(c.send, "shape", { key: key, value: value }); }
    function date(keep, value, key, title) {  /* the page's own picker (plan.js dateInput), never the computer's */
      return c.dateInput(value || "", function (v) { if (v) { put(key, v); } }, keep, { disabled: busy, title: title });
    }
    rows.push(fr(h, "Starts", [date("tb-start", s.start, "start", "Every set and quiz moves with it")]));
    rows.push(fr(h, "Ends with", [select(h, s.ends, s.end, function (v) { put("end", v); }, { disabled: busy, "aria-label": "Ends with" }),
      s.end === "day" ? date("tb-endday", s.endDay, "end_day") : null]));
    var days = h("div.tdays", { role: "group", "aria-label": "Study days" });
    "MTWTFSS".split("").forEach(function (x, i) {
      days.appendChild(h("button" + (s.days[i] ? ".on" : ""), { type: "button", text: x, title: DAYS[i], disabled: busy,
        "aria-pressed": s.days[i] ? "true" : "false", onclick: function () { put("day", i); } }));
    });
    rows.push(fr(h, "Study days", [days]));
    var daily = null;
    if (s.mode === "daily") {
      var n = h("input.in.num", { type: "number", min: 1, max: 5000, "data-keep": "tb-daily", disabled: busy, "aria-label": "New cards a day" });
      n.value = s.daily;
      n.addEventListener("change", function () { if (this.value) { put("daily", this.value); } });
      daily = h("label.unit", {}, [n, h("span.muted", { text: "a day" })]);
    }
    rows.push(fr(h, "New cards", [seg(h, s.modes.map(function (m) {
      return { label: m.label, on: s.mode === m.v, off: busy, fn: function () { put("mode", m.v); } };
    }), { "aria-label": "New cards" }), daily]));
    var taper = h("input.in.num", { type: "number", min: 0, max: 60, "data-keep": "tb-taper", disabled: busy || s.taperOff,
      "aria-label": "No new cards before the end" });
    taper.value = s.taper;
    taper.addEventListener("change", function () { if (this.value !== "") { put("taper", this.value); } });
    rows.push(fr(h, "No new cards before the end", [h("label.unit", {}, [taper, h("span.muted", { text: "days" })])]));
    rows.push(fr(h, "Catch-up weeks", [select(h, s.catchups, s.catchup, function (v) { put("catchup", v); },
      { disabled: busy, title: "A week now and then with no new cards", "aria-label": "Catch-up weeks" })]));
    if (s.preview) {
      var words = h("span.grow");
      s.preview.parts.forEach(function (x) { words.appendChild(x[0] === "b" ? h("b", { text: x[1] }) : document.createTextNode(x[1])); });
      rows.push(fr(h, "", [h("div.tprev" + (s.preview.bad ? ".bad" : ""), { role: "status" }, [words,
        c.btn("Put it back", function () { run(c.send, "shape_back"); }, "t"),
        c.btn(s.go, function () { run(c.send, "shape_save"); }, "pri", { disabled: busy || s.preview.bad })])]));
    }
    return rows;
  }
  function coauthors(c, d) {
    var h = c.h, box = h("div.tco"), tip = "They edit it with you, and its tags go on their notes in Anki. Each one says yes first.";
    if (d.coauthors.length) {
      var list = h("div.tlist", { title: tip });
      d.coauthors.forEach(function (e) {
        list.appendChild(h("div.tli", {}, [h("b", { text: e.name }), h("span.muted.grow", { text: e.what }),
          e.hand ? c.btn("Hand it to them", function () { run(c.send, "hand", { uid: e.uid }); }, "t", { disabled: d.busy }) : null,
          e.off ? c.btn(e.off, function () { run(c.send, "coauthor_off", { uid: e.uid }); }, "t bad", { disabled: d.busy }) : null]));
      });
      box.appendChild(list);
    }
    var acts = h("div.row");
    if (d.canAsk) { acts.appendChild(c.btn("Ask one of my crew…", function () { run(c.send, "coauthor_ask"); }, "", { disabled: d.busy, title: tip })); }
    if (d.offered) { acts.appendChild(c.btn("Take the offer back", function () { run(c.send, "unhand"); }, "", { disabled: d.busy })); }
    if (d.leave) { acts.appendChild(c.btn("Leave this plan", function () { run(c.send, "leave"); }, "", { disabled: d.busy })); }
    if (acts.childNodes.length) { box.appendChild(acts); }
    if (!box.childNodes.length) { box.appendChild(h("span.muted", { text: "None" })); }
    return box;
  }
  function author(d, c) {
    var h = c.h, box = h("div.tb.tset"), busy = d.busy;
    /* the plan */
    var nm = kept(c.ui, d.pid, "name", d.name), ln = kept(c.ui, d.pid, "line", d.line);
    var name = input(h, "tb-name", 60, nm.typed, { "aria-label": "Name" });
    var line = input(h, "tb-line", 120, ln.typed, { placeholder: "Organ systems, one a week, done by January.", "aria-label": "One line" });
    var meta = c.btn("Save", function () { run(c.send, "meta", { name: name.value, line: line.value }); }, "pri");
    function metaShown() {
      meta.style.display = norm(name.value) !== d.name || norm(line.value) !== d.line ? "" : "none";
      meta.disabled = !name.value.trim() || busy;
    }
    name.addEventListener("input", function () { nm.typed = this.value; metaShown(); });
    line.addEventListener("input", function () { ln.typed = this.value; metaShown(); });
    [name, line].forEach(function (b) { b.addEventListener("keydown", function (e) { if (e.key === "Enter" && meta.style.display !== "none" && !meta.disabled) { meta.click(); } }); });
    metaShown();
    var plan = [fr(h, "Name", [name]), fr(h, "One line", [line, meta])].concat(shape(c, d));
    plan.push(fr(h, "Every week", [h("span.grow", { text: d.every }), c.btn("Change…", function () { run(c.send, "every"); }, "",
      { disabled: busy, title: "Lines followers tick in Due on the same weekday every week of the plan" })]));
    box.appendChild(sec(h, "The plan", plan));
    /* sharing */
    var share = [fr(h, "Code", [h("b.code", { text: d.code }),
      c.btn("Copy link", function () { run(c.send, "copy_link"); }, "", { disabled: !d.hasCode }),
      c.btn("Open its page", function () { run(c.send, "open_page"); }, "", { disabled: !d.hasCode })])];
    var url = savedBox(c, d, "url", d.url, 300, { placeholder: "https://…", title: d.urlTip, "aria-label": "Where to get the deck" },
      function (v) { run(c.send, "deck_url", { url: v }); });
    share.push(fr(h, "Where to get the deck", [url.box, url.save]));
    if (d.owner) {
      share.push(fr(h, "Offer it to one of my squads", [select(h, [{ v: "", label: "No squad" }].concat(d.squads.map(function (q) { return { v: q.id, label: q.name }; })),
        d.squad || "", function (v) { run(c.send, "who", { squad: v || null, audience: d.audience }); }, { disabled: busy, "aria-label": "Offer it to one of my squads" })]));
      var who = h("div.tradio", { role: "radiogroup", "aria-label": "Who can follow" });
      [["code", "Anyone with the code"], ["squad", "Only people in that squad of mine"]].forEach(function (x) {
        var r = h("input", { type: "radio", name: "tb-who", checked: d.audience === x[0], disabled: busy || (x[0] === "squad" && !d.squad) });
        r.addEventListener("change", function () { run(c.send, "who", { squad: d.squad, audience: x[0] }); });
        who.appendChild(h("label", {}, [r, h("span", { text: x[1] })]));
      });
      share.push(fr(h, "Who can follow", [who]));
    } else {
      share.push(fr(h, "Who can follow", [h("span.muted", { text: d.ownerOnly })]));
    }
    share.push(fr(h, "Followers", [h("span", { text: d.following }), c.btn("Posts…", function () { run(c.send, "posts"); }, "",
      { disabled: busy, title: "What followers were told (each send's line too), and a line to them" })]));
    share.push(fr(h, "Co-authors", [coauthors(c, d)], { cls: "top" }));
    var lib = [];
    if (d.library.shown) {
      var cb = h("input", { type: "checkbox", checked: d.library.on, disabled: d.library.off });
      cb.addEventListener("change", function () { run(c.send, "listed", { on: this.checked }); });
      lib.push(h("label.tcheck", { title: "Anyone signed in can find it, look at its calendar, follow it, or copy it into a plan " +
        "of their own. Your name shows as its author, and its code shows there." }, [cb, h("span", { text: "List it in the library" })]));
    }
    if (d.library.said) { lib.push(h("div.muted.sm", { text: d.library.said })); }
    if (lib.length) { share.push(fr(h, "Library", [h("div.tstack", {}, lib)])); }
    box.appendChild(sec(h, "Sharing", share));
    /* my own follow of it (d.mine): its rows, as a follower's; not following it, Start it here… (Anki's: the Follow window on its code) */
    if (d.mine && d.mine.start) {
      box.appendChild(sec(h, "Your follow", [fr(h, "On this account", [h("span.grow.muted", { text: "You don't follow it yet." }),
        c.btn("Start it here…", function () { run(c.send, "start_here"); }, "", { disabled: busy,
          title: "Follow it in this Anki: the deck it runs on, how its cards open, and Today's set" })])]));
    } else if (d.mine) {
      box.appendChild(sec(h, d.mine.head, followRows(d.mine, c)));
    }
    /* this computer: d.ai null where there's no AI app (duecrew.com) */
    if (d.ai !== null) {
      box.appendChild(sec(h, "This computer", [fr(h, "Your AI app", [h("span", { text: d.ai }), c.btn("Set up…", function () { run(c.send, "ai_app"); }, "",
        { title: "An AI app on this computer (Claude, say) reads your plans and puts changes under one for you to send; it never sends" })])]));
    }
    box.appendChild(sec(h, "This plan", [
      fr(h, "Copy", [c.btn("Copy it for next year", function () { run(c.send, "next_year"); }, "", { disabled: busy || !d.canCopy }),
        c.btn("Copy as a table", function () { run(c.send, "table"); })]),
      /* d.more: a host's own ways on from here ([{label, name}], duecrew.com's); Anki's view has none */
      (d.more || []).length ? fr(h, "Its page", (d.more || []).map(function (x) { return c.btn(x.label, function () { run(c.send, x.name); }); })) : null,
      d.delete ? fr(h, "Delete", [c.btn("Delete this plan…", function () { run(c.send, "delete_plan"); }, "bad", { disabled: busy })]) : null]));
    return box;
  }

  /* ---- Settings, a follower's: my follow ---- */
  var LESSON_TIP = "Each open set is a deck of its own under Due Crew in Anki's deck list: " +
    "its new cards and the ones you're learning. Reviews stay where they are.";
  function followRows(d, c) {
    var h = c.h, rows = [];
    rows.push(fr(h, "My dates", [seg(h, [
      { label: "As the plan", on: !d.shift, fn: function () { run(c.send, "shift", { later: false }); } },
      { label: d.later, on: !!d.shift, again: true, fn: function () { run(c.send, "shift", { later: true }); } }], { "aria-label": "My dates" })]));
    var skip = h("div.tstack");
    d.skips.forEach(function (x) {
      skip.appendChild(h("div.tli", {}, [h("span.grow", { text: x.label }), h("button.x", { type: "button", text: "✕", title: "Stop skipping it",
        onclick: function () { run(c.send, "skip", { uid: x.uid, on: false }); } })]));
    });
    skip.appendChild(h("div", {}, [c.btn("Skip a set", function (e, b) {
      c.menu(d.ahead.length ? d.ahead.map(function (u) { return item("skip", u.label, { uid: u.uid, on: true }); })
        : [{ label: "No set ahead to skip", off: true }], b);
    }, "ch")]));
    rows.push(fr(h, "Skipping", [skip], { cls: "top" }));
    rows.push(fr(h, "Cards open", [seg(h, [
      { label: "Each morning, on their dates", on: !d.own, fn: function () { run(c.send, "own", { own: "" }); } },
      { label: "When I'm ready", on: !!d.own, title: "Up next on the board opens the next set's cards when you say",
        fn: function () { run(c.send, "own", { own: "ready" }); } }], { "aria-label": "Cards open" })]));
    if (d.lesson !== null && d.lesson !== undefined) {
      rows.push(fr(h, "Today's set", [seg(h, [
        { label: "In " + (d.deckName || "your deck"), on: !d.lesson, fn: function () { run(c.send, "lesson_deck", { on: false }); } },
        { label: "Its own deck", on: !!d.lesson, title: LESSON_TIP, fn: function () { run(c.send, "lesson_deck", { on: true }); } }], { "aria-label": "Today's set" })]));
    }
    /* d.held null: no Hold back where there's no Anki; d.team: in or out of its squad;
       d.hide: More's steps only Anki takes (duecrew.com's) */
    var hide = d.hide || [];
    rows.push(d.held === null ? null : fr(h, "Held back", [d.held ? c.btn(d.held, function () { run(c.send, "held"); }, "", { title: "The cards Hold back keeps suspended till their day" })
      : h("span.muted", { text: "Nothing held back." })]));
    rows.push(fr(h, "Squad", [h("span.muted", { text: d.squad, title: d.squadTip || null }),
      d.team ? c.btn(d.team, function () { run(c.send, "team"); }, "", { disabled: d.busy }) : null]));
    var acts = h("div.row.tacts", {}, [c.btn(d.paused ? "Resume" : "Pause until…", function () { run(c.send, "pause"); }),
      d.copy ? c.btn("Make my own copy", function () { run(c.send, "copy_mine"); }) : null,
      c.btn("More", function (e, b) {
        var more = [item("change_deck", "Change deck…"), item("open_everything", "Open everything now"),
          { label: "Open early", off: !!d.own, sub: d.early.map(function (x) { return item("early", x.label, { n: x.n }, { on: x.on }); }) },
          item("own_next", "When I'm ready, the next opens once I've seen most of the last", { on: d.own !== "next" },
            { on: d.own === "next", off: !d.own })];
        if (d.sched) { more.push(item("schedule", "My schedule…")); }
        if (d.reset) { more.push(item("reset", "Reset to default…")); }
        c.menu(more.filter(function (x) { return !(x.args && hide.indexOf(x.args.name) >= 0); }), b);
      }, "ch")].concat((d.more || []).map(function (x) { return c.btn(x.label, function () { run(c.send, x.name); }); }),  /* a host's own, as the author's */
      [h("span.grow"), c.btn("Stop following…", function () { run(c.send, "stop_following"); }, "bad")]));
    return rows.concat([acts]);
  }
  function follower(d, c) {
    var h = c.h, box = h("div.tb.tset");
    if (d.gone) { box.appendChild(h("div.empty", { text: d.gone })); return box; }
    box.appendChild(sec(h, d.head, followRows(d, c)));
    return box;
  }

  P.tabs.settings = function (d, c) {
    if (d.none !== undefined) { return c.h("div.tb"); }
    return d.role === "author" ? author(d, c) : follower(d, c);
  };

  /* ---- sheets of their own: Posts, History, a pick ---- */
  function lines(h, rows, row) {
    var list = h("div.tlist.tsheet");
    rows.forEach(function (x) { list.appendChild(row(x)); });
    return list;
  }
  P.sheets = P.sheets || {};
  P.sheets.posts = function (sh, body, c) {
    var h = c.h, box = body.querySelector("input");
    body.classList.add("wide");
    if (box) {
      var count = h("div.muted.sm", { style: "text-align:right;margin:-6px 0 6px" });
      var counted = function () { count.textContent = box.value.length + " / " + (sh.fields[0].max || 200); sh.fields[0].value = box.value; };
      box.addEventListener("input", counted);
      counted();
      box.parentNode.appendChild(count);
    }
    if (sh.rows.length) {
      body.appendChild(lines(h, sh.rows, function (x) {
        return h("div.tli", {}, [h("b", { text: x.who }), h("span.grow", { text: x.text, title: x.text }), h("span.muted.sm", { text: x.ago }),
          x.remove ? c.btn("Remove it", function () { run(c.send, "unpost", { id: x.id }); }, "t bad") : null]);
      }));
    }
  };
  P.sheets.history = function (sh, body, c) {
    var h = c.h;
    body.classList.add("wide");
    if (sh.rows.length) {
      body.appendChild(lines(h, sh.rows, function (x) {
        return h("div.tli", {}, [h("b", { text: x.who }), h("span.grow", { text: x.text, title: x.text }), h("span.muted.sm", { text: x.ago })]);
      }));
    }
  };
  P.sheets.pick = function (sh, body, c) {
    var h = c.h, box = h("div.tpick", { role: "radiogroup", "aria-label": sh.title });
    function draw() {
      box.textContent = "";
      sh.options.forEach(function (o) {
        var on = sh.args.uid === o.v;
        box.appendChild(h("div.opt" + (on ? ".on" : ""), { role: "radio", tabindex: "0", "aria-checked": on ? "true" : "false",
          onclick: function () { sh.args.uid = o.v; draw(); },
          ondblclick: function () { sh.args.uid = o.v; c.close(); run(c.send, sh.args.name, { uid: o.v }); },
          onkeydown: function (e) { if (e.key === " ") { e.preventDefault(); sh.args.uid = o.v; draw(); } } },
          [h("span.rd"), h("b", { text: o.label })]));
      });
    }
    draw();
    body.appendChild(box);
  };
})();
