# Manual Anki checklist (v2.0)

Automated tests cover client logic against a fake backend; the rules test
needs the emulator. None of them run inside Anki. Before a release, do this
in a real Anki with the add-on installed (quit and reopen Anki after
installing — add-ons load at launch).

## Appearance (Decks screen)
- [ ] Light mode: one white rounded card around the board; no outer border, no shadow.
- [ ] Night mode: the same card in neutral near-black on Anki's gray canvas — no green tint, no lighter rectangle behind the table.
- [ ] Inside the card: no header underline, no row lines, no rounded cells; only the soft green highlight on your own row.
- [ ] Narrow the window (~480 px): the table never scrolls sideways; a long display name ellipsizes instead of overlapping the numbers. Other add-ons' content on the page is unaffected (we no longer touch `body`).
- [ ] Switch Today / Week / Decks / Server; pills stay one row or wrap cleanly.

## Squads
- [ ] Squads pill → "+ join or create" → Create "busm": the code appears, the invite lands on the clipboard, your row shows after the next sync.
- [ ] A second account joins with the code: the preview shows the name, founder, and "open"; after Join both boards list both people with reviews, time, retention, and streak; plain ranks, no medals.
- [ ] Founder → Lock: a third account's Join reads "Locked."; existing members still update. Open again works.
- [ ] Tap a non-crew squadmate → Add sends a knock; the founder also sees Remove.
- [ ] Leave removes you from the board on both sides; the switcher moves to the next squad or shows "join or create".
- [ ] A wrong code says "No squad with that code."; squads never appear anywhere you didn't paste a code.
## Friend requests (knocks)
- [ ] After a squadmate taps Add on you, your board shows "👋 <name> added you from <squad> · Add back"; Add back makes you crew and the banner goes; × mutes that person.
- [ ] The Friends dialog lists the same knock with Add back / Ignore.
- [ ] Someone who shares no squad with you cannot knock you (rules test covers it).
## Clipboard output
- [ ] Your card → "Copy for the chat: today" → paste into Messages/WhatsApp/Notes: emoji intact (no `?`, no `∑`); one line of numbers under "Today · <date>".
- [ ] Your card → "week" → seven squares, "N of 7 days", totals, footer.
- [ ] Week view footer → "Share week" → one row per crewmate who studied, most days first; a crewmate who hasn't synced since mid-week reads "· as of <day>"; nobody with zero days appears.
- [ ] Today view footer → "Share today" → the same today line.

## Cheer notes, status, away (v2.2)
- [ ] 🎉 on a crewmate's row → dialog: emoji picked, optional note, Send. They get the flurry with the note in quotes after their next sync; "click to send one back" still works.
- [ ] With the OLD rules still published, a cheer with a note is sent without the note and the tooltip says so (then publish rules-v5 and retry).
- [ ] Click your own name → "Set a status" → type a line → your row on Today shows the bubble (truncates with … when long; full text on hover and on your card); crewmates see it after your sync; empty text clears it.
- [ ] Settings → Privacy → "Share when I'm away" with dates → ✈️ "back <date>" by your name on Today; a crewmate on the old version sees nothing odd; the week share shows ✈️ squares for those days and still counts studied days honestly.

## Accent colors
- [ ] Settings → Appearance → Accent: each of the six recolors the pills, links, your-row highlight, and the profile/stranger cards' buttons; check one in light and one in dark mode.

## Rules deployment (maintainer)
- [ ] Rules published in the console BEFORE the add-on release; after it, no v2.0 client shows "server catching up" in the footer.
- [ ] Console: delete the retired `server_board`, `server_names`, and `servers` collections once v1.x clients are gone.
- [ ] Firebase budget alert is set.
