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

Eirene's command runtime uses kernel isolation through Bubblewrap on Linux.
It fails closed when Bubblewrap or user namespaces are unavailable. The workspace is writable; other host paths are mounted
only through explicit grants. Commands receive a private temporary directory and
home, and network access is disabled unless approved. Containers share the host
kernel; this is not virtual-machine isolation.

Built-in file tools enforce resolved-path containment in the application, not an
OS sandbox. Browser/HTTP tools run in the application and request network approval.
Configured hooks and Eirene-managed MCP subprocesses use the command runtime.
Codex and Claude Code subscription providers own their execution environments;
Eirene forwards approvals and requests their native sandbox controls.

User configuration cannot select an unisolated runtime or a container backend.
Legacy backend settings are normalized to automatic Bubblewrap isolation.
See [execution and recovery](docs/harness.md) for the full trust model.
