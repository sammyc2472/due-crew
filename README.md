<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/logo/svg/due-crew-logo-dark.svg">
  <img alt="Due Crew" src="docs/logo/svg/due-crew-logo.svg" width="220">
</picture>

Your friends' studying next to yours, on Anki's Decks screen.

<img alt="The Due Crew board on the Decks screen" src="https://raw.githubusercontent.com/sammyc2472/due-crew/main/docs/images/board.png" width="600">

Studying for a big exam can get lonely. Due Crew puts your friends'
studying next to yours on Anki's Decks screen, so you can keep each other
going.

It's meant for friends helping friends. You only see people you've added,
and they only see you once they've added you back.

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

- **Status.** One line under your name. Start it with a number, like
  "200 cards, then bed", and it ticks itself off as you go.
- **Stuck on a card?** Flag it from the reviewer's More menu. A friend
  with the same card can send you a tip, which shows under the answer
  next time.
- **Shared decks.** Decks you have in common, like AnKing, match up
  automatically, so you can see how far each of you has gotten.
- **Squads.** A private board for your class or your Discord, behind an
  invite code.
- **Just show up.** If you'd rather not share numbers, share only
  whether you studied.
- **Exam and away dates.** Add an exam date and your crew sees it
  coming. Add away dates and a few missed days read as a trip.
- **Six accent colours.** The logo changes with them.

## Install

Tools → Add-ons → Get Add-ons, code **2035408484**. Needs Anki 2.1.55 or
newer. Restart Anki after installing.

## Get started

1. Click **Join** on the Decks screen and sign up.
2. Copy your invite and send it to a friend.
3. When they add you, click **Add back**. You're crew.

## Privacy

Your stats go only to people you've added, and to squads you join, where
squadmates see your name and today's numbers. Choose what you share in
Settings → Privacy, or pause sharing at any time. Those choices are saved
to your account, where only you can read them, so they follow you to other
computers. Your email is only used to sign in. Deleting your account
deletes your data.

Until an upcoming update, your profile (name, emoji, exam date, time zone
and friend list) can be read by anyone with your account id, which your
squadmates have.

The server rules that enforce this are in
[firestore.rules](https://github.com/sammyc2472/due-crew/blob/main/firestore.rules).

## Development

Plain Python and Anki hooks, no build step. Run the tests with
`python3 tests/test_due_crew.py`; `tests/README.md` has the rest. Issues
and pull requests are welcome.

## License

MIT. Copyright (c) 2026 Sammy Caplan and Claude.
