"""Song of the moment (3.9.6, Sam: "leverage music databases to put a song
as their soundtrack / song of the moment"): the one song a person picks
from Apple's public catalog to show their crew. Pure: what a song is, what
the catalog's answer holds, and where Listen goes in each music app.

A song is {"t": title, "a": artist, "id": the catalog's track id, "url": its
page on Apple Music} and, when there, "al" album, "y" year, "art" its cover,
"at" the day it was picked. Only Apple's hosts for its links (the Worker's
songOf in worker/src/board.ts holds to the same, and tests/fakes.py restates
it); strings short, no control characters.

Apple's terms for the Search API's covers and previews: they promote the
song, beside Apple's own badge linking to it, credited ("courtesy of"), and
a preview only ever streamed, never downloaded or kept. Anki's web view
can't play Apple's audio and its player can't stream a link, so there are
no previews (Sam's pick, after the click test); every cover sits on a card
whose foot says "Courtesy of Apple Music" beside BADGE_URL, linked to the
song's page, at Apple's 30 px digital minimum. Spotify and YouTube Music get
a search link and nothing of theirs is shown, so they ask nothing of us.

Due Crew never knows what anyone is actually listening to: only the song
they chose to show."""

import re
import urllib.parse

TEXT_MAX = 120
URL_MAX = 400
RESULTS_MAX = 8
QUERY_MAX = 80

# who may host what (the Worker's SONG_HOSTS)
_HOSTS = {
    "url": re.compile(r"^(music|itunes|geo\.music)\.apple\.com$"),
    "art": re.compile(r"^([a-z0-9-]+\.)*mzstatic\.com$"),
}
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")

APPS = (("apple", "Apple Music"), ("spotify", "Spotify"), ("youtube", "YouTube Music"), ("other", "Another app"))
MOTIONS = ("gentle", "lively", "still")

# Apple's own badge, as its marketing tools serve it (never redrawn or altered)
BADGE_URL = "https://tools.applemediaservices.com/api/badges/listen-on-apple-music/badge/en-us?size=250x83"
BADGE_H = 30  # px: Apple's smallest on a screen
CREDIT = "Courtesy of Apple Music"  # the credit Apple asks for, at the foot of every card with a cover
SEARCH_URL = "https://itunes.apple.com/search"


def _text(v, need=True):
    if not isinstance(v, str):
        return None
    v = v.strip()
    if not v or len(v) > TEXT_MAX or _CTRL.search(v):
        return None
    return v


def _url(v, kind):
    """An https link on the hosts Apple serves that kind from, as given."""
    if not isinstance(v, str) or not v or len(v) > URL_MAX or _CTRL.search(v) or " " in v:
        return None
    try:
        u = urllib.parse.urlsplit(v)
    except ValueError:
        return None
    if u.scheme != "https" or u.username or u.password or u.port not in (None, 443):
        return None
    return v if _HOSTS[kind].match((u.hostname or "").lower()) else None


def clean(v):
    """A song as Due Crew keeps and shows it, or None. Required: title,
    artist, a positive id, its Apple Music link; the rest dropped when it
    doesn't hold."""
    if not isinstance(v, dict):
        return None
    t, a, url = _text(v.get("t")), _text(v.get("a")), _url(v.get("url"), "url")
    i = v.get("id")
    if not (t and a and url) or isinstance(i, bool) or not isinstance(i, int) or not 0 < i < 2 ** 53:
        return None
    out = {"t": t, "a": a, "id": i, "url": url}
    al = _text(v.get("al"))
    if al:
        out["al"] = al
    y = v.get("y")
    if isinstance(y, int) and not isinstance(y, bool) and 1900 <= y <= 2100:
        out["y"] = y
    art = _url(v.get("art"), "art")
    if art:
        out["art"] = art
    at = v.get("at")
    if isinstance(at, str) and _DAY.match(at):
        out["at"] = at
    return out


def same(a, b):
    """Two songs the same pick (the same track, picked the same day)."""
    return bool(a and b and a.get("id") == b.get("id") and a.get("at") == b.get("at"))


def search_url(q, country="us"):
    """The catalog's search for q: songs only, a few. "" for nothing to ask."""
    q = " ".join(str(q or "").split())[:QUERY_MAX]
    if len(q) < 2:
        return ""
    return SEARCH_URL + "?" + urllib.parse.urlencode(
        {"term": q, "media": "music", "entity": "song", "limit": RESULTS_MAX + 4, "country": country or "us"})


def _cover(u):
    """The catalog's 100 px cover, asked at 300 px (the card shows it at 64)."""
    if isinstance(u, str):
        return re.sub(r"/\d+x\d+bb\.(jpg|png|webp)$", r"/300x300bb.\1", u)
    return u


def parse(data):
    """The catalog's answer ({"results": [...]}) as songs: tracks of kind
    song, each cleaned, one per id, at most RESULTS_MAX."""
    out, seen = [], set()
    rows = data.get("results") if isinstance(data, dict) else None
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or r.get("kind") != "song":
            continue
        rd = str(r.get("releaseDate") or "")
        y = int(rd[:4]) if rd[:4].isdigit() else None
        s = clean({"t": r.get("trackName"), "a": r.get("artistName"), "al": r.get("collectionName"),
                   "y": y, "id": r.get("trackId"), "url": r.get("trackViewUrl"),
                   "art": _cover(r.get("artworkUrl100"))})
        if s and s["id"] not in seen:
            seen.add(s["id"])
            out.append(s)
        if len(out) >= RESULTS_MAX:
            break
    return out


def app_name(key):
    return dict(APPS).get(key, "")


def listen_url(song, app):
    """Where Listen goes in that app: Apple Music, the song itself; Spotify
    and YouTube Music, a search for its title and artist (it comes first);
    another app, nowhere (the title and artist, to copy)."""
    song = clean(song)
    if not song:
        return None
    words = f'{song["t"]} {song["a"]}'
    if app == "apple":
        return song["url"]
    if app == "spotify":
        return "https://open.spotify.com/search/" + urllib.parse.quote(words, safe="")
    if app == "youtube":
        return "https://music.youtube.com/search?" + urllib.parse.urlencode({"q": words})
    return None


def words(song):
    """"Title · Artist", to copy or say."""
    song = clean(song) or {}
    return " · ".join(x for x in (song.get("t"), song.get("a")) if x)


def newest_first(people):
    """Crewmates with a song, the one picked most lately first, then by name."""
    by_name = sorted(people, key=lambda p: str(p.get("name") or "").lower())
    return sorted(by_name, key=lambda p: str((p.get("song") or {}).get("at") or ""), reverse=True)
