# Windows command sandbox

[Documentation](README.md) / Windows command sandbox

Eirene's default native Windows command path uses AppContainer. `execution_isolation:
auto` selects this backend for commands, managed processes, diagnostics and hooks
using the command supervisor. Explicit full access selects ordinary host execution.
External providers such as Claude Code manage their own execution boundaries.

## Kernel boundary and workspace grants

Each workspace has its own persistent AppContainer profile, with separate profiles
for read-only execution and for commands with approved network access. Before a
command's primary thread runs, Eirene verifies that the actual kernel token is an
AppContainer, matches the profile SID, and carries exactly the requested
capabilities. The suspended process is assigned to a kill-on-close Job before it
resumes. Normal children inherit the restrictions. There is no unsandboxed retry
when setup fails.

The first command in a workspace grants its profile SID Modify (read/execute for
read-only execution) on the workspace through an inheritable ACL entry. Windows
propagates that entry once; files created later inherit it, so later commands
start without touching ACLs. Grants persist with the profile and only that
profile's processes can use them. Modify does not grant permission to change
existing ACLs or ownership. Inheritance does not follow junctions or symlinks:
the link object receives the entry, its target does not, and access through a
link is checked against the target's own ACL. Workspaces may therefore contain
reparse points, including a user profile folder used as the workspace. Files with
protected ACLs, such as those Python creates with `os.mkdir(path, 0o700)`, keep
their own access rules (see below).

Folders above the workspace receive read-attributes only, without inheritance and
without listing, so tools such as Git can stat their way to the workspace.
Folders the user cannot re-ACL, such as `C:\Users`, are skipped. When Eirene runs
elevated it also grants the drive root read-attributes and top-level listing,
which `dir`, `vol` and PowerShell's provider need; otherwise PowerShell starts in
a `Workspace:\` drive mapped to the working directory. On non-interactive window
stations, such as SSH sessions, the profile receives limited window station and
desktop rights (no clipboard, screen reading, hooks or journaling) so that
PowerShell and other `user32` programs can start.

Windows and Program Files already admit AppContainers. User-installed runtimes on
PATH, such as per-user Python, Node, Git, Cargo/rustup and uv-managed Python, are
granted read/execute through a shared custom capability, `Eirene.Sandbox.Toolchains`.
Broad profile folders (the profile itself, AppData, Programs, Temp, `.local`) and
anything containing Eirene's own data are never granted.

Approved extra paths are granted per command to a capability derived from a unique
name, so concurrent commands cannot see each other's grants, and are revoked when
the command ends. They must name existing, specific local paths; filesystem roots
and network shares are rejected. Commands run concurrently, as on Linux.

Persistent grants outlive Eirene. Removing them is currently manual: `icacls
<workspace> /remove:g *<SID>` for the profile's `S-1-15-2-...` SID, then deleting
the profile's `%LOCALAPPDATA%\Packages\eirene.workspace.*` folder.

This is a regular AppContainer, not an LPAC or a virtual machine. Windows resources
already exposed through existing AppContainer ACLs remain exposed. This does not
make a filesystem namespace or remove pre-existing broad package permissions.
Concurrent trusted host applications can still modify the workspace.

## Input, output and network

Commands inherit only an explicit list of standard handles: private input and
output files for ordinary commands, or anonymous pipes for long-lived protocol
servers. Host credentials and loader variables are not inherited. HOME,
USERPROFILE, TEMP and TMP point to private storage. LOCALAPPDATA is explicitly
supplied during creation because Windows requires it to resolve and redirect
profile storage; omitting it produces WinError 203.

By default the token has no Internet, LAN or server capability. A command with
approved `network_access` runs in the workspace's network profile, which adds the
`internetClient`, `internetClientServer` and `privateNetworkClientServer`
capabilities. When Eirene runs elevated, that profile also receives a loopback
exemption so it can reach services on the host's localhost, as `--share-net` does
on Linux; ordinary commands never get one. Processes in the same profile can always
reach each other over loopback, so a sandboxed server and client work together.
PTYs are unsupported. Plan mode blocks arbitrary Windows commands and uses
application-validated fixed file/search tools.

Since 3.12.4, CPython's `os.mkdir(path, 0o700)` applies a protected DACL for
SYSTEM, Administrators and the owner only, which no AppContainer can open; this
breaks `tempfile.mkdtemp`, `venv`, pip and pytest. Sandboxed commands receive a
`sitecustomize` through PYTHONPATH that adds only the command's own profile SID to
that DACL, keeps itself available to venv's pip bootstrap, and then runs any
project `sitecustomize`. It is inert outside Eirene's sandbox.

Windows labels everything an AppContainer creates with Low integrity, and starts
a program whose file is labelled Low at Low integrity even from the user's own
shell; a venv built in the sandbox could then not read its own `pyvenv.cfg`. While
a command runs, Eirene watches its writable roots for new `.exe` and `.com` files
and gives them the normal Medium label when it ends, scanning modified files
instead when the change buffer overflows. Data files keep the Low label, which only
limits writes by lower-integrity processes.

## MCP servers and hooks

Sandboxed MCP stdio servers run in the workspace profile through the same runtime,
with their configured read and write paths granted for the server's lifetime and
network only when the server's definition allows it. Trusted plugin hooks run in
this runtime through `cmd`, which expands the `%PLUGIN_ROOT%`-style variables
Eirene substitutes and runs `.cmd` wrappers such as Superpowers' Git Bash launcher.
Runtime compatibility still depends on whether a program's executable, DLLs and
configuration are reachable through these grants.

## CI verification

The main suite runs once on Python 3.14. A separate Windows Server 2022/Python 3.14
job exercises Eirene's real Agent command path with default sandbox configuration
and no approval callback. It observes actual child tokens, checks allowed workspace
reads/writes, and requires outside-file and loopback HTTP requests to fail. A live
HTTP server and successful host request provide a network control. Managed commands
are polled through the ordinary tool path before checking completion.

The job also runs native token, private storage, process inheritance, timeout and
Job cleanup tests. Portable tests cover ABI layout, launch ordering, environment
filtering, handle allowlists, and failure ownership. Native checks are skipped on
Linux; portable success alone does not establish Windows containment. Native builds
and release publication require the Windows job to pass. CI skips per-OS binary
and archive smoke checks after the test jobs, while local build defaults retain them.

## References

- [AppContainer launch and access checks](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer)
- [Process attributes and explicit handle lists](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
- [Windows ACL permissions](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/icacls)
- [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
- [Job objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
