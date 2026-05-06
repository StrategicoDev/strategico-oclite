from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


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
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def run(self, model: str, instructions: str, message: str) -> str:
        ref = parse_model_ref(model)
        if ref.provider in ("openai", "openai-codex"):
            return self._openai_response(ref, instructions, message)
        if ref.provider == "mock":
            return message
        raise ProviderError(f"Unsupported provider '{ref.provider}' for model '{model}'")

    def _openai_response(self, ref: ModelRef, instructions: str, message: str) -> str:
        provider_config = self._provider_config(ref.provider)
        api_key = provider_config.get("apiKey") or os.environ.get(provider_config.get("apiKeyEnv", "OPENAI_API_KEY"))
        if not api_key:
            raise ProviderError(
                f"Missing API key for '{ref.provider}'. Set {provider_config.get('apiKeyEnv', 'OPENAI_API_KEY')} "
                "or configure a provider API key in OCLite."
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
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
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

    def _provider_config(self, provider: str) -> dict[str, Any]:
        providers = self.config.get("providers", {})
        return providers.get(provider) or providers.get("openai") or {}

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

