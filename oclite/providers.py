from __future__ import annotations

import json
import os
import time
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
        if provider == "github-copilot":
            provider = "copilot"
        return ModelRef(provider=provider, model=model_id)
    if ":" in model:
        provider, model_id = model.split(":", 1)
        if provider == "github-copilot":
            provider = "copilot"
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
        if ref.provider == "copilot":
            return self._copilot_response(ref, provider_config, instructions, message)
        if self._can_use_openai_compatible(ref, provider_config):
            return self._openai_response(ref, instructions, message)
        raise ProviderError(
            f"Provider '{ref.provider}' is registered as a direct/custom provider but has no runnable adapter yet. "
            "Add an OpenAI-compatible base URL or route it through a supported adapter before assigning this model to an active agent."
        )

    def live_model_probe(self, model: str) -> dict[str, Any]:
        ref = self._resolve_model_ref(model)
        provider_config = self._provider_config(ref)
        diagnostics = self.diagnostics(model)
        if ref.provider == "mock":
            return {
                **diagnostics,
                "ok": True,
                "alias": ref.alias or model,
                "actualModel": ref.model,
                "responsePreview": "mock probe",
                "message": "Mock provider echoed the live probe.",
            }
        if ref.provider == "copilot":
            return self._copilot_live_model_probe(ref, provider_config, diagnostics)
        if self._can_use_openai_compatible(ref, provider_config):
            return self._openai_live_model_probe(ref, provider_config, diagnostics)
        raise ProviderError(f"Provider '{ref.provider}' does not support live model probing yet.")

    def test_auth(self, provider_id: str) -> dict[str, Any]:
        provider_config = self._provider_config(provider_id)
        if provider_id == "copilot":
            credential = self._copilot_credential(provider_id, provider_config)
            models = self._copilot_models(credential, provider_config)
            return {
                "ok": True,
                "providerId": provider_id,
                "authType": "oauth",
                "modelCount": len(models),
                "models": models,
            }
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
        if ref.provider == "copilot":
            credential = self._copilot_credential(ref.provider, provider_config)
            models = self._copilot_models(credential, provider_config)
            if ref.model not in models:
                suggestions = ", ".join(models[:12])
                return {
                    "ok": False,
                    "status": "invalid model",
                    "alias": ref.alias or model,
                    "providerId": ref.provider,
                    "model": ref.model,
                    "authType": "oauth",
                    "modelCount": len(models),
                    "message": f"Model '{ref.model}' was not found in GitHub Copilot's available model list. Try one of: {suggestions}",
                }
            return {
                "ok": True,
                "status": "ready",
                "alias": ref.alias or model,
                "providerId": ref.provider,
                "model": ref.model,
                "authType": "oauth",
                "modelCount": len(models),
                "message": "GitHub Copilot session token accepted.",
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
        elif ref.provider == "copilot":
            endpoint_path = "/v1/messages" if self._is_copilot_anthropic_model(ref.model) else "/responses"
            endpoint = f"{provider_config.get('baseUrl', 'https://api.individual.githubcopilot.com').rstrip('/')}{endpoint_path}"
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

    def _copilot_response(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        instructions: str,
        message: str,
    ) -> str:
        if self._is_copilot_anthropic_model(ref.model):
            return self._copilot_anthropic_response(ref, provider_config, instructions, message)
        return self._copilot_openai_response(ref, provider_config, instructions, message)

    def _copilot_live_model_probe(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if self._is_copilot_anthropic_model(ref.model):
            data = self._copilot_anthropic_request(
                ref,
                provider_config,
                "You are verifying runtime routing. Reply with exactly: OK",
                "Return exactly OK.",
                max_tokens=16,
            )
            preview = self._extract_anthropic_text(data)
        else:
            data = self._copilot_openai_request(
                ref,
                provider_config,
                "You are verifying runtime routing. Reply with exactly: OK",
                "Return exactly OK.",
                max_tokens=16,
            )
            preview = self._extract_response_text(data)
        return {
            **diagnostics,
            "ok": True,
            "alias": ref.alias,
            "requestedModel": ref.model,
            "actualModel": data.get("model") or data.get("response", {}).get("model") or "not reported",
            "responseId": data.get("id"),
            "responsePreview": preview[:200],
            "message": "Live provider probe completed.",
        }

    def _copilot_openai_response(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        instructions: str,
        message: str,
    ) -> str:
        data = self._copilot_openai_request(ref, provider_config, instructions, message)
        return self._extract_response_text(data)

    def _copilot_openai_request(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        instructions: str,
        message: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        credential = self._copilot_credential(ref.provider, provider_config)
        base_url = provider_config.get("baseUrl", "https://api.individual.githubcopilot.com").rstrip("/")
        body = {
            "model": ref.model,
            "instructions": instructions,
            "input": message,
            "max_output_tokens": max_tokens or int(provider_config.get("maxOutputTokens", 1200)),
        }
        request = urllib.request.Request(
            f"{base_url}/responses",
            data=json.dumps(body).encode("utf-8"),
            headers=self._copilot_headers(credential),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(provider_config.get("timeoutSeconds", 120))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"GitHub Copilot API error {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"GitHub Copilot API network error: {exc.reason}") from exc
        return data

    def _copilot_anthropic_response(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        instructions: str,
        message: str,
    ) -> str:
        data = self._copilot_anthropic_request(ref, provider_config, instructions, message)
        return self._extract_anthropic_text(data)

    def _copilot_anthropic_request(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        instructions: str,
        message: str,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        credential = self._copilot_credential(ref.provider, provider_config)
        base_url = provider_config.get("baseUrl", "https://api.individual.githubcopilot.com").rstrip("/")
        body = {
            "model": ref.model,
            "system": instructions,
            "messages": [{"role": "user", "content": message}],
            "max_tokens": max_tokens or int(provider_config.get("maxOutputTokens", 1200)),
        }
        request = urllib.request.Request(
            f"{base_url}/v1/messages",
            data=json.dumps(body).encode("utf-8"),
            headers={**self._copilot_headers(credential), "anthropic-version": "2023-06-01"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(provider_config.get("timeoutSeconds", 120))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"GitHub Copilot Claude API error {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"GitHub Copilot Claude API network error: {exc.reason}") from exc
        return data

    def _copilot_models(self, credential: str, provider_config: dict[str, Any]) -> list[str]:
        base_url = provider_config.get("baseUrl", "https://api.individual.githubcopilot.com").rstrip("/")
        request = urllib.request.Request(
            f"{base_url}/models",
            headers=self._copilot_headers(credential),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(provider_config.get("timeoutSeconds", 120))) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise ProviderError(f"GitHub Copilot model test failed with HTTP {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"GitHub Copilot model test network error: {exc.reason}") from exc
        return [item.get("id") for item in data.get("data", []) if item.get("id")]

    def _copilot_credential(self, provider: str, provider_config: dict[str, Any]) -> str:
        profile = self._oauth_profile(provider, provider_config)
        if not profile:
            raise ProviderError(
                "Missing OAuth profile for GitHub Copilot. Use Providers -> Start OAuth with provider 'copilot'."
            )
        cached = profile.get("copilotAccess")
        if cached and int(profile.get("copilotExpires", 0)) > int(time.time()) + 60:
            if profile.get("copilotBaseUrl"):
                provider_config["baseUrl"] = profile["copilotBaseUrl"]
            return cached
        github_token = profile.get("access")
        if not github_token:
            raise ProviderError("GitHub Copilot OAuth profile has no GitHub access token")
        token_data = self._exchange_copilot_token(github_token, provider_config)
        session_token = token_data.get("token")
        if not session_token:
            raise ProviderError("GitHub Copilot token exchange returned no session token")
        expires_at = int(token_data.get("expires_at", int(time.time()) + int(token_data.get("expires_in", 3600))))
        base_url = self._copilot_base_url(token_data, provider_config)
        if self.home:
            AuthStore(self.home).update_profile(
                provider,
                provider_config.get("profileId", "default"),
                {
                    "copilotAccess": session_token,
                    "copilotExpires": expires_at,
                    "copilotBaseUrl": base_url,
                },
            )
        provider_config["baseUrl"] = base_url
        return session_token

    def _exchange_copilot_token(self, github_token: str, provider_config: dict[str, Any]) -> dict[str, Any]:
        errors: list[str] = []
        request = urllib.request.Request(
            provider_config.get("tokenUrl", "https://api.github.com/copilot_internal/v2/token"),
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {github_token}",
                **self._copilot_client_headers(),
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(provider_config.get("timeoutSeconds", 120))) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            errors.append(f"GET Bearer: HTTP {exc.code}: {details}")
        except urllib.error.URLError as exc:
            raise ProviderError(f"GitHub Copilot token exchange network error: {exc.reason}") from exc
        details = " | ".join(errors)
        if "Resource not accessible by personal access token" in details:
            raise ProviderError(
                "GitHub token was saved, but it cannot access the Copilot token exchange. "
                "Use a token from the GitHub account that has an active Copilot subscription, "
                "or configure GitHub CLI/device login for this provider. Details: " + details
            )
        raise ProviderError("GitHub Copilot token exchange failed. " + details)

    def _copilot_base_url(self, token_data: dict[str, Any], provider_config: dict[str, Any]) -> str:
        configured = provider_config.get("baseUrl", "").rstrip("/")
        endpoint = (token_data.get("endpoints") or {}).get("api") or configured
        endpoint = str(endpoint or "https://api.individual.githubcopilot.com").rstrip("/")
        if "githubcopilot.com" in endpoint:
            return endpoint.replace("://proxy.", "://api.").replace("://proxy-", "://api-")
        return configured or "https://api.individual.githubcopilot.com"

    def _copilot_headers(self, credential: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {credential}",
            "Content-Type": "application/json",
            "Openai-Organization": "github-copilot",
            "x-initiator": "user",
            **self._copilot_client_headers(),
        }

    def _copilot_client_headers(self) -> dict[str, str]:
        return {
            "User-Agent": "GitHubCopilotChat/0.35.0",
            "Editor-Version": "vscode/1.96.2",
            "Editor-Plugin-Version": "copilot-chat/0.35.0",
            "Copilot-Integration-Id": "vscode-chat",
            "X-GitHub-Api-Version": "2025-04-01",
        }

    def _is_copilot_anthropic_model(self, model: str) -> bool:
        return model.startswith("claude-")

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

    def _openai_live_model_probe(
        self,
        ref: ModelRef,
        provider_config: dict[str, Any],
        diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if ref.provider == "openai-codex" and self._oauth_profile(ref.provider, provider_config):
            response = self._codex_oauth_response(
                ref,
                provider_config,
                "You are verifying runtime routing. Reply with exactly: OK",
                "Return exactly OK.",
            )
            return {
                **diagnostics,
                "ok": True,
                "alias": ref.alias,
                "requestedModel": ref.model,
                "actualModel": "not reported by streaming response",
                "responsePreview": response[:200],
                "message": "Live Codex OAuth probe completed, but the streaming response does not expose a model id.",
            }
        credential = self._credential(ref.provider, provider_config)
        if not credential:
            raise ProviderError(
                f"Missing API key for '{ref.provider}'. Set {provider_config.get('apiKeyEnv', 'OPENAI_API_KEY')} "
                "or configure a provider API key/OAuth profile in OCLite."
            )
        base_url = provider_config.get("baseUrl", "").rstrip("/")
        body = {
            "model": ref.model,
            "instructions": "You are verifying runtime routing. Reply with exactly: OK",
            "input": "Return exactly OK.",
            "max_output_tokens": 16,
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
        return {
            **diagnostics,
            "ok": True,
            "alias": ref.alias,
            "requestedModel": ref.model,
            "actualModel": data.get("model") or "not reported",
            "responseId": data.get("id"),
            "responsePreview": self._extract_text(data)[:200],
            "message": "Live provider probe completed.",
        }

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
        if provider == "copilot" and self.home:
            profile_id = provider_config.get("profileId", "default")
            return AuthStore(self.home).get_profile(provider, profile_id)
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

    def _extract_chat_text(self, data: dict[str, Any]) -> str:
        texts: list[str] = []
        for choice in data.get("choices", []):
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                texts.append(content.strip())
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("text"):
                        texts.append(str(part["text"]).strip())
        if texts:
            return "\n".join(text for text in texts if text).strip()
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return data["output_text"].strip()
        raise ProviderError("GitHub Copilot returned no chat text output")

    def _extract_anthropic_text(self, data: dict[str, Any]) -> str:
        texts: list[str] = []
        for part in data.get("content", []):
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                texts.append(str(part["text"]).strip())
        if texts:
            return "\n".join(text for text in texts if text).strip()
        raise ProviderError("GitHub Copilot Claude returned no text output")

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
