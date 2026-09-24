# Due Crew logo: Seven days

<picture><source media="(prefers-color-scheme: dark)" srcset="svg/due-crew-logo-dark.svg"><img alt="due-crew-logo" src="svg/due-crew-logo.svg" width="320"></picture>

The wordmark over one week of day squares, Monday to Sunday, with Thursday
off: 🟩🟩🟩⬜🟩🟩🟩. It's the README's own example week. The squares are the
board's own (`#due-crew .sq` in `due_crew/board.py`). A day off is fine, and
nobody gets ranked.

The name in running text stays "Due Crew". Only the mark is lowercase.

## Stacked (primary)

<picture><source media="(prefers-color-scheme: dark)" srcset="svg/due-crew-logo-dark.svg"><img alt="due-crew-logo" src="svg/due-crew-logo.svg" width="400"></picture>

## One line

For short spaces: headers, bars, footers.

<picture><source media="(prefers-color-scheme: dark)" srcset="svg/due-crew-logo-line-dark.svg"><img alt="due-crew-logo-line" src="svg/due-crew-logo-line.svg" width="455"></picture>

## Icon: the week, wrapped

Four over three, for avatars and favicons. Shown at 128, 64 and 32 px wide.

<picture><source media="(prefers-color-scheme: dark)" srcset="svg/due-crew-icon-dark.svg"><img alt="due-crew-icon" src="svg/due-crew-icon.svg" width="128"></picture> &nbsp; <picture><source media="(prefers-color-scheme: dark)" srcset="svg/due-crew-icon-dark.svg"><img alt="due-crew-icon" src="svg/due-crew-icon.svg" width="64"></picture> &nbsp; <picture><source media="(prefers-color-scheme: dark)" srcset="svg/due-crew-icon-dark.svg"><img alt="due-crew-icon" src="svg/due-crew-icon.svg" width="32"></picture>

Square avatar (512 px, background included): `svg/due-crew-avatar.svg`
and `svg/due-crew-avatar-dark.svg`.

## In the chat

The week share is already the logo, in text. Leave shares as they are: no
images and no ASCII art. The footer stays as it is.

```
This week · Sep 14–20
🟩🟩🟩⬜🟩🟩🟩 6 of 7 days
3,412 reviews · 8h 02m · 🔥 17
— Due Crew · Anki add-on 2035408484
```

## README

The stacked logo at 220 px wide replaces the `# Due Crew` line, directly
above the tagline. It switches with the viewer's light or dark mode. The
AnkiWeb listing starts at the tagline and shows its own title, so the
logo stays GitHub-only.

## Colours

All from `due_crew/board.py`. Green here and on GitHub, where nobody's
accent is known. Inside the add-on (`due_crew/logo.py`) the studied days
take the accent the user picked in Settings, in the same light or dark
shade the board uses; the day off and the wordmark stay as below.

| | light | dark | from |
|---|---|---|---|
| studied day | `#2e7d32` | `#7cc47f` | `ACCENTS["green"]` |
| day off | `#e2e2da` | `#3d403b` | `LIGHT` / `DARK` `line` |
| wordmark | `#242424` | `#e6e8e3` | near `ink` |
| background | `#ffffff` | `#1c1c1c` | the board card |

## Construction

- Wordmark: Outfit SemiBold, tracking −0.012 em, converted to outlines.
  No font is needed to use the files.
- Squares: corner radius 18% of a side, gap 50% of a side (the board draws
  12 px squares 18 px apart with a 2 px radius).
- Stacked: the row of squares spans exactly the wordmark's width. Their
  tops sit 0.20 em below the baseline.
- One line: each square is one x-height tall and sits on the baseline.
  The wordmark follows after a 0.26 em gap.
- Icon: four squares over three, gap 30% of a side.

## Alternate: today

The same set with the last square pale instead: today, still due. It's
not in use; it lives in `svg/today/` and `png/today/`.

<picture><source media="(prefers-color-scheme: dark)" srcset="svg/today/due-crew-logo-dark.svg"><img alt="due-crew-logo" src="svg/today/due-crew-logo.svg" width="400"></picture>

## Rules

- Don't redraw, re-typeset or recolour it, and don't move the pale square.
- No shadows, outlines or gradients, and no backgrounds except the two
  above.
- Keep one square's width clear on every side.
- Smallest sizes: stacked 120 px wide, one line 160 px, icon 16 px.

## Files

| | light | dark |
|---|---|---|
| stacked | `svg/due-crew-logo.svg` | `svg/due-crew-logo-dark.svg` |
| one line | `svg/due-crew-logo-line.svg` | `svg/due-crew-logo-line-dark.svg` |
| icon | `svg/due-crew-icon.svg` | `svg/due-crew-icon-dark.svg` |
| avatar | `svg/due-crew-avatar.svg` | `svg/due-crew-avatar-dark.svg` |

PNG exports are in `png/`, with the width in each file name: stacked 400
and 800, one line 455 and 910, icon 32, 64, 128 and 256, avatar 512. The
alternate set is in `svg/today/` and `png/today/`, with the same names.
