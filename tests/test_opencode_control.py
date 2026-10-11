"""Control commands read real isolated state and never invoke delivery."""

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve().parents[1] / "opencode-control" / "__init__.py"


class ControlEnglishTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        spec = importlib.util.spec_from_file_location("opencode_control_test", SOURCE)
        self.control = importlib.util.module_from_spec(spec)
        with patch.dict("os.environ", {"OPENCODE_HERMES_BASE_DIR": self.directory.name}):
            spec.loader.exec_module(self.control)
        self.control.STATE_DIR.mkdir(parents=True)
        self.control.INSTANCE_DIR.mkdir(parents=True)
        # Fail immediately if a tested command starts a process or sends a message.
        self.process_guard = patch.object(self.control.subprocess, "run", side_effect=AssertionError("No subprocesses in state command tests"))
        self.process_guard.start()
        self.addCleanup(self.process_guard.stop)

    def save_state(self):
        now = datetime.now(timezone.utc).isoformat()
        title = "\u0417\u0430\u0434\u0430\u0447\u0430"
        summary = "\u0413\u043e\u0442\u043e\u0432\u043e <done> & checked"
        state = {
            "sessionID": "session-demo", "title": title, "lastSummary": summary,
            "project": "example", "directory": "/tmp/example", "status": "idle",
            "updatedAt": now, "tests": [],
            "sessionDiff": {"available": True, "filesCount": 1, "additions": 3, "deletions": 1,
                            "files": [{"file": "src/example.py", "status": "modified"}], "scope": "turn"},
            "turns": [{"finishedAt": now, "durationSeconds": 65, "outcome": "done", "cost": 0.25,
                       "filesCount": 1, "additions": 3, "deletions": 1}],
        }
        (self.control.STATE_DIR / "session-demo.json").write_text(json.dumps(state), encoding="utf-8")
        return title, summary

    def test_help_exposes_english_commands_and_target_hints(self):
        help_text = self.control.handle_ochelp("")
        self.assertIn("/oc [number|session_id|all]", help_text)
        self.assertIn("Mute watcher notifications", help_text)
        self.assertIn("[minutes|off|types]", help_text)
        self.assertNotRegex(help_text, "[\u0400-\u04ff]")

    def test_empty_and_corrupt_state_commands_degrade_in_english(self):
        (self.control.STATE_DIR / "broken.json").write_text("{broken", encoding="utf-8")
        (self.control.STATE_DIR / "list.json").write_text("[]", encoding="utf-8")
        self.assertIn("No live OpenCode windows", self.control.handle_oc(""))
        self.assertIn("No completed turns", self.control.handle_ocstats("21"))
        self.assertIn("21 days", self.control.handle_ocstats("21"))
        self.assertIn("not found", self.control.handle_oc("missing"))
        self.assertEqual(self.control.handle_oc("all"), self.control.handle_oc("\u0432\u0441\u0435"))

    def test_saved_state_preserves_user_unicode_and_displays_english_labels(self):
        title, summary = self.save_state()
        result = self.control.handle_ocsum("session-demo")
        self.assertIn(title, result)
        self.assertIn(summary, result)
        self.assertIn("Tests: not run", result)
        self.assertIn("src/example.py", self.control.handle_ocdiff("session-demo"))
        self.assertIn("Turns: 1", self.control.handle_ocstats("1"))
        self.assertIn("1 day", self.control.handle_ocstats("1"))
        self.assertIn(title, self.control.handle_ocfind(title))

    def test_english_pluralization_handles_twenty_one_and_zero(self):
        for count, expected in [(0, "hours"), (1, "hour"), (2, "hours"), (11, "hours"), (21, "hours")]:
            with self.subTest(count=count):
                self.assertEqual(self.control.plural_ru(count, "hour", "hours", "hours"), expected)

    def test_mute_writes_only_isolated_control_and_uses_english_units(self):
        for minutes, phrase in [(1, "1 minute"), (21, "21 minutes")]:
            with self.subTest(minutes=minutes):
                self.assertIn(phrase, self.control.handle_ocmute(str(minutes)))
                saved = json.loads(self.control.CONTROL_PATH.read_text(encoding="utf-8"))
                self.assertIn("muteUntil", saved)
        self.assertIn("Disabled notifications: done, retry", self.control.handle_ocmute("retry done"))
        saved = json.loads(self.control.CONTROL_PATH.read_text(encoding="utf-8"))
        self.assertEqual(saved["disabledLevels"], ["done", "retry"])
        self.assertIn("All notifications enabled", self.control.handle_ocmute("off"))
        saved = json.loads(self.control.CONTROL_PATH.read_text(encoding="utf-8"))
        self.assertNotIn("muteUntil", saved)
        self.assertNotIn("disabledLevels", saved)

    def test_one_process_remains_one_window_with_all_session_statuses(self):
        collapsed = self.control.collapse_instances_by_pid({
            "empty": {"pid": 42, "statuses": {"old": {"type": "idle"}}},
            "current": {"pid": 42, "currentSessionID": "session-demo", "statuses": {"session-demo": {"type": "busy"}}},
        })
        self.assertEqual(len(collapsed), 1)
        instance = next(iter(collapsed.values()))
        self.assertEqual(instance["currentSessionID"], "session-demo")
        self.assertEqual(set(instance["statuses"]), {"old", "session-demo"})


if __name__ == "__main__":
    unittest.main()
