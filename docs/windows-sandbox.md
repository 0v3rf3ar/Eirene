# Windows command sandbox

[Documentation](README.md) / Windows command sandbox

Eirene's default native Windows command path uses AppContainer. `execution_isolation:
auto` selects this backend for commands, managed processes, diagnostics and hooks
using the command supervisor. Explicit full access selects ordinary host execution.
External providers such as Claude Code manage their own execution boundaries.

## Kernel boundary and workspace grants

Each command gets a unique AppContainer profile. Before the primary thread runs,
Eirene verifies that the actual kernel token is an AppContainer, matches the
profile SID, and has zero capabilities. The suspended process is assigned to a
kill-on-close Job before it resumes. Normal children inherit the restrictions.
There is no unsandboxed retry when setup fails.

The runtime grants the package SID read/execute or Modify access through Windows
ACLs. Modify does not grant permission to change existing host ACLs or ownership.
The workspace is writable for ordinary commands and read-only for read-only
execution. Additional grants must name existing, specific local paths. Missing
permissions, protected ACLs and inaccessible runtimes fail closed. Windows and
Program Files runtimes use existing OS permissions; a caller-owned runtime outside
the workspace may receive an additional read/execute grant.

Grant operations and command execution are serialized per user/session with a
named semaphore. This prevents another Eirene sandbox from modifying the workspace
while grants are being prepared. A concurrent launch fails with an instruction to
poll or stop the current command. Trees containing symlinks/junctions or other
reparse points, filesystem roots, and network-share grants are rejected.

Cleanup terminates and reaps the entire Job before removing only this unique
package SID's temporary grants and deleting its profile. It does not restore an
old ACL snapshot over unrelated changes. Cleanup failures are reported as failed
commands. If processes cannot be reaped, the command slot remains held. An abrupt
host termination can leave orphaned profiles and SID ACL entries; automatic
recovery is not implemented. These profiles must not be reused for other work.

This is a regular AppContainer, not an LPAC or a virtual machine. Windows resources
already exposed through existing AppContainer ACLs remain exposed. This does not
make a filesystem namespace or remove pre-existing broad package permissions.
Concurrent trusted host applications can still modify the workspace.

## Input, output and limitations

The child inherits only an explicit list of standard handles for private input and
output files. Input is supplied before creation; output is streamed into the
existing command supervisor and artifacts. Host credentials and loader variables
are not inherited. HOME, USERPROFILE, TEMP and TMP point to private storage.
LOCALAPPDATA is explicitly supplied during creation because Windows requires it
to resolve and redirect profile storage; omitting it produces WinError 203.

Network grants are currently unsupported. The token receives no Internet, LAN or
server capabilities, and no loopback exemptions are installed. Requesting network
enablement fails closed; `/permissions full-access` remains an explicit host-access
choice. PTYs and interactive streaming stdin are unsupported. Plan mode blocks
arbitrary Windows commands and uses application-validated fixed file/search tools.
Those fixed tools are trusted operations, not arbitrary model-supplied scripts.

MCP stdio launch wrapping is not integrated with this runtime. Sandboxed Windows
MCP startup fails closed; existing full-access/provider-owned execution has its own
boundary. Runtime compatibility still depends on whether its executable, DLLs and
configuration are accessible through the granted paths. User-installed toolchains
may require specific read grants.

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
