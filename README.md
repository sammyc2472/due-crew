# Due Crew

Your friends' studying next to yours, on Anki's Decks screen.

Due Crew is a small, consent-based social layer for Anki. It's not a
competition: you see the people you chose, they see you, and everyone's
streak means what it says.

<!-- screenshot: board with Today view -->

## What it does

- **Board on the Decks screen** — reviews, study time, retention, and streak
  for you and your crew. Today, This week, or shared-deck progress.
- **Consent-based friendships** — swap 6-character codes. You see someone's
  stats only after they add your code, and vice versa. Remove someone and
  they stop seeing yours immediately.
- **Cheers** — send 🎉 💪 🔥 to a friend; they get a full-screen flurry with
  your name after their next sync.
- **Shared decks** — progress bars through decks you have in common
  (seen and mature counts). Decks match automatically by note fingerprint:
  AnKing and other imported decks pair up with no setup.
- **Privacy controls** — choose which stats you share, or pause sharing
  entirely ("on a break"). Pausing hides your stats; your streak keeps
  counting as long as you keep studying.
- **Friend profiles** — click a name for their half-year heatmap, streak,
  and how many of the same days you've both studied. Shared only if they
  keep "My heatmap" on.
- **Crew Wrap and cheers-back** — a weekly together-total banner, streak
  milestone toasts, and a cheer flurry you can answer with one click.
- **Crew servers** — run your whole crew on your own free Firebase project.
  One person does the setup; everyone else joins with a name and a code.
- **Light on everything** — the whole board loads in 3 HTTP requests, all
  network runs off the main thread with timeouts, and it refreshes only when
  Anki syncs or you click Refresh.

## Install

From AnkiWeb (code: TBD), or download `due_crew.ankiaddon` from releases and
double-click it. Anki 2.1.55+.

## Getting started

1. Tools → Due Crew → Sign in (or click "Join your crew" on the Decks screen).
2. Friends → copy your code, send it to a friend. They add yours, you add
   theirs — you're crew.
3. Study. Stats sync when Anki syncs.

## Privacy

Stats live in Firebase, readable only by people you've added (enforced
server-side by the [Firestore rules](firestore.rules) in this repo). Your
email is used for sign-in only and is never shown to friends or stored in
the database. Deleting your account removes your data.

## Run your own crew server

One person per crew does this once; everyone else just types a name and a
code. About ten minutes:

1. [console.firebase.google.com](https://console.firebase.google.com) →
   Add project (any name, Analytics off).
2. Build → Authentication → Get started → enable **Email/Password**.
3. Build → Firestore Database → Create database (production mode) → Rules →
   paste [firestore.rules](firestore.rules) → Publish.
4. Project settings → Your apps → add a **Web app** → copy the `apiKey` and
   `projectId` from the config it shows.
5. In Anki: Tools → Due Crew → Settings → **Register your own…** → paste
   both → Register. You get a server name (say it aloud) and a code (share
   privately).

Friends then use **Join a different crew server…** on the sign-in screen,
pick the name, enter the code, and sign up as usual. Your crew now runs on
your own free Firebase quota, fully independent of the default server.

## Development

The add-on is plain Python + Anki hooks, no build step. Package with:

    cd due_crew && zip -r ../due_crew.ankiaddon . -x "*.DS_Store"

## License

MIT — Copyright (c) 2026 Sammy Caplan and Claude. See [LICENSE](LICENSE).
