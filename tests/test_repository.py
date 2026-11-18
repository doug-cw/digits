"""Tests for scripts/check_repository.py and the shared index check."""

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import check_repository as guard
from scripts import check_secrets as secret_guard

REPO_ROOT = Path(__file__).resolve().parent.parent

# Assembled at run time so this file never contains a literal machine path.
SLASH = "/"
MAC_HOME_PREFIX = SLASH + "Users" + SLASH
LINUX_HOME_PREFIX = SLASH + "home" + SLASH


class GuardTestCase(unittest.TestCase):
    """Fresh temporary repository root and HOME for each test."""

    def setUp(self):
        self.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="digits-guard-")))
        self.addCleanup(shutil.rmtree, str(self.tmp), True)
        self.root = self.tmp / "repo"
        self.root.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()

        environment = {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CEILING_DIRECTORIES": str(self.tmp),
        }
        patcher = mock.patch.dict(os.environ, environment)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (
            guard.PRIVATE_TERMS_ENV,
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_CONFIG_GLOBAL",
        ):
            os.environ.pop(name, None)

        for module in (guard, secret_guard):
            root_patch = mock.patch.object(module, "ROOT", self.root)
            root_patch.start()
            self.addCleanup(root_patch.stop)

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def inspect(self, relative, content="text\n"):
        self.write(relative, content)
        return guard.inspect_file(relative)

    def git(self, *args):
        return subprocess.run(
            ["git"] + list(args),
            cwd=str(self.root),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def init_repo(self):
        self.git("init", "-q")

    def run_main(self, module=guard):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = module.main()
        return status, out.getvalue(), err.getvalue()

    def terms_file(self, lines, path=None):
        path = path or self.home / guard.DEFAULT_PRIVATE_TERMS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


class PerFileInspectionTests(GuardTestCase):
    def test_private_configuration_names_are_rejected(self):
        for name in (
            "mcp-config.json",
            "session-state/transcript.json",
            "saved.bak-20261020",
        ):
            with self.subTest(name=name):
                self.assertTrue(self.inspect(name, "{}"))

    def test_machine_home_paths_are_rejected(self):
        content = MAC_HOME_PREFIX + "fixture" + SLASH + ".copilot"
        errors = self.inspect("settings.md", content)
        self.assertEqual(errors, ["settings.md: hardcoded user home path"])

    def test_sanitized_example_is_valid_and_broken_json_fails(self):
        example = json.dumps({"env": {"LOCAL_VALUE": "__LOCAL__"}})
        self.assertEqual(self.inspect("mcp-config.example.json", example), [])
        self.assertTrue(self.inspect("broken.json", "{"))

    def test_symlink_short_circuits_other_checks(self):
        self.write("target.txt", "{ not json glimmerfax\n")
        os.symlink("target.txt", str(self.root / "link.json"))
        errors = guard.inspect_file("link.json")
        self.assertEqual(len(errors), 1)
        self.assertIn("symlink", errors[0])
        self.assertTrue(errors[0].startswith("link.json: "))

    def test_dangling_and_directory_symlinks_are_rejected(self):
        (self.root / "folder").mkdir()
        os.symlink("missing", str(self.root / "dangling"))
        os.symlink("folder", str(self.root / "dirlink"))
        for name in ("dangling", "dirlink"):
            errors = guard.inspect_file(name)
            self.assertEqual(len(errors), 1)
            self.assertIn("symlink", errors[0])

    def test_backup_name_pattern(self):
        for name in ("notes.backup", "config.bak.json", "x.backup-1"):
            with self.subTest(name=name):
                self.assertTrue(self.inspect(name, "{}\n"))
        for name in ("bakery.md", "backup.md", "a.bakfile"):
            with self.subTest(name=name):
                self.assertEqual(self.inspect(name), [])

    def test_environment_files(self):
        for name in (".env", ".env.example", ".env.local"):
            with self.subTest(name=name):
                self.assertTrue(self.inspect(name))
        self.assertEqual(self.inspect("env.md"), [])

    def test_private_directory_anywhere_in_path(self):
        for name in ("docs/logs/readme.md", "a/node_modules/b.js", "x/.local/y.txt"):
            with self.subTest(name=name):
                errors = self.inspect(name)
                self.assertEqual(len(errors), 1)
                self.assertIn("artifact is not allowed", errors[0])

    def test_private_suffixes_are_case_sensitive_and_last_suffix_only(self):
        self.assertTrue(self.inspect("image.png", "x"))
        self.assertEqual(self.inspect("archive.zip.md"), [])
        self.assertEqual(self.inspect("IMAGE.PNG", "x"), [])
        self.assertEqual(self.inspect(".pem"), [])
        self.assertEqual(self.inspect("mcp-config.example.json", "{}"), [])

    def test_non_utf8_content_reports_only_the_encoding_error(self):
        home_text = MAC_HOME_PREFIX + "someone" + SLASH
        content = (home_text + "\n").encode("utf-8") + b"\xff\n"
        errors = self.inspect("notes.md", content)
        self.assertEqual(errors, ["notes.md: file must be readable UTF-8 source"])
        json_errors = self.inspect("bad.json", b"{\xff")
        self.assertEqual(json_errors, ["bad.json: file must be readable UTF-8 source"])

    def test_directory_entry_reports_utf8_error(self):
        (self.root / "submodule").mkdir()
        errors = guard.inspect_file("submodule")
        self.assertEqual(errors, ["submodule: file must be readable UTF-8 source"])

    def test_home_path_boundaries(self):
        accepted = [
            "/Users/<name>/project",
            "~/x",
            "a bare /home/ path",
            "$HOME/.copilot/",
            MAC_HOME_PREFIX + "no-trailing-slash",
        ]
        for text in accepted:
            with self.subTest(text=text):
                self.assertEqual(self.inspect("doc.md", text), [])
        rejected = [
            LINUX_HOME_PREFIX + "ci-runner/",
            "see " + SLASH + "opt" + LINUX_HOME_PREFIX + "x/ here",
            "line one\n  indented " + MAC_HOME_PREFIX + "a.b-c_d/e\n",
        ]
        for text in rejected:
            with self.subTest(text=text):
                self.assertEqual(
                    self.inspect("doc.md", text), ["doc.md: hardcoded user home path"]
                )
        repeated = (LINUX_HOME_PREFIX + "ci-runner/\n") * 3
        self.assertEqual(len(self.inspect("doc.md", repeated)), 1)

    def test_json_line_number(self):
        errors = self.inspect("data.json", '{\n  "a": ,\n  "b": 1\n}\n')
        self.assertEqual(errors, ["data.json: invalid JSON at line 2"])

    def test_empty_json_is_invalid_and_other_extensions_are_not_parsed(self):
        self.assertEqual(self.inspect("empty.json", ""), ["empty.json: invalid JSON at line 1"])
        self.assertEqual(self.inspect("data.jsonl", "{\n"), [])
        self.assertEqual(self.inspect("data.json5", "{\n"), [])

    def test_multiple_errors_are_all_reported(self):
        errors = self.inspect("mcp-config.json", "{")
        self.assertEqual(len(errors), 2)
        self.assertIn("artifact is not allowed", errors[0])
        self.assertIn("invalid JSON at line 1", errors[1])


class IndexAgreementTests(GuardTestCase):
    def test_staged_content_hidden_by_cleaner_copy_is_rejected_by_both_guards(self):
        self.init_repo()
        self.write("README.md", "# Fixture\n")
        self.write("fixture.txt", "path " + MAC_HOME_PREFIX + "fixture" + SLASH + "\n")
        self.git("add", "README.md", "fixture.txt")
        self.write("fixture.txt", "harmless text\n")

        for module in (guard, secret_guard):
            with self.subTest(module=module.__name__):
                status, out, err = self.run_main(module)
                self.assertEqual(status, 1)
                self.assertIn("Staged files differ", err)
                self.assertEqual(out, "")

        self.git("add", "fixture.txt")
        guard.require_index_match(self.root)

    def test_deleted_tracked_file_is_a_mismatch(self):
        self.init_repo()
        self.write("README.md", "# Fixture\n")
        self.git("add", "README.md")
        (self.root / "README.md").unlink()
        with self.assertRaises(guard.IndexMismatchError):
            guard.require_index_match(self.root)

    def test_untracked_files_do_not_affect_the_index_check(self):
        self.init_repo()
        self.write("README.md", "# Fixture\n")
        guard.require_index_match(self.root)

    def test_failed_comparison_is_not_a_match(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        with self.assertRaises(guard.IndexComparisonError) as caught:
            guard.require_index_match(plain)
        self.assertIn("Could not compare", str(caught.exception))
        self.assertNotIsInstance(caught.exception, guard.IndexMismatchError)

    def test_index_check_precedes_everything(self):
        self.init_repo()
        self.write("README.md", "# Fixture\n")
        self.git("add", "README.md")
        self.write("README.md", "# Changed\n")
        os.environ[guard.PRIVATE_TERMS_ENV] = str(self.tmp / "missing-terms.txt")
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("Staged files differ", err)
        self.assertNotIn(guard.PRIVATE_TERMS_ENV, err)
        self.assertEqual(out, "")

    def test_main_outside_git_fails(self):
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("Could not compare", err)
        self.assertEqual(out, "")


class RepositoryRunTests(GuardTestCase):
    def setUp(self):
        super().setUp()
        self.init_repo()
        self.write("README.md", "# Fixture\n")
        self.write("notes.md", "# Release notes\nShipped by Glimmerfax today\n")

    def test_match_reports_location_only(self):
        self.terms_file(["# private names", "", "glimmerfax"])
        status, out, err = self.run_main()
        combined = out + err
        self.assertEqual(status, 1)
        self.assertIn("notes.md:2: private term #3", combined)
        self.assertNotIn("glimmerfax", combined.casefold())
        self.assertEqual(out, "")

    def test_comments_and_blank_lines_are_not_terms(self):
        self.terms_file(["# Release notes", "", "   \t"])
        status, out, err = self.run_main()
        self.assertEqual(status, 0, err)
        self.assertIn("checked 0 terms", out)

    def test_missing_default_terms_file_skips_the_guard(self):
        status, out, err = self.run_main()
        self.assertEqual(status, 0, err)
        self.assertIn("guard skipped", out)
        self.assertEqual(err, "")

    def test_explicit_missing_terms_file_fails(self):
        missing = self.tmp / "nowhere" / "terms.txt"
        os.environ[guard.PRIVATE_TERMS_ENV] = str(missing)
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("DIGITS_PRIVATE_TERMS", out + err)
        self.assertIn(str(missing), err)
        self.assertEqual(out, "")

    def test_unreadable_terms_file_is_a_configuration_error(self):
        path = self.home / guard.DEFAULT_PRIVATE_TERMS
        path.parent.mkdir(parents=True)
        path.write_bytes(b"glimmerfax\n\xff\n")
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertNotIn("glimmerfax", err.casefold())
        self.assertNotIn("notes.md", err)
        self.assertEqual(out, "")

    def test_term_numbering_and_multiplicity(self):
        self.write("upper.md", "ALPHA and beta, alpha again\nnothing here\n")
        self.terms_file(["# c", "alpha", "", "Beta"])
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        lines = err.splitlines()
        self.assertEqual(
            [line for line in lines if line.startswith("upper.md")],
            ["upper.md:1: private term #2", "upper.md:1: private term #4"],
        )
        folded = (out + err).casefold()
        self.assertNotIn("alpha", folded)
        self.assertNotIn("beta", folded)

    def test_substring_matching(self):
        self.terms_file(["fax"])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("notes.md:2: private term #1", err)
        self.assertNotIn("fax", err.casefold())

    def test_zero_terms_success_summary(self):
        self.terms_file(["# only a comment", "# another"])
        status, out, err = self.run_main()
        self.assertEqual(status, 0, err)
        self.assertIn("guard checked 0 terms", out)

    def test_empty_override_equals_unset(self):
        os.environ[guard.PRIVATE_TERMS_ENV] = ""
        status, out, _ = self.run_main()
        self.assertEqual(status, 0)
        self.assertIn("guard skipped", out)
        self.terms_file(["glimmerfax"])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("notes.md:2: private term #1", err)

    def test_explicit_override_with_tilde(self):
        self.terms_file(["# header", "glimmerfax"], path=self.home / "terms.txt")
        os.environ[guard.PRIVATE_TERMS_ENV] = "~/terms.txt"
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("notes.md:2: private term #2", err)

    def test_symlink_is_not_scanned_for_terms(self):
        os.symlink("notes.md", str(self.root / "link.json"))
        self.terms_file(["glimmerfax"])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertNotRegex(err, r"link\.json:\d+:")
        self.assertIn("link.json: symlinks are not accepted", err)
        self.assertIn("notes.md:2: private term #1", err)

    def test_untracked_non_ignored_files_are_inspected_ignored_are_not(self):
        self.write(".gitignore", "*.log\n")
        self.write("out.log", "ignored\n")
        self.write("keys.pem", "not ignored here\n")
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertIn("keys.pem: private, generated, or binary artifact", err)
        self.assertNotIn("out.log", err)
        self.assertEqual(out, "")

    def test_failures_are_ordered_with_readme_last(self):
        (self.root / "README.md").unlink()
        self.write("b.json", "{")
        self.write("a.png", "x")
        self.terms_file(["glimmerfax"])
        status, _, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(
            err.splitlines(),
            [
                "a.png: private, generated, or binary artifact is not allowed",
                "b.json: invalid JSON at line 1",
                "notes.md:2: private term #1",
                "README.md: missing project README",
            ],
        )

    def test_success_summary_reports_file_count(self):
        self.write("docs/guide.md", "hello\n")
        self.git("add", "docs/guide.md")
        status, out, err = self.run_main()
        self.assertEqual(status, 0, err)
        self.assertEqual(
            out.strip(),
            "Repository structure/JSON/path checks passed (3 files); "
            "private-terms guard skipped (no terms file).",
        )
        self.assertEqual(err, "")


class MissingReadmeTests(GuardTestCase):
    def test_missing_root_readme(self):
        self.init_repo()
        self.write("a.md", "content\n")
        status, out, err = self.run_main()
        self.assertEqual(status, 1)
        self.assertEqual(err.splitlines(), ["README.md: missing project README"])
        self.assertEqual(out, "")

    def test_ignored_readme_still_satisfies_the_requirement(self):
        self.init_repo()
        self.write(".gitignore", "README.md\n")
        self.write("README.md", "# hidden\n")
        status, _, err = self.run_main()
        self.assertEqual(status, 0, err)


class RepositorySelfCheckTests(GuardTestCase):
    """Run both guards on a staged copy of this checkout (index untouched)."""

    def copy_checkout(self):
        listing = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=str(REPO_ROOT),
            check=True,
            stdout=subprocess.PIPE,
            env=dict(os.environ, GIT_CEILING_DIRECTORIES=""),
        ).stdout.decode("utf-8", errors="surrogateescape")
        for relative in sorted({entry for entry in listing.split("\0") if entry}):
            source = REPO_ROOT / relative
            target = self.root / relative
            if not os.path.lexists(str(source)):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if os.path.islink(str(source)):
                os.symlink(os.readlink(str(source)), str(target))
            elif source.is_file():
                shutil.copy2(str(source), str(target))
        self.init_repo()
        self.git("add", "-A")

    def test_checkout_passes_both_guards(self):
        self.copy_checkout()
        status, out, err = self.run_main(guard)
        self.assertEqual(status, 0, err)
        self.assertIn("guard skipped", out)
        if shutil.which(secret_guard.SCANNER) is None:
            self.skipTest("detect-secrets not on PATH; install requirements-dev.txt")
        status, out, err = self.run_main(secret_guard)
        self.assertEqual(status, 0, err)


class ProjectFileTests(unittest.TestCase):
    def test_example_config_validity(self):
        data = json.loads((REPO_ROOT / "mcp" / "mcp-config.example.json").read_text("utf-8"))
        self.assertEqual(list(data), ["mcpServers"])
        servers = data["mcpServers"]
        self.assertEqual(
            list(servers), ["atlassian", "slack", "example-remote", "example-local"]
        )
        self.assertEqual(
            [servers[name]["type"] for name in servers], ["http", "http", "http", "local"]
        )
        allowed_urls = {
            "https://mcp.atlassian.com/v2/mcp",
            "https://mcp.slack.com/mcp",
            "https://mcp.example.invalid/mcp",
        }
        placeholder = re.compile(r"__[A-Z]+(?:_[A-Z]+)*__")

        def check(value, key=None):
            if isinstance(value, dict):
                for child_key, child in value.items():
                    check(child, child_key)
            elif isinstance(value, list):
                if value == ["*"]:
                    return
                for item in value:
                    check(item)
            elif key == "type":
                self.assertIn(value, {"http", "local"})
            elif key == "url":
                self.assertIn(value, allowed_urls)
            else:
                self.assertRegex(value, r"\A" + placeholder.pattern + r"\Z")

        check(servers)
        self.assertEqual(servers["atlassian"]["tools"], ["*"])
        self.assertEqual(servers["slack"]["tools"], ["*"])
        self.assertEqual(
            servers["example-remote"]["headers"], {"Authorization": "__SET_IN_LOCAL_CONFIG__"}
        )
        self.assertEqual(
            servers["example-local"]["env"], {"EXAMPLE_API_TOKEN": "__SET_IN_LOCAL_CONFIG__"}
        )

    def test_marketplace_manifest(self):
        data = json.loads(
            (REPO_ROOT / ".github" / "plugin" / "marketplace.json").read_text("utf-8")
        )
        self.assertEqual(set(data), {"name", "owner", "plugins"})
        self.assertEqual(data["name"], "digits")
        self.assertEqual(data["owner"], {"name": "Digits maintainers"})
        self.assertEqual(len(data["plugins"]), 1)
        entry = data["plugins"][0]
        self.assertEqual(set(entry), {"name", "description", "version", "source"})
        self.assertEqual(entry["name"], "digits")
        self.assertEqual(entry["version"], "1.0.4")
        self.assertEqual(entry["source"], "./plugin")
        self.assertTrue(entry["description"].strip())
        manifest = REPO_ROOT / "plugin" / "plugin.json"
        if not manifest.is_file():
            self.skipTest("plugin/plugin.json not present")
        plugin = json.loads(manifest.read_text("utf-8"))
        self.assertEqual(entry["version"], plugin["version"])

    def test_ci_workflow(self):
        text = (REPO_ROOT / ".github" / "workflows" / "checks.yml").read_text("utf-8")
        self.assertRegex(text, r"(?m)^name: Source checks$")
        self.assertRegex(text, r"(?m)^on:\n  pull_request:\n  push:\n    branches:\n      - main\n")
        self.assertRegex(text, r"(?m)^permissions:\n  contents: read\n\n")
        self.assertRegex(text, r"(?m)^jobs:\n  source:\n    runs-on: macos-latest$")
        self.assertNotIn("${{ secrets", text)
        self.assertNotRegex(text, r"(?m)^\s*env:")
        self.assertEqual(len(re.findall(r"(?m)^  [A-Za-z_-]+:$", text.split("jobs:", 1)[1])), 1)
        self.assertIn('python-version: "3.12"', text)
        self.assertIn('node-version: "22"', text)

        steps = re.findall(r"(?m)^      - name: .*\n((?:        .*\n?)+)", text)
        actions = []
        for body in steps:
            found = re.search(r"(?m)^        (uses|run): (.*)$", body)
            actions.append(found.group(2).strip())
        self.assertEqual(
            actions,
            [
                "actions/checkout@v4",
                "actions/setup-python@v5",
                "actions/setup-node@v4",
                "brew list tmux >/dev/null 2>&1 || brew install tmux",
                "python -m pip install -r requirements-dev.txt",
                "python scripts/check_repository.py",
                "python scripts/check_secrets.py",
                "python -m unittest discover -s tests",
                "python -m unittest discover -s plugin/skills/inter-env -p 'test_*.py'",
                'for helper in plugin/skills/standup-update/*.sh; do bash -n "$helper" || exit 1; done',
                "node --check copilot/extensions/env-dashboard/extension.mjs",
                "node --test copilot/extensions/env-dashboard/*.test.mjs",
                'for entry in plugin/com.github.copilot/extensions/*/extension.mjs; do node --check "$entry" || exit 1; done',
                "node --test plugin/com.github.copilot/extensions/*/*.test.mjs",
            ],
        )

    def test_requirements_and_gitignore(self):
        requirements = (REPO_ROOT / "requirements-dev.txt").read_text("utf-8").split()
        self.assertEqual(requirements, ["detect-secrets==1.5.0"])
        entries = set((REPO_ROOT / ".gitignore").read_text("utf-8").splitlines())
        for entry in (
            ".DS_Store __pycache__/ *.pyc .venv/ node_modules/ .env .env.* "
            "*.local.json *.local.yml *.local.yaml *.pem *.key *.p12 *.pfx "
            "*.bak *.log *.db *.db-shm *.db-wal session-state/ "
            "mcp-oauth-config/ resurrect/ .local/"
        ).split():
            self.assertIn(entry, entries)


DOCUMENTS = [
    "README.md",
    ".github/CONTRIBUTING.md",
    ".github/SECURITY.md",
    ".github/CODE_OF_CONDUCT.md",
    "docs/provenance.md",
    "docs/build-your-own.md",
    "docs/open-source-release-checklist.md",
    "mcp/README.md",
]
LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def github_slugs(markdown):
    slugs = set()
    in_fence = False
    for line in markdown.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        heading = re.match(r"#{1,6}\s+(.*?)\s*#*\s*$", line)
        if in_fence or not heading:
            continue
        text = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", r"\1", heading.group(1)).lower()
        slug = re.sub(r"[^\w\- ]", "", text).replace(" ", "-")
        slugs.add(slug)
    return slugs


class DocumentationLinkTests(unittest.TestCase):
    def test_relative_links_resolve(self):
        missing = []
        for document in DOCUMENTS:
            path = REPO_ROOT / document
            text = path.read_text("utf-8")
            text = re.sub(r"(?ms)^```.*?^```", "", text)
            for target in LINK.findall(text):
                if re.match(r"[a-z][a-z0-9+.-]*:", target):
                    continue
                file_part, _, anchor = target.partition("#")
                resolved = (path.parent / file_part).resolve() if file_part else path
                if not resolved.exists():
                    missing.append("{} -> {}".format(document, target))
                    continue
                if anchor and resolved.suffix == ".md":
                    if anchor not in github_slugs(resolved.read_text("utf-8")):
                        missing.append("{} -> {} (anchor)".format(document, target))
        self.assertEqual(missing, [])

    def test_readme_anchors_exist(self):
        slugs = github_slugs((REPO_ROOT / "README.md").read_text("utf-8"))
        self.assertIn("make-it-yours", slugs)
        self.assertIn("verification", slugs)


if __name__ == "__main__":
    unittest.main()
