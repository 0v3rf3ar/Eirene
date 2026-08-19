<div align="center">

<h1>Eirene</h1>

<img src="img/Eirene.png" alt="Eirene" width="180">

<p>
<a href="https://github.com/0v3rf3ar/Eirene"><img src="https://img.shields.io/badge/GitHub-0v3rf3ar%2FEirene-181717?style=plastic&logo=github&logoColor=white" alt="GitHub repository"></a>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=plastic&logo=python&logoColor=white" alt="Python 3.10+"></a>
</p>

<hr>

</div>

## About

Eirene is a terminal-based coding agent. You give it a project directory and talk
to it through a Textual interface; it can read files, make changes, run commands,
and keep sessions around for later. It also supports one-off prompts and scheduled
tasks when an interactive session is not needed.

It works with API-based providers as well as existing Codex and Claude Code
subscriptions. File and command permissions can be switched between manual, auto,
and read-only planning modes. The project sandbox helps prevent accidental access
outside the selected directory, but it is not a replacement for a container or an
OS-level sandbox.

## Install

Python 3.10 or newer is required.

```sh
git clone https://github.com/0v3rf3ar/Eirene.git
cd Eirene
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
eirene
```

On Windows, activate the environment with `.venv\Scripts\activate` instead.

Once Eirene opens, run `/connect` to choose a provider. API keys can be entered
there or supplied through environment variables. The ChatGPT and Claude
subscription options use the `codex` and `claude` command-line tools respectively,
so the matching tool must already be installed and signed in.

Run `/help` inside Eirene to see the available commands.
