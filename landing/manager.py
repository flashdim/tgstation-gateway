"""Single-host player container lifecycle; not connected to the landing server.

Docker daemon access is privileged. Keep the socket private to the manager and
never expose this module's operations to players without a trusted ownership
check in front of them.
"""

from concurrent.futures import Future
from dataclasses import dataclass, field, replace
import http.client
import json
import os
import re
import stat
import socket
import threading
import time
from urllib.parse import quote, urlencode
from uuid import UUID, uuid4
import weakref

from sessions import LABEL_PREFIX, PROJECT, SessionState

SESSION_LABEL = LABEL_PREFIX + "session"
ACTIVE = {SessionState.READY, SessionState.RECONNECT_GRACE}
CONTROLLER_GRACE = 30
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


class SecretUnavailable(SessionError):
    status = 503
    code = "secret_unavailable"


class SecretMountFailed(StartupFailed):
    status = 502
    code = "secret_mount_failed"


class CleanupFailed(SessionError):
    status = 500
    code = "cleanup_failed"


class DockerError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class TraefikConfig:
    """Trusted per-player route settings backed by an existing Traefik middleware."""

    domain: str
    middleware: str
    entrypoint: str = "https"

    def __post_init__(self):
        domain_pattern = (
            r"(?=.{1,253}\Z)(?:[a-zA-Z0-9]"
            r"(?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
            r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+"
        )
        reference_pattern = r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9_-]+)?"
        if not isinstance(self.domain, str) or not re.fullmatch(
            domain_pattern, self.domain
        ):
            raise ValueError("Traefik player domain must be a DNS name")
        if not isinstance(self.middleware, str) or not re.fullmatch(
            reference_pattern, self.middleware
        ):
            raise ValueError("A single configured Traefik auth middleware is required")
        if not isinstance(self.entrypoint, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?", self.entrypoint
        ):
            raise ValueError("Invalid Traefik entrypoint")

    def labels(self, account, session_id, network):
        if not isinstance(account, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,24}[A-Za-z0-9])?", account
        ):
            raise ValueError("Invalid slot account for Traefik routing")
        if not isinstance(session_id, str) or str(UUID(session_id)) != session_id:
            raise ValueError("Traefik route requires a canonical session UUID")
        if not isinstance(network, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*", network
        ):
            raise ValueError("Traefik routing requires a valid shared Docker network")
        route_host = f"{account.lower().replace('_', '-')}.{self.domain}"
        route_id = "gateway-" + session_id.replace("-", "")
        router = f"{route_id}-router"
        service = f"{route_id}-service"
        return {
            "traefik.enable": "true",
            "traefik.docker.network": network,
            f"traefik.http.routers.{router}.rule": f"Host(`{route_host}`)",
            f"traefik.http.routers.{router}.entrypoints": self.entrypoint,
            f"traefik.http.routers.{router}.tls": "true",
            f"traefik.http.routers.{router}.middlewares": self.middleware,
            f"traefik.http.routers.{router}.service": service,
            f"traefik.http.services.{service}.loadbalancer.server.port": "8080",
        }


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
            raise DockerError(
                f"Docker API returned {response.status} for {method} {path}",
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

    def list_volumes(self, labels):
        filters = json.dumps({"label": [f"{k}={v}" for k, v in labels.items()]})
        result = self._request("GET", "/volumes", {"filters": filters})
        if not isinstance(result, dict) or "Volumes" not in result:
            raise DockerError("Docker API returned an invalid volume list")
        items = result["Volumes"]
        if items is None:
            items = []
        if not isinstance(items, list):
            raise DockerError("Docker API returned an invalid volume list")
        volumes = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("Name"), str):
                raise DockerError("Docker API returned an invalid volume")
            volumes.append({"name": item["Name"], "labels": item.get("Labels") or {}})
        return volumes

    def remove_volume(self, name):
        try:
            self._request("DELETE", f"/volumes/{quote(name, safe='')}", ok=(204,))
        except DockerError as error:
            if error.status != 404:
                raise


@dataclass(frozen=True)
class PlayerSpec:
    """Non-secret player container template supplied by the operator."""

    image: str
    seccomp_profile: str
    secret_directory: str
    environment: dict = field(default_factory=dict)
    controller_socket_directory: str = "/run/tgstation-gateway"
    network: str | None = None
    traefik: TraefikConfig | None = None
    shm_size: int = 2 * 1024**3
    memory: int = 4 * 1024**3
    nano_cpus: int = 2 * 10**9
    pids_limit: int = 512

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
        if not isinstance(self.secret_directory, str) or not os.path.isabs(
            self.secret_directory
        ):
            raise ValueError("Secret directory must be an absolute path")
        if not isinstance(self.controller_socket_directory, str) or not os.path.isabs(
            self.controller_socket_directory
        ):
            raise ValueError("Controller socket directory must be an absolute path")
        if self.traefik is not None and not isinstance(self.traefik, TraefikConfig):
            raise ValueError("Traefik configuration must be operator-supplied")
        if self.traefik and not self.network:
            raise ValueError("Traefik routing requires a shared Docker network")
        for value in (self.shm_size, self.memory, self.nano_cpus, self.pids_limit):
            if type(value) is not int or value <= 0:
                raise ValueError("Resource limits must be positive integers")
        for key, value in self.environment.items():
            if not isinstance(key, str) or not key or "=" in key:
                raise ValueError("Invalid environment variable name")
            if not isinstance(value, str):
                raise ValueError("Environment values must be strings")
            if key in {"BYOND_KEY_FILE", "WINEPREFIX", "HOME"}:
                raise ValueError("Session paths are managed by the manager")

    def secret_path(self, account):
        path = os.path.normpath(
            "/" + os.path.join(self.secret_directory, f"{account}_key.txt").lstrip("/")
        )
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_size == 0
                    or info.st_nlink != 1
                    or not (
                        (info.st_uid == 1000 and info.st_mode & stat.S_IRUSR)
                        or (
                            info.st_uid != 1000
                            and info.st_mode & stat.S_IRGRP
                            and info.st_mode & stat.S_IROTH
                        )
                    )
                ):
                    raise OSError("Invalid secret file")
            finally:
                os.close(fd)
        except OSError:
            raise SecretUnavailable("Selected credential file is unavailable") from None
        return path

    def container_body(self, labels, secret_path, controller_socket_path):
        target = "/run/secrets/byond_key.txt"
        controller_socket_target = "/run/gateway/controller.sock"
        host = {
            "Init": True,
            "ShmSize": self.shm_size,
            "Memory": self.memory,
            "NanoCpus": self.nano_cpus,
            "PidsLimit": self.pids_limit,
            "SecurityOpt": ["seccomp=" + self.seccomp_profile],
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": secret_path,
                    "Target": target,
                    "ReadOnly": True,
                },
                {
                    "Type": "bind",
                    "Source": controller_socket_path,
                    "Target": controller_socket_target,
                    "ReadOnly": False,
                },
            ]
            + [
                {
                    "Type": "volume",
                    "Target": volume_target,
                    "VolumeOptions": {"Labels": labels},
                }
                for volume_target in ("/home/ubuntu/.wine", "/home/ubuntu/.local/share")
            ],
        }
        if self.network:
            host["NetworkMode"] = self.network
        return {
            "Image": self.image,
            "Env": [f"{k}={v}" for k, v in sorted(self.environment.items())]
            + [
                f"BYOND_KEY_FILE={target}",
                f"GATEWAY_CONTROLLER_SOCKET={controller_socket_target}",
            ],
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
    create_indeterminate: bool = False
    controller_connected: bool = False
    grace_deadline: float | None = None


class ControllerEventChannel:
    """Private, per-session Unix socket for trusted Selkies controller events."""

    def __init__(self, path, callback):
        self.path = path
        self.callback = callback
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        if os.path.islink(os.path.dirname(path)):
            raise OSError("Controller socket directory must not be a symlink")
        os.chmod(os.path.dirname(path), 0o700)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        bound = False
        try:
            self.server.bind(path)
            bound = True
            os.chmod(path, 0o666)
            self.server.listen()
            self.server.settimeout(0.5)
        except Exception:
            self.server.close()
            if bound:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
            raise
        self.closed = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while not self.closed.is_set():
            try:
                connection, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with connection:
                connection.settimeout(1)
                try:
                    data = bytearray()
                    while len(data) <= 256 and not data.endswith(b"\n"):
                        chunk = connection.recv(257 - len(data))
                        if not chunk:
                            break
                        data.extend(chunk)
                    if len(data) > 256 or not data.endswith(b"\n"):
                        continue
                    event = json.loads(data)
                    if event in ("connected", "disconnected"):
                        self.callback(event)
                except (OSError, ValueError, TypeError):
                    continue

    def close(self):
        self.closed.set()
        self.server.close()
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=1)
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        try:
            os.rmdir(os.path.dirname(self.path))
        except OSError:
            pass


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
        self.controller_grace = CONTROLLER_GRACE
        self.clock = clock
        self.sleep = sleep
        self.capacity = len(self.config.slots)
        self._slot_locks = {s.account: threading.Lock() for s in self.config.slots}
        self._host_lock = threading.Lock()
        self._meta_lock = threading.Lock()
        self._sessions = {}
        self._attempt_lock = threading.Lock()
        self._attempts = {}
        self._controller_channels = {}
        self._grace_timers = {}
        weakref.finalize(
            self,
            self._close_resources,
            self._controller_channels,
            self._grace_timers,
        )

    @staticmethod
    def _close_resources(channels, timers):
        for timer in timers.values():
            timer.cancel()
        for channel in channels.values():
            channel.close()
        timers.clear()
        channels.clear()

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
            self.registry.release(account)
            self._sessions.pop(account, None)

    def _publish(self, session, state):
        with self._meta_lock:
            self.registry.transition(session.account, state)
            self._sessions[session.account] = session

    def status(self):
        """Operator status; session IDs are omitted."""
        with self._meta_lock:
            result = []
            for slot in self.config.slots:
                state = self.registry.state(slot.account)
                session = self._sessions.get(slot.account)
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
        with self._attempt_lock:
            attempt = self._attempts.get(account)
            leader = attempt is None
            if leader:
                attempt = self._attempts[account] = Future()
        if not leader:
            return attempt.result()
        with self._slot_locks[account]:
            try:
                result = self._start(slot)
            except BaseException as error:
                with self._attempt_lock:
                    attempt.set_exception(error)
                    del self._attempts[account]
                raise
            with self._attempt_lock:
                attempt.set_result(result)
                del self._attempts[account]
        return result

    def _start(self, slot):
        account = slot.account
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
        creating = False
        try:
            name = self._container_name(session)
            secret_path = self.spec.secret_path(account)
            socket_directory = os.path.join(
                self.spec.controller_socket_directory, session.session_id
            )
            os.makedirs(socket_directory, mode=0o700, exist_ok=True)
            socket_path = os.path.join(socket_directory, f"{session.session_id}.sock")

            manager_ref = weakref.ref(self)

            def controller_event(event):
                manager = manager_ref()
                if manager is not None:
                    manager._handle_controller_event(account, session.session_id, event)

            channel = ControllerEventChannel(
                socket_path, controller_event
            )
            with self._meta_lock:
                self._controller_channels[account] = channel
            body = self.spec.container_body(
                self.config.container_labels(account, session.session_id),
                secret_path,
                socket_path,
            )
            if self.spec.traefik:
                body["Labels"].update(
                    self.spec.traefik.labels(
                        account, session.session_id, self.spec.network
                    )
                )
            creating = True
            container_id = self.docker.create(name, body)
            creating = False
            session = replace(session, container_id=container_id)
            self._put(session)
            try:
                self.docker.start(container_id)
            except DockerError as error:
                raise SecretMountFailed(
                    "Container start or credential mount failed"
                ) from error
            self._wait_ready(container_id, secret_path)
        except Exception as error:
            if isinstance(error, SessionError):
                failure = error
            elif isinstance(error, DockerError):
                failure = StartupFailed("Docker API failure during startup")
            else:
                failure = StartupFailed("Unexpected startup failure")
            session = self._get(account)
            if creating:
                session = replace(session, create_indeterminate=True)
            session = self._fail(session, failure.code)
            self._stop_controller_channel(account)
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
        self._publish(session, SessionState.READY)
        return session

    def terminate(self, account, session_id):
        """Remove only the selected session's project-owned container."""
        self._slot(account)
        with self._slot_locks[account]:
            session = self._get(account)
            if session is None or session.session_id != session_id:
                raise UnknownSession("Unknown session")
            self._teardown(account)

    def controller_connected(self, account, session_id):
        """Resume the same live session before its controller grace expires."""
        self._slot(account)
        with self._slot_locks[account]:
            session = self._get(account)
            if session is None or session.session_id != session_id:
                return False
            state = self.registry.state(account)
            if state is SessionState.RECONNECT_GRACE:
                if self.clock() >= session.grace_deadline:
                    self._teardown(account)
                    return False
                self._cancel_grace(account)
                session = replace(
                    session, controller_connected=True, grace_deadline=None
                )
                self._publish(session, SessionState.READY)
            elif state is SessionState.READY:
                self._put(replace(session, controller_connected=True))
            else:
                return False
            return True

    def controller_disconnected(self, account, session_id):
        """Start grace only when the controlling stream disconnects."""
        self._slot(account)
        with self._slot_locks[account]:
            session = self._get(account)
            if session is None or session.session_id != session_id:
                return False
            if (
                self.registry.state(account) is not SessionState.READY
                or not session.controller_connected
            ):
                return False
            session = replace(
                session,
                controller_connected=False,
                grace_deadline=self.clock() + self.controller_grace,
            )
            self._publish(session, SessionState.RECONNECT_GRACE)
            self._schedule_grace(session)
            return True

    def _handle_controller_event(self, account, session_id, event):
        try:
            if event == "connected":
                self.controller_connected(account, session_id)
            elif event == "disconnected":
                self.controller_disconnected(account, session_id)
        except SessionError:
            pass

    def _schedule_grace(self, session):
        manager_ref = weakref.ref(self)

        def expire():
            manager = manager_ref()
            if manager is not None:
                try:
                    manager._expire_grace(
                        session.account, session.session_id, session.grace_deadline
                    )
                except SessionError:
                    pass

        timer = threading.Timer(
            self.controller_grace,
            expire,
        )
        timer.daemon = True
        with self._meta_lock:
            previous = self._grace_timers.pop(session.account, None)
            self._grace_timers[session.account] = timer
        if previous:
            previous.cancel()
        timer.start()

    def _cancel_grace(self, account):
        with self._meta_lock:
            timer = self._grace_timers.pop(account, None)
        if timer:
            timer.cancel()

    def _expire_grace(self, account, session_id, deadline):
        with self._slot_locks[account]:
            session = self._get(account)
            if (
                session is None
                or session.session_id != session_id
                or session.grace_deadline != deadline
                or self.clock() < deadline
                or self.registry.state(account) is not SessionState.RECONNECT_GRACE
            ):
                return
            try:
                self._teardown(account)
            except SessionError:
                pass

    def _stop_controller_channel(self, account):
        with self._meta_lock:
            channel = self._controller_channels.pop(account, None)
        if channel:
            channel.close()

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
                    if (
                        state is SessionState.RECONNECT_GRACE
                        and session.grace_deadline is not None
                        and self.clock() >= session.grace_deadline
                    ):
                        self._teardown(slot.account)
                        continue
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
                present = {
                    container["labels"].get(SESSION_LABEL) for container in containers
                }
                used = len(containers)
                for other in self.config.slots:
                    state = self.registry.state(other.account)
                    if state is None:
                        continue
                    session = self._sessions.get(other.account)
                    if session and session.session_id in present:
                        continue
                    if state is not SessionState.FAILED or (
                        session and session.cleanup_pending
                    ):
                        used += 1
                if used >= self.capacity:
                    raise CapacityExhausted("All player slots are in use")
                session = Session(slot.account, str(uuid4()), cleanup_pending=True)
                self.registry.transition(slot.account, SessionState.STARTING)
                self._sessions[slot.account] = session
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

    def _wait_ready(self, container_id, secret_path):
        deadline = self.clock() + self.start_timeout
        while True:
            if self.clock() >= deadline:
                raise StartupTimeout("Player container did not become ready")
            inspection = self.docker.inspect(container_id)
            if self.clock() >= deadline:
                raise StartupTimeout("Player container did not become ready")
            mounts = inspection.get("Mounts") or []
            if not any(
                mount.get("Type") == "bind"
                and mount.get("Source") == secret_path
                and mount.get("Destination") == "/run/secrets/byond_key.txt"
                and mount.get("RW") is False
                for mount in mounts
            ):
                raise SecretMountFailed("Credential mount could not be verified")
            state = inspection.get("State") or {}
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
        with self._meta_lock:
            if self.registry.state(session.account) is not SessionState.FAILED:
                self.registry.transition(session.account, SessionState.FAILED)
            self._sessions[session.account] = session
        return session

    def _teardown(self, account):
        session = self._get(account)
        self._publish(session, SessionState.STOPPING)
        self._cancel_grace(account)
        self._stop_controller_channel(account)
        try:
            self._cleanup(session)
        except DockerError as error:
            self._publish(
                replace(session, error=CleanupFailed.code, cleanup_pending=True),
                SessionState.FAILED,
            )
            raise CleanupFailed("Session cleanup did not complete") from error
        self._drop(account)

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

        def owned_volumes():
            return [
                volume
                for volume in self.docker.list_volumes(labels)
                if self.config.owns_container(volume["labels"])
                and volume["labels"].get(SESSION_LABEL) == session.session_id
                and volume["labels"].get(LABEL_PREFIX + "account") == session.account
            ]

        for volume in owned_volumes():
            self.docker.remove_volume(volume["name"])
        if owned_volumes():
            raise DockerError("Session volumes remain after removal")
        if session.create_indeterminate:
            raise DockerError("Container creation outcome is indeterminate")
