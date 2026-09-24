# Due Crew

Use **Tools → Due Crew** to change settings — it's the same keys with a real UI.
Raw keys, for reference:

| Key | Values | Meaning |
| --- | --- | --- |
| `show_leaderboard` | true/false | Board on the Decks screen |
| `period` | today / week / decks / squads | Default view |
| `sort` | reviews / time / retention / streak | Default sort |
| `show_stale` | true/false | Show yesterday for friends who haven't synced today |
| `sync_notifications` | true/false | Toasts about your crew: studied, streaks, returns, milestones |
| `theme` | auto / light / dark | auto follows Anki's night mode |
| `accent` | green / blue / purple / teal / amber / rose | Accent color, light and dark variants |
| `status` | text, up to 80 chars | One line under your name on Today, crew-only. Set it by clicking your own name |
| `away_from`, `away_to` | YYYY-MM-DD or empty | Away dates: ✈️ by your name, ✈️ squares in week shares |
| `compact`, `show_last_active`, `highlight_me` | true/false | Board display |
| `share_reviews`, `share_time`, `share_retention`, `share_streak` | true/false | What your crew and squads see |
| `share_heatmap` | true/false | Heatmap on your profile card |
| `emoji` | one emoji | Shown in front of your name; set from your own card |
| `sort` also takes `week` | | The squad board's 7-days column; the crew board reads it as reviews |
| `squads`, `squad` | list, id | Squads you've joined (with their invite codes) and the one shown; managed from the board |
| `crew_label` | text | The name your crew goes by in shares ("busm today") |
| `paused` | true/false | Crew sees "on a break" instead of numbers |
| `exam_date` | ISO date or empty | 📖 by your name for the two weeks before; empty = off |
| `shared_decks` | deck ids | Set from Tools → Due Crew → Shared decks |

Sign-in state (account, name, tokens) lives in `user_files/<profile>/`,
not here — restoring defaults never signs you out.
