<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo/svg/due-crew-logo-dark.svg">
  <img alt="Due Crew" src="docs/logo/svg/due-crew-logo.svg" width="220">
</picture>

Your friends' studying next to yours, on Anki's Decks screen.

<img alt="The Due Crew board on the Decks screen, your day folded above it" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/board.png?v=12" width="600">

Studying for a big exam is more fun with friends! Due Crew puts yours
right under your decks. Nobody's alone at 11pm with 400 cards left.

Friends only. Your cards never leave your computer.

## Get it

In Anki: Tools → Add-ons → Get Add-ons, code **2035408484**. Restart,
sign in with your email, send a friend your invite. Two minutes, no
password.

## Magic search

Type "30 minutes of renal". Get 30 minutes of renal.

<img alt="Magic search: heart failure, 27 cards, Study now" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/magic.png?v=2" width="600">

## Study plans

One person makes the calendar. Everyone wakes up to that day's cards.
Fall behind and it waits for you.

<img alt="You › Plans: a plan's week, today's assignments open" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/plans.png?v=10" width="600">

## Insights

What you know, what you don't, and how bad next week is going to be.

<img alt="You › Insights: what you know by topic, and your reviews for the weeks ahead" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/insights.png?v=2" width="600">

## Cheers

Your friend hit 700 reviews. Throw confetti at their screen.

<img alt="A cheer landing" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/flurry.png" width="600">

## Study rooms

25 minutes on, five off, together. The timer lives in Anki's top bar.

<img alt="A study room in Anki's top bar" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/room.png?v=2" width="420">

## Study soundtrack

Put on the song you're studying to. Your crew dances to theirs.

<img alt="The dance floor: your Pip at the booth, your crew's Pips with their songs" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/dance.png?v=1" width="420">

## Squad bingo

A new card for your class every Monday. Most squares take a few of
you, so somebody has to text the group chat.

<img alt="A squad's bingo card with a line" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/bingo.png?v=3" width="600">

## Pip

The little square from the logo. Study, and it earns hats.

<img alt="Pip's closet: hats, glasses and costumes earned by showing up" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/closet.png?v=1" width="600">

## Pip Party

Trivia night, but the questions are your own cards. Phones in hand,
Anki on the TV. (Beta.)

<img alt="You › Party: three games, and a map of your deck to pick the night's topics from" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/party.png?v=2" width="600">

## And more

- **Hooks.** Write down what made a card click. It shows up the next
  time you miss it, and for a friend who misses it too.
- **Good-luck cards** the night before a friend's exam.
- **Today.** What's due, your plan and your to-dos in one list.
- **Fifteen?** One button, fifteen minutes. Good for starting.
- **Why isn't this card showing?** Right-click it in Browse and find
  out.
- **Scrapbook.** Everything your friends sent you, kept by month.
- **Pick your colour.** Six of them, and every picture here is a
  different one.

## Privacy

- Your stats go only to people you've added and squads you join.
  Anyone else sees your name and emoji, nothing more.
- You choose what to share in Settings → Privacy, and you can pause
  any time.
- Card text never leaves your computer. A friend sees a card's text
  only if they have the same card. A plan stores card IDs, and each
  follower's Anki looks them up in its own deck.
- Insights, your topic map, your year and your bingo progress stay on
  your computer.
- Your email is only used to sign you in.
- Your to-dos are saved with your settings so all your computers have
  them. Only you see them.
- If you write in for help, SC, who runs Due Crew, can look up your
  account, your squads and who's on your crew list. Never how you
  study. Each look is logged.
- Feedback you send goes to SC with your name.
- Deleting your account deletes your data. Accounts with no activity
  for 12 months (24 when paused) are deleted too. Opening Anki with
  Due Crew on, or signing in at duecrew.com, counts as activity.

The add-on and server are on
[GitHub](https://github.com/sammyc2472/due-crew).

## Development

Plain Python and Anki hooks, no build step. The server is a Cloudflare
Worker in `worker/`, duecrew.com is `site/`. Tests:
`python3 tests/test_due_crew.py`, and `npx vitest run` in `worker/`. See
`tests/README.md`.

## License

The add-on is MIT. The server and site (`worker/`, `site/`) are
[PolyForm Shield 1.0.0](https://polyformproject.org/licenses/shield/1.0.0).
Copyright (c) 2026 SC.

**Name, logo and Pip.** The licences above cover Due Crew's code, not its
name or look. "Due Crew", the Seven days logo, and Pip (its name and how it
looks) are trademarks of SC and aren't part of either licence;
from 17 October 2026 the logo's and Pip's artwork is all rights reserved
too (LICENSE lists the files). You're welcome to build on the code, but
give your version its own name, logo and characters so no one mistakes it
for Due Crew. You can always say what it's based on ("based on Due Crew").
