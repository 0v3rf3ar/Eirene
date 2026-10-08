# Security Policy

Security fixes are made against the latest release of Eirene.

If you find a security problem, please do not open a public issue. Use **Report a
vulnerability** under the repository's **Security** tab so the details stay private
until a fix is available.

Include the Eirene version, operating system, a short description of the impact,
and enough steps to reproduce the issue. Remove API keys, tokens, and other private
information before sending the report.

Issues involving unapproved file access, command execution, or credential exposure
are in scope. Problems in third-party model providers or external command-line tools
should be reported to those projects.

By default, Eirene's native command runtime uses Bubblewrap on Linux and sandbox-exec
(Seatbelt) on macOS. It fails closed when the required backend is unavailable;
Linux also requires working user namespaces. The workspace is writable, and
additional paths need explicit grants. Network access is disabled unless approved.
Execution approval (yes or always) grants full host access only for the current
response. The approval UI discloses this scope. Sandbox restrictions return on
completion, failure, interruption, or cancellation; managed services and commands
started under the grant are stopped. Normal question answers never grant access,
and plan mode cannot obtain full access through approval.
Linux commands receive a private temporary directory and home. macOS commands use
a private scratch directory and an allowlist of runtime paths. Both backends use
the host kernel; neither provides virtual-machine isolation.

Windows has no native kernel isolation backend. Arbitrary shell commands require
explicit approval or an active full-access grant and run with the user's account permissions. Plan mode blocks
arbitrary shell commands, and headless commands that require approval fail closed.

Fixed native read/search templates validate paths and pass patterns as data.
On Linux/macOS they run in the read-only command sandbox; Windows permits these
fixed templates as application-validated read tools, including in plan mode.
They never accept arbitrary model-supplied script text. File edits and patches
enforce resolved-path containment in the application. Browser/HTTP tools run in the application and request network approval.
Configured hooks and Eirene-managed MCP subprocesses use the command runtime.
Manually enabled MCP declarations can grant that server network access with `network: true`.
The optional OmniRoute management adapter uses this grant and, once enabled through `/mcp`,
uses the saved OmniRoute URL/key and its declared gateway data directory.
Codex and Claude Code subscription providers own their execution environments;
Eirene forwards approvals and requests their native sandbox controls.

`/permissions full-access` explicitly disables command isolation, path containment,
network restrictions, and Eirene approval prompts for the current process.
Commands retain the OS account's privileges; this does not grant root access.
Plan mode remains read-only. `/permissions sandboxed` stops Eirene-managed command
processes and MCP servers and restores restrictions. External effects already
performed cannot be undone. Every new process starts sandboxed, including resumes.
Legacy backend settings are normalized to automatic platform isolation.
See [execution boundaries](docs/harness.md) for the full trust model.
