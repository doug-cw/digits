---
name: draft-pr-sweep
description: Read-only triage of the user's open draft pull requests that sorts each by its next move (a blocking label, an unmet dependency, merge conflicts, CI state, a review already in flight, feedback to assess, or readiness for review), offers follow-up actions in one approval form, and hands approved work to the rebase-pr, assess-and-address and request-review skills. Use when asked to sweep or triage my draft PRs or report where they stand.
user-invocable: true
---

# Draft PR sweep

Usage: `/digits:draft-pr-sweep [owner/repo#N ...]`

The sweep itself is read-only: it does not push, rebase, comment, post,
request reviews, change draft state, or assign tickets. Nothing happens until
the user approves it in step 3, and each approved action is carried out by the
skill that owns it.

## Steps

### 1. Collect status

Run the helper and save its output in the session workspace (never `/tmp`,
never inside a repository):

```bash
python3 "<skill-dir>/pr_status.py" [owner/repo#N ...] > "<session-files>/draft-pr-status.jsonl"
```

With no targets it covers every open draft authored by the `gh`-authenticated
user. Each line holds the state, CI rollup, when the automated review happened,
open threads split into human and automated, dependency hints, and a proposed
`bucket`. A line with `bucket: error` means that PR could not be read: report
it and do not guess.

**Ranking.** If the bindings define `standup_priority_query`, run it read-only
with whichever issue-tracker tools are available. Match PRs to tickets by a
ticket key in the PR title, head branch or body. Order the form and the report
by rank, put PRs without a ticket last, and mention ranked tickets that have no
open PR. Without a configured query, or if the tracker is unreachable, say the
order is unranked. Never guess boards or projects.

### 2. Confirm buckets

The helper applies these in order; the first match wins.

| Bucket | Situation | Offer |
|---|---|---|
| `skip-blocked-label` | blocking or do-not-merge style label | nothing; say what would unblock it |
| `check-dependency` | body mentions a dependency, stack parent or merge hold | check the dependency's live state; if satisfied, re-bucket and offer to remove the stale note |
| `rebase` | GitHub reports conflicts | `/digits:rebase-pr` |
| `review-in-flight` | an automated reviewer is currently requested | nothing now; look again at the end |
| `check-active-elsewhere` | head changed less than 15 minutes ago | find the owning chat; hands off |
| `fix-ci` / `ci-pending` | head checks failing / still running | read the failing job and offer a fix, or wait |
| `to-assess` | open threads waiting on the user | `/digits:assess-and-address` |
| `no-automated-review` | never reviewed automatically | request an automated review the repository's way |
| `check-stale-review` | commits newer than the last automated review | if they only implement that review's findings, treat as ready; else offer a new review |
| `ready-candidate` | nothing above matched | `/digits:request-review` (mark ready, chat post, optional ticket transition) |

Re-derive hints instead of trusting them: read the live status of the
dependency PR or release, and inspect `commitsAfterReview`. Threads where the
user spoke last need nothing. A cherry-pick that gets a fresh review may be
flagged for code already on the default branch; that fix belongs there first.
A merged stack parent leaves a stale dependency note behind.

Before offering `ready-candidate`, check: CI is green on the exact head
(skipped jobs do not count); the title carries any mandatory release marker;
and, if `automated_review_size_limit` is configured, additions plus deletions
against the actual base are within it. A failed check moves the PR to the
matching bucket.

### 3. One approval form

Make exactly one batched ask (the Digits bootstrap's Communication rule: one `ask_user` or `AskUserQuestion` call, or one numbered list when the decisions do not fit) with one question per PR (or per group of PRs
sharing a ticket). The field description shows the evidence: bucket, CI
status, what the automated review concluded, open human threads, caveats. The
choices are the offered action(s) plus "Skip", with a recommended default.
Suggest reviewers already requested on the PR or the team that owns the
repository; `request-review` maps them to chat users or groups at run time.

### 4. Execute approved actions

Before every action, re-read the PR head and its review requests. If another
session has pushed, requested review, or marked it ready since the sweep, skip
it and say why.

- **Rebase** - hand to `/digits:rebase-pr`, one PR at a time.
- **Assess** - hand to `/digits:assess-and-address`, one PR at a time. Approval
  here covers that skill's push only if push was an explicit choice in the
  form.
- **Automated review** - `gh pr edit <N> --repo <owner/repo> --add-reviewer @copilot`,
  only in repositories that use that reviewer; otherwise use whatever trigger
  the repository documents for its automated reviewer.
- **Ready** - hand to `/digits:request-review` with its mark-ready option; PRs
  sharing a ticket go in one message.

At the end, look again at `review-in-flight` PRs and freshly requested reviews
(they usually finish within minutes). Do not use sleep loops.

### 5. Report

One table with columns: PR (link text shows repository and number), bucket,
action taken or reason skipped, and what would unblock each skipped PR. Below
it, list what only the user can unblock: pending apply gates, decisions on
human reviews, dependencies that must be released. Propose ticket status
follow-ups without changing any ticket.

## Gotchas

- The helper uses GraphQL because the CLI's `reviewRequests` JSON field omits
  the Copilot reviewer.
- `mergeable` is `UNKNOWN` until GitHub computes it, so the helper retries once.
- A rebase rewrites `committedDate`, so staleness is judged by `authoredDate`.
- `check-active-elsewhere` cannot tell who pushed; a push the user made earlier
  in the same sweep also lands there.
- Cross-repository inventories query GitHub, not local clones, whose default
  branch may be stale or not called `main`.
- Where a Terraform repository applies infrastructure from PR branches, a PR
  can show plan differences caused by another open PR's applied state. Point
  this out and never approve that gate.
