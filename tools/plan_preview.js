// Screenshots of tools/plan_preview.py's pages: light, dark, narrow. Errors on the page fail it.
//   node tools/plan_preview.js DIR
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
(async () => {
  const dir = process.argv[2] || path.join(__dirname, "plan_preview");
  const b = await chromium.launch();
  let bad = 0;
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith(".html"))) {
    for (const [w, h, scheme] of [[1240, 820, "light"], [1240, 820, "dark"], [760, 820, "light"]]) {
      const p = await b.newPage({ viewport: { width: w, height: h }, colorScheme: scheme });
      const errs = [];
      p.on("pageerror", (e) => errs.push(e.message));
      p.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
      await p.goto("file://" + path.join(dir, f));
      await p.waitForTimeout(150);
      const out = path.join(dir, `${f.replace(".html", "")}-${w}-${scheme}.png`);
      await p.screenshot({ path: out });
      if (errs.length) { bad++; console.log(f, w, scheme, "ERRORS", errs); }
      await p.close();
    }
  }
  await b.close();
  console.log(bad ? `${bad} with errors` : "ok");
  process.exit(bad ? 1 : 0);
})();
