<div align="center">

<h1>Eirene</h1>
<img src="img/Eirene.png" alt="Eirene" width="180">

A terminal coding agent.

</div>

Eirene reads files, edits code, and runs commands in your project. It works with
Ollama and API providers, or through an installed Codex or Claude Code CLI.
Conversations can be resumed, and tasks can run from the terminal interface or
in headless mode.

## Install

Linux (AMD64/ARM64) and macOS (Apple Silicon):

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

Windows (AMD64), in PowerShell:

```powershell
irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1 | iex
```

The releases are standalone binaries; you don't need Python. The installer shows
download progress, extracts the archive, and tests the binary before replacing
an existing installation. The Bash installer makes no additional download after
the archive finishes. The PowerShell installer also verifies release checksums.

Linux and macOS install to `~/.local/bin` and configure each detected supported
shell. Existing profiles are backed up. The installer sources `.bashrc` in a
verification shell; follow the printed `source` command to refresh your current
terminal, or open a new one. Windows installs to
`%LOCALAPPDATA%\Programs\eirene`, updates your user PATH, and refreshes the current
PowerShell window.

Run the same installer to update. Close Eirene first on Windows. You can also
download an archive from [Releases](https://github.com/0v3rf3ar/Eirene/releases).

Installer options:

| Variable | Purpose |
| --- | --- |
| `EIRENE_INSTALL_DIR` | Choose the installation directory |
| `EIRENE_VERSION` | Install a specific release tag, such as `v0.1.9` |
| `EIRENE_NO_PATH=1` | Leave shell profiles and persistent PATH unchanged |
| `NO_COLOR=1` | Disable installer colors |

See [platform and installer details](docs/platforms.md) for shell configuration,
architecture support, and recovery steps.

## Start

```sh
cd your-project
eirene
```

Use `/connect` to choose a provider and configure the connection. Ollama needs a
running local server and a downloaded model. API providers need their credentials.
Codex and Claude Code need their own CLI installed and signed in.

Groq is available through `/connect groq`; enter a key from
[Groq Console](https://console.groq.com/keys), or set `EIRENE_GROQ_API_KEY`.
It uses Groq's [OpenAI-compatible API](https://console.groq.com/docs/openai)
with streaming responses and tool calling.

Start with a small task, for example:

```text
Explain how this project starts, and point out the main modules.
```

Use `/help` or F1 for commands and `/keybindings` for shortcuts. Shift+Tab switches
between manual, auto, and plan modes. Plan mode is for inspecting and planning;
review permission requests before allowing commands or access outside the project.
Use `/review` to inspect working-tree changes and `/sessions` to resume earlier
conversations.

For a single prompt without the interface:

```sh
eirene -p "Explain the project structure" --mode plan
```

If setup fails, run `eirene --doctor` for installation diagnostics and `/sandbox`
inside Eirene for execution status.

Eirene checks GitHub for a newer stable release in the background when the
terminal interface starts. Run `/update` to download the matching platform
archive, verify its SHA-256 checksum, and test the executable before installing
it. `/update check` only checks availability. Restart after installation; Windows
replaces the executable after Eirene exits. Source runs download a standalone
binary and leave the Python environment and checkout untouched. Set
`check_updates` to `false` in your config, or `EIRENE_NO_UPDATE_CHECK=1`, to disable
startup checks. Offline startup continues normally.

## Code navigation

The agent can locate definitions and callers with `find_symbol` and
`find_references`, inspect focused source ranges, and run installed parsers or
compilers with `language_diagnostics`. See [code navigation](docs/code-navigation.md)
for usage and limitations.

## Platforms and execution

| Host | Native command execution |
| --- | --- |
| Linux | Bubblewrap; requires `bwrap` and working user namespaces |
| macOS | sandbox-exec (Seatbelt); requires `sandbox-exec` |
| Windows | Explicit approval for each command; no native kernel isolation |

Linux and macOS fail closed when the required isolation backend is unavailable.
Windows plan mode blocks native commands. Codex and Claude Code use their own
execution environments and permission controls.

Changes apply to your real workspace. Read [execution boundaries](docs/harness.md)
and the [security policy](SECURITY.md) for the details.

## Web search

`/search-api` configures an optional Tavily key in a hidden prompt. Normal web
search runs first; Tavily is used only when it fails and a key is configured.
Run `/search-api` again to replace or remove the key.

## Skills and plugins

Install portable plugins from GitHub (requires Git):

```text
/plugins install DietrichGebert/ponytail
/plugins inspect ponytail
/plugins trust ponytail
/ponytail ultra
/ponytail-review
```

Skills and Markdown commands appear in slash completion. Executable hooks and
stdio MCP servers require explicit plugin trust. Ponytail also requires Node.js.
Inspect a plugin before trusting it.

`/plugins browse` lists available bundles. `/skills` toggles individual skills;
`/plugins` toggles bundles. Local directories, repository subdirectories, and
GitHub repository/tree URLs are accepted. For an existing skills-only
installation, run `/plugins refresh ponytail`, then inspect and trust it.

See [plugin setup and compatibility](docs/plugins.md) for prerequisites, provider
behavior, and supported components. Host-specific features such as native
statuslines and subagent lifecycle hooks are not emulated.

## Development

Source builds require Python 3.11+ and Git:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

Run `python -m ruff check .` and `python -m mypy` for static checks, and
`python -m pytest -q --cov --cov-report=term:skip-covered --cov-report=xml` for
branch coverage. CI runs these checks and uploads a coverage report. Type
checking covers paths, subprocess helpers, updates, and language servers; the older application
modules can be added incrementally. Linting checks syntax and undefined names
across the repository without imposing a new formatting style.

On Windows, use `py -3 -m venv .venv` and `.venv\Scripts\Activate.ps1` in
PowerShell. Linux sandbox tests need Bubblewrap and working user namespaces.

Run `python build.py` to test and package a native binary. See
[build instructions](docs/platforms.md#build-on-the-target-machine) and
[real-model evaluations](docs/harness.md#evaluation) for more detail.

Eirene is licensed under [Apache-2.0](LICENSE).
