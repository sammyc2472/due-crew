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
