/* Magic search's page (3.9.7): it draws the view magic_flow.Search sends
   (dcMagic.show) and says each click as "dcmagic:" + JSON through Anki's
   bridge. Every word from the view is set as text, never as markup. */
var dcMagic = (function () {
  'use strict';
  var V = null, root = null, els = {}, typed = null, sparkled = false, seen = {}, preview = false, making = false, madeFor = null;
  var landed = null, meant = null, dropped = {};  // 3.9.11: the answer that last landed, the "did you mean" last shown, each day's share
  var REDUCE = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function send(cmd, args) {
    var msg = 'dcmagic:' + JSON.stringify(Object.assign({ cmd: cmd }, args || {}));
    if (preview) { (window.dcMagicSent = window.dcMagicSent || []).push(msg); return; }
    if (window.pycmd && !waiting.length) { window.pycmd(msg); return; }
    // 3.9.9 (Sam: opened on a search already typed, the window stayed at its first size): Anki's bridge
    // comes up a moment after the page, and what was said before it (the page's height) was dropped
    waiting.push(msg);
    if (waiting.length === 1) flush();
  }
  var waiting = [], waited = 0;
  function flush() {
    if (window.pycmd) { var all = waiting; waiting = []; all.forEach(function (m) { window.pycmd(m); }); return; }
    if (++waited > 400) { waiting = []; return; }
    setTimeout(flush, 25);
  }
  function h(tag, attrs, kids) {
    var e = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      var v = attrs[k];
      if (v === null || v === undefined || v === false) return;
      if (k === 'text') e.textContent = v;
      else if (k === 'cls') e.className = v;
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? '' : v);
    });
    (kids || []).forEach(function (c) { if (c !== null && c !== undefined && c !== false) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return e;
  }
  function clear(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; }
  function n(x) { return Number(x || 0).toLocaleString(); }
  function plural(k, one, many) { return n(k) + ' ' + (k === 1 ? one : (many || one + 's')); }
  function btn(cls, text, cmd, args, extra) { return h('button', Object.assign({ cls: cls, type: 'button', text: text, onclick: function () { send(cmd, args); } }, extra || {})); }

  var MAG = '<svg class="mag" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" aria-hidden="true">' +
    '<circle cx="10" cy="11" r="6.2"/><path d="M19.4 20.4l-4.7-4.7"/>' +
    '<path class="st" d="M19 1.6l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9z" fill="var(--dc-hours)" stroke="none"/></svg>';

  function build() {
    root = document.getElementById('dcm');
    clear(root);
    els.deck = h('select', { cls: 'deck', 'aria-label': 'Deck', onchange: function () { send('deck', { did: els.deck.value }); } });
    var head = h('div', { cls: 'hd' }, [h('b', { text: 'Magic search' }), h('span', { cls: 'sp' }), els.deck,
      btn('x', '?', 'intro', { show: true }, { 'aria-label': 'What it can do', title: 'What it can do' }),
      btn('x', '×', 'close', {}, { 'aria-label': 'Close' })]);
    var box = h('div', { cls: 'box' });
    box.innerHTML = MAG;
    els.q = h('textarea', { cls: 'q', rows: '1', spellcheck: 'false', 'aria-label': 'What to find',
      placeholder: 'A topic, a filter, QIDs, a quiz on Friday, plan lines…' });
    box.appendChild(els.q);
    els.live = h('span', { cls: 'live', 'aria-hidden': 'true' });  // 3.9.11: the answer in the box as it's typed (what it found says it in full)
    els.live.hidden = true;
    box.appendChild(els.live);
    els.box = box;
    ['rows', 'topics', 'filters', 'found', 'lines', 'tops', 'tiles', 'pod', 'said', 'recent'].forEach(function (k) { els[k] = h('div', { cls: k }); });
    els.intro = h('div', { cls: 'intro', role: 'dialog', 'aria-label': 'Magic search' });
    // round 3: the box, what it understood (the filters' Only line, each topic and its tree), what it found, what to do
    [head, box, els.rows, els.filters, els.recent, els.topics, els.lines, els.found, els.tops, els.tiles, els.pod, els.said, els.intro]
      .forEach(function (e) { root.appendChild(e); });
    if (window.ResizeObserver) { var ro = new ResizeObserver(report); ro.observe(root); ro.observe(els.intro); }
    els.q.addEventListener('input', function () {
      fit();
      clearTimeout(typed);
      typed = setTimeout(function () { send('type', { text: els.q.value }); }, 140);
    });
    els.q.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && els.q.value.indexOf('\n') < 0) { e.preventDefault(); clearTimeout(typed); send('type', { text: els.q.value }); }
      if (e.key === 'Escape' && els.intro.hidden) send('close');
    });
    els.q.addEventListener('focus', sparkle);
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (!els.intro.hidden) { send('intro', { show: false }); setTimeout(function () { els.q.focus(); }, 0); }  // the how-to first, then the window
      else if (document.activeElement !== els.q) send('close');
    });
  }

  function fit() { els.q.style.height = 'auto'; els.q.style.height = Math.min(160, els.q.scrollHeight) + 'px'; liveFit(); }

  // the answer in the box: only beside one line of words, and only where there's room for both
  function liveFit() {
    if (!els.live) return;
    var F = V && V.found;
    els.q.style.paddingRight = '';
    var one = els.q.value.indexOf('\n') < 0 && els.q.scrollHeight <= 52;
    els.live.hidden = !(F && one && root.clientWidth >= 430);
    if (els.live.hidden) return;
    var w = els.live.offsetWidth + 18;
    els.q.style.paddingRight = w + 'px';
    if (els.q.scrollHeight > 52) { els.q.style.paddingRight = ''; els.live.hidden = true; }  // the words wrapped under it: the words win
  }

  // a number counting up to itself (once, when an answer lands)
  function roll(el, to, say) {
    if (REDUCE || !to) { el.textContent = say(to); return; }
    var t0 = null, dur = Math.min(600, 240 + to * 2);
    el.textContent = say(0);
    function step(t) {
      if (t0 === null) t0 = t;
      var k = Math.min(1, (t - t0) / dur);
      el.textContent = say(Math.round(to * (1 - Math.pow(1 - k, 3))));
      if (k < 1 && el.isConnected) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  // sparkles off anything in the window, drawn on the window so a redraw doesn't take them
  function burst(el, k) {
    if (REDUCE || !el || !el.isConnected) return;
    var a = el.getBoundingClientRect(), b = root.getBoundingClientRect();
    var x = a.left - b.left + a.width / 2, y = a.top - b.top + a.height / 2;
    for (var i = 0; i < k; i++) {
      var ang = (-150 + i * (300 / k)) * Math.PI / 180, d = 20 + (i % 3) * 9 + (k > 9 ? 8 : 0);
      var s = h('span', { cls: 'spk' + (i % 3 === 1 ? ' g' : '') });
      s.style.left = x + 'px'; s.style.top = y + 'px';
      s.style.setProperty('--sz', (5 + (i % 3) * 2) + 'px');
      s.style.setProperty('--dx', Math.round(Math.cos(ang) * d) + 'px');
      s.style.setProperty('--dy', Math.round(Math.sin(ang) * d) + 'px');
      s.style.animationDelay = (i * 16) + 'ms';
      root.appendChild(s);
      setTimeout(function (x) { return function () { if (x.parentNode) x.parentNode.removeChild(x); }; }(s), 1200);
    }
  }
  function twirl() {
    var mag = els.box.querySelector('.mag');
    if (!mag || REDUCE) return;
    mag.classList.remove('twirl'); void mag.getBoundingClientRect(); mag.classList.add('twirl');
  }
  function setText(t) { els.q.value = t; fit(); send('type', { text: t }); setTimeout(function () { els.q.focus(); }, 0); }

  // Sam: "should change size according to content": the window is as tall as what's in it
  // (the how-to's card when it's up), the glue holding it to the screen (ui/magic_window.py)
  var told = 0, asked = 0;
  function tall() {
    var hh = Math.ceil(root.getBoundingClientRect().height);
    var card = !els.intro.hidden && els.intro.firstChild;
    if (card) hh = Math.max(hh, Math.ceil(card.getBoundingClientRect().height) + 28);
    return hh;
  }
  function report() {
    if (asked) return;
    asked = requestAnimationFrame(function () {
      asked = 0;
      var hh = tall();
      if (Math.abs(hh - told) < 2) return;
      told = hh;
      send('size', { h: hh });
    });
  }

  // the joy: once a window, the star sends a few sparkles off when the box is picked
  function sparkle() {
    if (sparkled || REDUCE) return;
    sparkled = true;
    var mag = els.box.querySelector('.mag');
    if (mag) { mag.classList.remove('twirl'); void mag.getBoundingClientRect(); mag.classList.add('twirl'); }
    for (var i = 0; i < 9; i++) {
      var a = (-150 + i * 34) * Math.PI / 180, d = 22 + (i % 3) * 9;
      var s = h('span', { cls: 'spk' + (i % 3 === 1 ? ' g' : '') });
      s.style.left = '21px'; s.style.top = '20px';
      s.style.setProperty('--sz', (5 + (i % 3) * 2) + 'px');
      s.style.setProperty('--dx', Math.round(Math.cos(a) * d) + 'px');
      s.style.setProperty('--dy', Math.round(Math.sin(a) * d) + 'px');
      s.style.animationDelay = (i * 18) + 'ms';
      els.box.appendChild(s);
      setTimeout(function (x) { return function () { if (x.parentNode) x.parentNode.removeChild(x); }; }(s), 1100);
    }
  }

  function words(parts) {
    return (parts || []).map(function (p) { return p[1] === 'b' ? h('b', { text: p[0] }) : document.createTextNode(p[0]); });
  }

  function dests(cmd) {
    var ds = V.dests || [];
    if (ds.length < 2) {
      var d0 = ds[0];
      return d0 && d0.note ? h('span', { cls: 'dest-note', text: 'to ' + d0.name + ' · ' + d0.note }) : h('span', { cls: 'dest-note', text: 'to ' + (d0 ? d0.name : 'My plan') });
    }
    var seg = h('span', { cls: 'seg', role: 'group', 'aria-label': 'Which plan' }, ds.map(function (d) {
      return btn(d.key === V.dest ? 'on' : '', d.name, 'dest', { key: d.key }, { 'aria-pressed': d.key === V.dest ? 'true' : 'false' });
    }));
    var cur = ds.filter(function (d) { return d.key === V.dest; })[0] || ds[0];
    return h('span', { cls: 'row' }, [seg, cur && cur.note ? h('span', { cls: 'dest-note', text: ' ' + cur.note }) : null]);
  }

  function drawRows() {
    clear(els.rows);
    if (V.kind === 'plantext' && V.plantext) {
      var pt = V.plantext, nd = pt.dates.length, ne = pt.events.length;
      var lead = [h('b', { text: 'Add ' + plural(nd, 'date') + (ne ? ' and ' + plural(ne, 'event') : '') }),
        document.createTextNode((pt.span ? ', ' + pt.span : '') + ' · ' + plural(pt.n, 'card'))];
      els.rows.appendChild(h('div', { cls: 'do' }, [h('span', { cls: 'ic', text: '🗒' }), h('span', { cls: 'w' }, lead),
        dests(), btn('b pri', 'Add', 'plantext', {}, { disabled: V.busy || !nd && !ne ? true : null })]));
      var list = h('div', { cls: 'plines' });
      pt.dates.concat(pt.events.map(function (e) { return { label: e.label, name: '📝 ' + e.name, ev: true, day: e.day }; }))
        .sort(function (a, b) { return a.day < b.day ? -1 : a.day > b.day ? 1 : 0; })
        .forEach(function (x) {
          list.appendChild(h('div', {}, [h('span', { cls: 'd', text: x.label }), h('span', { text: x.name + (x.due ? ' · due ' + x.due : '') }),
            x.ev ? null : h('span', { cls: 'n' + (x.n ? '' : ' none'), text: x.n ? plural(x.n, 'card') : 'no cards here' })]));
        });
      els.rows.appendChild(list);
      if (pt.none) els.rows.appendChild(h('div', { cls: 'lines', text: plural(pt.none, 'date') + ' with no cards here yet' }));
      (pt.errors || []).forEach(function (e) { els.rows.appendChild(h('div', { cls: 'lines', text: e })); });
      return;
    }
    (V.rows || []).forEach(function (r) {
      var kids = [h('span', { cls: 'ic', text: r.done ? '✓' : r.icon }), h('span', { cls: 'w' }, words(r.words).concat(r.note ? [h('span', { cls: 'note', text: r.note })] : []))];
      if (r.choose && !r.done) kids.push(dests());
      if (r.done) kids.push(btn('b', 'Undo', 'undo', {}));
      else kids.push(btn(r.k === 'before' ? 'b' : 'b pri', r.verb, 'act', { i: r.i }, { disabled: V.busy ? true : null }));
      els.rows.appendChild(h('div', { cls: 'do' + (r.done ? ' done' : '') }, kids));
    });
  }

  // one row a typed topic (Sam: "combine things with similar names so long as the tag goes all the way to the end"):
  // its tick, its cards, its tags' count opening its tree; Also under it, the near names a tap takes in
  function drawTopics() {
    clear(els.topics);
    var fresh = {};
    (V.topics || []).forEach(function (tp) {
      var key = 't:' + tp.name + ':' + tp.seg;
      fresh[key] = 1;
      var r1 = h('div', { cls: 'tr1' });
      if (tp.join) r1.appendChild(h('span', { cls: 'join', text: 'with', title: 'Only the cards in both' }));
      var cb = null;
      if (tp.can) {
        cb = h('input', { type: 'checkbox', 'aria-label': (tp.on ? 'Leave out ' : 'Take in ') + tp.name, onchange: function () { send('seg', { seg: tp.seg }); } });
        cb.checked = !!tp.on;
      }
      r1.appendChild(h('label', { cls: 'tl' + (tp.can ? '' : ' mu') }, [cb, h('b', { text: tp.name })]));
      if (tp.on) r1.appendChild(h('span', { cls: 'tn mu', text: tp['in'] !== null && tp['in'] !== undefined ? n(tp['in']) + ' of ' + plural(tp.n, 'card') : plural(tp.n, 'card') }));
      r1.appendChild(h('span', { cls: 'sp' }));
      if (tp.ntags) r1.appendChild(btn('tg', plural(tp.ntags, 'tag') + (tp.open ? ' ▴' : ' ▾'), 'open', { seg: tp.seg }, { 'aria-expanded': tp.open ? 'true' : 'false' }));
      var row = h('div', { cls: 'topic' + (seen[key] ? '' : ' pop') }, [r1]);
      if ((tp.also || []).length) {
        row.appendChild(h('div', { cls: 'also' }, [h('span', { cls: 'mu', text: tp.can ? 'Also' : 'Which?' })].concat(tp.also.map(function (a) {
          return h('button', { type: 'button', cls: 'ad', title: 'Take it in', onclick: function () { send('chip', { i: a.i }); } }, [a.name + ' ', h('small', { text: n(a.n) })]);
        }))));
      }
      if (tp.open && tp.tree) row.appendChild(drawTree(tp));
      els.topics.appendChild(row);
    });
    var bits = [(V.neg || []).length ? 'Leaving out ' + V.neg.join(', ') : '', V.limit ? 'Taking ' + n(V.limit) : ''].filter(Boolean);
    if (bits.length) els.topics.appendChild(h('div', { cls: 'tx mu', text: bits.join(' · ') }));
    seen = fresh;
  }

  // a topic's tags under where each is from, each to its last part (Sam: "the tag tree to go all the way to the
  // last tag"): a resource's tick takes all its tags in or out, each tag's tick just that one
  function drawTree(tp) {
    var box = h('div', { cls: 'tags' });
    tp.tree.forEach(function (g, gi) {
      var ts = g.tags.map(function (t) { return t.t; });
      var ons = g.tags.filter(function (t) { return t.on; }).length;
      var top = g.res && g.tags.length > 1;
      if (top) {
        var all = h('input', { type: 'checkbox', onchange: function () { send('tags', { ts: ts, on: all.checked }); } });
        all.checked = ons === g.tags.length;
        all.indeterminate = ons > 0 && ons < g.tags.length;
        box.appendChild(h('label', { cls: 'rs' + (gi ? ' sep' : '') }, [all, h('span', { cls: 'p', text: g.res }), h('span', { cls: 'n', text: n(g.n) })]));
      }
      g.tags.forEach(function (t) {
        var cb = h('input', { type: 'checkbox', onchange: function () { send('tag', { t: t.t }); } });
        cb.checked = !!t.on;
        var words = top ? [t.path] : (g.res && t.path ? [h('b', { text: g.res }), ' · ' + t.path] : [g.res || t.path]);
        box.appendChild(h('label', { cls: top ? 'in' : (gi ? 'sep' : ''), title: t.t }, [cb, h('span', { cls: 'p' }, words), h('span', { cls: 'n', text: n(t.n) })]));
      });
    });
    return box;
  }

  // the filters, one quiet line under the box, always there (Sam: "should show more of the time")
  function drawFilters() {
    clear(els.filters);
    els.filters.className = 'only';
    els.filters.appendChild(h('span', { cls: 'ol', text: 'Only' }));
    (V.filters || []).forEach(function (f) {
      els.filters.appendChild(btn('ot' + (f.on ? ' on' : ''), f.label, 'filter', { k: f.k }, { 'aria-pressed': f.on ? 'true' : 'false' }));
    });
    clear(els.recent);
    if ((V.recent || []).length) {
      els.recent.appendChild(h('span', { cls: 'lab', text: 'Recent' }));
      V.recent.forEach(function (t) {
        // its words are its own (never what's on the button: that's cut to fit, magic.css)
        els.recent.appendChild(btn('chip', t, 'type', { text: t }, { title: t, onclick: function () { els.q.value = t; fit(); send('type', { text: t }); } }));
      });
    }
    els.recent.hidden = !(V.recent || []).length;
  }

  // what it found, each card once by what Study now would do with it, how long that is at my pace
  function drawFound() {
    clear(els.found); clear(els.lines);
    var F = V.found, Q = V.qids, t = V.count;
    (V.lines || []).forEach(function (l) { els.lines.appendChild(h('div', { text: l })); });
    if (Q && Q.ask && (Q.banks || []).length > 1) {
      // QBank QIDs: two banks have these numbers; which (the one with most, till I pick)
      var bank = h('select', { cls: 'b', 'aria-label': 'Question bank', onchange: function () { send('bank', { name: bank.value }); } },
        Q.banks.map(function (b) { return h('option', { value: b, text: b }); }));
      bank.value = Q.bank || Q.banks[0];
      els.lines.appendChild(h('div', { cls: 'bank' }, [h('span', { text: 'Question bank' }), bank]));
    }
    drawQTopics(Q);
    els.found.className = 'found';
    clear(els.live);
    if (!F) {
      landed = '';
      liveFit();
      var N = V.none, means = (N && N.mean) || [], waits = (N && N.waiting) || [];
      if (means.length || waits.length) {
        // 3.9.11: nothing found is a way on: the tag it nearly was, and what's waiting today (the line above says what wasn't found)
        els.found.hidden = false;
        els.found.className = 'found none';
        var fresh = meant !== V.text;
        meant = V.text;
        if (means.length) {
          els.found.appendChild(h('div', { cls: 'dym' + (fresh && !REDUCE ? ' wob' : '') }, [h('span', { cls: 'mu', text: 'Did you mean' })].concat(means.map(function (m) {
            return h('span', { cls: 'm1' }, [h('button', { type: 'button', cls: 'mean', text: m.name + '?', onclick: function () { twirl(); setText(m.text); } }),
              h('span', { cls: 'mu tn', text: plural(m.n, 'card') })]);
          }))));
        }
        if (waits.length) {
          els.found.appendChild(h('div', { cls: 'recent' }, [h('span', { cls: 'lab', text: means.length ? 'Or' : 'Waiting today' })].concat(waits.map(function (w) {
            return h('button', { type: 'button', cls: 'chip', onclick: function () { setText(w.text); } }, [w.label + ' ', h('small', { cls: 'tn', text: n(w.n) })]);
          }))));
        }
        return;
      }
      meant = null;
      els.found.hidden = !(t && !t.n && !(V.kind === 'empty' && !V.picked));
      if (!els.found.hidden) els.found.appendChild(h('span', { cls: 'mu', text: 'No cards for that here.' }));
      return;
    }
    meant = null;
    els.found.hidden = false;
    // 3.9.11, it answers while you type: when a new answer lands its count rolls up (here and in the box), the bar
    // grows and the star twinkles, more for a big find; the same answer drawn again is still
    var key = (V.q || '') + '|' + F.n, lands = key !== landed;
    landed = key;
    var cnt = h('b', { text: Q && Q.q ? plural(Q.q, 'question') : plural(F.n, 'card') });
    var lb = h('b', { cls: 'tn', text: n(F.n) });
    els.live.appendChild(lb);
    els.live.appendChild(document.createTextNode(' ' + (F.n === 1 ? 'card' : 'cards') + (F.time ? ' · ' + F.time : '')));
    liveFit();
    if (lands && !REDUCE) {
      if (!(Q && Q.q)) roll(cnt, F.n, function (k) { return plural(k, 'card'); });
      roll(lb, F.n, n);
      setTimeout(function () { if (landed === key) { twirl(); burst(els.box.querySelector('.mag'), F.n >= 100 ? 14 : 7); } }, 320);
    }
    els.found.appendChild(h('div', { cls: 'fh' }, [cnt,
      Q && Q.q ? h('span', { cls: 'mu', text: '· ' + plural(F.n, 'card') }) : null, h('span', { cls: 'sp' }), btn('link', 'Browse', 'browse', {})]));
    var tot = Math.max(1, F.due + F.new + F.notdue);
    function seg(c, k) { return k ? h('i', { cls: c, style: 'flex-basis:' + Math.max(0.8, 100 * k / tot) + '%' }) : null; }
    els.found.appendChild(h('div', { cls: 'bar' + (lands && !REDUCE ? ' grow' : ''), 'aria-hidden': 'true' }, [seg('d', F.due), seg('nw', F.new), seg('s', F.notdue)]));
    var key = [];
    if (F.due) key.push(h('span', {}, [h('i', { cls: 'd' }), h('b', { text: n(F.due) }), ' due now']));
    if (F.new) key.push(h('span', {}, [h('i', { cls: 'nw' }), h('b', { text: n(F.new) }), ' new', F.susp_new ? h('span', { cls: 'mu', text: ' · ' + n(F.susp_new) + ' suspended' }) : null]));
    if (F.notdue) key.push(h('span', {}, [h('i', { cls: 's' }), h('b', { text: n(F.notdue) }), ' not due yet']));
    els.found.appendChild(h('div', { cls: 'key' }, key));
    if (F.time) {
      els.found.appendChild(h('div', { cls: 'nt' }, [(F.all ? 'All ' + n(F.study) : 'New and due') + ': ', h('b', { text: F.time }),
        F.usual ? ' · you usually do ' + F.usual + ' a day' : '']));
    }
    var xs = [];
    if (F.leech) xs.push(plural(F.leech, 'leech', 'leeches') + ' left out');
    (F.infilt || []).forEach(function (x) { xs.push(n(x[1]) + ' already in ' + x[0]); });
    xs.forEach(function (x) { els.found.appendChild(h('div', { cls: 'xl', text: x })); });
  }

  // Sam's four: Study now, Schedule ahead, Make a new filtered deck, Unsuspend; the one that fits filled
  function drawTiles() {
    clear(els.tiles);
    var T = V.tiles;
    els.tiles.hidden = !T;
    if (!T) { making = false; return; }
    if (madeFor !== T.keep) { making = false; madeFor = T.keep; }
    function tile(k, title, sub, on, extra) {
      return h('button', Object.assign({ type: 'button', cls: 'tile' + (T.rec === k ? ' rec' : ''), onclick: on }, extra || {}),
        [h('b', { text: title }), h('span', { cls: 'mu', text: sub })]);
    }
    els.tiles.appendChild(h('div', { cls: 'tl4' }, [
      tile('study', 'Study now', plural(T.study, 'card'), function () { send('study', {}); },
        { disabled: !T.study || V.busy ? true : null, title: T.deck }),
      tile('days', 'Schedule ahead', T.days ? plural(T.days, 'day') : 'pick days', function () { send('days', { show: V.mode !== 'days' }); },
        { 'aria-expanded': V.mode === 'days' ? 'true' : 'false' }),
      tile('keep', 'Make a new filtered deck', '“' + T.keep + '”', function () { making = !making; drawTiles(); report(); },
        { 'aria-expanded': making ? 'true' : 'false' }),
      tile('uns', 'Unsuspend', T.uns ? plural(T.uns, 'card') : 'none suspended', function () { send('uns', {}); },
        { disabled: !T.uns || V.busy ? true : null })]));
    if (making) {
      var kn = h('input', { cls: 'kname', type: 'text', maxlength: '80', 'aria-label': 'The deck’s name', value: T.keep });
      var go = function () { making = false; send('keep', { name: kn.value }); };
      kn.addEventListener('keydown', function (e) { if (e.key === 'Enter') go(); if (e.key === 'Escape') { e.stopPropagation(); making = false; drawTiles(); report(); } });
      els.tiles.appendChild(h('div', { cls: 'mk' }, [h('span', { cls: 'mu', text: 'Name' }), kn,
        h('button', { type: 'button', cls: 'b pri', text: 'Make', onclick: go })]));
      setTimeout(function () { kn.focus(); kn.select(); }, 0);
    }
    var rest = [];
    if ((V.filtered || []).length) {
      var addto = h('select', { cls: 'lk', 'aria-label': 'Add to a filtered deck', onchange: function () { if (addto.value) send('addto', { did: addto.value }); } },
        [h('option', { value: '', text: 'Add to a filtered deck…' })].concat(V.filtered.map(function (d) { return h('option', { value: String(d.did), text: d.name }); })));
      rest.push(addto);
    }
    if (T.all) rest.push(btn('link', 'Study all ' + n(T.all), 'study', { all: true }, { title: 'With the ' + n(T.all - T.study) + ' not due yet' }));
    if (rest.length) els.tiles.appendChild(h('div', { cls: 'rest' }, rest));
  }

  // QBank QIDs' Their topics (3.9.5): the map's parts the questions are in, each a Study of what I missed there
  function drawQTopics(Q) {
    clear(els.tops);
    var rows = (Q && Q.topics) || [];
    els.tops.hidden = !rows.length;
    if (!rows.length) return;
    els.tops.appendChild(h('div', { cls: 'th', text: 'Their topics' }));
    rows.forEach(function (r) {
      els.tops.appendChild(h('div', { cls: 'tr' }, [h('span', { cls: 'w' }, [h('b', { text: r.name }), h('span', { cls: 'mu', text: r.line })]),
        r.missed ? btn('link', 'Study', 'topic', { i: r.i }, { title: 'The ' + n(r.missed) + ' you missed' }) : null]));
    });
    if (Q.more) els.tops.appendChild(h('div', { cls: 'mu', style: 'font-size:12px', text: Q.more }));
  }

  function drawDays() {
    clear(els.pod);
    var D = V.days, show = V.mode === 'days' && D && V.count && V.count.n;
    els.pod.hidden = !show;
    els.pod.className = 'pod';
    if (!show) { dropped = {}; return; }
    els.pod.appendChild(h('div', { cls: 'ph' }, [h('b', { text: 'Schedule ahead' })]));
    var grid = h('div', { cls: 'days', role: 'group', 'aria-label': 'Days' });
    // 3.9.11: each picked day wears its share ("+5", dropping in when it's new or changes), and its count is what it would be
    var share = {}, now = {};
    (D.each || []).forEach(function (e) { share[e.iso] = e.n; });
    D.list.forEach(function (d) {
      var add = share[d.iso] || 0, tot = (d.load || 0) + add;
      if (add) now[d.iso] = add;
      grid.appendChild(h('button', { type: 'button', cls: 'day' + (d.on ? ' on' : '') + (d.today ? ' tdy' : '') + (d.light ? ' light' : ''),
        'aria-pressed': d.on ? 'true' : 'false', title: d.light ? 'A light day' : null,
        'aria-label': d.dow + ' ' + d.d + ' ' + d.mon + (d.load ? ', ' + d.load + ' due' : '') + (add ? ', ' + add + ' more from this' : '') + (d.light ? ', a light day' : ''),
        onclick: function () { send('day', { iso: d.iso }); } }, [
        h('span', { cls: 'dw', text: d.dow }), h('span', { cls: 'dn', text: String(d.d) }), h('span', { cls: 'dl', text: tot ? n(tot) + ' due' : '–' }),
        add ? h('span', { cls: 'plus' + (dropped[d.iso] !== add && !REDUCE ? ' drop' : ''), text: '+' + n(add) }) : null]));
    });
    dropped = now;
    els.pod.appendChild(grid);
    // 3.9.9: a stretch longer than these two weeks, filled in: how many days (or to my exam's eve), the weekdays to skip
    var F = D.fill || {};
    if (F.on) {
      var nIn = h('input', { cls: 'fn', type: 'number', min: '2', max: String(F.max || 90), value: String(F.n), 'aria-label': 'How many days',
        onchange: function () { send('fill', { n: parseInt(nIn.value, 10) || F.n }); } });
      var dows = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map(function (w, i) {
        var off = (F.skip || []).indexOf(i) >= 0;
        return h('button', { type: 'button', cls: 'dw' + (off ? '' : ' on'), 'aria-pressed': off ? 'false' : 'true', text: w,
          title: off ? 'Skipped' : 'A study day', onclick: function () { send('fillskip', { dow: i }); } });
      });
      els.pod.appendChild(h('div', { cls: 'fill' }, [h('span', { text: 'From tomorrow for' }), nIn, h('span', { text: 'days, to ' + F.to_label }),
        F.eve && F.eve_label !== F.to_label ? btn('link', 'To my exam’s eve', 'fill', { to: F.eve }) : null,
        h('span', { cls: 'sp' }), btn('link', 'Pick days', 'fill', { off: true })]));
      els.pod.appendChild(h('div', { cls: 'fill', role: 'group', 'aria-label': 'Study days' }, dows));
    } else {
      els.pod.appendChild(h('div', { cls: 'fill' }, [h('span', { cls: 'mu', text: 'More than two weeks?' }),
        btn('link', 'Go longer', 'fill', { n: 30 }), F.eve ? btn('link', 'To my exam’s eve, ' + F.eve_label, 'fill', { to: F.eve }) : null]));
    }
    var name = h('input', { cls: 'kname', type: 'text', maxlength: '60', 'aria-label': 'The set’s name', value: D.name,
      onchange: function () { send('dayname', { name: name.value }); } });
    els.pod.appendChild(h('div', { cls: 'podrow' }, [h('label', { text: 'Name' }), name, dests()]));
    var each = D.each || [];
    if (each.length) {
      els.pod.appendChild(h('div', { cls: 'split', text: each.length === 1 ? plural(each[0].n, 'card')
        : each.length > 8 ? plural(each.length, 'day') + ' · about ' + plural(F.per || each[0].n, 'card') + ' a day'
        : each.map(function (e) { return n(e.n); }).join(' · ') + ' cards' }));
    }
    if (D.note) els.pod.appendChild(h('div', { cls: 'split', text: D.note }));
    var go = 'Put on ' + (each.length ? plural(each.length, 'day') : 'days');
    els.pod.appendChild(h('div', { cls: 'acts' }, [btn('b', 'Cancel', 'days', { show: false }), h('span', { cls: 'sp' }),
      h('button', { type: 'button', cls: 'b pri', text: go, disabled: !each.length || V.busy || !V.signed_in ? true : null,
        onclick: function () {
          [].slice.call(grid.querySelectorAll('.day.on')).slice(0, 7).forEach(function (d, i) { setTimeout(function () { burst(d, 5); }, i * 70); });
          send('dayname', { name: name.value }); send('put', {}); } })]));
    if (!V.signed_in) els.pod.appendChild(h('div', { cls: 'split', text: 'Sign in to put cards on a plan.' }));
  }

  function drawSaid() {
    clear(els.said);
    if (!V.said || !V.said.text) return;
    els.said.appendChild(h('span', { text: V.said.text }));
    if (V.said.open) els.said.appendChild(btn('link', 'Open the plan', 'open_plan', { pid: V.said.open }));
    if (V.said.undo) els.said.appendChild(btn('link', 'Undo', 'undo', {}));
  }

  function tryChip(t, label) {
    return h('button', { type: 'button', cls: 'chip', text: label || t, onclick: function () { els.q.value = t; fit(); send('try', { text: t }); setTimeout(function () { els.q.focus(); }, 0); } });
  }

  function drawIntro() {
    clear(els.intro);
    var H = V.intro && V.howto;
    els.intro.hidden = !H;
    if (!H) return;
    // the how-to's words are magic.HOWTO's, the same as the Decks screen's first-time card (board.MAGIC_HOWTO_JS)
    var card = h('div', { cls: 'ic2' });
    var t = h('div', { cls: 't' });
    t.innerHTML = MAG;
    t.appendChild(h('b', { text: 'Magic search' }));
    card.appendChild(t);
    card.appendChild(h('p', { cls: 'lede', text: H.lede }));
    var how = h('div', { cls: 'how' });
    (H.parts || []).forEach(function (x) {
      var tries = (x['try'] || []).map(function (q, i) { return tryChip(q, (x.label || [])[i]); });
      how.appendChild(h('div', {}, [h('h4', { text: x.t }), h('p', { text: x.w }), x.code ? h('code', { text: x.code }) : null,
        tries.length ? h('div', { cls: 'try' }, tries) : null]));
    });
    card.appendChild(how);
    card.appendChild(h('div', { cls: 'then' }, [h('b', { text: 'Then, with what it finds' }),
      h('ul', {}, (H.then || []).map(function (x) { return h('li', { text: x }); }))]));
    card.appendChild(h('div', { cls: 'foot' }, [h('span', { cls: 'mu', style: 'font-size:12px', text: H.foot }),
      h('button', { type: 'button', cls: 'b pri', text: 'Got it', onclick: function () { send('intro', { show: false }); setTimeout(function () { els.q.focus(); }, 0); } })]));
    els.intro.appendChild(card);
  }

  function show(v) {
    V = v;
    if (!root) build();
    if (document.activeElement !== els.q && els.q.value !== (v.text || '')) { els.q.value = v.text || ''; fit(); }
    clear(els.deck);
    (v.decks || []).forEach(function (d) { els.deck.appendChild(h('option', { value: String(d.did), text: d.name })); });
    els.deck.value = String(v.did || '');
    els.deck.hidden = (v.decks || []).length < 2;
    drawRows(); drawFilters(); drawTopics(); drawFound(); drawTiles(); drawDays(); drawSaid(); drawIntro();
    report();
  }

  function start(v, isPreview) {
    preview = !!isPreview;
    show(v);
    if (!v.intro) setTimeout(function () { els.q.focus(); }, 30);
    send('ready');
  }

  return { start: start, show: show, sparkle: sparkle, _send: send };
})();
