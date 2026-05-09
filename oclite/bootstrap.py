from __future__ import annotations

from pathlib import Path

from .models import Agent, utc_now
from .store import Store


BOOTSTRAP_PROMPT = """Before we begin, I need to bootstrap this workspace.

Please reply with:

Agent: who I am, my role, tone, and responsibilities.
User: who you are, what I should call you, your preferences, and what you want this OCLite instance to help with.

You can answer naturally; I will save it into the OpenClaw workspace context."""


class Bootstrapper:
    def __init__(self, store: Store):
        self.store = store

    def handle(self, agent: Agent, message: str) -> str | None:
        state = agent.bootstrap or {}
        if state.get("status") == "complete":
            return None
        if state.get("phase") != "awaiting_context":
            agent.bootstrap = {
                "status": "pending",
                "phase": "awaiting_context",
                "requestedAt": utc_now(),
            }
            self.store.save_agent(agent)
            return BOOTSTRAP_PROMPT
        self._save_context(agent, message)
        agent.bootstrap = {
            **agent.bootstrap,
            "status": "complete",
            "phase": "complete",
            "completedAt": utc_now(),
        }
        self.store.save_agent(agent)
        return "Bootstrap saved. I now have the initial agent and user context in the workspace. What would you like to work on first?"

    def _save_context(self, agent: Agent, message: str) -> None:
        workspace = Path(agent.workspace)
        workspace.mkdir(parents=True, exist_ok=True)
        agent_context, user_context = self._split_context(message)
        timestamp = utc_now()
        self._append(
            workspace / "IDENTITY.md",
            f"\n\n## OCLite Bootstrap Identity ({timestamp})\n\n{agent_context or message.strip()}\n",
        )
        self._append(
            workspace / "USER.md",
            f"\n\n## OCLite Bootstrap User Context ({timestamp})\n\n{user_context or message.strip()}\n",
        )
        self._append(
            workspace / "MEMORY.md",
            f"\n\n## OCLite Bootstrap Memory ({timestamp})\n\nAgent context:\n{agent_context or 'Not specified.'}\n\nUser context:\n{user_context or message.strip()}\n",
        )
        self._append(
            workspace / "BOOTSTRAP.md",
            f"\n\n## Completed By OCLite ({timestamp})\n\n{message.strip()}\n",
        )

    def _split_context(self, message: str) -> tuple[str, str]:
        agent_lines: list[str] = []
        user_lines: list[str] = []
        active: list[str] | None = None
        for line in message.splitlines():
            lowered = line.strip().lower()
            if lowered.startswith("agent:"):
                active = agent_lines
                active.append(line.split(":", 1)[1].strip())
                continue
            if lowered.startswith("user:"):
                active = user_lines
                active.append(line.split(":", 1)[1].strip())
                continue
            if active is not None:
                active.append(line.strip())
        return "\n".join(line for line in agent_lines if line).strip(), "\n".join(line for line in user_lines if line).strip()

    def _append(self, path: Path, text: str) -> None:
        if not path.exists():
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

