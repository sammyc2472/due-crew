/* New plan, in the window's place of the tabs (webnew.py): a resource at
   my pace, someone's plan, or start empty. Every name set as text. */
(function () {
  "use strict";
  var DAY1 = ["M", "T", "W", "T", "F", "S", "S"], DAYN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  var laid = "";  // 3.9.6: the path last laid out; drawn again the same, it doesn't lay itself out again

  /* 3.9.6, day one (Sam's pick): the plan as the board's path will draw it, set by set, the first
     outlined (where I start), its exam a diamond at the end; its sets come in one after another
     when the plan changes shape (new.css, nothing with Reduce motion). No Pip in the plan window. */
  function path(h, p) {
    var key = [p.n, p.first, p.end].join("|"), fresh = key !== laid, n = Math.min(400, p.n);
    laid = key;
    var step = Math.min(0.045, 1 / n), box = h("div.npath" + (fresh ? ".jin" : "") + (n > 120 ? ".g0" : n > 60 ? ".g1" : n > 30 ? ".g2" : ""),
      { role: "img", "aria-label": n + " set" + (n === 1 ? "" : "s") + (p.event && p.end ? ", then " + p.end : "") });
    for (var i = 0; i < n; i++) { box.appendChild(h("i", { style: "--d:" + (0.12 + i * step).toFixed(3) + "s" })); }
    if (p.event) { box.appendChild(h("em", { style: "--d:" + (0.12 + n * step).toFixed(3) + "s" })); }
    return [box, h("div.nppl", { style: "--d:" + (0.12 + n * step).toFixed(3) + "s" }, [h("span", { text: p.first || "" }), h("span", { text: p.end || "" })])];
  }

  dcPlan.newPlan = function (n, k) {
    var h = k.h, btn = k.btn, send = k.send;
    var set = function (key, value) { send("new_set", { key: key, value: value }); };
    var box = h("div.newp", { "data-step": n.step });

    function head(title) {
      return h("div.nhead", {}, [n.step !== "pick" ? btn("‹ Back", function () { send("new_step", { step: "pick" }); }, "t") : null,
        h("h2", { text: title })]);
    }
    function row(label, ctl) { return h("div.fl", {}, [h("span", { text: label }), ctl]); }
    function seg(opts, on, fn, label) {
      var s = h("div.seg", { role: "group", "aria-label": label });
      opts.forEach(function (o) {
        s.appendChild(h("button", { type: "button", text: o[1], cls: o[0] === on ? "on" : "", "aria-pressed": o[0] === on ? "true" : "false",
          onclick: function () { if (o[0] !== on) { fn(o[0]); } } }));
      });
      return s;
    }
    function deckSelect() {
      var sel = h("select.in", { "aria-label": "Deck", onchange: function () { set("deck", +this.value); }, disabled: n.busy });
      n.decks.forEach(function (d) { var o = h("option", { value: d.id, text: d.label }); if (d.id === n.deck) { o.selected = true; } sel.appendChild(o); });
      return sel;
    }
    function text(key, value, hint, keep, max) {
      var i = h("input.in", { type: "text", placeholder: hint || "", maxlength: max || 60, "data-keep": keep, disabled: n.busy });
      i.value = value || "";
      i.addEventListener("change", function () { set(key, this.value); });
      return i;
    }
    function date(key, value, keep) {
      var i = k.dateInput(value, function (v) { if (v) { set(key, v); } }, keep);
      i.min = n.today;
      return i;
    }
    function lesson() {
      return row("Today's set", seg([["deck", "In " + (n.deckName || "your deck")], ["own", "Its own deck"]], n.lesson,
        function (v) { set("lesson", v); }, "Today's set"));
    }
    function makeRow(nameInput, nameHint, inFoot) {
      var later = btn("Make it, start later", go(false)), start = btn("Start it", go(true), "pri");
      function ok() {
        var v = (nameInput.value || nameHint || "").trim();
        later.disabled = start.disabled = !v || n.busy || (n.step === "resource" && !(n.resource || {}).ok);
      }
      function go(st) {
        return function () {
          if ((nameInput.value || "") !== (n.name || "")) { set("name", nameInput.value); }
          send("new_make", { start: st });
        };
      }
      nameInput.addEventListener("input", ok);
      ok();
      return h("div.nfoot", {}, [inFoot ? h("div.row.grow", {}, [nameInput, h("span.muted.sm", { text: "· just you" })]) : h("div.grow"),
        later, start]);
    }

    if (n.step === "pick") {
      box.appendChild(head("New plan"));
      [["resource", "A resource, at my pace", "Chapters of something in your deck, in order."],
        ["someone", "Someone's plan", "A code, or the library."]].filter(function (o) {
        return !n.ways || n.ways.indexOf(o[0]) >= 0;  /* n.ways: the ways this host has (duecrew.com's); Anki's view has every one */
      }).forEach(function (o) {
        box.appendChild(h("div.opt", { tabindex: 0, role: "button", onclick: function () { send("new_step", { step: o[0] }); },
          onkeydown: function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); send("new_step", { step: o[0] }); } } },
          [h("span.rd"), h("span", {}, [h("b", { text: o[1] }), h("span.m", { text: o[2] })])]));
      });
      box.appendChild(h("div.row.sp", { style: "margin-top:10px" }, [btn("Start empty", function () { send("new_step", { step: "empty" }); }, "t"),
        btn("Cancel", function () { send("new_cancel"); })]));
    }

    if (n.step === "someone") {
      box.appendChild(head("Someone's plan"));
      var code = h("input.in", { type: "text", placeholder: "Their code", maxlength: 40, "data-keep": "newcode", style: "width:16em" });
      code.value = n.code || "";
      var follow = btn("Follow…", function () { send("new_follow", { code: code.value }); }, "pri");
      code.addEventListener("input", function () { follow.disabled = !code.value.trim(); });
      code.addEventListener("keydown", function (e) { if (e.key === "Enter" && code.value.trim()) { send("new_follow", { code: code.value }); } });
      follow.disabled = !code.value.trim();
      box.appendChild(h("div.row", {}, [code, follow]));
      box.appendChild(h("div.row", { style: "margin-top:14px" }, [h("span.muted", { text: "Or find one in the library." }),
        btn("The library on duecrew.com ›", function () { send("new_library"); }, "t")]));
    }

    if (n.step === "empty") {
      box.appendChild(head("Start empty"));
      var nm = text("name", n.name, "MS2 Block 2", "newname");
      box.appendChild(row("Name", nm));
      box.appendChild(row("Deck", deckSelect()));
      box.appendChild(row("Ends with", h("div.row", {}, [text("end_name", n.endName, "Block 2 exam (or leave it empty)", "newend"),
        date("end_day", n.endDay, "newendday")])));
      if (n.lesson) { box.appendChild(lesson()); }  /* no Today's set where there's no Anki (duecrew.com) */
      box.appendChild(makeRow(nm, ""));
    }

    if (n.step === "resource") {
      var r = n.resource || {};
      box.appendChild(head("A resource, at my pace"));
      box.appendChild(row("Deck", deckSelect()));
      if (r.empty || !(r.parts || []).length) {
        box.appendChild(h("p.muted", { text: r.empty || "Reading the deck…" }));
      } else {
        var parts = h("div.parts", { role: "radiogroup", "aria-label": "Which part" });
        r.parts.forEach(function (p) {
          parts.appendChild(h("div.opt.part" + (p.on ? ".on" : ""), { role: "radio", tabindex: 0, "aria-checked": p.on ? "true" : "false",
            onclick: function () { if (!p.on) { set("res", p.path); } },
            onkeydown: function (e) { if ((e.key === "Enter" || e.key === " ") && !p.on) { e.preventDefault(); set("res", p.path); } } },
            [h("span.rd"), h("span.prow", {}, [h("b", { text: p.name }), h("span.m", { text: p.sub }), h("span.m.n", { text: p.cards.toLocaleString() })])]));
        });
        box.appendChild(row("Which part", parts));
        if ((r.only || []).length) {
          var only = h("select.in", { "aria-label": "Only", onchange: function () { set("only", this.value); } });
          only.appendChild(h("option", { value: "", text: "All of it" }));
          r.only.forEach(function (o) {
            var op = h("option", { value: o.path, text: o.label + " · " + o.n.toLocaleString() });
            if (o.path === r.onlyOn) { op.selected = true; }
            only.appendChild(op);
          });
          box.appendChild(row("Only", h("div.row", {}, [only, r.onlyCount ? h("span.muted.sm", { text: r.onlyCount }) : null])));
        }
        var pace = [seg([["daily", "About " + r.daily + " new a day"], ["by", "Finish by…"], ["ready", "When I'm ready"]], r.pace,
          function (v) { set("pace", v); }, "Pace")];
        if (r.pace !== "by") {
          var num = h("input.in.num", { type: "number", min: 1, max: 500, "aria-label": "New cards a day", "data-keep": "newdaily", style: "width:5.5em" });
          num.value = r.daily;
          num.addEventListener("change", function () { set("daily", this.value); });
          pace.push(h("div.row", {}, [h("span.muted.sm", { text: "About" }), num, h("span.muted.sm", { text: "new a day" + (r.pace === "ready" ? ", to lay it out; each opens when you're ready" : "") })]));
        } else {
          pace.push(h("div.row", {}, [date("by", r.by, "newby"), text("end_name", n.endName, "The exam (or leave it empty)", "newexam"),
            h("span.muted.sm", { text: "about " + r.daily + " new a day" })]));
        }
        box.appendChild(row("Pace", h("div.col", {}, pace)));
        var days = h("div.days", { role: "group", "aria-label": "Study days" });
        r.days.forEach(function (on, i) {
          days.appendChild(h("button.dy" + (on ? ".on" : ""), { type: "button", text: DAY1[i], title: DAYN[i], "aria-pressed": on ? "true" : "false",
            onclick: function () { set("day", i); } }));
        });
        box.appendChild(row("Study days", days));
        box.appendChild(row("Starts", date("starts", r.starts, "newstarts")));
        box.appendChild(lesson());
        var sum = h("div.nsum");
        if (r.summary) { sum.appendChild(h("div", {}, [h("b", { text: r.summary })])); }
        if (r.note) { sum.appendChild(h("div.muted.sm", { text: r.note })); }
        if (r.said) { sum.appendChild(h("div.bad", { text: r.said })); }
        if (r.path && r.path.n) { path(h, r.path).forEach(function (el) { sum.appendChild(el); }); }
        (r.dates || []).forEach(function (u) {
          sum.appendChild(h("div.nl", {}, [h("span.muted", { text: String(u.n) }), h("span", { text: u.name }), h("span.muted", { text: u.when }),
            h("span.muted.n", { text: u.cards.toLocaleString() })]));
        });
        if (r.more) { sum.appendChild(h("div.muted.sm", { text: "… " + r.more.toLocaleString() + " more" })); }
        box.appendChild(sum);
      }
      box.appendChild(makeRow(text("name", n.name, r.name || "Name", "newname"), r.name || "", true));
    }
    if (n.said) { box.appendChild(h("div.nsaid", { text: n.said, role: "status" })); }
    return box;
  };
})();
