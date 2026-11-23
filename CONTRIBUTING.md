# Contributing to Due Crew

Thanks for wanting to help! I'm Sam, and I maintain Due Crew on my own, so small,
focused changes are the easiest for me to say yes to.

## What you can work on

- **The add-on** (`due_crew/`), its **tests** (`tests/`) and **tools** (`tools/`). Pull requests welcome.
- **Translations** (`due_crew/lang/`). Very welcome, see below.
- **The server and the site** (`worker/`, `site/`). Also welcome, but please talk to me
  first: changes here touch everyone's data.
- **Pip and the logo** are the one thing that's off the table. Please don't redraw or restyle them.

## Before you build

If your change alters anything a person sees or reads (a screen, a button, some wording),
tell me about it first. Open a GitHub issue or email me at sam@duecrew.com. Two lines
is plenty. I'd rather agree on it up front than have you build something I can't take.

Bug fixes that don't change what people see can go straight to a pull request.

## Translations

Each language is one file: `due_crew/lang/<code>.json`, English on the left, yours on
the right. `docs/languages.md` explains how it works and has a glossary.

- Spanish, Portuguese, German and French are in the add-on already, but they're machine
  drafts. A native speaker reading through one is the most useful thing you can do.
- For a new language, copy one of those files, translate the right-hand side, and say
  so in your pull request.
- Leave anything in `{braces}` exactly as it is. `python3 tools/words.py` checks that for you.

## Checking your work

    python3 -m pyflakes due_crew tests tools
    python3 tests/test_due_crew.py

You only need Python 3 and `pip install pyflakes`. The same checks, and a few more, run
automatically on every pull request. They need to pass before I can merge.

## House rules

These are the things I care about most. They're what makes Due Crew what it is.

- **Card text never leaves the computer.** Nothing a person wrote on a card gets sent anywhere.
- **Friends, not rivals.** No rank, rival, compete or leaderboard, in code or in words people read.
- **Anything a click adds has a way back on the same screen.**
- **Words people read go through `t("...")`.** Sentence case, and keep it short. English
  only is fine in your pull request; I'll fill in the other languages.
- **Standard library only in the add-on.** No new dependencies: it has to run inside Anki's Python.
- **Never import the add-on by its folder name.** AnkiWeb installs it as `2035408484`,
  so use relative imports (`from . import x`).
- **A refresh is one request and a sync is one.** No polling, and no request per friend.
- **Network calls run in background threads with timeouts.** Anything that touches the
  collection stays on the main thread.
- **Escape anything that came from the server** before it reaches a page or a label.
- **Never log emails, sign-in codes or tokens.**
- **No other product's name** (a deck, a question bank, a game) in code, comments or test data.
- **One change per pull request,** with a test where the test suite can reach it.

## Your work, and the licence

What you write stays yours, and I'll credit you in [CONTRIBUTORS.md](CONTRIBUTORS.md).

- **Add-on, tests, tools, translations:** your contribution is shared under the MIT
  licence, same as the code around it.
- **Server and site:** your contribution is shared under PolyForm Shield, same as the
  code around it. You also let the project relicense it later, so the licence can change
  someday without my having to track down everyone who ever sent a fix.

Ticking the box on your pull request says you're happy with this.

Thank you. It means a lot that you'd spend your time on this.

Sam
