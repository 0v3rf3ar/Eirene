"""Process-local, event-loop-scoped request limits shared by related agents."""
from __future__ import annotations

import asyncio
import hashlib
import random

from .base import _retry_after

class RequestGate:
    def __init__(self):
        self.slots = asyncio.Semaphore(4)
        self.until = 0.0
        self.spread_until = 0.0
        self.next_admission = 0.0
        self.failures = 0

    async def wait(self):
        loop = asyncio.get_running_loop()
        while True:
            now = loop.time()
            deadline = max(self.until, self.next_admission if now < self.spread_until else 0)
            if deadline > now:
                await asyncio.sleep(deadline - now)
                continue
            if now < self.spread_until:
                # Stagger peers after a cooldown instead of releasing all four
                # waiting requests at exactly the same instant.
                self.next_admission = now + random.uniform(0.05, 0.2)
            return

    def observe(self, response):
        if response.status_code == 429:
            self.failures = min(self.failures + 1, 6)
            delay = _retry_after(response)
            if delay is None:
                delay = min(2 ** (self.failures - 1), 30)
            self.until = max(self.until, asyncio.get_running_loop().time() + delay + random.uniform(0.05, 0.3))
            self.spread_until = self.until + 2
        elif response.status_code < 400:
            self.failures = 0


def gate_for(provider):
    loop = asyncio.get_running_loop()
    # Let the loop own its gates. A global weak-key map can still retain the
    # loop indirectly through a contended semaphore's internal loop reference.
    gates = getattr(loop, '_eirene_provider_gates', None)
    if gates is None:
        gates = loop._eirene_provider_gates = {}
    # Keep credentials out of both logs and the registry's keys.
    identity = hashlib.sha256((provider.api_key or '').encode()).digest()
    key = (provider.name, provider.base_url, identity)
    return gates.setdefault(key, RequestGate())
