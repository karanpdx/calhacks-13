"""Read KEY=VALUE lines from the repo's .env into the environment (no dependency, values never printed).

Real environment variables win over .env. Skipped under pytest so the tests stay offline and free (hard rule 7).
.env is git-ignored: never commit it.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path=None):
    """Returns the names (not values) it set."""
    if "pytest" in sys.modules:
        return []
    path = path or os.path.join(ROOT, ".env")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    names = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        if key and value and key not in os.environ:
            os.environ[key] = value
            names.append(key)
    return names


def status():
    """Which integrations are configured, by name only, for a startup line."""
    return {"claude": bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")),
            "crs_live": bool(os.environ.get("CRS_USER") and os.environ.get("CRS_PASS"))}
