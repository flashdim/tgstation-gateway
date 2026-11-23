"""Serve the test landing page and generate slots.js from the environment."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import re
import sys

LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOST_PATTERN = re.compile(
    rf"(?P<name>{LABEL}(?:\.{LABEL})*)(?::(?P<port>[1-9][0-9]{{0,4}}))?"
)
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,24}")
PATH_PATTERN = re.compile(r"/[A-Za-z0-9._~/{}-]*")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
PAGE_ROOT = "/srv/landing"


class ConfigError(ValueError):
    pass


def build_slots(env):
    host = env.get("GATEWAY_PLAY_HOST", "").strip() or "localhost:8080"
    match = HOST_PATTERN.fullmatch(host)
    if not match or len(match["name"]) > 253 or int(match["port"] or 1) > 65535:
        raise ConfigError("GATEWAY_PLAY_HOST must be a DNS name with an optional port")
    hostname = match["name"].lower()

    scheme = env.get("GATEWAY_PLAY_SCHEME", "").strip().lower()
    if not scheme:
        scheme = "http" if hostname in LOCAL_HOSTS else "https"
    if scheme not in ("http", "https"):
        raise ConfigError("GATEWAY_PLAY_SCHEME must be http or https")

    count_text = env.get("GATEWAY_SLOT_COUNT", "").strip() or "1"
    if not count_text.isdigit() or not 1 <= int(count_text) <= 99:
        raise ConfigError("GATEWAY_SLOT_COUNT must be between 1 and 99")
    count = int(count_text)

    prefix = env.get("GATEWAY_ACCOUNT_PREFIX", "").strip() or "LGplayer"
    if not PREFIX_PATTERN.fullmatch(prefix):
        raise ConfigError(
            "GATEWAY_ACCOUNT_PREFIX must contain only letters, digits, _ or -"
        )

    path = env.get("GATEWAY_SLOT_PATH", "").strip() or "/"
    if not PATH_PATTERN.fullmatch(path):
        raise ConfigError("GATEWAY_SLOT_PATH must be an absolute URL path")
    leftover = re.sub(r"\{(?:account|number)\}", "", path)
    if "{" in leftover or "}" in leftover:
        raise ConfigError("GATEWAY_SLOT_PATH supports only {account} and {number}")
    if count > 1 and "{account}" not in path and "{number}" not in path:
        raise ConfigError(
            "GATEWAY_SLOT_PATH must include {account} or {number} for multiple slots"
        )

    accounts = [f"{prefix}{number:02d}" for number in range(1, count + 1)]
    active = {
        name.strip()
        for name in env.get("GATEWAY_ACTIVE_SLOTS", "").split(",")
        if name.strip()
    }
    unknown = active - set(accounts)
    if unknown:
        raise ConfigError(
            "GATEWAY_ACTIVE_SLOTS lists unknown accounts: " + ", ".join(sorted(unknown))
        )

    return [
        {
            "account": account,
            "url": f"{scheme}://{host}"
            + path.replace("{account}", account).replace("{number}", f"{number:02d}"),
            "active": account in active,
        }
        for number, account in enumerate(accounts, 1)
    ]


def render_slots(slots):
    data = json.dumps(slots, indent=2).replace("<", "\\u003c")
    return (
        "// Generated from the landing container environment. Test data only.\n"
        f"window.GATEWAY_SLOTS = {data};\n"
    ).encode()


class LandingHandler(SimpleHTTPRequestHandler):
    slots_js = b""

    def send_head(self):
        if self.path.split("?", 1)[0] != "/slots.js":
            return super().send_head()
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(self.slots_js)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return io.BytesIO(self.slots_js)


def main():
    try:
        slots = build_slots(os.environ)
    except ConfigError as error:
        print(f"Invalid landing configuration: {error}", file=sys.stderr)
        return 2
    LandingHandler.slots_js = render_slots(slots)
    for slot in slots:
        state = "active" if slot["active"] else "available"
        print(f"Slot {slot['account']}: {slot['url']} ({state})", flush=True)
    handler = partial(LandingHandler, directory=PAGE_ROOT)
    ThreadingHTTPServer(("0.0.0.0", 8000), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
