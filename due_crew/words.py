"""3.10.0, languages: what a person reads, in theirs. Pure.

English is the key: `t("Add a tip")` gives the phrase in the language in
use, or the English when that language's file hasn't got it, so a missing
phrase is never a blank and the suites read English as before. A phrase
with a number or a name in it takes them by name: `t("{n} days", n=3)`;
one that changes with a count is `tn("{n} day", "{n} days", n)`.

The languages are files: `lang/<code>.json`, {English: theirs}. They were
drafted by AI (SC, 13 Nov 2026: said plainly where the language is picked,
with a way to send a better wording in one's own language): NOTE below.

Which one: Anki's own language unless Settings › Board › Language says
otherwise (`pick`); the glue calls `use` at a profile's open and when the
setting changes. Per computer, like the theme.

`tools/words.py` lists what the code asks for that a language hasn't got,
and what a file has that nothing asks for; the suite checks every file's
phrases keep their {names} and bring no markup of their own.
"""

import json
import os
import re

EN = "en"
# code -> its own name, as its speakers write it (never translated)
NAMES = {"en": "English", "es": "Español", "pt": "Português", "de": "Deutsch", "fr": "Français"}
AUTO = "auto"
CHOICES = (AUTO,) + tuple(NAMES)
NOTE = "Translations are drafted by AI. If a phrase reads wrong, send a better one."

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lang")
_state = {"lang": EN, "cat": {}}
_files = {}


def code_of(anki_lang):
    """Anki's language ("pt_BR", "es-ES", "de") as one of ours, or English."""
    head = re.split(r"[-_]", str(anki_lang or "").strip().lower())[0]
    return head if head in NAMES else EN


def pick(setting, anki_lang):
    """The language to use: Settings' choice, or with "auto" (or nothing, or one we haven't got) Anki's."""
    return setting if setting in NAMES else code_of(anki_lang)


def catalog(code):
    """A language's phrases, {English: theirs}, read once; {} for English, a missing file or a broken one."""
    if code == EN or code not in NAMES:
        return {}
    if code not in _files:
        try:
            with open(os.path.join(_DIR, code + ".json"), encoding="utf-8") as f:
                got = json.load(f)
            _files[code] = {k: v for k, v in got.items() if isinstance(k, str) and isinstance(v, str) and v} if isinstance(got, dict) else {}
        except (OSError, ValueError):
            _files[code] = {}
    return _files[code]


def use(code):
    """Speak `code` from here on (one we haven't got: English). Returns the one in use."""
    code = code if code in NAMES else EN
    _state.update(lang=code, cat=catalog(code))
    return code


def lang():
    return _state["lang"]


def t(text, **names):
    """`text` in the language in use (the English itself when it hasn't got it), its {names} filled."""
    said = _state["cat"].get(text, text)
    if not names:
        return said
    try:
        return said.format(**names)
    except (KeyError, IndexError, ValueError):
        return text.format(**names)  # a phrase whose names don't fit is said in English, whole


def later(text):
    """A phrase kept in a constant and said when it's drawn (`t(label)`): marks it for tools/words.py."""
    return text


def tn(one, many, n, **names):
    """The phrase for a count: `one` for exactly one, `many` otherwise, {n} filled."""
    return t(one if n == 1 else many, n=n, **names)


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def month(number):
    """A month's short name, 1 to 12."""
    return t(MONTHS[(int(number) - 1) % 12])


DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def weekday(number):
    """A weekday's short name, 0 (Monday) to 6, as date.weekday() counts."""
    return t(DAYS[int(number) % 7])


def names_of(phrase):
    """The {names} a phrase takes, sorted: a translation must take the same."""
    return sorted(set(re.findall(r"\{([a-z_]+)\}", phrase)))


def wrong(code):
    """What's wrong with a language's file, as lines ([]: nothing): a phrase whose {names} differ from
    its English, or one that brings markup the English hasn't."""
    out = []
    for en, theirs in sorted(catalog(code).items()):
        if names_of(en) != names_of(theirs):
            out.append(f"{code}: names differ: {en!r}")
        if ("<" in theirs) != ("<" in en) or any(c in theirs and c not in en for c in '&"'):
            out.append(f"{code}: markup: {en!r}")
    return out
