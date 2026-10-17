// 3.9.0, the motion audit (Sam: "everything should be smooth!"): every scenario in
// tools/motion_preview.html played with its animations held still and stepped through
// by hand, then the last frame of the motion set against the page once every animation
// has finished and cleaned up. A motion that ends anywhere but where the page settles
// jumps on its last frame (the pill that ended square, a box that ended its padding
// too tall); this counts the pixels that jump, scenario by scenario.
//
//   python3 tools/motion_preview.py
//   NODE_PATH=$(npm root -g) node tools/motion_audit.js [key,key,...] [--out DIR]
//
// Needs Playwright's Chromium (CHROMIUM=/path/to/chrome to pick one). --out keeps each
// frame as a picture. Exits 1 when a scenario's end is off by more than LIMIT pixels.
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
// a Pip's blink, a breathing chip, or a row's text drawn in its own layer while something on it
// moves (the same place, its edges a shade apart) come to a few hundred; a jump is thousands
const LIMIT = 500;
const args = process.argv.slice(2), at = args.indexOf("--out");
const OUT = at >= 0 ? args.splice(at, 2)[1] : null, ONLY = args[0] ? args[0].split(",") : null;
const PAGE = path.join(__dirname, "motion_preview.html");

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 1000, height: 1400 } });
  const cmp = await browser.newPage();
  await page.addInitScript(() => {
    const orig = Element.prototype.animate;
    window.__anims = []; window.__rec = false;
    Element.prototype.animate = function (kf, o) {
      const a = orig.call(this, kf, o);
      if (window.__rec) { try { a.pause(); a.currentTime = 0; } catch (e) {} window.__anims.push(a); }
      return a;
    };
  });
  await page.goto("file://" + PAGE);
  // how many pixels differ between two pictures, and where
  async function differ(a, b) {
    return cmp.evaluate(async ([a, b]) => {
      const load = (s) => new Promise((ok) => { const i = new Image(); i.onload = () => ok(i); i.src = "data:image/png;base64," + s; });
      const [A, B] = [await load(a), await load(b)];
      const w = Math.max(A.width, B.width), h = Math.max(A.height, B.height);
      const px = (im) => { const c = document.createElement("canvas"); c.width = w; c.height = h; const x = c.getContext("2d");
        x.fillStyle = "#fff"; x.fillRect(0, 0, w, h); x.drawImage(im, 0, 0); return x.getImageData(0, 0, w, h).data; };
      const p = px(A), q = px(B);
      let n = 0, box = null;
      for (let i = 0; i < p.length; i += 4) {
        // as bright as a difference has to be to be seen (text's own edges blur a little either way)
        if (0.299 * Math.abs(p[i] - q[i]) + 0.587 * Math.abs(p[i + 1] - q[i + 1]) + 0.114 * Math.abs(p[i + 2] - q[i + 2]) > 40) {
          n++; const x = (i / 4) % w, y = Math.floor(i / 4 / w);
          box = box ? [Math.min(box[0], x), Math.min(box[1], y), Math.max(box[2], x), Math.max(box[3], y)] : [x, y, x, y];
        }
      }
      return { n, box };
    }, [a.toString("base64"), b.toString("base64")]);
  }
  const keys = await page.evaluate(() => Array.from(document.querySelectorAll("#pick option")).map((o) => o.value));
  const rows = [];
  for (const k of keys) {
    if (ONLY && !ONLY.includes(k)) continue;
    const dir = OUT ? path.join(OUT, k) : null;
    if (dir) fs.mkdirSync(dir, { recursive: true });
    await page.evaluate((k) => { window.__rec = false; window.__anims = []; load(k); }, k);
    await page.waitForTimeout(400);
    const stage = await page.$("#stage");
    const shot = async (name) => { const b = await stage.screenshot(); if (dir) fs.writeFileSync(path.join(dir, name + ".png"), b); return b; };
    const hold = () => document.getAnimations().forEach((a) => {
      if (!window.__anims.includes(a)) { try { a.__base = a.currentTime || 0; a.pause(); window.__anims.push(a); } catch (e) {} }
    });
    const day = await page.evaluate(([k, hold]) => {
      const sc = S[k];
      window.__rec = true;
      if (sc.hint === "zoom") document.querySelector(".tmap .tm").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      if (sc.hint === "add" || sc.hint === "addlater") {
        const r = document.getElementById("du-in").getBoundingClientRect();
        dcMotion.say({ add: "Buy colored pens", when: sc.hint === "add" ? "today" : "later", from: { x: r.left, y: r.top } });
      }
      if (sc.hint === "day") { document.querySelectorAll(".pwk .pc")[4].click(); return true; }
      (0, eval)(sc.swap);
      (0, eval)("(" + hold + ")")();  // what CSS already had moving (Pip, a breathing chip) holds still with it
      return false;
    }, [k, hold.toString()]);
    if (day) { await page.waitForTimeout(150); await page.evaluate((hold) => (0, eval)("(" + hold + ")")(), hold.toString()); }
    const end = await page.evaluate(() => Math.min(4000, Math.max(0, ...window.__anims.map((a) => {
      const t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : {};
      return isFinite(t.endTime) ? t.endTime : 0;
    }))));
    // through it a step at a time (timers that start a later part still run as the frames go)
    let i = 0;
    for (let t = 0; t < end; t += Math.max(16, Math.ceil(end / 30))) {
      await page.evaluate((t) => window.__anims.forEach((a) => { try { a.currentTime = (a.__base || 0) + t; } catch (e) {} }), t);
      await page.waitForTimeout(5);
      if (dir) await shot("f" + String(i++).padStart(3, "0"));
    }
    // its last frame, still held; then every one let go to finish and clean up
    await page.evaluate(() => window.__anims.forEach((a) => {
      try { const t = a.effect.getComputedTiming(); if (isFinite(t.endTime)) a.currentTime = t.endTime - 0.01; } catch (e) {}
    }));
    await page.waitForTimeout(5);
    const last = await shot("end");
    await page.evaluate(() => {
      window.__rec = false;
      window.__anims.forEach((a) => { try { if (isFinite(a.effect.getComputedTiming().endTime)) a.finish(); else a.play(); } catch (e) {} });
    });
    await page.waitForTimeout(80);
    const settled = await shot("settled");
    const d = await differ(last, settled);
    rows.push([k, d.n, d.box]);
    console.log(`${k.padEnd(24)} ${String(d.n).padStart(8)} px off at the end${d.box ? "  " + JSON.stringify(d.box) : ""}`);
  }
  await browser.close();
  const bad = rows.filter((r) => r[1] > LIMIT);
  console.log(bad.length ? `\n${bad.length} motion(s) end off where the page settles: ${bad.map((r) => r[0]).join(", ")}`
                         : `\nevery motion ends where the page settles (${rows.length} played)`);
  process.exit(bad.length ? 1 : 0);
})();
