from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .models import Agent, OPENCLAW_WORKSPACE_FILES
from .providers import ProviderError, ProviderRunner
from .store import Store


class AgentRuntime:
    def __init__(self, store: Store):
        self.store = store

    def workspace_context(self, agent: Agent) -> str:
        workspace = Path(agent.workspace)
        parts: list[str] = []
        for filename in OPENCLAW_WORKSPACE_FILES:
            path = workspace / filename
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                parts.append(f"## {filename}\n{text}")
        return "\n\n".join(parts)

    def run_task(self, agent: Agent, message: str, session_id: str) -> str:
        self.store.append_session_event(session_id, {"role": "user", "content": message})
        if agent.model == "mock:echo":
            response = self._mock_response(agent, message)
        else:
            try:
                response = ProviderRunner(self.store.config(), self.store.home).run(
                    agent.model,
                    self.workspace_context(agent),
                    message,
                )
            except ProviderError as exc:
                response = f"Provider error: {exc}"
        self.store.append_session_event(session_id, {"role": "assistant", "content": response})
        return response

    def _mock_response(self, agent: Agent, message: str) -> str:
        if agent.id == "main" and "create" in message.lower() and "agent" in message.lower():
            return (
                "I can create agents from the control UI or API now. "
                "Use Agents -> Create, assign an authorized model, then bind a Telegram bot."
            )
        return f"{agent.name} received: {message}"

class TelegramPoller:
    def __init__(self, store: Store):
        self.store = store
        self.runtime = AgentRuntime(store)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.offsets: dict[str, int] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="telegram-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            config = self.store.config()
            bots = config.get("telegram", {}).get("bots", {})
            for account_id, bot in bots.items():
                if bot.get("enabled", True):
                    self._poll_bot(account_id, bot)
            time.sleep(2)

    def _poll_bot(self, account_id: str, bot: dict[str, Any]) -> None:
        token = bot.get("token") or os.environ.get(bot.get("tokenEnv", ""))
        if not token:
            return
        params = {"timeout": 1}
        if account_id in self.offsets:
            params["offset"] = self.offsets[account_id]
        url = f"https://api.telegram.org/bot{token}/getUpdates?{urllib.parse.urlencode(params)}"
        try:
            data = self._request_json(url)
        except Exception as exc:
            self._log({"type": "telegram_error", "accountId": account_id, "error": str(exc)})
            return
        for update in data.get("result", []):
            self.offsets[account_id] = int(update["update_id"]) + 1
            message = update.get("message") or update.get("edited_message")
            if message:
                self._handle_message(account_id, token, message)

    def _handle_message(self, account_id: str, token: str, message: dict[str, Any]) -> None:
        chat_id = str(message.get("chat", {}).get("id", ""))
        sender_id = str(message.get("from", {}).get("id", chat_id))
        text = message.get("text", "")
        config = self.store.config()
        telegram = config.setdefault("telegram", {})
        detected = telegram.setdefault("detectedSenders", [])
        if sender_id and sender_id not in detected:
            detected.append(sender_id)
            self.store.save_config(config)
        if sender_id not in telegram.get("allowlist", []):
            self._send(token, chat_id, f"Sender {sender_id} is not allowed yet.")
            return
        agent = self._agent_for_bot(account_id)
        if not agent:
            self._send(token, chat_id, f"Bot '{account_id}' is not bound to an agent yet.")
            return
        session = self.store.create_or_touch_session(agent, "telegram", account_id, sender_id)
        try:
            response = self.runtime.run_task(agent, text, session.id)
        except Exception as exc:
            response = f"Runtime error: {type(exc).__name__}: {exc}"
            self.store.append_session_event(session.id, {"role": "system", "content": response})
        self._send(token, chat_id, response)

    def _agent_for_bot(self, account_id: str) -> Agent | None:
        for agent in self.store.list_agents():
            for binding in agent.bindings:
                if binding.get("channel") == "telegram" and binding.get("accountId") == account_id:
                    return agent
        return None

    def _send(self, token: str, chat_id: str, text: str) -> None:
        if not chat_id:
            return
        body = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
        request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
        try:
            urllib.request.urlopen(request, timeout=10).read()
        except Exception as exc:
            self._log({"type": "telegram_send_error", "error": str(exc)})

    def _request_json(self, url: str) -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _log(self, event: dict[str, Any]) -> None:
        self.store.logs_dir.mkdir(exist_ok=True)
        with (self.store.logs_dir / "runtime.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), **event}) + "\n")
