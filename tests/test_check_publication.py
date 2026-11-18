"""Tests for scripts/check_publication.py."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_publication as preflight
from scripts import check_repository as repository_guard

# Assembled at run time so this file never contains a literal address or path.
AT = "@"
NOREPLY = "1234+fixture" + AT + "users.noreply.github.com"
ASSISTANT = "noreply" + AT + "anthropic.com"
OUTSIDE = "someone" + AT + "fixture-corp.com"
EXAMPLE = "someone" + AT + "example.com"
HOME_TEXT = "/" + "Users" + "/fixture/notes"
TERM = "glimmerfax"
MARKER = "FAKE-SECRET-MARKER"

FAKE_SCANNER = """#!{python}
import json, os, sys
mode = os.environ.get("FAKE_SCANNER_MODE", "")
if mode == "fail":
    sys.exit(3)
results = {{}}
for name in sorted(os.listdir(".")):
    with open(name, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if "{marker}" in line:
                results.setdefault(name, []).append(
                    {{"type": "Fake Detector " + os.path.splitext(name)[1],
                     "line_number": number,
                     "hashed_secret": "0" * 40}})
print(json.dumps({{"results": results}}))
"""


class PreflightTestCase(unittest.TestCase):
    """Temporary repository, HOME and global Git config for each test."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="digits-preflight-")))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        global_config = self.tmp / "gitconfig"
        global_config.write_text("", encoding="utf-8")

        environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "GIT_CONFIG_GLOBAL": str(global_config),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": str(self.tmp),
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (
            repository_guard.PRIVATE_TERMS_ENV,
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "FAKE_SCANNER_MODE",
        ):
            os.environ.pop(name, None)

        scanner = self.tmp / "fake-scanner"
        scanner.write_text(
            FAKE_SCANNER.format(python=sys.executable, marker=MARKER), encoding="utf-8"
        )
        scanner.chmod(0o755)
        for target, value in (("ROOT", self.root), ("SCANNER", str(scanner))):
            attribute = mock.patch.object(preflight, target, value)
            attribute.start()
            self.addCleanup(attribute.stop)

        self.git("init", "-q")
        self.commit("README.md", "fixture\n", "chore: start")
        self.base = self.head()

    def git(self, *args, author=NOREPLY, committer=NOREPLY):
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME="Fixture Author",
            GIT_AUTHOR_EMAIL=author,
            GIT_COMMITTER_NAME="Fixture Committer",
            GIT_COMMITTER_EMAIL=committer,
        )
        return subprocess.run(
            ["git"] + list(args),
            cwd=str(self.root),
            env=env,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def head(self):
        return self.git("rev-parse", "HEAD").stdout.decode().strip()

    def commit(self, relative, content, message, **identity):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message, **identity)

    def terms_file(self, lines=("# private names", TERM)):
        path = self.home / repository_guard.DEFAULT_PRIVATE_TERMS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def run_main(self, *argv, stdin=""):
        data = stdin if isinstance(stdin, bytes) else stdin.encode("utf-8")
        stream = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with mock.patch.object(sys, "stdin", stream):
                status = preflight.main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def check_range(self):
        return self.run_main("--range", self.base + "..HEAD")


class IdentityTests(PreflightTestCase):
    def test_clean_range_with_assistant_trailer_passes(self):
        self.terms_file()
        message = "feat: add notes\n\nCo-Authored-By: Assistant <{}>".format(ASSISTANT)
        self.commit("notes.md", "plain words\n", message)
        status, out, err = self.check_range()
        self.assertEqual((status, err), (0, ""))
        self.assertIn("1 commits", out)
        self.assertIn("used 1 terms", out)
        self.assertIn("secret scan covered 2 non-empty blocks", out)

    def test_author_and_committer_must_be_github_noreply(self):
        self.commit("a.md", "a\n", "docs: a", author=EXAMPLE)
        self.commit("b.md", "b\n", "docs: b", committer=EXAMPLE)
        status, out, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertEqual(out, "")
        self.assertIn("author email is not a GitHub noreply address", err)
        self.assertIn("committer email is not a GitHub noreply address", err)
        self.assertNotIn(EXAMPLE, err)

    def test_trailer_emails_must_be_noreply(self):
        message = "fix: b\n\nCo-authored-by: Someone <{}>\nReviewed-by: Other <{}>".format(
            EXAMPLE, NOREPLY
        )
        self.commit("b.md", "b\n", message)
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("message:3: trailer email is not a noreply address", err)
        self.assertNotIn("message:4", err)
        self.assertNotIn(EXAMPLE, err)


class ContentTests(PreflightTestCase):
    def test_private_terms_match_as_substrings_without_echo(self):
        self.terms_file()
        content = "\n".join(
            [
                "uses " + TERM.capitalize() + "Widgets",
                "see " + TERM + "corp.atlassian.net",
                "ok",
            ]
        )
        self.commit("docs/x.md", content + "\n", "docs: mention " + TERM)
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("message:1: private term #2", err)
        self.assertIn("docs/x.md:1: private term #2", err)
        self.assertIn("docs/x.md:2: private term #2", err)
        self.assertNotIn("docs/x.md:3:", err)
        self.assertNotIn(TERM, err.casefold())

    def test_noreply_login_is_not_scanned_for_terms(self):
        self.terms_file()
        address = "9+" + TERM + AT + "users.noreply.github.com"
        self.commit("a.md", "a\n", "docs: a", author=address, committer=address)
        status, _, err = self.check_range()
        self.assertEqual((status, err), (0, ""))

    def test_other_identity_emails_are_scanned_for_terms(self):
        self.terms_file()
        self.commit("a.md", "a\n", "docs: a", author=TERM + AT + "example.com")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("author email: private term #2", err)
        self.assertIn("author email is not a GitHub noreply address", err)
        self.assertNotIn(TERM, err)

    def test_added_line_that_looks_like_a_file_header(self):
        self.terms_file()
        self.commit("notes.md", "++ " + TERM + "\n" + HOME_TEXT + "\n", "docs: notes")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("notes.md:1: private term #2", err)
        self.assertIn("notes.md:2: hardcoded user home path", err)

    def test_diff_prefix_configuration_is_ignored(self):
        self.git("config", "diff.noprefix", "true")
        self.git("config", "diff.mnemonicPrefix", "true")
        self.git("config", "log.showSignature", "true")
        self.commit("notes.md", HOME_TEXT + "\n", "docs: notes")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("notes.md:1: hardcoded user home path", err)

    def test_binary_changes_are_findings(self):
        self.commit("blob.dat", "", "chore: placeholder")
        (self.root / "blob.dat").write_bytes(b"\x00\x01binary\x00")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "chore: blob")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertEqual(err.count("blob.dat: binary file not inspected"), 1)

    def test_sensitive_path_is_reported_by_position(self):
        self.terms_file()
        self.commit("{}/notes.md".format(TERM), "line\n", "docs: notes")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("changed path 1: private term #2", err)
        self.assertNotIn(TERM, err)

    def test_home_paths_and_outside_emails_in_added_lines(self):
        content = "\n".join([HOME_TEXT, "mail " + OUTSIDE, "mail " + EXAMPLE]) + "\n"
        self.commit("notes.md", content, "docs: notes")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("notes.md:1: hardcoded user home path", err)
        self.assertIn("notes.md:2: email address outside the example domains", err)
        self.assertNotIn("notes.md:3", err)
        self.assertNotIn(OUTSIDE, err)

    def test_removed_lines_are_not_findings(self):
        self.terms_file()
        self.commit("old.md", "a {} b\n".format(TERM), "docs: add")
        self.base = self.head()
        self.commit("old.md", "clean\n", "docs: clean")
        status, _, err = self.check_range()
        self.assertEqual((status, err), (0, ""))

    def test_root_and_merge_commits_are_inspected(self):
        self.git("checkout", "-q", "-b", "side")
        self.commit("side.md", HOME_TEXT + "\n", "docs: side")
        self.git("checkout", "-q", "-")
        self.commit("main.md", "main\n", "docs: main")
        self.git("merge", "-q", "--no-ff", "-m", "merge side", "side")
        status, out, err = self.run_main("--range", "HEAD")
        self.assertEqual(status, 1)
        self.assertEqual(err.count("side.md:1: hardcoded user home path"), 2)

    def test_empty_range_fails(self):
        status, out, err = self.run_main("--range", "HEAD..HEAD")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("selected no commits", err)

    def test_every_range_is_scanned(self):
        self.commit("one.md", HOME_TEXT + "\n", "docs: one")
        first = self.head()
        self.commit("two.md", "mail " + OUTSIDE + "\n", "docs: two")
        status, _, err = self.run_main(
            "--range", self.base + ".." + first, "--range", first + "..HEAD"
        )
        self.assertEqual(status, 1)
        self.assertIn("one.md:1: hardcoded user home path", err)
        self.assertIn("two.md:1: email address outside", err)

    def test_invalid_range_fails_without_claiming_success(self):
        status, out, err = self.run_main("--range", "no-such-ref..HEAD")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("no passing result is claimed", err)


class TextTests(PreflightTestCase):
    def test_text_file_and_stdin(self):
        self.terms_file()
        body = self.tmp / "pr.md"
        body.write_text("Summary\n\nThanks " + OUTSIDE + "\n", encoding="utf-8")
        status, _, err = self.run_main(
            "--text", str(body), "--text", "-", stdin="ok\n" + TERM + "\n"
        )
        self.assertEqual(status, 1)
        self.assertIn("pr.md:3: email address outside the example domains", err)
        self.assertIn("stdin:2: private term #2", err)

    def test_clean_text_passes(self):
        status, out, _ = self.run_main("--text", "-", stdin="Fixes the parser.\n")
        self.assertEqual(status, 0)
        self.assertIn("1 texts", out)
        self.assertIn("secret scan covered 1 non-empty blocks", out)

    def test_non_utf8_stdin_fails_cleanly(self):
        status, out, err = self.run_main("--text", "-", stdin=b"ok\n\xff\n")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("stdin is not valid UTF-8", err)

    def test_arguments_are_required(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                preflight.main([])


class ConfigurationTests(PreflightTestCase):
    def test_missing_default_terms_file_is_announced_and_other_checks_run(self):
        self.commit("notes.md", HOME_TEXT + "\n", "docs: notes")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("private-term check skipped", err)
        self.assertIn("hardcoded user home path", err)

    def test_missing_default_terms_file_is_named_in_the_summary(self):
        status, out, err = self.run_main("--text", "-", stdin="ok\n")
        self.assertEqual(status, 0)
        self.assertIn("NOTE: no private-terms file", err)
        self.assertIn("private-term check skipped (no terms file)", out)

    def test_explicit_missing_terms_file_fails(self):
        os.environ[repository_guard.PRIVATE_TERMS_ENV] = str(self.tmp / "missing.txt")
        status, out, err = self.run_main("--text", "-", stdin="ok\n")
        self.assertEqual((status, out), (1, ""))
        self.assertIn(repository_guard.PRIVATE_TERMS_ENV, err)


class SecretScanTests(PreflightTestCase):
    def test_secret_findings_map_to_original_lines_without_values(self):
        content = "one\ntwo\n"
        self.commit("config.py", content, "feat: config")
        self.base = self.head()
        self.commit("config.py", content + "token = " + MARKER + "\n", "feat: token")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        self.assertIn("config.py:3: secret (Fake Detector .py)", err)
        self.assertNotIn(MARKER, err)
        self.assertNotIn("0" * 40, err)

    def test_scanned_suffix_is_neutral_unless_keyword_rules_need_it(self):
        line = "key: " + MARKER + "\n"
        for name in ("style.css", "yarn.lock", "notes.md"):
            self.commit(name, line, "chore: " + name)
        self.commit("config.yaml", line, "chore: yaml")
        status, _, err = self.check_range()
        self.assertEqual(status, 1)
        for name in ("style.css", "yarn.lock", "notes.md"):
            self.assertIn(name + ":1: secret (Fake Detector .txt)", err)
        self.assertIn("config.yaml:1: secret (Fake Detector .yaml)", err)

    def test_missing_scanner_is_not_success(self):
        with mock.patch.object(preflight, "SCANNER", str(self.tmp / "absent")):
            status, out, err = self.run_main("--text", "-", stdin="ok\n")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("requirements-dev.txt", err)

    def test_scanner_failure_is_not_success(self):
        os.environ["FAKE_SCANNER_MODE"] = "fail"
        status, out, err = self.run_main("--text", "-", stdin="ok\n")
        self.assertEqual((status, out), (1, ""))
        self.assertIn("no passing result is claimed", err)


class EmailRuleTests(unittest.TestCase):
    def test_publishable_addresses(self):
        for address in (
            NOREPLY,
            ASSISTANT,
            "noreply" + AT + "github.com",
            EXAMPLE,
            "a" + AT + "mail.example.org",
            "a" + AT + "host.invalid",
            "a" + AT + "box.test",
        ):
            with self.subTest(address=address):
                self.assertTrue(preflight.is_publishable_email(address))
        for address in (OUTSIDE, "a" + AT + "example.com.fixture-corp.com"):
            with self.subTest(address=address):
                self.assertFalse(preflight.is_publishable_email(address))
        self.assertFalse(preflight.is_github_noreply(ASSISTANT))


if __name__ == "__main__":
    unittest.main()
