from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_CODEX_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_CODEX_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_CODEX_REDIRECT_URI = "http://localhost:1455/auth/callback"
OPENAI_CODEX_SCOPE = "openid profile email offline_access"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_COPILOT_DEVICE_SCOPE = "read:user"
GITHUB_COPILOT_TOKEN_ENV = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")


class OAuthError(RuntimeError):
    pass


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_pkce_pair() -> tuple[str, str]:
    verifier = b64url(secrets.token_bytes(48))
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class AuthStore:
    def __init__(self, home: Path):
        self.home = home
        self.path = home / "auth-profiles.json"
        self.pending_path = home / "oauth-pending.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"profiles": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, data: dict[str, Any]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def save_profile(self, provider_id: str, profile_id: str, token_data: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        profiles = data.setdefault("profiles", {})
        profile = {
            "providerId": provider_id,
            "profileId": profile_id,
            "authType": "oauth",
            "access": token_data["access_token"],
            "refresh": token_data.get("refresh_token"),
            "expires": int(time.time()) + int(token_data.get("expires_in", 3600)) - 60,
            "accountId": token_data.get("account_id") or profile_id,
            "tokenType": token_data.get("token_type", "Bearer"),
            "updatedAt": int(time.time()),
        }
        profiles[f"{provider_id}:{profile_id}"] = profile
        self.save(data)
        return profile

    def get_profile(self, provider_id: str, profile_id: str = "default") -> dict[str, Any] | None:
        return self.load().get("profiles", {}).get(f"{provider_id}:{profile_id}")

    def delete_profile(self, provider_id: str, profile_id: str = "default") -> None:
        data = self.load()
        profiles = data.setdefault("profiles", {})
        key = f"{provider_id}:{profile_id}"
        if key in profiles:
            del profiles[key]
            self.save(data)

    def update_profile(self, provider_id: str, profile_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        data = self.load()
        profiles = data.setdefault("profiles", {})
        key = f"{provider_id}:{profile_id}"
        profile = profiles.get(key)
        if not profile:
            raise OAuthError(f"OAuth profile '{key}' was not found")
        profile.update(updates)
        profile["updatedAt"] = int(time.time())
        profiles[key] = profile
        self.save(data)
        return profile

    def list_profiles(self) -> list[dict[str, Any]]:
        return list(self.load().get("profiles", {}).values())

    def save_pending(self, pending: dict[str, Any]) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")

    def load_pending(self, state: str) -> dict[str, Any]:
        if not self.pending_path.exists():
            raise OAuthError("No OAuth login is pending. Start OAuth again from the active OCLite control UI.")
        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        if pending.get("state") != state:
            raise OAuthError(
                "OAuth state mismatch. This callback belongs to a different or older login attempt; "
                "close this tab and start OAuth again from the active OCLite control UI."
            )
        return pending

    def clear_pending(self) -> None:
        if self.pending_path.exists():
            self.pending_path.unlink()


def start_openai_codex_oauth(home: Path, profile_id: str = "default") -> dict[str, Any]:
    verifier, challenge = make_pkce_pair()
    state = secrets.token_urlsafe(24)
    pending = {
        "providerId": "openai-codex",
        "profileId": profile_id or "default",
        "state": state,
        "verifier": verifier,
        "createdAt": int(time.time()),
    }
    AuthStore(home).save_pending(pending)
    params = {
        "client_id": OPENAI_CODEX_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": OPENAI_CODEX_REDIRECT_URI,
        "scope": OPENAI_CODEX_SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": "pi",
    }
    ensure_callback_server(home)
    return {
        "providerId": "openai-codex",
        "profileId": pending["profileId"],
        "authUrl": f"{OPENAI_CODEX_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}",
        "redirectUri": OPENAI_CODEX_REDIRECT_URI,
    }


def start_github_copilot_oauth(home: Path, profile_id: str = "default") -> dict[str, Any]:
    auth_store = AuthStore(home)
    profile_id = profile_id or "default"
    existing = auth_store.get_profile("copilot", profile_id)
    if existing and existing.get("accountId") != "github device login":
        auth_store.delete_profile("copilot", profile_id)
    client_id = os.environ.get("OCLITE_GITHUB_OAUTH_CLIENT_ID", "").strip() or GITHUB_COPILOT_CLIENT_ID
    body = urllib.parse.urlencode({"client_id": client_id, "scope": GITHUB_COPILOT_DEVICE_SCOPE}).encode("utf-8")
    request = urllib.request.Request(
        GITHUB_DEVICE_CODE_URL,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OAuthError(f"GitHub device login failed: {exc}") from exc
    if data.get("error"):
        raise OAuthError(f"GitHub device login failed: {data.get('error_description') or data['error']}")
    state = secrets.token_urlsafe(24)
    auth_store.save_pending(
        {
            "providerId": "copilot",
            "profileId": profile_id,
            "state": state,
            "clientId": client_id,
            "deviceCode": data["device_code"],
            "userCode": data["user_code"],
            "verificationUri": data["verification_uri"],
            "interval": int(data.get("interval", 5)),
            "expiresAt": int(time.time()) + int(data.get("expires_in", 900)),
            "createdAt": int(time.time()),
        }
    )
    return {
        "providerId": "copilot",
        "profileId": profile_id,
        "status": "pending",
        "authUrl": data["verification_uri"],
        "verificationUri": data["verification_uri"],
        "userCode": data["user_code"],
        "state": state,
        "interval": int(data.get("interval", 5)),
        "expiresIn": int(data.get("expires_in", 900)),
    }


def import_github_copilot_token(home: Path, profile_id: str = "default") -> dict[str, Any] | None:
    for env_name in GITHUB_COPILOT_TOKEN_ENV:
        token = os.environ.get(env_name, "").strip()
        if token:
            profile = AuthStore(home).save_profile(
                "copilot",
                profile_id or "default",
                {
                    "access_token": token,
                    "expires_in": 60 * 60 * 24 * 365,
                    "token_type": "Bearer",
                    "account_id": env_name,
                },
            )
            return {"profile": profile, "message": f"Imported GitHub token from {env_name}."}
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    token = result.stdout.strip()
    if result.returncode == 0 and token:
        profile = AuthStore(home).save_profile(
            "copilot",
            profile_id or "default",
            {
                "access_token": token,
                "expires_in": 60 * 60 * 24 * 365,
                "token_type": "Bearer",
                "account_id": "gh auth token",
            },
        )
        return {"profile": profile, "message": "Imported GitHub token from GitHub CLI."}
    return None


def poll_github_copilot_oauth(home: Path, state: str) -> dict[str, Any]:
    auth_store = AuthStore(home)
    pending = auth_store.load_pending(state)
    if pending.get("providerId") != "copilot":
        raise OAuthError("Pending OAuth login is not for GitHub Copilot")
    if int(time.time()) >= int(pending.get("expiresAt", 0)):
        auth_store.clear_pending()
        raise OAuthError("GitHub device login expired")
    body = urllib.parse.urlencode(
        {
            "client_id": pending["clientId"],
            "device_code": pending["deviceCode"],
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        GITHUB_ACCESS_TOKEN_URL,
        data=body,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OAuthError(f"GitHub device token exchange failed: {exc}") from exc
    error = data.get("error")
    if error == "authorization_pending":
        return {"providerId": "copilot", "profileId": pending["profileId"], "status": "pending"}
    if error == "slow_down":
        pending["interval"] = int(pending.get("interval", 5)) + 5
        auth_store.save_pending(pending)
        return {"providerId": "copilot", "profileId": pending["profileId"], "status": "pending", "slowDown": True}
    if error:
        raise OAuthError(f"GitHub device token exchange failed: {data.get('error_description') or error}")
    auth_store.clear_pending()
    profile = auth_store.save_profile(
        "copilot",
        pending["profileId"],
        {
            "access_token": data["access_token"],
            "expires_in": 60 * 60 * 24 * 365,
            "token_type": data.get("token_type", "Bearer"),
            "account_id": "github device login",
        },
    )
    return {"providerId": "copilot", "profileId": pending["profileId"], "status": "complete", "profile": profile}


def complete_openai_codex_oauth(home: Path, code: str, state: str) -> dict[str, Any]:
    auth_store = AuthStore(home)
    pending = auth_store.load_pending(state)
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "code": code,
            "code_verifier": pending["verifier"],
            "redirect_uri": OPENAI_CODEX_REDIRECT_URI,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENAI_CODEX_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            token_data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OAuthError(f"OAuth token exchange failed: {exc}") from exc
    auth_store.clear_pending()
    return auth_store.save_profile(pending["providerId"], pending["profileId"], token_data)


def refresh_openai_codex_oauth(home: Path, profile: dict[str, Any]) -> dict[str, Any]:
    refresh = profile.get("refresh")
    if not refresh:
        raise OAuthError("OAuth profile has no refresh token")
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "refresh_token": refresh,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        OPENAI_CODEX_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            token_data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OAuthError(f"OAuth refresh failed: {exc}") from exc
    if "refresh_token" not in token_data:
        token_data["refresh_token"] = refresh
    return AuthStore(home).save_profile(profile["providerId"], profile["profileId"], token_data)


_callback_server_started = False


def ensure_callback_server(home: Path) -> None:
    global _callback_server_started
    if _callback_server_started:
        return

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/auth/callback":
                self.send_error(404)
                return
            params = urllib.parse.parse_qs(parsed.query)
            code = params.get("code", [""])[0]
            state = params.get("state", [""])[0]
            try:
                complete_openai_codex_oauth(home, code, state)
                body = b"OCLite OAuth login complete. You can return to OCLite."
                self.send_response(200)
            except Exception as exc:
                body = f"OCLite OAuth login failed: {exc}".encode("utf-8")
                self.send_response(400)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    try:
        server = ThreadingHTTPServer(("127.0.0.1", 1455), CallbackHandler)
    except OSError as exc:
        raise OAuthError(
            "OAuth callback port 1455 is already in use. Stop the other OCLite/Python gateway process "
            "or use the control UI served by that process, then start OAuth again."
        ) from exc
    thread = threading.Thread(target=server.serve_forever, name="oauth-callback", daemon=True)
    thread.start()
    _callback_server_started = True
