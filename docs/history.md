# Due Crew: how it got here

Every feature's notes, by version, moved out of `CLAUDE.md` (which keeps the
map and the rules). Each entry says what was built, where it lives, and why
it is the way it is; the mocks it names are on the design-spec artifact.
Read a feature's entry before changing it (search for its module, its
command or its mock's name), and add a bullet here, in the same voice, with
every release that changes how something works.

Since 3.9.12 it's a folder, oldest first, so a feature's entry is found without reading the rest:
`grep -rn "<its module, command or mock>" docs/history/`.

- [`history/the-model-to-3.7.md`](history/the-model-to-3.7.md): the data model, and 2.x to 3.7, 58 entries
- [`history/3.8.md`](history/3.8.md): 3.8.0 to 3.8.22, 10 entries
- [`history/3.9.0-3.9.5.md`](history/3.9.0-3.9.5.md): 3.9.0 to 3.9.5, 103 entries
- [`history/3.9.6-3.9.9.md`](history/3.9.6-3.9.9.md): 3.9.6 to 3.9.9, 28 entries
- [`history/3.9.10-3.9.12.md`](history/3.9.10-3.9.12.md): 3.9.10 to 3.9.12 (the newest; a new bullet goes at its end), 52 entries
