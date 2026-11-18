# Resume, ownership, and evidence continuity

Use when resuming earlier work, handing work off, fanning work out to several environments or agents, inspecting another environment, or reconciling a status that might be out of date.
Scope: per-session and per-workstream state only; this page sets no durable shared policy.
Sources: the maintainer's agreements and the plugin's `inter-env` skill.
Reviewed: 2026-11-16.
Recheck: the user's most recent decisions, the exact session identity, refs, receipts, and current activity on the target.

## Reconcile before acting

Decision procedure:

1. Identify the current session or workstream, the checkout in use and its status, the latest decision the user made, and concrete proof of what was actually implemented.
2. Treat summaries and earlier reports as leads to follow, never as proof that something ran.
3. If the advice depends on a live chat or PR conversation, reread everything new since your last look before every handoff, draft, or go/no-go recommendation.
4. Compare old plans with later decisions and with the published, source, and runtime artifacts before repeating any step.
5. Record live state in session artifacts, not in this library.

Reading history:

- Cloud history can trail behind; when a recent turn you know about does not appear, fall back to a bounded read of local history.
- Read the user's corrections, not only the assistant's output.
- A summary that is missing or generic, or a turn that merely acknowledges something, is no evidence that a chat has gone idle.
- Stakeholders can reverse requirements within minutes, so a reply that arrived after your last read can change the answer.

Timestamps and review cursors:

- Restarts and reindexing can shift the timestamp of an indexed turn even though the stored message has not changed.
- Use date-bounded indexes for discovery, but a borderline or suspicious hit only counts as "new" after you have checked the original event IDs and stored timestamps of the relevant user and assistant messages.
- Open only the visible messages you need; never dump tool payloads, hidden reasoning, or entire histories.
- Deduplicate by event identity or content, and keep the review cutoff fixed while you work.
- Prompts sent to delegated agents, and what they returned, are not user decisions and carry no operational authority.
- When the real timing cannot be demonstrated, log the gap and keep the last good review cursor where it is.

Stale plans:

- A preview, repair, grant, or recovery that has already happened is not repeated merely because an outdated checklist still lists it.
- Keep historical evidence; mark obsolete instructions or state as superseded instead of quietly treating them as current.

## Compact workstream packet

Keep a minimal packet in the owner's session workspace containing:

- the ticket or workstream, the exact owning environment and session, the objective, and what is excluded;
- the actions approved right now, with exact targets or refs, their side effects, and where the approval came from;
- status broken into implemented, published, released, deployed, and accepted, each backed by dated evidence;
- local-only or dirty work and any unique refs that must be protected, plus decisions that have since been superseded;
- the current dependency, the actual blocker, the next action, who performs it, and which approval is needed next;
- any temporary mitigation, together with the ticket for its permanent fix and the place where that fix will be verified.

Packets and approval:

- A packet carries evidence from one chat to another; it never carries authority.
- Advice from a different chat, a green CI run, or an approval that has gone stale does not authorize a new action or a new target.
- A scoped approval given explicitly in this chat stays valid until the user withdraws or changes it. Do not demand repeated acknowledgements while approved work is ready, and do not cancel every approval just because a chat was resumed or a head moved.
- Example: monitoring an approved rollout may continue after a purely informational handoff, but that does not grant a new deployment.
- Example: approval to apply or merge one exact head does not extend to a different head or target.
- When a boundary has shifted, say which one changed and that it needs fresh approval.

## Other environments

- Use the loaded `inter-env` skill, and the helper shipped with it, to identify environments, read their progress, and deliver messages that were individually approved.
- Never pick a target by the newest file, a pane title, or a hard-coded pane ID.
- Tell apart several chats running in the same environment, and keep approval prompts exactly as they are.
- Never type raw keystrokes into, write files inside, or restart a busy chat that belongs to another environment.
- Report the incremental progress, the real blocker, whether it fits and who owns it, and the exact message you propose to send.
- Before you summarize where a ticket or PR stands, what should happen next, or how far its rollout has got (and before you pick it up yourself), consult inter-env progress and recent local history to find out whether some other environment is already driving it; if one does, name that owner rather than duplicating the work.
- When you defer to another owner, hand over the open risks explicitly (what must be checked and by when) and obtain an acknowledgement. A promise not to duplicate work does not close the risk.

## Fanning out work

Every environment, subagent and delegated agent shares one machine. Running several
heavy jobs at once can exhaust memory, and on macOS a starved machine may also flood
the screen with keychain password dialogs that block typing.

1. Before dispatching work to more than one environment or agent, check that at least
   30% of memory is free (`memory_pressure`) and that the one-minute load average
   (`uptime`) is below the core count (`sysctl -n hw.ncpu`). Otherwise wait, or
   dispatch less.
2. Run one heavy job at a time across the machine: a full test suite, a build, or an
   extra agent process. Delegates run only the tests their change touches; the
   coordinator runs full suites one branch at a time.
3. Never start an extra agent process (a headless or test instance of the host CLI)
   without the coordinator's approval, and never more than one at a time. Each reads
   its login from the system keychain. Prefer asking the user to check something in a
   chat that is already open.
4. Shut down any tmux server or other test service you started as soon as you finish.
5. Repeat rules 2 to 4 in every delegated brief; the recipient cannot see this chat.
6. When the user reports slowness or popups, stop dispatching and tell every delegate
   to stop. A coordinator's stop overrides the task.

## Scheduling and recovery

- Treat these as five distinct claims: something is scheduled; its trigger fired; the job executed; its output got saved; a person looked at that output.
- Hunt for receipts showing a job started, finished, or failed, and note which period each receipt actually spans.
- State gaps plainly; "no failures that we noticed" is not an all-clear when sources are missing or stale.
- Do not blame sleep, reboots, authentication, or time zones without evidence.
- Every target has a single execution owner; never add a second supervisor to make up for uncertainty.
- Finishing one stage proves nothing about the others: recovery, data acceptance, rollout, release, and local code with its CI each need separate evidence that they are done.
- For a brief update about blocked work, follow the [writing reference](../references/writing.md) instead of replaying the whole packet.
