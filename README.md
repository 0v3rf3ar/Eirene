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

No Python needed. Reopen your terminal after installing.
Run the same command to update; close Eirene first on Windows.
You can also download a binary from [Releases](https://github.com/0v3rf3ar/Eirene/releases).

## Use

Run `eirene` in your project folder, then `/connect` to choose a provider.
Codex and Claude Code need their own CLI installed and signed in.
Use `/help` or F1 for commands, and `/keybindings` for shortcuts.

Linux command isolation needs Bubblewrap and enabled user namespaces.
See [platform support and building from source](docs/platforms.md) or
[permissions and recovery](docs/harness.md) for details.
