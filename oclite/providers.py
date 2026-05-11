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
    alias: str = ""


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
        ref = self._resolve_model_ref(model)
        provider_config = self._provider_config(ref)
        if ref.provider == "mock":
            return message
        if self._can_use_openai_compatible(ref, provider_config):
            return self._openai_response(ref, instructions, message)
        raise ProviderError(
            f"Provider '{ref.provider}' is registered as a direct/custom provider but has no runnable adapter yet. "
            "Add an OpenAI-compatible base URL or route it through a supported adapter before assigning this model to an active agent."
        )

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
        base_url = provider_config.get("baseUrl", "").rstrip("/")
        if not base_url:
            return {
                "ok": False,
                "providerId": provider_id,
                "authType": provider_config.get("authType", "custom"),
                "modelCount": 0,
                "models": [],
                "message": (
                    "This provider is in the valid catalogue, but OCLite does not have a runnable auth/test "
                    "adapter for it yet. It can be exposed for migration/reference, but active agents need a "
                    "supported adapter or an OpenAI-compatible base URL."
                ),
            }
        credential = self._credential(provider_id, provider_config)
        if not credential:
            raise ProviderError(
                f"Missing API key for '{provider_id}'. Set {provider_config.get('apiKeyEnv', 'OPENAI_API_KEY')} "
                "or save an API key/OAuth profile for this provider."
            )
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

    def test_model(self, model: str) -> dict[str, Any]:
        ref = self._resolve_model_ref(model)
        provider_config = self._provider_config(ref)
        if ref.provider == "mock":
            return {
                "ok": True,
                "status": "ready",
                "alias": ref.alias or model,
                "providerId": ref.provider,
                "model": ref.model,
                "message": "Mock provider is ready.",
            }
        profile = self._oauth_profile(ref.provider, provider_config)
        if profile:
            return {
                "ok": True,
                "status": "ready",
                "alias": ref.alias or model,
                "providerId": ref.provider,
                "model": ref.model,
                "authType": "oauth",
                "message": f"OAuth profile '{profile.get('profileId', 'default')}' is linked.",
            }
        credential = self._credential(ref.provider, provider_config)
        if not credential:
            return {
                "ok": False,
                "status": "needs auth",
                "alias": ref.alias or model,
                "providerId": ref.provider,
                "model": ref.model,
                "message": f"Missing API key or OAuth profile for '{ref.provider}'.",
            }
        base_url = provider_config.get("baseUrl", "").rstrip("/")
        if not base_url:
            return {
                "ok": False,
                "status": "adapter pending",
                "alias": ref.alias or model,
                "providerId": ref.provider,
                "model": ref.model,
                "message": "Provider is configured but has no runnable endpoint yet.",
            }
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
            raise ProviderError(f"Model auth failed with HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Model auth network error: {exc.reason}") from exc
        models = [item.get("id") for item in data.get("data", []) if item.get("id")]
        return {
            "ok": True,
            "status": "ready",
            "alias": ref.alias or model,
            "providerId": ref.provider,
            "model": ref.model,
            "authType": "api-key",
            "modelCount": len(models),
            "message": "API key accepted.",
        }

    def diagnostics(self, model: str) -> dict[str, Any]:
        ref = self._resolve_model_ref(model)
        provider_config = self._provider_config(ref)
        profile = self._oauth_profile(ref.provider, provider_config)
        has_api_key = bool(provider_config.get("apiKey") or os.environ.get(provider_config.get("apiKeyEnv", "OPENAI_API_KEY")))
        auth_type = "oauth" if profile else "api-key" if has_api_key else "missing"
        if ref.provider == "openai-codex" and profile:
            endpoint = f"{provider_config.get('codexBaseUrl', 'https://chatgpt.com/backend-api/codex').rstrip('/')}/responses"
        elif not provider_config.get("baseUrl"):
            endpoint = "direct/custom provider - no runnable endpoint configured"
        else:
            endpoint = f"{provider_config.get('baseUrl', 'https://api.openai.com/v1').rstrip('/')}/responses"
        return {
            "provider": ref.provider,
            "model": ref.model,
            "alias": ref.alias,
            "authType": auth_type,
            "profileId": provider_config.get("profileId", "default"),
            "oauthProfileFound": bool(profile),
            "apiKeyConfigured": has_api_key,
            "endpoint": endpoint,
        }

    def _openai_response(self, ref: ModelRef, instructions: str, message: str) -> str:
        provider_config = self._provider_config(ref)
        if ref.provider == "openai-codex" and self._oauth_profile(ref.provider, provider_config):
            return self._codex_oauth_response(ref, provider_config, instructions, message)
        credential = self._credential(ref.provider, provider_config)
        if ref.provider == "openai-codex" and not credential and provider_config.get("authType") != "api-key":
            raise ProviderError(
                "openai-codex is configured without an OAuth profile. "
                "Use Providers -> Start OAuth, then save provider openai-codex with profile id 'default'."
            )
        if not credential:
            raise ProviderError(
                f"Missing API key for '{ref.provider}'. Set {provider_config.get('apiKeyEnv', 'OPENAI_API_KEY')} "
                "or configure a provider API key/OAuth profile in OCLite."
            )
        base_url = provider_config.get("baseUrl", "").rstrip("/")
        if not base_url:
            raise ProviderError(f"Provider '{ref.provider}' has no base URL configured")
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
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": message,
                        }
                    ],
                }
            ],
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

    def _resolve_model_ref(self, model: str) -> ModelRef:
        aliases = self.config.get("models", {}).get("aliases", {})
        alias = aliases.get(model)
        if alias:
            return ModelRef(
                provider=alias.get("providerId", "openai"),
                model=alias.get("model", model),
                alias=model,
            )
        return parse_model_ref(model)

    def _provider_config(self, ref: ModelRef | str) -> dict[str, Any]:
        provider = ref.provider if isinstance(ref, ModelRef) else ref
        providers = self.config.get("providers", {})
        provider_config = dict(providers.get(provider) or {})
        if isinstance(ref, ModelRef) and ref.alias:
            alias = self.config.get("models", {}).get("aliases", {}).get(ref.alias, {})
            if alias.get("authType"):
                provider_config["authType"] = alias["authType"]
            if alias.get("apiKeyEnv"):
                provider_config["apiKeyEnv"] = alias["apiKeyEnv"]
            if alias.get("profileId"):
                provider_config["profileId"] = alias["profileId"]
        return provider_config

    def _can_use_openai_compatible(self, ref: ModelRef, provider_config: dict[str, Any]) -> bool:
        if ref.provider in ("openai", "openai-codex"):
            return True
        return provider_config.get("adapter") == "openai-compatible" and bool(provider_config.get("baseUrl"))

    def _credential(self, provider: str, provider_config: dict[str, Any]) -> str | None:
        profile = self._oauth_profile(provider, provider_config)
        if profile:
            return profile.get("access")
        return provider_config.get("apiKey") or os.environ.get(provider_config.get("apiKeyEnv", "OPENAI_API_KEY"))

    def _oauth_profile(self, provider: str, provider_config: dict[str, Any]) -> dict[str, Any] | None:
        if provider_config.get("authType") == "api-key":
            return None
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
        status = getattr(response, "status", 200)
        if not raw.strip():
            raise ProviderError(f"Provider returned empty response body with HTTP {status} and content-type '{content_type}'")
        stripped = raw.lstrip()
        is_stream = (
            "text/event-stream" in content_type
            or stripped.startswith("data:")
            or stripped.startswith("event:")
        )
        if not is_stream:
            try:
                return self._extract_text(json.loads(raw))
            except json.JSONDecodeError as exc:
                preview = raw[:500].replace("\n", "\\n")
                raise ProviderError(
                    f"Provider returned non-JSON response with HTTP {status}, content-type '{content_type}': {preview}"
                ) from exc
        return self._extract_stream_text(raw)

    def _extract_stream_text(self, raw: str) -> str:
        deltas: list[str] = []
        final_items: list[str] = []
        completed: dict[str, Any] | None = None
        event_name = ""
        for line in raw.splitlines():
            line = line.strip()
            if line.startswith("event:"):
                event_name = line[6:].strip()
                continue
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            event_type = event.get("type") or event_name
            if event_type in (
                "response.output_text.delta",
                "response.refusal.delta",
                "response.output_text_annotation.added",
            ):
                if event.get("delta"):
                    deltas.append(event["delta"])
                elif event.get("text"):
                    deltas.append(event["text"])
            elif event_type == "response.output_item.done":
                final_items.extend(self._extract_texts_from_item(event.get("item")))
            elif event_type == "response.content_part.done":
                final_items.extend(self._extract_texts_from_item({"content": [event.get("part", {})]}))
            elif event_type == "response.output_item.added":
                final_items.extend(self._extract_texts_from_item(event.get("item")))
            elif event_type == "response.completed" and isinstance(event.get("response"), dict):
                completed = event["response"]
        if deltas:
            return self._dedupe_repeated_text("".join(deltas).strip())
        if final_items:
            return self._dedupe_repeated_text("\n".join(self._unique_texts(final_items)).strip())
        if completed:
            return self._extract_text(completed)
        raise ProviderError("Provider returned no streamed text output")

    def _extract_texts_from_item(self, item: Any) -> list[str]:
        if not isinstance(item, dict):
            return []
        texts: list[str] = []
        for content in item.get("content", []):
            if content.get("text"):
                texts.append(content["text"])
        return texts

    def _unique_texts(self, texts: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for text in texts:
            cleaned = text.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                unique.append(cleaned)
        return unique

    def _dedupe_repeated_text(self, text: str) -> str:
        for parts in range(2, 5):
            if len(text) % parts:
                continue
            chunk = text[: len(text) // parts]
            if chunk and chunk * parts == text:
                return chunk.strip()
        return text
