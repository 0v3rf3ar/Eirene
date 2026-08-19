"""Portable language diagnostics and reference discovery."""

from __future__ import annotations

import shutil

import pytest

from eirene.core.errors import ToolError
from eirene.tools import language


async def test_python_diagnostics_report_success_and_failure(box, workdir):
    (workdir / "good.py").write_text("answer = 42\n", encoding="utf-8")
    (workdir / "bad.py").write_text("def broken(\n", encoding="utf-8")
    assert "no syntax diagnostics" in await language.diagnostics(box, "good.py")
    assert "SyntaxError" in await language.diagnostics(box, "bad.py")


async def test_json_diagnostics(box, workdir):
    (workdir / "data.json").write_text('{"valid": true}', encoding="utf-8")
    assert "no JSON syntax errors" == await language.diagnostics(box, "data.json")


@pytest.mark.skipif(not shutil.which("rg"), reason="ripgrep unavailable")
def test_reference_search_is_identifier_aware(box, workdir):
    (workdir / "code.py").write_text("value = 1\nprint(value)\nnotvalue = 2\n",
                                     encoding="utf-8")
    result = language.references(box, "value")
    assert result.count("code.py") == 2


def test_reference_search_rejects_expressions(box):
    with pytest.raises(ToolError, match="identifier"):
        language.references(box, "value + other")

