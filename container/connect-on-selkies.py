#!/usr/bin/env python3
"""Start Dream Seeker for a connected Selkies client with the slot's saved key."""

import fcntl
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import stat
import subprocess
import sys
import time
from urllib.parse import quote

PAGER_PATTERN = r'(^|[\\/])byond[.]exe"?([[:space:]]|$)'
GAME_PATTERN = r'(^|[\\/])dreamseeker[.]exe"?([[:space:]]|$)'
KEY_HEADER = re.compile(rb"^\[?BEGIN KEY[ \t]+([A-Za-z0-9_-]{1,48})\]?$", re.I)
KEY_END = re.compile(rb"^\[?END KEY\]?$", re.I)
MAX_KEY_BYTES = 1024 * 1024
MAX_SESSION_BYTES = 1024 * 1024


class ObservationError(Exception):
    pass


def server_url(server):
    server = server.removeprefix("byond://")
    match = re.fullmatch(
        r"(?:[a-zA-Z0-9._-]+|\[[0-9a-fA-F:.]+\]):([0-9]{1,5})", server
    )
    if not match or not 1 <= int(match.group(1)) <= 65535:
        raise ValueError("Invalid BYOND_SERVER: expected host:port or byond://host:port")
    return f"byond://{server}"


def sessions_present(port, path):
    errors = []
    for scheme in ("http", "https"):
        connection = None
        try:
            if scheme == "http":
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            else:
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                connection = http.client.HTTPSConnection(
                    "127.0.0.1", port, timeout=3, context=context
                )
            connection.request("GET", path)
            response = connection.getresponse()
            if response.status != 200:
                errors.append(f"{scheme} returned HTTP {response.status}")
                continue
            data = response.read(MAX_SESSION_BYTES + 1)
            if len(data) > MAX_SESSION_BYTES:
                raise ObservationError("Selkies sessions response is too large")
            try:
                payload = json.loads(data)
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ObservationError("Selkies sessions response is invalid JSON") from error
            if (
                not isinstance(payload, dict)
                or not isinstance(payload.get("sessions"), list)
                or not all(isinstance(item, dict) for item in payload["sessions"])
            ):
                raise ObservationError("Selkies sessions response has an invalid shape")
            return bool(payload["sessions"])
        except (OSError, http.client.HTTPException) as error:
            errors.append(f"{scheme}: {type(error).__name__}")
        finally:
            if connection is not None:
                connection.close()
    raise ObservationError("cannot query Selkies sessions (" + "; ".join(errors) + ")")


def key_matches(path, account):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                return False, "BYOND key.txt is not a regular file"
            data = file.read(MAX_KEY_BYTES + 1)
    except FileNotFoundError:
        return False, "BYOND key.txt is missing"
    except OSError as error:
        return False, f"Cannot read BYOND key.txt: {error.strerror or type(error).__name__}"
    if len(data) > MAX_KEY_BYTES:
        return False, "BYOND key.txt is too large to check"

    expected = account.encode("ascii").lower()
    matching = False
    has_data = False
    for line in data.splitlines():
        line = line.strip()
        header = KEY_HEADER.fullmatch(line)
        if header:
            matching = header.group(1).lower() == expected
            has_data = False
        elif KEY_END.fullmatch(line):
            if matching and has_data:
                return True, ""
            matching = False
        elif matching and line:
            has_data = True
    return False, f"BYOND key.txt has no complete key for {account}"


def process_ids(pattern):
    try:
        result = subprocess.run(
            ["pgrep", "-i", "-f", "-u", str(os.getuid()), pattern],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ObservationError(f"cannot check BYOND processes: {type(error).__name__}") from error
    if result.returncode == 1:
        return frozenset()
    if result.returncode != 0:
        raise ObservationError(f"cannot check BYOND processes: pgrep exited {result.returncode}")
    try:
        return frozenset(int(pid) for pid in result.stdout.split())
    except ValueError as error:
        raise ObservationError("cannot parse BYOND process IDs") from error


class GameConnector:
    def __init__(self, env):
        self.env = dict(env)
        self.account = env.get("BYOND_ACCOUNT", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", self.account):
            raise ValueError("BYOND_ACCOUNT must identify the slot's BYOND account")
        self.server = server_url(env.get("BYOND_SERVER", ""))
        port = env.get("SELKIES_PORT") or "8080"
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
            raise ValueError("SELKIES_PORT must be a valid TCP port")
        self.port = int(port)
        prefix = env.get("SELKIES_SUBFOLDER", env.get("SUBFOLDER", "")).strip("/")
        self.sessions_path = f"/{quote(prefix, safe='/~._-')}/api/sessions" if prefix else "/api/sessions"
        self.runtime = Path(env.get("XDG_RUNTIME_DIR") or "/tmp/runtime-ubuntu")
        self.prefix = Path(env.get("WINEPREFIX") or "/home/ubuntu/.wine")
        self.key = self.prefix / "drive_c/users/steamuser/Documents/BYOND/key.txt"
        self.game = self.prefix / "drive_c/Program Files (x86)/BYOND/bin/dreamseeker.exe"
        self.connected = False
        self.attempted = False
        self.pager_pids = None
        self.last_notice = None
        self.child = None

    def notice(self, message):
        if message != self.last_notice:
            print(message, file=sys.stderr, flush=True)
            self.last_notice = message

    def disconnect(self):
        if self.connected:
            print("Selkies disconnected; leaving any running Dream Seeker open", file=sys.stderr, flush=True)
        self.connected = False
        self.attempted = False
        self.pager_pids = None
        self.last_notice = None

    def game_env(self):
        env = self.env.copy()
        env.pop("LD_PRELOAD", None)
        if env.get("SELKIES_WAYLAND", "false") == "true":
            try:
                lines = (self.runtime / "byond-xwayland").read_text().splitlines()
                if len(lines) != 2 or not all(lines) or not os.access(lines[1], os.R_OK):
                    raise ValueError
            except (OSError, ValueError):
                raise ObservationError("waiting for an authenticated XWayland display") from None
            env["DISPLAY"], env["XAUTHORITY"] = lines
        else:
            env["DISPLAY"] = env.get("DISPLAY") or ":20"
        return env

    def step(self):
        if self.child is not None:
            code = self.child.poll()
            if code is not None:
                if code:
                    print(f"Dream Seeker exited with status {code}", file=sys.stderr, flush=True)
                self.child = None

        try:
            present = sessions_present(self.port, self.sessions_path)
        except ObservationError as error:
            self.notice(f"Waiting for Selkies: {error}")
            return
        if not present:
            self.disconnect()
            return
        if not self.connected:
            print("Selkies client connected", file=sys.stderr, flush=True)
            self.connected = True
            self.attempted = False
            self.last_notice = None

        try:
            with (self.runtime / "byond-cleanup.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    self.notice("Waiting for BYOND startup or reset to finish")
                    return

                pager_pids = process_ids(PAGER_PATTERN)
                if self.pager_pids is not None and not (self.pager_pids & pager_pids):
                    self.attempted = False
                self.pager_pids = pager_pids
                if not pager_pids:
                    self.notice("Waiting for the BYOND pager")
                    return
                if self.attempted:
                    return

                matches, reason = key_matches(self.key, self.account)
                if not matches:
                    self.notice(f"{reason}; log in as {self.account} and save the password")
                    return
                if process_ids(GAME_PATTERN):
                    self.attempted = True
                    self.notice("Dream Seeker is already running")
                    return
                env = self.game_env()
                if not sessions_present(self.port, self.sessions_path):
                    self.disconnect()
                    return
                try:
                    self.child = subprocess.Popen(
                        ["wine", str(self.game), self.server], env=env, close_fds=True
                    )
                except OSError as error:
                    self.attempted = True
                    self.notice(f"Could not start Dream Seeker: {error.strerror or type(error).__name__}")
                    return
                self.attempted = True
                self.last_notice = None
                print(f"Starting Dream Seeker for {self.account}", file=sys.stderr, flush=True)
        except ObservationError as error:
            self.notice(f"Waiting to start Dream Seeker: {error}")
        except OSError as error:
            self.notice(f"Cannot access BYOND startup lock: {error.strerror or type(error).__name__}")


def main():
    if not os.environ.get("BYOND_SERVER"):
        print("BYOND_SERVER is not configured; automatic game connection is disabled", file=sys.stderr, flush=True)
        while True:
            time.sleep(3600)
    try:
        connector = GameConnector(os.environ)
    except ValueError as error:
        print(f"Automatic game connection disabled: {error}", file=sys.stderr, flush=True)
        while True:
            time.sleep(3600)
    while True:
        connector.step()
        time.sleep(2)


if __name__ == "__main__":
    main()
