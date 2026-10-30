"""/connect"""

from __future__ import annotations

from ..core.subprocesses import external_environment

import asyncio
import subprocess
import sys
import webbrowser

from ..core.errors import AuthError, CommandError, EireneError, ProviderError
from ..providers import registry as providers
from ..ui import art
from . import register


@register("connect", "sign in, add an API key, or switch provider", "/connect [provider]")
async def run(app, args: str) -> None:
    key = await _pick(app, args)
    if not key:
        return
    spec = providers.spec(key)
    if key == "chatgpt-plan":
        await _connect_chatgpt_plan(app, key, spec)
        return
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
            if name.lower() == "ollama":
                return await _pick_ollama(app)
            return key
        except ProviderError as exc:
            raise CommandError(str(exc)) from exc
    options = []
    for key in providers.ORDER:
        if key == "ollama-local":
            continue
        if not providers.available(key):
            continue
        spec = providers.SPECS[key]
        keys = ("ollama", "ollama-local") if key == "ollama" else (key,)
        options.append((key, spec.label, _connection_marks(app, keys)))
    selected = "ollama" if app.config.provider == "ollama-local" else app.config.provider
    chosen = await app.ask_choice("connect to which provider?", options,
                                  selected=selected or "", right_hint=True) or ""
    return await _pick_ollama(app) if chosen == "ollama" else chosen


def _connection_marks(app, keys: tuple[str, ...]) -> str:
    marks = []
    for key in keys:
        spec = providers.spec(key)
        saved = app.config.get("providers", {}).get(key, {})
        if app.config.api_key(key) or (not spec.needs_key and saved.get("model")):
            marks.append("configured")
            break
    if app.config.provider in keys:
        marks.append("active")
    return ", ".join(marks)


async def _pick_ollama(app) -> str:
    selected = app.config.provider if app.config.provider in {"ollama", "ollama-local"} else ""
    if not selected:
        selected = "ollama-local" if app.config.provider_config("ollama-local").get("model") else "ollama"
    return await app.ask_choice("Ollama connection", [
        ("ollama", "Cloud", _connection_marks(app, ("ollama",)) or "Ollama account and API key"),
        ("ollama-local", "Local", _connection_marks(app, ("ollama-local",)) or "running Ollama service"),
    ], selected=selected, right_hint=True) or ""


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
    chosen = await app.ask_choice(f"model for {providers.spec(key).label}", options,
                                  selected=str(saved or "")) or ""
    if chosen and key == "deepseek" and not await _choose_reasoning(app, provider, key, chosen):
        return ""
    return chosen


def _open_browser(url: str) -> bool:
    """Use desktop URL handlers even when Python cannot detect a browser."""
    if sys.platform.startswith("linux"):
        for command in (("xdg-open", url), ("gio", "open", url),
                        ("kde-open", url), ("exo-open", "--launch", "WebBrowser", url)):
            try:
                result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                        timeout=10, check=False, env=external_environment())
                if result.returncode == 0:
                    return True
            except (OSError, subprocess.TimeoutExpired):
                continue
    try:
        return webbrowser.open(url, new=2)
    except (webbrowser.Error, OSError):
        return False


async def _open_sign_in(app, url: str) -> None:
    """Open the host browser independently of provider/model execution."""
    app.say(url, markdown=True)
    from ..ui.terminal import remote_session
    if remote_session():
        # A browser here would open on the server. Show the whole link on the normal
        # terminal screen, where the user's terminal selects or opens it in one piece.
        app.copy_to_clipboard(url)
        app.show_outside(url)
        app.say("Eirene is running over SSH: open the sign-in link in the browser on your computer "
                "(click the link above to show it in full again).")
        return
    opened = await asyncio.to_thread(_open_browser, url)
    if not opened:
        app.say("Could not open your browser automatically; click the URL above or copy it into your browser.", "warn")


async def _choose_reasoning(app, provider, key: str, model: str) -> bool:
    picker = getattr(provider, "reasoning_options", None)
    if picker is None:
        return True
    options = await picker(model)
    saved = app.config.provider_config(key).get("reasoning_efforts", {}).get(model, "default")
    if saved not in {option[0] for option in options}:
        saved = "default"
    effort = await app.ask_choice(f"reasoning level for {model}", options, selected=saved)
    if effort is None:
        app.say("cancelled - no reasoning level chosen")
        return False
    efforts = app.config.provider_config(key).setdefault("reasoning_efforts", {})
    efforts[model] = effort
    provider.reasoning_efforts[model] = effort
    return True


async def _connect_chatgpt_plan(app, key: str, spec) -> None:
    provider = providers.build(key, app.config)
    connected = False
    try:
        accounts = provider.auth.accounts()
        choice = "new"
        if accounts:
            options = [("account:" + account_id, f"{email} ({account_id[-8:]})",
                        "active" if active else "saved ChatGPT account")
                       for account_id, email, active in accounts]
            options += [("new", "sign in to another account", "use OpenAI's browser sign-in"),
                        ("reauth", "sign in again to the active account", "renew plan permission"),
                        ("logout", "sign out of the active account", "clear its saved tokens")]
            selected = next(("account:" + account_id for account_id, _, active in accounts if active), "new")
            choice = await app.ask_choice("ChatGPT account", options, selected=selected)
            if not choice:
                return
        if choice == "logout":
            confirmed = await provider.auth.logout()
            if app.config.provider == key:
                app.config.provider = None
                app.config.model = None
                app._save_config()
                app.agent.use(None, "", "")
                app.refresh_mode_line()
            app.say("signed out of ChatGPT")
            if not confirmed:
                app.say("remote sign-out was not confirmed; disconnect Eirene in ChatGPT Settings", "warn")
            return
        if choice.startswith("account:"):
            await provider.auth.select(choice[len("account:"):])
            if not provider.auth.account().get("refresh_token"):
                choice = "reauth"
        if choice in {"new", "reauth"}:
            account = provider.auth.account() if choice == "reauth" else {}
            url = await provider.auth.login(account.get("client_id", ""))
            app.say("Sign in to ChatGPT in your browser; you can choose Continue with Google.")
            await _open_sign_in(app, url)
            app.say("waiting for ChatGPT sign-in…")
            await _wait_for_chatgpt_plan(app, provider.auth)
        app.say("checking ChatGPT plan access…")
        note = await provider.validate()
        model = await _choose_model(app, provider, key)
        if not model:
            app.say("cancelled - no model chosen")
            return
        if not await _choose_reasoning(app, provider, key, model):
            return
        app.config.set_provider(key, model=model)
        app.config.provider = key
        app.config.model = model
        app._save_config()
        app.agent.use(provider, key, model)
        connected = True
        app.refresh_mode_line()
        email = provider.auth.account().get("email", "")
        identity = f" as {email}" if email else ""
        app.say(f"{art.icon('ok')} connected to {spec.label}{identity} ({note}) using {model}")
        app.say("Eirene runs your tools. Review plan usage and app limits at https://chatgpt.com/settings/usage")
    except EireneError as exc:
        app.say(f"ChatGPT connection failed: {exc.user_message()}", "fail")
    finally:
        if not connected:
            await provider.close()


async def _wait_for_chatgpt_plan(app, auth) -> None:
    """Over SSH the browser's redirect to 127.0.0.1 reaches the user's own computer,
    not this server: accept the address they paste, or a forwarded callback."""
    from ..ui.terminal import remote_session
    if not remote_session():
        await auth.wait_for_login()
        return
    port = auth.callback_port
    app.say("After you sign in, the browser will show an error page at http://127.0.0.1:"
            f"{port}/… - that is expected. Copy that page's full address and paste it here.")
    app.say(f"Alternatively, reconnect with `ssh -L {port}:127.0.0.1:{port} …` before signing in "
            "and the redirect will reach Eirene by itself.", markdown=True)
    login = asyncio.create_task(auth.wait_for_login())
    while True:
        pasted = asyncio.create_task(app.ask_text("paste the http://127.0.0.1 address from your browser"))
        await asyncio.wait({login, pasted}, return_when=asyncio.FIRST_COMPLETED)
        if login.done():
            pasted.cancel()
            await asyncio.gather(pasted, return_exceptions=True)
            await login
            return
        address = pasted.result()
        if not address:
            login.cancel()
            await asyncio.gather(login, return_exceptions=True)
            raise AuthError("ChatGPT sign-in cancelled")
        if auth.accept(address):
            await login
            return
        app.say("that is not this sign-in's address - copy the whole http://127.0.0.1:"
                f"{port}/auth/callback?… address shown after signing in", "warn")


async def _connect_subscription(app, key: str, spec) -> None:
    """Authenticate through Codex without handling ChatGPT credentials."""
    provider = providers.build(key, app.config)
    try:
        account = await provider.account(refresh=True)
        if not account or account.get("type") != "chatgpt":
            from ..ui.terminal import remote_session
            remote = remote_session()
            method = await app.ask_choice("sign in to ChatGPT", [
                ("chatgpt", "browser sign-in", "needs a browser on this machine" if remote
                 else "shows a localhost callback URL"),
                ("chatgptDeviceCode", "device-code sign-in",
                 "works over SSH: open a URL anywhere and enter a short code" if remote
                 else "open a URL and enter a short code"),
            ], selected="chatgptDeviceCode" if remote else "")
            if not method:
                app.say("cancelled")
                await provider.close()
                return
            login = await provider.login(method)
            login_id = str(login.get("loginId") or "")
            if method == "chatgptDeviceCode":
                url = str(login.get("verificationUrl") or "")
                code = str(login.get("userCode") or "")
            else:
                url = str(login.get("authUrl") or "")
            if not login_id or not url:
                raise ProviderError("Codex did not return a sign-in URL")
            await _open_sign_in(app, url)
            if method == "chatgptDeviceCode":
                app.say(f"enter code {code} in your browser")
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
