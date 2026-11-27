import contextlib
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
from unittest import TestCase
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "connect_on_selkies", ROOT / "container/connect-on-selkies.py"
)
connector_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connector_module)


class GameConnectorTest(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runtime = self.root / "runtime"
        self.runtime.mkdir()
        self.env = {
            "BYOND_SERVER": "example.org:1337",
            "BYOND_ACCOUNT": "LGplayer01",
            "SELKIES_SUBFOLDER": "/LGplayer01/",
            "SELKIES_WAYLAND": "false",
            "WINEPREFIX": str(self.root / "wine"),
            "XDG_RUNTIME_DIR": str(self.runtime),
            "DISPLAY": ":42",
            "LD_PRELOAD": "do-not-inherit",
        }
        self.connector = connector_module.GameConnector(self.env)
        self.connector.key.parent.mkdir(parents=True)
        self.present = False
        self.pager = frozenset({101})
        self.game = frozenset()
        self.log = io.StringIO()
        self.enterContext(contextlib.redirect_stderr(self.log))

        def sessions(port, path):
            self.assertEqual((port, path), (8080, "/LGplayer01/api/sessions"))
            return self.present

        def processes(pattern):
            return (
                self.pager if pattern == connector_module.PAGER_PATTERN else self.game
            )

        self.sessions_mock = self.enterContext(
            patch.object(connector_module, "sessions_present", side_effect=sessions)
        )
        self.enterContext(
            patch.object(connector_module, "process_ids", side_effect=processes)
        )
        child = Mock()
        child.poll.return_value = None
        self.launch = self.enterContext(
            patch.object(connector_module.subprocess, "Popen", return_value=child)
        )

    def save_key(self, account="LGplayer01"):
        self.connector.key.write_bytes(
            f"BEGIN KEY {account}\r\nsynthetic-secret\r\n`\r\nEND KEY\r\n".encode()
        )

    def test_waits_for_a_viewer_and_matching_key_then_starts_once(self):
        self.save_key()
        self.connector.step()
        self.launch.assert_not_called()

        self.present = True
        self.save_key("LGplayer02")
        self.connector.step()
        self.launch.assert_not_called()
        self.assertIn("no complete key for LGplayer01", self.log.getvalue())

        self.save_key("lgPLAYER01")
        self.connector.step()
        self.connector.step()
        self.launch.assert_called_once()
        args, kwargs = self.launch.call_args
        self.assertEqual(
            args[0], ["wine", str(self.connector.game), "byond://example.org:1337"]
        )
        self.assertEqual(kwargs["env"]["DISPLAY"], ":42")
        self.assertNotIn("LD_PRELOAD", kwargs["env"])
        self.assertNotIn("synthetic-secret", self.log.getvalue())

    def test_missing_key_can_be_saved_without_reconnecting(self):
        self.present = True
        self.connector.step()
        self.assertIn("BYOND key.txt is missing", self.log.getvalue())
        self.launch.assert_not_called()
        self.save_key()
        self.connector.step()
        self.launch.assert_called_once()

    def test_disconnect_and_reconnect_never_duplicate_running_game(self):
        self.save_key()
        self.present = True
        self.connector.step()
        self.assertEqual(self.launch.call_count, 1)

        self.present = False
        self.connector.step()
        self.game = frozenset({202})
        self.present = True
        self.connector.step()
        self.assertEqual(self.launch.call_count, 1)
        self.assertIn("already running", self.log.getvalue())

        self.present = False
        self.connector.step()
        self.game = frozenset()
        self.present = True
        self.connector.step()
        self.assertEqual(self.launch.call_count, 2)

    def test_new_pager_after_reset_retries_while_viewer_stays_connected(self):
        self.save_key()
        self.present = True
        self.connector.step()
        self.pager = frozenset()
        self.connector.step()
        self.pager = frozenset({102})
        self.connector.step()
        self.assertEqual(self.launch.call_count, 2)

    def test_requires_live_presence_again_immediately_before_launch(self):
        self.save_key()
        self.sessions_mock.side_effect = [True, False]
        self.connector.step()
        self.launch.assert_not_called()
        self.assertFalse(self.connector.connected)

    def test_session_errors_do_not_start_or_reset_an_active_session(self):
        self.save_key()
        self.present = True
        self.connector.step()
        self.sessions_mock.side_effect = connector_module.ObservationError(
            "unavailable"
        )
        self.connector.step()
        self.assertIn("unavailable", self.log.getvalue())
        self.sessions_mock.side_effect = lambda port, path: True
        self.connector.step()
        self.assertEqual(self.launch.call_count, 1)

    def test_waits_for_cleanup_lock_and_authenticated_xwayland(self):
        self.save_key()
        self.present = True
        self.connector.env["SELKIES_WAYLAND"] = "true"
        with (self.runtime / "byond-cleanup.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.connector.step()
            self.assertIn("Waiting for BYOND startup or reset", self.log.getvalue())
            self.launch.assert_not_called()
        self.connector.step()
        self.assertIn("authenticated XWayland", self.log.getvalue())
        self.launch.assert_not_called()
        authority = self.runtime / "authority"
        authority.write_text("test cookie")
        (self.runtime / "byond-xwayland").write_text(f":7\n{authority}\n")
        self.connector.step()
        self.assertEqual(self.launch.call_args.kwargs["env"]["DISPLAY"], ":7")
        self.assertEqual(
            self.launch.call_args.kwargs["env"]["XAUTHORITY"], str(authority)
        )

    def test_rejects_mismatched_truncated_and_misleading_keys(self):
        cases = (
            b"BEGIN KEY LGplayer010\nsecret\nEND KEY\n",
            b"BEGIN KEY Other\nLGplayer01\nEND KEY\n",
            b"BEGIN KEY LGplayer01\nsecret\n",
            b"BEGIN KEY LGplayer01\nEND KEY\n",
        )
        for data in cases:
            with self.subTest(data=data):
                self.connector.key.write_bytes(data)
                self.assertFalse(
                    connector_module.key_matches(self.connector.key, "LGplayer01")[0]
                )
        self.connector.key.write_bytes(
            b"BEGIN KEY Guest\nx\nEND KEY\n[BEGIN KEY lgplayer01]\ny\n[END KEY]\n"
        )
        self.assertTrue(
            connector_module.key_matches(self.connector.key, "LGplayer01")[0]
        )
        with patch.object(connector_module, "MAX_KEY_BYTES", 10):
            self.assertFalse(
                connector_module.key_matches(self.connector.key, "LGplayer01")[0]
            )

    def test_invalid_configuration_fails_closed(self):
        for server in (
            "",
            "example.org",
            "https://example.org:1337",
            "example.org:0",
            "example.org:65536",
            "example.org:1337 extra",
            ":1337",
        ):
            with self.subTest(server=server):
                with self.assertRaises(ValueError):
                    connector_module.GameConnector({**self.env, "BYOND_SERVER": server})
        for account in ("", "player name", "../LGplayer01"):
            with self.subTest(account=account):
                with self.assertRaises(ValueError):
                    connector_module.GameConnector(
                        {**self.env, "BYOND_ACCOUNT": account}
                    )
        self.assertEqual(
            connector_module.server_url("byond://[::1]:1337"), "byond://[::1]:1337"
        )


class SessionsApiTest(TestCase):
    def test_queries_local_prefixed_api_and_rejects_invalid_responses(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.server.paths.append(self.path)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(self.server.body)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.paths = []
        server.body = json.dumps({"sessions": []}).encode()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]
        self.assertFalse(
            connector_module.sessions_present(port, "/LGplayer01/api/sessions")
        )
        server.body = json.dumps({"sessions": [{"role": None}]}).encode()
        self.assertTrue(
            connector_module.sessions_present(port, "/LGplayer01/api/sessions")
        )
        self.assertEqual(server.paths, ["/LGplayer01/api/sessions"] * 2)
        server.body = b'{"sessions": "not a list"}'
        with self.assertRaises(connector_module.ObservationError):
            connector_module.sessions_present(port, "/LGplayer01/api/sessions")
