"""Exercise release archives, version consistency, and file inclusion boundaries."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        shutil.copytree(ROOT, self.project, ignore=shutil.ignore_patterns(
            "node_modules", "dist", "archive", "__pycache__", ".git", "history"))
        self.metadata = json.loads((self.project / "watcher/package.json").read_text())
        self.watcher = self.metadata["name"]
        self.control = "opencode-control" if self.watcher == "hermes-watch" else "codex-control"
        (self.project / "watcher/.env").write_text("private fixture")
        (self.project / "watcher/unrelated.ts").write_text("private fixture")
        cache = self.project / self.control / "__pycache__"
        cache.mkdir(exist_ok=True)
        (cache / "private.pyc").write_bytes(b"private fixture")

    def run_package(self, component):
        return subprocess.run([sys.executable, str(self.project / "scripts/package.py"), component],
                              cwd=self.project, capture_output=True, text=True,
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))

    def test_archives_contain_installable_sources_without_unrelated_files(self):
        for component in ("watcher", "control"):
            result = self.run_package(component)
            self.assertEqual(result.returncode, 0, result.stderr)
            name = self.watcher if component == "watcher" else self.control
            archives = list((self.project / "dist").glob(f"{name}-v*.zip"))
            self.assertEqual(len(archives), 1)
            folder = self.project / ("watcher" if component == "watcher" else self.control)
            expected = {"README.md", "CHANGELOG.md", "LICENSE"}
            if component == "watcher":
                expected |= {"package.json", f"{self.watcher}.ts"}
                if self.watcher == "codex-watch":
                    expected.add("codex-daemon.ts")
            else:
                expected |= {"__init__.py", "plugin.yaml"}
            with ZipFile(archives[0]) as archive:
                self.assertEqual(set(archive.namelist()), {f"{name}/{p}" for p in expected})
                for filename in expected:
                    source = self.project / "LICENSE" if filename == "LICENSE" else folder / filename
                    self.assertEqual(archive.read(f"{name}/{filename}"), source.read_bytes())

    def test_watcher_mismatch_does_not_create_release(self):
        manifest = self.project / "watcher/package.json"
        self.metadata["version"] = "99.0.0"
        manifest.write_text(json.dumps(self.metadata))
        result = self.run_package("watcher")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Versions", result.stderr)
        self.assertFalse(list((self.project / "dist").glob("*.zip")))
        self.assertEqual(self.run_package("control").returncode, 0)

    def test_control_mismatch_does_not_create_release(self):
        source = self.project / self.control / "__init__.py"
        source.write_text(re.sub(r"(PLUGIN_VERSION\s*=\s*['\"])[^'\"]+", r"\g<1>99.0.0",
                                 source.read_text(), count=1))
        result = self.run_package("control")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Versions", result.stderr)
        self.assertFalse(list((self.project / "dist").glob("*.zip")))
        self.assertEqual(self.run_package("watcher").returncode, 0)

    def test_rebuilding_same_sources_produces_identical_archive(self):
        result = self.run_package("watcher")
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = next((self.project / "dist").glob("*.zip"))
        original = archive.read_bytes()
        for path in (self.project / "watcher").glob("*"):
            os.utime(path, (1800000000, 1800000000))
        self.assertEqual(self.run_package("watcher").returncode, 0)
        self.assertEqual(archive.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
