# Languages

Due Crew in Spanish, Portuguese, German and French, beside English (SC, 13 Nov 2026). Drafted by AI, said
so where the language is picked, with a way to send a better wording. Anki's language unless Settings ›
Board › Language says otherwise.

## How it works

- `due_crew/words.py`: `t("phrase")`, `t("{n} days", n=3)`, `tn(one, many, n)`, `later("phrase")` for a
  phrase kept in a constant (say it with `t(label)` where it's drawn). English is the key.
- `due_crew/lang/<code>.json`: {English: theirs}. A phrase a file hasn't got is said in English.
- `python3 tools/words.py`: missing, unused, wrong, by language. The suite fails on any.
- A translation goes into the page where the English did: escape it where the English was escaped, and
  it brings no markup, `&` or `"` the English hasn't.
- A phrase is whole: never built from halves ("nothing " + "yet"), since word order differs. A count
  gets `tn`. A name or number goes in by {name}.
- Not translated: Due Crew, Pip, Pip Party, a person's own words (names, statuses, tips), deck names.

## Wrapping a surface

1. Wrap what a person reads in `_t(...)` (`from ..words import t as _t`); constants take `later`.
2. `python3 tools/words.py --keys` shows the new phrases; add all four to each `lang/*.json`.
3. `DC_LANG=de python3 tools/preview.py` and look: German is the longest, so it shows what won't fit.
4. The suite's English checks pass untouched; add one check that the surface says its phrases in
   another language.

## Order

Done: the ground, Settings' Language row, the whole crew tab (Today, Week, Decks, the show-up view, asks), the
board's foot, its banners (off-line, notice, exam eve, knocks, milestones, last week, month and year), the
Share menu's items, the signed-out, expired and loading cards. About 190 phrases.

Next, a surface at a time:
1. The rest of the board: the tab names (`base.YOU_MORE`, `HIDEABLE_TABS`), Squads and bingo, the You tabs, cheers, the fridge, the closet, the
   dance floor, bingo, the scrapbook.
2. Settings, sign-in and welcome, the Qt windows (`ui/`), the Tools menu, tooltips and sheets.
3. The review screen: the chip, tips, rooms, Fifteen.
4. Plans (the board's cards, the plan window, `planner/`), Insights, Magic search (its words to type
   stay English for now: a parser in four languages is its own job).
5. Pip Party (the tab, the TV and phones on the site).
6. The site: `site/public/words.js`, the same files, the browser's language with a pick in Account.
7. The Worker: the sign-in email in the language the request names; previews (`og.ts`).
8. Text shares and pictures (the week card), the README and AnkiWeb listing per language.

## Open

- A better wording goes through Feedback for now. If many come in, a form that names the phrase
  (pick it on the screen, type yours) would save SC reading free text.
- A crewmate's own words are never translated; a share I send is in my language, not the reader's.

## A round done by a helper

You wrap one set of files (yours alone; nobody else touches them) and hand back a branch.

1. In each file, wrap what a person reads: `from ..words import t as _t, tn as _tn, later as _later` (one dot
   for a module directly in `due_crew/`). Buttons, labels, headings, titles and aria-labels, tooltips, menu
   items, messages, placeholders. Not: commands (`duecrew:…`), CSS, ids, keys, log prints, comments, test
   data, AI prompts (`planner/prompts.py`, the request text in `planner/ai.py`), words a person types that
   the code parses (Magic search's), deck and tag names, a person's own words, `Due Crew`, `Pip`, `Pip Party`.
2. **The English a page draws must not change by a byte.** The key is the English exactly as the source has
   it, entities and all (`"Can&rsquo;t reach"` stays `&rsquo;`). Then no existing test changes. If a test
   must change anyway, change the least you can and say so in your report.
3. A phrase is whole. Turn an f-string into one phrase with {names}: `_t("{n} of {of} days", n=a, of=b)`. A
   link or bold name inside a sentence goes in by {name} (`who=f"<b>{name}</b>"`). A count takes
   `_tn("{n} tip", "{n} tips", n)`. Names are lowercase letters and underscores.
4. A module-level constant (a tuple of labels, a dict of messages) takes `_later("…")` so the tool finds it,
   and is said with `_t(label)` where it's drawn. Never call `_t` at import time: the language isn't set yet.
5. A string the code compares or uses as a key (`== "away"`, a dict lookup) must keep working: translate
   where it's shown, not where it's decided. An `lru_cache`d function that returns text must not cache
   across languages: add `words.lang()` to what it's keyed on, or say it at the caller.
6. Text inside a script (a `.js` file, or JS in a Python string): pass the phrases in from Python (a dict
   built with `_t`, sent with the page's data) and read them there; don't hard-code another language in JS.
7. Translations: do **not** edit `due_crew/lang/*.json`. Write `lang_parts/<your name>.json` at the repo
   root: `{"English key": ["es", "pt", "de", "fr"], …}`, every new key, all four. Reuse a phrase that
   `due_crew/lang/es.json` already has instead of inventing a near-copy.
8. Check: `python3 -m pyflakes due_crew tests tools` clean; `python3 tests/test_due_crew.py` and the other
   `tests/test_*.py` pass, except the one check "every language has every phrase the code asks for" (it
   fails until the parts are merged; expected). Every key `python3 tools/words.py --keys` lists that isn't
   in `due_crew/lang/es.json` must be in your parts file with the same {names} and no markup, `&` or `"`
   the English hasn't.
9. Commit on your branch (don't push). End the message with the two trailer lines you were given.
   Report: the branch name, how many phrases, anything you left in English and why, any test you changed.

Voice: terse, friendly, sentence case. es: tú. pt: você (Brazil). de: du. fr: vous.

| English | es | pt | de | fr |
|---|---|---|---|---|
| crew | equipo | turma | Crew | équipe |
| squad | grupo | grupo | Gruppe | groupe |
| deck | mazo | baralho | Stapel | paquet |
| card | tarjeta | cartão | Karte | carte |
| review(s) | repaso(s) | revisão(ões) | Wiederholung(en) | révision(s) |
| new cards | tarjetas nuevas | cartões novos | neue Karten | nouvelles cartes |
| due | pendiente | pendente | fällig | à réviser |
| streak | racha | sequência | Serie | série |
| retention | retención | retenção | Behaltensquote | rétention |
| tip | consejo | dica | Tipp | astuce |
| cheer (to) | ánimo (animar) | incentivo (incentivar) | Anfeuern (anfeuern) | encouragement (encourager) |
| plan | plan | plano | Plan | plan |
| a plan's set | bloque | bloco | Block | bloc |
| study room | sala de estudio | sala de estudo | Lernraum | salle d’étude |
| suspend / unsuspend | suspender / reactivar | suspender / reativar | aussetzen / reaktivieren | suspendre / réactiver |
| leech | sanguijuela | sanguessuga | Lernbremse | sangsue |
| Settings | Ajustes | Configurações | Einstellungen | Réglages |
| Board (the tab) | Tablero | Quadro | Board | Tableau |
| Insights | Análisis | Análises | Einblicke | Aperçus |
| Privacy | Privacidad | Privacidade | Datenschutz | Confidentialité |
| scrapbook | álbum | álbum | Album | album |
| closet | armario | armário | Kleiderschrank | placard |
| fridge | nevera | geladeira | Kühlschrank | frigo |
| bingo | bingo | bingo | Bingo | bingo |
| sign in | iniciar sesión | entrar | anmelden | se connecter |
| sync | sincronizar | sincronizar | synchronisieren | synchroniser |
