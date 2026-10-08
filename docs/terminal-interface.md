# Terminal interface

[Documentation](README.md) / Terminal interface

The transcript shows your requests, responses, and tool activity. The composer at
the bottom accepts a task, a follow-up, or a slash command. The model and mode
indicators show the connection and working policy currently in use.

## Compose and send

Press Enter to send. For a new line, type a backslash at the end of the current
line and press Enter; the backslash is replaced by the line break. Multiline
pastes keep their line breaks. Large pastes collapse into a short label in the
composer and expand back to their full text when sent.

Up and Down recall previous prompts when you are at the corresponding edge of
the input. In a multiline draft, they first move through its lines. Secret input
is masked and excluded from ordinary prompt history.

Type `/` to browse commands. Up and Down select a menu item, Tab completes it
without running it, and Enter accepts it. A command that needs arguments lets you
supply them before submitting the task. Escape closes the active popup.

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| F1 | Show command help and shortcuts. |
| F2 | Pick a model. |
| F3 | Pick a saved session. |
| Ctrl+K | Show keybindings. |
| Ctrl+B | View output or stop running commands. |
| Ctrl+T | Pick a theme. |
| Ctrl+P | Toggle prompt suggestions. |
| Shift+Tab | Cycle Manual, Auto, and Plan modes. |
| Escape | Close a popup or interrupt current work. |
| Ctrl+E | Jump to the latest transcript output. |
| Ctrl+Shift+C | Copy selected input or transcript text. |
| Ctrl+C | Copy selected text quietly. |
| Right click | Copy selected text. |
| Ctrl+D | Exit. |
| Tab or Right arrow | Copy a suggestion into an empty composer. |

Ctrl+C is a copy shortcut inside the interface; use Escape to stop the agent.
Keyboard behavior can depend on your terminal's own bindings. `/keybindings`
shows the same shortcuts from within Eirene.

## Follow tool activity

Command output starts as a compact preview. Select the output block to expand or
collapse it. Expanded views are still bounded; for a long log, ask Eirene to read
the saved output around the relevant error. Expand/collapse choices survive a
session resume.

A background-work line appears below the model name while commands are running.
Select it or press Ctrl+B to inspect output and stop a process. A quiet command
can still be running; elapsed time alone does not establish that it is stuck.
See [running commands](processes.md).

The live status indicator can show model reasoning or waiting activity without
adding that text to the saved conversation. Reduced-motion settings keep the
status readable with a static marker.

## Steer or stop an active task

A new message sent during a response is queued for the next execution boundary.
Eirene can incorporate it before continuing with pending actions. Already running
commands and parallel reads may finish before the new instruction is applied.
Use Escape when you need work stopped rather than queued guidance.

Stopping cancels the response and managed work associated with it. It does not
roll back changes already written to your project or actions already taken on an
external service. Inspect your files or Git diff before continuing.

## Pickers and approvals

Pickers are used for models, sessions, skills, plugins, and settings. Choose an
item to apply it; Escape cancels or closes the popup. The composer retains a draft
when opening ordinary quick-action menus.

Approval prompts are different from ordinary choices. A command approval can
grant host access for the rest of the response, as disclosed by the prompt.
Answering an ordinary task question does not grant execution access. Read
[modes and permissions](harness.md) for the scope of those decisions.

## Clipboard and display

Linux may need `wl-clipboard` or `xclip` for system clipboard copying. Terminal
clipboard integration and host utilities affect whether the copy reaches your
desktop clipboard. `/theme`, `--no-color`, and `--reduce-motion` control display;
see [appearance](appearance.md).
