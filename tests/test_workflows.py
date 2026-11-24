import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import re


ROOT = Path(__file__).resolve().parents[1]


def workflow_jobs(filename):
    workflow = (ROOT / ".github/workflows" / filename).read_text()
    workflow = workflow[workflow.index("\njobs:\n") :]
    return dict(
        re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:|\Z)", workflow, re.M | re.S)
    )


class WorkflowTest(unittest.TestCase):
    def test_ci_and_release_build_local_player_images(self):
        for filename, tag in (("ci.yml", "ci"), ("publish.yml", "release")):
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github/workflows" / filename).read_text()
                self.assertIn("key: wine-prefix-v4-proton-", workflow)
                self.assertIn("wine-download-v1-", workflow)
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
                if filename == "publish.yml":
                    self.assertLess(
                        workflow.index("tests/check-wine-runtime.sh"),
                        workflow.index(f"docker tag tgstation-gateway-player:{tag}"),
                    )

    def test_ci_unit_tests_and_image_run_independently_after_formatting(self):
        jobs = workflow_jobs("ci.yml")
        for job in ("unit-tests", "image", "landing-image"):
            with self.subTest(job=job):
                self.assertEqual(
                    re.findall(r"^    needs: (.+)$", jobs[job], re.M), ["formatting"]
                )
        command = "python3 -m unittest discover -s tests -v"
        self.assertIn(command, jobs["unit-tests"])
        self.assertNotIn(command, jobs["image"])
        self.assertNotIn(command, jobs["landing-image"])

    def test_landing_and_player_images_build_in_separate_jobs(self):
        for filename, player, tag in (
            ("ci.yml", "image", "ci"),
            ("publish.yml", "player-image", "release"),
        ):
            jobs = workflow_jobs(filename)
            with self.subTest(workflow=filename):
                landing = jobs["landing-image"]
                self.assertIn("landing/Dockerfile", landing)
                self.assertIn(
                    f"tests/smoke-landing.sh tgstation-gateway-landing:{tag}", landing
                )
                self.assertNotIn("landing/Dockerfile", jobs[player])
                self.assertNotIn("tgstation-gateway-landing", jobs[player])
                self.assertNotIn("wine", landing.lower())
                self.assertNotIn("tgstation-gateway-player", landing)
                self.assertIn(f"tgstation-gateway-player:{tag}", jobs[player])
                needs = re.findall(r"^    needs: (.+)$", landing, re.M)
                self.assertEqual(
                    needs, re.findall(r"^    needs: (.+)$", jobs[player], re.M)
                )

    def test_ci_publishes_dev_image_before_container_validation(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        publish = workflow.index("name: Publish development image")
        self.assertLess(workflow.index("name: Build player image"), publish)
        publish_step = workflow[
            publish : workflow.index("\n      - name:", publish + 1)
        ]
        self.assertIn(
            "github.event_name == 'pull_request' && "
            "format('dev-pr{0}', github.event.pull_request.number) || 'dev'",
            publish_step,
        )
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            publish_step,
        )
        for validation in (
            "name: Validate Compose example",
            "name: Smoke-test player image",
            "name: Smoke-test Wayland session",
            "tests/check-wine-runtime.sh",
        ):
            with self.subTest(validation=validation):
                self.assertLess(publish, workflow.index(validation))

    def test_ci_builds_publishes_and_smoke_tests_landing_image(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        build = workflow.index("name: Build landing image")
        publish = workflow.index("name: Publish development landing image")
        smoke = workflow.index(
            "bash tests/smoke-landing.sh tgstation-gateway-landing:ci"
        )
        self.assertLess(build, publish)
        self.assertLess(publish, smoke)
        build_step = workflow[build : workflow.index("\n      - name:", build + 1)]
        self.assertIn("file: landing/Dockerfile", build_step)
        self.assertIn("load: true", build_step)
        self.assertIn("tags: tgstation-gateway-landing:ci", build_step)
        publish_step = workflow[
            publish : workflow.index("\n      - name:", publish + 1)
        ]
        self.assertIn("ghcr.io/${{ github.repository }}-landing:", publish_step)
        self.assertIn(
            "format('dev-pr{0}', github.event.pull_request.number) || 'dev'",
            publish_step,
        )
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            publish_step,
        )
        self.assertIn('docker tag tgstation-gateway-landing:ci "$IMAGE"', publish_step)

    def test_release_smoke_tests_landing_image_before_publishing(self):
        jobs = workflow_jobs("publish.yml")
        self.assertEqual(set(jobs), {"unit-tests", "player-image", "landing-image"})
        self.assertIn("python3 -m unittest discover -s tests -v", jobs["unit-tests"])
        for job in ("player-image", "landing-image"):
            with self.subTest(job=job):
                self.assertIn(
                    "ref: refs/tags/${{ github.event.release.tag_name }}", jobs[job]
                )
                self.assertEqual(
                    re.findall(r"^    needs: (.+)$", jobs[job], re.M), ["unit-tests"]
                )
        workflow = jobs["landing-image"]
        self.assertIn("images: ghcr.io/${{ github.repository }}-landing", workflow)
        self.assertIn("tags: tgstation-gateway-landing:release", workflow)
        self.assertIn("labels: ${{ steps.landing-meta.outputs.labels }}", workflow)
        self.assertIn("IMAGE_TAGS: ${{ steps.landing-meta.outputs.tags }}", workflow)
        smoke = workflow.index(
            "bash tests/smoke-landing.sh tgstation-gateway-landing:release"
        )
        login = workflow.index("name: Log in to GHCR")
        self.assertLess(workflow.index("name: Build release landing image"), smoke)
        self.assertLess(smoke, login)
        self.assertLess(
            login, workflow.index("docker tag tgstation-gateway-landing:release")
        )

    def test_cached_prefix_requires_selected_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        block = re.search(
            r"RUN --mount=type=bind,from=wine-prefix-cache,target=/tmp/wine-prefix-cache \\\n(.*?)(?:\n\n)",
            dockerfile,
            re.S,
        )[1].replace("\\\n", " ")
        for cached_version in ("10.0-3", "10.0-4", "11.22", None):
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
                        (source / ".gateway-proton-version").write_text(cached_version)
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
                            "WINE_PROTON_VERSION": "10.0-4",
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        result.returncode == 0,
                        cached_version == "10.0-4",
                        result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
