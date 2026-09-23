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

## 2.5: emoji, squads week, block, Refresh
- [ ] Your card → "Pick an emoji" → 🦊: it shows before your name on Today, on your card, in the Friends list, in the crew week share, and (after a sync) on the squad board.
- [ ] Squads pill: a "Week" column shows N/7 for each member and sorts; the crew's Today/Week tables ignore that sort.
- [ ] Squad footer → Share: copies "busm · <date> / N studying · M reviews together / 🟩 top three".
- [ ] Founder → tap a member → Block: they vanish and cannot rejoin with the code while the squad is open. Make founder hands the Lock/Remove links to them.
- [ ] Refresh on the board after studying without syncing: your own row updates.
- [ ] Two accounts: after one adds the other, the Friends dialog shows ⏳ pending, and after the add-back both show ✓, with the second account never having synced its profile array (2.5 edges vouch alone).
- [ ] Your card → "month" / "year": copies "My September so far …" / "My 2026 so far …" with numbers matching Anki's Stats screen for the same range.
- [ ] Between the 1st and 7th: a "Your <last month>:" banner with Copy and ×; × hides it for that month only.

## 2.5.1: sync reliability
- [ ] Study a few cards, do NOT sync, go back to the Decks screen after 15+ minutes (or restart Anki and wait ~10 s): your row updates on its own.
- [ ] Turn Wi-Fi off and click Refresh: the footer reads "Couldn't sync · Updated …". Turn it back on and Refresh: the warning goes.
- [ ] Two accounts, an OPEN squad: founder removes the other person; that person syncs; they do NOT reappear on the founder's board, and their own board says "You're no longer in …".
- [ ] Your card → emoji: a long joined emoji (e.g. a family) is refused with "That one's too long."

## 2.6: decks, calendar weeks, sync status
- [ ] Decks tab: each bar shows a hatched "unlocked" span after seen and mature; suspend a batch of new cards and sync, and your hatched span shrinks while "seen / total" stays.
- [ ] Decks tab in dark mode: the legend (solid / faded / hatched) still describes the bars.
- [ ] Hover a bar: exact seen, mature, unlocked, total, this week, and 7-day retention. Study in a shared deck, Refresh: "+N today" appears on your row.
- [ ] Privacy → turn off Retention: your deck rows lose the % for your crew after the next sync.
- [ ] Week view on a Wednesday sums Monday–Wednesday only; "Share week" shows three squares, "3 of 3 days".
- [ ] On a Monday the "Last week, together" banner covers the previous Monday–Sunday, even if you first open Anki on Tuesday.
- [ ] Settings → Account shows "Synced … · v2.6.0"; with Wi-Fi off after a failed Refresh it still shows the last ACCEPTED sync.
- [ ] A one-person board offers "Copy invite".
- [ ] Shared Decks: a deck you already share says "matches <friend>", never your own name.

## 2.7: any emoji in cheers (rules-v8)
- [ ] Cheer a friend: six quick picks, the first preselected; Send delivers it and the tooltip names it.
- [ ] Click "other": the system emoji palette opens (Mac). Pick one: it lands in the box with the green border, no quick pick checked; Send delivers that one.
- [ ] Pick a second emoji from the palette: it replaces the first. The box never holds two.
- [ ] Paste "hello" into the box: it vanishes and the first quick pick is selected again.
- [ ] Receiving: a crewmate on 2.6 sees a 2.7 client's new emoji as a normal flurry; their "click to send one back" does nothing for it (expected until they update).
- [ ] With the footer saying "server catching up" (rules-v8 not pasted yet): the picker shows only 🎉 💪 🔥 and no "other" box.
- [ ] Windows (not tested by me): "other" should open the Win-period emoji panel; if it doesn't, typing or pasting an emoji into the box still works.
- [ ] A cheer plays once; after it, the sender's doc under your `cheers` collection is gone in the console.
- [ ] With AnkiWeb auto-sync OFF: open Anki, wait ten seconds; your profile's `lastUpdated` in the console is now (the push on open, dead since 2.5.1 when online).
- [ ] Open Anki with auto-sync on: the console's read count for the minute is about a third of what 2.6 did (one fetch, not three).
- [ ] Add a friend on another device: they appear after Refresh or the next day's first open, not on an automatic refresh (profiles are read once a day).
- [ ] A crewmate in a far time zone still shows their live numbers in the evening (their profile now carries `tz` and `rollover`).
- [ ] Close Anki: the closing sync still uploads (console `lastUpdated`), and nothing is fetched.
- [ ] With more than ten crewmates: Today and Week scroll inside the card, the header stays while scrolling, and the board opens with your own row in view. Ten or fewer: unchanged.
- [ ] Same on a squad of more than ten, and on Decks when the bars pass ten (legend stays below the box).
- [ ] Decks tab: no more "X shares Y — open Shared decks" lines; the dialog still says "matches …".


## 2.8: just show up
- [ ] Settings → Privacy → Just show up, Save: the board becomes one Crew view, a square per day (Monday to today), today's letter in green, "N showed up today" above; the Today/Week pills are one "Crew" pill.
- [ ] Your next sync: in the console your daily doc has `studied` and no numbers; your squad member doc has no numbers either, `joinedAt` intact.
- [ ] A crewmate on numbers sees you as a check after the ranked rows (Today), "· N of 7 days" (Week), and on a squad board a check with your 7-day count.
- [ ] In the mode: toasts say "X just studied" with no count; no streak toasts; a crewmate's card shows no streak and a which-days heatmap; a squadmate's card says "showed up today"; Share week copies squares with no totals line.
- [ ] Switch it off, Save, sync: numbers return everywhere on the next fetch.
