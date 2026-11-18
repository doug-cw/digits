"""Tests for claude/bin/digits-claude, the Claude Code launch command (spec 10 section 5a)."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import install  # noqa: E402

SCRIPT = ROOT / "claude" / "bin" / "digits-claude"


class DigitsClaudeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name).resolve()
        self.home = self.tmp / "home"
        self.home.mkdir()
        # A stand-in for claude that prints each argument on its own line.
        self.fake = self.tmp / "fake-claude"
        self.fake.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n')
        self.fake.chmod(0o755)

    def run_in(self, cwd, *args, **env):
        environ = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.home),
                   "DIGITS_CLAUDE": str(self.fake)}
        environ.update(env)
        result = subprocess.run(["/bin/sh", str(SCRIPT)] + list(args), cwd=str(cwd), env=environ,
                                capture_output=True, text=True, timeout=10)
        return result.returncode, result.stdout.splitlines(), result.stderr

    def test_names_every_environment_and_passes_arguments_on(self):
        for environment in install.ENVIRONMENTS:
            folder = self.home / environment / "repo" / "src"
            folder.mkdir(parents=True)
            code, argv, err = self.run_in(folder, "--continue", "two words")
            self.assertEqual(code, 0, err)
            self.assertEqual(argv, ["-n", environment.replace("_", "-"), "--continue", "two words"])

    def test_no_name_outside_an_environment(self):
        for folder in (self.home, self.home / "left_pinky_old", self.home / "Code" / "left_pinky", self.tmp):
            folder.mkdir(parents=True, exist_ok=True)
            code, argv, err = self.run_in(folder, "-p", "hi")
            self.assertEqual(code, 0, err)
            self.assertEqual(argv, ["-p", "hi"], folder)

    def test_plugin_dir(self):
        folder = self.home / "left_thumb"
        folder.mkdir()
        plugin = self.tmp / "plugin"
        (plugin / ".claude-plugin").mkdir(parents=True)
        (plugin / ".claude-plugin" / "plugin.json").write_text("{}")
        code, argv, err = self.run_in(folder, "-c", DIGITS_PLUGIN_DIR=str(plugin))
        self.assertEqual(code, 0, err)
        self.assertEqual(argv, ["--plugin-dir", str(plugin), "-n", "left-thumb", "-c"])
        code, argv, err = self.run_in(folder, DIGITS_PLUGIN_DIR=str(self.tmp / "missing"))
        self.assertEqual((code, argv), (1, []))
        self.assertIn("DIGITS_PLUGIN_DIR", err)

    def test_repository_plugin_has_a_claude_manifest(self):
        self.assertTrue((ROOT / "plugin" / ".claude-plugin" / "plugin.json").is_file())

    def test_environment_list_matches_installer(self):
        text = SCRIPT.read_text()
        for environment in install.ENVIRONMENTS:
            self.assertIn(environment, text)
        self.assertEqual(text.count("left_") + text.count("right_"), len(install.ENVIRONMENTS))

    def test_executable(self):
        self.assertEqual(SCRIPT.stat().st_mode & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()
