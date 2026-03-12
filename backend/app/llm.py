from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.models import LiteLLMConfig


@dataclass
class LiteLLMError(RuntimeError):
    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


CompletionFn = Callable[..., Awaitable[Any]]


class LiteLLMAdapter:
    def __init__(self, completion_fn: CompletionFn | None = None) -> None:
        if completion_fn is not None:
            self._completion = completion_fn
            return

        try:
            from litellm import acompletion  # type: ignore
        except Exception as exc:  # pragma: no cover - import guard
            raise LiteLLMError(code="missing_dependency", message="litellm is not installed") from exc
        self._completion = acompletion

    async def complete_json(
        self,
        *,
        config: LiteLLMConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "response_format": {"type": "json_object"},
        }

        if config.api_base:
            kwargs["api_base"] = config.api_base

        if config.api_key:
            kwargs["api_key"] = config.api_key
        elif config.api_key_env:
            api_key = os.getenv(config.api_key_env)
            if api_key:
                kwargs["api_key"] = api_key

        if config.extra_headers:
            kwargs["extra_headers"] = dict(config.extra_headers)

        if config.extra_body:
            kwargs.update(config.extra_body)

        try:
            response = await self._completion(**kwargs)
        except Exception as exc:
            raise self._normalize_error(exc) from exc

        content = self._extract_content(response)
        if content is None:
            raise LiteLLMError(code="empty_response", message="Model returned empty content")

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            repaired = self._extract_json_block(content)
            if repaired is None:
                raise LiteLLMError(code="invalid_json", message="Model response is not valid JSON")
            try:
                return json.loads(repaired)
            except json.JSONDecodeError as exc:
                raise LiteLLMError(code="invalid_json", message=f"Unable to parse JSON block: {exc}") from exc

    @staticmethod
    def _extract_content(response: Any) -> str | None:
        if isinstance(response, dict):
            choices = response.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        content = message.get("content")
                        if isinstance(content, str):
                            return content
            return None

        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or not choices:
            return None
        first = choices[0]
        message = getattr(first, "message", None)
        if message is None and isinstance(first, dict):
            message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            return content if isinstance(content, str) else None
        content = getattr(message, "content", None)
        return content if isinstance(content, str) else None

    @staticmethod
    def _extract_json_block(text: str) -> str | None:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        return match.group(0)

    @staticmethod
    def _normalize_error(exc: Exception) -> LiteLLMError:
        raw = str(exc)
        lowered = raw.lower()

        if "auth" in lowered or "api key" in lowered:
            code = "authentication_error"
        elif "rate" in lowered or "429" in lowered:
            code = "rate_limit"
        elif "timeout" in lowered:
            code = "timeout"
        elif "context" in lowered or "token" in lowered:
            code = "context_limit"
        else:
            code = "provider_error"

        return LiteLLMError(code=code, message=raw)
