import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import re


ROOT = Path(__file__).resolve().parents[1]


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
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        jobs = dict(
            re.findall(r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:|\Z)", workflow, re.M | re.S)
        )
        for job in ("unit-tests", "image"):
            with self.subTest(job=job):
                self.assertEqual(
                    re.findall(r"^    needs: (.+)$", jobs[job], re.M), ["formatting"]
                )
        command = "python3 -m unittest discover -s tests -v"
        self.assertIn(command, jobs["unit-tests"])
        self.assertNotIn(command, jobs["image"])

    def test_ci_publishes_dev_image_before_container_validation(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        publish = workflow.index("name: Publish development image")
        self.assertLess(workflow.index("name: Build player image"), publish)
        for validation in (
            "name: Validate Compose example",
            "name: Smoke-test player image",
            "name: Smoke-test Wayland session",
            "tests/check-wine-runtime.sh",
        ):
            with self.subTest(validation=validation):
                self.assertLess(publish, workflow.index(validation))

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
