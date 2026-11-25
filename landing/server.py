"""Serve the test landing page and generate slots.js from the environment."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import subprocess
import sys
import threading
import time

from sessions import ConfigError, HOST_PATTERN, SessionConfig, SlotRegistry

PAGE_ROOT = "/srv/landing"
STATUS_INTERVAL = 5
STATUS_MAX_AGE = 20


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
    return SlotRegistry(SessionConfig.from_env(env)).snapshot()


def render_slots(slots):
    data = json.dumps(slots, indent=2).replace("<", "\\u003c")
    return (
        "// Generated from configured slots and server-side lifecycle state.\n"
        f"window.GATEWAY_SLOTS = {data};\n"
    ).encode()


class LandingHandler(SimpleHTTPRequestHandler):
    slot_registry = None
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
            data = render_slots(self.slot_registry.snapshot())
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
        registry = SlotRegistry(SessionConfig.from_env(os.environ))
        config = query_config(os.environ)
    except ConfigError as error:
        print(f"Invalid landing configuration: {error}", file=sys.stderr)
        return 2
    LandingHandler.slot_registry = registry
    if config:
        LandingHandler.status_monitor = StatusMonitor(config)
        threading.Thread(target=LandingHandler.status_monitor.run, daemon=True).start()
    for slot in registry.snapshot():
        print(f"Slot {slot['account']}: {slot['url']} (status unknown)", flush=True)
    handler = partial(LandingHandler, directory=PAGE_ROOT)
    ThreadingHTTPServer(("0.0.0.0", 8000), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
