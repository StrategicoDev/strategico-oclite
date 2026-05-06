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

The OpenAI API uses API keys for API authentication. OCLite does not implement OpenAI OAuth because OpenAI's API authentication is Bearer API-key based; OAuth in OpenAI docs applies to GPT Actions signing users into external services, not linking a ChatGPT subscription to local API calls.

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
