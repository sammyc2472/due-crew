// The reviewer's bottom bar kept centred around our chip and room
// (room_model.BAR_BALANCE; see the note above it there).
(function () {
  window.dcBarBalance = function () {
    var t = document.getElementById('innertable'), row = t && t.rows[0];
    if (!row || row.cells.length < 3) { return; }
    var l = row.cells[0], m = row.cells[1], r = row.cells[row.cells.length - 1];
    l.style.width = r.style.width = '';  // what 3.7.5 set, gone
    var t0 = document.getElementById('dc-knows-t');
    if (t0) {
      t0.style.maxWidth = '24vw'; t0.textContent = t0.getAttribute('data-full') || t0.textContent;
      [].forEach.call(t0.parentNode.querySelectorAll('span,b'), function (x) { x.style.display = ''; });
      t0.style.display = 'inline-block';
    }  // as drawn (cards._CHIP_JS); shrunk again below if need be
    // another add-on can draw its button over the bar (positioned, out of
    // the row), so ours would sit underneath it: step past anything that does
    function clear(el) {
      if (!el) { return; }
      el.style.marginLeft = '';
      var over = [].filter.call(document.body.getElementsByTagName('*'), function (o) {
        if (o === el || el.contains(o) || o.contains(el)) { return false; }
        var p = getComputedStyle(o).position;
        return p === 'absolute' || p === 'fixed';
      });
      for (var pass = 0; pass < 4; pass++) {
        var b = el.getBoundingClientRect(), push = 0;
        over.forEach(function (o) {
          var q = o.getBoundingClientRect();
          if (q.width > 0 && q.height > 0 && q.left < b.right && q.right > b.left && q.top < b.bottom && q.bottom > b.top) {
            push = Math.max(push, q.right - b.left + 8);
          }
        });
        if (!push) { return; }
        el.style.marginLeft = (parseFloat(getComputedStyle(el).marginLeft) || 0) + push + 'px';
      }
    }
    clear(document.getElementById('dc-room-bottom'));
    // 3.7.6: no cell widths any more. Measure where the answer buttons are and
    // slide them (a transform, which moves nothing else) to the bar's middle,
    // as near as the side cells' own buttons allow: another add-on's button,
    // added whenever, can't throw the arithmetic off
    function span(c, skip) {   // where a cell's own buttons are, leaving `skip` out
      var a = Infinity, z = -Infinity;
      for (var k = 0; k < c.children.length; k++) {
        if (c.children[k] === skip) { continue; }
        var b = c.children[k].getBoundingClientRect();
        if (b.width > 0) { a = Math.min(a, b.left); z = Math.max(z, b.right); }
      }
      return z > a ? [a, z] : null;
    }
    [].forEach.call(m.children, function (x) { x.style.transform = ''; });
    var tb = t.getBoundingClientRect(), mid = tb.left + tb.width / 2, txt = document.getElementById('dc-knows-t');
    var chip = document.getElementById('dc-knows'), ms0 = span(m);
    if (!ms0) { return; }
    var half = (ms0[1] - ms0[0]) / 2, gap = 12;
    // the chip goes beside More (bottom right, where its card sits too), or
    // Edit's side when More's has no room beside a centred row of answer
    // buttons, and gives way there: its words shrink, then its short form
    function fits(side) {
      var cw = chip.getBoundingClientRect().width + 10;
      if (side === l) { var a = span(l, chip); return (a ? a[1] : tb.left) + cw + gap <= mid - half; }
      var b = span(r, chip); return (b ? b[0] : tb.right) - cw - gap >= mid + half;
    }
    function place(side) {
      chip.style.marginLeft = side === r ? '0' : '10px';
      chip.style.marginRight = side === r ? '10px' : '';
      if (chip.parentNode === side) { return; }
      if (side === r) { r.insertBefore(chip, r.firstChild); } else { l.appendChild(chip); }
    }
    if (chip && txt) {
      var side = fits(r) ? r : fits(l) ? l : null;
      if (!side) {
        side = (span(l, chip) || [0, tb.left])[1] - tb.left < tb.right - (span(r, chip) || [tb.right])[0] ? l : r;
        place(side);
        for (var i = 0; !fits(side) && i < 4; i++) {
          var tw = txt.getBoundingClientRect().width;
          if (tw <= 120) { break; }
          txt.style.maxWidth = '120px';
        }
        if (!fits(side)) {
          txt.textContent = txt.getAttribute('data-short') || txt.textContent;
          txt.style.maxWidth = 'none';
          [].forEach.call(chip.children, function (x) {
            if (x !== txt && (x.tagName === 'SPAN' || txt.getAttribute('data-tip'))) { x.style.display = 'none'; }
          });
        }
      }
      place(side);
      clear(chip);  // on its side now: step past another add-on's floating button there
    }
    var ms = span(m), ls = span(l), rs = span(r);
    var dx = mid - (ms[0] + ms[1]) / 2;
    if (ls && ms[0] + dx < ls[1] + gap) { dx = ls[1] + gap - ms[0]; }        // never under a side's buttons
    if (rs && ms[1] + dx > rs[0] - gap) { dx = Math.min(dx, rs[0] - gap - ms[1]); }
    if (Math.abs(dx) >= 1) { [].forEach.call(m.children, function (x) { x.style.transform = 'translateX(' + Math.round(dx) + 'px)'; }); }
  };
  if (!window.dcBarResize) {
    window.dcBarResize = true;
    window.addEventListener('resize', function () { window.dcBarBalance(); });
    // anything added to the bar later (another add-on's button, Anki's answer
    // buttons for the next card) balances it again; our own style changes don't
    if (window.MutationObserver) {
      var pend = 0;
      new MutationObserver(function (recs) {
        // the chip's own moves and text swaps aren't news; nor (3.9.1) the room's, whose tick balances when its words change
        var chip = document.getElementById('dc-knows'), room = document.getElementById('dc-room-bottom');
        if ((chip || room) && recs.every(function (x) {
          var nodes = [].slice.call(x.addedNodes).concat([].slice.call(x.removedNodes));
          return (chip && chip.contains(x.target)) || (room && room.contains(x.target))
            || (nodes.length && nodes.every(function (n) { return n === chip || n === room; }));
        })) { return; }
        clearTimeout(pend);
        pend = setTimeout(function () { window.dcBarBalance(); }, 30);
      }).observe(document.body, { childList: true, subtree: true });
    }
  }
  window.dcBarBalance();
  clearTimeout(window.dcBarLater);
  window.dcBarLater = setTimeout(function () { window.dcBarBalance(); }, 400);
})();
