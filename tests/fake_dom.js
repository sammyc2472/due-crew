// A small DOM to run the Cheer window in node (3.9.2's QoL pass: a `var moved`
// overwrote the window's scroll/resize handler, and every close threw, so
// nothing picked, sent or closed; the suite only read the script's text).
// Its elements are real EventTargets, so a listener that isn't a function
// throws as it does in a browser. Usage: node fake_dom.js <window.js> <steps>
// where steps is a comma list of: quick:<emoji>, button:<label>, esc,
// backdrop, scroll. Prints {open, sent, errors} as JSON.
const fs = require("fs");
const errors = [];
process.on("uncaughtException", (e) => errors.push(String(e.message)));

class El extends EventTarget {
  constructor(tag) {
    super();
    this.tagName = tag.toUpperCase(); this.children = []; this.parent = null; this.attrs = {};
    this.style = { setProperty() {} }; this.className = ""; this._text = ""; this.dataset = {}; this.value = "";
    this.scrollTop = 0; this.offsetTop = 0; this.hidden = false;
  }
  set textContent(t) { this._text = String(t); this.children = []; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set innerHTML(t) { this._html = t; } get innerHTML() { return this._html || ""; }
  set id(v) { this.attrs.id = v; } get id() { return this.attrs.id; }
  setAttribute(k, v) { this.attrs[k] = String(v); } getAttribute(k) { return this.attrs[k] ?? null; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(c) { c.remove(); c.parent = this; this.children.push(c); return c; }
  insertBefore(c) { return this.appendChild(c); }
  remove() { if (this.parent) { this.parent.children = this.parent.children.filter((x) => x !== this); this.parent = null; } }
  get isConnected() { let p = this; while (p.parent) p = p.parent; return p === document.documentElement; }
  contains(x) { while (x) { if (x === this) return true; x = x.parent; } return false; }
  focus() { document.activeElement = this; }
  blur() { if (document.activeElement === this) document.activeElement = document.body; }
  getBoundingClientRect() { return { left: 100, top: 120, width: 74, height: 36, right: 174, bottom: 156 }; }
  setPointerCapture() {} releasePointerCapture() {} closest() { return null; } querySelectorAll() { return []; }
  querySelector() { return null; }
  getContext() { return new Proxy({}, { get: () => () => {}, set: () => true }); }
  click() { this.dispatchEvent(new Event("click", { bubbles: true })); }
}

const document = new (class extends EventTarget {})();
document.documentElement = new El("html");
document.body = document.documentElement.appendChild(new El("body"));
document.head = document.documentElement.appendChild(new El("head"));
document.activeElement = document.body;
document.createElement = (t) => new El(t);
document.createElementNS = (_ns, t) => new El(t);
document.getElementById = (id) => {
  const walk = (n) => (n.id === id ? n : n.children.map(walk).find(Boolean));
  return walk(document.documentElement) || null;
};
document.querySelector = () => null;
document.querySelectorAll = () => [];
global.document = document;
global.window = global;
const win = new EventTarget();
global.addEventListener = win.addEventListener.bind(win);
global.removeEventListener = win.removeEventListener.bind(win);
global.dispatchEvent = win.dispatchEvent.bind(win);
global.matchMedia = () => ({ matches: false, addEventListener() {} });
global.getComputedStyle = () => ({ getPropertyValue: () => "" });
global.requestAnimationFrame = (f) => setImmediate(f);
global.devicePixelRatio = 1;
const sent = [];
global.pycmd = (s) => sent.push(String(s).split("|")[0]);
global.dcBK = "KEY";

try { (0, eval)(fs.readFileSync(process.argv[2], "utf8")); } catch (e) { errors.push(String(e.message)); }

const back = document.getElementById("dc-cheer");
const all = () => { const out = []; (function walk(n) { out.push(n); n.children.forEach(walk); })(back || document.body); return out; };
const button = (t) => all().find((n) => n.tagName === "BUTTON" && n.textContent === t);
const key = (k) => document.dispatchEvent(Object.assign(new Event("keydown"), { key: k }));

(async () => {
  for (const s of String(process.argv[3] || "").split(",").filter(Boolean)) {
    const [what, arg] = s.split(/:(.*)/s);
    try {
      if (what === "quick" || what === "button") {
        const b = button(arg);
        if (!b) { errors.push(`no button ${arg}`); continue; }
        b.click();
      } else if (what === "esc") key("Escape");
      else if (what === "backdrop") { back.dispatchEvent(new Event("pointerdown")); back.dispatchEvent(new Event("click")); }
      else if (what === "scroll") back.dispatchEvent(new Event("scroll"));
    } catch (e) { errors.push(String(e.message)); }
    await new Promise((r) => setImmediate(r));
  }
  console.log(JSON.stringify({ open: !!document.getElementById("dc-cheer"), sent, errors }));
})();
