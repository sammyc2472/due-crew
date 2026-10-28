# Due Crew

Use **Tools → Due Crew → Settings…** to change settings (the board's own, on the Decks screen): the same keys with a real UI.
Raw keys, for reference:

| Key | Values | Meaning |
| --- | --- | --- |
| `show_leaderboard` | true/false | Board on the Decks screen |
| `period` | today / week / decks / squads | The board's view: Crew's Today, Week or Decks, or Squads |
| `sort` | reviews / time / retention / streak | Default sort |
| `show_stale` | true/false | Show yesterday for friends who haven't synced today |
| `sync_notifications` | true/false | Toasts about your crew: studied, streaks, returns, milestones |
| `theme` | auto / light / dark | auto follows Anki's night mode |
| `accent` | green / blue / purple / teal / amber / rose | Accent color, light and dark variants |
| `status` | text, up to 80 chars | One line under your name on Today, crew-only. Set it by clicking your own name |
| `away_from`, `away_to` | YYYY-MM-DD or empty | Away dates: ✈️ by your name, ✈️ squares in week shares |
| `compact`, `highlight_me` | true/false | Board display |
| `share_reviews`, `share_time`, `share_retention`, `share_streak` | true/false | What your crew and squads see |
| `share_heatmap` | true/false | Heatmap on your profile card |
| `emoji` | one emoji | Shown in front of your name; set from your own card |
| `sort` also takes `week` | | The squad board's 7-days column; the crew board reads it as reviews |
| `squads`, `squad` | list, id | Squads you've joined (with their invite codes) and the one shown; managed from the board |
| `crew_label` | text | The name your crew goes by in shares ("busm today") |
| `paused` | true/false | Crew sees "on a break" instead of numbers |
| `exam_date` | ISO date or empty | 📖 by your name for the two weeks before; empty = off |
| `shared_decks` | deck ids | Set from Tools → Due Crew → Shared decks |
| `room_chip_side` | right / left | Which end of Anki's top bar the study-room chip sits at |
| `hidden_tabs` | list of decks / squads / plans / insights | What this computer doesn't show (Settings › Shows); Crew always shows |
| `due_tab` | today / upcoming / later / plans / insights / party | The tab open in the box above the board |
| `party_pick` | a Pip Party source | What You › Pip Party plays from on this computer: this week's misses, a plan's week, a saved scope |
| `plan_pick` | plan id | The plan You › Plans shows when you follow two or more; picked by its name at the top |
| `due_show` | true/false | Today, Upcoming and Later in that box (Plans and Insights stay) |
| `shortcuts` | true/false | Ctrl+Shift+S (study what's next) and Ctrl+Shift+Q (ask the squad about this card), on this computer |
| `fifteen` | true/false | ▶ Fifteen? in the top bar, and the nudge when you haven't started by your usual time, on this computer |
| `sev` | true/false | Pip, the square from the logo: beside it on the board and in your fifteens, on this computer |
| `sev_break` | breathe / stretch | A fifteen's break: breathe along with Pip, four counts a side, or stretch |
| `room_sound` | off / brown / rain / fire / waves | The sound under a fifteen or a study room, picked from the speaker on its chip; made in Anki, never sent, on this computer |
| `room_sound_vol` | 0 to 100 | Its volume |
| `ins_deck` | deck id | The deck Insights shows on this computer |
| `muted` | user ids | Crewmates whose cheers and knocks you don't get; right-click their name on the board |

Sign-in state (account, name, tokens) lives in `user_files/<profile>/`,
not here — restoring defaults never signs you out. So do the plans you
follow on this profile (`plans.json`: the deck each runs on and which
dates have opened).
