from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .oauth import AuthStore, OAuthError, refresh_openai_codex_oauth


class ProviderError(RuntimeError):
    pass


@dataclass
class ModelRef:
    provider: str
    model: str


def parse_model_ref(model: str) -> ModelRef:
    if "/" in model:
        provider, model_id = model.split("/", 1)
        return ModelRef(provider=provider, model=model_id)
    if ":" in model:
        provider, model_id = model.split(":", 1)
        return ModelRef(provider=provider, model=model_id)
    return ModelRef(provider="openai", model=model)


class ProviderRunner:
    def __init__(self, config: dict[str, Any], home: Path | None = None):
        self.config = config
        self.home = home

    def run(self, model: str, instructions: str, message: str) -> str:
        ref = parse_model_ref(model)
        if ref.provider in ("openai", "openai-codex"):
            return self._openai_response(ref, instructions, message)
        if ref.provider == "mock":
            return message
        raise ProviderError(f"Unsupported provider '{ref.provider}' for model '{model}'")

    def test_auth(self, provider_id: str) -> dict[str, Any]:
        provider_config = self._provider_config(provider_id)
        profile = self._oauth_profile(provider_id, provider_config)
        if profile:
            return {
                "ok": True,
                "providerId": provider_id,
                "authType": "oauth",
                "modelCount": 0,
                "models": [],
            }
        credential = self._credential(provider_id, provider_config)
        if not credential:
            raise ProviderError(
                f"Missing API key for '{provider_id}'. Set {provider_config.get('apiKeyEnv', 'OPENAI_API_KEY')} "
                "or save an API key/OAuth profile for this provider."
            )
        base_url = provider_config.get("baseUrl", "https://api.openai.com/v1").rstrip("/")
        request = urllib.request.Request(
            f"{base_url}/models",
            headers=self._headers(credential, provider_config),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(provider_config.get("timeoutSeconds", 60))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Provider auth failed with HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Provider auth network error: {exc.reason}") from exc
        models = [item.get("id") for item in data.get("data", []) if item.get("id")]
        return {"ok": True, "providerId": provider_id, "modelCount": len(models), "models": models[:25]}

    def _openai_response(self, ref: ModelRef, instructions: str, message: str) -> str:
        provider_config = self._provider_config(ref.provider)
        if ref.provider == "openai-codex" and self._oauth_profile(ref.provider, provider_config):
            return self._codex_oauth_response(ref, provider_config, instructions, message)
        credential = self._credential(ref.provider, provider_config)
        if not credential:
            raise ProviderError(
                f"Missing API key for '{ref.provider}'. Set {provider_config.get('apiKeyEnv', 'OPENAI_API_KEY')} "
                "or configure a provider API key/OAuth profile in OCLite."
            )
        base_url = provider_config.get("baseUrl", "https://api.openai.com/v1").rstrip("/")
        body = {
            "model": ref.model,
            "instructions": instructions,
            "input": message,
            "max_output_tokens": int(provider_config.get("maxOutputTokens", 1200)),
        }
        request = urllib.request.Request(
            f"{base_url}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(credential, provider_config),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(provider_config.get("timeoutSeconds", 60))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"OpenAI API error {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"OpenAI API network error: {exc.reason}") from exc
        return self._extract_text(data)

    def _codex_oauth_response(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        instructions: str,
        message: str,
    ) -> str:
        credential = self._credential(ref.provider, provider_config)
        if not credential:
            raise ProviderError("Missing OAuth profile for openai-codex")
        base_url = provider_config.get("codexBaseUrl", "https://chatgpt.com/backend-api/codex").rstrip("/")
        body = {
            "model": ref.model,
            "instructions": instructions[:32000],
            "input": message,
            "store": False,
            "stream": True,
        }
        request = urllib.request.Request(
            f"{base_url}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers=self._headers(credential, provider_config),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(provider_config.get("timeoutSeconds", 120))) as response:
                return self._read_response(response)
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"Codex OAuth API error {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Codex OAuth API network error: {exc.reason}") from exc

    def _provider_config(self, provider: str) -> dict[str, Any]:
        providers = self.config.get("providers", {})
        return providers.get(provider) or providers.get("openai") or {}

    def _credential(self, provider: str, provider_config: dict[str, Any]) -> str | None:
        profile = self._oauth_profile(provider, provider_config)
        if profile:
            return profile.get("access")
        return provider_config.get("apiKey") or os.environ.get(provider_config.get("apiKeyEnv", "OPENAI_API_KEY"))

    def _oauth_profile(self, provider: str, provider_config: dict[str, Any]) -> dict[str, Any] | None:
        if provider == "openai-codex" and self.home:
            profile_id = provider_config.get("profileId", "default")
            profile = AuthStore(self.home).get_profile(provider, profile_id)
            if profile:
                if int(profile.get("expires", 0)) <= int(__import__("time").time()):
                    try:
                        profile = refresh_openai_codex_oauth(self.home, profile)
                    except OAuthError as exc:
                        raise ProviderError(str(exc)) from exc
                return profile
        return None

    def _headers(self, api_key: str, provider_config: dict[str, Any]) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider_config.get("organization"):
            headers["OpenAI-Organization"] = provider_config["organization"]
        if provider_config.get("project"):
            headers["OpenAI-Project"] = provider_config["project"]
        return headers

    def _extract_text(self, data: dict[str, Any]) -> str:
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return data["output_text"].strip()
        texts: list[str] = []
        for item in data.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    texts.append(content["text"])
                elif content.get("type") == "refusal" and content.get("refusal"):
                    texts.append(content["refusal"])
        if texts:
            return "\n".join(texts).strip()
        raise ProviderError("Provider returned no text output")

    def _read_response(self, response: Any) -> str:
        content_type = response.headers.get("content-type", "")
        raw = response.read().decode("utf-8", errors="replace")
        if "text/event-stream" not in content_type and not raw.lstrip().startswith("data:"):
            return self._extract_text(json.loads(raw))
        return self._extract_stream_text(raw)

    def _extract_stream_text(self, raw: str) -> str:
        deltas: list[str] = []
        completed: dict[str, Any] | None = None
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type in ("response.output_text.delta", "response.refusal.delta"):
                deltas.append(event.get("delta", ""))
            elif event_type == "response.completed" and isinstance(event.get("response"), dict):
                completed = event["response"]
        if deltas:
            return "".join(deltas).strip()
        if completed:
            return self._extract_text(completed)
        raise ProviderError("Provider returned no streamed text output")
