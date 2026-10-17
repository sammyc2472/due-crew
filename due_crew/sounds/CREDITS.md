# Room sounds

Rain, fire and waves are recordings, each dedicated to the public domain by
its maker under CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/).
These files stay CC0: the add-on's MIT License doesn't cover them. Brown
noise has no file: `sounds.js` makes it.

Each is a seamless loop cut from the recording's high-quality preview on
Freesound by `tools/cut_sound.sh`: the seconds after the loop's end crossfade
(equal power) into its first seconds, then it's levelled to -23.3 LUFS (the
made brown noise's level), limited to -1 dBFS and encoded as Ogg Opus,
80 kbps, 48 kHz stereo. Licences checked on each sound's page, 17 Oct 2026.

| File | Recording | By | Cut |
|---|---|---|---|
| `rain.ogg` | "Rain Slowly Passing TREATED LOOP_Edgewater_06192020.wav", https://freesound.org/s/525046/ | speakwithanimals | 60 s from 0:36, 3 s crossfade |
| `fire.ogg` | "Fireplace.wav", https://freesound.org/s/132534/ | inchadney | 60 s from 2:49, 1.5 s crossfade |
| `waves.ogg` | "Waves at Baltic Sea shore.wav", https://freesound.org/s/339517/ | pulswelle | 61.5 s from 5:18.5, 1.5 s crossfade, the seam between two waves |

Thank you, all three.
