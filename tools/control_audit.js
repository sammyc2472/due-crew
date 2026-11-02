// Every button, select, box and tick on our pages, as we mean them, checked
// against what the host puts on top: Anki's own webview.css (every page Anki
// shows gets it: a button's padding, its 4px side margin, a gradient on hover,
// an inset shadow when pressed, `outline: none !important`, macOS's 13px) and
// a native-control layer standing in for macOS's own look (Liquid Glass on
// macOS 26/27 draws a control natively whenever its `appearance` isn't none).
//
//   node tools/control_audit.js [--site] PAGE.html|DIR|URL ...  (a directory of pages, or a served page:
//   node tools/plan_site_preview.js serves duecrew.com's plan pages at http://localhost:8790)
//
// For each page: each control's look at rest, hovered, pressed, focused (and
// disabled where it is), first as the page alone, then under the host's CSS;
// any difference is the host overriding us. Also: a control whose appearance
// isn't none (macOS draws it), one with no visible focus, words clipped in a
// button. Exits 1 on anything found. Chromium as QtWebEngine runs it.
"use strict";
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

// Anki 25.02's css/webview.css, its rules on controls (from the aqt 25.02.7 wheel, its variables filled in);
// its body has isMac and, unless minimalist, fancy (theme.body_class): .fancy button's raised shadow, deeper on hover
const ANKI = `
.isWin button { font-size: 12px; }
.isMac button { font-size: 13px; }
button { outline: none !important; background: #fcfcfc; border-radius: 5px; border: 1px solid #e4e4e4; font-weight: 500;
  padding: 8px 10px; margin: 0 4px; -webkit-appearance: none; cursor: pointer; border-bottom-color: #c4c4c4; color: #020202; }
button:hover { background: linear-gradient(180deg, white 0%, #fcfcfc 100%); border: 1px solid #c4c4c4; }
button:active { box-shadow: inset 0 0.66px 2px rgba(0,0,0,.35); border-color: #e4e4e4; }
button[disabled], button[disabled]:hover { cursor: not-allowed; color: #858585; box-shadow: none !important; background-color: #fcfcfc; }
.fancy button { border-radius: 9px; box-shadow: 0px 2px 1px -1px rgba(20,20,20,.12), 0px 1px 1px 0px rgba(20,20,20,.06), 0px 1px 3px 0px rgba(20,20,20,.04); }
.fancy button:hover { box-shadow: 0px 3px 1px -2px rgba(20,20,20,.2), 0px 2px 2px 0px rgba(20,20,20,.14), 0px 1px 5px 0px rgba(20,20,20,.12); }
textarea:focus, input:focus, input[type]:focus { outline: 0 none; border-color: #3b82f6; }
html { font-family: -apple-system, sans-serif; }
`;
// a stand-in for native (Liquid Glass) controls: anything we don't set, set otherwise
const NATIVE = `
button, input, select, textarea { appearance: auto; -webkit-appearance: auto; backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px); border-radius: 999px; background-color: rgba(255,255,255,.35);
  box-shadow: inset 0 1px 0 rgba(255,255,255,.6), 0 1px 3px rgba(0,0,0,.2); min-height: 28px; letter-spacing: .02em;
  text-transform: none; line-height: 1.6; font-size: 13px; font-weight: 500; text-shadow: 0 1px 0 rgba(255,255,255,.5); }
`;
const PROPS = ["appearance", "background-color", "background-image", "color", "border-top-color", "border-bottom-color",
  "border-top-width", "border-radius", "box-shadow", "font-size", "font-weight", "letter-spacing", "line-height",
  "padding-top", "padding-left", "margin-left", "margin-right", "min-height", "backdrop-filter", "text-shadow",
  "outline-style", "outline-width"];
const SEL = "button, select, input:not([type=hidden]), textarea, [role=button], [role=checkbox], [role=radio], a.b";
const STATES = [[], ["hover"], ["active"], ["focus", "focus-visible"]];

// --site: a page of duecrew.com's, in a browser: no Anki CSS on top, only macOS's own controls
const SITE = process.argv.includes("--site");
// AUDIT_WITHIN="#due-crew, #dc-sheet": only the controls inside these (the board's preview draws some parts bare)
const WITHIN = process.env.AUDIT_WITHIN || "";

function pages(args) {
  const out = [];
  for (const a of args) {
    if (/^https?:/.test(a)) { out.push(a); continue; }
    if (fs.existsSync(a) && fs.statSync(a).isDirectory()) {
      fs.readdirSync(a).filter((f) => f.endsWith(".html")).sort().forEach((f) => out.push(path.resolve(a, f)));
    } else out.push(path.resolve(a));
  }
  return out;
}

async function look(page, client, host) {
  if (host) {
    await page.addStyleTag({ content: (SITE ? "" : ANKI) + NATIVE });
    if (!SITE) await page.evaluate(() => { document.body.classList.add("isMac", "fancy"); });
  }
  await page.evaluate(() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); });
  await page.waitForTimeout(50);
  const { root } = await client.send("DOM.getDocument", { depth: -1 });
  const { nodeIds } = await client.send("DOM.querySelectorAll", { nodeId: root.nodeId, selector: SEL });
  const out = [];
  for (let i = 0; i < nodeIds.length; i++) {
    const id = nodeIds[i];
    const one = { states: {} };
    for (const st of STATES) {
      await client.send("CSS.forcePseudoState", { nodeId: id, forcedPseudoClasses: st });
      const { computedStyle } = await client.send("CSS.getComputedStyleForNode", { nodeId: id });
      const m = {};
      computedStyle.forEach((p) => { if (PROPS.includes(p.name)) m[p.name] = p.value; });
      one.states[st[0] || "rest"] = m;
    }
    await client.send("CSS.forcePseudoState", { nodeId: id, forcedPseudoClasses: [] });
    const { object } = await client.send("DOM.resolveNode", { nodeId: id });
    const { result } = await client.send("Runtime.callFunctionOn", {
      objectId: object.objectId, returnByValue: true,
      functionDeclaration: `function () {
        const r = this.getBoundingClientRect(), cs = getComputedStyle(this);
        const vis = r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
        const words = (this.innerText || this.value || this.getAttribute("aria-label") || this.title || this.placeholder || "").trim().slice(0, 40);
        const within = ${JSON.stringify(WITHIN)};
        return { inside: !within || !!this.closest(within), tag: this.tagName.toLowerCase() + (this.type && this.tagName !== "BUTTON" ? "[" + this.type + "]" : ""),
                 cls: String(this.className || "").slice(0, 40), words, vis, w: Math.round(r.width), h: Math.round(r.height),
                 clipped: this.tagName === "BUTTON" && this.scrollWidth > this.clientWidth + 1, disabled: !!this.disabled };
      }` });
    Object.assign(one, result.value);
    out.push(one);
  }
  return out;
}

function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

(async () => {
  const files = pages(process.argv.slice(2).filter((a) => a !== "--site"));
  if (!files.length) { console.error("usage: node tools/control_audit.js PAGE.html|DIR ..."); process.exit(2); }
  const browser = await chromium.launch();
  let bad = 0;
  for (const f of files) {
    const probs = [];
    const run = async (host) => {
      const page = await browser.newPage({ viewport: { width: 1240, height: 820 } });
      await page.goto(/^https?:/.test(f) ? f : "file://" + f, { waitUntil: "domcontentloaded", timeout: 60000 });
      await page.waitForLoadState("networkidle").catch(() => {});
      await page.waitForTimeout(250);
      const client = await page.context().newCDPSession(page);
      await client.send("DOM.enable"); await client.send("CSS.enable");
      const got = await look(page, client, host);
      await page.close();
      return got;
    };
    const mine = await run(false), host = await run(true);
    const n = Math.min(mine.length, host.length);
    for (let i = 0; i < n; i++) {
      const a = mine[i], b = host[i], name = `${a.tag}${a.cls ? "." + a.cls.split(" ").join(".") : ""} "${a.words}"`;
      if (!a.vis || !a.inside) continue;
      if (a.states.rest.appearance !== "none" && !/\[(checkbox|radio|range|color|file)\]$/.test(a.tag)) {
        probs.push(`${name}: appearance ${a.states.rest.appearance} (macOS draws it natively)`);
      }
      for (const st of SITE ? [] : Object.keys(a.states)) {  // the site has no host CSS on top: what's drawn natively is what counts
        const quiet = (s) => s["outline-style"] === "none";  // an outline's width means nothing without one
        const diff = PROPS.filter((p) => a.states[st][p] !== b.states[st][p] && p !== "appearance"
          && !(p === "outline-width" && quiet(a.states[st]) && quiet(b.states[st])));
        if (diff.length) probs.push(`${name} [${st}] the host changes: ` + diff.map((p) => `${p} ${a.states[st][p]} → ${b.states[st][p]}`).join("; "));
      }
      if (!SITE && (a.w !== b.w || a.h !== b.h)) probs.push(`${name}: the host resizes it ${a.w}×${a.h} → ${b.w}×${b.h}`);
      const f0 = a.states.focus, r0 = a.states.rest, fb = b.states.focus;
      const visible = (s, r) => s["outline-style"] !== "none" && s["outline-width"] !== "0px" || s["box-shadow"] !== r["box-shadow"]
        || s["border-top-color"] !== r["border-top-color"] || s["background-color"] !== r["background-color"];
      if (!visible(fb, b.states.rest) && !a.disabled) probs.push(`${name}: no visible focus under the host's outline:none`);
      if (a.clipped || b.clipped) probs.push(`${name}: its words are clipped`);
    }
    if (mine.length !== host.length) probs.push(`controls differ in number: ${mine.length} vs ${host.length}`);
    const uniq = [...new Set(probs)];
    console.log(`${uniq.length ? "FAIL" : "ok  "} ${/^https?:/.test(f) ? f.replace(/^https?:\/\/[^/]+/, "") : path.basename(f)} (${mine.filter((x) => x.vis).length} controls)`);
    const most = process.env.AUDIT_ALL ? Infinity : 40;
    uniq.slice(0, most).forEach((p) => console.log("     " + p));
    if (uniq.length > most) console.log(`     … ${uniq.length - most} more (AUDIT_ALL=1 lists them all)`);
    bad += uniq.length ? 1 : 0;
  }
  await browser.close();
  process.exit(bad ? 1 : 0);
})();
