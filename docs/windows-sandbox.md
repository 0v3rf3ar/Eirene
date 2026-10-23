# Windows sandbox implementation

[Documentation](README.md) / Windows sandbox implementation

Status: experimental launch primitive. Eirene's normal Windows commands still
require approval and run with the user's access. This implementation is not
selected by `execution_isolation: auto`, and `/sandbox` continues to report that
there is no active native command sandbox. No Android behavior changes.

## Implemented boundary

`eirene.tools.windows_appcontainer.AppContainer` creates a unique, per-user
AppContainer profile using the documented Win32 APIs. It launches an absolute
executable with `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`, zero capabilities,
`CREATE_SUSPENDED`, and an explicit Unicode environment. The executable does not
inherit handles or the parent's environment. Standard input/output pipes are not
implemented in this first stage.

Before resuming the primary thread, the launcher queries the actual process
token and requires all three of these conditions:

- `TokenIsAppContainer` is true.
- `TokenAppContainerSid` matches the newly created profile.
- `TokenCapabilities` contains no capabilities.

It then assigns the suspended process to a Job with kill-on-close enabled and
resumes the known primary thread handle. Failures stop execution; there is no
host-execution retry. Normal child processes inherit the AppContainer token and
Job membership. Closing the context terminates the Job, waits for the primary
process and all Job members to exit, closes handles, and deletes the profile.
If process cleanup fails, profile deletion is withheld and `close()` can retry.

The child starts in the profile's private `LocalState` directory. `HOME`,
`USERPROFILE`, `TEMP`, and `TMP` point there. `PATH` contains only Windows
System32. The environment explicitly supplies the host's `LOCALAPPDATA`, which
Windows needs to resolve and redirect AppContainer profile storage during
`CreateProcessW`. Missing or invalid values fail before process creation with a
message naming the variable, rather than Windows error 203. Commands cannot yet
access a project through an Eirene workspace grant.
The launcher does not change host filesystem ACLs, integrity labels, firewall
rules, or loopback exemptions. It does not request network capabilities.

This is a regular AppContainer, not an LPAC or a virtual machine. Resources
already made available to AppContainers by Windows or existing ACLs remain
available. Zero capabilities do not mean a universal filesystem deny rule.
The profile also has its own persistent storage and registry state until cleanup.
An abrupt termination of the Eirene host can leave the profile on disk; Job
kill-on-close still applies, but startup recovery of orphaned profiles is not
implemented. The API is synchronous and must not be called on the UI event loop.

Development example on Windows, outside the production command runtime:

```python
import os
from pathlib import Path
from eirene.tools.windows_appcontainer import AppContainer

cmd = str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe")
with AppContainer() as sandbox:
    process = sandbox.spawn([cmd, "/d", "/s", "/c", "echo hello>result.txt"])
    assert process.wait(timeout=15) == 0
    print((sandbox.home / "result.txt").read_text())
```

The caller is trusted orchestration code. Do not expose profile creation,
environment construction, or native handles as model-controlled tool arguments.
Use this API from one thread and always close its context.

## Validation and remaining integration

Portable tests verify launch ordering, failure cleanup, profile retention after
cleanup failures, Win32 structure layouts, Unicode limits, zero-capability
creation attributes, token rejection, and environment filtering. Native Windows
tests exercise private storage, denied access to outside files, child-process
inheritance, exit codes, and Job cleanup. The Windows CI job runs on Python 3.14
after the single full-suite Python 3.14 job. It additionally requires the normal
Agent command path, with default sandbox configuration and no approval handler,
to execute a real command with an AppContainer token and zero capabilities, allow
workspace access, and deny outside-file and loopback network access. A live HTTP
server and a successful host curl request provide the network control.

The default-runtime gate currently fails because the launcher is not integrated
into Agent execution. It has no expected-failure or availability skip on Windows;
all native builds and release publication wait for it to pass. Linux skips these
Windows tests. Passing portable or standalone launcher tests cannot satisfy the
default-runtime gate. CI builds archives without per-OS smoke checks once the
test jobs pass; local build/archive commands still perform smoke checks.

Before enabling automatic Windows command isolation, complete and validate:

1. Workspace and additional-path grants, including read-only execution,
   overlapping grants, inherited/protected ACLs, reparse points, hard links,
   concurrent commands, rollback, and abrupt-exit recovery. Grants must not give
   commands ownership or permission to change host ACLs.
2. Async stdout/stdin pipe integration with an explicit inherited handle list,
   cancellation, deadlines, background services, and descendant cleanup.
3. Network grant semantics, including Internet, LAN, DNS, loopback, and inherited
   sockets; no silent fallback or automatic firewall exemptions.
4. Compatibility with PowerShell, CMD, Git, Python, Node, and common build tools,
   including runtimes installed under the user's profile.
5. All launch paths: commands, diagnostics, hooks, MCP servers, fixed native
   read/search tools, and external-provider boundaries. External providers need
   separate review because they own their command execution.
6. Permission decisions, plan-mode enforcement, sandbox status, diagnostics,
   packaged-executable tests, and Windows client-device validation. The current
   CI target is Windows Server 2022, not every supported Windows client.

## Reference documentation

The implementation follows Microsoft's documented
[AppContainer launch procedure](https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer),
[profile creation](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile),
[profile storage](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-getappcontainerfolderpath),
[process attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[token inspection](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-gettokeninformation),
and [profile deletion](https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-deleteappcontainerprofile).
See also [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
and [legacy application behavior](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-for-legacy-applications-).
