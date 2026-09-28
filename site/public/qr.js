// 3.5, C3: a QR code for a plan's link on the class poster. Byte mode,
// error correction M, versions 1 to 10 (a duecrew.com link needs 3). The
// arithmetic is the standard's (ISO/IEC 18004), laid out as in Project
// Nayuki's QR Code generator (MIT). Kept here because the site's CSP runs
// only its own scripts. QR.matrix(text) -> rows of booleans (true: dark).
"use strict";

const QR = (() => {
  // error correction M, per version: codewords per block, and blocks
  const ECC = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
  const BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];

  const rawModules = (v) => {
    let n = (16 * v + 128) * v + 64;
    if (v >= 2) { const a = Math.floor(v / 7) + 2; n -= (25 * a - 10) * a - 55; if (v >= 7) n -= 36; }
    return n;
  };
  const dataCodewords = (v) => Math.floor(rawModules(v) / 8) - ECC[v] * BLOCKS[v];

  function mul(x, y) {
    let z = 0;
    for (let i = 7; i >= 0; i--) { z = (z << 1) ^ ((z >>> 7) * 0x11d); z ^= ((y >>> i) & 1) * x; }
    return z;
  }
  function divisor(degree) {
    const r = new Array(degree).fill(0);
    r[degree - 1] = 1;
    let root = 1;
    for (let i = 0; i < degree; i++) {
      for (let j = 0; j < r.length; j++) { r[j] = mul(r[j], root); if (j + 1 < r.length) r[j] ^= r[j + 1]; }
      root = mul(root, 0x02);
    }
    return r;
  }
  function remainder(data, div) {
    const r = div.map(() => 0);
    for (const b of data) {
      const f = b ^ r.shift();
      r.push(0);
      div.forEach((c, i) => { r[i] ^= mul(c, f); });
    }
    return r;
  }

  function codewords(bytes, v) {
    const bits = [];
    const put = (val, len) => { for (let i = len - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
    put(4, 4);
    put(bytes.length, v < 10 ? 8 : 16);
    for (const b of bytes) put(b, 8);
    const cap = dataCodewords(v) * 8;
    put(0, Math.min(4, cap - bits.length));
    put(0, (8 - (bits.length % 8)) % 8);
    for (let pad = 0xec; bits.length < cap; pad ^= 0xec ^ 0x11) put(pad, 8);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
    // split into blocks, add each block's error correction, interleave
    const n = BLOCKS[v], e = ECC[v], raw = Math.floor(rawModules(v) / 8);
    const short = n - (raw % n), shortLen = Math.floor(raw / n);
    const div = divisor(e);
    const blocks = [];
    for (let i = 0, k = 0; i < n; i++) {
      const d = data.slice(k, k + shortLen - e + (i < short ? 0 : 1));
      k += d.length;
      const ecc = remainder(d, div);
      if (i < short) d.push(0);
      blocks.push(d.concat(ecc));
    }
    const out = [];
    for (let i = 0; i < blocks[0].length; i++) blocks.forEach((b, j) => { if (i !== shortLen - e || j >= short) out.push(b[i]); });
    return out;
  }

  function alignments(v) {
    if (v === 1) return [];
    const a = Math.floor(v / 7) + 2;
    const step = Math.ceil((v * 4 + 4) / (a * 2 - 2)) * 2;
    const r = [6];
    for (let pos = v * 4 + 10; r.length < a; pos -= step) r.splice(1, 0, pos);
    return r;
  }

  const MASKS = [
    (x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
    (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
    (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0, (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
  ];

  /** The code for `text` (UTF-8), masked as the standard picks. `mask` (0-7) forces one, for tests. */
  function matrix(text, mask) {
    const bytes = [...new TextEncoder().encode(text)];
    let v = 1;
    while (v <= 10 && 4 + (v < 10 ? 8 : 16) + bytes.length * 8 > dataCodewords(v) * 8) v++;
    if (v > 10) throw new Error("too long for a QR code here");
    const size = v * 4 + 17;
    const m = Array.from({ length: size }, () => new Array(size).fill(false));
    const fn = Array.from({ length: size }, () => new Array(size).fill(false));
    const set = (x, y, dark) => { m[y][x] = dark; fn[y][x] = true; };
    const bit = (x, i) => ((x >>> i) & 1) !== 0;

    for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    for (const [cx, cy] of [[3, 3], [size - 4, 3], [3, size - 4]]) {
      for (let dy = -4; dy <= 4; dy++) {
        for (let dx = -4; dx <= 4; dx++) {
          const d = Math.max(Math.abs(dx), Math.abs(dy)), x = cx + dx, y = cy + dy;
          if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, d !== 2 && d !== 4);
        }
      }
    }
    const al = alignments(v);
    for (let i = 0; i < al.length; i++) {
      for (let j = 0; j < al.length; j++) {
        if ((i === 0 && j === 0) || (i === 0 && j === al.length - 1) || (i === al.length - 1 && j === 0)) continue;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(al[i] + dx, al[j] + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }
    }
    const format = (k) => {
      const data = (0 << 3) | k;  // error correction M is 00
      let rem = data;
      for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
      const b = ((data << 10) | rem) ^ 0x5412;
      for (let i = 0; i <= 5; i++) set(8, i, bit(b, i));
      set(8, 7, bit(b, 6)); set(8, 8, bit(b, 7)); set(7, 8, bit(b, 8));
      for (let i = 9; i < 15; i++) set(14 - i, 8, bit(b, i));
      for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(b, i));
      for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(b, i));
      set(8, size - 8, true);
    };
    format(0);
    if (v >= 7) {
      let rem = v;
      for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
      const b = (v << 12) | rem;
      for (let i = 0; i < 18; i++) { const a = size - 11 + (i % 3), c = Math.floor(i / 3); set(a, c, bit(b, i)); set(c, a, bit(b, i)); }
    }
    const cw = codewords(bytes, v);
    let i = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j, y = ((right + 1) & 2) === 0 ? size - 1 - vert : vert;
          if (!fn[y][x] && i < cw.length * 8) { m[y][x] = bit(cw[i >>> 3], 7 - (i & 7)); i++; }
        }
      }
    }
    const apply = (k) => { for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fn[y][x] && MASKS[k](x, y)) m[y][x] = !m[y][x]; };

    function penalty() {
      let score = 0;
      const addHistory = (run, h) => { if (h[0] === 0) run += size; h.pop(); h.unshift(run); };
      const count = (h) => {
        const n = h[1];
        const core = n > 0 && h[2] === n && h[3] === n * 3 && h[4] === n && h[5] === n;
        return (core && h[0] >= n * 4 && h[6] >= n ? 1 : 0) + (core && h[6] >= n * 4 && h[0] >= n ? 1 : 0);
      };
      const line = (get) => {
        let color = false, run = 0;
        const h = [0, 0, 0, 0, 0, 0, 0];
        for (let k = 0; k < size; k++) {
          if (get(k) === color) { run++; if (run === 5) score += 3; else if (run > 5) score++; }
          else { addHistory(run, h); if (!color) score += count(h) * 40; color = get(k); run = 1; }
        }
        if (color) { addHistory(run, h); run = 0; }
        run += size;
        addHistory(run, h);
        score += count(h) * 40;
      };
      for (let y = 0; y < size; y++) line((x) => m[y][x]);
      for (let x = 0; x < size; x++) line((y) => m[y][x]);
      for (let y = 0; y < size - 1; y++) {
        for (let x = 0; x < size - 1; x++) { const c = m[y][x]; if (c === m[y][x + 1] && c === m[y + 1][x] && c === m[y + 1][x + 1]) score += 3; }
      }
      const dark = m.reduce((n, row) => n + row.filter(Boolean).length, 0);
      score += (Math.ceil(Math.abs(dark * 20 - size * size * 10) / (size * size)) - 1) * 10;
      return score;
    }

    let best = mask;
    if (best === undefined) {
      let low = Infinity;
      for (let k = 0; k < 8; k++) {
        apply(k); format(k);
        const p = penalty();
        if (p < low) { low = p; best = k; }
        apply(k);
      }
    }
    apply(best); format(best);
    return m;
  }

  /** The code as an SVG element: one path, a four-module quiet zone. */
  function svg(text, px) {
    const m = matrix(text);
    const n = m.length, q = 4;
    const ns = "http://www.w3.org/2000/svg";
    const el = document.createElementNS(ns, "svg");
    el.setAttribute("viewBox", `0 0 ${n + 2 * q} ${n + 2 * q}`);
    el.setAttribute("width", px); el.setAttribute("height", px);
    el.setAttribute("role", "img"); el.setAttribute("aria-label", `QR code: ${text}`);
    el.setAttribute("shape-rendering", "crispEdges");
    const bg = document.createElementNS(ns, "rect");
    bg.setAttribute("width", n + 2 * q); bg.setAttribute("height", n + 2 * q); bg.setAttribute("fill", "#fff");
    let d = "";
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) if (m[y][x]) d += `M${x + q} ${y + q}h1v1h-1z`;
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d); path.setAttribute("fill", "#000");
    el.append(bg, path);
    return el;
  }

  return { matrix, svg };
})();

if (typeof module !== "undefined") module.exports = QR;
