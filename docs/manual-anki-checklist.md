# Manual Anki checklist (v1.10)

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

## Sharing and the server board
- [ ] Settings → Privacy → "Share on the server board" on; sync; the Server pill shows your row.
- [ ] If the board asks for the crew code (installs that joined before v1.6), enter it once; the board loads.
- [ ] A second account on a **different** crew (different name + code, same project) cannot see your row; the board it sees is its own.
- [ ] Turn sharing off; sync; your row disappears for others (retracted), and the pill shows the opt-in text for you.
- [ ] Pause sharing; same result. Un-pause; row returns after a sync.
- [ ] Old add-on versions on the same server: their server board shows an error / "rules need an update" until they update — expected.

## Friend requests (knocks)
- [ ] From the Server view, click a stranger's name → card → Add to crew. They see "wants to be crew — Add back" in Friends after their next sync.
- [ ] Add back on their side → both boards show each other as crew.
- [ ] A user on a different crew cannot knock you (verify with the rules test; not reproducible by hand without a second crew).
- [ ] Ignore hides that person's future knocks locally.

## Clipboard output
- [ ] Your card → "Copy for the chat: today" → paste into Messages/WhatsApp/Notes: emoji and block glyphs intact (no `?`, no `∑`).
- [ ] Same for "tape" and for the Today view's "Share today".
- [ ] The crew tape lists only people who studied today; friends who don't share study time appear as "N not sharing hours", never as empty rows; totals say "(partial)" when someone hides their count.
- [ ] Friends' rows sit on your clock: a friend in another time zone lands at the real hour on your day.

## Rules deployment (founders)
- [ ] After pasting the new rules: the footer notice "Server rules need an update" clears within a day (or on Refresh) for v1.10 clients.
