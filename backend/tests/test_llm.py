from __future__ import annotations

import pytest

from app.llm import LiteLLMAdapter, LiteLLMError
from app.models import LiteLLMConfig


@pytest.mark.asyncio
async def test_litellm_request_shaping() -> None:
    captured: dict = {}

    async def fake_completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"question":"What payload keys are required?"}',
                    }
                }
            ]
        }

    adapter = LiteLLMAdapter(completion_fn=fake_completion)
    config = LiteLLMConfig(
        model="ollama/llama3.1",
        temperature=0.1,
        max_tokens=250,
        api_base="http://localhost:11434",
        extra_headers={"x-test": "1"},
        extra_body={"timeout": 30},
    )

    result = await adapter.complete_json(
        config=config,
        system_prompt="sys",
        user_prompt="usr",
    )

    assert result["question"] == "What payload keys are required?"
    assert captured["model"] == "ollama/llama3.1"
    assert captured["api_base"] == "http://localhost:11434"
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["extra_headers"] == {"x-test": "1"}
    assert captured["timeout"] == 30


@pytest.mark.asyncio
async def test_litellm_error_normalization() -> None:
    async def fake_completion(**kwargs):  # noqa: ARG001
        raise RuntimeError("Invalid API key")

    adapter = LiteLLMAdapter(completion_fn=fake_completion)
    config = LiteLLMConfig(model="openai/gpt-4o-mini")

    with pytest.raises(LiteLLMError) as exc:
        await adapter.complete_json(config=config, system_prompt="sys", user_prompt="usr")

    assert exc.value.code == "authentication_error"


@pytest.mark.asyncio
async def test_litellm_explicit_api_key_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_completion(**kwargs):
        captured.update(kwargs)
        return {
            "choices": [
                {
                    "message": {
                        "content": "{\"ok\": true}",
                    }
                }
            ]
        }

    monkeypatch.setenv("TEST_API_KEY_ENV", "env-key")
    adapter = LiteLLMAdapter(completion_fn=fake_completion)
    config = LiteLLMConfig(
        model="openai/gpt-4o-mini",
        api_key_env="TEST_API_KEY_ENV",
        api_key="explicit-key",
    )

    payload = await adapter.complete_json(config=config, system_prompt="sys", user_prompt="usr")
    assert payload["ok"] is True
    assert captured["api_key"] == "explicit-key"
