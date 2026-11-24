"""Configuration and state primitives; no Docker access or authorization API."""

from dataclasses import dataclass
from enum import Enum
import re
import threading
from uuid import UUID

LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOST_PATTERN = re.compile(
    rf"(?P<name>{LABEL}(?:\.{LABEL})*)(?::(?P<port>[1-9][0-9]{{0,4}}))?"
)
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,24}")
PATH_PATTERN = re.compile(r"/[A-Za-z0-9._~/{}-]*")
DEPLOYMENT_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
LABEL_PREFIX = "io.tgstation-gateway."
PROJECT = "tgstation-gateway"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Slot:
    number: int
    account: str
    path: str
    url: str


@dataclass(frozen=True)
class SessionConfig:
    deployment_id: str
    slots: tuple[Slot, ...]

    @classmethod
    def from_env(cls, env):
        if "GATEWAY_ACTIVE_SLOTS" in env:
            raise ConfigError(
                "GATEWAY_ACTIVE_SLOTS is removed; status now comes from session lifecycle"
            )
        host = env.get("GATEWAY_PLAY_HOST", "").strip() or "localhost:8080"
        match = HOST_PATTERN.fullmatch(host)
        if not match or len(match["name"]) > 253 or int(match["port"] or 1) > 65535:
            raise ConfigError(
                "GATEWAY_PLAY_HOST must be a DNS name with an optional port"
            )
        scheme = env.get("GATEWAY_PLAY_SCHEME", "").strip().lower()
        if not scheme:
            scheme = (
                "http"
                if match["name"].lower() in {"localhost", "127.0.0.1"}
                else "https"
            )
        if scheme not in ("http", "https"):
            raise ConfigError("GATEWAY_PLAY_SCHEME must be http or https")

        count_text = env.get("GATEWAY_SLOT_COUNT", "").strip() or "1"
        if (
            not re.fullmatch(r"[0-9]{1,2}", count_text)
            or not 1 <= int(count_text) <= 99
        ):
            raise ConfigError("GATEWAY_SLOT_COUNT must be between 1 and 99")
        count = int(count_text)
        prefix = env.get("GATEWAY_ACCOUNT_PREFIX", "").strip() or "LGplayer"
        if not PREFIX_PATTERN.fullmatch(prefix):
            raise ConfigError(
                "GATEWAY_ACCOUNT_PREFIX must contain 1–24 letters, digits, _ or -"
            )
        path = env.get("GATEWAY_SLOT_PATH", "").strip() or "/"
        if not PATH_PATTERN.fullmatch(path) or "//" in path:
            raise ConfigError(
                "GATEWAY_SLOT_PATH must be an absolute URL path without //"
            )
        if {".", ".."} & set(path.split("/")):
            raise ConfigError("GATEWAY_SLOT_PATH must not contain . or .. segments")
        leftover = re.sub(r"\{(?:account|number)\}", "", path)
        if "{" in leftover or "}" in leftover:
            raise ConfigError("GATEWAY_SLOT_PATH supports only {account} and {number}")
        if count > 1 and "{account}" not in path and "{number}" not in path:
            raise ConfigError(
                "GATEWAY_SLOT_PATH must include {account} or {number} for multiple slots"
            )
        deployment = env.get("GATEWAY_DEPLOYMENT_ID", "local").strip()
        if not DEPLOYMENT_PATTERN.fullmatch(deployment):
            raise ConfigError(
                "GATEWAY_DEPLOYMENT_ID must contain 1–64 letters, digits, _, . or - "
                "and start with a letter or digit"
            )
        slots = []
        for number in range(1, count + 1):
            account = f"{prefix}{number:02d}"
            slot_path = path.replace("{account}", account).replace(
                "{number}", f"{number:02d}"
            )
            slots.append(
                Slot(number, account, slot_path, f"{scheme}://{host}{slot_path}")
            )
        return cls(deployment, tuple(slots))

    def slot(self, account):
        for slot in self.slots:
            if slot.account == account:
                return slot
        raise ValueError("Unknown slot account")

    def route(self, path):
        """Exact allowlist lookup, to be used only after trusted ownership checks."""
        for slot in self.slots:
            if slot.path == path:
                return slot
        raise ValueError("Unknown slot path")

    @property
    def ownership_filter(self):
        return {
            LABEL_PREFIX + "project": PROJECT,
            LABEL_PREFIX + "deployment": self.deployment_id,
            LABEL_PREFIX + "role": "player",
        }

    def container_labels(self, account, session_id):
        slot = self.slot(account)
        if not isinstance(session_id, str) or str(UUID(session_id)) != session_id:
            raise ValueError("Session ID must be a canonical UUID")
        return {
            **self.ownership_filter,
            LABEL_PREFIX + "slot": f"{slot.number:02d}",
            LABEL_PREFIX + "account": slot.account,
            LABEL_PREFIX + "session": session_id,
        }

    def owns_container(self, labels):
        """Fail closed before any future adoption, reconciliation or deletion."""
        if not isinstance(labels, dict):
            return False
        try:
            expected = self.container_labels(
                labels.get(LABEL_PREFIX + "account"),
                labels.get(LABEL_PREFIX + "session"),
            )
        except (ValueError, TypeError, AttributeError):
            return False
        return all(labels.get(key) == value for key, value in expected.items())


class SessionState(str, Enum):
    STARTING = "starting"
    READY = "ready"
    RECONNECT_GRACE = "reconnect_grace"
    STOPPING = "stopping"
    FAILED = "failed"


TRANSITIONS = {
    None: {SessionState.STARTING},
    SessionState.STARTING: {
        SessionState.READY,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    SessionState.READY: {
        SessionState.RECONNECT_GRACE,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    SessionState.RECONNECT_GRACE: {
        SessionState.READY,
        SessionState.STOPPING,
        SessionState.FAILED,
    },
    SessionState.STOPPING: {SessionState.FAILED},
    SessionState.FAILED: {SessionState.STOPPING},
}


class SlotRegistry:
    def __init__(self, config):
        self.config = config
        self._states = {slot.account: None for slot in config.slots}
        self._lock = threading.Lock()

    def transition(self, account, state):
        self.config.slot(account)
        if not isinstance(state, SessionState):
            raise ValueError("Invalid session state")
        with self._lock:
            if state not in TRANSITIONS[self._states[account]]:
                raise ValueError("Invalid session state transition")
            self._states[account] = state

    def release(self, account):
        """Caller must confirm container/session-data cleanup before releasing."""
        self.config.slot(account)
        with self._lock:
            if self._states[account] not in {
                SessionState.STOPPING,
                SessionState.FAILED,
            }:
                raise ValueError("Slot is not awaiting cleanup")
            self._states[account] = None

    def snapshot(self):
        with self._lock:
            return [
                {
                    "account": slot.account,
                    "url": slot.url,
                    "state": self._states[slot.account].value
                    if self._states[slot.account]
                    else None,
                }
                for slot in self.config.slots
            ]
