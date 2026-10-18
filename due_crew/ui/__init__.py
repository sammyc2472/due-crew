"""Shared dialog plumbing.

attach_alive() must be called once per dialog: it sets dialog._alive and
clears it on the `finished` signal, which Qt emits for every way a dialog
ends (accept, reject, Esc, window close) — unlike closeEvent, which
accept()/reject() skip.

run_bg() runs a job off the main thread and delivers (result, error_code)
back on the main thread, only while the owner is still alive. error_code is
an AuthError code, "NETWORK" for transport failures, or None.
"""

import subprocess
import sys

from aqt import mw
from aqt.qt import QApplication

from ..backend.shapes import AuthError, TransportError


def copy_text(text):
    """Put text on the system clipboard (_clip), and say so on the board's
    link that asked for it (3.8.0, Board in Motion 32: Copied ✓ in place;
    the page knows which link was clicked, and a copy from a dialog finds
    none and shows nothing)."""
    ok = _clip(text)
    try:
        if mw.web:
            mw.web.eval("try{window.dcMotion&&dcMotion.copied();}catch(e){}")
    except Exception:
        pass
    return ok


def _clip(text):
    """Put text on the system clipboard, emoji and all.

    Qt's macOS pasteboard also offers a legacy "traditional Mac plain text"
    flavor, converted through Latin-1 with '?' for anything it can't encode
    — and some apps paste that one, turning every emoji and block glyph
    into '?' (and '·' into '∑'). pbcopy under a UTF-8 locale writes only
    the UTF-8 flavor, so it goes first on macOS; Qt with explicit UTF-8
    mime data is the fallback everywhere else."""
    text = str(text)
    if sys.platform == "darwin":
        try:
            subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True,
                           timeout=5, env={"LC_ALL": "en_US.UTF-8",
                                           "LANG": "en_US.UTF-8",
                                           "PATH": "/usr/bin:/bin"})
            return True
        except Exception:
            pass  # fall through to Qt
    clip = QApplication.clipboard()
    try:
        from aqt.qt import QMimeData
        mime = QMimeData()
        mime.setText(text)
        mime.setData("text/plain;charset=utf-8", text.encode("utf-8"))
        clip.setMimeData(mime)
    except Exception:
        clip.setText(text)
    return True


def open_emoji_picker(edit):
    """Open the system emoji palette over a text field: on macOS the one
    Ctrl-Cmd-Space opens, asked for through AppKit; on Windows the Win-period
    panel, by pressing the keys for the user. Both type the pick into the
    focused field. False where there is no palette (Linux), and the field
    takes a typed or pasted emoji instead. Never raises."""
    edit.setFocus()
    try:
        if sys.platform == "darwin":
            return _mac_character_palette()
        if sys.platform == "win32":
            return _win_emoji_panel()
    except Exception:
        pass
    return False


def _mac_character_palette():
    import ctypes
    objc = ctypes.cdll.LoadLibrary("/usr/lib/libobjc.dylib")
    ctypes.cdll.LoadLibrary("/System/Library/Frameworks/AppKit.framework/AppKit")
    objc.objc_getClass.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = [ctypes.c_char_p]
    objc.sel_registerName.restype = ctypes.c_void_p
    objc.sel_registerName.argtypes = [ctypes.c_char_p]
    # objc_msgSend is variadic; a fixed prototype per arity is what makes the
    # arguments land on arm64 (a wrong one here is a crash, not an exception:
    # checked in a real Qt process on an Apple Silicon Mac, 2026-09-23)
    send0 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", objc))
    send1 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(
        ("objc_msgSend", objc))
    cls = objc.objc_getClass(b"NSApplication")
    nsapp = send0(cls, objc.sel_registerName(b"sharedApplication")) if cls else None
    if not nsapp:
        return False
    send1(nsapp, objc.sel_registerName(b"orderFrontCharacterPalette:"), None)
    return True


def _win_emoji_panel():
    import ctypes
    user32 = ctypes.windll.user32
    lwin, period, keyup = 0x5B, 0xBE, 0x0002
    for key, flags in ((lwin, 0), (period, 0), (period, keyup), (lwin, keyup)):
        user32.keybd_event(key, 0, flags, 0)
    return True


def _night():
    try:
        from aqt.theme import theme_manager
        return bool(theme_manager.night_mode)
    except Exception:
        return False


def _dark():
    """3.9.1: the board's theme (Settings › Theme), so a window wears what
    the board does; Match Anki follows Anki's night mode."""
    try:
        from ..app import cfg
        theme = cfg().get("theme", "auto")
    except Exception:
        theme = "auto"
    return theme == "dark" if theme in ("light", "dark") else _night()


def _mix(a, b, t):
    """Colour a moved toward b by t (0 to 1), as #rrggbb."""
    a, b = a.lstrip("#"), b.lstrip("#")
    return "#" + "".join(f"{round(int(a[i:i + 2], 16) * (1 - t) + int(b[i:i + 2], 16) * t):02x}"
                         for i in (0, 2, 4))


def tokens():
    """The board's colours for its theme and accent (board.palette), its red
    for a step that can't be taken back, and what a window draws that the
    board does in CSS: a box's edge, a tick's (edge-2, darker: it has to be
    seen), a pressed button, the main action under the pointer, and its
    ring when the keyboard is on it; and the small print's ink (ink-2,
    between muted and ink: a window's notes are read, not glanced at)."""
    from ..board import palette
    dark = _dark()
    t = dict(palette("dark" if dark else "light", _accent_name()))
    t.update({"bad": danger(), "bad-ink": "#2a1212" if dark else "#ffffff"})
    toward = "#ffffff" if dark else "#000000"
    t.update({"edge": _mix(t["line"], t["muted"], .4), "edge-2": _mix(t["line"], t["muted"], .75),
              "press": _mix(t["well"], t["line"], .7), "go-hover": _mix(t["accent"], toward, .12),
              "bad-hover": _mix(t["bad"], toward, .12), "go-ring": _mix(t["accent"], t["mark"], .3),
              "ink-2": _mix(t["muted"], t["ink"], .4)})
    return t


def tone(key):
    """One of the board's colours (tokens) for a label's own style sheet:
    a window in the board's look ignores its palette, so palette(mid) and
    the like would come out Anki's, not the board's."""
    try:
        return tokens()[key]
    except Exception:
        return {"muted": "#7a7a72", "faded": "#aaaaa2", "line": "#e2e2da", "well": "#f2f2ec", "bg": "#ffffff",
                "ink": "#333333", "ink-2": "#5e5e58", "mark": "#242424", "accent": "#2e7d32",
                "you-bg": "#e9f2e9", "hours": "#b26a00"}.get(key, "#7a7a72")


def title(text):
    """A window's heading (role "title"), as the board's sheets have: plain
    text, since a plan's or a person's name can be in it."""
    from aqt.qt import QLabel, Qt
    label = QLabel(str(text))
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return role(label, "title")


def heading(dialog, layout, text=None):
    """The window's title at the top of its layout, in the board's type
    (title), and "Due Crew" on its frame instead, so the words aren't said
    twice: the frame says whose window it is, the window what it's for."""
    label = title(dialog.windowTitle() if text is None else text)
    label.setContentsMargins(0, 0, 0, 4)
    layout.insertWidget(0, label)
    dialog.setWindowTitle("Due Crew")
    return label


def note(label):
    """Small print under a choice or a box (role "note"), word-wrapped."""
    label.setWordWrap(True)
    return role(label, "note")


def role(label, name):
    """A label's part in the window (the style sheet's QLabel[dc=...]):
    "title" the window's own heading, "head" a part's, "note" the small
    print under a choice. One type scale for every window, not each its
    own font sizes."""
    label.setProperty("dc", name)
    return label


# 3.9.1 (Sam: "make sure all modals are in our style", then "washed out, bad
# spacing, not engaging"): a Qt window in the board's look, as its sheets and
# the Cheer window are. Every box, arrow, tick, radio dot and list is drawn
# here, on Fusion (base_style), so a Mac, Windows and Linux, and Anki's own
# style or the system's, all get the same window: a style sheet over the
# Mac's native style dressed the box but left its arrow and popup native.
# Sizes in px, as the board's: 13 the text, 12 the small print, 16 a title;
# 8px corners; boxes and buttons 30px high. The window's frame stays the
# computer's.
QSS = """
* {{ font-size: 13px; }}
QDialog, QMessageBox, QInputDialog {{ background: {bg}; color: {ink}; }}
QLabel {{ color: {ink}; background: transparent; border: none; }}
QLabel:disabled {{ color: {faded}; }}
QLabel[dc="title"] {{ font-size: 16px; font-weight: 700; color: {mark}; }}
QLabel[dc="head"] {{ font-weight: 700; color: {mark}; }}
QLabel[dc="note"] {{ font-size: 12px; color: {ink-2}; }}
QMessageBox QLabel#qt_msgbox_label {{ font-size: 16px; font-weight: 700; color: {mark}; }}

QPushButton {{ background: {bg}; color: {ink}; border: 1px solid {edge}; border-radius: 8px; padding: 6px 16px; margin: 0; min-height: 16px; }}
QPushButton:default {{ border: 1px solid {edge}; }}
QPushButton:hover {{ background: {well}; }}
QPushButton:pressed {{ background: {press}; }}
QPushButton:checked {{ background: {you-bg}; border: 1px solid {accent}; }}
QPushButton:focus {{ border: 2px solid {accent}; padding: 5px 15px; outline: none; }}
QPushButton:disabled {{ background: {bg}; color: {faded}; border: 1px solid {line}; }}
QPushButton:flat {{ background: transparent; color: {accent}; border: 1px solid transparent; }}
QPushButton:flat:hover {{ background: {well}; }}
QPushButton[dc="go"] {{ background: {accent}; color: {accent-ink}; border: 1px solid {accent}; font-weight: 700; }}
QPushButton[dc="go"]:hover {{ background: {go-hover}; border-color: {go-hover}; }}
QPushButton[dc="go"]:focus {{ border: 2px solid {go-ring}; }}
QPushButton[dc="bad"] {{ background: {bad}; color: {bad-ink}; border: 1px solid {bad}; font-weight: 700; }}
QPushButton[dc="bad"]:hover {{ background: {bad-hover}; border-color: {bad-hover}; }}
QPushButton[dc="go"]:disabled, QPushButton[dc="bad"]:disabled {{ background: {well}; color: {faded}; border: 1px solid {line}; }}

QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox {{ background: {bg}; color: {ink}; border: 1px solid {edge}; border-radius: 8px; padding: 6px 10px; margin: 0; selection-background-color: {accent}; selection-color: {accent-ink}; }}
QLineEdit:hover, QPlainTextEdit:hover, QTextEdit:hover, QAbstractSpinBox:hover, QComboBox:hover {{ border-color: {edge-2}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border: 2px solid {accent}; padding: 5px 9px; }}
QLineEdit:disabled, QPlainTextEdit:disabled, QTextEdit:disabled, QAbstractSpinBox:disabled, QComboBox:disabled {{ color: {faded}; border-color: {line}; background: {bg}; }}
QPlainTextEdit, QTextEdit {{ padding: 6px 8px; }}

QComboBox {{ padding: 6px 30px 6px 10px; combobox-popup: 0; }}
QComboBox:focus, QComboBox:on {{ border: 2px solid {accent}; padding: 5px 29px 5px 9px; }}
QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: center right; width: 30px; border: none; background: transparent; margin: 0; padding: 0; }}
QComboBox::down-arrow {{ image: url("{i-down}"); width: 12px; height: 12px; }}
QComboBox::down-arrow:disabled {{ image: url("{i-down-off}"); }}
QComboBox QAbstractItemView {{ background: {bg}; color: {ink}; border: 1px solid {edge}; padding: 4px; outline: 0; selection-background-color: {you-bg}; selection-color: {ink}; }}
QComboBox QAbstractItemView::item {{ min-height: 28px; padding: 0 8px; border: none; border-radius: 6px; color: {ink}; background: transparent; }}
QComboBox QAbstractItemView::item:hover, QComboBox QAbstractItemView::item:selected {{ background: {you-bg}; color: {ink}; }}

QAbstractSpinBox {{ padding: 6px 28px 6px 10px; }}
QAbstractSpinBox:focus {{ border: 2px solid {accent}; padding: 5px 27px 5px 9px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 24px; border: none; background: transparent; margin: 0; padding: 0; }}
QAbstractSpinBox::up-button {{ subcontrol-position: top right; border-top-right-radius: 8px; }}
QAbstractSpinBox::down-button {{ subcontrol-position: bottom right; border-bottom-right-radius: 8px; }}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{ background: {well}; }}
QAbstractSpinBox::up-button:pressed, QAbstractSpinBox::down-button:pressed {{ background: {press}; }}
QAbstractSpinBox::up-arrow {{ image: url("{i-up}"); width: 10px; height: 10px; }}
QAbstractSpinBox::down-arrow {{ image: url("{i-down}"); width: 10px; height: 10px; }}
QAbstractSpinBox::up-arrow:disabled, QAbstractSpinBox::up-arrow:off {{ image: url("{i-up-off}"); }}
QAbstractSpinBox::down-arrow:disabled, QAbstractSpinBox::down-arrow:off {{ image: url("{i-down-off}"); }}
QDateTimeEdit::drop-down {{ subcontrol-origin: border; subcontrol-position: center right; width: 30px; border: none; background: transparent; margin: 0; padding: 0; }}
QDateTimeEdit::down-arrow {{ image: url("{i-down}"); width: 12px; height: 12px; }}

QCheckBox, QRadioButton {{ color: {ink}; background: transparent; spacing: 8px; margin: 0; padding: 2px 0; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {faded}; }}
QCheckBox::indicator, QRadioButton::indicator, QAbstractItemView::indicator {{ width: 16px; height: 16px; border: 1px solid {edge-2}; background: {bg}; margin: 0; image: none; }}
QCheckBox::indicator, QAbstractItemView::indicator {{ border-radius: 5px; }}
QRadioButton::indicator {{ border-radius: 9px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover, QAbstractItemView::indicator:hover {{ border-color: {accent}; }}
QCheckBox:focus {{ outline: none; }}
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {{ background: {accent}; border: 1px solid {accent}; image: url("{i-check}"); }}
QRadioButton::indicator:checked {{ background: {accent-ink}; border: 5px solid {accent}; width: 8px; height: 8px; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {line}; background: {well}; }}
QCheckBox::indicator:checked:disabled {{ background: {faded}; border-color: {faded}; image: url("{i-check}"); }}
QRadioButton::indicator:checked:disabled {{ background: {bg}; border: 5px solid {faded}; }}

QListWidget, QListView, QTreeWidget, QTreeView, QTableWidget {{ background: {bg}; color: {ink}; border: 1px solid {edge}; border-radius: 10px; padding: 4px; outline: 0; alternate-background-color: {well}; selection-background-color: {you-bg}; selection-color: {ink}; }}
QListWidget::item, QListView::item, QTreeView::item, QTableWidget::item {{ padding: 4px 6px; border: none; color: {ink}; }}
QListWidget::item:hover, QListView::item:hover, QTreeView::item:hover {{ background: {well}; }}
QListWidget::item:selected, QListView::item:selected, QTreeView::item:selected, QTableWidget::item:selected {{ background: {you-bg}; color: {ink}; }}
QTreeView::branch {{ background: transparent; border: none; image: none; }}
QTreeView::branch:has-children:closed {{ image: url("{i-right}"); }}
QTreeView::branch:has-children:open {{ image: url("{i-down}"); }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: transparent; color: {muted}; border: none; border-bottom: 1px solid {line}; padding: 2px 6px 6px 6px; font-size: 12px; font-weight: 700; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px 2px 2px 0; border: none; }}
QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 0 2px 2px 2px; border: none; }}
QScrollBar::handle {{ background: {edge}; border: none; border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:vertical {{ margin: 0 2px; }}
QScrollBar::handle:horizontal {{ margin: 2px 0; }}
QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background: {edge-2}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QAbstractScrollArea::corner {{ background: transparent; border: none; }}

QCalendarWidget QWidget {{ background: {bg}; color: {ink}; alternate-background-color: {bg}; }}
QCalendarWidget QWidget#qt_calendar_navigationbar {{ background: {bg}; border-bottom: 1px solid {line}; }}
QCalendarWidget QToolButton {{ color: {ink}; background: transparent; border: none; border-radius: 6px; padding: 4px 8px; margin: 2px; font-weight: 700; }}
QCalendarWidget QToolButton:hover {{ background: {well}; }}
QCalendarWidget QToolButton::menu-indicator {{ image: none; width: 0; }}
QCalendarWidget QToolButton#qt_calendar_prevmonth {{ qproperty-icon: url("{i-left}"); }}
QCalendarWidget QToolButton#qt_calendar_nextmonth {{ qproperty-icon: url("{i-right}"); }}
QCalendarWidget QAbstractItemView {{ background: {bg}; color: {ink}; border: none; outline: 0; padding: 0; selection-background-color: {accent}; selection-color: {accent-ink}; }}
QCalendarWidget QAbstractItemView:disabled {{ color: {faded}; }}
QCalendarWidget QSpinBox {{ padding: 2px 22px 2px 6px; }}

QGroupBox {{ border: 1px solid {line}; border-radius: 10px; margin-top: 14px; padding: 10px 8px 8px 8px; background: transparent; font-weight: 700; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 10px; padding: 0 4px; margin: 0; color: {muted}; }}
QFrame[frameShape="4"] {{ border: none; background: {line}; min-height: 1px; max-height: 1px; }}
QDialogButtonBox {{ background: transparent; }}
QMenu {{ background: {bg}; color: {ink}; border: 1px solid {edge}; padding: 4px; }}
QMenu::item {{ background: transparent; padding: 5px 16px; margin: 0; border-radius: 6px; }}
QMenu::item:selected {{ background: {you-bg}; color: {ink}; }}
QMenu::separator {{ height: 1px; background: {line}; margin: 4px 8px; }}
QToolTip {{ background: {bg}; color: {ink}; border: 1px solid {edge}; padding: 4px 6px; }}
"""

# a chevron or a tick, drawn on a 16px square; each a file the style sheet names
_SHAPES = {
    "down": '<path d="M4.5 6.25 8 9.75l3.5-3.5"/>',
    "up": '<path d="M4.5 9.75 8 6.25l3.5 3.5"/>',
    "left": '<path d="M9.75 4.5 6.25 8l3.5 3.5"/>',
    "right": '<path d="M6.25 4.5 9.75 8l-3.5 3.5"/>',
    "check": '<path d="M3.75 8.4 6.6 11.2 12.25 5.2" stroke-width="2.2"/>',
}
_ICON_DIR = []


def _icon_dir():
    """Where the drawings go: user_files/_qt beside the add-on (kept across
    updates), or the computer's temp folder. '' where neither takes a file."""
    if not _ICON_DIR:
        import os
        import tempfile
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for d in (os.path.join(here, "user_files", "_qt"), os.path.join(tempfile.gettempdir(), "due-crew-qt")):
            try:
                os.makedirs(d, exist_ok=True)
                _ICON_DIR.append(d)
                break
            except OSError:
                continue
        else:
            _ICON_DIR.append("")
    return _ICON_DIR[0]


def _icon(shape, colour):
    """The path of one drawing in one colour, written the first time (Qt's
    style sheets take an image from a file, not from text), with / for every
    computer's separator. '' if it can't be written: the box goes without."""
    import os
    folder = _icon_dir()
    if not folder:
        return ""
    path = os.path.join(folder, f"{shape}-{colour.lstrip('#').lower()}.svg")
    if not os.path.isfile(path):
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
               f'<g fill="none" stroke="{colour}" stroke-width="1.8" stroke-linecap="round" '
               f'stroke-linejoin="round">{_SHAPES[shape]}</g></svg>')
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
        except OSError:
            return ""
    return path.replace("\\", "/").replace('"', "")


def qss(t=None):
    """The style sheet for these tokens (tokens() unless given), its arrows
    and tick drawn in them."""
    t = dict(t or tokens())
    for shape, key in (("down", "muted"), ("up", "muted"), ("left", "muted"), ("right", "muted")):
        t[f"i-{shape}"] = _icon(shape, t[key])
        t[f"i-{shape}-off"] = _icon(shape, t["faded"])
    t["i-check"] = _icon("check", t["accent-ink"])
    return QSS.format(**t)


_STYLE = []


def base_style():
    """Fusion under every Due Crew window, whatever Anki's own style is (the
    Mac's native style draws a dressed box's arrow and its popup its own
    way), with a window's edges and the room between its rows a little
    more generous: 22px at the sides, 8 between rows. One for the session;
    None where this Qt has no Fusion."""
    if not _STYLE:
        from aqt.qt import QProxyStyle, QStyle, QStyleFactory
        fusion = QStyleFactory.create("Fusion")
        if fusion is None:
            return None
        M = QStyle.PixelMetric
        edges = {M.PM_LayoutLeftMargin: 22, M.PM_LayoutRightMargin: 22,
                 M.PM_LayoutTopMargin: 20, M.PM_LayoutBottomMargin: 18}
        gaps = {M.PM_LayoutHorizontalSpacing: 8, M.PM_LayoutVerticalSpacing: 8}

        class DcStyle(QProxyStyle):
            def pixelMetric(self, metric, option=None, widget=None):
                if metric in gaps:
                    return gaps[metric]
                if metric in edges and widget is not None and widget.isWindow():
                    return edges[metric]
                return super().pixelMetric(metric, option, widget)
        _STYLE.append(DcStyle(fusion))
    return _STYLE[0]


def styled(dialog):
    """The board's look on a Qt window: base_style under it, the style sheet
    (qss) over every box, arrow, tick and list, and its palette for what
    paints itself (a chart, a link); a label's own style sheet takes tone(),
    as palette(...) there would be Anki's. As it first shows, _tidy does
    what a style sheet can't, and its default button turns the accent,
    unless it says already which is which (confirm's yes). Never raises:
    the suite's Qt has none of it."""
    try:
        from aqt.qt import QColor, QPalette
        t = tokens()
        pal = dialog.palette()
        R, G = QPalette.ColorRole, QPalette.ColorGroup
        for role_, key in (("Window", "bg"), ("WindowText", "ink"), ("Base", "bg"), ("AlternateBase", "well"),
                           ("Text", "ink"), ("Button", "bg"), ("ButtonText", "ink"), ("PlaceholderText", "faded"),
                           ("Mid", "muted"), ("Highlight", "accent"), ("HighlightedText", "accent-ink"),
                           ("ToolTipBase", "bg"), ("ToolTipText", "ink"), ("Link", "accent"), ("LinkVisited", "accent")):
            pal.setColor(getattr(R, role_), QColor(t[key]))
        for role_ in ("WindowText", "Text", "ButtonText"):
            pal.setColor(G.Disabled, getattr(R, role_), QColor(t["faded"]))
        dialog.setPalette(pal)
        style = base_style()
        if style is not None:
            dialog.setStyle(style)
        dialog.setStyleSheet(qss(t))
        dialog.installEventFilter(_marker(dialog))
    except Exception:
        pass
    return dialog


def _tidy(dialog):
    """What a style sheet can't reach, done before the window takes its
    size (it's polished first; again as it shows, for anything added since):
    a box's list drawn by rows the sheet dresses (Qt's own row ignores it),
    and never narrower than its words (up to 240px: a long deck name may
    still be cut); a calendar's weekends in ink rather than red, no week
    numbers, its days roomier; room above the window's row of buttons. True if it changed
    anything."""
    from aqt.qt import (QCalendarWidget, QColor, QComboBox, QDateTimeEdit, QDialogButtonBox,
                        QStyledItemDelegate, QTextCharFormat, Qt)
    changed = False
    t = None
    for box in dialog.findChildren(QComboBox):
        if box.property("dcTidy"):
            continue
        box.setProperty("dcTidy", True)
        box.setItemDelegate(QStyledItemDelegate(box))
        box.setMinimumWidth(max(box.minimumWidth(), min(box.sizeHint().width(), 240)))
        changed = True
    cals = list(dialog.findChildren(QCalendarWidget))
    cals += [e.calendarWidget() for e in dialog.findChildren(QDateTimeEdit) if e.calendarPopup()]
    for cal in cals:
        if cal is None or cal.property("dcTidy"):
            continue
        cal.setProperty("dcTidy", True)
        t = t or tokens()
        day = QTextCharFormat()
        day.setForeground(QColor(t["ink"]))
        for d in (Qt.DayOfWeek.Saturday, Qt.DayOfWeek.Sunday):
            cal.setWeekdayTextFormat(d, day)
        head = QTextCharFormat()
        head.setForeground(QColor(t["muted"]))
        cal.setHeaderTextFormat(head)
        cal.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        cal.setMinimumSize(max(cal.minimumWidth(), 280), max(cal.minimumHeight(), 230))  # rows with room to tap
        changed = True
    top = dialog.layout()
    for row in dialog.findChildren(QDialogButtonBox):
        m = row.contentsMargins()
        alone = top is not None and top.indexOf(row) >= 0  # its own row, not beside a button of the window's
        if alone and not (row.property("dcTidy") or m.left() or m.top() or m.right() or m.bottom()):
            row.setProperty("dcTidy", True)
            row.setContentsMargins(0, 8, 0, 0)
            changed = True
    return changed


def _fit(window):
    """Wide enough for its rows and tall enough for its words at that width.
    Qt sizes a new window from its widest-and-shortest wish and then caps it
    at two thirds of the screen, so a window of wrapped lines (Follow a
    plan's) came out shorter than they need and its rows ran into each
    other; and a window with a minimum width of its own never widens for a
    row that grows after it opened (Friends' code, once it arrives), so the
    row's buttons slid over each other. It grows to what they need, up to
    the screen it's on. It never shrinks a window."""
    try:
        window.setProperty("dcFit", False)
        lay = window.layout()
        if lay is None or not window.isVisible():
            return
        w, h = window.width(), window.height()
        room = window.screen().availableGeometry() if window.screen() is not None else None
        frame_w = max(window.frameGeometry().width() - w, 0)
        frame_h = max(window.frameGeometry().height() - h, 0)
        least = lay.totalMinimumSize()
        need_w = max(w, least.width())
        if room is not None:
            need_w = min(need_w, room.width() - frame_w)
        need_h = max(h, least.height())
        if lay.hasHeightForWidth():
            need_h = max(need_h, lay.totalHeightForWidth(need_w))
        if room is not None:
            need_h = min(need_h, room.height() - frame_h)
        if (need_w, need_h) != (w, h) and need_w >= w and need_h >= h:
            window.resize(need_w, need_h)
    except Exception:
        pass  # a window gone before its turn came


def _mark(dialog):
    """The default button in the accent (dc="go"), when no button is marked:
    the one the window chose (setDefault, or its button box's OK), never a
    link-like one (flat, or dressed by its own style sheet)."""
    try:
        from aqt.qt import QPushButton
        buttons = dialog.findChildren(QPushButton)
        if any(b.property("dc") for b in buttons):
            return
        for b in buttons:
            if b.isDefault() and not b.isFlat() and not b.styleSheet():
                b.setProperty("dc", "go")
                b.style().unpolish(b)
                b.style().polish(b)
    except Exception:
        pass


_MARKER = []


def _marker(dialog):
    """An event filter, the dialog's child, that tidies it as it's polished
    (before it takes its size) and as it shows, and then marks its buttons:
    by then its own default is set (and its button box's), and focus hasn't
    yet moved one to whichever button it lands on."""
    if not _MARKER:
        from aqt.qt import QEvent, QObject, Qt, QTimer

        class Marker(QObject):
            def eventFilter(self, obj, ev):
                kind = ev.type()
                if obj is not self.parent():
                    return False
                if kind in (QEvent.Type.Polish, QEvent.Type.Show):
                    try:
                        grew = _tidy(obj)
                    except Exception:
                        grew = False
                    if kind == QEvent.Type.Show:
                        if grew and not obj.testAttribute(Qt.WidgetAttribute.WA_Resized):
                            obj.adjustSize()  # what came after its size was taken still fits
                        _mark(obj)
                if kind in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest) and not obj.property("dcFit"):
                    obj.setProperty("dcFit", True)  # one look at a time, once the layout has settled
                    QTimer.singleShot(0, lambda w=obj: _fit(w))
                return False
        _MARKER.append(Marker)
    return _MARKER[0](dialog)


def _accent_name():
    from ..board import DEFAULT_ACCENT
    try:
        return (mw.addonManager.getConfig(__name__) or {}).get("accent") or DEFAULT_ACCENT
    except Exception:
        return DEFAULT_ACCENT


def accent():
    """The board's accent (Settings → Accent) in the shade made for Anki's
    current theme. Until 2.9 dialogs were always green. Dialogs rebuild on
    every open, so a change is picked up next time."""
    shade = "dark" if _dark() else "light"
    try:
        from ..board import ACCENTS, DEFAULT_ACCENT
        return ACCENTS.get(_accent_name(), ACCENTS[DEFAULT_ACCENT])[shade][0]
    except Exception:
        return "#7cc47f" if shade == "dark" else "#2e7d32"


def _svg_by_renderer(data, w, h):
    """The image plugin's stand-in: QtSvg's renderer, where the build has
    it. None where it doesn't."""
    try:
        from PyQt6.QtCore import QByteArray, Qt
        from PyQt6.QtGui import QImage, QPainter
        from PyQt6.QtSvg import QSvgRenderer
    except Exception:
        return None
    renderer = QSvgRenderer(QByteArray(data))
    if not renderer.isValid():
        return None
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def logo_label(width=150):
    """The stacked logo in the user's accent and Anki's theme (2.10), for
    the top of the sign-in and welcome screens, or None if this Qt can't
    draw SVG (then the screen goes without). Drawn at the screen's pixel
    ratio so it stays sharp; one square's width of clear space around it."""
    from aqt.qt import QLabel
    from ..logo import ASPECT, svg
    pixmap = _svg_pixmap(svg("dark" if _dark() else "light", _accent_name()), width, round(width * ASPECT))
    if pixmap is None:
        return None
    label = QLabel()
    label.setPixmap(pixmap)
    label.setAccessibleName("Due Crew")
    clear = round(width * 40 / 401)  # one square
    label.setContentsMargins(4, 4, 0, clear)  # the dialog's margin makes up the rest
    return label


def _svg_pixmap(markup, width, height):
    """An SVG drawn at the screen's pixel ratio, so it stays sharp; None if
    this Qt can't draw SVG."""
    from aqt.qt import QBuffer, QByteArray, QGuiApplication, QIODevice, QImageReader, QPixmap, QSize
    try:
        ratio = max(1.0, float(QGuiApplication.primaryScreen().devicePixelRatio()))
    except Exception:
        ratio = 1.0
    w, h = round(width * ratio), round(height * ratio)
    data = markup.encode("utf-8")
    buf = QBuffer()
    buf.setData(QByteArray(data))
    buf.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buf, QByteArray(b"svg"))
    reader.setScaledSize(QSize(w, h))
    image = reader.read()
    if image.isNull():
        image = _svg_by_renderer(data, w, h)
    if image is None or image.isNull():
        return None
    pixmap = QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


def sev_label(pose="hello", size=64, name="Pip"):
    """3.8.1: Pip in a dialog's corner (Welcome back), in the accent and
    Anki's theme: sev.py's one drawing, still (a Qt window can't play the
    board's motion; it's the frame Reduce motion shows). None if this Qt
    can't draw SVG: the dialog goes without."""
    from aqt.qt import QLabel, Qt
    from ..sev import still
    try:  # 3.8.2: in what it has on from the closet
        from ..closet_flow import look
        mine = look()
    except Exception:
        mine = None
    pixmap = _svg_pixmap(still(pose, accent(), look=mine), size, size)
    if pixmap is None:
        return None
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)  # a picture; never markup
    label.setPixmap(pixmap)
    label.setAccessibleName(name)
    return label


def danger():
    return "#ef8383" if _dark() else "#d32f2f"


def warn():
    """The board's warning colour (its "hours" token), for "not in your copy"."""
    return "#dda45c" if _dark() else "#b26a00"


def esc(text):
    """For rich-text labels: anything from the server or a deck goes through this."""
    import html
    return html.escape(str(text))


def confirm(parent, title, text, yes, danger=False):
    """The one way to ask before a step that can't be taken back: the button
    says what happens ("Remove", "Leave"), Cancel is the default, and the
    text is plain, because names in it come from the server. Until 2.9 there
    were three styles of this. 3.9.1: in the board's look, as its sheet
    (sheets.confirm, whose fallback this is): the title in bold over the
    words, no icon, the yes in the accent (danger: the board's red)."""
    box, go = _question(parent, title, text, yes, danger)
    box.exec()
    return box.clickedButton() is go


def confirm_check(parent, title, text, yes, check, checked=True, danger=False):
    """confirm, with one box to tick under the text (3.8.0: "Take its tags
    off my notes too"). Returns (yes, ticked)."""
    from aqt.qt import QCheckBox
    box, go = _question(parent, title, text, yes, danger)
    tick = QCheckBox(check)
    tick.setChecked(bool(checked))
    box.setCheckBox(tick)
    box.exec()
    return box.clickedButton() is go, tick.isChecked()


def _question(parent, title, text, yes, danger):
    from aqt.qt import QMessageBox, Qt
    box = QMessageBox(parent or mw)
    box.setIcon(QMessageBox.Icon.NoIcon)
    box.setWindowTitle("Due Crew")  # the title is the box's own words (ui.heading)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(title)
    if text:
        box.setInformativeText(text)  # plain too: the box's format holds for both
    go = box.addButton(yes, QMessageBox.ButtonRole.AcceptRole)
    cancel = box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(cancel)
    go.setProperty("dc", "bad" if danger else "go")
    cancel.setProperty("dc", "no")
    styled(box)
    return box, go


def _plain_input(parent, title, label):
    """A QInputDialog whose label is plain text: names in it come from the
    server, and Qt reads a label with a tag in it as rich text."""
    from aqt.qt import QInputDialog, QLabel, Qt
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    for lb in dlg.findChildren(QLabel):
        lb.setTextFormat(Qt.TextFormat.PlainText)
    return styled(dlg)


def ask_text(parent, title, label, text=""):
    """(text, ok), as QInputDialog.getText, with a plain-text label."""
    dlg = _plain_input(parent, title, label)
    dlg.setTextValue(text)
    ok = bool(dlg.exec())
    return dlg.textValue(), ok


def ask_item(parent, title, label, items, current=0):
    """(item, ok), as QInputDialog.getItem (not editable), with a plain-text label."""
    dlg = _plain_input(parent, title, label)
    dlg.setComboBoxItems(list(items))
    dlg.setComboBoxEditable(False)
    if items:
        dlg.setTextValue(items[max(0, min(current, len(items) - 1))])
    ok = bool(dlg.exec())
    return dlg.textValue(), ok


def shared_words(cfg):
    """The numbers the Privacy switches share, as words for a sentence:
    "reviews, time, retention, and streak". '' when none are."""
    words = [w for key, w in (("share_reviews", "reviews"), ("share_time", "time"),
                              ("share_retention", "retention"), ("share_streak", "streak"))
             if cfg.get(key, True)]
    if len(words) <= 2:
        return " and ".join(words)
    return ", ".join(words[:-1]) + f", and {words[-1]}"


def attach_alive(dialog):
    dialog._alive = True
    dialog.finished.connect(lambda _=0: setattr(dialog, "_alive", False))
    styled(dialog)  # 3.9.1: every window that comes here wears the board's look


def run_bg(owner, job, done):
    def worker():
        try:
            result, err = job(), None
        except AuthError as e:
            result, err = None, e.code
        except TransportError:
            result, err = None, "NETWORK"
        except Exception:
            result, err = None, "NETWORK"
        mw.taskman.run_on_main(
            lambda: getattr(owner, "_alive", False) and done(result, err))
    mw.taskman.run_in_background(worker)
