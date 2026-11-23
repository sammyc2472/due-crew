"""3.10.2: beside a dashboard that takes the Decks screen's place (Onigiri, AnkiWeb 1011095603). Pure but
for `sidebar`.

Such an add-on draws the Decks screen itself and asks another add-on's render hook only for what a person
has placed in its grid, in a fixed cell, so the board (Due and the crew, one `#due-crew`) was missing. The maintainer,
18 Nov 2026: full width under its dashboard, and only there (in its grid too, for a day: taken out).

- `asked(mw, content)`: its grid asking our hook for a cell's worth: the hook draws nothing there.
- `under_js(html)`: the board's draw put under what the dashboard drew (`#dc-oni`), its scripts run.
- `sidebar(command)`: its sidebar's own way in for other add-ons, a "Due Crew" entry that brings the board
  into view. Onigiri keeps a new entry in its archive until a person shows it.
"""

import json

ADDON = "1011095603"
PRESENT = "onigiri_present"  # what it sets on Anki's main window as it loads (its api/bento.py)

def asked(mw, content):
    """Whether this is the dashboard's grid asking our hook for a widget (what it hands over has no deck
    tree; Anki's own, and ours for under it, have)."""
    return bool(getattr(mw, PRESENT, False)) and not hasattr(content, "tree")


def under_js(html_out):
    """The draw `html_out` under a dashboard that didn't ask for it: into #dc-oni, the last thing in its
    main column (the page itself when it has none), its scripts run as a page's own would."""
    return """
    (function () {
        var host = document.getElementById('dc-oni');
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
    var el = document.getElementById('dc-oni') || document.getElementById('due-crew');
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
