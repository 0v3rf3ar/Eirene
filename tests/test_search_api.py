"""Search routing, credit budgets, source retrieval and secret setup."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from eirene.commands import search_api
from eirene.core.config import Config
from eirene.core.errors import CommandError, ConfigError, ToolError
from eirene.tools import browser, registry, search

KEY = "tvly-test-valid-key"
PAGE = "A useful source about Python benchmarks and performance. " * 30


@pytest.fixture
def service(config, monkeypatch):
    monkeypatch.setattr(browser, "search", AsyncMock(side_effect=ToolError("CAPTCHA")))
    monkeypatch.setattr(browser, "fetch_text", AsyncMock(side_effect=ToolError("blocked")))
    config.set_search_api(KEY)
    return search.SearchService(config)


def result(url="https://example.com/article", *, score=0.8, raw=PAGE):
    return {"url": url, "title": "Example", "content": "Relevant snippet",
            "score": score, "raw_content": raw}


@pytest.mark.parametrize("key", ["", "bad-key", "tvly-short", "tvly-abc defghijk",
                                 "tvly-abc\nabcdefgh", "tvly-" + "a" * 600,
                                 "tvly-abcdefgh\x1b", "tvly-abcdefgh🙂"])
def test_key_validation_never_echoes_invalid_secrets(key):
    with pytest.raises(ToolError) as caught:
        search.validate_key(key)
    if key:
        assert key not in str(caught.value)


def test_key_validation_trims_edges():
    assert search.validate_key("  " + KEY + "\n") == KEY


async def test_working_normal_search_never_calls_api(service, monkeypatch):
    browser.search.return_value = "Normal search results"
    browser.search.side_effect = None
    api = AsyncMock(side_effect=AssertionError("Paid API must not be called"))
    monkeypatch.setattr(search, "_api", api)
    assert await service.search("Python") == "Normal search results"
    api.assert_not_awaited()


async def test_no_config_never_calls_api(service, monkeypatch):
    service.config.forget_search_api()
    api = AsyncMock(side_effect=AssertionError("No key"))
    monkeypatch.setattr(search, "_api", api)
    with pytest.raises(ToolError, match="/search-api"):
        await service.search("Python")
    api.assert_not_awaited()


async def test_one_credit_payload_and_cached_concurrent_search(service, monkeypatch):
    api = AsyncMock(return_value={"results": [result()]})
    monkeypatch.setattr(search, "_api", api)
    a, b = await asyncio.gather(service.search("Python"), service.search("Python"))
    assert a == b and PAGE[:100] in a
    assert "https://example.com/article" in a
    assert len(a) <= search.MAX_OUTPUT
    assert api.await_count == 1
    payload = api.call_args.args[2]
    assert payload["search_depth"] == "basic"
    assert payload["auto_parameters"] is False
    assert payload["include_answer"] is False
    assert payload["include_raw_content"] == "text"
    browser.fetch_text.assert_not_awaited()
    assert await service.fetch("https://example.com/article") == PAGE.strip()
    browser.fetch_text.assert_not_awaited()


async def test_ranked_pages_iterate_after_failure_without_another_search(service, monkeypatch):
    api = AsyncMock(return_value={"results": [
        result("https://low.example/article", score=0.1, raw=""),
        result("https://best.example/article", score=0.99, raw=""),
        result("https://next.example/article", score=0.9, raw=""),
        result("https://third.example/article", score=0.8, raw=""),
        result("https://unused.example/article", score=0.7, raw=""),
    ]})
    monkeypatch.setattr(search, "_api", api)
    browser.fetch_text.side_effect = [ToolError("blocked"), PAGE, PAGE]
    output = await service.search("Python")
    assert [call.args[0] for call in browser.fetch_text.call_args_list] == [
        "https://best.example/article", "https://next.example/article", "https://third.example/article"]
    assert api.await_count == 1
    assert "Fetched page text" in output


async def test_all_pages_fail_preserves_snippets_and_bounds_attempts(service, monkeypatch):
    monkeypatch.setattr(search, "_api", AsyncMock(return_value={"results": [
        result(f"https://example.com/{i}", raw="") for i in range(8)]}))
    output = await service.search("Python", limit=8)
    assert "Relevant snippet" in output and "only the search snippets" in output
    assert browser.fetch_text.await_count == 4


async def test_malformed_duplicate_private_urls_do_not_get_fetched(service, monkeypatch):
    monkeypatch.setattr(search, "_api", AsyncMock(return_value={"results": [
        None, {}, result("http://127.0.0.1"), result("file:///etc/passwd"),
        result("https://example.com\n/"), result(), result(),
        result("https://nan.example", score=float("nan")),
    ]}))
    output = await service.search("Python")
    assert "127.0.0.1" not in output and "file:///" not in output
    assert output.count("1. Example") == 1
    browser.fetch_text.assert_not_awaited()


@pytest.mark.parametrize("data", [{}, {"results": None}, {"results": [None, {}]}])
async def test_malformed_api_results_are_handled(service, monkeypatch, data):
    monkeypatch.setattr(search, "_api", AsyncMock(return_value=data))
    with pytest.raises(ToolError, match="Search API"):
        await service.search("Python")


async def test_empty_results_are_cached_without_fetching(service, monkeypatch):
    api = AsyncMock(return_value={"results": []})
    monkeypatch.setattr(search, "_api", api)
    assert "No results" in await service.search("Python")
    assert "No results" in await service.search("Python")
    assert api.await_count == 1
    browser.fetch_text.assert_not_awaited()


async def test_quota_pause_still_allows_normal_search(service, monkeypatch):
    api = AsyncMock(side_effect=search.SearchAPIError("credit limit reached", 3600))
    monkeypatch.setattr(search, "_api", api)
    for query in ["Python", "Java"]:
        with pytest.raises(ToolError, match="credit limit"):
            await service.search(query)
    assert api.await_count == 1
    assert browser.search.await_count == 2
    browser.search.side_effect = None
    browser.search.return_value = "Working normal results"
    assert await service.search("Rust") == "Working normal results"
    assert api.await_count == 1


async def test_replacing_key_resets_authentication_pause(service, monkeypatch):
    api = AsyncMock(side_effect=[search.SearchAPIError("rejected", float("inf")),
                                {"results": [result()]}])
    monkeypatch.setattr(search, "_api", api)
    with pytest.raises(ToolError):
        await service.search("Python")
    service.config.set_search_api("tvly-another-valid-key")
    assert "Search results" in await service.search("Java")
    assert api.await_count == 2


async def test_failures_are_cached_and_expire(service, monkeypatch):
    clock = [1000]
    monkeypatch.setattr(search.time, "monotonic", lambda: clock[0])
    service.config.forget_search_api()
    for _ in range(2):
        with pytest.raises(ToolError):
            await service.search("Python")
    assert browser.search.await_count == 1
    clock[0] += 31
    with pytest.raises(ToolError):
        await service.search("Python")
    assert browser.search.await_count == 2


async def test_bad_queries_spend_nothing(service):
    for query in ["", "a" * 1501]:
        with pytest.raises(ToolError):
            await service.search(query)
    browser.search.assert_not_awaited()


async def test_isolation_prevents_search_service_access(service, box):
    with pytest.raises(ToolError, match="isolate_network"):
        await registry.execute("web_search", {"query": "Python"}, box,
                               search_service=service, isolate_network=True)
    browser.search.assert_not_awaited()


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(
        **kw, transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("status, message", [
    (400, "rejected the request"), (401, "key was rejected"), (403, "key was rejected"),
    (402, "limit reached"), (422, "rejected the request"), (429, "rate limited"),
    (432, "limit reached"), (433, "limit reached"), (500, "temporarily unavailable"),
    (302, "temporarily unavailable"),
])
async def test_api_http_errors_never_expose_response_secrets(monkeypatch, status, message):
    mock_http(monkeypatch, lambda request: httpx.Response(
        status, text=KEY, headers={"Retry-After": "120"}))
    with pytest.raises(search.SearchAPIError, match=message) as caught:
        await search._api(KEY, "/search", {"query": "Python"})
    assert KEY not in str(caught.value)
    if status == 429:
        assert caught.value.cooldown == 120


@pytest.mark.parametrize("body", ["not json", "[]", '{"error":"secret"}'])
async def test_api_invalid_json(monkeypatch, body):
    mock_http(monkeypatch, lambda request: httpx.Response(200, text=body))
    with pytest.raises(search.SearchAPIError):
        await search._api(KEY, "/search", {"query": "Python"})


async def test_timeout_never_exposes_key_or_retries(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout(KEY, request=request)
    mock_http(monkeypatch, handler)
    with pytest.raises(search.SearchAPIError) as caught:
        await search._api(KEY, "/search", {"query": "Python"})
    assert KEY not in str(caught.value) and len(calls) == 1


async def test_key_check_uses_usage_not_search(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"key": {"usage": 5, "limit": 1000}})
    mock_http(monkeypatch, handler)
    assert await search.check_key(KEY) == "key verified"
    assert len(calls) == 1
    assert calls[0].method == "GET" and calls[0].url.path == "/usage"
    assert calls[0].headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in str(calls[0].url)


@pytest.mark.parametrize("value", ["nan", "inf", "invalid", "-10", "120"])
def test_retry_after_is_bounded(value):
    assert 1 <= search._retry_after(value) <= 86400


def test_excerpt_finds_relevant_passages_beyond_intro():
    text = "Navigation menu " * 300 + "Python benchmarks show 1234 points. " * 25
    excerpt = search._excerpt(text, "Python benchmarks", 1800)
    assert "1234 points" in excerpt and len(excerpt) <= 1800


def test_search_config_is_separate_from_model_providers(config):
    config.set_search_api(KEY)
    config.save()
    loaded = Config.load()
    assert loaded.search_api_key() == KEY
    assert "tavily" not in loaded.configured_providers()
    loaded.forget_search_api()
    assert loaded.search_api_key() is None


def app_stub(config, *, choices=("tavily",), keys=(KEY,)):
    return SimpleNamespace(config=config,
        agent=SimpleNamespace(search_service=search.SearchService(config)),
        ask_choice=AsyncMock(side_effect=list(choices)),
        ask_text=AsyncMock(side_effect=list(keys)), say=lambda *args: None)


async def test_command_validates_and_saves_key_hidden(config, monkeypatch):
    app = app_stub(config)
    check = AsyncMock(return_value="key verified")
    monkeypatch.setattr(search, "check_key", check)
    await search_api.run(app, "")
    assert Config.load().search_api_key() == KEY
    assert app.ask_text.call_args.kwargs["secret"] is True
    check.assert_awaited_once_with(KEY)


async def test_command_invalid_then_valid_key(config, monkeypatch):
    app = app_stub(config, keys=("wrong", KEY))
    check = AsyncMock(return_value="key verified")
    monkeypatch.setattr(search, "check_key", check)
    await search_api.run(app, "")
    assert app.ask_text.await_count == 2
    check.assert_awaited_once_with(KEY)


async def test_command_bad_auth_preserves_old_key(config, monkeypatch):
    config.set_search_api(KEY)
    app = app_stub(config, choices=("tavily", "replace"), keys=("tvly-new-valid-key", None))
    monkeypatch.setattr(search, "check_key", AsyncMock(side_effect=search.SearchAPIError("rejected", float("inf"))))
    await search_api.run(app, "")
    assert config.search_api_key() == KEY


async def test_command_removes_key(config):
    config.set_search_api(KEY)
    app = app_stub(config, choices=("tavily", "remove"))
    await search_api.run(app, "")
    assert Config.load().search_api_key() is None
    app.ask_text.assert_not_awaited()


async def test_command_save_failure_restores_config(config, monkeypatch):
    config.set_search_api(KEY)
    app = app_stub(config, choices=("tavily", "replace"), keys=("tvly-new-valid-key",))
    monkeypatch.setattr(search, "check_key", AsyncMock(return_value="key verified"))
    monkeypatch.setattr(config, "save", lambda: (_ for _ in ()).throw(ConfigError("disk full")))
    with pytest.raises(CommandError, match="could not save"):
        await search_api.run(app, "")
    assert config.search_api_key() == KEY


async def test_cancelled_setup_preserves_config(config):
    app = app_stub(config, keys=(None,))
    await search_api.run(app, "")
    assert config.search_api_key() is None


async def test_failed_pages_are_cached(service):
    for _ in range(2):
        with pytest.raises(ToolError, match="another result"):
            await service.fetch("https://blocked.example/article")
    assert browser.fetch_text.await_count == 1


async def test_removing_key_save_failure_preserves_key(config, monkeypatch):
    config.set_search_api(KEY)
    app = app_stub(config, choices=("tavily", "remove"))
    monkeypatch.setattr(config, "save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(CommandError, match="could not save"):
        await search_api.run(app, "")
    assert config.search_api_key() == KEY


async def test_cancel_search_propagates_without_spending_again(service, monkeypatch):
    api = AsyncMock(side_effect=asyncio.CancelledError)
    monkeypatch.setattr(search, "_api", api)
    with pytest.raises(asyncio.CancelledError):
        await service.search("Python")
    with pytest.raises(ToolError, match="cancelled"):
        await service.search("Python")
    assert api.await_count == 1


def test_search_keyring_never_persists_secret(config, monkeypatch):
    from eirene.core import credentials

    values = {}
    monkeypatch.setattr(credentials, "set", lambda name, secret: values.update({name: secret}))
    monkeypatch.setattr(credentials, "get", lambda name: values.get(name))
    monkeypatch.setattr(credentials, "delete", lambda name: values.pop(name, None))
    config.set("credential_store", "keyring")
    config.set_search_api(KEY)
    config.save()
    assert KEY not in config.path.read_text()
    assert Config.load().search_api_key() == KEY
    config.forget_search_api()
    assert values == {}


async def test_keyring_failed_save_restores_old_secret(config, monkeypatch):
    from eirene.core import credentials

    values = {}
    monkeypatch.setattr(credentials, "set", lambda name, secret: values.update({name: secret}))
    monkeypatch.setattr(credentials, "get", lambda name: values.get(name))
    monkeypatch.setattr(credentials, "delete", lambda name: values.pop(name, None))
    config.set("credential_store", "keyring")
    config.set_search_api(KEY)
    app = app_stub(config, choices=("tavily", "replace"), keys=("tvly-new-valid-key",))
    monkeypatch.setattr(search, "check_key", AsyncMock(return_value="key verified"))
    monkeypatch.setattr(config, "save", lambda: (_ for _ in ()).throw(ConfigError("disk full")))
    with pytest.raises(CommandError, match="could not save"):
        await search_api.run(app, "")
    assert config.search_api_key() == KEY


def test_inline_key_is_not_kept_in_prompt_history():
    from eirene.ui.composer import Prompt

    prompt = Prompt()
    prompt.remember("/search-api " + KEY)
    assert not prompt.recent


async def test_api_truncated_json_is_handled(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, text="{}" + " " * 2_000_001))
    with pytest.raises(search.SearchAPIError, match="download limit"):
        await search._api(KEY, "/search", {"query": "Python"})


async def test_large_source_output_stays_bounded_with_complete_citations(service, monkeypatch):
    entries = []
    for i in range(8):
        entry = result(f"https://example.com/{i}/" + "a" * 1900,
                       raw=PAGE * 20, score=1 - i * 0.1)
        entry["title"] = "Title " * 100
        entry["content"] = "Snippet " * 300
        entries.append(entry)
    monkeypatch.setattr(search, "_api", AsyncMock(return_value={"results": entries}))
    output = await service.search("Python", limit=8)
    assert len(output) <= search.MAX_OUTPUT
    assert entries[0]["url"] in output


async def test_corrupt_saved_key_is_handled_after_normal_search(service):
    service.config.set("search_api", {"provider": "tavily", "api_key": "wrong"})
    with pytest.raises(ToolError, match="Saved search API key is invalid"):
        await service.search("Python")


async def test_real_no_results_do_not_spend_api_credits(service, monkeypatch):
    browser.search.side_effect = None
    browser.search.return_value = "No results found for: Python"
    api = AsyncMock(side_effect=AssertionError("No API"))
    monkeypatch.setattr(search, "_api", api)
    assert "No results" in await service.search("Python")
    api.assert_not_awaited()
