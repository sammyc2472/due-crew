"""3.9.1: the emoji drawer behind the Cheer window's "other" (Sam: "the
other button in the emoji for cheers selector doesn't pop up with the emoji
drawer"). The window is a page on the Decks screen, which can't open the
computer's own emoji picker, so it carries its own: these, by group, each
with the words a search finds it by. Every one passes clean_emoji (the
suite checks), so any pick can be sent. Pure data; the drawing is
board.cheer_overlay_js's."""

GROUPS = (
    ("Faces", (
        ("😀", "grin happy smile"), ("😄", "smile happy joy"), ("😁", "beam grin"), ("😂", "laugh tears lol"),
        ("🤣", "rofl laugh rolling"), ("😊", "blush smile happy"), ("🙂", "smile ok"), ("😉", "wink"),
        ("😍", "love eyes heart"), ("🥰", "adore love hearts"), ("😘", "kiss love"), ("😎", "cool sunglasses"),
        ("🤓", "nerd study glasses"), ("🧐", "monocle curious"), ("🤔", "think hmm"), ("🤗", "hug"),
        ("🤩", "star struck wow amazing"), ("🥳", "party celebrate"), ("😅", "sweat phew relief"),
        ("😮‍💨", "exhale relief phew"), ("😴", "sleep tired zzz"), ("🥱", "yawn tired"), ("😤", "determined huff"),
        ("🫡", "salute respect"), ("🙃", "upside down silly"), ("😇", "angel halo good"), ("🥹", "touched tears grateful"),
        ("😭", "cry sob"), ("😬", "grimace yikes"), ("🫠", "melt"), ("🤯", "mind blown wow"), ("😱", "scream shock"),
        ("🤠", "cowboy yeehaw"), ("👻", "ghost boo"), ("💀", "skull dead"), ("🤖", "robot"), ("👽", "alien"),
    )),
    ("Hands", (
        ("👍", "thumbs up yes good"), ("👏", "clap applause bravo"), ("🙌", "raise hands hooray"), ("🙏", "thanks please pray"),
        ("🤝", "handshake deal"), ("✌️", "peace victory"), ("🤞", "fingers crossed luck"), ("🤟", "love you"),
        ("👊", "fist bump"), ("✊", "fist power"), ("💪", "strong muscle flex"), ("👋", "wave hi hello bye"),
        ("🫶", "heart hands love"), ("🤙", "call shaka"), ("👌", "ok perfect"), ("☝️", "point one"), ("🫵", "you point"),
        ("🧠", "brain smart"), ("👀", "eyes look"), ("🫂", "hug people"), ("🧑‍🎓", "student graduate"),
        ("🧑‍⚕️", "doctor health"), ("🧑‍🔬", "scientist lab"), ("🏃", "run fast"), ("🧘", "calm yoga breathe"),
        ("💃", "dance"), ("🕺", "dance disco"),
    )),
    ("Hearts", (
        ("❤️", "red heart love"), ("🧡", "orange heart"), ("💛", "yellow heart"), ("💚", "green heart"),
        ("💙", "blue heart"), ("💜", "purple heart"), ("🖤", "black heart"), ("🤍", "white heart"),
        ("💖", "sparkling heart love"), ("💞", "hearts love"), ("💯", "hundred perfect"), ("✨", "sparkles magic"),
        ("⭐", "star"), ("🌟", "glowing star shine"), ("💫", "dizzy star"), ("⚡", "lightning energy zap"),
        ("🔥", "fire lit streak hot"), ("💥", "boom bang"), ("✅", "check done yes"), ("✔️", "tick done"),
        ("🎯", "target bullseye goal"), ("🆗", "ok"), ("🆒", "cool"),
    )),
    ("Party", (
        ("🎉", "party popper tada celebrate"), ("🎊", "confetti celebrate"), ("🎈", "balloon party"),
        ("🎁", "gift present"), ("🏆", "trophy win champion"), ("🥇", "gold medal first"), ("🏅", "medal"),
        ("👑", "crown king queen"), ("🎂", "cake birthday"), ("🍾", "champagne bottle pop"), ("🥂", "cheers toast"),
        ("🎆", "fireworks"), ("🎇", "sparkler"), ("🪅", "pinata party"), ("🎵", "music note"), ("🎶", "music notes"),
        ("🎸", "guitar rock"), ("🎮", "game controller"), ("🎲", "dice game"), ("🧩", "puzzle piece"),
        ("🏁", "finish flag done"), ("🚀", "rocket launch fast"), ("🌈", "rainbow"),
    )),
    ("Study", (
        ("📚", "books study"), ("📖", "open book read"), ("📝", "memo notes write"), ("✏️", "pencil"), ("🖊️", "pen"),
        ("📓", "notebook"), ("🗂️", "cards dividers index"), ("📇", "card index flashcards"), ("🧪", "test tube lab"),
        ("🔬", "microscope science"), ("🩺", "stethoscope doctor"), ("💊", "pill pharm medicine"), ("🧬", "dna genetics"),
        ("🫀", "heart anatomy cardio"), ("🦴", "bone"), ("🧮", "abacus math"), ("📐", "ruler triangle"),
        ("💻", "laptop computer"), ("⏰", "alarm clock time"), ("⏳", "hourglass time"), ("☕", "coffee"),
        ("🍵", "tea"), ("🎧", "headphones music focus"), ("💡", "idea bulb"), ("🗓️", "calendar plan"),
        ("📈", "chart up progress"), ("🔖", "bookmark"),
    )),
    ("Nature", (
        ("🐶", "dog puppy"), ("🐱", "cat kitty"), ("🐻", "bear"), ("🐼", "panda"), ("🐨", "koala"), ("🦊", "fox"),
        ("🐸", "frog"), ("🐧", "penguin"), ("🦉", "owl wise night"), ("🐝", "bee busy"), ("🦋", "butterfly"),
        ("🐢", "turtle slow steady"), ("🐙", "octopus"), ("🦄", "unicorn magic"), ("🐉", "dragon"), ("🦖", "dino t-rex"),
        ("🐳", "whale"), ("🐬", "dolphin"), ("🐣", "chick hatch"), ("🦥", "sloth slow"), ("🙈", "monkey see no evil"),
        ("🌱", "sprout grow"), ("🌻", "sunflower"), ("🌸", "blossom flower"), ("🌷", "tulip flower"),
        ("🍀", "clover luck"), ("🌵", "cactus"), ("🌳", "tree"), ("☀️", "sun sunny"), ("🌙", "moon night"),
        ("⛅", "cloud sun"), ("🌊", "wave sea"), ("❄️", "snow cold"), ("🍂", "leaves autumn fall"),
    )),
    ("Food", (
        ("🍕", "pizza"), ("🍩", "donut doughnut"), ("🍪", "cookie"), ("🧁", "cupcake"), ("🍰", "cake slice"),
        ("🍫", "chocolate"), ("🍿", "popcorn"), ("🍦", "ice cream"), ("🍓", "strawberry"), ("🍎", "apple"),
        ("🍌", "banana"), ("🍉", "watermelon"), ("🥑", "avocado"), ("🌮", "taco"), ("🍜", "noodles ramen"),
        ("🍣", "sushi"), ("🥐", "croissant"), ("🧇", "waffle"), ("🥞", "pancakes"), ("🍔", "burger"),
        ("🍟", "fries"), ("🧋", "boba bubble tea"), ("🍋", "lemon"),
    )),
)


def view():
    """[[group, [[emoji, words], ...]], ...] for the window's JSON."""
    return [[name, [list(x) for x in items]] for name, items in GROUPS]
