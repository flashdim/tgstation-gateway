import os
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class UatTest(unittest.TestCase):
    def test_matrix_has_separate_immutable_tags_and_mode_checks(self):
        workflow = (ROOT / ".github/workflows/uat.yml").read_text()
        self.assertIn("  workflow_dispatch:", workflow)
        self.assertNotIn("  pull_request:", workflow)
        self.assertNotIn("  release:", workflow)
        self.assertIn("fail-fast: false", workflow)
        self.assertIn("proton: [10.0-4, 11.0-2]", workflow)
        self.assertIn("display: [x11, wayland]", workflow)
        self.assertIn(
            ":uat-issue-7-${{ github.sha }}-proton-${{ matrix.proton }}-${{ matrix.display }}",
            workflow,
        )
        self.assertIn("WINE_PROTON_VERSION=${{ matrix.proton }}", workflow)
        self.assertIn("SELKIES_WAYLAND=${{ env.SELKIES_WAYLAND }}", workflow)
        self.assertIn('grep -Fx "wayland=$SELKIES_WAYLAND"', workflow)
        for mode in ("container", "wayland"):
            self.assertIn(f"bash tests/smoke-{mode}.sh", workflow)
        self.assertLess(
            workflow.index("name: Smoke-test tagged display mode"),
            workflow.index('docker push "$IMAGE"'),
        )
        self.assertIn(
            "Refusing to overwrite an existing commit-specific UAT tag", workflow
        )
        self.assertIn("Cannot establish tag absence; refusing publication", workflow)
        self.assertIn('docker pull "$reference"', workflow)
        self.assertIn("published-digest.txt", workflow)
        self.assertNotIn(":latest", workflow)
        self.assertNotIn(":dev", workflow)

    def test_caches_include_selected_runtime_and_prefix_inputs(self):
        workflow = (ROOT / ".github/workflows/uat.yml").read_text()
        self.assertIn(
            "key: uat-wine-download-v1-${{ matrix.proton }}-${{ hashFiles('container/wine-proton.env', 'container/download-wine.sh') }}",
            workflow,
        )
        self.assertIn(
            "key: uat-wine-prefix-v1-${{ matrix.proton }}-${{ matrix.display }}-",
            workflow,
        )
        for source in (
            "Dockerfile",
            "wine-proton.env",
            "download-wine.sh",
            "install-client.sh",
            "install-byond.sh",
            "install-graphics.sh",
        ):
            self.assertIn(source, workflow)

    def test_cached_prefix_requires_selected_runtime(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        block = re.search(
            r"RUN --mount=type=bind,from=wine-prefix-cache,target=/tmp/wine-prefix-cache \\\n(.*?)(?:\n\n)",
            dockerfile,
            re.S,
        )[1].replace("\\\n", " ")
        for cached_version in ("10.0-4", "11.0-2", None):
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
                            "WINE_PROTON_VERSION": "11.0-2",
                        },
                        capture_output=True,
                        text=True,
                    )
                    self.assertEqual(
                        result.returncode == 0,
                        cached_version == "11.0-2",
                        result.stderr,
                    )


if __name__ == "__main__":
    unittest.main()
