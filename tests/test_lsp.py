"""Real stdio framing with a deterministic fake language server."""

from __future__ import annotations

import sys
import shutil
from pathlib import Path

import pytest

from eirene.core.errors import ToolError
from eirene.tools import lsp


SERVER = '''
import json, sys
def send(body):
    payload = json.dumps(body).encode()
    sys.stdout.buffer.write(('Content-Length: %d\\r\\n\\r\\n' % len(payload)).encode() + payload)
    sys.stdout.buffer.flush()
uri = ''
while True:
    header = sys.stdin.buffer.readline()
    if not header: break
    length = int(header.split(b':')[1])
    while sys.stdin.buffer.readline().strip(): pass
    body = json.loads(sys.stdin.buffer.read(length))
    method = body.get('method')
    if method == 'initialize':
        result = {'capabilities': {'definitionProvider': True, 'referencesProvider': True, 'hoverProvider': True}}
    elif method == 'textDocument/didOpen':
        uri = body['params']['textDocument']['uri']
        send({'jsonrpc': '2.0', 'method': 'textDocument/publishDiagnostics', 'params': {'uri': uri, 'diagnostics': [
            {'range': {'start': {'line': 0, 'character': 0}}, 'severity': 2, 'message': 'sample diagnostic'}]}})
        continue
    elif method == 'textDocument/hover':
        result = {'contents': {'kind': 'markdown', 'value': 'function value() -> int'}}
    elif method in ('textDocument/definition', 'textDocument/references'):
        result = [{'uri': uri, 'range': {'start': {'line': 0, 'character': 4}}}]
    else: continue
    send({'jsonrpc': '2.0', 'id': body['id'], 'result': result})
'''


@pytest.mark.parametrize("action,expected", [
    ("definition", "main.py:1:5"), ("references", "main.py:1:5"),
    ("hover", "function value()"), ("diagnostics", "sample diagnostic"),
])
async def test_stdio_server(box, workdir, action, expected):
    (workdir / "main.py").write_text("def value(): return 1\n")
    result = await lsp.query(box, "main.py", action, line=1, column=5,
        definitions={"python": {"command": [sys.executable, "-u", "-c", SERVER]}},
        read_only=False)
    assert expected in result
    assert result.startswith("LSP ")


def test_utf16_position_conversion():
    assert lsp._position("a😀foo", 1, 3) == {"line": 0, "character": 3}
    with pytest.raises(ToolError, match="outside"):
        lsp._position("abc", 2, 1)


def test_external_locations_filtered(box, workdir, outside):
    result = [{"uri": (outside / "secret.txt").as_uri(), "range": {"start": {"line": 0, "character": 0}}}]
    assert "secret" not in lsp._locations(result, box, 100)


def test_location_links_and_limits(box, workdir):
    result = [{"targetUri": (workdir / "main.py").as_uri(),
               "targetSelectionRange": {"start": {"line": i, "character": 0}}} for i in range(3)]
    body = lsp._locations(result, box, 1)
    assert body.startswith("main.py:1:1")
    assert "Partial result" in body


async def test_no_server_fallback_is_labeled(box, workdir):
    (workdir / "main.py").write_text("def value(): return 1\n")
    result = await lsp.query(box, "main.py", "definition", column=5, definitions={"python": False})
    assert "lexical fallback" in result
    assert "main.py" in result


async def test_unisolated_read_only_server_rejected(box, workdir):
    (workdir / "main.py").write_text("value = 1\n")
    with pytest.raises(ToolError, match="needs a sandbox"):
        await lsp.query(box, "main.py", "hover", definitions={"python": {"command": [sys.executable]}})


async def test_server_timeout(box, workdir):
    (workdir / "main.py").write_text("value = 1\n")
    with pytest.raises(ToolError, match="TimeoutError"):
        await lsp.query(box, "main.py", "hover", timeout=1, read_only=False,
            definitions={"python": {"command": [sys.executable, "-c", "import time; time.sleep(30)"]}})


async def test_oversize_protocol_frame(box, workdir):
    (workdir / "main.py").write_text("value = 1\n")
    code = "import sys,time; sys.stdout.buffer.write(b'Content-Length: 999999999\\r\\n\\r\\n'); sys.stdout.flush(); time.sleep(30)"
    with pytest.raises(ToolError, match="message length"):
        await lsp.query(box, "main.py", "hover", timeout=2, read_only=False,
            definitions={"python": {"command": [sys.executable, "-c", code]}})


def test_invalid_server_config():
    with pytest.raises(ToolError, match="argv"):
        lsp.server_for(Path("main.py"), {"python": {"command": "pylsp --stdio"}})


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bwrap"), reason="Linux Bubblewrap integration")
async def test_server_cannot_write_workspace(box, workdir):
    (workdir / "main.py").write_text("def value(): return 1\n")
    write_probe = '''
from pathlib import Path
try:
    Path('forbidden.txt').write_text('unsafe')
except OSError:
    pass
else:
    raise RuntimeError('workspace was writable')
'''
    executable = str(Path(sys.executable).resolve())
    result = await lsp.query(box, "main.py", "hover", isolation="bubblewrap",
        definitions={"python": {"command": [executable, "-u", "-c", write_probe + SERVER],
                                "read_paths": [str(Path(executable).parent.parent)]}})
    assert "function value()" in result
    assert not (workdir / "forbidden.txt").exists()
