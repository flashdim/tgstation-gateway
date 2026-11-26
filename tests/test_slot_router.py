import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "examples/slot-router.py"
spec = importlib.util.spec_from_file_location("slot_router", SCRIPT)
router = importlib.util.module_from_spec(spec)
spec.loader.exec_module(router)


class SlotRouterTest(unittest.TestCase):
    def setUp(self):
        self.env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ["HOME"],
            "GATEWAY_PLAY_HOST": "play.example.org",
            "GATEWAY_TRAEFIK_NETWORK": "public",
            "GATEWAY_TRAEFIK_ENTRYPOINT": "https",
            "GATEWAY_SLOT_COUNT": "2",
            "BYOND_SERVER": "game.example.org:1337",
        }

    def test_generated_router_keeps_backends_unpublished(self):
        result = router.compose_config(self.env)
        services = result["services"]
        self.assertEqual(set(services), {"landing", "player01", "player02", "router"})
        for service in services.values():
            self.assertNotIn("ports", service)
        self.assertEqual(services["player01"]["networks"], {"slot_01": None})
        self.assertEqual(services["player02"]["networks"], {"slot_02": None})
        self.assertEqual(
            result["networks"]["traefik"], {"external": True, "name": "public"}
        )
        self.assertEqual(
            services["landing"]["environment"]["GATEWAY_SLOT_PATH"], "/{account}/"
        )
        name = result["name"]
        labels = services["router"]["labels"]
        self.assertEqual(labels["traefik.docker.network"], "public")
        self.assertEqual(
            labels[f"traefik.http.routers.{name}.rule"], "Host(`play.example.org`)"
        )
        self.assertEqual(labels[f"traefik.http.routers.{name}.entrypoints"], "https")
        self.assertEqual(labels[f"traefik.http.routers.{name}.tls"], "true")
        self.assertEqual(
            labels[f"traefik.http.services.{name}.loadbalancer.server.port"], "8080"
        )
        caddy = result["configs"]["caddyfile"]["content"]
        self.assertIn("bind {$ROUTER_BIND_IP}", caddy)
        self.assertIn("handle /LGplayer01/*", caddy)
        self.assertIn("reverse_proxy player01:8080", caddy)
        self.assertIn("handle /LGplayer02/*", caddy)
        self.assertIn("reverse_proxy player02:8080", caddy)
        self.assertIn("header_up -Cookie", caddy)

    def test_custom_path_and_network(self):
        result = router.compose_config(
            {
                **self.env,
                "GATEWAY_SLOT_PATH": "/play/{number}/",
                "GATEWAY_TRAEFIK_NETWORK": "edge-network",
                "GATEWAY_TRAEFIK_ENTRYPOINT": "websecure",
                "GATEWAY_PORT": "65535",
                "GATEWAY_LANDING_PORT": "8080",
            }
        )
        self.assertEqual(result["networks"]["traefik"]["name"], "edge-network")
        self.assertIn("handle /play/01/*", result["configs"]["caddyfile"]["content"])
        self.assertEqual(
            result["services"]["router"]["labels"][
                f"traefik.http.routers.{result['name']}.entrypoints"
            ],
            "websecure",
        )

    def test_invalid_configuration_fails(self):
        for change in (
            {"GATEWAY_PLAY_HOST": ""},
            {"GATEWAY_PLAY_HOST": "example.org:443"},
            {"GATEWAY_PLAY_SCHEME": "http"},
            {"GATEWAY_TRAEFIK_NETWORK": ""},
            {"GATEWAY_TRAEFIK_NETWORK": "bad network"},
            {"GATEWAY_TRAEFIK_ENTRYPOINT": ""},
            {"GATEWAY_TRAEFIK_ENTRYPOINT": "https,other"},
            {"GATEWAY_SLOT_PATH": "/"},
            {"GATEWAY_SLOT_PATH": "/assets/{account}/"},
            {"GATEWAY_SLOT_PATH": "/Assets/{account}/"},
            {"GATEWAY_SLOT_PATH": "/{account}"},
            {"SELKIES_MODE": "webrtc"},
        ):
            with self.subTest(change=change):
                with self.assertRaises(router.ConfigError):
                    router.compose_config({**self.env, **change})

    def test_generated_compose_config_is_valid(self):
        output = subprocess.run(
            [sys.executable, str(SCRIPT)],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compose.json"
            path.write_text(output)
            resolved = subprocess.run(
                ["docker", "compose", "-f", str(path), "config", "--format", "json"],
                env=self.env,
                capture_output=True,
                text=True,
                check=True,
            )
        config = json.loads(resolved.stdout)
        self.assertEqual(
            set(config["services"]), {"landing", "player01", "player02", "router"}
        )
        self.assertIn(
            "bind {$$ROUTER_BIND_IP}", config["configs"]["caddyfile"]["content"]
        )


@unittest.skipUnless(
    os.environ.get("GATEWAY_TEST_ROUTER_IMAGE")
    and os.environ.get("GATEWAY_TEST_BACKEND_IMAGE")
    and os.environ.get("GATEWAY_TEST_TRAEFIK_IMAGE"),
    "Set fixture images to run the Docker routing test",
)
class SlotRouterDockerTest(unittest.TestCase):
    setUp = SlotRouterTest.setUp

    def test_generated_compose_routes_and_isolates_backends(self):
        network = f"gateway-router-test-{uuid.uuid4().hex}"
        created = subprocess.run(
            ["docker", "network", "create", network],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        try:
            config = router.compose_config(
                {**self.env, "GATEWAY_TRAEFIK_NETWORK": network}
            )
            config["name"] = f"gateway-router-test-{uuid.uuid4().hex}"
            config["services"]["router"]["image"] = os.environ[
                "GATEWAY_TEST_ROUTER_IMAGE"
            ]
            alias = config["services"]["router"]["environment"]["ROUTER_ALIAS"]
            config["services"]["router"]["labels"]["gateway.fixture"] = network
            config["services"]["traefik"] = {
                "image": os.environ["GATEWAY_TEST_TRAEFIK_IMAGE"],
                "networks": {"traefik": None},
                "volumes": ["/var/run/docker.sock:/var/run/docker.sock:ro"],
                "command": [
                    "--providers.docker=true",
                    "--providers.docker.exposedbydefault=false",
                    f"--providers.docker.constraints=Label(`gateway.fixture`,`{network}`)",
                    "--entrypoints.https.address=:8443",
                ],
            }
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
            self.wfile.write(json.dumps({"name": os.environ["NAME"], "path": self.path, "headers": dict(self.headers)}).encode())
    def log_message(self, *args):
        pass
ThreadingHTTPServer(("0.0.0.0", int(os.environ["PORT"])), Handler).serve_forever()
"""
            for name, backend_port in (
                ("landing", 8000),
                ("player01", 8080),
                ("player02", 8080),
            ):
                config["services"][name] = {
                    "image": os.environ["GATEWAY_TEST_BACKEND_IMAGE"],
                    "networks": config["services"][name]["networks"],
                    "environment": {"NAME": name, "PORT": str(backend_port)},
                    "command": ["python3", "-u", "-c", backend],
                }
            config["services"]["probe"] = {
                "image": os.environ["GATEWAY_TEST_BACKEND_IMAGE"],
                "networks": {"traefik": None},
                "command": ["python3", "-c", "import time; time.sleep(3600)"],
            }
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "compose.json"
                path.write_text(json.dumps(router.fixed_slots.escape_compose(config)))
                command = ["docker", "compose", "-f", str(path)]
                try:
                    up = subprocess.run(
                        [*command, "up", "-d"],
                        capture_output=True,
                        text=True,
                        env=self.env,
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    for _ in range(60):
                        response = self.request(command, alias, "/LGplayer01/")
                        if response.returncode == 0:
                            data = json.loads(response.stdout)
                            if (
                                data["status"] == 200
                                and data["body"]["name"] == "player01"
                            ):
                                break
                        time.sleep(0.2)
                    else:
                        logs = subprocess.run(
                            [*command, "logs", "--no-color", "router"],
                            capture_output=True,
                            text=True,
                            env=self.env,
                        )
                        self.fail(
                            f"Router did not start: {response.stderr}\n{logs.stdout}"
                        )
                    for _ in range(60):
                        response = self.request(command, alias, "/", traefik=True)
                        if response.returncode == 0:
                            data = json.loads(response.stdout)
                            if (
                                data["status"] == 200
                                and data["body"]["name"] == "landing"
                            ):
                                break
                        time.sleep(0.2)
                    else:
                        logs = subprocess.run(
                            [*command, "logs", "--no-color", "traefik"],
                            capture_output=True,
                            text=True,
                            env=self.env,
                        )
                        self.fail(
                            f"Traefik did not route: {response.stderr}\n{logs.stdout}"
                        )
                    for path, target in (
                        ("/", "landing"),
                        ("/LGplayer01/assets/client.js", "player01"),
                        ("/LGplayer02/api/websockets?view=1", "player02"),
                    ):
                        response = self.request(
                            command, alias, path, sensitive=True, traefik=True
                        )
                        self.assertEqual(response.returncode, 0, response.stderr)
                        data = json.loads(response.stdout)
                        self.assertEqual(data["status"], 200)
                        self.assertEqual(
                            (data["body"]["name"], data["body"]["path"]), (target, path)
                        )
                        for header in (
                            "Cookie",
                            "Authorization",
                            "Cf-Access-Jwt-Assertion",
                        ):
                            self.assertNotIn(header, data["body"]["headers"])
                    response = self.request(
                        command,
                        alias,
                        "/LGplayer02/api/websockets",
                        websocket=True,
                        traefik=True,
                    )
                    self.assertEqual(response.returncode, 0, response.stderr)
                    self.assertEqual(json.loads(response.stdout)["status"], 101)
                    isolation = subprocess.run(
                        [
                            *command,
                            "exec",
                            "-T",
                            "player01",
                            "python3",
                            "-c",
                            "import socket; socket.create_connection(('router', 8080), timeout=2)",
                        ],
                        capture_output=True,
                        text=True,
                        env=self.env,
                    )
                    self.assertNotEqual(
                        isolation.returncode, 0, "A player can reach the router"
                    )
                finally:
                    subprocess.run(
                        [*command, "down", "--volumes", "--remove-orphans"],
                        capture_output=True,
                        check=False,
                        env=self.env,
                    )
        finally:
            subprocess.run(
                ["docker", "network", "rm", network],
                capture_output=True,
                check=False,
                env=self.env,
            )

    def request(
        self, command, alias, path, sensitive=False, websocket=False, traefik=False
    ):
        code = """
import http.client, json, os, ssl
if os.environ["TRAEFIK"] == "1":
    conn = http.client.HTTPSConnection("traefik", 8443, context=ssl._create_unverified_context(), timeout=2)
else:
    conn = http.client.HTTPConnection(os.environ["ALIAS"], 8080, timeout=2)
headers = {"Host": "play.example.org"}
if os.environ["SENSITIVE"] == "1":
    headers.update({"Cookie": "secret=1", "Authorization": "Bearer secret", "Cf-Access-Jwt-Assertion": "secret"})
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
                f"ALIAS={alias}",
                "-e",
                f"PATH_TO_CHECK={path}",
                "-e",
                f"SENSITIVE={int(sensitive)}",
                "-e",
                f"WEBSOCKET={int(websocket)}",
                "-e",
                f"TRAEFIK={int(traefik)}",
                "probe",
                "python3",
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            env=self.env,
        )


if __name__ == "__main__":
    unittest.main()
