import datetime
import hashlib
from pathlib import Path
import tempfile
import unittest

import release

SHA = "e282f11816cd" + "0" * 28
COMMITTED = datetime.datetime(2026, 10, 4, 6, 23, 0, tzinfo=datetime.timezone.utc)


class VersionTest(unittest.TestCase):
    def test_nightly_uses_commit_time_and_drops_prerelease_suffix(self):
        self.assertEqual(release.nightly_version("0.1.0", SHA, COMMITTED), "0.1.0-nightly.20261004062300.ge282f11816cd")
        self.assertEqual(release.nightly_version("0.2.0-beta.1", SHA, COMMITTED),
                         "0.2.0-nightly.20261004062300.ge282f11816cd")

    def test_nightly_converts_to_utc(self):
        local = COMMITTED.astimezone(datetime.timezone(datetime.timedelta(hours=-5)))
        self.assertEqual(release.nightly_version("0.1.0", SHA, local), "0.1.0-nightly.20261004062300.ge282f11816cd")

    def test_rejects_unknown_base_versions(self):
        for base in ("0.1", "0.1.0-alpha.0.1", "0.1.0-nightly.1", "v0.1.0"):
            with self.assertRaises(ValueError):
                release.nightly_version(base, SHA, COMMITTED)
            with self.assertRaises(ValueError):
                release.release_version(base, "")

    def test_release_tag_must_match(self):
        self.assertEqual(release.release_version("0.1.0-beta.1", "refs/tags/v0.1.0-beta.1"), "0.1.0-beta.1")
        self.assertEqual(release.release_version("0.1.0", "refs/heads/main"), "0.1.0")
        with self.assertRaises(ValueError):
            release.release_version("0.1.0", "refs/tags/v0.1.1")


class RegistryEntryTest(unittest.TestCase):
    def test_describes_archives_with_verified_checksums(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = directory / "chunk-0.1.0-linux-x64.tar.gz"
            archive.write_bytes(b"archive")
            digest = hashlib.sha256(b"archive").hexdigest()
            archive.with_name(archive.name + ".sha256").write_text(f"{digest}  {archive.name}\n")
            entry = release.registry_entry("chunk", "0.1.0", "chunkzero/chunk", directory)
        self.assertEqual(entry, {
            "version": "0.1.0",
            "tag": "v0.1.0",
            "assets": {"linux-x64": {
                "url": "https://github.com/chunkzero/chunk/releases/download/v0.1.0/chunk-0.1.0-linux-x64.tar.gz",
                "sha256": digest,
            }},
        })

    def test_rejects_mismatched_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive = directory / "chunk-0.1.0-linux-x64.tar.gz"
            archive.write_bytes(b"archive")
            archive.with_name(archive.name + ".sha256").write_text("0" * 64 + "\n")
            with self.assertRaises(ValueError):
                release.registry_entry("chunk", "0.1.0", "chunkzero/chunk", directory)


if __name__ == "__main__":
    unittest.main()
