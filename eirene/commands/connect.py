"""/connect"""

from __future__ import annotations

from ..core.errors import CommandError, EireneError, ProviderError
from ..providers import registry as providers
from ..ui import art
from . import register


@register("connect", "sign in, add an API key, or switch provider", "/connect [provider]")
async def run(app, args: str) -> None:
    key = await _pick(app, args)
    if not key:
        return
    spec = providers.spec(key)
    if key == "chatgpt-subscription":
        await _connect_subscription(app, key, spec)
        return
    if key == "claude-code":
        await _connect_claude_code(app, key, spec)
        return
    stored = app.config.api_key(key)

    if stored and not args.endswith("!"):
        if await _switch(app, key):
            return

    base_url = spec.base_url
    if spec.needs_base_url:
        base_url = await _ask_base_url(app, key, spec)
        if not base_url:
            return

    token = None
    if spec.needs_key:
        token = await _ask_key(app, spec)
        if not token:
            return
    elif spec.optional_key:
        token = await _ask_key(app, spec, optional=True)
        if token is None:
            return

    app.say(f"checking {spec.label}…")
    try:
        provider = providers.build(key, app.config, api_key=token, base_url=base_url)
        note = await provider.validate()
    except EireneError as exc:
        app.say(f"{spec.label} rejected that: {exc.user_message()}", "fail")
        return

    app.config.set_provider(key, api_key=token or "", base_url=base_url or "")
    model = await _choose_model(app, provider, key)
    if not model:
        app.say("cancelled - no model chosen")
        return
    app.config.set_provider(key, model=model)
    app.config.provider = key
    app.config.model = model
    app._save_config()
    app.agent.use(providers.build(key, app.config), key, model)
    app.refresh_mode_line()
    app.say(f"{art.icon('ok')} connected to {spec.label} ({note}) using {model}")
    if spec.note:
        app.say(spec.note, "warn")


async def _pick(app, args: str) -> str:
    name = args.strip().rstrip("!")
    if name:
        try:
            key = providers.resolve_alias(name)
            if not providers.available(key):
                raise CommandError("install the provider plugin first: /plugins install omniroute")
            return key
        except ProviderError as exc:
            raise CommandError(str(exc)) from exc
    options = []
    for key in providers.ORDER:
        if not providers.available(key):
            continue
        spec = providers.SPECS[key]
        marks = []
        if app.config.api_key(key) or not spec.needs_key:
            marks.append("configured")
        if key == app.config.provider:
            marks.append("active")
        options.append((key, spec.label, ", ".join(marks)))
    return await app.ask_choice("connect to which provider?", options,
                                selected=app.config.provider or "") or ""


async def _switch(app, key: str) -> bool:
    """Reuse a stored key, or fall through."""
    spec = providers.spec(key)
    choice = await app.ask_choice(
        f"{spec.label} already has a key",
        [("use", "switch to it", "keep the saved key"),
         ("replace", "replace the key", "enter a new one"),
         ("forget", "forget it", "remove the saved key")])
    if choice is None:
        return True
    if choice == "forget":
        app.config.forget_provider(key)
        if app.config.provider == key:
            app.config.provider = None
        app._save_config()
        app.say(f"forgot the {spec.label} key")
        return True
    if choice == "replace":
        return False
    try:
        provider = providers.build(key, app.config)
    except EireneError as exc:
        app.say(exc.user_message(), "fail")
        return True
    model = await _choose_model(app, provider, key)
    if not model:
        app.say("cancelled - no model chosen")
        return True
    app.config.provider = key
    app.config.model = model
    app.config.set_provider(key, model=model)
    app._save_config()
    app.agent.use(providers.build(key, app.config), key, model)
    app.refresh_mode_line()
    app.say(f"{art.icon('ok')} switched to {spec.label} using {model}")
    return True


async def _ask_key(app, spec, *, optional=False) -> str | None:
    for attempt in range(3):
        label = f"{spec.label} API key"
        if spec.key_hint:
            label += f" ({spec.key_hint})"
        raw = await app.ask_text(label, secret=True)
        if raw is None:
            app.say("cancelled")
            return None
        if optional and not raw.strip():
            return ""
        try:
            return providers.validate_key(spec.key, raw)
        except ProviderError as exc:
            remaining = 2 - attempt
            suffix = f", {remaining} tries left" if remaining else ""
            app.say(f"{exc.user_message()}{suffix}", "warn")
    return None


async def _ask_base_url(app, key: str, spec) -> str:
    default = app.config.base_url(key) or spec.base_url
    for attempt in range(3):
        hint = f"Enter for {default}" if default else "https://host/v1"
        raw = await app.ask_text(f"{spec.label} base URL ({hint})")
        if raw is None:
            app.say("cancelled")
            return ""
        try:
            return providers.validate_base_url(raw or default)
        except ProviderError as exc:
            remaining = 2 - attempt
            suffix = f", {remaining} tries left" if remaining else ""
            app.say(f"{exc.user_message()}{suffix}", "warn")
    return ""


async def _choose_model(app, provider, key: str) -> str:
    try:
        names = await provider.models()
    except EireneError as exc:
        app.say(f"could not list models: {exc.user_message()}", "warn")
        names = providers.spec(key).models
    if not names:
        raise CommandError("no models available for that provider")
    saved = app.config.provider_config(key).get("model")
    options = [(name, name, "saved" if name == saved else "") for name in names]
    return await app.ask_choice(f"model for {providers.spec(key).label}", options,
                                selected=str(saved or "")) or ""


async def _connect_subscription(app, key: str, spec) -> None:
    """Authenticate through Codex without handling ChatGPT credentials."""
    provider = providers.build(key, app.config)
    try:
        account = await provider.account(refresh=True)
        if not account or account.get("type") != "chatgpt":
            method = await app.ask_choice("sign in to ChatGPT", [
                ("chatgpt", "browser sign-in", "shows a localhost callback URL"),
                ("chatgptDeviceCode", "device-code sign-in",
                 "open a URL and enter a short code"),
            ])
            if not method:
                app.say("cancelled")
                await provider.close()
                return
            login = await provider.login(method)
            login_id = str(login.get("loginId") or "")
            if method == "chatgptDeviceCode":
                url = str(login.get("verificationUrl") or "")
                code = str(login.get("userCode") or "")
                app.say(f"open {url} and enter code {code}")
            else:
                url = str(login.get("authUrl") or "")
                app.say(f"open this URL to sign in: {url}")
            if not login_id or not url:
                raise ProviderError("Codex did not return a sign-in URL")
            app.say("waiting for ChatGPT sign-in…")
            account = await provider.wait_for_login(login_id)

        note = await provider.validate()
        model = await _choose_model(app, provider, key)
        if not model:
            app.say("cancelled - no model chosen")
            await provider.close()
            return
    except EireneError as exc:
        app.say(f"{spec.label} connection failed: {exc.user_message()}", "fail")
        await provider.close()
        return

    app.config.set_provider(key, model=model)
    app.config.provider = key
    app.config.model = model
    app._save_config()
    app.agent.use(provider, key, model)
    app.refresh_mode_line()
    email = str(account.get("email") or "").strip()
    identity = f" as {email}" if email else ""
    app.say(f"{art.icon('ok')} connected to {spec.label}{identity} ({note}) using {model}")


async def _connect_claude_code(app, key: str, spec) -> None:
    """Connect to the login securely managed by the Claude Code CLI."""
    provider = providers.build(key, app.config)
    try:
        note = await provider.validate()
        model = await _choose_model(app, provider, key)
        if not model:
            app.say("cancelled - no model chosen")
            await provider.close()
            return
    except EireneError as exc:
        app.say(f"{spec.label} connection failed: {exc.user_message()}", "fail")
        await provider.close()
        return

    app.config.set_provider(key, model=model)
    app.config.provider = key
    app.config.model = model
    app._save_config()
    app.agent.use(provider, key, model)
    app.refresh_mode_line()
    app.say(f"{art.icon('ok')} connected to {spec.label} ({note}) using {model}")
