<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo/svg/due-crew-logo-dark.svg">
  <img alt="Due Crew" src="docs/logo/svg/due-crew-logo.svg" width="220">
</picture>

Your friends' studying next to yours, on Anki's Decks screen.

<img alt="The Due Crew board on the Decks screen" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/board.png" width="600">

Studying for a big exam can get lonely. Due Crew puts your friends right
there on Anki's Decks screen: who's studied today, who's studying now, and
how far each of you has gotten. Cheer each other on, study side by side in
a room, follow the same plan to exam day, and play squad bingo every week.

It's made for friends helping friends. You only see people you've added,
and they only see you once they've added you back. Your cards never leave
your computer.

## Squad bingo

Every Monday your squad gets a fresh 3×3 card, the same one for every
squad. The eight squares are about studying: an early start, twenty
minutes without a break, a day that ends with nothing due, new cards
three days in a row. Most take more than one of you, and a bigger squad
needs more hands. The middle square unlocks when enough of you do
something together, like joining a study room or sharing a deck.

Pass a square and your stamp lands on it at your next sync, so the card
fills in with your squad's faces. Get three in a row and it's bingo. Copy
the card to your group chat as a grid of squares, without who did what.

<img alt="A squad's bingo card with a line" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/bingo.png" width="600">

## Study plans

Plan a class's or a crew's studying on a calendar at duecrew.com. Start
from a deck in Anki (Tools → Due Crew → Make a plan from a deck), pick the
chapters (tags, subdecks, a search, or just the deck in order), set a
pace, and mark the quizzes and the exam. Share the link or the code.

Everyone following gets that day's cards opened each morning. The Plans
tab shows today's work, the week ahead and how the crew is doing. Fall
behind and **Catch up** works the missed cards in alongside today's, or
**Move my days back** shifts your own dates without touching anyone
else's.

<img alt="The Plans tab: today's work and the week" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/plans.png" width="600">

Write a plan with co-authors, leave notes on a day, add it to your
calendar app, or print it. Good plans can go in the library at
duecrew.com/library, where anyone can follow or copy one.

## Ways to show up for each other

**Cheers.** Tap 🎉 next to a friend's name and it rains down their screen
after their next sync, with your name and any note you added. They can
send one right back.

<img alt="A cheer arriving" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/flurry.png" width="600">

**Study rooms.** Open a room and your crew can join you for 25-minute
rounds with short breaks in between. While you review, the timer and
who's in the room sit in Anki's top bar, out of the way of your cards.
When a round ends you finish the card you're on, and then everyone takes
the break together.

<img alt="A study room in Anki's top bar" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/room.png" width="420">

**Stuck on a card?** Ask your crew from the reviewer's menu. Anyone who
has that card down sees your ask and can send a tip, which shows beside
Edit the next time the card comes up. Only crewmates with the same card
see it.

**Good-luck cards.** The night before a friend's exam, leave them a line.
On exam morning they open Anki to every note their crew wrote.

<img alt="A good-luck card on exam morning" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/luck.png" width="420">

**Friend profiles.** Click a name for half a year of their studying, and
how many days in a row the two of you have both shown up.

<img alt="A friend's profile with a heatmap" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/profile.png" width="420">

**Group chat material.** Copy your crew's week as a grid of squares and
paste it into your group chat.

<img alt="The crew's week pasted into a group chat" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/share.png" width="420">

**And also**

- **Squads.** A private board for your class or your Discord, behind an
  invite code. Squads play bingo together.
- **Shared decks.** Decks you have in common, like AnKing, match up
  automatically, so you can see how far each of you has gotten.
- **Status.** One line under your name. Start it with a number, like
  "200 cards, then bed", and it ticks itself off as you go.
- **Exam and away dates.** Add an exam date and your crew sees it
  coming. Add away dates and a few missed days read as a trip.
- **Just show up.** If you'd rather not share numbers, share only
  whether you studied.
- **On the web too.** duecrew.com has your board, your year of studying,
  and your log, which you can download.
- **Six accent colours.** The logo changes with them.

## Install

Tools → Add-ons → Get Add-ons, code **2035408484**. Needs Anki 2.1.55 or
newer. Restart Anki after installing.

## Get started

1. Click **Start with your email** on the Decks screen. Type in the code
   we send you. There's no password.
2. Got an invite, or a code from a class, a squad or a plan? Paste it on
   the welcome screen. Otherwise, copy your invite and send it to a
   friend. When they paste it, you're crew. One invite per friend.
3. Someone added you? Click **Add back**.

## Privacy

Your stats go only to people you've added, and to squads you join, where
squadmates see your name and today's numbers. Choose what you share in
Settings → Privacy, or pause sharing at any time. Those choices are saved
to your account, where only you can read them, so they follow you to other
computers. Anyone else sees your name and emoji, nothing more.

Card text never leaves your computer. A card you ask about goes up as an
ID, and a crewmate sees its text only if they have the same card in their
own Anki. Bingo sends which squares you've passed and a few yes-or-no
facts about your days, like whether you studied before 8; your Privacy
switches keep the rest at home.

You sign in with a code sent to your email; there's no password. Your email
is only used for that, and so Sam, who runs Due Crew, can find your account
if you write in. Deleting your account deletes your data.

The add-on and the server that enforces all of this are on
[GitHub](https://github.com/sammyc2472/due-crew) for anyone to read.

## Development

The add-on is plain Python and Anki hooks, no build step; the server is a
Cloudflare Worker in `worker/`. Run the tests with
`python3 tests/test_due_crew.py` and, in `worker/`, `npx vitest run`;
`tests/README.md` has the rest. Issues and pull requests are welcome.

## License

The add-on is MIT. The server and the site (`worker/`, `site/`) are
[PolyForm Shield 1.0.0](https://polyformproject.org/licenses/shield/1.0.0):
read them, run them, change them, just not to offer a competing service.
Copyright (c) 2026 Sammy Caplan.
