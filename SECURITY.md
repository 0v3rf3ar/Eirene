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

Windows has no native kernel isolation backend. Each arbitrary shell command requires
explicit approval and runs with the user's account permissions. Plan mode blocks
arbitrary shell commands, and headless commands that require approval fail closed.

Fixed native read/search templates validate paths and pass patterns as data.
On Linux/macOS they run in the read-only command sandbox; Windows permits these
fixed templates as application-validated read tools, including in plan mode.
They never accept arbitrary model-supplied script text. File edits and patches
enforce resolved-path containment in the application. Browser/HTTP tools run in the application and request network approval.
Configured hooks and Eirene-managed MCP subprocesses use the command runtime.
Codex and Claude Code subscription providers own their execution environments;
Eirene forwards approvals and requests their native sandbox controls.

User configuration cannot select an unisolated runtime or a container backend.
Legacy backend settings are normalized to automatic platform isolation.
See [execution boundaries](docs/harness.md) for the full trust model.
