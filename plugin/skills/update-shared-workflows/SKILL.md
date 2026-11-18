---
name: update-shared-workflows
description: Check and bump pinned versions of an organization's shared GitHub workflow and action repositories. Finds each repository's newest tag (repositories come from arguments or bindings), inventories pinned references in one repository, reads release notes for breaking changes, then applies approved same-major updates through a preview-first helper. Use when asked to check, bump or update shared workflow or action versions.
user-invocable: true
---

# Update shared workflows

Usage: `/digits:update-shared-workflows [repository path] [owner/repo ...]`

## Scope

- One confirmed checkout per run (default: the current directory). Files change
  only after the plan is approved.
- This skill never commits or pushes. It leaves other environment directories
  and other chats' checkouts alone.
- Shared repositories come from, in order: `owner/repo` arguments; the
  `shared_workflow_repos` binding in
  `~/.config/digits/context/tool-and-repo-bindings.md` (comma-separated
  `owner/repo` list); otherwise one batched ask (the Digits bootstrap's Communication rule: one `ask_user` or `AskUserQuestion` call, or one numbered list when the decisions do not fit). The helper has no
  built-in list, so pass each repository with its own `--repo`. Confirm each
  one exists with `gh repo view <owner/repo>`; never guess names.

The helper is invoked as `python3 "<skill-dir>/shared_refs.py" ...`.

## Steps

### 1. Target

Check identity and state:

```bash
git -C <path> remote -v
git -C <path> branch --show-current
git -C <path> status --porcelain
```

Unrelated dirty files stop the run (no stashing). If a PR is wanted, branch
fresh from the verified `origin` default branch.

### 2. Inventory

```bash
python3 "<skill-dir>/shared_refs.py" latest --repo <o/r> [--repo ...]
python3 "<skill-dir>/shared_refs.py" scan --root <path> --repo <o/r> [--repo ...]
```

Show one table: repository, pinned version(s) each with a count, newest tag,
and a status of `current`, `update`, `mixed`, or non-semver pin (SHA or
branch). Non-semver pins are never modified, but call them out.

### 3. Release notes

For every repository that will change, read all releases from the oldest
pinned version up to the target:

```bash
gh release list --repo <o/r>
gh release view <tag> --repo <o/r>
```

If releases are missing, use the compare view between the two tags.
Breaking-change checklist:

- workflows, actions, inputs, outputs or secrets removed or renamed;
- inputs or permissions that are newly required;
- runner or tool changes;
- major version bumps.

If the notes are thin, compare the changed workflow's declared inputs between
the two tags. Record the risk, the local changes needed, and links.

### 4. Approval

One batched ask listing, per repository: current version(s), target version,
affected files, risk, and local changes. Same-major is the default scope. A
cross-major update needs its own explicit confirmation for that repository,
and its required local changes ship in the same change.

### 5. Apply

For each approved (repository, old version) pair, preview first and then
write:

```bash
python3 "<skill-dir>/shared_refs.py" update --root <path> --repo <o/r> --from <old> --to <new>
python3 "<skill-dir>/shared_refs.py" update --root <path> --repo <o/r> --from <old> --to <new> --write
```

Add `--allow-major` only for an approved cross-major pair. Then run `scan`
again and check that the total reference count is unchanged, no approved old
version remains, and every ref is well formed. Run `actionlint` if it is
installed, and review `git diff`.

### 6. Report

- A table: repository, previous version, new version, references changed,
  files changed.
- Risks found in the release notes and the local edits made.
- Anything skipped, with reasons.
- A proposed commit message, for example `ci: update shared workflows`.

Publishing follows the usual delivery rules: a draft PR when requested, any
release markers the repository requires, and CI verified on the exact head
commit.

## Helper reference

- `scan` prints a JSON array of `{file, line, repo, path, ref, semver}` for
  `.github/workflows/*.y(a)ml` and `.github/actions/**/action.y(a)ml`.
- `latest` prints `{repo: newest semantic tag or null}` using
  `gh api --paginate repos/<o/r>/tags`.
- `update` prints `{"write": bool, "changes": [{file, references}]}`. It
  refuses non-semantic tags, downgrades and equal versions, and major changes
  without `--allow-major` (exit 2). Without `--write` nothing is written. It
  only replaces the exact old tag, so `v1.2.1` never touches `v1.2.10`.
