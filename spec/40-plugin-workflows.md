# Digits plugin: workflow skills and their helpers

This file specifies seven of the fourteen plugin skills, the three Python
helpers that ship with them, and the Python test module that covers them. The
plugin manifest, lifecycle extensions, the remaining skills (`inter-env`,
`self-improve`, `summarize`, `done`, `standup-update`, `request-review`), and
the plugin README live in `30-plugin-core.md`. Conventions from
`00-overview.md` apply throughout (Python 3.9 standard library only, `unittest`,
no network or real services in tests, no hardcoded home paths).

| Section | Skill | Bundled files |
|---|---|---|
| 2 | `investigate` | `references/artifact-shapes.md` |
| 3 | `challenge-pass` | `references/challenger-prompt.md` |
| 4 | `assess-and-address` | none |
| 5 | `draft-pr-sweep` | `pr_status.py` |
| 6 | `rebase-pr` | none |
| 7 | `update-shared-workflows` | `shared_refs.py` |
| 8 | `review-reactions` | `reaction_plan.py` |
| 9 | (tests) | `tests/test_adapted_skills.py` |
| 10 | Acceptance tests | |

## 1. Shared conventions for these seven skills

### 1.1 File layout (MUST)

```text
plugin/skills/investigate/SKILL.md
plugin/skills/investigate/references/artifact-shapes.md
plugin/skills/challenge-pass/SKILL.md
plugin/skills/challenge-pass/references/challenger-prompt.md
plugin/skills/assess-and-address/SKILL.md
plugin/skills/draft-pr-sweep/SKILL.md
plugin/skills/draft-pr-sweep/pr_status.py
plugin/skills/rebase-pr/SKILL.md
plugin/skills/update-shared-workflows/SKILL.md
plugin/skills/update-shared-workflows/shared_refs.py
plugin/skills/review-reactions/SKILL.md
plugin/skills/review-reactions/reaction_plan.py
tests/test_adapted_skills.py
```

Each helper starts with a `#!/usr/bin/env python3` shebang and a module
docstring summarizing its usage, is importable as a module without side effects
(all work happens in a `main(argv)` function called only under
`if __name__ == "__main__"`), and exits with `main`'s return value. Skills
always invoke helpers as `python3 "<skill-dir>/<helper>.py" ...`, where
`<skill-dir>` is resolved at runtime to the installed skill directory. Per
`00-overview.md`, files with a shebang are committed executable.

### 1.2 SKILL.md frontmatter (MUST)

Every `SKILL.md` in this file begins with exactly these three keys between
`---` fences, in this order, with no other keys and no blank lines:

```text
---
name: <directory name>
description: <one line, non-empty, starts with a non-space character>
user-invocable: true
---
```

- `name` equals the skill's directory name.
- `description` is a single physical line. The wording below is a suggested
  fresh phrasing; any wording is acceptable if it conveys the listed triggers.
- No `allowed-tools`, model, or other invocation keys are present.
- The file (including frontmatter) is at most 190 lines.
- After the frontmatter: a level-1 title, then a `Usage:` line showing the
  `/digits:<name>` command form, then the body sections described below.

### 1.3 Required literal phrases (MUST)

The test suite looks for write-gating wording verbatim. Each SKILL.md listed
here MUST contain the given substrings (case-sensitive), used naturally inside
its gating rules:

| Exact substrings that must appear | In the SKILL.md of |
|---|---|
| `--force-with-lease=refs/heads/<head>:<old-sha>` | `rebase-pr` |
| `Do not hardcode` ; `only after approval` | `review-reactions` |
| `never commits or pushes` | `update-shared-workflows` |
| `re-read the PR head` ; `read-only` | `draft-pr-sweep` |
| `three rounds` ; `never reply, resolve` | `assess-and-address` |
| `never enable auto-merge` ; `Only after explicit approval` | `request-review` (specified in `30-plugin-core.md`) |

### 1.4 Configuration resolution (MUST)

Any organization-specific value a skill needs is taken from, in order:

1. the skill's invocation arguments;
2. the user's private bindings file
   `~/.config/digits/context/tool-and-repo-bindings.md`, which holds Markdown
   `- key: value` lines (comma-separated values for lists);
3. otherwise, one batched ask (spec 30, section 2.1) covering all values still unknown.

Skills never guess channel, user, repository, board, project, or field IDs, and
never hardcode them. Binding keys used in this file:

| Key | Used by | Value | When unset |
|---|---|---|---|
| `standup_priority_query` | draft-pr-sweep | issue-tracker query whose result order is the priority rank | report is unranked |
| `automated_review_size_limit` | draft-pr-sweep | max additions + deletions against the actual base for automated review | no size check |
| `shared_workflow_repos` | update-shared-workflows | comma-separated `owner/repo` list | ask once |
| `review_channel` | review-reactions | chat channel name used for review requests | ask once |
| `review_reaction_feedback` | review-reactions | emoji list: primary first, then aliases | `speech_balloon,comment` |
| `review_reaction_approved` | review-reactions | emoji list | `white_check_mark` |
| `review_reaction_merged` | review-reactions | emoji list | `twisted_rightwards_arrows,merge,merged` |

### 1.5 Session workspace and links

"Session workspace" means the Copilot CLI session folder; intermediate files go
in its `files/` subdirectory (written below as `<session-files>`), never in
`/tmp` and never inside a repository. Whenever a skill refers the user to a
local Markdown file, it supplies the absolute `file:///` URL together with a
copy-pasteable `md-view '<absolute path>'` invocation (viewer defined in
`10-workbench.md`).

### 1.6 Automated-login rule (MUST, shared by both GitHub helpers)

A GitHub login counts as automated if at least one of these is true:

- lowercasing it yields a string containing `copilot`;
- it ends in `[bot]` (case-sensitive comparison);
- it equals (case-sensitively) `github-advanced-security`, `copilot-swe-agent`,
  `github-actions`, or `copilot-pull-request-reviewer`.

The empty login is not automated; any other login counts as human.

## 2. Skill `investigate`

### 2.1 Frontmatter

- `name: investigate`
- Suggested description: "Evidence-first investigation of incidents and
  anomalies. Begins at the original artifact (alert, log query, chat thread,
  ticket, pull request, CI run, incident, or data anomaly), locates the
  introducing change, challenges its own conclusions, compares options (doing
  nothing included) by impact, blast radius and cost, gathers every decision in
  one batch, and produces only approved follow-ups. Use for requests to
  investigate, triage, dig into or look into something, or to explain why a
  failure, alert, incident or anomaly happened."

### 2.2 Usage and preamble

Usage: `/digits:investigate <artifact: link, ticket key, monitor ID, CI run URL, or pasted output>`.

Statements the body MUST make (own wording):

- Authority: this skill is a procedure, not a permission. Writing, production
  access, publishing and posting stay governed by the always-on Digits rules.
  Context pages that matter (engineering decisions, infrastructure lifecycle,
  MCP diagnosis) are consulted only when the case calls for them.
- Handoff: when the work may span sessions, keep `files/handoff.md` in the
  session workspace with four parts (status, findings, open questions, next
  actions); on resuming, read it before doing anything else. Each time the
  agent refers the user to the handoff, or to a lengthy draft stored next to
  it, it gives the link and viewer command described in 1.5.
- Investigation state is never written to durable memory.

### 2.3 Ordered phases

1. **Artifact first.** Inspect the primary object before hypothesizing. For an
   alert that means the monitor's event timeline; for logs, the precise query;
   for chat, every message and reply; for a ticket, its comments and linked
   items; for a PR, its review threads; for CI, the failing job log. Capture the
   time window (with timezone) and the environments, tenants, accounts and
   services in play. When the user gave only a verbal description, track down
   the artifact before continuing.
2. **Evidence.**
   - Direct measurement in authoritative systems: logs, metrics, job runs,
     warehouse query history, and which version is deployed in each environment
     (the default branch proves nothing about deployment).
   - Prior knowledge: tickets in every status (closed as Done or Won't Do
     included), earlier chat sessions (Copilot: `session_store_sql`; Claude
     Code: `../self-improve/session_history.py turns --grep <term>` from the
     installed skill directory, spec 30 section 12.6), decisions
     recorded in chat, current and past incidents. Never open a duplicate
     ticket for something already tracked.
   - Origin: locate the commit that introduced the behavior with pickaxe and
     line-history search (`git log -S`, `git log -L`) and release reach with
     `git tag --contains`; then find its PR, its ticket, and the date it landed
     in each environment.
   - Missing access: give the user a read-only query or command, spell out
     what each likely outcome would imply, and pause for the answer.
     Forbidden: inventing the outcome, changing role or credentials, falling
     back to production-sized compute.
   - Back-testing: any proposed change to a limit, threshold, schedule or
     monitor is first replayed over recent real data, showing how it would
     have behaved.
3. **Challenge gate.** Invoke `challenge-pass` before stating a root cause,
   before recommending an action (or inaction), and before labelling anything
   broken, benign, fixed, safe or harmless. Its corrections are applied inside
   the analysis; whatever it could not verify stays visible as an open
   question.
4. **Presentation.** Answer first, evidence second. The option list always
   contains "do nothing". For every option give: its effect and what stays
   unfixed; concrete impact (who notices: users, partners, downstream jobs);
   blast radius (environments, tenants, datasets, services); cost (money,
   compute or CI capacity, alert noise, engineering effort to build and
   maintain); whether it can be undone; dependencies such as release order,
   approvals or other teams; and an owner. Close with exactly one
   recommendation. For long threads, start with a recap of what is decided,
   what is open, and which objections exist.
5. **Decision batch.** One batched ask lists every pending decision (for
   example: whether to fix, whether to file a ticket, the posting destination,
   whether to suppress, whom to notify), each with options and a recommended default. If the user answers
   with bullets, map them one at a time and ask about any that do not map.
6. **Artifacts.** Shape them per `references/artifact-shapes.md`. Before any
   external write, display the exact text and obtain the applicable approval.
   Ticket fields follow whatever issue-tracker conventions the bindings or
   context define. After publishing, re-read each artifact to confirm it
   rendered correctly and reached the intended destination.
7. **Wrap-up.** Refresh the handoff and the ticket (what is done, what
   remains). Consider whether some rule, test, check or monitor would have
   caught the problem earlier, preferring deterministic checks over written
   guidance. Lessons about Digits itself are routed to `/digits:self-improve` or
   to a harness edit the user has approved, never to ad hoc memory. For anything repaired by
   hand, offer a ticket plus a draft PR that encodes the repair.

### 2.4 `references/artifact-shapes.md` content (MUST cover, own wording)

A title and a short preamble: publishing anything requires the applicable
approval, and the exact text, destination and posting identity are shown first.
Then five sections:

1. **Tickets** (any tracker). Look for an existing ticket first; when one
   exists, propose commenting there and explain why. The description is
   actionable: a short problem statement followed by acceptance criteria;
   extended analysis and implementation suggestions go in a separate comment
   headed as recommendations. Link the change that introduced the problem and
   any related incidents or duplicates. State impact concretely (observed
   symptom, affected environments or tenants, frequency, cost when relevant)
   and cover the entire blast radius rather than only where it surfaced.
   Required fields come from bindings or context; custom field IDs are never
   guessed; the created ticket is read back.
2. **Comments and posts** (tickets, GitHub, chat, incidents). The opening
   sentence carries whatever alters the reader's view: the answer, a
   correction, or a fact contradicting current belief. Evidence comes after.
   Analysis comments contain evidence a reader can re-run (queries, links,
   time windows). When drafting in the user's voice, preserve their phrasing
   and layout; sharpen claims without changing tone.
3. **Corrections.** Correct the claim in every location it reached (thread,
   ticket, PR description, canvas). Order: what was wrong, what is right, what
   follows from that. Tell readers plainly to disregard the earlier figure.
   Edit the original where possible and mark it as revised.
4. **Draft PRs.** Created only on request and in draft state by default. The
   title names the ticket key and carries whatever release marker the
   repository mandates. Generated
   outputs are committed together with the change that generates them. State
   dependencies, merge order, and any cost approval required.
5. **Closures and no action.** A no-action result is acceptable: record the
   evidence and the reason (for example it is rare, recovers by itself, was
   fixed upstream, or costs more than it is worth) and propose the closing
   status. For noisy alerts, pick among a downtime, a suppression, a monitor
   adjustment or nothing, and explain why each alternative was rejected. A
   real availability or data-loss signal is never muted for the sake of quiet.
   Every downtime has an end time and links a ticket.

### 2.5 Non-goals

No writes, posts, ticket creation, or production actions without the approval
named in phase 6; no durable-memory writes.

## 3. Skill `challenge-pass`

### 3.1 Frontmatter

- `name: challenge-pass`
- Suggested description: "Put an investigation's conclusions through a fresh,
  read-only subagent prior to sharing them or calling one the root cause. It
  probes each claim for direct observation, earlier history, recent change,
  whole-population coverage, sourcing, a more direct signal, the real meaning
  of labels, independent confirmation, fit to the original goal, and
  consistency. Use before publishing analysis, asserting a root cause, or
  declaring something broken, benign, fixed, safe or harmless, and whenever
  asked to sanity-check or challenge an analysis."

### 3.2 Usage and when to run

Usage: `/digits:challenge-pass [claims or analysis text; default = current conclusions]`.

Rationale the body gives (own wording): a few targeted questions that compare a
conclusion with evidence outside the agent's current context catch most
justified objections, and asking them from a clean context avoids anchoring on
the first explanation that seemed to fit.

When: before results go anywhere shared (chat, ticket, PR, incident); before
naming a root cause; before advising a production change, a new ticket, or no
action at all; before declaring anything missing, broken, harmless, benign, safe, fixed or
self-healed. Not needed for simple factual lookups or routine code edits.

### 3.3 Ordered steps

1. **Claim sheet**, four parts:
   - Goal: one or two lines identifying the originating question, ticket or
     incident.
   - Claims, numbered: each lists its supporting evidence (precise query, tool
     or source, the result, the time window) and the observation that would
     refute it.
   - Already examined: repositories, environments, windows, tickets, threads
     and sessions covered so far, so the challenger expands coverage instead of
     duplicating it.
   - Pointers: file paths, ticket keys, links, environment or tenant, window.
2. **Launch the challenger**: a single subagent of type `general-purpose`
   (lookup tools are needed). Its prompt is the full text of
   `references/challenger-prompt.md` with the claim sheet appended. When the
   sheet holds roughly nine or more claims, or spans several systems, divide the claims among
   two or three challengers running in parallel; every one receives the
   complete goal and context.
3. **Verify the challenger.** Its findings can be confidently mistaken: any
   finding that would alter a conclusion is re-checked against the cited
   source before it is accepted. Then each claim is classed as:
   - Holds: no contrary evidence surfaced, or new support surfaced;
   - Changed: corrected, narrowed or withdrawn, with the evidence;
   - Unverified: blocked on access the agent does not have; retain the
     read-only query (or the question to ask) able to decide it and the interpretation
     of each possible answer.
4. **Report first.** Begin with a brief section titled "Challenge pass": what
   changed and why, what is still unverified, and the questions or queries for
   the user. Changed claims are rewritten in the body of the analysis rather
   than footnoted. Only afterwards may posts be drafted, under the normal
   approval rules. A change caused by a recurring mistake leads to a proposed
   lesson, routed through `/digits:self-improve` or a user-approved harness
   edit.

### 3.4 `references/challenger-prompt.md` content (MUST cover, own wording)

A title; one line saying the subagent receives this whole file followed by the
claim sheet; a horizontal rule; then the prompt itself:

- **Stance.** The subagent is an adversarial reviewer of conclusions that are
  about to be shared. Every claim is unproven until it meets the bar a
  skeptical senior engineer would set. It hunts for weak points, neither
  agreeing by reflex nor inventing objections; confirming a claim with extra
  evidence is a useful outcome.
- **Rules.**
  - Read-only everywhere: in no system may it send, deploy, merge, approve,
    create, edit, transition, comment or post; it must not run warehouse
    queries that scan large volumes or use production-scale compute, nor exec
    into live workloads. In those cases it writes the read-only query or
    command out for a person to run.
  - It never changes credentials, roles, accounts or connections; any auth or
    permission failure is listed under "Not checked".
  - Every command is pinned to an explicit directory (`git -C`, `env -C`);
    any invocation of `gh` names its repository with `--repo owner/name`.
  - Each finding quotes exact evidence (query plus result, file plus line,
    ticket key, message link); inference is never dressed up as a finding.
- **Ten questions**, each applied to every claim it fits:
  1. Direct observation: consult the primary source (monitor history, live
     configuration, the ticket's own timestamps, the present value) and redo
     calculations from raw figures.
  2. History: search about a year of the issue tracker (Done and Won't Do
     included), earlier sessions, chat threads with their replies, repository
     docs, and code comments that capture decisions.
  3. Changes the code does not reveal: per-environment deployed versions,
     flags and rollout percentages, sampling or retention edits, configuration
     applied but not yet live, manual operations, incidents inside the window.
  4. Population: compare the claimed scope with the complete set
     (repositories, tenants, datasets, partitions, time buckets) and widen and
     recount where it matters.
  5. Sources: identify where each surprising or load-bearing fact comes from;
     check that cited APIs, flags, fields, grants and settings really exist;
     flag inference presented as if documented.
  6. Directness: prefer, e.g., status codes to string matching, unsampled
     metrics to sampled logs, query history to dashboards, deterministic checks
     to instructions.
  7. Labels: for words such as "best effort", "handled", "benign",
     "self-healed", "harmless" or "rare", inspect what the code or data
     actually does.
  8. Strong claims: anything described as broken, missing, zero, never, safe
     or harmless gets a second, independent confirmation.
  9. Goal fit: does the conclusion or fix answer the original goal directly;
     is it excessive; does a standard solution exist; is the true defect
     upstream (a bad value being accepted at all)?
  10. Consistency: do claims, numbers or recommendations conflict; do rates,
      totals and durations add up?
- **Output** in Markdown, five sections in this order: (1) Verdicts, a table
  whose columns are claim number, deciding question(s), verdict (one of
  `holds`, `changed`, `unverified`) and evidence; (2) Changes, giving the
  corrected wording of every `changed` claim; (3) To verify, giving for every
  `unverified` claim the read-only query, command or question to settle it,
  the person or role able to run it, and how to read each possible result; (4) New facts worth knowing
  even when no claim changed; (5) Not checked, naming each unanswered question
  with the reason.

## 4. Skill `assess-and-address`

### 4.1 Frontmatter

- `name: assess-and-address`
- Suggested description: "Go through every open pull request review thread and
  top-level review comment, decide whether each is correct, commit focused
  fixes for the valid ones, reply to and resolve threads raised by automated
  reviewers, and draft (never post) answers for human reviewers. Use for
  requests to address or work through PR feedback or review comments, including
  Copilot and other bot findings."

### 4.2 Usage and write rules

Usage: `/digits:assess-and-address [owner/repo#N or PR URL] [push]`.

Rules stated at the top of the body:

- **Automated sources** (Copilot and other AI review bots, logins ending in
  `[bot]`, review comments posted by github-actions): once an item is fixed,
  rebutted, or deferred with a recorded reason, the agent may reply in that
  thread and mark it resolved with no confirmation needed.
- **Human reviewers**: the body contains the literal `never reply, resolve` in
  a rule saying the agent takes none of these actions for a human (replying,
  resolving, reacting, re-requesting review) unless the user approved the
  precise text and action; it prepares drafts instead.
- **Pushing** happens only on request: the invocation includes the word
  `push`, or the user approves pushing during step 7. Force-pushing is out of scope here (`rebase-pr` owns it), as are
  merging, marking ready, and posting to chat.

### 4.3 Ordered steps

1. **Target and checkout.** Take the PR from the argument, else the current
   branch's PR; confirm the repository by passing an explicit `--repo`; note the
   head SHA. Acceptable workspaces: a clean checkout on the PR branch owned by
   this chat, or a fresh worktree. Prohibited: switching, stashing or resetting
   a checkout that holds someone else's changes, and adopting a branch another
   chat is working on.
2. **Retrieve feedback with GraphQL**: review threads (node ID, `isResolved`,
   `isOutdated`, path, line, every comment with its author) and reviews whose
   body is non-empty. Follow `hasNextPage` to the end on every connection;
   default page sizes (such as 50 threads or 5 comments per thread) are not
   enough. Top-level review bodies carry design feedback with no line anchor
   and are included. An item is actionable when its thread is unresolved, not
   outdated, and its newest comment is not the user's. Outdated threads are
   still compared with current code because the point may still hold.
3. **Assess.** Record the source (human or automated) and category (bug or edge
   case, logic, missing test, security or performance, convention, docs, style,
   design, question). Check against the code, not against the comment's own
   account: read at least 50 surrounding lines and related PR files; look for
   established patterns, repository instructions and lint configuration;
   confirm that every method, field, flag or behaviour the comment mentions
   really exists. Automated reviewers frequently suggest patterns foreign to the repository or
   misjudge intent, and a "minor" note can conceal a serious problem, so check
   what the code is actually for. Outcome: **valid**, **invalid** or **needs
   decision**. Human comments about design or scope (for instance, adopt a
   shared module, or relocate some code) are the user's decision: ask first.
   Flag items that would need large architectural change.
4. **Fix.** One commit per finding unless several findings form one logical
   change. Stage named paths only; respect how the repository writes commit messages,
   its signing configuration, and any release or version-bump rule. For a regression
   test, show that it goes red when the fix is absent: briefly put the
   committed source back to its pre-fix state, run the test, then reinstate the
   fix. Uncommitted test or user work is
   never thrown away. Relevant lint and tests run before anything is pushed.
5. **Automated threads.** Fixed: answer citing the commit, then resolve.
   Invalid: answer with a short concrete reason (such as the repository pattern
   it conflicts with), then resolve. Deferred: answer with the reason and the
   follow-up ticket when one exists, then resolve. If a human has posted in that
   thread, do not answer there. Answers use the GraphQL mutation
   `addPullRequestReviewThreadReply`; resolution uses `resolveReviewThread`.
6. **Human items.** Nothing is posted. For each, prepare: location and
   reviewer, the point raised, the agent's assessment with evidence, the commit
   addressing it (if any), and a proposed reply. A single batched ask
   covers all of them, with per-item choices for the reply (post / edit / skip)
   and the thread (resolve / leave open). Only the exact approved text is
   posted.
7. **Push and bounded re-review.** Just before pushing, read the PR head and
   requested reviewers again; should another session have pushed, or review
   state have moved, after step 1, halt and report it. If the invocation lacked `push`, ask once,
   showing the commits and check results. Push without force. Re-review applies
   only when the agent pushed and an automated reviewer has already reviewed
   this PR: wait without sleep loops, either by blocking on the corresponding
   review workflow run using `gh run watch <run-id>` together with `--repo` and
   `--exit-status`, or by checking again on the next turn. Repeat steps 2-6 for
   new findings, capped at `three rounds` (literal) per invocation. Stop sooner
   when the latest automated review adds no comments, when only declined or
   human items remain, or when no review shows up within a few minutes. Never
   presume a repository re-reviews on push; confirm it for each PR. Finally
   check CI on the exact new head, treating skipped jobs as not passing.
8. **Report**, in short sections: what was addressed (commit and finding);
   automated threads answered and resolved; human items awaiting a decision with
   proposed replies; how many re-review rounds ran and why they ended; CI
   status for the exact head commit; and any lesson worth turning into a repository rule or
   test (offered, never added unasked).

### 4.4 Non-goals

No human-thread writes without approval, no force-push, no merge, no ready
toggle, no chat posts, no durable rule changes unasked.

## 5. Skill `draft-pr-sweep` and helper `pr_status.py`

### 5.1 Frontmatter

- `name: draft-pr-sweep`
- Suggested description: "Read-only triage of the user's open draft pull
  requests that groups each by its next move (a blocking label, an unmet
  dependency, merge conflicts, CI state, a review already in flight, feedback
  to assess, or readiness for review), offers follow-up actions in one approval
  form, and delegates approved work through the rebase-pr, assess-and-address
  and request-review skills. Use for requests to sweep or triage my draft PRs or
  report where they stand."

### 5.2 Usage and gating

Usage: `/digits:draft-pr-sweep [owner/repo#N ...]`.

The body declares the sweep `read-only` (literal): it does not push, rebase,
comment, post, request reviews, change draft state, or assign tickets. Nothing
happens until the user approves it in step 3, and each approved action is
carried out by the skill that owns it.

### 5.3 Ordered steps

1. **Collect status.** Run `python3 "<skill-dir>/pr_status.py"` with any
   targets and redirect stdout to `<session-files>/draft-pr-status.jsonl`
   (never `/tmp`, never a repository). With no targets the helper covers all
   open drafts whose author is the `gh`-authenticated user. Every line reports
   state, CI rollup, when the automated review happened, open threads split
   into human and automated, dependency hints, and a proposed `bucket`. A
   `bucket: error` line means that PR could not be read: report it, do not
   guess.
   - Ranking: if the bindings define `standup_priority_query` (for example a
     tracker query selecting this week's labelled, unfinished tickets assigned
     to the current user, ordered by rank), execute it, read-only, with
     whichever issue-tracker tools discovery finds. Associate PRs with tickets by
     a ticket key found in the PR title, head branch or body. Sort the form and
     the report in rank order with PRs lacking a ticket at the end, and mention
     ranked tickets for which no PR is open. Without a configured query, or when the tracker cannot be reached, say
     the order is unranked; boards and projects are never guessed.
2. **Confirm buckets.** Helper precedence, first match wins:

   | Bucket | Situation | What to offer |
   |---|---|---|
   | `skip-blocked-label` | a blocking or do-not-merge style label | nothing; state what would unblock it |
   | `check-dependency` | the body cites a dependency, stack parent or merge hold | verify the dependency's current state; if satisfied, re-bucket and offer to remove the outdated note |
   | `rebase` | GitHub marks it conflicting | `rebase-pr` |
   | `review-in-flight` | an automated reviewer is currently requested | nothing now; look again at the end |
   | `check-active-elsewhere` | the head changed under 15 minutes ago | identify the owning chat; hands off |
   | `fix-ci` / `ci-pending` | head checks failing / still running | read the failing job and offer a fix, or wait |
   | `to-assess` | open threads waiting on the user | hand to `assess-and-address` |
   | `no-automated-review` | never reviewed automatically | ask for an automated review using the repository's mechanism |
   | `check-stale-review` | commits newer than the last automated review | if they only implement that review's findings, treat as ready; otherwise offer a new review |
   | `ready-candidate` | no earlier rule matched | hand to `request-review` (mark ready, chat post, optional ticket transition) |

   Hints are re-derived, not trusted: read the dependency PR's or release's live
   status and inspect `commitsAfterReview`. Threads in which the user spoke last
   need nothing. A cherry-pick that gets a fresh review may be flagged for code
   already present on the default branch; that fix goes there first. A merged
   stack parent leaves an outdated dependency note behind.

   Pre-checks before offering a `ready-candidate`: CI green on the exact head
   (skipped jobs do not count); the title has any mandatory release marker; and,
   when `automated_review_size_limit` is configured, the diff against the
   actual base is within it. A failed pre-check moves the PR to the matching
   bucket.
3. **Single approval form.** Exactly one batched ask. One question per PR (or
   per set of PRs sharing a ticket); the field description shows the evidence
   (bucket, CI status, what the automated review concluded, human threads still
   open, caveats); the
   choices are the offered action(s) plus "Skip", with a recommended default.
   Suggested reviewers are drawn from reviewers already requested on the PR or
   from the team that owns the repository; `request-review` maps them to chat users or groups
   at run time.
4. **Execute approved actions.** Prior to every action,
   `re-read the PR head` (literal) and its review requests; if since the sweep
   another session has pushed, requested review, or marked it ready, skip it and
   say why.
   - Rebase: hand to `rebase-pr`, one PR after another.
   - Assess: hand to `assess-and-address`, one PR after another; approval in
     this form extends to that skill's push only if push was an explicit choice
     in the form.
   - Automated review request: `gh pr edit` with `--repo` and
     `--add-reviewer @copilot`, only for repositories that use that reviewer;
     otherwise whatever trigger the repository documents for a different
     automated reviewer.
   - Ready: hand to `request-review`, choosing its option that marks the PR
     ready; PRs that share a ticket go in one message.
   At the end, revisit `review-in-flight` PRs and freshly requested reviews
   (they usually complete within minutes), without sleep loops.
5. **Report.** A single table whose columns are PR (link text shows repository
   and number), bucket, action taken or reason for skipping, and what would
   unblock each skipped PR. After it, list what only the user can unblock:
   pending apply gates, decisions on human reviews, and dependencies that must
   be released. Propose ticket status follow-ups without
   changing any ticket.

### 5.4 Gotchas section (MUST include, own wording)

- GraphQL is used because the CLI's `reviewRequests` JSON field leaves out the
  Copilot reviewer.
- `mergeable` stays `UNKNOWN` until GitHub computes it, so the helper retries
  once.
- A rebase rewrites `committedDate`; staleness therefore uses `authoredDate`.
- The active-elsewhere bucket cannot tell who pushed, so a push the user made
  earlier in the same sweep also lands there.
- Inventories spanning repositories query GitHub, not local clones (their
  default branch may be stale or not named `main`).
- Where a Terraform repository applies infrastructure from PR branches, a PR can display plan
  differences belonging to another open PR's applied state; point this out and
  never approve that gate.

### 5.5 `pr_status.py` command line

```text
pr_status.py [owner/repo#N ...]
```

- No options. Each positional argument must fully match
  the shape `owner/name#number`, where owner and name are each one or more
  characters from `[A-Za-z0-9._-]` and number is one or more ASCII digits,
  with nothing before or after. Any non-matching argument stops
  the program with a message on stderr naming the expected form and the bad
  value, exit status 1, and no records printed.
- Operation order: (1) obtain the current login by running
  `gh api user --jq .login` and stripping whitespace; (2) take the current UTC
  time once; (3) determine targets; (4) for each target, fetch, classify and
  print one line immediately. A failure in step 1 aborts with a non-zero exit
  and no output.
- Targets from arguments are processed in argument order, without
  de-duplication.
- With no arguments, targets come from
  `gh search prs` with the options `--draft`, `--state open`, `--author @me`,
  `--json repository,number` and `--limit 100`.
  From each result row it reads `repository.nameWithOwner` (split at the first
  `/` into owner and name) and `number`. The target list is sorted ascending as
  string triples `(owner, name, number-as-decimal-string)`, so number order is
  lexicographic (`10` before `9`). A failure of this call aborts with non-zero
  exit.
- All `gh` subprocesses run with stdin closed (null device), captured output,
  a 60-second timeout, and fail on non-zero exit.

### 5.6 GraphQL fetch

For each target the helper runs `gh api graphql` with the query passed via
`-f query=...` and variables via `-F owner=<owner>`, `-F name=<name>`,
`-F number=<number>` (typed, so `number` is an integer). The query is
`repository(owner, name) { pullRequest(number) { ... } }` requesting the fields
below. If the returned `mergeable` is `UNKNOWN`, wait 3 seconds and fetch once
more; the second response is used whatever it says.

Fields requested and read (connection sizes are part of the contract):

| Path under `pullRequest` | Used for |
|---|---|
| `number`, `url`, `title`, `isDraft`, `state`, `mergeable` | copied to output |
| `baseRefName`, `headRefName`, `headRefOid` | copied to output; head SHA comparison |
| `body` | dependency hints |
| `labels(first: 20).nodes[].name` | labels, blocked check |
| `reviewRequests(first: 20).nodes[].requestedReviewer` with `__typename`, and `login` for `User` and `Bot`, `slug` for `Team` | requested reviewers |
| `reviews(last: 50)`, per node: `state`, `commit.oid`, `submittedAt`, `author.login` | automated review timing |
| `reviewThreads(first: 100)`, per thread: `isOutdated`, `isResolved`, and `comments(first: 30)` giving per comment `body`, `path`, `author.login` | open threads |
| `commits(last: 30)`, per node's `commit`: `statusCheckRollup.state`, `parents.totalCount`, `messageHeadline`, `committedDate`, `authoredDate`, `oid` | head, CI, commits after review |

The response is read at `data.repository.pullRequest`.

### 5.7 Classification (pure function, MUST)

The module exposes `classify(pr, me, now)` where `pr` is the `pullRequest`
object above (a dict), `me` is the user's login, and `now` is a timezone-aware
UTC datetime. It returns the record of 5.8 without the `repo` key. Timestamps
are ISO 8601; a trailing `Z` means UTC. Derived values:

- **labels**: label names in input order.
- **head**: the last node of `commits` (or none if the list is empty).
- **ci**: the head's `statusCheckRollup.state`, or null when the rollup is null
  or there is no head.
- **automated reviews**: reviews whose author login (missing or null author →
  empty string) is automated (1.6). **last automated review** = the last such
  review in input order. **reviewedAt** = its `submittedAt`, or empty when there
  is none (a null `submittedAt` behaves as empty).
- **commits after review**: only if reviewedAt is non-empty; every commit in
  input order whose `parents.totalCount` is exactly 1 (merge commits excluded)
  and whose `authoredDate` is strictly later than reviewedAt. Each is rendered
  as the first 7 characters of `oid`, one space, then `messageHeadline`.
  `committedDate` is deliberately not used here.
- **requested reviewers**: non-null `requestedReviewer` objects in order.
  **automated requested** is true if any has a `login` that is automated (teams
  have no login and never count).
- **open threads**: threads that are neither resolved nor outdated and have at
  least one comment. For each: `author` = first comment's author login,
  `lastAuthor` = last comment's author login, `path` = first comment's `path`
  (may be null), `body` = first comment's body (null → empty) truncated to its
  first 160 characters, `automated` = whether `author` is automated.
- **awaiting me**: open threads whose `lastAuthor` differs from `me`.
- **dependency hints**: scan `body` (null → empty) case-insensitively, left to
  right, for non-overlapping matches of any of these phrase patterns; keep each
  whole match with surrounding whitespace trimmed; keep at most the first 4:
  1. `depends on`, then an optional `:`, then any whitespace (which may include
     newlines), then 1 to 120 characters that are not newlines (as many as
     possible). It does not match when the text right after `depends on`,
     allowing an optional `:` and whitespace, is the word `nothing`, `none` or
     `n/a` ending at a word boundary (so `Depends on: none` gives no hint but
     `Depends on: nonexistent` does). It needs at least one character after the
     phrase (a trailing space suffices; the trimmed hint is then `Depends on`).
  2. `blocked by` followed by 0 to 100 non-newline characters.
  3. `stacked on` followed by 0 to 100 non-newline characters.
  4. `do not merge` followed by 0 to 80 non-newline characters.
  5. `must not merge` followed by 0 to 80 non-newline characters.
  6. `before merge` or `before merging` followed by 0 to 120 non-newline
     characters.
  The trailing character runs are greedy, so a later phrase on the same line
  inside the consumed span is not reported separately. Original casing is kept.
- **minutes since head**: whole minutes from the head's `committedDate` to
  `now`, computed as floor of elapsed seconds divided by 60 (negative if the
  head is in the future). With no head, elapsed time is zero.

**Bucket** (first matching rule wins):

| # | Condition | Bucket |
|---|---|---|
| 1 | any label, lowercased, equals `blocked`, `do not merge`, `do-not-merge` or `on hold` (exact, not substring) | `skip-blocked-label` |
| 2 | at least one dependency hint | `check-dependency` |
| 3 | `mergeable` is `CONFLICTING` | `rebase` |
| 4 | automated requested | `review-in-flight` |
| 5 | minutes since head < 15 | `check-active-elsewhere` |
| 6 | ci is `FAILURE` or `ERROR` | `fix-ci` |
| 7 | ci is `PENDING` or `EXPECTED` | `ci-pending` |
| 8 | awaiting-me list non-empty | `to-assess` |
| 9 | no automated review exists | `no-automated-review` |
| 10 | commits-after-review list non-empty | `check-stale-review` |
| 11 | otherwise | `ready-candidate` |

`isDraft` and `state` do not influence the bucket. A null ci (no checks) passes
rules 6 and 7.

### 5.8 Output record

One JSON object per line on stdout, serialized with sorted keys at every level,
`", "` and `": "` separators, and non-ASCII characters escaped as `\uXXXX`
(Python `json.dumps(..., sort_keys=True)` formatting). Keys:

| Key | Type | Meaning |
|---|---|---|
| `url` | string | PR URL |
| `number` | int | PR number |
| `title` | string | title |
| `isDraft` | bool | draft flag |
| `state` | string | e.g. `OPEN` |
| `mergeable` | string or null | `MERGEABLE`, `CONFLICTING`, `UNKNOWN` |
| `base` | string | base branch name |
| `headRef` | string | head branch name |
| `head` | string | head SHA (`headRefOid`) |
| `labels` | string[] | label names |
| `ci` | string or null | head rollup state |
| `minutesSinceHead` | int | see 5.7 |
| `automatedReviewAt` | string or null | last automated review time; null when none |
| `automatedReviewOnHead` | bool | true only if a last automated review exists and its `commit.oid` equals `headRefOid` |
| `automatedReviewRequested` | bool | automated reviewer currently requested |
| `commitsAfterReview` | string[] | `"<7-char sha> <headline>"` entries |
| `humanReviewersRequested` | (string or null)[] | for each requested reviewer whose login is not automated: its `login`, else its `slug` (null if neither) |
| `threadsAwaitingMe` | int | size of awaiting-me list |
| `humanThreadsAwaitingMe` | int | awaiting-me threads whose `automated` is false |
| `openThreads` | object[] | each `{author, automated, body, lastAuthor, path}` as in 5.7 |
| `dependencyHints` | string[] | up to 4 hints |
| `bucket` | string | one of the 11 buckets |
| `repo` | string | `owner/name` of the target (added by the CLI, always present) |

**Error record:** if fetching or classifying one target raises a subprocess
failure or timeout, a missing key, a wrong type, or a value/JSON parse error,
the line instead holds exactly `bucket: "error"`, `error` (a message describing
the failure, at most 300 characters; exact text not part of the contract),
`repo`, and `url` = `https://github.com/<owner>/<name>/pull/<number>`. The
sweep continues with the next target. A GraphQL response whose `pullRequest` is
null SHOULD also yield an error record.

**Exit status:** 0 when every target produced a normal record (including zero
targets), 1 when at least one error record was printed.

## 6. Skill `rebase-pr`

### 6.1 Frontmatter

- `name: rebase-pr`
- Suggested description: "Rebase one GitHub pull request onto the current tip
  of its base branch, with ownership preflight, a dedicated worktree, conflict
  resolution that preserves what both sides intended, a semantic check of
  code that merged without conflict, verification, and a lease-guarded force
  push bound to the previously recorded head SHA. Use for conflicting or out-of-date PRs and for
  requests to rebase a PR, bring it up to date, or fix its merge conflicts."

### 6.2 Usage, authority and pace

Usage: `/digits:rebase-pr <owner/repo#N or PR URL> [push]`.

- The invocation alone authorizes a local rebase plus verification.
- A lease-protected push of the rewritten branch is authorized only if the
  invocation includes `push` (or asks to update the PR) **and** the user
  authored all commits on the branch; otherwise ask a single time, showing the
  results.
- Forbidden: pushing without a lease, merging, rebasing a branch owned by
  another chat. Natively stacked PRs go to the built-in `pr-stack` skill.
- Pace: once begun, preflight through report happen in a single turn; never
  say a push is happening unless that turn performs it.

### 6.3 Ordered steps

1. **Preflight (read-only).** `gh pr view <N>` with `--repo` and `--json`
   requesting these fields (any order): `headRefOid`, `baseRefName`,
   `headRefName`, `state`, `isDraft`, `mergeable`, `isCrossRepository`,
   `headRepositoryOwner`, `labels`, `commits`. Native-stack lookup: `gh api`
   against host `github.com`, path `repos/<owner>/<repo>/stacks`, with query
   parameter `pull_request` set to the PR number. Stop and ask if: the PR is
   not open; it originates from a fork; any commit has an author other than the
   user; a label signals blocked or do-not-merge; it is part of a native stack;
   or GitHub already reports `mergeable` as `MERGEABLE` (proceed only if explicitly asked to
   bring it current). `UNKNOWN` means GitHub has not computed it yet: read
   again.
2. **Choose the checkout**, by preference:
   1. a clean checkout on the head branch that this chat owns;
   2. else a new worktree used only for this PR, created with
      `git worktree add` from an existing clone on the head branch; when that
      branch is checked out in some other worktree, a detached worktree
      (`--detach`) at the head SHA instead, later pushing to
      `HEAD:refs/heads/<head>`. Another chat's checkout, or any dirty clone, is
      never switched, stashed or reset.
   3. Fetch `origin` inside the worktree and confirm that the local head,
      `origin/<head>` and the preflight SHA agree; unpushed local commits mean
      halting to ask. Then **record the old head SHA**, which the lease needs.
3. **Context before editing.** Find the merge base of `HEAD` and
   `origin/<base>`; list base commits since the merge base (one line each);
   produce a diffstat of the PR against the base (three-dot form); and show the
   base's changes since the merge base restricted to the PR's files. What each
   side intended is understood first, because mechanically easy resolutions are
   often semantically wrong.
4. **Rebase and resolve.** Rebase non-interactively onto `origin/<base>` with
   `GIT_EDITOR=true` and stdin redirected from `/dev/null`. Every conflicting
   hunk keeps both intents; there is no default side.
   - Both sides reworded the same text: produce one wording carrying both.
   - Lock files and generated outputs (e.g. `*.lock`, `uv.lock`,
     `poetry.lock`, `.terraform.lock.hcl`, dbt or OpenAPI outputs, schema
     dumps): settle the sources first, then regenerate using the repository's
     own tooling.
   - A path that both base and PR add: at every stop retain base's version and
     skip commits that end up empty; at the end add a single commit that folds
     the PR's content in.
   - Ordered or timestamped migrations: renumber the PR's migrations to follow
     base's latest using a generated sequence, fix references, and run the
     repository's migration check as proof.
   - A cancelled command might nevertheless have completed the rebase; run
     `git status -sb` before trying again.
   - Semantic read: for each function the PR touches, read the merged version
     and note anything base introduced that now interacts with the PR's
     behaviour (locking, transactions, retries, handlers, contracts,
     configuration). These go in the report; change them only if a test fails.
5. **Verify** (inside the worktree):
   - `git grep` for conflict markers: lines starting `<<<<<<< ` or `>>>>>>> `,
     or consisting solely of `=======`;
   - log of `origin/<base>..HEAD` showing short hash, signature status (`%G?`),
     author email and subject;
   - `git range-diff` comparing the old range (`origin/<base>...<old-sha>`)
     with the new one (`origin/<base>..HEAD`).
   Pass criteria: zero conflict markers; every author preserved; signature
   status acceptable under the repository's policy; the range-diff differs only in conflict hunks.
   Parse every edited data file. Run lint plus tests covering the PR's files
   and whatever base changed in that same code. A failure elsewhere is environmental
   only when it reproduces identically on `origin/<base>`; say which applies.
6. **Push** with `git push` from the worktree to `origin`, refspec
   `HEAD:refs/heads/<head>`, using the option
   `--force-with-lease=refs/heads/<head>:<old-sha>` (literal; `<old-sha>` is
   the SHA recorded in step 2). Then confirm via `gh pr view`: the new head
   appears, `mergeable` reaches `MERGEABLE` (it can lag a few seconds), commit
   verification still holds where required, and CI has started on the new
   head. Existing automated reviews are now stale; do not request a new one
   unless asked.
7. **Report**: PR link naming the repository; old and new head SHAs; the base
   commit used; for every conflict, the file, what each side changed and how
   they were combined; interactions found in step 4, presented as points for
   reviewers and kept unposted unless the user asks; lint and test outcomes with counts, plus evidence for
   any environmental failure.

### 6.4 Non-goals

No unleased push, no merge, no stash/reset of foreign checkouts, no automated
re-review request, no posting.

## 7. Skill `update-shared-workflows` and helper `shared_refs.py`

### 7.1 Frontmatter

- `name: update-shared-workflows`
- Suggested description: "Check and bump pinned versions of an organization's
  shared GitHub workflow and action repositories: find each repository's
  newest tag (repositories come from arguments or bindings), inventory pinned
  references in one repository, read release notes for breaking changes, then
  apply approved same-major updates through a preview-first helper. Use when
  asked to check, bump or update shared workflow or action versions."

### 7.2 Usage, scope and inputs

Usage: `/digits:update-shared-workflows [repository path] [owner/repo ...]`.

- One confirmed checkout per run (default: the current directory). Files are
  edited only once the plan is approved. The body states that the skill
  `never commits or pushes` (literal) and that it leaves other environment
  directories and other chats' checkouts alone.
- Shared repositories come from (1) `owner/repo` arguments given at
  invocation, else (2) the `shared_workflow_repos` binding (a comma-separated `owner/repo` list), else
  (3) a single batched ask. No repository list is built into the
  helper, so each one is supplied through its own `--repo`. Existence of each is confirmed with
  `gh repo view` rather than by guessing names.

### 7.3 Ordered steps

1. **Target.** Check identity with `git -C <path> remote -v`, the current
   branch, and cleanliness. Unrelated dirty files halt the run (no stashing).
   When a PR is wanted, branch fresh from the verified `origin` default branch.
2. **Inventory.** Run the helper's `latest` for all repositories and
   `scan --root <path>` for all repositories. Present a single table: repository,
   pinned version(s) each with a count, newest tag, and a status of `current`,
   `update`, `mixed`, or non-semver pin (SHA or branch). Non-semver pins are
   never modified but are called out.
3. **Release notes.** For every repository that will change, go through all
   releases from the oldest pinned version up to the target using
   `gh release list` and `gh release view <tag>` (both with `--repo`), or the
   compare view between tags when releases are missing. Breaking-change
   checklist: workflows, actions, inputs, outputs or secrets removed or
   renamed; inputs or permissions newly required; runner or tool changes; major
   bumps. If notes are sparse, compare the changed workflow's declared inputs
   between the two tags.
   Record the risk, the local changes required, and links.
4. **Approval.** One batched ask listing, per repository: current version(s),
   target version, affected files, risk, local changes. Same-major is the default
   scope. A cross-major update needs its own explicit confirmation for that
   repository, and its required local changes ship in the same change.
5. **Apply.** For each approved (repository, old version) pair: helper
   `update` without `--write` as a preview, then again with `--write`; add
   `--allow-major` only for an approved cross-major pair. Then `scan` again and
   check that the total reference count is unchanged, that no approved old
   version is left, and that every ref is well formed. Run `actionlint` when
   installed and review `git diff`.
6. **Report.** A table with repository, previous version, new version,
   references changed and files changed; then risks found in release notes and
   the local edits made; then whatever was skipped, with reasons. Propose a
   commit message, for instance `ci: update shared workflows`. Publishing
   follows the usual delivery rules (draft PR when requested, release markers
   required by the repository, CI verified on the exact head commit).

### 7.4 `shared_refs.py` command line

```text
shared_refs.py scan    [--root DIR] --repo OWNER/REPO [--repo OWNER/REPO ...]
shared_refs.py latest  --repo OWNER/REPO [--repo OWNER/REPO ...]
shared_refs.py update  [--root DIR] --repo OWNER/REPO --from OLD_TAG --to NEW_TAG [--allow-major] [--write]
```

Standard argparse-style parsing: a subcommand is required; unknown options,
missing subcommand, or missing required options (`update`'s `--repo`, `--from`,
`--to`) print usage to stderr and exit 2.

| Subcommand | Option | Meaning |
|---|---|---|
| `scan` | `--root DIR` | repository root, default `.` |
| `scan`, `latest` | `--repo` (repeatable) | shared repositories, order preserved, duplicates kept |
| `update` | `--repo` (single, required) | the one repository to update |
| `update` | `--from`, `--to` (required) | old and new tag |
| `update` | `--root DIR` | default `.` |
| `update` | `--allow-major` | permit a major-version change |
| `update` | `--write` | actually rewrite files; without it nothing is written |

**Repository validation** (all subcommands): each repository must fully match
`^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`. For `scan` and `latest`, zero `--repo`
values ends the program with a message asking for at least one repository; an
invalid value ends it with a message naming the value. Both print to stderr and
exit 1 with nothing on stdout. For `update` the single repository is validated
the same way before any version checks.

### 7.5 Semantic versions

A tag is a semantic version when it fully matches an optional lowercase `v`
followed by three dot-separated non-negative decimal integers (`v1.2.3`,
`1.2.3`). Prerelease or build suffixes (`v1.2.3-rc1`), two-part (`v1.2`),
uppercase `V`, and anything else (`main`, SHAs) are not semantic versions. The
version value is the integer triple; comparison is numeric and lexicographic by
(major, minor, patch).

### 7.6 Files examined

Under `<root>/.github`:

- `workflows/*.yml` and `workflows/*.yaml` (top level of `workflows` only);
- `action.yml` and `action.yaml` anywhere under `actions/`, at any depth
  including directly in `actions/`.

Only regular files that are not symbolic links are included. The set is
de-duplicated and sorted by path components (component-wise string
comparison, so `actions/a/action.yml` sorts before `actions/a-b/action.yml`).
A missing `.github` directory yields no files. Files are read as UTF-8 text.

### 7.7 `scan`

For each file in order, for each line (1-based numbering; universal line
splitting), for each `--repo` in argument order, report every
non-overlapping match, left to right, of this reference shape (case-sensitive):

- the text `uses:` (anywhere in the line), then optional whitespace, then an
  optional single or double quote;
- the repository name exactly as given;
- an optional sub-path: `/` followed by any characters except `@`, whitespace
  and quotes;
- `@`, then the ref: one or more characters excluding whitespace, quotes and
  `#`.

The repository must immediately follow the `uses:` prefix, so `other/o/r@x`
does not count for `o/r`, and a repository name followed by more name
characters (e.g. `o/r2@x` for `o/r`) does not match.

Output: a JSON array (2-space indent, Python `json.dumps(indent=2)` formatting,
ASCII-escaped) of objects with keys in this order:

| Key | Type | Value |
|---|---|---|
| `file` | string | path relative to root, `/`-separated |
| `line` | int | 1-based line number |
| `repo` | string | the `--repo` value that matched |
| `path` | string | sub-path with all leading `/` removed; empty string when absent |
| `ref` | string | text after `@` |
| `semver` | bool | whether `ref` is a semantic version (7.5) |

Exit 0. No repository network access.

### 7.8 `latest`

For each `--repo` in order, list the repository's tags with
`gh api --paginate repos/<owner/repo>/tags --jq .[].name` (stdin closed, 60 s
timeout, failure aborts the program with non-zero exit and no stdout). Split
the output on whitespace; keep semantic-version tags; choose the maximum by
(version triple, then tag string), so between `1.2.3` and `v1.2.3` the `v` form
wins. API order is irrelevant. Output a JSON object (2-space indent) mapping
each repository to its chosen tag, or `null` if it has none; keys in first
occurrence order (a repeated `--repo` yields one key). Exit 0.

### 7.9 `update`

Validation, in order (each failure: message on stderr, nothing on stdout,
exit 2, no files touched):

1. both `--from` and `--to` are semantic versions;
2. the new version is strictly greater than the old one (equal is refused);
3. the major numbers are equal, unless `--allow-major` is given.

Matching: across the full text of each examined file (7.6), find every
occurrence of: `uses:`, optional whitespace (newlines included, since the whole
file is searched), an optional quote, the repository exactly as given, an
optional sub-path (as in 7.7), `@`, then the old tag exactly as given
(literally; `1.2.1` and `v1.2.1` are different texts), immediately followed by
end of file, whitespace, a quote, or `#`. Only the tag is replaced by the new
tag; everything else is preserved. Hence `v1.2.1` never matches `v1.2.10` or
`v1.2.1-rc`, and other repositories with the same tag are untouched. Non-semver
pins are never changed.

Result: a list, in file order, of `{"file": <relative path>, "references":
<replacement count>}` for files with at least one replacement. With `--write`,
each such file is rewritten with the updated text (other files are not
written); without it nothing is written. Output a JSON object (2-space indent):
`{"write": <bool>, "changes": [...]}`, exit 0. No matches gives
`{"write": ..., "changes": []}` and exit 0. The helper never runs git. Files
are decoded with universal newlines and written back with LF line endings;
tests must not depend on CRLF handling.

Python API (used by tests): `scan(root, repos)` returns the list of 7.7;
`update` takes positional `root`, `repo`, `old`, `new` plus keyword flags
`allow_major` and `write` (both default false); it returns the
change list of 7.9 and raises `ValueError` for any validation failure.

## 8. Skill `review-reactions` and helper `reaction_plan.py`

### 8.1 Frontmatter

- `name: review-reactions`
- Suggested description: "Maintain status reactions on the user's own
  review-request messages in the configured team chat channel: one for comments
  from humans other than the PR author, one once every linked PR is approved,
  and one once every linked PR is merged. Plans as a dry run first and adds
  reactions only when the user approves. Use for requests to sync, refresh or
  check the status reactions on review requests."

### 8.2 Usage and boundaries

Usage: `/digits:review-reactions [window in days, default 7] [channel]`.

Purpose: reviewers skim the channel by reaction, so a reaction tells them at a
glance that a request already has comments, is approved, or has merged. The
skill is additive only: it never removes reactions, never posts or edits
messages, and never reacts to messages written by others. The reference
integration is the Slack MCP server. Intermediate files go to
`<session-files>`. The body includes the literal `only after approval` in the
rule governing when reactions are added.

### 8.3 Ordered steps

1. **Configuration and identity at run time.** The body includes the literal
   `Do not hardcode` in the rule about IDs. Each setting comes from the
   invocation, else the bindings, else a single batched ask:
   `review_channel` (shared with `request-review`; asked for when unset) and
   the three `review_reaction_*` lists (defaults in 1.4; first name is added,
   others are aliases). Identities: the chat user ID is the Slack MCP's
   current user (`slack_read_user_profile` called with no user, or the user
   shown in search results); the channel ID is the configured name resolved
   with `slack_search_channels`; the GitHub login comes from
   `gh api user --jq .login`. Missing or unauthenticated chat tooling ends the
   run with the required setup named; credentials are never switched.
2. **Read and normalize.** `slack_read_channel` with `oldest` = now minus the
   window, `limit` 100, and the detailed response format (so reactions are
   included), paging until the whole window is read. Thread replies are
   ignored. Only the user's top-level messages are written to
   `<session-files>/review-messages.json` as an array of objects with `ts`
   (exact original string), `user`, `text` (complete, every link intact) and
   `reactions` (a list of `{"name": ...}` objects or plain strings).
3. **Dry-run plan.** Run the helper (8.4) with that file plus `--user-id`,
   `--author-login`, `--seconds`, and any configured `--feedback`,
   `--approved`, `--merged` lists. The helper reads PRs through `gh` and never
   calls the chat tool. Role rules are in 8.7; they are planned in the order
   feedback, approved, merged so the reactions read chronologically from left
   to right. A post that already carries any configured alias is treated as having that
   role's reaction. Rows with status
   `Error` were not checked and are reported, never guessed.
4. **Approve, then apply.** Present a single plain-text table with columns
   for the post (its date plus PR links that name their repositories), status,
   reactions needed and reactions missing. If nothing is missing, report that
   and stop. Check each emoji name with `slack_search_emojis` first, since
   workspaces define different custom emoji; if a primary name is rejected,
   offer one of its configured aliases. Ask once through a batched ask whether to
   apply. Once approved, invoke `slack_add_reaction` (arguments: channel ID,
   message `ts`, emoji name) once per planned call, following plan order. The `already_reacted` error counts as success; any other error
   halts the run and identifies the post.
5. **Report.** A closing table of reactions added, reactions already present,
   and rows skipped or errored. Point out posts whose PRs were closed without
   merging so the user can decide whether to add a thread note; that note is
   never posted by the skill.

### 8.4 `reaction_plan.py` command line

```text
reaction_plan.py MESSAGES_JSON --user-id ID [--seconds N] [--now EPOCH] [--author-login LOGIN]
                 [--merged LIST] [--approved LIST] [--feedback LIST]
```

| Argument | Type | Default | Meaning |
|---|---|---|---|
| `MESSAGES_JSON` | path | required | messages file |
| `--user-id` | string | required | chat user whose posts are considered; must fully match `^[UW][A-Z0-9]+$`, else usage error (exit 2) explaining a user ID is needed, not a channel or DM ID |
| `--author-login` | string | none | PR author login to exclude from feedback |
| `--seconds` | int | `604800` (7 days) | window length |
| `--now` | float | current time | epoch seconds; a value of `0` is treated as unset |
| `--feedback`, `--approved`, `--merged` | emoji list | 1.4 defaults | override that role's names entirely |

**Emoji list parsing:** split on `,`; trim whitespace from each item; drop
items that are empty after trimming; then strip `:` from both ends of each
remaining item. The result must be non-empty and every name must fully match
`^[a-z0-9_+'-]+$` (lowercase letters, digits, `_`, `+`, `'`, `-`); otherwise a
usage error (exit 2). E.g. ` :eyes: ,ok` → `eyes`, `ok`; `Eyes` and `::` are
rejected. The first name is the one added; the rest are aliases.

**Cutoff** = now − seconds.

**Messages file:** either a JSON array of messages or an object whose
`messages` key holds the array (missing key → no messages). Message fields read:
`user`, `ts` (string or number, parsed as a float), `text` (missing → empty),
`reactions` (missing or null → none; each item a string or an object whose
`name` is used, missing name → empty). A reaction name is cut at the first
`::` (skin-tone suffix), so `thumbsup::skin-tone-2` reads as `thumbsup`.

### 8.5 Candidate selection

- Keep messages whose `user` equals `--user-id` and whose `ts` as a number is
  at least the cutoff (a missing `ts` counts as 0). Other users' messages are
  skipped without parsing their `ts`.
- Extract PR links from `text`: `https://github.com/<owner>/<repo>/pull/<digits>`
  where owner and repo use `[A-Za-z0-9._-]`. Each is normalized to exactly that
  canonical URL (trailing `/files`, `|label`, `>` etc. dropped) and
  de-duplicated in first-seen order. `http://` and other hosts do not count.
- Messages with no PR link are dropped.
- Candidates are ordered by numeric `ts`, newest first (ties keep input order).

### 8.6 PR status

Default fetcher: `gh pr view <url> --json state,reviewDecision,author,reviews`
with a `--jq` projection producing
`{state, reviewDecision, author: <author login>, reviews: [{state, login: <review author login>}]}`;
stdin closed, 30-second timeout, failure on non-zero exit. A subprocess failure
or timeout, or a value/JSON parse error, counts as a read error for that URL.

Python API (used by tests):
`plan(messages, user_id, cutoff, fetch=<default>, author_login=None, reactions=None)`
where `fetch(url)` returns the status object above and `reactions` maps any of
`feedback`, `approved`, `merged` to a tuple of names (primary first) overriding
the defaults for those roles only.

### 8.7 Planning rules

For each candidate, fetch every linked PR (all are attempted even after a
failure).

- **Any read error**: emit an error row whose keys, in order, are `ts`;
  `prs`; `status`, holding `Error`; `reactions`, an empty list; `action`,
  holding the text `Skipped (PR read failed)`; and `errors`, a list of strings
  shaped `<url>: <message>` with the message cut to 120 characters (the
  message wording itself is not part of the contract). The row has
  no `missing` key and produces no calls. Continue with the next candidate.
- **Author**: `--author-login` if given (non-empty), else the `author` of the
  first linked PR's status. This one login is used for all linked PRs.
- **Roles needed**, always in order feedback, approved, merged:
  - feedback: some linked PR has a review whose `state` is `COMMENTED` or
    `CHANGES_REQUESTED`, whose `login` differs from the author, and whose login
    is not automated (1.6). `APPROVED`, `DISMISSED` and `PENDING` reviews never
    count. A review with a null login (deleted account) SHOULD be treated as a
    human other than the author rather than aborting the run.
  - approved: every linked PR's `reviewDecision` is `APPROVED`.
  - merged: every linked PR's `state` is `MERGED`.
- **Present roles**: a role is present when any of its names (primary or
  alias) is among the post's existing reaction names (from anyone).
- **missing**: the primary name of each needed role that is not present, in
  role order.
- **action**: `No reaction needed` if no role is needed; else `Already present`
  if nothing is missing; else `Pending`.
- **status** label, first match wins: all linked states `MERGED` → `Merged`;
  any `CLOSED` → `Closed (check)`; approved needed → `Approved`; feedback needed
  → `Has feedback`; some `MERGED` → `Partly merged`; otherwise
  `Awaiting review`.
- **Row** (keys in order): `ts` (the original value), `prs` (canonical URLs),
  `status`, `reactions` (primary names of all needed roles), `missing`,
  `action`.
- **Calls**: for each missing name, append `{"ts": <ts>, "emoji": <name>}`;
  calls follow row order then role order.

Output: `{"rows": [...], "calls": [...]}` as 2-space-indented JSON
(`json.dumps(indent=2)` formatting), exit 0. The helper never contacts the chat
service and never adds reactions.

## 9. Test module `tests/test_adapted_skills.py`

A `unittest` module that loads the three helpers by file path (no package
imports), uses fixed inputs and in-memory fakes, and touches only temporary
directories. Fixtures:

- **Draft PR fixture** (for `classify`, with `me = "me"` and
  `now = 2025-06-02T12:00:00Z`): PR 7 at `https://github.com/o/r/pull/7`,
  draft, `OPEN`, `MERGEABLE`, head ref `h`, base `main`, head SHA = 40 × `b`,
  empty body, no labels, no review requests, one review by
  `copilot-pull-request-reviewer` (`COMMENTED`, submitted
  `2025-06-02T10:00:00Z`, on the head SHA), no threads, one commit (head SHA,
  authored and committed `2025-06-02T09:00:00Z`, headline `work`, one parent,
  rollup `SUCCESS`). Tests override individual fields.
- **Thread helper**: an unresolved, non-outdated thread whose first comment is by
  a given author on `a.py`, optionally followed by a second comment by another
  login.
- **Workflow fixture** (for `shared_refs`, repository
  `example-org/github-workflows`, temporary root): `.github/workflows/ci.yml`
  with four jobs using, in order, the repository's `x.yml` at `v1.2.1`
  (unquoted), its `y.yml` at `v1.2.10` (single-quoted), its `z.yml` at `main`,
  and `other/repo/.github/workflows/x.yml@v1.2.1`.
- **Reaction fixture**: PR A at `https://github.com/o/r/pull/1` and PR B at
  `https://github.com/o/r/pull/2`; default message ts `200.0` by `U1` linking A
  and B in chat link syntax with an existing `speech_balloon` reaction;
  cutoff `100.0`; statuses built with author `me`.

## 10. Acceptance tests

Tests 1-15 restate every test in `tests/test_adapted_skills.py`; the rest are
required edge cases. Unless stated, draft-sweep tests use the fixture of
section 9 with `me = "me"` and the fixed `now`.

### Draft sweep classification

1. **Ready by default.** Given the unmodified draft fixture, when classified,
   then the bucket is `ready-candidate`.
2. **Precedence.** Given a `Blocked` label and `CONFLICTING`, then
   `skip-blocked-label`. Given body `Depends on: o/r#3` and `CONFLICTING`, then
   `check-dependency`. Given body `Depends on: none`, then `ready-candidate`.
   Given only `CONFLICTING`, then `rebase`. Given a requested reviewer of type
   `Bot` with login `copilot-pull-request-reviewer`, then `review-in-flight`.
3. **My last reply clears a thread.** Given one thread opened by
   `copilot-pull-request-reviewer` whose last comment is by `me`, then
   `ready-candidate`. Given one thread opened by `alice` with no reply, then the
   bucket is `to-assess` and `humanThreadsAwaitingMe` is 1.
4. **Authored date drives staleness.** Given the head commit's
   `committedDate` changed to `2025-06-02T11:00:00Z` (authored date unchanged),
   then `ready-candidate`. Given both dates `2025-06-02T11:00:00Z`, then
   `check-stale-review`. Given `committedDate` `2025-06-02T11:55:00Z`, then
   `check-active-elsewhere`.
5. **CI and missing review.** Given rollup `FAILURE`, then `fix-ci`. Given no
   reviews, then `no-automated-review`.

### Shared references

6. **Scan.** Given the workflow fixture, when scanning for the fixture
   repository, then exactly three references come back, in this order: the
   `x.yml` workflow pinned at `v1.2.1` (semver true), the `y.yml` workflow at
   `v1.2.10` (semver true), and the `z.yml` workflow at `main` (semver false);
   each `path` value is `.github/workflows/<name>`. The `other/repo` line is
   not reported.
7. **Dry run and exact tag.** When updating `v1.2.1` → `v1.3.0` without write,
   then the result is `[{"file": ".github/workflows/ci.yml", "references": 1}]`
   and the file is byte-identical. When repeated with write, then the file
   contains `x.yml@v1.3.0`, still contains `y.yml@v1.2.10`, and still contains
   `other/repo/.github/workflows/x.yml@v1.2.1`.
8. **Unsafe versions refused.** With write requested, each of `v1.2.1`→`v2.0.0`
   (cross-major), `v1.2.1`→`v1.2.0` (older), and `main`→`v1.3.0` (non-semver)
   raises a validation error. Then `v1.2.1`→`v2.0.0` with `allow_major` returns a
   non-empty change list.

### Reaction plan

9. **All linked PRs must qualify.** Given A merged+approved and B open+approved,
   then the row's `reactions` is `["white_check_mark"]`. Given both merged and
   approved, then the call emojis are `["white_check_mark",
   "twisted_rightwards_arrows"]`.
10. **Only outside humans count; aliases count as present.** Given both PRs with
    reviews `copilot-pull-request-reviewer` COMMENTED, `me` COMMENTED and
    `x[bot]` CHANGES_REQUESTED, then `reactions` is `[]`. Given A with `alice`
    CHANGES_REQUESTED and B with none, then the action is `Already present`
    (existing `speech_balloon`) and there are no calls.
11. **Configured names and aliases.** Given one message at ts `200.0` by `U1`
    linking A with existing reaction string `merge`, A merged, approved, with
    `alice` COMMENTED, and overrides feedback=`eyes`, approved=`ok`, then
    `reactions` is `["eyes", "ok", "twisted_rightwards_arrows"]` and call emojis
    are `["eyes", "ok"]`.
12. **Filtering and errors.** Given messages (`200.0`, `U2`, A), (`50.0`, `U1`,
    A), (`300.0`, `U1`, B) and a fetcher that always fails with a value error,
    then rows are exactly `[("300.0", "Error")]` (ts, status) and calls are
    empty.

### Skill files

13. **Frontmatter and size.** For each of the seven skills in this file
    (`review-reactions`, `rebase-pr`, `investigate`, `draft-pr-sweep`,
    `challenge-pass`, `update-shared-workflows`, `assess-and-address`), the
    SKILL.md starts with
    exactly `---`, `name: <dir>`, a non-empty one-line `description:`,
    `user-invocable: true`, `---`, and has at most 190 lines.
14. **Every skill's name matches its directory.** For every
    `plugin/skills/*/SKILL.md` (all fourteen), the frontmatter block exists at
    the start of the file, contains the line `name: <directory>`, and contains a
    `description:` line whose value starts with a non-space character.
15. **Write gates stay documented.** Each phrase in the table of 1.3 occurs
    verbatim in the named SKILL.md.

### Additional edge cases (MUST)

16. Given body `Depends on nothing.` or `depends on N/A`, then no hint. Given
    `Depends on: nonexistent`, then hint `Depends on: nonexistent`. Given a body
    with `depends on: #12`, `stacked on #3`, `blocked by z`, `must not merge`,
    `before merge` on five lines, then exactly the first four are returned.
17. Given labels `On Hold` or `DO-NOT-MERGE`, then `skip-blocked-label`; given
    label `blocked-by-infra`, then not that bucket.
18. Given rollup `ERROR` → `fix-ci`; `PENDING` or `EXPECTED` → `ci-pending`;
    null rollup with nothing else outstanding → `ready-candidate`.
19. Given a commit authored after the review but with two parents, then it is
    not in `commitsAfterReview` and the bucket is `ready-candidate`.
20. Given a later review by human `alice` after the automated one, then
    `automatedReviewAt` is still the automated review's time; given the last
    automated review on an older commit, then `automatedReviewOnHead` is false.
21. Given a requested `Team` with slug `core` and a requested user `bob`, then
    `humanReviewersRequested` is `["core", "bob"]` in request order and the
    bucket is not `review-in-flight`.
22. Given a thread first authored by `dependabot[bot]` with no reply, then the
    bucket is `to-assess`, `threadsAwaitingMe` is 1 and
    `humanThreadsAwaitingMe` is 0; resolved or outdated threads never appear in
    `openThreads`; a 300-character first comment is truncated to 160.
23. Given an empty commit list, then `minutesSinceHead` is 0 and the bucket is
    `check-active-elsewhere` (when rules 1-4 do not apply).
24. CLI: given argument `o/r#x` (with a stubbed `gh` that answers the login
    call), then exit 1 with nothing on stdout. Given two valid targets where the
    stubbed `gh` fails for the second, then two lines are printed, the second
    with `bucket: "error"`, `repo`, `url`, `error`, and exit is 1. Given a first
    GraphQL answer with `mergeable: UNKNOWN`, then exactly one more fetch is
    made. Given no targets and search results `a/b#10`, `a/b#9`, then `#10` is
    processed first. Output lines have sorted keys.
25. Shared refs: `.github/actions/build/action.yaml` and `.github/actions/action.yml`
    are scanned; `.github/workflows/sub/x.yml` and symlinked workflow files are
    not; a `uses:` line with `@v1.2.1 # pin` is updated, `@v1.2.1,` is not.
26. Shared refs CLI: `scan` without `--repo` → exit 1; `--repo bad` → exit 1;
    `update` with `--from v1.2.1 --to v1.2.1` → exit 2, stdout empty;
    `update` with `--from 1.2.1` does not change `@v1.2.1` text; success prints
    `{"write": false, "changes": [...]}`.
27. Shared refs `latest` (stubbed `gh` returning `v1.10.0 v1.9.0 main 1.10.0
    v2.0.0-rc1`) → `v1.10.0`; tags with no semantic version → `null`.
28. Reaction CLI: `--user-id C123` → exit 2; `--feedback Eyes` → exit 2;
    `--feedback " :eyes: ,look"` → feedback primary `eyes` with alias `look`; a
    `{"messages": [...]}` wrapper is accepted.
29. Reactions: a post with existing `thumbsup::skin-tone-2`-style names is
    compared after cutting at `::`; a post linking the same PR twice (and once
    with `/files`) lists one URL; posts are ordered newest first; a post whose
    PRs are open with no reviews gets action `No reaction needed` and status
    `Awaiting review`; one merged and one closed PR → status `Closed (check)`;
    one merged and one open (neither approved) → `Partly merged`; `--author-login` overrides the
    first PR's author for the feedback exclusion.
30. Reactions: with no `--now`, the cutoff uses the current clock; with
    `--seconds 0`, only messages at or after now count.
