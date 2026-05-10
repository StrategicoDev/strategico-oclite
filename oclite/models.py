from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


OPENCLAW_WORKSPACE_FILES = [
    "AGENTS.md",
    "SOUL.md",
    "USER.md",
    "IDENTITY.md",
    "TOOLS.md",
    "HEARTBEAT.md",
    "BOOT.md",
    "BOOTSTRAP.md",
    "MEMORY.md",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class Agent:
    id: str
    name: str
    role: str
    workspace: str
    model: str
    status: str = "active"
    identity: dict[str, str] = field(default_factory=dict)
    tools: list[str] = field(default_factory=list)
    bindings: list[dict[str, str]] = field(default_factory=list)
    bootstrap: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=lambda: {"recentTurns": 16})
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "workspace": self.workspace,
            "model": self.model,
            "status": self.status,
            "identity": self.identity,
            "tools": self.tools,
            "bindings": self.bindings,
            "bootstrap": self.bootstrap,
            "context": self.context,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Agent":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            role=data.get("role", ""),
            workspace=data["workspace"],
            model=data.get("model", "mock:echo"),
            status=data.get("status", "active"),
            identity=data.get("identity", {}),
            tools=data.get("tools", []),
            bindings=data.get("bindings", []),
            bootstrap=data.get("bootstrap", {}),
            context=data.get("context", {"recentTurns": 16}),
            created_at=data.get("created_at", utc_now()),
        )


@dataclass
class SessionMeta:
    id: str
    agent_id: str
    channel: str
    account_id: str
    sender_id: str
    model: str
    created_at: str = field(default_factory=utc_now)
    last_active_at: str = field(default_factory=utc_now)
    status: str = "active"
    token_estimate: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agentId": self.agent_id,
            "channel": self.channel,
            "accountId": self.account_id,
            "senderId": self.sender_id,
            "model": self.model,
            "createdAt": self.created_at,
            "lastActiveAt": self.last_active_at,
            "status": self.status,
            "tokenEstimate": self.token_estimate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMeta":
        return cls(
            id=data["id"],
            agent_id=data.get("agentId", data.get("agent_id", "")),
            channel=data.get("channel", "telegram"),
            account_id=data.get("accountId", data.get("account_id", "")),
            sender_id=data.get("senderId", data.get("sender_id", "")),
            model=data.get("model", "mock:echo"),
            created_at=data.get("createdAt", data.get("created_at", utc_now())),
            last_active_at=data.get("lastActiveAt", data.get("last_active_at", utc_now())),
            status=data.get("status", "active"),
            token_estimate=int(data.get("tokenEstimate", data.get("token_estimate", 0))),
        )


@dataclass
class TaskRecord:
    id: str
    title: str
    status: str
    agent_id: str
    session_id: str
    parent_id: str | None = None
    assignee_id: str | None = None
    channel: str = ""
    source: str = ""
    message: str = ""
    result: str = ""
    events: list[dict[str, str]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "agentId": self.agent_id,
            "sessionId": self.session_id,
            "parentId": self.parent_id,
            "assigneeId": self.assignee_id,
            "channel": self.channel,
            "source": self.source,
            "message": self.message,
            "result": self.result,
            "events": self.events,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "completedAt": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskRecord":
        return cls(
            id=data["id"],
            title=data.get("title", data["id"]),
            status=data.get("status", "in_progress"),
            agent_id=data.get("agentId", data.get("agent_id", "")),
            session_id=data.get("sessionId", data.get("session_id", "")),
            parent_id=data.get("parentId", data.get("parent_id")),
            assignee_id=data.get("assigneeId", data.get("assignee_id")),
            channel=data.get("channel", ""),
            source=data.get("source", ""),
            message=data.get("message", ""),
            result=data.get("result", ""),
            events=data.get("events", []),
            created_at=data.get("createdAt", data.get("created_at", utc_now())),
            updated_at=data.get("updatedAt", data.get("updated_at", utc_now())),
            completed_at=data.get("completedAt", data.get("completed_at")),
        )


def ensure_openclaw_workspace(path: Path, agent_name: str, role: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "memory").mkdir(exist_ok=True)
    defaults = {
        "AGENTS.md": f"# {agent_name}\n\nRole: {role}\n",
        "SOUL.md": f"# Soul\n\nYou are {agent_name}. {role}\n",
        "USER.md": "# User\n\nUse this file for user preferences and operating context.\n",
        "IDENTITY.md": f"# Identity\n\nname: {agent_name}\nrole: {role}\n",
        "TOOLS.md": """# Tools

Allowed tools are managed by OCLite runtime metadata.

## OCLite Runtime Tool Protocol

When you need to operate the platform, return exactly one JSON object and no extra prose.

Create an agent:
{"oclite_tool":"create_agent","args":{"id":"researcher","name":"Researcher","role":"Research and analysis agent","user":"same user as orchestrator","what":"A focused research agent with a precise, source-aware style.","model":"openai-codex/gpt-5.5"}}

List agents:
{"oclite_tool":"list_agents","args":{}}

Delegate a task:
{"oclite_tool":"delegate_task","args":{"agentId":"researcher","task":"Summarize the project state."}}

After a delegate returns, OCLite asks the orchestrator for this exact decision JSON:
{"oclite_orchestration":"completed","message_to_user":"Final user-facing answer."}
{"oclite_orchestration":"blocked","message_to_user":"Specific user input or approval needed."}
{"oclite_orchestration":"delegate_again","message_to_user":"Why another child task is needed.","next_delegate":{"agentId":"coder","task":"Implement sprint 1."}}

Only the orchestrator/default agent may create, delete, seed, or delegate to agents.
Delegate tasks are one level deep only. Child tasks return results to the orchestrator and must not create child tasks.
For app/software build requests, the orchestrator should use a solution architect agent for scope/spec/sprint planning, a coder agent for implementation, and repeat one-level child tasks until the final deliverable is ready.
""",
        "HEARTBEAT.md": "# Heartbeat\n\nNo heartbeat behavior configured yet.\n",
        "BOOT.md": "# Boot\n\nLoad workspace files, then follow the active task.\n",
        "BOOTSTRAP.md": "# Bootstrap\n\nThis workspace is ready for first-run initialization.\n",
        "MEMORY.md": "# Memory\n\nLong-lived memory goes here.\n",
    }
    for filename in OPENCLAW_WORKSPACE_FILES:
        target = path / filename
        if not target.exists():
            target.write_text(defaults[filename], encoding="utf-8")
