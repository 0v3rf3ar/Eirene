<div align="center">

<h1>Eirene</h1>
<img src="img/Eirene.png" alt="Eirene" width="180">

Fully autonomous AI agent for coding, automation, and deployment.

[![0v3rf3ar / Eirene](https://img.shields.io/badge/0v3rf3ar-Eirene-7c3aed)](https://github.com/0v3rf3ar/Eirene)
[![Release](https://img.shields.io/github/v/release/0v3rf3ar/Eirene?include_prereleases)](https://github.com/0v3rf3ar/Eirene/releases)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

</div>

Eirene works directly in your project to inspect code, implement changes, run
tests, diagnose failures, and carry out automation and deployment workflows. It
uses execution results to guide subsequent actions, correct errors, and verify
changes, allowing you to delegate multi-step tasks while retaining control over
permissions and execution.

Connect local models, API providers, or installed Codex and Claude Code CLIs.
Use `/connect chatgpt-plan` for direct ChatGPT subscription sign-in with Eirene's
own agent loop; account eligibility and plan limits apply.
For local Ollama models, [dynamic context shifting](docs/context-shifting.md)
adapts context budgets and tool instructions to the model and available hardware,
summarizing earlier work
while preserving task decisions and execution evidence. This keeps longer tasks
manageable within smaller context windows.

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

[Configuration reference](docs/config-file.md) · [Data and source layout](docs/data-layout.md) ·
[Standalone MCP setup](docs/mcp.md#declare-a-standalone-server)
