# GitHub delivery, review, and release

Use when creating branches, preparing or reviewing pull requests, cutting releases, or diagnosing why the wrong code was picked up.
Scope: a personal working method; always check the target repository's own review and release rules first.
Sources: maintainer agreements, Conventional Commits 1.0.0 (`https://www.conventionalcommits.org/en/v1.0.0/`), and the target repository's workflows.
Reviewed: 2026-11-16.
Recheck: the PR's actual base and head, the workflows on the current default branch, and the message the merge will really use.

## Establish the source identity

1. Verify the owning organization and repository, the clone's status and index, and
   whatever work is already present in it.
2. For new work based on the default branch, fetch the remote and confirm which branch
   is actually the default (it may be `main`, `trunk`, `master`, or `develop`), then
   branch from that remote ref. Never start from a stale local `main` or from whatever
   branch the current task happens to be on. An approved stacked or alternative base
   wins over this default.
3. Keep unrelated staged or unstaged edits and local-only commits intact. Before a
   rebase, reconcile the published head with upstream and make sure the original refs
   can still be recovered.
4. Obey the repository's instructions and CI configuration. Reuse its generators,
   package managers, formatters, and checks instead of building parallel tooling.

## Before publication or recommending a merge

Decision procedure: prove behavior locally, size the diff, confirm the release path and
message, map consumers, recheck prior review, then read CI at job level for the exact head.

- **Prove the behavior.** Use focused regression tests plus local equivalents of the
  relevant CI: the configured pre-commit hooks, pinned tool versions, and any parse or
  config checks particular to the target. Read the current files; a command you remember
  from another repository is not universal.
- **Run the publication preflight before the first push to a public or outside
  remote.** Where the repository ships it (Digits does), run
  `python3 scripts/check_publication.py --range <base>..HEAD` for the commits and
  `--text <file>` (or `-`) for PR or issue text; it checks noreply identities and
  trailers, private terms, home paths, emails and secrets, and says so when no
  private-terms file is configured. A clean run does not replace reading the commits
  and the text yourself.
- **Measure size** as additions plus deletions against the real base. Some repositories
  refuse automated AI review above a threshold (for instance a raw changed-line count
  that includes tests and docs). Record any such limit per repository in the private
  `tool-and-repo-bindings.md` file and confirm it against the live workflow. Oversized
  work becomes a coherent stack of dependent PRs that link to their neighbours and merge
  from the bottom up.
- **Re-measure after any rebase, retarget, or fix**, and recheck CI and review for that
  precise head. Inherited diffs, old approvals, skipped jobs, and trigger comments are
  not fresh validation. A review job skipped because the PR was a draft is neither a
  review nor a human approval.
- **Know how versions are bumped.** A `fix:` prefix or a version-file edit may publish
  nothing. If the repository needs a marker such as `#patch`, it has to land in the
  final squash or merge commit, not merely in the PR description.
- **Conventional Commits** for both commit messages and PR titles:
  `type(scope): imperative summary`, using `feat`, `fix`, `docs`, `refactor`, `test`,
  `perf`, `build`, `ci`, or `chore`; flag breaking changes with `!` or a
  `BREAKING CHANGE:` footer. A squash merge usually reuses the PR title (or the only
  commit's message), so each of them has to follow the format. Any ticket key or bump
  marker the repository requires stays in place, as in
  `fix(sync): resume interrupted uploads [PROJ-42] #patch`. The type alone never
  guarantees a release, and published history is not rewritten just to rename it.
- **Tie releases to commits.** Confirm the SHA behind every tag or release and the pins
  held downstream (images, workflows, libraries). Source merge, release selection,
  consumer adoption, rollout, and recovery are five separate outcomes.
- **Map consumers of shared artifacts.** For shared libraries, workflows, and images,
  list every consumer and how it selects a version (exact pin, range, or a moving tag
  such as `latest`) before merging or releasing. For moving-tag consumers, the merge or
  release *is* a production rollout: run their prerequisites first (database migrations,
  for example) or pin them. "Rollout complete" requires that whole list, not only the
  deployment the user mentioned.
- **Revisit earlier review.** Re-read substantive comments on previous PRs from the same
  ticket or workstream, especially any that call for this follow-up, and say how each is
  addressed. A rule summarised into context does not replace reading the original review.
- **Reply in threads** with the GraphQL mutation `addPullRequestReviewThreadReply` or the
  REST endpoint `POST /repos/<owner>/<repo>/pulls/<pr>/comments/<id>/replies`.
- **Consequential changes** get the risk-based challenge described in
  [Challenge consequential changes before publication](engineering-decisions.md#challenge-consequential-changes-before-publication).
- **Read CI at job and step level**, including steps allowed to fail and skipped matrix
  entries; a green summary can conceal a requirement that never ran. Local success only
  counts as CI evidence once you have checked that runner, dependency versions, and
  service setup match CI. When updating pinned actions, verify each SHA really is the
  version it claims. Ship a hook together with its CI counterpart when both protect the
  same invariant. None of this justifies migrating runners or tooling beyond the request.
- **Trace red gates before dismissing them.** Before labelling a failure unrelated or the
  task done, connect it to the original goal and to recent upstream changes. A CI default
  still pointing at a deliberately retired target may need a small workflow fix, not a
  revived target and not a blanket exemption. Propose the smallest change that keeps the
  intent, the remaining validation, and supported deployments. Truly separate work needs
  its own scoped approval, and a deliberately skipped deployment is untested, not a live
  success.

## Review boundaries

- Notes, reviews, and replies aimed at people stay local unless posting has been
  explicitly allowed. Threads raised by bots may be answered and resolved once handled,
  but that does not extend to a human who has replied inside such a thread.
- Unless asked, never merge, mark a PR ready for review, close it, approve a deployment
  gate, or use a manual trigger to sidestep an instruction not to post.
- Use the existing `request-review` skill only when someone really wants reviewers
  requested or pinged. Keep PR descriptions short and current (see
  [writing guidance](../references/writing.md)); raise stylistic nits only on request.
- Per-PR ephemeral deployments follow
  [Keep ephemeral PR validation representative](infra-lifecycle.md#keep-ephemeral-pr-validation-representative);
  approving every variant merely to clear pending gates is wrong.

## Automated review discovery

- The AI reviewer in use varies by repository. Read the review workflow on the current
  default branch to learn its triggers (a comment posted by hand, a PR being opened, a
  draft becoming ready, fresh commits arriving, or some other bot completing), how drafts are treated, which variables enable it, who
  can trigger it manually, and whether a size ceiling applies.
- Reviewer inventories in private bindings are dated hints to aid discovery; they do not
  show that a review ran on the current head. A neighbouring repository having a reviewer
  says nothing about this one.

## Organization release procedures

When a repository demands its own release sequence (unusual tag prefixes, per-tenant or
per-environment dispatch workflows, an approved tag passed as input, and so on), document
it in that repository or in a private binding, and then:

1. Get approval that names the exact commit, target, and environment.
2. Work out the next version from tags and releases already published and from earlier
   successful deployments, not from a manifest field or generic semver habit.
3. Confirm the tag's SHA, the actual deployment result, and the live outputs.

A naming pattern confers no authority to deploy and no permission for other targets.
Consult the [data warehouse page](../domains/data-warehouse.md) before picking a data
target; the [repository map](../references/repository-map.md) lists source links.

Example pitfall: a tag `acme-tenant-globex-v1.4.2` exists, so someone assumes they may
dispatch `v1.4.3` to every tenant. Without approval naming commit, target, and
environment, that is out of scope.
