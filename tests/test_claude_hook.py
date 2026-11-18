"""Tests for the Claude Code dashboard hook (claude/hooks/env_dashboard.py)."""

import importlib.util
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "claude/hooks/env_dashboard.py"
_COUNTER = itertools.count()


def load_hook():
    spec = importlib.util.spec_from_file_location(
        "claude_env_dashboard_{}".format(next(_COUNTER)), str(HOOK)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


hook = load_hook()
OWNER, STATE, SINCE, TOOK, AGENTS = hook.OWNER, hook.STATE, hook.SINCE, hook.TOOK, hook.AGENTS
HOST, RESUME = hook.HOST, hook.RESUME
SESSION = "session-1"


def event(name, **fields):
    return dict({"hook_event_name": name, "session_id": SESSION}, **fields)


class Replay:
    """Apply events to an in-memory option set, as main() does against tmux."""

    def __init__(self, **options):
        self.options = {option: "" for option in hook.OPTIONS}
        self.options.update(options)

    def send(self, payload, now):
        for option, value in hook.transition(dict(self.options), payload, now).items():
            self.options[option] = "" if value is None else value
        return self

    @property
    def state(self):
        return self.options[STATE]


class TransitionTests(unittest.TestCase):
    def test_session_start_claims_pane_as_ready(self):
        replay = Replay(**{STATE: "ERROR", SINCE: "5", TOOK: "3", AGENTS: "x"})
        replay.send(event("SessionStart", source="startup"), 100)
        self.assertEqual(replay.options, {OWNER: SESSION, STATE: "READY", SINCE: "", TOOK: "", AGENTS: "",
                                          HOST: "claude", RESUME: ""})

    def test_compaction_keeps_the_running_state(self):
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("SessionStart", source="compact"), 150)
        self.assertEqual((replay.state, replay.options[SINCE]), ("WORKING", "100"))

    def test_tool_turn_finishes_with_duration(self):
        replay = Replay()
        replay.send(event("SessionStart", source="startup"), 90)
        replay.send(event("UserPromptSubmit", prompt="q"), 100)
        self.assertEqual((replay.state, replay.options[SINCE]), ("WORKING", "100"))
        replay.send(event("PreToolUse", tool_name="Bash", tool_use_id="t1"), 102)
        replay.send(event("PostToolUseFailure", tool_name="Bash", tool_use_id="t1"), 103)
        self.assertEqual((replay.state, replay.options[SINCE]), ("WORKING", "100"))
        replay.send(event("Stop", background_tasks=[]), 175)
        self.assertEqual(
            (replay.state, replay.options[SINCE], replay.options[TOOK]), ("YOUR TURN", "175", "75")
        )

    def test_background_agent_after_stop_is_ignored(self):
        # Captured order: Stop, then SubagentStop from an agent with an empty type.
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("Stop"), 110)
        replay.send(event("SubagentStop", agent_id="internal", agent_type=""), 112)
        replay.send(event("PreToolUse", agent_id="internal", agent_type="", tool_name="Read"), 112)
        self.assertEqual(replay.state, "YOUR TURN")

    def test_subagents_outlive_the_turn(self):
        # Captured order: Agent tool returns at once, the turn stops, the
        # subagent finishes and its result arrives as a new prompt.
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("PreToolUse", tool_name="Agent", tool_use_id="a"), 101)
        replay.send(event("PostToolUse", tool_name="Agent", tool_use_id="a"), 101)
        replay.send(event("SubagentStart", agent_id="sub1", agent_type="general-purpose"), 101)
        replay.send(event("PreToolUse", agent_id="sub1", agent_type="general-purpose", tool_name="Bash"), 102)
        self.assertEqual(replay.state, "WORKING")
        replay.send(event("Stop"), 103)
        self.assertEqual((replay.state, replay.options[SINCE]), ("SUBAGENTS", "100"))
        replay.send(event("SubagentStop", agent_id="sub1", agent_type="general-purpose"), 130)
        self.assertEqual((replay.state, replay.options[TOOK]), ("YOUR TURN", "30"))
        self.assertEqual(replay.options[AGENTS], "")
        replay.send(event("UserPromptSubmit", prompt="<result>"), 131)
        self.assertEqual((replay.state, replay.options[SINCE]), ("WORKING", "131"))

    def test_prompts_start_a_fresh_run_unless_mid_turn(self):
        replay = Replay(**{OWNER: SESSION, STATE: "SUBAGENTS", SINCE: "100", AGENTS: "sub1 sub2"})
        replay.send(event("SubagentStop", agent_id="sub1", agent_type="Explore"), 120)
        self.assertEqual((replay.state, replay.options[AGENTS]), ("SUBAGENTS", "sub2"))
        replay.send(event("UserPromptSubmit", prompt="next"), 121)
        self.assertEqual((replay.state, replay.options[SINCE]), ("WORKING", "121"))
        replay.send(event("UserPromptSubmit", prompt="queued"), 125)
        self.assertEqual((replay.state, replay.options[SINCE]), ("WORKING", "121"))

    def test_question_tool_shows_question_until_answered(self):
        replay = Replay(**{OWNER: SESSION, HOST: "claude", STATE: "WORKING", SINCE: "100"})
        replay.send(event("PreToolUse", tool_name="AskUserQuestion"), 110)
        self.assertEqual((replay.state, replay.options[RESUME]), ("QUESTION", "WORKING"))
        # The dialog may also raise a permission prompt; it stays a question.
        replay.send(event("PermissionRequest", tool_name="AskUserQuestion"), 111)
        replay.send(event("Notification", notification_type="permission_prompt"), 112)
        self.assertEqual(replay.state, "QUESTION")
        replay.send(event("PostToolUse", tool_name="AskUserQuestion"), 140)
        self.assertEqual((replay.state, replay.options[SINCE], replay.options[RESUME]), ("WORKING", "100", ""))
        # Any other approval is still NEEDS YOU.
        replay.send(event("PermissionRequest", tool_name="Bash"), 150)
        self.assertEqual(replay.state, "NEEDS YOU")

    def test_subagent_question_resumes_the_run(self):
        replay = Replay(**{OWNER: SESSION, HOST: "claude", STATE: "SUBAGENTS", SINCE: "100", AGENTS: "sub1"})
        child = {"agent_id": "sub1", "agent_type": "general-purpose"}
        replay.send(event("PreToolUse", tool_name="AskUserQuestion", **child), 110)
        self.assertEqual((replay.state, replay.options[RESUME]), ("QUESTION", "SUBAGENTS"))
        replay.send(event("PostToolUse", tool_name="AskUserQuestion", **child), 130)
        self.assertEqual((replay.state, replay.options[SINCE]), ("SUBAGENTS", "100"))

    def test_subagent_permission_prompt_needs_you(self):
        replay = Replay(**{OWNER: SESSION, STATE: "SUBAGENTS", SINCE: "100", AGENTS: "sub1"})
        replay.send(event("PermissionRequest", agent_id="sub1", agent_type="general-purpose"), 110)
        self.assertEqual(replay.state, "NEEDS YOU")

    def test_subagent_tool_after_permission_resumes_the_run(self):
        # Foreground subagent: approval shows NEEDS YOU, the subagent's next
        # tool event (proof the approval was given) restores WORKING.
        replay = Replay(**{OWNER: SESSION, HOST: "claude", STATE: "WORKING", SINCE: "100", AGENTS: "sub1"})
        child = {"agent_id": "sub1", "agent_type": "general-purpose"}
        replay.send(event("PermissionRequest", **child), 110)
        self.assertEqual((replay.state, replay.options[RESUME]), ("NEEDS YOU", "WORKING"))
        replay.send(event("PostToolUse", tool_name="Bash", **child), 130)
        self.assertEqual((replay.state, replay.options[RESUME], replay.options[SINCE]), ("WORKING", "", "100"))
        # Background subagent after the turn: back to SUBAGENTS, and its end
        # finishes the run even if it ends while still waiting for approval.
        replay = Replay(**{OWNER: SESSION, HOST: "claude", STATE: "SUBAGENTS", SINCE: "100", AGENTS: "sub1"})
        replay.send(event("Notification", notification_type="permission_prompt", **child), 110)
        replay.send(event("PreToolUse", tool_name="Read", **child), 120)
        self.assertEqual(replay.state, "SUBAGENTS")
        replay.send(event("PermissionRequest", **child), 130)
        replay.send(event("SubagentStop", **child), 160)
        self.assertEqual((replay.state, replay.options[TOOK], replay.options[RESUME]), ("YOUR TURN", "60", ""))

    def test_every_input_notification_needs_you(self):
        for kind in hook.INPUT_NOTIFICATIONS:
            replay = Replay(**{OWNER: SESSION, HOST: "claude", STATE: "WORKING", SINCE: "100"})
            replay.send(event("Notification", notification_type=kind), 110)
            self.assertEqual(replay.state, "NEEDS YOU", kind)
        self.assertIn("agent_needs_input", hook.INPUT_NOTIFICATIONS)

    def test_child_session_start_never_resets_the_pane(self):
        replay = Replay(**{OWNER: SESSION, HOST: "claude", STATE: "WORKING", SINCE: "100"})
        before = dict(replay.options)
        replay.send(event("SessionStart", source="startup", agent_id="sub1", agent_type="general-purpose"), 110)
        self.assertEqual(replay.options, before)

    def test_claim_marks_the_pane_as_claude(self):
        replay = Replay()
        replay.send(event("PreToolUse", tool_name="Read"), 100)
        self.assertEqual((replay.options[OWNER], replay.options[HOST]), (SESSION, "claude"))
        # A pane claimed before the marker existed gets it on the next event.
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("PostToolUse", tool_name="Read"), 110)
        self.assertEqual(replay.options[HOST], "claude")
        replay.send(event("SessionStart", source="compact"), 120)
        self.assertEqual(replay.options[HOST], "claude")

    def test_stop_with_other_background_task_types_is_your_turn(self):
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("Stop", background_tasks=[{"type": "monitor", "status": "running"}]), 110)
        self.assertEqual(replay.state, "YOUR TURN")

    def test_stop_with_running_background_agent_task(self):
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("Stop", background_tasks=[{"type": "agent", "status": "running"}]), 110)
        self.assertEqual(replay.state, "SUBAGENTS")

    def test_stop_with_only_a_background_shell_is_your_turn(self):
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        shell = {"id": "b1", "type": "shell", "status": "running", "command": "sleep 20"}
        replay.send(event("Stop", background_tasks=[shell]), 110)
        self.assertEqual(replay.state, "YOUR TURN")

    def test_permission_needs_you_until_the_tool_runs(self):
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("PermissionRequest", tool_name="Bash"), 105)
        self.assertEqual(replay.state, "NEEDS YOU")
        replay.send(event("PostToolUse", tool_name="Bash"), 140)
        self.assertEqual((replay.state, replay.options[SINCE]), ("WORKING", "100"))
        for kind in ("permission_prompt", "elicitation_dialog"):
            replay.send(event("Notification", notification_type=kind), 141)
            self.assertEqual(replay.state, "NEEDS YOU")

    def test_idle_prompt_finishes_a_turn_that_never_stopped(self):
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100"})
        replay.send(event("Notification", notification_type="idle_prompt"), 160)
        self.assertEqual((replay.state, replay.options[TOOK]), ("YOUR TURN", "60"))
        before = dict(replay.options)
        replay.send(event("Notification", notification_type="idle_prompt"), 220)
        self.assertEqual(replay.options, before)
        replay = Replay(**{OWNER: SESSION, STATE: "NEEDS YOU", SINCE: "100"})
        replay.send(event("Notification", notification_type="idle_prompt"), 160)
        self.assertEqual(replay.state, "NEEDS YOU")

    def test_stop_failure_is_error(self):
        replay = Replay(**{OWNER: SESSION, STATE: "WORKING", SINCE: "100", AGENTS: "sub1"})
        replay.send(event("StopFailure", error="rate_limit"), 110)
        self.assertEqual((replay.state, replay.options[AGENTS]), ("ERROR", ""))

    def test_other_owner_is_left_alone(self):
        replay = Replay(**{OWNER: "other", STATE: "WORKING", SINCE: "100"})
        for name in ("UserPromptSubmit", "Stop", "SessionEnd", "StopFailure"):
            self.assertEqual(hook.transition(dict(replay.options), event(name), 120), {}, name)

    def test_unclaimed_pane_is_claimed_by_any_event(self):
        replay = Replay()
        replay.send(event("UserPromptSubmit", prompt="q"), 100)
        self.assertEqual((replay.options[OWNER], replay.state), (SESSION, "WORKING"))

    def test_session_end_clears_only_its_own_pane(self):
        replay = Replay(**{OWNER: SESSION, STATE: "YOUR TURN", SINCE: "100", TOOK: "4"})
        replay.send(event("SessionEnd", reason="exit"), 120)
        self.assertEqual(set(replay.options.values()), {""})
        self.assertEqual(hook.transition(Replay().options, event("SessionEnd"), 120), {})

    def test_unknown_events_change_nothing(self):
        self.assertEqual(hook.transition(Replay().options, event("PreCompact"), 1), {})


@unittest.skipUnless(shutil.which("tmux"), "tmux is required")
class TmuxTests(unittest.TestCase):
    """main() against an isolated tmux server running the real dashboard formats."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="digits-claude-hook-"))
        self.addCleanup(shutil.rmtree, str(self.root), True)
        self.socket = str(self.root / "tmux.sock")
        self.env = dict(os.environ, HOME=str(self.root), TMUX="")
        self.tmux("-f", "/dev/null", "new-session", "-d", "-s", "ai-agents", "-x", "200", "-y", "40", "/bin/sh")
        self.addCleanup(self.tmux_quiet, "kill-server")
        self.tmux("source-file", str(REPO / "terminal/ai-agents.conf"))
        self.pane = self.tmux("display-message", "-p", "-t", "ai-agents:", "#{pane_id}")
        self.environ = {"TMUX": "{},1,0".format(self.socket), "TMUX_PANE": self.pane}

    def tmux(self, *args):
        result = subprocess.run(
            ["tmux", "-S", self.socket, *args], capture_output=True, text=True,
            env=self.env, stdin=subprocess.DEVNULL, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def tmux_quiet(self, *args):
        subprocess.run(["tmux", "-S", self.socket, *args], capture_output=True, env=self.env)

    def evaluate(self, text):
        return self.tmux("display-message", "-p", "-t", self.pane, text)

    def poll(self, predicate, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()

    def send(self, payload, now):
        self.assertEqual(hook.main(io.StringIO(json.dumps(payload)), self.environ, now), 0)

    def test_dashboard_renders_the_published_states(self):
        # Claude Code is not a shell, so stand in a foreground program for it.
        self.tmux("send-keys", "-t", self.pane, "sleep 60", "Enter")
        self.assertTrue(self.poll(lambda: self.evaluate("#{pane_current_command}") == "sleep"))
        self.assertEqual(self.evaluate("#{E:@hand-status-state}"), "WORKING")  # unclaimed
        self.send(event("SessionStart", source="startup"), 100)
        self.assertEqual(self.evaluate("#{@env-dashboard-owner}"), SESSION)
        self.assertEqual(self.evaluate("#{E:@hand-status-state}"), "READY")
        self.send(event("UserPromptSubmit", prompt="q"), 100)
        self.send(event("PermissionRequest", tool_name="Bash"), 101)
        self.assertEqual(self.evaluate("#{E:@hand-status-state}"), "NEEDS YOU")
        self.send(event("PostToolUse", tool_name="Bash"), 102)
        self.send(event("PreToolUse", tool_name="AskUserQuestion"), 103)
        self.assertEqual(self.evaluate("#{E:@hand-status-state}"), "QUESTION")
        self.assertEqual(self.evaluate("#{E:@hand-status-state-style}"), "#[fg=colour213]")
        self.send(event("PostToolUse", tool_name="AskUserQuestion"), 104)
        self.send(event("Stop"), 175)
        self.assertEqual(self.evaluate("#{E:@hand-status-state}"), "YOUR TURN")
        self.assertEqual(self.evaluate("#{@env-copilot-took}"), "75")
        self.assertTrue(self.evaluate("#{E:@hand-status-timer}").startswith("1m15s @"))
        self.send(event("SubagentStop", agent_id="internal", agent_type=""), 177)
        self.assertEqual(self.evaluate("#{E:@hand-status-state}"), "YOUR TURN")
        self.send(event("SessionEnd", reason="exit"), 180)
        for option in hook.OPTIONS:
            self.assertEqual(self.evaluate("#{%s}" % option), "", option)

    def test_outside_tmux_or_bad_input_never_fails(self):
        self.assertEqual(hook.main(io.StringIO("{}"), {}, 1), 0)
        stderr = io.StringIO()
        original, sys.stderr = sys.stderr, stderr
        try:
            self.assertEqual(hook.main(io.StringIO("not json"), self.environ, 1), 0)
            self.assertEqual(hook.main(io.StringIO("[]"), self.environ, 1), 0)
        finally:
            sys.stderr = original
        self.assertIn("Digits dashboard hook:", stderr.getvalue())
        self.assertEqual(self.evaluate("#{@env-copilot-state}"), "")

    def test_panes_outside_the_dashboard_session_are_left_alone(self):
        self.tmux("new-session", "-d", "-s", "other", "/bin/sh")
        pane = self.tmux("display-message", "-p", "-t", "other:", "#{pane_id}")
        environ = dict(self.environ, TMUX_PANE=pane)
        payload = io.StringIO(json.dumps(event("SessionStart", source="startup")))
        self.assertEqual(hook.main(payload, environ, 100), 0)
        self.assertEqual(self.tmux("display-message", "-p", "-t", pane, "#{@env-dashboard-owner}"), "")

    def test_script_runs_as_a_hook_command(self):
        self.assertTrue(os.access(str(HOOK), os.X_OK))
        result = subprocess.run(
            [str(HOOK)], input=json.dumps(event("SessionStart", source="startup")),
            capture_output=True, text=True, env=dict(self.env, **self.environ), timeout=10,
        )
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(self.evaluate("#{@env-copilot-state}"), "READY")


if __name__ == "__main__":
    unittest.main()
