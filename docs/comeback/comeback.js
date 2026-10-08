/* Comeback: the comeback plan's character, for the board and the site.

   One inline SVG (viewBox 520 x 104) drawn from a plain model, plus the two
   short lines above it. No dependencies, no fonts, no images. Every colour
   is a CSS custom property the host sets on the widget (comeback.css):
   --accent, --accent-ink (faces on the accent), --ink, --muted, --line,
   --card, --warm, --cheek.

   Comeback.plan(total, days)  -> the day pieces, in cards
   Comeback.draw(m)            -> SVG text for one frame
   Comeback.words(m)           -> {left, right}, short HTML lines
   Comeback.mount(el, m, opts) -> a live widget: set(patch), review(n),
                                  cheer(who), destroy()

   The model (m):
     kind    'pip' | 'daylings' | 'scout'
     state   'away' | 'start' | 'work' | 'rest' | 'missed' | 'caught'
     total   cards piled up when the plan began (912)
     usual   a usual day, in reviews (150)
     days    the plan's length, 3..21
     day     today's place in the plan, 0-based
     off     days missed so far: each is drawn as a low, flat day before today
     done    cards of today's piece answered (may be fractional mid-animation)
     cheers  [{who: 'D'}]: a crewmate's initial, nothing more
     walk    0..1 while the character is moving, else null (animation only)

   Idle motion is CSS (comeback.css) and stops under prefers-reduced-motion;
   every still frame shows the whole state. JS only runs while progress moves. */
(function (root) {
  'use strict';

  const VW = 520, VH = 104, K = 0.18;      // K: corner radius, 18% of the shorter side (the logo's)
  const n = v => Math.round(v * 100) / 100;
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const lerp = (a, b, t) => a + (b - a) * t;
  const ease = t => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
  const fmt = v => Math.round(v).toLocaleString('en-US');
  let uid = 0;                              // clip-path ids, unique on the page

  // ---------- the plan, in cards ----------

  function plan(total, days) {
    const piece = Math.ceil(total / days), out = [];
    for (let i = 0; i < days; i++) out.push(Math.max(0, Math.min(piece, total - i * piece)));
    return out;
  }

  function norm(m) {
    const days = clamp(Math.round(m.days || 5), 3, 21);
    const pieces = plan(m.total, days);
    const day = clamp(m.day || 0, 0, days - 1);
    const won = pieces.slice(0, day).reduce((a, b) => a + b, 0);
    const piece = pieces[day];
    const done = m.state === 'rest' || m.state === 'caught' ? piece : clamp(m.done || 0, 0, piece);
    return Object.assign({}, m, { days, day, pieces, piece, won, done, off: m.off || 0, cheers: m.cheers || [] });
  }

  // one entry per square, in order: {f: 0..1 filled, today, off}
  function slots(m) {
    const out = [];
    for (let i = 0; i < m.days; i++) {
      if (i === m.day) for (let k = 0; k < m.off; k++) out.push({ f: 0, off: true });
      let f = 0;
      if (m.state === 'caught') f = 1;
      else if (m.state !== 'start' && m.state !== 'away') f = i < m.day ? 1 : i === m.day ? m.done / m.piece : 0;
      out.push({ f, today: i === m.day && /^(work|rest|missed)$/.test(m.state) });
    }
    return out;
  }

  // squares in rows of up to seven (a week a row), sized to fit the box
  function grid(count, box, sMax, align) {
    const cols = Math.min(7, count), rows = Math.ceil(count / cols);
    const s = Math.min(sMax, box.w / (cols * 1.5 - 0.5), box.h / (rows * 1.5 - 0.5)), gap = s / 2;
    const w = cols * s + (cols - 1) * gap, h = rows * s + (rows - 1) * gap;
    const x0 = align === 'center' ? box.x + (box.w - w) / 2 : box.x + box.w - w, y0 = box.y + box.h - h;
    return Array.from({ length: count }, (_, i) => ({
      x: x0 + (i % cols) * (s + gap), y: y0 + Math.floor(i / cols) * (s + gap), s,
    }));
  }

  // ---------- shapes ----------

  const rr = (x, y, w, h, c) =>
    `<rect x="${n(x)}" y="${n(y)}" width="${n(w)}" height="${n(h)}" rx="${n(Math.min(w, h) * K)}" class="${c}"/>`;
  const pill = (x, y, w, h, c) =>
    `<rect x="${n(x)}" y="${n(y)}" width="${n(w)}" height="${n(h)}" rx="${n(h / 2)}" class="${c}"/>`;
  const rot = (deg, cx, cy, body) => (deg ? `<g transform="rotate(${n(deg)} ${n(cx)} ${n(cy)})">${body}</g>` : body);
  const move = (x, y, body) => (x || y ? `<g transform="translate(${n(x)} ${n(y)})">${body}</g>` : body);
  // an idle loop: a CSS class on a wrapper (never on an element with its own transform)
  const loop = (cls, d, body, origin) =>
    `<g class="${cls}" style="--d:${n(d)}s${origin ? `;transform-origin:${n(origin[0])}px ${n(origin[1])}px` : ''}">${body}</g>`;
  const arm = (x, y, len, th, deg, c) =>
    rot(deg, x, y, `<rect x="${n(x - th / 2)}" y="${n(y - th / 2)}" width="${n(len + th)}" height="${n(th)}" rx="${n(th / 2)}" class="${c}"/>`);
  const clip = (shape, body) => {
    const id = 'cbk' + (++uid);
    return `<clipPath id="${id}">${shape}</clipPath><g clip-path="url(#${id})">${body}</g>`;
  };
  const zz = (x, y, s) =>
    [[0, 0, 1, 0], [s * 1.5, -s * 1.9, 0.72, 1.4]].map(([dx, dy, k, d]) => loop('k-z', d,
      `<path d="M${n(x + dx)} ${n(y + dy)}h${n(s * k)}l${n(-s * k)} ${n(s * k * 1.1)}h${n(s * k)}" class="s-mu" stroke-width="${n(s * 0.24)}"/>`)).join('');
  const confetti = pts => pts.map(([x, y, deg, c, d], i) =>
    loop('k-fall', d == null ? i * 0.45 : d, rot(deg, x, y, rr(x - 2.6, y - 2.6, 5.2, 5.2, c)))).join('');
  // a crewmate: an initial in an accent circle (the board's face)
  const mate = (cx, cy, who, r, fresh) => {
    const body = `<circle cx="${n(cx)}" cy="${n(cy)}" r="${n(r)}" class="a"/>` +
      `<text x="${n(cx)}" y="${n(cy + r * 0.36)}" text-anchor="middle" class="cb-who" style="font-size:${n(r * 1.05)}px">${esc(who)}</text>`;
    return loop(fresh ? 'k-pop' : 'k-bob', fresh ? 0 : cx / 97, body);
  };
  const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]).slice(0, 12);

  // a face: eyes centred on (cx, cy), sized from the body's side s
  function face(cx, cy, s, o = {}) {
    const col = o.col || 'ai', ex = s * 0.2, w = s * 0.16, sw = n(Math.max(1.2, s * 0.055));
    const [lx, ly] = o.look || [0, 0];
    let eyes = '';
    for (const sx of [-1, 1]) {
      const x = cx + sx * ex + lx, y = cy + ly;
      if (o.eyes === 'happy')
        eyes += `<path d="M${n(x - w / 2)} ${n(y + w * 0.22)}Q${n(x)} ${n(y - w * 0.6)} ${n(x + w / 2)} ${n(y + w * 0.22)}" class="s-${col}" stroke-width="${sw}"/>`;
      else if (o.eyes === 'shut')
        eyes += `<path d="M${n(x - w / 2)} ${n(y)}Q${n(x)} ${n(y + w * 0.62)} ${n(x + w / 2)} ${n(y)}" class="s-${col}" stroke-width="${sw}"/>`;
      else
        eyes += `<ellipse cx="${n(x)}" cy="${n(y)}" rx="${n(s * 0.064)}" ry="${n(s * 0.092)}" class="${col}"/>`;
    }
    let out = o.eyes === 'happy' || o.eyes === 'shut' || o.still ? eyes : loop('k-blink', o.blink || 0, eyes);
    if (o.blush) for (const sx of [-1, 1])
      out += `<ellipse cx="${n(cx + sx * s * 0.33 + lx * 0.5)}" cy="${n(cy + s * 0.12)}" rx="${n(s * 0.075)}" ry="${n(s * 0.045)}" class="ck"/>`;
    const mx = cx + lx * 0.7, my = cy + s * 0.16 + ly * 0.4;
    if (o.mouth === 'smile')
      out += `<path d="M${n(mx - s * 0.075)} ${n(my)}Q${n(mx)} ${n(my + s * 0.075)} ${n(mx + s * 0.075)} ${n(my)}" class="s-${col}" stroke-width="${sw}"/>`;
    else if (o.mouth === 'grin')
      out += `<path d="M${n(mx - s * 0.1)} ${n(my - s * 0.015)}Q${n(mx)} ${n(my + s * 0.15)} ${n(mx + s * 0.1)} ${n(my - s * 0.015)}Z" class="${col}"/>`;
    else if (o.mouth === 'o')
      out += `<ellipse cx="${n(mx)}" cy="${n(my + s * 0.03)}" rx="${n(s * 0.055)}" ry="${n(s * 0.065)}" class="${col}"/>`;
    return out;
  }

  // feet: standing, or one lifted mid-stride (step: 0..1 through a stride)
  function feet(gx, gy, s, step, spread) {
    const fw = s * 0.26, fh = s * 0.17, up = s * 0.09;
    const ph = step == null ? 0 : Math.sin(step * Math.PI * 2);
    return pill(gx - s * spread - fw / 2, gy - fh - Math.max(0, ph) * up, fw, fh, 'a') +
      pill(gx + s * spread - fw / 2, gy - fh - Math.max(0, -ph) * up, fw, fh, 'a');
  }

  // ---------- Pip: a day square on two feet ----------
  // (gx, gy): the ground under its feet. o: s, pose (stand|walk|loaf|hop), dir, arms, card, step, eyes, mouth
  function pip(gx, gy, o = {}) {
    const s = o.s || 44, dir = o.dir || 1;
    if (o.pose === 'loaf') {
      const w = s * 1.22, h = s * 0.74;
      return loop('k-breathe', 0.4, rr(gx - w / 2, gy - h, w, h, 'a') +
        face(gx, gy - h * 0.45, s, { eyes: 'shut', mouth: 'smile', blush: true }));
    }
    const bob = o.step == null ? 0 : Math.abs(Math.sin(o.step * Math.PI * 2)) * s * 0.05;
    const by = gy - s * 0.1 - s - bob, bx = gx - s / 2, th = s * 0.17;
    let back = '', body = '';
    if (o.arms === 'wave') back += loop('k-wave', 0, arm(bx + s - th * 0.6, by + s * 0.5, s * 0.34, th, -58, 'a'), [bx + s - th * 0.6, by + s * 0.5]);
    if (o.arms === 'up') back += arm(bx + th * 0.6, by + s * 0.45, s * 0.34, th, -130, 'a') + arm(bx + s - th * 0.6, by + s * 0.45, s * 0.34, th, -50, 'a');
    body += rr(bx, by, s, s, 'a') + face(gx + dir * s * 0.02, by + s * 0.58, s, {
      eyes: o.eyes, mouth: o.mouth || 'smile', blush: true,
      look: o.look || [dir * s * 0.05, o.card ? -s * 0.07 : 0], blink: 0.7,
    });
    if (o.card) body += rot(-6 * dir, gx, by, rr(gx - s * 0.44, by - s * 0.2, s * 0.9, s * 0.18, 'ln'));
    const figure = back + feet(gx, gy - bob * 0.3, s, o.step, 0.19) + (o.pose === 'stand' ? loop('k-breathe', 0, body) : body);
    return o.pose === 'hop' ? loop('k-hop', 0, figure) : figure;
  }

  function stack(x, gy, count, w) {
    const jit = [0, 4, -3, 2, -2, 3, 0, -3];
    let out = '';
    for (let i = 0; i < count; i++) out += rr(x + jit[i % 8], gy - (i + 1) * 12 + 2, w, 10, 'ln');
    return out;
  }

  // a square of the plan: filled from the bottom; a day off is low and flat
  function square(p, q) {
    if (q.off) return rr(p.x, p.y + p.s * 0.58, p.s, p.s * 0.42, 'ln');
    if (q.f >= 1) return rr(p.x, p.y, p.s, p.s, 'a');
    let out = rr(p.x, p.y, p.s, p.s, 'ln');
    if (q.f > 0) out += clip(rr(p.x, p.y, p.s, p.s, ''), `<rect x="${n(p.x)}" y="${n(p.y + p.s * (1 - q.f))}" width="${n(p.s)}" height="${n(p.s * q.f)}" class="a"/>`);
    return out;
  }

  function pipScene(m) {
    const gy = 98;
    if (m.state === 'away') {
      return stack(190, gy, 3, 60) + rr(216, gy - 36, 7, 36, 'wm') +
        pip(312, gy, { pose: 'stand', arms: 'wave', eyes: 'happy' }) + mates(m, 340, 18);
    }
    const left = m.total - m.won - m.done;
    const cards = m.state === 'start' ? 8 : m.state === 'caught' ? 0 : Math.max(1, Math.ceil(8 * left / m.total));
    const sl = slots(m), L = grid(sl.length, { x: 222, y: 4, w: 282, h: 94 }, 42);
    let out = stack(18, gy, cards, 64) + sl.map((q, i) => square(L[i], q)).join('');
    const t = L[sl.findIndex(q => q.today)];
    const A = 106, B = 178;
    if (m.state === 'work' && m.walk != null && t) {
      // a trip: carry a card from the stack, toss it into today's square, walk back
      const w = m.walk;
      if (w < 0.42) out += pip(lerp(A, B, ease(w / 0.42)), gy, { pose: 'walk', card: true, step: w / 0.42 * 2.5, dir: 1 });
      else if (w < 0.58) {
        const p = (w - 0.42) / 0.16, hx = B, hy = gy - 44 * 1.1 - 12;
        const cx = lerp(hx, t.x + t.s / 2, p), cy = lerp(hy, t.y + t.s * 0.4, p) - Math.sin(p * Math.PI) * 26;
        out += pip(B, gy, { pose: 'stand', arms: 'up', eyes: 'happy', mouth: 'grin' });
        out += rot(p * 200, cx, cy, rr(cx - 20 * (1 - p * 0.5), cy - 4, 40 * (1 - p * 0.5), 8, 'ln'));
      } else out += pip(lerp(B, A, ease((w - 0.58) / 0.42)), gy, { pose: 'walk', step: (w - 0.58) / 0.42 * 2.5, dir: -1 });
    } else if (m.state === 'rest') {
      out += pip(160, gy, { pose: 'loaf' }) + zz(176, 40, 6);
    } else if (m.state === 'missed') {
      out += pip(160, gy, { pose: 'stand', arms: 'wave', eyes: 'happy' });
    } else if (m.state === 'caught') {
      out += pip(150, gy, { pose: 'hop', arms: 'up', eyes: 'happy', mouth: 'grin' }) +
        confetti([[104, 30, 20, 'a'], [126, 12, 50, 'wm'], [176, 8, -15, 'a'], [200, 26, 35, 'wm'], [92, 58, -30, 'wm'], [214, 52, 10, 'a']]);
    } else {
      out += pip(m.state === 'start' ? 150 : B, gy, { pose: 'stand', dir: 1 });
    }
    return out + mates(m, m.state === 'caught' ? 224 : 210, 16);
  }

  // ---------- Daylings: the plan's days, awake when their day comes ----------
  function dayling(p, o) {
    const { x, y, s } = p, cx = x + s / 2, cy = y + s * 0.6;
    let out = '';
    const wave = o.wave ? loop('k-wave', 0, arm(x + s * 0.9, y + s * 0.45, s * 0.3, s * 0.15, -55, o.kind === 'today' && o.f < 0.45 ? 'ln' : 'a'), [x + s * 0.9, y + s * 0.45]) : '';
    if (o.kind === 'off') {                // a day off: lying down, content
      const h = s * 0.42;
      return loop('k-breathe', 1.1, rr(x, y + s - h, s, h, 'ln') + face(cx, y + s - h * 0.48, s * 0.8, { eyes: 'shut', mouth: 'smile', col: 'mu' }));
    }
    if (o.kind === 'later') {              // not yet: asleep
      return loop('k-breathe', (x % 7) / 3, rr(x, y, s, s, 'ln') + face(cx, cy, s, { eyes: 'shut', col: 'mu' }));
    }
    if (o.kind === 'ready') {              // the first day, before starting: awake and ready
      return rr(x, y, s, s, 'ln') + face(cx, cy, s, { col: 'ink', mouth: 'smile', look: [s * 0.03, -s * 0.02] });
    }
    if (o.kind === 'done') {
      const body = wave + rr(x, y, s, s, 'a') + face(cx, cy, s, { eyes: o.eyes || 'happy', mouth: o.mouth || 'smile', blush: true, look: o.look });
      if (o.hop) return loop('k-hop', o.hop, body);
      return o.sway ? loop('k-sway', o.sway, rot(3, cx, y + s, body)) : body;
    }
    // today: fills like a glass; the eyes are ink above the waterline and accent-ink below it
    const f = clamp(o.f), wy = y + s * (1 - f);
    const fo = { eyes: o.eyes, mouth: o.mouth || 'o', look: o.look || [0, -s * 0.05], blink: 1.3 };
    out += wave + rr(x, y, s, s, 'ln');
    if (f > 0) out += clip(rr(x, y, s, s, ''), `<rect x="${n(x)}" y="${n(wy)}" width="${n(s)}" height="${n(s * f)}" class="a"/>`);
    out += face(cx, cy, s, Object.assign({}, fo, { col: 'ink' }));
    if (f > 0) out += clip(`<rect x="${n(x)}" y="${n(wy)}" width="${n(s)}" height="${n(s * f + 1)}"/>`, face(cx, cy, s, fo));
    return out;
  }

  function dayScene(m) {
    if (m.state === 'away') {
      const L = grid(3, { x: 120, y: 30, w: 280, h: 68 }, 50, 'center');
      return dayling(L[0], { kind: 'done', wave: true, eyes: 'happy' }) + dayling(L[1], { kind: 'later' }) +
        dayling(L[2], { kind: 'later' }) + zz(L[2].x + L[2].s * 0.8, L[2].y - 8, 6) + mates(m, 420, 18);
    }
    const sl = slots(m), L = grid(sl.length, { x: 16, y: 4, w: 488, h: 94 }, 56, 'center');
    const last = sl.length - 1;
    let out = sl.map((q, i) => {
      const p = L[i];
      if (q.off) return dayling(p, { kind: 'off' });
      if (m.state === 'caught') return dayling(p, { kind: 'done', hop: i * 0.12, mouth: 'grin' });
      if (m.state === 'start') return dayling(p, { kind: i === 0 ? 'ready' : 'later' });
      if (q.today) {
        if (m.state === 'rest') return dayling(p, { kind: 'done', eyes: 'shut', mouth: 'smile' });
        return dayling(p, { kind: 'today', f: q.f, wave: m.state === 'missed',
          eyes: m.state === 'missed' ? 'happy' : null, mouth: m.state === 'missed' ? 'smile' : 'o',
          look: [0, -p.s * (0.02 + 0.06 * (1 - q.f))] });
      }
      if (q.f >= 1) return dayling(p, { kind: 'done', sway: i * 0.6, look: [p.s * 0.03, 0] });
      return dayling(p, { kind: 'later' });
    }).join('');
    if (m.state !== 'caught' && !sl[last].f && !sl[last].today) out += zz(L[last].x + L[last].s * 0.82, L[last].y - 8, Math.max(4, L[last].s * 0.12));
    if (m.state === 'caught') out += confetti([[40, 18, 20, 'a'], [120, 8, 50, 'wm'], [400, 10, -15, 'a'], [480, 22, 35, 'wm'], [260, 4, 15, 'wm']]);
    const t = L[sl.findIndex(q => q.today)] || L[last], c = Math.min(3, m.cheers.length);
    return out + mates(m, t.x + t.s / 2 - (c - 1) * 10, Math.max(10, t.y - 13));
  }

  // ---------- Scout: climbs back one step a day ----------
  function scout(gx, gy, o = {}) {
    const s = o.s || 32, w = s * 0.84, dir = o.dir || 1;
    const bob = o.step == null ? 0 : Math.abs(Math.sin(o.step * Math.PI * 2)) * s * 0.05;
    const sit = o.pose === 'sit';
    const bodyBot = gy - (sit ? 0 : s * 0.12) - bob, by = bodyBot - s, bx = gx - w / 2, th = s * 0.17;
    let back = rr(gx - dir * (w / 2 + s * 0.16) - s * 0.2, by + s * 0.2, s * 0.4, s * 0.58, 'wm');   // the backpack
    if (o.arms === 'wave') back += loop('k-wave', 0, arm(bx + w - th * 0.6, by + s * 0.48, s * 0.34, th, -60, 'a'), [bx + w - th * 0.6, by + s * 0.48]);
    if (o.arms === 'up') back += arm(bx + th * 0.6, by + s * 0.42, s * 0.34, th, -125, 'a') + arm(bx + w - th * 0.6, by + s * 0.42, s * 0.34, th, -55, 'a');
    const legs = sit ? pill(gx - s * 0.32, bodyBot - s * 0.12, s * 0.24, s * 0.17, 'a') + pill(gx + s * 0.1, bodyBot - s * 0.12, s * 0.24, s * 0.17, 'a')
      : feet(gx, gy - bob * 0.3, s, o.step, 0.16);
    let body = rr(bx, by, w, s, 'a') + face(gx + dir * s * 0.06, by + s * 0.56, s * 0.9, {
      eyes: o.eyes || (sit ? 'shut' : null), mouth: o.mouth || 'smile', blush: true, look: o.look || [dir * s * 0.06, 0], blink: 2.1,
    });
    if (o.mug) body += rr(gx + w * 0.5 - 2, by + s * 0.55, s * 0.26, s * 0.3, 'wm') +
      `<path d="M${n(gx + w * 0.5 - 2 + s * 0.26)} ${n(by + s * 0.62)}h2.2v${n(s * 0.14)}h-2.2" class="s-wm" stroke-width="1.6"/>`;
    const figure = back + legs + (o.step == null && o.pose !== 'hop' ? loop('k-breathe', 0.3, body) : body);
    return o.pose === 'hop' ? loop('k-hop', 0, figure) : figure;
  }

  function scoutScene(m) {
    const base = 98, X = 96, Wd = 408, Hmax = 52;
    const sl = m.state === 'away' ? [0, 0, 0, 0, 0].map(() => ({ f: 0 })) : slots(m);
    const count = sl.length, plain = m.state === 'away' ? 5 : m.days;
    const gap = count > 9 ? 3 : 7, w = (Wd - (count - 1) * gap) / count, rise = (m.state === 'away' ? 30 : Hmax) / plain;
    let k = 0, prev = rise * 0.5, out = '';
    const steps = sl.map((q, i) => {
      const h = q.off ? prev : rise * ++k; prev = h;
      const x = X + i * (w + gap), y = base - h;
      let g = rr(x, y, w, h, q.f >= 1 ? 'a' : 'ln');
      if (q.f > 0 && q.f < 1) g += clip(rr(x, y, w, h, ''), `<rect x="${n(x)}" y="${n(y)}" width="${n(w * q.f)}" height="${n(h)}" class="a"/>`);
      out += g;
      return { x, y, w, h };
    });
    const top = steps[count - 1];
    const px = top.x + top.w - 4;
    out += `<rect x="${n(px)}" y="${n(top.y - 22)}" width="2.4" height="22" rx="1.2" class="mu"/>` +
      loop('k-flag', 0, `<path d="M${n(px + 2.4)} ${n(top.y - 22)}l14 4.5l-14 4.5z" class="wm"/>`, [px + 2.4, top.y - 17]);
    const ti = sl.findIndex(q => q.today), t = steps[ti];
    if (m.state === 'away') out += scout(46, base, { arms: 'wave', eyes: 'happy', s: 34 });
    else if (m.state === 'start') out += scout(46, base, { look: [2.5, -1.5], s: 34, mouth: 'smile' });
    else if (m.state === 'caught') {
      out += scout(top.x + Math.min(top.w * 0.4, top.w - 24), top.y, { pose: 'hop', arms: 'up', eyes: 'happy', mouth: 'grin', s: 30 });
      out += confetti([[top.x - 60, 20, 20, 'a'], [top.x - 30, 6, 50, 'wm'], [top.x - 96, 34, -25, 'wm'], [top.x + 8, 10, 15, 'a']]);
    } else if (t) {
      const s = 32;
      if (m.state === 'rest') out += scout(t.x + t.w - Math.min(t.w * 0.3, 14), t.y, { pose: 'sit', mug: true, s: 30 }) + zz(t.x + t.w + 4, t.y - 44, 5);
      else if (m.state === 'missed') out += scout(t.x + Math.min(t.w * 0.3, 16), t.y, { arms: 'wave', eyes: 'happy', s });
      else {
        const f = clamp(sl[ti].f, 0.12, 0.88);
        out += scout(t.x + t.w * f, t.y, { s, step: m.walk == null ? null : m.walk * 3 });
      }
    }
    // the crew waits at the top
    if (m.state === 'caught' && count > 1) {
      const below = steps[count - 2];
      return out + mates(m, below.x + below.w - 12, below.y - 9, -1);
    }
    return out + mates(m, top.x + top.w * 0.32, top.y - 10, -1);
  }

  // crewmates' cheers, in a short row starting at (x, y)
  function mates(m, x, y, dir = 1) {
    return m.cheers.slice(-3).map((c, i) => mate(x + dir * i * 20, y, c.who, 8.5, c.fresh)).join('');
  }

  // ---------- public ----------

  function draw(model) {
    const m = norm(model);
    const scene = m.kind === 'daylings' ? dayScene(m) : m.kind === 'scout' ? scoutScene(m) : pipScene(m);
    return `<svg viewBox="0 0 ${VW} ${VH}" role="img" aria-label="${esc2(label(m))}">${scene}</svg>`;
  }
  const esc2 = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

  function label(m) {
    const w = words(m);
    return (w.left + ', ' + w.right).replace(/<[^>]+>/g, '');
  }

  // the two lines above the drawing, counted in cards
  function words(model) {
    const m = norm(model), won = m.won + m.done;
    switch (m.state) {
      case 'away': return { left: '<b>See you soon</b>', right: 'your cards will wait' };
      case 'start': return { left: `<b>${fmt(m.total)}</b> to win back`, right: `<b>${fmt(m.pieces[0])}</b> extra a day` };
      case 'rest': return { left: `<b>${fmt(won)} won back</b> · on track`, right: `today's ${fmt(m.piece)} done` };
      case 'missed': return { left: `<b>Hi again</b> · ${fmt(won)} won back`, right: 'ends a day later' };
      case 'caught': return { left: `<b>${fmt(m.total)} won back</b>`, right: 'all caught up' };
      default: return {
        left: won < 1 ? '<b>Day one</b> · on track' : `<b>${fmt(won)} won back</b> · on track`,
        right: m.done >= 1 ? `<b>${fmt(m.done)}</b> of today's ${fmt(m.piece)}` : `today's ${fmt(m.piece)}`,
      };
    }
  }

  const reduce = root.matchMedia ? root.matchMedia('(prefers-reduced-motion: reduce)') : { matches: false };

  // a live widget in el. opts.still(): true to skip motion (the media query is always honoured).
  // opts.actions(m, el): optional controls under the drawing (the board's length picker).
  function mount(el, model, opts = {}) {
    let m = Object.assign({ kind: 'pip', state: 'work', total: 912, usual: 150, days: 5, day: 0, off: 0, done: 0, cheers: [], walk: null }, model);
    el.classList.add('cb');
    el.innerHTML = '<div class="cb-top"><span class="cb-l"></span><span class="cb-r"></span></div><div class="cb-art"></div><div class="cb-act"></div>';
    const art = el.querySelector('.cb-art'), l = el.querySelector('.cb-l'), r = el.querySelector('.cb-r'), act = el.querySelector('.cb-act');
    const still = () => reduce.matches || !!(opts.still && opts.still());
    let raf = 0, after = 0, settle = 0;

    function paint() {
      art.style.setProperty('--cb-t', `${-(performance.now() % 12000)}ms`);   // idle loops keep their phase across redraws
      const now = performance.now();
      const v = Object.assign({}, m, { cheers: m.cheers.map(c => ({ who: c.who, fresh: now - (c.at || 0) < 650 })) });
      art.innerHTML = draw(v);
      const w = words(v);
      l.innerHTML = w.left; r.innerHTML = w.right;
      act.hidden = !opts.actions;
      if (opts.actions) opts.actions(norm(m), act);
    }
    function stop() { cancelAnimationFrame(raf); clearTimeout(after); raf = 0; m.walk = null; }

    const api = {
      get model() { return norm(m); },
      set(patch) { stop(); m = Object.assign({}, m, patch); paint(); return api; },
      // n more cards of today's piece: the drawing catches up, then rests when the piece is done
      review(count, onDone) {
        const v = norm(m);
        if (!/^(work|missed)$/.test(v.state)) return api;
        stop();
        const from = v.done, to = Math.min(v.piece, from + count);
        if (m.state === 'missed') m.state = 'work';
        const finish = () => {
          m.done = to; m.walk = null; paint();
          if (to >= v.piece) after = setTimeout(() => {
            m.state = v.day >= v.days - 1 ? 'caught' : 'rest';
            paint(); if (onDone) onDone(norm(m));
          }, still() ? 0 : 900);
          else if (onDone) onDone(norm(m));
        };
        if (still()) { finish(); return api; }
        const trips = m.kind === 'pip' ? clamp(Math.round(count / 14), 1, 4) : 1;
        const ms = m.kind === 'pip' ? trips * 1500 : clamp(count * 45, 1200, 3200);
        const t0 = performance.now();
        const frame = now => {
          const p = clamp((now - t0) / ms);
          if (m.kind === 'pip') {
            // the square fills as each card lands
            const k = Math.min(trips - 1, Math.floor(p * trips)), w = p * trips - k;
            m.walk = p >= 1 ? null : w;
            m.done = from + (to - from) * (k + clamp((w - 0.5) / 0.12)) / trips;
          } else {
            m.walk = p >= 1 ? null : p;
            m.done = from + (to - from) * ease(p);
          }
          paint();
          if (p < 1) raf = requestAnimationFrame(frame); else finish();
        };
        raf = requestAnimationFrame(frame);
        return api;
      },
      cheer(who) {
        m.cheers = m.cheers.concat({ who, at: performance.now() }).slice(-3);
        paint();
        clearTimeout(settle);
        if (!still()) settle = setTimeout(() => { if (!raf) paint(); }, 700);   // settle the pop into its idle bob
        return api;
      },
      destroy() { stop(); clearTimeout(settle); el.innerHTML = ''; el.classList.remove('cb'); },
    };
    paint();
    return api;
  }

  root.Comeback = { plan, draw, words, mount, VW, VH };
})(window);
