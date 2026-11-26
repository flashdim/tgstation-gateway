import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "examples/compose.traefik.yaml"


class ComposeTest(unittest.TestCase):
    def setUp(self):
        self.env = {
            **os.environ,
            "GATEWAY_DEPLOYMENT_ID": "gatewaytest",
            "GATEWAY_PLAY_HOST": "play.example.org",
            "GATEWAY_TRAEFIK_NETWORK": "public",
            "GATEWAY_TRAEFIK_ENTRYPOINT": "https",
            "GATEWAY_SLOT_COUNT": "4",
            "BYOND_SERVER": "tgstation:1337",
        }

    def test_compose_uses_one_manager_and_no_static_players(self):
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config", "--format", "json"],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        config = json.loads(result.stdout)
        services = config["services"]
        self.assertEqual(set(services), {"landing", "router", "manager"})
        self.assertEqual(services["landing"]["environment"]["GATEWAY_SLOT_COUNT"], "4")
        self.assertEqual(services["manager"]["environment"]["GATEWAY_SLOT_COUNT"], "4")
        self.assertEqual(config["networks"]["edge"]["name"], "public")
        self.assertEqual(
            services["router"]["labels"]["traefik.http.routers.gatewaytest.rule"],
            "Host(`play.example.org`)",
        )
        self.assertEqual(
            services["router"]["labels"][
                "traefik.http.services.gatewaytest.loadbalancer.server.port"
            ],
            "8080",
        )
        self.assertNotIn("ports", services["landing"])
        self.assertNotIn("ports", services["router"])
        self.assertNotIn("/var/run/docker.sock", json.dumps(services["router"]))
        self.assertNotIn("/var/run/docker.sock", json.dumps(services["landing"]))
        self.assertIn("/var/run/docker.sock", json.dumps(services["manager"]))
        self.assertIn("path_regexp slot", config["configs"]["router_config"]["content"])

    def test_required_configuration(self):
        for key in ("GATEWAY_PLAY_HOST", "BYOND_SERVER"):
            env = dict(self.env)
            env.pop(key)
            result = subprocess.run(
                ["docker", "compose", "-f", str(COMPOSE), "config"],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(key, result.stderr)

    def test_manager_rejects_invalid_values_before_using_docker(self):
        for key, value in (
            ("GATEWAY_SLOT_COUNT", "0"),
            ("GATEWAY_SLOT_COUNT", "100"),
            ("GATEWAY_DEPLOYMENT_ID", "bad/name"),
            ("BYOND_SERVER", "tgstation:0"),
            ("SELKIES_WAYLAND", "invalid"),
        ):
            result = subprocess.run(
                ["sh", str(ROOT / "examples/slot-manager.sh")],
                env={**self.env, key: value},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(key, result.stderr)


@unittest.skipUnless(
    all(
        os.environ.get(key)
        for key in ("GATEWAY_TEST_BACKEND_IMAGE", "GATEWAY_TEST_TRAEFIK_IMAGE")
    ),
    "Set fixture images to run the Docker manager and routing test",
)
class ManagerDockerTest(unittest.TestCase):
    def test_manager_creates_routes_reconciles_and_retains_volumes(self):
        project = f"gatewaytest{uuid.uuid4().hex[:12]}"
        network = f"{project}-edge"
        fixture_image = f"{project}-fixture"
        env = {
            **os.environ,
            "GATEWAY_DEPLOYMENT_ID": project,
            "GATEWAY_PLAY_HOST": "play.example.org",
            "GATEWAY_TRAEFIK_NETWORK": network,
            "GATEWAY_TRAEFIK_ENTRYPOINT": "https",
            "GATEWAY_SLOT_COUNT": "2",
            "BYOND_SERVER": "tgstation:1337",
            "GATEWAY_IMAGE": fixture_image,
            "GATEWAY_LANDING_IMAGE": os.environ["GATEWAY_TEST_BACKEND_IMAGE"],
        }
        created = subprocess.run(
            ["docker", "network", "create", network],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        backend = """
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        upgrade = self.headers.get("Upgrade")
        self.send_response(101 if upgrade else 200)
        if upgrade:
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
        self.end_headers()
        if not upgrade:
            self.wfile.write(json.dumps({"name": os.environ.get("SELKIES_SUBFOLDER", "landing"), "path": self.path, "headers": dict(self.headers)}).encode())
    def log_message(self, *args):
        pass
ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("FIXTURE_PORT", "8080"))), Handler).serve_forever()
"""
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "app.py").write_text(backend)
                (root / "Dockerfile").write_text(
                    f'FROM {os.environ["GATEWAY_TEST_BACKEND_IMAGE"]}\nCOPY app.py /app.py\nCMD ["python3", "-u", "/app.py"]\n'
                )
                build = subprocess.run(
                    ["docker", "build", "-t", fixture_image, str(root)],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(build.returncode, 0, build.stderr)
                overrides = {
                    "services": {
                        "landing": {
                            "entrypoint": ["python3", "-u", "-c", backend],
                            "environment": {"FIXTURE_PORT": "8000"},
                            "healthcheck": {"disable": True},
                        },
                        "traefik": {
                            "image": os.environ["GATEWAY_TEST_TRAEFIK_IMAGE"],
                            "networks": ["edge"],
                            "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                            "command": [
                                "--providers.docker=true",
                                "--providers.docker.exposedbydefault=false",
                                f"--providers.docker.constraints=Label(`com.docker.compose.project`,`{project}`)",
                                "--entrypoints.https.address=:8443",
                            ],
                        },
                        "probe": {
                            "image": os.environ["GATEWAY_TEST_BACKEND_IMAGE"],
                            "networks": ["edge"],
                            "command": [
                                "python3",
                                "-c",
                                "import time; time.sleep(3600)",
                            ],
                        },
                    }
                }
                override = root / "override.json"
                override.write_text(json.dumps(overrides))
                command = ["docker", "compose", "-f", str(COMPOSE), "-f", str(override)]
                try:
                    up = subprocess.run(
                        [*command, "up", "-d", "--build"],
                        env=env,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
                    self.wait_for_route(command, env, "/LGplayer02/", "/LGplayer02/")
                    for number in (1, 2):
                        path = f"/LGplayer{number:02}/api/websockets"
                        result = self.request(command, env, path, True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(json.loads(result.stdout)["status"], 101)
                    player = f"{project}-player02"
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            player,
                            "sh",
                            "-c",
                            "echo retained > /home/ubuntu/.wine/marker",
                        ],
                        env=env,
                        check=True,
                    )
                    first = f"{project}-player01"
                    original_id = subprocess.check_output(
                        ["docker", "inspect", "-f", "{{.Id}}", first],
                        env=env,
                        text=True,
                    ).strip()
                    env["GATEWAY_SLOT_COUNT"] = "1"
                    up = subprocess.run(
                        [*command, "up", "-d"], env=env, capture_output=True, text=True
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    for _ in range(100):
                        check = subprocess.run(
                            ["docker", "inspect", player], env=env, capture_output=True
                        )
                        if check.returncode != 0:
                            break
                        time.sleep(0.2)
                    else:
                        self.fail("Manager did not remove the extra player")
                    self.assertEqual(
                        subprocess.check_output(
                            ["docker", "inspect", "-f", "{{.Id}}", first],
                            env=env,
                            text=True,
                        ).strip(),
                        original_id,
                    )
                    volume = subprocess.run(
                        ["docker", "volume", "inspect", f"{player}-wine"],
                        env=env,
                        capture_output=True,
                    )
                    self.assertEqual(volume.returncode, 0)
                    env["GATEWAY_SLOT_COUNT"] = "2"
                    up = subprocess.run(
                        [*command, "up", "-d"], env=env, capture_output=True, text=True
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    self.wait_for_route(command, env, "/LGplayer02/", "/LGplayer02/")
                    marker = subprocess.check_output(
                        ["docker", "exec", player, "cat", "/home/ubuntu/.wine/marker"],
                        env=env,
                        text=True,
                    )
                    self.assertEqual(marker.strip(), "retained")
                    subprocess.run(
                        ["docker", "stop", first],
                        env=env,
                        check=True,
                        capture_output=True,
                    )
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
                    unrelated = f"{project}-player03"
                    subprocess.run(
                        ["docker", "run", "-d", "--name", unrelated, fixture_image],
                        env=env,
                        check=True,
                        capture_output=True,
                    )
                    env["GATEWAY_SLOT_COUNT"] = "3"
                    up = subprocess.run(
                        [*command, "up", "-d"], env=env, capture_output=True, text=True
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    for _ in range(100):
                        logs = subprocess.run(
                            [*command, "logs", "--no-color", "manager"],
                            env=env,
                            capture_output=True,
                            text=True,
                        )
                        if (
                            f"Refusing to modify unowned container {unrelated}"
                            in logs.stdout
                        ):
                            break
                        time.sleep(0.2)
                    else:
                        self.fail(
                            f"Manager did not reject name collision: {logs.stdout}"
                        )
                    state = subprocess.check_output(
                        ["docker", "inspect", "-f", "{{.State.Running}}", unrelated],
                        env=env,
                        text=True,
                    )
                    self.assertEqual(state.strip(), "true")
                finally:
                    subprocess.run(
                        [*command, "down", "--volumes", "--remove-orphans"],
                        env=env,
                        capture_output=True,
                    )
                    for number in (1, 2, 3):
                        player = f"{project}-player{number:02}"
                        subprocess.run(
                            ["docker", "rm", "-f", player], env=env, capture_output=True
                        )
                        subprocess.run(
                            [
                                "docker",
                                "volume",
                                "rm",
                                f"{player}-wine",
                                f"{player}-data",
                            ],
                            env=env,
                            capture_output=True,
                        )
        finally:
            subprocess.run(
                ["docker", "network", "rm", network], env=env, capture_output=True
            )
            subprocess.run(
                ["docker", "image", "rm", fixture_image, f"{project}-manager"],
                env=env,
                capture_output=True,
            )

    def wait_for_route(self, command, env, path, expected):
        for _ in range(100):
            result = self.request(command, env, path)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data["status"] == 200 and data["body"]["name"] == expected:
                    for header in (
                        "Cookie",
                        "Authorization",
                        "Cf-Access-Jwt-Assertion",
                    ):
                        self.assertNotIn(header, data["body"]["headers"])
                    return
            time.sleep(0.2)
        logs = subprocess.run(
            [*command, "logs", "--no-color", "manager", "router", "traefik"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.fail(f"Route {path} unavailable: {result.stderr}\n{logs.stdout}")

    @staticmethod
    def request(command, env, path, websocket=False):
        code = """
import http.client, json, os, ssl
conn = http.client.HTTPSConnection("traefik", 8443, context=ssl._create_unverified_context(), timeout=2)
headers = {"Host": "play.example.org", "Cookie": "secret=1", "Authorization": "Bearer secret", "Cf-Access-Jwt-Assertion": "secret"}
if os.environ["WEBSOCKET"] == "1":
    headers.update({"Connection": "Upgrade", "Upgrade": "websocket"})
conn.request("GET", os.environ["PATH_TO_CHECK"], headers=headers)
response = conn.getresponse()
body = response.read()
print(json.dumps({"status": response.status, "body": json.loads(body) if body else {}}))
conn.close()
"""
        return subprocess.run(
            [
                *command,
                "exec",
                "-T",
                "-e",
                f"PATH_TO_CHECK={path}",
                "-e",
                f"WEBSOCKET={int(websocket)}",
                "probe",
                "python3",
                "-c",
                code,
            ],
            env=env,
            capture_output=True,
            text=True,
        )
