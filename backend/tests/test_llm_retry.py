from __future__ import annotations

import pytest
import requests

from app.services import article_body_native


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", empty_content: bool = False) -> None:
        self.status_code = status_code
        self.text = text
        self.empty_content = empty_content

    def json(self) -> dict:
        if self.empty_content:
            return {"choices": [{"message": {"content": "   "}}], "model": "minimax-m2.7"}
        return {
            "choices": [{"message": {"content": '{"body_markdown": "## 一、正文"}'}}],
            "model": "minimax-m2.7",
        }


def test_llm_call_retries_on_server_error_then_succeeds(monkeypatch) -> None:
    calls: list[int] = []

    def fake_post(*_args, **_kwargs) -> _FakeResponse:
        calls.append(1)
        if len(calls) == 1:
            return _FakeResponse(520, "<html>gateway error</html>")
        return _FakeResponse(200)

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    result = article_body_native._call_openai_compatible("prompt")

    assert result["body_markdown"] == "## 一、正文"
    assert len(calls) == 2


def test_llm_call_raises_after_all_retries_exhausted(monkeypatch) -> None:
    calls: list[int] = []

    def fake_post(*_args, **_kwargs) -> _FakeResponse:
        calls.append(1)
        return _FakeResponse(520, "<html>gateway error</html>")

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    with pytest.raises(article_body_native.NativeArticleGenerationError, match="LLM HTTP 520"):
        article_body_native._call_openai_compatible("prompt")

    assert len(calls) == 5  # default retries=4 -> 5 attempts on the primary model only


def test_llm_call_does_not_retry_on_4xx_auth_error(monkeypatch) -> None:
    calls: list[int] = []

    def fake_post(*_args, **_kwargs) -> _FakeResponse:
        calls.append(1)
        return _FakeResponse(401, '{"error":"unauthorized"}')

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    with pytest.raises(article_body_native.NativeArticleGenerationError, match="LLM HTTP 401"):
        article_body_native._call_openai_compatible("prompt")

    assert len(calls) == 1


def test_llm_call_retries_on_connection_error(monkeypatch) -> None:
    calls: list[int] = []

    def fake_post(*_args, **_kwargs) -> _FakeResponse:
        calls.append(1)
        if len(calls) == 1:
            raise requests.exceptions.ConnectionError("connection reset")
        return _FakeResponse(200)

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    result = article_body_native._call_openai_compatible("prompt")

    assert result["body_markdown"] == "## 一、正文"
    assert len(calls) == 2


def test_llm_call_retries_on_empty_content(monkeypatch) -> None:
    calls: list[int] = []

    def fake_post(*_args, **_kwargs) -> _FakeResponse:
        calls.append(1)
        if len(calls) == 1:
            return _FakeResponse(200, empty_content=True)
        return _FakeResponse(200)

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    result = article_body_native._call_openai_compatible("prompt")

    assert result["body_markdown"] == "## 一、正文"
    assert len(calls) == 2


def test_llm_call_raises_after_all_empty_retries(monkeypatch) -> None:
    calls: list[int] = []

    def fake_post(*_args, **_kwargs) -> _FakeResponse:
        calls.append(1)
        return _FakeResponse(200, empty_content=True)

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    with pytest.raises(article_body_native.NativeArticleGenerationError, match="empty content"):
        article_body_native._call_openai_compatible("prompt")

    assert len(calls) == 5  # default retries=4 -> 5 attempts on the primary model only


def test_llm_call_falls_back_immediately_on_429_quota(monkeypatch) -> None:
    models: list[str] = []

    def fake_post(*_args, **kwargs) -> _FakeResponse:
        model = kwargs["json"]["model"]
        models.append(model)
        if model != "agnes-2.5-flash":
            return _FakeResponse(429, '{"error":{"message":"rate limit exceeded","type":"insufficient_quota"}}')
        return _FakeResponse(200)

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native._fallback_api_key", lambda: "fallback-key")
    monkeypatch.setattr("app.services.article_body_native._model_name", lambda: "agnes-2.0-flash")
    monkeypatch.setattr("app.services.article_body_native._fallback_model_name", lambda: "agnes-2.5-flash")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    result = article_body_native._call_openai_compatible("prompt")

    assert result["body_markdown"] == "## 一、正文"
    assert models == ["agnes-2.0-flash", "agnes-2.5-flash"]


def test_llm_call_falls_back_on_quota_message_without_429(monkeypatch) -> None:
    models: list[str] = []

    def fake_post(*_args, **kwargs) -> _FakeResponse:
        model = kwargs["json"]["model"]
        models.append(model)
        if model == "agnes-2.0-flash":
            return _FakeResponse(403, '{"error":"余额不足 限额已用尽"}')
        return _FakeResponse(200)

    monkeypatch.setattr("app.services.article_body_native._api_key", lambda: "test-key")
    monkeypatch.setattr("app.services.article_body_native._fallback_api_key", lambda: "fallback-key")
    monkeypatch.setattr("app.services.article_body_native._model_name", lambda: "agnes-2.0-flash")
    monkeypatch.setattr("app.services.article_body_native._fallback_model_name", lambda: "agnes-2.5-flash")
    monkeypatch.setattr("app.services.article_body_native.requests.post", fake_post)
    monkeypatch.setattr("app.services.article_body_native.time.sleep", lambda _: None)

    result = article_body_native._call_openai_compatible("prompt")

    assert result["body_markdown"] == "## 一、正文"
    assert models == ["agnes-2.0-flash", "agnes-2.5-flash"]