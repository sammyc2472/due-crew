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

## Sharing and the Everyone board
- [ ] Settings → Privacy → "Share on the Everyone board" on; sync; the Everyone pill shows the top rows, the "N studying today · M reviews together" headline, and your rank line when you're outside the top 50.
- [ ] A second account that is NOT sharing cannot see the board (opt-in text) and cannot be knocked.
- [ ] Turn sharing off; sync; your row disappears for others (retracted), and the pill shows the opt-in text for you.
- [ ] Pause sharing; same result. Un-pause; row returns after a sync.
- [ ] An install upgraded from v1.x with a leftover server.json: the file is removed silently (default project) or you're asked to sign in again (custom project).
- [ ] Old add-on versions: their Server view errors until they update — expected. Their friends/cheers/decks keep working.

## Friend requests (knocks)
- [ ] From the Server view, click a stranger's name → card → Add to crew. They see "wants to be crew — Add back" in Friends after their next sync.
- [ ] Add back on their side → both boards show each other as crew.
- [ ] A user who isn't sharing cannot knock you (rules test covers it).
- [ ] Ignore hides that person's future knocks locally.

## Clipboard output
- [ ] Your card → "Copy for the chat: today" → paste into Messages/WhatsApp/Notes: emoji and block glyphs intact (no `?`, no `∑`).
- [ ] Same for "tape" and for the Today view's "Share today".
- [ ] The crew tape lists only people who studied today; friends who don't share study time appear as "N not sharing hours", never as empty rows; totals say "(partial)" when someone hides their count.
- [ ] Friends' rows sit on your clock: a friend in another time zone lands at the real hour on your day.

## Rules deployment (maintainer)
- [ ] Rules published in the console BEFORE the add-on release; after it, no v2.0 client shows "server catching up" in the footer.
- [ ] Console: delete the retired `server_board`, `server_names`, and `servers` collections once v1.x clients are gone.
- [ ] Firebase budget alert is set.
