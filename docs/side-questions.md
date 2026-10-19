# Side questions

[Documentation](README.md) / Side questions

Use `/btw` for a small question you want answered without changing the saved
conversation. It opens a side panel and gives the model session context without
adding the question or answer to the session.

```text
/btw What does chmod 755 mean?
/btw Why would this query need an index?
```

A provider must already be connected. The side request has no workspace tools,
so it cannot inspect a new file, edit code, or execute a command. Ask a normal
main-conversation question when you need investigation or want the answer retained
for later work.

Side questions are additional model requests and can consume provider tokens or
subscription allowance. They are not a private channel from your provider: recent
session context and the question are sent to the selected model service.

Close the panel with Escape. If a decision from the answer should guide the main
task, state it in the main conversation; the side answer is not saved there.

## Request construction

The side request uses a bounded tail of complete message exchanges plus a bounded
session snapshot: user requests, the saved plan and its step statuses, compaction
handoff, recent tool results, outstanding tool calls, queued input, and any reply
currently streaming. This keeps the task visible when many tool calls push it out
of the recent history. The snapshot reflects when the question started; work may
continue while the side answer streams. It is partial context, not a fresh
verification of the workspace or a guarantee that recorded plan statuses are current.

The request has no tools and a 2048-token requested output allowance. Where
supported, the provider's isolated stream keeps the request separate from its main
native thread. Only text deltas populate the panel. Asking another side question
cancels the previous side request so their answers cannot mix in the panel.

It does not load a new filesystem observation merely because the question names
a path. Main-turn usage totals may not include this auxiliary request, and it is
not written as a normal session message. Provider credentials and connection
selection still use [the same config lookup](config-file.md#provider-selection-and-credentials).
