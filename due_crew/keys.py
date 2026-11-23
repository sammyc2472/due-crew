"""3.10.3: Anki's one-letter keys stand down while a box of ours is typed in (Lorry, 23 Nov 2026, Anki 26.09
on a Mac: "when sending messages to crew members (or most other fields) anki overwrites text and takes it
as shortcuts (e.g. b for browse)"). The Decks page says when a text box gains and loses the caret
(`WATCH_JS`, `duecrew:typing`); meanwhile every enabled shortcut of the main window that is one bare key is
off, and comes back as it was at the box's blur, at a change of screen, or at the next focus."""

WATCH_JS = """
(function () {
    if (window.dcTyping) { return; }
    window.dcTyping = true;
    function box(t) {
        return !!t && (t.tagName === 'TEXTAREA' || t.isContentEditable
            || (t.tagName === 'INPUT' && !/^(checkbox|radio|button|submit|range|color|file)$/.test(t.type)));
    }
    function say(on) { if (typeof pycmd !== 'undefined' && window.dcBK) { pycmd('duecrew:typing:' + on + '|' + window.dcBK); } }
    document.addEventListener('focusin', function (e) { if (box(e.target)) { say(1); } }, true);
    document.addEventListener('focusout', function (e) { if (box(e.target)) { say(0); } }, true);
})();
"""

_held = []


def bare(text):
    """Whether a shortcut's key, as Qt says it ("B", "Ctrl+B", "F5"), is one key alone that typing would hit."""
    return len(str(text or "")) == 1


def typing(on, mw=None):
    """Hold Anki's bare-key shortcuts (on) or give them back. Never raises."""
    try:
        for sc in _held:
            try:
                sc.setEnabled(True)
            except Exception:
                pass  # the screen changed and Anki dropped it
        del _held[:]
        if not on:
            return
        if mw is None:
            from aqt import mw
        try:
            from aqt.qt import QShortcut
        except Exception:
            QShortcut = object
        for sc in mw.findChildren(QShortcut):
            if sc.isEnabled() and bare(sc.key().toString()):
                sc.setEnabled(False)
                _held.append(sc)
    except Exception:
        pass
