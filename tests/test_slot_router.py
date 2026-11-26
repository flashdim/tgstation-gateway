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
            "GATEWAY_MANAGER_IMAGE": "ghcr.io/flashdim/tgstation-gateway-manager:latest",
            "GATEWAY_MANAGER_GPU": "false",
            "DRI_RENDER_GID": "",
            "GATEWAY_SECRET_DIRECTORY": "",
        }

    def test_compose_uses_one_manager_and_no_static_players(self):
        self.env.update(GATEWAY_MANAGER_GPU="true", DRI_RENDER_GID="123")
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE), "config", "--format", "json"],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        config = json.loads(result.stdout)
        services = config["services"]
        self.assertEqual(set(services), {"landing", "manager"})
        self.assertEqual(services["landing"]["environment"]["GATEWAY_SLOT_COUNT"], "4")
        self.assertEqual(services["manager"]["environment"]["GATEWAY_SLOT_COUNT"], "4")
        self.assertEqual(
            services["manager"]["image"],
            "ghcr.io/flashdim/tgstation-gateway-manager:latest",
        )
        self.assertNotIn("build", services["manager"])
        self.assertEqual(config["networks"]["edge"]["name"], "public")
        self.assertEqual(
            services["landing"]["labels"][
                "traefik.http.routers.gatewaytest-landing.rule"
            ],
            "Host(`play.example.org`)",
        )
        self.assertEqual(
            services["landing"]["labels"][
                "traefik.http.services.gatewaytest-landing.loadbalancer.server.port"
            ],
            "8000",
        )
        self.assertNotIn("ports", services["landing"])
        self.assertNotIn("/var/run/docker.sock", json.dumps(services["landing"]))
        self.assertIn("/var/run/docker.sock", json.dumps(services["manager"]))
        self.assertEqual(
            services["manager"]["environment"]["GATEWAY_PLAY_HOST"], "play.example.org"
        )
        self.assertEqual(
            services["manager"]["environment"]["GATEWAY_TRAEFIK_ENTRYPOINT"], "https"
        )
        self.assertEqual(
            services["manager"]["environment"]["GATEWAY_MANAGER_GPU"], "true"
        )
        self.assertEqual(services["manager"]["environment"]["DRI_RENDER_GID"], "123")
        self.assertNotIn("devices", services["manager"])
        self.assertNotIn("devices", services["landing"])

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

    def test_gpu_override_mounts_metadata_only_in_manager(self):
        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                str(COMPOSE),
                "-f",
                str(ROOT / "examples/compose.traefik.gpu.yaml"),
                "config",
                "--format",
                "json",
            ],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        services = json.loads(result.stdout)["services"]
        manager = services["manager"]
        self.assertEqual(manager["environment"]["GATEWAY_MANAGER_GPU"], "true")
        mount = next(v for v in manager["volumes"] if v["target"] == "/dev/dri")
        self.assertEqual(mount["source"], "/dev/dri")
        self.assertTrue(mount["read_only"])
        self.assertFalse(mount["bind"].get("create_host_path", False))
        self.assertNotIn("devices", manager)
        self.assertNotIn("/dev/dri", json.dumps(services["landing"]))

    def test_key_override_mounts_directory_only_in_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "-f",
                    str(COMPOSE),
                    "-f",
                    str(ROOT / "examples/compose.traefik.keys.yaml"),
                    "config",
                    "--format",
                    "json",
                ],
                env={**self.env, "GATEWAY_SECRET_DIRECTORY": directory},
                capture_output=True,
                text=True,
                check=True,
            )
            services = json.loads(result.stdout)["services"]
            manager = services["manager"]
            self.assertEqual(
                manager["environment"]["GATEWAY_SECRET_DIRECTORY"], directory
            )
            mount = next(v for v in manager["volumes"] if v["target"] == directory)
            self.assertEqual(mount["source"], directory)
            self.assertTrue(mount["read_only"])
            self.assertFalse(mount["bind"].get("create_host_path", False))
            self.assertNotIn(directory, json.dumps(services["landing"]))

    def test_manager_rejects_invalid_values_before_using_docker(self):
        for key, value in (
            ("GATEWAY_SLOT_COUNT", "0"),
            ("GATEWAY_SLOT_COUNT", "100"),
            ("GATEWAY_DEPLOYMENT_ID", "bad/name"),
            ("BYOND_SERVER", "tgstation:0"),
            ("SELKIES_WAYLAND", "invalid"),
            ("GATEWAY_PLAY_HOST", "example.org`) || PathPrefix(`/"),
            ("GATEWAY_TRAEFIK_ENTRYPOINT", "https,other"),
            ("GATEWAY_TRAEFIK_NETWORK", "bad network"),
            ("GATEWAY_MANAGER_GPU", "invalid"),
            ("GATEWAY_SECRET_DIRECTORY", "relative"),
            ("GATEWAY_SECRET_DIRECTORY", "/path,other"),
            ("GATEWAY_SECRET_DIRECTORY", '/path"other'),
        ):
            result = subprocess.run(
                ["sh", str(ROOT / "examples/slot-manager.sh")],
                env={**self.env, key: value},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(key, result.stderr)

    def test_manager_key_mount_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keys = root / "keys with spaces"
            keys.mkdir()
            first = keys / "LGplayer01_key.txt"
            second = keys / "LGplayer02_key.txt"
            first.write_bytes(b"synthetic $`\\'\r\n")
            second.write_bytes(b"other key")
            script = (ROOT / "examples/slot-manager.sh").read_text()
            script = script.replace(
                "/run/gateway-lock/manager.lock", str(root / "lock")
            )
            script = script.replace("/opt/gateway/seccomp.json", str(root / "seccomp"))
            (root / "manager.sh").write_text(script)
            (root / "seccomp").write_text("{}")
            docker = root / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                'case "$1 $2" in\n'
                '  "image inspect") echo fixture-image ;;\n'
                '  "volume inspect") exit 1 ;;\n'
                '  "run -d") printf "%s\\n" "$@" > "$ARGUMENTS"; exit 23 ;;\n'
                "esac\n"
            )
            docker.chmod(0o755)
            env = {
                **self.env,
                "GATEWAY_SLOT_COUNT": "2",
                "GATEWAY_SECRET_DIRECTORY": str(keys),
                "PATH": f"{root}:{os.environ['PATH']}",
                "ARGUMENTS": str(root / "arguments"),
            }

            def run():
                return subprocess.run(
                    ["sh", str(root / "manager.sh")],
                    env=env,
                    capture_output=True,
                    text=True,
                )

            result = run()
            self.assertEqual(result.returncode, 23, result.stderr)
            arguments = (root / "arguments").read_text().splitlines()
            self.assertIn(
                f"type=bind,src={first},dst=/run/secrets/byond_key.txt,readonly",
                arguments,
            )
            self.assertIn("BYOND_KEY_FILE=/run/secrets/byond_key.txt", arguments)
            self.assertNotIn(str(second), "\n".join(arguments))
            self.assertNotIn("synthetic", result.stdout + result.stderr)

            for kind in ("missing", "empty", "symlink", "hardlink"):
                with self.subTest(kind=kind):
                    second.unlink()
                    if kind == "empty":
                        second.touch()
                    elif kind == "symlink":
                        second.symlink_to(first)
                    elif kind == "hardlink":
                        os.link(first, second)
                    result = run()
                    self.assertNotEqual(result.returncode, 23)
                    invalid_slot = "01" if kind == "hardlink" else "02"
                    self.assertIn(
                        f"Missing or invalid key file for LGplayer{invalid_slot}",
                        result.stderr,
                    )
                    if kind == "missing":
                        second.write_bytes(b"other key")
            second.unlink(missing_ok=True)
            second.write_bytes(b"other key")
            second.chmod(0)
            result = run()
            self.assertNotEqual(result.returncode, 23)
            self.assertIn("readable by container UID 1000", result.stderr)

    def test_manager_gpu_arguments_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (ROOT / "examples/slot-manager.sh").read_text()
            script = script.replace(
                "/run/gateway-lock/manager.lock", str(root / "lock")
            )
            script = script.replace("/opt/gateway/seccomp.json", str(root / "seccomp"))
            script = script.replace("/dev/dri/renderD", str(root / "renderD"))
            (root / "manager.sh").write_text(script)
            (root / "seccomp").write_text("{}")
            docker = root / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                'case "$1 $2" in\n'
                '  "image inspect") echo fixture-image ;;\n'
                '  "volume inspect") exit 1 ;;\n'
                '  "run -d") printf "%s\\n" "$@" > "$ARGUMENTS"; exit 23 ;;\n'
                "esac\n"
            )
            docker.chmod(0o755)
            settings = []
            for gpu, gid in (("false", ""), ("true", "123"), ("true", "456")):
                result = subprocess.run(
                    ["sh", str(root / "manager.sh")],
                    env={
                        **self.env,
                        "PATH": f"{root}:{os.environ['PATH']}",
                        "ARGUMENTS": str(root / "arguments"),
                        "GATEWAY_MANAGER_GPU": gpu,
                        "DRI_RENDER_GID": gid,
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 23, result.stderr)
                arguments = (root / "arguments").read_text().splitlines()
                if gpu == "true":
                    self.assertEqual(
                        arguments[arguments.index("--device") + 1], "/dev/dri:/dev/dri"
                    )
                    self.assertEqual(arguments[arguments.index("--group-add") + 1], gid)
                else:
                    self.assertNotIn("--device", arguments)
                    self.assertNotIn("--group-add", arguments)
                settings.append(
                    next(
                        arg
                        for arg in arguments
                        if arg.startswith("io.tgstation-gateway.settings=")
                    )
                )
            self.assertEqual(len(set(settings)), 3)
            for gid in ("", "-1", "render", "4294967295"):
                result = subprocess.run(
                    ["sh", str(root / "manager.sh")],
                    env={
                        **self.env,
                        "GATEWAY_MANAGER_GPU": "true",
                        "DRI_RENDER_GID": gid,
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("DRI_RENDER_GID", result.stderr)
            node = root / "renderD128"
            node.symlink_to("/dev/null")
            env = {
                **self.env,
                "PATH": f"{root}:{os.environ['PATH']}",
                "ARGUMENTS": str(root / "arguments"),
                "GATEWAY_MANAGER_GPU": "true",
            }
            result = subprocess.run(
                ["sh", str(root / "manager.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 23, result.stderr)
            arguments = (root / "arguments").read_text().splitlines()
            self.assertEqual(
                arguments[arguments.index("--group-add") + 1],
                str(os.stat("/dev/null").st_gid),
            )
            (root / "renderD129").symlink_to("/dev/null")
            result = subprocess.run(
                ["sh", str(root / "manager.sh")],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Cannot auto-detect DRI_RENDER_GID", result.stderr)
            result = subprocess.run(
                ["sh", str(root / "manager.sh")],
                env={**env, "DRI_RENDER_GID": "123"},
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 23, result.stderr)


@unittest.skipUnless(
    all(
        os.environ.get(key)
        for key in (
            "GATEWAY_TEST_MANAGER_IMAGE",
            "GATEWAY_TEST_BACKEND_IMAGE",
            "GATEWAY_TEST_TRAEFIK_IMAGE",
        )
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
            "GATEWAY_MANAGER_IMAGE": os.environ["GATEWAY_TEST_MANAGER_IMAGE"],
            "GATEWAY_MANAGER_GPU": "false",
            "DRI_RENDER_GID": "",
            "GATEWAY_SECRET_DIRECTORY": "",
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
        if self.path.endswith("/api/health"):
            if self.path != os.environ.get("SELKIES_SUBFOLDER", "/") + "api/health":
                self.send_response(404)
            else:
                self.send_response(503 if os.path.exists("/tmp/health-down") else 200)
            self.end_headers()
            return
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
                root.chmod(0o755)
                keys = root / "keys"
                keys.mkdir(mode=0o755)
                for number in (1, 2):
                    key = keys / f"LGplayer{number:02}_key.txt"
                    key.write_bytes(f"fixture {number} $`\\'\r\n".encode())
                    key.chmod(0o444)
                env["GATEWAY_SECRET_DIRECTORY"] = str(keys)
                (root / "app.py").write_text(backend)
                (root / "curl").write_text(
                    "#!/usr/bin/env python3\n"
                    "import sys, urllib.request\n"
                    "urllib.request.urlopen(sys.argv[-1], timeout=2).close()\n"
                )
                (root / "Dockerfile").write_text(
                    f"FROM {os.environ['GATEWAY_TEST_BACKEND_IMAGE']}\n"
                    "COPY app.py /app.py\nCOPY --chmod=755 curl /usr/local/bin/curl\n"
                    'HEALTHCHECK CMD exit 1\nCMD ["python3", "-u", "/app.py"]\n'
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
                                f"--providers.docker.constraints=Label(`io.tgstation-gateway.deployment`,`{project}`)",
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
                command = [
                    "docker",
                    "compose",
                    "-f",
                    str(COMPOSE),
                    "-f",
                    str(ROOT / "examples/compose.traefik.keys.yaml"),
                    "-f",
                    str(override),
                ]
                try:
                    up = subprocess.run(
                        [*command, "up", "-d", "--no-build", "--pull", "never"],
                        env=env,
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    manager_id = subprocess.check_output(
                        [*command, "ps", "-q", "manager"], env=env, text=True
                    ).strip()
                    actual_image = subprocess.check_output(
                        ["docker", "inspect", "-f", "{{.Image}}", manager_id],
                        env=env,
                        text=True,
                    ).strip()
                    expected_image = subprocess.check_output(
                        [
                            "docker",
                            "image",
                            "inspect",
                            "-f",
                            "{{.Id}}",
                            env["GATEWAY_MANAGER_IMAGE"],
                        ],
                        env=env,
                        text=True,
                    ).strip()
                    self.assertEqual(actual_image, expected_image)
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
                    self.wait_for_route(command, env, "/LGplayer02/", "/LGplayer02/")
                    self.wait_for_route(command, env, "/", "landing")
                    for number in (1, 2):
                        player = f"{project}-player{number:02}"
                        content = subprocess.check_output(
                            [
                                "docker",
                                "exec",
                                player,
                                "cat",
                                "/run/secrets/byond_key.txt",
                            ],
                            env=env,
                        )
                        self.assertEqual(
                            content,
                            (keys / f"LGplayer{number:02}_key.txt").read_bytes(),
                        )
                        write = subprocess.run(
                            [
                                "docker",
                                "exec",
                                player,
                                "sh",
                                "-c",
                                "echo changed > /run/secrets/byond_key.txt",
                            ],
                            env=env,
                            capture_output=True,
                        )
                        self.assertNotEqual(write.returncode, 0)
                    first = f"{project}-player01"
                    self.wait_for_health(env, first, "healthy")
                    subprocess.run(
                        ["docker", "exec", first, "touch", "/tmp/health-down"],
                        env=env,
                        check=True,
                    )
                    self.wait_for_health(env, first, "unhealthy")
                    self.wait_for_route(command, env, "/LGplayer01/", "landing")
                    subprocess.run(
                        ["docker", "exec", first, "rm", "/tmp/health-down"],
                        env=env,
                        check=True,
                    )
                    self.wait_for_health(env, first, "healthy")
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
                    labels = json.loads(
                        subprocess.check_output(
                            [
                                "docker",
                                "inspect",
                                "-f",
                                "{{json .Config.Labels}}",
                                f"{project}-player01",
                            ],
                            env=env,
                            text=True,
                        )
                    )
                    self.assertEqual(
                        labels[f"traefik.http.routers.{project}-player01.rule"],
                        "Host(`play.example.org`) && PathPrefix(`/LGplayer01/`)",
                    )
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
                    self.wait_for_route(command, env, "/LGplayer02/", "landing")
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
                    env["GATEWAY_PLAY_HOST"] = "new.example.org"
                    up = subprocess.run(
                        [*command, "up", "-d"], env=env, capture_output=True, text=True
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    self.wait_for_route(command, env, "/LGplayer02/", "/LGplayer02/")
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
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
                ["docker", "image", "rm", fixture_image], env=env, capture_output=True
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
                        "Cf-Access-Client-Secret",
                    ):
                        self.assertNotIn(header, data["body"]["headers"])
                    return
            time.sleep(0.2)
        logs = subprocess.run(
            [*command, "logs", "--no-color", "manager", "landing", "traefik"],
            env=env,
            capture_output=True,
            text=True,
        )
        self.fail(f"Route {path} unavailable: {result.stderr}\n{logs.stdout}")

    def wait_for_health(self, env, player, expected):
        for _ in range(150):
            status = subprocess.check_output(
                ["docker", "inspect", "-f", "{{.State.Health.Status}}", player],
                env=env,
                text=True,
            ).strip()
            if status == expected:
                return
            time.sleep(0.2)
        self.fail(f"{player} health is {status}, expected {expected}")

    @staticmethod
    def request(command, env, path, websocket=False):
        code = """
import http.client, json, os, ssl
conn = http.client.HTTPSConnection("traefik", 8443, context=ssl._create_unverified_context(), timeout=2)
headers = {"Host": os.environ["HOST_TO_CHECK"], "Cookie": "secret=1", "Authorization": "Bearer secret", "Cf-Access-Jwt-Assertion": "secret", "Cf-Access-Client-Secret": "secret"}
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
                "-e",
                f"HOST_TO_CHECK={env['GATEWAY_PLAY_HOST']}",
                "probe",
                "python3",
                "-c",
                code,
            ],
            env=env,
            capture_output=True,
            text=True,
        )
