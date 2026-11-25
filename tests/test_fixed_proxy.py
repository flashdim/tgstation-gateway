import base64
from http.client import HTTPSConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
NGINX = shutil.which("nginx")
OPENSSL = shutil.which("openssl")


class Player(BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.requests.append((self.path, dict(self.headers)))
        self.send_response(101 if self.headers.get("Upgrade") else 200)
        if self.headers.get("Upgrade"):
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "upgrade")
        self.end_headers()
        if not self.headers.get("Upgrade"):
            self.wfile.write(self.server.name.encode())

    def log_message(self, *args):
        pass


@unittest.skipUnless(NGINX and OPENSSL, "nginx and openssl are required")
class FixedProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        directory.chmod(0o755)
        cls.players = []
        for name in ("first", "second"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), Player)
            server.name = name
            server.requests = []
            cls.players.append(server)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.addClassCleanup(server.server_close)
            cls.addClassCleanup(server.shutdown)

        subprocess.run(
            [
                OPENSSL,
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(directory / "key.pem"),
                "-out",
                str(directory / "cert.pem"),
                "-subj",
                "/CN=localhost",
                "-days",
                "1",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for number in (1, 2):
            password = subprocess.check_output(
                [OPENSSL, "passwd", "-apr1", f"password{number}"], text=True
            ).strip()
            (directory / f"LGplayer0{number}.htpasswd").write_text(
                f"user{number}:{password}\n"
            )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        config = (ROOT / "examples/nginx-fixed-slots.conf").read_text()
        config = config.replace("listen 443 ssl;", f"listen 127.0.0.1:{cls.port} ssl;")
        config = config.replace(
            "/etc/nginx/gateway/fullchain.pem", str(directory / "cert.pem")
        )
        config = config.replace(
            "/etc/nginx/gateway/privkey.pem", str(directory / "key.pem")
        )
        config = config.replace("/etc/nginx/gateway/", f"{directory}/")
        for number, server in enumerate(cls.players, 1):
            config = config.replace(
                f"127.0.0.1:{8079 + number}", f"127.0.0.1:{server.server_port}"
            )
        (directory / "nginx.conf").write_text(
            f"pid {directory}/nginx.pid;\nerror_log {directory}/error.log;\n"
            f"events {{}}\nhttp {{ access_log off;\n{config}\n}}\n"
        )
        cls.process = subprocess.Popen(
            [NGINX, "-c", str(directory / "nginx.conf"), "-g", "daemon off;"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        cls.addClassCleanup(cls.stop_nginx)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError(cls.process.stderr.read().decode())
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            raise RuntimeError("nginx failed to start")

    @classmethod
    def stop_nginx(cls):
        cls.process.terminate()
        cls.process.communicate(timeout=5)

    def request(self, path, user=None, websocket=False, headers=None):
        headers = dict(headers or {})
        headers.setdefault("Host", "play.example.org")
        if user:
            token = base64.b64encode(f"user{user}:password{user}".encode()).decode()
            headers["Authorization"] = f"Basic {token}"
        if websocket:
            headers.update({"Connection": "Upgrade", "Upgrade": "websocket"})
        connection = HTTPSConnection(
            "127.0.0.1", self.port, context=ssl._create_unverified_context()
        )
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_account_routing_and_authorization_before_http_and_websocket(self):
        for server in self.players:
            server.requests.clear()
        for number, server in enumerate(self.players, 1):
            root = f"/LGplayer0{number}/"
            for path in (
                root,
                root + "assets/client.js",
                root + "api/websockets",
                root + "api/websockets?view=1",
            ):
                with self.subTest(path=path):
                    before = [len(player.requests) for player in self.players]
                    for user in (None, 3 - number):
                        for websocket in (False, True):
                            status, _ = self.request(
                                path,
                                user,
                                websocket,
                                {"X-Forwarded-User": f"user{number}"},
                            )
                            self.assertEqual(status, 401)
                    self.assertEqual(
                        [len(player.requests) for player in self.players], before
                    )
                    status, body = self.request(path, number)
                    self.assertEqual((status, body), (200, server.name.encode()))
                    websocket_before = [len(player.requests) for player in self.players]
                    status, _ = self.request(path, number, websocket=True)
                    self.assertEqual(status, 101)
                    self.assertEqual(
                        [len(player.requests) for player in self.players],
                        [
                            count + int(player is server)
                            for count, player in zip(websocket_before, self.players)
                        ],
                    )
                    self.assertNotIn("Authorization", server.requests[-1][1])
                    self.assertEqual(server.requests[-1][0], path)
        before = [len(player.requests) for player in self.players]
        for path in (
            "/",
            "/LGplayer01",
            "/LGplayer03/",
            "/LGplayer01/../LGplayer02/api/websockets",
            "/LGplayer01/%2e%2e/LGplayer02/",
        ):
            status, _ = self.request(path, 1, websocket=True)
            self.assertIn(status, (401, 404))
        status, _ = self.request(
            "/LGplayer01/", 1, headers={"Host": "attacker.example"}
        )
        self.assertEqual(status, 404)
        self.assertEqual([len(player.requests) for player in self.players], before)
