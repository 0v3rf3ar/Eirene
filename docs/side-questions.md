# Side questions

[Documentation](README.md) / Side questions

Use `/btw` for a small question you want answered without changing the saved
conversation. It opens a side panel and gives the model recent conversation
context without adding the question or answer to the session.

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
conversation context and the question are sent to the selected model service.

Close the panel with Escape. If a decision from the answer should guide the main
task, state it in the main conversation; the side answer is not saved there.
