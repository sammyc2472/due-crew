"""Crew-server directory. Always talks to the DEFAULT project, whatever
server the user is on.

A server registration is two documents on the default project:
  server_names/{name}          — browsable; proves the name is taken
  servers/{sha1(name:code)}    — the config; get-only, never listable,
                                 immutable, so a code can't be repointed.
Knowing name+code is the capability. Lookups need no account; registration
signs in anonymously (one console toggle on the default project).
"""

import datetime
import hashlib
import secrets
import string

import requests

from .firebase import (AuthError, DEFAULT_API_KEY, DEFAULT_PROJECT_ID,
                       TIMEOUT, TransportError, _fv, _parse, firestore_base)

BASE = firestore_base(DEFAULT_PROJECT_ID)

ADJECTIVES = (
    "brave quiet lucky mellow swift cosmic gentle bright rustic amber "
    "velvet crimson daring plucky sturdy breezy clever solar tidal spry "
    "nimble golden hidden mighty wandering patient curious humble bold calm"
).split()
ANIMALS = (
    "otter lantern heron walrus falcon badger dolphin magpie yak lynx "
    "gecko panda ibis newt corgi bison koala moose finch tapir "
    "hippo osprey marmot beaver puffin quokka wombat toucan seal fox"
).split()


def _now_ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key(name, code):
    return hashlib.sha1(f"{name.strip().lower()}:{code.strip().upper()}"
                        .encode()).hexdigest()


def generate_name():
    return (f"{secrets.choice(ADJECTIVES)}-{secrets.choice(ANIMALS)}"
            f"-{secrets.randbelow(9000) + 1000}")


def generate_code():
    return "".join(secrets.choice(string.ascii_uppercase + string.digits)
                   for _ in range(6))


def _req(method, url, **kw):
    try:
        return requests.request(method, url, timeout=TIMEOUT, **kw)
    except requests.RequestException:
        raise TransportError(f"directory {method} failed")


def check_project(api_key):
    """True when the pasted API key belongs to a live Firebase project with
    email auth enabled — probed with a deliberately-failing sign-in, which
    only a valid project answers with a credentials error."""
    r = _req("POST", "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword",
             params={"key": api_key},
             json={"email": "probe@example.com", "password": "probe-probe",
                   "returnSecureToken": True})
    if r.status_code == 200:
        return True
    code = (r.json() if r.content else {}).get("error", {}).get("message", "")
    return code.split(" ")[0].rstrip(":") in (
        "INVALID_LOGIN_CREDENTIALS", "EMAIL_NOT_FOUND", "INVALID_PASSWORD")


def _anonymous_token():
    r = _req("POST", "https://identitytoolkit.googleapis.com/v1/accounts:signUp",
             params={"key": DEFAULT_API_KEY},
             json={"returnSecureToken": True})
    if r.status_code != 200:
        code = (r.json() if r.content else {}).get("error", {}) \
            .get("message", "UNKNOWN")
        raise AuthError(code.split(" ")[0].rstrip(":"))
    return r.json()["idToken"]


def _create_doc(token, collection, doc_id, data):
    """Create-only write: fails on an existing doc instead of overwriting."""
    r = _req("POST", f"{BASE}/{collection}",
             params={"documentId": doc_id},
             headers={"Authorization": f"Bearer {token}"},
             json={"fields": {k: _fv(v) for k, v in data.items()}})
    return r.status_code in (200, 201), r.status_code


NAME_RE = __import__("re").compile(r"[a-z0-9][a-z0-9-]{2,39}$")


def valid_custom_name(name):
    return bool(NAME_RE.fullmatch(name))


class NameTaken(Exception):
    """A custom name already exists — the founder picks another."""


def register_server(api_key, project_id, custom_name=None):
    """Registers a founder's project. Returns (name, code).
    Raises NameTaken for an occupied custom name,
    TransportError/AuthError otherwise."""
    token = _anonymous_token()
    for _ in range(4):
        name = custom_name or generate_name()
        code = generate_code()
        fields = {"createdAt": {"timestampValue": _now_ts()}}
        if custom_name:
            fields["custom"] = True
        ok, status = _create_doc(token, "server_names", name, fields)
        if not ok:
            if status == 409:
                if custom_name:
                    raise NameTaken(name)
                continue  # generated name taken — new roll
            raise TransportError(f"name registration failed: {status}")
        ok, status = _create_doc(token, "servers", _key(name, code), {
            "apiKey": api_key,
            "projectId": project_id,
            "name": name,
            "createdAt": {"timestampValue": _now_ts()},
        })
        if not ok:
            raise TransportError(f"config registration failed: {status}")
        return name, code
    raise TransportError("couldn't find a free name")


def follow_rename(name):
    """The founder can rename a crew: the console (owner-only — rules keep
    clients create-only) adds `renamedTo` on the old server_names doc, and
    every member's add-on follows it. Returns the new name, or None."""
    r = _req("GET", f"{BASE}/server_names/{name.strip().lower()}")
    if r.status_code != 200:
        return None
    target = _parse(r.json().get("fields")).get("renamedTo")
    if not isinstance(target, str):
        return None
    target = target.strip().lower()
    if target == name or not NAME_RE.fullmatch(target):
        return None
    return target


def lookup_server(name, code):
    """{apiKey, projectId, name} or None when name+code match nothing."""
    r = _req("GET", f"{BASE}/servers/{_key(name, code)}")
    if r.status_code == 404:
        return None
    if r.status_code != 200:
        raise TransportError(f"lookup failed: {r.status_code}")
    doc = _parse(r.json().get("fields"))
    if not doc.get("apiKey") or not doc.get("projectId"):
        return None
    return {"apiKey": str(doc["apiKey"]), "projectId": str(doc["projectId"]),
            "name": str(doc.get("name") or name)}


def browse_names(limit=30):
    """Recent server names, newest first. Names only — never configs."""
    r = _req("GET", f"{BASE}/server_names",
             params={"pageSize": limit, "orderBy": "createdAt desc"})
    if r.status_code != 200:
        raise TransportError(f"browse failed: {r.status_code}")
    return [doc["name"].rsplit("/", 1)[-1]
            for doc in r.json().get("documents", [])]
