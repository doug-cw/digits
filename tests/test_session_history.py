"""Tests for plugin/skills/self-improve/session_history.py on invented transcripts."""

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "plugin" / "skills" / "self-improve" / "session_history.py"
SKILLS = ROOT / "plugin" / "skills"

spec = importlib.util.spec_from_file_location("digits_session_history_under_test", HELPER)
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)

ENV_A = "/srv/envs/left_pinky"
ENV_A2 = "/srv/envs/left_pinky2"  # slug-prefix neighbour of ENV_A
ENV_B = "/srv/envs/right_ring"


def user(stamp, text, cwd, **extra):
    record = {"type": "user", "timestamp": stamp, "cwd": cwd,
              "message": {"role": "user", "content": text}, "origin": {"kind": "human"}}
    record.update(extra)
    return record


def assistant(stamp, text, cwd, **extra):
    record = {"type": "assistant", "timestamp": stamp, "cwd": cwd,
              "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}
    record.update(extra)
    return record


class SessionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = Path(self.tmp.name) / "projects"
        self.projects.mkdir()
        a = ENV_A
        self.write(a, "aaaa0001", [
            {"type": "permission-mode", "permissionMode": "default", "sessionId": "aaaa0001"},
            user("2026-03-02T09:00:00Z", "Please fix the widget parser", a),
            assistant("2026-03-02T09:00:05Z", "", a, message={"content": [{"type": "thinking", "thinking": "x"}]}),
            {"type": "assistant", "timestamp": "2026-03-02T09:00:06Z", "cwd": a,
             "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
            user("2026-03-02T09:00:07Z", None, a, origin=None,
                 message={"content": [{"type": "tool_result", "content": "secret tool output"}]}),
            assistant("2026-03-02T09:01:00Z", "Fixed the widget parser; tests pass.", a),
            user("2026-03-02T09:02:00Z", "<system-reminder>injected</system-reminder>No, that was wrong: revert it", a),
            user("2026-03-02T09:02:30Z", "peer says hello", a, isMeta=True, origin={"kind": "peer", "from": "x"}),
            user("2026-03-02T09:02:40Z", "task finished", a, origin={"kind": "task-notification"}),
            user("2026-03-02T09:02:50Z", "summary of earlier conversation", a, isCompactSummary=True),
            user("2026-03-02T09:02:55Z", "sub-agent prompt", a, isSidechain=True),
            user("2026-03-02T09:02:58Z", "<local-command-stdout>ok</local-command-stdout>", a, origin=None),
            {"type": "ai-title", "aiTitle": "Widget parser fix", "sessionId": "aaaa0001"},
            {"type": "custom-title", "customTitle": "WID-7 parser", "sessionId": "aaaa0001"},
            assistant("2026-03-02T09:03:00Z", "Reverted. " + "x" * 50, a + "/work"),
        ])
        # Started in a subfolder of ENV_A: still that environment.
        self.write(a + "/work", "aaaa0002", [
            user("2026-03-05T12:00:00+02:00", "Draft my standup", a + "/work"),
            assistant("2026-03-05T10:00:10Z", "**Progress:** widget parser merged", a + "/work"),
        ])
        self.write(ENV_A2, "cccc0001", [
            user("2026-03-04T08:00:00Z", "neighbour folder widget", ENV_A2),
        ])
        self.write(ENV_B, "bbbb0001", [
            user("2026-02-20T08:00:00Z", "old widget question", ENV_B),
            assistant("2026-02-20T08:00:30Z", "old answer", ENV_B),
        ])
        # A sub-agent transcript nested under a session folder is not a session.
        nested = self.projects / history.slug(ENV_B) / "bbbb0001" / "subagents"
        nested.mkdir(parents=True)
        (nested / "agent-1.jsonl").write_text(
            json.dumps(user("2026-03-06T08:00:00Z", "nested widget", ENV_B)) + "\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, cwd, session_id, entries):
        folder = self.projects / history.slug(cwd)
        folder.mkdir(exist_ok=True)
        lines = [json.dumps(e) for e in entries]
        lines.insert(1, "{not json")
        (folder / f"{session_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = history.main(["--projects-dir", str(self.projects), *argv])
        return code, (json.loads(out.getvalue()) if code == 0 else None), err.getvalue()

    def test_slug_matches_claude_code_rule(self):
        self.assertEqual(history.slug("/srv/a.b/x_y/c-d"), "-srv-a-b-x-y-c-d")

    def test_sessions_by_root_include_subfolder_starts_and_exclude_prefix_neighbours(self):
        code, result, _ = self.run_cli("sessions", "--root", ENV_A)
        self.assertEqual(code, 0)
        self.assertEqual([s["session_id"] for s in result["items"]], ["aaaa0002", "aaaa0001"])
        first = result["items"][1]
        self.assertEqual(first["title"], "WID-7 parser")
        self.assertEqual((first["created"], first["updated"]), ("2026-03-02T09:00:00Z", "2026-03-02T09:03:00Z"))
        self.assertEqual((first["user_turns"], first["assistant_turns"]), (2, 2))
        self.assertEqual(set(first), {"session_id", "cwd", "title", "created", "updated",
                                      "user_turns", "assistant_turns"})

    def test_sessions_window_and_paging(self):
        code, result, _ = self.run_cli("sessions", "--since", "2026-03-01", "--until", "2026-03-04")
        self.assertEqual([s["session_id"] for s in result["items"]], ["cccc0001", "aaaa0001"])
        code, result, _ = self.run_cli("sessions", "--limit", "2")
        self.assertEqual((result["total"], result["next_offset"]), (4, 2))
        code, rest, _ = self.run_cli("sessions", "--limit", "2", "--offset", "2")
        self.assertEqual([s["session_id"] for s in rest["items"]], ["aaaa0001", "bbbb0001"])
        self.assertIsNone(rest["next_offset"])

    def test_user_turns_exclude_tools_meta_peers_and_reminders(self):
        code, result, _ = self.run_cli("turns", "--root", ENV_A, "--role", "user", "--order", "oldest")
        texts = [t["text"] for t in result["items"]]
        self.assertEqual(texts, ["Please fix the widget parser", "No, that was wrong: revert it",
                                 "Draft my standup"])
        self.assertEqual(result["items"][2]["timestamp"], "2026-03-05T10:00:00Z")
        self.assertNotIn("secret tool output", json.dumps(result))

    def test_grep_across_environments_newest_first_and_skips_nested(self):
        code, result, _ = self.run_cli("turns", "--grep", "WIDGET", "--grep", "nothing-matches")
        self.assertEqual([(t["session_id"], t["role"]) for t in result["items"]], [
            ("aaaa0002", "assistant"), ("cccc0001", "user"), ("aaaa0001", "assistant"),
            ("aaaa0001", "user"), ("bbbb0001", "user")])

    def test_session_filter_truncation_and_time_window(self):
        code, result, _ = self.run_cli("turns", "--session", "aaaa0001", "--role", "assistant",
                                       "--since", "2026-03-02T09:02:00Z", "--max-chars", "12")
        self.assertEqual(result["items"], [{
            "session_id": "aaaa0001", "cwd": ENV_A + "/work", "timestamp": "2026-03-02T09:03:00Z",
            "role": "assistant", "text": "Reverted. xx", "truncated": True}])

    def test_old_files_are_skipped_by_mtime(self):
        old = self.projects / history.slug(ENV_B) / "bbbb0001.jsonl"
        stamp = time.mktime((2026, 1, 1, 0, 0, 0, 0, 0, 0))
        os.utime(old, (stamp, stamp))
        self.assertEqual(list(history.transcripts(self.projects, [ENV_B], history.parse_time("2026-02-01"))), [])

    def test_limits_and_bad_input_are_refused(self):
        for argv in (("turns", "--limit", "201"), ("turns", "--max-chars", "4001"), ("sessions", "--offset", "-1")):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                history.main(["--projects-dir", str(self.projects), *argv])
        code, _, err = self.run_cli("turns", "--since", "yesterday")
        self.assertEqual(code, 1)
        self.assertIn("Session history:", err)

    def test_missing_projects_dir_is_empty(self):
        code, result, _ = self.run_cli("--projects-dir", str(self.projects / "absent"), "sessions")
        self.assertEqual((code, result["total"]), (0, 0))

    def test_runs_as_a_script(self):
        done = subprocess.run([sys.executable, str(HELPER), "--projects-dir", str(self.projects),
                               "turns", "--root", ENV_B, "--limit", "1"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout)["items"][0]["text"], "old answer")


class SkillWiringTests(unittest.TestCase):
    """Each skill that reads chat history names both hosts' tools."""

    def test_skills_point_claude_code_at_the_helper(self):
        for name in ("investigate", "self-improve", "standup-update"):
            with self.subTest(skill=name):
                text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
                for phrase in ("session_store_sql", "session_history.py", "Claude Code"):
                    self.assertTrue(phrase in text, f"{name} lacks {phrase}")


if __name__ == "__main__":
    unittest.main()
