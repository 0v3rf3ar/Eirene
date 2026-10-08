# Your first session

[Documentation](README.md) / Your first session

Start in the directory you want Eirene to work on. This directory is the workspace
for file access, commands, session selection, and project instructions.

## Open a project

```sh
cd /path/to/project
eirene
```

You can also launch from elsewhere with `eirene -C /path/to/project`. The directory
must already exist. Eirene edits your actual project files, so use your normal
version control workflow to inspect changes.

## Connect a provider

Enter this inside Eirene:

```text
/connect
```

Choose a provider, complete its credential or sign-in prompts, and select a model.
API keys are entered in a hidden field. For a local model, choose `ollama-local`
and have your Ollama service running first. An installed Codex or Claude Code CLI
can use its own account login.

The connection and model are saved for later sessions. Use `/connect` to switch
providers and `/model` to choose another model. The [provider guide](providers.md)
explains prerequisites and the differences between connection types.

## Start with inspection

```text
/agents plan
Explain this project's main components and how to run its tests. Do not change files.
```

Plan mode lets Eirene inspect the workspace without editing files or running
arbitrary shell commands. Give a concrete question and mention any directory or
file that matters. If a read needs external access, Eirene may still ask for
permission.

## Make a small change

Switch to Manual mode when you are ready:

```text
/agents manual
Fix the empty-state message in the settings page. Keep the layout unchanged and run the relevant tests.
```

Manual mode presents approval controls for writes, commands, and access outside
the workspace boundary. Ordinary harmless workspace reads can proceed directly.
Read the requested action and its access scope before accepting it.
Auto mode allows ordinary workspace actions without a prompt; external access
still requires approval. See [modes and permissions](harness.md).

## Check the result

Eirene reports its work and any checks it ran. Expand command output to inspect
errors, review the actual Git diff in your usual tools, and ask for a follow-up
when necessary.

```text
/review
```

This starts a separate read-only review of staged and unstaged changes. It reports
concrete findings rather than applying fixes. You can ask Eirene to address a
finding afterward.

## Continue later

Use `/exit` or Ctrl+D to leave. Resume from the same project directory:

```sh
eirene --resume
```

Choose a saved session. Resuming restores conversation context; it does not undo
or replay file changes. See [sessions](sessions.md) for searching and exports.

```text
open workspace -> connect -> inspect -> approve changes -> verify -> resume later
```

For longer work, use [plans](plans.md). To add a reusable workflow, start with the
[plugin catalog](plugin-catalog.md); installing a plugin does not automatically
enable its executable hooks or external tool servers.
