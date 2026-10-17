/* 3.9.0: how a cheer lands (Sam's picks, "Cheers, everywhere"): a show over
   the whole Decks screen, a different one each time (shows.py keeps the bag).
   board.flurry_js starts one: DCShow.play(kind, D), with
   D = {senders: [{name, emoji, note, a: [light, dark], hello, jump, cheer, idle}],
        dark, line, amb, mut, accent, accentInk, sevcss}.
   Pips are sev.py's own markup (a name only in its label, escaped there);
   every name, emoji and note goes in as textContent. Nothing here sends
   anything; a click anywhere (but on a present or a bubble) or Esc ends it.
   Reduce motion never gets here: flurry_js stands the Pips in its banner. */
(function () {
  if (window.DCShow) { return; }
  var CSS = [
    "#dc-show{position:fixed;inset:0;z-index:68;pointer-events:none;overflow:hidden}",
    "#dc-show *{box-sizing:border-box}",
    "#dc-show[aria-hidden=true] *{pointer-events:none!important}",
    ".dcs-pp{position:absolute;display:block;line-height:0}",
    ".dcs-pp svg{width:100%;height:100%;display:block;overflow:visible}",
    ".dcs-pt{position:absolute;left:0;top:0;line-height:1;pointer-events:none;will-change:transform}",
    ".dcs-cf{position:absolute;width:9px;height:6px;border-radius:1.5px;pointer-events:none}",
    ".dcs-flash{position:absolute;border-radius:8px;pointer-events:none}",
    ".dcs-word{position:absolute;font:900 22px -apple-system,'Segoe UI',sans-serif;color:#e2582b;letter-spacing:.02em;text-shadow:0 2px 0 #fff,0 0 12px rgba(255,255,255,.6);pointer-events:none;white-space:nowrap}",
    ".dcs-rk{position:absolute;width:6px;height:6px;border-radius:50%;background:#ffd66b;box-shadow:0 0 10px 3px #ffd66b}",
    ".dcs-rk::after{content:'';position:absolute;left:1.5px;top:6px;width:3px;height:34px;border-radius:2px;background:linear-gradient(#ffd66b,transparent)}",
    ".dcs-lbl{position:absolute;font:800 15px -apple-system,'Segoe UI',sans-serif;transform:translate(-50%,-50%);pointer-events:none;white-space:nowrap}",
    ".dcs-dim{position:absolute;inset:0;background:#0b0e1c;opacity:0;pointer-events:none}",
    ".dcs-thing{position:absolute;pointer-events:none}",
    ".dcs-thing svg{display:block;overflow:visible}",
    ".dcs-click{pointer-events:auto;cursor:pointer}",
    ".dcs-wait{animation:dcs-jig 1.8s ease-in-out infinite;transform-origin:50% 100%}",
    "@keyframes dcs-jig{0%,70%,100%{transform:rotate(0)}76%{transform:rotate(-7deg)}82%{transform:rotate(6deg)}88%{transform:rotate(-4deg)}94%{transform:rotate(2deg)}}",
    ".dcs-hint{position:absolute;font:800 13px -apple-system,'Segoe UI',sans-serif;border-radius:99px;padding:3px 11px;white-space:nowrap;pointer-events:none;box-shadow:0 4px 12px rgba(0,0,0,.2)}",
    ".dcs-tag{position:absolute;background:#fff8e6;color:#3a3220;border:1px solid #e8d9a8;border-radius:7px;padding:6px 11px;font:14px/1.35 -apple-system,'Segoe UI',sans-serif;box-shadow:0 8px 20px rgba(0,0,0,.2);max-width:260px;pointer-events:none;transform-origin:50% 0;text-align:left}",
    ".dcs-tag b{display:block;font-size:11.5px;color:#8a7a4a}",
    ".dcs-bub{position:absolute;border-radius:50%;pointer-events:auto;cursor:pointer;background:radial-gradient(circle at 32% 28%,rgba(255,255,255,.95) 0 6%,rgba(255,255,255,.35) 12%,rgba(160,200,255,.18) 45%,rgba(120,170,255,.28) 72%,rgba(120,170,255,.55) 100%);box-shadow:inset 0 0 14px rgba(120,170,255,.45),0 4px 14px rgba(0,0,0,.08)}",
    ".dcs-bub i{position:absolute;right:4px;bottom:6px;font-style:normal;font-size:22px;line-height:1}",
    ".dcs-ring{position:absolute;border:2px solid rgba(120,170,255,.8);border-radius:50%;pointer-events:none}",
    ".dcs-light{position:absolute;border-radius:50%;pointer-events:none;mix-blend-mode:screen;filter:blur(2px)}"
  ].join("\n");

  var R = Math.random, T = [], LOOPS = [], ov = null, D = null, onKey = null, onDown = null;
  function W() { return window.innerWidth; } function H() { return window.innerHeight; }
  function box(el) { var r = el.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width, h: r.height }; }
  function myRow() {  // my row on the board, if it's on screen
    var r = document.querySelector("#due-crew tr.you"), b = r && box(r);
    return b && b.h && b.y > 0 && b.y + b.h < H() ? b : null;
  }
  function rowOr() { return myRow() || { x: W() * 0.2, y: H() * 0.66, w: W() * 0.6, h: 30, none: true }; }
  function acc(a) { return a[D.dark ? 1 : 0]; }
  function later(ms, fn) { T.push(setTimeout(function () { if (ov) { fn(); } }, ms)); }
  function loop(fn) { var o = { on: true }; LOOPS.push(o); (function f(t) { if (!o.on || !ov) { return; } if (fn(t) !== false) { requestAnimationFrame(f); } })(performance.now()); return o; }
  function add(tag, cls, css, parent) { var e = document.createElement(tag); if (cls) { e.className = cls; } if (css) { e.style.cssText = css; } (parent || ov).appendChild(e); return e; }
  function pip(svg, a, size, css, parent) {
    var p = add("span", "dcs-pp", "width:" + size + "px;height:" + size + "px;" + (css || ""), parent);
    p.innerHTML = svg; p.setAttribute("aria-hidden", "true");
    p.style.setProperty("--sv-a", acc(a)); p.style.setProperty("--sv-line", D.line); p.style.setProperty("--sv-amb", D.amb); p.style.setProperty("--sv-mut", D.mut);
    return p;
  }
  function gone(an, el) { an.onfinish = function () { el.remove(); }; return an; }
  function txt(x, y, s, cls, css) { var e = add("span", cls || "dcs-word", "left:" + x + "px;top:" + y + "px;" + (css || "")); e.textContent = s; return e; }
  function noteOf(s) { return s.note ? "“" + s.note + "”" : "A cheer for today"; }
  var CONF = ["#e2582b", "#f2b33d", "#3d8be0", "#7b5cd6", "#2e9d5b", "#e2589c", "#20b2aa"];

  function fly(x, y, t, o) {
    var p;
    if (t) { p = add("span", "dcs-pt", "left:" + x + "px;top:" + y + "px;font-size:" + o.size + "px"); p.textContent = t; }
    else { p = add("span", "dcs-cf", "left:" + x + "px;top:" + y + "px;background:" + CONF[Math.floor(R() * CONF.length)]); }
    var ks = [];
    for (var i = 0; i <= 12; i++) {
      var u = i / 12;
      ks.push({ transform: "translate(-50%,-50%) translate(" + (o.vx * u) + "px," + (o.vy * u + 0.5 * o.g * u * u) + "px) rotate(" + (o.rot * u) + "deg) scale(" + (o.grow ? 0.4 + 0.6 * Math.min(1, u * 4) : 1) + ")",
                opacity: u > 0.8 ? (1 - u) / 0.2 : 1 });
    }
    gone(p.animate(ks, { duration: o.dur, delay: o.delay || 0, easing: "linear", fill: "both" }), p);
  }
  function burst(x, y, emojis, n, o) {
    for (var i = 0; i < n; i++) {
      var conf = o.conf && i % 3 === 2, ang = o.ring ? (i / n) * Math.PI * 2 : 0;
      fly(x, y, conf ? null : emojis[i % emojis.length], {
        vx: o.ring ? Math.cos(ang) * o.spread : (R() - 0.5) * o.spread + (o.dx || 0),
        vy: o.ring ? Math.sin(ang) * o.spread : -(o.up * (0.45 + R() * 0.75)),
        g: o.g, dur: o.dur * (0.8 + R() * 0.4), rot: (R() - 0.5) * 540, size: o.size * (0.8 + R() * 0.5),
        delay: o.delay || 0, grow: o.grow });
    }
  }
  function rain(emojis, n, dur, delay, o) {
    o = o || {};
    for (var i = 0; i < n; i++) {
      var p = add("span", "dcs-pt", "left:" + (R() * W()) + "px;top:-40px;font-size:" + ((o.size || 20) + R() * 14) + "px");
      p.textContent = emojis[i % emojis.length];
      var end = o.settle ? H() - 14 - R() * 26 : H() + 60, sway = (R() - 0.5) * (o.sway ? 160 : 80), turn = (R() - 0.5) * 200;
      var ks = o.settle ? [{ transform: "translate(0,0) rotate(0)" }, { transform: "translate(" + sway + "px," + (end + 40) + "px) rotate(" + turn + "deg)", offset: 0.8 },
                           { transform: "translate(" + sway + "px," + (end + 40) + "px) rotate(" + turn + "deg)", opacity: 1, offset: 0.93 }, { transform: "translate(" + sway + "px," + (end + 40) + "px) rotate(" + turn + "deg)", opacity: 0 }]
                         : [{ transform: "translate(0,0) rotate(0)" }, { transform: "translate(" + sway + "px," + end + "px) rotate(" + (turn * 2) + "deg)" }];
      gone(p.animate(ks, { duration: dur * (0.7 + R() * 0.6), delay: (delay || 0) + R() * dur * 0.5, easing: o.settle ? "ease-out" : "cubic-bezier(.3,.1,.7,1)", fill: "both" }), p);
    }
  }
  function flash(s) {  // my row lights up, if it's on screen
    var r = myRow(); if (!r) { return; }
    var f = add("div", "dcs-flash", "left:" + (r.x - 4) + "px;top:" + (r.y - 2) + "px;width:" + (r.w + 8) + "px;height:" + (r.h + 4) + "px;background:" + acc(s.a));
    gone(f.animate([{ opacity: 0 }, { opacity: 0.35 }, { opacity: 0 }], { duration: 1400, easing: "ease-out", fill: "both" }), f);
    var row = document.querySelector("#due-crew tr.you");
    if (row) { row.querySelectorAll("td").forEach(function (td) { td.animate([{ transform: "none" }, { transform: "translateY(-4px) scale(1.03)" }, { transform: "none" }], { duration: 520, easing: "ease-out" }); }); }
  }
  function dim(op, total) { var d = add("div", "dcs-dim"); gone(d.animate([{ opacity: 0 }, { opacity: op, offset: 0.1 }, { opacity: op, offset: 0.86 }, { opacity: 0 }], { duration: total, fill: "both" }), d); }
  function shake(px, dur) {
    document.body.animate([{ transform: "none" }, { transform: "translate(" + px + "px," + (-px / 2) + "px) rotate(.4deg)" }, { transform: "translate(" + (-px) + "px," + (px / 2) + "px) rotate(-.4deg)" },
                           { transform: "translate(" + (px / 2) + "px,0)" }, { transform: "none" }], { duration: dur || 450, easing: "ease-out" });
  }
  function popIn(el, d) { el.animate([{ transform: "scale(0)", opacity: 0 }, { transform: "scale(1.12)", opacity: 1, offset: 0.7 }, { transform: "scale(1)" }], { duration: d || 420, easing: "ease-out", fill: "both" }); }
  function fadeOut(el, delay, d) { later(delay, function () { gone(el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: d || 500, fill: "both" }), el); }); }
  function tag(x, y, s) {
    var t = add("div", "dcs-tag", "left:" + x + "px;top:" + y + "px;"), b = document.createElement("b");
    b.textContent = "From " + s.name + " " + s.emoji; t.appendChild(b);
    var n = document.createElement("span"); n.textContent = noteOf(s); t.appendChild(n);
    t.animate([{ opacity: 0, transform: "rotate(-4deg) scaleY(.2)" }, { opacity: 1, transform: "rotate(-4deg) scaleY(1)" }], { duration: 450, easing: "ease-out", fill: "both" });
    return t;
  }
  function svgEl(html, x, y, w, h) { var t = add("div", "dcs-thing", "left:" + x + "px;top:" + y + "px;width:" + w + "px;height:" + h + "px;"); t.innerHTML = html; t.setAttribute("aria-hidden", "true"); return t; }
  function clickable(el, label, fn) {
    el.className += " dcs-click"; el.setAttribute("role", "button"); el.setAttribute("tabindex", "0"); el.setAttribute("aria-label", label); el.title = label;
    el.addEventListener("click", function (e) { e.stopPropagation(); fn(); });
    el.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); fn(); } });
  }

  var CANNON = '<svg viewBox="0 0 58 38" width="58" height="38"><rect x="4" y="8" width="42" height="16" rx="8" fill="#4a4f57"/><rect x="42" y="5" width="10" height="22" rx="4" fill="#33373d"/><circle cx="17" cy="28" r="9" fill="#7a5a3a"/><circle cx="17" cy="28" r="3" fill="#c9a77a"/></svg>';
  function giftSvg(c, w) {
    return '<svg viewBox="0 0 58 64" width="' + w + '" height="' + (w * 64 / 58) + '"><g class="dcs-lid"><rect x="0" y="8" width="58" height="14" rx="3" fill="' + c + '"/><rect x="25" y="8" width="8" height="14" fill="#fff"/>' +
      '<path d="M29 9 C 18 -2 10 6 22 10 Z M29 9 C 40 -2 48 6 36 10 Z" fill="#fff" stroke="' + c + '" stroke-width="1.5"/></g><rect x="3" y="22" width="52" height="42" rx="3" fill="' + c + '" opacity=".88"/><rect x="25" y="22" width="8" height="42" fill="#fff"/></svg>';
  }
  function hexOk(c) { return /^#[0-9a-f]{3,8}$/i.test(c) ? c : "#7b5cd6"; }  // a colour from the board's accent pairs, never markup

  var SHOW = {};
  SHOW.cannon = function (list) {  // their Pips roll cannons into the bottom corners; it rains on everything
    list.forEach(function (s, i) {
      later(i * 750, function () {
        var right = i % 2 === 1, x0 = right ? W() - 120 : 34, y0 = H() - 100;
        var p = pip(s.hello, s.a, 78, "left:" + x0 + "px;top:" + y0 + "px;" + (right ? "transform:scaleX(-1);" : ""));
        var c = svgEl(CANNON, right ? x0 - 44 : x0 + 60, y0 + 34, 58, 38), ang = right ? 215 : -38;
        c.style.transformOrigin = "20% 70%"; c.style.transform = "rotate(" + ang + "deg)";
        [p, c].forEach(function (e) { gone(e.animate([{ translate: "0 130px" }, { translate: "0 0", offset: 0.12 }, { translate: "0 0", offset: 0.85 }, { translate: "0 130px" }], { duration: 2900, easing: "ease-in-out", fill: "both" }), e); });
        later(520, function () {
          c.animate([{ transform: "rotate(" + ang + "deg)" }, { transform: "rotate(" + ang + "deg) translateX(-10px)" }, { transform: "rotate(" + ang + "deg)" }], { duration: 260 });
          burst(right ? x0 - 30 : x0 + 112, y0 + 6, [s.emoji], 48, { spread: W() * 0.9, dx: right ? -W() * 0.32 : W() * 0.32, up: H() * 1.15, g: H() * 1.3, dur: 1800, size: 28, conf: true });
          later(260, function () { rain([s.emoji], 42, 2500, 0); });
          later(900, function () { flash(s); });
        });
      });
    });
    return 1000 + list.length * 750 + 3200;
  };
  SHOW.pinata = function (list) {  // a whack a cheer; the last one breaks it, with no word (Sam)
    var cx = W() / 2, top = Math.min(110, H() * 0.16);
    var hang = svgEl('<svg width="120" height="' + (top + 90) + '" style="overflow:visible"><line x1="60" y1="0" x2="60" y2="' + top + '" stroke="#8a7a5a" stroke-width="2.5"/>' +
      '<g transform="translate(60 ' + (top + 46) + ') scale(1.45)"><polygon points="0,-36 9,-12 34,-11 14,4 21,29 0,15 -21,29 -14,4 -34,-11 -9,-12" fill="#f2b33d" stroke="#d9822b" stroke-width="2"/>' +
      '<path d="M-26 -6 H26 M-20 8 H20 M-12 20 H12" stroke="#e2589c" stroke-width="4" stroke-linecap="round"/><path d="M-24 1 H24 M-16 14 H16" stroke="#3d8be0" stroke-width="3" stroke-linecap="round"/>' +
      '<circle cx="-6" cy="-10" r="2.5" fill="#33373d"/><circle cx="6" cy="-10" r="2.5" fill="#33373d"/></g></svg>', cx - 60, 0, 120, top + 90);
    hang.style.transformOrigin = "50% 0";
    hang.animate([{ transform: "translateY(-" + (top + 110) + "px) rotate(0)" }, { transform: "translateY(0) rotate(9deg)", offset: 0.5 }, { transform: "translateY(0) rotate(-6deg)", offset: 0.75 }, { transform: "translateY(0) rotate(0)" }], { duration: 950, easing: "ease-out", fill: "both" });
    list.forEach(function (s, i) {
      later(1000 + i * 850, function () {
        var left = i % 2 === 0, last = i === list.length - 1, px = left ? cx - 150 : cx + 70, py = top + 50;
        var p = pip(s.jump, s.a, 76, "left:" + px + "px;top:" + py + "px;" + (left ? "" : "transform:scaleX(-1);"));
        gone(p.animate([{ opacity: 0, translate: "0 40px" }, { opacity: 1, translate: "0 0", offset: 0.2 }, { translate: "0 -24px", offset: 0.45 }, { translate: "0 0", offset: 0.65 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }], { duration: 1300, fill: "both" }), p);
        later(520, function () {
          hang.animate([{ transform: "rotate(0)" }, { transform: "rotate(" + (left ? 28 : -28) + "deg)" }, { transform: "rotate(" + (left ? -14 : 14) + "deg)" }, { transform: "rotate(0)" }], { duration: 700, easing: "ease-out" });
          if (!last) {
            var t = txt(cx + (left ? -120 : 50), top + 4, "THWACK!");
            gone(t.animate([{ opacity: 0, transform: "scale(.4) rotate(-8deg)" }, { opacity: 1, transform: "scale(1.2) rotate(-8deg)", offset: 0.3 }, { opacity: 0, transform: "scale(1) rotate(-8deg) translateY(-14px)" }], { duration: 800, fill: "both" }), t);
          } else {
            later(160, function () {
              gone(hang.animate([{ opacity: 1 }, { opacity: 0, transform: "translateY(-30px) scale(1.4)" }], { duration: 300, fill: "both" }), hang);
              var ems = list.map(function (q) { return q.emoji; }).concat(["\u{1F36C}", "\u{1F36D}", "\u{1F36C}", "\u{1F36B}"]);
              burst(cx, top + 46, ems, 54, { spread: W() * 0.9, up: 300, g: 900, dur: 1900, size: 26, conf: true });
              rain(ems, 36, 2600, 300);
              later(700, function () { flash(s); });
            });
          }
        });
      });
    });
    return 1000 + list.length * 850 + 3600;
  };
  SHOW.fireworks = function (list) {  // the screen dims; each bursts in the sender's emoji and colour (no name in the middle: Sam)
    var shots = list.length === 1 ? [list[0], list[0], list[0]] : list.concat([list[0], list[list.length - 1]]);
    dim(0.6, 900 + shots.length * 820 + 1600);
    shots.forEach(function (s, i) {
      later(400 + i * 820, function () {
        var x = W() * (0.14 + 0.72 * ((i * 0.41 + R() * 0.2) % 1)), y = H() * (0.12 + R() * 0.3), big = i === shots.length - 1;
        var rk = add("span", "dcs-rk", "left:" + x + "px;top:" + H() + "px;");
        rk.animate([{ transform: "translateY(0)" }, { transform: "translateY(" + (y - H()) + "px)" }], { duration: 800, easing: "cubic-bezier(.2,.7,.4,1)", fill: "both" }).onfinish = function () {
          rk.remove(); if (!ov) { return; }
          burst(x, y, [s.emoji], big ? 20 : 14, { ring: true, spread: big ? 210 : 150, g: 80, dur: 1600, size: big ? 30 : 24, grow: true });
          for (var k = 0; k < 30; k++) {
            var c = hexOk(acc(s.a)), sp = add("span", "", "position:absolute;left:" + x + "px;top:" + y + "px;width:4px;height:4px;border-radius:50%;background:" + c + ";box-shadow:0 0 8px " + c);
            var a2 = R() * Math.PI * 2, d = (big ? 170 : 120) * (0.5 + R() * 0.6);
            gone(sp.animate([{ transform: "translate(0,0)", opacity: 1 }, { transform: "translate(" + Math.cos(a2) * d + "px," + (Math.sin(a2) * d + 50) + "px)", opacity: 0 }], { duration: 1200 + R() * 500, easing: "cubic-bezier(.2,.8,.4,1)", fill: "both" }), sp);
          }
        };
      });
    });
    later(400 + shots.length * 820 + 400, function () { flash(list[0]); });
    return 900 + shots.length * 820 + 2000;
  };
  SHOW.gift = function (list) {  // a present each, to open; one you don't opens itself
    var n = list.length, gw = 116, gh = gw * 64 / 58, gy = Math.max(150, Math.min(230, H() * 0.26)), opened = 0;  // clear of the banner, room to spring
    list.forEach(function (s, i) {
      later(i * 380, function () {
        var gx = W() / 2 - gw / 2 + (i - (n - 1) / 2) * 170, c = hexOk(acc(s.a)), done = false;
        var g = add("div", "dcs-thing", "left:" + gx + "px;top:" + gy + "px;width:" + gw + "px;height:" + gh + "px;");
        g.innerHTML = giftSvg(c, gw);
        g.animate([{ transform: "translateY(-" + (gy + 160) + "px)" }, { transform: "translateY(0)", offset: 0.6 }, { transform: "translateY(-22px) scaleY(1.05)", offset: 0.78 }, { transform: "translateY(0)" }], { duration: 750, easing: "ease-in", fill: "both" })
          .onfinish = function () { if (!done) { g.classList.add("dcs-wait"); } };
        if (i === n - 1) {
          var h = add("span", "dcs-hint", "left:" + (W() / 2 - 44) + "px;top:" + (gy + gh + 14) + "px;background:" + D.accent + ";color:" + D.accentInk + ";");
          h.textContent = n > 1 ? "Open them" : "Open me";
          h.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 400, delay: 800, fill: "both" });
        }
        function open() {
          if (done || !ov) { return; } done = true; opened += 1;
          g.classList.remove("dcs-wait"); g.classList.remove("dcs-click"); g.style.pointerEvents = "none";
          if (opened === n) { ov.querySelectorAll(".dcs-hint").forEach(function (x) { x.remove(); }); }
          var lid = g.querySelector(".dcs-lid");
          if (lid) { lid.animate([{ transform: "none" }, { transform: "translate(" + (R() > 0.5 ? 60 : -60) + "px,-110px) rotate(" + (R() > 0.5 ? 40 : -40) + "deg)", opacity: 0 }], { duration: 700, easing: "cubic-bezier(.2,.8,.4,1)", fill: "both" }); }
          var p = pip(s.jump, s.a, 110, "left:" + (gx + 3) + "px;top:" + (gy + 10) + "px;");
          p.animate([{ transform: "translateY(20px) scaleY(.6)" }, { transform: "translateY(-100px) scaleY(1.12)", offset: 0.35 }, { transform: "translateY(-66px) scaleY(.94)", offset: 0.55 }, { transform: "translateY(-82px) scaleY(1.03)", offset: 0.75 }, { transform: "translateY(-78px)" }], { duration: 950, easing: "ease-out", fill: "both" });
          burst(gx + gw / 2, gy + 10, [s.emoji], 44, { spread: W() * 0.7, up: 420, g: 900, dur: 1700, size: 26, conf: true });
          later(200, function () { rain([s.emoji], 28, 2400, 0); });
          flash(s);
          fadeOut(tag(gx + gw / 2 - 120, gy + gh + 16, s), 4200);
          fadeOut(p, 4200); fadeOut(g, 4200);
          if (opened === n) { end(5200); }
        }
        clickable(g, "Open " + s.name + "’s cheer", open);
        later(10000 + i * 600, open);  // nobody opened it: it opens itself
      });
    });
    return 0;  // it ends when they're all open
  };
  SHOW.bubbles = function (list) {  // a Pip in each; pop one, or it pops at the top
    var all = list.map(function (s) { return { s: s }; });
    for (var e = 0; e < 6; e++) { all.push({ s: list[e % list.length], empty: true }); }
    all.forEach(function (o, i) {
      later(i * 360, function () {
        var s = o.s, sz = o.empty ? 34 + R() * 26 : 104, x = W() * (0.08 + 0.84 * ((i * 0.37 + R() * 0.15) % 1));
        var b = add("div", "dcs-bub", "left:" + x + "px;top:" + H() + "px;width:" + sz + "px;height:" + sz + "px;");
        if (!o.empty) { pip(s.hello, s.a, 66, "left:19px;top:16px;", b); var em = add("i", "", "", b); em.textContent = s.emoji; }
        else { b.style.pointerEvents = "none"; }
        var ks = [], Hd = H();
        for (var k = 0; k <= 18; k++) { var t = k / 18; ks.push({ transform: "translate(" + (Math.sin(t * Math.PI * 3 + i) * 30) + "px," + (-(Hd + 140) * t) + "px)" }); }
        var an = b.animate(ks, { duration: (o.empty ? 6500 : 11000) + R() * 2000, easing: "linear", fill: "both" }), popped = false;
        function pop() {
          if (popped || !ov) { return; } popped = true;
          var bb = box(b), cx = bb.x + bb.w / 2, cy = bb.y + bb.h / 2; an.pause();
          gone(b.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 220, fill: "both" }), b);
          var rg = add("span", "dcs-ring", "left:" + (cx - sz / 2) + "px;top:" + (cy - sz / 2) + "px;width:" + sz + "px;height:" + sz + "px;");
          gone(rg.animate([{ transform: "scale(.8)", opacity: 1 }, { transform: "scale(1.7)", opacity: 0 }], { duration: 450, fill: "both" }), rg);
          if (!o.empty) {
            burst(cx, cy, [s.emoji], 22, { spread: 320, up: 260, g: 520, dur: 1200, size: 22 });
            var nm = txt(cx, cy, s.name + " " + s.emoji, "dcs-lbl", "color:" + D.ink + ";");
            gone(nm.animate([{ opacity: 0 }, { opacity: 1, offset: 0.2 }, { opacity: 0, transform: "translate(-50%,-110%)" }], { duration: 1500, fill: "both" }), nm);
          }
        }
        if (!o.empty) { clickable(b, "Pop " + s.name + "’s cheer", pop); }
        an.onfinish = pop;
      });
    });
    return 14500;
  };
  SHOW.wave = function (list) {  // every deck, then every crewmate, a leap in turn; my row bursts
    var rows = [].slice.call(document.querySelectorAll("tr.deck, #due-crew tbody tr")).filter(function (r) { var b = box(r); return b.h && b.y + b.h > 0 && b.y < H(); });
    rows.sort(function (a, b) { return box(a).y - box(b).y; });
    var mine = document.querySelector("#due-crew tr.you"), burstAt = null;
    rows.forEach(function (row, i) {
      later(i * 110, function () {
        row.querySelectorAll("td").forEach(function (td) { td.animate([{ transform: "none" }, { transform: "translateY(-12px) scale(1.04)", offset: 0.4 }, { transform: "translateY(2px)", offset: 0.75 }, { transform: "none" }], { duration: 520, easing: "ease-out" }); });
        var b = box(row), s = list[i % list.length];
        fly(b.x + b.w - 40 - R() * 60, b.y + b.h / 2, s.emoji, { vx: (R() - 0.5) * 60, vy: -90, g: 60, dur: 900, rot: 90, size: 18 });
        if (row === mine || (!mine && i === rows.length - 1)) { burstAt = b; later(200, function () { finale(b); }); }
      });
    });
    function finale(b) {
      flash(list[0]);
      burst(b.x + b.w * 0.55, b.y + b.h / 2, list.map(function (q) { return q.emoji; }), 34, { spread: 520, up: 340, g: 700, dur: 1500, size: 24, conf: true });
      list.forEach(function (q, j) {
        var p = pip(q.jump, q.a, 64, "left:" + (b.x + b.w - 90 - j * 62) + "px;top:" + (b.y - 64) + "px;");
        gone(p.animate([{ opacity: 0, transform: "translateY(30px)" }, { opacity: 1, transform: "translateY(0)", offset: 0.15 }, { transform: "translateY(-16px)", offset: 0.35 }, { transform: "translateY(0)", offset: 0.55 }, { opacity: 1, offset: 0.85 }, { opacity: 0 }], { duration: 2200, delay: j * 120, fill: "both" }), p);
      });
    }
    if (!rows.length) { later(100, function () { finale(rowOr()); }); }
    return rows.length * 110 + 3200;
  };
  SHOW.balloons = function (list) {  // a bunch in the crew's colours, Pips riding the biggest; they pop at the top
    function balloon(x, c, em, dur, delay, rider) {
      var bw = rider ? 70 : 46, bh = bw * 1.2, n = rider ? 3 : 1, html = "";
      var b = add("div", "dcs-thing", "left:" + x + "px;top:" + (H() + 20) + "px;width:110px;height:" + (rider ? 190 : 120) + "px;");
      for (var q = 0; q < n; q++) {
        var ox = rider ? [-24, 0, 24][q] : 0, oy = rider ? [10, -6, 10][q] : 0, cc = rider ? [c, CONF[(q + 2) % 7], CONF[(q + 4) % 7]][q] : c;
        html += '<ellipse cx="' + (55 + ox) + '" cy="' + (bh / 2 + 10 + oy) + '" rx="' + (bw / 2) + '" ry="' + (bh / 2) + '" fill="' + cc + '"/><ellipse cx="' + (55 + ox - bw / 6) + '" cy="' + (bh / 3 + 10 + oy) + '" rx="' + (bw / 10) + '" ry="' + (bh / 7) + '" fill="#fff" opacity=".45"/>' +
                '<path d="M' + (55 + ox) + ' ' + (bh + 10 + oy) + ' q -6 20 0 ' + (rider ? 52 - oy : 40) + '" stroke="#999" fill="none"/>';
      }
      b.innerHTML = '<svg width="110" height="' + (rider ? 190 : 120) + '" style="overflow:visible">' + html + "</svg>";
      if (rider) { pip(rider.hello, rider.a, 60, "left:25px;top:" + (bh + 46) + "px;", b); }
      else { var e = add("span", "dcs-pt", "left:55px;top:" + (bh + 46) + "px;font-size:20px;transform:translate(-50%,-50%)", b); e.textContent = em; }
      var ks = [], Hd = H();
      for (var k = 0; k <= 14; k++) { var t = k / 14; ks.push({ transform: "translate(" + (Math.sin(t * 5 + x) * 22) + "px," + (-(Hd + 260) * t) + "px)" }); }
      b.animate(ks, { duration: dur, delay: delay, easing: "linear", fill: "both" });
      later(delay + dur * 0.86, function () { var bb = box(b); burst(bb.x + 55, Math.max(20, bb.y + 30), [em], 12, { spread: 240, up: 120, g: 500, dur: 1200, size: 18, conf: true }); b.remove(); });
    }
    for (var i = 0; i < 16; i++) { var s = list[i % list.length]; balloon(W() * (0.02 + 0.9 * R()), i % 3 === 0 ? hexOk(acc(s.a)) : CONF[i % 7], s.emoji, 4200 + R() * 1800, R() * 900, null); }
    list.forEach(function (s, j) { balloon(W() * (0.22 + 0.24 * j), hexOk(acc(s.a)), s.emoji, 6200, 400 + j * 300, s); });
    later(1200, function () { flash(list[0]); });
    return 8600;
  };
  SHOW.rocket = function (list) {  // a countdown on my row, then up through the decks and off the top
    var r = rowOr();
    list.forEach(function (s, i) {
      var x = Math.max(10, r.x + r.w - 120 - i * 90), y = r.y - 110;
      var rk = svgEl('<svg viewBox="0 0 50 110" width="56" height="124"><path d="M25 0 C 45 22 46 60 40 84 L10 84 C 4 60 5 22 25 0 Z" fill="#f4f4f4" stroke="#9aa0aa" stroke-width="2"/>' +
        '<path d="M10 70 L0 98 L12 88 Z M40 70 L50 98 L38 88 Z" fill="' + hexOk(acc(s.a)) + '"/><rect x="14" y="84" width="22" height="8" rx="2" fill="#9aa0aa"/><circle cx="25" cy="38" r="12" fill="#cfe8ff" stroke="#9aa0aa" stroke-width="2"/></svg>', x, y, 56, 124);
      pip(s.idle, s.a, 30, "left:13px;top:26px;", rk);
      popIn(rk, 360);
      if (i === 0) {
        ["3", "2", "1"].forEach(function (c, k) {
          later(500 + k * 420, function () { var t = txt(x - 30, y + 20, c, "dcs-word", "font-size:30px;"); gone(t.animate([{ opacity: 0, transform: "scale(.4)" }, { opacity: 1, transform: "scale(1.2)", offset: 0.3 }, { opacity: 0, transform: "scale(1)" }], { duration: 420, fill: "both" }), t); });
        });
      }
      later(1800 + i * 300, function () {
        shake(3, 300);
        var an = rk.animate([{ transform: "translateY(0)" }, { transform: "translateY(10px)", offset: 0.06 }, { transform: "translateY(-" + (y + 260) + "px)" }], { duration: 1700, easing: "cubic-bezier(.5,0,.8,.6)", fill: "both" });
        var o = loop(function () {
          var bb = box(rk); if (bb.y + bb.h < -40) { rk.remove(); return false; }
          fly(bb.x + bb.w / 2 + (R() - 0.5) * 10, bb.y + bb.h, R() < 0.5 ? s.emoji : null, { vx: (R() - 0.5) * 80, vy: 60 + R() * 80, g: 300, dur: 900, rot: 200, size: 18 });
        });
        an.onfinish = function () { o.on = false; rk.remove(); if (!ov) { return; } var st = txt(x + 10, 30, "✨", "dcs-pt", "font-size:34px;"); gone(st.animate([{ opacity: 0, transform: "scale(.3)" }, { opacity: 1, transform: "scale(1.4)" }, { opacity: 0 }], { duration: 900, fill: "both" }), st); };
      });
    });
    later(2400, function () { flash(list[0]); });
    return 2000 + list.length * 300 + 2600;
  };
  SHOW.stamp = function (list) {  // a giant rubber stamp thumps down, the screen jolts, their emoji and name in ink
    list.forEach(function (s, i) {
      later(i * 650, function () {
        var x = W() * [0.5, 0.27, 0.73][i % 3], y = H() * [0.34, 0.24, 0.42][i % 3], c = hexOk(acc(s.a));
        var st = svgEl('<svg viewBox="0 0 120 150" width="120" height="150"><rect x="44" y="0" width="32" height="70" rx="14" fill="#8a5a3a"/><rect x="20" y="64" width="80" height="22" rx="6" fill="#6b4a32"/><rect x="12" y="84" width="96" height="30" rx="5" fill="' + c + '"/></svg>', x - 60, y - 140, 120, 150);
        gone(st.animate([{ transform: "translateY(-" + (y + 60) + "px) scale(1.3)" }, { transform: "translateY(0) scale(1)", offset: 0.5, easing: "ease-in" }, { transform: "translateY(4px) scale(1.03,.95)", offset: 0.6 }, { transform: "translateY(4px) scale(1.03,.95)", offset: 0.75 }, { transform: "translateY(-" + (y + 60) + "px) scale(1.2)", opacity: 0.6 }],
                        { duration: 1300, fill: "both" }), st);
        later(650, function () {
          shake(6, 380);
          var pr = add("div", "dcs-thing", "left:" + (x - 80) + "px;top:" + (y - 34) + "px;width:160px;height:90px;border:4px solid " + c + ";border-radius:14px;color:" + c +
            ";display:grid;place-items:center;text-align:center;font:900 15px -apple-system,'Segoe UI',sans-serif;transform:rotate(-9deg);opacity:.92;");
          var e1 = add("span", "", "font-size:34px;line-height:1", pr), e2 = add("span", "", "letter-spacing:.06em;text-transform:uppercase", pr);
          e1.textContent = s.emoji; e2.textContent = "From " + s.name;
          pr.animate([{ opacity: 0, transform: "rotate(-9deg) scale(1.1)" }, { opacity: 0.92, transform: "rotate(-9deg) scale(1)" }], { duration: 120, fill: "both" });
          for (var k = 0; k < 8; k++) { fadeOut(add("span", "", "position:absolute;left:" + (x + (R() - 0.5) * 220) + "px;top:" + (y + 10 + (R() - 0.5) * 120) + "px;width:" + (4 + R() * 7) + "px;height:" + (4 + R() * 7) + "px;border-radius:50%;background:" + c + ";opacity:.7"), 2400); }
          fadeOut(pr, 2600, 700);
          if (i === list.length - 1) { flash(s); }
        });
      });
    });
    return list.length * 650 + 3800;
  };
  SHOW.disco = function (list) {  // a disco ball drops and spins, lights sweep the screen, the Pips bop along the bottom
    var cx = W() / 2, ball = add("div", "dcs-thing", "left:" + (cx - 46) + "px;top:0;width:92px;height:200px;");
    var cord = add("div", "", "position:absolute;left:45px;top:0;width:2px;height:100px;background:#999", ball);
    var db = add("div", "", "position:absolute;left:0;top:96px;width:92px;height:92px;border-radius:50%;background:repeating-linear-gradient(90deg,#d8dde6 0 10px,#9aa3b2 10px 12px),#ccc;" +
      "box-shadow:inset -14px -14px 22px rgba(0,0,0,.35),inset 10px 10px 18px rgba(255,255,255,.6),0 0 30px rgba(255,255,255,.4);background-blend-mode:multiply;", ball);
    void cord;
    ball.animate([{ transform: "translateY(-220px)" }, { transform: "translateY(0)" }], { duration: 700, easing: "ease-out", fill: "both" });
    db.animate([{ backgroundPosition: "0 0" }, { backgroundPosition: "120px 0" }], { duration: 900, iterations: 6 });
    dim(0.45, 5200);
    var cols = ["#ff4d6d", "#ffd166", "#06d6a0", "#4cc9f0", "#c77dff", "#ff9f1c"];
    for (var k = 0; k < 20; k++) {
      var sz = 30 + R() * 50, l = add("span", "dcs-light", "left:0;top:0;width:" + sz + "px;height:" + sz + "px;background:" + cols[k % 6] + ";opacity:.75;"), ks = [];
      for (var q = 0; q < 6; q++) { ks.push({ transform: "translate(" + (R() * W()) + "px," + (R() * H()) + "px)" }); }
      gone(l.animate(ks, { duration: 4600, delay: 500, easing: "ease-in-out", fill: "both" }), l);
    }
    list.forEach(function (s, j) {
      var p = pip(s.jump, s.a, 72, "left:" + (W() * (0.25 + 0.25 * j) - 36) + "px;top:" + (H() - 90) + "px;");
      p.animate([{ transform: "translateY(0) rotate(-6deg)" }, { transform: "translateY(-18px) rotate(6deg)" }, { transform: "translateY(0) rotate(-6deg)" }], { duration: 520, iterations: 8, delay: j * 120 });
      popIn(p, 400); fadeOut(p, 4600);
    });
    rain(list.map(function (s) { return s.emoji; }), 30, 4200, 600, { size: 18 });
    later(4800, function () { gone(ball.animate([{ transform: "translateY(0)" }, { transform: "translateY(-220px)" }], { duration: 600, easing: "ease-in", fill: "both" }), ball); flash(list[0]); });
    return 6000;
  };
  SHOW.hat = function (list) {  // a top hat, a tap of the wand, a fountain of their emoji. Ta-da!
    var cx = W() / 2, cy = Math.min(190, H() * 0.3), s0 = list[0];
    var hat = svgEl('<svg viewBox="0 0 120 110" width="120" height="110"><ellipse cx="60" cy="96" rx="58" ry="12" fill="#222"/><rect x="22" y="14" width="76" height="82" rx="6" fill="#2b2b2b"/><rect x="22" y="66" width="76" height="14" fill="' + hexOk(acc(s0.a)) + '"/><ellipse cx="60" cy="16" rx="38" ry="8" fill="#3a3a3a"/></svg>', cx - 60, cy, 120, 110);
    popIn(hat, 450);
    var p = pip(s0.cheer, s0.a, 84, "left:" + (cx - 170) + "px;top:" + (cy + 24) + "px;"); popIn(p, 400);
    var wand = svgEl('<svg viewBox="0 0 80 20" width="80" height="20"><rect x="0" y="8" width="66" height="5" rx="2" fill="#222"/><rect x="0" y="8" width="10" height="5" fill="#fff"/><circle cx="70" cy="10" r="6" fill="#f2b33d"/></svg>', cx - 100, cy + 40, 80, 20);
    wand.style.transformOrigin = "0 50%";
    wand.animate([{ transform: "rotate(10deg)" }, { transform: "rotate(-24deg)", offset: 0.4 }, { transform: "rotate(10deg)", offset: 0.6 }, { transform: "rotate(-24deg)", offset: 0.8 }, { transform: "rotate(0)" }], { duration: 1000, delay: 500, fill: "both" });
    list.slice(1).forEach(function (s, j) { var q = pip(s.hello, s.a, 64, "left:" + (cx + 76 + j * 64) + "px;top:" + (cy + 44) + "px;"); popIn(q, 400); fadeOut(q, 4400); });
    later(1100, function () { burst(cx, cy + 10, ["✨"], 14, { spread: 220, up: 160, g: 200, dur: 900, size: 18 }); });
    var ems = list.map(function (s) { return s.emoji; });
    for (var k = 0; k < 26; k++) { (function (k) { later(1400 + k * 70, function () { fly(cx + (R() - 0.5) * 30, cy + 14, ems[k % ems.length], { vx: (R() - 0.5) * W() * 0.8, vy: -(260 + R() * 220), g: 900, dur: 1700, rot: (R() - 0.5) * 500, size: 22 + R() * 10 }); }); })(k); }
    later(3400, function () {
      var big = txt(cx, cy, ems[0], "dcs-pt", "font-size:40px;");
      gone(big.animate([{ transform: "translate(-50%,0) scale(.5)", opacity: 0 }, { transform: "translate(-50%,-120px) scale(3)", opacity: 1, offset: 0.6 }, { transform: "translate(-50%,-140px) scale(3.2)", opacity: 0 }], { duration: 1400, easing: "ease-out", fill: "both" }), big);
      var td = txt(cx + 70, cy - 80, "Ta-da!"); gone(td.animate([{ opacity: 0, transform: "scale(.5)" }, { opacity: 1, transform: "scale(1.2)", offset: 0.4 }, { opacity: 0 }], { duration: 1300, fill: "both" }), td);
      flash(s0); fadeOut(hat, 1200); fadeOut(p, 1200); fadeOut(wand, 1000);
    });
    return 5400;
  };
  SHOW.snow = function (list) {  // the screen shakes like a snow globe; their emoji snow down and settle
    shake(10, 700);
    var gl = add("div", "", "position:absolute;inset:0;background:radial-gradient(ellipse at 30% 20%, rgba(255,255,255,.35), transparent 45%);pointer-events:none;");
    gone(gl.animate([{ opacity: 0 }, { opacity: 1, offset: 0.2 }, { opacity: 1, offset: 0.8 }, { opacity: 0 }], { duration: 5200, fill: "both" }), gl);
    later(500, function () { rain(list.map(function (s) { return s.emoji; }).concat(["❄"]), 70, 5200, 0, { settle: true, sway: true, size: 16 }); });
    later(1800, function () { flash(list[0]); });
    return 8400;
  };

  function stop() {
    T.forEach(clearTimeout); T = []; LOOPS.forEach(function (o) { o.on = false; }); LOOPS = [];
    if (ov) {
      // a click or Esc mid-show: it fades away, never gone in one frame; what's mid-air goes with it
      var o = ov, a = o.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 260, easing: "ease-out", fill: "forwards" });
      ov = null;
      o.setAttribute("aria-hidden", "true"); o.inert = true; o.style.pointerEvents = "none";
      o.querySelectorAll(".dcs-click").forEach(function (x) { x.classList.remove("dcs-click"); });
      a.onfinish = a.oncancel = function () { o.remove(); };
    }
    if (onKey) { document.removeEventListener("keydown", onKey, true); onKey = null; }
    if (onDown) { document.removeEventListener("pointerdown", onDown, true); onDown = null; }
  }
  function end(ms) { T.push(setTimeout(stop, ms)); }

  window.DCShow = {
    kinds: Object.keys(SHOW),
    stop: stop,
    play: function (kind, data) {
      stop();
      if (!SHOW[kind] || !data || !data.senders || !data.senders.length || !document.body.animate) { return false; }
      D = data;
      if (D.sevcss && !document.getElementById("dc-sev-css-show")) {
        var sc = document.createElement("style"); sc.id = "dc-sev-css-show"; sc.textContent = D.sevcss; (document.head || document.body).appendChild(sc);
      }
      if (!document.getElementById("dc-show-css")) {
        var st = document.createElement("style"); st.id = "dc-show-css"; st.textContent = CSS; (document.head || document.body).appendChild(st);
      }
      ov = document.createElement("div"); ov.id = "dc-show"; ov.setAttribute("aria-hidden", "false");
      document.body.appendChild(ov);
      onKey = function (e) { if (e.key === "Escape") { stop(); } };
      onDown = function (e) { if (!(e.target && e.target.closest && e.target.closest(".dcs-click"))) { stop(); } };
      document.addEventListener("keydown", onKey, true);
      document.addEventListener("pointerdown", onDown, true);
      var ms = SHOW[kind](data.senders.slice(0, 3));
      if (ms) { end(ms); }
      else { end(20000); }  // a present: when they're all open, or at the latest
      return true;
    }
  };
})();
