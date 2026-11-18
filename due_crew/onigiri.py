"""3.10.2: beside a dashboard that takes the Decks screen's place (Onigiri, AnkiWeb 1011095603). Pure but
for `sidebar`.

Such an add-on draws the Decks screen itself and asks another add-on's render hook only for what a person
has placed in its grid, so the board (Due and the crew, one `#due-crew`) was missing. SC, 18 Nov 2026: under
its dashboard by default, or in its grid where a person puts it, at our full width either way.

- `HERE`: goes out with every draw the hook is asked for; the page says by it that the board is on it.
- `under_js(html)`: for a Decks screen drawn without asking us: the same draw, put under what's there
  (`#dc-oni`), its scripts run. Does nothing where the page already holds the board.
- `GRID_JS`: in its grid, the cell takes the whole row and as many rows as the board is tall, and the
  widgets below move down by as much (their places are fixed rows; ours isn't a fixed height).
  On Anki's own Decks screen it finds no cell and does nothing.
- `sidebar(command)`: its sidebar's own way in for other add-ons, a "Due Crew" entry that brings the board
  into view. Onigiri keeps a new entry in its archive until a person shows it.
"""

import json

ADDON = "1011095603"
PRESENT = "onigiri_present"  # what it sets on Anki's main window as it loads (its api/bento.py)
HERE = '<i id="dc-here" hidden></i>'

GRID_JS = r"""<script>
(function () {
  var here = document.getElementById('dc-here');
  var cell = here && here.closest ? here.closest('.external-widget-container') : null;
  if (!cell || !cell.parentNode) { return; }
  var grid = cell.parentNode;
  cell.id = 'dc-oni-cell';
  function start(el) {
    if (!el.hasAttribute('data-dc-row')) {
      var cs = getComputedStyle(el), s = parseInt(cs.gridRowStart, 10), e = cs.gridRowEnd, n = 1;
      var m = /span\s+(\d+)/.exec(e);
      if (m) { n = parseInt(m[1], 10); } else if (parseInt(e, 10) > s) { n = parseInt(e, 10) - s; }
      el.setAttribute('data-dc-row', isNaN(s) ? '' : s + ',' + n);
    }
    var v = el.getAttribute('data-dc-row').split(',');
    return v.length === 2 ? {s: +v[0], n: +v[1]} : null;
  }
  function fit() {
    var me = start(cell);
    if (!me) { return; }
    var gs = getComputedStyle(grid), rowH = parseFloat(gs.gridAutoRows) || 0, gap = parseFloat(gs.rowGap) || 0;
    var inner = 0;
    for (var i = 0; i < cell.children.length; i++) { inner += cell.children[i].getBoundingClientRect().height; }
    var rows = rowH > 0 ? Math.max(1, Math.ceil((inner + 24 + gap) / (rowH + gap))) : me.n;
    cell.style.gridColumn = '1 / -1';
    cell.style.gridRow = me.s + ' / span ' + rows;
    for (var k = 0; k < grid.children.length; k++) {
      var el = grid.children[k];
      if (el === cell || el.tagName === 'STYLE' || el.tagName === 'SCRIPT') { continue; }
      var at = start(el);
      if (!at || at.s < me.s) { continue; }
      var to = at.s + (at.s >= me.s + me.n ? rows - me.n : rows);
      el.style.gridRowStart = to;
      el.style.gridRowEnd = 'span ' + at.n;
    }
  }
  cell.style.height = 'auto'; cell.style.maxHeight = 'none'; cell.style.overflow = 'visible';
  cell.style.textAlign = '-webkit-center';
  fit();
  if (window.ResizeObserver && !cell.dcWatch) {
    var t = null;
    cell.dcWatch = new ResizeObserver(function () { clearTimeout(t); t = setTimeout(fit, 60); });
    cell.dcWatch.observe(cell);
  }
})();
</script>"""


def under_js(html_out):
    """The draw `html_out` under a dashboard that didn't ask for it: into #dc-oni, the last thing in its
    main column (the page itself when it has none), its scripts run as a page's own would."""
    return """
    (function () {
        var host = document.getElementById('dc-oni');
        if (!host && document.getElementById('dc-here')) { return; }  // the page asked for the board: it's on it
        if (!host) {
            host = document.createElement('div');
            host.id = 'dc-oni';
            host.style.cssText = 'width:100%%;box-sizing:border-box;text-align:-webkit-center;margin:16px auto 0;';
            (document.querySelector('.main-content') || document.body).appendChild(host);
        }
        host.innerHTML = %s;
        var ss = host.querySelectorAll('script');
        for (var i = 0; i < ss.length; i++) {
            var n = document.createElement('script');
            n.text = ss[i].textContent;
            ss[i].parentNode.replaceChild(n, ss[i]);
        }
    })();
    """ % json.dumps(html_out).replace("</", "<\\/")


SHOW_JS = """
(function () {
    var el = document.getElementById('dc-oni') || document.getElementById('dc-oni-cell') || document.getElementById('due-crew');
    if (el) { el.scrollIntoView({behavior: 'smooth', block: 'start'}); }
})();
"""

ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16"><rect x="1" y="6" width="3" height="4" rx="1"/>'
        '<rect x="6.5" y="6" width="3" height="4" rx="1"/><rect x="12" y="6" width="3" height="4" rx="1"/></svg>')


def sidebar(command):
    """Due Crew in the dashboard's sidebar, by its own API; False where there's no such add-on (or it
    has no such API). Never raises: another add-on's code is not ours to trust."""
    try:
        import importlib
        api = importlib.import_module(ADDON + ".api.sidebar")
        api.register_sidebar_action("due_crew.board", "Due Crew", command, icon_svg=ICON)
        return True
    except Exception:
        return False
