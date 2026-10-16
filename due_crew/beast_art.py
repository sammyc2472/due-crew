"""3.9.0: the beasts' drawings (the fun round's, round two), each in a 200 x
170 drawing, feet on y 163. Pure data and markup, our own: nothing in it
comes from a person or the server.

The Backlog Beast breaks up as it's beaten (CSS on its classes: a horn at
a quarter, the other at half with a brow and a sweat, dizzy at three
quarters, a puff of smoke at the end); the others shrink. Three kinds,
no pets (Sam's rounds 2 and 3)."""

_CARD_SPOTS = ((44, 92, 6.9), (58, 60, 13.5), (84, 44, 16.5), (116, 44, 24.8), (142, 60, 13.4), (156, 92, 23.7),
               (160, 122, -26.4), (40, 124, -1.9), (70, 146, 24.8), (130, 146, 8.3), (100, 36, 22.5), (50, 108, -21.7),
               (150, 108, -1.7), (100, 150, -14.2))


def _card(x, y, r):
    return (f'<g transform="translate({x} {y}) rotate({r})"><rect x="-9" y="-6.5" width="18" height="13" rx="2.5" fill="#fff" '
            'stroke="#c9c3dd" stroke-width=".8"/><rect x="-6" y="-3" width="8" height="1.6" rx=".8" fill="#c9c3dd"/>'
            '<rect x="-6" y=".6" width="11" height="1.6" rx=".8" fill="#c9c3dd"/><rect x="4.2" y="-4" width="2.4" height="2.4" rx=".5" fill="#7b5cd6"/></g>')


def backlog(stages=True):
    """The Backlog Beast: purple, horned, made of cards. stages: with the
    parts that come and go as it's beaten (brow, sweat, dizzy eyes, puff)."""
    cards = "".join(_card(x, y, r) for x, y, r in _CARD_SPOTS)
    extra = ""
    if stages:
        spiral = ('m-1 0 a1 1 0 1 1 2 0 a3 3 0 1 1 -6 0 a5 5 0 1 1 10 0 a7 7 0 1 1 -14 0 a9 9 0 1 1 18 0" fill="none" '
                  'stroke="#241640" stroke-width="2"/>')
        extra = ('<g class="bdizzy"><circle cx="78" cy="80" r="15.5" fill="#fff"/><circle cx="122" cy="80" r="15.5" fill="#fff"/>'
                 f'<path d="M78 80 {spiral}<path d="M122 80 {spiral}</g>'
                 '<g class="bbrow"><path d="M64 60 Q76 54 90 62" stroke="#3a2470" stroke-width="4" fill="none" stroke-linecap="round"/>'
                 '<path d="M136 60 Q124 54 110 62" stroke="#3a2470" stroke-width="4" fill="none" stroke-linecap="round"/></g>'
                 '<g class="bsweat"><path d="M150 54 C146 62 154 66 156 60 C157 57 153 56 150 54 Z" fill="#9fd3f5"/>'
                 '<path d="M48 60 C44 68 52 72 54 66 C55 63 51 62 48 60 Z" fill="#9fd3f5"/></g>')
    poof = ('<g class="bpoof">' + "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#f4f1fb"/>'
                                          for x, y, r in ((70, 110, 26), (100, 96, 32), (132, 112, 26), (86, 130, 24), (118, 132, 24)))
            + "</g>") if stages else ""
    return ('<g class="bz"><g class="bb"><ellipse class="bsh" cx="100" cy="163" rx="62" ry="6" fill="rgba(0,0,0,.13)"/>'
            '<rect x="66" y="140" width="24" height="22" rx="9" fill="#5a3fa8"/><rect x="110" y="140" width="24" height="22" rx="9" fill="#5a3fa8"/>'
            '<path class="bhorn hl" d="M60 44 L64 22 L76 38 Z" fill="#f2b33d"/><path class="bhorn hr" d="M140 44 L136 22 L124 38 Z" fill="#f2b33d"/>'
            '<path d="M30 118 C22 70 52 30 100 30 C148 30 178 70 170 118 C168 148 140 158 100 158 C60 158 32 148 30 118 Z" fill="#7b5cd6"/>'
            '<path d="M30 112 C20 110 14 120 18 128 C22 132 30 130 33 126 Z M170 112 C180 110 186 120 182 128 C178 132 170 130 167 126 Z" fill="#6a4cc8"/>'
            '<ellipse cx="100" cy="120" rx="44" ry="29" fill="#9c84e6"/>' + cards
            + '<g class="beye"><circle cx="78" cy="80" r="15.5" fill="#fff"/><circle cx="122" cy="80" r="15.5" fill="#fff"/>'
            '<circle cx="81" cy="84" r="6.8" fill="#241640"/><circle cx="125" cy="84" r="6.8" fill="#241640"/>'
            '<circle cx="83.5" cy="81" r="2" fill="#fff"/><circle cx="127.5" cy="81" r="2" fill="#fff"/></g>'
            + extra
            + '<path d="M80 112 Q100 128 120 112 Z" fill="#3a2470"/><path d="M87 113.4 L90 119.5 L93 114.6 Z M107 114.6 L110 119.5 L113 113.4 Z" fill="#fff"/>'
            '</g>' + poof + '</g>')


def pile():
    cards = ""
    for x, y, r in ((100, 146, -4), (96, 128, 5), (104, 110, -6), (98, 92, 3), (102, 74, -3)):
        cards += (f'<g transform="translate({x} {y}) rotate({r})"><rect x="-46" y="-14" width="92" height="28" rx="6" fill="#fff" '
                  'stroke="#cfc8b5" stroke-width="1.6"/><rect x="-36" y="-5" width="40" height="3.4" rx="1.7" fill="#d9d2bf"/>'
                  '<rect x="-36" y="2" width="56" height="3.4" rx="1.7" fill="#d9d2bf"/></g>')
    return ('<g class="bz"><g class="bb"><ellipse cx="100" cy="163" rx="56" ry="6" fill="rgba(0,0,0,.12)"/>' + cards
            + '<circle cx="86" cy="70" r="11" fill="#fff" stroke="#2b2d29" stroke-width="2"/><circle cx="114" cy="70" r="11" fill="#fff" stroke="#2b2d29" stroke-width="2"/>'
            '<circle cx="88" cy="73" r="4.8" fill="#2b2d29"/><circle cx="112" cy="73" r="4.8" fill="#2b2d29"/>'
            '<path d="M70 162 h12 M118 162 h12" stroke="#2b2d29" stroke-width="5" stroke-linecap="round"/></g></g>')


def leech():
    return ('<g class="bz"><g class="bb"><ellipse cx="100" cy="164" rx="70" ry="5.5" fill="rgba(0,0,0,.12)"/>'
            '<path d="M18 150 C30 154 60 156 70 152" stroke="#c7d38f" stroke-width="5" fill="none" stroke-linecap="round" opacity=".6"/>'
            '<path d="M40 158 C40 118 70 96 112 96 C150 96 176 120 176 150 C176 160 168 163 150 163 H52 C44 163 40 162 40 158 Z" fill="#8a9a4a"/>'
            '<path d="M56 158 C60 136 84 122 112 122 C140 122 160 136 162 156 Z" fill="#a8b866"/>'
            '<path d="M118 100 C116 84 112 74 106 64 M140 104 C142 88 148 78 156 70" stroke="#8a9a4a" stroke-width="7" fill="none" stroke-linecap="round"/>'
            '<circle cx="105" cy="60" r="10" fill="#fff" stroke="#6b7a34" stroke-width="2.4"/><circle cx="157" cy="66" r="10" fill="#fff" stroke="#6b7a34" stroke-width="2.4"/>'
            '<circle cx="107" cy="62" r="4.6" fill="#2b2d29"/><circle cx="159" cy="68" r="4.6" fill="#2b2d29"/>'
            '<path d="M118 82 L122 70 L128 80 L134 68 L140 80 L146 70 L150 82 Z" fill="#f2c230" stroke="#c98a12" stroke-width="1.2"/>'
            '<path d="M120 132 Q132 140 146 132" stroke="#4f5a24" stroke-width="3" fill="none" stroke-linecap="round"/></g></g>')


ART = {"backlog": backlog, "pile": pile, "leech": leech}


def art(kind, stages=False):
    """A beast's drawing, by kind (the Backlog Beast with its stages, when asked)."""
    if kind == "backlog":
        return backlog(stages)
    return ART.get(kind, pile)()


def svg(kind, cls="", label=None, stages=False, inner=None):
    """A beast as its own <svg>, our markup; label: what it's called, or hidden."""
    a = f'role="img" aria-label="{label}"' if label else 'aria-hidden="true"'
    return (f'<svg class="dc-bst {cls}" viewBox="0 0 200 170" {a}>'
            f'{inner if inner is not None else art(kind, stages)}</svg>')


CSS = """
    #due-crew .dc-bst { overflow: visible; display: block; }
    #due-crew .dc-bst .bdizzy, #due-crew .dc-bst .bbrow, #due-crew .dc-bst .bsweat, #due-crew .dc-bst .bpoof { opacity: 0; transition: opacity .3s; }
    #due-crew .dc-bst .bb, #due-crew .dc-bst .bz { transform-box: fill-box; transform-origin: 50% 100%; }
    #due-crew .dc-bst .bhorn { transform-box: fill-box; transform-origin: 50% 100%; transition: transform .8s ease-in, opacity .8s; }
    #due-crew .dc-bst.st1 .bhorn.hl, #due-crew .dc-bst.st2 .bhorn, #due-crew .dc-bst.st3 .bhorn { transform: translate(-30px, 90px) rotate(-120deg); opacity: 0; }
    #due-crew .dc-bst.st2 .bhorn.hr, #due-crew .dc-bst.st3 .bhorn.hr { transform: translate(30px, 90px) rotate(120deg); }
    #due-crew .dc-bst.st2 .bbrow, #due-crew .dc-bst.st2 .bsweat, #due-crew .dc-bst.st3 .bbrow, #due-crew .dc-bst.st3 .bsweat { opacity: 1; }
    #due-crew .dc-bst.st3 .beye { opacity: 0; } #due-crew .dc-bst.st3 .bdizzy { opacity: 1; }
    #due-crew .dc-bst.poof .bb { opacity: 0; } #due-crew .dc-bst.poof .bpoof { opacity: 1; }
    @media (prefers-reduced-motion: no-preference) {
      #due-crew .dc-bst.big .bz { animation: dc-bbreath 3.2s ease-in-out infinite; }
      @keyframes dc-bbreath { 0%, 100% { transform: none; } 50% { transform: scale(1.02, .98); } }
      #due-crew .dc-bst.st3 .bb { animation: dc-bdz 1.6s ease-in-out infinite; }
      @keyframes dc-bdz { 0%, 100% { rotate: -3deg; } 50% { rotate: 3deg; } }
      #due-crew .dc-bst .bdizzy path { transform-box: fill-box; transform-origin: 50% 50%; animation: dc-bspin 1.2s linear infinite; }
      @keyframes dc-bspin { to { transform: rotate(360deg); } }
      #due-crew .dc-bst.poof .bpoof circle { transform-box: fill-box; transform-origin: 50% 50%; animation: dc-bpuff .9s ease-out both; }
      @keyframes dc-bpuff { from { transform: scale(.2); } to { transform: scale(1.15); opacity: 0; } }
    }
"""
