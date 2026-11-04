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
    ['rows', 'chips', 'tags', 'filters', 'res', 'lines', 'acts', 'pod', 'said', 'recent'].forEach(function (k) { els[k] = h('div', { cls: k }); });
    els.intro = h('div', { cls: 'intro', role: 'dialog', 'aria-label': 'Magic search' });
    [head, box, els.rows, els.chips, els.tags, els.filters, els.recent, els.res, els.lines, els.acts, els.pod, els.said, els.intro]
      .forEach(function (e) { root.appendChild(e); });
    els.q.addEventListener('input', function () {
      fit();
      clearTimeout(typed);
      typed = setTimeout(function () { send('type', { text: els.q.value }); }, 140);
    });
    els.q.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && els.q.value.indexOf('\n') < 0) { e.preventDefault(); clearTimeout(typed); send('type', { text: els.q.value }); }
      if (e.key === 'Escape') send('close');
    });
    els.q.addEventListener('focus', sparkle);
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && document.activeElement !== els.q) send('close'); });
  }

  function fit() { els.q.style.height = 'auto'; els.q.style.height = Math.min(160, els.q.scrollHeight) + 'px'; }

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
    var fresh = {};
    (V.chips || []).forEach(function (c) {
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
      els.tags.appendChild(h('div', { cls: 'th' }, [h('span', { text: open.name + ': ' + plural(open.list.length, 'tag') }), h('span', { text: 'untick one to leave it out' })]));
      open.list.forEach(function (t) {
        var cb = h('input', { type: 'checkbox', onchange: function () { send('tag', { t: t.t }); } });
        cb.checked = !!t.on;
        els.tags.appendChild(h('label', { title: t.t }, [cb, h('span', { cls: 'p', text: t.name }), h('span', { cls: 'n', text: n(t.n) })]));
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
    clear(els.res); clear(els.lines); clear(els.acts);
    var t = V.count;
    (V.lines || []).forEach(function (l) { els.lines.appendChild(h('div', { text: l })); });
    if (!t) return;
    if (!t.n) {
      els.res.appendChild(h('span', { cls: 'mu', text: V.kind === 'empty' && !V.picked ? '' : 'No cards for that here.' }));
      return;
    }
    var bits = [t.new ? n(t.new) + ' new' : '', t.seen ? n(t.seen) + ' seen' : '', t.susp ? n(t.susp) + ' suspended' : '',
      t.due ? n(t.due) + ' due' : '', t.leech ? plural(t.leech, 'leech', 'leeches') : ''].filter(Boolean).join(' · ');
    els.res.appendChild(h('b', { text: plural(t.n, 'card') }));
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
    els.intro.hidden = !V.intro;
    if (!V.intro) return;
    var card = h('div', { cls: 'ic2' });
    var t = h('div', { cls: 't' });
    t.innerHTML = MAG;
    t.appendChild(h('b', { text: 'Magic search' }));
    card.appendChild(t);
    card.appendChild(h('p', { cls: 'lede', text: 'Say what you want to study, or what’s coming up, the way you’d say it. It reads your deck’s own tags, on this computer; nothing you type leaves it.' }));
    var how = h('div', { cls: 'how' });
    function sec(title, text, tries, code) {
      how.appendChild(h('div', {}, [h('h4', { text: title }), h('p', { text: text }), code ? h('code', { text: code }) : null,
        tries ? h('div', { cls: 'try' }, tries.map(function (x) { return tryChip(x[0], x[1]); })) : null]));
    }
    sec('A topic', 'Its name, its initials or a typo: every tag that says it, as one chip. Tap a chip to leave it out; its tags to pick which.', [['heart failure'], ['hf drugs']]);
    sec('A filter', 'New, seen, due, due tomorrow, missed today or this week, learning, suspended, leeches, flagged. Or tap them under the box.', [['anemia I missed this week']]);
    sec('How many', 'A number first takes that many, in the deck’s order.', [['10 new platelets']]);
    sec('Leave some out', '“but not”, “except” or “without”, then the topic.', [['platelets but not itp']]);
    sec('QIDs, IDs, a search', 'Paste a block’s question IDs, note or card IDs, or an Anki search.', [['10234 10911 11002', 'a block’s QIDs']]);
    sec('What’s coming up', 'A quiz goes on a plan, its topics on the days before it. An exam, or being away, goes in Settings.', [['quiz friday on anemia'], ['I’m away till monday']]);
    sec('Plan lines', 'Lines from our prompts or the Text tab become a plan’s dates and events.', null, '2026-11-12 | Anemia | tag:…');
    sec('Your plan’s words', '“tomorrow’s set”, “the heme quiz”: the cards your plan has for them.', [['tomorrow’s set']]);
    card.appendChild(how);
    card.appendChild(h('div', { cls: 'then' }, [h('b', { text: 'Then, with what it finds' }), h('ul', {}, [
      h('li', { text: 'Study now: new and due, or all of them, in a filtered deck. Suspended ones open; leeches stay out.' }),
      h('li', { text: 'Keep as a filtered deck: named by you; Rebuild fills it again any day. Cards never move.' }),
      h('li', { text: 'Add to a filtered deck you have, like a deck of QBank misses.' }),
      h('li', { text: 'Unsuspend, or Browse them.' }),
      h('li', { text: 'Put on days: tap one or several; each is a date on My plan, opened that morning.' })])]));
    card.appendChild(h('div', { cls: 'foot' }, [h('span', { cls: 'mu', style: 'font-size:12px', text: '? brings this back. Ctrl+Shift+F opens Magic search from anywhere.' }),
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
  }

  function start(v, isPreview) {
    preview = !!isPreview;
    show(v);
    if (!v.intro) setTimeout(function () { els.q.focus(); }, 30);
    send('ready');
  }

  return { start: start, show: show, sparkle: sparkle, _send: send };
})();
