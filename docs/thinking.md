# Local model thinking

[Documentation](README.md) / Local model thinking

`/think` controls the thinking option sent to the local Ollama connection. It is
available only when `ollama-local` is selected; it is not a universal reasoning
control for every provider.

```text
/connect ollama-local
/think think
/think nothink
```

`/think` with no argument toggles the current value. `on` and `off` are also
accepted. The local default is thinking enabled, and the choice is saved with that
provider's settings.

The selected Ollama model must support the option for it to have the intended
effect. Thinking can change latency and resource use; it does not guarantee
correctness, enlarge context, or enable tool calling in an unsupported model.

The live status may display reasoning activity separately from the saved answer.
For selecting models and diagnosing local service issues, see
[providers](providers.md) and [troubleshooting](troubleshooting.md).
