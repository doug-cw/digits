"""Acceptance tests for the ai-agents launcher, the dashboard configuration,
the shortcut fragments and md-view, run against isolated tmux servers.

Every test uses a temporary home and its own tmux socket (``tmux -L <unique>
-f /dev/null``); the user's tmux server, home and configuration are never
touched.
"""

import contextlib
import importlib.machinery
import importlib.util
import io
import itertools
import json
import os
import pty
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import threading
import time
import fcntl
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import install  # noqa: E402

REAL_TMUX = shutil.which("tmux")
TIMEOUT = 10.0
POLL_INTERVAL = 0.05
# tmux folds a press that arrives within about 300 ms of the previous one into
# a double or triple click; successive clicks are spaced beyond that window.
DOUBLE_CLICK_GUARD = 0.35
# Alt+z, bound by ClientTests.sync() to record that tmux reached it.
BARRIER_KEY = b"\x1bz"
_COUNTER = itertools.count()
NAMES = [
    "Left Pinky", "Left Ring", "Left Middle", "Left Pointer", "Left Thumb",
    "Right Thumb", "Right Pointer", "Right Middle", "Right Ring", "Right Pinky",
]


def load_module(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def ghostty_sequences():
    """Map Ghostty key names to the bytes Ghostty sends, from the fragment."""
    result = {}
    text = (REPO / "terminal/ghostty-keybindings.conf").read_text()
    for line in text.splitlines():
        match = re.match(r"keybind = (\S+?)=csi:(\S+)$", line)
        if match:
            result[match.group(1)] = b"\x1b[" + match.group(2).encode()
    return result


def poll(predicate, timeout=TIMEOUT):
    """Re-evaluate ``predicate`` until it is truthy or ``timeout`` expires."""
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            return value
        time.sleep(POLL_INTERVAL)


class Client:
    """A tmux client attached through a pseudo-terminal of 240x40."""

    def __init__(self, case, target):
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 240, 0, 0))
        env = dict(case.env, TERM="xterm-256color")
        self.process = subprocess.Popen(
            [str(case.wrapper), "attach-session", "-t", target],
            stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True,
        )
        os.close(slave)
        self.master = master
        self.buffer = bytearray()
        self.lock = threading.Lock()
        self.position = 0
        self.closed = False
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()
        self.case = case
        self.clicked = False
        self.name = poll(self._find_name)
        if not self.name:
            raise AssertionError("tmux client did not attach")
        # The first full draw ends with the status line's hotkeys button.
        if not self.wait_for("hotkeys"):
            raise AssertionError("tmux client did not draw its status line")
        self.mark()

    def _find_name(self):
        listing = self.case.tmux_raw("list-clients", "-F", "#{client_pid} #{client_name}")
        for line in listing.stdout.splitlines():
            pid, _, name = line.partition(" ")
            if pid == str(self.process.pid):
                return name
        return None

    def _drain(self):
        while True:
            try:
                data = os.read(self.master, 65536)
            except OSError:
                return
            if not data:
                return
            with self.lock:
                self.buffer.extend(data)

    def mark(self):
        with self.lock:
            self.position = len(self.buffer)

    def output(self):
        with self.lock:
            return bytes(self.buffer[self.position:])

    def wait_for(self, *texts):
        wanted = [text.encode() for text in texts]
        return poll(lambda: all(text in self.output() for text in wanted))

    def send(self, data):
        os.write(self.master, data)

    def click(self, column, row, button=0):
        if self.clicked:
            self._outlast_double_click()
        self.send("\x1b[<{};{};{}M".format(button, column, row).encode())
        self.send("\x1b[<{};{};{}m".format(button, column, row).encode())
        self.clicked = True

    def _outlast_double_click(self):
        """Wait until tmux can no longer pair the next press with the last one.

        Callers observe each click's effect before clicking again, so the
        server has processed it. ``client_activity`` is the whole second of the
        last input tmux processed; once the clock is more than one second plus
        the guard past it, the previous click is older than the guard.
        """
        activity = int(self.case.tmux("display-message", "-p", "-c", self.name, "#{client_activity}"))
        if not poll(lambda: time.time() >= activity + 1 + DOUBLE_CLICK_GUARD):
            raise AssertionError("clock did not pass the tmux double-click window")

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        try:
            os.close(self.master)
        except OSError:
            pass
        self.reader.join(1)


@unittest.skipIf(REAL_TMUX is None, "tmux is not installed")
class TmuxTestCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="digits-launcher-")))
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.home = self.root / "home"
        self.home.mkdir()
        for name in install.ENVIRONMENTS:
            (self.home / name).mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.socket = "digits-test-{}-{}".format(os.getpid(), next(_COUNTER))
        self.wrapper = self.bin / "tmux"
        self.wrapper.write_text(
            '#!/bin/sh\nunset TMUX TMUX_PANE\nexec "{}" -L "{}" -f /dev/null "$@"\n'.format(
                REAL_TMUX, self.socket
            )
        )
        self.wrapper.chmod(0o755)
        self.env = {
            name: value for name, value in os.environ.items()
            if not name.startswith("TMUX") and not name.startswith("VSCODE_")
        }
        self.env["HOME"] = str(self.home)
        self.env["PATH"] = os.pathsep.join(
            [str(self.bin), os.path.dirname(sys.executable), "/usr/bin", "/bin"]
        )
        self.tmux_raw("new-session", "-d", "-s", "unrelated", "-x", "240", "-y", "40", "/bin/sh")
        self.addCleanup(self.tmux_raw, "kill-server")
        self.clients = []
        self.addCleanup(self._close_clients)
        self.launcher = load_module(
            REPO / "bin/ai-agents", "ai_agents_under_test_{}".format(next(_COUNTER))
        )
        self.launcher.HOME = self.home
        self.launcher.CONFIG = REPO / "terminal/ai-agents.conf"
        self.launcher.FISH = "/bin/sh"
        self.launcher.TMUX = str(self.wrapper)

    def _close_clients(self):
        for client in self.clients:
            client.close()

    # --- helpers -----------------------------------------------------------

    def tmux_raw(self, *args):
        return subprocess.run(
            [str(self.wrapper), *args], capture_output=True, text=True,
            env=getattr(self, "env", None), stdin=subprocess.DEVNULL,
        )

    def tmux(self, *args):
        result = self.tmux_raw(*args)
        if result.returncode != 0:
            raise AssertionError("tmux {} failed: {}".format(args, result.stderr))
        return result.stdout.rstrip("\n")

    def ensure(self):
        self.launcher.ensure_session()

    def listing(self):
        return self.tmux(
            "list-windows", "-t", "=ai-agents:", "-F",
            "#{window_index} #{window_name} #{window_id} #{pane_id} #{pane_pid}",
        ).splitlines()

    def active_window(self, session="ai-agents"):
        return int(self.tmux("display-message", "-p", "-t", "={}:".format(session), "#{window_index}"))

    def wait_window(self, index):
        return poll(lambda: self.active_window() == index)

    def window(self, index):
        return "=ai-agents:{}".format(index)

    def pane_set(self, index, option, value):
        self.tmux("set-option", "-p", "-t", self.window(index), option, str(value))

    def pane_unset(self, index, option):
        self.tmux("set-option", "-p", "-u", "-t", self.window(index), option)

    def pane_get(self, index, option):
        return self.tmux("show-options", "-p", "-qv", "-t", self.window(index), option)

    def evaluate(self, index, text):
        return self.tmux("display-message", "-p", "-t", self.window(index), text)

    def evaluate_together(self, index, *formats):
        """Expand several formats in one tmux evaluation and split the results."""
        separator = "<digits-field-separator>"
        values = self.evaluate(index, separator.join(formats)).split(separator)
        self.assertEqual(len(values), len(formats), values)
        return values

    def state(self, index):
        return self.evaluate(index, "#{E:@hand-status-state}")

    def simulate_copilot(self):
        for name in ("activity", "timer", "title"):
            option = "@hand-status-" + name
            value = self.tmux("show-options", "-qv", "-t", "=ai-agents:", option)
            self.assertIn("#{pane_current_command}", value)
            self.tmux(
                "set-option", "-t", "=ai-agents:", option,
                value.replace("#{pane_current_command}", "copilot"),
            )

    def install_workbench(self):
        with mock.patch.object(install, "check_prerequisites", lambda *_host: None):
            install.execute(self.home, install.build_plan(self.home))
        self.launcher.CONFIG = self.home / ".tmux/ai-agents.conf"
        self.tmux("set-environment", "-g", "HOME", str(self.home))
        self.tmux("set-environment", "-g", "PATH", self.env["PATH"])

    def attach(self, target="=ai-agents:"):
        client = Client(self, target)
        self.clients.append(client)
        return client

    def run_cli(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(REPO / "bin/ai-agents"), *args],
            capture_output=True, text=True, env=env or self.cli_env(),
            stdin=subprocess.DEVNULL, timeout=60,
        )

    def cli_env(self):
        fish = self.bin / "fish"
        if not fish.exists():
            fish.write_text("#!/bin/sh\nexec /bin/sh \"$@\"\n")
            fish.chmod(0o755)
        return dict(self.env)

    def fake_code(self, exit_code=0, stderr=""):
        directory = self.root / "codebin"
        directory.mkdir(exist_ok=True)
        marker = self.root / "code-calls.jsonl"
        script = directory / "code"
        script.write_text(
            "#!{python}\n"
            "import json, os, sys\n"
            "with open({marker!r}, 'a') as handle:\n"
            "    handle.write(json.dumps({{'args': sys.argv[1:],"
            " 'ipc': os.environ.get('VSCODE_IPC_HOOK_CLI', ''),"
            " 'env': sorted(os.environ)}}) + '\\n')\n"
            "sys.stderr.write({stderr!r})\n"
            "sys.exit({code})\n".format(
                python=sys.executable, marker=str(marker), stderr=stderr, code=exit_code
            )
        )
        script.chmod(0o755)
        self.env["PATH"] = str(directory) + os.pathsep + self.env["PATH"]
        return marker

    @staticmethod
    def calls(marker):
        if not marker.exists():
            return []
        return [json.loads(line) for line in marker.read_text().splitlines()]


class SessionTests(TmuxTestCase):
    def test_51_windows_and_reconnect(self):
        self.ensure()
        names = [line.split(" ", 1)[1].rsplit(" ", 3)[0] for line in self.listing()]
        indices = [int(line.split(" ", 1)[0]) for line in self.listing()]
        self.assertEqual(indices, list(range(1, 11)))
        self.assertEqual(names, NAMES)
        self.tmux("select-window", "-t", self.window(7))
        before = self.listing()
        self.ensure()
        self.assertEqual(self.listing(), before)
        self.assertEqual(self.active_window(), 7)
        self.assertEqual(self.tmux("show-options", "-v", "-t", "=ai-agents:", "status"), "5")

    def test_52_killed_window_is_recreated_alone(self):
        self.ensure()
        before = self.listing()
        self.tmux("kill-window", "-t", self.window(7))
        self.ensure()
        after = self.listing()
        self.assertEqual(len(after), 10)
        self.assertEqual(
            [line for line in after if not line.startswith("7 ")],
            [line for line in before if not line.startswith("7 ")],
        )
        self.assertNotIn(next(line for line in after if line.startswith("7 ")), before)

    def test_53_global_options_untouched_with_installed_configuration(self):
        self.tmux("set-option", "-g", "renumber-windows", "on")
        self.tmux("set-option", "-g", "mouse", "off")
        self.install_workbench()
        self.ensure()
        before = self.listing()
        self.tmux("kill-window", "-t", self.window(7))
        self.ensure()
        after = self.listing()
        self.assertEqual(len(after), 10)
        self.assertEqual(
            [line for line in after if not line.startswith("7 ")],
            [line for line in before if not line.startswith("7 ")],
        )
        self.assertEqual(self.tmux("show-options", "-v", "-t", "=ai-agents:", "mouse"), "on")
        self.assertEqual(self.tmux("show-options", "-gv", "mouse"), "off")
        self.assertEqual(self.tmux("show-options", "-gv", "renumber-windows"), "on")
        self.assertFalse(os.path.lexists(str(self.home / ".tmux.conf")))

    def test_54_unmanaged_session_is_refused(self):
        self.tmux("new-session", "-d", "-s", "ai-agents", "/bin/sh")
        before = self.listing()
        with self.assertRaisesRegex(self.launcher.LauncherError, "unmanaged"):
            self.ensure()
        self.assertEqual(self.listing(), before)

    def test_55_renamed_window_is_refused(self):
        self.ensure()
        self.tmux("rename-window", "-t", self.window(3), "Other work")
        before = self.listing()
        with self.assertRaisesRegex(self.launcher.LauncherError, "^Unexpected window =ai-agents:3"):
            self.ensure()
        self.assertEqual(self.listing(), before)

    def test_56_killed_session_is_recreated(self):
        self.ensure()
        before = set(self.listing())
        self.tmux("kill-session", "-t", "=ai-agents")
        self.ensure()
        after = self.listing()
        self.assertEqual(len(after), 10)
        self.assertFalse(before & set(after))
        self.assertTrue(poll(lambda: self.state(1) == "READY"), self.state(1))


class DashboardTests(TmuxTestCase):
    def setUp(self):
        super().setUp()
        self.ensure()

    def test_57_timers_and_cells(self):
        self.simulate_copilot()
        now = int(time.time())
        self.pane_set(1, "@env-copilot-since", now - 83)
        for label, colour in (("WORKING", "colour75"), ("SUBAGENTS", "colour141"), ("WATCHING", "colour117")):
            self.pane_set(1, "@env-copilot-state", label)
            # One evaluation, so the timer and the cell see the same second.
            timer, cell = self.evaluate_together(1, "#{E:@hand-status-timer}", "#{E:@hand-status-cell}")
            self.assertRegex(timer, r"^1m2[3-9]s$")
            self.assertIn(timer, cell)
            self.assertIn("#[range=window|1]", cell)
            self.assertIn("#[fg={}]{}".format(colour, label), cell)
        clock = time.strftime("%H:%M", time.localtime(1000000000))
        self.pane_set(1, "@env-copilot-state", "YOUR TURN")
        self.pane_set(1, "@env-copilot-since", 1000000000)
        self.pane_set(1, "@env-copilot-took", 252)
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-timer}"), "4m12s @" + clock)
        self.assertIn(
            "#[fg=colour226]YOUR TURN  4m12s @{} ".format(clock),
            self.evaluate(1, "#{E:@hand-status-cell}"),
        )
        self.pane_unset(1, "@env-copilot-took")
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-timer}"), "@" + clock)
        self.pane_set(1, "@env-copilot-since", int(time.time()) - 83)
        self.pane_set(1, "@env-waiting-reason", "review")
        self.assertRegex(self.evaluate(1, "#{E:@hand-status-timer}"), r"^1m2[3-9]s ago$")
        self.assertIn("#[fg=colour244]WAITING", self.evaluate(1, "#{E:@hand-status-cell}"))
        self.pane_unset(1, "@env-waiting-reason")
        for label in ("NEEDS YOU", "ERROR", "READY"):
            self.pane_set(1, "@env-copilot-state", label)
            self.assertEqual(self.evaluate(1, "#{E:@hand-status-timer}"), "", label)
        self.pane_set(1, "@env-copilot-state", "YOUR TURN")
        self.pane_unset(1, "@env-copilot-since")
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-timer}"), "")
        self.assertEqual(self.tmux("show-options", "-v", "-t", "=ai-agents:", "status-interval"), "1")

    def test_58_titles(self):
        self.simulate_copilot()
        cases = {
            "GitHub Copilot": "",
            "Fix flaky test - GitHub Copilot": "Fix flaky test",
            "GitHub Copilot setup - GitHub Copilot": "GitHub Copilot setup",
            "GitHub Copilotish": "GitHub Copilotish",
        }
        for title, expected in cases.items():
            self.tmux("select-pane", "-t", self.window(1), "-T", title)
            self.assertEqual(self.evaluate(1, "#{E:@hand-status-title}"), expected, title)

    def test_62_waiting_reason_in_title(self):
        self.simulate_copilot()
        self.tmux("select-pane", "-t", self.window(1), "-T", "Ship it - GitHub Copilot")
        self.pane_set(1, "@env-copilot-state", "YOUR TURN")
        self.pane_set(1, "@env-copilot-reason", "retired")
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-title}"), "Ship it")
        self.pane_set(1, "@env-waiting-reason", "review #[fg=red]")
        expected = "Waiting on: review # [fg=red] | Ship it"
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-title}"), expected)
        self.pane_set(1, "@env-copilot-state", "REVIEW")
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-title}"), expected)
        self.pane_unset(1, "@env-waiting-reason")
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-title}"), "Ship it")

    def test_69_automatic_clearing(self):
        self.simulate_copilot()

        def prepare():
            for index in (1, 6):
                self.pane_set(index, "@env-copilot-state", "YOUR TURN")
                self.pane_set(index, "@env-dashboard-owner", "old")
                self.pane_set(index, "@env-waiting-owner", "old")
                self.pane_set(index, "@env-waiting-reason", "review")

        for label in ("NEEDS YOU", "ERROR", "WORKING", "SUBAGENTS", "UNKNOWN"):
            prepare()
            self.pane_set(6, "@env-copilot-state", label)
            self.assertEqual(self.pane_get(6, "@env-waiting-reason"), "", label)
            self.assertEqual(self.pane_get(1, "@env-waiting-reason"), "review", label)
        prepare()
        self.pane_set(6, "@env-dashboard-owner", "new")
        self.assertEqual(self.pane_get(6, "@env-waiting-reason"), "")
        self.assertEqual(self.pane_get(1, "@env-waiting-reason"), "review")
        prepare()
        self.pane_set(6, "@env-copilot-state", "DECIDE")
        self.assertEqual(self.pane_get(6, "@env-waiting-reason"), "review")
        self.assertEqual(self.state(6), "WAITING")

    def test_70_durations(self):
        self.simulate_copilot()
        self.tmux("set-option", "-t", "=ai-agents:", "@hand-status-now", "200000")
        self.pane_set(1, "@env-copilot-state", "WORKING")
        expected = {
            -5: "0s", 0: "0s", 59: "59s", 60: "1m0s", 3599: "59m59s",
            3600: "1h0m", 86399: "23h59m", 86400: "1d0h", 90000: "1d1h",
        }
        for elapsed, text in expected.items():
            self.pane_set(1, "@env-copilot-since", 200000 - elapsed)
            self.assertEqual(self.evaluate(1, "#{E:@hand-status-duration}"), text, elapsed)
            self.assertEqual(self.evaluate(1, "#{E:@hand-status-timer}"), text, elapsed)

    def test_87_fallback_states(self):
        self.simulate_copilot()
        self.assertEqual(self.state(1), "COPILOT")
        self.assertIn("#[fg=colour244]COPILOT", self.evaluate(1, "#{E:@hand-status-cell}"))
        self.assertEqual(self.evaluate(1, "#{E:@hand-status-timer}"), "")
        self.ensure()  # restores the real formats
        self.tmux("set-option", "-w", "-t", self.window(2), "remain-on-exit", "on")
        self.tmux("respawn-pane", "-k", "-t", self.window(2), "true")
        self.assertTrue(poll(lambda: self.evaluate(2, "#{pane_dead}") == "1"))
        self.assertEqual(self.state(2), "ERROR")
        self.tmux("send-keys", "-t", self.window(3), "sleep 30", "Enter")
        self.assertTrue(poll(lambda: self.evaluate(3, "#{pane_current_command}") == "sleep"))
        self.assertEqual(self.state(3), "WORKING")

    def test_90_other_host_claims_pane(self):
        # A host that is not matched by name (Claude Code reports its version
        # number as the command) publishes state once it owns the pane.
        self.tmux("send-keys", "-t", self.window(4), "sleep 30", "Enter")
        self.assertTrue(poll(lambda: self.evaluate(4, "#{pane_current_command}") == "sleep"))
        self.pane_set(4, "@env-copilot-state", "NEEDS YOU")
        self.assertEqual(self.state(4), "WORKING")  # unclaimed: just a program
        # An owner alone is what a crashed Copilot extension leaves behind:
        # that pane keeps Copilot's old rule and shows WORKING.
        self.tmux("set-option", "-p", "-t", self.window(4), "@env-dashboard-owner", "4242")
        self.assertEqual(self.state(4), "WORKING")
        self.assertEqual(self.evaluate(4, "#{E:@hand-status-title}"), "")
        self.tmux("set-option", "-p", "-t", self.window(4), "@env-dashboard-host", "claude")
        self.assertEqual(self.state(4), "NEEDS YOU")
        self.tmux("set-option", "-t", "=ai-agents:", "@hand-status-now", "200000")
        self.pane_set(4, "@env-copilot-state", "YOUR TURN")
        self.pane_set(4, "@env-copilot-since", 200000 - 30)
        self.pane_set(4, "@env-copilot-took", 75)
        self.assertEqual(self.state(4), "YOUR TURN")
        self.assertTrue(self.evaluate(4, "#{E:@hand-status-timer}").startswith("1m15s @"))
        self.tmux("select-pane", "-t", self.window(4), "-T", "Fix #[fg=red]flaky test")
        self.assertEqual(self.evaluate(4, "#{E:@hand-status-title}"), "Fix # [fg=red]flaky test")
        # The host exits without cleaning up: a plain shell is READY again.
        self.tmux("send-keys", "-t", self.window(4), "C-c", "")
        self.assertTrue(poll(lambda: self.state(4) == "READY"))
        self.assertEqual(self.evaluate(4, "#{E:@hand-status-timer}"), "")
        self.assertEqual(self.evaluate(4, "#{E:@hand-status-title}"), "")


class AttentionTests(TmuxTestCase):
    def setUp(self):
        super().setUp()
        self.ensure()

    def test_61_idle_labels_and_jumps(self):
        self.simulate_copilot()
        for index, label in ((2, "YOUR TURN"), (3, "REVIEW"), (5, "DECIDE"), (7, "BLOCKED")):
            self.pane_set(index, "@env-copilot-state", label)
            self.assertEqual(self.state(index), "YOUR TURN")
        self.tmux("select-window", "-t", self.window(1))
        visited = []
        for _ in range(5):
            self.launcher.focus_next_attention()
            visited.append(self.active_window())
        self.assertEqual(visited, [2, 3, 5, 7, 2])

    def test_63_plain_shell_with_stale_state_is_ready(self):
        self.pane_set(2, "@env-copilot-state", "YOUR TURN")
        self.assertEqual(self.state(2), "READY")
        self.tmux("select-window", "-t", self.window(1))
        self.launcher.focus_next_attention()
        self.assertEqual(self.active_window(), 1)

    def test_64_extra_window_is_ignored(self):
        self.simulate_copilot()
        self.tmux("new-window", "-d", "-t", "=ai-agents:11", "/bin/sh")
        self.pane_set(11, "@env-copilot-state", "NEEDS YOU")
        self.assertEqual(self.state(11), "NEEDS YOU")
        self.tmux("select-window", "-t", self.window(1))
        self.launcher.focus_next_attention()
        self.assertEqual(self.active_window(), 1)


class ClientTests(TmuxTestCase):
    """Tests that drive a real attached client with keys and mouse clicks."""

    def setUp(self):
        super().setUp()
        self.keys = ghostty_sequences()
        self.install_workbench()
        self.ensure()
        self.tmux("source-file", str(REPO / "terminal/ai-agents-shortcuts.tmux.conf"))

    def press(self, client, key):
        client.send(self.keys[key])

    def sync(self, client):
        """Wait until tmux has finished everything the client's input so far triggered.

        A client's keys run in order on its command queue, and a binding's
        ``run-shell`` (without ``-b``) holds that queue until the command exits.
        So once the barrier key's own binding has run, every earlier key, mouse
        event, menu choice and prompt submission is complete. If a menu or prompt
        is still open it swallows the barrier key and this fails.
        """
        token = "barrier-{}".format(next(_COUNTER))
        self.tmux("bind-key", "-n", "M-z", "set-option", "-g", "@digits-test-barrier", token)
        client.send(BARRIER_KEY)
        reached = poll(lambda: self.tmux("show-options", "-gqv", "@digits-test-barrier") == token)
        self.assertTrue(reached, "tmux did not reach the barrier key (is a menu or prompt still open?)")

    def press_escape(self, client):
        """Send a lone Escape and wait for tmux to act on it.

        A lone ESC is held for ``escape-time`` and would merge with a following
        escape sequence, so wait until the status line (covered by the open
        prompt or menu) is redrawn before sending anything else.
        """
        client.mark()
        client.send(b"\x1b")
        self.assertTrue(client.wait_for("hotkeys"), "Escape did not close the prompt")

    def test_59_shortcuts(self):
        client = self.attach()
        digits = ["cmd+{}".format(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)]
        for index, key in enumerate(digits, start=1):
            self.press(client, key)
            self.assertTrue(self.wait_window(index), key)
        self.press(client, "cmd+shift+bracket_right")
        self.assertTrue(self.wait_window(1))
        self.press(client, "cmd+shift+bracket_left")
        self.assertTrue(self.wait_window(10))
        self.press(client, "cmd+7")
        self.assertTrue(self.wait_window(7))
        self.press(client, "cmd+semicolon")
        self.assertTrue(self.wait_window(10))

        self.tmux("bind-key", "-n", "M-1", "set-option", "-g", "@alt-one", "fired")
        client.send(b"\x1b1")
        self.assertTrue(poll(lambda: self.tmux("show-options", "-gqv", "@alt-one") == "fired"))

        self.tmux("new-window", "-d", "-t", "=unrelated:", "/bin/sh")
        self.tmux("switch-client", "-c", client.name, "-t", "=unrelated:0")
        self.assertTrue(poll(lambda: self.tmux("display-message", "-p", "-c", client.name, "#{session_name}") == "unrelated"))
        self.press(client, "cmd+1")
        self.sync(client)
        self.assertEqual(self.active_window("unrelated"), 0)

        self.tmux("switch-client", "-c", client.name, "-t", "=ai-agents:")
        self.tmux("set-option", "-t", "=ai-agents:", "@ai-agents-managed", "0")
        self.press(client, "cmd+1")
        self.sync(client)
        self.assertEqual(self.active_window(), 10)
        with self.assertRaisesRegex(self.launcher.LauncherError, "unmanaged"):
            self.launcher.focus_next_attention()

    def test_60_attention_shortcut(self):
        self.simulate_copilot()
        for index in (2, 4, 6):
            self.pane_set(index, "@env-copilot-state", "YOUR TURN")
        for index in (3, 8):
            self.pane_set(index, "@env-copilot-state", "NEEDS YOU")
        self.pane_set(4, "@env-waiting-reason", "someone")
        self.assertEqual(self.state(4), "WAITING")
        client = self.attach()
        for expected in (3, 8, 3):
            self.press(client, "cmd+backquote")
            self.assertTrue(self.wait_window(expected), expected)
        self.tmux("select-window", "-t", self.window(1))
        client.send(self.keys["cmd+backquote"] * 2)
        self.assertTrue(self.wait_window(8))
        self.sync(client)
        self.assertEqual(self.active_window(), 8)
        for index in (3, 8):
            self.pane_set(index, "@env-copilot-state", "WORKING")
        # A pending question comes after approvals and before YOUR TURN.
        self.pane_set(5, "@env-copilot-state", "QUESTION")
        self.press(client, "cmd+backquote")
        self.assertTrue(self.wait_window(5))
        self.pane_set(5, "@env-copilot-state", "WORKING")
        self.tmux("select-window", "-t", self.window(8))
        for expected in (2, 6):
            self.press(client, "cmd+backquote")
            self.assertTrue(self.wait_window(expected), expected)
        self.pane_set(2, "@env-copilot-state", "WORKING")
        client.mark()
        self.press(client, "cmd+backquote")
        self.assertTrue(client.wait_for("No other chats need attention"))
        self.assertEqual(self.active_window(), 6)

    def test_65_markdown_shortcut(self):
        marker = self.fake_code()
        self.tmux("set-environment", "-g", "PATH", self.env["PATH"])
        self.tmux("set-environment", "-g", "VSCODE_IPC_HOOK_CLI", "/tmp/not-a-real-vscode.sock")
        folder = self.root / "session-folder"
        documents = {
            "plan.md": 100,
            "files/summary.md": 300,
            "checkpoints/index.md": 200,
            "rewind-file-snapshots/README.md": 400,
        }
        for relative, mtime in documents.items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# {}\n".format(relative))
            os.utime(str(path), (mtime, mtime))
        empty = self.root / "empty-folder"
        empty.mkdir()
        self.pane_set(3, "@env-session-dir", folder)
        self.pane_set(5, "@env-session-dir", empty)
        client = self.attach()

        self.press(client, "cmd+4")
        self.assertTrue(self.wait_window(4))
        client.mark()
        self.press(client, "cmd+shift+m")
        self.assertTrue(client.wait_for("No Copilot session folder for this chat"))
        self.press(client, "cmd+5")
        self.assertTrue(self.wait_window(5))
        client.mark()
        self.press(client, "cmd+shift+m")
        self.assertTrue(client.wait_for("No Markdown in this chat's session folder yet"))
        self.assertEqual(self.calls(marker), [])

        self.press(client, "cmd+3")
        self.assertTrue(self.wait_window(3))
        self.press(client, "cmd+shift+m")
        self.assertTrue(poll(lambda: self.calls(marker)))
        profile = self.home / "Library/Application Support/digits-markdown-viewer"
        call = self.calls(marker)[0]
        self.assertEqual(
            call["args"],
            [
                "--user-data-dir", str(profile),
                "--extensions-dir", str(profile / "extensions"),
                "--reuse-window",
                str((folder / "files/summary.md").resolve()),
            ],
        )
        self.assertEqual(call["ipc"], "")
        settings = json.loads((profile / "User/settings.json").read_text())
        self.assertEqual(
            settings["workbench.editorAssociations"], {"*.md": "vscode.markdown.preview.editor"}
        )
        unrelated_pane = self.tmux("display-message", "-p", "-t", "=unrelated:", "#{pane_id}")
        with self.assertRaisesRegex(self.launcher.LauncherError, "not in the ai-agents session"):
            self.launcher.show_markdown(unrelated_pane)

    def test_66_hotkeys_menu_and_window_clicks(self):
        self.tmux("select-window", "-t", self.window(1))
        self.tmux("select-window", "-t", self.window(3))
        client = self.attach()
        client.click(238, 1)
        self.assertTrue(client.wait_for("Digits shortcuts", "Cmd+Shift+M"))
        client.click(238, 1)
        self.sync(client)  # fails if the second click left the menu open
        client.send(b"\x1b[A")
        client.send(b"\r")
        self.sync(client)
        self.assertEqual(self.active_window(), 3)
        client.mark()
        client.click(238, 1)
        self.assertTrue(client.wait_for("Digits shortcuts"))
        client.send(b"\x1b[A")
        client.send(b"\r")
        self.assertTrue(self.wait_window(1))
        client.click(10, 2)
        self.assertTrue(self.wait_window(2))

    def submit_reason(self, client, column, row, text, clear=False):
        client.mark()
        client.click(column, row, button=2)
        self.assertTrue(client.wait_for("Waiting on (empty clears)"))
        if clear:
            client.send(b"\x15")  # Ctrl+U clears the pre-filled text
        client.send(text.encode())
        client.send(b"\r")
        self.sync(client)

    def test_67_right_click_reason_is_literal(self):
        self.simulate_copilot()
        self.pane_set(6, "@env-copilot-state", "YOUR TURN")
        self.pane_set(6, "@env-dashboard-owner", "fixture")
        self.tmux("select-window", "-t", self.window(7))
        before = self.listing()
        client = self.attach()
        text = 'review, "quoted"; #{pane_id} #[fg=red] $(not-a-command)'
        self.submit_reason(client, 125, 1, text)
        self.assertTrue(poll(lambda: self.pane_get(6, "@env-waiting-reason") == text))
        self.assertEqual(self.pane_get(6, "@env-waiting-owner"), "fixture")
        self.assertEqual(self.state(6), "WAITING")
        title = self.evaluate(6, "#{E:@hand-status-title}")
        self.assertIn("Waiting on:", title)
        self.assertIn("# [fg=red]", title)
        self.assertEqual(self.listing(), before)
        self.assertEqual(self.active_window(), 6)

        self.submit_reason(client, 125, 1, "")
        self.assertEqual(self.pane_get(6, "@env-waiting-reason"), text)
        self.tmux("source-file", str(self.launcher.CONFIG))
        self.simulate_copilot()
        self.assertEqual(self.pane_get(6, "@env-waiting-reason"), text)
        self.pane_set(6, "@env-copilot-state", "WORKING")
        self.assertEqual(self.pane_get(6, "@env-waiting-reason"), "")
        self.pane_set(6, "@env-copilot-state", "YOUR TURN")
        self.assertEqual(self.state(6), "YOUR TURN")

    def test_68_prompt_cancel_clear_and_not_idle(self):
        self.simulate_copilot()
        self.pane_set(1, "@env-copilot-state", "YOUR TURN")
        client = self.attach()
        self.submit_reason(client, 5, 1, "external review")
        self.assertTrue(poll(lambda: self.pane_get(1, "@env-waiting-reason") == "external review"))

        client.mark()
        client.click(5, 1, button=2)
        self.assertTrue(client.wait_for("Waiting on (empty clears)"))
        client.send(b"\x15changed")
        self.press_escape(client)
        self.sync(client)
        self.assertEqual(self.pane_get(1, "@env-waiting-reason"), "external review")

        self.submit_reason(client, 5, 1, "", clear=True)
        self.assertTrue(poll(lambda: self.state(1) == "YOUR TURN"))
        self.assertEqual(self.pane_get(1, "@env-waiting-reason"), "")

        client.mark()
        client.click(5, 1, button=2)
        self.assertTrue(client.wait_for("Waiting on (empty clears)"))
        self.pane_set(1, "@env-copilot-state", "WORKING")
        client.send(b"too late\r")
        self.assertTrue(client.wait_for("stopped being idle"))
        self.assertEqual(self.pane_get(1, "@env-waiting-reason"), "")


class LauncherEdgeTests(TmuxTestCase):
    def test_72_exclusive_modes(self):
        result = self.run_cli("--next-attention", "--no-attach")
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage", result.stderr)

    def test_73_missing_environment(self):
        (self.home / "right_pinky").rmdir()
        with self.assertRaisesRegex(self.launcher.LauncherError, "Missing independent environment:"):
            self.ensure()
        self.assertNotIn("ai-agents", self.tmux("list-sessions", "-F", "#{session_name}").split())
        outside = self.root / "outside"
        outside.mkdir()
        (self.home / "right_pinky").symlink_to(outside)
        with self.assertRaisesRegex(self.launcher.LauncherError, "Missing independent environment:"):
            self.ensure()
        (self.home / "right_pinky").unlink()
        (self.home / "right_pinky").mkdir()
        self.ensure()
        before = self.listing()
        (self.home / "left_ring").rmdir()
        self.ensure()
        self.assertEqual(self.listing(), before)

    def test_74_shell_required_only_for_new_windows(self):
        self.launcher.FISH = None
        self.launcher.LOGIN_SHELL = None
        with self.assertRaisesRegex(self.launcher.LauncherError, "login shell is required"):
            self.ensure()
        self.assertNotIn("ai-agents", self.tmux("list-sessions", "-F", "#{session_name}").split())
        self.launcher.FISH = "/bin/sh"
        self.ensure()
        before = self.listing()
        self.launcher.FISH = None
        self.ensure()
        self.assertEqual(self.listing(), before)

    def test_89_login_shell_used_when_fish_is_absent(self):
        self.launcher.FISH = None
        for unusable in ("sh", str(self.root / "no-such-shell")):
            self.launcher.LOGIN_SHELL = unusable
            self.assertIsNone(self.launcher.environment_shell())
        self.launcher.LOGIN_SHELL = "/bin/sh"
        self.assertEqual(self.launcher.environment_shell(), "/bin/sh")
        self.ensure()
        # /bin/sh may be bash in disguise (macOS), so accept any plain shell.
        self.assertTrue(poll(lambda: self.evaluate(1, "#{pane_current_command}") in ("sh", "bash", "dash")))
        self.launcher.FISH = "/bin/sh"
        self.launcher.LOGIN_SHELL = str(self.root / "no-such-shell")
        self.assertEqual(self.launcher.environment_shell(), "/bin/sh")

    def test_75_missing_configuration(self):
        result = self.run_cli("--no-attach")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ai-agents: Missing session configuration:", result.stderr)

    def test_76_no_attach(self):
        self.install_workbench()
        result = self.run_cli("--no-attach")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "Ready: ai-agents\n")
        self.assertEqual(len(self.listing()), 10)
        self.assertEqual(self.tmux("list-clients"), "")

    def test_77_concurrent_launchers(self):
        self.install_workbench()
        env = self.cli_env()
        command = [sys.executable, str(REPO / "bin/ai-agents"), "--no-attach"]
        processes = [
            subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             stdin=subprocess.DEVNULL)
            for _ in range(2)
        ]
        for process in processes:
            _out, err = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, err)
        sessions = self.tmux("list-sessions", "-F", "#{session_name}").split("\n")
        self.assertEqual(sessions.count("ai-agents"), 1)
        self.assertEqual(len(self.listing()), 10)

    def test_88_viewer_failure_is_a_message(self):
        self.ensure()
        folder = self.root / "folder"
        folder.mkdir()
        (folder / "plan.md").write_text("# plan\n")
        self.pane_set(1, "@env-session-dir", folder)
        pane = self.evaluate(1, "#{pane_id}")
        client = self.attach()
        silent = self.root / "silent-viewer"
        silent.write_text("#!/bin/sh\nexit 1\n")
        silent.chmod(0o755)
        real_viewer = self.launcher.viewer_path
        cases = (
            (real_viewer, "first\nlast line of failure\n", "last line of failure"),
            (lambda: silent, "", "md-view failed"),
        )
        for viewer, stderr, expected in cases:
            self.launcher.viewer_path = viewer
            marker = self.fake_code(exit_code=3, stderr=stderr)
            if marker.exists():
                marker.unlink()
            client.mark()
            with mock.patch.dict(os.environ, {"PATH": self.env["PATH"], "HOME": str(self.home)}):
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = self.launcher.main(["--markdown", pane, "--client", client.name])
            self.assertEqual(code, 0, err.getvalue())
            self.assertEqual(err.getvalue(), "")
            self.assertTrue(client.wait_for(expected), expected)
        self.assertEqual(len(self.calls(marker)), 0)


class MarkdownViewerTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(os.path.realpath(tempfile.mkdtemp(prefix="digits-mdview-")))
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.home = self.root / "home"
        self.home.mkdir()
        self.codebin = self.root / "codebin"
        self.codebin.mkdir()
        self.marker = self.root / "calls.jsonl"
        code = self.codebin / "code"
        code.write_text(
            "#!{}\nimport json, os, sys\n"
            "open({!r}, 'a').write(json.dumps({{'args': sys.argv[1:], 'env': sorted(os.environ)}}) + '\\n')\n".format(
                sys.executable, str(self.marker)
            )
        )
        code.chmod(0o755)
        self.profile = self.home / "Library/Application Support/digits-markdown-viewer"
        self.document = self.root / "doc.md"
        self.document.write_text("# doc\n")
        self.env = {
            name: value for name, value in os.environ.items()
            if not name.startswith("VSCODE_") and name != "ELECTRON_RUN_AS_NODE"
        }
        self.env.update(HOME=str(self.home), PATH="{}:/usr/bin:/bin".format(self.codebin))

    def run_viewer(self, *args, env=None):
        return subprocess.run(
            [sys.executable, str(REPO / "bin/md-view"), *args],
            capture_output=True, text=True, env=env or self.env, cwd=str(self.root),
            stdin=subprocess.DEVNULL, timeout=30,
        )

    def calls(self):
        if not self.marker.exists():
            return []
        return [json.loads(line) for line in self.marker.read_text().splitlines()]

    def test_71_missing_file_and_user_settings(self):
        result = self.run_viewer(str(self.root / "missing.md"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("Not a file", result.stderr)
        self.assertEqual(self.calls(), [])
        settings = self.profile / "User/settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text('{"editor.fontSize": 20}\n')
        result = self.run_viewer("doc.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(self.calls()[0]["args"][-1], str(self.document))
        self.assertEqual(settings.read_text(), '{"editor.fontSize": 20}\n')

    def test_78_missing_code_and_stripped_environment(self):
        viewer = load_module(REPO / "bin/md-view", "md_view_under_test")
        viewer.SYSTEM_APPLICATIONS = self.root / "Applications"
        environment = {"HOME": str(self.home), "PATH": "/usr/bin:/bin"}
        with mock.patch.dict(os.environ, environment), mock.patch.object(
            viewer.shutil, "which", lambda name: None
        ):
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = viewer.main([str(self.document)])
        self.assertEqual(code, 1)
        self.assertTrue(err.getvalue().startswith("md-view: "))
        self.assertIn("code", err.getvalue())
        self.assertFalse(self.profile.exists())

        env = dict(self.env, VSCODE_IPC_HOOK_CLI="/tmp/x.sock", VSCODE_PID="1",
                   ELECTRON_RUN_AS_NODE="1")
        result = self.run_viewer(str(self.document), env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        seen = self.calls()[0]["env"]
        self.assertFalse([name for name in seen if name.startswith("VSCODE_")])
        self.assertNotIn("ELECTRON_RUN_AS_NODE", seen)

    def test_79_settings_written_once(self):
        result = self.run_viewer(str(self.document))
        self.assertEqual(result.returncode, 0, result.stderr)
        settings = self.profile / "User/settings.json"
        text = settings.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertIn("Markdown \u2014 ${activeEditorShort}", text)
        self.assertIn('\n  "', text)
        self.assertEqual(
            set(json.loads(text)),
            {
                "chat.disableAIFeatures", "extensions.ignoreRecommendations", "update.mode",
                "security.workspace.trust.untrustedFiles", "window.restoreWindows",
                "window.title", "workbench.activityBar.location",
                "workbench.editorAssociations", "workbench.enableExperiments",
                "workbench.layoutControl.enabled", "workbench.startupEditor",
                "workbench.statusBar.visible", "workbench.tips.enabled",
            },
        )
        self.assertTrue((self.profile / "extensions").is_dir())
        stamp = settings.stat().st_mtime_ns
        self.run_viewer(str(self.document))
        self.assertEqual(settings.read_text(encoding="utf-8"), text)
        self.assertEqual(settings.stat().st_mtime_ns, stamp)
        self.assertEqual(len(self.calls()), 2)


if __name__ == "__main__":
    unittest.main()
