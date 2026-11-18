# MCP discovery, schema, execution, and access

Use when tools seem to be missing, discovery returns nothing, someone suggests repairing an integration or its authentication, or a task drives a browser.
Scope: diagnosis using the tools already available; this page is never a route to alternative credentials.
Sources: the loaded tool contracts, results of real harmless calls, and the integration's official documentation.
Reviewed: 2026-11-16.
Recheck: the exact loaded or deferred schema, the response to the call, and whether the server is connected right now.

## Decision procedure

1. A deferred tool whose schema has not been loaded must be found through the provided discovery mechanism before it is used. Never invent function names or arguments.
2. A loaded schema that exactly matches may be used. A later search that comes back empty neither removes it nor proves the tool is unavailable.
3. When you need to diagnose, make a harmless read through that schema, within the scope the user already has. Never send a message or perform a write as a connectivity check.
4. On a genuine authentication, permission, or connection error, stop and report the integration, the operation or capability that was refused, and the setup that is needed. No second attempt may switch to a different account, credential, role, or host, nor go through raw HTTP, a headless helper or browser automation. Before accepting the error as genuine, call the currently documented operation, confirm the error concerns the intended object and identity, and where possible read the identity's effective capability (for example GitHub's `viewerPermission`). When a badly formed path yields a 404, or a stale or mismatched call yields FORBIDDEN, the mistake lies in how the tool was called, not in what access exists; correcting the call under the same identity is not evasion.
5. If there is neither a schema nor a successful harmless read, state which evidence is missing. Do not upgrade a guess such as "the registry is stale" into a confirmed root cause.

Further rules:

- For servers exposing many functions, search by name or description instead of listing the full catalog, reuse schemas already in context, and stop retrying an MCP server that is disconnected.
- Prefer `gh` for GitHub reads and writes, under its usual approval rules.
- Some vendor MCP servers (Datadog is one example) come with dedicated setup or configuration skills; set them up via those skills and operate them via their own tools. A broken integration is not an invitation to improvise direct API requests.
- Signing in a headless helper needs its own approval as a distinct workflow; it is not a plan B when interactive sign-in did not work.

## Browser automation

- Before the first action, confirm which browser and profile the automation is attached to and which account is signed in. If it is not the one the task needs, stop and ask; never sign in or switch profiles to get past it.
- On admin and settings pages, submitting a form, pressing Enter in a field, subscribing, adding to a list and opening an object for editing are writes that need approval. Read the values back before saving.

## Two canonical examples

- Chat tool (Slack, for example): discovery lists nothing, but the channel-list schema is loaded. Run the permitted channel-list read. If it succeeds, there is no evidence that re-authentication or a configuration change is required. Read access, moreover, says nothing about permission to post.
- Issue tracker (Jira, for example): a read through a known schema is explicitly refused for lack of a site grant. Stop and name the grant that is required. Remembering an earlier discovery mistake does not justify switching to other credentials or another site.

Keep five facts apart: the server is connected, a schema is visible, an access grant exists, operational permission exists, and a receipt for a successful write is held. Each is separate and none implies the next.

If the outcome of a send is unclear, check the approved destination for that exact message before even considering a second send. Sending always goes through the existing guarded skill; do not rebuild its approval or receipt handling.
