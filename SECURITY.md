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

Eirene's working-directory checks are meant to prevent accidents; they are not an
OS security boundary. A command you approve runs with your user account's access.
Use a container or another restricted environment when stronger isolation is
needed.
