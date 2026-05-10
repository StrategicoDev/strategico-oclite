from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .models import Agent, SessionMeta, TaskRecord, ensure_openclaw_workspace, new_id, utc_now


DEFAULT_ALLOWED_MODELS = ["mock:echo"]
DEFAULT_TOOLS = ["read_file", "write_file", "list_files", "create_agent", "delegate_task"]
DEFAULT_PROVIDERS = {
    "openai": {
        "apiKeyEnv": "OPENAI_API_KEY",
        "baseUrl": "https://api.openai.com/v1",
        "maxOutputTokens": 1200,
        "timeoutSeconds": 60,
    },
    "openai-codex": {
        "apiKeyEnv": "OPENAI_API_KEY",
        "baseUrl": "https://api.openai.com/v1",
        "codexBaseUrl": "https://chatgpt.com/backend-api/codex",
        "maxOutputTokens": 1200,
        "timeoutSeconds": 120,
    },
}


class Store:
    def __init__(self, home: Path | None = None):
        self.home = home or Path(os.environ.get("OCLITE_HOME", ".oclite")).expanduser().resolve()
        self.config_path = self.home / "config.json"
        self.agents_dir = self.home / "agents"
        self.workspaces_dir = self.home / "workspaces"
        self.sessions_dir = self.home / "sessions"
        self.tasks_dir = self.home / "tasks"
        self.logs_dir = self.home / "logs"

    def setup(self, main_workspace: str | None = None) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(exist_ok=True)
        self.workspaces_dir.mkdir(exist_ok=True)
        self.sessions_dir.mkdir(exist_ok=True)
        self.tasks_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)
        if not self.config_path.exists():
            self._write_config(
                {
                    "runtime": {
                        "defaultAgent": "main",
                        "staleAfterHours": 24,
                        "archiveAfterDays": 7,
                        "deleteAfterDays": 30,
                        "maxActivePerAgent": 5,
                    },
                    "models": {"allowed": DEFAULT_ALLOWED_MODELS, "default": "mock:echo"},
                    "providers": DEFAULT_PROVIDERS,
                    "telegram": {"bots": {}, "allowlist": [], "detectedSenders": []},
                }
            )
        if not (self.agents_dir / "main.json").exists():
            workspace = Path(main_workspace).expanduser().resolve() if main_workspace else self.workspaces_dir / "main"
            ensure_openclaw_workspace(workspace, "Main", "Primary OCLite orchestrator agent")
            agent = Agent(
                id="main",
                name="Main",
                role="Primary OCLite orchestrator agent",
                workspace=str(workspace),
                model=self.config()["models"]["default"],
                identity={"name": "Main", "theme": "orchestration", "emoji": "", "avatar": ""},
                tools=DEFAULT_TOOLS,
            )
            self.save_agent(agent)
        elif main_workspace:
            agent = self.get_agent("main")
            if agent:
                self.set_agent_workspace(agent.id, main_workspace)

    def config(self) -> dict[str, Any]:
        self.setup_dirs_only()
        if not self.config_path.exists():
            self.setup()
        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        changed = self._ensure_config_defaults(config)
        if changed:
            self.save_config(config)
        return config

    def save_config(self, config: dict[str, Any]) -> None:
        self._write_config(config)

    def setup_dirs_only(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.agents_dir.mkdir(exist_ok=True)
        self.workspaces_dir.mkdir(exist_ok=True)
        self.sessions_dir.mkdir(exist_ok=True)
        self.tasks_dir.mkdir(exist_ok=True)
        self.logs_dir.mkdir(exist_ok=True)

    def _write_config(self, config: dict[str, Any]) -> None:
        self.config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

    def _ensure_config_defaults(self, config: dict[str, Any]) -> bool:
        changed = False
        if "providers" not in config:
            config["providers"] = DEFAULT_PROVIDERS
            changed = True
        else:
            for provider, defaults in DEFAULT_PROVIDERS.items():
                if provider not in config["providers"]:
                    config["providers"][provider] = defaults
                    changed = True
                else:
                    for key, value in defaults.items():
                        if key not in config["providers"][provider]:
                            config["providers"][provider][key] = value
                            changed = True
        return changed

    def list_agents(self) -> list[Agent]:
        self.setup()
        agents: list[Agent] = []
        for path in sorted(self.agents_dir.glob("*.json")):
            agents.append(Agent.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        return agents

    def get_agent(self, agent_id: str) -> Agent | None:
        path = self.agents_dir / f"{agent_id}.json"
        if not path.exists():
            return None
        return Agent.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_agent(self, agent: Agent) -> None:
        self.setup_dirs_only()
        (self.agents_dir / f"{agent.id}.json").write_text(
            json.dumps(agent.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def set_agent_workspace(self, agent_id: str, workspace: str) -> Agent:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent '{agent_id}'")
        path = Path(workspace).expanduser().resolve()
        ensure_openclaw_workspace(path, agent.name, agent.role)
        agent.workspace = str(path)
        self.save_agent(agent)
        return agent

    def set_agent_model(self, agent_id: str, model: str) -> Agent:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent '{agent_id}'")
        config = self.config()
        if model not in config["models"]["allowed"]:
            raise ValueError(f"Model '{model}' is not authorized")
        agent.model = model
        self.save_agent(agent)
        return agent

    def set_agent_context(self, agent_id: str, recent_turns: int) -> Agent:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent '{agent_id}'")
        recent_turns = max(0, min(int(recent_turns), 100))
        agent.context = {**(agent.context or {}), "recentTurns": recent_turns}
        self.save_agent(agent)
        return agent

    def reset_agent_bootstrap(self, agent_id: str) -> Agent:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent '{agent_id}'")
        agent.bootstrap = {}
        self.save_agent(agent)
        return agent

    def delete_agent(self, agent_id: str, delete_workspace: bool = False) -> dict[str, Any]:
        if agent_id == self.config()["runtime"].get("defaultAgent", "main"):
            raise ValueError("Cannot delete the default orchestrator agent")
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent '{agent_id}'")
        agent_path = self.agents_dir / f"{agent_id}.json"
        if agent_path.exists():
            agent_path.unlink()
        if delete_workspace:
            workspace = Path(agent.workspace).resolve()
            root = self.workspaces_dir.resolve()
            if root in workspace.parents or workspace == root / agent_id:
                import shutil

                shutil.rmtree(workspace, ignore_errors=True)
            else:
                raise ValueError("Refusing to delete workspace outside OCLite workspaces directory")
        return {"deleted": agent_id, "workspaceDeleted": delete_workspace}

    def seed_agent(self, agent_id: str, user: str | None = None, what: str | None = None) -> Agent:
        agent = self.get_agent(agent_id)
        if not agent:
            raise ValueError(f"Unknown agent '{agent_id}'")
        workspace = Path(agent.workspace)
        self._seed_agent_context(
            workspace,
            agent,
            user or self._main_user_context(),
            what or self._default_agent_what(agent.name, agent.role),
        )
        agent.bootstrap = {
            "status": "complete",
            "phase": "complete",
            "completedAt": utc_now(),
            "source": "seed_agent",
        }
        self.save_agent(agent)
        return agent

    def agent_registry_summary(self) -> str:
        lines = ["## Live OCLite Agent Registry"]
        for agent in self.list_agents():
            bootstrap = (agent.bootstrap or {}).get("status", "new")
            bindings = ", ".join(f"{b.get('channel')}:{b.get('accountId')}" for b in agent.bindings) or "none"
            lines.append(
                f"- {agent.id}: {agent.name} | role={agent.role} | model={agent.model} | "
                f"status={agent.status} | bootstrap={bootstrap} | bindings={bindings} | workspace={agent.workspace}"
            )
        return "\n".join(lines)

    def list_tasks(self) -> list[dict[str, Any]]:
        self.setup()
        tasks: list[TaskRecord] = []
        for path in sorted(self.tasks_dir.glob("*.json")):
            tasks.append(TaskRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
        tasks.sort(key=lambda task: task.created_at, reverse=True)
        return [task.to_dict() for task in tasks]

    def get_task(self, task_id: str) -> TaskRecord | None:
        path = self.tasks_dir / f"{task_id}.json"
        if not path.exists():
            return None
        return TaskRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_task(self, task: TaskRecord) -> None:
        self.setup_dirs_only()
        task.updated_at = utc_now()
        (self.tasks_dir / f"{task.id}.json").write_text(
            json.dumps(task.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def create_task(
        self,
        title: str,
        agent_id: str,
        session_id: str,
        message: str,
        channel: str,
        source: str,
        parent_id: str | None = None,
        assignee_id: str | None = None,
    ) -> TaskRecord:
        if parent_id:
            parent = self.get_task(parent_id)
            if parent and parent.parent_id:
                raise ValueError("Child tasks cannot have child tasks")
        task = TaskRecord(
            id=new_id("task"),
            title=self._task_title(title or message),
            status="in_progress",
            agent_id=agent_id,
            session_id=session_id,
            parent_id=parent_id,
            assignee_id=assignee_id or agent_id,
            channel=channel,
            source=source,
            message=message,
            events=[{"ts": utc_now(), "status": "in_progress", "message": "Task started"}],
        )
        self.save_task(task)
        return task

    def update_task(self, task_id: str, status: str, message: str | None = None, result: str | None = None) -> TaskRecord:
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Unknown task '{task_id}'")
        if status not in {"in_progress", "completed", "blocked", "cancelled"}:
            raise ValueError(f"Unsupported task status '{status}'")
        task.status = status
        if result is not None:
            task.result = result
        if status in {"completed", "blocked", "cancelled"}:
            task.completed_at = utc_now()
        if message:
            task.events.append({"ts": utc_now(), "status": status, "message": message})
        self.save_task(task)
        return task

    def _task_title(self, text: str) -> str:
        cleaned = " ".join(str(text).split())
        if not cleaned:
            return "Untitled task"
        return cleaned[:96] + ("..." if len(cleaned) > 96 else "")

    def save_provider(self, provider_id: str, data: dict[str, Any]) -> dict[str, Any]:
        provider_id = provider_id.strip()
        if not provider_id:
            raise ValueError("Provider id is required")
        config = self.config()
        providers = config.setdefault("providers", {})
        existing = providers.get(provider_id, {})
        api_key_env = data.get("apiKeyEnv") or existing.get("apiKeyEnv") or f"{provider_id.upper()}_API_KEY"
        base_url = data.get("baseUrl") or existing.get("baseUrl") or "https://api.openai.com/v1"
        updated = {
            **existing,
            "apiKeyEnv": api_key_env,
            "baseUrl": base_url,
            "maxOutputTokens": int(data.get("maxOutputTokens", existing.get("maxOutputTokens", 1200))),
            "timeoutSeconds": int(data.get("timeoutSeconds", existing.get("timeoutSeconds", 60))),
        }
        if data.get("organization"):
            updated["organization"] = data["organization"]
        if data.get("project"):
            updated["project"] = data["project"]
        if data.get("profileId"):
            updated["profileId"] = data["profileId"]
        if data.get("apiKey"):
            updated["apiKey"] = data["apiKey"]
        providers[provider_id] = updated
        self.save_config(config)
        return updated

    def create_agent(self, data: dict[str, Any]) -> Agent:
        config = self.config()
        agent_id = data.get("id") or data.get("name", "agent").lower().replace(" ", "-")
        agent_id = "".join(ch for ch in agent_id if ch.isalnum() or ch in "-_").strip("-_")
        if not agent_id:
            agent_id = new_id("agent")
        if self.get_agent(agent_id):
            raise ValueError(f"Agent '{agent_id}' already exists")
        model = data.get("model") or config["models"]["default"]
        if model not in config["models"]["allowed"]:
            raise ValueError(f"Model '{model}' is not authorized")
        workspace = Path(data.get("workspace") or self.workspaces_dir / agent_id).expanduser().resolve()
        name = data.get("name") or agent_id.title()
        role = data.get("role") or "OCLite worker agent"
        ensure_openclaw_workspace(workspace, name, role)
        user_context = data.get("user") or self._main_user_context()
        what = data.get("what") or self._default_agent_what(name, role)
        agent = Agent(
            id=agent_id,
            name=name,
            role=role,
            workspace=str(workspace),
            model=model,
            identity={
                "name": data.get("identity", {}).get("name", name),
                "theme": data.get("identity", {}).get("theme", role),
                "emoji": data.get("identity", {}).get("emoji", ""),
                "avatar": data.get("identity", {}).get("avatar", ""),
            },
            tools=data.get("tools") or ["read_file", "write_file", "list_files"],
            bindings=data.get("bindings") or [],
            bootstrap={
                "status": "complete",
                "phase": "complete",
                "completedAt": utc_now(),
                "source": "create_agent",
            },
        )
        self._seed_agent_context(workspace, agent, user_context, what)
        self.save_agent(agent)
        return agent

    def _main_user_context(self) -> str:
        main = self.get_agent("main")
        if not main:
            return "Use the same user context as the orchestrator."
        user_path = Path(main.workspace) / "USER.md"
        if user_path.exists():
            text = user_path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                return text
        return "Use the same user context as the orchestrator."

    def _default_agent_what(self, name: str, role: str) -> str:
        return (
            f"{name} is a specialist agent focused on {role}. "
            "Work with the orchestrator's practical, clear, and task-oriented style. "
            "Be precise, proactive, and concise; ask for missing context only when necessary."
        )

    def _seed_agent_context(self, workspace: Path, agent: Agent, user_context: str, what: str) -> None:
        timestamp = utc_now()
        self._append_workspace_file(
            workspace / "IDENTITY.md",
            f"\n\n## OCLite Agent Seed ({timestamp})\n\nname: {agent.name}\nrole: {agent.role}\n\n{what}\n",
        )
        self._append_workspace_file(
            workspace / "SOUL.md",
            f"\n\n## OCLite Agent Seed ({timestamp})\n\n{what}\n",
        )
        self._append_workspace_file(
            workspace / "USER.md",
            f"\n\n## Inherited User Context ({timestamp})\n\n{user_context}\n",
        )
        self._append_workspace_file(
            workspace / "MEMORY.md",
            f"\n\n## Created By OCLite ({timestamp})\n\nAgent: {agent.name}\nRole: {agent.role}\n\n{what}\n",
        )
        self._append_workspace_file(
            workspace / "BOOTSTRAP.md",
            f"\n\n## Completed By OCLite Create Agent ({timestamp})\n\nAgent context and inherited user context were seeded at creation.\n",
        )

    def _append_workspace_file(self, path: Path, text: str) -> None:
        if not path.exists():
            path.write_text("", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def list_sessions(self) -> list[dict[str, Any]]:
        self.setup()
        sessions: list[dict[str, Any]] = []
        for path in sorted(self.sessions_dir.glob("*.meta.json")):
            sessions.append(json.loads(path.read_text(encoding="utf-8")))
        return sessions

    def create_or_touch_session(self, agent: Agent, channel: str, account_id: str, sender_id: str) -> SessionMeta:
        session_id = f"{agent.id}_{channel}_{account_id}_{sender_id}"
        meta_path = self.sessions_dir / f"{session_id}.meta.json"
        if meta_path.exists():
            meta = SessionMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
            meta.last_active_at = utc_now()
            meta.status = "active"
        else:
            meta = SessionMeta(
                id=session_id,
                agent_id=agent.id,
                channel=channel,
                account_id=account_id,
                sender_id=sender_id,
                model=agent.model,
            )
        meta_path.write_text(json.dumps(meta.to_dict(), indent=2) + "\n", encoding="utf-8")
        return meta

    def append_session_event(self, session_id: str, event: dict[str, Any]) -> None:
        event = {"ts": utc_now(), **event}
        with (self.sessions_dir / f"{session_id}.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event) + "\n")

    def recent_session_events(self, session_id: str, limit: int = 16) -> list[dict[str, Any]]:
        limit = max(0, int(limit))
        if limit == 0:
            return []
        path = self.sessions_dir / f"{session_id}.jsonl"
        if not path.exists():
            return []
        events: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("role") in {"user", "assistant", "system"} and event.get("content"):
                events.append(event)
        return events[-limit:]

    def prune_stale(self) -> int:
        config = self.config()
        from datetime import datetime, timezone, timedelta

        threshold = datetime.now(timezone.utc) - timedelta(hours=config["runtime"]["staleAfterHours"])
        count = 0
        for session in self.list_sessions():
            last_active = datetime.fromisoformat(session["lastActiveAt"])
            if session.get("status") == "active" and last_active < threshold:
                session["status"] = "stale"
                path = self.sessions_dir / f"{session['id']}.meta.json"
                path.write_text(json.dumps(session, indent=2) + "\n", encoding="utf-8")
                count += 1
        return count
