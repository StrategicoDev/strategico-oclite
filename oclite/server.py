from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import Agent
from .providers import ProviderError, ProviderRunner
from .runtime import AgentRuntime, TelegramPoller
from .store import Store


STATIC_DIR = Path(__file__).parent / "static"


class OCLiteHandler(SimpleHTTPRequestHandler):
    store = Store()
    runtime = AgentRuntime(store)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            return self.json_response(self.state())
        if parsed.path == "/api/agents":
            return self.json_response([agent.to_dict() for agent in self.store.list_agents()])
        if parsed.path == "/api/sessions":
            return self.json_response(self.store.list_sessions())
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
            if parsed.path == "/api/agents/bind":
                return self.bind_agent()
            if parsed.path == "/api/telegram/bots":
                return self.add_bot()
            if parsed.path == "/api/telegram/allow":
                return self.allow_sender()
            if parsed.path == "/api/models/allow":
                return self.allow_model()
            if parsed.path == "/api/providers":
                return self.save_provider()
            if parsed.path == "/api/providers/auth":
                return self.auth_provider()
            if parsed.path == "/api/sessions/prune":
                count = self.store.prune_stale()
                return self.json_response({"pruned": count})
            if parsed.path == "/api/tasks":
                return self.run_task()
        except ValueError as exc:
            return self.json_response({"error": str(exc)}, 400)
        except ProviderError as exc:
            return self.json_response({"error": str(exc)}, 400)
        self.send_error(404)

    def state(self) -> dict:
        config = self.store.config()
        agents = [agent.to_dict() for agent in self.store.list_agents()]
        sessions = self.store.list_sessions()
        return {
            "home": str(self.store.home),
            "config": config,
            "agents": agents,
            "sessions": sessions,
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
        result = ProviderRunner(self.store.config()).test_auth(data["providerId"])
        self.json_response(result)

    def run_task(self) -> None:
        data = self.read_json()
        agent = self.store.get_agent(data["agentId"])
        if not agent:
            raise ValueError("Unknown agent")
        session = self.store.create_or_touch_session(agent, "ui", "control", "local")
        response = self.runtime.run_task(agent, data.get("message", ""), session.id)
        self.json_response({"response": response, "session": session.to_dict()})

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
        content_type = "text/html"
        if target.suffix == ".css":
            content_type = "text/css"
        if target.suffix == ".js":
            content_type = "application/javascript"
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()
    run_server(args.host, args.port, poll_telegram=not args.no_telegram)


if __name__ == "__main__":
    main()
