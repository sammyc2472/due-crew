<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo/svg/due-crew-logo-dark.svg">
  <img alt="Due Crew" src="docs/logo/svg/due-crew-logo.svg" width="220">
</picture>

Your friends' studying next to yours, on Anki's Decks screen.

<img alt="The Due Crew board on the Decks screen" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/board.png" width="600">

Studying for a big exam is more fun with friends! Due Crew puts your friends on
Anki's Decks screen: who's studied today, who's studying now, how far
each of you has gotten. You only see people you've added, and they see
you once they add you back. Your cards never leave your computer.

## Showing up for each other

**Cheers.** Tap 🎉 next to a friend's name and it rains down their
screen, with your note.

<img alt="A cheer arriving" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/flurry.png" width="600">

**Study rooms.** 25-minute rounds with your crew, the timer in Anki's top
bar, breaks together.

<img alt="A study room in Anki's top bar" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/room.png" width="420">

- **Stuck on a card?** Ask your crew. Anyone who has it down can send a
  tip, which shows next time the card comes up.
- **Good-luck cards.** Leave a line the night before a friend's exam.
- **Profiles.** Half a year of a friend's studying, and your days in a
  row together.
- **Shared decks.** Decks you have in common, like AnKing, match up.
- **Status, exam and away dates, just-show-up mode,** six accent colours,
  and your board and log on duecrew.com.

## Squad bingo

Every Monday your squad gets a new 3×3 card of studying squares: an early
start, twenty minutes without a break, a day with nothing left due, new
cards three days in a row. Most need more than one of you, and the middle
unlocks when enough of you do something together. Three in a row is
bingo. Copy the card to your group chat.

<img alt="A squad's bingo card with a line" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/bingo.png?v=2" width="600">

## Study plans

Plan a class's or a crew's studying on a calendar at duecrew.com: pick
chapters from a deck (Tools → Due Crew → Make a plan from a deck), set a
pace, mark the exam, and share the code. Everyone following gets that
day's cards each morning. Behind? **Catch up** or **Move my days back**.
Plans can have co-authors and notes, go in your calendar app, and be
shared in the library.

<img alt="The Plans tab: today's work and the week" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/plans.png?v=2" width="600">

## Install

Tools → Add-ons → Get Add-ons, code **2035408484**. Needs Anki 2.1.55 or
newer. Restart Anki after installing.

## Get started

1. Click **Start with your email** on the Decks screen and type in the
   code we send you. No password.
2. Paste an invite, or a class, squad or plan code, on the welcome
   screen. Or copy your invite and send it to a friend.
3. Someone added you? Click **Add back**.

## Privacy

Your stats go only to people you've added and squads you join. Choose
what you share in Settings → Privacy, or pause at any time. Anyone else
sees your name and emoji, nothing more. Card text never leaves your
computer: a crewmate sees a card's text only if they have the same card.
Your email is used to sign you in, and so Sam, who runs Due Crew, can find
your account if you write in. Feedback you send goes to Sam with your
name. Deleting your account deletes your data.
The add-on and server are on
[GitHub](https://github.com/sammyc2472/due-crew).

## Development

Plain Python and Anki hooks, no build step; the server is a Cloudflare
Worker in `worker/`. Tests: `python3 tests/test_due_crew.py`, and
`npx vitest run` in `worker/`. See `tests/README.md`.

## License

The add-on is MIT. The server and site (`worker/`, `site/`) are
[PolyForm Shield 1.0.0](https://polyformproject.org/licenses/shield/1.0.0).
Copyright (c) 2026 Sammy Caplan.
