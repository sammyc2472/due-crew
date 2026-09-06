# Due Crew

Your friends' studying next to yours, on Anki's Decks screen.

Due Crew is a small, consent-based social layer for Anki. It's not a
competition: you see the people you chose, they see you, and everyone's
streak means what it says.

## What it does

- **Board on the Decks screen** — reviews, study time, retention, and streak
  for you and your crew. Today, Week, and shared-deck progress. Friends
  who go quiet stay on the board; that's when a cheer counts — and the
  day they're back, the board says so.
- **Consent-based friendships** — swap 6-character codes. You see someone's
  stats only after they add your code, and vice versa. Remove someone and
  they stop seeing yours immediately.
- **Cheers** — send 🎉 💪 🔥 and your friend gets a full-screen flurry with
  your name on it after their next sync. Click a flurry to cheer back.
- **Shared decks** — progress bars through decks you have in common
  (seen and mature counts). Decks match automatically by note fingerprint:
  AnKing and other imported decks pair up with no setup.
- **Friend profiles** — click a name for their half-year heatmap, streak,
  how many of the same days you've both studied, and your current run of
  days studied together. Click your own name to see your card exactly as
  your crew sees it.
- **Exam flags** — share an exam date and 📖 sits by your name for the two
  weeks before, so your crew knows when a 💪 matters most. On the eve, the
  board offers the 💪 itself.
- **Crew Wrap** — a weekly "together we did X" banner, plus streak
  milestones and all-time crew milestones ("250,000 reviews together").
  One click copies it for the group chat.
- **Privacy controls** — choose which stats you share (heatmap included),
  or pause sharing entirely ("on a break"). Pausing hides your stats; your
  streak keeps counting as long as you keep studying.
- **Everyone board** — opt in (Privacy) to a Today-only board of everyone
  on Due Crew who's also sharing, worldwide: the top 50 by reviews, the
  together number ("2,381 studying today · 1.2M reviews"), and your own
  place in it. No medals, no cheers — these aren't necessarily people you
  know; weeks, days, decks, and heatmaps stay crew-only. Tap a name, knock,
  and you're crew when they add back.
- **Share it** — paste-ready for the group chat: the crew's day as a
  tape (everyone's study hours side by side, only those who showed up),
  or your own day as a sparkline or tape, signed with the add-on code.
  Copy from the Today view's footer or your own profile card. Counts are
  reviews (every answer counts); a day runs from your Anki rollover hour;
  friends' hours sit on your clock, as of their last sync; anyone who
  studied but doesn't share hours is counted as "not sharing hours", and a
  total missing someone's hidden count says "(partial)".
- **Light on everything** — the whole board loads in 3 HTTP requests, all
  network runs off the main thread with timeouts, and it refreshes only
  when Anki syncs or you click Refresh.

## Install

In Anki: Tools → Add-ons → Get Add-ons → code **2035408484**
([AnkiWeb listing](https://ankiweb.net/shared/info/2035408484)) — or
download `due_crew.ankiaddon` from
[the releases page](https://github.com/sammyc2472/due-crew/releases)
and install it with Tools → Add-ons → Install from file. Anki 2.1.55+;
restart Anki after installing.

## Getting started

1. Click Due Crew on the Decks screen and sign up (an email and a
   display name).
2. Friends → Copy invite (or just your code), send it to a friend. They
   add yours, you add theirs — you're crew.
3. Study. Stats sync when Anki syncs.
4. Optional: Settings → Privacy → **Share on the Everyone board** to see
   everyone on Due Crew studying today, and be seen.

## Privacy

Due Crew runs on one hosted backend (the maintainer pays for it). Stats
live there, readable only by people you've added — and, only if you opt
into the Everyone board, a single name-and-today's-numbers row readable by
others who've opted in too, anywhere in the world. All of it is enforced
server-side by the
[Firestore rules](https://github.com/sammyc2472/due-crew/blob/main/firestore.rules)
in this repo. Your email is used for sign-in only and is never shown to
friends or stored in the database. Deleting your account removes your data.

## Development

Open source, MIT: https://github.com/sammyc2472/due-crew — issues and pull
requests welcome. The add-on is plain Python + Anki hooks, no build step.
Tests: `python3 tests/test_due_crew.py` (no dependencies) and the emulator
rules test in `tests/rules/` — see `tests/README.md`; the manual Anki
checklist is in `docs/`. The Firestore rules in `firestore.rules` are the
ones deployed to the hosted backend. Package with:

    cd due_crew && zip -r ../due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*"

## License

MIT — Copyright (c) 2026 Sammy Caplan and Claude.
