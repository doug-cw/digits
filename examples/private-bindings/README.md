# Private context bindings

Bindings are small Markdown files on your own machine that hold the non-secret facts
the shared library deliberately leaves out: account family, dbt profile, compute, issue
project, mandatory fields, preferred shell and repository inventory. The bootstrap and
the topic pages refer to them by file name; when one is missing, only the action that
needs it pauses.

## Install

```sh
mkdir -p ~/.config/digits/context
chmod 700 ~/.config/digits/context
cp examples/private-bindings/tool-and-repo-bindings.example.md ~/.config/digits/context/tool-and-repo-bindings.md
cp examples/private-bindings/data-warehouse-bindings.example.md ~/.config/digits/context/data-warehouse-bindings.md
chmod 600 ~/.config/digits/context/*.md
```

Then replace every fictional `example-org` value with facts you have verified. Delete
sections you do not need rather than leaving realistic-looking placeholders behind.

## Rules

- Never commit filled-in bindings anywhere, not even to a private fork. The context
  installer does not read, copy or export them.
- No credentials of any kind: no passwords, tokens, private keys, client secrets or
  session cookies. Use SSO or a secret store; a binding may name the store.
- Note where each fact came from (a file, a command or a document) and the date you
  checked it; agents then read old or unchecked rows as leads rather than truth.
- A binding names the thing to use, nothing more: it is never permission to deploy,
  query production, post anything, or move to another account.
- Keep in-flight task details such as owners, approvals, PR heads and receipts in the
  session's own artifacts instead.

## Files

| Binding file | Referenced by |
|---|---|
| `tool-and-repo-bindings.md` | The bootstrap and the writing, workspace and terminal, repository map, issue tracker and GitHub delivery pages |
| `data-warehouse-bindings.md` | The bootstrap and the data warehouse page |
| `token-projects.json` | The `token-usage` skill, to group cost by project (copy `token-projects.example.json`) |
