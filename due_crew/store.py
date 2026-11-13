"""3.9.12, one way to keep a file (the foundations round: ten modules each
wrote their own JSON file, each a little differently). Standard library
only, no Anki: anything may import it.

A file is written whole to `<path>.tmp`, then swapped in: a crash mid-write
leaves the old file, never half of one (half a file loads as nothing, and
took wrap.json's all-time totals with it once). A write that fails takes
its .tmp with it and says so (False): the caller decides what that means.

`load`/`save` are for a file kept in memory between reads: the caller owns
a cache ({"path", "data", "disk"}); a new path (another profile) reads
again, and a save writes only when the text differs from what's on disk.
"""

import json
import os


def write_text(path, text, private=False):
    """Text to a file, whole then swapped in. private: mine alone from the
    first byte (0600: a session token's file). True when it's there."""
    tmp = str(path) + ".tmp"
    try:
        if private:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            f = os.fdopen(fd, "w", encoding="utf-8")
        else:
            f = open(tmp, "w", encoding="utf-8")
        with f:
            f.write(text)
        if private:
            os.chmod(tmp, 0o600)  # an older .tmp kept its own mode
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def write_json(path, data, private=False, **dumps):
    """`data` as JSON, whole then swapped in. True when it's there."""
    return write_text(path, json.dumps(data, **dumps), private=private)


def read_json(path, default=None):
    """(what the file holds, its text). A file that's missing, unreadable or
    not a JSON object gives (default, None): a dict is the only shape kept."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        got = json.loads(text)
    except (OSError, ValueError):
        return default, None
    return (got, text) if isinstance(got, dict) else (default, None)


def load(cache, path, ok=None, empty=dict):
    """The file's data, kept in `cache` till the path changes. ok(data):
    whether what was read is the right shape (else empty()). The dict
    returned is the cache's own: change it, then save()."""
    path = str(path)
    if cache.get("path") != path or cache.get("data") is None:
        got, text = read_json(path)
        good = got is not None and (ok is None or ok(got))
        cache.update(path=path, data=got if good else empty(), disk=text if good else None)
    return cache["data"]


def save(cache):
    """Write the cache's data when it says something the file doesn't.
    True when the file holds it (written now, or already)."""
    if cache.get("path") is None or cache.get("data") is None:
        return False
    text = json.dumps(cache["data"])
    if cache.get("disk") == text:
        return True
    if write_text(cache["path"], text):
        cache["disk"] = text
        return True
    return False
