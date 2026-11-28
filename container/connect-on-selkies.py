#!/usr/bin/env python3
"""Start Dream Seeker when a Selkies client connects and stop it on disconnect."""

import http.client
import json
import os
import re
import ssl
import subprocess
import sys
import time
from urllib.parse import quote

MAX_SESSION_BYTES = 1024 * 1024


class ObservationError(Exception):
    pass


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
                raise ObservationError(
                    "Selkies sessions response is invalid JSON"
                ) from error
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


class SessionWatcher:
    def __init__(self, env, control=None):
        port = env.get("SELKIES_PORT") or "8080"
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
            raise ValueError("SELKIES_PORT must be a valid TCP port")
        self.port = int(port)
        prefix = env.get("SELKIES_SUBFOLDER", env.get("SUBFOLDER", "")).strip("/")
        self.sessions_path = (
            f"/{quote(prefix, safe='/~._-')}/api/sessions"
            if prefix
            else "/api/sessions"
        )
        self.control = control or self.run_control
        self.applied = None
        self.last_notice = None

    @staticmethod
    def run_control(action):
        subprocess.run(
            ["/usr/local/bin/byond-game.sh", action],
            check=True,
            timeout=60,
            env={**os.environ, "BYOND_GAME_QUIET": "1"},
        )

    def notice(self, message):
        if message != self.last_notice:
            print(message, file=sys.stderr, flush=True)
            self.last_notice = message

    def step(self):
        try:
            present = sessions_present(self.port, self.sessions_path)
        except ObservationError as error:
            self.notice(f"Waiting for Selkies: {error}")
            return
        action = "start" if present else "stop"
        try:
            self.control(action)
        except (OSError, subprocess.SubprocessError) as error:
            if (
                isinstance(error, subprocess.CalledProcessError)
                and error.returncode == 76
            ):
                self.notice("Waiting for a saved BYOND key matching the slot account")
            else:
                self.notice(f"Could not {action} Dream Seeker: {type(error).__name__}")
            return
        self.last_notice = None
        if self.applied != action:
            print(
                "Selkies client connected; starting Dream Seeker"
                if present
                else "Selkies client disconnected; stopped Dream Seeker",
                file=sys.stderr,
                flush=True,
            )
        self.applied = action


def main():
    try:
        watcher = SessionWatcher(os.environ)
    except ValueError as error:
        print(f"Selkies session watcher disabled: {error}", file=sys.stderr, flush=True)
        while True:
            time.sleep(3600)
    while True:
        watcher.step()
        time.sleep(2)


if __name__ == "__main__":
    main()
