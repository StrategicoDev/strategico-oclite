# OCLite

OCLite is a lightweight OpenClaw-compatible gateway/runtime for basic agentic task execution.

The MVP keeps a deliberately small surface:

- OpenClaw-compatible agent workspaces.
- A main orchestrator agent.
- Additional agents with roles, identities, workspaces, and assigned models.
- Telegram as the only external communication channel.
- Sender allowlist plus bot-to-agent bindings.
- Lightweight filesystem sessions.
- Minimal local control UI.
- OpenAI-compatible provider execution through the Responses API.
- First-contact bootstrap that asks for agent/user context and saves it into OpenClaw workspace files.
- Recent session context is injected into each model call so agents can follow the active conversation.

## Quick Start

```bash
python -m oclite setup
python -m oclite run --port 8787
```

Then open:

```text
http://localhost:8787
```

The app stores runtime state in `./.oclite` by default. Set `OCLITE_HOME` to use another location.

## One-Line macOS/Linux Install

After this project is pushed to GitHub, install or update it with:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/StrategicoDev/strategico-oclite/main/scripts/install-mac-linux.sh)"
```

The installer:

- clones or updates the code in `~/.oclite-src`
- keeps runtime state in `~/.oclite`
- creates `~/.local/bin/oclite`
- adds `~/.local/bin` to your shell profile when needed
- runs `oclite setup`
- leaves existing OpenClaw installs untouched

Start the UI:

```bash
oclite run --host 127.0.0.1 --port 8787
```

If your current shell has not reloaded its profile yet:

```bash
~/.local/bin/oclite run --host 127.0.0.1 --port 8787
```

To attach a copied OpenClaw workspace:

```bash
oclite setup --main-workspace "$HOME/.oclite/workspaces/main"
```

## OpenClaw Workspace Compatibility

OCLite preserves the OpenClaw workspace contract. Agent workspaces contain these files exactly:

```text
AGENTS.md
SOUL.md
USER.md
IDENTITY.md
TOOLS.md
HEARTBEAT.md
BOOT.md
BOOTSTRAP.md
MEMORY.md
memory/
```

Runtime metadata lives outside those files so existing OpenClaw workspaces can be pointed at directly.

## Bootstrap

On first contact, each agent pauses normal model execution and asks for initial context:

```text
Agent: who I am, my role, tone, and responsibilities.
User: who you are, what I should call you, your preferences, and what you want this OCLite instance to help with.
```

The reply is saved into:

```text
IDENTITY.md
USER.md
MEMORY.md
BOOTSTRAP.md
```

After that, the agent runs normally using the saved workspace context.

## Session Context

OCLite stores session transcripts as JSONL and injects recent user/assistant/system messages into each model call under `Recent Session Context`.

Each agent has its own context window setting. The default is 16 recent messages, and it can be changed from Agents -> Conversation Context.

This keeps follow-up requests coherent without adding a database or long-term vector memory.

## Runtime Tool Protocol

Agents can operate OCLite by returning a single JSON tool call. The runtime executes the call and sends the result back to the user.

## Task Orchestration

OCLite logs every external agent request as a parent task. When the orchestrator delegates, OCLite creates a child task assigned to the delegate agent, waits synchronously for the delegate response, and writes the child result back into the parent flow.

Only one task level is allowed below a parent task. Delegate agents cannot create child tasks. After a delegate responds, the orchestrator must decide whether the parent task is complete, blocked pending user input/approval, or needs another one-level child task.

Task statuses are `in_progress`, `completed`, `blocked`, and `cancelled`. The control UI includes a Tasks dashboard for monitoring parent and child task sessions.

Create an agent:

```json
{"oclite_tool":"create_agent","args":{"id":"researcher","name":"Researcher","role":"Research and analysis agent","user":"same user as orchestrator","what":"A focused research agent with a precise, source-aware style.","model":"openai-codex/gpt-5.5"}}
```

When creating agents, the orchestrator should ask for or infer:

- `name`: optional; generate a creative name from the role if none is given.
- `user`: optional; inherit the orchestrator's user context if none is given.
- `what`: optional; generate role, personality, and style from the agent role and orchestrator flavor if none is given.

Agents created through the runtime tool are seeded into `IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`, and marked bootstrap-complete so delegation can start immediately.

List agents:

```json
{"oclite_tool":"list_agents","args":{}}
```

Delegate a task:

```json
{"oclite_tool":"delegate_task","args":{"agentId":"researcher","task":"Summarize the project state."}}
```

The tool contract is injected into agent context and written into new agents' `TOOLS.md`.

OCLite injects a live agent registry on every turn, including model, status, bootstrap state, bindings, and workspace path.

When the orchestrator delegates to an agent whose bootstrap is incomplete, OCLite seeds that agent from the orchestrator context first, then runs the delegated task.

Only the default orchestrator agent may create, delete, or seed delegate agents.

## Telegram Linking

Telegram is the only supported MVP communication channel.

Linking is intentionally simple:

1. Add a bot in the UI with a bot id and token env var.
2. Start the runtime with that env var set.
3. Send `/start` to the Telegram bot.
4. The sender id appears in the UI.
5. Click allow, then bind the bot id to an agent.

Only allowed sender ids can talk to bound agents.

The bot token field accepts any of these:

```text
TELEGRAM_BOT_TOKEN_MAIN
8697975956:AAF...
AAF...
```

When you enter only the token secret, OCLite combines it with the bot id.

## Provider Execution

`mock:echo` is built in for smoke testing.

OpenAI-compatible models use either `provider/model` or `provider:model`:

```text
openai/gpt-5.5
openai:gpt-5.5
openai-codex/gpt-5.5
```

The default providers are `openai` and `openai-codex`, both using:

```text
https://api.openai.com/v1
OPENAI_API_KEY
```

You can also save a provider API key in the control UI. Env vars are cleaner for a longer-running Mac install:

```bash
export OPENAI_API_KEY="sk-..."
oclite run --host 127.0.0.1 --port 8787
```

The standard OpenAI API uses API keys for API authentication, and OCLite keeps that path available.

For `openai-codex/*`, OCLite also supports the OpenAI Codex/ChatGPT subscription OAuth flow used by OpenClaw:

- PKCE browser login through `https://auth.openai.com/oauth/authorize`
- local callback on `http://localhost:1455/auth/callback`
- scope: `openid profile email offline_access`
- Codex/OpenClaw authorize params: `id_token_add_organizations=true`, `codex_cli_simplified_flow=true`, `originator=pi`
- token exchange through `https://auth.openai.com/oauth/token`
- profile storage in `~/.oclite/auth-profiles.json`
- automatic refresh when an OAuth profile expires
- model calls route to `https://chatgpt.com/backend-api/codex/responses`, matching Codex CLI subscription auth

In the UI, use Providers -> Start OAuth with provider `openai-codex` and profile `default`. After the browser callback completes, set provider `openai-codex` to profile `default`, then assign an `openai-codex/...` model to the agent.

The control UI can:

- allow models
- set the default model
- assign a model to an existing agent
- configure provider API key/env/base URL
- test provider auth by listing available models

## CLI

```bash
python -m oclite setup
python -m oclite run --host 127.0.0.1 --port 8787
python -m oclite agents
python -m oclite sessions --prune-stale
```
