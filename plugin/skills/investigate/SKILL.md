---
name: investigate
description: Evidence-first investigation of incidents and anomalies. Starts from the original artifact (alert, log query, chat thread, ticket, pull request, CI run, incident or data anomaly), finds the change that introduced the behavior, challenges its own conclusions, weighs options including doing nothing by impact, blast radius and cost, collects every decision in one batch, and produces only approved follow-ups. Use when asked to investigate, triage, dig into or look into something, or to explain why a failure, alert, incident or anomaly happened.
user-invocable: true
---

# Investigate

Usage: `/digits:investigate <artifact: link, ticket key, monitor ID, CI run URL, or pasted output>`

## Ground rules

- **This is a procedure, not a permission.** Anything that writes, touches
  production, publishes or posts is still governed by the always-on Digits
  rules. Load context pages (engineering decisions, infrastructure lifecycle,
  MCP diagnosis) only when the case actually needs them.
- **Handoff file.** If the work could outlast this session, maintain
  `files/handoff.md` in the session workspace with four parts: status,
  findings, open questions, next actions. When resuming, read it before
  anything else. Whenever you point the user at the handoff, or at a long draft
  stored beside it, give its absolute `file:///` URL and a copy-pasteable
  `md-view '<absolute path>'` command.
- **No durable memory.** Investigation state never goes into long-term memory;
  it lives in the session workspace only.

## Phases (in order)

### 1. Artifact first

Look at the primary object before forming any hypothesis:

- alert: the monitor's event timeline;
- logs: the exact query that was run;
- chat: every message and every reply in the thread;
- ticket: its comments and linked items;
- pull request: its review threads;
- CI: the log of the failing job.

Write down the time window (with timezone) and the environments, tenants,
accounts and services involved. If the user only described the problem in
words, find the artifact before going further.

### 2. Evidence

- **Measure directly** in the authoritative systems: logs, metrics, job runs,
  warehouse query history, and the version actually deployed in each
  environment. The default branch says nothing about what is deployed.
- **Prior knowledge.** Search tickets in every status (including Done and
  Won't Do), earlier chats (Copilot: `session_store_sql`; Claude Code:
  `python3 "<absolute-skill-directory>/../self-improve/session_history.py" turns --grep <term>`,
  with the placeholder replaced by this `SKILL.md`'s absolute parent directory),
  decisions recorded in chat, and current or past incidents. Never file a duplicate of something already
  tracked.
- **Origin.** Find the commit that introduced the behavior with pickaxe and
  line-history search (`git log -S`, `git log -L`), see which releases carry
  it with `git tag --contains`, then trace its PR, its ticket, and the date it
  reached each environment.
- **Missing access.** Hand the user a read-only query or command, explain what
  each plausible result would mean, and wait for the answer. Never invent the
  result, never switch role or credentials, and never fall back to
  production-sized compute.
- **Back-test.** Before proposing a change to a limit, threshold, schedule or
  monitor, replay it over recent real data and show how it would have behaved.

### 3. Challenge gate

Run `/digits:challenge-pass` before you state a root cause, before you
recommend any action (or no action), and before calling anything broken,
benign, fixed, safe or harmless. Fold its corrections into the analysis itself;
anything it could not verify stays visible as an open question.

### 4. Presentation

Lead with the answer, then the evidence. The options always include
"do nothing". For each option state:

- what it does and what remains unfixed;
- concrete impact: who notices (users, partners, downstream jobs);
- blast radius: environments, tenants, datasets, services;
- cost: money, compute or CI capacity, alert noise, and the engineering effort
  to build and maintain it;
- whether it can be reversed;
- dependencies such as release order, approvals or other teams;
- an owner.

Finish with exactly one recommendation. For long threads, open with a recap:
what is settled, what is open, and which objections are on the table.

### 5. Decision batch

Use a single batched ask (the Digits bootstrap's Communication rule: one `ask_user` or `AskUserQuestion` call, or one numbered list when the decisions do not fit) that lists every pending decision (for example:
fix or not, file a ticket or not, where to post, whether to suppress, whom to
notify), each with options and a recommended default. If the user replies with
bullets, map them one by one and ask about any bullet that does not map.

### 6. Artifacts

Shape every output according to `references/artifact-shapes.md`. Before any
external write, show the exact text and get the approval that applies. Ticket
fields follow the issue-tracker conventions defined in the bindings or context.
After publishing, re-read each artifact to confirm it rendered correctly and
landed in the intended place.

### 7. Wrap-up

- Refresh the handoff and the ticket: what is done and what remains.
- Ask whether a rule, test, check or monitor would have caught this sooner;
  prefer deterministic checks over written guidance.
- Lessons about Digits itself go to `/digits:self-improve` or to a harness edit
  the user has approved, never to ad hoc memory.
- For anything repaired by hand, offer a ticket plus a draft PR that encodes
  the repair.

## Non-goals

No writes, posts, ticket creation or production actions without the approval
described in phase 6, and no durable-memory writes.
