"""3.10.3, the Fifteen's sound (KV, 19 Nov 2026: "could we please get the white noise back? ... one button
for a timer & focusing noise"; SC: "an option on the drop down caret on Fifteen"). Room sounds went in 3.9.8;
this is the part that was used: Fire (a recording, CC0: sounds/CREDITS.md) and Brown noise (made by
sounds.js), picked from the arrow beside Fifteen? in the top bar, played by the top bar's page while a
fifteen or a room runs, through its breaks. No chip speaker, no volume, no rain or waves. Pure.

This computer's (`fifteen_sound`: off, fire, brown), never sent: each person their own."""

import json

from .words import later as _later

KEY = "fifteen_sound"
KINDS = ("off", "fire", "brown")
LABELS = {"off": _later("No sound"), "fire": _later("Fire"), "brown": _later("Brown noise")}
VOL = 0.6
RECORDED = ("fire",)  # brown noise is made, as brown noise is


def pick(cfg):
    """This computer's pick: off unless picked."""
    kind = cfg.get(KEY)
    return kind if kind in KINDS else "off"


def state(span, kind, files=None):
    """What the top bar's player needs: the pick and the session's span (start, end: datetimes), or None
    in no session (it stops). files: where the recording is (`files`)."""
    if span is None:
        return None
    return {"kind": kind if kind in KINDS else "off", "vol": VOL,
            "from": int(span[0].timestamp() * 1000), "until": int(span[1].timestamp() * 1000),
            "files": dict(files or {})}


def files(folder, have):
    """{kind: url} for the recordings the add-on has, served to the top bar's page by Anki's /_addons/."""
    from urllib.parse import quote
    return {k: f"/_addons/{quote(str(folder))}/sounds/{k}.ogg" for k in RECORDED if k in set(have or ())}


_SRC = []


def _sounds_js():
    if not _SRC:
        import os
        with open(os.path.join(os.path.dirname(__file__), "sounds.js"), encoding="utf-8") as f:
            _SRC.append(f.read())
    return _SRC[0]


# the top bar's player: the pick plays while the session runs, from any
# screen (Anki keeps the top bar's page through review), and stops at its end
SOUND_RUNTIME = r"""
(function (S) {
  var R = window.dcRoomSound;
  if (!R) {
    R = window.dcRoomSound = {s: null, t: null};
    R.check = function () {
      var s = R.s, now = Date.now(), on = !!(s && s.kind !== 'off' && now >= s.from && now < s.until);
      if (window.dcSounds) {
        if (on) { window.dcSounds.play(s.kind, s.vol); } else if (window.dcSounds.playing()) { window.dcSounds.stop(); }
      }
      if ((!s || now >= s.until) && R.t) { clearInterval(R.t); R.t = null; }
    };
    R.set = function (s) {
      if (s && window.dcSounds && window.dcSounds.files) { window.dcSounds.files(s.files); }
      R.s = s; R.check(); if (s && !R.t) { R.t = setInterval(R.check, 5000); }
    };
    R.pick = function (kind, vol) { if (R.s) { R.s.kind = kind; R.s.vol = vol; } R.check(); };
    R.volume = function (vol) { if (R.s) { R.s.vol = vol; } if (window.dcSounds) { window.dcSounds.setVolume(vol); } };
  }
  R.set(S);
})(__SOUND__);
"""


def js(st):
    """The top bar's player, told the pick and the session (`state`); None stops it. The sounds
    themselves (sounds.js) go only once one is picked."""
    if st is None:
        return "window.dcRoomSound && window.dcRoomSound.set(null);"
    return ((_sounds_js() if st.get("kind") in KINDS and st["kind"] != "off" else "")
            + SOUND_RUNTIME.replace("__SOUND__", json.dumps(st)))
