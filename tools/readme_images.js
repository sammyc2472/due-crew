// Screenshot tools/readme_board.html and readme_plans.html (tools/readme_images.py
// writes them) to docs/images/board.png and plans.png at twice their size, Pips
// still (Reduce motion); plans.png is the You box alone.
//     node tools/readme_images.js      (CHROMIUM=/path/to/chrome if Playwright's own isn't there)
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 700, height: 1000 }, deviceScaleFactor: 2 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const [file, sel, png] of [["readme_board.html", "#shot", "board.png"], ["readme_plans.html", "#shot .du", "plans.png"]]) {
    await page.goto("file://" + path.join(__dirname, file));
    await page.waitForTimeout(400);
    await (await page.$(sel)).screenshot({ path: path.join(__dirname, "..", "docs", "images", png) });
    console.log("wrote docs/images/" + png);
  }
  await browser.close();
})();
