# Due Crew

Use **Tools → Due Crew** to change settings — it's the same keys with a real UI.
Raw keys, for reference:

| Key | Values | Meaning |
| --- | --- | --- |
| `show_leaderboard` | true/false | Board on the Decks screen |
| `period` | today / week / decks | Default view |
| `sort` | reviews / time / retention / streak | Default sort |
| `show_stale` | true/false | Show yesterday for friends who haven't synced today |
| `sync_notifications` | true/false | Toast when a friend syncs |
| `theme` | auto / light / dark | auto follows Anki's night mode |
| `compact`, `show_last_active`, `highlight_me` | true/false | Board display |
| `share_reviews`, `share_time`, `share_retention`, `share_streak` | true/false | What your crew sees |
| `share_heatmap` | true/false | Heatmap on your profile card |
| `paused` | true/false | Crew sees "on a break" instead of numbers |
| `shared_decks` | deck ids | Set from Tools → Due Crew → Shared decks |

Sign-in state (account, name, tokens) lives in `user_files/<profile>/`,
not here — restoring defaults never signs you out.
