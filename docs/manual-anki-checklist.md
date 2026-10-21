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

## 2.9: onboarding, a lighter week, consistency (rules-v9)
- [ ] Rules-v9 pasted in the console BEFORE the release; the footer shows no "server catching up" on 2.9.
- [ ] A fresh profile (no email used yet): the Decks screen says "Nothing is shared until you join. Join · Sign in"; Join opens the dialog on Join, Sign in on Sign In.
- [ ] Join: the welcome screen shows your code at once, Copy Invite copies, and nothing is uploaded until it closes (console: no daily_stats doc yet). Tick "Just show up", Done: the first upload has no numbers.
- [ ] Welcome → paste a friend's whole invite into "Have a code?" → Add: "Added X. They'll see it on their board."
- [ ] On that friend's account: within an hour, or at once on Refresh, the board says "👋 <name> added your code · Add back"; Add back makes you crew on both boards.
- [ ] Friends dialog: paste an invite in the old wording ("My friend code: ABC123"): it adds. The list says "⏳ … — waiting", the section is "Added you".
- [ ] A one-person board: "Just you so far. Your code ABC123 · Copy invite · Add a code"; Add a code opens Friends with the box focused.
- [ ] Two 2.9 accounts: in the console, `users/{uid}/shared/week` holds the last days; after one Refresh the other's week view matches their day docs. Away dates show as ✈️ for the right days with no future `daily_stats` docs needed by 2.9 readers.
- [ ] A 2.8 crewmate still sees a 2.9 account normally (day docs are still written).
- [ ] Privacy → turn Retention off, Save: your squad row loses retention for squadmates after the next sync. Squads dialog note matches what's shared.
- [ ] Settings → Theme: Light with Anki in night mode: your card, a squadmate's card, and a cheer banner are light, in your accent. Dialogs (the code box, cheer picks) use your accent too.
- [ ] Sort the squad board by 7 days, open Settings, Save: still sorted by 7 days.
- [ ] Settings has three tabs, You · Board · Privacy. You: emoji, name, and status, each editable there; the emoji picker and status box open over Settings, and the tab shows the change at once.
- [ ] Privacy: "My numbers" / "Just that I studied" / "Nothing for now". The number boxes grey out under the other two and keep their ticks; switching back to My numbers shares what was ticked.
- [ ] Choose "Nothing for now", Save: the board shows you "on a break" to your crew (as Pause did). Choose "Just that I studied": the one Crew view.
- [ ] Board → Reset Board: only that tab changes; Privacy (choice, numbers, dates) stays as it was. There is no Restore Defaults any more.
- [ ] Your card → Privacy…: Settings opens on the Privacy tab. The board footer ends "Refresh · Settings", which opens Settings.
- [ ] Board tab: no "Sort by"; the note says to sort by the headers. Accent shows a color dot per choice.
- [ ] Your card → Pick an emoji: the picker with quick picks and "other"; Remove clears it.
- [ ] Squad board: "Copy invite · Lock · Leave" on the squad's line, "Share today" in the footer. Founder card: Remove / Block / Make founder on a row of their own, Close beside Add.
- [ ] Remove, Leave, Block, Sign out, Delete account: one confirmation style, the button says what happens, Cancel is the default.
- [ ] A window about 480 px wide: headers are icons, names keep their room, the footer links don't break mid-word.
- [ ] Shared Decks: a collapsed tree with a filter; a deck someone shares says "matches <name>" and is expanded into view.
- [ ] A large collection: syncing no longer stutters the Decks screen (the heatmap and fingerprints are cached for the day).
- [ ] A crew of more than 20 loads (it didn't before 2.9).


## 2.10: studying together (rules-v10)
- [ ] Rules-v10 pasted in the console BEFORE the release.
- [ ] Footer → "I'm studying": a dot and "studying now" by your name; a crewmate on 2.10 sees it after a Refresh; "Stop studying" clears it; after an hour it clears on its own.
- [ ] Status "200 cards, then bed": a small bar and count under your name that fills as you study, then "✓ 200 cards, then bed". A status without a leading number is unchanged.
- [ ] Reviewer → More (and right-click) → "Due Crew: this one's getting me": tooltip says it's flagged. A crewmate with the same deck sees "🧩 <you> finds “…” tricky" on the Decks tab; a cloze reads […]. A crewmate without the deck sees nothing.
- [ ] They click Send a tip, write a line: you get a toast; the next time that card's answer shows, the tip sits under it. Not on the question side.
- [ ] Set a friend's exam date to tomorrow: your board's eve banner says "Add a line to their card". Send one. On their exam day, their first Decks screen opens the good-luck card with the lines; Thanks, crew sends each writer a 💚. It shows once.
- [ ] A crewmate crosses a 100-day streak: a banner with "Send 💯"; it sends and goes away; × dismisses it.
- [ ] A cheer in October has 🎃/🍂 in its flurry.
- [ ] With rules-v9 still published: a tip or a line goes as a plain cheer with its words, and the tooltip says the server needs an update.
- [ ] The board's top left is the one-line logo, not the words "Due Crew", in your accent; Settings → Accent changes it on Save; night mode turns the wordmark pale. A narrow window puts the Today/Week/Decks/Squads pills under it. The signed-out and loading cards show it too.
- [ ] The logo tops Sign In / Join and the welcome screen, sharp on a Retina or high-DPI screen. Settings → Accent → rose, reopen Sign In: the studied days are rose. Anki in night mode: the wordmark is pale and the squares take the dark shade.

## 2.11: the logo on the board, New Code

- [ ] The board's top left is the logo (see the 2.10 logo lines above).
- [ ] Friends → New Code → confirm: a different code shows; Copy Invite copies it; the solo board's Copy invite copies the new one too, without waiting for tomorrow.
- [ ] A friend adds the OLD code: "That code doesn't match anyone." They add the new one: it works, and you get the Add back banner.
- [ ] Your crew is unchanged after New Code, on your board and on theirs.

## 2.11.1: streaks from the phone

- [ ] Study only on the phone for a day (desktop closed), sync the phone. Next morning open desktop Anki: while it syncs, your streak on the board doesn't drop; once the sync lands it shows the full run (yesterday included), the same morning, not the day after.
- [ ] The heatmap (click your name) shows the phone-only days after that same sync.
- [ ] A profile that doesn't sync with AnkiWeb: the streak is exactly the count from this computer, as before.

## 2.12: study rooms

- [ ] Footer → Open a room → 4 × 25, 5-min breaks, Now → Open Room. The board shows the room (ring, rounds, Study, Leave); the top bar shows the chip with the seven squares, the ring, "Round 1 of 4", and your initial.
- [ ] A crewmate on 2.12 refreshes: an invite with Join. They join; after your next refresh both of you show "in <host>'s room" and both initials sit in the chip.
- [ ] Review: the chip stays in the top bar; the card is untouched. Click it: the room card (rounds, who's in, Tuck it away, Leave). Tuck it away leaves only the ring.
- [ ] Preferences → hide the top bar while reviewing: the room moves beside Edit in the bottom bar. Hide the bottom bar too, window wide: a card in the left margin, gone on a card with a full-width image.
- [ ] Open a room of 2 × 15 with 5-min breaks, review past the 15 minutes: the card on screen stays until you answer it; then the break replaces the next card, keys do nothing, the answer buttons are hidden. Skip the break brings the card and keys back. Waiting it out does too.
- [ ] Cheer the room on the break sends 🎉 to each roommate.
- [ ] On a type-in-the-answer card, let the break arrive: Enter does nothing under it. On an audio card: no sound under the break; the audio plays when it ends.
- [ ] Browse → the card you came back to after the break: its time is the few seconds after the break, not the break.
- [ ] A friend joins mid-round: at the next break your chip shows their initial.
- [ ] Close Anki while in a room; a friend refreshes: you're no longer "in the room".
- [ ] After the last round: the chip goes, and the board says "Room done: … together with …", with Share (copies a line) and × .
- [ ] "At 20:00": the invite says "starts at 20:00"; the chip shows "starts 20:00" until then.
- [ ] Night mode: chip, bottom bar, margin card, break and room card all read well.
- [ ] 3.8.1: Settings → Room chip → Left. On a break, the chip's ring and the board's fill the same way (as the break passes) and both say the minutes left. Click the chip: the room card opens at the left and the chip hides; drag the card by its squares row (it stays on screen), close it with ×, then open it again: back where you left it, and the chip shows again whenever the card is closed (×, a click outside, Tuck, Leave, or going to another screen). Right: the same at the right.

## 2.13: settings follow the account (rules-v11)

- [ ] Rules-v11 pasted in the console BEFORE the release.
- [ ] Computer A: share two decks, turn Retention off, set an exam date and a status. Computer B (or a fresh Anki profile), sign in: before its first upload, B shows the same shared decks, Retention off, exam date and status. A crewmate's board never loses your decks.
- [ ] B: change the status. A, the next day (or restart A): the new status is there.
- [ ] Accent and sort differ between A and B and stay that way.
- [ ] Settings shows the line about what follows your account.
- [ ] With rules-v10 still published: B carries on as before 2.13, and its first sync doesn't empty your shared decks.
- [ ] Learn a few new cards and review some old ones: under your Reviews a grey "N new" line; hover says "N of M were new cards". Only new cards today: "all new". None: no line.
- [ ] Week tab: the line adds up the week. Squads tab (rules-v11 published): the same line on your row.
- [ ] Turn Reviews off in Privacy: the line goes from your friends' boards with the number. Just show up: neither.
- [ ] Your profile card: "Today: X reviews (N new)". Share today and Share week: "(N new)" after the reviews.

## 3.0: the Worker, and sign-in by code

Against the dev Worker first: in Tools → Add-ons → Due Crew → Config, set
`"api_base": "https://api-dev.duecrew.com"`, restart Anki. Remove the key
before trying the real thing.

- [ ] A 2.13 profile, updated to 3.0: the board says Due Crew now signs in with a code by email. Sign in: the email arrives (plain text, no link), the code works, no name is asked.
- [ ] After the first sync: your friend code is the one you had, your crew is back (anyone not on 3.0 yet shows as waiting), and your squads are there under the same names.
- [ ] A wrong code says so; five wrong codes kill that code; a sixth locks the address for an hour (then it works again).
- [ ] A brand-new address: a new account, asked for a name; the welcome screen follows; Friends shows a code.
- [ ] A refresh is one request: `npx wrangler tail --env dev` shows one GET /board per refresh, one POST /sync per sync.
- [ ] Flag a card: a crewmate with the same note sees it on the Decks tab with the card's text (from their own copy); the server never has the text (`wrangler d1 execute due-crew-dev --remote --command "SELECT doc FROM weeks"`).
- [ ] Settings → Sign Out, then sign in on another computer: both work; Delete Account from one signs the other out at its next request.
- [ ] Paused, show-up, away dates, exam date, statuses, cheers with notes, good-luck lines, tips, rooms: each still reaches a crewmate on 3.0.

## 3.0.1: a tip clears the flag, mute and report, the room chip's side

Deploy the Worker first (the tag does), dev first as for 3.0.

- [ ] A flags a card; B (same note) sees it under "Flagged by the crew" and sends a tip: the flag goes from B's Decks tab at once, and from C's (same note) at C's next refresh. A gets the tip under the card's answer.
- [ ] The race: A flags two cards; B tips one. A clicks Anki's Sync before any refresh (a sync uploads before it reads the board): the tipped flag stays down for B and C, the other stays up, and A gets the tip. A syncs again: still down. A flags the card again: it's back up.
- [ ] A plain cheer (no tip) leaves A's flags alone.
- [ ] Right-click a crewmate's name on Today or Week: Mute cheers, Report…. Right-click your own name: no menu. A normal click still opens the profile.
- [ ] Mute B: B's cheers and knocks (a knock from a shared squad) no longer arrive; B is still crew on both boards, and B's board says nothing. The menu now says Unmute cheers; unmute and B's next cheer plays.
- [ ] A second computer signed in to the same account: B is muted there too after its next settings pull (restart Anki).
- [ ] B, muted, tips A's flag: the flag goes down for the crew, then comes back up at A's next sync (a muted tip doesn't count).
- [ ] Report… on B: "Report B", three choices, a note, "Sends their name, emoji and last cheer to Due Crew. Reporting also mutes them.", Cancel / Report. Cancel does nothing. Report: tooltip says reported and muted; B is muted. With REPORT_TO set, the mail arrives with both uids, B's name and emoji, the reason, the note, and B's cheer to you if it was still unread; your address isn't in it. Without REPORT_TO, `wrangler tail` shows "report received" and no ids.
- [ ] Settings → Board → Room chip: Left. Open a room: the chip sits at the left end of the top bar (Decks screen and while reviewing); with another add-on's chip in the top bar, the two don't overlap. Right puts it back. Reset Board puts it back on the right. A second computer keeps its own choice.

## 3.1: plans

Against the dev Worker and a dev site first (`api_base`, and `site_base`
for the builder's link), as for 3.0. Two accounts: Dre (author) and Maya
(follower), in one squad.

- [ ] Tools → Due Crew is a submenu: Friends…, Squads…, Make a plan from a deck…, Follow a plan…, Settings…. Each opens what it says.
- [ ] Dre: Make a plan from a deck… → pick a deck: "Sends N tag names and M subdeck names, with how many cards each has. No card text." Tags only / Subdecks only change the numbers. Open the builder: the browser opens duecrew.com/plans/new signed in as Dre, with that deck's tree. The link works once: reload it after five minutes and it asks for a sign-in.
- [ ] Dre builds three dates (one opening today, one yesterday, one next week), publishes, offers it to the squad.
- [ ] Dre: Browse → select three cards (one of them c2 of a cloze) → right-click → Due Crew: add to a plan… → the plan, "With <date>" → Add. The site shows 3 single cards on that date. Again with "On its own date": a new date appears.
- [ ] Maya: the Decks and Squads tabs show "Dre offered <squad> a plan: <name>" with Look and ×. Look opens Follow a plan with the code filled in; × hides it for good.
- [ ] Maya: Follow a plan… → paste the link (duecrew.com/p/CODE): the title, "Run it on" with the matching deck and "best match of your decks", the list of dates with what's found ("not in your copy" in orange for a missing one), "N cards found in your copy", "2 units have already opened (N cards)", "Join this plan's squad" unchecked (its tooltip says what it shares). Follow with Open them now: a toast "Due Crew opened 2 dates: N cards"; Edit → Undo says "Undo Due Crew: open 2 dates", and undoes all of them at once.
- [ ] A copy whose tags start differently (rename the top tag in Maya's collection first): "Your tags start differently … Use X::". Use it: the dates match.
- [ ] Follow again on a fresh profile with Start from the next unit: nothing opens now; the next date opens on its morning.
- [ ] The Decks tab: "<name> · Dre's plan", "week X of Y · N following", a row per opened date (You: seen, Crew: done, "N of M"), the next date's "opens …", "✓ Opened … this morning: N cards" with Undo. Review a card: Undo goes (Anki has a newer step).
- [ ] The next morning (change the computer's date, or wait): after Anki's sync on open, the day's date opens with the toast, once. A profile that doesn't sync: at the first refresh. Offline with sync on: three minutes after opening.
- [ ] Dre moves a date later and one earlier, adds a date: Maya's card says "Dre moved … and added …" with OK. Nothing that was open closes. The date moved earlier opens the next morning, not before.
- [ ] Your plans… › Settings › More › Open everything now: every date opens, one undo step. Change deck…: pick another deck; its cards for the opened dates open. Pause: no mornings; the card says paused. Resume: asks "N units opened while paused" with Open them now / Start from the next unit.
- [ ] Your plans… › Settings › Stop following…: "Stop following <name>? Nothing gets suspended…", Stop. The card goes; every open card stays open; Dre's progress page stops counting Maya.
- [ ] Follow with "Join this plan's squad" unchecked: Dre's progress page doesn't count Maya, the crew's done counts leave her out, and her own progress still shows on the site's Home. Join its squad from the plan card's line (it asks first, saying what it shares): she counts; Leave in the squad (its question says progress stops counting): she doesn't.
- [ ] 3.7.6: a date's details from today on have Move…: pick a day; the date shows there dashed with "· moved" and Put it back; the site's plan page says "1 date moved". Your plans… › Settings › More › Reset to default… lists what goes back; Reset puts it all back.
- [ ] 3.7.6: follow a plan whose first dates have passed: Start where everyone is (no behind, the earlier dates skipped with Undo skip), Catch up over 2 weeks (a catch-up note, no "behind"), Start from the beginning (today is its first date).
- [ ] 3.7.6: on a card with another add-on's button beside Edit (AnkiHub), the answer buttons sit in the middle and the ask chip sits beside More.
- [ ] 3.7.6: a follower who shared before the update sees "Join this plan's squad?" once on the plan card; Join puts them in it; No thanks makes it go without a question.
- [ ] A plan or date name with <b>markup</b>: shown as text on the card, in the dialogs, and in the toast.
- [ ] `wrangler tail`: a normal day is still one GET /board and one POST /sync per refresh and sync; the plans ride the day's first refresh (`decks=1`).

### 3.1.1: plan fixes

- [ ] Two profiles, A following a plan and B following none: open B, then A. A's card still shows its opened dates, and A's next morning opens only the new date (nothing it opened before). `user_files/<profile>/plans.json` exists for each; the add-on's config (Tools → Add-ons → Config) has no `plans` keys.
- [ ] Upgrading from 3.1.0 with a plan followed: the first profile opened whose decks the plan runs on keeps it (its card, its opened dates); the other profile doesn't show it as running.
- [ ] Switch profiles while the board is still loading (right after opening): the second profile's board shows its own crew and code, never the first's.
- [ ] Follow a plan on computer 1 with Start from the next unit. On computer 2 (after its sync): only today's date opens, not the earlier ones.
- [ ] Dre adds a tag to a date Maya already opened; Maya suspends one of its cards by hand, and one card of it is a leech. Next morning: only the added tag's cards open; the hand-suspended card and the leech stay suspended.
- [ ] The board's Undo: the cards go back to suspended, then the card's "Opened … this morning" line goes and the counts drop. Edit → Undo is not offered for that step again.
- [ ] Browse in Notes mode → Due Crew: add to a plan…: a tooltip asks to switch to Cards; nothing opens. In Cards mode it works as before.
- [ ] Your plans… › Settings › More › Change deck… on a plan named with <b>markup</b>: the question shows the name as text.
- [ ] Signed out, AnkiWeb sync done at open, then sign in: the plans' morning runs with the sign-in's refresh, not three minutes later.
- [ ] Close Anki with a sync on close on a new day before the morning ran: no plan cards open during the close.

## 3.2: plans as training, who knows this one, the site's home

Two accounts again, Dre (author) and Maya (follower), mutual friends, a
deck both share (Settings › Shared decks).

- [ ] Dre, on the site: Settings has Ends, Catch-up weeks and Taper (no exam target). Dates has a Checkpoint per date and the weeks strip (build, catch-up light, taper grey, a checkpoint ringed). A date opening in a catch-up week gets the orange note. Save; a taper without an end date is refused with a plain message.
- [ ] Maya: Follow a plan… → Follow: My schedule opens right after. Days: click S twice (×2, then rest), minutes, a later start. The chart shows reviews a day by week, amber over my time, "your 60 min ≈ N"; the sentence says what to do. Save: today's share opens (a toast), not the whole date. Cancel instead: dates open whole, as in 3.1.
- [ ] The plan card: three tiles (new today N / M, reviews due, ~minutes left), "On track." and Study now (opens the deck's review). A rest day says "rest day: no new"; a catch-up week and the taper say so.
- [ ] Skip two study days (change the date): the card says "You missed Tue and Wed: N new cards waiting" with Spread them (+N a day), Push my dates back 2 days, Leave them open. Push: one request, a tooltip; the plan's dates on the site don't move for Dre. Spread: the target grows by a quarter a day. Either way the question doesn't come back for those days.
- [ ] Your plans… › Settings › More › My schedule…: the same dialog with No schedule; No schedule takes it off.
- [ ] A checkpoint's morning: "Due Crew built Checkpoint · <date>", a filtered deck of that date's cards with most lapses first, under the Due Crew deck in the deck list. Study it: the card says "N done", then "Checkpoint … done: X of N right first time".
- [ ] The Monday of plan week 2: "Week 1 done: X of Y sessions, N new cards, on track." Dre's board shows "· week 1 done" beside Maya's name that day.
- [ ] Who knows this one: Maya presses Again on a card Dre has mature in the shared deck, then syncs. On its answer side, beside Edit: "🐙 Dre knows this · Ask". Ask → a line → the flag goes up. Dre's Decks tab: "Maya asks about a card you know: "…"" first, with Tip; the same card in Dre's reviewer shows "Maya asked about this · Tip". Dre tips: Maya's flag comes down; next time the card's answer shows "💡 Dre's tip"; click: the tip and This helped. Nothing is ever drawn inside the card.
- [ ] A card with no one who knows it and no tip: no chip. A card on the question side: no chip.
- [ ] The site, signed in: duecrew.com goes to Home (this week, today, cheers waiting, plans with on track or N behind, the crew with Cheer, Squads). A cheer shown there still plays in Anki. Log: tiles, 12 weeks by minutes/reviews/new/retention, each plan's line against my schedule. /admin: Sam only; anyone else gets Not found.
- [ ] `wrangler tail`: still one GET /board and one POST /sync per refresh and sync; My schedule and This helped are one request each, on a click.

### 3.2.1: the admin's notice

- [ ] Signed in on duecrew.com as the admin: the nav has Admin. Anyone else: no Admin, and /admin says Not found.
- [ ] Admin → A notice: post "Testing a notice" with https://duecrew.com as the link. It's under Showing now. In Anki (3.2.1), Refresh: 📣 Testing a notice · More · × on top of every tab. More opens the link in the browser; × hides it, and it stays hidden after a restart.
- [ ] Post one "only to add-ons older than 3.2.1": a 3.2.1 board doesn't show it. Take down: the next refresh drops it.
- [ ] A link that isn't https is refused with a plain message.

### 3.3: the calendar builder

- [ ] Anki: Make a plan from a deck… opens the site on the builder. Calendar tab: the left panel lists every tag readably with the raw tag under it; By resource / By system / Other tags / Subdecks when the deck has them. Search finds a tag by its raw or readable name.
- [ ] Tick two chapters, choose New cards a day (150), Lay it out: the days fill in order, big chapters split by their tags or evenly (a green edge, "1/3"), nothing on days off (untick S S) or in a catch-up week.
- [ ] Drag a chip to another day; drag a tag from the left onto a day; click a day: its panel on the right (name, Split…, ×, checkpoint, move). A heavy day shows the amber note with Split.
- [ ] Plan next week: only next Monday to Sunday fills. Save; Maya (no schedule) gets an even date's cards a slice a morning, not all at once.
- [ ] As text: Copy the prompt, paste it into an AI with a syllabus, paste the answer back, Read it: the preview lists each date; a made-up tag says not found; a "# Pick in Anki" line shows under To pick in Anki. Replace, Save.
- [ ] On a phone: the week shows as a list of days; What to cover folds.

### 3.3: following, the Plans tab, together (3.8.0: the tab is You › Plans, above the board)

- [ ] Follow a plan: nothing asks for a schedule; the board switches to a new Plans tab with the card (today's tiles, one status line, one bar a date). Decks has no plan card. Stop following everything: the tab goes.
- [ ] Make a plan from a big shared deck: the builder's tree reaches tags five levels down (#Videos › Cardiology › 2 · Anatomy › 4 · Penetrating…).
- [ ] Site, as the owner: + Co-author lists your crew; pick one. They see the plan under Yours (with you), can edit and save, can't see Settings. Remove them with ×.
- [ ] A follower opens the plan on the site: the calendar, read-only, with 💬 on days with notes; click a day, add a note; the author sees it and can take it down.
- [ ] History: each save with who and what; Undo on the latest puts it back.
- [ ] Two authors save the same plan from two browsers: the second says "Saved, with the other changes kept" and both changes are there.

### 3.3: a teacher and a class

- [ ] A deck with no tags: Make a plan opens its calendar straight away; tick the deck, Fill the calendar: 20 a day in the deck's order.
- [ ] A student imports the deck (all cards active) and follows: Follow shows "Hold back N cards of later dates until their day", checked. After Follow, only today's date is active; Edit › Undo undoes the hold. The next date opens on its morning. Stop following: everything held opens again.
- [ ] Not signed in: Make a plan / Follow a plan open the sign-in, then carry on.
- [ ] The plan's link in a private window: three steps, each with Copy.

### 3.3: a class through Step (C1–C5)

- [ ] C1: set the deck's New cards/day to 20 and follow a plan with 60 today: the card says "Anki shows 20 new a day in this deck; today has 60" with Raise to 60. Click: Deck Options shows 60 (a shared preset: this deck now has its own "(Due Crew)" copy; the others still 20). Edit › Undo puts it back.
- [ ] C2: Your plans… › Settings › More › Open early › 2 days: the next two days' cards open now; the card says "(2 days early)".
- [ ] C3: in the browser, search `tag:*Cardio* -tag:*Pharm*`, Due Crew: add to a plan › This search: the date shows the search with its count on the site; a follower's morning opens those cards. Paste a search on a day on the site: the same.
- [ ] C4: Study on a date's row opens "Due Crew · <date>". A review day on the site: that morning, "Review · A – B" (200 most-missed).
- [ ] C5: rename a tag in a follower's copy (like a new version of a shared deck): the date still opens its cards, and the card says the tags differ, with OK.

### 3.4: search counts, calendar

- [ ] Paste a search on a day on the site: "counted in your Anki soon". Refresh Anki (the day's first refresh, or tomorrow): the site shows its count; a search that finds nothing says so.
- [ ] Add to calendar › Google Calendar: Google offers to add "Step 1"; each date shows as an all-day event. Apple Calendar: the Calendar app subscribes. Move a date on the site: the calendar follows within a few hours.

### 3.4.0: a calmer builder, cards by ID, print, events, a follower's own days

On the site (as an author):
- [ ] Click a day: the side panel's second tab is that day (never a third column). Click a tag's + : it lands on that day, and What to cover says "Adding to …".
- [ ] The pace is one line; Finish by / Cards a day / I'll place each day each show only their own field. Fill says what it does ("Fill to Sun 1 Nov"); none when placing by hand.
- [ ] Share ▾ holds the code, Copy link, Add to calendar and co-authors. Save shows only while something's unsaved; ⌘S saves.
- [ ] E1: paste a column of note IDs into a day's Add cards: "N note IDs · all their cards", Add. The next refresh in your Anki counts them on the site.
- [ ] E2: Print: the list by week, topics by resource; the browser's print window shows only the list. A follower can print too.
- [ ] F1: on a day, Prep for › + New event (a name, a day). The event day shows "N days of prep"; pointing at it lights up its prep days. Finish by › "or an event…": Fill stops the day before and its new dates are for the event.

In Anki (as a follower):
- [ ] The plan card: "For Micro quiz on Thu · 2 more days of prep" while you prep.
- [ ] G1: Open now on the next date: that date opens (one Edit › Undo step); its morning opens nothing twice.
- [ ] G2: Not today, right after the morning: the cards close again, the card says they open tomorrow morning (Open it now works too); the next day they open.
- [ ] G3: Your plans… › Settings › Skip a date (or a date's Skip it in Upcoming): its row is crossed out with Undo skip; it never opens. Undo skip: it opens if its day has come.
- [ ] G4: Your plans… › Settings › Pause until… (your Away dates fill it in if set). The day after, "Welcome back": move my dates later, or open what I missed. Settings › My dates › Some days later… sets the days by hand; the card says "your dates +N days".
- [ ] G5: fall behind a day: "N new cards from earlier dates waiting · Catch up…": over 3 days, Anki's new count for the deck goes up today only; Stop puts it back.
- [ ] G6: on the site, the follower's plan page shows "you: 20 of 34", "you: skipped".

### 3.5: previews, the library, classes (site only)

- [ ] A: paste a plan's link (duecrew.com/p/CODE) into iMessage or Slack: the plan's name, one line and its picture show. A squad's plan shows the plain Due Crew card.
- [ ] B: a plan's Settings › Library › List it in the library; it shows at /library. Filter by its deck and length; search a word in its name.
- [ ] B: signed in as someone else: Look opens its calendar; Follow follows it (the add-on's next morning opens today's date); Copy › a Monday › it opens as your plan, "based on …".
- [ ] B: Report on someone's card sends a mail to REPORT_TO. As the admin, Take out: the author's Settings says why and the switch is gone.
- [ ] C1: duecrew.com/classes reads right on a phone and a computer; the landing links to it.
- [ ] C2: with 3+ followers sharing and most behind on a past date, Progress says so; Give the class a day moves the later dates (Save to keep).
- [ ] C3: Share › A poster for the class › Print: one page, the QR code scans to the plan's link.

### 3.5: home, log, admin (site)

- [ ] Home: the strip says what opens today, what's waiting, the next event, and today so far; the year shows under the board; "Since you were here" lists crew added back, notes and plan changes (a second visit shows only what's new).
- [ ] Home: a crewmate with an exam in the next two weeks: Send good luck › a line › Send. On their exam morning, their Anki shows it with the others.
- [ ] Log: tiles, the year, this week and last, 30 days by date, a plan's history line (after a few days of syncs); Export CSV downloads.
- [ ] Admin: tiles with lines (only accounts has a line the first day), sign-in codes, notices with Take down and Post again.

### 3.5.0: asking about a card (K1–K3)

- [ ] Right-click a card while reviewing (or More): "Due Crew: ask my crew about this…". The box names who has it down, if anyone; OK with or without a line. Right-click again: "take back my ask".
- [ ] A crewmate's Decks tab: "Asked of you" with your line, the card from their own copy, and Tip. Your own Decks tab: "Your asks", waiting, and who has it down.
- [ ] After their tip: your Decks tab shows "answered · 1 tip". When the card comes up, the answer side shows "💡 Name: the tip" beside Edit, cut short with the whole tip on hover; This helped turns to ✓ Helped without opening anything; clicking the tip opens all tips.
- [ ] Night mode and light mode: the chip and the new headings read clearly.

### 3.5.0: the Plans tab, and codes anywhere (3.8.0: You › Plans; its Today box went to Due's Today)

- [ ] Plans tab with a plan: the Today box names today's date(s), reviews, new and minutes; Study now starts the plan's deck; Put off to tomorrow closes them until tomorrow's morning.
- [ ] The week: today outlined, past days ticked or "N left", rest days faded, an event outlined. Click a later day: Open now opens it, Skip it skips it (Undo skip on the same day), Move my days back asks how many. ‹ › moves a week and "Today" comes back.
- [ ] Month on duecrew.com opens the plan's page, signed in.
- [ ] Narrow the Anki window: the week becomes a list. Night mode: everything reads.
- [ ] A rest day, a finished day (Next: … Open now), behind (Catch up…, Move my days back…), paused (Resume now).
- [ ] Following nothing: Follow a plan with three ways in; paste a plan code and Follow opens with it.
- [ ] Settings › Board › Tabs: untick Plans and Week; they're gone, and the board opens on Today. Tick them again.
- [ ] Welcome screen and the board's code box: a friend's code adds them; a plan's code opens Follow; a squad's opens Squads. A pasted invite works in each.
- [ ] Alone on the board after adding someone: "Waiting for Name to add you back."

### 3.5.0: invites (option B)

- [ ] Board › Copy invite: the clipboard is one line, "Study with me on
      Due Crew: duecrew.com/i/…", and the tooltip says "Send one per friend."
- [ ] Open the link signed out on a computer: "Name invited you", three
      steps, both Copy buttons work. On a phone: Email it only.
- [ ] Paste the whole line into a second account's welcome box: "You and
      … are crew", and both boards show each other with no Add back.
- [ ] Paste it again from a third account: "Added …", and the first
      account's board shows "… added you" with Add back.
- [ ] Pick an accent in Anki; sign in on duecrew.com: its buttons, links,
      logo and year wear it (light and dark). A second computer takes it
      at its next pull.
- [ ] Offline, Copy invite still copies a link, with the friend code in it;
      pasting that adds, and the other side sees Add back.
- [ ] Paste the link into iMessage or Discord: the preview reads "… invited
      you".

### 3.5.0: Settings in the board

- [ ] The board's ⚙ opens Settings where the board was; ‹ Board goes back.
      A name's card › Privacy… opens it on Privacy.
- [ ] Board: each switch, Theme, Accent (the logo and panel recolour at
      once), Tabs (a hidden tab is gone on ‹ Board), Crew name (saved on
      Enter or leaving the box), Reset board.
- [ ] Privacy: the three choices; the number switches under My numbers;
      a crewmate sees the change a few seconds later. Exam and Away: switch
      on, pick dates, switch off.
- [ ] You: Name…, Emoji…, Status… update the panel; Friends, Squads and
      Shared Decks open their dialogs; Sign out lands on the signed-out card.
- [ ] Night mode (Anki's and the Theme setting): every control readable,
      the date pickers too.
- [ ] Tab from control to control with the keyboard; Space toggles; focus
      stays on the control after it redraws.
- [ ] Turn off "Due Crew on the Decks screen": the board goes, with a
      tooltip; Tools › Due Crew › Settings opens the dialog to turn it back on.

### 3.6: squad bingo (two accounts in one squad)

- [ ] The Squads tab shows the card above the table: the mini grid, and on
      the first open of the week "A new card. This week's middle: …".
      After Open the card, that line gives way to how far you are.
- [ ] Open the card: it fills the board's place; ‹ Squads goes back, and
      so does switching tab. Light, dark, and a narrow window: squares
      readable, nothing centred that shouldn't be, no Anki button shadows.
- [ ] Click a square: its details show under the card (what exactly
      counts, "You: …" how close you are, who stamped it). Click another:
      it swaps. No request goes out.
- [ ] Study past a square's mark (Twenty minutes, Lunch break, a Due zero
      day), sync: your stamp shows on both accounts' cards. A team square
      says "2 of you · 1/2" until the second person passes it.
- [ ] Turn Time sharing off: a focus square keeps your "You: …" but says it
      stays on this computer, and your stamp leaves the other account's
      card at the next sync. Show-up mode: only the days squares go.
- [ ] Complete a line (or let the admin's test squad): "BINGO!" on the
      card, a tooltip once, and Copy for the group chat pastes the 3×3
      emoji grid with no names.
- [ ] 3.6.1: a squadmate on 3.5 is left out of "N of you" and named under
      the card ("1 of you needs to update Due Crew to play"), but still
      counts in "N of you". Squares say a number ("2 of you"); in a squad
      of 6, a half is 3. Every medium and hard square is days in a row.
- [ ] 3.6.1: install into a new add-on folder (config back to defaults,
      same sign-in): the squads come back on the first refresh, and the
      emoji and accent come back from the account.
- [ ] 3.6.1: Squads › Join a squad: look up a code; Join sits under Look
      Up at full size. Week tab with one row showing new cards: rows
      evenly spaced.
- [ ] /admin › Squad bingo: this week's card; edit a square's numbers
      (a wrong one says so), turn one off, add one; the counts appear the
      day after the cron runs.

### 3.6.5: picks that work in anyone's copy

- [ ] Browser, Notes mode: select three notes, right-click › Due Crew:
      copy as plan selector: "Copied 3 notes". Paste into a day's Add
      cards on the site: "3 notes · all their cards", Add. Cards mode
      does the same as cards: (card numbers from 1).
- [ ] Text: a line with notes:… and cards:… reads back as written (a
      guid with | or ` in it survives Read it). A line with nids: says
      to open Anki after saving. A name over 60 characters says it's cut.
- [ ] Text: Add to the plan is the first button; Replace asks again,
      naming how many dates it takes off.
- [ ] Paste note IDs onto a date and save; open Anki (the day's first
      refresh): a second profile whose copy has other note ids, following
      the plan, opens those cards the next morning.
- [ ] Add cards to a date that has opened (site and Anki's Add to a
      plan): both say followers get them tomorrow morning.
- [ ] A date with a leech, and one with a note your copy lacks: the
      plan card says "1 leech stays suspended…" and "1 of 2 exact cards
      aren't in your deck", with OK; OK hides it until the count grows.
- [ ] Plans tab: Today sits between ‹ and ›, greyed on this week. Opening
      the tab, today is open with the box on it and its date filled.
      Click another day: the box moves there with its details; click it
      again: both close. Move two weeks ahead, then Today: back, today
      open. No "~N min" anywhere on the plan card.
- [ ] Site, Text: opens on Add dates (an empty box). Paste a line with a
      date's own day and name: "adds to this date"; Add keeps every
      other date. Edit the whole plan: Read it lists what Replace takes
      off. Copy the prompt: it asks the AI to check its answer and gives
      each planned date's counts.
- [ ] Write a plan, open Anki (the day's first refresh), back on the
      site: a day says "N new here · M already on an earlier date", and
      a picked note your deck lacks says so.
- [ ] Tools › Due Crew › Export cards for my AI…: pick a plan, see the
      notes and size, Export to the Desktop. The file's first lines
      include "#guid column:1". Browser › Due Crew: export for my AI…
      does the selected notes.
- [ ] Send feedback from Tools › Due Crew, from the board's Settings ›
      You › Feedback, and from the site's footer. /admin › Feedback
      shows all three with name and version; Reply mails the sender
      (check the inbox), Mark done moves it to Done, Account looks them up.
- [ ] Plans tab, a day's details: under each date, what's in it grouped
      by resource (the tag's video series or book in bold, its topics
      after), searches and picked cards as one line each, and Browse N
      cards opens Anki's browser on exactly those cards. The Today box
      has one line of today's topics, cut with … when long.
- [ ] 3.8.0: each topic there (and in the Today box's line) is underlined
      with dots; a click opens Anki's browser on that topic's cards. A
      tag reads as "deck:<your deck>" tag:<the tag> in the search bar
      (your copy's tag when the plan's deck is another version) and finds
      the same cards as the date's own count; a subdeck, search or picked
      cards open by id. A topic none of whose cards are in your deck says
      so in a tooltip.
- [ ] 3.8.0: a past day's "16 left" in its cell opens Browse on just those
      unseen cards (the day itself doesn't open); its details show "Browse
      42 cards · 24 left". The Today box's "16 new behind" and Due's
      Behind "N cards to see" open the unseen cards of earlier dates. Due's
      plan rows: each topic opens its cards. Insights: a topic's name and
      the hero's "53 cards" open the same cards Study would. "3 leeches
      stay suspended" › See them.
- [ ] 3.8.0: Browse › select a card on a plan you follow › right-click ›
      Due Crew: show on my plan. Anki's main window comes forward on the
      Plans tab, that date's week, its details open; a tooltip names the
      date. A card on no plan says so. ‹ › lets go of that day.
- [ ] 3.8.0, the site: a date's panel (in the builder) › Copy search on a
      tag; paste it into Anki's Browse: it finds that tag's cards, in your
      copy's version of the deck too.

### The admin page, grown up (duecrew.com/admin)

- [ ] The sidebar switches pages and the address follows (/admin?p=people);
      a reload opens the same page. Narrow, the sidebar wraps above.
- [ ] An account: Delete account… stays shut until clicked; Cancel shuts it.
- [ ] Email them a fresh code: at Anki's code box, the code that arrives
      signs in. Clear their sign-in limits after ten asks lets them ask again.
- [ ] Change their email: both inboxes get a line; the old address still
      signs in; signing in at the new one lands on the same account.
- [ ] A squad by its code from the search box: Remove… (with a why) emails
      the founder and they can't rejoin; New code… shows the code once,
      the old code fails in Anki's Join, the new one works; Close joins;
      Rename; Make founder; Delete squad… with the name typed.
- [ ] The audit log lists each of the above; nothing in it shows an
      email or a code.

### Not yet today, and the site's board (3.6.7)

- [ ] A crewmate syncs before studying: in Anki and on duecrew.com/home
      their row has dashes, no rank or medal, "· nothing yet as of …", and sits
      under everyone who studied; their status still shows; 🎉 works.
- [ ] Week tab: someone with only zero days this week reads "nothing this
      week". A squad board: a 0-review row today sits under the ranked
      rows with dashes, and "N studying today" doesn't count it.
- [ ] duecrew.com/home beside Anki's board, the same day: Today, Week,
      Decks, Squads and Plans show the same people in the same order with
      the same chips and notes; the footer has Crew ▾ and "N waiting".

## Share cards (site)

- [ ] Home › This week › Share ›: the week card; each switch redraws it; Link size; Dark.
- [ ] On a phone, Share… opens the phone's share sheet with the picture; on a computer, Download saves a PNG.
- [ ] With Time studied off in Anki's Privacy, its switch is off and says so.
- [ ] Log › Share my 2026 ›: the year card, the days before the log dashed.
- [ ] Squads › a squad with bingo › Share ›: the card, a line ringed.
- [ ] A plan with every card seen: "Finished" on its page, Share a card ›; the code only on a code plan.
- [ ] On a computer, Copy picture, then paste into a chat.
- [ ] In December (or with the clock set), Home's rail opens with "Your 2026 in Anki"; Not now hides it after a reload.

## Quiet accounts (3.7)

- [ ] A crewmate with no sync in 90+ days: one "▸ N quiet" line under everyone; a click opens their rows. The same on a squad board and on duecrew.com.
- [ ] Settings › You ends with the 12-months sentence; Privacy's "Nothing for now" mentions 24 months; the Settings dialog has the sentence too.
- [ ] After deploying 0016: an account deleted by the job (or a test one with its uid hashed into `gone`), opened in Anki: "Welcome back… deleted after 12 months", and Start again signs up fresh.
- [ ] Admin › Today: the Housekeeping line under Needs you.


## Due (above the board; 3.8.0: the box's Today, Upcoming and Later)

- [ ] Due sits above the board on every tab; ▴ folds it to one line (and it stays folded after Anki restarts); the line's Study › opens the plan's deck.
- [ ] Today: Behind (a plan date from an earlier day not yet seen, an item of yours from yesterday), then Reviews, today's dates with each resource's numbers, your items. Review a date's cards: its box ticks itself at the next refresh.
- [ ] An author's line (add one in the builder's day panel under To do, with a link): tick it by hand; its link opens in the browser, not in the Decks screen.
- [ ] Type "Book the room fri": "→ Fri …" shows before Enter; Enter adds it to Friday and says "Added to Fri … · Show"; Show opens Upcoming. "×" on the preview keeps the words as text.
- [ ] Upcoming: today first, then two weeks; empty days fold into one line; + on a day adds to that day; the exam shows on its day.
- [ ] Later: an item with no day; Do today moves it; its day button moves it, Pick a day… opens a calendar, Edit… and Delete work.
- [ ] Settings › Board › Due: turning off Due, Suggestions, and Recover leeches (on: the next refresh brings leeches back as new, the tag off; Edit › Undo puts them back; "Recovered N leeches · See them" opens the browser).
- [ ] With 10+ misses today, "Go over today's N misses" builds a filtered deck and opens it; × hides it for the day.
- [ ] A second computer, after its morning pull, shows the same own items.


## 3.7.3: plan updates (an author and a follower)

- [ ] The author adds cards to today's date and saves. The follower, on the Decks screen, refreshes: "Dre added N cards to …" with Open and Not today; nothing opened yet. Open: they open in one step (Edit › Undo closes them). Mid-review the line waits until you're back on Decks.
- [ ] Not today: tomorrow's morning opens them. A later date the author changed redraws on the week at once.
- [ ] Held back on Follow: a new card added to a later date stays suspended.
- [ ] "Tell followers…" with a save, and a post on the plan page's Updates tab: the follower's plan card shows the newest one with OK; the site shows it above the calendar until Close.
- [ ] The author's Updates tab: "This version is in N of M followers' Anki" after the follower refreshes.

## 3.7.3: a plan's squad and Insights (two followers, or an author and a follower; 3.8.0: the squad is on the Squads tab)

- [ ] (3.8.0: no Plan · Insights tabs on the card; Insights is the box's own tab.) Not in its squad: the crew line ends "Join its squad"; it asks first, saying what it shares; Yes: "You're in. It's on the Squads tab."
- [ ] Both join. Review one of the plan's cards on one side and sync: on the other side, Squads › the plan's pill shows them lit (others faded); the plan card's line says "Squad: N of M showed up · Open ›", and Open goes to the squad.
- [ ] Ask the squad (type, Enter): it shows for the other at their next look, with a badge on the plan's pill and "Name asked ›" on the plan card until they open it; your own question never badges you.
- [ ] Squads with a squad of your own and a plan's squad: both pills; picking one shows it (a plan's: who showed up, then Ask the squad and its threads; "Open the plan · Leave" under it). With no squad of your own, the plan's squad is the one shown. Restart Anki: the pill you picked is still picked.
- [ ] Reply (Anki asks in a small box; the site opens one under the question); the asker marks That helped; Remove your own; Report someone else's (they're muted for you, their words go).
- [ ] In the reviewer, right-click a card from the plan's deck: "Due Crew: ask the squad about this…". The other side sees "on a card", or "on a card you have down" when they have it at 21+ days; See the card opens their browser on it. No card text leaves either computer.
- [ ] Squad bingo in a plan's squad: the small card under the faces, Open shows the full card (‹ Squads goes back); the same card and middle as the squad's, a square stamped once lit on both; nobody's name on a square.
- [ ] Studied on a phone yesterday, synced the computer today: yesterday counts for the squad (the streak, "Showed up 3 days").
- [ ] Insights (3.7.9): the header's % right against the 2 weeks before; with FSRS on, "N cards Anki won't show you before …" and Study N opens a filtered deck of them: an event with prep dates ("for") is named on the box and counts only those dates; an event no date preps for, or none, reads "Before Tue 13" and counts the whole plan; Not sticking yet rows (topic, its source, not right yet / forgot) each with Study; Your week in minutes with today marked; Optimize FSRS opens the deck's options, Not now hides it. A plan with no reviews says "Insights fill in after a week of reviews."
- [ ] Leave (under the plan's squad): its pill goes and the tab shows your own squad; your questions stay. Stopping the plan also takes you out.
- [ ] duecrew.com, the plan's page as a follower: no Team tab; "You're in its squad. Open it ›" (or what it shares and Join its squad), which lands on Home's Squads tab with the plan's pill picked: who showed up, its bingo, then Ask the squad. Leave there: the pill goes.
- [ ] Share ▾ in Anki on a Mac: "As text" and "As a picture" show as grey headings; My day, Our week, The squad's day; My day…, My week…, My year…, All time….

### 3.8.0: Crew, one tab (the four pills became two, below)

- [ ] Under Crew, Today, Week and Decks are picked as a squad is on the Squads tab; Week shows the week's table as before.
- [ ] Pick Week, go to Squads, click Crew: it comes back on Week. Pick Decks, the same. Restart Anki: still the one picked.
- [ ] Settings › Privacy › Just show up: This week and Decks.

### 3.8.0: You, and your people

- [ ] Open Anki on an install that was on the Plans tab: the board opens on Crew › Today, with the box above it open on Plans. A hidden Week (from 3.7) is gone from Settings and shows in the picker.
- [ ] The box above the board: Today · Upcoming · Later, a thin rule, then Plans · Insights, as words (the one on screen underlined). The count ("1 of 4 done") shows on Today and Upcoming only. Hide ▴ folds the whole box to one line; Show opens it.
- [ ] Today: a plan date's topics sit on its resources' rows (Video Series · Pharmacokinetics 6 / 85), each topic opening its cards in Browse; the list ends with the add line (no Tomorrow line; Upcoming has it). Behind shows on Today, not on Upcoming. Later's tab shows only while Later holds something; add one there ("Call home later") and the toast's Show opens it.
- [ ] The board under it: Crew · Squads pills, nothing else; the Decks view is in Crew's picker. Light, dark and a narrow window: nothing spills past the board's edge; on a narrow window Hide sits on the right.
- [ ] Plans (round five, Sam's pick A): the plan's name and Your plans…, its day in a line with Catch up…, then This week ‹ Today › and seven small days, each its bar (amber when behind) and what's left ("16 left", "24 to go", "38 new", ✓, rest), a quiz's name under its day; on a narrow window the days show their numbers alone and a quiz day is underlined. Due's lists on or off, the week is there. No Month ↗, no Done.
- [ ] Pick 3: follow two plans: the head is their names (one pressed), the shown plan's line and one Your plans… (on it); an amber dot on a plan that's behind. Click the other name: its card, week and lines; restart Anki: still that one. Browse › Show on my plan on the other plan's card: that plan, its day open. Two plans of one name show their whole titles. One plan: no switch.
- [ ] Pick A: click a day: its assignments open under the week (unfolding), whole: each date's name and bar, its topics by resource (each opens Browse), the authors' notes and lines (a Watch line with a link opens the browser), Browse N cards, N left, Open now, Study, Move…, Skip it, Put it back after a move, Undo skip, "N leeches stay shut"; a quiz day names the quiz (Study for it is the quiz row under the week). Click the same day: they fold away. Click another: the ring slides to it and the box grows or shrinks to the new day. With Reduce motion, nothing moves. Browse › Show on my plan opens the card's day there; ‹ › to another week shuts it.
- [ ] Round five: Today and Upcoming: click a plan date's name: its details open under it (Browse N cards, N left, Open now ahead of its day, Move…, Skip it, Put it back after a move, "N leeches stay shut"); click again, they shut. Each one does what the old week's did, and the board redraws with it.
- [ ] Plans: each plan's card with no Today box: its line (week, followers, "opens 2 days early" when set), the week, the next exam's cards at risk ("53 cards Anki won't show you before KSA … · Study 53") with FSRS on, one note, the crew line. Paused: "No new cards while it's paused" with Resume now. A rest day says so.
- [ ] Behind on a plan: its day's line has Catch up…; my dates later is Your plans… › Settings › My dates (no link in a day's details).
- [ ] The morning opens cards: Today says "This morning opened N new cards" with Put off to tomorrow, which closes them until tomorrow's morning; review a card and the line goes. With Due off in Settings, the line is on Plans instead.
- [ ] Following no plan: Plans shows the three ways in. A squad's offer to follow a plan shows on Plans and on Squads.
- [ ] Insights with a plan's deck picked: as 3.7.9, its leeches at the bottom ("N leeches stay suspended in this deck · See them" opens the browser on them). The plan card no longer mentions leeches.
- [ ] Insights on a deck with no plan (pick it in Insights' row of decks, or "How it's sticking ›" beside your deck on Crew › Decks): Exam and a date field sit in its head; set a date within three weeks there and the box reads "Your exam · …" over the whole deck, and Settings › Privacy shows the same date; clear the field and it's gone from both. Not sticking yet names topics from the deck's tags (never "leech"), or its subdecks when the cards have no tags; Study and the name's Browse open the same cards. Your week's key says "what Anki has due".
- [ ] The deck you picked stays picked after a restart (it's this computer's), and stays in the row after ten minutes.
- [ ] Settings › Board › Shows: Crew (always), Decks, Squads, Plans, Insights. Hide Plans and Insights with Due off: no box at all. A link to a hidden one (Insights › on a plan, How it's sticking ›) shows it again.
- [ ] Browse › right-click › Due Crew: show on my plan: the box opens on Plans, that date's week, its details open.
- [ ] Following a plan (Follow…): the box opens on Plans with the new plan.
- [ ] duecrew.com Home: Crew · Squads with Today · Week · Decks under Crew; a saved Decks or Plans tab opens on Crew. The rail's Plans panel lists each plan (following none: the library and Your plans). As admin, the plan-load chart is on the Log page under each plan.

### 3.8.0: five small ones, repeating to-dos, no jumps

- [ ] Filtered decks: Study a plan date (a "Due Crew · …" deck), finish every card in it; the next morning it's gone from the Decks screen, and Edit › Undo right after the morning still offers the morning's step (Put off to tomorrow works). A Due Crew deck with cards left stays. A filtered deck you made yourself stays.
- [ ] Learning back: review until only learning cards are left with steps of 10 min or more: Reviews says "N back at H:MM" (your clock) and isn't ticked; the box doesn't fold for the day until they're done.
- [ ] Sync now: with an AnkiWeb login, after the morning opens cards the line reads "This morning opened N new cards. Sync now · Put off to tomorrow"; Sync now runs Anki's sync, and once synced the link goes. Not logged in to AnkiWeb: no Sync now.
- [ ] Hard: on a deck where you press Hard on a fifth of reviews, Insights says "You press Hard on N% of reviews. Anki counts Hard as remembered." Not now hides it on every deck (for 30 days).
- [ ] Repeating to-dos: add "Practice block every tue" (the add box previews "→ every Tue"; × keeps the words). On a Tuesday it's on Today with "every Tue ▾"; tick it, and Upcoming shows next Tuesday's (no tick on that one). Its ▾ has Edit…, Stop repeating (a one-off today), Delete. "every mon: X", "X daily", "X weekdays", "X mondays" work too. duecrew.com's Due panel shows it on its days.
- [ ] No jumps: with the pointer on the box, flick Today → Insights → Later: the board under it stays put while the pointer stays on Due Crew; move it off and the box eases to its size. Squads while fetching keeps its height. Hide still folds at once.


### 3.8.0: one Settings, two keys, Study today, the topic map

- [ ] Tools › Due Crew › Settings… from the review screen: Anki goes to the Decks screen with Settings open. The add-on's Config button (Tools › Add-ons) does the same and the Add-ons window closes. Signed out, Settings still opens (Sign in… on You).
- [ ] Turn "Due Crew on the Decks screen" off: the board goes; Tools › Due Crew › Show on the Decks screen (a check) brings it back.
- [ ] Ctrl+Shift+S from the Decks screen, a deck's overview and Browse's main window: Study today starts. Ctrl+Shift+Q while reviewing a plan's card in its squad asks the squad; elsewhere it says what it's for. Settings › Board › Shortcuts › off: neither key does anything; on again, both do.
- [ ] Study today with a plan and two other decks due: the plan's deck first; when it's done Anki goes straight to the next deck ("Next: …"), then "Done for today" on the Decks screen; with 10+ misses today it builds no deck (no "Due Crew::Today's misses" appears). Press Escape mid-deck: "Study today stopped. This deck stays open.", and when the deck runs out Anki stays on its overview (no "Next: …").
- [ ] On a Mac: Settings › Board › Shortcuts shows ⌘⇧S and ⌃⇧Q; ⌃⇧Q (the Control key) while reviewing asks the squad, and nothing asks to log out.
- [ ] Squads: a squad with a long name (24 letters, or a plan's) is cut short in the table's corner, its whole name on hover; the table stays inside the card in a narrow window. Switching squads, the names don't jump sideways while it loads.
- [ ] Type half a to-do, then wait for a refresh (or a learning card coming back): the words and the day stay; press Enter and the box empties.
- [ ] Insights › What you know: broad subjects (a big shared deck: its systems), the big ones big, shaded by how well you know them; no lecture names, no subject twice. FSRS off: the tooltip says "right on their last review".
- [ ] With one block unsuspended (say all of Cardio), the map shows that block's parts, not one big Cardio tile; a subject with nothing started reads "new"; one partly started has a bar along its foot.
- [ ] The map's heading reads "by Systems ▾" (or another grouping); a yield rating isn't the first pick when a topic tree is there. Pick another way: the map redraws from the top, and stays that way for this deck after Anki restarts.
- [ ] Share › on the map's key: a sheet with the card as on screen (the opened level, its trail in the title). Copy picture, paste into a chat: a sharp 1080 square. Save… writes a .png. Copy as text: a line a subject with its square (🟩 🟨 🟧 ⬜) and %, then the foot. Percentages off: no numbers on the card or in the text, a Less–More key. Dark: the dark card.
- [ ] Share › As a picture › My week… (3.8.0): a sheet in Anki, not the browser: the card as on duecrew.com (squares, the big number, the stats, "with N crew this week"). With Time in Privacy off, Time studied starts off and says "off in Privacy"; tick it and the time shows. Story / Link change the shape; Copy picture pastes a sharp 1080×1350 (or 1200×630) into a chat; Save… writes a .png.
- [ ] My day…: today's card, "Today · Wed 14 Oct". In Just show up, My day… isn't offered and My week… starts with every number off.
- [ ] My year…: this year's calendar, the picker lists the years you studied in and All time; pick a year and back. Cheers from my crew says "counting…" for a moment, then ticks on with "Cheered on N times" (or "none yet"). Signed out: "sign in to count". The first open on a big collection may show a wait cursor for a second; the second is instant.
- [ ] Browse › right-click a suspended card › Due Crew: why isn't it showing?: "Suspended, so Anki never shows it." Unsuspend: the card unsuspends, the sheet reads again, Edit › Undo puts it back. Signed out, the item is still there.
- [ ] The same on a buried card (Show it today), a review due next week (Study it now: due today in Browse), a card in a filtered deck (Empty …: the deck empties), a new card deep in a big deck (N more new today: Anki's deck list shows the higher New count today). Pick ten cards of mixed kinds: a line a kind, with how many.
- [ ] Settings › Find a setting: type colour: Accent, Board › How it looks; Enter: the Accent row lights. Type holiday on the Board tab: Away; pick it: the Privacy tab opens and Away lights. Type something it doesn't have: "Nothing by that name". Esc empties it.
- [ ] Motion (3.8.0): tick a to-do: the check draws, the words get their line, the bar grows. Tick the day's last: the box folds with one soft green light and says ✓ Done for today. Add a to-do for Thursday: a chip flies to Upcoming. Click Upcoming, then Plans: the green line slides under each, and the box eases to its height. Crew ↔ Squads: the pill slides. Open Decks: the bars grow in. ↻: it turns until the board's back. With the system's Reduce motion on (macOS Accessibility › Display), none of it moves.
- [ ] Motion, round two (3.8.0): ⚙ slides Settings in, ‹ Board slides it back. Sort by Time: the column washes green once. Open Dre's card: it grows from the name and its year waves in; ✕, Escape and a click outside each shrink it back into the name. Dismiss a knock: it folds and the board closes up. Copy on a banner: the link says Copied ✓, then Copy again. Study a deck from Study today › (it names the deck) and come back to Decks: the box's numbers roll and ticks draw (the memory), with no tab sliding. Study a stuck topic's cards right: it says "sticking now ✓" and folds. Hover the logo: the six studied days do the wave, Thursday sits out; it also waves at the day's first board and when the day's done. A friend who adds you back: their row opens in with "new" for a few seconds, once. Reduce motion on: none of it moves.
- [ ] Motion: leave the board open while a friend studies; on the next refresh their numbers count up and glow; a refresh with nothing new moves nothing. Nothing slides between rows when the order changes.
- [ ] This week's change: off with "From next week" the first time; a week later (or with the clock moved on), on, with ↑/↓ pills on the tiles and "up N since …" at the foot; switching the map's "by" keeps each way's week.
- [ ] A tile with a › opens its parts, with "All › Cardio · N cards, N% · Browse all" above them; All goes back; Browse all opens every card of the subject (new ones too). A tile without a › opens all of its cards in Browse.
- [ ] Not sticking yet: a topic's name opens all of its cards in Browse; its Study N builds the hard ones only.
- [ ] Insights on a plan's deck: no plan name or › to Plans in its head; the exam date box is there. An exam date sooner than the plan's next event names the box "Your exam"; later, the plan's event does.
- [ ] The board's head: Today · Week · Decks in the table's top-left corner (light, dark, a narrow window); on Decks a line of its own with the key at its right; show-up mode's "N showed up today" under the table. Squads: the squad names in the corner (+ join or create wraps when narrow), the squad's line, its week and the bingo card under the table. Crew and Share in the footer have no ▾ and still open their menus.
- [ ] Squads: under the table, "Last 7 days: N study days between M of you" (no line when only one of you studied), the same on duecrew.com.
- [ ] A plan with an "Every week" line (builder, under the pace: Do · Practice questions, F): on a Friday it's in Today with the plan's name and "every Fri"; tick it, it's done for today only; Upcoming shows it once, on the next Friday; its link opens in the browser; it's never Behind; duecrew.com's Due panel shows it on Fridays.
- [ ] Due Crew's filtered decks (a date's Study, Insights' Study, a checkpoint, today's misses) sit under one Due Crew deck that folds with Anki's +/−. Once they're all studied, the next morning's tidy removes them and the Due Crew deck in one step (Edit › Undo: Delete Deck); an old "Due Crew · …" deck at the top goes the same way once empty. A Today's misses deck left unstudied is emptied back into its decks the next morning, then goes with the rest.
- [ ] Settings › Board › Due › Recover leeches, switched on with a leech in the collection: "1 leech back as new cards. Edit › Undo puts it back." at once; Edit › Undo does.
- [ ] Plan tags, as the author (3.8.0): in Browse pick a few notes › right-click › Due Crew: tag for a plan…: only plans you made or co-author are listed; type SLG 12, it says where it lands (DueCrew::<plan>::SLG_12) › Tag N notes: the browser's sidebar has the tag at once, and Edit › Undo takes it off here. Pick some of those notes again: Take N off is there. A plan you only follow: "Only a plan's author or co-authors tag for it."
- [ ] Plan tags on duecrew.com: the builder's What to cover starts with This plan's tags (SLG 12 · 3 notes); + puts it on the picked day; Rename moves it on every date that used it; × asks, then drops it. A day with a plan tag: Overlap › SLG 12 · but not · a tag › Add makes "SLG 12 but not …" on that day. Text › Edit the whole plan starts with `tag | SLG 12 | notes:…` lines. Text › Tag by objective › Copy the tagging prompt carries the plan's tags and says to attach your own export.
- [ ] Plan tags, as a follower: after the author saves, the next morning (after AnkiWeb's sync, on the Decks screen) or a mid-day update gives your notes DueCrew::<plan>::SLG_12; the plan card says "New tags: SLG 12" once, with Browse them (opens on DueCrew::<plan>::*) and OK. Edit › Undo right after takes them off in one step. Reviewing when the update lands: nothing changes until you're back on Decks. Your own tags never change.
- [ ] Plan tags, stopping: Stop following asks, with "Take its tags off my notes" ticked; untick it and they stay; ticked, every DueCrew::<plan> tag goes (and DueCrew too when nothing else is under it).
- [ ] Plan tags, as an author who doesn't follow the plan: make a tag on duecrew.com from another tag (This plan's tags, or a `tag |` line in Text), save; Anki's next morning (or a refresh that brings the plan) tags your own notes DueCrew::<plan>::<tag> in one undo step and says so once; the builder's date counts it after that. Follow your own plan: nothing is announced again. Delete the plan on the site: the next morning takes the tags off your notes.
- [ ] Plan tags on duecrew.com, as a follower: the plan's page lists This plan's tags under the pace, with "in your Anki under DueCrew › …"; Copy search copies a search Browse finds them with.
- [ ] Round two (3.8.1), the builder: a day with a deck tag (a video) › its chip's All of it ▾ › Only SLG 12: the chip reads "Cephalosporins · SLG 12" with "38 of 64" once your Anki counts it; Rename SLG 12: the date follows; × on SLG 12 › Delete it: the date has the whole video again. Overlap › SLG 12 · and · a deck tag › Add makes the same kind of chip. Text › Add dates: `2026-10-14 | | tag:<a deck tag> in SLG 12` and `tag | SLG 13 | cards:<guid>:2` read and add.
- [ ] Round two, taking a tag off: Text › Edit the whole plan › delete a `tag |` line a date uses › Read it: "Takes off 1 tag … N dates still use it" with each date; Take them off those dates too lists what happens to each (a date left with nothing goes); Keep the tags puts the line back; Replace anyway replaces.
- [ ] Round two in Anki, as a follower: a date "Cephalosporins · SLG 12" opens only the video's cards that are in SLG 12, and its row reads that way in You › Plans and Due. A plan tag holding one cloze of a note: Browse them shows that card, not its siblings. The author adds a note to SLG 12 after the date opened: the next update opens just that note's cards.
- [ ] Round two, Insights: a deck with a plan's tags: the map's "by" lists "<plan>'s tags"; pick it: one tile each, and a line naming the tags no card in the deck carries. The map's first pick and the topics never show DueCrew tags. Tools › Due Crew › Export cards for my AI: the file has a `#cards` column.
- [ ] Your own pace: Follow a plan with "When I'm ready" (and, once, with the box under it): the late-start question goes, the line says nothing opens by itself; a deck whose later cards are open offers "Hold back N cards of later dates until you open them". The next morning opens nothing. You › Plans: "at your pace", Up next with N new, Open and Open and study, Then …, where the plan's dates are; no Behind, and Today has no Behind for it either.
- [ ] Open: the date's cards open (no leech) and Anki's next new cards are theirs (check the Browse Due column: they're first); the card says "Opened … first in line. Undo"; Undo shuts them again and it's Up next again. Open and study goes straight into a Due Crew deck of those new cards.
- [ ] With "the next once I've seen the last": study most of the opened date, and the next morning opens the following one by itself, only one.
- [ ] Put back on the plan card: only the unseen cards of the last date shut again; Edit › Undo puts them back. Stop following opens them.
- [ ] Your plans… › Settings › Cards open (and More's "the next once I've seen most of the last"): switch to When I'm ready (a deck with open later cards offers Hold back), and back to the plan's dates (dates passed since ask, as Resume does). duecrew.com's plan page shows "At your pace · next: …" and the same choice; changing it there reaches Anki at its next refresh.
- [ ] Browse: right-click a tag in the sidebar › Due Crew: open its cards…: the sheet counts what opens, what's open already, the leeches (they stay suspended), and the plans that hold them; Open with First in line ticked puts them first in Anki's new cards; one Edit › Undo shuts them. Pick cards in the table › Due Crew: open these…: the same for just those. Signed out: both are there.

### 3.9.2: the short pass before release (about 25 minutes)

The parts of 3.9.2 only a live Anki can show, riskiest first. Use a deck with
some history (a few weeks of reviews) and a few leeches.

- [ ] Stop new: You › Insights on a deck with new cards, Reviews ahead › Stop new now › Do it. The Decks screen shows 0 new on the deck and its subdecks; Deck Options' preset is unchanged. Edit › Undo (one step, "Due Crew: new cards stopped") brings them back; Do it again, then Turn new cards back on: they're back. With an exam date set 10+ days out, Stop new a week before the exam says "From <day>, … till your exam, <date>" and today keeps its new cards.
- [ ] Stop new before studying: Do it, then quit and reopen Anki the next day (or change the computer's date) and go straight to Study without visiting the Decks screen: no new cards.
- [ ] A plan on a stopped deck: its card says "New cards are stopped in this deck (Insights)" with Turn them back on (no "Raise to N"); Catch up… says to turn them back on first. Browse › a new card › Why isn't this card showing?: "you stopped new cards in <deck>".
- [ ] Leeches: Insights › See them. Each card shows its own question (a reversed card its back field; a cloze with its answer as […]). Bring back: the card is due again, one Edit › Undo re-suspends it. A Basic (and reversed) note with both cards leeches: Bring back one, the other stays listed. ⋯ › Leave it out: gone, and the list's foot says "1 left out · Put it back"; Put it back works. Study a card the list shows, come back: the list is current.
- [ ] Insights with FSRS off (Deck Options): the exam box never says "nothing at risk", the right % has no "Anki aims for".
- [ ] The map › by When you started them: weeks named by the map's own topics (never a shared deck's source names); a week you just started reads "too soon"; open a week: its topics, and Browse all on one opens only that week's cards.
- [ ] Polaroids: a doodle sent in your evening shows your day, not tomorrow's. Settings › Theme › Dark (and Match Anki with Anki's night mode): the Polaroids go dark, black ink reads light, colours readable, Pip in its night colour.
- [ ] Mac or Windows: Cheer window › other: the picker's pick lands; with the box up, click a quick emoji (the box goes), scroll or resize the window (it goes), or press Esc. Never left floating after the window closes.
- [ ] Tag Only leeches: a deck whose preset's Leech action is Tag Only (Anki's default since 23.10). Fail a card past its leech count (or use one tagged leech with lapses at the threshold): Insights says "N leeches still in your reviews · See them"; the view lists it under "Leeches still in your reviews", due today or back in N days, ⋯ with Learn it fresh, Edit, Leave it out (no Bring back). Learn it fresh: a new card, tag off, one Edit › Undo.
- [ ] The map › by When you started them, on a deck you only started this week: it stays by topic and says "Everything you've started is from one week".
- [ ] Cheer window › other: © or ™ from the computer's picker lands as the cheer.
- [ ] Offline: turn Wi-Fi off, quit and reopen Anki, wait a minute on the Decks screen, then click the board's ↻: no error window from Due Crew (the board's foot says it couldn't sync; Anki's own sync may say it's offline). Wi-Fi back on, ↻: the board fills in.
- [ ] duecrew.com builder, a plan you wrote: with an unsaved change, Share › Copy for next year says to save first; saved, it makes a copy named "<plan> (next year)" whose dates fall on the same weekdays a year on.

### 3.9.1: the short pass before release (about 15 minutes; the rest of 3.9.1 below as time allows)

The riskiest of 3.9.1, the parts only a live Anki can show, in order:

- [ ] Board clicks after a review (the Decks page's key): study a few cards, go back to Decks, then click Week, a crewmate's name (their card), ↻, ⚙ (Settings), a Due tick. Each works. Then Sync, and click them again. Switch profile and back: again. (If any click does nothing, stop: that's a release blocker.)
- [ ] The whole window dims: open the Cheer window on a crewmate. The top bar and the bottom bar grey with the board; click the grey top bar: the window closes and the bars clear. Open it again and press S (study): the bars clear on the way out, never stuck grey.
- [ ] A question on the board: own card › Set a status: a sheet in the board's look (not a Qt box); type, Enter: the status shows on your row. Settings › You › Display name: the same. Settings › Sign out: the sheet, Cancel does nothing; Esc and the backdrop the same.
- [ ] A question off the board: while reviewing, Ctrl+Shift+Q (Ask the squad) on a plan's card: a Qt box in the board's colours, readable, OK and Cancel work.
- [ ] The Qt windows: open Friends, Squads and (a plan's ⋯) Pause: board colours, the main button in your accent, ticks and radio dots visible, nothing cut off (Friends' code whole). Settings › Theme › Dark, open Friends again: dark, all readable.
- [ ] Round two (on the Mac): Open a Study Room: its title in the window ("Open a Study Room"), the frame says Due Crew; the round length box opens a list in the board's look (no tick column, "15 min" whole), the rounds box has its own up/down arrows; nothing looks washed out. Follow a plan with a code: the plan's dates evenly spaced, Follow and Cancel fully in view. Pause's date box opens a calendar with no red weekends.
- [ ] Mac or Windows: Cheer window › "other": the system's emoji picker opens and its pick lands.
- [ ] Leave Anki on the Decks screen a minute: Pips stop moving after about twelve seconds; the fan quiet (no busy CPU).
- [ ] The fridge: × on a drawing: "Taken down · Undo" in its place; Undo: it's back where it was. Take one down and wait: the Undo fades after about eight seconds. Sign out: the fridge is empty; sign in as someone else on the same Anki profile: none of the first person's drawings.

### 3.9.1: cheers, clearer (the pill, the Cheer window)

- [ ] The crew rows: no 🎉 at the end of any row, and no pill anywhere at rest. Point at a crewmate's name: a green "🎉 Cheer" pill shows after it (and after an exam or "studying now" chip); move off the name and it goes. Pointing at their numbers shows nothing. Tab to a name: it shows. Never on your own row. A very long name ends sooner while the pill shows; the pill is never cut off.
- [ ] Click the pill (or "🎉 Send a cheer" on their card): the Cheer window opens over the Decks screen in the board's look (your accent, light and dark both right), their Pip and "Cheer Dre" at the top. Pick an emoji, or type/paste any other into "other" (⌃⌘Space on a Mac). Draw on the pad with the mouse, a trackpad or a pen; Black, Thin, Thick, Undo, Clear. Sign: type, and the paper shows it.
- [ ] Send (or Enter in the note): the window fades, "Sent 🔥 and a drawing to Dre.", and the emoji floats up from their row. Cancel, Esc and a click on the dim backdrop close it without sending; a line drawn off the pad's edge never closes it.
- [ ] duecrew.com: the same pill after the name, only while pointing at the name; on a phone, tap the name for their card and its "🎉 Send a cheer"; the 🎉 column is gone.

### 3.9.1: two buttons

- [ ] Settings › Board › Reviewing: Two buttons, off. Its line: "Again and Good. Hard and Easy hide; 2, 3 and 4 count as Good. Phones keep four." With FSRS off (Deck options › FSRS), the line ends "Works best with FSRS on."; with it on, it doesn't. Find a setting: "hard" finds it.
- [ ] Turn it on and review: the bar shows Again and Good only, each with its interval, in Anki's own words (try another interface language). Learning cards that already show two buttons look as before.
- [ ] Keys: 1 is Again; Space, Enter, 2, 3 and 4 all answer Good (check the card's info: Good, not Hard or Easy). Turn it off: four buttons, and 2 and 4 are Hard and Easy again, at once.
- [ ] In a study room, on its break: no key answers (2 and 4 included), as before.
- [ ] A second computer signed in to the same account: it's on there after the account's settings come down. Your phone keeps four buttons.
- [ ] You › Insights on a deck where you press Hard a lot (15% of 200 answers): the Hard habit line ends "Try two buttons · Not now". Try two buttons: the line says "Two buttons are on … Undo", and Settings shows it on. Undo: off, and the Hard line is back. Reopen Anki with it on: no Hard habit line.

### 3.9.1: room sounds

- [ ] The chip says it: during a fifteen, the chip ends in an outlined "Sound" with a struck speaker; pick Rain: it reads "Rain" in your colour. A compact chip (narrow window) shows the speaker alone.
- [ ] Settings › Board › Fifteen and Pip › Room sounds, off: the sound fades out and the chip loses its speaker at once; start a fifteen: no speaker, no sound. On again: the speaker's back, with your last pick.
- [ ] Waves is the Pacific one now: listen for two minutes on loop: no click where it comes round.
- [ ] The picker closes by itself: pick Rain and leave the pointer still: the chip is back in a second and a half. Drag the volume and hold it: it stays; let go: back in two seconds. Open it and move away: back in a second. Open it and do nothing: back in four.
- [ ] The recordings: Rain is real rain, Fire a real fireplace (soft pops), Waves a real shore, each a minute or so that loops; listen for two minutes each: no click or jump where it comes round, no voices, birds or hum. Brown noise is the made one, as before. All four sound about as loud at one volume.

- [ ] Start a fifteen: its chip in the top bar ends in a grey speaker (struck through). Click it: the chip becomes Off · Brown noise · Rain · Fire · Waves; Off is filled. Esc, or a click anywhere else, puts the chip back; a click on the chip (not the speaker) still opens its card.
- [ ] Pick Rain: it fades in over a second or so (headphones for Brown noise and Waves: laptop speakers barely play them); the volume slider appears and changes it as you drag. Pick Fire: Rain fades as Fire comes in. The speaker is in your accent, with waves. Off: it fades out.
- [ ] Study with a sound on: it plays on through Review (cards changing don't cut it), through a fifteen's break and its question; Stop here: it fades out. Take five, then another: it plays through.
- [ ] Restart Anki, start a fifteen: your last pick comes back by itself (no click), at its volume. Sync (the top bar redraws): it carries on, or comes back within a moment.
- [ ] A crew room with someone who picked a different sound (or none): each of you hears your own; theirs never changes yours. The room ends: yours stops.
- [ ] Preferences › hide the top bar while reviewing: the room shows in the bottom bar or the margin with no speaker, and the sound plays on.
- [ ] No room and no fifteen: no sound, ever (it never starts on its own outside a session).

### 3.9.1: doodle cheers (deploy the Worker first: migration 0029)

- [ ] 🎉 a crewmate: the Cheer window opens small: the emoji, "Add Draw · Sign" with neither picked, the note, Send. Send now: a plain cheer. Press Draw: the pad opens; press Draw again: it shuts, and Send sends no drawing (open it again: what you drew is still there). Sign the same.
- [ ] Draw on the pad with the mouse (and a trackpad, and a pen if you have one): the lines follow, in your accent. The colours under the pad: yours first ("My colour"), then the other five accents, then Black; each changes the next line, as Thin and Thick do; a drawing can mix them. Undo takes the last line, Clear all of them. Night mode: the pad stays paper-light.
- [ ] Send a drawing in three colours: on their screen (held up, and on the fridge) each line is in the colour it was drawn in, whatever their own accent.
- [ ] Mac: "other" turns into a box ("pick one") and the Character Viewer opens; double-click any emoji, a skin tone, a flag: it's picked and "other" shows it. Esc instead: "other" is back. Windows: the same with the emoji panel (Win + .). Linux: the drawer below, as before.
- [ ] (Linux, or when the system's picker can't open) "other": a drawer opens under the emoji, in the window's look: Find, a row of groups (Faces, Hands, Hearts, Party, Study, Nature, Food), and the emoji. Type "coffee": ☕ (and only what matches); type nonsense: "Nothing by that name". A group's button scrolls to it. Click one: the drawer shuts and "other" shows it, picked. Paste or type an emoji into Find (⌃⌘Space on a Mac, Win+. on Windows): it's picked. Esc with the drawer open shuts the drawer, not the window; Esc again closes the window. A quick pick after that puts "other" back.
- [ ] Send with a drawing: "Sent 🎉 and a drawing to Adina." Send with the pad blank: a plain cheer, as before.
- [ ] Sign: type a few words; the paper under it shows them as they'll look; 24 letters at most. Send from the Sign tab: "Sent 🎉 and a sign …".
- [ ] On their Decks screen (or yours, cheered by a second account): the banner at the top, and your Pip (your colour, your look) rises at the board's bottom right holding the drawing (or the sign) up on two sticks, then ducks down as the banner goes. No show that time. A hat on your Pip sits under the sign, not in front of it.
- [ ] Reduce motion (system setting): no Pip rising; the drawing sits in the banner on its paper, under the note. Settings › Pip off: the same, with the emoji flurry.
- [ ] Held up, its note is under it as a caption, "from Adina", and isn't in the banner a second time. In the Cheer window, once you draw (or type a sign) the note's box says "A caption under it (optional)".
- [ ] Pip at rest (3.9.1): ▶ Fifteen?'s Pip naps (or blinks) for about twelve seconds, then holds still; point at it and it moves again. Same for a fifteen's chip and a room's card. A fifteen's break: the breathing square (or the stretch) goes on all break. Crew rows' Pips move while the row is hovered, still otherwise. The studying-now dot pulses a few times, then stays lit.
- [ ] The fridge: back on the Decks screen, the doodle is pinned beside the board as a Polaroid (a white frame, a little crooked, taped up with a see-through strip in their colour), the note on the frame under it, then their Pip and name and the day (no "from"). More of them fill the left side and the right, newest highest. Drag one anywhere: it stays there after Anki restarts; nothing redraws while you drag. Their Pips are still until you point at one (as crew rows).
- [ ] Window sizes: drag one just right of the board, then make the window wider and narrower: it keeps its distance from the board. Narrow the window till there's no room for it: it waits on the pile in the bottom right corner. Widen it again: it's back where you put it. A short window lifts a low one into view; a tall one puts it back. A new doodle that comes in goes round the ones you placed, not under them. Restart Anki: all still where you left them. Point at one: × takes it down. A narrow window with no room beside the board: a small pile in the bottom right corner, still draggable. Twelve at most; the oldest comes down to make room. Pip's closet has no Fridge page any more.
- [ ] duecrew.com's home, before Anki opens: "Adina cheered with a drawing: …, It waits for your Anki screen".
- [ ] Report someone who sent a sign: the admin's Inbox shows "(with a sign: "…")" in their last cheer.

### 3.9.0: cheers land everywhere

- [ ] Have a crewmate cheer you, then open the Decks screen: a show plays over the whole page, the deck list and the board, never over Anki's top bar; the banner at the top names them, with their note and "click to send one back". Cheered again (or a few cheers at once): a different show each time, never the same twice in a row, all twelve before any repeats.
- [ ] Three crewmates at once: the big version (three Pips, three presents, three stamps…). A present: click it and their Pip springs out with their note on the tag; leave it and it opens itself. Bubbles: click one and it pops.
- [ ] A click anywhere (but a present or bubble) or Esc ends it at once; otherwise it ends on its own and the page is as it was.
- [ ] Reduce motion (system setting): no show, the senders' Pips standing in the banner. Settings › Pip off: the emoji flurry, as before.

### 3.9.0: the closet's colour, the review chip

- [ ] Pip's closet: under Pip, Colour with the six swatches, yours ringed. Click one: Pip, the closet and (‹ Board) the board are in it; Settings › Board › Accent shows the same one. A crewmate sees your Pip in it after your next sync.
- [ ] Review a card a crewmate knows: the chip beside Edit has their Pip whole (hat and feet inside the pill), light and dark.

### 3.9.0: who knows it, the moment you miss it

- [ ] A crewmate (mutual, sharing the same deck) has a card down that you've never missed. Open Anki (the day's first sync), study, press Again on that card for the first time: ten minutes later it's back, and on its answer side their Pip pops up from the bottom right (no lightbulb), "I know this one", Ask Dre, Not now. No sync needed in between.
- [ ] Before you've missed it: nothing. The next card: their Pip ducks back down. Not now: the same. Ask Dre: the ask window, as before.
- [ ] Two crewmates know it: both Pips side by side at the same height whatever they wear (a hat, an umbrella), never blinking together, "Dre and Mo know this", Ask; three: "Dre, Mo and Jo know this"; four or more: three Pips, "Dre, Mo, Jo and 1 more know this". No lightbulb. Already asked: Asked. An ask from a crewmate or a plan's note: the corner card, folded (below), not the peek.
- [ ] A card whose text or picture fills that corner: still the peek, never the chip beside Edit; scroll down and the card's last lines clear it.
- [ ] Settings › Pip off: the same bubble in the same corner without Pip, "Dre knows this", Ask, Not now; it fades in, and out on the next card. Reduce motion (system setting): the Pip and bubble there at once, no pop, no duck. Settings › Pip off: the corner card as before.

### 3.9.0: asks and tips

- [ ] Ask on a card someone has down: the window says "Goes to everyone in your crew who has this card. Adina has it down. One line, optional." On a card nobody has down: the first and last sentences only. Asked already: "… You've asked. Change your line, or leave it as it is."
- [ ] A tip on a card you're stuck on: the tipper's Pip peeks up from the bottom right, its bubble edged in their colour (who knows it: a plain grey line), "Adina left a tip", Show, Not now; no words, and none on a hover. Show: "Adina: …" with This helped (and +1 more with two tips). This helped: it stays open (and asks first, as before). Pip off: the same bubble with 💡.
- [ ] A one-by-one card (a cloze that shows its parts a step at a time) with a tip: nothing of the tip's words shows until Show, whatever step you're on.
- [ ] A crewmate's ask with a line: their Pip and "Sam asked about this card", Show, Not now; Show: their line, Tip. An ask without a line: "Sam asked about this", Tip, as before. A plan's note: "📌 A note from Block 1", Show; Show: the note.
- [ ] Where the corner isn't free (a long card): the chip beside Edit says the same folded words with Show; a click shows the words, then This helped / Tip work as before. Opened on the card and then moved to the bar: still open there.

- [ ] Squad bingo: point at a square two or three of you stamped: their Pips blink each on their own, in no order and never together. A plan card's squad line, a study room's seats and the peek's Pips: the same.

### 3.9.0: smooth motion

- [ ] Crew ↔ Squads, back and forth: the green pill slides across, round at both ends on its way, and lands round on the outside edge; no frame of it square, no second outline, the words changing colour as it passes. Today · Week · Decks: the underline slides, the same.
- [ ] Fold and open the Due box, change tabs in it, add a to-do, tick one: the box grows and shrinks to its size and stops there, nothing below it jumping a few pixels at the end. A note or a knock leaving, the last topic that starts sticking, Caught up: what's under them settles once, no hop.
- [ ] Click ↻ and let the board redraw: the arrow finishes its turn, never snapping upright.
- [ ] A crewmate's cheer: the banner fades in; click it to send one back and it fades out. During a show, click anywhere or press Esc: the show fades away (a quarter second), not gone in one frame.
- [ ] On a card with a tip, press Show in the corner: the bubble grows to fit the words, which fade in; the chip beside Edit fades its words in too.
- [ ] Reduce motion (system setting): nothing slides, grows or turns; the banner only fades.

### 3.9.0: your Wrapped

- [ ] Tools › Due Crew › Your year…: the board's place shows Your 2026 on a phone-shaped card; it moves on every few seconds and waits while the pointer is on it; the right side or → goes on, the left or ← goes back. Each slide's Pip plays as it comes, in your look. ‹ Board goes back.
- [ ] The slides your year can fill, and no others: a year without Fifteens has no Fifteens slide; the comeback slide only if you were away a week or more; Night owl or Early bird only with 30 days or more. None of it says missed, fewer or behind.
- [ ] The card you turned around shows a real card's front as text; "Leave out the card you turned around" takes it off (and the link says Show it again). Make the picture opens Share's picture on that year, Pip hopping on it; Copy and Save work.
- [ ] Another year (2025, …) from the list beside it; All on one page lists every slide as text. Reduce motion: it never moves on by itself; the Pips are still.
- [ ] Set the date to 1 December (or wait): the board's line "Your 2026 so far is ready"; Open plays it; × puts it away, and it stays away on your other computer after a sync. 16 January: no line.

### 3.8.22: Pips on a plan card's squad line

- [ ] You › Plans, a plan whose squad you're in: "Squad: N of M showed up" starts with who showed up as Pips (yours in your look, a crewmate's in their colour and look, anyone else a plain green Pip), no emojis; no hat touches the line above. Click your Pip: the closet. Settings › Pip off: the emojis come back.
- [ ] Review a card a crewmate knows or asked about: the chip beside Edit (and the card in the bottom right corner, when it's free) starts with their Pip in their colour and look, no emoji, nothing touching the words. Night mode: their night colour.
- [ ] Squads › click someone who isn't in your crew: their card has a plain Pip where the emoji was. Settings › You: your Pip by your name; click it, the closet. Squad bingo: who stamped a square are Pips, bigger than the old emoji circles, none cut off at the square's edge. Tools › Due Crew › Friends: names, no emojis.
- [ ] duecrew.com: your Pip at the top of Account; Home's Since you were here: "added you back" and a crewmate's exam lead with their Pip.
- [ ] Settings › Pip off: every one of these is back to emojis (the Friends dialog stays names only).
- [ ] Halloween week (set the computer's date to 24 to 31 Oct, or wait): a line under the logo, "Halloween week · N days so far", the five things as little Pips (yours in colour), and what's next ("study today for the pumpkin"); the first board of the day, three bats fly across that line (not across the logo), and not again that day; Reduce motion: no bats. Every Pip on your crew's rows in a Halloween thing: a cobweb in the line's corner and "A spooky crew". × hides the line; it stays hidden till next year. 1 Nov: gone.
- [ ] A crewmate cheers you (have them send one, then Refresh): their Pip rises from the bottom of the board, tosses the emoji onto your row, which lights for a moment, and ducks back down; no flurry. Three or more at once: one after another, three at most, the banner "Dre, Mo, Ana and 1 more sent cheers". From someone who hasn't added you back: a plain Pip. Reduce motion: their Pips standing in the banner. Pip off: the flurry.
- [ ] Do a Fifteen, cheer someone, sit in a room with your crew: user_files' wrap.json has `closet.years.2026` counting them (and `worn` with what Pip had on today).

### 3.8.21: Pips on Squads

- [ ] Squads › a squad: each person's Pip where the emoji was; yours in your look (it opens the closet), a crewmate's in their colour and look, everyone else a plain green Pip. Settings › Pip off: the emojis come back.
- [ ] Squads › a plan's squad: the faces under Showed up today are Pips, and so is whoever asked a question. duecrew.com's Squads the same.
- [ ] A crew study room: the top bar's chip shows each person's Pip where the initials were (yours in your look, a crewmate's in theirs); with five or more, four and +N. On the review screen, the margin card beside a narrow card and the room's break show everyone's Pips, no hat touching the line above. Settings › Pip off: the initials come back. A Fifteen's chip is as before.

### 3.8.2: Pip's closet

- [ ] First refresh after updating: the board's line says the closet is open and how many things your days had earned already; See them opens it. Your crew's rows show each person's Pip where their emoji was, in their colour (yours in yours); Settings › Pip off brings the emojis back.
- [ ] The closet (Settings › Fifteen and Pip › Pip's closet, or Tools › Due Crew › Pip's closet, or click your Pip on your row or your card): your Pip big, in what it has on, and what's on place by place; ‹ Board goes back. The count says N of 64. Yours shows your things by place, each with what earned it; what's on is filled with a ✓ On.
- [ ] Put on a hat, then another hat: the second replaces the first. Glasses and a hat together: both on. Earmuffs and a scarf (winter) with a scarf on: the scarf comes off.
- [ ] A costume (the Dinosaur, say) over a look: only the costume shows; a second costume replaces the first; take the costume off (click it again, or its chip): the look you had comes back. Put a hat on while in a costume: the costume comes off.
- [ ] To earn: everything you haven't got, by how it's earned, greyed, with what it needs (and how far along); clicking does nothing, Pip never wears it. A secret says it's a secret and shows nothing. A place on Yours with nothing yet says what's next.
- [ ] Almost there (top of To earn): the next in a line you're at least halfway to, with a bar. A costume on: the things under it say Under, and the list on the left greys them.
- [ ] Something new (do your first Fifteen: the headphones): the board's line says New for your Pip: Headphones; Wear it puts them on and the line goes; × just goes; the closet marks it new.
- [ ] A held thing (the coffee mug): by the logo when Pip hops, the mug goes up with the hand; in a fifteen's chip (Pip holding its card) no mug.
- [ ] A crewmate on 3.8.2 puts something on: after your next refresh, their row's Pip wears it, and in a room together their seat does too. A crewmate on an older add-on: their Pip, plain.
- [ ] Another computer: what's earned and what's on follow you (Settings sync), nothing earned is lost if both earn at once.
- [ ] Night mode and Reduce motion: rows' Pips still (they move only when the row is pointed at), the closet's tiles still.
- [ ] Wear a hat: ▶ Fifteen? in the top bar wears it; on the crew rows no hat is cut off at the top, the name sits clear of Pip and on the numbers' line. Click a crewmate's Pip: their card, with their Pip where the emoji was; yours has Pip's closet · Change emoji.
- [ ] Share › week picture card: Pip hops across it in your look.
- [ ] Wear the mug (or any held thing) and start a Fifteen: in the top bar's chip Pip holds its card and the mug sits on the ground beside it, clear of the clock; on the break and after, it's back in Pip's hand. ▶ Fifteen? with a costume or a held thing: nothing touches the ▶.
- [ ] Everywhere it's named (Settings, the closet, cards, tooltips, the Tools menu, the site's privacy page) it says Pip, never Sev. Your Settings › Pip switch and break choice are as you left them.

### 3.8.1: the Fifteen and Pip

- [ ] Signed in, in no room: ▶ Fifteen? (with Pip) at the chip's end of the top bar, on the Decks screen, Overview and Review; Settings › Room chip Left moves it; Settings › Fifteen and Pip › Fifteen? off takes it away.
- [ ] Click it (from the Decks screen, Overview and Review: each must start one): the chip becomes Fifteen · 15 min left (Pip jumps, then heads down) and Study today opens. A crewmate's board shows you studying now, not a room (no Join).
- [ ] At 15 minutes, mid-card: nothing until you answer; then "That's fifteen." takes the next card's place, with how many cards; Space and the answer keys do nothing under it.
- [ ] Take five, then another fifteen: the break (Pip breathing along a square, four counts a side; Settings › On a break › Stretch gives a stretch), Start now starts the next at once; otherwise at five it ends and the card comes back.
- [ ] Another fifteen now: the card comes back and the chip says Fifteen 2 · 15 min left.
- [ ] On the Decks screen when a fifteen ends: the board asks the same question (Take five, Another now, Stop here); the chip says done, and its card answers too.
- [ ] Stop here (from the question, the break, the board or the chip's card): back on the Decks screen, "Your session: N fifteens · M m · C cards." with Pip stacking a square for each; × takes it away. Your crew stops seeing you studying at their next refresh.
- [ ] Walk away at the question: after five minutes it ends by itself, and the session's line is there.
- [ ] Eight fifteens: the eighth's question offers Stop here only.
- [ ] Close Anki in a fifteen: next open, no fifteen, and the session's line is there.
- [ ] Pip by the logo, only for a moment: Today done, back on the Decks screen it pops in, hops (the week's squares fly) and goes after a few seconds, not again that day; a cheer that lands: a gift and a blush, then gone; the night before your exam: a star; the first day back from away: a wave. Any other time the logo's alone. System Settings › Reduce motion: it shows still for those seconds, then goes.
- [ ] The nudge: with cards due, nothing studied, past your usual start (three days of history needed), the You box's Today says "Not started yet today. Fifteen?" with Pip peeking; Start starts one; × hides it for today; not on an away day.
- [ ] Settings › Pip off: no Pip anywhere (the chip, the question and the break show the logo's squares).
- [ ] A fifteen's card (click the chip): the logo's squares head it, as a room's; Pip sits at the end of the clock's row, heads down; it says "15 min left" (no "then your call"); at the question the chip says done.
- [ ] Welcome back (follow a plan, study nothing for 3+ days, open Anki): Pip waves, still, at the window's top left, in your accent (night mode too); the words and buttons as before. Settings › Pip off: the window without Pip.
- [ ] Share › As a picture › My week, with a day off this week: Pip stands on the last day studied, a dotted hop from each day studied to the next (a long one over the day off), Story and Link, Light and Dark; Copy picture and Save… have it too. My day: Pip on today's square once studied, no hops. Settings › Pip off: the card as before, no Pip.
- [ ] In a room with two crewmates who picked different accents: the Decks screen's lobby and the chip's card show each of you as a Pip in your own accent (yours is yours), blinking at different moments (still with Reduce motion), each named on hover; night mode, the night shades; Settings › Pip off: the initials again.
- [ ] Pip's moves (variety): finish Today on two days running: by the logo Pip does something different each day (a hop, a twirl, a little dance, a big jump), never the same twice in a row, restarting Anki between. In a fifteen of three rounds, the chip's Pip reads differently each round (nods, scratches its head, taps a foot); Settings › On a break › Stretch, each break a different stretch (shakes it out, marches, looks around); Breathe stays Breathe. The question: the clock rings, or Pip points at it, or jumps at it. The session's line, the nudge and a room's seats too (each seat its own small thing). Reduce motion: each shows still.
- [ ] Signed out (Sign out, Decks screen): Pip waves beside "Your friends' studying next to yours…" (words beside it at a narrow window, not under it), plays once, then rests; an expired sign-in shows no Pip. Settings › Pip off: the card as before.
- [ ] A crewmate passes a 100-day streak (or a year): the banner has Pip hopping in place of 💯, once, then it rests (not mid-hop, with Reduce motion too); Send 💯 and × as before. Settings › Pip off: the 💯.
