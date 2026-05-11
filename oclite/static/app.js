let state = null;
let activeView = "dashboard";
let selectedAgentId = "main";
let selectedTaskId = null;
let refreshInFlight = false;
let lastRefreshAt = null;
let taskLimit = normalizeTaskLimit(localStorage.getItem("ocliteTaskLimit") || 25);
let modelAuthStatus = {};
let providerModelOptions = {};

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
  if (refreshInFlight) return;
  refreshInFlight = true;
  setLiveStatus("Refreshing...");
  try {
    state = await api("/api/state");
    lastRefreshAt = new Date();
    render();
    setLiveStatus(`Live · updated ${lastRefreshAt.toLocaleTimeString()}`);
  } catch (error) {
    setLiveStatus(`Live refresh error: ${error.message}`);
    throw error;
  } finally {
    refreshInFlight = false;
  }
}

function render() {
  document.querySelector("#home").textContent = state.home;
  document.querySelector("#agent-count").textContent = state.agents.length;
  document.querySelector("#session-count").textContent = state.sessions.length;
  document.querySelector("#task-count").textContent = (state.tasks || []).length;
  document.querySelector("#sender-count").textContent = state.config.telegram.allowlist.length;
  renderAppMetadata();

  renderDashboard();
  renderModels();
  renderProviders();
  renderAgents();
  renderTelegram();
  renderTasks();
  renderSessions();
  renderWorkspaceFiles();
  showView(activeView);
}

function renderAppMetadata() {
  const app = state.app || {};
  const version = app.version || "0.0.0";
  document.querySelector("#version-badge").textContent = `v${version}`;
  const details = [app.name || "OCLite", app.branch, app.commit].filter(Boolean).join(" · ");
  document.querySelector("#release-meta").textContent = details || `OCLite v${version}`;
  document.querySelector("#release-notes").textContent = app.releaseNotes || "No release notes available.";
}

function renderDashboard() {
  const agents = state.agents || [];
  const sessions = state.sessions || [];
  const tasks = state.tasks || [];
  const telegram = state.config.telegram || {};
  const bots = Object.values(telegram.bots || {});
  const bindings = agents.flatMap((agent) => agent.bindings || []);
  const providers = state.config.providers || {};
  const aliases = state.config.models.aliases || {};
  const defaultModel = state.config.models.default;
  const bootstrapped = agents.filter((agent) => agent.bootstrap && agent.bootstrap.status === "complete").length;
  const stale = sessions.filter((session) => session.status === "stale").length;
  const active = sessions.filter((session) => session.status === "active").length;
  const inProgressTasks = tasks.filter((task) => task.status === "in_progress").length;
  const blockedTasks = tasks.filter((task) => task.status === "blocked").length;
  const completedTasks = tasks.filter((task) => task.status === "completed").length;

  document.querySelector("#dashboard-agents").innerHTML = `
    <strong>${agents.length}</strong>
    <small>${bootstrapped} bootstrapped · ${Math.max(agents.length - bootstrapped, 0)} pending</small>
    <small>Default orchestrator: ${state.config.runtime.defaultAgent}</small>
  `;
  document.querySelector("#dashboard-models").innerHTML = `
    <strong>${Object.keys(aliases).length}</strong>
    <small>Default: ${defaultModel}</small>
    <small>${Object.keys(providers).length} providers · ${(state.config.models.catalog || []).length} models</small>
  `;
  document.querySelector("#dashboard-channels").innerHTML = `
    <strong>${bots.length}</strong>
    <small>${telegram.allowlist.length} allowed senders · ${bindings.length} bindings</small>
    <small>Telegram only</small>
  `;
  document.querySelector("#dashboard-tasks").innerHTML = `
    <strong>${tasks.length}</strong>
    <small>${inProgressTasks} in progress · ${blockedTasks} blocked</small>
    <small>${completedTasks} completed</small>
  `;
  document.querySelector("#dashboard-sessions").innerHTML = `
    <strong>${sessions.length}</strong>
    <small>${active} active · ${stale} stale</small>
    <small>Retention: ${state.config.runtime.staleAfterHours}h stale threshold</small>
  `;
}

function renderTasks() {
  const tasks = state.tasks || [];
  const allParents = tasks.filter((task) => !task.parentId);
  const effectiveLimit = taskLimit > 0 ? taskLimit : allParents.length;
  const parents = allParents.slice(0, effectiveLimit);
  const childrenByParent = tasks.reduce((groups, task) => {
    if (task.parentId) {
      groups[task.parentId] = groups[task.parentId] || [];
      groups[task.parentId].push(task);
    }
    return groups;
  }, {});
  if (!parents.some((task) => task.id === selectedTaskId)) {
    selectedTaskId = parents[0] ? parents[0].id : null;
  }
  const selected = parents.find((task) => task.id === selectedTaskId);
  document.querySelector("#task-limit").value = String(taskLimit);
  document.querySelector("#task-limit-status").textContent = `Showing ${parents.length} of ${allParents.length}`;
  document.querySelector("#tasks").innerHTML =
    parents.map((task) => renderTaskRow(task, childrenByParent[task.id] || [])).join("") || item("<small>No tasks yet</small>");
  document.querySelector("#task-detail").innerHTML = renderTaskDetail(selected, selected ? childrenByParent[selected.id] || [] : []);
}

function renderTaskRow(task, children) {
  const current = currentTaskHolder(task, children);
  const childSummary = children.length
    ? `<small>${children.length} child ${children.length === 1 ? "task" : "tasks"} · latest: ${escapeHtml(current.childStatus)}</small>`
    : "<small>No child tasks</small>";
  return `
    <button class="task-row ${task.id === selectedTaskId ? "selected" : ""}" data-task-select="${escapeHtml(task.id)}">
      <span class="task-row-title">${escapeHtml(task.title)}</span>
      <span class="task-row-agent">${escapeHtml(current.agent)}</span>
      <span class="pill">${escapeHtml(current.status)}</span>
      ${childSummary}
    </button>
  `;
}

function renderTaskDetail(task, children) {
  if (!task) return item("<small>Select a task to see detail</small>");
  const events = (task.events || []).slice(-4);
  const childHtml = children
    .map(
      (child) => `
        <div class="item task-item">
          <header><strong>${escapeHtml(child.title)}</strong><span class="pill">${escapeHtml(child.status)}</span></header>
          <div class="task-meta">
            <small>child: ${escapeHtml(child.id)}</small>
            <small>agent: ${escapeHtml(child.assigneeId || child.agentId)}</small>
          </div>
          ${child.result ? `<div class="task-result compact">${escapeHtml(child.result)}</div>` : ""}
        </div>
      `
    )
    .join("");
  return item(`
    <div class="task-item">
      <header><strong>${escapeHtml(task.title)}</strong><span class="pill">${escapeHtml(task.status)}</span></header>
      <div class="task-meta">
        <small>${escapeHtml(task.id)}</small>
        <small>agent: ${escapeHtml(task.agentId)}</small>
        <small>${escapeHtml(task.channel || "runtime")} · ${escapeHtml(task.source || "local")}</small>
        <small>updated ${escapeHtml(task.updatedAt || "")}</small>
      </div>
      ${isTerminalTask(task) ? "" : `<button class="secondary task-cancel" data-task-cancel="${escapeHtml(task.id)}">Cancel Task</button>`}
      ${task.result ? `<div class="task-result">${escapeHtml(task.result)}</div>` : ""}
      ${
        events.length
          ? `<div class="task-events">${events
              .map((event) => `<small>${escapeHtml(event.ts || "")} · ${escapeHtml(event.status || "")}: ${escapeHtml(event.message || "")}</small>`)
              .join("")}</div>`
          : ""
      }
      ${childHtml}
    </div>
  `);
}

function currentTaskHolder(task, children) {
  const activeChild = [...children].reverse().find((child) => !isTerminalTask(child));
  const latestChild = children.length ? children[children.length - 1] : null;
  const child = activeChild || latestChild;
  if (child && task.status === "in_progress") {
    return {
      agent: child.assigneeId || child.agentId,
      status: child.status,
      childStatus: `${child.assigneeId || child.agentId} ${child.status}`,
    };
  }
  if (child) {
    return {
      agent: task.agentId,
      status: task.status,
      childStatus: `${child.assigneeId || child.agentId} ${child.status}`,
    };
  }
  return {
    agent: task.agentId,
    status: task.status,
    childStatus: "none",
  };
}

function showView(name) {
  activeView = name;
  document.querySelectorAll("[data-view]").forEach((view) => {
    view.classList.toggle("active", view.dataset.view === name);
  });
  document.querySelectorAll("[data-view-target]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.viewTarget === name);
  });
}

function setLiveStatus(text) {
  const target = document.querySelector("#live-status");
  if (target) target.textContent = text;
}

function renderModels() {
  const modelConfig = state.config.models || {};
  const aliases = modelConfig.aliases || {};
  const defaultModel = state.config.models.default;
  const providerIds = validProviderIds();
  const agentModels = agentModelChoices();
  const aliasRows = Object.values(aliases).map((alias) => renderModelAliasRow(alias, defaultModel)).join("");
  document.querySelector("#model-aliases").innerHTML = aliasRows
    ? `<div class="model-row model-row-head"><span>Alias</span><span>Provider</span><span>Model</span><span>Auth</span><span>Status</span><span></span></div>${aliasRows}`
    : `<div class="empty-row">No exposed models yet</div>`;
  fillSelect("#agent-model", agentModels, defaultModel);
  fillSelect("#set-agent-model", agentModels, defaultModel);
  fillSelect("#alias-provider", providerIds, preferredSelectValue("#alias-provider", providerIds, "openai-codex"));
  syncAliasModelSuggestions();
}

function renderModelAliasRow(alias, defaultModel) {
  const auth = alias.authType || "api-key";
  const credential = auth === "oauth"
    ? `OAuth: ${alias.profileId || "default"}`
    : alias.apiKeyEnv
      ? `env: ${alias.apiKeyEnv}`
      : auth;
  const status = modelStatusForAlias(alias);
  return `
    <div class="model-row">
      <strong>${escapeHtml(alias.alias)}</strong>
      <span>${escapeHtml(alias.providerId)}</span>
      <span>${escapeHtml(alias.model)}</span>
      <span>${escapeHtml(credential)}</span>
      <span title="${escapeHtml(status.message || "")}">
        <span class="pill ${status.ok ? "ok" : "warn"}">${escapeHtml(status.label)}</span>
        ${alias.alias === defaultModel ? '<span class="pill">default</span>' : ""}
      </span>
      <span class="row-actions">
        <button class="secondary compact-button" data-model-test="${escapeHtml(alias.alias)}">Test</button>
        ${alias.alias === "mock:echo" ? "" : `<button class="secondary compact-button danger-button" data-model-delete="${escapeHtml(alias.alias)}">Remove</button>`}
      </span>
    </div>
  `;
}

function modelStatusForAlias(alias) {
  const tested = modelAuthStatus[alias.alias];
  if (tested) return tested;
  if ((alias.authType || "api-key") === "oauth") {
    const profileId = alias.profileId || "default";
    const linked = (state.authProfiles || []).some(
      (profile) => profile.providerId === alias.providerId && profile.profileId === profileId
    );
    return linked ? { ok: true, label: "linked" } : { ok: false, label: "needs OAuth" };
  }
  if ((alias.authType || "api-key") === "none") {
    return { ok: true, label: "ready" };
  }
  return alias.apiKeyEnv ? { ok: true, label: "configured" } : { ok: false, label: "needs key" };
}

function renderProviders() {
  const providers = state.config.providers || {};
  const presets = exposableProviderPresets();
  const setupIds = presets.filter((preset) => preset.id !== "mock").map((preset) => preset.id);
  fillSelect("#setup-provider", setupIds, preferredSelectValue("#setup-provider", setupIds, "copilot"));
  syncProviderSetupFields();
  document.querySelector("#providers").innerHTML =
    presets
      .map((preset) => {
        const provider = providers[preset.id];
        const configured = Boolean(provider) || preset.id === "mock";
        const readiness = providerReadiness(preset, provider, configured);
        return `
          <div class="provider-row ${configured ? "configured" : ""}">
            <div>
              <strong>${escapeHtml(preset.name)}</strong>
              <small>${escapeHtml(preset.id)} · ${escapeHtml(preset.description || "")}</small>
            </div>
            <small>${escapeHtml(readiness.detail)}</small>
            <span class="row-actions">
              <span class="pill ${readiness.ok ? "ok" : "warn"}">${escapeHtml(readiness.status)}</span>
              ${preset.id === "mock" ? "" : `<button class="secondary compact-button" data-provider-setup="${escapeHtml(preset.id)}">Setup</button>`}
            </span>
          </div>
        `;
      })
      .join("");
  const providerIds = sortedConfiguredProviderIds();
  fillSelect("#auth-provider", providerIds, preferredSelectValue("#auth-provider", providerIds, "openai-codex"));
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
  const agents = sortedAgents();
  if (!agents.some((agent) => agent.id === selectedAgentId)) {
    selectedAgentId = agents[0] ? agents[0].id : "main";
  }
  const selected = agents.find((agent) => agent.id === selectedAgentId);
  document.querySelector("#agents").innerHTML = agents
    .map((agent) =>
      item(`
        <header><strong>${agent.name}</strong><span class="pill">${agent.id === selectedAgentId ? "selected" : agent.status}</span></header>
        <small>${agent.id} · ${agent.model}</small><br />
        <small>bootstrap: ${(agent.bootstrap && agent.bootstrap.status) || "new"}</small><br />
        <small>context: ${recentTurns(agent)} recent messages</small><br />
        <small>${agent.role}</small><br />
        <small>${agent.workspace}</small>
      `)
    )
    .join("");
  fillSelect("#selected-agent", agents.map((agent) => agent.id), selectedAgentId);
  fillSelect("#bind-agent", agents.map((agent) => agent.id));
  fillSelect("#task-agent", agents.map((agent) => agent.id));
  fillSelect("#diagnostics-agent", agents.map((agent) => agent.id));
  setAgentFormTargets(selected);
  renderSelectedAgentSummary(selected);
}

function sortedAgents() {
  return [...(state.agents || [])].sort((a, b) => {
    if (a.id === "main") return -1;
    if (b.id === "main") return 1;
    return a.id.localeCompare(b.id);
  });
}

function setAgentFormTargets(agent) {
  const id = agent ? agent.id : "";
  ["#workspace-agent", "#model-agent", "#context-agent", "#bootstrap-agent", "#seed-agent", "#delete-agent"].forEach((selector) => {
    document.querySelector(selector).value = id;
  });
  document.querySelector("#set-agent-model").value = agent ? agent.model : state.config.models.default;
  document.querySelector("#context-recent-turns").value = agent ? recentTurns(agent) : 16;
  document.querySelector("#agent-delete-form button").disabled = id === "main" || !id;
}

function renderSelectedAgentSummary(agent) {
  if (!agent) {
    document.querySelector("#selected-agent-summary").innerHTML = "<small>No agents found</small>";
    return;
  }
  const bindings = (agent.bindings || []).map((binding) => `${binding.channel}:${binding.accountId}`).join(", ") || "none";
  document.querySelector("#selected-agent-summary").innerHTML = `
    <div><span class="label">Name</span><strong>${agent.name}</strong></div>
    <div><span class="label">Role</span><strong>${agent.role}</strong></div>
    <div><span class="label">Model</span><strong>${agent.model}</strong></div>
    <div><span class="label">Context Window</span><strong>${recentTurns(agent)} recent messages</strong></div>
    <div><span class="label">Bootstrap</span><strong>${(agent.bootstrap && agent.bootstrap.status) || "new"}</strong></div>
    <div><span class="label">Bindings</span><strong>${bindings}</strong></div>
    <div><span class="label">Workspace</span><strong>${agent.workspace}</strong></div>
  `;
}

function recentTurns(agent) {
  const value = agent && agent.context ? Number(agent.context.recentTurns) : 16;
  return Number.isFinite(value) ? value : 16;
}

function validProviderIds() {
  return exposableProviderPresets().map((preset) => preset.id);
}

function sortedConfiguredProviderIds() {
  const known = new Set(validProviderIds());
  return Object.keys(state.config.providers || {})
    .filter((providerId) => known.has(providerId))
    .sort((a, b) => providerLabel(a).localeCompare(providerLabel(b)));
}

function exposableProviderPresets() {
  return sortedProviderPresets().filter((preset) => preset.exposeSupported);
}

function sortedProviderPresets() {
  return [...(state.providerPresets || [])]
    .filter((preset) => preset.id !== "github-copilot")
    .sort((a, b) => (a.name || a.id).localeCompare(b.name || b.id));
}

function agentModelChoices() {
  const allowed = state.config.models.allowed || [];
  const aliases = Object.keys(state.config.models.aliases || {});
  return [...new Set([...aliases, ...allowed])];
}

function modelRef(providerId, model) {
  return providerId === "mock" ? `${providerId}:${model}` : `${providerId}/${model}`;
}

function syncAliasModelSuggestions() {
  const providerId = document.querySelector("#alias-provider").value;
  const catalog = state.config.models.catalog || [];
  const values = new Set();
  catalog
    .filter((entry) => entry.providerId === providerId)
    .forEach((entry) => values.add(entry.model));
  (providerModelOptions[providerId] || []).forEach((model) => values.add(model));
  (state.modelPresets || []).forEach((ref) => {
    if (!ref.includes("/")) return;
    const [presetProvider, presetModel] = ref.split("/", 2);
    if (presetProvider === providerId) values.add(presetModel);
  });
  document.querySelector("#model-options").innerHTML = [...values]
    .sort((a, b) => a.localeCompare(b))
    .map((model) => `<option value="${escapeHtml(model)}"></option>`)
    .join("");
  const preset = providerPreset(providerId);
  document.querySelector("#model-provider-status").textContent = preset
    ? modelProviderStatus(preset)
    : "Choose an available provider.";
}

function syncAliasProviderDefaults() {
  const preset = providerPreset(document.querySelector("#alias-provider").value);
  if (!preset) return;
  syncAliasModelSuggestions();
}

function providerPreset(providerId) {
  return (state.providerPresets || []).find((preset) => preset.id === providerId);
}

function providerLabel(providerId) {
  const preset = providerPreset(providerId);
  return preset ? preset.name : providerId;
}

function authOptionsForProvider(providerId) {
  const preset = providerPreset(providerId);
  if (!preset || !preset.auth) return ["api-key"];
  return [preset.auth];
}

function providerReadiness(preset, provider, configured) {
  if (!configured) {
    return { ok: false, status: "available", detail: preset.auth === "oauth" ? "OAuth required" : "API key required" };
  }
  if (preset.id === "mock") {
    return { ok: true, status: "ready", detail: "local" };
  }
  if (preset.auth === "oauth") {
    const profileId = (provider && provider.profileId) || "default";
    const profile = authProfile(preset.id, profileId);
    if (preset.id === "copilot" && profile && (!profile.copilotAccess || Number(profile.copilotExpires || 0) <= Date.now() / 1000)) {
      return { ok: false, status: "needs validation", detail: "Load models to validate token" };
    }
    const linked = Boolean(profile);
    if (linked) {
      return { ok: true, status: "linked", detail: `OAuth profile: ${profileId}` };
    }
    return { ok: false, status: "needs auth", detail: preset.id === "copilot" ? "GitHub device login" : "OAuth not linked" };
  }
  const envName = (provider && provider.apiKeyEnv) || defaultProviderEnv(preset.id);
  return { ok: true, status: "linked", detail: provider.baseUrl || envName };
}

function modelProviderStatus(preset) {
  const auth = authOptionsForProvider(preset.id)[0];
  if (auth === "oauth") {
    const ready = providerReadiness(preset, (state.config.providers || {})[preset.id], Boolean((state.config.providers || {})[preset.id]));
    if (!ready.ok) {
      return `${preset.name} needs provider setup before agents can use exposed aliases.`;
    }
    return `${preset.name} is linked. Expose Model will save the alias for agents.`;
  }
  return `${preset.name} is linked. Expose Model will save the alias for agents.`;
}

function hasAuthProfile(providerId, profileId = "default") {
  return Boolean(authProfile(providerId, profileId));
}

function authProfile(providerId, profileId = "default") {
  return (state.authProfiles || []).find(
    (profile) => profile.providerId === providerId && profile.profileId === profileId
  );
}

function defaultProviderEnv(providerId) {
  if (providerId === "copilot") return "COPILOT_GITHUB_TOKEN";
  if (providerId === "openai") return "OPENAI_API_KEY";
  if (providerId === "openai-codex") return "OPENAI_API_KEY";
  return `${providerId.toUpperCase().replaceAll("-", "_")}_API_KEY`;
}

function syncProviderSetupFields() {
  const providerId = document.querySelector("#setup-provider").value;
  const preset = providerPreset(providerId);
  const keyInput = document.querySelector("#setup-api-key");
  if (!preset) return;
  keyInput.hidden = false;
  keyInput.disabled = false;
  keyInput.value = "";
  if (providerId === "copilot") {
    keyInput.hidden = true;
    keyInput.disabled = true;
    document.querySelector("#provider-setup-status").textContent =
      "GitHub Copilot uses GitHub device login with the official Copilot plugin app.";
  } else if (preset.auth === "oauth") {
    keyInput.hidden = true;
    keyInput.disabled = true;
    document.querySelector("#provider-setup-status").textContent = `${preset.name} will open its OAuth flow.`;
  } else {
    keyInput.placeholder = `${defaultProviderEnv(providerId)} value`;
    document.querySelector("#provider-setup-status").textContent = `${preset.name} needs an API key saved to .oclite/.env.`;
  }
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

function truncate(text, maxLength) {
  const value = String(text || "");
  return value.length > maxLength ? `${value.slice(0, maxLength).trim()}...` : value;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function isTerminalTask(task) {
  return ["completed", "blocked", "cancelled"].includes(task.status);
}

function normalizeTaskLimit(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 25;
  return Math.max(1, Math.min(Math.trunc(number), 500));
}

function preferredSelectValue(selector, values, fallback) {
  const current = document.querySelector(selector).value;
  if (current && values.includes(current)) return current;
  if (fallback && values.includes(fallback)) return fallback;
  return values[0] || "";
}

function fillSelect(selector, values, selected) {
  const select = document.querySelector(selector);
  const stringValues = values.map((value) => String(value));
  const previous = select.value;
  const currentValues = Array.from(select.options).map((option) => option.value);
  const optionsChanged = currentValues.length !== stringValues.length || currentValues.some((value, index) => value !== stringValues[index]);
  if (optionsChanged) {
    select.innerHTML = stringValues.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  }
  const target = selected === undefined && stringValues.includes(previous) ? previous : String(selected || stringValues[0] || "");
  if (target && stringValues.includes(target) && select.value !== target) {
    select.value = target;
  }
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

document.querySelector("#refresh").addEventListener("click", () => refresh().catch((error) => alert(error.message)));
document.querySelector("#tasks-refresh").addEventListener("click", () => refresh().catch((error) => alert(error.message)));
document.querySelector("#version-badge").addEventListener("click", () => {
  const dialog = document.querySelector("#release-dialog");
  if (dialog.showModal) {
    dialog.showModal();
  } else {
    alert(document.querySelector("#release-notes").textContent);
  }
});
document.querySelector("#close-release-dialog").addEventListener("click", () => {
  document.querySelector("#release-dialog").close();
});
document.querySelector("#copilot-token-help").addEventListener("click", () => {
  const dialog = document.querySelector("#copilot-token-dialog");
  if (dialog.showModal) {
    dialog.showModal();
  } else {
    window.open("https://github.com/settings/tokens", "_blank", "noopener,noreferrer");
  }
});
document.querySelector("#close-copilot-token-dialog").addEventListener("click", () => {
  document.querySelector("#copilot-token-dialog").close();
});
document.querySelector("#update-gateway").addEventListener("click", async () => {
  const button = document.querySelector("#update-gateway");
  button.disabled = true;
  button.textContent = "Updating...";
  try {
    const result = await api("/api/system/update", { method: "POST", body: "{}" });
    console.info("OCLite update output:", result.output || result);
    alert("Update Completed. Restart the gateway");
  } catch (error) {
    alert(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Update";
  }
});
document.querySelector("#restart-gateway").addEventListener("click", async () => {
  const button = document.querySelector("#restart-gateway");
  button.disabled = true;
  button.textContent = "Restarting...";
  let restartRequested = false;
  try {
    await api("/api/system/restart", { method: "POST", body: "{}" });
    restartRequested = true;
  } catch (error) {
    if (isLikelyRestartDisconnect(error)) {
      restartRequested = true;
    } else {
      alert(error.message);
      button.disabled = false;
      button.textContent = "Restart Gateway";
      return;
    }
  }
  if (restartRequested) {
    try {
      await waitForGateway();
      window.location.reload();
    } catch (error) {
      alert(error.message);
      button.disabled = false;
      button.textContent = "Restart Gateway";
    }
  }
});

function isLikelyRestartDisconnect(error) {
  const message = String((error && error.message) || error || "").toLowerCase();
  return message.includes("fetch") || message.includes("network") || message.includes("failed to fetch");
}

async function waitForGateway(timeoutMs = 30000) {
  const started = Date.now();
  await sleep(900);
  while (Date.now() - started < timeoutMs) {
    try {
      const response = await fetch("/api/version", { cache: "no-store" });
      if (response.ok) return;
    } catch (_) {
      // The server is expected to disappear briefly during restart.
    }
    await sleep(1000);
  }
  throw new Error("Gateway restart was requested, but the server did not come back within 30 seconds. Start OCLite from the terminal or enable startup on login.");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
document.querySelectorAll("[data-view-target]").forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.viewTarget));
});
document.querySelector("#selected-agent").addEventListener("change", (event) => {
  selectedAgentId = event.currentTarget.value;
  renderAgents();
});
document.querySelector("#select-main-agent").addEventListener("click", () => {
  selectedAgentId = "main";
  renderAgents();
});
document.querySelector("#prune").addEventListener("click", async () => {
  await api("/api/sessions/prune", { method: "POST", body: "{}" });
  await refresh();
});
document.querySelector("#task-limit").addEventListener("change", (event) => {
  taskLimit = normalizeTaskLimit(event.currentTarget.value || 25);
  localStorage.setItem("ocliteTaskLimit", String(taskLimit));
  renderTasks();
});
document.querySelector("#setup-provider").addEventListener("change", syncProviderSetupFields);
document.querySelector("#alias-provider").addEventListener("change", syncAliasProviderDefaults);
document.querySelector("#load-provider-models").addEventListener("click", async (event) => {
  await loadProviderModels(document.querySelector("#alias-provider").value, event.currentTarget);
});
document.addEventListener("click", async (event) => {
  const setupButton = event.target.closest("[data-provider-setup]");
  if (setupButton) {
    document.querySelector("#setup-provider").value = setupButton.dataset.providerSetup;
    syncProviderSetupFields();
    document.querySelector("#setup-api-key").focus();
    return;
  }
  const modelButton = event.target.closest("[data-model-test]");
  if (modelButton) {
    await testModelAlias(modelButton);
    return;
  }
  const deleteButton = event.target.closest("[data-model-delete]");
  if (deleteButton) {
    await deleteModelAlias(deleteButton.dataset.modelDelete);
    return;
  }
  const row = event.target.closest("[data-task-select]");
  if (row) {
    selectedTaskId = row.dataset.taskSelect;
    renderTasks();
    return;
  }
  const button = event.target.closest("[data-task-cancel]");
  if (!button) return;
  await api("/api/tasks/status", {
    method: "POST",
    body: JSON.stringify({
      taskId: button.dataset.taskCancel,
      status: "cancelled",
      message: "Cancelled from the task dashboard.",
    }),
  });
  await refresh();
});

async function testModelAlias(button) {
  const alias = button.dataset.modelTest;
  button.disabled = true;
  button.textContent = "Testing...";
  modelAuthStatus[alias] = { ok: false, label: "testing" };
  renderModels();
  try {
    const result = await api("/api/models/test", {
      method: "POST",
      body: JSON.stringify({ alias }),
    });
    modelAuthStatus[alias] = {
      ok: Boolean(result.ok),
      label: result.status || (result.ok ? "ready" : "failed"),
      message: result.message || "",
    };
  } catch (error) {
    modelAuthStatus[alias] = { ok: false, label: "failed", message: error.message };
  } finally {
    renderModels();
  }
}

async function loadProviderModels(providerId, button = null) {
  const status = document.querySelector("#model-provider-status");
  const originalText = button ? button.textContent : "";
  if (button) {
    button.disabled = true;
    button.textContent = "Loading...";
  }
  try {
    const result = await api("/api/providers/auth", {
      method: "POST",
      body: JSON.stringify({ providerId }),
    });
    providerModelOptions[providerId] = result.models || [];
    syncAliasModelSuggestions();
    const count = providerModelOptions[providerId].length;
    status.textContent = count
      ? `${providerLabel(providerId)} returned ${count} available models. Choose one from the Model field.`
      : `${providerLabel(providerId)} did not return a model list; use a known model id.`;
    return result;
  } catch (error) {
    status.textContent = error.message;
    throw error;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = originalText;
    }
  }
}

async function deleteModelAlias(alias) {
  const affectedAgents = (state.agents || []).filter((agent) => agent.model === alias);
  const replacementChoices = agentModelChoices().filter((model) => model !== alias);
  let replacement = "";
  if (affectedAgents.length) {
    if (!replacementChoices.length) {
      alert("Cannot remove this model because agents use it and no replacement model is available.");
      return;
    }
    replacement = await chooseReplacementModel(alias, affectedAgents, replacementChoices);
    if (!replacement) return;
  } else if (!confirm(`Remove exposed model '${alias}'?`)) {
    return;
  }
  try {
    await api("/api/models/delete", {
      method: "POST",
      body: JSON.stringify({ alias, replacement }),
    });
    delete modelAuthStatus[alias];
    await refresh();
  } catch (error) {
    alert(error.message);
  }
}

async function chooseReplacementModel(alias, affectedAgents, choices) {
  const lines = affectedAgents.map((agent) => `- ${agent.name} (${agent.id})`).join("\n");
  const choiceList = choices.map((choice, index) => `${index + 1}. ${choice}`).join("\n");
  const answer = prompt(
    `Remove '${alias}'?\n\nThese agents use it and need one replacement model:\n${lines}\n\nAvailable replacements:\n${choiceList}\n\nEnter the replacement number or exact model alias:`,
    "1"
  );
  if (answer === null) return "";
  const trimmed = answer.trim();
  const number = Number(trimmed);
  if (Number.isInteger(number) && number >= 1 && number <= choices.length) {
    return choices[number - 1];
  }
  if (choices.includes(trimmed)) {
    return trimmed;
  }
  alert("Replacement was not recognized. No changes were made.");
  return "";
}

wireForm("#agent-form", "/api/agents");
wireForm("#workspace-form", "/api/agents/workspace");
wireForm("#agent-model-form", "/api/agents/model");
wireForm("#agent-context-form", "/api/agents/context", (form) => {
  const data = formJson(form);
  data.recentTurns = Math.max(0, Math.min(Number(data.recentTurns || 16), 100));
  return data;
});
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

document.querySelector("#provider-setup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const status = document.querySelector("#provider-setup-status");
  const data = formJson(form);
  const preset = providerPreset(data.providerId);
  let oauthWindow = null;
  try {
    if (!preset) throw new Error("Choose a supported provider.");
    if (preset.auth === "oauth") {
      if (data.providerId === "copilot") {
        alert("OCLite will copy the GitHub device code to your clipboard, then open the GitHub authorization tab.");
      }
      oauthWindow = window.open("about:blank", "_blank");
      if (!oauthWindow) {
        status.textContent = "Browser blocked the authorization tab. Allow popups for this OCLite page and try again.";
        return;
      }
    }
    const payload = { providerId: data.providerId };
    if (data.providerId === "copilot") payload.baseUrl = "https://api.individual.githubcopilot.com";
    if (data.apiKey) payload.apiKey = data.apiKey;
    status.textContent = `Saving ${providerLabel(data.providerId)}...`;
    await api("/api/providers", { method: "POST", body: JSON.stringify(payload) });
    if (preset.auth === "oauth") {
      status.textContent = `Linking ${providerLabel(data.providerId)}...`;
      await startProviderOAuth(data.providerId, "default", oauthWindow);
    } else {
      const result = await api("/api/providers/auth", {
        method: "POST",
        body: JSON.stringify({ providerId: data.providerId }),
      });
      providerModelOptions[data.providerId] = result.models || [];
      status.textContent = result.ok ? `${providerLabel(data.providerId)} is configured.` : result.message || "Provider saved.";
    }
    form.reset();
    await refresh();
  } catch (error) {
    closeOAuthWindow(oauthWindow);
    status.textContent = error.message;
  }
});

document.querySelector("#model-alias-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const data = formJson(form);
    data.makeDefault = form.elements.makeDefault.checked;
    if (data.providerId === "copilot" && !hasAuthProfile("copilot", "default")) {
      throw new Error("Enable GitHub Copilot in Provider Setup before exposing Copilot models.");
    }
    try {
      await api("/api/models/alias", { method: "POST", body: JSON.stringify(data) });
    } catch (error) {
      throw error;
    }
    form.reset();
    await refresh();
  } catch (error) {
    alert(error.message);
  }
});

document.querySelector("#provider-auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await api("/api/providers/auth", {
      method: "POST",
      body: JSON.stringify(formJson(event.currentTarget)),
    });
    providerModelOptions[result.providerId] = result.models || [];
    syncAliasModelSuggestions();
    const heading = result.ok ? "Auth OK" : "Auth not testable";
    document.querySelector("#provider-auth-output").textContent =
      `${heading}. ${result.modelCount || 0} models available.\n${result.message || ""}\n${(result.models || []).join("\n")}`;
  } catch (error) {
    document.querySelector("#provider-auth-output").textContent = error.message;
  }
});

async function startProviderOAuth(providerId, profileId = "default", targetWindow = null) {
  let result;
  try {
    result = await api("/api/oauth/start", {
      method: "POST",
      body: JSON.stringify({ providerId, profileId }),
    });
  } catch (error) {
    closeOAuthWindow(targetWindow);
    throw error;
  }
  if (result.status === "complete") {
    closeOAuthWindow(targetWindow);
    setOAuthStatus(`OAuth linked: ${result.providerId}:${result.profileId}\n${result.message || ""}`);
    await refresh();
    return result;
  }
  const isDeviceLogin = result.userCode && result.state;
  if (isDeviceLogin) {
    await copyDeviceCodeToClipboard(result.userCode);
  }
  setOAuthStatus(isDeviceLogin
    ? githubDeviceLoginMessage(result, { authUrl: result.authUrl, userCode: result.userCode })
    : `Opening OAuth for ${result.providerId}:${result.profileId}\n${result.authUrl}\n\nCallback: ${result.redirectUri}`);
  if (!result.authUrl) {
    closeOAuthWindow(targetWindow);
    throw new Error(result.message || `OAuth did not return a login URL for ${providerId}.`);
  }
  if (targetWindow) {
    targetWindow.location.href = result.authUrl;
  } else {
    window.open(result.authUrl, "_blank", "noopener,noreferrer");
  }
  if (isDeviceLogin) {
    await pollProviderOAuth(result.providerId, result.state, result.interval || 5, {
      authUrl: result.authUrl,
      userCode: result.userCode,
    });
  }
  return result;
}

async function copyDeviceCodeToClipboard(userCode) {
  if (!userCode) return;
  try {
    await navigator.clipboard.writeText(userCode);
    alert(`GitHub device code copied to your clipboard:\n\n${userCode}\n\nPaste it into the GitHub authorization page.`);
  } catch (_) {
    alert(`Copy this GitHub device code:\n\n${userCode}\n\nPaste it into the GitHub authorization page.`);
  }
}

function setOAuthStatus(message) {
  const target = document.querySelector("#provider-setup-status") || document.querySelector("#provider-auth-output");
  if (target) target.textContent = message;
}

function closeOAuthWindow(targetWindow) {
  try {
    if (targetWindow && !targetWindow.closed) targetWindow.close();
  } catch (_) {
    // Some browsers disallow script-closing a tab once it has navigated away.
  }
}

function githubDeviceLoginMessage(result, loginInfo = {}) {
  const authUrl = loginInfo.authUrl || result.authUrl || "https://github.com/login/device";
  const userCode = loginInfo.userCode || result.userCode || "";
  const codeLine = userCode ? `\nCode: ${userCode}` : "";
  return `GitHub device login for ${result.providerId}:${result.profileId}\nOpen: ${authUrl}${codeLine}\n\nWaiting for authorization...`;
}

async function pollProviderOAuth(providerId, stateId, intervalSeconds = 5, loginInfo = {}) {
  let intervalMs = Math.max(3, Number(intervalSeconds || 5)) * 1000;
  const started = Date.now();
  while (Date.now() - started < 15 * 60 * 1000) {
    await sleep(intervalMs);
    const result = await api("/api/oauth/poll", {
      method: "POST",
      body: JSON.stringify({ providerId, state: stateId }),
    });
    if (result.status === "complete") {
      setOAuthStatus(`OAuth linked: ${result.providerId}:${result.profileId}`);
      await refresh();
      return result;
    }
    if (result.slowDown) intervalMs += 5000;
    setOAuthStatus(githubDeviceLoginMessage(result, loginInfo));
  }
  throw new Error("GitHub device login timed out. Start OAuth again when you are ready.");
}

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

refresh().catch((error) => alert(error.message));
