# Due Crew

Your friends' studying next to yours, on Anki's Decks screen.

Due Crew is a small, consent-based social layer for Anki. It's not a
competition: you see the people you chose, they see you, and everyone's
streak means what it says.

## What it does

- **Board on the Decks screen** — reviews, study time, retention, and streak
  for you and your crew. Today, Week, shared-deck progress — or Days, a
  numbers-free view of who showed up. Friends who go quiet stay on the
  board; that's when a cheer counts — and the day they're back, the board
  says so.
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
- **Crew servers** — run your whole group on your own free Firebase
  project. One person does the setup; everyone else joins with a name and
  a code — a name the founder can pick ("busm").
- **Server board** — opt in (Privacy) to a Today-only board of everyone on
  your server who's also sharing. No medals, no cheers — these aren't
  necessarily people you know; weeks, days, decks, and heatmaps stay
  crew-only. Tap a name, knock, and you're crew when they add back.
- **Light on everything** — the whole board loads in 3 HTTP requests, all
  network runs off the main thread with timeouts, and it refreshes only
  when Anki syncs or you click Refresh.

## Install

In Anki: Tools → Add-ons → Get Add-ons → code **2035408484**
([AnkiWeb listing](https://ankiweb.net/shared/info/2035408484)) — or
download `due_crew.ankiaddon` from
[the releases page](https://github.com/sammyc2472/due-crew/releases)
and double-click it. Anki 2.1.55+.

## Getting started

1. Click Due Crew on the Decks screen: join your crew with the server name
   and code a friend sent you — or start a new crew.
2. Friends → Copy invite (or just your code), send it to a friend. They
   add yours, you add theirs — you're crew.
3. Study. Stats sync when Anki syncs.

## Privacy

Stats live in Firebase, readable only by people you've added — and, only
if you opt into the server board, a single name-and-today's-numbers row
readable by others who've opted in too. All of it is enforced
server-side by the
[Firestore rules](https://github.com/sammyc2472/due-crew/blob/main/firestore.rules)
in this repo. Your email is used for sign-in only and is never shown to
friends or stored in the database. Deleting your account removes your data.

## Run your own crew server

One person per crew does this once; everyone else just types a name and a
code. About ten minutes:

1. [console.firebase.google.com](https://console.firebase.google.com) →
   Add project (any name, Analytics off).
2. Build → Authentication → Get started → enable **Email/Password**.
3. Build → Firestore Database → Create database (production mode) → Rules →
   paste
   [firestore.rules](https://github.com/sammyc2472/due-crew/blob/main/firestore.rules)
   → Publish.
4. Project settings → Your apps → add a **Web app** → copy the `apiKey` and
   `projectId` from the config it shows.
5. In Anki: Due Crew → **Start a new crew** → Continue → paste both →
   Register — typing your own crew name is optional (3–40 characters,
   lower-case letters, digits, dashes; first come, first named). You get
   the name (say it aloud) and a code (share privately) — then click
   **Use this server now** and sign up on it.

Friends then pick **Join your crew**, enter the name and code, and sign up
as usual. Your crew runs on your own free Firebase quota.

If a later Due Crew version needs updated rules, the board shows "Server
rules need an update" with a one-click copy of the new rules — re-do step 3
and you're current.

## Development

Open source, MIT: https://github.com/sammyc2472/due-crew — issues and pull
requests welcome. The add-on is plain Python + Anki hooks, no build step.
Package with:

    cd due_crew && zip -r ../due_crew.ankiaddon . -x "*.DS_Store" -x "user_files/*"

## License

MIT — Copyright (c) 2026 Sammy Caplan and Claude.
