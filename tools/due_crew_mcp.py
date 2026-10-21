#!/usr/bin/env python3
"""Due Crew's AI app shim (docs/planner.md, Your AI app): an AI app that
starts a program for its tools (stdio) talks to the Due Crew add-on's local
server in Anki through this. Each JSON-RPC line on stdin goes to
http://127.0.0.1:PORT/mcp with the token; each answer comes back as one line
on stdout (none for a notification). When Anki isn't running, or Your AI app
is off in it, it says so on stderr and answers each request with an error.
Standard library only; it logs nothing, the token least of all.

    python3 -I due_crew_mcp.py --port N          (the token in DUE_CREW_MCP_TOKEN)
    python3 -I due_crew_mcp.py --port N --token T

Anki's Your AI app window copies the setup, with this file's path in the
add-on (due_crew/planner/mcp_shim.py there; tools/due_crew_mcp.py is the
same file, byte for byte)."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT = 180  # a tool may wait on Anki's main thread, or read a big deck's tags


def _say(words):
    sys.stderr.write(f"due-crew: {words}\n")
    sys.stderr.flush()


def _error(mid, words, code=-32000):
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": words}}


def _waiting(msg):
    """The ids a message waits on answers for (a notification waits on none)."""
    items = msg if isinstance(msg, list) else [msg]
    return [m.get("id") for m in items if isinstance(m, dict) and "id" in m and "method" in m]


def _errors(msg, words):
    ids = _waiting(msg)
    if not ids:
        return []
    errs = [_error(i, words) for i in ids]
    return [errs] if isinstance(msg, list) else errs


def forward(line, url, token, opener):
    """The answers for one line from stdin: [] for a notification."""
    try:
        msg = json.loads(line)
    except ValueError:
        return [_error(None, "That isn't JSON.", -32700)]
    req = urllib.request.Request(url, data=line.encode("utf-8"), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}"})
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status = e.code
        words = {401: "Due Crew's token doesn't match. Copy the setup again from Anki (Your AI app).",
                 403: "Due Crew turned this away: it takes requests from this computer only.",
                 413: "That's more than Due Crew takes at once."}.get(status, f"Due Crew answered {status}.")
        _say(words)
        return _errors(msg, words)
    except (urllib.error.URLError, OSError):
        words = "Anki isn't running, or Your AI app is off in it."
        _say(words)
        return _errors(msg, words)
    if status == 202 or not body.strip():
        return []
    try:
        return [json.loads(body.decode("utf-8"))]
    except ValueError:
        return _errors(msg, "Due Crew's answer didn't read.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Due Crew's AI app shim: stdio to the add-on's local server in Anki.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("DUE_CREW_MCP_PORT") or 0))
    ap.add_argument("--token", default=os.environ.get("DUE_CREW_MCP_TOKEN") or "")
    a = ap.parse_args(argv)
    if not a.port or not a.token:
        _say("it needs the port and the token (--port, and --token or DUE_CREW_MCP_TOKEN): "
             "Anki's Your AI app copies them.")
        return 2
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    url = f"http://127.0.0.1:{a.port}/mcp"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # this computer: never through a proxy
    while True:
        line = sys.stdin.readline()
        if not line:
            return 0
        if not line.strip():
            continue
        for answer in forward(line.strip(), url, a.token, opener):
            sys.stdout.write(json.dumps(answer, separators=(",", ":")) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
