from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import tomllib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import Agent
from .oauth import (
    AuthStore,
    OAuthError,
    complete_openai_codex_oauth,
    poll_github_copilot_oauth,
    start_github_copilot_oauth,
    start_openai_codex_oauth,
)
from .providers import ProviderError, ProviderRunner
from .runtime import AgentRuntime, TelegramPoller
from .store import Store


STATIC_DIR = Path(__file__).parent / "static"


class OCLiteHandler(SimpleHTTPRequestHandler):
    store = Store()
    runtime = AgentRuntime(store)
    app_metadata_cache: dict | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            return self.json_response(self.state())
        if parsed.path == "/api/agents":
            return self.json_response([agent.to_dict() for agent in self.store.list_agents()])
        if parsed.path == "/api/sessions":
            return self.json_response(self.store.list_sessions())
        if parsed.path == "/api/tasks":
            return self.json_response(self.store.list_tasks())
        if parsed.path == "/api/version":
            return self.json_response(self.app_metadata())
        if parsed.path == "/api/auth/profiles":
            return self.json_response(AuthStore(self.store.home).list_profiles())
        if parsed.path == "/api/diagnostics/agent":
            query = parse_qs(parsed.query)
            return self.agent_diagnostics(query.get("agentId", ["main"])[0])
        if parsed.path == "/" or not parsed.path.startswith("/api/"):
            return self.serve_static(parsed.path)
        self.send_error(404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/setup":
                self.store.setup()
                return self.json_response(self.state())
            if parsed.path == "/api/agents":
                agent = self.store.create_agent(self.read_json())
                return self.json_response(agent.to_dict(), 201)
            if parsed.path == "/api/agents/workspace":
                data = self.read_json()
                agent = self.store.set_agent_workspace(data["agentId"], data["workspace"])
                return self.json_response(agent.to_dict())
            if parsed.path == "/api/agents/model":
                data = self.read_json()
                agent = self.store.set_agent_model(data["agentId"], data["model"])
                return self.json_response(agent.to_dict())
            if parsed.path == "/api/agents/context":
                data = self.read_json()
                agent = self.store.set_agent_context(data["agentId"], int(data["recentTurns"]))
                return self.json_response(agent.to_dict())
            if parsed.path == "/api/agents/bootstrap/reset":
                data = self.read_json()
                agent = self.store.reset_agent_bootstrap(data["agentId"])
                return self.json_response(agent.to_dict())
            if parsed.path == "/api/agents/seed":
                data = self.read_json()
                agent = self.store.seed_agent(data["agentId"], data.get("user"), data.get("what"))
                return self.json_response(agent.to_dict())
            if parsed.path == "/api/agents/delete":
                data = self.read_json()
                result = self.store.delete_agent(data["agentId"], bool(data.get("deleteWorkspace", False)))
                return self.json_response(result)
            if parsed.path == "/api/agents/bind":
                return self.bind_agent()
            if parsed.path == "/api/telegram/bots":
                return self.add_bot()
            if parsed.path == "/api/telegram/allow":
                return self.allow_sender()
            if parsed.path == "/api/models/allow":
                return self.allow_model()
            if parsed.path == "/api/models/register":
                data = self.read_json()
                return self.json_response(self.store.save_model(data), 201)
            if parsed.path == "/api/models/alias":
                data = self.read_json()
                return self.json_response(self.store.save_model_alias(data), 201)
            if parsed.path == "/api/models/delete":
                data = self.read_json()
                return self.json_response(self.store.delete_model_alias(data.get("alias", ""), data.get("replacement")))
            if parsed.path == "/api/models/test":
                return self.test_model()
            if parsed.path == "/api/providers":
                return self.save_provider()
            if parsed.path == "/api/providers/auth":
                return self.auth_provider()
            if parsed.path == "/api/oauth/start":
                return self.start_oauth()
            if parsed.path == "/api/oauth/poll":
                return self.poll_oauth()
            if parsed.path == "/api/oauth/complete":
                return self.complete_oauth()
            if parsed.path == "/api/system/update":
                return self.system_update()
            if parsed.path == "/api/system/restart":
                return self.system_restart()
            if parsed.path == "/api/sessions/prune":
                count = self.store.prune_stale()
                return self.json_response({"pruned": count})
            if parsed.path == "/api/tasks/status":
                data = self.read_json()
                task = self.store.update_task(data["taskId"], data["status"], data.get("message"))
                return self.json_response(task.to_dict())
            if parsed.path == "/api/tasks":
                return self.run_task()
        except ValueError as exc:
            return self.json_response({"error": str(exc)}, 400)
        except ProviderError as exc:
            return self.json_response({"error": str(exc)}, 400)
        except OAuthError as exc:
            return self.json_response({"error": str(exc)}, 400)
        self.send_error(404)

    def state(self) -> dict:
        config = self.store.config()
        agents = [agent.to_dict() for agent in self.store.list_agents()]
        sessions = self.store.list_sessions()
        tasks = self.store.list_tasks()
        return {
            "home": str(self.store.home),
            "config": config,
            "agents": agents,
            "sessions": sessions,
            "tasks": tasks,
            "app": self.app_metadata(),
            "providerPresets": self.store.provider_presets(),
            "modelPresets": self.store.model_presets(),
            "authProfiles": AuthStore(self.store.home).list_profiles(),
            "workspaceFiles": [
                "AGENTS.md",
                "SOUL.md",
                "USER.md",
                "IDENTITY.md",
                "TOOLS.md",
                "HEARTBEAT.md",
                "BOOT.md",
                "BOOTSTRAP.md",
                "MEMORY.md",
                "memory/",
            ],
        }

    def app_metadata(self) -> dict:
        if self.__class__.app_metadata_cache is not None:
            return self.__class__.app_metadata_cache
        root = Path(__file__).resolve().parents[1]
        version = "0.0.0"
        pyproject = root / "pyproject.toml"
        if pyproject.exists():
            try:
                version = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("version", version)
            except tomllib.TOMLDecodeError:
                version = "0.0.0"
        release_notes_path = root / "RELEASE_NOTES.md"
        release_notes = release_notes_path.read_text(encoding="utf-8", errors="replace") if release_notes_path.exists() else ""
        git = self.git_metadata(root)
        metadata = {
            "name": "OCLite",
            "version": version,
            "releaseNotes": release_notes,
            **git,
        }
        self.__class__.app_metadata_cache = metadata
        return metadata

    def git_metadata(self, root: Path) -> dict:
        if not (root / ".git").exists():
            return {"branch": "", "commit": ""}
        try:
            branch = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
            commit = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        except subprocess.SubprocessError:
            return {"branch": "", "commit": ""}
        return {"branch": branch, "commit": commit}

    def bind_agent(self) -> None:
        data = self.read_json()
        agent = self.store.get_agent(data["agentId"])
        if not agent:
            raise ValueError("Unknown agent")
        account_id = data["accountId"]
        agent.bindings = [
            binding
            for binding in agent.bindings
            if not (binding.get("channel") == "telegram" and binding.get("accountId") == account_id)
        ]
        agent.bindings.append({"channel": "telegram", "accountId": account_id})
        self.store.save_agent(agent)
        self.json_response(agent.to_dict())

    def add_bot(self) -> None:
        data = self.read_json()
        account_id = data["accountId"].strip()
        token_env = data.get("tokenEnv", "").strip()
        token = data.get("token", "").strip()
        token_secret = data.get("tokenSecret", "").strip()
        if not token and token_secret and account_id.isdigit():
            token = f"{account_id}:{token_secret}"
        if token and ":" not in token and account_id.isdigit():
            token = f"{account_id}:{token}"
        if not account_id or not (token_env or token):
            raise ValueError("Bot id and token env or token are required")
        config = self.store.config()
        bot = {
            "accountId": account_id,
            "enabled": True,
        }
        if token_env:
            bot["tokenEnv"] = token_env
        if token:
            bot["token"] = token
        config["telegram"]["bots"][account_id] = bot
        self.store.save_config(config)
        self.json_response(config["telegram"]["bots"][account_id], 201)

    def allow_sender(self) -> None:
        data = self.read_json()
        sender_id = str(data["senderId"]).strip()
        config = self.store.config()
        allowlist = config["telegram"].setdefault("allowlist", [])
        if sender_id and sender_id not in allowlist:
            allowlist.append(sender_id)
        self.store.save_config(config)
        self.json_response({"allowlist": allowlist})

    def allow_model(self) -> None:
        data = self.read_json()
        model = data["model"].strip()
        config = self.store.config()
        allowed = config["models"].setdefault("allowed", [])
        if model and model not in allowed:
            allowed.append(model)
        if data.get("makeDefault"):
            config["models"]["default"] = model
        self.store.save_config(config)
        self.json_response(config["models"])

    def save_provider(self) -> None:
        data = self.read_json()
        provider = self.store.save_provider(data["providerId"], data)
        self.json_response(provider)

    def auth_provider(self) -> None:
        data = self.read_json()
        result = ProviderRunner(self.store.config(), self.store.home).test_auth(data["providerId"])
        self.json_response(result)

    def test_model(self) -> None:
        data = self.read_json()
        model = data.get("model") or data.get("alias")
        if not model:
            raise ValueError("Model alias is required")
        result = ProviderRunner(self.store.config(), self.store.home).test_model(model)
        self.json_response(result)

    def start_oauth(self) -> None:
        data = self.read_json()
        provider_id = data.get("providerId", "openai-codex")
        if provider_id == "openai-codex":
            result = start_openai_codex_oauth(self.store.home, data.get("profileId", "default"))
        elif provider_id in {"copilot", "github-copilot"}:
            result = start_github_copilot_oauth(self.store.home, data.get("profileId", "default"))
        else:
            raise OAuthError("Only openai-codex and GitHub Copilot OAuth are supported right now")
        self.json_response(result)

    def poll_oauth(self) -> None:
        data = self.read_json()
        provider_id = data.get("providerId", "")
        if provider_id not in {"copilot", "github-copilot"}:
            raise OAuthError("OAuth polling is only supported for GitHub Copilot device login")
        result = poll_github_copilot_oauth(self.store.home, data["state"])
        self.json_response(result)

    def complete_oauth(self) -> None:
        data = self.read_json()
        result = complete_openai_codex_oauth(self.store.home, data["code"], data["state"])
        self.json_response(result)

    def agent_diagnostics(self, agent_id: str) -> None:
        agent = self.store.get_agent(agent_id)
        if not agent:
            raise ValueError("Unknown agent")
        diag = ProviderRunner(self.store.config(), self.store.home).diagnostics(agent.model)
        self.json_response({"agentId": agent.id, "agentModel": agent.model, **diag})

    def run_task(self) -> None:
        data = self.read_json()
        agent = self.store.get_agent(data["agentId"])
        if not agent:
            raise ValueError("Unknown agent")
        session = self.store.create_or_touch_session(agent, "ui", "control", "local")
        response = self.runtime.run_task(agent, data.get("message", ""), session.id, channel="ui", source="control")
        self.json_response({"response": response, "session": session.to_dict()})

    def system_update(self) -> None:
        root = Path(__file__).resolve().parents[1]
        if not (root / ".git").exists():
            return self.json_response(
                {
                    "ok": False,
                    "root": str(root),
                    "output": "OCLite source directory is not a git checkout.",
                },
                400,
            )
        result = subprocess.run(
            ["git", "-C", str(root), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
        self.json_response(
            {
                "ok": result.returncode == 0,
                "root": str(root),
                "returnCode": result.returncode,
                "output": output or "No output.",
            },
            200 if result.returncode == 0 else 500,
        )

    def system_restart(self) -> None:
        self.json_response({"ok": True, "message": "Restarting OCLite gateway."})
        threading.Timer(0.5, restart_process).start()

    def read_json(self) -> dict:
        length = int(self.headers.get("content-length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def json_response(self, data, status: int = 200) -> None:
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, request_path: str) -> None:
        path = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        target = (STATIC_DIR / path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.exists():
            target = STATIC_DIR / "index.html"
        content_types = {
            ".css": "text/css",
            ".html": "text/html",
            ".js": "application/javascript",
            ".svg": "image/svg+xml",
        }
        content_type = content_types.get(target.suffix, "application/octet-stream")
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str, port: int, poll_telegram: bool = True) -> None:
    store = Store()
    store.setup()
    OCLiteHandler.store = store
    OCLiteHandler.runtime = AgentRuntime(store)
    poller = TelegramPoller(store)
    if poll_telegram:
        poller.start()
    server = ThreadingHTTPServer((host, port), OCLiteHandler)
    print(f"OCLite control UI running at http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        poller.stop()


def restart_process() -> None:
    entry = Path(sys.argv[0]).resolve()
    if entry.name == "__main__.py" and entry.parent.name == "oclite":
        args = [sys.executable, "-m", "oclite", *sys.argv[1:]]
    else:
        args = [sys.executable, *sys.argv]
    helper = (
        "import os, subprocess, sys, time; "
        "time.sleep(1); "
        "subprocess.Popen(sys.argv[1:], cwd=os.getcwd())"
    )
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [sys.executable, "-c", helper, *args],
        cwd=os.getcwd(),
        close_fds=True,
        creationflags=creationflags,
    )
    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()
    run_server(args.host, args.port, poll_telegram=not args.no_telegram)


if __name__ == "__main__":
    main()
