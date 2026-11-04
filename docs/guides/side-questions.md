# Side questions

[Documentation](../README.md) / Guides / Side questions

Use `/btw` for a quick question you want answered without adding it to the conversation:

```text
/btw What does chmod 755 mean?
/btw Why would this query need an index?
```

The answer opens in a panel, and work in the main conversation can continue meanwhile. Close the panel with Escape.

## What the model can see

The model receives a bounded snapshot of the session from when you asked: your requests, the saved plan and its step statuses,
any compaction handoff, recent tool results, pending tool calls, queued input and any reply being streamed.

It has no tools, so it cannot open a file, edit code or run a command, even if your question names a path. For anything that
needs investigating, or an answer you want kept, ask in the main conversation. The side answer is not saved, so if it leads to a
decision, tell the main agent.

## What to keep in mind

- A provider must already be connected.
- Each question is an additional model request with up to 2,048 output tokens, and it may not appear in `/usage`.
- The question and recent session context go to your model service like any other request.
- Asking another side question cancels the previous one.
