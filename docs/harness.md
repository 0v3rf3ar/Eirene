# Modes and permissions

[Documentation](README.md) / Modes and permissions

Eirene works on the real files in your workspace. A mode controls which actions
need approval. A permission setting controls whether those actions are restricted
to the workspace or can access the host. These are separate choices.

## Choose a mode

```text
/agents manual
/agents auto
/agents plan
```

Use `/agents` without arguments for a picker, or Shift+Tab to cycle modes. The
interactive default is Manual. Your mode selection is saved; a headless `-p` run
defaults to Auto unless you pass `--mode`.

| Mode | Reads | File changes | Arbitrary commands |
| --- | --- | --- | --- |
| Manual | Harmless workspace reads allowed | Approval required | Approval required; recognized harmless read commands can proceed |
| Auto | Allowed in the workspace | Allowed in the workspace | Allowed within available isolation |
| Plan | Workspace reads allowed | Blocked | Blocked |

External-path access may require a prompt even for a read. Plan mode can inspect
files and use supported fixed read/search operations; it cannot launch imported
hooks or MCP servers, edit project files, or use unrestricted execution. Updating
session plan metadata is permitted because it does not change project files.

## Inspect the boundary

```text
/sandbox
```

The status panel shows your workspace, effective permissions, platform runtime,
external-path access, and network policy. It is a status command and does not
accept container, image, or backend options.

The [platform guide](platforms.md) explains Linux Bubblewrap, macOS Seatbelt, and
Windows command approval. Codex and Claude Code connections own their native
execution environments; Eirene forwards their approvals and requests their
sandbox controls.

## Sandboxed access

New Eirene processes start with `sandboxed` permissions. Workspace edits are
allowed according to the mode. External files, network requests, and host actions
can require approval. Linux and macOS command execution requires a working
platform isolation backend; Eirene does not silently run without it.

An execution approval can grant **full host access for the current response**.
The approval prompt states that scope. Restrictions return when the response
finishes, fails, or is stopped. Managed commands and services started under that
temporary grant are stopped when it ends. Ordinary question answers do not grant
this access, and Plan mode cannot acquire it through an execution approval.

While that full-access grant is active, remaining normal-mode actions in the
response can proceed without another approval. Manual mode is therefore not a
promise of a separate prompt for each later action after granting host access.

## Explicit full access

```text
/permissions full-access
```

This removes Eirene's filesystem containment, command isolation, network
restrictions, and approval prompts for the current process. Commands still have
only your operating-system account's privileges. It does not provide root or
administrator access, and Plan mode remains read-only.

Full access is process-local. It is not saved as the startup default, including
when you resume a conversation. Stop the current turn before changing it.

To restore restrictions:

```text
/permissions sandboxed
```

Eirene stops its managed command processes and MCP servers when restoring
sandboxed access. This does not undo completed writes, commits, network calls,
or other external effects.

## Plugins and access

Plugin installation makes written guidance available. Hooks require a separate
`/plugins trust NAME` confirmation. Each MCP server requires its own `/mcp`
activation. Trusting hooks does not enable MCP, and enabling a server does not
approve every possible action on your behalf.

A server declaration can include network access and writable paths. The MCP
picker displays them before you enable it. Its tools and plugin commands remain
subject to the selected execution policy. A plugin's requested model or list of
allowed tools does not override Eirene's permissions.

See [plugins](plugins.md), [MCP servers](mcp.md), and the project's
[security policy](../SECURITY.md) for related guidance.

## Configuration and enforcement layers

`mode` is the saved workflow preference. `permissions` and `execution_isolation`
are normalized on config load; writing `full-access` or a legacy backend into
JSON does not make a new process unrestricted. The [config reference](config-file.md#modes-access-and-interface)
describes the stored fields. Permission commands modify the current process,
while saved activation maps control which executable integrations are available.

File tools resolve paths and enforce workspace containment in the application,
including symlink resolution. Command tools apply the platform runtime boundary.
Browser/HTTP helpers run in the application and request the appropriate network
access. Native CLI connections forward policy to their own execution runtimes.
These are distinct enforcement points, not one shell setting shared by all tools.

An MCP declaration can expose additional paths and network to that server when
manually activated. It does not change the global `isolate_network` preference.
Read-only guidance and a service's own authorization are separate from process
access; see [MCP runtime boundaries](mcp.md#runtime-and-grant-boundaries).
