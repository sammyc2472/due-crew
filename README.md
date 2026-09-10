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
  your name on it after their next sync. Add a short note and it rides
  along. Click a flurry to cheer back.
- **Status** — click your own name and set one line ("coffee, then 400
  cards"). It sits in a bubble under your name on Today, for your crew and
  no one else.
- **Shared decks** — progress bars through decks you have in common
  (seen and mature counts). Decks match automatically by note fingerprint:
  AnKing and other imported decks pair up with no setup.
- **Friend profiles** — click a name for their half-year heatmap, streak,
  how many of the same days you've both studied, and your current run of
  days studied together. Click your own name to see your card exactly as
  your crew sees it.
- **Exam and away flags** — share an exam date and 📖 sits by your name
  for the two weeks before, so your crew knows when a 💪 matters most. On
  the eve, the board offers the 💪 itself. Share away dates and ✈️ sits by
  your name for those days, with ✈️ squares in week shares, so a gap reads
  as a trip, not a slip.
- **Crew Wrap** — a weekly "together we did X" banner, plus streak
  milestones and all-time crew milestones ("250,000 reviews together").
  One click copies it for the group chat.
- **Privacy controls** — choose which stats you share (heatmap included),
  or pause sharing entirely ("on a break"). Pausing hides your stats; your
  streak keeps counting as long as you keep studying.
- **Squads** — a private board for any group: a class, a Discord, a
  study group. Join with an invite code, or create one and share yours.
  Squadmates see your name and today's reviews, time, retention, and
  streak, nothing more. Plain ranks, everyone in the squad, Today only.
  The founder can lock the door and remove people; anyone can leave. Tap a
  name to add someone; you're crew when they add back, and the board tells
  you when someone adds you.
- **Share it** — paste-ready for the group chat: your week as seven
  squares (🟩🟩🟩⬜🟩🟩🟩 6 of 7 days), the crew's week as a row per
  person, or today's numbers in one line — each signed with the add-on
  code. Copy from the Today and Week footers or your own profile card.
  Counts are reviews (every answer counts), and a crewmate who hasn't
  synced since mid-week is marked "as of" their last sync rather than
  shown as absent.
- **Your colors** — six accent colors (Settings → Appearance), each tuned
  for light and dark mode; the whole board, your row highlight, and the
  cards follow it.
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
4. Optional: Squads → **+ join or create**. Share the invite code with
   your class or group chat.

## Privacy

Due Crew runs on one hosted backend (the maintainer pays for it). Stats
live there, readable only by people you've added — and, in any squad you
join, a single name-and-today's-numbers row readable by that squad's
members. Squads have no directory: only people holding the invite code can
find one, and the founder can lock it. All of it is enforced server-side
by the
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
