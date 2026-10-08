"""OmniRoute gateway with live provider/combination discovery."""

from __future__ import annotations

from .openai_compat import OpenAICompatible
from urllib.parse import urlparse


class OmniRoute(OpenAICompatible):
    def __init__(self, api_key, base_url, *, timeout=300.0):
        # A static fallback would make /connect succeed with a stopped gateway.
        super().__init__(api_key, base_url, name="omniroute", timeout=timeout)
        self.trust_env = urlparse(base_url).hostname not in {"localhost", "127.0.0.1", "::1"}

    async def models(self) -> list[str]:
        names = await super().models()
        # Virtual routing IDs are usable even when omitted from /v1/models.
        return list(dict.fromkeys(["auto/coding", "auto", *names]))
