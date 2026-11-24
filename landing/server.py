"""Serve the test landing page and generate slots.js from the environment."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import re
import subprocess
import sys
import threading
import time

LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOST_PATTERN = re.compile(
    rf"(?P<name>{LABEL}(?:\.{LABEL})*)(?::(?P<port>[1-9][0-9]{{0,4}}))?"
)
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,24}")
PATH_PATTERN = re.compile(r"/[A-Za-z0-9._~/{}-]*")
LOCAL_HOSTS = {"localhost", "127.0.0.1"}
PAGE_ROOT = "/srv/landing"
STATUS_INTERVAL = 5
STATUS_MAX_AGE = 20


class ConfigError(ValueError):
    pass


def query_config(env):
    host = env.get("GATEWAY_QUERY_HOST", "").strip()
    port = env.get("GATEWAY_QUERY_PORT", "").strip()
    if not host and not port:
        return None
    match = HOST_PATTERN.fullmatch(host)
    if not match or match["port"] or len(host) > 253:
        raise ConfigError("GATEWAY_QUERY_HOST must be a DNS name or IPv4 address")
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise ConfigError("GATEWAY_QUERY_PORT must be between 1 and 65535")
    return host, int(port)


def fetch_status(host, port):
    result = subprocess.run(
        ["byond-wire", host, str(port), "?status&format=json"],
        capture_output=True,
        check=True,
        timeout=7,
    )
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise ValueError("Invalid status response")
    name = data["map_name"]
    players = data["players"]
    duration = data["round_duration"]
    game_state = data["gamestate"]
    popcap = data.get("popcap")
    if (
        not isinstance(name, str)
        or not name
        or type(players) is not int
        or not 0 <= players <= 2**53 - 1
        or type(duration) not in (int, float)
        or not 0 <= duration <= 2**53 - 1
        or (
            popcap is not None
            and (type(popcap) is not int or not 0 <= popcap <= 2**53 - 1)
        )
        or type(game_state) is not int
        or game_state < 0
    ):
        raise ValueError("Invalid status fields")
    return {
        "online": True,
        "map": name[:200],
        "round_seconds": int(duration) if game_state >= 3 else None,
        "players": players,
        "popcap": popcap,
    }


class StatusMonitor:
    def __init__(self, config):
        self.config = config
        self.value = None
        self.updated = 0
        self.lock = threading.Lock()

    def snapshot(self):
        with self.lock:
            if time.monotonic() - self.updated > STATUS_MAX_AGE:
                return {"online": None}
            return self.value or {"online": None}

    def run(self):
        while True:
            try:
                value = fetch_status(*self.config)
            except Exception:
                value = None
            with self.lock:
                self.value = value
                self.updated = time.monotonic()
            time.sleep(STATUS_INTERVAL)


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
    if {".", ".."} & set(path.split("/")):
        raise ConfigError("GATEWAY_SLOT_PATH must not contain . or .. segments")
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
    status_monitor = None

    def send_head(self):
        path = self.path.split("?", 1)[0]
        if path == "/status.json":
            data = json.dumps(
                self.status_monitor.snapshot()
                if self.status_monitor
                else {"online": None}
            ).encode()
            content_type = "application/json; charset=utf-8"
        elif path == "/slots.js":
            data = self.slots_js
            content_type = "text/javascript; charset=utf-8"
        else:
            return super().send_head()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return io.BytesIO(data)


def main():
    try:
        slots = build_slots(os.environ)
        config = query_config(os.environ)
    except ConfigError as error:
        print(f"Invalid landing configuration: {error}", file=sys.stderr)
        return 2
    LandingHandler.slots_js = render_slots(slots)
    if config:
        LandingHandler.status_monitor = StatusMonitor(config)
        threading.Thread(target=LandingHandler.status_monitor.run, daemon=True).start()
    for slot in slots:
        state = "active" if slot["active"] else "available"
        print(f"Slot {slot['account']}: {slot['url']} ({state})", flush=True)
    handler = partial(LandingHandler, directory=PAGE_ROOT)
    ThreadingHTTPServer(("0.0.0.0", 8000), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
