# Windows sandbox

[Documentation](../README.md) / Platforms / Windows sandbox

On Windows, Eirene runs commands, managed processes, diagnostics, hooks and MCP stdio servers inside an AppContainer, a kernel-enforced Windows security boundary. This page explains what that means in practice. For an overview of all systems, see [Platform support](platform-support.md).

With [full access](../guides/modes-and-permissions.md#full-access), commands run normally instead. External providers such as Claude Code manage their own boundaries.

## How a command is started

Each workspace has its own persistent AppContainer profile, with separate profiles for read-only commands and for commands with approved network access. Before a command's first thread runs, Eirene checks the real kernel token: it must be an AppContainer, match the profile, and carry exactly the expected capabilities. The process is placed in a Job that kills it when the Job closes,
and its child processes inherit the same restrictions.

If setup fails, the command fails. There is no retry without the sandbox.

## What sandboxed commands can reach

**The workspace.** The first command in a workspace grants its profile Modify access (read and execute for the read-only profile) through an inherited ACL entry. Files created later inherit it, so later commands start without touching ACLs, and commands can run at the same time. Modify does not allow changing ACLs or ownership. Junctions and symlinks inside the workspace do not extend the grant: access through a link
is checked against the target's own ACL.

**Folders above the workspace.** These get read-attributes only, with no listing, so tools such as Git can find their way to the workspace. Folders you cannot change the ACL of, such as `C:\Users`, are skipped. When Eirene runs elevated, it also grants the drive root read-attributes and top-level listing; otherwise PowerShell starts in a `Workspace:\` drive mapped to the working directory.

**Your installed tools.** Windows and Program Files already admit AppContainers. Per-user runtimes on `PATH`, such as Python, Node, Git, Cargo, rustup and uv-managed Python, are granted read and execute through a shared capability, `Eirene.Sandbox.Toolchains`. Broad folders are never granted: your profile itself, AppData, Programs, Temp, `.local`, or anything holding Eirene's own data.

**Extra paths you approve.** These are granted per command to a uniquely named capability and revoked when the command ends. They must be existing, specific local paths; drive roots and network shares are rejected.

**The network.** By default, a command has no Internet, LAN or server capability. An approved command runs in the workspace's network profile, which adds `internetClient`, `internetClientServer` and `privateNetworkClientServer`. When Eirene runs elevated, that profile can also reach services on the host's localhost. Processes in the same profile can always reach each other over loopback, so a sandboxed
server and client work together.

## Environment

Commands inherit only an explicit list of standard handles. Host credentials and loader variables are not inherited. `HOME`, `USERPROFILE`, `TEMP` and `TMP` point to private storage.

Plan mode blocks arbitrary commands and uses Eirene's own validated file and search tools. PTYs are not supported.

## Compatibility adjustments

Two Windows behaviors would break common developer tools, so Eirene handles them:

**Python's private folders.** Since CPython 3.12.4, `os.mkdir(path, 0o700)` creates a folder that no AppContainer can open, which breaks `tempfile.mkdtemp`, `venv`, pip and pytest. Sandboxed commands get a small `sitecustomize`, through `PYTHONPATH`, that adds only the command's own profile to these folders. It then runs any `sitecustomize` your project has, and does nothing outside the sandbox.

**Low-integrity files.** Windows labels everything an AppContainer creates as Low integrity, and runs a program with that label at Low integrity even when you start it yourself. A virtual environment built in the sandbox could then not read its own `pyvenv.cfg`. So while a command runs, Eirene watches for new `.exe` and `.com` files and restores the normal Medium label on them when it ends. Data files keep the Low label, which only limits
writes by lower-integrity processes.

## MCP servers and hooks

MCP stdio servers run in the workspace's profile, with their configured read and write paths granted for the server's lifetime, and network only if their definition allows it.

Trusted plugin hooks run through `cmd`, which expands `%PLUGIN_ROOT%`-style variables and runs `.cmd` wrappers.

Whether a program works depends on whether its executable, DLLs and configuration are reachable through these grants.

## Limits of the boundary

This is a regular AppContainer, not an LPAC or a virtual machine:

- Resources already open to all AppContainers through existing ACLs remain reachable.
- There is no separate filesystem namespace.
- Other programs you are running can still change the workspace.
- On non-interactive sessions such as SSH, the profile gets limited window station and desktop rights, without clipboard, screen reading or hooks, so that PowerShell can start.

## Remove the grants

Workspace grants outlive Eirene and are currently removed by hand:

1. Find the profile's SID, which begins `S-1-15-2-`, and remove its entry:

   ```powershell
   icacls C:\path\to\workspace /remove:g "*S-1-15-2-..."
   ```

2. Delete the profile's folder from `%LOCALAPPDATA%\Packages\eirene.workspace.*`.

## Further reading

- [Implementing an AppContainer](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
- [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
- [Job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
- [`icacls`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls)
