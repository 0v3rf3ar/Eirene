<div align="center">

<h1>Eirene</h1>
<img src="img/Eirene.png" alt="Eirene" width="180">

A terminal coding agent.

[![Release](https://img.shields.io/github/v/release/0v3rf3ar/Eirene?include_prereleases)](https://github.com/0v3rf3ar/Eirene/releases)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

</div>

Eirene reads files, edits code, and runs commands in your project. Connect a local
model, an API provider, or an installed Codex or Claude Code CLI, then describe
what you want to do.

## Installation

Linux (AMD64/ARM64) and macOS (Apple Silicon):

```sh
bash <(curl -fsSL https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.sh)
```

Windows (AMD64), in PowerShell:

```powershell
irm https://raw.githubusercontent.com/0v3rf3ar/Eirene/master/install.ps1 | iex
```

The releases are standalone binaries and do not require Python. Open a new
terminal after installation, run `eirene` from your project directory, and use
`/connect` to set up your provider.

[Documentation](docs/README.md) · [Installation options](docs/installation.md) ·
[Release downloads](https://github.com/0v3rf3ar/Eirene/releases)
