"""Labs (docs/planner.md): the plan window's requests, each one on a click,
off the main thread (they raise TransportError like every request). All of
them are routes the site's builder uses already: nothing new on the server.

Who may open the window is asked of the server (GET /auth/me says admin for
the admin's account, worker/src/notices.isAdmin); the window opens only for
that account. A save is the builder's: PUT /plans/{id} with the version it
started from; the server keeps what only the author's Anki sends.
"""

import json

from ..backend.shapes import TransportError, clean_plan

# a refused save, in words (builder.js SAVE_ERRORS, as the window says them)
SAVE_WORDS = {
    "bad_plan": "The plan didn't take that change.",
    "not_author": "You're not one of this plan's authors any more.",
    "no_plan": "This plan was deleted.",
    "too_big": "The plan is too big to save.",
    "slow_down": "That's a lot of saves today. Try again tomorrow.",
}


def is_admin(client):
    """True for the admin's account (GET /auth/me's admin), else False."""
    status, data = client._call("GET", "/auth/me")
    return status == 200 and data.get("admin") is True


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


def save(client, pid, version, doc, summary):
    """("saved", raw) | ("stale", raw now) | ("refused", words). A save whose
    answer was lost on the way and sent again comes back stale, because the
    first one landed: one whose doc is the plan's now is "saved"."""
    from .edits import lean
    body = {"version": int(version), "doc": lean(doc), "summary": str(summary)[:120]}
    status, data = client._call("PUT", f"/plans/{pid}", body)
    if status == 200 and isinstance(data.get("doc"), dict):
        return "saved", data
    if status == 409 and data.get("error") == "stale":
        raw, _plan = load(client, pid)
        return ("saved" if _canon(raw.get("doc")) == _canon(doc) else "stale"), raw
    return "refused", SAVE_WORDS.get(str(data.get("error") or ""), "That didn't save. Try again.")
