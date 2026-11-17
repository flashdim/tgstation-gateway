import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DownloadWineTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.script = self.root / "download-wine.sh"
        self.script.write_text((ROOT / "container/download-wine.sh").read_text())
        self.manifest = self.root / "wine-proton.env"
        self.payload = self.root / "payload"
        self.payload.write_bytes(b"immutable wine archive")
        self.set_manifest("1", hashlib.sha256(self.payload.read_bytes()).hexdigest())
        self.bin = self.root / "bin"
        self.bin.mkdir()
        curl = self.bin / "curl"
        curl.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LOG"\n'
            'while [ "$1" != "-o" ]; do shift; done\ncp "$PAYLOAD" "$2"\n'
        )
        curl.chmod(0o755)
        self.log = self.root / "curl.log"
        self.cache = self.root / "cache"

    def set_manifest(self, version, checksum):
        self.manifest.write_text(
            f"WINE_PROTON_VERSION={version}\nWINE_PROTON_SHA256={checksum}\n"
        )

    def download(self, **extra_env):
        return subprocess.run(
            ["sh", str(self.script), str(self.cache)],
            env={
                **os.environ,
                "PATH": f"{self.bin}:{os.environ['PATH']}",
                "LOG": str(self.log),
                "PAYLOAD": str(self.payload),
                **extra_env,
            },
            capture_output=True,
            text=True,
        )

    def test_downloads_once_and_verifies_cache_hit(self):
        self.assertEqual(self.download().returncode, 0)
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Verifying cached", result.stdout)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        self.assertIn("proton-1/wine-proton-1-amd64.tar.xz", self.log.read_text())

    def test_rejects_bad_download_and_corrupt_cache(self):
        self.set_manifest("1", "0" * 64)
        self.assertNotEqual(self.download().returncode, 0)
        self.assertFalse((self.cache / "wine-proton.tar.xz").exists())
        (self.cache / "wine-proton.tar.xz").write_bytes(b"corrupt")
        self.assertNotEqual(self.download().returncode, 0)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)

    def test_selects_each_pinned_artifact(self):
        self.manifest.write_text((ROOT / "container/wine-proton.env").read_text())
        for version, checksum in (
            (
                "10.0-4",
                "ffaf6e766f916a408d273254f6b9c42b1589ac1bb4b02e09ab04650c87bca290",
            ),
            (
                "11.0-2",
                "51e1b54068c242c0a59c329674afe4b0ae03d313516a535be4acd1c5f3277e9b",
            ),
        ):
            with self.subTest(version=version):
                result = subprocess.run(
                    [
                        "sh",
                        "-c",
                        '. "$1"; printf "%s %s" "$WINE_PROTON_VERSION" "$WINE_PROTON_SHA256"',
                        "sh",
                        str(self.manifest),
                    ],
                    env={**os.environ, "WINE_PROTON_VERSION": version},
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, f"{version} {checksum}")
                result = self.download(WINE_PROTON_VERSION=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"proton-{version}/wine-proton-{version}-amd64.tar.xz",
                    self.log.read_text(),
                )
                self.assertFalse((self.cache / "wine-proton.tar.xz").exists())

    def test_rejects_unknown_runtime_before_download(self):
        self.manifest.write_text((ROOT / "container/wine-proton.env").read_text())
        result = self.download(WINE_PROTON_VERSION="../../unknown")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsupported WINE_PROTON_VERSION", result.stderr)
        self.assertFalse(self.log.exists())

    def test_rejects_retired_runtimes_before_download(self):
        self.manifest.write_text((ROOT / "container/wine-proton.env").read_text())
        for version in ("8.0-5", "9.0-4"):
            with self.subTest(version=version):
                result = self.download(WINE_PROTON_VERSION=version)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Unsupported WINE_PROTON_VERSION", result.stderr)
                self.assertFalse(self.log.exists())

    def test_workflows_key_download_and_prefix_on_manifest(self):
        for workflow in ("ci.yml", "publish.yml"):
            content = (ROOT / ".github/workflows" / workflow).read_text()
            self.assertIn(
                "wine-download-v1-${{ hashFiles('container/wine-proton.env') }}",
                content,
            )
            self.assertIn(
                "'container/wine-proton.env', 'container/download-wine.sh'", content
            )
            self.assertIn(
                "wine-download-cache=${{ runner.temp }}/wine-download-cache", content
            )

    def test_release_workflow_saves_download_cache_on_miss(self):
        content = (ROOT / ".github/workflows/publish.yml").read_text()
        self.assertIn("if: steps.wine-download.outputs.cache-hit != 'true'", content)
        self.assertIn(
            "key: ${{ steps.wine-download.outputs.cache-primary-key }}", content
        )
        self.assertIn(
            "uses: actions/cache/save@0057852bfaa89a56745cba8c7296529d2fc39830 # v4",
            content,
        )


if __name__ == "__main__":
    unittest.main()
