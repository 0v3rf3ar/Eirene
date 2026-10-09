"""ChatGPT public-client authorization and Eirene-owned tool execution."""

import asyncio
import base64
import hashlib
import json
import os
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from eirene.core.errors import AuthError, ProviderError
from eirene.core.session import Session
from eirene.core.usage import estimate_messages
from eirene.providers import base, registry
from eirene.providers.chatgpt_auth import ChatGPTAuth, ISSUER, PLAN_SCOPE, RESOURCE, TOKEN
from eirene.providers.chatgpt_plan import ChatGPTPlan, to_responses_input


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


def save_account(auth, *, expired=False):
    record = {"client_id": "oaiapp_test", "subject": "person", "email": "person@example.com",
              "access_token": "access-secret", "refresh_token": "refresh-secret",
              "id_token": "identity-secret", "scopes": [PLAN_SCOPE, "resource.invoke"],
              "expires_at": time.time() + (-1 if expired else 3600)}
    auth._save({"host_id": "urn:uuid:test", "active": record["client_id"],
                "accounts": {record["client_id"]: record}})
    return record


def token_response(**overrides):
    return {"access_token": "new-access", "refresh_token": "new-refresh", "token_type": "Bearer",
            "expires_in": 3600, "scope": PLAN_SCOPE + " resource.invoke", **overrides}


async def callback(url, **values):
    redirect = parse_qs(urlsplit(url).query)["redirect_uri"][0]
    parsed = urlsplit(redirect)
    reader, writer = await asyncio.open_connection(parsed.hostname, parsed.port)
    writer.write(f"GET {parsed.path}?{urlencode(values)} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
    await writer.drain()
    response = await reader.read()
    writer.close()
    await writer.wait_closed()
    return response


async def test_pkce_callback_verification_and_secure_save(monkeypatch):
    auth = ChatGPTAuth()
    url = await auth.login()
    params = parse_qs(urlsplit(url).query)
    assert params["client_id"] == ["dynamic_agent_client"]
    assert params["agent_name_hint"] == ["Eirene"]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(auth._pending["verifier"].encode()).digest()).decode().rstrip("=")
    assert params["code_challenge"] == [challenge]
    assert b"400" in await callback(url, state="forged", code="ignored")
    assert not auth._pending["future"].done()
    seen = {}
    async def exchange(form):
        seen.update(form)
        return token_response(id_token="signed-token")
    async def identity(token, client_id, nonce):
        assert token == "signed-token" and nonce == params["nonce"][0]
        assert client_id == "oaiapp_new"
        return {"sub": "person", "email": "person@example.com"}
    monkeypatch.setattr(auth, "_token", exchange)
    monkeypatch.setattr(auth, "_identity", identity)
    assert b"200" in await callback(url, state=params["state"][0], code="code", client_id="oaiapp_new")
    record = await auth.wait_for_login()
    assert seen["redirect_uri"] == params["redirect_uri"][0]
    assert seen["resource"] == RESOURCE
    assert record["email"] == "person@example.com"
    assert auth._server is None
    if os.name != "nt":
        assert auth.path.stat().st_mode & 0o777 == 0o600
        assert auth.path.parent.stat().st_mode & 0o777 == 0o700
    host_id = auth._read()["host_id"]
    url = await auth.login("oaiapp_new")
    params = parse_qs(urlsplit(url).query)
    assert params["ext_agent_host_id"] == [host_id]
    assert params["client_id"] == ["oaiapp_new"]
    assert "agent_name_hint" not in params and "id_token_hint" not in params
    await auth.close()


@pytest.mark.parametrize("values", [{"error": "access_denied"}, {"code": "code"},
                                  {"code": "code", "client_id": "dynamic_agent_client"}])
async def test_declined_or_incomplete_registration_does_not_save(values):
    auth = ChatGPTAuth()
    url = await auth.login()
    state = parse_qs(urlsplit(url).query)["state"][0]
    await callback(url, state=state, **values)
    with pytest.raises(AuthError):
        await auth.wait_for_login()
    assert not auth.accounts()
    assert auth._server is None


async def test_timeout_closes_listener():
    auth = ChatGPTAuth()
    await auth.login()
    with pytest.raises(AuthError, match="timed out"):
        await auth.wait_for_login(timeout=.01)
    assert auth._server is None and auth._pending is None


@pytest.mark.parametrize("change", [{"nonce": "wrong"}, {"aud": "wrong"}, {"iss": "wrong"},
                                  {"exp": 1}, {"sub": ""}, {"nonce": None}])
async def test_signed_identity_rejects_invalid_claims(change):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test"
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json={"keys": [jwk]})))
    claims = {"sub": "person", "aud": "oaiapp_test", "iss": ISSUER, "nonce": "nonce",
              "iat": int(time.time()), "exp": int(time.time()) + 300, **change}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
    with pytest.raises(AuthError):
        await ChatGPTAuth()._identity(token, "oaiapp_test", "nonce")


async def test_signed_identity_valid_and_forged_signature():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk["kid"] = "test"
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json={"keys": [jwk]})))
    claims = {"sub": "person", "aud": "oaiapp_test", "iss": ISSUER, "nonce": "nonce",
              "iat": int(time.time()), "exp": int(time.time()) + 300}
    token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test"})
    assert (await ChatGPTAuth()._identity(token, "oaiapp_test", "nonce"))["sub"] == "person"
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(claims, other, algorithm="RS256", headers={"kid": "test"})
    with pytest.raises(AuthError):
        await ChatGPTAuth()._identity(forged, "oaiapp_test", "nonce")


async def test_refresh_is_serialized_and_rotates_all_tokens():
    auth = ChatGPTAuth()
    save_account(auth, expired=True)
    requests = []
    async def exchange(req):
        requests.append(req)
        await asyncio.sleep(.02)
        assert parse_qs(req.content.decode())["client_id"] == ["oaiapp_test"]
        return httpx.Response(200, json=token_response())
    base.set_transport(httpx.MockTransport(exchange))
    tokens = await asyncio.gather(auth.access_token(), ChatGPTAuth().access_token())
    assert tokens == ["new-access", "new-access"] and len(requests) == 1
    assert auth.account()["refresh_token"] == "new-refresh"
    assert auth.account()["id_token"] == "identity-secret"


async def test_refresh_rejection_keeps_saved_record_and_redacts_error():
    auth = ChatGPTAuth()
    before = save_account(auth, expired=True)
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(400, json={"error": "refresh-secret"})))
    with pytest.raises(AuthError) as error:
        await auth.access_token()
    assert "refresh-secret" not in str(error.value)
    assert auth.account() == before


def test_plan_permission_is_required():
    with pytest.raises(AuthError, match="not authorized"):
        ChatGPTAuth()._record(token_response(scope="openid email"), {})


async def test_logout_clears_tokens_and_preserves_registration():
    auth = ChatGPTAuth()
    save_account(auth)
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json={"revocation_endpoint": ISSUER + "/revoke"})
        assert parse_qs(req.content.decode())["token"] == ["refresh-secret"]
        return httpx.Response(200)
    base.set_transport(httpx.MockTransport(handler))
    assert await auth.logout()
    assert auth.account()["client_id"] == "oaiapp_test"
    assert "refresh_token" not in auth.account()
    assert auth._read()["host_id"] == "urn:uuid:test"


def sse(*events):
    return "".join("data: " + json.dumps(event) + "\n\n" for event in events)


TOOLS = [{"name": "read_file", "description": "Read a file", "parameters": {
    "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}]


async def test_responses_tool_round_trip_and_session_resume(workdir):
    provider = ChatGPTPlan()
    save_account(provider.auth)
    output = [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
              {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_file",
               "namespace": "eirene", "arguments": '{"path":"a.py"}', "status": "completed"}]
    requests = []
    def handler(req):
        requests.append(req)
        assert req.headers["Authorization"] == "Bearer access-secret"
        if req.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"slug": "model-b", "visibility": "list"},
                {"slug": "hidden", "visibility": "hide"}, {"slug": "model-a", "visibility": "list"}]})
        body = json.loads(req.content)
        assert body["store"] is False and body["stream"] is True
        assert "max_output_tokens" not in body and "max_tokens" not in body
        assert body["tools"][0]["type"] == "namespace"
        assert body["tools"][0]["name"] == "eirene"
        return httpx.Response(200, text=sse(
            {"type": "response.reasoning_summary_text.delta", "delta": "Looking"},
            {"type": "response.completed", "response": {"status": "completed", "output": output,
                "usage": {"input_tokens": 25, "output_tokens": 12}}}))
    base.set_transport(httpx.MockTransport(handler))
    assert await provider.models() == ["model-b", "model-a"]
    session = Session.create(workdir)
    session.add_user("read a.py")
    events = [e async for e in provider.stream(session.messages, "model-b", system="rules", tools=TOOLS)]
    call = next(e for e in events if isinstance(e, base.ToolCall))
    assert call.name == "read_file" and call.arguments == {"path": "a.py"}
    assert events[-1].reason == "tool_use"
    session.add_assistant("", [{"id": call.id, "name": call.name, "arguments": call.arguments}],
                          response_items=events[-1].response_items)
    session.add_tool_result(call.id, call.name, "file contents")
    session.close()
    resumed = Session.resume(session.id)
    inputs = to_responses_input(resumed.messages)
    assert inputs[1:3] == output
    assert inputs[3] == {"type": "function_call_output", "call_id": "call_1", "output": "file contents"}
    assert estimate_messages(resumed.messages) >= len(str(output)) // 4
    resumed.close()


@pytest.mark.parametrize("end", [None, {"type": "response.failed"},
                                {"type": "response.incomplete"}])
async def test_partial_response_never_yields_executable_tools(end):
    provider = ChatGPTPlan()
    save_account(provider.auth)
    events = [{"type": "response.output_item.done", "item": {"type": "function_call",
        "name": "read_file", "call_id": "call_1", "arguments": '{"path":"x"}'}}]
    if end:
        events.append(end)
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, text=sse(*events))))
    received = []
    with pytest.raises(ProviderError):
        async for event in provider.stream([], "test", tools=TOOLS):
            received.append(event)
    assert not any(isinstance(e, base.ToolCall) for e in received)


def test_images_developer_messages_and_registry(config):
    inputs = to_responses_input([{"role": "system", "content": "rules"},
        {"role": "user", "content": "look", "attachments": [{"mime_type": "image/png", "data": "abc"}]}])
    assert inputs[0]["role"] == "developer"
    assert inputs[1]["content"][1] == {"type": "input_image", "image_url": "data:image/png;base64,abc"}
    provider = registry.build("chatgpt-plan", config)
    assert provider.supports_tools and not provider.owns_context
    assert registry.resolve_alias("codex") == "chatgpt-subscription"


async def test_agent_executes_own_tools_and_sends_results(workdir, config, box):
    from eirene.core.agent import Agent, Answer, Failed, ToolFinished
    from eirene.core.modes import Mode
    (workdir / "a.py").write_text("print('eirene owns execution')\n")
    provider = ChatGPTPlan()
    save_account(provider.auth)
    calls = []
    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        # Title generation is a separate inference call without tools.
        if not body.get("tools"):
            return httpx.Response(200, text=sse(
                {"type": "response.output_text.delta", "delta": "Read file"},
                {"type": "response.completed", "response": {"status": "completed", "output": []}}))
        results = [item for item in body["input"] if item.get("type") == "function_call_output"]
        if not results:
            output = [{"type": "reasoning", "id": "rs_1", "summary": [], "encrypted_content": "opaque"},
                      {"type": "function_call", "call_id": "c1", "name": "read_file", "namespace": "eirene",
                       "arguments": '{"path":"a.py"}', "status": "completed"}]
            return httpx.Response(200, text=sse(
                *[{"type": "response.output_item.done", "output_index": index, "item": item}
                  for index, item in enumerate(output)],
                {"type": "response.completed", "response": {"status": "completed", "output": []}}))
        assert "eirene owns execution" in results[0]["output"]
        assert any(item.get("encrypted_content") == "opaque" for item in body["input"])
        return httpx.Response(200, text=sse(
            {"type": "response.output_text.delta", "delta": "Read successfully"},
            {"type": "response.output_item.done", "output_index": 0, "item": {
                "type": "message", "role": "assistant", "content": [
                    {"type": "output_text", "text": "Read successfully", "annotations": []}]}},
            {"type": "response.completed", "response": {"status": "completed", "output": []}}))
    base.set_transport(httpx.MockTransport(handler))
    session = Session.create(workdir)
    runner = Agent(session, config, box)
    runner.mode = Mode.AUTO
    runner.use(provider, "chatgpt-plan", "test-model")
    try:
        events = [event async for event in runner.run("Read a.py")]
        assert not any(isinstance(event, Failed) for event in events)
        assert any(isinstance(event, ToolFinished) and event.name == "read_file" for event in events)
        assert "Read successfully" == "".join(event.text for event in events if isinstance(event, Answer))
        assert len([body for body in calls if body.get("tools")]) == 2
    finally:
        await runner.close()
        session.close()


async def test_connect_saved_account_and_logout(config):
    from types import SimpleNamespace
    from eirene.commands.connect import run
    auth = ChatGPTAuth()
    save_account(auth)
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json={"models": [
        {"slug": "test-model", "visibility": "list"}]})))
    messages = []
    selected = []
    async def choice(title, options, **kwargs):
        return options[0][0]
    app = SimpleNamespace(config=config, say=lambda *args: messages.append(args), ask_choice=choice,
        _save_config=config.save, refresh_mode_line=lambda: None,
        agent=SimpleNamespace(use=lambda *args: selected.append(args)))
    await run(app, "chatgpt-plan")
    assert config.provider == "chatgpt-plan" and config.model == "test-model"
    assert isinstance(selected[-1][0], ChatGPTPlan)
    assert not selected[-1][0].owns_context
    async def logout_choice(*args, **kwargs):
        return "logout"
    app.ask_choice = logout_choice
    await run(app, "chatgpt-plan")
    assert config.provider is None and selected[-1][0] is None
    assert "refresh_token" not in auth.account()
    assert any("remote sign-out was not confirmed" in str(message) for message in messages)


@pytest.mark.parametrize("result", [True, False, OSError("browser unavailable")])
async def test_sign_in_opens_browser_and_keeps_clickable_fallback(monkeypatch, result):
    from types import SimpleNamespace
    from eirene.commands.connect import _open_sign_in
    from eirene.ui.chat import NoticeBlock
    url = ISSUER + "/api/accounts/authorize?state=" + "x" * 800
    opened, notices = [], []
    def open_browser(target, **kwargs):
        opened.append((target, kwargs))
        if isinstance(result, Exception):
            raise result
        return result
    monkeypatch.setattr("eirene.commands.connect.webbrowser.open", open_browser)
    app = SimpleNamespace(say=lambda text, kind="info", **kwargs: notices.append((text, kind, kwargs)))
    await _open_sign_in(app, url)
    assert opened == [(url, {"new": 2})]
    message, _, options = notices[0]
    assert message == f"[Sign in to ChatGPT]({url})" and options == {"markdown": True}
    block = NoticeBlock(message, markdown=True)
    body = block.content
    assert "Sign in to ChatGPT" in body.plain and "https://" not in body.plain
    assert any(span.style.meta.get("@click") == f"open_link({url!r})" for span in body.spans
               if hasattr(span.style, "meta"))
    assert len(notices) == (1 if result is True else 2)


async def test_sign_in_fallback_click_opens_full_url():
    from textual.app import App
    from eirene.ui.chat import NoticeBlock
    url = ISSUER + "/api/accounts/authorize?state=" + "x" * 800
    opened = []
    class LinkApp(App):
        def compose(self):
            yield NoticeBlock(f"[Sign in to ChatGPT]({url})", markdown=True)
        def open_url(self, target, **kwargs):
            opened.append(target)
    async with LinkApp().run_test(size=(50, 10)) as pilot:
        await pilot.click(NoticeBlock, offset=(8, 0))
        await pilot.pause()
    assert opened == [url]


@pytest.mark.parametrize("final_output", [{}, {"output": []}, {"output": None}])
@pytest.mark.parametrize("with_deltas", [False, True])
async def test_sparse_completion_recovers_text_once(final_output, with_deltas):
    provider = ChatGPTPlan()
    save_account(provider.auth)
    message = {"type": "message", "role": "assistant", "status": "completed", "content": [
        {"type": "output_text", "text": "Recovered answer", "annotations": []}]}
    events = []
    if with_deltas:
        events += [{"type": "response.output_text.delta", "output_index": 0, "content_index": 0,
                    "delta": "Recovered "}]
    events += [{"type": "response.output_text.done", "output_index": 0, "content_index": 0,
                "text": "Recovered answer"},
               {"type": "response.output_item.done", "output_index": 0, "item": message},
               {"type": "response.completed", "response": {"status": "completed", **final_output}}]
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, text=sse(*events))))
    result = [e async for e in provider.stream([], "test")]
    assert "".join(e.text for e in result if isinstance(e, base.TextDelta)) == "Recovered answer"
    assert result[-1].response_items == [message]


async def test_final_refusal_without_deltas_is_visible():
    provider = ChatGPTPlan()
    save_account(provider.auth)
    output = [{"type": "message", "role": "assistant", "content": [
        {"type": "refusal", "refusal": "I cannot help with that request."}]}]
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, text=sse(
        {"type": "response.completed", "response": {"status": "completed", "output": output}}))))
    result = [e async for e in provider.stream([], "test")]
    assert "".join(e.text for e in result if isinstance(e, base.TextDelta)) == "I cannot help with that request."


@pytest.mark.parametrize("output", [[], [{"type": "reasoning", "summary": [], "encrypted_content": "opaque"}]])
async def test_empty_answer_is_an_error_not_success(output):
    provider = ChatGPTPlan()
    save_account(provider.auth)
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, text=sse(
        {"type": "response.completed", "response": {"status": "completed", "output": output}}))))
    with pytest.raises(ProviderError, match="no answer or tool calls"):
        _ = [e async for e in provider.stream([], "test")]


async def test_reasoning_catalog_picker_and_wire_payload(config):
    from types import SimpleNamespace
    from eirene.commands.connect import _choose_reasoning
    catalog = {"models": [{"slug": "test", "visibility": "list", "default_reasoning_level": "medium",
                           "supported_reasoning_levels": [
                               {"effort": "low", "description": "Fast"},
                               {"effort": "high", "description": "Thorough"}]}]}
    captured = []
    def handler(req):
        if req.method == "GET":
            return httpx.Response(200, json=catalog)
        captured.append(json.loads(req.content))
        return httpx.Response(200, text=sse({"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.completed", "response": {"status": "completed", "output": []}}))
    base.set_transport(httpx.MockTransport(handler))
    provider = registry.build("chatgpt-plan", config)
    save_account(provider.auth)
    async def choose(title, options, **kwargs):
        assert title == "reasoning level for test"
        assert [option[0] for option in options] == ["default", "low", "high"]
        assert kwargs["selected"] == "default"
        return "high"
    app = SimpleNamespace(config=config, ask_choice=choose, say=lambda *args: None)
    assert await _choose_reasoning(app, provider, "chatgpt-plan", "test")
    assert config.provider_config("chatgpt-plan")["reasoning_efforts"] == {"test": "high"}
    rebuilt = registry.build("chatgpt-plan", config)
    _ = [e async for e in rebuilt.stream([], "test")]
    assert captured[-1]["reasoning"] == {"effort": "high"}
    _ = [e async for e in rebuilt.stream([], "different-model")]
    assert "reasoning" not in captured[-1]


async def test_model_command_asks_reasoning_and_cancellation_preserves_selection(config):
    from types import SimpleNamespace
    from eirene.commands.model import run
    config.provider = "chatgpt-plan"
    config.model = "old-model"
    base.set_transport(httpx.MockTransport(lambda req: httpx.Response(200, json={"models": [
        {"slug": "new-model", "visibility": "list", "supported_reasoning_levels": [{"effort": "high"}]}]})))
    save_account(ChatGPTAuth())
    used = []
    async def cancel(*args, **kwargs):
        return None
    app = SimpleNamespace(config=config, ask_choice=cancel, say=lambda *args: None,
                          _save_config=config.save, refresh_mode_line=lambda: None,
                          agent=SimpleNamespace(use=lambda *args: used.append(args)))
    await run(app, "new-model")
    assert config.model == "old-model" and not used
    async def choose(*args, **kwargs):
        return "high"
    app.ask_choice = choose
    await run(app, "new-model")
    assert config.model == "new-model" and used[-1][0].reasoning_efforts == {"new-model": "high"}


def test_previous_empty_response_items_do_not_discard_visible_history():
    inputs = to_responses_input([{"role": "assistant", "content": "earlier answer", "response_items": []}])
    assert inputs[0]["content"][0]["text"] == "earlier answer"
