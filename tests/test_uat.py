import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UatTest(unittest.TestCase):
    def test_matrix_has_one_staging_immutable_tag_and_mode_checks(self):
        workflow = (ROOT / ".github/workflows/uat.yml").read_text()
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("  pull_request:", workflow)
        self.assertNotIn("  release:", workflow)
        self.assertIn("fail-fast: false", workflow)
        self.assertEqual(workflow.count("- wine_package_version:"), 1)
        self.assertIn("wine_package_version: 11.22~resolute-1", workflow)
        self.assertIn("tag_variant: winehq-staging-11.22", workflow)
        self.assertIn("dpkg-query -W winehq-staging | cut -f2", workflow)
        self.assertNotIn("display:", workflow)
        self.assertIn(
            ":uat-issue-7-${{ github.sha }}-${{ matrix.tag_variant }}-wayland",
            workflow,
        )
        self.assertIn(
            "WINE_PACKAGE_VERSION=${{ matrix.wine_package_version }}", workflow
        )
        self.assertIn(
            'test "$(command -v wine)" = /opt/wine-staging/bin/wine', workflow
        )
        self.assertIn('SELKIES_WAYLAND: "true"', workflow)
        self.assertNotIn("${{ matrix.display }}", workflow)
        self.assertIn('grep -Fx "wayland=$SELKIES_WAYLAND"', workflow)
        self.assertIn("bash tests/smoke-wayland.sh", workflow)
        self.assertNotIn("bash tests/smoke-container.sh", workflow)
        self.assertLess(
            workflow.index("name: Smoke-test tagged display mode"),
            workflow.index('docker push "$IMAGE"'),
        )
        self.assertIn(
            "Refusing to overwrite an existing commit-specific UAT tag", workflow
        )
        self.assertIn("Cannot establish tag absence; refusing publication", workflow)
        self.assertIn('docker pull "$reference"', workflow)
        self.assertIn('reference="${IMAGE%:*}@$digest"', workflow)
        self.assertNotIn("{{index .RepoDigests 0}}", workflow)
        self.assertIn("published-digest.txt", workflow)
        self.assertNotIn(":latest", workflow)
        self.assertNotIn(":dev", workflow)

    def test_caches_include_selected_runtime_and_prefix_inputs(self):
        workflow = (ROOT / ".github/workflows/uat.yml").read_text()
        self.assertIn(
            "key: uat-wine-prefix-v4-staging-${{ matrix.wine_package_version }}-wayland-",
            workflow,
        )
        self.assertNotIn("wine-download", workflow)
        for source in (
            "Dockerfile",
            "install-client.sh",
            "install-byond.sh",
            "install-graphics.sh",
        ):
            self.assertIn(source, workflow)

    def test_ci_and_release_publish_the_smoke_tested_player_image(self):
        for filename, tag in (("ci.yml", "ci"), ("publish.yml", "release")):
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github/workflows" / filename).read_text()
                self.assertIn("key: wine-prefix-v5-staging-", workflow)
                self.assertNotIn("wine-download", workflow)
                self.assertNotIn("WINE_PACKAGE_SOURCE", workflow)
                self.assertIn("load: true", workflow)
                self.assertNotIn("push: true", workflow)
                self.assertIn(f"tags: tgstation-gateway-player:{tag}", workflow)
                for smoke in ("smoke-container.sh", "smoke-wayland.sh"):
                    self.assertIn(
                        f"bash tests/{smoke} tgstation-gateway-player:{tag}", workflow
                    )
                self.assertIn("tests/check-wine-runtime.sh", workflow)
                self.assertIn(f"docker tag tgstation-gateway-player:{tag}", workflow)
                self.assertLess(
                    workflow.index("tests/check-wine-runtime.sh"),
                    workflow.index(f"docker tag tgstation-gateway-player:{tag}"),
                )

    def test_publication_refuses_existing_or_uncertain_tags(self):
        workflow = (ROOT / ".github/workflows/uat.yml").read_text()
        self.assertIn(
            'echo "EVIDENCE=$RUNNER_TEMP/uat-evidence" >> "$GITHUB_ENV"', workflow
        )
        self.assertNotIn("      EVIDENCE: ${{ runner.temp }}", workflow)
        publish = textwrap.dedent(
            re.search(
                r"- name: Publish once and verify pull by digest\n        run: \|\n(.*?)\n      - name:",
                workflow,
                re.S,
            )[1]
        )
        for state in ("absent", "exists", "unauthorized", "network"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                docker = root / "docker"
                docker.write_text(
                    '#!/bin/sh\nprintf "%s\\n" "$*" >> "$DOCKER_LOG"\n'
                    'if [ "$1" = buildx ]; then\n'
                    '  case "$REGISTRY_STATE" in\n'
                    "    exists) exit 0 ;;\n"
                    '    absent) echo "ERROR: example: not found" >&2 ;;\n'
                    '    unauthorized) echo "unauthorized" >&2 ;;\n'
                    '    network) echo "dial tcp: lookup ghcr.io: no such host" >&2 ;;\n'
                    "  esac\n"
                    "  exit 1\n"
                    "fi\n"
                    'if [ "$1" = push ]; then echo "uat: digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa size: 10"; fi\n'
                )
                docker.chmod(0o755)
                result = subprocess.run(
                    ["bash", "-c", publish],
                    env={
                        **os.environ,
                        "PATH": f"{root}:{os.environ['PATH']}",
                        "REGISTRY_STATE": state,
                        "DOCKER_LOG": str(root / "docker.log"),
                        "IMAGE": "ghcr.io/example/player:uat",
                        "EVIDENCE": str(root),
                        "GITHUB_SHA": "a" * 40,
                        "WINE_PACKAGE_VERSION": "11.22~resolute-1",
                        "GITHUB_STEP_SUMMARY": str(root / "summary"),
                    },
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(
                    result.returncode == 0, state == "absent", result.stderr
                )
                commands = (root / "docker.log").read_text()
                if state == "absent":
                    self.assertIn("push ghcr.io/example/player:uat", commands)
                    self.assertIn(
                        "pull ghcr.io/example/player@sha256:" + "a" * 64,
                        commands,
                    )
                    self.assertEqual(
                        (root / "published-digest.txt").read_text().strip(),
                        "ghcr.io/example/player@sha256:" + "a" * 64,
                    )
                else:
                    self.assertNotIn("push ", commands)
                    self.assertNotIn("tag ", commands)

    def test_cached_prefix_requires_selected_wine_package(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        block = re.search(
            r"RUN --mount=type=bind,from=wine-prefix-cache,target=/tmp/wine-prefix-cache \\\n(.*?)(?:\n\n)",
            dockerfile,
            re.S,
        )[1].replace("\\\n", " ")
        for cached_version in ("11.21~resolute-1", "11.22~resolute-1", None):
            with self.subTest(cached_version=cached_version):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    source = root / "source"
                    source.mkdir()
                    (source / "system.reg").write_text("registry")
                    webview = (
                        source
                        / "drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application/1"
                    )
                    webview.mkdir(parents=True)
                    (webview / "msedgewebview2.exe").touch()
                    if cached_version:
                        (source / ".gateway-wine-package-version").write_text(
                            cached_version
                        )
                    cache = root / "cache"
                    cache.mkdir()
                    with tarfile.open(cache / "prefix.tar.gz", "w:gz") as archive:
                        archive.add(source, arcname=".")
                    result = subprocess.run(
                        [
                            "sh",
                            "-ec",
                            block.replace("/tmp/wine-prefix-cache", str(cache)),
                        ],
                        env={
                            **os.environ,
                            "WINEPREFIX": str(root / "prefix"),
                            "WINE_PACKAGE_VERSION": "11.22~resolute-1",
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        result.returncode == 0,
                        cached_version == "11.22~resolute-1",
                        result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
