"""The courses, one JSON file a profile in the add-on's user_files (deck ids
belong to one collection). Written whole, through a temporary file."""

import json
import os
import re


def path(folder, profile):
    name = re.sub(r"[^\w.-]+", "_", str(profile or "default"))[:60] or "default"
    return os.path.join(folder, "courses", f"{name}.json")


def load(folder, profile):
    p = path(folder, profile)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("courses"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"courses": [], "current": 0}


def save(folder, profile, data):
    p = path(folder, profile)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, p)
