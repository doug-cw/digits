"""Tests for the self-improve checkpoint helper and the plugin package rules."""

import contextlib
import datetime
import importlib.util
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugin"
SKILLS = PLUGIN / "skills"
SELF_IMPROVE = SKILLS / "self-improve"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


checkpoint = load_module("digits_checkpoint_under_test", SELF_IMPROVE / "checkpoint.py")

ENVIRONMENTS = [
    "left_pinky", "left_ring", "left_middle", "left_pointer", "left_thumb",
    "right_thumb", "right_pointer", "right_middle", "right_ring", "right_pinky",
]
NOW = datetime.datetime(2026, 11, 6, 22, 0, tzinfo=datetime.timezone.utc)
SINCE = NOW - datetime.timedelta(days=2)


def frontmatter(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return None, lines
    end = lines.index("---", 1)
    keys = []
    for line in lines[1:end]:
        match = re.match(r"([A-Za-z0-9_-]+):\s*(.*)$", line)
        if match:
            keys.append((match.group(1), match.group(2)))
        else:
            keys.append((None, line))
    return keys, lines[end + 1:]


class CheckpointBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home"
        self.home.mkdir()
        self.files = self.base / "artifacts"
        self.files.mkdir()
        self.evidence = self.write("evidence.md", "Reviewed everything up to the baseline.\n")
        self.readable = self.write("report.md", "# Review\n\nExecutive summary: nothing to change.\n")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, text):
        path = self.files / name
        path.write_text(text, encoding="utf-8")
        return path

    def write_json(self, name, value):
        return self.write(name, json.dumps(value, indent=2))

    def state_file(self):
        return self.home / checkpoint.STATE

    def op(self, action, now=NOW, **args):
        return checkpoint.operate(self.home, action, now=now, **args)

    def initialize(self):
        return self.op("initialize", since=checkpoint.iso(SINCE), evidence=str(self.evidence))


class ContextBase(CheckpointBase):
    """Installs the real context library into the temporary home."""

    def setUp(self):
        super().setUp()
        self.installer = load_module("digits_context_install_for_checkpoint", ROOT / "context_install.py")
        import install

        install.execute(self.home, self.installer.make_plan(self.home))
        self.entry = self.home / self.installer.ENTRY
        self.initialize()
        self.run = self.op("begin", owner="owning-session", harness_root=str(ROOT))["active"]

    def proposal(self, name="proposal.json", changes=None, **overrides):
        value = {
            "run_id": self.run["run_id"],
            "reviewed_since": self.run["reviewed_since"],
            "reviewed_through": self.run["reviewed_through"],
            "coverage": {
                "environments": list(ENVIRONMENTS),
                "local": "complete",
                "cloud": "lagging",
                "material_gaps": [],
                "sessions_considered": 4,
                "turns_considered": 37,
            },
            "themes": [],
            "changes": changes or [],
            "deferred": [],
            "readable_report": str(self.readable),
        }
        for key, val in overrides.items():
            if key in value["coverage"]:
                value["coverage"][key] = val
            else:
                value[key] = val
        return self.write_json(name, value)

    def approve(self, proposal, now=NOW):
        return self.op("approve", now=now, run_id=self.run["run_id"], proposal=str(proposal),
                       approval_ref="owning-session/turn-12")

    def completion(self, sha, outcome="no_change", checks=None, name="completion.json", run_id=None):
        return self.write_json(name, {
            "run_id": run_id or self.run["run_id"],
            "proposal_sha256": sha,
            "outcome": outcome,
            "checks": checks if checks is not None else [
                {"command": "python3 -m unittest discover -s tests", "result": "passed", "evidence": "OK (120 tests)"}
            ],
            "summary": "Reviewed the window; nothing needed changing.",
        })

    def finish(self, report, now=NOW + datetime.timedelta(hours=5)):
        return self.op("finish", now=now, run_id=self.run["run_id"], report=str(report))

    def stored(self):
        return checkpoint.read_state(self.home)


class StatusAndBaselineTests(CheckpointBase):
    def test_status_is_read_only(self):
        self.assertEqual(self.op("status"), {"initialized": False})
        self.assertFalse((self.home / ".local").exists())
        with self.assertRaisesRegex(ValueError, "Initialize"):
            self.op("begin", owner="owning-session", harness_root=str(ROOT))
        self.assertFalse(self.state_file().exists())

    def test_baseline(self):
        state = self.initialize()
        self.assertIsNone(state["last_success"])
        self.assertIsNone(state["active"])
        self.assertEqual(state["baseline"]["reviewed_through"], checkpoint.iso(SINCE))
        self.assertEqual(state["baseline"]["evidence"]["path"], str(self.evidence))
        with self.assertRaisesRegex(ValueError, "already initialized"):
            self.initialize()
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            checkpoint.timestamp("2026-11-04T22:00:00")
        self.assertEqual(checkpoint.iso(checkpoint.timestamp("2026-11-04T23:00:00+01:00")),
                         "2026-11-04T22:00:00.000000Z")
        self.assertEqual(stat.S_IMODE(os.stat(self.state_file()).st_mode), 0o600)

    def test_bad_baseline(self):
        with self.assertRaisesRegex(ValueError, "future"):
            self.op("initialize", since=checkpoint.iso(NOW + datetime.timedelta(minutes=1)), evidence=str(self.evidence))
        with self.assertRaisesRegex(ValueError, "Missing evidence"):
            self.op("initialize", since=checkpoint.iso(SINCE), evidence=str(self.files / "absent.md"))
        with self.assertRaisesRegex(ValueError, "UTC offset"):
            self.op("initialize", since="2026-11-04T22:00:00", evidence=str(self.evidence))
        self.assertFalse(self.state_file().exists())

    def test_symlinks_are_refused(self):
        target = self.base / "elsewhere"
        target.mkdir()
        (self.home / ".local").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.initialize()
        self.assertEqual(list(target.iterdir()), [])
        link = self.files / "linked-evidence.md"
        link.symlink_to(self.evidence)
        with self.assertRaisesRegex(ValueError, "symlink"):
            checkpoint.artifact(str(link))
        with self.assertRaises(ValueError):
            checkpoint.artifact("relative/evidence.md")

    def test_lock_is_exclusive(self):
        with checkpoint.locked(self.home):
            with self.assertRaises(BlockingIOError):
                with checkpoint.locked(self.home):
                    pass
        with checkpoint.locked(self.home):
            pass

    def test_invalid_state_is_rejected_without_rewrite(self):
        self.initialize()
        path = self.state_file()
        original = path.read_bytes()
        cases = []
        os.chmod(path, 0o644)
        cases.append("mode")
        with self.assertRaisesRegex(ValueError, "0600"):
            self.op("status")
        self.assert_cli_rejects(original)
        os.chmod(path, 0o600)

        bad_format = json.loads(original)
        bad_format["format"] = 2
        path.write_text(json.dumps(bad_format))
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            self.op("status")
        self.assert_cli_rejects(path.read_bytes())

        drifted = json.loads(original)
        drifted["active"] = {
            "run_id": "a" * 32, "owner": "x", "harness_root": str(ROOT),
            "reviewed_since": checkpoint.iso(SINCE - datetime.timedelta(hours=1)),
            "query_since": checkpoint.iso(SINCE - datetime.timedelta(days=1)),
            "reviewed_through": checkpoint.iso(NOW), "installed_before": None, "approval": None,
        }
        path.write_text(json.dumps(drifted))
        with self.assertRaisesRegex(ValueError, "reviewed_since"):
            self.op("status")
        self.assert_cli_rejects(path.read_bytes())

    def assert_cli_rejects(self, expected_bytes):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = checkpoint.main(["--home", str(self.home), "abort", "--run-id", "a" * 32])
        self.assertEqual(code, 1)
        self.assertTrue(stderr.getvalue().startswith("Self-improvement checkpoint:"))
        self.assertEqual(self.state_file().read_bytes(), expected_bytes)

    def test_cli_status_and_help(self):
        result = subprocess.run(
            [sys.executable, str(SELF_IMPROVE / "checkpoint.py"), "--home", str(self.home), "status"],
            capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"initialized": False})
        for command in ("status", "initialize", "begin", "approve", "finish", "abort"):
            helped = subprocess.run(
                [sys.executable, str(SELF_IMPROVE / "checkpoint.py"), command, "--help"],
                capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            self.assertEqual(helped.returncode, 0, command)


class RunTests(ContextBase):
    def test_frozen_first_window(self):
        self.assertEqual(self.run["query_since"], checkpoint.iso(SINCE))
        self.assertEqual(self.run["reviewed_since"], checkpoint.iso(SINCE))
        self.assertEqual(self.run["reviewed_through"], checkpoint.iso(NOW))
        self.assertTrue(re.fullmatch(r"[0-9a-f]{32}", self.run["run_id"]))
        with self.assertRaisesRegex(ValueError, "already active"):
            self.op("begin", owner="other-session", harness_root=str(ROOT))
        state = self.stored()
        self.assertEqual(state["active"], self.run)
        self.assertIsNone(state["last_success"])

    def test_approval_and_coverage_are_required(self):
        with self.assertRaisesRegex(ValueError, "Explicit proposal approval"):
            self.finish(self.completion("0" * 64))
        bad = [
            {"local": "partial"},
            {"environments": ["left_thumb"]},
            {"environments": ENVIRONMENTS[:9] + ["left_thumb"]},
            {"material_gaps": ["left_ring 2026-11-05"]},
            {"sessions_considered": -1},
            {"turns_considered": True},
            {"cloud": "stale"},
        ]
        for overrides in bad:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    self.approve(self.proposal(**overrides))
                self.assertIsNone(self.stored()["last_success"])
                self.assertIsNone(self.stored()["active"]["approval"])
        with self.assertRaises(ValueError):
            self.op("approve", run_id=self.run["run_id"], proposal=str(self.proposal()), approval_ref="  ")

    def test_no_skipped_windows(self):
        self.op("abort", run_id=self.run["run_id"])
        state = self.stored()
        self.assertIsNone(state["active"])
        self.assertIsNone(state["last_success"])
        self.run = self.op("begin", now=NOW + datetime.timedelta(hours=1), owner="owning-session",
                           harness_root=str(ROOT))["active"]
        self.assertEqual(self.run["reviewed_since"], checkpoint.iso(SINCE))
        approval = self.approve(self.proposal())["active"]["approval"]
        report = self.completion(approval["sha256"], checks=[
            {"command": "python3 -m unittest", "result": "skipped", "evidence": "not run"}])
        with self.assertRaisesRegex(ValueError, "passed"):
            self.finish(report)
        state = self.stored()
        self.assertEqual(state["baseline"]["reviewed_through"], checkpoint.iso(SINCE))
        self.assertIsNone(state["last_success"])
        self.assertEqual(state["active"]["run_id"], self.run["run_id"])
        with self.assertRaisesRegex(ValueError, "passed"):
            self.finish(self.completion(approval["sha256"], checks=[]))

    def test_no_change_run_advances(self):
        approval = self.approve(self.proposal())["active"]["approval"]
        later = NOW + datetime.timedelta(hours=5)
        state = self.finish(self.completion(approval["sha256"]), now=later)
        success = state["last_success"]
        self.assertEqual(success["reviewed_through"], checkpoint.iso(NOW))
        self.assertEqual(success["completed_at"], checkpoint.iso(later))
        self.assertEqual(success["outcome"], "no_change")
        self.assertEqual(success["owner"], "owning-session")
        self.assertIsNone(state["active"])
        self.assertEqual(stat.S_IMODE(os.stat(self.state_file()).st_mode), 0o600)
        old = self.run
        nxt = self.op("begin", now=later + datetime.timedelta(hours=1), owner="next-session",
                      harness_root=str(ROOT))["active"]
        self.assertEqual(nxt["reviewed_since"], checkpoint.iso(NOW))
        self.assertEqual(nxt["query_since"], checkpoint.iso(NOW - datetime.timedelta(days=1)))
        with self.assertRaisesRegex(ValueError, "Wrong"):
            self.op("finish", run_id=old["run_id"], report=str(self.completion(approval["sha256"])))

    def test_reapproval_after_change(self):
        proposal = self.proposal()
        approval = self.approve(proposal)["active"]["approval"]
        self.readable.write_text("# Review\n\nEdited after approval.\n")
        with self.assertRaisesRegex(ValueError, "changed"):
            self.finish(self.completion(approval["sha256"]))
        approval = self.approve(proposal)["active"]["approval"]
        data = json.loads(proposal.read_text())
        data["themes"] = ["sneaked in"]
        proposal.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "changed"):
            self.finish(self.completion(approval["sha256"]))
        self.assertIsNone(self.stored()["last_success"])

    def test_window_and_report_binding(self):
        with self.assertRaisesRegex(ValueError, "frozen"):
            self.approve(self.proposal(reviewed_through=checkpoint.iso(NOW + datetime.timedelta(hours=1))))
        approval = self.approve(self.proposal())["active"]["approval"]
        with self.assertRaisesRegex(ValueError, "match"):
            self.finish(self.completion("f" * 64))
        with self.assertRaisesRegex(ValueError, "match"):
            self.finish(self.completion(approval["sha256"], outcome="updated"))
        with self.assertRaisesRegex(ValueError, "match"):
            self.finish(self.completion(approval["sha256"], run_id="b" * 32))
        self.assertIsNone(self.stored()["last_success"])

    def test_tampered_install_blocks_finish(self):
        approval = self.approve(self.proposal())["active"]["approval"]
        os.chmod(self.entry, 0o600)
        self.entry.write_text("tampered\n")
        with self.assertRaisesRegex(ValueError, "modified"):
            self.finish(self.completion(approval["sha256"]))
        state = self.stored()
        self.assertIsNone(state["last_success"])
        self.assertEqual(state["active"]["run_id"], self.run["run_id"])

    def test_verify_context_delegates_to_installer_verify_owned(self):
        self.assertFalse(hasattr(checkpoint, "_verify_owned_fallback"))
        real_load = checkpoint._load_installer
        calls = []

        def load(harness):
            module = real_load(harness)
            self.assertTrue(callable(getattr(module, "verify_owned", None)))

            def verify_owned(home, receipt):
                calls.append((Path(home), receipt))
                raise ValueError("sentinel: context file modified")

            module.verify_owned = verify_owned
            return module

        with mock.patch.object(checkpoint, "_load_installer", side_effect=load):
            with self.assertRaisesRegex(ValueError, "sentinel"):
                checkpoint.verify_context(self.home, ROOT)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], self.home)
        self.assertEqual(calls[0][1], self.installer.read_receipt(self.home))

    def test_verify_context_requires_installer_verify_owned(self):
        real_load = checkpoint._load_installer

        def load(harness):
            module = real_load(harness)
            del module.verify_owned
            return module

        with mock.patch.object(checkpoint, "_load_installer", side_effect=load):
            with self.assertRaises(AttributeError):
                checkpoint.verify_context(self.home, ROOT)

    def test_updated_success(self):
        target = self.home / ".config" / "digits" / "context" / "tool-and-repo-bindings.md"
        change = {"path": str(target), "summary": "Add the review channel binding",
                  "proposed": "- review_channel: example-reviews", "rationale": "asked twice", "check": "re-read"}
        approval = self.approve(self.proposal(changes=[change]))["active"]["approval"]
        self.assertEqual(approval["changes_before"], [{"path": str(target), "sha256": None}])
        report = self.completion(approval["sha256"], outcome="updated")
        with self.assertRaisesRegex(ValueError, "not applied"):
            self.finish(report)
        target.parent.mkdir(parents=True)
        target.write_text("## Digits plugin\n- review_channel: example-reviews\n")
        with mock.patch.object(checkpoint, "verify_context", side_effect=ValueError("Source and live context differ")):
            with self.assertRaisesRegex(ValueError, "differ"):
                self.finish(report)
        self.assertIsNone(self.stored()["last_success"])
        state = self.finish(report)
        self.assertEqual(state["last_success"]["outcome"], "updated")

    def test_change_scope(self):
        context_dir = ROOT / "context"
        existing = ROOT / "context" / "bootstrap.md"
        bad = [
            [{"path": "/unrelated-repository/file.md", "summary": "x"}],
            [{"path": str(ROOT) + "/../outside-context.md", "summary": "x"}],
            [{"path": str(context_dir), "summary": "x"}, {"path": str(context_dir), "summary": "y"}],
            [{"path": str(existing), "summary": "x"}, {"path": str(existing), "summary": "y"}],
            [{"path": "context/bootstrap.md", "summary": "x"}],
            [{"path": str(self.home / ".config" / "digits" / "context"), "summary": "x"}],
            [{"path": str(existing), "summary": ""}],
        ]
        for index, changes in enumerate(bad):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    self.approve(self.proposal(name=f"scope-{index}.json", changes=changes))
                self.assertIsNone(self.stored()["active"]["approval"])
        ok = self.approve(self.proposal(changes=[{"path": str(existing), "summary": "tighten wording"}]))
        self.assertEqual(ok["active"]["approval"]["changes_before"][0]["path"], str(existing))

    def test_atomic_write_failure_keeps_state(self):
        approval = self.approve(self.proposal())["active"]["approval"]
        before = self.state_file().read_bytes()
        report = self.completion(approval["sha256"])
        with mock.patch("os.replace", side_effect=OSError("simulated replace failure")):
            with self.assertRaisesRegex(OSError, "simulated replace failure"):
                self.finish(report)
        self.assertEqual(self.state_file().read_bytes(), before)
        self.assertEqual(list(self.state_file().parent.glob(".checkpoint-*")), [])


class SkillTextTests(unittest.TestCase):
    PHRASES = [
        "/digits:self-improve",
        "Always obtain explicit approval",
        "24-hour overlap",
        "no changes",
        "No default pushes",
        "never assume a checkout",
        "Material missing history",
        "Creating this command is not permission",
    ]

    def test_self_improve_skill_text(self):
        text = (SELF_IMPROVE / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(len(text.splitlines()), 190)
        for phrase in self.PHRASES:
            self.assertIn(phrase, text)

    def test_report_contract_exists(self):
        text = (SELF_IMPROVE / "report-contract.md").read_text(encoding="utf-8")
        for key in ("proposal.json", "completion.json", "material_gaps", "proposal_sha256", "readable_report"):
            self.assertIn(key, text)


EXPECTED_SKILLS = {
    "standup-update", "request-review", "review-reactions", "draft-pr-sweep", "assess-and-address",
    "rebase-pr", "update-shared-workflows", "investigate", "challenge-pass", "inter-env",
    "self-improve", "done", "summarize", "token-usage",
}


class PackageTests(unittest.TestCase):
    def test_plugin_manifest(self):
        manifest = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(list(manifest), ["$schema", "name", "version", "description", "license"])
        self.assertEqual(manifest["$schema"], "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json")
        self.assertEqual(manifest["name"], "digits")
        self.assertEqual(manifest["version"], "1.0.2")
        self.assertTrue(manifest["description"].strip())
        self.assertNotIn("\n", manifest["description"])

    def test_claude_manifest_matches_plugin(self):
        # Claude Code ignores plugin.json at the root and reads .claude-plugin/plugin.json.
        manifest = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        claude = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(list(claude), ["name", "version", "description", "license"])
        for key in ("name", "version", "license"):
            self.assertEqual(claude[key], manifest[key], key)
        self.assertTrue(claude["description"].strip())
        self.assertNotIn("\n", claude["description"])
        self.assertNotIn("Copilot", claude["description"])

    def test_versions_match_marketplace(self):
        manifest = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
        catalog = json.loads((ROOT / ".github" / "plugin" / "marketplace.json").read_text(encoding="utf-8"))
        entries = [p for p in catalog["plugins"] if p["name"] == "digits"]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["version"], manifest["version"])
        self.assertEqual(entries[0]["source"], "./plugin")

    def test_fourteen_skills_with_frontmatter(self):
        directories = sorted(p.name for p in SKILLS.iterdir() if p.is_dir())
        self.assertEqual(set(directories), EXPECTED_SKILLS)
        for name in directories:
            with self.subTest(skill=name):
                keys, body = frontmatter(SKILLS / name / "SKILL.md")
                self.assertIsNotNone(keys, "missing frontmatter")
                self.assertEqual(keys[0], ("name", name))
                description = dict(k for k in keys if k[0])["description"]
                self.assertTrue(description.strip())
                self.assertNotIn(None, [k for k, _ in keys], "multi-line frontmatter value")
                flags = dict(keys)
                if name == "done":
                    self.assertEqual(flags.get("disable-model-invocation"), "true")
                else:
                    self.assertNotIn("disable-model-invocation", flags)
                if name == "standup-update":
                    self.assertNotIn("user-invocable", flags)
                else:
                    self.assertEqual(flags.get("user-invocable"), "true")

    def test_own_skill_bodies_start_with_heading_and_usage(self):
        for name in ("done", "summarize", "request-review", "standup-update", "inter-env", "self-improve"):
            with self.subTest(skill=name):
                _, body = frontmatter(SKILLS / name / "SKILL.md")
                content = [line for line in body if line.strip()]
                self.assertTrue(content[0].startswith("# "))
                self.assertIn("Usage:", content[1])
                self.assertIn(f"/digits:{name}", content[1])

    def test_standup_frontmatter(self):
        keys, _ = frontmatter(SKILLS / "standup-update" / "SKILL.md")
        self.assertEqual([k for k, _ in keys], ["name", "description", "allowed-tools", "license"])
        values = dict(keys)
        self.assertEqual(values["license"], "MIT")
        self.assertEqual([t.strip() for t in values["allowed-tools"].split(",")], [
            "shell(gh:*)", "shell(./fetch-jira-activity.sh:*)", "shell(./fetch-github-activity.sh:*)",
            "atlassian-searchJiraIssuesUsingJql", "atlassian-getJiraIssue", "atlassian-atlassianUserInfo",
            "atlassian-getAccessibleAtlassianResources", "atlassian-search", "atlassian-fetch",
            "session_store_sql",
        ])

    def test_request_review_phrases(self):
        text = (SKILLS / "request-review" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Only after explicit approval", text)
        self.assertIn("never enable auto-merge", text)

    def test_executables_and_syntax(self):
        for script in sorted((SKILLS / "standup-update").glob("*.sh")):
            with self.subTest(script=script.name):
                self.assertEqual(stat.S_IMODE(os.stat(script).st_mode), 0o755)
                self.assertEqual(subprocess.run(["bash", "-n", str(script)]).returncode, 0)
        for helper in (SKILLS / "self-improve" / "checkpoint.py", SKILLS / "self-improve" / "session_history.py",
                       SKILLS / "inter-env" / "inter_env.py"):
            self.assertTrue(helper.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n"))
            self.assertTrue(os.stat(helper).st_mode & stat.S_IXUSR)
        node = subprocess.run(["which", "node"], capture_output=True, text=True).stdout.strip()
        if not node:
            self.skipTest("node is not installed")
        for entry in sorted((PLUGIN / "com.github.copilot" / "extensions").glob("*/extension.mjs")):
            with self.subTest(entry=entry.parent.name):
                self.assertEqual(subprocess.run([node, "--check", str(entry)]).returncode, 0)

    def test_no_private_material_in_package(self):
        home_path = re.compile(r"/(Users|home)/[A-Za-z0-9._-]+/")
        forbidden_names = re.compile(r"(\.log|\.receipt\.json|\.pem|\.key|\.env|\.pyc)$")
        token = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})")
        for path in sorted(PLUGIN.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            with self.subTest(path=str(path.relative_to(ROOT))):
                self.assertIsNone(forbidden_names.search(path.name))
                text = path.read_text(encoding="utf-8", errors="replace")
                self.assertIsNone(home_path.search(text))
                self.assertIsNone(token.search(text))


if __name__ == "__main__":
    unittest.main()
