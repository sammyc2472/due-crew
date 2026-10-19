Course on a Mac (PoC). Change these in Tools › Course on a Mac (PoC) › Settings… rather than here.

- `runner`: `auto` (the built helper, else the `fm` command, else none), `helper`, `fm` or `none` (plain rules, no model).
- `timeout`: seconds a model call may take (the first call, while the model loads, gets at least 180).
- `prompt_chars`: the most a prompt holds; the Mac model's window is small (4,096 tokens in Apple's WWDC26 Q&A).
- `read_batch`: cards read in one call.
- `groups_max`, `tag_max_notes`: how many tags a lecture considers, and how big a tag may be to count as a lecture's.
- `part_max`, `found_max`: cards read from a part, and cards found by the search words outside the tags.
- `first_in_line`: opened cards go first in Anki's line of new cards.
- `day_first`: read 26/10 as 26 October.
- `verbose_log`: the log keeps the model's answers too (the log is in this add-on's user_files, on this computer).
- `fm_schema_flag`: try passing a JSON schema to `fm respond --schema` (off: its flags aren't settled yet).
