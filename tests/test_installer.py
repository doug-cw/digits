"""Acceptance tests for the workbench installer (install.py)."""

import contextlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import install  # noqa: E402

LAUNCHER = ".local/bin/ai-agents"
VIEWER = ".local/bin/md-view"
CONF = ".tmux/ai-agents.conf"


def no_prerequisites(*_host):
    return None


class InstallerTestCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="digits-installer-"))
        self.addCleanup(shutil.rmtree, str(self.home), True)
        patcher = mock.patch.object(install, "check_prerequisites", no_prerequisites)
        patcher.start()
        self.addCleanup(patcher.stop)

    def listing(self):
        return sorted(
            str(path.relative_to(self.home)) for path in self.home.rglob("*")
        )

    def snapshot(self):
        result = {}
        for path in self.home.rglob("*"):
            relative = str(path.relative_to(self.home))
            if path.is_symlink():
                result[relative] = ("link", os.readlink(str(path)))
            elif path.is_file():
                result[relative] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
            else:
                result[relative] = ("dir",)
        return result

    def install(self, source=None):
        install.execute(self.home, install.build_plan(self.home, source=source))

    def uninstall(self):
        install.execute(self.home, install.build_plan(self.home, uninstall=True))

    def receipt(self):
        return json.loads((self.home / install.RECEIPT).read_text())

    def write_receipt(self, receipt):
        (self.home / install.RECEIPT).write_text(json.dumps(receipt))

    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = install.main(["--home", str(self.home), *arguments])
        return code, out.getvalue(), err.getvalue()


class ReferenceTests(InstallerTestCase):
    def test_38_preview_changes_nothing(self):
        code, out, _err = self.run_main()
        self.assertEqual(code, 0)
        self.assertIn("WRITE", out)
        self.assertEqual(self.listing(), [])

    def test_39_install_matches_sources_and_uninstall_empties_home(self):
        self.install()
        for source, destination, mode in install.FILES:
            installed = self.home / destination
            self.assertEqual(installed.read_bytes(), (REPO / source).read_bytes())
            self.assertEqual(stat.S_IMODE(installed.stat().st_mode), mode)
        second = install.build_plan(self.home)
        self.assertEqual(second["writes"], {})
        self.assertEqual(second["create"], [])
        for absent in (
            ".tmux.conf",
            ".tmux/ai-agents-shortcuts.conf",
            ".config/ghostty/config",
            ".copilot/settings.json",
        ):
            self.assertFalse(os.path.lexists(str(self.home / absent)), absent)
        self.uninstall()
        self.assertEqual(self.listing(), [])

    def test_40_foreign_file_not_in_receipt(self):
        self.install()
        receipt = self.receipt()
        del receipt["files"][VIEWER]
        self.write_receipt(receipt)
        (self.home / VIEWER).write_text("foreign\n")
        with self.assertRaisesRegex(ValueError, "unowned"):
            install.build_plan(self.home)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.uninstall()
        self.assertFalse((self.home / LAUNCHER).exists())
        self.assertEqual((self.home / VIEWER).read_text(), "foreign\n")

    def test_40_missing_unlisted_file_is_reinstalled(self):
        self.install()
        receipt = self.receipt()
        del receipt["files"][VIEWER]
        self.write_receipt(receipt)
        (self.home / VIEWER).unlink()
        self.install()
        self.assertEqual(
            (self.home / VIEWER).read_bytes(), (REPO / "bin/md-view").read_bytes()
        )
        self.assertIn(VIEWER, self.receipt()["files"])

    def test_41_preexisting_configuration_is_unowned(self):
        (self.home / ".tmux").mkdir()
        (self.home / CONF).write_text("mine\n")
        with self.assertRaisesRegex(ValueError, "unowned"):
            install.build_plan(self.home)
        self.assertEqual((self.home / CONF).read_text(), "mine\n")
        self.assertFalse((self.home / ".local").exists())

    def test_42_modified_file_blocks_install_and_uninstall(self):
        self.install()
        conf = self.home / CONF
        conf.write_text(conf.read_text() + "# my edit\n")
        receipt_before = (self.home / install.RECEIPT).read_bytes()
        for uninstall in (False, True):
            with self.assertRaisesRegex(ValueError, "modified"):
                install.build_plan(self.home, uninstall=uninstall)
        self.assertTrue(conf.read_text().endswith("# my edit\n"))
        self.assertEqual((self.home / install.RECEIPT).read_bytes(), receipt_before)

    def test_43_user_files_survive_uninstall(self):
        (self.home / ".copilot").mkdir()
        settings = self.home / ".copilot/settings.json"
        settings.write_text('{"theme": "dark"}\n')
        self.install()
        (self.home / "left_pinky/notes.txt").write_text("keep\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.uninstall()
        self.assertEqual((self.home / "left_pinky/notes.txt").read_text(), "keep\n")
        self.assertEqual(settings.read_text(), '{"theme": "dark"}\n')

    def test_44_symlinked_tmux_directory_is_refused(self):
        outside = Path(tempfile.mkdtemp(prefix="digits-outside-"))
        self.addCleanup(shutil.rmtree, str(outside), True)
        (self.home / ".tmux").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            install.build_plan(self.home)
        self.assertEqual(list(outside.iterdir()), [])

    def test_45_failed_second_write_rolls_back_fresh_install(self):
        real = install.atomic_write
        calls = []

        def failing(path, data, mode):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("simulated write failure")
            return real(path, data, mode)

        plan = install.build_plan(self.home)
        with mock.patch.object(install, "atomic_write", failing):
            with self.assertRaisesRegex(OSError, "simulated"):
                install.execute(self.home, plan)
        self.assertEqual(self.listing(), [])

    def test_46_deleted_launcher_is_restored(self):
        self.install()
        (self.home / LAUNCHER).unlink()
        self.install()
        self.assertEqual(
            (self.home / LAUNCHER).read_bytes(), (REPO / "bin/ai-agents").read_bytes()
        )

    def test_47_uninstall_without_receipt_removes_nothing(self):
        (self.home / ".tmux").mkdir()
        (self.home / CONF).write_text("mine\n")
        plan = install.build_plan(self.home, uninstall=True)
        self.assertEqual(plan["remove"], [])
        install.execute(self.home, plan)
        self.assertEqual((self.home / CONF).read_text(), "mine\n")

    def test_48_command_line_install_and_uninstall(self):
        code, _out, _err = self.run_main("--apply")
        self.assertEqual(code, 0)
        self.assertTrue((self.home / install.RECEIPT).is_file())
        code, _out, _err = self.run_main("--uninstall", "--apply")
        self.assertEqual(code, 0)
        self.assertEqual(self.listing(), [])

    def test_49_symlinked_environment_blocks_uninstall(self):
        self.install()
        outside = Path(tempfile.mkdtemp(prefix="digits-outside-"))
        self.addCleanup(shutil.rmtree, str(outside), True)
        (self.home / "right_pinky").rmdir()
        (self.home / "right_pinky").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symlink"):
            install.build_plan(self.home, uninstall=True)
        self.assertTrue((self.home / LAUNCHER).is_file())

    def test_50_failed_receipt_write_restores_previous_bytes(self):
        self.install()
        before_launcher = (self.home / LAUNCHER).read_bytes()
        before_receipt = (self.home / install.RECEIPT).read_bytes()
        source = Path(tempfile.mkdtemp(prefix="digits-source-"))
        self.addCleanup(shutil.rmtree, str(source), True)
        for relative, _destination, _mode in install.FILES:
            (source / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(REPO / relative), str(source / relative))
        with open(str(source / "bin/ai-agents"), "a") as handle:
            handle.write("# updated\n")
        plan = install.build_plan(self.home, source=source)
        self.assertEqual(set(plan["writes"]), {LAUNCHER, install.RECEIPT})
        real = install.atomic_write
        failed = []

        def failing(path, data, mode):
            if Path(path).name == "dashboard.json" and not failed:
                failed.append(path)
                raise OSError("simulated receipt failure")
            return real(path, data, mode)

        with mock.patch.object(install, "atomic_write", failing):
            with self.assertRaisesRegex(OSError, "simulated"):
                install.execute(self.home, plan)
        self.assertEqual((self.home / LAUNCHER).read_bytes(), before_launcher)
        self.assertEqual((self.home / install.RECEIPT).read_bytes(), before_receipt)


class EdgeCaseTests(InstallerTestCase):
    def test_80_invalid_receipts_fail_every_plan(self):
        self.install()
        good = self.receipt()
        record = good["files"][LAUNCHER]

        def variant(change):
            receipt = json.loads(json.dumps(good))
            change(receipt)
            return receipt

        variants = [
            variant(lambda r: r.update(version=2)),
            variant(lambda r: r["files"].update({".local/bin/other": record})),
            variant(lambda r: r["directories"].append("Documents")),
            variant(lambda r: r["files"][LAUNCHER].update(sha256="z" * 64)),
            variant(lambda r: r["files"][LAUNCHER].update(mode=0o600)),
            variant(lambda r: r["files"][LAUNCHER].update(mode=True)),
        ]
        for receipt in variants:
            self.write_receipt(receipt)
            before = self.snapshot()
            for uninstall in (False, True):
                with self.subTest(receipt=receipt, uninstall=uninstall):
                    code, _out, err = self.run_main(
                        *(["--uninstall"] if uninstall else []), "--apply"
                    )
                    self.assertEqual(code, 1)
                    self.assertIn("receipt", err)
                    self.assertEqual(self.snapshot(), before)

    def test_81_non_empty_created_directory_is_kept(self):
        self.install()
        (self.home / ".tmux/other.conf").write_text("x\n")
        code, out, _err = self.run_main("--uninstall", "--apply")
        self.assertEqual(code, 0)
        self.assertIn("KEEP non-empty directory {}".format(self.home / ".tmux"), out)
        self.assertEqual((self.home / ".tmux/other.conf").read_text(), "x\n")

    def test_82_lock_held_by_another_installer(self):
        import fcntl

        descriptor = os.open(str(self.home), os.O_RDONLY)
        self.addCleanup(os.close, descriptor)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        code, _out, err = self.run_main("--apply")
        self.assertEqual(code, 1)
        self.assertIn("Dashboard installer:", err)
        self.assertEqual(self.listing(), [])

    def test_83_prerequisites_block_install_but_not_uninstall(self):
        mock.patch.stopall()
        self.install()
        with mock.patch.object(install.shutil, "which", lambda name: None), mock.patch.object(
            install.platform, "system", lambda: "Darwin"
        ):
            for arguments in ((), ("--apply",)):
                code, _out, err = self.run_main(*arguments)
                self.assertEqual(code, 1)
                self.assertIn("tmux, node, copilot", err)
        with mock.patch.object(install.platform, "system", lambda: "Linux"):
            code, _out, err = self.run_main()
            self.assertEqual(code, 1)
            self.assertIn("macOS", err)
            code, _out, _err = self.run_main("--uninstall", "--apply")
            self.assertEqual(code, 0)
        self.assertEqual(self.listing(), [])


class ClaudeHostTests(InstallerTestCase):
    HOOK = ".claude/hooks/digits-env-dashboard.py"
    EXTENSION = ".copilot/extensions/env-dashboard/extension.mjs"

    def install_host(self, host):
        install.execute(self.home, install.build_plan(self.home, host=host))

    def test_91_claude_host_installs_hook_not_extension(self):
        code, out, _err = self.run_main("--host", "claude")
        self.assertEqual(code, 0)
        self.assertIn(self.HOOK, out)
        self.assertIn("claude/settings.json", out)
        self.assertEqual(self.listing(), [])
        self.assertEqual(self.run_main("--host", "claude", "--apply")[0], 0)
        hook = self.home / self.HOOK
        self.assertEqual(hook.read_bytes(), (REPO / "claude/hooks/env_dashboard.py").read_bytes())
        self.assertEqual(stat.S_IMODE(hook.stat().st_mode), 0o755)
        self.assertFalse(os.path.lexists(str(self.home / ".copilot")))
        self.assertFalse(os.path.lexists(str(self.home / ".claude/settings.json")))
        for environment in install.ENVIRONMENTS:
            self.assertTrue((self.home / environment).is_dir(), environment)
        again = install.build_plan(self.home, host="claude")
        self.assertEqual((again["writes"], again["create"]), ({}, []))

    def test_92_switching_hosts_keeps_ownership_and_uninstalls_everything(self):
        self.install_host("copilot")
        self.install_host("claude")
        files = self.receipt()["files"]
        self.assertIn(self.EXTENSION, files)
        self.assertIn(self.HOOK, files)
        self.assertTrue((self.home / self.EXTENSION).is_file())
        self.install_host("copilot")
        self.assertIn(self.HOOK, self.receipt()["files"])
        self.uninstall()
        self.assertEqual(self.listing(), [])

    def test_92_uninstall_mentions_claude_settings_only_with_the_hook(self):
        note = "Remove the Digits hooks from ~/.claude/settings.json"
        self.install_host("copilot")
        code, out, _err = self.run_main("--uninstall", "--apply")
        self.assertEqual(code, 0)
        self.assertNotIn(note, out)
        self.install_host("claude")
        code, out, _err = self.run_main("--uninstall", "--apply")
        self.assertEqual(code, 0)
        self.assertIn(note, out)

    def test_93_host_prerequisites(self):
        mock.patch.stopall()
        with mock.patch.object(install.shutil, "which", lambda name: None), mock.patch.object(
            install.platform, "system", lambda: "Darwin"
        ):
            code, _out, err = self.run_main("--host", "claude")
            self.assertEqual(code, 1)
            self.assertIn("tmux, claude, python3", err)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                install.main(["--host", "codex"])


if __name__ == "__main__":
    unittest.main()
