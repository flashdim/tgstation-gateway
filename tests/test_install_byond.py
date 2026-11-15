import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


class InstallByondTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        curl = self.bin / "curl"
        curl.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$4" > "$URL_FILE"\ncp "$FIXTURE" "$6"\n'
        )
        curl.chmod(0o755)
        self.fixture = self.root / "fixture.zip"
        self.url_file = self.root / "url"
        self.prefix = self.root / "prefix"

    def make_archive(self, path="byond/bin/byond.exe"):
        with zipfile.ZipFile(self.fixture, "w") as archive:
            archive.writestr(path, b"BYOND fixture")
            archive.writestr("byond/bin/byondcore.dll", b"fixture DLL")

    def install(self, version="516.1688", checksum="", base_url=None):
        env = {
            **os.environ,
            "BYOND_VERSION": version,
            "BYOND_SHA256": checksum,
            "WINEPREFIX": str(self.prefix),
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "FIXTURE": str(self.fixture),
            "URL_FILE": str(self.url_file),
        }
        env.pop("BYOND_DOWNLOAD_BASE_URL", None)
        if base_url is not None:
            env["BYOND_DOWNLOAD_BASE_URL"] = base_url
        return subprocess.run(
            ["sh", str(ROOT / "container/install-byond.sh")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_extracts_requested_version_to_wine_prefix(self):
        self.make_archive()
        digest = hashlib.sha256(self.fixture.read_bytes()).hexdigest()
        result = self.install("517.1701", digest)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.url_file.read_text().strip(),
            "https://byond-builds.dm-lang.org/517/517.1701_byond.zip",
        )
        byond = self.prefix / "drive_c/Program Files (x86)/BYOND/bin"
        self.assertEqual((byond / "byond.exe").read_bytes(), b"BYOND fixture")
        self.assertTrue((byond / "byondcore.dll").is_file())

    def test_ignores_legacy_download_base_override(self):
        self.make_archive()
        result = self.install(base_url="https://example.org")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.url_file.read_text().strip(),
            "https://byond-builds.dm-lang.org/516/516.1688_byond.zip",
        )
        self.assertTrue(
            (self.prefix / "drive_c/Program Files (x86)/BYOND/bin/byond.exe").is_file()
        )

    def test_rejects_invalid_versions_before_downloading(self):
        for version in ("516", "516.", ".1688", "516.1688.1", "516:1.1688", "../x"):
            with self.subTest(version=version):
                result = self.install(version)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid BYOND_VERSION", result.stderr)
                self.assertFalse(self.url_file.exists())

    def test_rejects_checksum_mismatch(self):
        self.make_archive()
        result = self.install(checksum="0" * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.prefix.exists())

    def test_rejects_unexpected_archive_layout(self):
        self.make_archive("not-byond/bin/byond.exe")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing byond/bin/byond.exe", result.stderr)
        self.assertFalse(self.prefix.exists())

    def test_rejects_corrupted_archive(self):
        self.fixture.write_bytes(b"not a zip file")
        result = self.install()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.prefix.exists())


if __name__ == "__main__":
    unittest.main()
