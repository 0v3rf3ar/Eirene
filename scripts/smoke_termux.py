#!/usr/bin/env python3
"""Exercise Android-native imports, shell selection and approved tool execution."""
import asyncio
import tempfile
from pathlib import Path

import cryptography.hazmat.bindings._rust
import pydantic_core
import rpds
import PIL.Image
import mcp
import textual

from eirene.core.platforms import Host, is_termux
from eirene.tools import native, shell, processes
from eirene.tools.sandbox import Sandbox


async def main():
    assert is_termux(), 'This smoke check must run in Termux'
    host = Host.detect()
    assert host.distribution == 'Termux' and host.package_manager == 'pkg'
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / 'example.txt').write_text('Termux file read works\n')
        result = await shell.run('printf termux-shell-ok', root, execution='foreground')
        assert result.ok and result.output == 'termux-shell-ok', result.summary()
        token = native.POLICY.set({'isolation': 'auto', 'read_only': True})
        try:
            result = await native.command(Sandbox(root), ['cat', str(root / 'example.txt')])
            assert result.ok and 'Termux file read works' in result.output
        finally:
            native.POLICY.reset(token)
    await processes.stop_all()
    print('Termux native imports, host detection, shell execution and file reads passed.')


if __name__ == '__main__':
    asyncio.run(main())
