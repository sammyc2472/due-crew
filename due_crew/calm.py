"""The calm board (3.9.9; Sam's pick from the review's mocks). A new person
sees Crew and Today; a part of the board stays folded until it has
something to show them, then says so in one line. Nothing is removed: Show
all opens everything, Settings › Board has the switch, and any link to a
part opens it for good.

Pure. This computer's config: `calm` (on for a new account, off for
everyone who had the board before; Settings › Board › Calm board),
`calm_open` (the parts let out, never held again) and `calm_news` (let out
by themselves and not opened yet: the board's one line)."""

PARTS = ("decks", "squads", "plans", "insights", "party")  # board.HIDEABLE_TABS' keys
INSIGHTS_DAYS = 14

# part: (the line's bold words, the rest, its button)
WORDS = {
    "decks": ("Decks is ready:", "the decks you and your crew share.", "Open"),
    "squads": ("You're in a squad.", "Its week is on Squads.", "Open"),
    "plans": ("You have a plan.", "Its days are on Plans.", "Open"),
    "insights": ("Insights is ready:", "two weeks of reviews to read.", "Open"),
}


def on(cfg):
    return bool(cfg.get("calm"))


def held(cfg):
    """The parts the calm board keeps folded for now."""
    if not on(cfg):
        return set()
    out = set(cfg.get("calm_open") or [])
    return {p for p in PARTS if p not in out}


def ready(facts):
    """The parts with something to show. facts: friends (mutual), squads,
    plans (followed or written), days (since my first review; None unknown).
    Pip Party never by itself: Tools › Due Crew › Pip Party… opens it."""
    out = []
    if int(facts.get("friends") or 0) > 0:
        out.append("decks")
    if int(facts.get("squads") or 0) > 0:
        out.append("squads")
    if int(facts.get("plans") or 0) > 0:
        out.append("plans")
    if facts.get("days") is not None and int(facts["days"]) >= INSIGHTS_DAYS:
        out.append("insights")
    return out


def release(cfg, parts, news=False):
    """Let parts out for good. news: they came by themselves, so the board
    says so once. True when anything changed (the caller saves)."""
    if not on(cfg):
        return False
    have = [p for p in (cfg.get("calm_open") or []) if p in PARTS]
    new = [p for p in parts if p in PARTS and p not in have]
    if not new:
        return False
    cfg["calm_open"] = have + new
    if news:
        cfg["calm_news"] = [p for p in (cfg.get("calm_news") or []) if p in WORDS] + [p for p in new if p in WORDS]
    return True


def seen(cfg, part=None):
    """A part opened (or the line put away: part None takes the first): its line goes. True when changed."""
    news = list(cfg.get("calm_news") or [])
    if not news:
        return False
    cfg["calm_news"] = [p for p in news if p != part] if part else news[1:]
    return cfg["calm_news"] != news


def hint(cfg):
    """The board's one line: (part, bold, rest, button), or None."""
    if not on(cfg):
        return None
    for p in cfg.get("calm_news") or []:
        if p in WORDS and p not in held(cfg):
            return (p,) + WORDS[p]
    return None


def show_all(cfg):
    cfg["calm"] = False
    cfg["calm_news"] = []
