<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo/svg/due-crew-logo-dark.svg">
  <img alt="Due Crew" src="docs/logo/svg/due-crew-logo.svg" width="220">
</picture>

Your friends' studying next to yours, on Anki's Decks screen.

Due Crew is a small, consent-based social layer for Anki. It's not a
competition: you see the people you chose, they see you, and everyone's
streak means what it says.

## What it does

- **Board on the Decks screen** — reviews, study time, retention, and streak
  for you and your crew. Today, Week, and shared-deck progress. Friends
  who go quiet stay on the board; that's when a cheer counts — and the
  day they're back, the board says so.
- **Consent-based friendships** — add a friend's 6-character code (or
  paste their whole invite) and their board offers "Add back": one click and
  you're crew. You see someone's stats only after they add you, and vice
  versa. Remove someone and they stop seeing yours immediately.
- **Cheers** — send an emoji (six quick picks, or any one from your emoji
  picker) and your friend gets a full-screen flurry with your name on it
  after their next sync. Add a short note and it rides along. Click a
  flurry to cheer back.
- **Status** — click your own name and set one line ("coffee, then 400
  cards"). It sits in a bubble under your name on Today, for your crew and
  no one else. Start it with a number ("200 cards, then bed") and it's a
  plan: it fills in as you study and ticks itself off.
- **Studying now** — tap "I'm studying" in the footer and a dot sits by
  your name for an hour, so friends can come study too.
- **Stuck on a card?** — in the reviewer's More menu, "this one's getting
  me" flags it for a week. Crewmates who have the same card see it on the
  Decks tab and can send a one-line tip, which shows under the answer the
  next time it comes up. A cloze never shows its answer in the flag.
- **Good-luck card** — on the eve of a friend's exam, add a line to their
  card. On exam morning they open Anki to every line their crew wrote.
- **Shared decks** — progress bars through decks you have in common:
  how much of the deck each person has unlocked, seen, and matured, what
  they've done in it today and this week, and how well it's sticking. Hover
  a bar for the exact numbers. Decks match automatically by note
  fingerprint: AnKing and other imported decks pair up with no setup.
- **Just show up** — a choice in Privacy: share only that you studied, and
  see only that of others. Your row is a check, never a rank; your board is
  a square per day.
- **A bit of the season** — flurries carry the season's emoji, and a
  crewmate's 100-day streak gets a banner with a one-tap 💯.
- **Crew emoji** — pick one emoji from your own card and it sits in front
  of your name on the board, on cards, and in shares.
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
  Squadmates see your name and today's numbers, whichever your Privacy
  switches share, plus how many of the last seven days you studied. Plain ranks,
  everyone in the squad, Today only. The founder can lock the door, remove
  or block people, and hand the squad on; anyone can leave. Tap a name to
  add someone; you're crew when they add back, and the board tells you when
  someone adds you. Share copies the day's headline for the group chat.
- **Share it** — paste-ready for the group chat: your week so far as
  squares (🟩🟩🟩⬜🟩 4 of 5 days, Monday to today), the crew's week as a row per
  person, today's numbers in one line, or your month and your year (exact,
  from your own review history) — each signed with the add-on code. Copy
  from the Today and Week footers or your own profile card. In the first
  week of a month the board offers last month's review; from December 20
  it offers the year's.
  Counts are reviews (every answer counts), and a crewmate who hasn't
  synced since mid-week is marked "as of" their last sync rather than
  shown as absent.
- **Your colors** — six accent colors (Settings → Board), each tuned
  for light and dark mode; the whole board, your row highlight, and the
  cards follow it.
- **Light on everything** — a refresh reads one small document per
  friend, all network runs off the main thread with timeouts, and it syncs
  when Anki opens or syncs, when you come back to a board more than 15
  minutes old, or when you click Refresh. If a sync fails, the board says
  so.

## Install

In Anki: Tools → Add-ons → Get Add-ons → code **2035408484**
([AnkiWeb listing](https://ankiweb.net/shared/info/2035408484)) — or
download `due_crew.ankiaddon` from
[the releases page](https://github.com/sammyc2472/due-crew/releases)
and install it with Tools → Add-ons → Install from file. Anki 2.1.55+;
restart Anki after installing.

## Getting started

1. Click **Join** on the Decks screen and sign up (an email and a
   display name). One screen follows: copy your invite, add a code you
   were sent, or join a squad, and see what your crew will see first.
2. Send your invite. When your friend adds your code, **Add back** shows
   up on your board: click it and you're crew.
3. Study. Stats sync when Anki opens and syncs.
4. Optional: Squads → **+ join or create**. Share the invite with your
   class or group chat.

## Privacy

Due Crew runs on one hosted backend (the maintainer pays for it). Stats
live there, readable only by people you've added — and, in any squad you
join, a single name-and-today's-numbers row readable by that squad's
members, with the same Privacy switches applied. Your profile can be
read by anyone who has your account id, which squadmates have: your name
and emoji, and until a coming release finishes moving them, your exam
date, time zone, and friend list. Squads have no directory: only people holding the invite code can
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
