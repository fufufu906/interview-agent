"""Classify upstream failures without leaking credentials or replaying sent requests."""

import httpx
import pytest

from mianshi_agent.chat import ChatCompletionClient, ChatUnavailable


def make_chat(monkeypatch, handler):
    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        "mianshi_agent.chat.httpx.AsyncClient",
        lambda **kwargs: original(transport=transport, **kwargs),
    )
    return ChatCompletionClient(
        base_url="https://model.example/v1", api_key="private-key", model="test", timeout=1
    )


async def ask(chat):
    return await chat.complete_json(
        system_prompt="Return JSON", messages=[{"role": "user", "content": "test"}], max_tokens=30
    )


async def test_connection_retry_once_then_success(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("private-key", request=request)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})

    assert await ask(make_chat(monkeypatch, handler)) == {"ok": True}
    assert calls == 2


@pytest.mark.parametrize(
    ("failure", "code", "expected_calls"),
    [
        (httpx.ConnectError, "chat_model_connection_failed", 2),
        (httpx.ConnectTimeout, "chat_model_timeout", 2),
        (httpx.ReadTimeout, "chat_model_timeout", 1),
        (httpx.ReadError, "chat_model_connection_failed", 1),
        (httpx.WriteError, "chat_model_connection_failed", 1),
    ],
)
async def test_network_failures_have_bounded_safe_retries(
    monkeypatch, caplog, failure, code, expected_calls
):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise failure("private-key", request=request)

    with pytest.raises(ChatUnavailable, match=code):
        await ask(make_chat(monkeypatch, handler))
    assert calls == expected_calls
    assert "private-key" not in caplog.text


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "chat_model_auth_failed"),
        (403, "chat_model_auth_failed"),
        (429, "chat_model_rate_limited"),
        (503, "chat_model_upstream_unavailable"),
        (400, "chat_model_request_rejected"),
    ],
)
async def test_http_errors_are_classified_without_replay(monkeypatch, caplog, status, code):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, json={"error": {"message": "private-key"}})

    with pytest.raises(ChatUnavailable, match=code):
        await ask(make_chat(monkeypatch, handler))
    assert calls == 1
    assert "private-key" not in caplog.text
