import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
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
            "GATEWAY_IMAGE_POLICY": "pull",
            "DRI_RENDER_GID": "",
        }

    def test_compose_uses_one_manager_and_no_static_players(self):
        self.env.update(
            GATEWAY_MANAGER_GPU="true",
            DRI_RENDER_GID="123",
            GATEWAY_IMAGE_POLICY="local",
        )
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
        self.assertEqual(
            services["manager"]["environment"]["GATEWAY_IMAGE_POLICY"], "local"
        )
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

    def test_manager_compose_selkies_defaults_and_overrides(self):
        self.env.update(SELKIES_UI_TITLE="Custom title", SELKIES_MANUAL_WIDTH="1280")
        configs = []
        for compose in (COMPOSE, ROOT / "examples/compose.yaml"):
            result = subprocess.run(
                ["docker", "compose", "-f", str(compose), "config", "--format", "json"],
                env=self.env,
                capture_output=True,
                text=True,
                check=True,
            )
            services = json.loads(result.stdout)["services"]
            configs.append(services["manager" if compose == COMPOSE else "player"])
        manager_env, player_env = (service["environment"] for service in configs)
        for key, value in player_env.items():
            if key.startswith("SELKIES_"):
                self.assertEqual(manager_env.get(key), value, key)
        self.assertEqual(manager_env["SELKIES_UI_TITLE"], "Custom title")
        self.assertEqual(manager_env["SELKIES_MANUAL_WIDTH"], "1280")

    def test_manager_forwards_selkies_environment_and_hashes_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (ROOT / "examples/slot-manager.sh").read_text()
            script = script.replace(
                "/run/gateway-lock/manager.lock", str(root / "lock")
            )
            script = script.replace(
                "/run/gateway-lock/startup-generation", str(root / "generation")
            )
            script = script.replace("/opt/gateway/seccomp.json", str(root / "seccomp"))
            (root / "manager.sh").write_text(script)
            (root / "seccomp").write_text("{}")
            docker = root / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                'case "$1 $2" in\n'
                '  "image inspect") echo sha256:fixture ;;\n'
                '  "volume inspect") case "$4" in *deployment*) echo gatewaytest;; '
                '*slot*) echo 01;; *role*) case "$5" in *wine) echo wine;; *byond) echo byond;; *) echo data;; esac;; esac ;;\n'
                '  "run -d") printf "%s\\0" "$@" > "$ARGS"; '
                'printenv SELKIES_CUSTOM > "$VALUE"; exit 43 ;;\n'
                "esac\n"
            )
            docker.chmod(0o755)
            env = {
                **self.env,
                "PATH": f"{root}:{os.environ['PATH']}",
                "ARGS": str(root / "args"),
                "VALUE": str(root / "value"),
                "GATEWAY_SLOT_COUNT": "1",
                "GATEWAY_IMAGE_POLICY": "local",
                "SELKIES_CUSTOM": "value with spaces\nSELKIES_FAKE=injected",
                "SELKIES_EMPTY": "",
                "SELKIES_SUBFOLDER": "/wrong/",
                "UNRELATED_SETTING": "ignored",
            }

            def run():
                result = subprocess.run(
                    ["sh", str(root / "manager.sh")],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, 43, result.stderr)
                args = (root / "args").read_bytes().decode().split("\0")[:-1]
                settings = next(
                    arg
                    for arg in args
                    if arg.startswith("io.tgstation-gateway.settings=")
                )
                return args, settings

            args, settings = run()
            self.assertEqual(
                (root / "value").read_text(),
                "value with spaces\nSELKIES_FAKE=injected\n",
            )
            self.assertIn("SELKIES_CUSTOM", args)
            self.assertIn("SELKIES_EMPTY", args)
            self.assertNotIn("SELKIES_FAKE", args)
            self.assertNotIn("UNRELATED_SETTING", args)
            self.assertNotIn("SELKIES_SUBFOLDER", args)
            self.assertIn("SELKIES_SUBFOLDER=/LGplayer01/", args)
            env["SELKIES_SUBFOLDER"] = "/another/"
            self.assertEqual(run()[1], settings)
            env["SELKIES_CUSTOM"] = "changed"
            self.assertNotEqual(run()[1], settings)

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
            ("GATEWAY_IMAGE_POLICY", "invalid"),
        ):
            result = subprocess.run(
                ["sh", str(ROOT / "examples/slot-manager.sh")],
                env={**self.env, key: value},
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(key, result.stderr)

    def test_manager_image_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (ROOT / "examples/slot-manager.sh").read_text()
            script = script.replace(
                "/run/gateway-lock/manager.lock", str(root / "lock")
            )
            script = script.replace(
                "/run/gateway-lock/startup-generation", str(root / "generation")
            )
            script = script.replace("/opt/gateway/seccomp.json", str(root / "seccomp"))
            (root / "manager.sh").write_text(script)
            (root / "seccomp").write_text("{}")
            docker = root / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                'printf "%s\\n" "$*" >> "$EVENTS"\n'
                'case "$1 $2" in\n'
                '  "pull "*) [ "$FAIL_PULL" != true ] || exit 41 ;;\n'
                '  "image inspect") [ "$MISSING_IMAGE" != true ] || exit 42; echo sha256:fixture ;;\n'
                '  "volume inspect") case "$4" in *deployment*) echo gatewaytest;; '
                '*slot*) echo 01;; *role*) case "$5" in *wine) echo wine;; *byond) echo byond;; *) echo data;; esac;; esac ;;\n'
                '  "run -d") exit 43 ;;\n'
                "esac\n"
            )
            docker.chmod(0o755)
            for policy, fail_pull, missing, expected in (
                (None, "false", "false", 43),
                ("local", "true", "false", 43),
                ("local", "false", "true", 1),
                ("pull", "true", "false", 41),
                ("pull", "false", "false", 43),
            ):
                with self.subTest(policy=policy, fail_pull=fail_pull, missing=missing):
                    events = root / "events"
                    events.unlink(missing_ok=True)
                    env = {
                        **self.env,
                        "PATH": f"{root}:{os.environ['PATH']}",
                        "EVENTS": str(events),
                        "GATEWAY_SLOT_COUNT": "1",
                        "GATEWAY_IMAGE": "private.example/player:local",
                        "FAIL_PULL": fail_pull,
                        "MISSING_IMAGE": missing,
                    }
                    if policy is None:
                        env.pop("GATEWAY_IMAGE_POLICY")
                    else:
                        env["GATEWAY_IMAGE_POLICY"] = policy
                    result = subprocess.run(
                        ["sh", str(root / "manager.sh")],
                        env=env,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, expected, result.stderr)
                    calls = events.read_text().splitlines()
                    self.assertEqual(
                        any(call.startswith("pull ") for call in calls),
                        policy != "local",
                    )
                    if missing == "true":
                        self.assertIn(
                            "Player image is unavailable locally", result.stderr
                        )
                        self.assertFalse(
                            any(call.startswith("container ls") for call in calls)
                        )
                    if expected == 43:
                        self.assertTrue(
                            any(
                                call.startswith("run -d ")
                                and call.endswith("sha256:fixture")
                                for call in calls
                            )
                        )

    def test_documents_migration_retries_and_does_not_restore_stale_data(self):
        manager = (ROOT / "examples/slot-manager.sh").read_text()
        script = manager.split('"$@" "$image_id" -ec \'', 1)[1].split(
            "' >/dev/null", 1
        )[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "legacy/drive_c/users/steamuser/Documents/BYOND"
            target = root / "target"
            source.mkdir(parents=True)
            target.mkdir()
            (source / "key.txt").write_text("saved key")
            (root / "chown").write_text("#!/bin/sh\nexit 0\n")
            (root / "cp").write_text(
                '#!/bin/sh\n/bin/cp "$@" || exit $?\n'
                '[ "${FAIL_COPY:-false}" != true ]\n'
            )
            (root / "chown").chmod(0o755)
            (root / "cp").chmod(0o755)
            script = script.replace("/legacy", str(root / "legacy")).replace(
                "/target", str(target)
            )
            env = {**os.environ, "PATH": f"{root}:{os.environ['PATH']}"}

            def migrate(**extra):
                return subprocess.run(
                    ["sh", "-ec", script],
                    env={**env, **extra},
                    capture_output=True,
                    text=True,
                )

            self.assertNotEqual(migrate(FAIL_COPY="true").returncode, 0)
            self.assertFalse((target / ".gateway-migration-complete").exists())
            self.assertEqual(migrate().returncode, 0)
            self.assertEqual((target / "documents/key.txt").read_text(), "saved key")
            (target / "documents/key.txt").write_text("new key")
            self.assertEqual(migrate().returncode, 0)
            self.assertEqual((target / "documents/key.txt").read_text(), "new key")

            (target / ".gateway-migration-complete").unlink()
            source.rename(source.with_name("old"))
            source.symlink_to(source.with_name("old"), target_is_directory=True)
            self.assertNotEqual(migrate().returncode, 0)
            self.assertFalse((target / ".gateway-migration-complete").exists())

    def test_manager_recreates_players_on_startup_preserving_volumes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (ROOT / "examples/slot-manager.sh").read_text()
            script = script.replace(
                "/run/gateway-lock/manager.lock", str(root / "lock")
            )
            script = script.replace(
                "/run/gateway-lock/startup-generation", str(root / "startup-generation")
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
                '      *startup-generation*) cat "$STATE/generation" ;;\n'
                '      *Running*) cat "$STATE/running" ;;\n'
                "    esac ;;\n"
                '  "volume ls")\n'
                '    volume="${4#name=^}"; volume="${volume%$}"\n'
                '    [ ! -f "$STATE/$volume" ] || echo "$volume" ;;\n'
                '  "volume inspect")\n'
                '    if [ "$3" = --format ]; then\n'
                '      case "$4" in\n'
                '        *deployment*) echo "${VOLUME_OWNER:-gatewaytest}" ;;\n'
                '        *slot*) echo "${VOLUME_SLOT:-01}" ;;\n'
                '        *role*) case "$5" in *-wine) echo wine;; *-byond) echo byond;; *) echo data;; esac ;;\n'
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
                "      io.tgstation-gateway.startup-generation=*)\n"
                '        echo "${arg#*=}" > "$STATE/generation" ;;\n'
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
            self.assertTrue(
                any(
                    "source=gatewaytest-player01-byond,target=/home/ubuntu/.wine/drive_c/users/steamuser/Documents/BYOND,volume-subpath=documents"
                    in event
                    for event in events
                    if event.startswith("run -d ")
                )
            )
            self.assertFalse(
                any(event.startswith(("rm ", "volume rm ")) for event in events)
            )
            settings = (root / "settings").read_text()
            for role in ("byond", "data"):
                (root / f"gatewaytest-player01-{role}").write_text("saved login")
            (root / "gatewaytest-player01-wine").write_text("legacy")
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
                    for role in ("byond", "data"):
                        volume = f"gatewaytest-player01-{role}"
                        self.assertEqual((root / volume).read_text(), "saved login")
                        self.assertNotIn(f"volume rm {volume}", events)
                        self.assertFalse(
                            any(event.startswith("volume create ") for event in events)
                        )
                    self.assertEqual(
                        sum(event.startswith("run -d ") for event in events), 1
                    )
                    self.assertTrue(
                        any(
                            "source=gatewaytest-player01-wine,target=/legacy,readonly,volume-nocopy"
                            in event
                            for event in events
                        )
                    )
                    self.assertEqual(
                        (root / "gatewaytest-player01-wine").read_text(), "legacy"
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

    def test_manager_preflights_and_resumes_interrupted_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (ROOT / "examples/slot-manager.sh").read_text()
            script = script.replace(
                "/run/gateway-lock/manager.lock", str(root / "lock")
            )
            script = script.replace(
                "/run/gateway-lock/startup-generation", str(root / "startup-generation")
            )
            script = script.replace("/opt/gateway/seccomp.json", str(root / "seccomp"))
            (root / "manager.sh").write_text(script)
            (root / "seccomp").write_text("{}")
            docker = root / "docker"
            docker.write_text(
                "#!/bin/sh\n"
                'echo "$*" >> "$STATE/events"\n'
                'case "$1 $2" in\n'
                '  "image inspect") echo fixture-image ;;\n'
                '  "container ls")\n'
                '    case "$*" in *--no-trunc*)\n'
                '      case "$*" in *player01*) slot=01;; *player02*) slot=02;; esac\n'
                '      [ ! -f "$STATE/exists$slot" ] || echo "id$slot" ;;\n'
                "    esac ;;\n"
                '  "inspect --format")\n'
                '    slot="${4#id}"\n'
                '    case "$3" in\n'
                "      *project*) echo tgstation-gateway ;;\n"
                "      *deployment*) echo gatewaytest ;;\n"
                "      *role*) echo player ;;\n"
                '      *slot*) echo "$slot" ;;\n'
                '      *settings*) cat "$STATE/settings$slot" ;;\n'
                '      *startup-generation*) cat "$STATE/generation$slot" ;;\n'
                "      *Running*) echo true ;;\n"
                "    esac ;;\n"
                '  "volume ls")\n'
                '    [ "${FAIL_LIST:-0}" != 1 ] || exit 42\n'
                '    volume="${4#name=^}"; echo "${volume%$}" ;;\n'
                '  "volume inspect")\n'
                '    [ "${FAIL_INSPECT:-0}" != 1 ] || exit 42\n'
                '    if [ "$3" = --format ]; then\n'
                '      case "$5" in *player01*) slot=01;; *) slot=02;; esac\n'
                '      case "$4" in\n'
                '        *deployment*) if [ "$slot" = 02 ] && [ "${CONFLICT:-0}" = 1 ]; then echo other; else echo gatewaytest; fi ;;\n'
                '        *slot*) echo "$slot" ;;\n'
                '        *role*) case "$5" in *-wine) echo wine;; *-byond) echo byond;; *) echo data;; esac ;;\n'
                "      esac\n"
                "    fi ;;\n"
                '  "rm -f") rm "$STATE/exists${3#id}" ;;\n'
                '  "run --rm") case "$*" in *gatewaytest-player02-migration*) '
                '[ "${FAIL:-}" != migration ] || exit 42;; esac ;;\n'
                '  "run -d")\n'
                '    for arg in "$@"; do\n'
                '      case "$arg" in\n'
                "        gatewaytest-player01) slot=01;; gatewaytest-player02) slot=02;;\n"
                '        io.tgstation-gateway.settings=*) settings="${arg#*=}" ;;\n'
                '        io.tgstation-gateway.startup-generation=*) generation="${arg#*=}" ;;\n'
                "      esac\n"
                "    done\n"
                '    if [ "$slot" = 02 ] && [ "${FAIL:-}" = before ]; then exit 42; fi\n'
                '    echo "$settings" > "$STATE/settings$slot"\n'
                '    echo "$generation" > "$STATE/generation$slot"\n'
                '    touch "$STATE/exists$slot"\n'
                '    if [ "$slot" = 02 ] && [ "${FAIL:-}" = after ]; then exit 42; fi ;;\n'
                "esac\n"
            )
            docker.chmod(0o755)
            sleep = root / "sleep"
            sleep.write_text("#!/bin/sh\nexit 23\n")
            sleep.chmod(0o755)
            for slot in ("01", "02"):
                (root / f"exists{slot}").touch()
                (root / f"settings{slot}").write_text("old")
                (root / f"generation{slot}").write_text("old")
            env = {
                **self.env,
                "GATEWAY_SLOT_COUNT": "2",
                "STATE": str(root),
                "PATH": f"{root}:{os.environ['PATH']}",
            }

            def run(**overrides):
                (root / "events").write_text("")
                result = subprocess.run(
                    ["sh", str(root / "manager.sh")],
                    env={**env, **overrides},
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                return result, (root / "events").read_text().splitlines()

            result, events = run(CONFLICT="1")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing to use unowned volume", result.stderr)
            self.assertFalse(
                any(event.startswith(("rm ", "run -d ")) for event in events)
            )
            for failure in ("FAIL_LIST", "FAIL_INSPECT"):
                result, events = run(**{failure: "1"})
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertFalse(
                    any(event.startswith(("rm ", "run -d ")) for event in events)
                )

            result, events = run(FAIL="migration")
            self.assertEqual(result.returncode, 42, result.stderr)
            self.assertIn("rm -f id01", events)
            generation = (root / "startup-generation").read_text()
            self.assertEqual((root / "generation01").read_text(), generation)
            for failure in ("migration", "before", "after"):
                result, events = run(FAIL=failure)
                self.assertEqual(result.returncode, 42, result.stderr)
                self.assertNotIn("rm -f id01", events)
                self.assertEqual((root / "startup-generation").read_text(), generation)

            result, events = run()
            self.assertEqual(result.returncode, 23, result.stderr)
            self.assertNotIn("rm -f id01", events)
            self.assertNotIn("rm -f id02", events)
            self.assertFalse(any(event.startswith("run -d ") for event in events))
            self.assertFalse((root / "startup-generation").exists())

    def test_manager_gpu_arguments_and_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = (ROOT / "examples/slot-manager.sh").read_text()
            script = script.replace(
                "/run/gateway-lock/manager.lock", str(root / "lock")
            )
            script = script.replace(
                "/run/gateway-lock/startup-generation", str(root / "startup-generation")
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
                '  "volume ls") ;;\n'
                '  "volume inspect") case "$4" in\n'
                "    *deployment*) echo gatewaytest ;;\n"
                "    *slot*) echo 01 ;;\n"
                '    *role*) case "$5" in *-wine) echo wine;; *-byond) echo byond;; *) echo data;; esac ;;\n'
                "  esac ;;\n"
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
    os.environ.get("GATEWAY_DOCKER_TEST_IMAGE"),
    "Set GATEWAY_DOCKER_TEST_IMAGE to a local shell-capable fixture image",
)
class DocumentsMigrationDockerTest(unittest.TestCase):
    def test_existing_documents_are_copied_once(self):
        image = os.environ["GATEWAY_DOCKER_TEST_IMAGE"]
        legacy = f"gateway-migration-{uuid.uuid4().hex}"
        target = f"{legacy}-target"
        script = (
            (ROOT / "examples/slot-manager.sh")
            .read_text()
            .split('"$@" "$image_id" -ec \'', 1)[1]
            .split("' >/dev/null", 1)[0]
        )

        def docker(*args):
            return subprocess.run(
                ["docker", *args], check=True, capture_output=True, text=True
            )

        try:
            docker("volume", "create", legacy)
            docker("volume", "create", target)
            docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "sh",
                "-v",
                f"{legacy}:/legacy",
                image,
                "-ec",
                "mkdir -p /legacy/drive_c/users/steamuser/Documents/BYOND && "
                "echo old > /legacy/drive_c/users/steamuser/Documents/BYOND/key.txt && "
                "echo obsolete > /legacy/old-client",
            )

            def migrate():
                docker(
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--user",
                    "0:0",
                    "--entrypoint",
                    "sh",
                    "--mount",
                    f"type=volume,source={legacy},target=/legacy,readonly,volume-nocopy",
                    "--mount",
                    f"type=volume,source={target},target=/target,volume-nocopy",
                    image,
                    "-ec",
                    script,
                )

            migrate()
            docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "sh",
                "--mount",
                f"type=volume,source={target},target=/byond,volume-subpath=documents",
                image,
                "-ec",
                'test "$(cat /byond/key.txt)" = old && '
                "test ! -e /byond/old-client && "
                "test ! -e /byond/.gateway-migration-complete && "
                "echo new > /byond/key.txt",
            )
            migrate()
            docker(
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "sh",
                "-v",
                f"{target}:/target",
                image,
                "-ec",
                'test "$(cat /target/documents/key.txt)" = new',
            )
        finally:
            subprocess.run(
                ["docker", "volume", "rm", legacy, target], capture_output=True
            )


@unittest.skipUnless(
    all(
        os.environ.get(key)
        for key in (
            "GATEWAY_TEST_MANAGER_IMAGE",
            "GATEWAY_TEST_BACKEND_IMAGE",
            "GATEWAY_TEST_TRAEFIK_IMAGE",
            "GATEWAY_TEST_REGISTRY_IMAGE",
        )
    ),
    "Set fixture images to run the Docker manager and routing test",
)
class ManagerDockerTest(unittest.TestCase):
    def test_manager_creates_routes_recreates_players_and_retains_data(self):
        project = f"gatewaytest{uuid.uuid4().hex[:12]}"
        network = f"{project}-edge"
        registry = f"{project}-registry"
        fixture_image = ""
        env = {
            **os.environ,
            "GATEWAY_DEPLOYMENT_ID": project,
            "GATEWAY_PLAY_HOST": "play.example.org",
            "GATEWAY_TRAEFIK_NETWORK": network,
            "GATEWAY_TRAEFIK_ENTRYPOINT": "https",
            "GATEWAY_SLOT_COUNT": "2",
            "BYOND_SERVER": "tgstation:1337",
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
            subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    registry,
                    "-p",
                    "127.0.0.1::5000",
                    os.environ["GATEWAY_TEST_REGISTRY_IMAGE"],
                ],
                env=env,
                check=True,
                capture_output=True,
            )
            address = subprocess.check_output(
                ["docker", "port", registry, "5000/tcp"], env=env, text=True
            ).strip()
            fixture_image = f"{address}/{project}-fixture:latest"
            env["GATEWAY_IMAGE"] = fixture_image
            for _ in range(100):
                try:
                    with urllib.request.urlopen(f"http://{address}/v2/", timeout=1):
                        break
                except (OSError, urllib.error.URLError):
                    time.sleep(0.1)
            else:
                self.fail("Fixture registry did not become ready")
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
                    "RUN mkdir -p /home/ubuntu/.wine/drive_c/users/steamuser/Documents/BYOND"
                    " && echo fresh > /home/ubuntu/.wine/marker\n"
                    'HEALTHCHECK CMD exit 1\nCMD ["python3", "-u", "/app.py"]\n'
                )
                build = subprocess.run(
                    ["docker", "build", "-t", fixture_image, str(context)],
                    env=env,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(build.returncode, 0, build.stderr)
                subprocess.run(
                    ["docker", "push", fixture_image],
                    env=env,
                    check=True,
                    capture_output=True,
                )
                legacy = f"{project}-player02-wine"
                subprocess.run(
                    [
                        "docker",
                        "volume",
                        "create",
                        "--label",
                        f"io.tgstation-gateway.deployment={project}",
                        "--label",
                        "io.tgstation-gateway.slot=02",
                        "--label",
                        "io.tgstation-gateway.role=wine",
                        legacy,
                    ],
                    env=env,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    [
                        "docker",
                        "run",
                        "--rm",
                        "--entrypoint",
                        "sh",
                        "-v",
                        f"{legacy}:/legacy",
                        fixture_image,
                        "-c",
                        "mkdir -p /legacy/drive_c/users/steamuser/Documents/BYOND && "
                        "echo migrated > /legacy/drive_c/users/steamuser/Documents/BYOND/marker && "
                        "echo obsolete > /legacy/marker",
                    ],
                    env=env,
                    check=True,
                    capture_output=True,
                )
                subprocess.run(
                    ["docker", "image", "rm", fixture_image],
                    env=env,
                    check=True,
                    capture_output=True,
                )
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
                            'test "$(cat /home/ubuntu/.wine/marker)" = fresh && '
                            'test "$(cat /home/ubuntu/.wine/drive_c/users/steamuser/Documents/BYOND/marker)" = migrated && '
                            "echo stale > /home/ubuntu/.wine/drive_c/users/steamuser/Documents/BYOND/marker && "
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
                                'test "$(cat /home/ubuntu/.wine/marker)" = fresh && '
                                'test "$(cat /home/ubuntu/.wine/drive_c/users/steamuser/Documents/BYOND/marker)" = stale && '
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
                            "echo stale > /home/ubuntu/.wine/drive_c/users/steamuser/Documents/BYOND/marker; "
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
                        ["docker", "volume", "inspect", f"{player}-byond"],
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
                    before_conflict = [state["Id"] for state in player_state()]
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
                    subprocess.run(
                        [*command, "restart", "manager"],
                        env=env,
                        check=True,
                        capture_output=True,
                    )
                    time.sleep(2)
                    self.assertEqual(
                        [state["Id"] for state in player_state()], before_conflict
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
                                f"{player}-byond",
                                f"{player}-data",
                            ],
                            env=env,
                            capture_output=True,
                        )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", registry], env=env, capture_output=True
            )
            subprocess.run(
                ["docker", "network", "rm", network], env=env, capture_output=True
            )
            if fixture_image:
                subprocess.run(
                    ["docker", "image", "rm", fixture_image],
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
