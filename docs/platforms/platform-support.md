# Platform support

[Documentation](../README.md) / Platforms / Platform support

Eirene uses your system's shell and installed tools. Installing it does not install your compilers, package managers or browsers.

| System | Builds | Shell for commands | Command sandbox |
| --- | --- | --- | --- |
| Linux | AMD64, ARM64 | Bash, falling back to POSIX `sh` | Bubblewrap with user namespaces |
| macOS | Apple Silicon | System Bash or `sh` | `sandbox-exec` (Seatbelt) |
| Windows | AMD64 | PowerShell, with CMD for batch syntax | [AppContainer](windows-sandbox.md) |

Run `/sandbox` to see the state of the sandbox on your machine, and `eirene --doctor` for a summary of your setup.

## Linux

Commands need the `bwrap` program and a system that permits user namespaces. Root is not required. Unlike macOS and Windows, whose sandboxes are built in, Linux may need Bubblewrap installed; minimal servers and containers often lack it.

If the sandbox cannot start, Eirene refuses to run commands and never falls back to running without isolation. The installer and `/sandbox` both try starting an empty sandbox, and report either `Ready` or the problem with its fix:

| Problem | Fix |
| --- | --- |
| `bwrap` is missing | Install your distribution's `bubblewrap` package. |
| Blocked by a `sysctl` setting | Change `kernel.unprivileged_userns_clone`, `user.max_user_namespaces`, or on Ubuntu `kernel.apparmor_restrict_unprivileged_userns`, as `/sandbox` advises. |
| A container forbids nesting | Allow it. On Proxmox LXC, use `features: nesting=1`. |

## macOS

Commands need the system's `sandbox-exec` utility, and Eirene reports a failure if Seatbelt cannot start. Commands use macOS shell and BSD tool conventions, which can differ from Linux: `sed -i` is an example.

## Windows

Eirene chooses PowerShell 7 or Windows PowerShell when available, and CMD otherwise. Ask for CMD explicitly when a task needs batch syntax. PowerShell 5.1 does not support Bash-style `&&`.

Commands run in an [AppContainer](windows-sandbox.md). Plan mode blocks arbitrary commands and uses Eirene's own file and search tools. Interactive terminal sessions (PTYs) are not available in the sandbox.

Claude Code on native Windows has no kernel isolation, so each normal turn needs your approval, and Plan mode disables its command and edit tools. Under WSL2, Eirene sees a Linux environment and needs the Linux build and its requirements.

## What sandboxed commands see

| | Linux (Bubblewrap) | macOS (Seatbelt) | Windows (AppContainer) |
| --- | --- | --- | --- |
| Workspace | Writable, or read-only for read-only commands | Writable, or read-only for read-only commands | Writable, or read-only for read-only commands |
| System programs and libraries | Read-only | Allowed runtime paths | Readable |
| Home and temp | Private | Private scratch directory | Private |
| Network | Off unless approved | Off unless approved | Off unless approved |
| Extra paths | Must already exist; `/` is refused | Must already exist; `/` is refused | Must exist and be specific local paths |

All three use your computer's kernel and installed programs. None is a container image or a virtual machine. The [security policy](../../SECURITY.md) describes the boundary.

The environment is also filtered: `PATH`, locale, time zone and, on Windows, system path variables are kept, and tool-specific values are added. Credentials and loader variables are not inherited.

Commands start without your shell profile, so aliases and `PATH` changes made in `.bashrc` are unavailable. A program found on `PATH` can still fail if its dependencies live in your home directory, since the sandbox cannot see them. Put required tools on the `PATH` Eirene was started with, or use project-local configuration.

## Shell profiles

The Linux and macOS installer configures `PATH` in the profiles it detects for sh, Dash, Bash, Zsh, Fish, Ksh, Csh, Tcsh, PowerShell and Nushell. It respects `ZDOTDIR` and `XDG_CONFIG_HOME`, backs up any profile it changes, and avoids duplicate entries on repeat installs. Unusual startup-file locations may need configuring by hand.

The Windows installer updates your persistent user `PATH` and the current PowerShell session. Other open terminals need restarting.

## Optional tools

| Feature | Uses |
| --- | --- |
| Clipboard on Linux | `wl-clipboard` or `xclip` |
| [Desktop notifications](../guides/notifications.md) | A notification utility for your system |
| [Built-in browser](../guides/web-and-browser.md#use-the-browser) | Chromium, Chrome or Edge |
| File diagnostics | [Your language's compiler or tools](../guides/working-with-code.md#check-the-result) |
| [Routines](../automation/routines.md) | systemd user services, launchd or Task Scheduler |
