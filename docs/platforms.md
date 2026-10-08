# Platform support

[Documentation](README.md) / Platform support

Eirene uses your operating system's shell and installed tools. Standalone
release availability and command execution requirements are separate: installing
the binary does not install your compiler, package manager, browser, or sandbox.

## Releases and command environments

| System | Standalone release | Command environment | Native execution boundary |
| --- | --- | --- | --- |
| Linux | AMD64, ARM64 | Bash, with POSIX sh fallback | Bubblewrap and permitted user namespaces |
| macOS | Apple Silicon | System Bash/sh and macOS utilities | `sandbox-exec` / Seatbelt |
| Windows | AMD64 | PowerShell; CMD available for CMD syntax | Explicit command approval; no kernel isolation backend |

Paths and filenames follow the host's conventions. Eirene receives host guidance
so it can choose installed utilities rather than assume every machine behaves
like Linux. Commands start without ordinary shell profiles, so put required
executables on the environment's PATH rather than relying on interactive aliases.

## Linux

Sandboxed command execution needs `bwrap` and a system policy that permits user
namespaces. If either is unavailable, Eirene reports the failure and does not
silently execute without isolation. Install Bubblewrap through your distribution's
package manager and check local namespace restrictions if `/sandbox` reports a
problem. File inspection alone does not prove command isolation works.

The command environment uses a private temporary directory and home. A dependency
available only through your usual home configuration may need explicit access or
project-local configuration.

## macOS

Sandboxed execution requires the system `sandbox-exec` utility. Commands use
macOS shell and BSD utility conventions. If Seatbelt cannot start, Eirene reports
that failure instead of bypassing the boundary. Use a matching Apple Silicon
release archive for standalone installation.

## Windows

Eirene selects PowerShell 7 or Windows PowerShell when available, then CMD as a
fallback. Ask explicitly for CMD when a task requires batch syntax. PowerShell
5.1 does not support Bash-style `&&`; dependent commands need host-appropriate
exit-code checks.

There is no native kernel isolation backend for arbitrary commands. They require
explicit approval and run with your user account's filesystem and network access,
unless you have explicitly enabled full access for this process. Headless runs
cannot answer these approvals and fail closed. Plan mode uses portable file tools
and validated fixed search/read operations rather than arbitrary shell scripts.

Claude Code on native Windows requires approval for each normal turn without
kernel isolation. Plan mode disables its command and edit tools. A WSL2 setup
uses the Linux environment and its separate installation requirements.

## Shell profiles and PATH

The Bash installer configures detected Sh/Dash, Bash, Zsh, Fish, Ksh, Csh/Tcsh,
PowerShell, and Nushell profiles. It respects supported user configuration
locations such as `ZDOTDIR` and `XDG_CONFIG_HOME`, backs up changed profiles, and
avoids duplicate PATH entries on repeated installs. Custom shell wrappers or
startup-file locations may need manual configuration.

Windows installation updates the persistent user PATH and the current PowerShell
process. Other already-open terminal apps can retain their old PATH. Restart them
if `eirene` is not found. See [installation](installation.md).

## Optional desktop tools

System clipboard support may need `wl-clipboard` or `xclip` on Linux. Desktop
notifications prefer `notify-send` on Linux, `terminal-notifier` or `osascript` on
macOS, and PowerShell on Windows; the [notification guide](notifications.md)
lists supported alternatives. Browser features need a supported installed
Chromium-based browser or
the dependencies of the selected browser plugin.

Use `eirene --doctor --json` for environment facts, `/sandbox` for the current
execution boundary, and `/plugins doctor` for plugin dependencies. The doctor
report does not contact providers or prove their credentials work.

## Sandbox environment and runtime mounts

Bubblewrap exposes system executable/library paths read-only, the workspace
writable for normal execution, and private `/tmp` and home locations. A read-only
command template makes the workspace read-only too. Extra read/write mounts
must already exist and cannot grant the filesystem root. Network isolation uses
a separate network namespace unless a network grant applies.

Seatbelt restricts filesystem operations through a generated profile and uses a
private scratch directory. Both mechanisms use the host kernel and installed
runtime; neither creates a container image or a virtual machine. System runtime
paths differ, so a launcher found on PATH can still fail if its dependencies are
in an unexposed home directory.

Isolated child environments retain a small allowlist including PATH, locale, TZ,
and Windows system path variables, then add explicit tool/server environment
values. They do not inherit every credential/loader variable. Outside isolation,
process inheritance differs. PTY execution is unavailable in Eirene's Windows
runtime. For server mounts/env, see [MCP fields](config-file.md#standalone-mcp-declarations).
