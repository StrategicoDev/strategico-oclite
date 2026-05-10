from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .bootstrap import Bootstrapper
from .models import Agent, OPENCLAW_WORKSPACE_FILES
from .providers import ProviderError, ProviderRunner
from .store import Store


TOOL_INSTRUCTIONS = """## OCLite Runtime Tools

You can operate the OCLite runtime by returning exactly one JSON object and no extra prose when a tool is needed.

Available tools:

1. Create an agent:
{"oclite_tool":"create_agent","args":{"id":"researcher","name":"Researcher","role":"Research and analysis agent","user":"Sipes","what":"A focused research agent with a precise, source-aware style.","model":"openai-codex/gpt-5.5"}}

2. List agents:
{"oclite_tool":"list_agents","args":{}}

3. Delete an agent:
{"oclite_tool":"delete_agent","args":{"agentId":"researcher","deleteWorkspace":false}}

4. Seed/bootstrap an existing agent:
{"oclite_tool":"seed_agent","args":{"agentId":"researcher","what":"A focused research agent with a precise, source-aware style."}}

5. Delegate a task:
{"oclite_tool":"delegate_task","args":{"agentId":"researcher","task":"Summarize the project state."}}

Rules:
- If the user asks you to create, spawn, set up, list, or delegate to an agent, use the OCLite tool JSON.
- Do not say you lack the platform interface for these actions.
- Only the orchestrator/default agent may create, delete, or seed delegate agents.
- Only the orchestrator/default agent may delegate tasks. Delegate agents return results to the orchestrator.
- Delegate tasks are one level deep only. Child tasks must not create child tasks.
- After a delegate returns, assess whether the parent task is complete, blocked pending user input/approval, or needs another one-level child task.
- Keep agent ids lowercase with letters, numbers, dashes, or underscores.
- Use an already authorized model when one is known; otherwise omit model and OCLite will use the default.
- Before creating an agent, ask for or infer:
  name: optional; create a creative name from the role if none is given.
  user: optional; use the same user context as the orchestrator if none is given.
  what: optional; create a basic role, personality, and style from the agent role and your own orchestrator flavor if none is given.
"""


class AgentRuntime:
    def __init__(self, store: Store):
        self.store = store

    def workspace_context(self, agent: Agent, recent_events: list[dict[str, Any]] | None = None) -> str:
        workspace = Path(agent.workspace)
        parts: list[str] = []
        for filename in OPENCLAW_WORKSPACE_FILES:
            path = workspace / filename
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                parts.append(f"## {filename}\n{text}")
        if recent_events:
            transcript = self._format_recent_events(recent_events)
            if transcript:
                parts.append(f"## Recent Session Context\n{transcript}")
        return "\n\n".join([*parts, TOOL_INSTRUCTIONS, self.store.agent_registry_summary()])

    def run_task(
        self,
        agent: Agent,
        message: str,
        session_id: str,
        task_id: str | None = None,
        parent_task_id: str | None = None,
        on_progress: Callable[[str], None] | None = None,
        channel: str = "",
        source: str = "",
    ) -> str:
        if task_id is None and parent_task_id is None:
            task = self.store.create_task(
                title=message,
                agent_id=agent.id,
                session_id=session_id,
                message=message,
                channel=channel,
                source=source,
                assignee_id=agent.id,
            )
            task_id = task.id
            self._progress(on_progress, f"Task started: {task.title}")
        recent_limit = int((agent.context or {}).get("recentTurns", 16))
        recent_events = self.store.recent_session_events(session_id, recent_limit)
        self.store.append_session_event(session_id, {"role": "user", "content": message})
        bootstrap_response = Bootstrapper(self.store).handle(agent, message)
        if bootstrap_response is not None:
            if task_id:
                self.store.update_task(task_id, "blocked", "Bootstrap is waiting for user context.", bootstrap_response)
            self.store.append_session_event(session_id, {"role": "assistant", "content": bootstrap_response})
            return bootstrap_response
        if agent.model == "mock:echo":
            response = self._mock_response(agent, message)
        else:
            try:
                response = ProviderRunner(self.store.config(), self.store.home).run(
                    agent.model,
                    self.workspace_context(agent, recent_events),
                    message,
                )
            except ProviderError as exc:
                response = f"Provider error: {exc}"
        response = self._maybe_execute_tool(agent, response, task_id, on_progress)
        if task_id:
            status = self._status_from_response(response)
            self.store.update_task(task_id, status, f"Task {status}.", response)
            if status == "completed":
                self._progress(on_progress, f"Task completed: {self.store.get_task(task_id).title}")
            elif status == "blocked":
                self._progress(on_progress, f"Task blocked: {self.store.get_task(task_id).title}")
        self.store.append_session_event(session_id, {"role": "assistant", "content": response})
        return response

    def _mock_response(self, agent: Agent, message: str) -> str:
        if agent.id == "main" and "create" in message.lower() and "agent" in message.lower():
            return (
                "I can create agents from the control UI or API now. "
                "Use Agents -> Create, assign an authorized model, then bind a Telegram bot."
            )
        return f"{agent.name} received: {message}"

    def _format_recent_events(self, events: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for event in events:
            role = event.get("role", "unknown")
            content = str(event.get("content", "")).strip()
            if not content:
                continue
            if len(content) > 1800:
                content = content[:1800].rstrip() + "..."
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)

    def _maybe_execute_tool(
        self,
        source_agent: Agent,
        response: str,
        active_task_id: str | None = None,
        on_progress: Callable[[str], None] | None = None,
        depth: int = 0,
    ) -> str:
        call = self._parse_tool_call(response)
        if not call:
            return response
        tool = call.get("oclite_tool")
        args = call.get("args") or {}
        try:
            if tool == "create_agent":
                if not self._is_orchestrator(source_agent):
                    return "Only the orchestrator agent can create delegate agents."
                agent = self.store.create_agent(args)
                return (
                    f"Created agent '{agent.id}' ({agent.name}).\n"
                    f"Role: {agent.role}\n"
                    f"Model: {agent.model}\n"
                    f"Workspace: {agent.workspace}"
                )
            if tool == "list_agents":
                agents = self.store.list_agents()
                return "\n".join(
                    f"- {agent.id}: {agent.name} | {agent.model} | {agent.status} | "
                    f"bootstrap={(agent.bootstrap or {}).get('status', 'new')} | {agent.workspace}"
                    for agent in agents
                )
            if tool == "delete_agent":
                if not self._is_orchestrator(source_agent):
                    return "Only the orchestrator agent can delete delegate agents."
                result = self.store.delete_agent(args["agentId"], bool(args.get("deleteWorkspace", False)))
                return f"Deleted agent '{result['deleted']}'. Workspace deleted: {result['workspaceDeleted']}."
            if tool == "seed_agent":
                if not self._is_orchestrator(source_agent):
                    return "Only the orchestrator agent can seed delegate agents."
                agent = self.store.seed_agent(args["agentId"], args.get("user"), args.get("what"))
                return f"Seeded agent '{agent.id}' and marked bootstrap complete."
            if tool == "delegate_task":
                if not self._is_orchestrator(source_agent):
                    return "Only the orchestrator agent can delegate tasks to other agents."
                if not active_task_id:
                    return "Cannot delegate without an active parent task."
                target = self.store.get_agent(args["agentId"])
                if not target:
                    return f"Cannot delegate: unknown agent '{args['agentId']}'."
                if (target.bootstrap or {}).get("status") != "complete":
                    target = self.store.seed_agent(target.id)
                session = self.store.create_or_touch_session(
                    target,
                    "delegate",
                    source_agent.id,
                    "runtime",
                )
                child_task = self.store.create_task(
                    title=args.get("task", ""),
                    agent_id=target.id,
                    session_id=session.id,
                    message=args.get("task", ""),
                    channel="delegate",
                    source=source_agent.id,
                    parent_id=active_task_id,
                    assignee_id=target.id,
                )
                self.store.update_task(active_task_id, "in_progress", f"Delegated child task to {target.id}.")
                self._progress(on_progress, f"Delegated to {target.name}. Waiting for response.")
                result = self.run_task(
                    target,
                    args.get("task", ""),
                    session.id,
                    task_id=child_task.id,
                    parent_task_id=active_task_id,
                    on_progress=on_progress,
                    channel="delegate",
                    source=source_agent.id,
                )
                self.store.update_task(active_task_id, "in_progress", f"Received response from {target.id}.")
                self._progress(on_progress, f"Response received from {target.name}.")
                if source_agent.model != "mock:echo" and depth < 3:
                    assessment = self._assess_delegate_result(source_agent, active_task_id, target, result)
                    return self._maybe_execute_tool(source_agent, assessment, active_task_id, on_progress, depth + 1)
                return f"Delegated to {target.id}.\n\n{result}"
            return f"Unknown OCLite tool '{tool}'."
        except Exception as exc:
            return f"OCLite tool error: {type(exc).__name__}: {exc}"

    def _parse_tool_call(self, response: str) -> dict[str, Any] | None:
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and data.get("oclite_tool"):
            return data
        return None

    def _is_orchestrator(self, agent: Agent) -> bool:
        return agent.id == self.store.config()["runtime"].get("defaultAgent", "main")

    def _assess_delegate_result(self, source_agent: Agent, task_id: str, target: Agent, result: str) -> str:
        parent = self.store.get_task(task_id)
        parent_message = parent.message if parent else "Unknown parent task"
        message = (
            "A delegate agent has returned a child task result.\n\n"
            f"Parent task:\n{parent_message}\n\n"
            f"Delegate agent: {target.id} ({target.name})\n\n"
            f"Delegate result:\n{result}\n\n"
            "Assess whether the parent task is now complete, blocked pending user input/approval, "
            "or needs one more delegate task. If one more delegation is required, return exactly one "
            "OCLite delegate_task JSON object. Otherwise reply to the user with the completed answer "
            "or the specific input/approval needed."
        )
        try:
            return ProviderRunner(self.store.config(), self.store.home).run(
                source_agent.model,
                self.workspace_context(source_agent, []),
                message,
            )
        except ProviderError as exc:
            return f"Provider error while assessing delegate result: {exc}\n\nDelegate result:\n{result}"

    def _status_from_response(self, response: str) -> str:
        lowered = response.lower()
        if "provider error:" in lowered or "runtime error:" in lowered or "tool error:" in lowered:
            return "blocked"
        if "need approval" in lowered or "need input" in lowered or "pending user" in lowered:
            return "blocked"
        return "completed"

    def _progress(self, callback: Callable[[str], None] | None, message: str) -> None:
        if callback:
            callback(message)

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
            response = self.runtime.run_task(
                agent,
                text,
                session.id,
                on_progress=lambda update: self._send(token, chat_id, update),
                channel="telegram",
                source=sender_id,
            )
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
