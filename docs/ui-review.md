# UI review: the add-on and duecrew.com

September 2026. Two passes over every screen, both rendered from this repo
(`tools/site_preview.sh`, `tools/preview.py`, `tools/dialogs.py`) at desktop
and phone width:

1. **The designer.** Someone ruthless about conversion, who has studied
   Linear, Superhuman, Vercel, Raycast and Arc and can spot a vibe-coded
   project from across the room. They go through every visual decision.
2. **The first-time user.** Someone who clicks through from the landing
   page to a working crew (and from a teacher's plan link to a followed
   plan), noting every moment they got confused or wanted to leave.

Due Crew is free, so "start a free trial" here means reaching the moment it
pays off:

- **Crew:** the add-on installed, signed in, and one friend added back.
- **Plans:** a plan followed, and its first morning's cards opened.

Each item is tagged **[D]** (designer), **[U]** (first-time user) or both.
It says where the problem is and suggests a fix. These are proposals only.
Per CLAUDE.md, anything users see goes to a mockup and Sam's sign-off
first. Where the designer's instincts clash with the product's rules
(friendship, never competition; terse copy; no ranking anywhere new), the
rules win, and the item says so.

---

## Critical: people leave here

### C1. A plan link shows a signed-out visitor nothing about the plan [U][D]
**Where:** `duecrew.com/p/CODE` when signed out.
The page's title is "Follow this plan in Anki", followed by three install
steps. The plan's name, its author, its dates and how many people follow it
only appear after signing in. A classmate sent by a teacher is asked to
install software without being told what it's for. The calendar feed
(`/p/CODE.ics`) already serves every date to anyone holding the code, so
the page is hiding less than it looks.
**Fix:** show the same peek as signed in (name, whose plan, "5 dates,
Mon 7 Sep to Mon 12 Oct", number following, the one line), plus a compact
list of dates, above the steps. It comes from the same data the calendar
feed serves; squad plans stay hidden.

### C2. A visitor on a phone hits a dead end [U]
**Where:** the landing page and `/p/CODE`, on a phone.
Step 1 is "Open Anki on your computer". Most people clicking a link from a
group chat are on their phone. Nothing on the page lets them take it with
them, so they close the tab.
**Fix:** on narrow screens, add one line and one button: "It's for Anki on
a computer. **Email me the link**", which sends a plain-text email through
the existing sign-in mail path. A cheaper version is a "Copy link" button
and the line "Open this on your computer". For plans, "Add to calendar"
already works on a phone. Make it the phone's main action on `/p/CODE`, so
the visit still produces something.

### C3. The landing page never says what to do until the bottom [D]
**Where:** `duecrew.com`.
The only call to action, the install code and **Copy code**, comes after
the screenshot and five bullet points. On a phone it's two full screens
down. The hero is a logo, a heading, and a paragraph that repeats the
heading ("Your friends' studying next to yours" appears twice).
**Fix:**
- Put the install box directly under the heading: the code, **Copy code**,
  and "Tools › Add-ons › Get Add-ons, then restart Anki".
- Cut the paragraph to one line that says something the heading doesn't
  ("Free. Only people you add see it.").
- Move the bullets under the screenshot as three short features, each with
  a small render (cheers, study room, plans).
- Shrink the logo to about half its size. It's taller than the heading.

### C4. The add-on's first screen offers two buttons that do the same thing [U]
**Where:** the signed-out card on Anki's Decks screen ("Nothing is shared
until you join. **Join** · **Sign in**").
Since 3.0 both go to the same emailed-code screen. A new user stops to work
out which one applies to them, and an existing user wonders whether "Join"
will make a second account.
**Fix:** one action, **Start with your email**, and the same one-sentence
promise. The dialog already works out whether the account is new.

### C5. After the first sign-in, the board is empty and inviting is a small link [U][D]
**Where:** the board on day one ("Just you so far. Your code K7Q2ZP · Copy
invite · Add a code").
Due Crew only pays off once a second person is on the board. On the most
important screen of the first session, inviting someone is 11-px green text
in the footer, the same weight as "Share today" and "Open a room".
**Fix:** while the crew is empty, replace the table with a single card:
- Your row, then a large **Copy invite** button with the code, and
  "Paste their code" beside it.
- One line: "Your crew shows up here once they add you back."

Once the first friend is mutual, the normal board takes over. The welcome
dialog already does this well; the board should carry it on.

### C6. The phone builder's Save bar covers what you're working on [U]
**Where:** `/plans/{id}` at phone width (see the `builder-m` render).
The sticky Save bar sits on top of the "Mon 21 Sep is heavy" note and the
first day of the calendar. The panel above the calendar takes the whole
first screen, so on a phone the calendar starts below the fold and behind
the bar.
**Fix:**
- On narrow screens, make the Save bar a slim floating button that shows
  only while there are unsaved changes, and pad the bottom of the page by
  its height.
- Fold the pace settings to one summary line ("Finish by Sun 1 Nov · 20 a
  day ▾") that opens on tap.

---

## High impact: they stay, but it costs them

### H1. The website mostly tells you to go back to Anki [U]
**Where:**
- the Plans list ("To make one: in Anki, Tools › Due Crew › Make a
  plan…"; "To follow one: in Anki…")
- home ("add your crew in Anki: Tools › Due Crew › Friends")
- the Friends box, and the cheers panel ("They play in Anki too")

A signed-in visitor tries three things and gets three sets of Anki menu
paths. The site feels like a read-only mirror.
**Fix:** do on the site what can be done there, on the existing API:
- **Friends:** add by code and add back (`POST /codes/{code}/add`,
  `PUT /friends/{uid}`).
- **Plans:** follow a plan (`POST /plans/follow`). The morning then happens
  in Anki on its own.
- **Your code:** show it with a copyable invite.

Keep "In Anki: …" only for what really needs Anki: making a plan from a
deck, and sharing decks.

### H2. "Fill the calendar" is greyed out and never says why [U]
**Where:** the builder, before anything is ticked in the "What to cover"
panel on the left.
Both fill buttons show disabled, with no tooltip or hint. A first-time
author presses them, nothing happens, and they leave.
**Fix:** keep the buttons enabled. With nothing ticked, the note line reads
"Tick what to cover on the left first", and the tree briefly flashes.
Alternatively, while nothing is ticked, show one grey line in their place:
"Tick chapters on the left, then fill the calendar."

### H3. On a phone, "What to cover" looks like a heading, not a button [U][D]
**Where:** the builder at phone width.
The collapsed panel shows the words "What to cover" with no arrow and no
box. Without it there is nothing to lay out, and it's the first thing an
author needs.
**Fix:** style it as a full-width button with a count ("What to cover ·
nothing ticked ▸"), and open it the first time when the plan has no dates.

### H4. The two sides don't look like one product [D]
**Where:** everywhere the add-on's dialogs and the site meet.
- **Qt dialogs use Title Case buttons:** "Look Up", "Add Back", "Copy
  Invite", "Join a Squad…", "Reset Board", "Delete Account…", "Sign Out".
- **The site and the board use sentence case:** "Copy link", "Add to
  calendar", "Send code".
- **The Friends dialog's "Ignore"** is plain text, so it reads as a label,
  not a button.
- **"New Code" sits right next to "Copy"**, although it makes your old code
  stop working.

**Fix:**
- Sentence case everywhere.
- Make Ignore a real (quiet) button.
- Move New code under a small "…" menu with a confirmation. It already
  says the old code stops working, but only after the click.

### H5. The board's footer is a row of small links of equal weight [D]
**Where:** the board footer: "1 waiting · Friends · Share today · Open a
room · I'm studying … Updated just now · Refresh · Settings".
There are eight to nine green 11-px links and no hierarchy. The two social
actions that matter day to day (Open a room, I'm studying) look the same as
Settings.
**Fix:**
- Put the main social action in a single pill button: **I'm studying**,
  becoming **Stop** while on.
- Move Friends and Share into one "Crew ▾" menu.
- Keep Refresh and Settings as quiet grey icons on the right.
- Make "1 waiting" a pill that opens Friends.

### H6. Banners stack up above the table [D]
**Where:** the board, "today" state: "Marisa's exam is tomorrow" and "Last
week, together …" stack before any rows.
On a normal Anki window the crew table starts halfway down, below the deck
list.
**Fix:**
- Show at most one banner at a time, the most time-sensitive first (exam
  eve, then the week's wrap). Queue the rest.
- Or fold them into one line that cycles.

### H7. The medals and "#4" read as a competition [D, conflicts with product rules]
**Where:** the board and the site's home ("🥇 🥈 🥉 #4 #5").
The designer's instinct is to lean into this. The product rule ("crew",
never competition) says to go the other way. Show-up mode proves the product
works without ranks.
**Fix (for Sam to decide):**
- Keep sorting, drop the medals and "#n".
- Give a small highlight to whoever studied most today ("🔥 top day") only
  when the crew has three or more people.

"No ranking anywhere new" means this is a question about taking something
away, not adding one.

### H8. Settings › You is mostly empty space [D]
**Where:** the Settings dialog's You tab (see the `settings-0-you` render).
There are large blank bands between the status line and the email line, and
between "Your crew" and its buttons. It looks unfinished.
**Fix:**
- Put the profile in one block: emoji, name, status, then Name… / Emoji… /
  Status….
- Show the account line in small grey text under it.
- Put the crew buttons in a row with no heading.
- Keep Sign out and Delete account at the bottom, as now.

### H9. The home page doesn't tell you what to do today [U]
**Where:** `/home`.
It's a faithful copy of the board, but the first thing a returning visitor
wants is "what's on for me today". The plan panel on the right says "32
behind" in 11-px orange text with no next step.
**Fix:**
- Put one line at the top: "Today: 42 new from *Boards sprint* · 311
  reviews due", with a link to the plan.
- Give the behind state a verb: "32 behind · catch up over 3 days". Those
  choices already exist in Anki's missed-days question.

### H10. The Plans list repeats itself and has no "New plan" [U][D]
**Where:** `/plans`.
Rows read "Step 1 · 5 dates · Step 1": the name repeats when it matches the
deck. There's no New plan button, only a sentence at the bottom about Anki.
Row cards are almost all empty space, with "3 following" floating top
right.
**Fix:**
- Rows as: **Name**, then "Step 1 deck · 5 dates · Mon 7 Sep–Mon 12 Oct",
  then "3 following" on the right, vertically centred.
- Leave the deck out when it matches the name.
- Add a **New plan** button that explains the single Anki step: "Pick the
  deck in Anki: Tools › Due Crew › Make a plan".

---

## Nice to have: polish

### N1. The landing screenshot can't be read on a phone [D]
The board image shrinks to 11-px text at 390 px. **Fix:** on phones, show a
crop of three rows plus a cheer, at readable size. Add a dark-mode version
(`prefers-color-scheme` via `<picture>`), since the logo already has one.

### N2. The landing page has no proof it's real [D]
There's no count, no names, and no "used by". The designer would add social
proof. Within the product's rules, the honest version is quiet: "Free, open
source, and on AnkiWeb" with the AnkiWeb rating, or "N people studying with
their crew this week" from `/admin/stats`, if Sam wants it public.

### N3. The sign-in page gives no context [D]
It's a lone form on a blank page, with no reason to sign in. **Fix:** one
grey line under the form: "Your crew, your plans and your log, from any
browser."

### N4. The site's nav is crowded on a phone [D]
Logo plus five links fill 390 px, and the account shows as a bare first
name ("Dre"). **Fix:** on phones, keep Home and Plans, and put Log, Admin
and the account under the avatar or name.

### N5. The log's charts leave half the width empty [D]
On desktop the weekly bars and the plan chart stop at 560 px inside a
1,020-px column. **Fix:** let them fill the width, up to about 900 px, or
put the two charts side by side.

### N6. The "As text" tab is a wall of monospace [D]
The format example, the textarea and the ghost **Read it** button all look
alike. **Fix:**
- Make Read it the primary button once the text has changed.
- Put the format example under a small "Format ▸" disclosure. The AI box
  above it already explains it.

### N7. Some builder words need a second read [U]
- "What to cover" / "ticked".
- "Day by day · as you place it": how does it differ from the calendar
  itself?
- "the rest".
- "Search" chips named just "Search".

**Fix:**
- "Day by day" → "I'll place each day".
- Name a search chip by its first tag ("Search: Cardio…").
- Keep the rest; they are learnable in one use.

### N8. "Cheers · They play in Anki too." is cryptic [U]
**Fix:** "They'll rain on your Anki screen next time you open it."

### N9. "matches igk" in the Shared decks dialog [U]
**Fix:** "you and igk both study it".

### N10. Stale dialog render in the shots folder [D, housekeeping]
`auth-join.png` in an old local shots folder still shows the 2.x password
form. `tools/dialogs.py` no longer makes it, so nothing ships with it. Clear
out old output folders before comparing renders.

### N11. The study-room dialog's time field [D]
"Starts ● Now ○ At [19:00]": the greyed-out time field reads as broken
until "At" is picked. **Fix:** hide the field until "At" is chosen.

---

## What's already right (keep it)

- **Sign-in:** the emailed code with no password, and "We'll email you a
  code. No password."
- **The welcome dialog:** invite, add a code, join a squad, and the privacy
  sentence, all on one screen.
- **The follow dialog:** it says exactly what matches your copy ("10 cards
  found … Missing ones are skipped").
- **The plan card on the Plans tab:** three numbers, one status line, one
  bar per date. It's the cleanest screen in the product.
- **The log:** tiles, one chart, "Only you see this."
- **Privacy wording and escaping:** consistent everywhere.
- **The logo:** a real brand mark used consistently, not a generic icon.
