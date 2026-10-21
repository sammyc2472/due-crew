"""The Mac's own language model, for the course PoC. Three ways in:

- helper: helper.swift, built on this Mac with swiftc (Xcode or its Command
  Line Tools) on Apple's FoundationModels framework (macOS 26 and later).
  Guided generation: every answer comes back in the shape asked for. Kept
  running between calls, so the model loads once.
- fm: the `fm` command macOS 27 ships. Its flags aren't settled in Apple's
  docs yet, so it gets plain text with the shape in words, and the answer is
  read as JSON and checked here.
- none: no model. Each job falls back to plain rules (jobs.py), so the
  whole flow runs anywhere and the model can be measured against them.

On-device only: nothing here asks for Private Cloud Compute, and nothing
leaves the computer. No aqt import: the tests run this with fakes."""

import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER_SRC = os.path.join(HERE, "helper.swift")
# built in this order, the first that compiles kept: the model with the
# guardrails for transforming text (card text about drugs, toxins, injuries;
# Apple applies them to plain-text answers), and its context size in the
# probe; then without what an older SDK lacks
PERMISSIVE = "SystemLanguageModel(useCase: .general, guardrails: .permissiveContentTransformations)"
VARIANTS = [(PERMISSIVE, "model.contextSize", "permissive"), ("SystemLanguageModel.default", "model.contextSize", "default"),
            (PERMISSIVE, "0", "permissive"), ("SystemLanguageModel.default", "0", "default")]


class ModelError(Exception):
    """A call that didn't give an answer: kind is "timeout", "context",
    "guardrail", "unavailable", "shape" or "error"."""

    def __init__(self, msg, kind="error"):
        super().__init__(msg)
        self.kind = kind


def kind_of(msg):
    m = str(msg).lower()
    if "context" in m and ("exceed" in m or "window" in m):
        return "context"
    if "guardrail" in m or "unsafe" in m:
        return "guardrail"
    if "unavailable" in m or "not enabled" in m or "notready" in m or "not ready" in m:
        return "unavailable"
    return "error"


# ---- schemas: a small subset both runners read ----

def obj(name, props):
    """props: [(name, schema)] or [(name, schema, description)]."""
    return {"type": "object", "name": name,
            "props": [{"name": p[0], "schema": p[1], **({"description": p[2]} if len(p) > 2 else {})} for p in props]}


def arr(items, max=None):
    s = {"type": "array", "items": items}
    if max:
        s["max"] = int(max)
    return s


def string(enum=None):
    return {"type": "string", **({"enum": list(enum)} if enum else {})}


def integer():
    return {"type": "integer"}


def boolean():
    return {"type": "boolean"}


def example(s):
    """The shape in words, for a runner without guided generation:
    {"terms": ["…"]}."""
    t = s.get("type")
    if t == "object":
        return "{" + ", ".join(f'"{p["name"]}": {example(p["schema"])}' for p in s["props"]) + "}"
    if t == "array":
        return "[" + example(s["items"]) + ", …]"
    if t == "integer":
        return "1"
    if t == "boolean":
        return "true"
    if s.get("enum"):
        return '"' + "|".join(s["enum"]) + '"'
    return '"…"'


def conform(v, s):
    """v made to fit the schema, or ModelError("shape"): numbers from
    strings, an enum read case-blind, a list cut at its max, an object's
    missing list empty. Every runner's answer passes through here."""
    t = s.get("type")
    if t == "object":
        if not isinstance(v, dict):
            raise ModelError(f"wanted an object, got {type(v).__name__}", "shape")
        out = {}
        for p in s["props"]:
            k, sub = p["name"], p["schema"]
            if k not in v or v[k] is None:
                if sub.get("type") == "array":
                    out[k] = []
                    continue
                if p.get("optional"):
                    continue
                raise ModelError(f"missing {k}", "shape")
            out[k] = conform(v[k], sub)
        return out
    if t == "array":
        if isinstance(v, dict) and len(v) == 1:
            v = next(iter(v.values()))  # {"terms": [...]} where a list was wanted
        if not isinstance(v, list):
            v = [v]
        items = []
        for x in v:
            try:
                items.append(conform(x, s["items"]))
            except ModelError:
                continue  # one bad item drops, not the answer
        return items[:s["max"]] if s.get("max") else items
    if t == "integer":
        if isinstance(v, bool):
            raise ModelError("wanted a number", "shape")
        if isinstance(v, (int, float)):
            return int(v)
        m = re.search(r"-?\d+", str(v))
        if not m:
            raise ModelError("wanted a number", "shape")
        return int(m.group())
    if t == "boolean":
        if isinstance(v, bool):
            return v
        w = str(v).strip().lower()
        if w in ("true", "yes", "y", "1"):
            return True
        if w in ("false", "no", "n", "0"):
            return False
        raise ModelError("wanted true or false", "shape")
    w = str(v).strip()
    if s.get("enum"):
        low = {e.lower(): e for e in s["enum"]}
        if w.lower() not in low:
            raise ModelError(f"{w!r} isn't one of {s['enum']}", "shape")
        return low[w.lower()]
    return w


def json_in(text):
    """The first JSON object in a model's text (inside ``` fences or not)."""
    t = str(text or "")
    i = t.find("{")
    while i >= 0:
        depth, quote, esc = 0, False, False
        for j in range(i, len(t)):
            ch = t[j]
            if quote:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    quote = False
            elif ch == '"':
                quote = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(t[i:j + 1])
                    except ValueError:
                        break
        i = t.find("{", i + 1)
    raise ModelError("no JSON in the answer", "shape")


# ---- the log (this computer only) ----

class Log:
    """One line a call: when, which job, how long, how it went. Card text
    only with verbose on, and the file stays in the add-on's user_files."""

    def __init__(self, path=None, verbose=False, keep=None):
        self.path, self.verbose = path, verbose
        self.keep = keep  # a list the window reads, or None
        self._lock = threading.Lock()

    def __call__(self, line, detail=None):
        stamp = time.strftime("%H:%M:%S")
        text = f"{stamp} {line}"
        if self.verbose and detail:
            text += "\n" + str(detail)[:4000]
        with self._lock:
            if self.keep is not None:
                self.keep.append(f"{stamp} {line}")
                del self.keep[:-400]
            if self.path:
                try:
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(text + "\n")
                except OSError:
                    pass


def _nolog(*_a, **_k):
    pass


# ---- runners ----

class Runner:
    name = "none"
    label = "No model"
    guided = False

    def available(self):
        return False, "No model chosen."

    def ask(self, job, instructions, prompt, schema, max_tokens=None, timeout=None):
        raise ModelError("no model", "unavailable")

    def close(self):
        pass


class NoModel(Runner):
    pass


class HelperRunner(Runner):
    """helper.swift, built here and kept running."""
    name = "helper"
    label = "Mac model (built helper)"
    guided = True

    def __init__(self, folder, log=_nolog, timeout=90):
        self.folder = folder
        self.bin = os.path.join(folder, "course_mac_helper")
        self.stamp = self.bin + ".stamp"
        self.log, self.timeout = log, timeout
        self.proc = None
        self.lines = queue.Queue()
        self.lock = threading.Lock()
        self.n = 0
        self.first = True

    def source_hash(self):
        with open(HELPER_SRC, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()[:12]

    def built(self):
        if not os.path.exists(self.bin):
            return False
        try:
            with open(self.stamp) as f:
                return f.read().split()[0] == self.source_hash()
        except (OSError, IndexError):
            return False

    @staticmethod
    def swiftc():
        """(the compiler's path or None, what xcrun said when it found none)."""
        said = ""
        try:
            r = subprocess.run(["xcrun", "--find", "swiftc"], capture_output=True, text=True, timeout=30)
            p = r.stdout.strip()
            if r.returncode == 0 and p and os.path.exists(p):
                return p, ""
            said = r.stderr or r.stdout
        except (OSError, subprocess.SubprocessError):
            pass
        return shutil.which("swiftc"), said

    def build(self):
        """(ok, what happened). Main thread or not; takes a minute or two."""
        swiftc, said_xcrun = self.swiftc()
        if license_blocked(said_xcrun):
            return False, license_help()
        if not swiftc:
            return False, ("No Swift compiler on this Mac. Install Apple's Command Line Tools "
                           "(run `xcode-select --install` in Terminal), then Build again." + _fm_note())
        os.makedirs(self.folder, exist_ok=True)
        with open(HELPER_SRC, encoding="utf-8") as f:
            src = f.read()
        said = []
        for i, (m, ctx, kind) in enumerate(VARIANTS):
            path = os.path.join(self.folder, "course_mac_helper.swift")
            with open(path, "w", encoding="utf-8") as f:
                f.write(src.replace("__MODEL__", m).replace("__CONTEXT__", ctx))
            try:
                r = subprocess.run([swiftc, "-O", path, "-o", self.bin], capture_output=True, text=True, timeout=900)
            except (OSError, subprocess.SubprocessError) as e:
                return False, f"swiftc didn't run: {e}"
            if license_blocked(r.stderr or r.stdout):
                return False, license_help()  # every variant would say the same
            if r.returncode == 0:
                self.close()
                with open(self.stamp, "w") as f:
                    f.write(f"{self.source_hash()} {kind}\n")
                said.append(f"Built ({kind} guardrails{'' if ctx != '0' else ', no context size'}).")
                return True, " ".join(said)
            said.append(f"Variant {i + 1} didn't build:\n{(r.stderr or r.stdout)[-1200:]}")
        return False, "\n\n".join(said)

    def guardrails(self):
        try:
            with open(self.stamp) as f:
                return (f.read().split() + ["", ""])[1]
        except OSError:
            return ""

    def _start(self):
        if self.proc and self.proc.poll() is None:
            return
        if not self.built():
            raise ModelError("the helper isn't built yet (Settings › Build the helper)", "unavailable")
        self.proc = subprocess.Popen([self.bin], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.lines = queue.Queue()
        self.first = True
        out = self.proc.stdout

        def read():
            for line in out:
                self.lines.put(line)
            self.lines.put(None)
        threading.Thread(target=read, daemon=True).start()

    def _send(self, req, timeout):
        with self.lock:
            self._start()
            self.n += 1
            req = dict(req, id=self.n)
            try:
                self.proc.stdin.write(json.dumps(req) + "\n")
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:
                self.close()
                raise ModelError(f"the helper stopped: {e}")
            end = time.time() + timeout
            while True:
                left = end - time.time()
                if left <= 0:
                    self.close()  # a stuck call: start fresh next time
                    raise ModelError(f"no answer in {timeout:.0f} s", "timeout")
                try:
                    line = self.lines.get(timeout=left)
                except queue.Empty:
                    continue
                if line is None:
                    self.close()
                    raise ModelError("the helper stopped")
                try:
                    got = json.loads(line)
                except ValueError:
                    continue
                if got.get("id") == self.n:
                    return got

    def available(self):
        if not self.built():
            return False, "The helper isn't built on this Mac yet."
        try:
            got = self._send({"op": "probe"}, 30)
        except ModelError as e:
            return False, str(e)
        if not got.get("ok"):
            return False, str(got.get("error"))
        if not got.get("available"):
            return False, f"Apple Intelligence isn't ready: {got.get('reason')}"
        ctx = int(got.get("context") or 0)
        return True, f"Ready ({self.guardrails()} guardrails" + (f", a {ctx:,}-token window)." if ctx else ").")

    def ask(self, job, instructions, prompt, schema, max_tokens=None, timeout=None):
        t = timeout or self.timeout
        if self.first:
            t = max(t, 180)  # the model loads on the first call
        got = self._send({"op": "ask", "instructions": instructions, "prompt": prompt, "schema": schema,
                          "max_tokens": max_tokens}, t)
        self.first = False
        if not got.get("ok") and schema and kind_of(got.get("error")) == "guardrail":
            # refused with the shape: once more as plain text, which the
            # permissive guardrails cover, the shape in words, read here
            self.log(f"{job}: guardrail with the shape; again as plain text")
            text = f"{prompt}\n\nAnswer with JSON only, nothing else, shaped like this:\n{example(schema)}"
            got = self._send({"op": "ask", "instructions": instructions, "prompt": text, "schema": None,
                              "max_tokens": max_tokens}, t)
            if got.get("ok"):
                return conform(json_in(got.get("text")), schema), got.get("ms"), got.get("text")
        if not got.get("ok"):
            raise ModelError(str(got.get("error")), kind_of(got.get("error")))
        raw = got.get("json") if schema else got.get("text")
        try:
            value = json.loads(raw) if schema else raw
        except (TypeError, ValueError):
            value = json_in(raw)
        return (conform(value, schema) if schema else value), got.get("ms"), raw

    def pdf_text(self, path):
        got = self._send({"op": "pdf", "path": path}, 60)
        if not got.get("ok"):
            raise ModelError(str(got.get("error")))
        return str(got.get("text") or "")

    def close(self):
        p, self.proc = self.proc, None
        if p:
            try:
                p.kill()
                p.wait(timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
            for pipe in (p.stdin, p.stdout):
                try:
                    pipe.close()
                except (OSError, AttributeError):
                    pass


def license_blocked(text):
    """A full Xcode whose license was never accepted: Apple's tools (xcrun,
    swiftc) refuse to run, and say so, until someone accepts it once."""
    t = (text or "").lower()
    return "license" in t and ("xcodebuild" in t or "agree" in t)


def _fm_note():
    return ("\n\nOr skip the helper: this Mac has the fm command, and Model \u203a Auto uses it "
            "with nothing to build." if FmRunner().path else "")


def license_help():
    """What to do about license_blocked, in a few words."""
    return ("Apple's developer tools need their license accepted once. In Terminal, run\n"
            "    sudo xcodebuild -license accept\n"
            "and type your Mac's password, then Build again." + _fm_note())


class FmRunner(Runner):
    """The `fm` command (macOS 27). Plain text in; the answer read as JSON."""
    name = "fm"
    label = "Mac model (fm command)"

    def __init__(self, log=_nolog, timeout=90, schema_flag=False):
        self.log, self.timeout = log, timeout
        self.schema_flag = schema_flag
        self.path = shutil.which("fm") or ("/usr/bin/fm" if os.path.exists("/usr/bin/fm") else None)

    def help_text(self):
        out = []
        for args in (["--help"], ["respond", "--help"]):
            try:
                r = subprocess.run([self.path] + args, capture_output=True, text=True, timeout=20)
                out.append(f"$ fm {' '.join(args)}\n{(r.stdout or r.stderr)[:3000]}")
            except (OSError, subprocess.SubprocessError, TypeError) as e:
                out.append(f"$ fm {' '.join(args)}\n{e}")
        return "\n\n".join(out)

    def available(self):
        if not self.path:
            return False, "No fm command on this Mac (it comes with macOS 27)."
        return True, f"Found {self.path}."

    def ask(self, job, instructions, prompt, schema, max_tokens=None, timeout=None):
        if not self.path:
            raise ModelError("no fm command", "unavailable")
        text = f"{instructions}\n\n{prompt}"
        if schema:
            text += f"\n\nAnswer with JSON only, nothing else, shaped like this:\n{example(schema)}"
        cmd = [self.path, "respond", text]
        tmp = None
        if schema and self.schema_flag:
            tmp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_files", "fm_schema.json")
            try:
                os.makedirs(os.path.dirname(tmp), exist_ok=True)
                with open(tmp, "w") as f:
                    json.dump(json_schema(schema), f)
                cmd += ["--schema", tmp]
            except OSError:
                tmp = None
        start = time.time()
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout or self.timeout)
        except subprocess.TimeoutExpired:
            raise ModelError("no answer in time", "timeout")
        except OSError as e:
            raise ModelError(str(e), "unavailable")
        ms = int((time.time() - start) * 1000)
        if r.returncode != 0:
            if tmp:  # the flag isn't what this fm takes: plain from now on
                self.schema_flag = False
                return self.ask(job, instructions, prompt, schema, max_tokens, timeout)
            raise ModelError((r.stderr or r.stdout or f"fm exited {r.returncode}")[:500], kind_of(r.stderr))
        raw = r.stdout
        if not schema:
            return raw.strip(), ms, raw
        return conform(json_in(raw), schema), ms, raw


def json_schema(s):
    """The subset as standard JSON Schema (for an fm that takes one)."""
    t = s.get("type")
    if t == "object":
        return {"type": "object", "properties": {p["name"]: json_schema(p["schema"]) for p in s["props"]},
                "required": [p["name"] for p in s["props"] if not p.get("optional")]}
    if t == "array":
        out = {"type": "array", "items": json_schema(s["items"])}
        if s.get("max"):
            out["maxItems"] = s["max"]
        return out
    if s.get("enum"):
        return {"type": "string", "enum": s["enum"]}
    return {"type": t or "string"}


def plain_why(why):
    """Why Apple's model isn't ready, in words a person knows, or ""."""
    t = str(why or "")
    if "appleIntelligenceNotEnabled" in t:
        return "Apple Intelligence is off (System Settings \u203a Apple Intelligence & Siri)"
    if "deviceNotEligible" in t:
        return "this Mac can't run Apple's model"
    if "modelNotReady" in t:
        return "Apple's model is still downloading"
    return ""


def setup_line(helper, fm):
    """Settings' first words: the model Auto will use, and whether anything
    needs building. With macOS 27's fm, nothing does."""
    if helper.built():
        return f"Model: the built helper ({helper.guardrails() or '?'} guardrails). Check the model to try it."
    if fm.path:
        return ("Model: the fm command, nothing to build. Check the model to try it.\n"
                "Building the helper is optional; it needs Apple's developer tools.")
    return ("No Mac model yet: Build the helper (it needs Apple's Command Line Tools). "
            "Until then Auto runs on plain rules.")


def pick_runner(choice, folder, log=_nolog, timeout=90, fm_schema_flag=False):
    """"auto" takes the built helper, then fm, then none."""
    helper = HelperRunner(folder, log, timeout)
    fm = FmRunner(log, timeout, fm_schema_flag)
    if choice == "helper":
        return helper
    if choice == "fm":
        return fm
    if choice == "none":
        return NoModel()
    if helper.built():
        return helper
    if fm.path:
        return fm
    return NoModel()
