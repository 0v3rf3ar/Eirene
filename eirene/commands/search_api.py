"""/search-api: configure the optional search fallback without exposing keys."""

from __future__ import annotations

from copy import deepcopy

from ..core.errors import CommandError, EireneError, ToolError
from ..tools import search
from . import register


@register("search-api", "configure a search API", "/search-api")
async def run(app, args: str) -> None:
    if args:
        # Keys belong only in the secret input, never in slash-command history.
        raise CommandError("run /search-api without arguments, then enter the key in the hidden prompt")
    entry = app.config.get("search_api", {})
    configured = isinstance(entry, dict) and entry.get("provider") == "tavily"
    provider = await app.ask_choice("search API", [
        ("tavily", "Tavily API", "configured" if configured else "optional web search"),
    ], selected="tavily" if configured else "")
    if provider != "tavily":
        return
    if configured:
        action = await app.ask_choice("Tavily API", [
            ("keep", "keep saved key", ""),
            ("replace", "replace key", "enter a new key"),
            ("remove", "remove key", "use normal search only"),
        ])
        if action is None or action == "keep":
            return
        if action == "remove":
            old = deepcopy(entry)
            # Persist removal before deleting the OS credential.
            app.config.set("search_api", {})
            try:
                app.config.save()
            except (EireneError, OSError):
                app.config.set("search_api", old)
                raise CommandError("could not save search API settings; check the config file") from None
            if old.get("api_key_ref") == "keyring":
                from ..core import credentials
                credentials.delete("search:tavily")
            app.agent.search_service.reset()
            app.say("search API removed")
            return
    for _ in range(3):
        raw = await app.ask_text("Enter your API key", secret=True)
        if raw is None:
            app.say("cancelled")
            return
        try:
            key = search.validate_key(raw)
        except ToolError as exc:
            app.say(str(exc), "warn")
            continue
        app.say("checking Tavily API…")
        try:
            note = await search.check_key(key)
        except search.SearchAPIError as exc:
            app.say(str(exc), "warn")
            if exc.cooldown == float("inf"):
                continue  # Rejected credentials can be corrected without a search charge.
            return
        old = deepcopy(app.config.get("search_api", {}))
        old_key = app.config.search_api_key()
        try:
            app.config.set_search_api(key)
            app.config.save()
        except (EireneError, OSError):
            app.config.set("search_api", old)
            if app.config.get("credential_store") == "keyring":
                from ..core import credentials
                try:
                    if old.get("api_key_ref") == "keyring" and old_key:
                        credentials.set("search:tavily", old_key)
                    else:
                        credentials.delete("search:tavily")
                except EireneError:
                    app.say("could not restore the saved credential; run /search-api to replace it", "warn")
            raise CommandError("could not save search API settings; check the config and credential store") from None
        if old.get("api_key_ref") == "keyring" and app.config.get("credential_store") != "keyring":
            from ..core import credentials
            credentials.delete("search:tavily")
        app.agent.search_service.reset()
        app.say(f"Tavily API configured ({note})")
        return
    app.say("key was not saved; run /search-api to try again", "warn")
