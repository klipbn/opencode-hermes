"""Exercise the publication language check against an isolated real Git index."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_language.py"


class LanguageCheckTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), "The publication language checker must exist")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "scripts").mkdir()
        self.script = self.root / "scripts/check_language.py"
        shutil.copy2(SCRIPT, self.script)

    def stage(self, *paths):
        subprocess.run(["git", "-C", str(self.root), "add", *paths], check=True)

    def check(self):
        return subprocess.run([sys.executable, str(self.script)], cwd=self.root,
                              capture_output=True, text=True)

    def test_rejects_untranslated_tracked_text_without_echoing_contents(self):
        text = chr(0x0410) + chr(0x0411)
        (self.root / "README.md").write_text("# " + text)
        self.stage("README.md")
        result = self.check()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("README.md:1", result.stderr)
        self.assertNotIn(text, result.stderr)

    def test_accepts_english_text_and_unicode_escapes(self):
        (self.root / "example.py").write_text('# English comment\nvalue = "\\u0410"\n')
        self.stage("example.py")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ignores_untracked_local_archive_and_binary_preview(self):
        (self.root / ".gitignore").write_text("archive/\n")
        (self.root / "archive").mkdir()
        (self.root / "archive/original.md").write_text(chr(0x0410))
        (self.root / "preview.png").write_bytes(b"\x89PNG\x00\xff")
        self.stage(".gitignore", "preview.png")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
