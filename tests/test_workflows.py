import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import re


ROOT = Path(__file__).resolve().parents[1]


class WorkflowTest(unittest.TestCase):
    def test_ci_and_release_publish_the_smoke_tested_player_image(self):
        for filename, tag in (("ci.yml", "ci"), ("publish.yml", "release")):
            with self.subTest(workflow=filename):
                workflow = (ROOT / ".github/workflows" / filename).read_text()
                self.assertIn("key: wine-prefix-v5-ge-proton-", workflow)
                self.assertIn("ge-proton-download-v1-", workflow)
                self.assertIn(
                    "steps.ge-proton-version.outputs.version }}.tar.gz", workflow
                )
                self.assertNotIn("GE-Proton10-34.tar.gz", workflow)
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

    def test_cached_prefix_requires_selected_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        block = re.search(
            r"RUN --mount=type=bind,from=wine-prefix-cache,target=/tmp/wine-prefix-cache \\\n(.*?)(?:\n\n)",
            dockerfile,
            re.S,
        )[1].replace("\\\n", " ")
        for cached_version in (
            "GE-Proton10-33",
            "GE-Proton10-34",
            "GE-Proton11-2",
            None,
        ):
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
                        (source / ".gateway-ge-proton-version").write_text(
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
                            "GE_PROTON_VERSION": "GE-Proton10-34",
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        result.returncode == 0,
                        cached_version == "GE-Proton10-34",
                        result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
