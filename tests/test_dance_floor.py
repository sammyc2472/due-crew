"""Song of the moment's dance floor (3.9.6): the board side. The Decks
screen's bottom-right corner, drawn into a <template> in the board
(board.dance_html) and put on the page by its script (dance_js, carried by
fridge_js): my Pip the DJ at its booth, headphones on; each crewmate with a
song dancing as their Pip, one bubble at a time; up to six, then "+N" in the
sixth's place; folded on a narrow window; folded into a chip (dancefold);
the song card (cover, ▶ 30 s, Listen in my app, Apple's badge), the search
sheet, Settings › Board's rows and the profile card's line. Everything
theirs or Apple's escaped; every command keyed and sent through _on_js as
the board sends it, reaching song_flow. Standard library only; node for the
scripts, when it's there.

Run: python3 tests/test_dance_floor.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import types
from urllib.parse import quote

HARNESS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HARNESS)
sys.path.insert(0, HARNESS)

import fakes  # noqa: E402

fakes.install_fake_requests(fakes.FakeWorker())
fakes.install_fake_aqt()
sys.path.insert(0, REPO)

from due_crew import board, closet_art, songs  # noqa: E402
from due_crew import song_flow as SF  # noqa: E402

CHECKS = []
KEY = board.BOARD_KEY


def check(name, cond, detail=""):
    CHECKS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond or detail == "" else f"\n     {detail}"))


def as_board(message):
    """A message as the Decks page sends it: with the board's key."""
    return message + "|" + KEY


def song(i, t="Lantern Hours", a="Mira Vale", al="Lantern Hours", y=2025, at="2026-10-30", art=True):
    s = {"t": t, "a": a, "al": al, "y": y, "id": 1700000000 + i, "at": at,
         "url": f"https://music.apple.com/us/album/x/{1600000000 + i}?i={1700000000 + i}"}
    if art:
        s["art"] = f"https://is1-ssl.mzstatic.com/image/thumb/Music/{i}/300x300bb.jpg"
    return s


NAMES = [("dre", "Dre", "blue", ["dino"]), ("marisa", "Marisa K.", "teal", ["wizard"]), ("noah", "Noah", "rose", ["partyhat"]),
         ("priya", "Priya", "amber", []), ("kai", "Kai", "purple", []), ("nia", "Nia", "green", ["beanie"]),
         ("jun", "Jun", "teal", []), ("lena", "Lena", "blue", []), ("bo", "Bo", "rose", [])]


def view(n=4, me=True, fresh=(), **kw):
    crew = [{"uid": u, "name": nm, "accent": acc, "look": lk, "song": song(i + 1, t=f"Song {i}"), "fresh": u in fresh}
            for i, (u, nm, acc, lk) in enumerate(NAMES[:n])]
    return dict({"me": song(50, t="Study Hall") if me else None, "crew": crew, "motion": "gentle", "app": "spotify",
                 "pip": True, "folded": False}, **kw)


def floor(html):
    """The floor inside its template."""
    return html.split('<template id="dc-dance-src"', 1)[1].split("</template>", 1)[0]


def dancers(html):
    """(classes, uid, x) of each dancer: its place, and the button over it that opens its card."""
    return [(c, u, x) for c, x, u in re.findall(
        r'<span class="(dz [^"]*)" style="--x:(-?\d+);.*?<button type="button" class="dzb" data-open="([^"]*)"', html)]


def test_none_and_shape():
    check("no view, no floor (off, or no board)", board.dance_html(None, {}) == "")
    h = board.dance_html(view(), {})
    f = floor(h)
    check("a template in the board (inert till dance_js puts it on the page), the floor its one child, and the room after the board",
          h.startswith('<template id="dc-dance-src" data-k="') and f.count('id="dc-dance"') == 1
          and 'id="dc-dance-room"' in h.split("</template>", 1)[1])
    check("one floor a draw: the booth, the dancers, the cards, the fold's chip; × hides it (dancehide), keyed",
          f.count('class="df-bo"') == 1 and f.count('class="df-chip"') == 1 and f.count('class="df-fd"') == 1
          and f"pycmd('duecrew:dancehide|{KEY}')" in f)


def test_escaped():
    """Every word from a crewmate or Apple's catalog is escaped, in text and in attributes."""
    v = view(2)
    v["crew"][0].update(name='Mo "<b>bold</b>" & co', uid="mo")
    v["crew"][0]["song"].update(t='Lantern "<img src=x onerror=alert(1)>"', a="A & B <i>", al="Al'bum </template>")
    v["me"].update(t="<script>alert(1)</script>")
    h = board.dance_html(v, {})
    check("names, titles, artists, albums escaped everywhere (a bubble, a card, the list, aria-labels); nothing ends the template",
          "<img src=x" not in h and "<b>bold</b>" not in h and "<i>" not in h and "<script>" not in h
          and h.count("</template>") == 1 and "Mo &quot;&lt;b&gt;bold&lt;/b&gt;&quot; &amp; co" in h
          and "Lantern &quot;&lt;img src=x onerror=alert(1)&gt;&quot;" in h and "Al&#x27;bum &lt;/template&gt;" in h
          and "&lt;script&gt;alert(1)&lt;/script&gt;" in h)
    bad = dict(song(3), art="javascript:alert(1)", url="https://evil.example/x")
    v2 = view(1)
    v2["crew"][0]["song"] = bad
    check("a song that isn't a song (songs.clean: not Apple's link) isn't drawn at all",
          'data-open="dre"' not in board.dance_html(v2, {}) and "evil.example" not in board.dance_html(v2, {}))
    v3 = view(1)
    v3["crew"][0]["song"] = dict(song(4), art="https://evil.example/a.jpg")
    h3 = board.dance_html(v3, {})
    check("a cover only from Apple's image host: one from anywhere else is dropped, the colour tile in its place",
          "evil.example" not in h3 and '<span class="cov"' in h3)


def test_dancers_and_more():
    for n in (1, 4, 6):
        ds = dancers(board.dance_html(view(n), {}))
        check(f"{n} songs: {n} dancing, no +N", len(ds) == n and "df-more" not in board.dance_html(view(n), {}).split("df-cards")[0]
              .replace("#dc-dance .df-more", ""))
    h = board.dance_html(view(9), {})
    ds = dancers(h)
    more = re.search(r'<button type="button" class="df-more" data-open="\*" style="--x:(\d+)"[^>]*>\+(\d+)</button>', h)
    places = [(int(x), " bk" in c) for c, _u, x in ds]
    check("nine songs: five dance, +4 in the sixth's place (the back row's last), on no dancer",
          len(ds) == 5 and more and more.group(2) == "4" and (int(more.group(1)), True) not in places
          and int(more.group(1)) == (5 - 3) * board.DANCE_SLOT + board.DANCE_SLOT // 2)
    check("…the list has all nine, each opening its card; the folded window's count says nine",
          h.count('<li><button type="button" data-open=') == 9 and "&#9834; 9</button>" in h)
    check("front row then a back row half a place along, none on another",
          len(set(places)) == len(places) and [p for p in places if not p[1]] == [(0, False), (66, False), (132, False)])
    css = board.DANCE_CSS
    check("the places count from the booth (Sam: start by the DJ, then toward the middle); a new song hops in from it",
          "#dc-dance .dz { position: absolute; bottom: 0; right: calc(var(--x) * 1px);" in css
          and "right: calc(var(--x) * 1px + 6px)" in css and "translate(48px, -26px)" in css and "left: calc(var(--x)" not in css)
    fl = lambda n: int(re.search(r'class="df-fl" style="--fl:(-?\d+)px"', board.dance_html(view(n), {})).group(1))  # noqa: E731
    check("the checkered floor under just the dancers there are: one by the booth, a small floor; three or more, the whole",
          fl(1) == board.DANCE_AREA - 60 - 24 and fl(2) == fl(1) - board.DANCE_SLOT and fl(3) == fl(2) - board.DANCE_SLOT
          and fl(9) == -10
          and fl(0) == -10, [fl(n) for n in (0, 1, 2, 3)])
    check("no party lights (Sam: distracting)", "df-lt" not in h and "bulb" not in h and "bulb" not in css
          and not hasattr(board, "_dance_lights"))
    one = board.dance_html(view(1), {})
    check("one song: no count (nothing more to list)", 'class="df-ct"' not in one)
    none = board.dance_html(view(0), {})
    check("no songs: “No one’s picked a song yet.”, no list", "No one&rsquo;s picked a song yet." in none and 'data-card="*"' not in none)


def test_fresh_and_bubbles():
    h = board.dance_html(view(4, fresh=("noah",)), {})
    ds = dancers(h)
    says = [u for c, u, _x in ds if " say" in c]
    check("one bubble at a time: the new song's first, with its star; the rest a ♪",
          says == ["noah"] and h.count('<b class="st">&#9733;</b>') == 1 and " fresh" in [c for c, u, _x in ds if u == "noah"][0])
    check("…no new song: the newest's bubble first", [u for c, u, _x in dancers(board.dance_html(view(4), {})) if " say" in c] == ["dre"])
    a, b = board._dance_keys(view(4, fresh=("noah",)), {}), board._dance_keys(view(4), {})
    check("the hop isn't in the floor's key: drawn again with it seen, the floor on the page stays as it is", a == b)
    c = board._dance_keys(dict(view(4), app="youtube"), {})
    d = board._dance_keys(dict(view(4), crew=view(5)["crew"]), {})
    e = board._dance_keys(dict(view(4), folded=True), {})
    check("my music app changes the cards' key only; a new song the floor's; the fold neither (the page's own)",
          c[0] == b[0] and c[1] != b[1] and d[0] != b[0] and e == b)
    check("the chip's star while a song's new", 'class="df-chip"' in h and h.split('class="df-chip"')[1].count("&#9733;") == 1
          and "&#9733;" not in board.dance_html(view(4), {}).split('class="df-chip"')[1])


def test_motion_and_fold():
    check("gentle is the default; an unknown motion is gentle", 'class="dm-gentle' in board.dance_html(dict(view(), motion=None), {})
          and 'class="dm-gentle' in board.dance_html(dict(view(), motion="wild"), {}))
    check("lively and still as asked", 'class="dm-lively' in board.dance_html(dict(view(), motion="lively"), {})
          and 'class="dm-still' in board.dance_html(dict(view(), motion="still"), {}))
    css = board.DANCE_CSS
    calm = css.split("@media (prefers-reduced-motion: no-preference)")[0]
    check("every move is under Reduce motion's no-preference; the bubbles fade, never move (3.9.7: the fade too)",
          "animation:" not in calm.replace("animation: none", "") and "transition:" not in calm
          and "@media (prefers-reduced-motion: no-preference) { #dc-dance .bub { transition: opacity .45s ease; } }" in css)
    check("gentle: a slow sway, from still and back (no pose swaps, no new drawing)",
          "@keyframes df-sway { 0%, 100% { transform: none; }" in css and "2.8s" in css)
    check("the Pips never take a click: the button around them does", re.search(r"#dc-dance \.pp \{[^}]*pointer-events: none", css))
    h = board.dance_html(dict(view(4), folded=True), {})
    check("folded: drawn folded, the chip says how many songs, the room after the board the chip's",
          'class="dm-gentle fold"' in h and "&#9834; 4</span>" in h and 'id="dc-dance-room" class=fold' in h
          and "#dc-dance.fold .df-sc, #dc-dance.fold .df-cards { display: none; }" in css)
    js = board.DANCE_JS
    check("folded: no dancing, no bubbles passed along; the fold at once on the page, then dancefold:1 / 0",
          "var on = !folded(f) && !still(f)" in js and "!away() && !S.open && !folded(f)) { S.saidAt = now; say(" in js
          and "send('dancefold:' + (on ? 1 : 0));" in js and "f.classList.toggle('fold', on);" in js)
    check("narrow: the booth, one dancer, a count", f"@media (max-width: {board.DANCE_NARROW - 1}px)" in css
          and "#dc-dance .dz:not(.d0), #dc-dance .df-more { display: none; }" in css)


def test_booth_and_dj():
    h = board.dance_html(view(2), {"sev_look": ["partyhat", "glasses"], "sev_closet": {"partyhat": "2026-10-01", "glasses": "2026-10-01"}})
    dj = h.split('<span class="dj"', 1)[1].split('<svg class="bsv"', 1)[0]
    phones = closet_art.ART["headphones"][0][:60]
    check("my Pip the DJ, headphones on (the closet's, in the party hat's place), the rest of my look on",
          phones in dj and closet_art.ART["partyhat"][0][:60] not in dj and closet_art.ART["glasses"][0][:60] in dj)
    check("my song on the booth; the booth opens my card", 'data-open="me"' in h and "&#9834; Study Hall</span>" in h
          and 'data-card="me"' in h)
    n = board.dance_html(view(0, me=False), {})
    check("no song of mine: Pip asks “Put on a song?”, the booth opens the search", "Put on a song?" in n
          and 'data-open="search"' in n and 'data-card="me"' not in n)
    off = board.dance_html(dict(view(2), pip=False), {})
    check("Pip off: no Pips, each crewmate's initial in their colour", '<svg class="sv' not in off and '<span class="fc">D</span>' in off)


def test_cards():
    v = view(3)
    v["crew"][2]["song"]["prev"] = "https://audio-ssl.itunes.apple.com/itunes-assets/AudioPreview/1.m4a"
    h = board.dance_html(v, {})
    card = lambda u: h.split(f'data-card="{u}"', 1)[1].split('<div class="df-pop"', 1)[0]  # noqa: E731
    check("a card: the cover (Apple's, from its host), title, artist · album · year, since when",
          '<img src="https://is1-ssl.mzstatic.com/' in card("dre") and "Song 0" in card("dre")
          and "Mira Vale &middot; Lantern Hours &middot; 2025" in card("dre") and "since 30 Oct" in card("dre"))
    check("no preview anywhere (Apple's terms: streamed only), even for a song that came with one",
          "songprev" not in h and "30 s" not in h and "&#9654;" not in h and "AudioPreview" not in h
          and ".pv" not in board.DANCE_CSS and "playing" not in board.DANCE_JS and "playing" not in board.DANCE_CSS)
    check("Listen in my app, by its name (songlisten); no ▾ on the card: changing it is Settings'",
          f"pycmd('duecrew:songlisten:dre|{KEY}')" in card("dre") and ">Listen in Spotify</button>" in card("dre")
          and "&#9662;" not in h and "duecrew:songapp:" not in h)
    ask = board.dance_html(dict(view(1), app=""), {})
    row = ask.split('<div class="lsn"', 1)[1].split("</div>", 1)[0] if '<div class="lsn"' in ask else ""
    check("no app yet (Sam: never offered): the card's own row, Listen in Apple Music · Spotify · YouTube Music · Other,"
          " each picking and opening (songlisten:<uid>:<app>), no lone Listen",
          '<span class="lw">Listen in</span>' in row and ">Listen</button>" not in ask
          and [m for m in re.findall(r"songlisten:dre:([a-z]+)\|", row)] == ["apple", "spotify", "youtube", "other"]
          and ">Apple Music</button>" in row and ">Other</button>" in row and 'title="Copies the title and artist"' in row, row[:400])
    check("another app picked: the title and artist, copied; YouTube Music by its name",
          ">Copy title and artist</button>" in board.dance_html(dict(view(1), app="other"), {})
          and ">Listen in YouTube Music</button>" in board.dance_html(dict(view(1), app="youtube"), {}))
    foot = card("dre").split('<div class="ft">', 1)[1] if '<div class="ft">' in card("dre") else ""
    check("Apple's credit at the foot of every card, the badge beside it, apart from Listen",
          foot.startswith('<span class="cr">Song and cover courtesy of Apple Music</span><span class="bdg">')
          and card("me").count('<span class="cr">Song and cover courtesy of Apple Music</span>') == 1
          and "border-top: 1px solid var(--dc-line)" in board.DANCE_CSS.split("#dc-dance .ft, #dc-song .ft {", 1)[1].split("}", 1)[0])
    ft = board.DANCE_CSS.split("#dc-dance .ft, #dc-song .ft {", 1)[1].split("}", 1)[0]
    check("the badge stays on the right: the credit wraps instead (Sam), the foot never does",
          "flex-wrap" not in ft and "#dc-dance .ft .bdg, #dc-song .ft .bdg { flex: none; margin-left: auto; }" in board.DANCE_CSS
          and "flex: 1 1 auto; min-width: 0;" in board.DANCE_CSS.split("#dc-dance .ft .cr, #dc-song .ft .cr {", 1)[1].split("}", 1)[0])
    check("the search: its own credit (Song search…) and the badge at its foot",
          "el('span', 'cr', \"Song search courtesy of Apple Music\")" in board.DANCE_JS
          and "img.height = 30;" in board.DANCE_JS)
    badge = card("dre").split('<span class="bdg">', 1)[1]
    check("Apple's badge with every cover, as Apple serves it (its alt), opening the song (songapple); its words if it doesn't load",
          f'<img src="{songs.BADGE_URL.replace("&", "&amp;")}" alt="Listen on Apple Music"' in badge
          and badge.count(f"pycmd('duecrew:songapple:dre|{KEY}')") == 2 and ">Listen on Apple Music</a>" in badge
          and "this.parentNode.nextElementSibling.hidden=false" in badge and "filter" not in badge)
    mine = card("me")
    check("called a study soundtrack (Sam), and mine says no more than that",
          "&#9834; Dre&rsquo;s study soundtrack &middot; since 30 Oct" in card("dre")
          and '<span>&#9834; Your study soundtrack</span>' in mine and "Decks screens" not in h and "song of the moment" not in h.lower()
          and "'Your study soundtrack'" in board.DANCE_JS and "Decks screens" not in board.DANCE_JS)
    clocks = re.findall(r'--sv-b:([\d.]+)s;--sv-d:(-?[\d.]+)s', board.dance_html(view(6), {}))
    check("each Pip blinks on its own clock, the DJ's too (Sam: they blinked together)",
          len(clocks) == 7 and len(set(clocks)) == 7, clocks)
    check("my card: Change… (the search), Take it off (songclear), the badge (songapple:me)",
          "data-find" in mine and f"pycmd('duecrew:songclear|{KEY}')" in mine and "songprev" not in mine
          and "songapple:me" in mine and "songlisten" not in mine)


def test_commands_keyed():
    h = board.dance_html(view(9), {}) + board._settings_board({"dance": "lively", "music_app": "apple"})
    cmds = re.findall(r"pycmd\('duecrew:([^'|]*)\|([^']*)'\)", h)
    check("every command on the floor and its settings carries the board's key", cmds and all(k == KEY for _c, k in cmds), cmds[:3])
    js = board.DANCE_JS
    check("the script's commands are keyed too; the search goes URL-encoded, from two letters, after a pause",
          "pycmd('duecrew:' + cmd + '|' + window.dcBK)" in js and "send('songsearch:' + encodeURIComponent(q))" in js
          and "q.length < 2" in js and "}, 400);" in js and "send('songuse:' + id)" in js and "/^\\d{1,16}$/.test(s.picked)" in js)
    check("the search's rows as text (never markup), a cover only from Apple's image host; only the latest search lands",
          "innerHTML" not in js and "el('b', null, song.t)" in js and "mzstatic\\.com" in js and "ART.test(song.art)" in js
          and "String(o.q || '') !== S.q" in js)
    check("the search is a sheet over the board: the bars dim with it", "dc-song" in board.VEIL_IDS and "aria-modal" in js)
    check("the floor's script comes with the fridge's (a page's scripts once), and the fridge's call puts it in step",
          board.DANCE_JS in board.fridge_js() and board.DANCE_JS not in board.fridge_js(scripts=False)
          and "window.dcDance.sync()" in js and board.fridge_js(scripts=False) == "\nif (window.dcFridge) { window.dcFridge(); }\n")
    check("nothing in the script ends a <script> it's put in", "</" not in board.DANCE_JS)


def test_settings_and_profile():
    b = board._settings_board({})
    check("Settings › Board: the dance floor on (× brings it here), Gentle, and no music app yet (ask)",
          "Study soundtrack" in b and "Song of the moment" not in b and 'aria-checked="true" aria-label="Dance floor" data-f="dancehide"' in b
          and 'aria-pressed="true" data-f="dancemotion:gentle"' in b and 'aria-pressed="true" data-f="songapp:ask"' in b)
    b2 = board._settings_board({"dance_floor": False, "dance": "still", "music_app": "youtube"})
    check("…off, Still, YouTube Music: as saved", 'data-f="danceshow"' in b2 and 'aria-pressed="true" data-f="dancemotion:still"' in b2
          and 'aria-pressed="true" data-f="songapp:youtube"' in b2)
    ix = board.settings_index({"signed_in": True, "tab": "board"}, {})
    found = {x["l"] for x in ix if "music" in x["k"]}
    check("Find a setting finds them by music words", {"Dance floor", "Dancing", "My music app"} <= found, found)
    p = board._profile_song({"uid": "dre", "song": song(2, t="Second <Wind>", a="North & bound")})
    check("their card: ♪ title · artist, Listen (songlisten, keyed), escaped",
          "&#9834; <b>Second &lt;Wind&gt;</b> &middot; North &amp; bound" in p and f"pycmd('duecrew:songlisten:dre|{KEY}')" in p)
    m = board._profile_song({"uid": "me", "you": True, "song": song(2)})
    check("mine: Change (the search); no song, no line", "dcDance.search()" in m and "songlisten" not in m
          and board._profile_song({"uid": "x"}) == "" and board._profile_song({"uid": "x", "song": {"t": "no url"}}) == "")
    js = board.profile_overlay_js({"name": "Dre", "uid": "dre", "cells": None, "last_active": "", "song": song(2)})
    check("the profile overlay carries the line", "songlisten:dre" in js)


def test_render_and_glue():
    data = {"entries": [], "labels": ["2026-11-02"], "tomorrow": "2026-11-03", "pending": []}
    with_floor = board.render(data, {"period": "today"}, 0, dance=view(2))
    check("render: the floor's template in the board, after the fridge; none without a view",
          'id="dc-dance-src"' in with_floor and 'id="dc-dance-src"' not in board.render(data, {"period": "today"}, 0))
    src = open(os.path.join(REPO, "due_crew", "__init__.py")).read()
    check("the glue draws it with the board (song_flow.floor_view) and says it's seen once on the page (mark_seen)",
          'dance=_state["dance_view"]' in src and src.count("    _dance_seen()\n") == 2 and "song_flow.mark_seen(view)" in src)
    import due_crew as dc
    from due_crew.app import _state
    box = {"cfg": {"sev": True, "song_seen": {"dre": "1"}}}
    saved = (SF.cfg, SF.save_cfg, _state.get("entries"), _state.get("dance_view"))
    try:
        SF.cfg = lambda: box["cfg"]
        SF.save_cfg = lambda c: box.update(cfg=c)
        _state["entries"] = [{"user_id": "me", "you": True, "name": "Me"},
                             {"user_id": "dre", "name": "Dre", "accent": "blue", "look": ["dino"], "song": song(1)},
                             {"user_id": "kai", "name": "Kai"}]
        v = dc._dance_view(box["cfg"])
        h = board.dance_html(v, box["cfg"])
        check("end to end: a crewmate's song from their entry on the floor, new to me (it changed), Kai (no song) not",
              [p["uid"] for p in v["crew"]] == ["dre"] and v["crew"][0]["fresh"] and 'data-open="dre"' in h and "kai" not in h)
        _state["dance_view"] = v
        dc._dance_seen()
        check("once drawn, it's seen: the next draw, no hop", box["cfg"]["song_seen"] == {"dre": f"{song(1)['id']}@2026-10-30", "kai": ""}
              and not dc._dance_view(box["cfg"])["crew"][0]["fresh"] and "dance_view" not in _state)
        box["cfg"]["dance_floor"] = False
        check("the floor off: no view", dc._dance_view(box["cfg"]) is None)
    finally:
        SF.cfg, SF.save_cfg = saved[:2]
        _state["entries"] = saved[2]
        if saved[3] is None:
            _state.pop("dance_view", None)


def _dc():
    import due_crew as dc
    from aqt.deckbrowser import DeckBrowser
    if "aqt.reviewer" not in sys.modules:
        sys.modules["aqt.reviewer"] = types.SimpleNamespace(Reviewer=type("Reviewer", (), {}))
    return dc, DeckBrowser


def test_commands_through_on_js():
    """Every command the floor, its cards, the search, Settings and the profile send, through _on_js as the board
    sends them, reaching song_flow; without the board's key, nothing."""
    dc, DeckBrowser = _dc()
    from due_crew import app as A
    box = {"cfg": {"music_app": "spotify", "song": dict(song(50, t="Study Hall"))}}
    did = []

    class Resp:
        status_code = 200

        def json(self):
            return {"results": [{"kind": "song", "trackId": 1701, "trackName": "Lantern Hours", "artistName": "Mira Vale",
                                 "collectionName": "Lantern Hours", "releaseDate": "2025-02-01T00:00:00Z",
                                 "trackViewUrl": "https://music.apple.com/us/album/x/1?i=1701",
                                 "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/a/100x100bb.jpg"}]}
    names = ("cfg", "save_cfg", "_redraw", "_get", "_open", "apple", "_today")
    saved = {k: getattr(SF, k) for k in names}
    saved_app = (A._bg, A.board_eval, A._state.get("entries"))
    send = lambda msg: dc._on_js(False, as_board("duecrew:" + msg), DeckBrowser())  # noqa: E731
    try:
        SF.cfg = lambda: box["cfg"]
        SF.save_cfg = lambda c: box.update(cfg=c)
        SF._redraw = lambda: did.append("redraw")
        SF._get = lambda url, stream=False: did.append(("get", url)) or Resp()
        SF._open = lambda s, key: did.append(("open", s["t"], key))
        SF.apple = lambda uid: did.append(("apple", uid))
        SF._today = lambda: "2026-11-02"
        A._bg = lambda job, done=None: done(job()) if done else job()
        A.board_eval = lambda js: did.append(("eval", js))
        A._state["entries"] = [{"user_id": "dre", "name": "Dre", "song": song(1, t="Second Wind")}]
        typed = "AC/DC: back | in black"
        send("songsearch:" + quote(typed, safe=""))
        got = [d for d in did if isinstance(d, tuple)]
        res = json.loads(got[-1][1].split("dcSong.results(", 1)[1][:-1]) if got and got[-1][0] == "eval" else {}
        check("songsearch: the words as typed (':' and '|' and all), Apple's catalog asked, the songs back to the page",
              got[0][0] == "get" and "term=AC%2FDC%3A+back+%7C+in+black" in got[0][1] and res.get("q") == typed
              and res["songs"][0]["id"] == 1701 and "window.dcSong&&dcSong.results(" in got[-1][1])
        send("songuse:1701")
        check("songuse: that song is mine, picked today", box["cfg"]["song"]["id"] == 1701 and box["cfg"]["song"]["at"] == "2026-11-02")
        did.clear()
        send("songlisten:dre")
        send("songapple:dre")
        check("songlisten, songapple: each to song_flow, for whom",
              did == [("open", "Second Wind", "spotify"), ("apple", "dre")], did)
        did.clear()
        send("songlisten:dre:youtube")
        check("songlisten:<uid>:<app>, a card's row: that app kept, the song opened there, the cards drawn again",
              box["cfg"]["music_app"] == "youtube" and did == [("open", "Second Wind", "youtube"), "redraw"], did)
        did.clear()
        send("songprev:dre")
        check("songprev: no more (the preview's gone)", not did, did)
        for msg, k, want in (("songapp:youtube", "music_app", "youtube"), ("dancemotion:lively", "dance", "lively"),
                             ("dancehide", "dance_floor", False), ("danceshow", "dance_floor", True),
                             ("dancefold:1", "dance_folded", True), ("dancefold:0", "dance_folded", False)):
            send(msg)
            check(f"{msg}: {k} is {want!r}", box["cfg"].get(k) == want, box["cfg"].get(k))
        did.clear()
        send("dancefold:1")
        check("the fold doesn't draw the board again (the page folded itself)", "redraw" not in did, did)
        send("songclear")
        check("songclear: my song off", "song" not in box["cfg"])
        before = dict(box["cfg"])
        did.clear()
        for msg in ("songapp:spotify", "dancehide", "songuse:1701", "songsearch:hello", "dancefold:0"):
            dc._on_js(False, "duecrew:" + msg, DeckBrowser())  # no key: a page before's, not the board's
        check("without the board's key, nothing", box["cfg"] == before and not did, (did, box["cfg"]))
        for msg in ("songapp:nope", "dancemotion:wild", "dancefold:2"):
            send(msg)
        check("a value it doesn't take changes nothing", box["cfg"] == before, box["cfg"])
    finally:
        for k, v in saved.items():
            setattr(SF, k, v)
        A._bg, A.board_eval = saved_app[:2]
        A._state["entries"] = saved_app[2]


def test_every_command_has_its_route():
    """The commands on the floor, its cards, the search, Settings and the profile, each routed in _on_js to song_flow."""
    h = (board.dance_html(view(9), {}) + board._settings_board({}) + board._settings_board({"dance_floor": False})
         + board._profile_song({"uid": "dre", "song": song(1)}))
    emitted = {c for c in set(re.findall(r"duecrew:([a-z]+)", h)) | set(re.findall(r"send\('([a-z]+):?'", board.DANCE_JS))
               if c.startswith(("song", "dance"))}
    src = open(os.path.join(REPO, "due_crew", "__init__.py")).read()
    routed = set(re.findall(r'"([a-z]+)"', re.search(r'elif cmd in \(("songsearch"[^)]*)\):', src).group(1)))
    flow = open(os.path.join(REPO, "due_crew", "song_flow.py")).read()
    handled = set(re.findall(r'cmd == "([a-z]+)"', flow)) | set(re.findall(r'"([a-z]+)"', " ".join(re.findall(r"cmd in \(([^)]*)\)", flow))))
    want = {"songsearch", "songuse", "songclear", "songlisten", "songapp", "songapple", "dancehide", "danceshow",
            "dancemotion", "dancefold"}
    check("every song and dance command on the page is routed to song_flow, which handles it",
          want <= emitted and emitted <= routed and routed <= handled,
          (sorted(want - emitted), sorted(emitted - routed), sorted(routed - handled)))


def test_scripts_parse():
    if not shutil.which("node"):
        check("node: not here, the scripts weren't parsed", True)
        return
    for name, js in (("the floor's", board.DANCE_JS), ("the fridge's, with it", board.fridge_js()),
                     ("the profile's", board.profile_overlay_js({"name": "Dre", "uid": "dre", "cells": None, "last_active": "",
                                                                  "song": song(2)}))):
        node = subprocess.run(["node", "--check", "-"], input=js, capture_output=True, text=True)
        check(f"{name} script parses", node.returncode == 0, node.stderr[:300])
    probe = r"""
    var none = function () { return null; };
    globalThis.window = globalThis;
    globalThis.document = {getElementById: none, querySelector: none, querySelectorAll: function () { return []; },
                           addEventListener: function () {}, body: {className: ''}};
    (0, eval)(JS);
    window.dcFridge();
    window.dcDance.sync();
    window.dcSong.results({q: 'x', songs: []});
    console.log('ok');
    """.replace("JS", json.dumps(board.fridge_js()))
    node = subprocess.run(["node", "-"], input=probe, capture_output=True, text=True)
    check("on a page with no floor (no template), the scripts and their calls do nothing, and never throw",
          node.returncode == 0 and node.stdout.strip() == "ok", node.stderr[:300])


def main():
    names = [n for n in list(globals()) if n.startswith("test_")]
    for n in names:
        globals()[n]()
    bad = [c for c in CHECKS if not c[1]]
    print(f"\n{len(CHECKS) - len(bad)}/{len(CHECKS)} checks passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
