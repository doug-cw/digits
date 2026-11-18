"""Tests for the Digits context library and its installer (spec 20-context.md)."""

import contextlib
import fcntl
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import context_install as ci  # noqa: E402
import install  # noqa: E402

CONTEXT = ROOT / "context"
FIXTURES = ROOT / "tests" / "fixtures" / "context-routing.json"
METADATA = ("Use when", "Scope:", "Sources:", "Reviewed:", "Recheck:")
EXPECTED_PAGES = {
    "bootstrap.md",
    "README.md",
    "workflows/github-delivery.md",
    "workflows/infra-lifecycle.md",
    "workflows/engineering-decisions.md",
    "workflows/continuity.md",
    "workflows/issue-tracker.md",
    "workflows/harness-maintenance.md",
    "domains/data-warehouse.md",
    "integrations/mcp.md",
    "references/repository-map.md",
    "references/writing.md",
    "references/workspace-and-terminal.md",
}
HOME_PATH_RE = re.compile(r"/(Users|home)/[A-Za-z0-9._-]+/")


def mode_of(path):
    return stat.S_IMODE(os.lstat(path).st_mode)


def listing(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames + filenames:
            found.append(Path(dirpath, name).relative_to(root).as_posix())
    return sorted(found)


def slug(heading):
    text = heading.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


class ContextTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.home = self.tmp / "home with spaces"
        self.home.mkdir()
        self.addCleanup(self._tmp.cleanup)

    # helpers -------------------------------------------------------------

    def apply(self, adopt_sha256=None, rollback=False):
        plan = ci.make_plan(self.home, adopt_sha256=adopt_sha256, rollback=rollback)
        with contextlib.redirect_stdout(io.StringIO()):
            install.execute(self.home, plan)
        return plan

    def plan(self, **kwargs):
        return ci.make_plan(self.home, **kwargs)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = ci.main(list(argv))
        return status, out.getvalue(), err.getvalue()

    def receipt(self):
        return json.loads((self.home / ci.RECEIPT).read_text())

    def entry(self):
        return self.home / ci.ENTRY

    def write_entry(self, text, mode):
        self.entry().parent.mkdir(parents=True, exist_ok=True)
        self.entry().write_text(text)
        os.chmod(self.entry(), mode)
        return install.digest(text.encode())

    def copy_source(self):
        copy = self.tmp / "source-copy" / "context"
        if not copy.exists():
            shutil.copytree(str(ci.SOURCE), str(copy))
        return copy

    @contextlib.contextmanager
    def changed_source(self):
        """Point ci.SOURCE at a copy whose patch version is bumped."""
        copy = self.copy_source()
        version_file = copy / "version.json"
        meta = json.loads(version_file.read_text())
        major, minor, patch = meta["version"].split(".")
        meta["version"] = "%s.%s.%d" % (major, minor, int(patch) + 1)
        version_file.write_bytes(ci.encoded(meta))
        with mock.patch.object(ci, "SOURCE", copy):
            yield copy

    def assertFails(self, substring, func, *args, **kwargs):
        with self.assertRaises(ValueError) as caught:
            func(*args, **kwargs)
        self.assertIn(substring, str(caught.exception))
        return caught.exception

    def release_files(self, receipt):
        return [name for name in receipt["files"] if name != ci.ENTRY]


class CliTests(ContextTestCase):
    def test_01_preview_writes_nothing(self):
        status, out, _ = self.run_main("--home", str(self.home))
        self.assertEqual(status, 0)
        self.assertIn("WRITE", out)
        self.assertEqual(listing(self.home), [])

    def test_23_locked_home_fails_without_writing(self):
        descriptor = os.open(str(self.home), os.O_RDONLY)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            status, _, err = self.run_main("--home", str(self.home), "--apply")
        finally:
            os.close(descriptor)
        self.assertEqual(status, 1)
        self.assertIn("Context installer:", err)
        self.assertEqual(listing(self.home), [])

    def test_24_bad_home_exits_1(self):
        missing = self.tmp / "missing"
        link = self.tmp / "link"
        link.symlink_to(self.home)
        for target in (missing, link):
            for extra in ([], ["--apply"]):
                status, _, err = self.run_main("--home", str(target), *extra)
                self.assertEqual(status, 1, (target, extra))
                self.assertIn("Context installer:", err)
        self.assertEqual(listing(self.home), [])

    def test_27_apply_output_and_noop(self):
        status, out, _ = self.run_main("--home", str(self.home), "--apply")
        self.assertEqual(status, 0)
        lines = out.strip().splitlines()
        self.assertTrue(any(line.startswith("WRITE ") for line in lines))
        self.assertIn("digits-refresh", lines[-2])
        self.assertIn("/restart", lines[-2])
        self.assertIn("restarted", lines[-1])
        status, out, _ = self.run_main("--home", str(self.home), "--apply")
        self.assertEqual(status, 0)
        self.assertIn("No file changes needed.", out)

    def test_cli_adopt_and_rollback_flags(self):
        sha = self.write_entry("manual\n", 0o644)
        status, _, err = self.run_main("--home", str(self.home))
        self.assertEqual(status, 1)
        self.assertIn("--adopt-sha256 " + sha, err)
        status, _, _ = self.run_main("--home", str(self.home), "--apply", "--adopt-sha256", sha)
        self.assertEqual(status, 0)
        status, out, _ = self.run_main("--home", str(self.home), "--rollback")
        self.assertEqual(status, 0)
        self.assertIn("REMOVE", out)
        status, _, _ = self.run_main("--home", str(self.home), "--rollback", "--apply")
        self.assertEqual(status, 0)
        self.assertEqual(self.entry().read_text(), "manual\n")
        self.assertEqual(mode_of(self.entry()), 0o644)


class InstallCycleTests(ContextTestCase):
    def test_02_rendered_entry(self):
        self.apply()
        text = self.entry().read_text()
        self.assertIn("home%20with%20spaces", text)
        self.assertIn("file:///", text)
        self.assertNotIn("{{", text)
        self.assertNotIn("exampleorg-producer", text)
        self.assertFalse(any(line.lstrip().startswith("@") for line in text.splitlines()))
        first = text.splitlines()[0]
        self.assertIn("Generated Digits context", first)
        self.assertIn("snapshot", first)
        self.assertEqual(self.apply()["writes"], {})
        for absent in (".copilot/instructions", ".copilot/settings.json", ".claude/CLAUDE.md", ".config"):
            self.assertFalse(os.path.lexists(self.home / absent), absent)

    def test_03_adoption_hash_and_rollback(self):
        sha = self.write_entry("existing user instructions\n", 0o640)
        self.assertFails("adopt-sha256", self.plan)
        error = self.assertFails("adopt-sha256", self.plan, adopt_sha256="0" * 64)
        self.assertIn(sha, str(error))
        self.apply(adopt_sha256=sha)
        self.assertEqual(mode_of(self.entry()), 0o600)
        self.apply(rollback=True)
        self.assertEqual(self.entry().read_text(), "existing user instructions\n")
        self.assertEqual(mode_of(self.entry()), 0o640)
        self.assertFalse((self.home / ci.RECEIPT).exists())
        backups = list((self.home / ci.STATE / "backups").glob("*.json"))
        self.assertGreaterEqual(len(backups), 1)

    def test_04_update_then_rollback(self):
        self.apply()
        r1 = self.receipt()
        e1 = self.entry().read_bytes()
        with self.changed_source():
            self.apply()
            self.assertNotEqual(self.entry().read_bytes(), e1)
            for name in r1["files"]:
                self.assertTrue((self.home / name).is_file(), name)
            r2 = self.receipt()
            self.apply(rollback=True)
            for name in self.release_files(r2):
                self.assertTrue((self.home / name).is_file(), name)
        self.assertEqual(self.entry().read_bytes(), e1)
        self.assertEqual(self.receipt(), r1)
        self.assertEqual(self.apply()["writes"], {})

    def test_05_initial_rollback_then_reinstall(self):
        self.apply()
        receipt = self.receipt()
        self.apply(rollback=True)
        self.assertFalse(os.path.lexists(self.entry()))
        self.assertFalse(os.path.lexists(self.home / ci.RECEIPT))
        for name in self.release_files(receipt):
            self.assertTrue((self.home / name).is_file(), name)
        self.apply()
        retained = json.loads((self.home / ci.RETAINED).read_text())["files"]
        expected = {k: v for k, v in receipt["files"].items() if k != ci.ENTRY}
        self.assertEqual(retained, expected)
        self.assertEqual(self.apply()["writes"], {})

    def test_06_rolled_back_manual_entry_needs_fresh_adoption(self):
        sha = self.write_entry("manual instructions\n", 0o600)
        self.apply(adopt_sha256=sha)
        self.apply(rollback=True)
        self.assertFails("adopt-sha256", self.plan)
        self.apply(adopt_sha256=install.digest(self.entry().read_bytes()))
        self.assertTrue((self.home / ci.RECEIPT).is_file())

    def test_07_retained_versions_owned_and_scoped(self):
        self.apply()
        self.apply(rollback=True)
        catalog_path = self.home / ci.RETAINED
        catalog = json.loads(catalog_path.read_text())
        victim = self.home / sorted(catalog["files"])[0]
        original = victim.read_bytes()
        victim.write_bytes(original + b"edit\n")
        self.assertFails("modified", self.plan)
        self.assertFails("modified", self.plan, rollback=True)
        victim.write_bytes(original)
        self.plan()
        catalog["files"][".ssh/config"] = {"mode": 0o600, "sha256": "a" * 64}
        catalog_path.write_bytes(ci.encoded(catalog))
        self.assertFails("retained context ownership", self.plan)
        self.assertFails("retained context ownership", self.plan, rollback=True)

    def test_08_local_edit_blocks_update_and_rollback(self):
        self.apply()
        victim = self.home / self.release_files(self.receipt())[0]
        victim.write_text("tampered\n")
        os.chmod(victim, 0o600)
        self.assertFails("modified", self.plan)
        self.assertFails("modified", self.plan, rollback=True)

    def test_08b_mode_change_counts_as_modified(self):
        self.apply()
        victim = self.home / self.release_files(self.receipt())[0]
        os.chmod(victim, 0o644)
        self.assertFails("modified", self.plan)

    def test_verify_owned_accepts_intact_install(self):
        self.apply()
        self.assertIsNone(ci.verify_owned(self.home, ci.read_receipt(self.home)))
        self.assertIsNone(ci.verify_owned(str(self.home), ci.read_receipt(self.home)))

    def test_verify_owned_detects_edited_missing_and_mode_changes(self):
        self.apply()
        receipt = ci.read_receipt(self.home)
        victim = self.home / self.release_files(receipt)[0]
        original = victim.read_bytes()
        victim.write_text("tampered\n")
        os.chmod(victim, 0o600)
        self.assertFails("modified", ci.verify_owned, self.home, receipt)
        victim.write_bytes(original)
        os.chmod(victim, 0o644)
        self.assertFails("modified", ci.verify_owned, self.home, receipt)
        victim.unlink()
        self.assertFails("modified", ci.verify_owned, self.home, receipt)
        self.entry().write_text("edited entry\n")
        self.assertFails("modified", ci.verify_owned, self.home, receipt)

    def test_verify_owned_detects_changed_directory(self):
        self.apply()
        receipt = ci.read_receipt(self.home)
        receipt = dict(receipt, files={}, directories=list(receipt["directories"]))
        target = self.home / receipt["directories"][-1]
        shutil.rmtree(str(target))
        target.write_text("not a directory\n")
        with self.assertRaises(ValueError):
            ci.verify_owned(self.home, receipt)

    def test_09_modified_backup_blocks_rollback(self):
        self.apply()
        backup = self.home / self.receipt()["backup"]["path"]
        backup.write_text("{}")
        self.assertFails("rollback snapshot", self.plan, rollback=True)
        backup.unlink()
        self.assertFails("rollback snapshot", self.plan, rollback=True)

    def test_10_symlinked_parent_and_unowned_release(self):
        outside = self.tmp / "outside"
        outside.mkdir()
        top = self.home / ci.ENTRY.split("/")[0]
        top.symlink_to(outside)
        self.assertFails("symlink", self.plan)
        top.unlink()
        files = ci.payload(self.home)
        name = next(n for n in files if n != ci.ENTRY)
        target = self.home / name
        target.parent.mkdir(parents=True)
        target.write_bytes(files[name])
        os.chmod(target, 0o600)
        self.assertFails("unowned", self.plan)
        self.assertEqual(listing(outside), [])

    def test_12_failed_adoption_restores_original(self):
        sha = self.write_entry("original\n", 0o644)
        plan = self.plan(adopt_sha256=sha)
        real = install.atomic_write
        receipt_path = self.home / ci.RECEIPT

        def failing(path, data, mode):
            if Path(path) == receipt_path:
                raise OSError("simulated receipt failure")
            return real(path, data, mode)

        with mock.patch.object(install, "atomic_write", failing):
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(OSError) as caught:
                    install.execute(self.home, plan)
        self.assertIn("simulated receipt failure", str(caught.exception))
        self.assertEqual(self.entry().read_text(), "original\n")
        self.assertEqual(listing(self.home), sorted(ci._ancestors(ci.ENTRY) + [ci.ENTRY]))

    def test_13_rollback_keeps_unowned_files_in_owned_dirs(self):
        self.apply()
        release_file = self.home / self.release_files(self.receipt())[0]
        note = release_file.parent / "user-note.txt"
        note.write_text("keep")
        self.apply(rollback=True)
        self.assertEqual(note.read_text(), "keep")

    def test_16_deterministic_release_naming(self):
        first = ci.payload(self.home)
        second = ci.payload(self.home)
        self.assertEqual(first, second)
        other = self.tmp / "other home"
        other.mkdir()
        fp = {n.split("/")[4] for n in first if n != ci.ENTRY}
        fp_other = {n.split("/")[4] for n in ci.payload(other) if n != ci.ENTRY}
        self.assertEqual(len(fp), 1)
        self.assertRegex(next(iter(fp)), r"^[a-f0-9]{16}$")
        self.assertNotEqual(fp, fp_other)
        self.assertEqual(list(first)[-1], ci.ENTRY)

    def test_22_two_rollbacks_chain(self):
        sha = self.write_entry("manual\n", 0o640)
        self.apply(adopt_sha256=sha)
        e1 = self.entry().read_bytes()
        r1 = self.receipt()
        with self.changed_source():
            self.apply()
            self.apply(rollback=True)
            self.assertEqual(self.entry().read_bytes(), e1)
            self.assertEqual(self.receipt(), r1)
            self.apply(rollback=True)
        self.assertEqual(self.entry().read_text(), "manual\n")
        self.assertEqual(mode_of(self.entry()), 0o640)
        self.assertFalse((self.home / ci.RECEIPT).exists())

    def test_22b_two_rollbacks_from_empty_home_remove_entry(self):
        self.apply()
        with self.changed_source():
            self.apply()
            self.apply(rollback=True)
            self.apply(rollback=True)
        self.assertFalse(os.path.lexists(self.entry()))
        self.assertFalse(os.path.lexists(self.home / ci.RECEIPT))

    def test_25_modes(self):
        top = ci.ENTRY.split("/")[0]
        existing = self.home / top
        existing.mkdir(mode=0o755)
        os.chmod(existing, 0o755)
        umask = os.umask(0)
        os.umask(umask)
        plan = self.apply()
        self.apply(rollback=True)
        self.apply()
        files = list(plan["writes"]) + [ci.RETAINED]
        for name in files:
            self.assertEqual(mode_of(self.home / name), 0o600, name)
        self.assertNotIn(top, plan["create"])
        for directory in plan["create"]:
            self.assertEqual(mode_of(self.home / directory), 0o700 & ~umask, directory)
        self.assertEqual(mode_of(existing), 0o755)

    def test_26_edited_owned_entry_blocks_even_with_hash(self):
        self.apply()
        self.entry().write_text("hand edit\n")
        os.chmod(self.entry(), 0o600)
        sha = install.digest(b"hand edit\n")
        self.assertFails("modified", self.plan, adopt_sha256=sha)
        self.assertFails("modified", self.plan, rollback=True)

    def test_receipt_and_backup_shapes(self):
        sha = self.write_entry("manual\n", 0o640)
        self.apply(adopt_sha256=sha)
        receipt = self.receipt()
        self.assertEqual(receipt["format"], 1)
        self.assertIn(ci.ENTRY, receipt["files"])
        self.assertRegex(receipt["backup"]["path"], r"backups/[a-f0-9]{32}\.json$")
        snapshot = json.loads((self.home / receipt["backup"]["path"]).read_text())
        self.assertEqual(snapshot, {"entry": {"mode": 0o640, "text": "manual\n"}, "format": 1, "receipt": None})
        raw = (self.home / ci.RECEIPT).read_bytes()
        self.assertEqual(raw, ci.encoded(receipt))
        # the no-op apply writes no new backup
        before = listing(self.home / ci.STATE / "backups")
        self.apply()
        self.assertEqual(listing(self.home / ci.STATE / "backups"), before)


class ValidationTests(ContextTestCase):
    def valid_receipt(self):
        self.apply()
        return self.receipt()

    def test_11_malicious_receipt_path(self):
        receipt = self.valid_receipt()
        receipt["files"][".ssh/config"] = {"mode": 0o600, "sha256": "b" * 64}
        self.assertFails("ownership", ci.validate_receipt, receipt)

    def test_20_receipt_validation_cases(self):
        base = self.valid_receipt()
        ci.validate_receipt(json.loads(json.dumps(base)))
        name = self.release_files(base)[0]

        def variant(change):
            copy = json.loads(json.dumps(base))
            change(copy)
            return copy

        for bad_mode in (True, 420):
            bad = variant(lambda r: r["files"][name].update(mode=bad_mode))
            self.assertFails("ownership", ci.validate_receipt, bad)
        bad = variant(lambda r: r["files"][name].update(sha256="z" * 64))
        self.assertFails("ownership", ci.validate_receipt, bad)
        bad = variant(lambda r: r["files"].update({ci.LIBRARY + "/0123456789abcdef/../x.md": r["files"][name]}))
        self.assertFails("ownership", ci.validate_receipt, bad)
        bad = variant(lambda r: r["directories"].append("Documents"))
        self.assertFails("directory ownership", ci.validate_receipt, bad)
        bad = variant(lambda r: r["directories"].append(7))
        self.assertFails("directory ownership", ci.validate_receipt, bad)
        bad = variant(lambda r: r["backup"].update(path=ci.STATE + "/backups/not-hex.json"))
        self.assertFails("receipt", ci.validate_receipt, bad)
        for change in (
            lambda r: r.update(format=2),
            lambda r: r["files"].pop(ci.ENTRY),
            lambda r: r.update(directories={}),
            lambda r: r.update(backup=[]),
        ):
            self.assertRaises(ValueError, ci.validate_receipt, variant(change))
        self.assertRaises(ValueError, ci.validate_receipt, [])

    def test_20_receipt_and_catalog_must_be_private_files(self):
        self.apply()
        receipt_path = self.home / ci.RECEIPT
        os.chmod(receipt_path, 0o644)
        self.assertRaises(ValueError, self.plan)
        os.chmod(receipt_path, 0o600)
        self.apply(rollback=True)
        catalog = self.home / ci.RETAINED
        os.chmod(catalog, 0o640)
        self.assertRaises(ValueError, self.plan)
        catalog.unlink()
        catalog.mkdir()
        self.assertRaises(ValueError, self.plan)

    def test_20_receipt_directory_is_refused(self):
        (self.home / ci.RECEIPT).mkdir(parents=True)
        self.assertRaises(ValueError, self.plan)

    def test_21_rollback_preconditions(self):
        self.assertRaises(ValueError, self.plan, rollback=True)
        self.apply()
        with self.changed_source():
            self.apply()
            receipt = self.receipt()
            backup = self.home / receipt["backup"]["path"]
            snapshot = json.loads(backup.read_text())
            self.assertIsNotNone(snapshot["receipt"])

            def tamper(change):
                copy = json.loads(json.dumps(snapshot))
                change(copy)
                data = ci.encoded(copy)
                backup.write_bytes(data)
                updated = json.loads(json.dumps(receipt))
                updated["backup"]["sha256"] = install.digest(data)
                (self.home / ci.RECEIPT).write_bytes(ci.encoded(updated))

            tamper(lambda s: s.update(entry=None))
            self.assertRaises(ValueError, self.plan, rollback=True)
            tamper(lambda s: s["entry"].update(text="different\n"))
            self.assertRaises(ValueError, self.plan, rollback=True)
            tamper(lambda s: s["entry"].update(mode=0o1000))
            self.assertRaises(ValueError, self.plan, rollback=True)
            tamper(lambda s: s.update(format=3))
            self.assertRaises(ValueError, self.plan, rollback=True)
            tamper(lambda s: None)
            self.plan(rollback=True)


class RenderingTests(ContextTestCase):
    def render(self, text, relative="bootstrap.md"):
        return ci.render(text, self.home, self.home / "release", relative).decode()

    def test_placeholders(self):
        out = self.render("{{HOME}} | {{CONTEXT_ROOT}} | {{PRIVATE_ROOT}}")
        self.assertEqual(
            out,
            "%s | %s | %s" % (self.home, self.home / "release", self.home / ".config/digits/context"),
        )
        self.assertFails("Unknown", self.render, "{{NOPE}}")

    def test_18_non_placeholder_braces_left_alone(self):
        text = "{{ value }} and {{lower}} and {{Mixed}}"
        self.assertEqual(self.render(text), text)

    def test_17_link_rules(self):
        self.assertFails("Broken", self.render, "[x](../README.md)")
        self.assertFails("Broken", self.render, "[x](missing.md)")
        unchanged = (
            "[a](https://example.com/page.md) [b](image.png) [c](file:///tmp/x.md) "
            "[d](README.md \"title\") [e](<README.md>)"
        )
        self.assertEqual(self.render(unchanged), unchanged)
        out = self.render("[x](workflows/continuity.md#some-heading)")
        release = self.home / "release"
        expected = "file://" + str(release).replace(" ", "%20") + "/workflows/continuity.md#some-heading"
        self.assertEqual(out, "[x](" + expected + ")")
        out = self.render("[x](../README.md)", relative="workflows/continuity.md")
        self.assertIn("/release/README.md)", out)

    def test_17_percent_encoded_target(self):
        copy = self.copy_source()
        (copy / "my page.md").write_text("# Page\n")
        with mock.patch.object(ci, "SOURCE", copy):
            out = self.render("[x](my%20page.md)")
        self.assertIn("/release/my%20page.md)", out)
        self.assertIn("home%20with%20spaces", out)

    def test_15_broken_link_and_unknown_placeholder_before_install(self):
        with self.changed_source() as copy:
            bootstrap = copy / "bootstrap.md"
            original = bootstrap.read_text()
            bootstrap.write_text(original + "\n[Missing](missing.md)\n")
            self.assertFails("Broken", self.plan)
            bootstrap.write_text("{{UNKNOWN}}\n")
            self.assertFails("Unknown", self.plan)
            status, _, err = self.run_main("--home", str(self.home), "--apply")
            self.assertEqual(status, 1)
            self.assertIn("Unknown", err)
        self.assertEqual(listing(self.home), [])

    def test_19_bad_sources_fail_before_writing(self):
        with self.changed_source() as copy:
            (copy / "version.json").write_text('{"version": "1.0"}\n')
            self.assertRaises(ValueError, self.plan)
        shutil.rmtree(str(self.tmp / "source-copy"))
        with self.changed_source() as copy:
            (copy / "extra.md").symlink_to(copy / "README.md")
            self.assertFails("symlink", self.plan)
        shutil.rmtree(str(self.tmp / "source-copy"))
        with self.changed_source() as copy:
            (copy / "bootstrap.md").unlink()
            self.assertRaises(ValueError, self.plan)
        self.assertEqual(listing(self.home), [])


class CorpusTests(unittest.TestCase):
    def pages(self):
        return {p.relative_to(CONTEXT).as_posix(): p for p in sorted(CONTEXT.rglob("*.md"))}

    def test_14_expected_files(self):
        self.assertEqual(set(self.pages()), EXPECTED_PAGES)
        self.assertEqual(json.loads((CONTEXT / "version.json").read_text()), {"version": "1.6.0"})

    def test_14_line_limit_and_metadata(self):
        for name, path in self.pages().items():
            text = path.read_text()
            self.assertLessEqual(len(text.splitlines()), 200, name)
            self.assertTrue(text.startswith("# "), name)
            self.assertNotIn("\n@", "\n" + "\n".join(l.lstrip() for l in text.splitlines()), name)
            self.assertIsNone(HOME_PATH_RE.search(text), name)
            if name == "bootstrap.md":
                continue
            for marker in METADATA:
                self.assertIn(marker, text, (name, marker))
            self.assertIn("Reviewed: 2026-11-16", text, name)

    def test_14_renders_with_any_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home with spaces"
            home.mkdir()
            for name, path in self.pages().items():
                out = ci.render(path.read_text(), home, home / "release", name).decode()
                self.assertNotIn("{{", out, name)
            ci.payload(home)

    def test_14_bootstrap_word_budget(self):
        words = len((CONTEXT / "bootstrap.md").read_text().split())
        self.assertLessEqual(words, 10000)
        if words > 3000:
            warnings.warn("bootstrap.md has %d words; keep it short" % words)

    def test_14_routing_fixtures(self):
        cases = json.loads(FIXTURES.read_text())
        self.assertEqual(len(cases), 42)
        bootstrap = (CONTEXT / "bootstrap.md").read_text()
        ids = set()
        for case in cases:
            self.assertEqual(set(case), {"id", "prompt", "routes", "expected"})
            self.assertRegex(case["id"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertNotIn(case["id"], ids)
            ids.add(case["id"])
            for route in case["routes"]:
                self.assertTrue((CONTEXT / route).is_file(), route)
                self.assertIn(route, bootstrap, route)
        self.assertTrue(any(not case["routes"] for case in cases))

    def test_anchors_match_headings(self):
        link_re = re.compile(r"\]\(([^\s)#:]+\.md)#([^\s)]+)\)")
        for name, path in self.pages().items():
            for target, anchor in link_re.findall(path.read_text()):
                page = (path.parent / target).resolve()
                headings = [slug(line[3:]) for line in page.read_text().splitlines() if line.startswith("## ")]
                self.assertIn(anchor, headings, (name, target, anchor))

    def test_bootstrap_has_no_binding_values(self):
        bootstrap = (CONTEXT / "bootstrap.md").read_text()
        for value in ("exampleorg-producer", "ADHOC_XS", "PIPELINE_L", "#example-reviews"):
            self.assertNotIn(value, bootstrap)

    def test_owned_files_have_no_home_paths(self):
        owned = [ROOT / "context_install.py", FIXTURES, Path(__file__)]
        owned += sorted((ROOT / "examples" / "private-bindings").glob("*.md"))
        for path in owned:
            self.assertIsNone(HOME_PATH_RE.search(path.read_text()), path)


class ClaudeHostMixin:
    """Run a test class against the Claude Code layout instead of Copilot's."""

    def setUp(self):
        super().setUp()
        ci.use_host("claude")
        self.addCleanup(ci.use_host, "copilot")


class ClaudeInstallCycleTests(ClaudeHostMixin, InstallCycleTests):
    pass


class ClaudeValidationTests(ClaudeHostMixin, ValidationTests):
    pass


class ClaudeHostTests(ContextTestCase):
    def test_layout_is_separate_from_copilot_and_user_files(self):
        self.assertEqual(ci.HOSTS["claude"]["entry"], ".claude/digits/CLAUDE.md")
        self.assertEqual(ci.CLAUDE_IMPORT, "@~/" + ci.HOSTS["claude"]["entry"])
        user_memory = self.home / ".claude" / "CLAUDE.md"
        user_memory.parent.mkdir()
        user_memory.write_text("mine\n")
        status, out, err = self.run_main("--home", str(self.home), "--host", "claude", "--apply")
        self.assertEqual(status, 0, err)
        self.assertIn(ci.CLAUDE_IMPORT, out)
        self.assertIn("never edits your", out)
        self.assertIn("ln -s ~/" + ci.HOSTS["claude"]["entry"], out)
        self.assertEqual(user_memory.read_text(), "mine\n")
        self.assertFalse(os.path.lexists(self.home / ".copilot"))
        entry = (self.home / ".claude" / "digits" / "CLAUDE.md").read_text()
        self.assertIn("Generated Digits context", entry)
        self.assertIn(str(self.home / ".claude" / "digits" / "context" / "releases"), entry)
        self.assertTrue((self.home / ".local/state/digits/context-claude/receipt.json").is_file())

    def test_hosts_install_side_by_side(self):
        status, _, err = self.run_main("--home", str(self.home), "--apply")
        self.assertEqual(status, 0, err)
        copilot_receipt = (self.home / ".local/state/digits/context/receipt.json").read_bytes()
        status, _, err = self.run_main("--home", str(self.home), "--host", "claude", "--apply")
        self.assertEqual(status, 0, err)
        self.assertEqual((self.home / ".local/state/digits/context/receipt.json").read_bytes(), copilot_receipt)
        status, _, err = self.run_main("--home", str(self.home), "--host", "claude", "--rollback", "--apply")
        self.assertEqual(status, 0, err)
        self.assertFalse(os.path.lexists(self.home / ".claude/digits/CLAUDE.md"))
        self.assertTrue((self.home / ".copilot/copilot-instructions.md").is_file())
        self.assertEqual(ci.HOST, "copilot")

    def test_rollback_prints_no_claude_note(self):
        status, _, err = self.run_main("--home", str(self.home), "--host", "claude", "--apply")
        self.assertEqual(status, 0, err)
        status, out, err = self.run_main("--home", str(self.home), "--host", "claude", "--rollback")
        self.assertEqual(status, 0, err)
        self.assertNotIn(ci.CLAUDE_IMPORT, out)

    def test_copilot_output_has_no_claude_note(self):
        status, out, err = self.run_main("--home", str(self.home))
        self.assertEqual(status, 0, err)
        self.assertNotIn(ci.CLAUDE_IMPORT, out)


if __name__ == "__main__":
    unittest.main()
