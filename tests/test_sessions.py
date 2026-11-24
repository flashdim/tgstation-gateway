import io
import json
from functools import partial
from pathlib import Path
import subprocess
import sys
import threading
import unittest
from unittest import mock
from uuid import uuid4
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "landing"))

import server  # noqa: E402
from sessions import (  # noqa: E402
    ConfigError,
    LABEL_PREFIX,
    SessionConfig,
    SessionState,
    SlotRegistry,
)


def configuration(**env):
    return SessionConfig.from_env({"GATEWAY_SLOT_PATH": "/{account}/{number}/", **env})


class SessionConfigTest(unittest.TestCase):
    def test_counts_and_account_derivation(self):
        for count in (1, 9, 10, 99):
            with self.subTest(count=count):
                config = configuration(
                    GATEWAY_SLOT_COUNT=str(count), GATEWAY_ACCOUNT_PREFIX="Test_-"
                )
                self.assertEqual(len(config.slots), count)
                self.assertEqual(config.slots[0].account, "Test_-01")
                self.assertEqual(config.slots[-1].account, f"Test_-{count:02d}")
                self.assertEqual(len({slot.path for slot in config.slots}), count)
        self.assertEqual(configuration(GATEWAY_SLOT_COUNT="01").slots[0].number, 1)

    def test_invalid_counts(self):
        for value in ("0", "100", "-1", "1.0", "+1", "²", "١", "9" * 5000):
            with self.subTest(value=value[:10]):
                with self.assertRaisesRegex(ConfigError, "GATEWAY_SLOT_COUNT"):
                    configuration(GATEWAY_SLOT_COUNT=value)

    def test_prefixes(self):
        for value in ("A", "a" * 24, "Player_1-"):
            with self.subTest(value=value):
                self.assertEqual(
                    configuration(GATEWAY_ACCOUNT_PREFIX=value).slots[0].account,
                    value + "01",
                )
        for value in ("a" * 25, "../", "a.b", "a/b", "a b", "é", "{number}"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ConfigError, "GATEWAY_ACCOUNT_PREFIX"):
                    configuration(GATEWAY_ACCOUNT_PREFIX=value)

    def test_exact_allowlisted_accounts_and_paths(self):
        config = configuration(GATEWAY_SLOT_COUNT="2")
        slot = config.slot("LGplayer02")
        self.assertEqual(slot.path, "/LGplayer02/02/")
        self.assertEqual(slot.url, "http://localhost:8080/LGplayer02/02/")
        self.assertIs(config.route(slot.path), slot)
        for account in ("LGplayer00", "LGplayer03", "LGplayer1", "Other01", 1, None):
            with self.subTest(account=account):
                with self.assertRaises(ValueError):
                    config.slot(account)
        for path in (
            "/LGplayer03/03/",
            "/LGplayer02/02",
            "//LGplayer02/02/",
            "/LGplayer02/02/?upstream=https://evil.test",
            "/%4cGplayer02/02/",
            "https://evil.test/",
            "/LGplayer02/02/#shared",
            None,
        ):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    config.route(path)

    def test_paths(self):
        for path in (
            "/",
            "/slot/{number}/",
            "/{account}/",
            "/~/{account}-{number}.html",
        ):
            with self.subTest(path=path):
                self.assertTrue(
                    configuration(GATEWAY_SLOT_PATH=path).slots[0].path.startswith("/")
                )
        for path in (
            "relative",
            "//evil.test/",
            "/x//y",
            "/../",
            "/./",
            "/{unknown}/",
            "/{{account}}/",
            "/%2e%2e/",
            "/?host=evil",
            "/#fragment",
            r"/a\b",
        ):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ConfigError, "GATEWAY_SLOT_PATH"):
                    configuration(GATEWAY_SLOT_PATH=path)
        with self.assertRaisesRegex(ConfigError, "GATEWAY_SLOT_PATH"):
            configuration(GATEWAY_SLOT_COUNT="2", GATEWAY_SLOT_PATH="/")

    def test_deployment_identity(self):
        self.assertEqual(configuration().deployment_id, "local")
        for value in ("prod", "A_1.test-2", "a" * 64):
            self.assertEqual(
                configuration(GATEWAY_DEPLOYMENT_ID=value).deployment_id, value
            )
        for value in ("", " ", "../", "_prod", "a" * 65, "a/b", "é"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ConfigError, "GATEWAY_DEPLOYMENT_ID"):
                    configuration(GATEWAY_DEPLOYMENT_ID=value)

    def test_removed_active_configuration_is_rejected(self):
        for value in ("", "LGplayer01"):
            with self.assertRaisesRegex(ConfigError, "GATEWAY_ACTIVE_SLOTS is removed"):
                configuration(GATEWAY_ACTIVE_SLOTS=value)

    def test_invalid_startup_does_not_start_threads_or_bind(self):
        for env in (
            {"GATEWAY_SLOT_COUNT": "100"},
            {"GATEWAY_ACCOUNT_PREFIX": "invalid/"},
            {"GATEWAY_SLOT_PATH": "//evil.test"},
            {"GATEWAY_DEPLOYMENT_ID": ""},
            {"GATEWAY_QUERY_HOST": "game.test"},
            {"GATEWAY_ACTIVE_SLOTS": "LGplayer01"},
        ):
            with (
                self.subTest(env=env),
                mock.patch.dict(server.os.environ, env, clear=True),
                mock.patch.object(server, "ThreadingHTTPServer") as httpd,
                mock.patch.object(server.threading, "Thread") as thread,
                mock.patch.object(server, "StatusMonitor") as monitor,
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                self.assertEqual(server.main(), 2)
                self.assertIn("Invalid landing configuration:", stderr.getvalue())
                httpd.assert_not_called()
                thread.assert_not_called()
                monitor.assert_not_called()

    def test_cli_reports_invalid_config(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "landing" / "server.py")],
            env={"GATEWAY_SLOT_COUNT": "²"},
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("GATEWAY_SLOT_COUNT", result.stderr)
        self.assertEqual(result.stdout, "")


class ContainerOwnershipTest(unittest.TestCase):
    def setUp(self):
        self.config = configuration(GATEWAY_DEPLOYMENT_ID="deployment-a")
        self.session_id = str(uuid4())
        self.labels = self.config.container_labels("LGplayer01", self.session_id)

    def test_project_labels_and_deployment_isolation(self):
        self.assertEqual(
            self.labels,
            {
                LABEL_PREFIX + "project": "tgstation-gateway",
                LABEL_PREFIX + "deployment": "deployment-a",
                LABEL_PREFIX + "role": "player",
                LABEL_PREFIX + "slot": "01",
                LABEL_PREFIX + "account": "LGplayer01",
                LABEL_PREFIX + "session": self.session_id,
            },
        )
        self.assertTrue(self.config.owns_container(self.labels))
        other = configuration(GATEWAY_DEPLOYMENT_ID="deployment-b")
        self.assertFalse(other.owns_container(self.labels))
        self.assertFalse(
            self.config.owns_container(
                other.container_labels("LGplayer01", self.session_id)
            )
        )
        self.assertTrue(self.config.owns_container({**self.labels, "other": "label"}))

    def test_missing_or_mismatched_labels_are_never_owned(self):
        for key in self.labels:
            with self.subTest(key=key):
                missing = dict(self.labels)
                del missing[key]
                self.assertFalse(self.config.owns_container(missing))
                self.assertFalse(
                    self.config.owns_container({**self.labels, key: "unrelated"})
                )
        for labels in (None, {}, [], self.config.ownership_filter):
            self.assertFalse(self.config.owns_container(labels))
        self.assertFalse(
            self.config.owns_container(
                {
                    **self.labels,
                    LABEL_PREFIX + "account": "LGplayer02",
                    LABEL_PREFIX + "slot": "02",
                }
            )
        )

    def test_label_generation_rejects_unknown_slots_and_session_ids(self):
        with self.assertRaises(ValueError):
            self.config.container_labels("LGplayer02", self.session_id)
        for value in (None, "", "not-a-session", self.session_id.replace("-", "")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.config.container_labels("LGplayer01", value)


class SlotLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.registry = SlotRegistry(configuration(GATEWAY_SLOT_COUNT="2"))
        self.account = "LGplayer01"

    def test_lifecycle_and_slot_isolation(self):
        self.assertIsNone(self.registry.snapshot()[0]["state"])
        for state in (
            SessionState.STARTING,
            SessionState.READY,
            SessionState.RECONNECT_GRACE,
            SessionState.READY,
            SessionState.STOPPING,
            SessionState.FAILED,
            SessionState.STOPPING,
        ):
            self.registry.transition(self.account, state)
            self.assertEqual(self.registry.snapshot()[0]["state"], state.value)
            self.assertIsNone(self.registry.snapshot()[1]["state"])
        self.registry.release(self.account)
        self.assertIsNone(self.registry.snapshot()[0]["state"])
        self.registry.transition(self.account, SessionState.STARTING)
        self.registry.transition(self.account, SessionState.FAILED)
        self.registry.release(self.account)

    def test_invalid_transitions_do_not_change_state(self):
        for target in (SessionState.READY, SessionState.FAILED, "starting", None):
            with self.assertRaises(ValueError):
                self.registry.transition(self.account, target)
            self.assertIsNone(self.registry.snapshot()[0]["state"])
        self.registry.transition(self.account, SessionState.STARTING)
        for target in (SessionState.STARTING, SessionState.RECONNECT_GRACE):
            with self.assertRaises(ValueError):
                self.registry.transition(self.account, target)
        with self.assertRaises(ValueError):
            self.registry.release(self.account)
        for account in ("LGplayer00", "LGplayer03", "unknown"):
            with self.assertRaises(ValueError):
                self.registry.transition(account, SessionState.STARTING)
            with self.assertRaises(ValueError):
                self.registry.release(account)

    def test_snapshots_cannot_mutate_state(self):
        snapshot = self.registry.snapshot()
        snapshot[0]["state"] = "ready"
        snapshot[0]["url"] = "https://evil.test/"
        self.assertIsNone(self.registry.snapshot()[0]["state"])
        self.assertNotEqual(self.registry.snapshot()[0]["url"], snapshot[0]["url"])

    def test_concurrent_starts_reserve_only_once(self):
        barrier = threading.Barrier(2)
        outcomes = []

        def start():
            barrier.wait()
            try:
                self.registry.transition(self.account, SessionState.STARTING)
                outcomes.append(True)
            except ValueError:
                outcomes.append(False)

        threads = [threading.Thread(target=start) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertCountEqual(outcomes, [True, False])

    def test_http_slots_follow_lifecycle_without_accepting_client_state(self):
        handler = partial(server.LandingHandler, directory=str(ROOT / "landing"))
        with (
            mock.patch.object(server.LandingHandler, "slot_registry", self.registry),
            mock.patch.object(server.LandingHandler, "log_message"),
            server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as httpd,
        ):
            thread = threading.Thread(target=httpd.serve_forever)
            thread.start()
            try:
                for state in (
                    SessionState.STARTING,
                    SessionState.READY,
                    SessionState.FAILED,
                ):
                    self.registry.transition(self.account, state)
                    url = (
                        f"http://127.0.0.1:{httpd.server_port}/slots.js"
                        "?state=ready&account=LGplayer02&upstream=https://evil.test"
                    )
                    with urlopen(url, timeout=5) as response:
                        script = response.read().decode()
                        data = json.loads(
                            script.split("window.GATEWAY_SLOTS = ", 1)[1][:-2]
                        )
                        self.assertEqual(response.headers["Cache-Control"], "no-store")
                        self.assertEqual(data[0]["state"], state.value)
                        self.assertIsNone(data[1]["state"])
                        self.assertEqual(
                            data[0]["url"], self.registry.snapshot()[0]["url"]
                        )
            finally:
                httpd.shutdown()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
