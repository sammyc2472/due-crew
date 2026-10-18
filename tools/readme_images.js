// Screenshot tools/readme_board.html (tools/readme_images.py writes it) to
// docs/images/board.png at twice its size, Pips still (Reduce motion).
//     node tools/readme_images.js      (CHROMIUM=/path/to/chrome if Playwright's own isn't there)
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const page = await browser.newPage({ viewport: { width: 700, height: 1000 }, deviceScaleFactor: 2 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("file://" + path.join(__dirname, "readme_board.html"));
  await page.waitForTimeout(400);
  await (await page.$("#shot")).screenshot({ path: path.join(__dirname, "..", "docs", "images", "board.png") });
  await browser.close();
  console.log("wrote docs/images/board.png");
})();
