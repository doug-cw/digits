---
name: assess-and-address
description: Work through every open pull request review thread and top-level review comment, judge whether each one is right, commit focused fixes for the valid ones, reply to and resolve threads opened by automated reviewers, and draft (never post) answers for human reviewers. Use when asked to address or work through PR feedback or review comments, including Copilot and other bot findings.
user-invocable: true
---

# Assess and address review feedback

Usage: `/digits:assess-and-address [owner/repo#N or PR URL] [push]`

## Write rules

- **Automated sources** (Copilot and other AI review bots, logins ending in
  `[bot]`, review comments posted by github-actions): once an item is fixed,
  rebutted, or deferred with a recorded reason, you may reply in that thread
  and resolve it without asking.
- **Human reviewers**: never reply, resolve, react or re-request review for a
  human reviewer unless the user approved the exact text and the exact action.
  Prepare drafts instead.
- **Pushing** happens only on request: the invocation contains `push`, or the
  user approves the push in step 7. Force-pushing is out of scope (that belongs
  to `/digits:rebase-pr`), and so are merging, marking ready, and posting to
  chat.

## Steps

### 1. Target and checkout

Use the PR from the argument, otherwise the PR for the current branch. Always
pass an explicit `--repo` so the repository is confirmed, and record the head
SHA. Work either in a clean checkout of the PR branch that this chat owns, or
in a fresh worktree. Never switch, stash or reset a checkout that holds someone
else's changes, and never take over a branch another chat is working on.

### 2. Fetch feedback with GraphQL

Request review threads (node ID, `isResolved`, `isOutdated`, path, line, and
every comment with its author) and every review with a non-empty body. Follow
`hasNextPage` to the end on every connection; default page sizes (such as 50
threads or 5 comments per thread) are not enough. Top-level review bodies hold
design feedback without a line anchor, so include them.

An item is actionable when its thread is unresolved, not outdated, and its
newest comment is not from the user. Still compare outdated threads with the
current code, because the point may still apply.

### 3. Assess

For each item record the source (human or automated) and a category: bug or
edge case, logic, missing test, security or performance, convention, docs,
style, design, question.

Judge against the code, not against the comment's description of it:

- read at least 50 surrounding lines and the related files in the PR;
- look for established patterns, repository instructions and lint config;
- confirm every method, field, flag or behavior the comment mentions exists.

Automated reviewers often suggest patterns that are foreign to the repository
or misread intent, and a "minor" note can hide a serious problem, so check what
the code is actually meant to do.

Outcome: **valid**, **invalid** or **needs decision**. Human comments about
design or scope (for example "use the shared module" or "move this code") are
the user's call: ask first. Flag anything that would need a large
architectural change.

### 4. Fix

- One commit per finding, unless several findings form one logical change.
- Stage named paths only. Follow the repository's commit message style, its
  signing setup, and any release or version-bump rule.
- For a regression test, prove it fails without the fix: temporarily restore
  the committed source to its pre-fix state, run the test, then put the fix
  back. Never discard uncommitted test or user work.
- Run the relevant lint and tests before anything is pushed.

### 5. Automated threads

Answer with the GraphQL mutation `addPullRequestReviewThreadReply` and resolve
with `resolveReviewThread`:

- **Fixed** - reply citing the commit, then resolve.
- **Invalid** - reply with a short, concrete reason (for example the
  repository pattern it conflicts with), then resolve.
- **Deferred** - reply with the reason and the follow-up ticket if there is
  one, then resolve.

If a human has commented in the thread, do not reply there.

### 6. Human items

Post nothing. For each item prepare: location and reviewer, the point raised,
your assessment with evidence, the commit that addresses it (if any), and a
proposed reply. Present them all in one batched ask (the Digits bootstrap's Communication rule: one `ask_user` or `AskUserQuestion` call, or one numbered list when the decisions do not fit) with per-item choices
for the reply (post / edit / skip) and the thread (resolve / leave open). Post
only the exact approved text.

### 7. Push and bounded re-review

- Right before pushing, re-read the PR head and the requested reviewers. If
  another session pushed, or the review state changed since step 1, stop and
  report it.
- If the invocation did not include `push`, ask once, showing the commits and
  the check results. Push without force.
- Re-review applies only when you pushed and an automated reviewer has already
  reviewed this PR. Do not use sleep loops: either block on the review workflow
  run with `gh run watch <run-id> --repo <owner/repo> --exit-status`, or check
  again on the next turn. Repeat steps 2-6 for new findings, capped at
  three rounds per invocation.
- Stop earlier when the latest automated review adds no comments, when only
  declined or human items remain, or when no review appears within a few
  minutes. Never assume a repository re-reviews on push; confirm it per PR.
- Finally check CI on the exact new head; skipped jobs do not count as passing.

### 8. Report

Short sections:

- addressed findings, each with its commit;
- automated threads answered and resolved;
- human items awaiting a decision, with proposed replies;
- how many re-review rounds ran and why they stopped;
- CI status for the exact head commit;
- any lesson worth turning into a repository rule or test (offer it; never add
  it unasked).

## Non-goals

No writes to human threads without approval, no force-push, no merge, no ready
toggle, no chat posts, and no durable rule changes unasked.
