import contextlib
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


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "container" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


connector_module = load("connect_on_selkies", "connect-on-selkies.py")
key_module = load("byond_key_check", "byond-key-check.py")


class SessionWatcherTest(TestCase):
    def setUp(self):
        self.restart = Mock()
        self.watcher = connector_module.SessionWatcher(
            {"SELKIES_SUBFOLDER": "/LGplayer01/"}, restart=self.restart
        )
        self.present = False
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))

        def sessions(port, path):
            self.assertEqual((port, path), (8080, "/LGplayer01/api/sessions"))
            return self.present

        self.enterContext(
            patch.object(connector_module, "sessions_present", side_effect=sessions)
        )

    def test_restarts_once_per_session_start(self):
        self.watcher.step()
        self.restart.assert_not_called()
        self.present = True
        self.watcher.step()
        self.watcher.step()
        self.assertEqual(self.restart.call_count, 1)
        self.present = False
        self.watcher.step()
        self.present = True
        self.watcher.step()
        self.assertEqual(self.restart.call_count, 2)

    def test_failed_restart_is_retried(self):
        self.present = True
        self.restart.side_effect = [OSError("busy"), None]
        self.watcher.step()
        self.watcher.step()
        self.assertEqual(self.restart.call_count, 2)
        self.watcher.step()
        self.assertEqual(self.restart.call_count, 2)

    def test_session_errors_do_not_restart_or_end_a_session(self):
        self.present = True
        self.watcher.step()
        with patch.object(
            connector_module,
            "sessions_present",
            side_effect=connector_module.ObservationError("down"),
        ):
            self.watcher.step()
        self.watcher.step()
        self.assertEqual(self.restart.call_count, 1)

    def test_invalid_port_fails_closed(self):
        for port in ("0", "65536", "http"):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    connector_module.SessionWatcher({"SELKIES_PORT": port})


class KeyCheckTest(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.key = Path(temporary.name) / "key.txt"

    def matches(self):
        return key_module.key_matches(self.key, "LGplayer01")[0]

    def test_missing_key_does_not_match(self):
        self.assertFalse(self.matches())

    def test_rejects_mismatched_truncated_and_misleading_keys(self):
        cases = (
            b"BEGIN KEY LGplayer010\nsecret\nEND KEY\n",
            b"BEGIN KEY Other\nLGplayer01\nEND KEY\n",
            b"BEGIN KEY LGplayer01\nsecret\n",
            b"BEGIN KEY LGplayer01\nEND KEY\n",
        )
        for data in cases:
            with self.subTest(data=data):
                self.key.write_bytes(data)
                self.assertFalse(self.matches())
        self.key.write_bytes(
            b"BEGIN KEY Guest\nx\nEND KEY\n[BEGIN KEY lgplayer01]\ny\n[END KEY]\n"
        )
        self.assertTrue(self.matches())
        with patch.object(key_module, "MAX_KEY_BYTES", 10):
            self.assertFalse(self.matches())


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
