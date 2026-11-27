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
        ):
            result = subprocess.run(
                ["sh", str(ROOT / "examples/slot-manager.sh")],
                env={**self.env, key: value},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(key, result.stderr)

    def test_manager_recreates_players_on_startup_preserving_volumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
                'printf "%s\\n" "$*" >> "$STATE/events"\n'
                'case "$1 $2" in\n'
                '  "image inspect") echo fixture-image ;;\n'
                '  "container ls")\n'
                '    case "$*" in *--no-trunc*)\n'
                '      [ ! -f "$STATE/exists" ] || echo fixture-id ;;\n'
                "    esac ;;\n"
                '  "inspect --format")\n'
                '    case "$3" in\n'
                "      *project*) echo tgstation-gateway ;;\n"
                "      *deployment*) echo gatewaytest ;;\n"
                '      *role*) echo "${ROLE:-player}" ;;\n'
                "      *slot*) echo 01 ;;\n"
                '      *settings*) cat "$STATE/settings" ;;\n'
                '      *Running*) cat "$STATE/running" ;;\n'
                "    esac ;;\n"
                '  "volume inspect")\n'
                '    if [ "$3" = --format ]; then\n'
                '      case "$4" in\n'
                '        *deployment*) echo "${VOLUME_OWNER:-gatewaytest}" ;;\n'
                '        *slot*) echo "${VOLUME_SLOT:-01}" ;;\n'
                '        *role*) case "$5" in *-wine) echo wine;; *) echo data;; esac ;;\n'
                "      esac\n"
                "    else\n"
                '      test -f "$STATE/$3"\n'
                "    fi ;;\n"
                '  "volume create")\n'
                '    for arg in "$@"; do volume="$arg"; done\n'
                '    touch "$STATE/$volume" ;;\n'
                '  "run -d")\n'
                '    for arg in "$@"; do\n'
                '      case "$arg" in io.tgstation-gateway.settings=*)\n'
                '        echo "${arg#*=}" > "$STATE/settings" ;;\n'
                "      esac\n"
                "    done\n"
                '    touch "$STATE/exists"\n'
                '    echo true > "$STATE/running" ;;\n'
                '  "rm -f")\n'
                '    [ "${FAIL_REMOVE:-false}" != true ] || exit 42\n'
                '    rm "$STATE/exists" ;;\n'
                "esac\n"
            )
            docker.chmod(0o755)
            sleep = root / "sleep"
            sleep.write_text(
                "#!/bin/sh\n"
                'if [ -f "$STATE/slept" ]; then exit 23; fi\n'
                'touch "$STATE/slept"\n'
            )
            sleep.chmod(0o755)
            env = {
                **self.env,
                "GATEWAY_SLOT_COUNT": "1",
                "STATE": str(root),
                "PATH": f"{root}:{os.environ['PATH']}",
            }

            def run(**overrides):
                (root / "events").write_text("")
                (root / "slept").unlink(missing_ok=True)
                result = subprocess.run(
                    ["sh", str(root / "manager.sh")],
                    env={**env, **overrides},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result, (root / "events").read_text().splitlines()

            result, events = run()
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertFalse(
                any(event.startswith(("rm ", "volume rm ")) for event in events)
            )
            settings = (root / "settings").read_text()
            for role in ("wine", "data"):
                (root / f"gatewaytest-player01-{role}").write_text("saved login")
            for running in ("true", "false", "missing"):
                with self.subTest(container=running):
                    (root / "running").write_text(running)
                    if running == "missing":
                        (root / "exists").unlink()
                    result, events = run()
                    self.assertEqual(result.returncode, 23, result.stderr)
                    self.assertEqual(
                        events.count("rm -f fixture-id"), int(running != "missing")
                    )
                    for role in ("wine", "data"):
                        volume = f"gatewaytest-player01-{role}"
                        self.assertEqual((root / volume).read_text(), "saved login")
                        self.assertNotIn(f"volume rm {volume}", events)
                        self.assertFalse(
                            any(event.startswith("volume create ") for event in events)
                        )
                    self.assertEqual(
                        sum(event.startswith("run -d ") for event in events), 1
                    )
            result, events = run(FAIL_REMOVE="true")
            self.assertEqual(result.returncode, 42)
            self.assertFalse(any(event.startswith("volume rm ") for event in events))
            result, events = run(ROLE="landing")
            self.assertNotEqual(result.returncode, 23)
            self.assertIn("Refusing to modify unowned container", result.stderr)
            self.assertNotIn("rm -f fixture-id", events)
            for overrides in ({"VOLUME_OWNER": "other"}, {"VOLUME_SLOT": "02"}):
                result, events = run(**overrides)
                self.assertNotEqual(result.returncode, 23)
                self.assertIn("Refusing to use unowned volume", result.stderr)
                self.assertFalse(
                    any(event.startswith(("volume rm ", "run -d ")) for event in events)
                )
            (root / "exists").touch()
            (root / "settings").write_text("outdated")
            result, events = run()
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertIn("rm -f fixture-id", events)
            self.assertTrue(any(event.startswith("run -d ") for event in events))
            self.assertNotIn("restart fixture-id", events)
            self.assertEqual((root / "settings").read_text(), settings)

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
                self.assertIn("BYOND_ACCOUNT=LGplayer01", arguments)
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
    def test_manager_creates_routes_recreates_players_and_retains_data(self):
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
                context = root / "backend"
                context.mkdir()
                (context / "app.py").write_text(backend)
                (context / "curl").write_text(
                    "#!/usr/bin/env python3\n"
                    "import sys, urllib.request\n"
                    "urllib.request.urlopen(sys.argv[-1], timeout=2).close()\n"
                )
                (context / "Dockerfile").write_text(
                    f"FROM {os.environ['GATEWAY_TEST_BACKEND_IMAGE']}\n"
                    "COPY app.py /app.py\nCOPY --chmod=755 curl /usr/local/bin/curl\n"
                    'HEALTHCHECK CMD exit 1\nCMD ["python3", "-u", "/app.py"]\n'
                )
                build = subprocess.run(
                    ["docker", "build", "-t", fixture_image, str(context)],
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
                            "echo stale > /home/ubuntu/.wine/marker; "
                            "echo stale > /home/ubuntu/.local/share/marker",
                        ],
                        env=env,
                        check=True,
                    )
                    first = f"{project}-player01"

                    def player_state():
                        result = subprocess.run(
                            ["docker", "inspect", first, player],
                            env=env,
                            text=True,
                            capture_output=True,
                        )
                        return (
                            json.loads(result.stdout) if result.returncode == 0 else []
                        )

                    def assert_retained_player():
                        subprocess.run(
                            [
                                "docker",
                                "exec",
                                player,
                                "sh",
                                "-c",
                                'test "$(cat /home/ubuntu/.wine/marker)" = stale && '
                                'test "$(cat /home/ubuntu/.local/share/marker)" = stale',
                            ],
                            env=env,
                            check=True,
                            capture_output=True,
                        )

                    before = player_state()
                    subprocess.run(
                        [*command, "restart", "manager"],
                        env=env,
                        check=True,
                        capture_output=True,
                    )
                    for _ in range(100):
                        after = player_state()
                        if len(after) == 2 and all(
                            old["Id"] != new["Id"] and new["State"]["Running"]
                            for old, new in zip(before, after)
                        ):
                            break
                        time.sleep(0.2)
                    else:
                        self.fail("Manager startup did not recreate both players")
                    for old, new in zip(before, after):
                        self.assertNotEqual(old["Id"], new["Id"])
                        self.assertEqual(
                            {mount["Destination"]: mount for mount in old["Mounts"]},
                            {mount["Destination"]: mount for mount in new["Mounts"]},
                        )
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
                    self.wait_for_route(command, env, "/LGplayer02/", "/LGplayer02/")
                    time.sleep(12)
                    self.assertEqual(
                        [state["State"]["StartedAt"] for state in player_state()],
                        [state["State"]["StartedAt"] for state in after],
                    )
                    assert_retained_player()
                    original_id = after[0]["Id"]
                    subprocess.run(
                        [
                            "docker",
                            "exec",
                            player,
                            "sh",
                            "-c",
                            "echo stale > /home/ubuntu/.wine/marker; "
                            "echo stale > /home/ubuntu/.local/share/marker",
                        ],
                        env=env,
                        check=True,
                    )
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
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
                    self.assertNotEqual(
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
                    assert_retained_player()
                    env["GATEWAY_PLAY_HOST"] = "new.example.org"
                    up = subprocess.run(
                        [*command, "up", "-d"], env=env, capture_output=True, text=True
                    )
                    self.assertEqual(up.returncode, 0, up.stderr)
                    self.wait_for_route(command, env, "/LGplayer02/", "/LGplayer02/")
                    self.wait_for_route(command, env, "/LGplayer01/", "/LGplayer01/")
                    assert_retained_player()
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
