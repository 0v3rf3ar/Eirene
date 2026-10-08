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

Eirene's native command runtime uses Bubblewrap on Linux and sandbox-exec
(Seatbelt) on macOS. It fails closed when the required backend is unavailable;
Linux also requires working user namespaces. The workspace is writable, and
additional paths need explicit grants. Network access is disabled unless approved.
Linux commands receive a private temporary directory and home. macOS commands use
a private scratch directory and an allowlist of runtime paths. Both backends use
the host kernel; neither provides virtual-machine isolation.

Windows has no native kernel isolation backend. Each native command requires
explicit approval and runs with the user's account permissions. Plan mode blocks
native commands, and headless commands that require approval fail closed.

Built-in file tools enforce resolved-path containment in the application, not an
OS sandbox. Browser/HTTP tools run in the application and request network approval.
Configured hooks and Eirene-managed MCP subprocesses use the command runtime.
Codex and Claude Code subscription providers own their execution environments;
Eirene forwards approvals and requests their native sandbox controls.

User configuration cannot select an unisolated runtime or a container backend.
Legacy backend settings are normalized to automatic platform isolation.
See [execution boundaries](docs/harness.md) for the full trust model.
