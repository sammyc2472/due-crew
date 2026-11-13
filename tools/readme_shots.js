// The README's other pictures (3.9.12), at twice their size, Pips still (Reduce motion):
// docs/images/magic.png (tools/readme_shots.py's page), and insights.png, closet.png, party.png and
// dance.png, each cut from its section of tools/preview.html (python3 tools/preview.py first).
const { chromium } = require('playwright');
const path = require('path');
const here = __dirname, img = path.join(here, '..', 'docs', 'images');
const only = process.argv[2] ? path.resolve(process.argv[2]) : img;   // another folder, to look before keeping
(async () => {
  const b = await chromium.launch();
  const page = async (w, h) => {
    const p = await b.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
    await p.emulateMedia({ reducedMotion: 'reduce' });
    return p;
  };
  let p = await page(760, 900);
  await p.goto('file://' + path.join(here, 'readme_magic.html'));
  await p.waitForTimeout(700);
  await (await p.$('#shot')).screenshot({ path: path.join(only, 'magic.png') });
  await p.close();

  p = await page(760, 900);
  await p.goto('file://' + path.join(here, 'preview.html'));
  await p.waitForTimeout(700);
  // the once-only lines on the board (what gets counted, the studying dot) aren't the listing's picture
  await p.addStyleTag({ content: '.bar, .dc-calm { display: none !important; }' });
  // the preview's names carry markup on purpose (it checks escaping); the listing's picture reads plainly
  await p.evaluate(() => {
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      if (/ <(weekend|lectures|3)>/.test(n.nodeValue)) n.nodeValue = n.nodeValue.replace(/ <(weekend|lectures|3)>/g, '');
    }
  });
  const section = (start) => p.evaluateHandle((s) => {
    const h = [...document.querySelectorAll('h3')].find((x) => x.textContent.startsWith(s));
    return h ? h.nextElementSibling : null;
  }, start);
  for (const [start, sel, png] of [
    ['3.8.0: You › Insights, the map opened on Cardio', '.du', 'insights.png'],
    ['3.9.5: You › Pip Party, three picked', '.du', 'party.png'],
    ["3.8.2: Pip's closet, in the board", null, 'closet.png'],
  ]) {
    const box = (await section(start)).asElement();
    if (!box) { console.log('no section:', start); process.exitCode = 1; continue; }
    const el = sel ? await box.$(sel) : box;
    await (el || box).screenshot({ path: path.join(only, png) });
    console.log(png);
  }
  // the dance floor: its frame opened wide (it folds where it would cover the board), the corner cut out
  const doc = await p.evaluate(() => {
    const h = [...document.querySelectorAll('h3')].find((x) => x.textContent.startsWith('3.9.6: the dance floor, four songs'));
    const f = h && (h.nextElementSibling.tagName === 'IFRAME' ? h.nextElementSibling : h.nextElementSibling.querySelector('iframe'));
    return f ? f.getAttribute('srcdoc') : null;
  });
  await p.close();
  if (doc) {
    p = await page(1500, 640);
    await p.setContent(doc);
    await p.addStyleTag({ content: '.dc-calm { display: none !important; }' });
    await p.waitForTimeout(900);
    await p.screenshot({ path: path.join(only, 'dance.png'), clip: { x: 1080, y: 400, width: 420, height: 240 } });
    console.log('dance.png');
    await p.close();
  } else { console.log('no dance floor frame'); process.exitCode = 1; }
  await b.close();
})();
