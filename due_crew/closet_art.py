"""3.8.2: the closet's drawings, in Pip's own 80 x 80 drawing (sev.py). Pure data.

ART[k] = (front, back): front goes over the body (under any arms in front),
back behind it. A held thing (closet SLOT "hand") is drawn where the right
hand is when the arm hangs down, (64.6, 56.8); sev.py moves it to wherever
the hand is. Classes animate under Reduce motion's no-preference (sev.CSS):
cl-prop, cl-steam, cl-flame, cl-flick, cl-bal, cl-flag,
cl-wing (cl-wl, cl-wr), cl-blink, cl-glow."""

ART = {
    "sprout": (
        ('<path d="M40 27.5 C40 24 40.4 21.5 41 19.5" stroke="#4f8a3c" stroke-width="1.8" fill="none" stroke-linecap="round"/>'
         '<path d="M41 20 C36.5 21 33 18.5 32.5 14.8 C36.8 14 40.4 16.2 41 20 Z" style="fill:#7cbf5a"/>'
         '<path d="M41 19.6 C45 20 48.8 17.2 49.2 13.4 C45.2 13 41.6 15.6 41 19.6 Z" style="fill:#9ad16f"/>'),
        ""),
    "beanie": (
        ('<path d="M21.5 31 C21.5 18 29 13 40 13 C51 13 58.5 18 58.5 31 Z" style="fill:#d9534f"/>'
         '<path d="M27 18 C31 15.6 35 14.6 40 14.6" stroke="#fff" stroke-opacity=".35" stroke-width="2" fill="none" stroke-linecap="round"/>'
         '<rect x="19.5" y="28.5" width="41" height="7" rx="3.5" style="fill:#b8403c"/>'
         '<path d="M23 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M27 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M31 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M35 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M39 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M43 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M47 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M51 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M55 30 v4" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<circle cx="40" cy="11.5" r="4.3" style="fill:#f4efe6"/>'),
        ""),
    "cap": (
        ('<path d="M24.5 30.8 C18 30.6 12 31.6 8.6 33.6 C12.4 35.4 18.6 34.6 25.4 33.4 Z" style="fill:#285f9c"/>'
         '<path d="M22 31.5 C22 20.5 30 15 40 15 C50 15 58 20.5 58 31.5 Z" style="fill:#2f6fb5"/>'
         '<path d="M40 15 V31.5" stroke="#285f9c" stroke-width="1.2"/>'
         '<path d="M29 18.8 C33 16.4 36.5 15.6 40 15.4" stroke="#fff" stroke-opacity=".35" stroke-width="2" fill="none" stroke-linecap="round"/>'
         '<circle cx="40" cy="15.2" r="1.8" style="fill:#285f9c"/>'),
        ""),
    "scarf": (
        ('<rect x="44" y="57" width="7" height="14.5" rx="2.5" transform="rotate(10 47.5 57)" style="fill:#2a62a3"/>'
         '<rect x="19.5" y="54.5" width="41" height="7" rx="3.5" style="fill:#2f6fb5"/>'
         '<path d="M24 55 v6" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M30 55 v6" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M36 55 v6" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M42 55 v6" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M48 55 v6" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M54 55 v6" stroke="#fff" stroke-opacity=".28" stroke-width="1.3"/>'
         '<path d="M44.8 71 v2.4 M47 71.3 v2.4 M49.2 71.6 v2.4" stroke="#2a62a3" stroke-width="1.2" stroke-linecap="round" transform="rotate(10 47.5 57)"/>'),
        ""),
    "cape": (
        ('<circle cx="27" cy="34" r="2.2" style="fill:#ffd23f"/>'
         '<circle cx="53" cy="34" r="2.2" style="fill:#ffd23f"/>'),
        ('<path d="M24 33 L56 33 L66.5 71 Q40 76 13.5 71 Z" style="fill:#c8373d"/>'
         '<path d="M24 33 L56 33 L58 38 Q40 41 22 38 Z" style="fill:#a52d33"/>')),
    "medal": (
        ('<path d="M35 51 L39 59 L41.2 58 L38 51 Z" style="fill:#2f6fb5"/>'
         '<path d="M45 51 L41 59 L38.8 58 L42 51 Z" style="fill:#d9534f"/>'
         '<circle cx="40" cy="61.4" r="4.6" style="fill:#f2b33d" stroke="#c98a12" stroke-width=".9"/>'
         '<polygon points="40,59 40.7,60.7 42.5,60.8 41.1,62 41.5,63.7 40,62.8 38.5,63.7 38.9,62 37.5,60.8 39.3,60.7" style="fill:#fff6d8" stroke-linejoin="round"/>'),
        ""),
    "laurel": (
        ('<ellipse cx="22.5" cy="31" rx="3.2" ry="1.4" transform="rotate(-70 22.5 31)" style="fill:#5f9d45"/>'
         '<ellipse cx="24" cy="25.5" rx="3.2" ry="1.4" transform="rotate(-50 24 25.5)" style="fill:#5f9d45"/>'
         '<ellipse cx="28" cy="21" rx="3.2" ry="1.4" transform="rotate(-30 28 21)" style="fill:#5f9d45"/>'
         '<ellipse cx="33.5" cy="18.4" rx="3.2" ry="1.4" transform="rotate(-12 33.5 18.4)" style="fill:#5f9d45"/>'
         '<ellipse cx="57.5" cy="31" rx="3.2" ry="1.4" transform="rotate(70 57.5 31)" style="fill:#5f9d45"/>'
         '<ellipse cx="56" cy="25.5" rx="3.2" ry="1.4" transform="rotate(50 56 25.5)" style="fill:#5f9d45"/>'
         '<ellipse cx="52" cy="21" rx="3.2" ry="1.4" transform="rotate(30 52 21)" style="fill:#5f9d45"/>'
         '<ellipse cx="46.5" cy="18.4" rx="3.2" ry="1.4" transform="rotate(12 46.5 18.4)" style="fill:#5f9d45"/>'
         '<ellipse cx="21" cy="28" rx="2.5" ry="1.1" transform="rotate(-100 21 28)" style="fill:#7cbf5a"/>'
         '<ellipse cx="25.6" cy="22.6" rx="2.5" ry="1.1" transform="rotate(-64 25.6 22.6)" style="fill:#7cbf5a"/>'
         '<ellipse cx="30.6" cy="19.2" rx="2.5" ry="1.1" transform="rotate(-40 30.6 19.2)" style="fill:#7cbf5a"/>'
         '<ellipse cx="59" cy="28" rx="2.5" ry="1.1" transform="rotate(100 59 28)" style="fill:#7cbf5a"/>'
         '<ellipse cx="54.4" cy="22.6" rx="2.5" ry="1.1" transform="rotate(64 54.4 22.6)" style="fill:#7cbf5a"/>'
         '<ellipse cx="49.4" cy="19.2" rx="2.5" ry="1.1" transform="rotate(40 49.4 19.2)" style="fill:#7cbf5a"/>'),
        ""),
    "glasses": (
        ('<g fill="none" stroke="#2b2d29" stroke-width="1.7"><circle cx="33" cy="43" r="7.3"/>'
         '<circle cx="47" cy="43" r="7.3"/><path d="M25.8 42 L20.6 40.4 M54.2 42 L59.4 40.4"/></g>'),
        ""),
    "nest": (
        ('<ellipse cx="40" cy="26" rx="14" ry="5.6" style="fill:#8a6a4a"/>'
         '<path d="M27 25 C33 28 47 28 53 25 M28.5 27.5 C34 30 46 30 51.5 27.5" stroke="#6f5136" stroke-width="1.1" fill="none"/>'
         '<ellipse cx="41" cy="19.5" rx="6.5" ry="5" style="fill:#f2c230"/>'
         '<circle cx="45.5" cy="15" r="3.6" style="fill:#f2c230"/>'
         '<circle cx="46.4" cy="14.2" r=".9" style="fill:#2b2d29"/>'
         '<path d="M48.8 14.8 L52 15.8 L48.8 16.6 Z" style="fill:#f08a24"/>'
         '<path d="M36 19 C33 17.5 32 20 35 21.5 Z" style="fill:#e0a92a"/>'),
        ""),
    "nightcap": (
        ('<path d="M21.5 31 C21 19.5 30 13.5 41 14 C52 14.5 59.5 22 63 33 L67.5 41 C63 39.5 59 35.5 57.5 31 Z" style="fill:#4a5aa8"/>'
         '<polygon points="32,20.2 32.5,21.3 33.7,21.4 32.8,22.3 33.1,23.5 32,22.8 30.9,23.5 31.2,22.3 30.3,21.4 31.5,21.3" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<polygon points="47,18 47.4,19 48.4,19 47.6,19.7 47.9,20.7 47,20.2 46.1,20.7 46.4,19.7 45.6,19 46.6,19" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<polygon points="56,26.6 56.4,27.5 57.3,27.6 56.6,28.2 56.8,29.1 56,28.6 55.2,29.1 55.4,28.2 54.7,27.6 55.6,27.5" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<rect x="19.5" y="28.5" width="41" height="5.5" rx="2.75" style="fill:#f4efe6"/>'
         '<circle cx="67.8" cy="42" r="3.8" style="fill:#f4efe6"/>'),
        ""),
    "toque": (
        ('<circle cx="31" cy="18" r="8" style="fill:#fff" stroke="#e1ddd4" stroke-width="1"/>'
         '<circle cx="49" cy="18" r="8" style="fill:#fff" stroke="#e1ddd4" stroke-width="1"/>'
         '<circle cx="40" cy="13.5" r="9" style="fill:#fff" stroke="#e1ddd4" stroke-width="1"/>'
         '<rect x="27" y="19.5" width="26" height="10" rx="2" style="fill:#fff" stroke="#e1ddd4" stroke-width="1"/>'
         '<path d="M33 21 V28 M40 21 V28 M47 21 V28" stroke="#e8e4da" stroke-width="1.2"/>'),
        ""),
    "mustache": (
        '<path d="M40 48.4 C36 46.2 30.6 46.6 28.4 50.2 C31.6 49.8 34.4 50.8 36.6 51 C38.4 51.2 39.4 50.2 40 49.4 C40.6 50.2 41.6 51.2 43.4 51 C45.6 50.8 48.4 49.8 51.6 50.2 C49.4 46.6 44 46.2 40 48.4 Z" style="fill:#9a6a3a" stroke="#5a3a20" stroke-width=".7"/>',
        ""),
    "stetho": (
        ('<path d="M26.5 49 C26.5 60 33 62.5 40 62.5 C47 62.5 53.5 60 53.5 49" stroke="#3b3f46" stroke-width="1.9" fill="none" stroke-linecap="round"/>'
         '<path d="M40 62.5 V65.2" stroke="#3b3f46" stroke-width="1.9"/>'
         '<circle cx="40" cy="66.3" r="2.6" style="fill:#c9ccd1" stroke="#3b3f46" stroke-width="1.3"/>'),
        ""),
    "tophat": (
        ('<ellipse cx="40" cy="28" rx="17.5" ry="3.2" style="fill:#2b2d33"/>'
         '<rect x="29" y="7.5" width="22" height="21" rx="2.5" style="fill:#33363d"/>'
         '<rect x="29" y="21.5" width="22" height="4.2" style="fill:#b03052"/>'
         '<path d="M32 10 V20" stroke="#fff" stroke-opacity=".15" stroke-width="2.4" stroke-linecap="round"/>'),
        ""),
    "monocle": (
        ('<circle cx="47" cy="43" r="7.4" style="fill:rgba(220,236,255,.18)" stroke="#c9a227" stroke-width="1.7"/>'
         '<path d="M50.5 49.6 C54 54 56 57 55 62" stroke="#c9a227" stroke-width="1" fill="none" stroke-dasharray="1.6 1.2"/>'),
        ""),
    "cardlei": (
        ('<g transform="translate(24.5 51.5) rotate(60)">'
         '<rect x="-3.4" y="-2.5" width="6.8" height="5" rx="1" style="fill:#fff" stroke="#d6d0c4" stroke-width=".5"/>'
         '<rect x="-2.2" y="-.6" width="3.6" height=".9" rx=".4" style="fill:#c9c2b3"/></g>'
         '<g transform="translate(27.5 56) rotate(40)">'
         '<rect x="-3.4" y="-2.5" width="6.8" height="5" rx="1" style="fill:#fde7a6" stroke="#d6d0c4" stroke-width=".5"/>'
         '<rect x="-2.2" y="-.6" width="3.6" height=".9" rx=".4" style="fill:#c9c2b3"/></g>'
         '<g transform="translate(32.5 59.2) rotate(20)">'
         '<rect x="-3.4" y="-2.5" width="6.8" height="5" rx="1" style="fill:#fff" stroke="#d6d0c4" stroke-width=".5"/>'
         '<rect x="-2.2" y="-.6" width="3.6" height=".9" rx=".4" style="fill:#c9c2b3"/></g>'
         '<g transform="translate(40 60.6) rotate(0)">'
         '<rect x="-3.4" y="-2.5" width="6.8" height="5" rx="1" style="fill:#cfe3fb" stroke="#d6d0c4" stroke-width=".5"/>'
         '<rect x="-2.2" y="-.6" width="3.6" height=".9" rx=".4" style="fill:#c9c2b3"/></g>'
         '<g transform="translate(47.5 59.2) rotate(-20)">'
         '<rect x="-3.4" y="-2.5" width="6.8" height="5" rx="1" style="fill:#fff" stroke="#d6d0c4" stroke-width=".5"/>'
         '<rect x="-2.2" y="-.6" width="3.6" height=".9" rx=".4" style="fill:#c9c2b3"/></g>'
         '<g transform="translate(52.5 56) rotate(-40)">'
         '<rect x="-3.4" y="-2.5" width="6.8" height="5" rx="1" style="fill:#fde7a6" stroke="#d6d0c4" stroke-width=".5"/>'
         '<rect x="-2.2" y="-.6" width="3.6" height=".9" rx=".4" style="fill:#c9c2b3"/></g>'
         '<g transform="translate(55.5 51.5) rotate(-60)">'
         '<rect x="-3.4" y="-2.5" width="6.8" height="5" rx="1" style="fill:#fff" stroke="#d6d0c4" stroke-width=".5"/>'
         '<rect x="-2.2" y="-.6" width="3.6" height=".9" rx=".4" style="fill:#c9c2b3"/></g>'),
        ""),
    "headphones": (
        ('<path d="M17.5 41 C17.5 20.5 26 15.5 40 15.5 C54 15.5 62.5 20.5 62.5 41" stroke="#3b3f46" stroke-width="3.2" fill="none" stroke-linecap="round"/>'
         '<path d="M18.6 38 C19.2 21.8 27 16.8 40 16.8" stroke="#8a909b" stroke-opacity=".7" stroke-width="1" fill="none" stroke-linecap="round"/>'
         '<rect x="13" y="35" width="9" height="14" rx="3.5" style="fill:#3b3f46"/>'
         '<rect x="58" y="35" width="9" height="14" rx="3.5" style="fill:#3b3f46"/>'
         '<rect x="15.2" y="37.6" width="4" height="8.8" rx="2" style="fill:#f2b33d"/>'
         '<rect x="60.8" y="37.6" width="4" height="8.8" rx="2" style="fill:#f2b33d"/>'),
        ""),
    "propeller": (
        ('<path d="M22 31.5 C22 20 30 15.5 40 15.5 C50 15.5 58 20 58 31.5 Z" style="fill:#d9534f"/>'
         '<path d="M40 15.5 C35 15.5 31 21 30.6 31.5 H40 Z" style="fill:#f2c230"/>'
         '<path d="M40 15.5 C45 15.5 49 21 49.4 31.5 H40 Z" style="fill:#2f6fb5"/>'
         '<rect x="39" y="10" width="2" height="6" style="fill:#6b6f67"/><g class="cl-prop">'
         '<ellipse cx="33.5" cy="10" rx="6.5" ry="1.8" style="fill:#7cc47f"/>'
         '<ellipse cx="46.5" cy="10" rx="6.5" ry="1.8" style="fill:#7cc47f"/></g>'
         '<circle cx="40" cy="10" r="1.6" style="fill:#ffd23f"/>'),
        ""),
    "sweatband": (
        ('<rect x="19.5" y="30" width="41" height="6.5" rx="3.2" style="fill:#f7f4ec"/>'
         '<rect x="19.5" y="32.2" width="41" height="2" style="fill:#d9534f"/>'),
        ""),
    "mug": (
        ('<g class="cl-steam">'
         '<path d="M64 48 C62.5 46 65.5 44.5 64 42.5 M67.5 48 C66 46 69 44.5 67.5 42.5" stroke="#b9b4aa" stroke-width="1.2" fill="none" stroke-linecap="round"/>'
         '</g><path d="M70 53.5 C74.5 53.5 74.5 59.5 70 59.5" stroke="#f4efe6" stroke-width="2" fill="none"/>'
         '<rect x="60.5" y="50.5" width="10.5" height="11" rx="2.2" style="fill:#f4efe6" stroke="#d6d0c4" stroke-width=".8"/>'
         '<rect x="60.5" y="54" width="10.5" height="2.2" style="fill:#2f6fb5"/>'),
        ""),
    "jetpack": (
        "",
        ('<g class="cl-flame"><path d="M14 64 C12 70 15 74 16 77 C17 74 20 70 18 64 Z" style="fill:#f08a24"/>'
         '<path d="M62 64 C60 70 63 74 64 77 C65 74 68 70 66 64 Z" style="fill:#f08a24"/>'
         '<path d="M15 65 C14.4 69 15.6 71 16 72.6 C16.4 71 17.6 69 17 65 Z" style="fill:#ffd23f"/>'
         '<path d="M63 65 C62.4 69 63.6 71 64 72.6 C64.4 71 65.6 69 65 65 Z" style="fill:#ffd23f"/></g>'
         '<rect x="11" y="38" width="10" height="27" rx="5" style="fill:#aeb6bf"/>'
         '<rect x="59" y="38" width="10" height="27" rx="5" style="fill:#aeb6bf"/>'
         '<rect x="11" y="38" width="10" height="6" rx="3" style="fill:#d9534f"/>'
         '<rect x="59" y="38" width="10" height="6" rx="3" style="fill:#d9534f"/>')),
    "bowtie": (
        ('<path d="M40 59 L32.5 54.6 L32.5 63.4 Z M40 59 L47.5 54.6 L47.5 63.4 Z" style="fill:#e0457b"/>'
         '<circle cx="40" cy="59" r="2.1" style="fill:#b8325f"/>'),
        ""),
    "blush": (
        ('<path d="M27 52.58 C23.92 50.38 25.02 47.96 27 49.61 C28.98 47.96 30.08 50.38 27 52.58 Z" style="fill:#ff6f91"/>'
         '<path d="M53 52.58 C49.92 50.38 51.02 47.96 53 49.61 C54.98 47.96 56.08 50.38 53 52.58 Z" style="fill:#ff6f91"/>'),
        ""),
    "partyhat": (
        ('<g transform="rotate(10 40 28)"><path d="M31 29 L41 5 L50 29 Z" style="fill:#7b5cd6"/>'
         '<path d="M35 19.5 H46.4 M32.9 24.5 H48.3" stroke="#ffd23f" stroke-width="2.2"/>'
         '<circle cx="41" cy="5" r="3.1" style="fill:#ffd23f"/></g>'),
        ""),
    "shades": (
        ('<path d="M24.5 39 H38.5 V43.5 A5.2 5.2 0 0 1 33.3 48.7 H29.7 A5.2 5.2 0 0 1 24.5 43.5 Z M41.5 39 H55.5 V43.5 A5.2 5.2 0 0 1 50.3 48.7 H46.7 A5.2 5.2 0 0 1 41.5 43.5 Z" style="fill:#1f2328"/>'
         '<path d="M38.5 40.6 H41.5" stroke="#1f2328" stroke-width="1.8"/>'
         '<path d="M27.4 41.3 H30.6 M44.4 41.3 H47.6" stroke="#fff" stroke-opacity=".55" stroke-width="1.2" stroke-linecap="round"/>'),
        ""),
    "halo": (
        ('<ellipse cx="40" cy="15.5" rx="13" ry="3.6" fill="none" stroke="#ffe27a" stroke-width="4" stroke-opacity=".35"/>'
         '<ellipse cx="40" cy="15.5" rx="13" ry="3.6" fill="none" stroke="#ffd23f" stroke-width="2.2"/>'),
        ""),
    "balloon": (
        ('<g class="cl-bal"><path d="M65 57 C68 48 64 38 70 26" stroke="#8a8f97" stroke-width=".9" fill="none"/>'
         '<ellipse cx="71" cy="17" rx="7.4" ry="9" style="fill:#e0457b"/>'
         '<path d="M69.5 26 L71 25.5 L72.5 26 L71 27.4 Z" style="fill:#c2386a"/>'
         '<ellipse cx="68.4" cy="13" rx="1.8" ry="3" style="fill:#fff" opacity=".45"/></g>'),
        ""),
    "wings": (
        "",
        ('<g class="cl-wing cl-wl">'
         '<path d="M22 40 C12 30 3 34 4 42 C5 49 13 50 21 48 Z" style="fill:#f4f1fb" stroke="#d9d2ee" stroke-width="1"/>'
         '</g><g class="cl-wing cl-wr">'
         '<path d="M58 40 C68 30 77 34 76 42 C75 49 67 50 59 48 Z" style="fill:#f4f1fb" stroke="#d9d2ee" stroke-width="1"/>'
         '</g>')),
    "lanyard": (
        ('<path d="M27 47 L40 58 L53 47" stroke="#2f6fb5" stroke-width="1.6" fill="none"/>'
         '<rect x="35" y="57" width="10" height="8.4" rx="1.4" style="fill:#fff" stroke="#d6d0c4" stroke-width=".7"/>'
         '<rect x="36.6" y="58.6" width="3" height="3" rx=".6" style="fill:#7cc47f"/>'
         '<rect x="40.8" y="59" width="3" height=".9" style="fill:#c9c2b3"/>'
         '<rect x="36.6" y="62.6" width="6.8" height=".9" style="fill:#c9c2b3"/>'),
        ""),
    "starpin": (
        '<polygon points="51,54.5 52.1,57 54.8,57.3 52.7,59.1 53.4,61.7 51,60.3 48.6,61.7 49.3,59.1 47.2,57.3 49.9,57" style="fill:#ffd23f" stroke="#b26a00" stroke-width=".8" stroke-linejoin="round"/>',
        ""),
    "facestar": (
        '<polygon points="53.5,47.1 54.4,49.3 56.7,49.4 55,51 55.5,53.3 53.5,52 51.5,53.3 52,51 50.3,49.4 52.6,49.3" style="fill:#ffd23f" stroke="#b26a00" stroke-width=".8" stroke-linejoin="round"/>',
        ""),
    "flag": (
        ('<path d="M65 63 V31" stroke="#6b6f67" stroke-width="1.6" stroke-linecap="round"/><g class="cl-flag">'
         '<path d="M65.8 31.5 C70 30 73 34 78.5 32.5 V41.5 C73 43 70 39 65.8 40.5 Z" style="fill:#d9534f"/>'
         '<rect x="69" y="33.8" width="4.4" height="4.4" rx=".8" style="fill:#fff"/></g>'
         '<circle cx="65" cy="30.6" r="1.6" style="fill:#ffd23f"/>'),
        ""),
    "backpack": (
        '<path d="M26.5 31 V58 M53.5 31 V58" stroke="#c96a12" stroke-width="2.4" stroke-linecap="round"/>',
        ('<rect x="15" y="33" width="50" height="30" rx="9" style="fill:#e08a2a"/>'
         '<rect x="15" y="46" width="50" height="9" rx="3" style="fill:#c96a12"/>')),
    "gradcap": (
        ('<rect x="30" y="20" width="20" height="9" rx="2" style="fill:#30343b"/>'
         '<path d="M21.5 20.5 L40 12.8 L58.5 20.5 L40 28.2 Z" style="fill:#454b55"/>'
         '<path d="M40 20.5 L53 22 L53.6 30" stroke="#f2b33d" stroke-width="1.4" fill="none"/>'
         '<rect x="51.8" y="29" width="3.6" height="5.4" rx="1.2" style="fill:#f2b33d"/>'
         '<circle cx="40" cy="20.5" r="1.5" style="fill:#f2b33d"/>'),
        ""),
    "umbrella": (
        ('<path d="M64 62 V24" stroke="#5b3a29" stroke-width="1.6"/>'
         '<path d="M64 62 C64 65.5 60.5 65.5 60.5 62.6" stroke="#5b3a29" stroke-width="1.6" fill="none" stroke-linecap="round"/>'
         '<path d="M45 26 C46 13 82 13 83 26 C79.8 23 76.5 23 74 26 C71 23 67 23 64 26 C61 23 57 23 54 26 C51.5 23 48.2 23 45 26 Z" style="fill:#4f9dd6"/>'
         '<path d="M64 14.6 C60 17 58 21 59 26 C61 23.4 62.6 23.2 64 26 C65.4 23.2 67 23.4 69 26 C70 21 68 17 64 14.6 Z" style="fill:#f2c230"/>'
         '<circle cx="64" cy="13.6" r="1.4" style="fill:#5b3a29"/>'),
        ""),
    "phoenix": (
        "",
        ('<g class="cl-wing cl-wl">'
         '<path d="M22 42 C14 34 9 26 3 24 C6 30 4 34 7 38 C3 37 1 40 2 44 C6 44 9 47 12 49 C9 50 9 53 12 54 C16 52 19 50 21 48 Z" style="fill:#f08a24"/>'
         '<path d="M21 44 C16 39 13 34 9 32 C10 37 9 40 11 43 C14 45 17 47 20 47 Z" style="fill:#ffd23f"/></g>'
         '<g class="cl-wing cl-wr">'
         '<path d="M58 42 C66 34 71 26 77 24 C74 30 76 34 73 38 C77 37 79 40 78 44 C74 44 71 47 68 49 C71 50 71 53 68 54 C64 52 61 50 59 48 Z" style="fill:#f08a24"/>'
         '<path d="M59 44 C64 39 67 34 71 32 C70 37 71 40 69 43 C66 45 63 47 60 47 Z" style="fill:#ffd23f"/></g>')),
    "pencil": (
        ('<g transform="rotate(-35 66 56)">'
         '<rect x="63.5" y="40" width="5" height="22" rx="1" style="fill:#f2c230"/>'
         '<rect x="63.5" y="40" width="5" height="3.2" style="fill:#f08aa0"/>'
         '<rect x="63.5" y="43" width="5" height="1.6" style="fill:#c9ccd1"/>'
         '<path d="M63.5 62 L66 67 L68.5 62 Z" style="fill:#f4d9a6"/>'
         '<path d="M65.3 65.6 L66 67 L66.7 65.6 Z" style="fill:#2b2d29"/></g>'),
        ""),
    "magnifier": (
        ('<path d="M66.5 52.5 L62.8 59.5" stroke="#6b4b2b" stroke-width="3" stroke-linecap="round"/>'
         '<circle cx="69.5" cy="46.5" r="6.4" style="fill:rgba(200,230,255,.55)" stroke="#6b4b2b" stroke-width="2"/>'
         '<path d="M66.6 44 C67.4 42.6 68.8 41.9 70.2 41.9" stroke="#fff" stroke-width="1.2" fill="none" stroke-linecap="round"/>'),
        ""),
    "pumpkin": (
        ('<ellipse cx="40" cy="22" rx="16.5" ry="11.5" style="fill:#f08a24"/>'
         '<path d="M33.6 11.6 C29.6 16.5 29.6 27.5 33.6 32.8 M46.4 11.6 C50.4 16.5 50.4 27.5 46.4 32.8 M40 10.6 V33.4" stroke="#c96a12" stroke-width="1.4" fill="none"/>'
         '<path d="M33 22 l2.6 -3.8 l2.6 3.8 Z M41.8 22 l2.6 -3.8 l2.6 3.8 Z M33.5 26 l2.2 2 l2.2 -2 l2.2 2 l2.2 -2 l2.2 2 l2.2 -2" style="fill:#6b3204" stroke="#6b3204" stroke-width=".9" stroke-linejoin="round"/>'
         '<path d="M40 11.2 C40 8 41 6.4 43.2 5.4" stroke="#4f7a2c" stroke-width="2.6" fill="none" stroke-linecap="round"/>'
         '<path d="M42.2 8 C46 5 50.2 6.8 50.4 9.2 C47.2 10.6 44.2 10.2 42.2 8 Z" style="fill:#6aa84f"/>'),
        ""),
    "witch": (
        ('<ellipse cx="40" cy="27.6" rx="21" ry="3.8" style="fill:#3a2a55"/>'
         '<path d="M28.5 27.5 C32 20 35.5 11.5 47.5 3.5 C45 12 47 20 51.5 27.5 Z" style="fill:#4a3570"/>'
         '<path d="M30.4 23.6 C37 24.8 44 24.8 49.8 23.6 L50.8 26 C44 27.2 37 27.2 29.4 26 Z" style="fill:#f08a24"/>'
         '<rect x="37.6" y="22.8" width="4.6" height="4" rx=".8" fill="none" stroke="#ffd23f" stroke-width="1"/>'),
        ""),
    "batwings": (
        "",
        ('<g class="cl-wing cl-wl">'
         '<path d="M22 38.5 C14 30 6 31 1.5 36 C5.5 37.2 6.8 40 6 43 C9.8 41 12.2 43 12.2 46.2 C15 43.4 18.4 44.2 20.4 46.6 Z" style="fill:#2f2a3a" stroke="#7d7396" stroke-width=".9"/>'
         '</g><g class="cl-wing cl-wr">'
         '<path d="M58 38.5 C66 30 74 31 78.5 36 C74.5 37.2 73.2 40 74 43 C70.2 41 67.8 43 67.8 46.2 C65 43.4 61.6 44.2 59.6 46.6 Z" style="fill:#2f2a3a" stroke="#7d7396" stroke-width=".9"/>'
         '</g>')),
    "winter": (
        ('<path d="M19 40 C19 22 28 17 40 17 C52 17 61 22 61 40" stroke="#c8373d" stroke-width="2.2" fill="none"/>'
         '<circle cx="18.5" cy="40.5" r="5.6" style="fill:#f4efe6"/>'
         '<circle cx="61.5" cy="40.5" r="5.6" style="fill:#f4efe6"/>'
         '<rect x="44" y="57" width="7" height="14.5" rx="2.5" transform="rotate(10 47.5 57)" style="fill:#b02f35"/>'
         '<rect x="19.5" y="54.5" width="41" height="7" rx="3.5" style="fill:#c8373d"/>'
         '<path d="M26 55 v6 M34 55 v6 M42 55 v6 M50 55 v6 M57 55 v6" stroke="#fff" stroke-width="2.4"/>'),
        ""),
    "lantern": (
        ('<path d="M66 47 C66 43 70 43 70 47" stroke="#5b3a29" stroke-width="1.2" fill="none"/>'
         '<circle class="cl-glow" cx="68" cy="54" r="9" style="fill:#ffd47a" opacity=".35"/>'
         '<rect x="63.5" y="47" width="9" height="13" rx="2" style="fill:#c94f3d"/>'
         '<rect x="65" y="49" width="6" height="9" rx="1.5" style="fill:#ffd47a"/>'
         '<rect x="62.8" y="46" width="10.4" height="2" rx="1" style="fill:#5b3a29"/>'
         '<rect x="62.8" y="59.4" width="10.4" height="2" rx="1" style="fill:#5b3a29"/>'),
        ""),
    "newyear": (
        ('<g transform="rotate(-8 40 28)"><path d="M31 29 L40 5 L49 29 Z" style="fill:#e3a21a"/>'
         '<path d="M34.9 19.5 H45.1 M32.9 24.5 H47.1" stroke="#fff6d8" stroke-width="2"/>'
         '<path d="M40 5 l-3 -3 M40 5 l0 -4 M40 5 l3 -3" stroke="#e3a21a" stroke-width="1.4" stroke-linecap="round"/>'
         '</g>'),
        ""),
    "hearts": (
        ('<path d="M35 28 C34 22 31 19 29 14.5 M45 28 C46 22 49 19 51 14.5" stroke="#2b2d29" stroke-width="1.3" fill="none" stroke-linecap="round"/>'
         '<path d="M28.6 15.7 C24.400000000000002 12.7 25.900000000000002 9.4 28.6 11.65 C31.3 9.4 32.8 12.7 28.6 15.7 Z" style="fill:#e0457b"/>'
         '<path d="M51.4 15.7 C47.2 12.7 48.699999999999996 9.4 51.4 11.65 C54.1 9.4 55.599999999999994 12.7 51.4 15.7 Z" style="fill:#e0457b"/>'),
        ""),
    "flowers": (
        ('<ellipse cx="22" cy="30.5" rx="2.5" ry="1.1" transform="rotate(-60 22 30.5)" style="fill:#6aa84f"/>'
         '<ellipse cx="30" cy="25.6" rx="2.5" ry="1.1" transform="rotate(-20 30 25.6)" style="fill:#6aa84f"/>'
         '<ellipse cx="50" cy="25.6" rx="2.5" ry="1.1" transform="rotate(20 50 25.6)" style="fill:#6aa84f"/>'
         '<ellipse cx="58" cy="30.5" rx="2.5" ry="1.1" transform="rotate(60 58 30.5)" style="fill:#6aa84f"/>'
         '<circle cx="24.5" cy="25.3" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="26.6" cy="26.8" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="25.8" cy="29.3" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="23.2" cy="29.3" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="22.4" cy="26.8" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="24.5" cy="27.5" r="1.3" style="fill:#ffd23f"/>'
         '<circle cx="32.5" cy="21.2" r="1.7" style="fill:#fff"/>'
         '<circle cx="34.8" cy="22.9" r="1.7" style="fill:#fff"/>'
         '<circle cx="33.9" cy="25.5" r="1.7" style="fill:#fff"/>'
         '<circle cx="31.1" cy="25.5" r="1.7" style="fill:#fff"/>'
         '<circle cx="30.2" cy="22.9" r="1.7" style="fill:#fff"/>'
         '<circle cx="32.5" cy="23.6" r="1.4" style="fill:#ffd23f"/>'
         '<circle cx="40.0" cy="19.9" r="1.9" style="fill:#f7a6c4"/>'
         '<circle cx="42.5" cy="21.7" r="1.9" style="fill:#f7a6c4"/>'
         '<circle cx="41.5" cy="24.6" r="1.9" style="fill:#f7a6c4"/>'
         '<circle cx="38.5" cy="24.6" r="1.9" style="fill:#f7a6c4"/>'
         '<circle cx="37.5" cy="21.7" r="1.9" style="fill:#f7a6c4"/>'
         '<circle cx="40" cy="22.5" r="1.6" style="fill:#ffd23f"/>'
         '<circle cx="47.5" cy="21.2" r="1.7" style="fill:#fff"/>'
         '<circle cx="49.8" cy="22.9" r="1.7" style="fill:#fff"/>'
         '<circle cx="48.9" cy="25.5" r="1.7" style="fill:#fff"/>'
         '<circle cx="46.1" cy="25.5" r="1.7" style="fill:#fff"/>'
         '<circle cx="45.2" cy="22.9" r="1.7" style="fill:#fff"/>'
         '<circle cx="47.5" cy="23.6" r="1.4" style="fill:#ffd23f"/>'
         '<circle cx="55.5" cy="25.3" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="57.6" cy="26.8" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="56.8" cy="29.3" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="54.2" cy="29.3" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="53.4" cy="26.8" r="1.6" style="fill:#f7a6c4"/>'
         '<circle cx="55.5" cy="27.5" r="1.3" style="fill:#ffd23f"/>'),
        ""),
    "sunhat": (
        ('<ellipse cx="40" cy="28.5" rx="25" ry="5.4" style="fill:#e9cf8f"/>'
         '<path d="M28 28.5 C28 18 33 15 40 15 C47 15 52 18 52 28.5 Z" style="fill:#e9cf8f"/>'
         '<rect x="28.2" y="23.4" width="23.6" height="4" style="fill:#4f9dd6"/>'
         '<circle cx="50.5" cy="22.5" r="1.4" style="fill:#fff"/>'
         '<circle cx="52.4" cy="23.9" r="1.4" style="fill:#fff"/>'
         '<circle cx="51.7" cy="26.1" r="1.4" style="fill:#fff"/>'
         '<circle cx="49.3" cy="26.1" r="1.4" style="fill:#fff"/>'
         '<circle cx="48.6" cy="23.9" r="1.4" style="fill:#fff"/>'
         '<circle cx="50.5" cy="24.5" r="1.2" style="fill:#f08a24"/>'),
        ""),
    "piehat": (
        ('<ellipse cx="40" cy="26.4" rx="15.6" ry="4" style="fill:#b97a35"/>'
         '<path d="M25 26 C25 19.6 32 17.4 40 17.4 C48 17.4 55 19.6 55 26 Z" style="fill:#e0a24a"/>'
         '<path d="M33 21.4 l2 2 M40 20 V23 M47 21.4 l-2 2" stroke="#b97a35" stroke-width="1.2" stroke-linecap="round"/>'
         '<g class="cl-steam">'
         '<path d="M36 15 C34.8 13 37.2 11.5 36 9.6 M44 15 C42.8 13 45.2 11.5 44 9.6" stroke="#cfcac0" stroke-width="1.1" fill="none" stroke-linecap="round"/>'
         '</g>'),
        ""),
    "catears": (
        ('<path d="M23.5 31 L27.5 14.5 L37 27 Z M56.5 31 L52.5 14.5 L43 27 Z" style="fill:#2f2a3a"/>'
         '<path d="M26.6 27.6 L28.6 19.6 L33.4 26.2 Z M53.4 27.6 L51.4 19.6 L46.6 26.2 Z" style="fill:#f08fa8"/>'),
        ""),
    "cakehat": (
        ('<rect x="29" y="18" width="22" height="10" rx="2.2" style="fill:#f4c6d4"/>'
         '<path d="M29 20.4 C31 23 33 23 34.5 20.6 C36 23.2 38.6 23.2 40 20.6 C41.4 23.2 44 23.2 45.5 20.6 C47 23 49 23 51 20.4 V19.6 C51 18.6 50.4 18 49.6 18 H30.4 C29.6 18 29 18.6 29 19.6 Z" style="fill:#fff"/>'
         '<rect x="38.8" y="9.6" width="2.4" height="8.6" rx=".6" style="fill:#7fb2f0"/><g class="cl-flick">'
         '<ellipse cx="40" cy="7.6" rx="1.8" ry="2.7" style="fill:#f08a24"/>'
         '<ellipse cx="40" cy="8.2" rx=".9" ry="1.5" style="fill:#ffd23f"/></g>'),
        ""),
    "popper": (
        ('<path d="M62 61 L66 44 L71 47 Z" style="fill:#7b5cd6"/>'
         '<path d="M63.4 55 L69.6 52 M64.6 50 L70.4 49" stroke="#ffd23f" stroke-width="1.2"/>'
         '<rect x="69" y="39" width="2.2" height="2.2" rx=".4" transform="rotate(20 69 39)" style="fill:#d9534f"/>'
         '<rect x="73" y="41" width="2.2" height="2.2" rx=".4" transform="rotate(-30 73 41)" style="fill:#2f6fb5"/>'
         '<rect x="66" y="36" width="2.2" height="2.2" rx=".4" transform="rotate(45 66 36)" style="fill:#f2c230"/>'
         '<rect x="75" y="36" width="2.2" height="2.2" rx=".4" transform="rotate(10 75 36)" style="fill:#7cc47f"/>'
         '<rect x="71" y="33" width="2.2" height="2.2" rx=".4" transform="rotate(-15 71 33)" style="fill:#e0457b"/>'),
        ""),
    "dino": (
        ('<path d="M19 40 C19 24 28 17 40 17 C52 17 61 24 61 40 L57 40 C57 29 50 22.5 40 22.5 C30 22.5 23 29 23 40 Z" style="fill:#5cb878"/>'
         '<path d="M24.6 22 L28 15.5 L31.4 22 Z" style="fill:#3f8f5a"/>'
         '<path d="M30.6 18.6 L34 12.100000000000001 L37.4 18.6 Z" style="fill:#3f8f5a"/>'
         '<path d="M36.6 17.4 L40 10.9 L43.4 17.4 Z" style="fill:#3f8f5a"/>'
         '<path d="M42.6 18.6 L46 12.100000000000001 L49.4 18.6 Z" style="fill:#3f8f5a"/>'
         '<path d="M48.6 22 L52 15.5 L55.4 22 Z" style="fill:#3f8f5a"/>'
         '<circle cx="23" cy="39" r="1.2" style="fill:#fff"/><circle cx="57" cy="39" r="1.2" style="fill:#fff"/>'
         '<ellipse cx="40" cy="60" rx="11" ry="5" style="fill:#a9dbb5" opacity=".9"/>'),
        ('<path d="M54 60 C64 62 72 66 78 72 C70 71 62 70 52 67 Z" style="fill:#4fa868"/>'
         '<path d="M63 63.6 l3.4 -5 l3.4 5 Z" style="fill:#3f8f5a"/>'
         '<path d="M69 66.6 l3.4 -5 l3.4 5 Z" style="fill:#3f8f5a"/>')),
    "robot": (
        ('<path d="M40 27 V18" stroke="#8a909b" stroke-width="1.6"/>'
         '<circle class="cl-blink" cx="40" cy="16.6" r="2.6" style="fill:#d9534f"/>'
         '<rect x="15.5" y="38" width="5" height="9" rx="1.5" style="fill:#aeb6bf"/>'
         '<rect x="59.5" y="38" width="5" height="9" rx="1.5" style="fill:#aeb6bf"/>'
         '<rect x="30" y="55" width="20" height="9" rx="2" style="fill:#d7dde3"/>'
         '<circle class="cl-blink" cx="34.6" cy="59.5" r="1.6" style="fill:#7cc47f"/>'
         '<circle cx="40" cy="59.5" r="1.6" style="fill:#f2c230"/>'
         '<circle cx="45.4" cy="59.5" r="1.6" style="fill:#4f9dd6"/>'
         '<circle cx="24" cy="31" r=".9" style="fill:#8a909b"/>'
         '<circle cx="56" cy="31" r=".9" style="fill:#8a909b"/>'
         '<circle cx="24" cy="62" r=".9" style="fill:#8a909b"/>'
         '<circle cx="56" cy="62" r=".9" style="fill:#8a909b"/>'),
        ""),
    "wizard": (
        ('<ellipse cx="40" cy="28" rx="21" ry="3.8" style="fill:#3d2f74"/>'
         '<path d="M27 28 C31 19 36 10 49 2 C46 11 48 19 53 28 Z" style="fill:#4a3a8c"/>'
         '<polygon points="36,19 36.5,20.3 37.9,20.4 36.9,21.3 37.2,22.6 36,21.9 34.8,22.6 35.1,21.3 34.1,20.4 35.5,20.3" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<polygon points="44,11.4 44.4,12.4 45.5,12.5 44.7,13.2 44.9,14.3 44,13.7 43.1,14.3 43.3,13.2 42.5,12.5 43.6,12.4" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<polygon points="46,22.7 46.3,23.5 47.2,23.6 46.6,24.2 46.8,25.1 46,24.6 45.2,25.1 45.4,24.2 44.8,23.6 45.7,23.5" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<polygon points="29,56.3 29.4,57.4 30.6,57.5 29.7,58.2 30,59.4 29,58.8 28,59.4 28.3,58.2 27.4,57.5 28.6,57.4" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<polygon points="50,59.5 50.4,60.5 51.4,60.5 50.6,61.2 50.9,62.2 50,61.7 49.1,62.2 49.4,61.2 48.6,60.5 49.6,60.5" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<polygon points="41,62.8 41.3,63.6 42.1,63.6 41.5,64.2 41.7,65 41,64.5 40.3,65 40.5,64.2 39.9,63.6 40.7,63.6" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '<path d="M65 61 L72 43" stroke="#6b4b2b" stroke-width="1.8" stroke-linecap="round"/><g class="cl-flick">'
         '<polygon points="72.6,38.4 73.4,40.4 75.6,40.6 74,42 74.5,44.2 72.6,43 70.7,44.2 71.2,42 69.6,40.6 71.8,40.4" style="fill:#ffd23f" stroke-linejoin="round"/>'
         '</g>'),
        ""),
    "astronaut": (
        ('<rect x="22" y="57" width="36" height="5" rx="2.5" style="fill:#e8ecf0"/>'
         '<rect x="34" y="57" width="12" height="5" style="fill:#d9534f"/>'
         '<circle cx="40" cy="43" r="25" style="fill:rgba(205,230,255,.22)" stroke="#e1e7ee" stroke-width="2.4"/>'
         '<path d="M24 34 C27 26 33 22 40 21" stroke="#fff" stroke-width="2.4" fill="none" stroke-linecap="round" opacity=".7"/>'),
        ('<rect x="16" y="34" width="48" height="28" rx="6" style="fill:#d7dde3"/>'
         '<rect x="18.5" y="38" width="6" height="12" rx="2" style="fill:#aeb6bf"/>'
         '<rect x="55.5" y="38" width="6" height="12" rx="2" style="fill:#aeb6bf"/>')),
    "bee": (
        ('<path d="M34 28 C33 22 30 19 27 16 M46 28 C47 22 50 19 53 16" stroke="#2b2d29" stroke-width="1.3" fill="none" stroke-linecap="round"/>'
         '<circle cx="26.6" cy="15.6" r="2.4" style="fill:#2b2d29"/>'
         '<circle cx="53.4" cy="15.6" r="2.4" style="fill:#2b2d29"/>'
         '<rect x="20.4" y="55.4" width="39.2" height="4" style="fill:#f2c230"/>'
         '<rect x="21.4" y="59.4" width="37.2" height="3.6" style="fill:#2b2d29"/>'
         '<path d="M23.4 63 H56.6 C55 65 52 66 47.5 66 H32.5 C28 66 25 65 23.4 63 Z" style="fill:#f2c230"/>'),
        ('<g class="cl-wing cl-wl">'
         '<ellipse cx="13" cy="39" rx="10" ry="6.5" transform="rotate(-25 13 39)" style="fill:rgba(220,236,255,.75)" stroke="#bcd3ea" stroke-width=".8"/>'
         '</g><g class="cl-wing cl-wr">'
         '<ellipse cx="67" cy="39" rx="10" ry="6.5" transform="rotate(25 67 39)" style="fill:rgba(220,236,255,.75)" stroke="#bcd3ea" stroke-width=".8"/>'
         '</g>')),
    "doctor": (
        ('<path d="M20.6 44 L31 52 L27 66 L21 62.4 C20.6 60 20.4 56 20.4 50 Z" style="fill:#fff"/>'
         '<path d="M59.4 44 L49 52 L53 66 L59 62.4 C59.4 60 59.6 56 59.6 50 Z" style="fill:#fff"/>'
         '<rect x="51.6" y="55" width="5" height="5.4" rx=".8" style="fill:#e8ecf0"/>'
         '<path d="M54 53.4 V57" stroke="#2f6fb5" stroke-width="1.2"/>'
         '<rect x="20" y="29.6" width="40" height="3.2" rx="1.6" style="fill:#3b3f46"/>'
         '<circle cx="40" cy="27" r="5.4" style="fill:#e8ecf0" stroke="#aeb6bf" stroke-width="1.2"/>'
         '<circle cx="40" cy="27" r="2" style="fill:#aeb6bf"/>'
         '<path d="M26.5 49 C26.5 60 33 62.5 40 62.5 C47 62.5 53.5 60 53.5 49" stroke="#3b3f46" stroke-width="1.9" fill="none" stroke-linecap="round"/>'
         '<path d="M40 62.5 V65.2" stroke="#3b3f46" stroke-width="1.9"/>'
         '<circle cx="40" cy="66.3" r="2.6" style="fill:#c9ccd1" stroke="#3b3f46" stroke-width="1.3"/>'),
        ""),
    "frog": (
        ('<path d="M19.5 37 C19.5 26 28 21 40 21 C52 21 60.5 26 60.5 37 L57 37 C57 30 50 26 40 26 C30 26 23 30 23 37 Z" style="fill:#5cb878"/>'
         '<circle cx="30" cy="22" r="6.4" style="fill:#5cb878"/>'
         '<circle cx="50" cy="22" r="6.4" style="fill:#5cb878"/>'
         '<circle cx="30" cy="21.4" r="3.8" style="fill:#fff"/>'
         '<circle cx="50" cy="21.4" r="3.8" style="fill:#fff"/>'
         '<circle cx="30.6" cy="22" r="1.9" style="fill:#2b2d29"/>'
         '<circle cx="50.6" cy="22" r="1.9" style="fill:#2b2d29"/>'),
        ""),
    "detective": (
        ('<path d="M21.5 31 C21.5 20 29 15 40 15 C51 15 58.5 20 58.5 31 Z" style="fill:#a07850"/>'
         '<path d="M21.5 31 C26 33 30 33 33 31 M58.5 31 C54 33 50 33 47 31" stroke="#7a5a3a" stroke-width="3.2" fill="none" stroke-linecap="round"/>'
         '<path d="M29 17 V30" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<path d="M35 17 V30" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<path d="M41 17 V30" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<path d="M47 17 V30" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<path d="M53 17 V30" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<path d="M22 21 H58" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<path d="M22 25 H58" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<path d="M22 29 H58" stroke="#7a5a3a" stroke-width=".8" opacity=".6"/>'
         '<circle cx="40" cy="14.8" r="1.6" style="fill:#7a5a3a"/>'
         '<path d="M66.5 52.5 L62.8 59.5" stroke="#6b4b2b" stroke-width="3" stroke-linecap="round"/>'
         '<circle cx="69.5" cy="46.5" r="6.4" style="fill:rgba(200,230,255,.55)" stroke="#6b4b2b" stroke-width="2"/>'
         '<path d="M66.6 44 C67.4 42.6 68.8 41.9 70.2 41.9" stroke="#fff" stroke-width="1.2" fill="none" stroke-linecap="round"/>'),
        ""),
    # 3.9.0: the Backlog Beast's (the fun round's mock, round three)
    "viking": (
        ('<path d="M24 25 C19 22 15 16 15 9 C19 13 22 15 27 18 Z" style="fill:#f4efe6"/>'
         '<path d="M56 25 C61 22 65 16 65 9 C61 13 58 15 53 18 Z" style="fill:#f4efe6"/>'
         '<path d="M22.5 31.5 C22.5 20 30 15 40 15 C50 15 57.5 20 57.5 31.5 Z" style="fill:#9aa3ad"/>'
         '<rect x="20.5" y="27.5" width="39" height="5" rx="2.5" style="fill:#7f8892"/>'
         '<circle cx="25" cy="30" r=".9" style="fill:#c9ced4"/>'
         '<circle cx="31" cy="30" r=".9" style="fill:#c9ced4"/>'
         '<circle cx="37" cy="30" r=".9" style="fill:#c9ced4"/>'
         '<circle cx="43" cy="30" r=".9" style="fill:#c9ced4"/>'
         '<circle cx="49" cy="30" r=".9" style="fill:#c9ced4"/>'
         '<circle cx="55" cy="30" r=".9" style="fill:#c9ced4"/>'
         '<path d="M40 15 V27.5" stroke="#7f8892" stroke-width="2"/>'),
        ""),
    "beasthood": (
        ('<path d="M18.5 40 C18.5 23 28 16 40 16 C52 16 61.5 23 61.5 40 L57.5 40 C57.5 29 50 22 40 22 C30 22 22.5 29 22.5 40 Z" style="fill:#7b5cd6"/>'
         '<path d="M26 20 L28 11 L34 18 Z M54 20 L52 11 L46 18 Z" style="fill:#f2b33d"/>'
         '<circle cx="34" cy="19" r="3.4" style="fill:#fff"/>'
         '<circle cx="46" cy="19" r="3.4" style="fill:#fff"/>'
         '<circle cx="34.6" cy="19.6" r="1.6" style="fill:#241640"/>'
         '<circle cx="46.6" cy="19.6" r="1.6" style="fill:#241640"/>'
         '<path d="M26 38 l2 3 l2 -3 M50 38 l2 3 l2 -3" style="fill:#fff"/>'),
        ""),
    "knight": (
        ('<path d="M21.5 34 C21.5 21 29.5 15 40 15 C50.5 15 58.5 21 58.5 34 Z" style="fill:#aeb6bf"/>'
         '<path d="M40 15 V34" stroke="#8f98a3" stroke-width="2"/>'
         '<rect x="21.5" y="31" width="37" height="4" rx="2" style="fill:#8f98a3"/>'
         '<path d="M40 15 C44 9 49 8 54 10 C49 11 45 13 42 16 Z" style="fill:#d9534f"/>'
         '<path d="M5 45 H19 V55 C19 61 12 65 12 65 C12 65 5 61 5 55 Z" style="fill:#2f6fb5" stroke="#f2c230" stroke-width="1.4"/>'
         '<path d="M12 46.5 V62 M6.5 52 H17.5" stroke="#f2c230" stroke-width="1.6"/>'),
        ""),
    "ghost": (
        ('<path d="M16.5 70.5 L16.5 41 C16.5 27 27 21 40 21 C53 21 63.5 27 63.5 41 L63.5 70.5 Q60 66.5 56.5 70.5 Q53 66.5 49.5 70.5 Q46 66.5 42.5 70.5 Q39 66.5 35.5 70.5 Q32 66.5 28.5 70.5 Q25 66.5 21.5 70.5 Q19 67.5 16.5 70.5 Z" style="fill:#fbfbf7" stroke="#d6d6cf" stroke-width="1"/>'
         '<g class="sv-eyes"><ellipse cx="33" cy="43" rx="3.9" ry="5.4" style="fill:#2b2d29"/>'
         '<ellipse cx="47" cy="43" rx="3.9" ry="5.4" style="fill:#2b2d29"/></g>'
         '<ellipse cx="40" cy="54" rx="2.6" ry="3.2" style="fill:#2b2d29"/>'),
        ""),
    "mummy": (
        ('<path d="M22 31 L58 29" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M21 55 L59 51" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M21 60 L58 63" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M22 49 L40 55" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M44 56 L59 60" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M24 36 L30 33" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M52 34 L58 36" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M21.5 64 L33 66" stroke="#f1ece0" stroke-width="3.6" stroke-linecap="round"/>'
         '<path d="M26 30 L56 33" stroke="#e2dccd" stroke-width="1" />'),
        ""),
}
