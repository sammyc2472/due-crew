// The room widgets' one runtime (room_model.widget_js): the chip, the bottom bar,
// the margin card, the break, the room's card, the question and the start.
// The words in capitals between double underscores are filled in as it's sent.
(function () {
  var D = __DATA__, KIND = __KIND__, SQ = __SQUARES__;
  var ids = ['chip', 'bottom', 'gutter', 'break', 'card', 'ask', 'start'];
  function drop(k) {
    var el = document.getElementById('dc-room-' + k);
    if (el) { el.remove(); if (k === 'bottom' && window.dcBarBalance) { window.dcBarBalance(); } }
    if (window['dcRoomTick_' + k]) { clearInterval(window['dcRoomTick_' + k]); window['dcRoomTick_' + k] = null; }
  }
  if (KIND === 'off') { ids.forEach(drop); window.dcRoomFit = null; window.dcBarBalance && window.dcBarBalance(); return; }
  drop(KIND);
  if (!D) { return; }
  function night() {
    return /night/i.test(document.body.className) || document.documentElement.classList.contains('night-mode') ||
      (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches && !document.body.className);
  }
  function C() {
    var n = night();
    return {a: n ? D.accent[1] : D.accent[0], bg: n ? '#2c2c2c' : '#ffffff', ink: n ? '#e8e8e8' : '#222222',
            mut: n ? '#9c9c9c' : '#777777', line: n ? '#3d403b' : '#e2e2da', warm: n ? '#dda45c' : '#b26a00',
            face: n ? '#3a3148' : '#efe9f9'};
  }
  function phase(now) {
    var t = D.start;
    if (now < t) { return {state: 'before', round: 0, left: t - now, until: t, total: 1}; }
    for (var i = 1; i <= D.rounds; i++) {
      if (now < t + D.round) { return {state: 'round', round: i, left: t + D.round - now, until: t + D.round, total: D.round}; }
      t += D.round;
      if (i < D.rounds && D.brk) {
        if (now < t + D.brk) { return {state: 'break', round: i, left: t + D.brk - now, until: t + D.brk, total: D.brk}; }
        t += D.brk;
      }
    }
    if (D.kind === 'fifteen') {
      // 3.8.1: the last fifteen's question, for its five minutes (room_model.phase)
      if (now < t + D.ask) { return {state: 'ask', round: D.rounds, left: t + D.ask - now, until: t + D.ask, total: D.ask}; }
      t += D.ask;
    }
    return {state: 'done', round: D.rounds, left: 0, until: t, total: 1};
  }
  function hm(ms) { return new Date(ms).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }
  function mins(ms) { return Math.max(1, Math.ceil(ms / 60000)); }
  function mmss(ms) { var s = Math.max(0, Math.round(ms / 1000)); return Math.floor(s / 60) + ':' + ('0' + s % 60).slice(-2); }
  // 3.9.6: a button's look is the widget's own, never Anki's (a margin, a pressed shadow) or macOS's (Liquid Glass)
  var BTN = '-webkit-appearance:none;appearance:none;margin:0;box-shadow:none;min-height:0;min-width:0;text-shadow:none;' +
    '-webkit-backdrop-filter:none;backdrop-filter:none;letter-spacing:normal;';
  function el(tag, css, text) {
    var e = document.createElement(tag), btn = tag === 'button';
    if (css || btn) { e.style.cssText = (btn ? BTN : '') + (css || ''); }
    if (text != null) { e.textContent = text; }
    if (btn) {  // Anki's button { outline: none !important } takes the focus ring: an inline !important brings it back
      e.addEventListener('focus', function () {
        if (e.matches && e.matches(':focus-visible')) { e.style.setProperty('outline', '2px solid ' + ((typeof c !== 'undefined' && c && c.a) || '#2e7d32'), 'important'); e.style.outlineOffset = '2px'; }
      });
      e.addEventListener('blur', function () { e.style.removeProperty('outline'); });
    }
    return e;
  }
  function ring(size, c) {
    var r = el('span', 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;display:inline-grid;place-items:center;flex:none;');
    var inner = el('b', 'width:' + (size - Math.max(6, size * .12)) + 'px;height:' + (size - Math.max(6, size * .12)) +
      'px;border-radius:50%;display:grid;place-items:center;background:' + c.bg + ';color:' + c.ink + ';font:600 ' +
      Math.round(size * (size > 60 ? .22 : .4)) + 'px -apple-system,Segoe UI,sans-serif;');
    r.appendChild(inner);
    r.set = function (frac, label, warm) {
      var col = warm ? c.warm : c.a;
      r.style.background = 'conic-gradient(' + col + ' ' + (frac * 360) + 'deg,' + c.line + ' 0)';
      inner.textContent = label;
    };
    return r;
  }
  function squares(c, w) {
    var s = el('span', 'display:block;width:' + w + 'px;flex:none;');
    s.innerHTML = SQ;
    s.querySelectorAll('.on').forEach(function (q) { q.setAttribute('fill', c.a); });
    s.querySelectorAll('.off').forEach(function (q) { q.setAttribute('fill', c.line); });
    return s;
  }
  function faces(c, size) {
    var f = el('span', 'display:inline-flex;');
    (D.initials || D.names).forEach(function (n, i) {
      var x = el('i', 'width:' + size + 'px;height:' + size + 'px;border-radius:50%;display:grid;place-items:center;font:700 ' +
        Math.round(size * .45) + 'px -apple-system,Segoe UI,sans-serif;font-style:normal;background:' + c.face + ';color:' + c.a +
        ';border:2px solid ' + c.bg + ';margin-left:' + (i ? -6 : 0) + 'px;', (n || '?').charAt(0).toUpperCase());
      f.appendChild(x);
    });
    return f;
  }
  function send(cmd) { try { pycmd('duecrew:' + cmd + '|' + __KEY__); } catch (e) {} }
  // 3.8.1: Pip, drawn by sev.py: our own markup, never a name, so it goes in as markup
  var FIF = D.kind === 'fifteen';
  if (D.sev && D.sevcss && !document.getElementById('dc-sev-css')) {
    var css = document.createElement('style'); css.id = 'dc-sev-css'; css.textContent = D.sevcss;
    (document.head || document.body).appendChild(css);
  }
  // a slot the body fills (sev.SLOT), so Pip centres on its neighbours; full:
  // the whole drawing (the question and the break have room for its effects)
  function sev(key, size, full) {
    var k = D.slot || [0.6, -0.2, -0.32], s = full ? size : Math.round(size * k[0]);
    var w = el('span', 'position:relative;display:inline-block;flex:none;width:' + s + 'px;height:' + s +
      'px;--sv-a:' + c.a + ';--sv-line:' + c.line + ';--sv-amb:' + c.warm + ';--sv-mut:' + c.mut + ';');
    w.set = function (key2) {
      if (w.k === key2 || !D.sev || !D.sev[key2]) { return; }
      w.k = key2; w.innerHTML = D.sev[key2];
      var v = w.firstChild;
      if (v && v.style) {
        v.style.position = 'absolute'; v.style.width = v.style.height = size + 'px';
        v.style.left = (full ? 0 : Math.round(size * k[1])) + 'px'; v.style.top = (full ? 0 : Math.round(size * k[2])) + 'px';
      }
    };
    w.set(key);
    return w;
  }
  // 3.8.1: a crew room's members as their Pips (room_model.seats): each in its
  // person's accent (by day or night, as mine), each blinking at its own moment;
  // a name is only ever a label, set as text
  // most: that many, then +N (3.8.21, the top bar's chip)
  function seats(size, most) {
    var f = el('span', 'display:inline-flex;align-items:center;gap:' + Math.max(3, Math.round(size / 8)) + 'px;'), n = night();
    D.seats.forEach(function (s, i) {
      if (most && i >= most) { return; }
      var w = sev(s.k && D.sev[s.k] ? s.k : s.m && s.m !== 'idle' && D.sev['idle.' + s.m] ? 'idle.' + s.m : 'idle', size), v = w.firstChild;
      w.style.setProperty('--sv-a', n ? s.a[1] : s.a[0]);
      w.style.setProperty('--sv-d', s.d + 's');
      if (s.b) { w.style.setProperty('--sv-b', s.b + 's'); }
      w.title = s.n;
      if (v && v.setAttribute) { v.setAttribute('aria-label', s.n); }
      f.appendChild(w);
    });
    if (most && D.seats.length > most) { f.appendChild(el('small', 'color:' + c.mut + ';font-size:11px;', '+' + (D.seats.length - most))); }
    return f;
  }
  // 3.8.21 (Sam: "no pips here either!"): with Pip on, a crew room's people are their Pips
  // wherever its faces were (the chip, the gutter, the break, the card); Pip off, the initials.
  // A face of size px is a seat of size / sev.SLOT[0]: the slot its Pip fills is the face's size
  // In a column (stack), their hats clear the line above and a crowd wraps
  function people(c, size, most, stack) {
    if (!(D.sev && D.seats && D.seats.length)) { return faces(c, size); }
    var s = Math.round(size / (D.slot || [0.6])[0]), f = seats(s, most);
    if (stack) {
      f.style.cssText += 'flex-wrap:wrap;justify-content:center;max-width:100%;padding-top:' + Math.round(s * .3) +
        'px;row-gap:' + Math.round(s * .35) + 'px;';
    }
    return f;
  }
  function ftitle(p) { var n = p.state === 'break' ? p.round + 1 : p.round; return p.state === 'break' ? 'Break' : 'Fifteen' + (n > 1 ? ' ' + n : ''); }
  function fsub(p) {
    return p.state === 'break' ? 'fifteen ' + (p.round + 1) + ' at ' + hm(p.until) : p.state === 'ask' ? 'done' : mins(p.left) + ' min left';
  }
  // the little Pip's moment: heads down in a fifteen (after a jump or a shake-out
  // as it starts), resting or stretching on a break, the clock at the question
  function fkey(p, fresh) {
    if (p.state === 'ask') { return vk('ring', p.round); }
    if (p.state === 'break') { return D.brk_pose === 'stretch' ? vk('stretch', p.round) : 'rest'; }
    if (fresh) { return p.round > 1 ? 'again' : 'ready'; }
    return vk('focus', p.round);
  }
  // 3.8.1 (Sam: "variety!"): a place's moves take turns, a round each (room_model.FIFTEEN_VARY)
  function vk(k, n) {
    var v = D.vary && D.vary[k];
    return v && v.length ? v[(((n + (D.vseed || 0)) % v.length) + v.length) % v.length] : k;
  }
  function fresh(p) { return p.state === 'round' && p.total - p.left < 4000; }
  function sub(p) {
    if (p.state === 'before') { return 'starts ' + hm(D.start); }
    if (p.state === 'break') { return 'Break · round ' + (p.round + 1) + ' at ' + hm(p.until); }
    return 'Round ' + p.round + ' of ' + D.rounds + (p.round < D.rounds && D.brk ? ' · break ' + hm(p.until) : ' · ends ' + hm(p.until));
  }
  var c = C(), root, update;

  if (KIND === 'chip') {
    root = el('div', 'position:fixed;__SIDE__:10px;top:50%;transform:translateY(-50%);height:26px;display:flex;align-items:center;gap:7px;' +
      'padding:0 10px 0 5px;border:1px solid ' + c.a + ';border-radius:14px;background:' + c.bg + ';color:' + c.ink +
      ';font:12px -apple-system,Segoe UI,sans-serif;cursor:pointer;z-index:99;white-space:nowrap;');
    root.title = FIF ? 'Your fifteen' : 'Your study room';
    var sq = FIF && D.sev ? sev('focus', 32) : squares(c, 34), rg = ring(20, c), tx = el('span', 'display:grid;line-height:1.1;'),
        t1 = el('b', 'font-size:11.5px;', D.title), t2 = el('small', 'font-size:10.5px;color:' + c.mut + ';'), fc = people(c, 18, 4);
    tx.appendChild(t1); tx.appendChild(t2);
    if (sq.set) { sq.style.marginRight = '5px'; }  // 3.8.2: what Pip set down to hold its card, clear of the clock
    root.appendChild(sq); root.appendChild(rg); root.appendChild(tx); root.appendChild(fc);
    if (D.compact) { tx.style.display = fc.style.display = 'none'; if (!sq.set) { sq.style.display = 'none'; } root.style.padding = '0 3px'; }
    if (!fc.childElementCount) { fc.style.display = 'none'; }  // no one with me: no empty slot doubling the gap
    root.onclick = function () { send('roomcard'); };
    update = function (p) {
      rg.set(p.state === 'before' ? 0 : p.state === 'ask' ? 1 : 1 - p.left / p.total,
             p.state === 'before' ? '·' : p.state === 'ask' ? '✓' : String(mins(p.left)), p.state === 'break');
      if (FIF) { t1.textContent = ftitle(p); t2.textContent = fsub(p); if (sq.set) { sq.set(fkey(p, fresh(p))); } }
      else { t2.textContent = sub(p); }
    };
  } else if (KIND === 'bottom') {
    var edit = document.querySelector('button[onclick*="edit"]');
    var cell = edit ? edit.parentNode : document.body;
    root = el('span', 'display:inline-flex;align-items:center;gap:6px;margin-left:10px;padding-left:10px;border-left:1px solid ' + c.line +
      ';font:12px -apple-system,Segoe UI,sans-serif;color:' + c.mut + ';vertical-align:middle;cursor:pointer;white-space:nowrap;');
    var sv2 = FIF && D.sev ? sev('focus', 30) : null, rg2 = ring(20, c), tx2 = el('span');
    if (sv2) { sv2.style.marginRight = '5px'; root.appendChild(sv2); }
    root.appendChild(rg2); root.appendChild(tx2);
    root.onclick = function () { send('roomcard'); };
    cell.appendChild(root);
    update = function (p) {
      rg2.set(p.state === 'before' ? 0 : p.state === 'ask' ? 1 : 1 - p.left / p.total,
              p.state === 'before' ? '·' : p.state === 'ask' ? '✓' : String(mins(p.left)), p.state === 'break');
      if (sv2) { sv2.set(fkey(p, fresh(p))); }
      tx2.textContent = (p.state === 'break' ? 'break ' + mins(p.left) + ' min' : p.state === 'before' ? 'starts ' + hm(D.start) :
        p.state === 'ask' ? 'done' : mins(p.left) + ' min') + (D.line ? ' · ' + D.line : '');
    };
  } else if (KIND === 'gutter') {
    root = el('div', 'position:fixed;left:16px;top:16px;width:' + __GUTTER__ + 'px;box-sizing:border-box;display:grid;justify-items:center;gap:5px;' +
      'padding:12px 8px;border:1px solid ' + c.line + ';border-radius:14px;background:' + c.bg + ';color:' + c.ink +
      ';font:12px -apple-system,Segoe UI,sans-serif;text-align:center;box-shadow:0 4px 14px rgba(0,0,0,.08);z-index:50;cursor:pointer;');
    var rg3 = ring(40, c), g1 = el('b', 'font-size:12.5px;'), g2 = el('small', 'color:' + c.mut + ';font-size:11px;'),
        g3 = el('small', 'color:' + c.mut + ';font-size:11px;line-height:1.3;', D.line);
    var sv3 = FIF && D.sev ? sev('focus', 72) : null;
    root.appendChild(sv3 || squares(c, 56)); root.appendChild(rg3); root.appendChild(g1); root.appendChild(g2); root.appendChild(people(c, 26, 0, true)); root.appendChild(g3);
    root.onclick = function () { send('roomcard'); };
    update = function (p) {
      rg3.set(p.state === 'before' ? 0 : p.state === 'ask' ? 1 : 1 - p.left / p.total,
              p.state === 'before' ? '·' : p.state === 'ask' ? '✓' : String(mins(p.left)), p.state === 'break');
      if (FIF) {
        if (sv3) { sv3.set(fkey(p, fresh(p))); }
        g1.textContent = ftitle(p); g2.textContent = fsub(p);
        return;
      }
      g1.textContent = p.state === 'break' ? 'Break' : p.state === 'before' ? D.title : 'Round ' + p.round + ' of ' + D.rounds;
      g2.textContent = p.state === 'break' ? 'round ' + (p.round + 1) + ' at ' + hm(p.until) : p.state === 'before' ? 'starts ' + hm(D.start) :
        (p.round < D.rounds && D.brk ? 'break at ' + hm(p.until) : 'ends ' + hm(p.until));
    };
    // shown only while the card leaves the left margin free; A and B
    // don't need this, since they never sit over the card
    window.dcRoomFit = function () {
      var qa = document.getElementById('qa'), left = window.innerWidth;
      if (qa) {
        var r = document.createRange(); r.selectNodeContents(qa);
        var rects = r.getClientRects();
        for (var i = 0; i < rects.length; i++) { if (rects[i].width > 0 && rects[i].height > 0) { left = Math.min(left, rects[i].left); } }
        qa.querySelectorAll('img,table,canvas,svg,video,iframe').forEach(function (m) {
          var b = m.getBoundingClientRect(); if (b.width > 0) { left = Math.min(left, b.left); }
        });
      }
      root.style.display = left > 16 + __GUTTER__ + 24 ? 'grid' : 'none';
    };
    if (!window.dcRoomFitResize) {
      window.dcRoomFitResize = true;
      window.addEventListener('resize', function () { window.dcRoomFit && window.dcRoomFit(); });
    }
  } else if (KIND === 'break') {
    // a type-in answer box keeps no focus under the break
    try { if (document.activeElement && document.activeElement.blur) { document.activeElement.blur(); } } catch (e) {}
    root = el('div', 'position:fixed;inset:0;background:' + c.bg + ';color:' + c.ink + ';display:grid;place-items:center;z-index:9999;' +
      'font:16px -apple-system,Segoe UI,sans-serif;text-align:center;');
    var box = el('div', 'display:grid;justify-items:center;gap:14px;max-width:520px;padding:20px;');
    var logo = el('span', 'display:flex;align-items:center;gap:8px;');
    // 3.8.1: a fifteen's break is Pip's: breathe along (a square, four counts a side), or stretch
    // breathing draws its square around Pip: the whole drawing; a stretch needs only Pip's own room
    var bs = FIF && D.sev ? (D.brk_pose === 'stretch' ? sev(vk('stretch', phase(Date.now()).round), 170) : sev('breathe', 180, true)) : null;
    if (bs) { bs.style.marginBottom = '10px'; }  // its shadow (or the square's "out") clear of the ring
    // 3.9.1 (Pip at rest, and the bug hunt): the break's Pip is the exercise, so its moves go on all break
    // (shake, march and look too, not only the stretch), where Pip elsewhere rests after a few rounds
    root.style.setProperty('--sv-on', 'infinite');
    logo.appendChild(bs || squares(c, 110));
    var rg4 = ring(FIF ? 96 : 150, c), h = el('div', 'font:600 28px -apple-system,Segoe UI,sans-serif;'), p1 = el('div', 'color:' + c.mut + ';max-width:40ch;');
    var btns = el('div', 'display:flex;gap:10px;flex-wrap:wrap;justify-content:center;');
    function btn(text, go, cmd) {
      var b = el('button', (go ? 'background:' + c.a + ';color:' + c.bg + ';border:0;font:600 14px ' : 'background:transparent;color:' + c.ink +
        ';border:1px solid ' + c.line + ';font:14px ') + '-apple-system,Segoe UI,sans-serif;border-radius:8px;padding:8px 16px;cursor:pointer;', text);
      b.onclick = function () { send(cmd); };
      btns.appendChild(b);
      return b;
    }
    if (FIF) {
      btn('Start now', true, 'room15now'); btn('Stop here', false, 'room15stop');
    } else {
      var cheer = btn('Cheer the room 🎉', true, 'roomcheer');
      cheer.onclick = function () { send('roomcheer'); cheer.textContent = 'Cheered ✓'; cheer.disabled = true; };
      btn('Skip the break', false, 'roomskip');
    }
    box.appendChild(logo); box.appendChild(rg4); box.appendChild(h); box.appendChild(p1); box.appendChild(people(c, 32, 0, true)); box.appendChild(btns);
    box.appendChild(el('small', 'color:' + c.mut + ';font-size:12px;', FIF ? (D.brk_pose === 'stretch' ?
      'Stand up, stretch, some water. Look at something far away.' : 'Breathe with Pip: in for four, hold, out for four, hold.') :
      'The break waited for you to finish your card.'));
    root.appendChild(box);
    var ended = false;
    update = function (p) {
      if (p.state !== 'break') {
        if (!ended) { ended = true; send('roombreakend'); }
        return;
      }
      rg4.set(1 - p.left / p.total, mmss(p.left), true);  // fills as the break passes, as every ring does
      if (FIF) {
        h.textContent = 'Break';
        p1.textContent = 'Fifteen ' + (p.round + 1) + ' starts at ' + hm(p.until) + '.';
        return;
      }
      h.textContent = 'Round ' + p.round + ' done. Break.';
      var others = D.names.filter(function (n) { return n !== 'you'; });
      p1.textContent = (others.length ? others.join(' and ') + (others.length > 1 ? ' are' : ' is') + ' on the same break. ' : '') +
        'Round ' + (p.round + 1) + ' starts at ' + hm(p.until) + '.';
    };
  } else if (KIND === 'ask') {
    // 3.8.1, the question at the end of a fifteen, once the card in front of me is answered
    try { if (document.activeElement && document.activeElement.blur) { document.activeElement.blur(); } } catch (e) {}
    root = el('div', 'position:fixed;inset:0;background:' + c.bg + ';color:' + c.ink + ';display:grid;place-items:center;z-index:9999;' +
      'font:16px -apple-system,Segoe UI,sans-serif;text-align:center;');
    var qb = el('div', 'display:grid;justify-items:center;gap:12px;max-width:520px;padding:20px;');
    // Pip with the clock (its shadow clear of the words), or with Pip off the logo's squares
    if (D.sev) { var qs0 = sev(vk('ring', D.rounds), 170); qs0.style.marginBottom = '10px'; qb.appendChild(qs0); } else { qb.appendChild(squares(c, 110)); }
    var n = D.rounds, cap = n >= D.max;
    qb.appendChild(el('div', 'font:600 28px -apple-system,Segoe UI,sans-serif;', 'That’s fifteen.'));
    if (D.cards != null) {
      qb.appendChild(el('div', 'color:' + c.mut + ';', D.cards + (D.cards === 1 ? ' card' : ' cards') + (n > 1 ? ' in fifteen ' + n : '') +
        (n > 1 && D.total != null ? ' · ' + D.total + ' this session' : '')));
    }
    qb.appendChild(el('div', 'max-width:40ch;', cap ? 'That’s eight fifteens: two hours. Enough for one sitting.' :
      'A five-minute break, then another fifteen?'));
    var qs = el('div', 'display:flex;gap:10px;flex-wrap:wrap;justify-content:center;');
    function qbtn(text, go, cmd) {
      var b = el('button', (go ? 'background:' + c.a + ';color:' + c.bg + ';border:0;font:600 14px ' : 'background:transparent;color:' + c.ink +
        ';border:1px solid ' + c.line + ';font:14px ') + '-apple-system,Segoe UI,sans-serif;border-radius:8px;padding:8px 16px;cursor:pointer;', text);
      b.onclick = function () { send(cmd); };
      qs.appendChild(b);
    }
    if (!cap) { qbtn('Take five, then another fifteen', true, 'room15five'); qbtn('Another fifteen now', false, 'room15now'); }
    qbtn('Stop here', cap, 'room15stop');
    qb.appendChild(qs);
    root.appendChild(qb);
    var gone = false;
    update = function (p) {
      if (p.state !== 'ask' && !gone) { gone = true; send('roombreakend'); }
    };
  } else if (KIND === 'start' && D.sit) {
    // 3.9.5, the Fifteen at 35 (only when my own log shows the slide): in ▶ Fifteen?'s place,
    // in the accent; Take five starts a fifteen in its break, × waves it off for this sitting
    root = el('div', 'position:fixed;__SIDE__:10px;top:50%;transform:translateY(-50%);height:26px;display:flex;align-items:center;gap:6px;' +
      'padding:0 5px 0 11px;border:1px solid ' + c.a + ';border-radius:14px;background:' + c.a + ';color:' + c.bg +
      ';font:600 12px -apple-system,Segoe UI,sans-serif;z-index:99;white-space:nowrap;');
    root.appendChild(el('span', '', D.sit + ' min in ·'));
    var five = el('a', 'color:inherit;text-decoration:underline;cursor:pointer;', 'Take five');
    five.title = 'Five minutes off, then a fifteen';
    var no = el('a', 'color:inherit;opacity:.85;cursor:pointer;font-size:15px;line-height:1;padding:0 4px;', '×');
    no.title = 'Not this time';
    [[five, 'room15sit'], [no, 'room15sitx']].forEach(function (p) {
      p[0].setAttribute('role', 'button'); p[0].tabIndex = 0;
      p[0].onclick = function () { send(p[1]); };
      p[0].onkeydown = function (ev) { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); send(p[1]); } };
    });
    no.setAttribute('aria-label', 'Not this time');
    root.appendChild(five); root.appendChild(no);
    root.id = 'dc-room-start';
    document.body.appendChild(root);
    return;
  } else if (KIND === 'start') {
    // 3.8.1: ▶ Fifteen? in the top bar, at the chip's end, whenever I'm in no room
    root = el('div', 'position:fixed;__SIDE__:10px;top:50%;transform:translateY(-50%);height:26px;display:flex;align-items:center;gap:6px;' +
      'padding:0 10px 0 9px;border:1px solid ' + c.line + ';border-radius:14px;background:' + c.bg + ';color:' + c.ink +
      ';font:600 12px -apple-system,Segoe UI,sans-serif;cursor:pointer;z-index:99;white-space:nowrap;');
    root.title = 'Fifteen minutes, now. At the end, one question: a break and another?';
    // 3.8.2: what Pip holds, or a costume's tail, reaches past its slot: room before the ▶
    if (D.sev) { var sw = sev(D.nap ? 'nap' : 'idle', 32); sw.style.marginRight = '4px'; root.appendChild(sw); }
    root.appendChild(el('span', 'color:' + c.a + ';font-size:10px;margin-left:2px;', '▶'));
    var word = el('span', '', 'Fifteen?');
    root.appendChild(word);
    if (D.compact) { word.style.display = 'none'; }
    root.onclick = function () { send('room15'); };
    // 3.9.10 (Open a room left the board's foot): the arrow opens the two ways, on my own or a room with my crew
    var more = el('span', 'color:' + c.mut + ';font-size:10px;border-left:1px solid ' + c.line + ';padding:2px 0 2px 7px;margin-left:2px;', '▾');
    more.title = 'On my own, or a room with my crew';
    more.setAttribute('role', 'button'); more.setAttribute('aria-label', 'On my own, or a room with my crew');
    more.onclick = function (e) { e.stopPropagation(); send('room15menu'); };
    root.appendChild(more);
    root.id = 'dc-room-start';
    document.body.appendChild(root);
    return;
  } else if (KIND === 'card') {
    // 3.8.1: it opens at the chip's end of the screen (the left one too), and moves by its top row
    root = el('div', 'position:fixed;__SIDE__:12px;top:10px;width:330px;box-sizing:border-box;border:1px solid ' + c.line +
      ';border-radius:14px;background:' + c.bg + ';color:' + c.ink + ';box-shadow:0 12px 34px rgba(0,0,0,.2);padding:12px 14px;' +
      'display:grid;gap:10px;font:13px -apple-system,Segoe UI,sans-serif;z-index:10000;text-align:left;');
    var hd = el('div', 'display:flex;justify-content:space-between;align-items:center;cursor:grab;user-select:none;'),
        x = el('span', 'cursor:pointer;color:' + c.mut + ';font-size:18px;', '×');
    hd.title = 'Drag to move';
    // the logo's squares head every room's card; a fifteen's Pip sits by its clock (Sam: the spacing)
    var sv5 = FIF && D.sev ? sev('focus', 44) : null;
    hd.appendChild(squares(c, 70)); hd.appendChild(x);
    var AT = 'dcRoomCardAt';
    function put(px, py) {
      var w = root.offsetWidth, h = root.offsetHeight;
      root.style.right = 'auto';
      root.style.left = Math.max(4, Math.min(window.innerWidth - w - 4, px)) + 'px';
      root.style.top = Math.max(4, Math.min(window.innerHeight - h - 4, py)) + 'px';
    }
    root.place = function () {
      // where it was last dragged to, on this side; on this page, or kept by the browser
      var at = window[AT];
      if (!at) { try { at = JSON.parse(localStorage.getItem(AT) || 'null'); } catch (e) { at = null; } }
      if (at && at.side === D.side && isFinite(at.x) && isFinite(at.y)) { put(at.x, at.y); }
    };
    hd.addEventListener('mousedown', function (ev) {
      if (ev.target === x || ev.button !== 0) { return; }
      ev.preventDefault();
      var r = root.getBoundingClientRect(), dx = ev.clientX - r.left, dy = ev.clientY - r.top;
      hd.style.cursor = 'grabbing';
      function mv(e) { put(e.clientX - dx, e.clientY - dy); }
      function up() {
        document.removeEventListener('mousemove', mv); document.removeEventListener('mouseup', up);
        hd.style.cursor = 'grab';
        var at = {x: parseFloat(root.style.left), y: parseFloat(root.style.top), side: D.side};
        if (!isFinite(at.x)) { return; }
        window[AT] = at;
        try { localStorage.setItem(AT, JSON.stringify(at)); } catch (e) {}
      }
      document.addEventListener('mousemove', mv); document.addEventListener('mouseup', up);
    });
    var row = el('div', 'display:flex;gap:10px;align-items:center;'), rg5 = ring(44, c), rt = el('div', 'display:grid;flex:1;min-width:0;'),
        k1 = el('b', '', D.title), k2 = el('small', 'color:' + c.mut + ';font-size:12px;');
    rt.appendChild(k1); rt.appendChild(k2); row.appendChild(rg5); row.appendChild(rt);
    if (sv5) { row.appendChild(sv5); }
    var bar = el('div', 'display:flex;gap:3px;align-items:center;'), segs = [];
    for (var i = 1; i <= D.rounds; i++) {
      var sg = el('i', 'flex:' + D.round + ';height:8px;border-radius:4px;background:' + c.line + ';position:relative;overflow:hidden;display:block;');
      var fill = el('i', 'position:absolute;left:0;top:0;bottom:0;width:0;background:' + c.a + ';display:block;');
      sg.appendChild(fill); bar.appendChild(sg); segs.push(fill);
      if (i < D.rounds && D.brk) { bar.appendChild(el('i', 'flex:' + D.brk + ';height:4px;border-radius:2px;background:' + c.warm + ';opacity:.45;display:block;')); }
    }
    var who = el('div', 'display:flex;align-items:center;gap:8px;color:' + c.mut + ';font-size:12px;');
    who.appendChild(people(c, 24)); who.appendChild(el('span', '', D.line));
    var ft = el('div', 'display:flex;justify-content:space-between;font-size:12.5px;font-weight:600;color:' + c.a + ';border-top:1px solid ' + c.line + ';padding-top:8px;');
    var tuck = el('span', 'cursor:pointer;', D.compact ? 'Show the whole chip' : 'Tuck it away'),
        leave = el('span', 'cursor:pointer;', FIF ? 'Stop here' : 'Leave room');
    ft.appendChild(tuck); ft.appendChild(leave);
    // 3.8.1: a fifteen's card answers its question, and starts the next one early
    var acts = el('div', 'display:flex;gap:8px;flex-wrap:wrap;'), five = null, now5 = null;
    if (FIF) {
      var abtn = function (text, go, cmd) {
        var b = el('button', (go ? 'background:' + c.a + ';color:' + c.bg + ';border:0;font:600 12.5px ' : 'background:transparent;color:' + c.ink +
          ';border:1px solid ' + c.line + ';font:12.5px ') + '-apple-system,Segoe UI,sans-serif;border-radius:7px;padding:5px 11px;cursor:pointer;', text);
        b.onclick = function () { shut(); send(cmd); };
        acts.appendChild(b);
        return b;
      };
      five = abtn('Take five, then another', true, 'room15five');
      now5 = abtn('Another fifteen now', false, 'room15now');
    }
    root.appendChild(hd); root.appendChild(row); root.appendChild(bar);
    if (FIF) { root.appendChild(acts); } else { root.appendChild(who); }
    root.appendChild(ft);
    // closed, the chip it popped out of comes back (3.8.1: it hides while this is out)
    function shut() { drop('card'); send('roomcardoff'); }
    x.onclick = shut;
    tuck.onclick = function () { shut(); send('roomtuck'); };
    leave.onclick = function () { shut(); send(FIF ? 'room15stop' : 'roomleave'); };
    setTimeout(function () {
      document.addEventListener('mousedown', function out(ev) {
        // a card closed some other way (×, Tuck, Leave, redrawn) takes this with it
        if (!root.isConnected) { document.removeEventListener('mousedown', out); return; }
        if (!root.contains(ev.target)) { shut(); document.removeEventListener('mousedown', out); }
      });
    }, 0);
    update = function (p) {
      rg5.set(p.state === 'before' ? 0 : p.state === 'ask' ? 1 : 1 - p.left / p.total,
              p.state === 'before' ? '·' : p.state === 'ask' ? '✓' : String(mins(p.left)), p.state === 'break');
      if (FIF) {
        var cap = D.rounds >= D.max;
        if (sv5) { sv5.set(fkey(p, false)); }
        k1.textContent = p.state === 'ask' ? 'That’s fifteen.' : ftitle(p);
        k2.textContent = p.state === 'ask' ? (cap ? 'That’s eight: two hours. Enough for one sitting.' : 'A five-minute break, then another fifteen?') :
          p.state === 'break' ? 'Fifteen ' + (p.round + 1) + ' at ' + hm(p.until) : mins(p.left) + ' min left';
        five.style.display = p.state === 'ask' && !cap ? '' : 'none';
        now5.style.display = (p.state === 'ask' && !cap) || p.state === 'break' ? '' : 'none';
        now5.textContent = p.state === 'break' ? 'Start now' : 'Another fifteen now';
        acts.style.display = five.style.display === 'none' && now5.style.display === 'none' ? 'none' : 'flex';
      } else {
      k2.textContent = p.state === 'before' ? 'Starts at ' + hm(D.start) + ' · ' + D.rounds + ' rounds' :
        p.state === 'break' ? 'Break · round ' + (p.round + 1) + ' at ' + hm(p.until) :
        'Round ' + p.round + ' of ' + D.rounds + ' · ' + mins(p.left) + ' min left';
      }
      var now = Date.now(), t = D.start;
      segs.forEach(function (f) {
        f.style.width = Math.max(0, Math.min(1, (now - t) / D.round)) * 100 + '%';
        t += D.round + D.brk;
      });
    };
  }
  if (KIND !== 'bottom') { document.body.appendChild(root); }
  root.id = 'dc-room-' + KIND;
  if (root.place) { root.place(); }
  var last = null, said = null;
  // 3.9.1 (the efficiency run): it ticks only as often as it shows: each
  // second on the break's mm:ss and the question, else at the next minute
  // its words turn over or its phase ends, ten seconds at most (the ring)
  function next(p) {
    if (KIND === 'break' || KIND === 'ask') { return 1000; }
    return Math.max(50, Math.min(10000, p.left > 0 ? p.left % 60000 + 50 : 10000));
  }
  function tick() {
    var p = phase(Date.now());
    // 3.8.1: a phase that changes redraws the Decks screen (its lobby asks the question too)
    if (KIND === 'chip' && p.state !== last) { if (last !== null) { send('roomtick'); } last = p.state; }
    if (p.state === 'done' && KIND !== 'break' && KIND !== 'ask') { drop(KIND); return; }
    update(p);
    if (KIND === 'gutter' && window.dcRoomFit) { window.dcRoomFit(); }
    // the bar's buttons move back to its middle only when the room's words changed width
    if (KIND === 'bottom' && window.dcBarBalance && root.textContent !== said) { said = root.textContent; window.dcBarBalance(); }
    window['dcRoomTick_' + KIND] = setTimeout(tick, next(p));
  }
  tick();
})();
