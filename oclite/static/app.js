let state = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}

async function refresh() {
  state = await api("/api/state");
  render();
}

function render() {
  document.querySelector("#home").textContent = state.home;
  document.querySelector("#agent-count").textContent = state.agents.length;
  document.querySelector("#session-count").textContent = state.sessions.length;
  document.querySelector("#sender-count").textContent = state.config.telegram.allowlist.length;

  renderModels();
  renderProviders();
  renderAgents();
  renderTelegram();
  renderSessions();
  renderWorkspaceFiles();
}

function renderModels() {
  const allowed = state.config.models.allowed;
  const defaultModel = state.config.models.default;
  document.querySelector("#models").innerHTML = allowed
    .map((model) => item(`<header><strong>${model}</strong>${model === defaultModel ? '<span class="pill">default</span>' : ""}</header>`))
    .join("");
  fillSelect("#agent-model", allowed, defaultModel);
  fillSelect("#set-agent-model", allowed, defaultModel);
  fillSelect("#model-provider", Object.keys(state.config.providers || {}), "openai-codex");
}

function renderProviders() {
  const providers = state.config.providers || {};
  document.querySelector("#providers").innerHTML =
    Object.entries(providers)
      .map(([id, provider]) =>
        item(`
          <header><strong>${id}</strong><span class="pill">${provider.apiKey ? "key saved" : provider.apiKeyEnv || "no key"}</span></header>
          <small>${provider.baseUrl || "https://api.openai.com/v1"}</small>
        `)
      )
      .join("") || item("<small>No providers yet</small>");
  fillSelect("#auth-provider", Object.keys(providers), "openai-codex");
  fillSelect("#oauth-provider", Object.keys(providers), "openai-codex");
  renderAuthProfiles();
}

async function renderAuthProfiles() {
  try {
    const profiles = await api("/api/auth/profiles");
    document.querySelector("#auth-profiles").innerHTML =
      profiles
        .map((profile) =>
          item(`
            <header><strong>${profile.providerId}:${profile.profileId}</strong><span class="pill">OAuth</span></header>
            <small>${profile.accountId || "account linked"} · expires ${new Date(profile.expires * 1000).toLocaleString()}</small>
          `)
        )
        .join("") || item("<small>No OAuth profiles yet</small>");
  } catch (error) {
    document.querySelector("#auth-profiles").innerHTML = item(`<small>${error.message}</small>`);
  }
}

function renderAgents() {
  document.querySelector("#agents").innerHTML = state.agents
    .map((agent) =>
      item(`
        <header><strong>${agent.name}</strong><span class="pill">${agent.status}</span></header>
        <small>${agent.id} · ${agent.model}</small><br />
        <small>bootstrap: ${(agent.bootstrap && agent.bootstrap.status) || "new"}</small><br />
        <small>${agent.role}</small><br />
        <small>${agent.workspace}</small>
      `)
    )
    .join("");
  fillSelect("#bind-agent", state.agents.map((agent) => agent.id));
  fillSelect("#task-agent", state.agents.map((agent) => agent.id));
  fillSelect("#workspace-agent", state.agents.map((agent) => agent.id));
  fillSelect("#model-agent", state.agents.map((agent) => agent.id));
  fillSelect("#bootstrap-agent", state.agents.map((agent) => agent.id));
  fillSelect("#seed-agent", state.agents.map((agent) => agent.id));
  fillSelect("#delete-agent", state.agents.filter((agent) => agent.id !== "main").map((agent) => agent.id));
  fillSelect("#diagnostics-agent", state.agents.map((agent) => agent.id));
}

function renderTelegram() {
  const bots = Object.values(state.config.telegram.bots);
  const allowlist = state.config.telegram.allowlist;
  const detected = state.config.telegram.detectedSenders;
  fillSelect("#bind-bot", bots.map((bot) => bot.accountId));
  const bindings = state.agents.flatMap((agent) =>
    agent.bindings.map((binding) => `${binding.channel}:${binding.accountId} -> ${agent.id}`)
  );
  document.querySelector("#telegram").innerHTML = [
    item(`<header><strong>Bots</strong><span class="pill">${bots.length}</span></header>${bots.map((bot) => `<small>${bot.accountId} · ${bot.tokenEnv || "stored token"}</small><br />`).join("") || "<small>No bots yet</small>"}`),
    item(`<header><strong>Allowed Senders</strong><span class="pill">${allowlist.length}</span></header>${allowlist.map((id) => `<small>${id}</small><br />`).join("") || "<small>No allowed senders yet</small>"}`),
    item(`<header><strong>Detected Senders</strong><span class="pill">${detected.length}</span></header>${detected.map((id) => `<small>${id}</small><br />`).join("") || "<small>No detected senders yet</small>"}`),
    item(`<header><strong>Bindings</strong><span class="pill">${bindings.length}</span></header>${bindings.map((line) => `<small>${line}</small><br />`).join("") || "<small>No bindings yet</small>"}`),
  ].join("");
}

function renderSessions() {
  document.querySelector("#sessions").innerHTML =
    state.sessions
      .map((session) =>
        item(`
          <header><strong>${session.id}</strong><span class="pill">${session.status}</span></header>
          <small>${session.agentId} · ${session.channel}:${session.accountId}</small><br />
          <small>last active ${session.lastActiveAt}</small>
        `)
      )
      .join("") || item("<small>No sessions yet</small>");
}

function renderWorkspaceFiles() {
  document.querySelector("#workspace-files").innerHTML = state.workspaceFiles
    .map((file) => `<span class="chip">${file}</span>`)
    .join("");
}

function item(html) {
  return `<div class="item">${html}</div>`;
}

function fillSelect(selector, values, selected) {
  const select = document.querySelector(selector);
  select.innerHTML = values.map((value) => `<option ${value === selected ? "selected" : ""}>${value}</option>`).join("");
}

function formJson(form) {
  const data = Object.fromEntries(new FormData(form).entries());
  for (const [key, value] of Object.entries(data)) {
    if (typeof value === "string") data[key] = value.trim();
  }
  return data;
}

function wireForm(selector, path, transform) {
  document.querySelector(selector).addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    try {
      const payload = transform ? transform(form) : formJson(form);
      await api(path, { method: "POST", body: JSON.stringify(payload) });
      form.reset();
      await refresh();
    } catch (error) {
      alert(error.message);
    }
  });
}

document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#prune").addEventListener("click", async () => {
  await api("/api/sessions/prune", { method: "POST", body: "{}" });
  await refresh();
});

wireForm("#agent-form", "/api/agents");
wireForm("#workspace-form", "/api/agents/workspace");
wireForm("#agent-model-form", "/api/agents/model");
wireForm("#bootstrap-reset-form", "/api/agents/bootstrap/reset");
wireForm("#agent-seed-form", "/api/agents/seed");
wireForm("#agent-delete-form", "/api/agents/delete", (form) => {
  const data = formJson(form);
  data.deleteWorkspace = form.elements.deleteWorkspace.checked;
  return data;
});
wireForm("#bot-form", "/api/telegram/bots", (form) => {
  const data = formJson(form);
  const tokenValue = data.token || "";
  delete data.token;
  if (/^\d+:[A-Za-z0-9_-]+$/.test(tokenValue)) {
    data.token = tokenValue;
  } else if (/^\d+$/.test(data.accountId || "") && /^[A-Za-z0-9_-]{20,}$/.test(tokenValue)) {
    data.token = `${data.accountId}:${tokenValue}`;
  } else {
    data.tokenEnv = tokenValue;
  }
  return data;
});
wireForm("#allow-form", "/api/telegram/allow");
wireForm("#bind-form", "/api/agents/bind");
wireForm("#model-form", "/api/models/allow", (form) => {
  const data = formJson(form);
  data.makeDefault = form.elements.makeDefault.checked;
  if (data.providerId && data.model && !data.model.includes("/") && !data.model.includes(":")) {
    data.model = `${data.providerId}/${data.model}`;
  }
  delete data.providerId;
  return data;
});
wireForm("#provider-form", "/api/providers");

document.querySelector("#provider-auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/providers/auth", {
      method: "POST",
      body: JSON.stringify(formJson(event.currentTarget)),
    });
    document.querySelector("#provider-auth-output").textContent =
      `Auth OK. ${result.modelCount} models available.\n` + result.models.join("\n");
  } catch (error) {
    document.querySelector("#provider-auth-output").textContent = error.message;
  }
});

document.querySelector("#oauth-start-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/oauth/start", {
      method: "POST",
      body: JSON.stringify(formJson(event.currentTarget)),
    });
    document.querySelector("#oauth-output").textContent =
      `Opening OAuth for ${result.providerId}:${result.profileId}\n${result.authUrl}\n\nCallback: ${result.redirectUri}`;
    window.open(result.authUrl, "_blank", "noopener,noreferrer");
  } catch (error) {
    document.querySelector("#oauth-output").textContent = error.message;
  }
});

document.querySelector("#oauth-complete-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/oauth/complete", {
      method: "POST",
      body: JSON.stringify(formJson(event.currentTarget)),
    });
    document.querySelector("#oauth-output").textContent = `OAuth linked: ${result.providerId}:${result.profileId}`;
    await refresh();
  } catch (error) {
    document.querySelector("#oauth-output").textContent = error.message;
  }
});

document.querySelector("#diagnostics-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const params = new URLSearchParams(formJson(event.currentTarget));
  try {
    const result = await api(`/api/diagnostics/agent?${params.toString()}`);
    document.querySelector("#diagnostics-output").textContent = JSON.stringify(result, null, 2);
  } catch (error) {
    document.querySelector("#diagnostics-output").textContent = error.message;
  }
});

document.querySelector("#task-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const payload = formJson(event.currentTarget);
    const result = await api("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
    document.querySelector("#task-output").textContent = result.response;
    await refresh();
  } catch (error) {
    alert(error.message);
  }
});

refresh();
