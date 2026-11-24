from http.server import BaseHTTPRequestHandler
import json
from pathlib import Path
import socketserver
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "landing"))

from manager import (  # noqa: E402
    CapacityExhausted,
    CleanupFailed,
    DockerClient,
    DockerError,
    DockerUnavailable,
    PlayerSpec,
    SessionManager,
    StartupFailed,
    StartupTimeout,
    UnknownSession,
    UnknownSlot,
)
from sessions import LABEL_PREFIX, SessionConfig, SessionState, SlotRegistry  # noqa: E402

SECCOMP = (ROOT / "examples" / "seccomp.json").read_text()


class FakeDocker:
    def __init__(self):
        self.lock = threading.Lock()
        self.containers = {}
        self.removed = []
        self.fail = {}
        self.health = "healthy"
        self.running_after_start = True
        self.hooks = {}
        self.peak = 0

    def _call(self, method):
        hook = self.hooks.get(method)
        if hook:
            hook()
        error = self.fail.get(method)
        if error:
            raise error

    def add(self, labels, running=True):
        container_id = uuid4().hex
        with self.lock:
            self.containers[container_id] = {
                "labels": dict(labels),
                "running": running,
                "health": "healthy",
            }
            self.peak = max(self.peak, len(self.containers))
        return container_id

    def list_containers(self, labels):
        self._call("list")
        with self.lock:
            return [
                {"id": container_id, "labels": dict(data["labels"])}
                for container_id, data in self.containers.items()
                if all(data["labels"].get(k) == v for k, v in labels.items())
            ]

    def create(self, name, body):
        self._call("create_before")
        container_id = self.add(body["Labels"], running=False)
        with self.lock:
            self.containers[container_id].update(name=name, body=body)
        self._call("create")
        return container_id

    def start(self, container_id):
        self._call("start")
        with self.lock:
            self.containers[container_id]["running"] = self.running_after_start
            self.containers[container_id]["health"] = self.health

    def inspect(self, container_id):
        self._call("inspect")
        with self.lock:
            if container_id not in self.containers:
                raise DockerError("missing", 404)
            data = self.containers[container_id]
            return {
                "Config": {"Labels": dict(data["labels"])},
                "State": {
                    "Running": data["running"],
                    "Health": {"Status": data["health"]},
                },
            }

    def remove(self, container_id):
        self._call("remove")
        with self.lock:
            if self.containers.pop(container_id, None) is not None:
                self.removed.append(container_id)


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def make_manager(count=2, docker=None, **kwargs):
    config = SessionConfig.from_env(
        {
            "GATEWAY_SLOT_COUNT": str(count),
            "GATEWAY_SLOT_PATH": "/{account}/",
            "GATEWAY_DEPLOYMENT_ID": "deployment-a",
        }
    )
    registry = SlotRegistry(config)
    clock = FakeClock()
    spec = PlayerSpec(
        image="player:test",
        seccomp_profile=SECCOMP,
        environment={"BYOND_SERVER": "byond://game.test:1337"},
    )
    manager = SessionManager(
        registry,
        docker or FakeDocker(),
        spec,
        start_timeout=kwargs.pop("start_timeout", 10),
        poll_interval=1,
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )
    return manager


def run_concurrently(count, target):
    barrier = threading.Barrier(count)
    results = [None] * count

    def worker(index):
        barrier.wait()
        try:
            results[index] = target(index)
        except Exception as error:
            results[index] = error

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    return results


class SessionManagerTest(unittest.TestCase):
    def setUp(self):
        self.manager = make_manager()
        self.docker = self.manager.docker
        self.account = "LGplayer01"

    def state(self, account="LGplayer01"):
        return self.manager.registry.state(account)

    def test_start_creates_owned_hardened_container_once(self):
        session = self.manager.start(self.account)
        self.assertEqual(self.state(), SessionState.READY)
        container = self.docker.containers[session.container_id]
        self.assertEqual(
            container["labels"],
            self.manager.config.container_labels(self.account, session.session_id),
        )
        host = container["body"]["HostConfig"]
        self.assertEqual(host["SecurityOpt"], ["seccomp=" + SECCOMP])
        self.assertTrue(host["Init"])
        self.assertEqual(host["ShmSize"], 2 * 1024**3)
        self.assertEqual(host["RestartPolicy"], {"Name": "no"})
        self.assertIn("BYOND_SERVER=byond://game.test:1337", container["body"]["Env"])
        self.assertIn(session.session_id, container["name"])
        self.assertEqual(self.manager.start(self.account), session)
        self.assertEqual(len(self.docker.containers), 1)

    def test_player_spec_requires_seccomp_profile(self):
        for profile in (None, "", "not json", "[]", "{}"):
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    PlayerSpec(image="player:test", seccomp_profile=profile)
        with self.assertRaises(ValueError):
            PlayerSpec(image="", seccomp_profile=SECCOMP)
        with self.assertRaises(ValueError):
            PlayerSpec(image="x", seccomp_profile=SECCOMP, environment={"A=B": "1"})

    def test_concurrent_first_requests_create_exactly_one_container(self):
        self.docker.hooks["create_before"] = lambda: time.sleep(0.05)
        results = run_concurrently(8, lambda _: self.manager.start(self.account))
        self.assertEqual(len(self.docker.containers), 1)
        self.assertEqual(len({session.session_id for session in results}), 1)
        self.assertEqual(self.state(), SessionState.READY)

    def test_all_slots_start_concurrently_within_capacity(self):
        manager = make_manager(count=4)
        manager.docker.hooks["create_before"] = lambda: time.sleep(0.02)
        accounts = [slot.account for slot in manager.config.slots]
        results = run_concurrently(8, lambda i: manager.start(accounts[i % 4]))
        self.assertFalse([r for r in results if isinstance(r, Exception)])
        self.assertEqual(len(manager.docker.containers), 4)
        self.assertEqual(manager.docker.peak, 4)

    def test_simultaneous_capacity_exhaustion_is_atomic(self):
        manager = make_manager(count=3)
        docker = manager.docker
        # Untracked project containers, e.g. left by a previous manager process.
        for _ in range(2):
            docker.add(
                manager.config.container_labels("LGplayer03", str(uuid4())),
            )
        docker.hooks["create_before"] = lambda: time.sleep(0.02)
        accounts = [slot.account for slot in manager.config.slots]
        results = run_concurrently(3, lambda i: manager.start(accounts[i]))
        errors = [r for r in results if isinstance(r, CapacityExhausted)]
        self.assertEqual(len(errors), 2)
        self.assertEqual(errors[0].status, 503)
        self.assertEqual(len(docker.containers), 3)
        self.assertLessEqual(docker.peak, 3)
        states = [manager.registry.state(a) for a in accounts]
        self.assertEqual(states.count(SessionState.READY), 1)
        self.assertEqual(states.count(None), 2)

    def test_capacity_counts_every_owned_container(self):
        manager = make_manager(count=2)
        session = manager.start("LGplayer01")
        manager.docker.add(
            manager.config.container_labels("LGplayer01", session.session_id)
        )
        with self.assertRaises(CapacityExhausted):
            manager.start("LGplayer02")
        self.assertEqual(len(manager.docker.containers), 2)

    def test_untracked_containers_of_other_deployments_do_not_use_capacity(self):
        manager = make_manager(count=1)
        other = SessionConfig.from_env({"GATEWAY_DEPLOYMENT_ID": "deployment-b"})
        manager.docker.add(other.container_labels("LGplayer01", str(uuid4())))
        manager.docker.add({"unrelated": "container"})
        manager.start("LGplayer01")
        self.assertEqual(manager.registry.state("LGplayer01"), SessionState.READY)

    def test_invalid_slot_references(self):
        for account in ("LGplayer00", "LGplayer03", "lgplayer01", "", None, 1, []):
            with self.subTest(account=account):
                with self.assertRaises(UnknownSlot) as context:
                    self.manager.start(account)
                self.assertEqual(context.exception.status, 404)
                with self.assertRaises(UnknownSlot):
                    self.manager.terminate(account, str(uuid4()))
        self.assertEqual(self.docker.containers, {})

    def test_startup_timeout_fails_cleans_up_and_retries(self):
        self.docker.health = "starting"
        with self.assertRaises(StartupTimeout) as context:
            self.manager.start(self.account)
        self.assertEqual(context.exception.status, 504)
        self.assertEqual(self.state(), SessionState.FAILED)
        self.assertEqual(
            self.manager.status()[0],
            {
                "account": self.account,
                "state": "failed",
                "error": "startup_timeout",
                "cleanup_pending": False,
            },
        )
        self.assertEqual(self.docker.containers, {})
        self.assertEqual(len(self.docker.removed), 1)
        self.docker.health = "healthy"
        self.manager.start(self.account)
        self.assertEqual(self.state(), SessionState.READY)
        self.assertIsNone(self.manager.status()[0]["error"])

    def test_docker_api_unavailable_does_not_reserve_slot(self):
        self.docker.fail["list"] = DockerError("down")
        with self.assertRaises(DockerUnavailable) as context:
            self.manager.start(self.account)
        self.assertEqual(context.exception.status, 502)
        self.assertIsNone(self.state())

    def test_docker_and_container_failures_clean_partial_starts(self):
        cases = {
            "create": lambda d: d.fail.__setitem__("create", DockerError("x", 500)),
            "start": lambda d: d.fail.__setitem__("start", DockerError("x", 500)),
            "inspect": lambda d: d.fail.__setitem__("inspect", DockerError("x")),
            "exited": lambda d: setattr(d, "running_after_start", False),
            "unhealthy": lambda d: setattr(d, "health", "unhealthy"),
            "no healthcheck": lambda d: setattr(d, "health", None),
        }
        for name, setup in cases.items():
            with self.subTest(name=name):
                manager = make_manager()
                setup(manager.docker)
                with self.assertRaises(StartupFailed):
                    manager.start(self.account)
                self.assertEqual(manager.docker.containers, {})
                self.assertEqual(manager.registry.state(self.account), "failed")
                self.assertEqual(manager.status()[0]["error"], "startup_failed")

    def test_cleanup_failure_is_observable_and_keeps_capacity(self):
        manager = make_manager(count=1)
        docker = manager.docker
        docker.fail["start"] = DockerError("x", 500)
        docker.fail["remove"] = DockerError("x", 500)
        with self.assertRaises(CleanupFailed) as context:
            manager.start(self.account)
        self.assertIsInstance(context.exception.__cause__, DockerError)
        self.assertEqual(manager.registry.state(self.account), SessionState.FAILED)
        self.assertEqual(
            manager.status()[0],
            {
                "account": self.account,
                "state": "failed",
                "error": "cleanup_failed",
                "cleanup_pending": True,
            },
        )
        self.assertEqual(len(docker.containers), 1)
        with self.assertRaises(CleanupFailed):
            manager.start(self.account)
        self.assertEqual(len(docker.containers), 1)
        del docker.fail["remove"], docker.fail["start"]
        session = manager.start(self.account)
        self.assertEqual(list(docker.containers), [session.container_id])

    def test_terminate_cleanup_failure_marks_failed(self):
        session = self.manager.start(self.account)
        self.docker.fail["remove"] = DockerError("x", 500)
        with self.assertRaises(CleanupFailed):
            self.manager.terminate(self.account, session.session_id)
        self.assertEqual(self.state(), SessionState.FAILED)
        self.assertTrue(self.manager.status()[0]["cleanup_pending"])
        del self.docker.fail["remove"]
        self.manager.terminate(self.account, session.session_id)
        self.assertIsNone(self.state())
        self.assertEqual(self.docker.containers, {})

    def test_cleanup_that_leaves_containers_fails(self):
        session = self.manager.start(self.account)
        self.docker.remove = lambda container_id: None
        with self.assertRaises(CleanupFailed):
            self.manager.terminate(self.account, session.session_id)
        self.assertIn(session.container_id, self.docker.containers)

    def test_terminate_removes_only_selected_owned_session(self):
        first = self.manager.start("LGplayer01")
        second = self.manager.start("LGplayer02")
        config = self.manager.config
        other = SessionConfig.from_env({"GATEWAY_DEPLOYMENT_ID": "deployment-b"})
        foreign = self.docker.add(
            other.container_labels("LGplayer01", first.session_id)
        )
        forged = self.docker.add(
            {
                **config.container_labels("LGplayer01", first.session_id),
                LABEL_PREFIX + "slot": "02",
            }
        )
        stopping = []
        self.docker.hooks["remove"] = lambda: stopping.append(self.state())
        self.manager.terminate("LGplayer01", first.session_id)
        self.assertEqual(stopping, [SessionState.STOPPING])
        self.assertEqual(self.docker.removed, [first.container_id])
        self.assertEqual(
            set(self.docker.containers), {second.container_id, foreign, forged}
        )
        self.assertIsNone(self.state())
        self.assertEqual(self.state("LGplayer02"), SessionState.READY)

    def test_terminate_rejects_unknown_or_stale_sessions(self):
        with self.assertRaises(UnknownSession):
            self.manager.terminate(self.account, str(uuid4()))
        old = self.manager.start(self.account)
        self.manager.terminate(self.account, old.session_id)
        new = self.manager.start(self.account)
        for value in (old.session_id, None, "", new.session_id.upper()):
            with self.assertRaises(UnknownSession):
                self.manager.terminate(self.account, value)
        self.assertIn(new.container_id, self.docker.containers)
        self.assertEqual(self.state(), SessionState.READY)

    def test_concurrent_terminations_remove_once(self):
        session = self.manager.start(self.account)
        self.docker.hooks["remove"] = lambda: time.sleep(0.02)
        results = run_concurrently(
            4, lambda _: self.manager.terminate(self.account, session.session_id)
        )
        self.assertEqual(results.count(None), 1)
        self.assertEqual(
            sum(isinstance(r, UnknownSession) for r in results), len(results) - 1
        )
        self.assertEqual(self.docker.removed, [session.container_id])
        self.assertIsNone(self.state())

    def test_terminate_waits_for_startup_then_tears_down(self):
        entered = threading.Event()
        proceed = threading.Event()

        def block():
            entered.set()
            proceed.wait(5)

        self.docker.hooks["start"] = block
        result = {}
        starter = threading.Thread(
            target=lambda: result.update(session=self.manager.start(self.account))
        )
        starter.start()
        self.assertTrue(entered.wait(5))
        self.assertEqual(self.state(), SessionState.STARTING)
        self.assertEqual(self.manager.status()[0]["state"], "starting")
        session_id = self.manager._get(self.account).session_id
        terminator = threading.Thread(
            target=self.manager.terminate, args=(self.account, session_id)
        )
        terminator.start()
        time.sleep(0.05)
        self.assertEqual(self.state(), SessionState.STARTING)
        proceed.set()
        starter.join(5)
        terminator.join(5)
        self.assertEqual(result["session"].session_id, session_id)
        self.assertIsNone(self.state())
        self.assertEqual(self.docker.containers, {})

    def test_start_and_terminate_race_never_leaks_containers(self):
        session = self.manager.start(self.account)
        self.docker.hooks["create_before"] = lambda: time.sleep(0.01)

        def act(index):
            if index % 2:
                return self.manager.start(self.account)
            return self.manager.terminate(self.account, session.session_id)

        run_concurrently(6, act)
        state = self.state()
        self.assertLessEqual(len(self.docker.containers), 1)
        if state is None:
            self.assertEqual(self.docker.containers, {})
        else:
            self.assertEqual(state, SessionState.READY)
            current = self.manager._get(self.account)
            self.assertEqual(list(self.docker.containers), [current.container_id])

    def test_crashed_sessions_are_reaped_or_replaced(self):
        session = self.manager.start(self.account)
        self.docker.containers[session.container_id]["running"] = False
        self.manager.reap()
        self.assertIsNone(self.state())
        self.assertEqual(self.docker.containers, {})

        session = self.manager.start(self.account)
        del self.docker.containers[session.container_id]
        replacement = self.manager.start(self.account)
        self.assertNotEqual(replacement.session_id, session.session_id)
        self.assertEqual(list(self.docker.containers), [replacement.container_id])

    def test_reap_leaves_busy_and_healthy_slots(self):
        session = self.manager.start(self.account)
        self.manager.reap()
        self.assertEqual(self.state(), SessionState.READY)
        self.docker.containers[session.container_id]["running"] = False
        self.docker.fail["remove"] = DockerError("x", 500)
        self.manager.reap()
        self.assertEqual(self.state(), SessionState.FAILED)
        self.assertEqual(self.manager.status()[0]["error"], "cleanup_failed")
        with self.manager._slot_locks[self.account]:
            del self.docker.fail["remove"]
            self.manager.reap()
            self.assertEqual(self.state(), SessionState.FAILED)
        self.manager.reap()
        self.assertIsNone(self.state())

    def test_docker_inspect_failure_on_active_session_keeps_state(self):
        self.manager.start(self.account)
        self.docker.fail["inspect"] = DockerError("down")
        with self.assertRaises(DockerUnavailable):
            self.manager.start(self.account)
        self.assertEqual(self.state(), SessionState.READY)

    def test_rejects_invalid_timeouts(self):
        for value in (0, -1):
            with self.assertRaises(ValueError):
                make_manager(start_timeout=value)


class FakeDockerHandler(BaseHTTPRequestHandler):
    def address_string(self):
        return "docker"

    def log_message(self, *args):
        pass

    def _reply(self, status, body=None):
        data = b"" if body is None else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else None
        url = urlsplit(self.path)
        self.server.requests.append((self.command, url.path, parse_qs(url.query), body))
        route = (self.command, url.path)
        if route == ("GET", "/v1.44/containers/json"):
            self._reply(200, [{"Id": "abc", "Labels": {"a": "b"}}])
        elif route == ("POST", "/v1.44/containers/create"):
            self._reply(201, {"Id": "abc"})
        elif route == ("POST", "/v1.44/containers/abc/start"):
            self._reply(204)
        elif route == ("DELETE", "/v1.44/containers/missing"):
            self._reply(404, {"message": "No such container"})
        elif route == ("DELETE", "/v1.44/containers/abc"):
            self._reply(204)
        else:
            self._reply(500, {"message": "boom"})

    do_GET = do_POST = do_DELETE = _handle


class DockerClientTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        path = str(Path(self.directory.name) / "docker.sock")

        class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

        self.server = Server(path, FakeDockerHandler)
        self.server.requests = []
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()
        self.client = DockerClient(path, timeout=5)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)
        self.directory.cleanup()

    def test_engine_api_requests(self):
        self.assertEqual(
            self.client.list_containers({"x": "1"}),
            [{"id": "abc", "labels": {"a": "b"}}],
        )
        self.assertEqual(self.client.create("name", {"Image": "i"}), "abc")
        self.client.start("abc")
        self.client.remove("abc")
        self.client.remove("missing")
        requests = self.server.requests
        self.assertEqual(requests[0][2]["all"], ["1"])
        self.assertEqual(json.loads(requests[0][2]["filters"][0]), {"label": ["x=1"]})
        self.assertEqual(requests[1][2], {"name": ["name"]})
        self.assertEqual(requests[1][3], {"Image": "i"})
        self.assertEqual(requests[3][2], {"force": ["1"], "v": ["1"]})

    def test_errors_are_explicit(self):
        with self.assertRaises(DockerError) as context:
            self.client.inspect("abc")
        self.assertEqual(context.exception.status, 500)
        self.assertIn("boom", str(context.exception))
        with self.assertRaises(DockerError):
            self.client.start("../other")
        self.assertEqual(
            self.server.requests[-1][1], "/v1.44/containers/..%2Fother/start"
        )
        missing = DockerClient(str(Path(self.directory.name) / "none.sock"))
        with self.assertRaises(DockerError) as context:
            missing.list_containers({})
        self.assertIsNone(context.exception.status)


if __name__ == "__main__":
    unittest.main()
