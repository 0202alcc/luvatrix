"""LLM providers for the llm_backend example app.

Providers:
- EchoProvider: offline, deterministic, echoes the question back. Default
  fallback so the app works with zero configuration.
- OpenAICompatProvider: POSTs to an OpenAI-compatible /chat/completions
  endpoint (Zhipu GLM, OpenRouter, Ollama, ...).

resolve_provider(env) picks a provider from environment variables:
- LUVATRIX_LLM_PROVIDER: "echo" | "openai-compat" (default: auto)
- LUVATRIX_LLM_BASE_URL: e.g. https://open.bigmodel.cn/api/paas/v4 (GLM),
  https://openrouter.ai/api/v1, http://127.0.0.1:11434/v1 (Ollama)
- LUVATRIX_LLM_API_KEY: bearer token (optional for local endpoints)
- LUVATRIX_LLM_MODEL: default "glm-4.5-flash"
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping

DEFAULT_MODEL = "glm-4.5-flash"
PROVIDER_ECHO = "echo"
PROVIDER_OPENAI_COMPAT = "openai-compat"


class LLMProviderError(RuntimeError):
    """Raised for provider configuration or request failures."""


@dataclass(frozen=True)
class LLMAnswer:
    answer: str
    model: str
    elapsed_ms: int


def _require_question(question: str) -> str:
    q = (question or "").strip()
    if not q:
        raise ValueError("question must not be empty")
    return q


class EchoProvider:
    """Deterministic offline provider used when no endpoint is configured."""

    name = PROVIDER_ECHO
    model = "echo-deterministic"

    def __init__(self, warnings: tuple[str, ...] = ()) -> None:
        self.warnings = warnings

    def ask(self, question: str, context: str | None = None, timeout_s: float = 60.0) -> LLMAnswer:
        del timeout_s
        q = _require_question(question)
        start = time.perf_counter()
        lines = [
            "Echo provider (offline fallback — no LLM endpoint configured).",
            f"Question: {q}",
        ]
        if context and context.strip():
            lines.append(f"Context: {context.strip()}")
        lines.append("Set LUVATRIX_LLM_BASE_URL (+ LUVATRIX_LLM_API_KEY) for real answers.")
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        return LLMAnswer(answer="\n".join(lines), model=self.model, elapsed_ms=elapsed_ms)


class OpenAICompatProvider:
    """OpenAI-compatible chat.completions client (stdlib urllib only)."""

    name = PROVIDER_OPENAI_COMPAT

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model: str,
        warnings: tuple[str, ...] = (),
    ) -> None:
        base = (base_url or "").strip().rstrip("/")
        if not base:
            raise LLMProviderError("openai-compat provider requires a base_url")
        self.base_url = base
        self.api_key = api_key
        self.model = model
        self.warnings = warnings

    def ask(self, question: str, context: str | None = None, timeout_s: float = 60.0) -> LLMAnswer:
        q = _require_question(question)
        messages: list[dict[str, str]] = []
        if context and context.strip():
            messages.append(
                {
                    "role": "system",
                    "content": "Answer using this canvas context:\n" + context.strip(),
                }
            )
        messages.append({"role": "user", "content": q})
        payload = {"model": self.model, "messages": messages, "stream": False}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            raise LLMProviderError(f"LLM endpoint returned HTTP {exc.code}: {body}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMProviderError(f"LLM request failed: {exc}") from exc
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMProviderError(f"malformed chat.completion response: {data!r:.200}") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError(f"empty completion content: {data!r:.200}")
        return LLMAnswer(answer=content.strip(), model=self.model, elapsed_ms=elapsed_ms)


def _env(env: Mapping[str, str], name: str) -> str:
    return (env.get(name) or "").strip()


def _missing_key_warnings(api_key: str | None) -> tuple[str, ...]:
    if api_key:
        return ()
    return ("LUVATRIX_LLM_API_KEY not set; authenticated endpoints will fail",)


def resolve_provider(env: Mapping[str, str]):
    """Pick a provider from environment; blank values count as unset."""
    provider_name = _env(env, "LUVATRIX_LLM_PROVIDER").lower()
    base_url = _env(env, "LUVATRIX_LLM_BASE_URL")
    api_key = _env(env, "LUVATRIX_LLM_API_KEY") or None
    model = _env(env, "LUVATRIX_LLM_MODEL") or DEFAULT_MODEL

    if provider_name == PROVIDER_ECHO:
        return EchoProvider()
    if provider_name == PROVIDER_OPENAI_COMPAT:
        if not base_url:
            raise LLMProviderError(
                "LUVATRIX_LLM_PROVIDER=openai-compat requires LUVATRIX_LLM_BASE_URL"
            )
        return OpenAICompatProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            warnings=_missing_key_warnings(api_key),
        )
    if provider_name:
        raise LLMProviderError(
            f"unknown LUVATRIX_LLM_PROVIDER={provider_name!r} "
            "(expected 'echo' or 'openai-compat')"
        )
    if base_url:
        return OpenAICompatProvider(
            base_url=base_url,
            api_key=api_key,
            model=model,
            warnings=_missing_key_warnings(api_key),
        )
    return EchoProvider(
        warnings=("no LLM endpoint configured; using the offline echo provider",)
    )
