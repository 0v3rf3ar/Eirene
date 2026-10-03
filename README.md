<div align="center">

<h1>Eirene</h1>

<img src="img/Eirene.png" alt="Eirene" width="180">

<p>
<a href="https://github.com/0v3rf3ar/Eirene"><img src="https://img.shields.io/badge/GitHub-0v3rf3ar%2FEirene-181717?style=plastic&logo=github&logoColor=white" alt="GitHub repository"></a>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=plastic&logo=python&logoColor=white" alt="Python 3.10+"></a>
</p>

<hr>

</div>

A terminal coding agent. Reads files, edits code, and runs commands.
Works with Ollama, API providers, Codex, and Claude Code.

## Install

Linux (AMD64/ARM64) and macOS (Apple Silicon):

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

Windows (AMD64), in PowerShell:

```powershell
irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1 | iex
```

No Python needed. The installer configures PATH and prints a command to start
immediately; open a new terminal to run `eirene` by name.
Linux and macOS install to `~/.local/bin`, with Bash, Zsh, Fish, or `.profile`
startup configuration. Windows installs to `%LOCALAPPDATA%\Programs\eirene`
and updates your user PATH without administrator access.
Existing shell profiles are backed up before changes. Set `EIRENE_INSTALL_DIR`
to choose another directory, or `EIRENE_NO_PATH=1` to skip PATH changes.
Run the same command to update; close Eirene first on Windows.
You can also download a binary from [Releases](https://github.com/0v3rf3ar/Eirene/releases).
Archives use `eirene-<OS>-<architecture>-<version>.<format>`: `Linux-amd64`,
`Linux-arm64`, and `MacOS-silicon` use `.tar.gz`; `Windows-amd64` uses `.zip`.
For example: `eirene-MacOS-silicon-0.1.7b1.tar.gz`.

## Use

Run `eirene` in your project folder, then `/connect` to choose a provider.
Codex and Claude Code need their own CLI installed and signed in.
Use `/help` or F1 for commands, and `/keybindings` for shortcuts.

Use `/search-api` to choose Tavily and enter a key in the hidden prompt. Normal
web search stays first; Tavily is used only when it fails and a key is configured.
Run `/search-api` again to replace or remove the saved key.

## Skills and plugins

Install portable plugins from GitHub (requires Git):

```text
/plugins install DietrichGebert/ponytail
/plugins inspect ponytail
/plugins trust ponytail
/ponytail ultra
/ponytail-review
```

Skills and Markdown commands appear in slash completion immediately, with
`/plugin:command` names and unambiguous short aliases. Supported startup/prompt
hooks provide automatic activation and mode tracking across API providers,
Codex, and Claude Code. Imported executable hooks and stdio MCP servers require
explicit plugin trust. Ponytail also requires Node.js.

For an existing skills-only installation, run `/plugins refresh ponytail`, then
inspect and trust it. `/plugins browse` lists Ponytail, Superpowers, Anthropic's
skills, official review/design/commit plugins, Playwright, Serena, and Vercel skills.
Install shortcuts such as `/plugins install frontend-design` or
`/plugins install playwright`. `/skills` toggles individual skills; `/plugins`
toggles whole bundles. Local directories, `owner/repo/path` subdirectories, and
GitHub repository/tree URLs are also accepted.

See [plugin setup and compatibility](docs/plugins.md) for supported components,
provider behavior, prerequisites, and limitations. Host-specific features such
as native statuslines and subagent lifecycle hooks are not emulated.
