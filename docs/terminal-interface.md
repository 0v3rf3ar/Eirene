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

Drop files from your file manager into the terminal to attach them to your next
chat message. This requires a terminal that delivers dropped paths as paste
events; pasting an absolute file path works too. Quoted paths, escaped spaces,
local `file://` URLs, and multiple files are supported. Each file appears inside
the input as a bold `[filename.ext]` token. Delete the token to remove it; undo
restores it. Files are sent with your next chat message.

Dropped files are copied into private attachment storage. The message includes
their attachment IDs, and the model can use the `read_attachment` tool to read
them without opening the original path. Text is read in pages, binary files can
be read as base64, and PNG, JPEG, GIF, and WebP files load for vision with an
image-capable model. The default limit is **20 MB per file**; edit
`max_attachment_bytes` in [config.json](config-file.md) to change it. You can
attach up to ten files, including files outside the project; attaching one does
not grant the agent access to other files in that location. Stored attachments
remain available when you resume the conversation.

Up and Down recall previous prompts when you are at the corresponding edge of
the input. In a multiline draft, they first move through its lines. Secret input
is masked and excluded from ordinary prompt history.

The terminal controls the font for the entire interface. To use Courier New,
select it in your terminal's font settings; Eirene cannot set a separate font
for the input field.

Type `/` to browse commands. Up and Down select a menu item, Tab completes it
without running it, and Enter accepts it. A command that needs arguments lets you
supply them before submitting the task. Escape closes the active popup.

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| F1 | Show command help and shortcuts. |
| F2 | Pick a model. |
| F3 | Pick a saved session. |
| F4 | Switch the mouse between Eirene's handling and your terminal's own selection. |
| Ctrl+K | Show keybindings. |
| Ctrl+B | View output or stop running commands. |
| Ctrl+T | Pick a theme. |
| Ctrl+P | Toggle prompt suggestions. |
| Shift+Tab | Cycle Manual, Auto, and Plan modes. |
| Escape | Close a popup or interrupt current work. |
| Ctrl+E | Jump to the latest transcript output. |
| PageUp / PageDown | Scroll the transcript while typing. |
| Ctrl+Shift+C | Copy selected input or transcript text (Ctrl+C on Windows, Cmd+C on macOS). |
| Ctrl+D | Exit. While the agent or a command is running, press it again within 3 seconds to confirm. |
| Tab or Right arrow | Copy a suggestion into an empty composer. |

Copy uses your platform's terminal copy shortcut only. Many Linux terminals
send Ctrl+Shift+C as plain Ctrl+C, so Ctrl+C copies there too. Use Escape to
stop the agent.
Keyboard behavior can depend on your terminal's own bindings. `/keybindings`
shows the same shortcuts from within Eirene.

## Follow tool activity

Command output starts as a compact preview. Select the output block to expand or
collapse it. Expanded views are still bounded; for a long log, ask Eirene to read
the saved output around the relevant error. Expand/collapse choices survive a
session resume.

A background-work line appears below the model name while commands are running.
Select it or press Ctrl+B to inspect a process's output; press S in that view to
stop it. A quiet command
can still be running; elapsed time alone does not establish that it is stuck.
See [running commands](processes.md).

The live status indicator can show model reasoning or waiting activity without
adding that text to the saved conversation. Reduced-motion settings keep the
status readable with a static marker.

The optional Eirene companion starts disabled. `/companion` toggles her silently;
`/companion on` and `/companion off` set and save the preference explicitly.
The command appears in the slash menu and help only in image-capable terminals.
When enabled, she sits on the right above the input. She uses her laptop
while thinking, working, or writing files. The question pose appears when she
asks you something or needs confirmation. Otherwise she rests with a neutral
expression. Her picture overlays the right edge of the interface, anchored to
the input border, so the composer and status keep their usual positions.
After a minute without attention while idle or waiting for you,
she falls asleep;
typing or clicking wakes her. She stays anchored to the input border and blinks
occasionally in terminals supporting
Kitty graphics or Sixel. On other terminals the companion is hidden. The companion
hides in windows smaller than 48 columns or 20 rows to leave room for input.
Set `companion` to `false` in configuration to hide her. `--reduce-motion`
keeps the current expression still; `--no-color` and accessible icons hide her.

Click her to get an annoyed reaction. Three clicks close together make her
furious. Angry lasts one second and furious lasts 1.3 seconds after the latest
click, then she returns to her current activity.
Clicks outside the character keep their usual behavior.

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
item to apply it; Escape cancels or closes the menu. The composer retains a draft
when opening ordinary quick-action menus.

Approval prompts are different from ordinary choices. A command approval can
grant host access for the rest of the response, as disclosed by the prompt.
Manual mode continues to ask before changes and commands under host access.
File-change prompts offer **allow edits for this session**; choosing it does not
approve commands. Other prompts offer **yes, and don't ask again for this tool**,
which approves later calls of that tool for the rest of the session, in the main
agent and its subagents, until `/clear` or a session switch. When the tool needed
access outside the sandbox, each remembered call gets the same access a fresh
**yes** would; web tools get no extra host access. Requests for full host access
always ask, so they never offer this choice. Long command labels are abbreviated in the transcript (at most
120 characters, shortened further to fit the terminal), while approval prompts
show the full command.

Drag `/sandbox` and `/usage` by their top border or title row to reposition them.
Answering an ordinary task question does not grant execution access. Read
[modes and permissions](harness.md) for the scope of those decisions.

## Clipboard and display

Selecting input or transcript text does not copy it. Press the platform copy
shortcut - Ctrl+Shift+C on Linux, Ctrl+C on Windows, Cmd+C on macOS - to copy
the selection. This works with mouse selection and keyboard selection in the
input. Right click does not copy.
Each copy shows `copied N characters` in the bottom-right corner for two seconds.

Linux may need `wl-clipboard` or `xclip` for system clipboard copying. Terminal
clipboard integration and host utilities affect whether the copy reaches your
desktop clipboard. `/theme`, `--no-color`, and `--reduce-motion` control display;
see [appearance](appearance.md).

### Over SSH

When Eirene runs on a server you reach with SSH, the server's clipboard and
browser are the wrong ones, so Eirene never uses `xclip`, `wl-copy` or a browser
there, and it leaves the mouse to your terminal: drag to select, copy with your
terminal's own shortcut (usually Ctrl+Shift+C), and Ctrl+click links, exactly as
in any other program. Copies land on the computer you are typing on, whatever
terminal you use. PageUp and PageDown scroll the transcript. Press F4 to give
the mouse back to Eirene (clicking tool blocks, dragging to select and copying
with Eirene's shortcut, which then uses an OSC 52 escape sequence); press it
again to return. The `mouse` setting chooses the start-up mode.

A full-screen program draws a long link as separate rows, so terminals that
detect links by their text only recognize its first row. Clicking a link in
Eirene, and every sign-in link over SSH, therefore prints the complete link on
the normal terminal screen, where it wraps as one link you can select or
Ctrl+click; press Enter to return to Eirene. Terminals that support OSC 8
hyperlinks also open the whole link from any of its rows inside Eirene.

Signing in to ChatGPT from a server:

- `chatgpt-subscription` preselects device-code sign-in: open the URL on any
  device and enter the code.
- `chatgpt-plan` shows the sign-in link in full. After you sign in, your
  browser tries to return to `http://127.0.0.1:PORT/...` on your own computer
  and shows an error page; copy that page's full address and paste it into
  Eirene, which verifies it and finishes. Alternatively, connect with
  `ssh -L PORT:127.0.0.1:PORT server` using the port Eirene shows, and the
  redirect reaches Eirene by itself.

## Displayed history versus active model context

The transcript can replay the original event log after compaction, while the
model sees the replacement summary and retained recent messages. Expanding a tool
block changes its presentation; it does not automatically resend all artifact
bytes to the model. Request a bounded output read when those details matter.

Output artifacts, session logs, and live process records have separate identities.
The [session schema](sessions.md#event-log-format) and [data layout](data-layout.md)
explain which state survives restart. Theme/notification/suggestion choices are
saved in [config.json](config-file.md), whereas an unfinished composer draft or
live native CLI thread is not a project snapshot.
