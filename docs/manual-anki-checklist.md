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
- [ ] Settings → Board → Room chip: Left. Open a room: the chip sits at the left end of the top bar (Decks screen and while reviewing); with AMBOSS installed, the two chips don't overlap. Right puts it back. Reset Board puts it back on the right. A second computer keeps its own choice.

## 3.1: plans

Against the dev Worker and a dev site first (`api_base`, and `site_base`
for the builder's link), as for 3.0. Two accounts: Dre (author) and Maya
(follower), in one squad.

- [ ] Tools → Due Crew is a submenu: Friends…, Squads…, Make a plan from a deck…, Follow a plan…, Settings…. Each opens what it says.
- [ ] Dre: Make a plan from a deck… → pick a deck: "Sends N tag names and M subdeck names, with how many cards each has. No card text." Tags only / Subdecks only change the numbers. Open the builder: the browser opens duecrew.com/plans/new signed in as Dre, with that deck's tree. The link works once: reload it after five minutes and it asks for a sign-in.
- [ ] Dre builds three dates (one opening today, one yesterday, one next week), publishes, offers it to the squad.
- [ ] Dre: Browse → select three cards (one of them c2 of a cloze) → right-click → Due Crew: add to a plan… → the plan, "With <date>" → Add. The site shows 3 single cards on that date. Again with "On its own date": a new date appears.
- [ ] Maya: the Decks and Squads tabs show "Dre offered <squad> a plan: <name>" with Look and ×. Look opens Follow a plan with the code filled in; × hides it for good.
- [ ] Maya: Follow a plan… → paste the link (duecrew.com/p/CODE): the title, "Run it on" with the matching deck and "best match of your decks", the list of dates with what's found ("not in your copy" in orange for a missing one), "N cards found in your copy", "2 units have already opened (N cards)", Share my progress checked. Follow with Open them now: a toast "Due Crew opened 2 dates: N cards"; Edit → Undo says "Undo Due Crew: open 2 dates", and undoes all of them at once.
- [ ] A copy whose tags start differently (rename the top tag in Maya's collection first): "Your tags start differently … Use X::". Use it: the dates match.
- [ ] Follow again on a fresh profile with Start from the next unit: nothing opens now; the next date opens on its morning.
- [ ] The Decks tab: "<name> · Dre's plan", "week X of Y · N following", a row per opened date (You: seen, Crew: done, "N of M"), the next date's "opens …", "✓ Opened … this morning: N cards" with Undo. Review a card: Undo goes (Anki has a newer step).
- [ ] The next morning (change the computer's date, or wait): after Anki's sync on open, the day's date opens with the toast, once. A profile that doesn't sync: at the first refresh. Offline with sync on: three minutes after opening.
- [ ] Dre moves a date later and one earlier, adds a date: Maya's card says "Dre moved … and added …" with OK. Nothing that was open closes. The date moved earlier opens the next morning, not before.
- [ ] Plan ▾ → Open everything now: every date opens, one undo step. Change deck…: pick another deck; its cards for the opened dates open. Pause: no mornings; the card says paused. Resume: asks "N units opened while paused" with Open them now / Start from the next unit.
- [ ] Plan ▾ → Stop following: "Stop following <name>? Nothing gets suspended…", Stop. The card goes; every open card stays open; Dre's progress page stops counting Maya.
- [ ] Share my progress off (follow with it unchecked): Dre's progress page doesn't count Maya; the Crew: done bars on other followers' cards don't include her.
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
- [ ] Plan ▾ → Change deck… on a plan named with <b>markup</b>: the question shows the name as text.
- [ ] Signed out, AnkiWeb sync done at open, then sign in: the plans' morning runs with the sign-in's refresh, not three minutes later.
- [ ] Close Anki with a sync on close on a new day before the morning ran: no plan cards open during the close.

## 3.2: plans as training, who knows this one, the site's home

Two accounts again, Dre (author) and Maya (follower), mutual friends, a
deck both share (Settings › Shared decks).

- [ ] Dre, on the site: Settings has Ends, Catch-up weeks and Taper (no exam target). Dates has a Checkpoint per date and the weeks strip (build, catch-up light, taper grey, a checkpoint ringed). A date opening in a catch-up week gets the orange note. Save; a taper without an end date is refused with a plain message.
- [ ] Maya: Follow a plan… → Follow: My schedule opens right after. Days: click S twice (×2, then rest), minutes, a later start. The chart shows reviews a day by week, amber over my time, "your 60 min ≈ N"; the sentence says what to do. Save: today's share opens (a toast), not the whole date. Cancel instead: dates open whole, as in 3.1.
- [ ] The plan card: three tiles (new today N / M, reviews due, ~minutes left), "On track." and Study now (opens the deck's review). A rest day says "rest day: no new"; a catch-up week and the taper say so.
- [ ] Skip two study days (change the date): the card says "You missed Tue and Wed: N new cards waiting" with Spread them (+N a day), Push my dates back 2 days, Leave them open. Push: one request, a tooltip; the plan's dates on the site don't move for Dre. Spread: the target grows by a quarter a day. Either way the question doesn't come back for those days.
- [ ] Plan ▾ → My schedule…: the same dialog with No schedule; No schedule takes it off.
- [ ] A checkpoint's morning: "Due Crew built Checkpoint · <date>", a filtered deck of that date's cards with most lapses first. Study it: the card says "N done", then "Checkpoint … done: X of N right first time".
- [ ] The Monday of plan week 2: "Week 1 done: X of Y sessions, N new cards, on track." Dre's board shows "· week 1 done" beside Maya's name that day.
- [ ] Who knows this one: Maya presses Again on a card Dre has mature in the shared deck, then syncs. On its answer side, beside Edit: "🐙 Dre knows this · Ask". Ask → a line → the flag goes up. Dre's Decks tab: "Maya asks about a card you know: "…"" first, with Tip; the same card in Dre's reviewer shows "Maya asked about this · Tip". Dre tips: Maya's flag comes down; next time the card's answer shows "💡 Dre's tip"; click: the tip and This helped. Nothing is ever drawn inside the card.
- [ ] A card with no one who knows it and no tip: no chip. A card on the question side: no chip.
- [ ] The site, signed in: duecrew.com goes to Home (this week, today, cheers waiting, plans with on track or N behind, the crew with Cheer, Squads). A cheer shown there still plays in Anki. Log: tiles, 12 weeks by minutes/reviews/new/retention, each plan's line against my schedule. /admin: Sam only; anyone else gets Not found.
- [ ] `wrangler tail`: still one GET /board and one POST /sync per refresh and sync; My schedule and This helped are one request each, on a click.

### 3.2.1: the admin's notice

- [ ] Signed in on duecrew.com as sammy: the nav has Admin. Anyone else: no Admin, and /admin says Not found.
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

### 3.3: following, the Plans tab, together

- [ ] Follow a plan: nothing asks for a schedule; the board switches to a new Plans tab with the card (today's tiles, one status line, one bar a date). Decks has no plan card. Stop following everything: the tab goes.
- [ ] Make a plan from an AnKing deck: the builder's tree reaches tags five levels down (#Bootcamp › Cardiology › 2 · Anatomy › 4 · Penetrating…).
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
- [ ] C2: Plan ▾ › Open early › 2 days: the next two days' cards open now; the card says "(2 days early)".
- [ ] C3: in the browser, search `tag:*Cardio* -tag:*Pharm*`, Due Crew: add to a plan › This search: the date shows the search with its count on the site; a follower's morning opens those cards. Paste a search on a day on the site: the same.
- [ ] C4: Study on a date's row opens "Due Crew · <date>". A review day on the site: that morning, "Review · A – B" (200 most-missed).
- [ ] C5: rename a tag in a follower's copy (like a new AnKing): the date still opens its cards, and the card says the tags differ, with OK.

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
- [ ] G3: Plan ▾ › Skip a date: its row is crossed out with Undo skip; it never opens. Undo skip: it opens if its day has come.
- [ ] G4: Plan ▾ › Pause until… (your Away dates fill it in if set). The day after, "Welcome back": move my dates later, or open what I missed. Plan ▾ › Push my dates back… sets the days by hand; the card says "your dates +N days".
- [ ] G5: fall behind a day: "N new cards from earlier dates waiting · Catch up…": over 3 days, Anki's new count for the deck goes up today only; Stop puts it back.
- [ ] G6: on the site, the follower's plan page shows "you: 20 of 34", "you: skipped".

### 3.5: previews, the library, classes (site only)

- [ ] A: paste a plan's link (duecrew.com/p/CODE) into iMessage or Slack: the plan's name, one line and its picture show. A squad's plan shows the plain Due Crew card.
- [ ] B: a plan's Settings › Library › List it in the library; it shows at /library. Filter by its deck and length; search a word in its name.
- [ ] B: signed in as someone else: Look opens its calendar; Follow follows it (the add-on's next morning opens today's date); Copy › a Monday › it opens as your plan, "based on …".
- [ ] B: Report on someone's card sends a mail to REPORT_TO. As sammy, Take out: the author's Settings says why and the switch is gone.
- [ ] C1: duecrew.com/classes reads right on a phone and a computer; the landing links to it.
- [ ] C2: with 3+ followers sharing and most behind on a past date, Progress says so; Give the class a day moves the later dates (Save to keep).
- [ ] C3: Share › A poster for the class › Print: one page, the QR code scans to the plan's link.

### 3.5: home, log, admin (site)

- [ ] Home: the strip says what opens today, what's waiting, the next event, and today so far; the year shows under the board; "Since you were here" lists crew added back, notes and plan changes (a second visit shows only what's new).
- [ ] Home: a crewmate with an exam in the next two weeks: Send good luck › a line › Send. On their exam morning, their Anki shows it with the others.
- [ ] Log: tiles, the year, this week and last, 30 days by date, a plan's history line (after a few days of syncs); Export CSV downloads.
- [ ] Admin (sammy): tiles with lines (only accounts has a line the first day), sign-in codes, the cutover, the bridge's last run, notices with Take down and Post again.

### 3.5.0: asking about a card (K1–K3)

- [ ] Right-click a card while reviewing (or More): "Due Crew: ask my crew about this…". The box names who has it down, if anyone; OK with or without a line. Right-click again: "take back my ask".
- [ ] A crewmate's Decks tab: "Asked of you" with your line, the card from their own copy, and Tip. Your own Decks tab: "Your asks", waiting, and who has it down.
- [ ] After their tip: your Decks tab shows "answered · 1 tip". When the card comes up, the answer side shows "💡 Name: the tip" beside Edit, cut short with the whole tip on hover; This helped turns to ✓ Helped without opening anything; clicking the tip opens all tips.
- [ ] Night mode and light mode: the chip and the new headings read clearly.

### 3.5.0: the Plans tab, and codes anywhere

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
