# Prompt suggestions

[Documentation](../README.md) / Guides / Prompt suggestions

After a response, the model can draft a likely next request for you. This is off by default.

```text
/prompt-suggest on
/prompt-suggest off
```

`/prompt-suggest` on its own opens a menu that also shows the current status or any failure. Ctrl+P toggles the setting, and your
choice is saved.

## Use a suggestion

A suggestion appears as muted text in the empty composer. Press Tab or the Right arrow to copy it into the composer, edit it if you
like, and press Enter to send. Typing your own text replaces it. A suggestion never runs by itself and is not part of the transcript
until you send it.

## What it costs

Each suggestion is an additional model request, up to 1,024 output tokens, using the start of your last request (4,000 characters) and
the end of the reply (8,000 characters). It has no tools and cannot edit files. It uses tokens or plan allowance even if you never
send the draft.

Suggestions may arrive some time after the response. Eirene waits up to 120 seconds, and discards a suggestion if the session or your
input has moved on. It also rejects drafts that were cut off, run longer than 240 characters or 30 words, or read like a reply from the
assistant, so you may not see one every time.
