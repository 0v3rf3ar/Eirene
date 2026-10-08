# Troubleshooting

[Documentation](README.md) / Troubleshooting

Start with the smallest check that matches the failure. Installation diagnostics,
a provider connection, command isolation, and plugin startup test different parts
of the environment.

## Read installation facts

```sh
eirene --version
eirene --doctor
eirene --doctor --json
```

The doctor is read-only. It reports data-directory access, configuration version,
provider presence, credential-store availability, and relevant platform utilities.
It does not contact the model service, run plugin code, or verify every dependency.
A `ready` result means its configuration checks passed, not that every feature
has been exercised.

## Common issues

| Symptom | What to check |
| --- | --- |
| `eirene` is not found | Open a new terminal or try the installed executable's full path. See [installation](installation.md). |
| The interface will not start in a pipe | Interactive use needs a terminal; use `-p` for a [headless run](headless.md). |
| The workspace is rejected | `-C` must name an existing directory; quote spaces and check permissions. |
| No provider is selected | Run `/connect` interactively and choose a model. |
| A key is rejected | Replace it through `/connect PROVIDER!`; check provider access and quota. |
| The model answers but cannot act | Choose a tool-capable connection; Perplexity is text-only. |
| A local model is unavailable | Check the Ollama service and downloaded models before reconnecting. |
| Commands cannot start on Linux | Check `bwrap`, user namespaces, and `/sandbox`. |
| Commands cannot start on macOS | Check the availability of `sandbox-exec` and its reported failure. |
| An unattended Windows command fails | It needs interactive approval; see [platform support](platforms.md). |
| A server disappears after a response | A temporary host-access grant may have ended. See [processes](processes.md). |
| Copying does not reach the desktop | Check terminal clipboard integration and Linux `wl-clipboard` or `xclip`. |
| A notification does not appear | Run `/notification test` and check the desktop session and OS settings. |

## A response is slow or reconnecting

The status indicator can show waiting or retry activity. Eligible transient API
failures before delivered content or tool activity are retried, with up to 12
attempts by default. Delays can grow to a minute, or longer when the service asks
for it. Escape cancels the wait.

Authentication, quota, and other permanent failures stop immediately. A partially
delivered response or a stalled native CLI turn is not automatically replayed,
because actions may already have run. Inspect current files and command state
before requesting a retry. Exhausted retries show that recovery failed, not proof
that the service is permanently unavailable.

## A plugin command is missing

```text
/plugins
/skills
/plugins inspect NAME
/plugins doctor NAME
```

Check that the bundle and relevant skill are enabled. Use its namespaced command
when the short name collides with another plugin or a built-in. A declared
non-user-invocable skill does not appear as a slash command. If installed files
changed, use `/plugins refresh NAME`; this also revokes hooks and disables its
MCP servers, so reapprove what you need.

## Hooks or MCP do not run

Hooks need `/plugins trust NAME`; MCP needs per-server `/mcp` activation. They are
separate grants. Plan mode does not launch either. Stop the current turn before
changing executable activation.

A missing `node`, `npx`, `uvx`, `git`, or gateway executable must be installed and
visible on PATH. First startup can need network access and downloads. A launcher
starting does not prove the browser, language server, or service account is ready.
Read the individual [plugin guide](plugin-catalog.md) for its prerequisites.

## Inspect logs and share a useful report

The runtime log is `logs/eirene.jsonl` beneath the data directory. Record the
version, OS, provider, exact command or prompt, and the displayed error. For plugin
issues, include `/plugins inspect NAME` and `/plugins doctor NAME` output.

Remove API keys, private URLs, conversation content, and other secrets before
sharing logs or exports. Use the repository's [security policy](../SECURITY.md)
for a security issue. Back up data before manually replacing configuration; do not
remove the whole data directory just to repair one provider connection.
