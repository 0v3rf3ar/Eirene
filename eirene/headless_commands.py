"""Noninteractive adapter for the shared slash-command handlers."""

from __future__ import annotations

import asyncio

from . import commands
from .core.errors import CommandError, EireneError
from .providers import registry as providers


class HeadlessApp:
    """Expose command services without mounting the terminal application."""

    def __init__(self, agent, output, provider="", model="", choices=None, inputs=None):
        self.agent, self.output = agent, output
        self.config, self.session, self.sandbox = agent.config, agent.session, agent.sandbox
        self.choices, self.inputs = list(choices or []), list(inputs or [])
        self.turn = None
        self.theme = "textual-dark"
        self.aside = self
        self.status = self
        self.active = False
        self.list_choices = False
        key = provider or self.config.provider
        if key:
            key = providers.resolve_alias(key)
            self.config.provider = key
            chosen = model or self.config.provider_config(key).get("model") or \
                self.config.model or providers.default_model(key)
            self.agent.provider_key, self.agent.model = key, chosen
            self.output.result.update(provider=key, model=chosen or None)

    def ensure_provider(self):
        if self.agent.ready:
            return
        key, model = self.agent.provider_key, self.agent.model
        if not key:
            raise CommandError("no provider configured; run eirene and use /connect")
        if not model:
            raise CommandError(f"no model set for {key}; use --model NAME")
        self.agent.use(providers.build(key, self.config), key, model)

    def say(self, text, level="info"):
        if level in {"warn", "fail"}:
            self.output.error(str(text))
        else:
            self.output.write(str(text) + "\n")

    def show_content(self, body):
        self.say(getattr(body, "plain", str(body)))

    async def push(self, block):
        from .ui.chat import UserBlock
        if not isinstance(block, UserBlock):
            self.show_content(block.content)

    async def ask_choice(self, label, options, **kwargs):
        if self.choices:
            choice = self.choices.pop(0)
            if choice not in {str(option[0]) for option in options}:
                raise CommandError(f"invalid --choice {choice!r} for {label}")
            return choice
        # Listing never selects a default, toggles settings or grants approval.
        self.output.result["data"] = [
            dict(key=row[0], label=row[1], details=list(row[2:])) for row in options
        ]
        self.say(label + "\n" + "\n".join(
            "  " + " — ".join(str(part) for part in row if part) for row in options))
        if not self.list_choices or any(str(row[0]) in {"yes", "replace", "forget"} for row in options):
            raise CommandError("an explicit --choice KEY is required for this action")
        return None

    async def ask_text(self, label, secret=False):
        if secret:
            raise CommandError("configure credentials beforehand; headless commands do not read secrets")
        if not self.inputs:
            raise CommandError(f"{label}: supply --command-input TEXT")
        return self.inputs.pop(0)

    def _save_config(self):
        self.config.save()

    def refresh_mode_line(self):
        self.output.result.update(provider=self.agent.provider_key or None,
                                  model=self.agent.model or None)

    def refresh(self, **kwargs):
        pass

    def stop(self, text=""):
        if text:
            self.say(text)

    async def switch_session(self, session_id, **kwargs):
        raise CommandError("session switching is not available in headless runs")

    async def _run_turn(self, text, *, record_text=None):
        self.ensure_provider()
        self.refresh_mode_line()
        self.session.add_note("headless", prompt=(record_text or text)[:400],
                              provider=self.agent.provider_key, model=self.agent.model)
        async for event in self.agent.run(text, record_text=record_text):
            self.output.event(event)

    async def list_providers(self, configured=False):
        saved = set(self.config.configured_providers())
        rows = []
        for key in providers.ORDER:
            if not providers.available(key) or configured and key not in saved:
                continue
            spec = providers.spec(key)
            rows.append(dict(provider=key, name=spec.label, configured=key in saved,
                             active=key == self.config.provider,
                             model=self.config.provider_config(key).get("model") or None))
        self.output.result["data"] = rows
        for row in rows:
            marks = ", ".join(mark for mark in ("configured" if row["configured"] else "",
                                               "active" if row["active"] else "") if mark)
            self.say(f"{row['provider']} — {row['name']}" + (f" ({marks})" if marks else ""))
        if not rows:
            self.say("no configured providers" if configured else "no available providers")

    async def list_models(self, name=""):
        key = name or self.agent.provider_key
        if not key:
            raise CommandError("specify a provider: /models PROVIDER or --provider NAME")
        key = providers.resolve_alias(key)
        provider = providers.build(key, self.config)
        try:
            names = await provider.models()
        finally:
            close = getattr(provider, "close", None)
            if close:
                await close()
        self.output.result.update(provider=key, data=list(names),
                                  model=self.agent.model if key == self.agent.provider_key else
                                  self.config.provider_config(key).get("model") or None)
        for name in names:
            self.say(name)

    async def connect(self, name):
        if not name:
            await self.list_providers()
            return
        if name.endswith("!"):
            raise CommandError("configure credentials beforehand; use /connect PROVIDER to switch")
        key = providers.resolve_alias(name)
        if not providers.available(key):
            raise CommandError("install the provider plugin first")
        model = self.agent.model if key == self.agent.provider_key else ""
        model = model or self.config.provider_config(key).get("model") or providers.default_model(key)
        if not model:
            raise CommandError(f"no model set for {key}; use --provider {key} --model NAME")
        provider = providers.build(key, self.config)
        try:
            await provider.validate()
        except BaseException:
            close = getattr(provider, "close", None)
            if close:
                await close()
            raise
        self.agent.use(provider, key, model)
        self.config.provider, self.config.model = key, model
        self.config.set_provider(key, model=model)
        self._save_config()
        self.refresh_mode_line()
        self.say(f"using {key} / {model}")

    async def dispatch(self, text):
        parts = text[1:].strip().split(maxsplit=1)
        name, args = (parts[0].lower(), parts[1] if len(parts) > 1 else "") if parts else ("", "")
        self.list_choices = name in {"agents", "permissions", "theme", "skills", "plugins",
                                     "plugin", "mcp", "sessions", "tasks", "search-api"}
        try:
            if name == "providers":
                if args not in {"", "configured"}:
                    raise CommandError("use /providers [configured]")
                await self.list_providers(args == "configured")
            elif name == "models" or name == "model" and not args:
                await self.list_models(args)
            elif name == "connect":
                await self.connect(args)
            elif name == "help":
                self.say("/providers [configured] — list provider connections\n/models [provider] — list models")
                self.say("\n".join(f"{c.usage} — {c.summary}" for c in commands.commands(self)))
            elif name in {"snow", "btw", "clear", "exit", "prompt-suggest", "keybindings"}:
                raise CommandError(f"/{name} is an interactive interface command")
            else:
                if name in {"compact", "think"}:
                    self.ensure_provider()
                await commands.dispatch(self, text)
            if self.turn:
                await self.turn
            if self.choices or self.inputs:
                raise CommandError("unused --choice or --command-input arguments")
        except EireneError as exc:
            self.output.error(exc.user_message())
        finally:
            if self.turn and not self.turn.done():
                self.turn.cancel()
                await asyncio.gather(self.turn, return_exceptions=True)
