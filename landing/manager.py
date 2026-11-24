"""Single-host player container lifecycle; not connected to the landing server.

Docker daemon access is privileged. Keep the socket private to the manager and
never expose this module's operations to players without a trusted ownership
check in front of them.
"""

from dataclasses import dataclass, field, replace
import http.client
import json
import socket
import threading
import time
from urllib.parse import quote, urlencode
from uuid import uuid4

from sessions import LABEL_PREFIX, PROJECT, SessionState

SESSION_LABEL = LABEL_PREFIX + "session"
ACTIVE = {SessionState.READY, SessionState.RECONNECT_GRACE}
MAX_RESPONSE = 16 * 1024 * 1024


class SessionError(Exception):
    """Explicit failure response; `status` is a suggested HTTP status."""

    status = 500
    code = "session_error"


class UnknownSlot(SessionError):
    status = 404
    code = "unknown_slot"


class UnknownSession(SessionError):
    status = 404
    code = "unknown_session"


class SlotBusy(SessionError):
    status = 409
    code = "slot_busy"


class CapacityExhausted(SessionError):
    status = 503
    code = "capacity_exhausted"


class DockerUnavailable(SessionError):
    status = 502
    code = "docker_unavailable"


class StartupFailed(SessionError):
    status = 502
    code = "startup_failed"


class StartupTimeout(SessionError):
    status = 504
    code = "startup_timeout"


class CleanupFailed(SessionError):
    status = 500
    code = "cleanup_failed"


class DockerError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class _UnixConnection(http.client.HTTPConnection):
    def __init__(self, path, timeout):
        super().__init__("localhost", timeout=timeout)
        self._path = path

    def connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(self._path)
        except BaseException:
            sock.close()
            raise
        self.sock = sock


class DockerClient:
    """Minimal Docker Engine API client over a private UNIX socket."""

    def __init__(
        self, socket_path="/var/run/docker.sock", api_version="1.44", timeout=30
    ):
        if not timeout > 0:
            raise ValueError("Docker API timeout must be positive")
        self.socket_path = socket_path
        self.prefix = f"/v{api_version}"
        self.timeout = timeout

    def _request(self, method, path, query=None, body=None, ok=(200,)):
        url = self.prefix + path + ("?" + urlencode(query) if query else "")
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Content-Type": "application/json"} if payload else {}
        connection = _UnixConnection(self.socket_path, self.timeout)
        try:
            connection.request(method, url, body=payload, headers=headers)
            response = connection.getresponse()
            data = response.read(MAX_RESPONSE + 1)
        except (OSError, http.client.HTTPException) as error:
            raise DockerError(f"Docker API request failed: {method} {path}") from error
        finally:
            connection.close()
        if len(data) > MAX_RESPONSE:
            raise DockerError("Docker API response is too large")
        if response.status not in ok:
            message = ""
            try:
                message = str(json.loads(data).get("message", ""))[:200]
            except (ValueError, AttributeError):
                pass
            raise DockerError(
                f"Docker API returned {response.status} for {method} {path}"
                + (f": {message}" if message else ""),
                response.status,
            )
        if not data:
            return None
        try:
            return json.loads(data)
        except ValueError as error:
            raise DockerError("Docker API returned invalid JSON") from error

    def list_containers(self, labels):
        filters = json.dumps({"label": [f"{k}={v}" for k, v in labels.items()]})
        result = self._request(
            "GET", "/containers/json", {"all": "1", "filters": filters}
        )
        if not isinstance(result, list):
            raise DockerError("Docker API returned an invalid container list")
        containers = []
        for item in result:
            if not isinstance(item, dict) or not isinstance(item.get("Id"), str):
                raise DockerError("Docker API returned an invalid container")
            containers.append({"id": item["Id"], "labels": item.get("Labels") or {}})
        return containers

    def create(self, name, body):
        result = self._request(
            "POST", "/containers/create", {"name": name}, body, ok=(201,)
        )
        if not isinstance(result, dict) or not isinstance(result.get("Id"), str):
            raise DockerError("Docker API returned an invalid create response")
        return result["Id"]

    def start(self, container_id):
        self._request(
            "POST", f"/containers/{quote(container_id, safe='')}/start", ok=(204, 304)
        )

    def inspect(self, container_id):
        result = self._request(
            "GET", f"/containers/{quote(container_id, safe='')}/json"
        )
        if not isinstance(result, dict):
            raise DockerError("Docker API returned an invalid inspect response")
        return result

    def remove(self, container_id):
        """Force-remove the container and its anonymous volumes; 404 is success."""
        try:
            self._request(
                "DELETE",
                f"/containers/{quote(container_id, safe='')}",
                {"force": "1", "v": "1"},
                ok=(204,),
            )
        except DockerError as error:
            if error.status != 404:
                raise


@dataclass(frozen=True)
class PlayerSpec:
    """Non-secret player container template supplied by the operator."""

    image: str
    seccomp_profile: str
    environment: dict = field(default_factory=dict)
    network: str | None = None
    shm_size: int = 2 * 1024**3

    def __post_init__(self):
        if not isinstance(self.image, str) or not self.image.strip():
            raise ValueError("Player image is required")
        if not isinstance(self.seccomp_profile, str):
            raise ValueError("A seccomp profile is required")
        try:
            profile = json.loads(self.seccomp_profile)
        except ValueError as error:
            raise ValueError("Seccomp profile must be JSON") from error
        if not isinstance(profile, dict) or not profile.get("defaultAction"):
            raise ValueError("Seccomp profile must define defaultAction")
        for key, value in self.environment.items():
            if not isinstance(key, str) or not key or "=" in key:
                raise ValueError("Invalid environment variable name")
            if not isinstance(value, str):
                raise ValueError("Environment values must be strings")

    def container_body(self, labels):
        host = {
            "Init": True,
            "ShmSize": self.shm_size,
            "SecurityOpt": ["seccomp=" + self.seccomp_profile],
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
        }
        if self.network:
            host["NetworkMode"] = self.network
        return {
            "Image": self.image,
            "Env": [f"{k}={v}" for k, v in sorted(self.environment.items())],
            "Labels": labels,
            "HostConfig": host,
        }


@dataclass(frozen=True)
class Session:
    account: str
    session_id: str
    container_id: str | None = None
    error: str | None = None
    cleanup_pending: bool = False


class SessionManager:
    """Serialize per-slot startup/teardown and enforce host capacity.

    Lock order is slot lock, then host lock. The host lock covers only the
    capacity check and reservation, so readiness waits do not block other slots.
    """

    def __init__(
        self,
        registry,
        docker,
        spec,
        start_timeout=180,
        poll_interval=1,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        if not start_timeout > 0 or not poll_interval > 0:
            raise ValueError("Timeouts must be positive")
        self.registry = registry
        self.config = registry.config
        self.docker = docker
        self.spec = spec
        self.start_timeout = start_timeout
        self.poll_interval = poll_interval
        self.clock = clock
        self.sleep = sleep
        self.capacity = len(self.config.slots)
        self._slot_locks = {s.account: threading.Lock() for s in self.config.slots}
        self._host_lock = threading.Lock()
        self._meta_lock = threading.Lock()
        self._sessions = {}

    def _slot(self, account):
        try:
            return self.config.slot(account)
        except (ValueError, TypeError):
            raise UnknownSlot("Unknown slot") from None

    def _get(self, account):
        with self._meta_lock:
            return self._sessions.get(account)

    def _put(self, session):
        with self._meta_lock:
            self._sessions[session.account] = session

    def _drop(self, account):
        with self._meta_lock:
            self._sessions.pop(account, None)

    def status(self):
        """Operator status; session IDs are omitted."""
        with self._meta_lock:
            sessions = dict(self._sessions)
        result = []
        for slot in self.config.slots:
            state = self.registry.state(slot.account)
            session = sessions.get(slot.account)
            result.append(
                {
                    "account": slot.account,
                    "state": state.value if state else None,
                    "error": session.error if session else None,
                    "cleanup_pending": bool(session and session.cleanup_pending),
                }
            )
        return result

    def start(self, account):
        """Return the slot's active session, creating exactly one if needed."""
        slot = self._slot(account)
        with self._slot_locks[account]:
            state = self.registry.state(account)
            session = self._get(account)
            if state in ACTIVE:
                if self._running(session):
                    return session
                self._fail(session, "container_stopped")
                state = SessionState.FAILED
            if state is SessionState.FAILED:
                self._teardown(account)
            elif state is not None:
                raise SlotBusy("Slot is busy")
            session = self._reserve(slot)
            try:
                container_id = self.docker.create(
                    self._container_name(session),
                    self.spec.container_body(
                        self.config.container_labels(account, session.session_id)
                    ),
                )
                session = replace(session, container_id=container_id)
                self._put(session)
                self.docker.start(container_id)
                self._wait_ready(container_id)
            except Exception as error:
                if isinstance(error, SessionError):
                    failure = error
                elif isinstance(error, DockerError):
                    failure = StartupFailed("Docker API failure during startup")
                else:
                    failure = StartupFailed("Unexpected startup failure")
                session = self._fail(self._get(account), failure.code)
                try:
                    self._cleanup(session)
                except DockerError as cleanup_error:
                    self._put(replace(session, error=CleanupFailed.code))
                    raise CleanupFailed(
                        "Startup failed and cleanup did not complete"
                    ) from cleanup_error
                self._put(replace(session, container_id=None, cleanup_pending=False))
                if failure is error:
                    raise
                raise failure from error
            session = replace(session, cleanup_pending=False)
            self._put(session)
            self.registry.transition(account, SessionState.READY)
            return session

    def terminate(self, account, session_id):
        """Remove only the selected session's project-owned container."""
        self._slot(account)
        with self._slot_locks[account]:
            session = self._get(account)
            if session is None or session.session_id != session_id:
                raise UnknownSession("Unknown session")
            self._teardown(account)

    def reap(self):
        """Clean up crashed and failed sessions without waiting for busy slots."""
        for slot in self.config.slots:
            lock = self._slot_locks[slot.account]
            if not lock.acquire(blocking=False):
                continue
            try:
                state = self.registry.state(slot.account)
                session = self._get(slot.account)
                try:
                    if state in ACTIVE and not self._running(session):
                        self._fail(session, "container_stopped")
                        state = SessionState.FAILED
                    if state is SessionState.FAILED:
                        self._teardown(slot.account)
                except SessionError:
                    pass
            finally:
                lock.release()

    def _reserve(self, slot):
        with self._host_lock:
            try:
                containers = self.docker.list_containers(self.config.ownership_filter)
            except DockerError as error:
                raise DockerUnavailable("Docker API unavailable") from error
            with self._meta_lock:
                sessions = dict(self._sessions)
            present = {
                container["labels"].get(SESSION_LABEL) for container in containers
            }
            used = len(containers)
            for other in self.config.slots:
                state = self.registry.state(other.account)
                if state is None:
                    continue
                session = sessions.get(other.account)
                if session and session.session_id in present:
                    continue
                if state is not SessionState.FAILED or (
                    session and session.cleanup_pending
                ):
                    used += 1
            if used >= self.capacity:
                raise CapacityExhausted("All player slots are in use")
            session = Session(slot.account, str(uuid4()), cleanup_pending=True)
            self._put(session)
            self.registry.transition(slot.account, SessionState.STARTING)
            return session

    def _container_name(self, session):
        return f"{PROJECT}-{self.config.deployment_id}-{session.account}-{session.session_id}"

    def _running(self, session):
        try:
            data = self.docker.inspect(session.container_id)
        except DockerError as error:
            if error.status == 404:
                return False
            raise DockerUnavailable("Docker API unavailable") from error
        labels = (data.get("Config") or {}).get("Labels") or {}
        if (
            not self.config.owns_container(labels)
            or labels.get(SESSION_LABEL) != session.session_id
        ):
            return False
        return (data.get("State") or {}).get("Running") is True

    def _wait_ready(self, container_id):
        deadline = self.clock() + self.start_timeout
        while True:
            if self.clock() >= deadline:
                raise StartupTimeout("Player container did not become ready")
            state = self.docker.inspect(container_id).get("State") or {}
            if self.clock() >= deadline:
                raise StartupTimeout("Player container did not become ready")
            if state.get("Running") is not True:
                raise StartupFailed("Player container exited during startup")
            health = (state.get("Health") or {}).get("Status")
            if health == "healthy":
                return
            if health is None:
                raise StartupFailed("Player container has no healthcheck")
            if health == "unhealthy":
                raise StartupFailed("Player container became unhealthy")
            remaining = deadline - self.clock()
            if remaining <= 0:
                raise StartupTimeout("Player container did not become ready")
            self.sleep(min(self.poll_interval, remaining))

    def _fail(self, session, error):
        session = replace(session, error=error, cleanup_pending=True)
        self._put(session)
        if self.registry.state(session.account) is not SessionState.FAILED:
            self.registry.transition(session.account, SessionState.FAILED)
        return session

    def _teardown(self, account):
        session = self._get(account)
        self.registry.transition(account, SessionState.STOPPING)
        try:
            self._cleanup(session)
        except DockerError as error:
            self._put(replace(session, error=CleanupFailed.code, cleanup_pending=True))
            self.registry.transition(account, SessionState.FAILED)
            raise CleanupFailed("Session cleanup did not complete") from error
        self._drop(account)
        self.registry.release(account)

    def _cleanup(self, session):
        """Remove the session's owned containers by label, then confirm removal."""
        labels = {**self.config.ownership_filter, SESSION_LABEL: session.session_id}

        def owned():
            return [
                container
                for container in self.docker.list_containers(labels)
                if self.config.owns_container(container["labels"])
                and container["labels"].get(SESSION_LABEL) == session.session_id
                and container["labels"].get(LABEL_PREFIX + "account") == session.account
            ]

        for container in owned():
            self.docker.remove(container["id"])
        if owned():
            raise DockerError("Session containers remain after removal")
