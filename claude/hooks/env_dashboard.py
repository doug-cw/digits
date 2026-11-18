#!/usr/bin/env python3
"""Claude Code hook that publishes this chat's activity to the ai-agents dashboard.

Claude Code runs this script for each lifecycle hook (see
``claude/settings.json``) with the event as JSON on stdin. It keeps the same
pane options the Copilot ``env-dashboard`` extension writes, so
``terminal/ai-agents.conf`` renders both hosts alike:

    @env-dashboard-owner   this chat's session id (claims the pane)
    @env-dashboard-host    "claude": marks the pane as a Claude Code chat
    @env-copilot-state     READY, WORKING, SUBAGENTS, NEEDS YOU, QUESTION, YOUR TURN, ERROR
    @env-copilot-since     start of the run, or when the turn finished
    @env-copilot-took      length of the finished turn, in seconds
    @env-claude-agents     ids of this chat's running subagents (space separated)
    @env-claude-resume     the running state to return to after NEEDS YOU

``transition`` holds every rule and does no I/O; ``main`` reads the pane's
options, applies the transition and writes the changes back. The script never
blocks Claude Code: it always exits 0 and reports problems on stderr.
"""

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import time

OWNER = "@env-dashboard-owner"
STATE = "@env-copilot-state"
SINCE = "@env-copilot-since"
TOOK = "@env-copilot-took"
AGENTS = "@env-claude-agents"
HOST = "@env-dashboard-host"
RESUME = "@env-claude-resume"
OPTIONS = (OWNER, STATE, SINCE, TOOK, AGENTS, HOST, RESUME)
HOST_NAME = "claude"
SESSION = "ai-agents"  # only panes of the managed dashboard session are touched

RUNNING = ("WORKING", "SUBAGENTS")
TOOL_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
INPUT_NOTIFICATIONS = (
    "permission_prompt",
    "elicitation_dialog",
    "elicitation_url_dialog",
    "agent_needs_input",
    "worker_permission_prompt",
)
QUESTION_TOOL = "AskUserQuestion"
WAITING_ON_USER = ("NEEDS YOU", "QUESTION")
TMUX = "tmux"
TMUX_TIMEOUT = 2


def _agents(current):
    return [item for item in current.get(AGENTS, "").split() if item]


def _background_agents(event):
    """True when Stop reports a running background agent task."""
    for task in event.get("background_tasks") or ():
        if isinstance(task, dict) and task.get("status") == "running" and task.get("type") == "agent":
            return True
    return False


def _needs_input(name, event):
    return name == "PermissionRequest" or (
        name == "Notification" and event.get("notification_type") in INPUT_NOTIFICATIONS
    )


def _asks_question(name, event):
    return name == "PreToolUse" and event.get("tool_name") == QUESTION_TOOL


def _finish(current, now, label="YOUR TURN"):
    """Close the run: record how long it took and when it finished."""
    since = current.get(SINCE, "")
    took = str(max(0, now - int(since))) if since.isdigit() else None
    return {STATE: label, SINCE: str(now), TOOK: took}


def transition(current, event, now):
    """Return the option changes for one hook event.

    ``current`` maps option names to their values ("" when unset); ``event`` is
    the hook payload; ``now`` is the current Unix time in whole seconds. The
    result maps option names to new values, with None meaning "unset"; an empty
    dict means nothing changes.
    """
    name = event.get("hook_event_name", "")
    session = str(event.get("session_id") or "")
    owner = current.get(OWNER, "")
    agent_id = str(event.get("agent_id") or "")
    mine = {OWNER: session, HOST: HOST_NAME}

    if name == "SessionStart":
        if agent_id:
            return {}  # a child agent starting never resets the parent's pane
        if event.get("source") == "compact":
            # Compaction can happen mid-turn; only make sure the pane is ours.
            return {} if owner == session and current.get(HOST) == HOST_NAME else mine
        return dict(mine, **{STATE: "READY", SINCE: None, TOOK: None, AGENTS: None, RESUME: None})
    if owner and owner != session:
        return {}  # another chat owns this pane
    claim = {} if owner and current.get(HOST) == HOST_NAME else mine
    state = current.get(STATE, "")

    if name == "SessionEnd":
        return {option: None for option in OPTIONS} if owner else {}

    asking = _asks_question(name, event)
    if asking or _needs_input(name, event):
        # Checked before the child-agent rule: a subagent waiting for approval
        # needs the user just as much as the main chat does. Remember the
        # running state, so the subagent's next tool event can restore it.
        # The question tool (and any prompt raised while it is open) is a
        # QUESTION; anything else needs an approval.
        question = asking or event.get("tool_name") == QUESTION_TOOL or state == "QUESTION"
        changes = dict(claim, **{STATE: "QUESTION" if question else "NEEDS YOU"})
        if state in RUNNING:
            changes[RESUME] = state
        return changes

    if agent_id and state in WAITING_ON_USER and name in TOOL_EVENTS:
        # The subagent's tool ran, so the approval was given.
        return dict(claim, **{STATE: current.get(RESUME) or "WORKING", RESUME: None})

    if agent_id:
        # Child agents never start or finish the parent's turn. Only real
        # subagents (with a type) are counted; Claude Code's own background
        # agents (empty type) run after Stop and must be ignored.
        if not event.get("agent_type"):
            return {}
        agents = _agents(current)
        if name == "SubagentStart" and agent_id not in agents:
            agents.append(agent_id)
        elif name == "SubagentStop" and agent_id in agents:
            agents.remove(agent_id)
        else:
            return {}
        changes = dict(claim, **{AGENTS: " ".join(agents) or None})
        waiting_on_subagents = state == "SUBAGENTS" or (
            state in WAITING_ON_USER and current.get(RESUME) == "SUBAGENTS"
        )
        if not agents and waiting_on_subagents:
            changes.update(_finish(current, now))
            changes[RESUME] = None
        elif agents and state == "YOUR TURN":
            changes[STATE] = "SUBAGENTS"
        return changes

    if name == "UserPromptSubmit":
        # A prompt queued while the chat is mid-turn continues that run; any
        # other prompt (including a subagent's result after Stop, which cannot
        # be told apart from one the user typed) starts a fresh one.
        keep_run = state == "WORKING" and current.get(SINCE, "").isdigit()
        return dict(claim, **{
            STATE: "WORKING",
            SINCE: current[SINCE] if keep_run else str(now),
            TOOK: None,
            RESUME: None,
        })
    if name in TOOL_EVENTS:
        changes = dict(claim)
        if state != "WORKING":
            changes[STATE] = "WORKING"
            changes[RESUME] = None
        if not current.get(SINCE, "").isdigit() or state not in RUNNING + WAITING_ON_USER:
            changes[SINCE] = str(now)
            changes[TOOK] = None
        return changes
    if name == "Notification" and event.get("notification_type") == "idle_prompt":
        # Idle and waiting for input, yet still marked busy: the turn ended
        # without a Stop event (for example, it was interrupted).
        return dict(claim, **_finish(current, now)) if state in RUNNING else {}
    if name == "Stop":
        busy = _background_agents(event) or bool(_agents(current))
        if busy:
            return dict(claim, **{STATE: "SUBAGENTS", RESUME: None})
        changes = dict(claim, **_finish(current, now))
        changes[RESUME] = None
        return changes
    if name == "StopFailure":
        return dict(claim, **{STATE: "ERROR", AGENTS: None, RESUME: None})
    return {}


# --- tmux transport ------------------------------------------------------------


def socket_path(value):
    """The socket path from $TMUX ("<path>,<pid>,<session>")."""
    return ",".join(value.split(",")[:-2])


def _tmux(socket, *args):
    result = subprocess.run(
        [TMUX, "-S", socket, *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=TMUX_TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "tmux {} failed".format(args[0]))
    return result.stdout


def read_options(socket, pane):
    """The pane's session name and its dashboard options."""
    separator = "\x1f"
    output = _tmux(
        socket, "display-message", "-p", "-t", pane,
        separator.join(["#{session_name}"] + ["#{%s}" % option for option in OPTIONS]),
    )
    values = output.rstrip("\n").split(separator)
    if len(values) != len(OPTIONS) + 1:
        raise RuntimeError("unexpected tmux reply for pane {}".format(pane))
    return values[0], dict(zip(OPTIONS, values[1:]))


def write_options(socket, pane, changes):
    commands = []
    for option, value in changes.items():
        if commands:
            commands.append(";")
        if value is None:
            commands += ["set-option", "-p", "-u", "-t", pane, option]
        else:
            commands += ["set-option", "-p", "-t", pane, option, value]
    _tmux(socket, *commands)
    # Redraw now rather than at the next one-second tick. With no client
    # attached there is nothing to redraw, and tmux reports an error.
    try:
        _tmux(socket, "refresh-client", "-S")
    except (RuntimeError, subprocess.SubprocessError):
        pass


def _lock_path(socket, pane):
    name = "digits-env-dashboard-{}-{}.lock".format(
        os.getuid(), "".join(c if c.isalnum() else "_" for c in socket + pane)
    )
    return os.path.join(tempfile.gettempdir(), name)


def main(stdin=None, environ=None, now=None):
    environ = os.environ if environ is None else environ
    pane = environ.get("TMUX_PANE", "")
    socket = socket_path(environ.get("TMUX", ""))
    if not socket or not pane.startswith("%") or not pane[1:].isdigit():
        return 0  # not inside tmux: nothing to publish
    try:
        event = json.load(stdin if stdin is not None else sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input is not a JSON object")
        # Hooks for parallel tool calls can overlap; serialise read-modify-write.
        with open(_lock_path(socket, pane), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            session, current = read_options(socket, pane)
            if session != SESSION:
                return 0  # a chat outside the dashboard: leave its pane alone
            changes = transition(current, event, int(time.time()) if now is None else now)
            changes = {k: v for k, v in changes.items() if (v or "") != current.get(k, "")}
            if changes:
                write_options(socket, pane, changes)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("Digits dashboard hook: {}".format(error), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
