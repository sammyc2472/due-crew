"""Your plans (docs/planner.md): the plan window's requests, each one on a click,
off the main thread (they raise TransportError like every request). All of
them are routes the site's builder uses already: nothing new on the server.

Anyone signed in opens the window (3.9.3); what each may change is the
server's to say, as it says it to the site. A save is the builder's: PUT
/plans/{id} with the version it started from; the server keeps what only
the author's Anki sends.
"""

import json

from ..backend.shapes import TransportError, clean_plan
from .edits import _cut

# a refused save, in words (builder.js SAVE_ERRORS, as the window says them)
SAVE_WORDS = {
    "plans_full": "Your plans hold as much as one account can. Make this one smaller, or delete a plan.",
    "bad_plan": "The plan didn't take that change.",
    "bad_name": "A date or an event has no name. Name it, then save.",
    "not_author": "You're not one of this plan's authors any more.",
    "no_plan": "This plan was deleted.",
    "too_big": "The plan is too big to save.",
    "slow_down": "That's a lot of saves today. Try again tomorrow.",
    "too_many_plans": "You have 50 plans, as many as one account keeps. Delete one first (its Settings › Delete this plan…).",
    "nothing_to_undo": "There's nothing to undo.",
}


def _refused(data):
    return "refused", SAVE_WORDS.get(str((data or {}).get("error") or ""), "That didn't save. Try again.")


def _call(client, method, path, body=None):
    """(status, data); a 429 (a ceiling, which the client raises as no
    answer) said as the server's slow_down."""
    try:
        return client._call(method, path, body) if body is not None else client._call(method, path)
    except TransportError as e:
        if getattr(e, "status", None) == 429:
            return 429, {"error": "slow_down"}
        raise


def my_plans(client):
    """[plan]: the plans I write and the ones I follow (GET /plans/mine),
    cleaned, each with its role; a date's single cards and ids left out."""
    return client.my_plans()


def load(client, pid):
    """(raw, plan): one plan as the server keeps it (GET /plans/{id}): raw,
    its every field for a save, and plan, cleaned for reading."""
    status, data = client._call("GET", f"/plans/{pid}")
    if status != 200 or not isinstance(data.get("doc"), dict):
        raise TransportError(f"plan: {status}", status)
    plan = clean_plan(data)
    if plan is None:
        raise TransportError("plan: unreadable", status)
    return data, plan


def _canon(doc):
    """A doc as two saves of it compare: what a save sends (edits.lean), its
    dates by id, keys in order."""
    from .edits import lean
    d = lean(doc or {})
    d["units"] = sorted(d.get("units") or [], key=lambda u: str(u.get("id")))
    for u in d["units"]:
        u.pop("n", None)  # the author's count: the same save, counted again
    return json.dumps(d, sort_keys=True)


def save(client, pid, version, doc, summary, post=None):
    """("saved", raw) | ("stale", raw now) | ("refused", words). A save whose
    answer was lost on the way and sent again comes back stale, because the
    first one landed: one whose doc is the plan's now is "saved". post
    (round five's send): one line to followers that goes with the save
    (plans.ts POST_MAX, five a day a plan; past them the save still goes)."""
    from .edits import lean
    body = {"version": int(version), "doc": lean(doc), "summary": str(summary)[:120]}
    line = " ".join(str(post or "").split())[:200]
    if line:
        body["post"] = line
    status, data = _call(client, "PUT", f"/plans/{pid}", body)
    if status == 200 and isinstance(data.get("doc"), dict):
        return "saved", data
    if status == 409 and data.get("error") == "stale":
        raw, _plan = load(client, pid)
        return ("saved" if _canon(raw.get("doc")) == _canon(doc) else "stale"), raw
    return _refused(data)


def undo(client, pid, version):
    """The builder's Undo: what the latest save replaced, back (POST
    /plans/{id}/undo, from the version it started at). ("saved", raw) |
    ("stale", raw now) | ("refused", words)."""
    status, data = _call(client, "POST", f"/plans/{pid}/undo", {"version": int(version)})
    if status == 200 and isinstance(data.get("doc"), dict):
        return "saved", data
    if status == 409 and data.get("error") == "stale":
        return "stale", load(client, pid)[0]
    return _refused(data)


def log(client, pid):
    """The builder's History: every save, newest first (GET /plans/{id}/log):
    [{version, uid, name, at, summary, undo}], the latest one undoable."""
    status, data = _call(client, "GET", f"/plans/{pid}/log")
    if status != 200 or not isinstance(data.get("log"), list):
        raise TransportError(f"log: {status}", status)
    return [x for x in data["log"] if isinstance(x, dict)]


def posts(client, pid):
    """The builder's Updates: what the authors said to followers, newest first (GET /plans/{id}/posts)."""
    status, data = _call(client, "GET", f"/plans/{pid}/posts")
    if status != 200 or not isinstance(data.get("posts"), list):
        raise TransportError(f"posts: {status}", status)
    return [x for x in data["posts"] if isinstance(x, dict)]


POST_WORDS = {"too_many_posts": "Five posts a day per plan. Try tomorrow.", "slow_down": "Five posts a day per plan. Try tomorrow.",
              "bad_post": "A post is one line, 200 characters at most.", "not_author": SAVE_WORDS["not_author"]}


def post(client, pid, text):
    """A post to the plan's followers (POST /plans/{id}/posts): ("saved", {id, text}) | ("refused", words)."""
    status, data = _call(client, "POST", f"/plans/{pid}/posts", {"text": str(text)})
    if status == 200 and data.get("id"):
        return "saved", data
    return "refused", POST_WORDS.get(str((data or {}).get("error") or ""), "That didn't post. Try again.")


def unpost(client, pid, post_id):
    """A post taken back (DELETE /plans/{id}/posts/{post}): its writer's, or the owner's. True when it went."""
    status, _data = _call(client, "DELETE", f"/plans/{pid}/posts/{int(post_id)}")
    return status == 200


NOTE_WORDS = {"too_many_notes": "That's as many notes as this plan holds from you. Remove one first.",
              "authors_only": "On a plan in the library, only its authors write notes.",
              "slow_down": "That's a lot of notes. Try again in an hour.",
              "bad_note": "A note is one line, 280 characters at most."}


def notes(client, pid):
    """Notes on days (GET /plans/{id}/notes), from anyone in the plan, oldest
    first: [{id, uid, name, day, text, at, mine, remove}]. Raises when it can't."""
    status, data = _call(client, "GET", f"/plans/{pid}/notes")
    if status != 200 or not isinstance(data.get("notes"), list):
        raise TransportError(f"notes: {status}", status)
    return [x for x in data["notes"] if isinstance(x, dict) and x.get("id") and isinstance(x.get("day"), str)]


def add_note(client, pid, day, text):
    """A note on a day (POST /plans/{id}/notes): ("saved", {id, day, text}) | ("refused", words)."""
    status, data = _call(client, "POST", f"/plans/{pid}/notes", {"day": str(day), "text": str(text)})
    if status == 200 and data.get("id"):
        return "saved", data
    return "refused", NOTE_WORDS.get(str((data or {}).get("error") or ""), "That note didn't post. Try again.")


def remove_note(client, pid, note_id):
    """A note taken off (DELETE /plans/{id}/notes/{note}): its writer's, or an author's. True when it went."""
    status, _data = _call(client, "DELETE", f"/plans/{pid}/notes/{int(note_id)}")
    return status == 200


# the builder's Settings, said as it says them
SETTINGS_WORDS = dict(SAVE_WORDS, **{
    "not_owner": "Only its owner changes that.",
    "bad_squad": "That squad isn't one of yours.",
    "too_many_listed": "You have 20 plans in the library. Take one out first.",
    "squad_plan": "Only a plan anyone with the code can follow goes in the library.",
    "no_dates": "Put some dates on it first.",
    "taken_out": "It was taken out of the library. Send feedback if that's a mistake.",
    "too_many_editors": "A plan has up to 10 co-authors.",
    "not_crew": "Co-authors come from your crew: you add each other.",
    "not_coauthor": "Only a co-author who said yes can be handed it.",
    "slow_down": "That's a lot of changes for now. Try again later.",
})


def _view(status, data):
    if status == 200 and isinstance(data.get("doc"), dict) and data.get("id"):
        return "saved", data
    return "refused", SETTINGS_WORDS.get(str((data or {}).get("error") or ""), "That didn't work. Try again.")


def save_meta(client, pid, version, fields, summary):
    """The builder's Settings saved: its name, line, who can follow and its
    squad (PUT /plans/{id} without the doc). ("saved", raw) | ("stale", raw
    now) | ("refused", words)."""
    body = dict({k: v for k, v in fields.items() if k in ("name", "line", "audience", "squad")},
                version=int(version), summary=str(summary)[:120])
    status, data = _call(client, "PUT", f"/plans/{pid}", body)
    if status == 409 and data.get("error") == "stale":
        return "stale", load(client, pid)[0]
    return _view(status, data)


def set_listed(client, pid, on):
    """In the library, or out (PUT /plans/{id}/listed, the owner's)."""
    return _view(*_call(client, "PUT", f"/plans/{pid}/listed", {"listed": bool(on)}))


def copy(client, pid, start):
    """A plan of my own from this one, its first date on `start` (POST /plans/{id}/copy)."""
    return _view(*_call(client, "POST", f"/plans/{pid}/copy", {"start": str(start)}))


def delete(client, pid):
    """The owner takes the plan down (DELETE /plans/{id}); followers keep what's open. True when it went."""
    status, _data = _call(client, "DELETE", f"/plans/{pid}")
    return status == 200


def crew(client):
    """My crew, the people a co-author comes from: [(uid, name)], mutual friends (GET /friends)."""
    status, data = _call(client, "GET", "/friends")
    if status != 200:
        raise TransportError(f"friends: {status}", status)
    return [(str(f["uid"]), str(f.get("name") or "?")) for f in data.get("friends") or []
            if isinstance(f, dict) and f.get("uid") and f.get("mutual")]


def add_editor(client, pid, uid):
    """Ask one of my crew to co-write it (POST /plans/{id}/editors): they say yes first."""
    return _view(*_call(client, "POST", f"/plans/{pid}/editors", {"uid": str(uid)}))


def remove_editor(client, pid, uid):
    """A co-author off it, an invite taken back, or me leaving (DELETE /plans/{id}/editors/{uid}). True when done."""
    status, _data = _call(client, "DELETE", f"/plans/{pid}/editors/{uid}")
    return status == 200


def offer(client, pid, uid):
    """Hand it to a co-author who said yes, or take the offer back (uid None): POST /plans/{id}/owner."""
    return _view(*_call(client, "POST", f"/plans/{pid}/owner", {"uid": uid}))


def create(client, name, deck):
    """A new plan, no dates yet, mine (POST /plans, the builder's New plan):
    ("saved", raw) | ("refused", words)."""
    status, data = _call(client, "POST", "/plans", {"name": _cut(" ".join(str(name).split()), 60), "deck": str(deck)})
    if status == 200 and isinstance(data.get("doc"), dict) and data.get("id"):
        return "saved", data
    return _refused(data)
