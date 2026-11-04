/* Magic search's page (3.9.7): it draws the view magic_flow.Search sends
   (dcMagic.show) and says each click as "dcmagic:" + JSON through Anki's
   bridge. Every word from the view is set as text, never as markup. */
var dcMagic = (function () {
  'use strict';
  var V = null, root = null, els = {}, typed = null, sparkled = false, seen = {}, preview = false;
  var REDUCE = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function send(cmd, args) {
    var msg = 'dcmagic:' + JSON.stringify(Object.assign({ cmd: cmd }, args || {}));
    if (preview) { (window.dcMagicSent = window.dcMagicSent || []).push(msg); return; }
    if (window.pycmd) window.pycmd(msg);
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
    els.box = box;
    ['rows', 'chips', 'tags', 'filters', 'res', 'lines', 'tops', 'acts', 'where', 'pod', 'said', 'recent'].forEach(function (k) { els[k] = h('div', { cls: k }); });
    els.intro = h('div', { cls: 'intro', role: 'dialog', 'aria-label': 'Magic search' });
    [head, box, els.rows, els.chips, els.tags, els.filters, els.recent, els.res, els.lines, els.tops, els.acts, els.where, els.pod, els.said, els.intro]
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

  function fit() { els.q.style.height = 'auto'; els.q.style.height = Math.min(160, els.q.scrollHeight) + 'px'; }

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
      if (pt.none) els.rows.appendChild(h('div', { cls: 'lines', text: plural(pt.none, 'date') + (pt.none === 1 ? ' has' : ' have') + ' no cards in this deck; it’s added, and fills in when its tag does.' }));
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

  function drawChips() {
    clear(els.chips);
    var fresh = {}, termOf = {}, last = null;
    (V.terms || []).forEach(function (t, i) { t.forEach(function (sg) { termOf[sg] = t.length > 1 ? i : null; }); });
    (V.chips || []).forEach(function (c) {
      // "both A and B", A AND B, A with B: the cards in both, a quiet "with" between their chips
      if (last !== null && c.seg !== last && termOf[c.seg] !== null && termOf[c.seg] !== undefined && termOf[c.seg] === termOf[last]) {
        els.chips.appendChild(h('span', { cls: 'brk', 'aria-hidden': 'true' }));  // the next topic on a line of its own, "with" first
        els.chips.appendChild(h('span', { cls: 'join', text: 'with', title: 'Only the cards in both' }));
      }
      last = c.seg;
      var key = 'g:' + c.name + ':' + c.seg;
      fresh[key] = 1;
      var g = h('span', { cls: 'grp' + (c.on ? ' on' : '') + (seen[key] ? '' : ' pop') }, [
        h('button', { type: 'button', cls: 'g1', 'aria-pressed': c.on ? 'true' : 'false', title: c.on ? 'Leave it out' : 'Take it in',
          onclick: function () { send('chip', { i: c.i }); } }, [c.name + ' ', h('small', { text: n(c.n) })])]);
      if (c.tags > 1) g.appendChild(btn('g2' + (c.open ? ' open' : ''), plural(c.tags, 'tag'), 'open', { i: c.i }, { 'aria-expanded': c.open ? 'true' : 'false' }));
      els.chips.appendChild(g);
    });
    (V.neg || []).forEach(function (name) {
      els.chips.appendChild(h('span', { cls: 'grp neg' }, [h('span', { cls: 'g1', style: 'font-size:12.5px;padding:3px 10px', text: 'not ' + name })]));
    });
    if (V.limit) els.chips.appendChild(h('span', { cls: 'lim', text: 'taking ' + n(V.limit) }));
    seen = fresh;
    clear(els.tags);
    var open = (V.chips || []).filter(function (c) { return c.open && c.list && c.list.length; })[0];
    els.tags.hidden = !open;
    if (open) {
      // a chip's tags under where each is from (Sam: "the overarching resource is an important thing"):
      // a resource's tick takes all its tags in or out, each tag's tick just that one
      els.tags.appendChild(h('div', { cls: 'th' }, [h('span', { text: open.name + ': ' + plural(open.tags, 'tag') }), h('span', { text: 'untick what to leave out' })]));
      open.list.forEach(function (g, gi) {
        var ts = g.tags.map(function (t) { return t.t; });
        var ons = g.tags.filter(function (t) { return t.on; }).length;
        var top = g.res && g.tags.length > 1;
        if (top) {
          var all = h('input', { type: 'checkbox', onchange: function () { send('tags', { ts: ts, on: all.checked }); } });
          all.checked = ons === g.tags.length;
          all.indeterminate = ons > 0 && ons < g.tags.length;
          els.tags.appendChild(h('label', { cls: 'rs' + (gi ? ' sep' : '') }, [all, h('span', { cls: 'p', text: g.res }), h('span', { cls: 'n', text: n(g.n) })]));
        }
        g.tags.forEach(function (t) {
          var cb = h('input', { type: 'checkbox', onchange: function () { send('tag', { t: t.t }); } });
          cb.checked = !!t.on;
          var words = top ? t.path : (g.res && t.path ? [h('b', { text: g.res }), ' \u00b7 ' + t.path] : [g.res || t.path]);
          els.tags.appendChild(h('label', { cls: top ? 'in' : (gi ? 'sep' : ''), title: t.t },
            [cb, h('span', { cls: 'p' }, typeof words === 'string' ? [words] : words), h('span', { cls: 'n', text: n(t.n) })]));
        });
      });
    }
  }

  function drawFilters() {
    clear(els.filters);
    (V.filters || []).forEach(function (f) {
      els.filters.appendChild(btn('chip' + (f.on ? ' on' : ''), f.label, 'filter', { k: f.k }, { 'aria-pressed': f.on ? 'true' : 'false' }));
    });
    clear(els.recent);
    if ((V.recent || []).length) {
      els.recent.appendChild(h('span', { cls: 'lab', text: 'Recent' }));
      V.recent.forEach(function (t) { els.recent.appendChild(btn('chip', t, 'type', { text: t }, { onclick: null })); });
      Array.prototype.forEach.call(els.recent.querySelectorAll('button'), function (b) {
        b.onclick = function () { els.q.value = b.textContent; fit(); send('type', { text: b.textContent }); };
      });
    }
    els.recent.hidden = !(V.recent || []).length;
  }

  function drawRes() {
    clear(els.res); clear(els.lines); clear(els.acts); clear(els.tops); clear(els.where);
    var t = V.count, Q = V.qids;
    (V.lines || []).forEach(function (l) { els.lines.appendChild(h('div', { text: l })); });
    if (Q && Q.ask && (Q.banks || []).length > 1) {
      // QBank QIDs: two banks have these numbers; which (the one with most, till I pick)
      var bank = h('select', { cls: 'b', 'aria-label': 'Question bank', onchange: function () { send('bank', { name: bank.value }); } },
        Q.banks.map(function (b) { return h('option', { value: b, text: b }); }));
      bank.value = Q.bank || Q.banks[0];
      els.lines.appendChild(h('div', { cls: 'bank' }, [h('span', { text: 'Question bank' }), bank]));
    }
    drawTopics(Q);
    if (!t) return;
    if (!t.n) {
      els.res.appendChild(h('span', { cls: 'mu', text: V.kind === 'empty' && !V.picked ? '' : 'No cards for that here.' }));
      return;
    }
    var bits = [t.new ? n(t.new) + ' new' : '', t.seen ? n(t.seen) + ' seen' : '', t.susp ? n(t.susp) + ' suspended' : '',
      t.due ? n(t.due) + ' due' : '', t.leech ? plural(t.leech, 'leech', 'leeches') : ''].filter(Boolean).join(' · ');
    if (Q && Q.q) bits = plural(t.n, 'card') + (bits ? ' · ' + bits : '');  // QBank QIDs: the questions first, as its window said
    els.res.appendChild(h('b', { text: Q && Q.q ? plural(Q.q, 'question') : plural(t.n, 'card') }));
    if (bits) els.res.appendChild(h('span', { cls: 'bits', text: bits }));
    els.res.appendChild(btn('link', 'Browse', 'browse', {}));
    var k = V.how === 'all' ? t.all : t.nd;
    els.acts.appendChild(btn('b pri', 'Study now · ' + n(k), 'study', {}, { disabled: !k || V.busy ? true : null }));
    var how = h('select', { cls: 'b', 'aria-label': 'Which to study', onchange: function () { send('how', { how: how.value }); } },
      [h('option', { value: 'nd', text: 'New and due' }), h('option', { value: 'all', text: 'All of them' })]);
    how.value = V.how;
    els.acts.appendChild(how);
    var addto = h('select', { cls: 'b', 'aria-label': 'Add to a filtered deck', onchange: function () {
      if (addto.value) send('addto', { did: addto.value }); } },
      [h('option', { value: '', text: 'Add to a filtered deck…' })].concat((V.filtered || []).map(function (d) { return h('option', { value: String(d.did), text: d.name }); })));
    if ((V.filtered || []).length) els.acts.appendChild(addto);
    if (t.susp) els.acts.appendChild(btn('b', 'Unsuspend ' + n(t.susp - Math.min(t.susp, t.leech)), 'uns', {}, { disabled: V.busy ? true : null }));
    els.acts.appendChild(h('span', { cls: 'sp' }));
    els.acts.appendChild(btn('b', 'Put on days…', 'days', { show: V.mode !== 'days' }, { 'aria-expanded': V.mode === 'days' ? 'true' : 'false' }));
    // keep it: a filtered deck that stays, named from the chips
    var keepRow = h('div', { cls: 'acts', style: 'width:100%' });
    var kn = h('input', { cls: 'kname', type: 'text', maxlength: '80', 'aria-label': 'The deck’s name', value: V.name });
    keepRow.appendChild(h('span', { cls: 'keep' }, [document.createTextNode('Keep as a filtered deck')]));
    keepRow.appendChild(kn);
    keepRow.appendChild(h('button', { cls: 'b', type: 'button', text: 'Keep', onclick: function () { send('keep', { name: kn.value }); } }));
    kn.addEventListener('keydown', function (e) { if (e.key === 'Enter') send('keep', { name: kn.value }); });
    els.acts.appendChild(keepRow);
    if (V.where && k) els.where.appendChild(h('span', { text: V.where }));
  }

  // QBank QIDs' Their topics (3.9.5): the map's parts the questions are in, each a Study of what I missed there
  function drawTopics(Q) {
    var rows = (Q && Q.topics) || [];
    els.tops.hidden = !rows.length;
    if (!rows.length) return;
    els.tops.appendChild(h('div', { cls: 'th', text: 'Their topics' }));
    rows.forEach(function (r) {
      els.tops.appendChild(h('div', { cls: 'tr' }, [h('span', { cls: 'w' }, [h('b', { text: r.name }), h('span', { cls: 'mu', text: r.line })]),
        r.missed ? btn('link', 'Study', 'topic', { i: r.i }, { title: 'A filtered deck of the ' + plural(r.missed, 'card') + ' you missed there' }) : null]));
    });
    if (Q.more) els.tops.appendChild(h('div', { cls: 'mu', style: 'font-size:12px', text: Q.more }));
  }

  function drawDays() {
    clear(els.pod);
    var D = V.days, show = V.mode === 'days' && D && V.count && V.count.n;
    els.pod.hidden = !show;
    els.pod.className = 'pod';
    if (!show) return;
    els.pod.appendChild(h('div', { cls: 'ph' }, [h('b', { text: 'Put on days' }), h('span', { cls: 'mu', style: 'font-size:12px', text: 'Tap as many as you like. Under each, what’s due that day; green, the light ones.' })]));
    var grid = h('div', { cls: 'days', role: 'group', 'aria-label': 'Days' });
    D.list.forEach(function (d) {
      grid.appendChild(h('button', { type: 'button', cls: 'day' + (d.on ? ' on' : '') + (d.today ? ' tdy' : '') + (d.light ? ' light' : ''),
        'aria-pressed': d.on ? 'true' : 'false', title: d.light ? 'A light day' : null,
        'aria-label': d.dow + ' ' + d.d + ' ' + d.mon + (d.load ? ', ' + d.load + ' due' : '') + (d.light ? ', a light day' : ''),
        onclick: function () { send('day', { iso: d.iso }); } }, [
        h('span', { cls: 'dw', text: d.dow }), h('span', { cls: 'dn', text: String(d.d) }), h('span', { cls: 'dl', text: d.load ? n(d.load) + ' due' : '–' })]));
    });
    els.pod.appendChild(grid);
    var name = h('input', { cls: 'kname', type: 'text', maxlength: '60', 'aria-label': 'The set’s name', value: D.name,
      onchange: function () { send('dayname', { name: name.value }); } });
    els.pod.appendChild(h('div', { cls: 'podrow' }, [h('label', { text: 'Name' }), name, dests()]));
    var each = D.each || [];
    if (each.length) {
      els.pod.appendChild(h('div', { cls: 'split', text: each.length === 1 ? plural(each[0].n, 'card') + ' on that day.'
        : 'Split over ' + each.length + ' days: ' + each.map(function (e) { return n(e.n); }).join(' · ') + ' cards, in the deck’s order.' }));
    }
    var go = 'Put on ' + (each.length ? plural(each.length, 'day') : 'days');
    els.pod.appendChild(h('div', { cls: 'acts' }, [btn('b', 'Cancel', 'days', { show: false }), h('span', { cls: 'sp' }),
      h('button', { type: 'button', cls: 'b pri', text: go, disabled: !each.length || V.busy || !V.signed_in ? true : null,
        onclick: function () { send('dayname', { name: name.value }); send('put', {}); } })]));
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
    drawRows(); drawChips(); drawFilters(); drawRes(); drawDays(); drawSaid(); drawIntro();
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
