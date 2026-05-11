let state = null;
let activeView = "dashboard";
let selectedAgentId = "main";
let selectedTaskId = null;
let refreshInFlight = false;
let lastRefreshAt = null;
let taskLimit = normalizeTaskLimit(localStorage.getItem("ocliteTaskLimit") || 25);

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
  document.querySelector("#model-aliases").innerHTML =
    Object.values(aliases)
      .map((alias) =>
        item(`
          <header><strong>${escapeHtml(alias.alias)}</strong>${alias.alias === defaultModel ? '<span class="pill">default</span>' : ""}</header>
          <small>${escapeHtml(alias.providerId)} / ${escapeHtml(alias.model)} · ${escapeHtml(alias.authType || "api-key")}</small>
          ${alias.apiKeyEnv ? `<br /><small>env: ${escapeHtml(alias.apiKeyEnv)}</small>` : ""}
          ${alias.profileId ? `<br /><small>OAuth profile: ${escapeHtml(alias.profileId)}</small>` : ""}
        `)
      )
      .join("") || item("<small>No aliases yet</small>");
  fillSelect("#agent-model", agentModels, defaultModel);
  fillSelect("#set-agent-model", agentModels, defaultModel);
  fillSelect("#alias-provider", providerIds, preferredSelectValue("#alias-provider", providerIds, "openai-codex"));
  syncAliasModelSuggestions();
  syncAliasAuthFields();
}

function renderProviders() {
  const providers = state.config.providers || {};
  const presets = sortedProviderPresets();
  document.querySelector("#providers").innerHTML =
    presets
      .map((preset) => {
        const provider = providers[preset.id];
        const configured = Boolean(provider) || preset.id === "mock";
        return `
          <div class="provider-row ${configured ? "configured" : ""}">
            <div>
              <strong>${escapeHtml(preset.name)}</strong>
              <small>${escapeHtml(preset.id)} · ${escapeHtml(preset.description || "")}</small>
            </div>
            <small>${escapeHtml((provider && provider.baseUrl) || preset.baseUrl || "local")}</small>
            <span class="pill">${configured ? "available" : "not added"}</span>
          </div>
        `;
      })
      .join("");
  const providerIds = sortedConfiguredProviderIds();
  fillSelect("#auth-provider", providerIds, preferredSelectValue("#auth-provider", providerIds, "openai-codex"));
  fillSelect("#oauth-provider", providerIds, preferredSelectValue("#oauth-provider", providerIds, "openai-codex"));
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
  return sortedProviderPresets()
    .filter((preset) => preset.id !== "mock")
    .map((preset) => preset.id);
}

function sortedConfiguredProviderIds() {
  const known = new Set(validProviderIds());
  return Object.keys(state.config.providers || {})
    .filter((providerId) => known.has(providerId))
    .sort((a, b) => providerLabel(a).localeCompare(providerLabel(b)));
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
    ? `${preset.name} selected. Enter the exact model id you want agents to use.`
    : "Choose a valid provider from the catalogue.";
}

function syncAliasProviderDefaults() {
  const preset = providerPreset(document.querySelector("#alias-provider").value);
  if (!preset) return;
  document.querySelector("#alias-auth-type").value = preset.auth || "api-key";
  syncAliasModelSuggestions();
  syncAliasAuthFields();
}

function syncAliasAuthFields() {
  const authType = document.querySelector("#alias-auth-type").value;
  document.querySelector("#alias-api-key").disabled = authType !== "api-key";
  document.querySelector("#alias-profile-id").disabled = authType !== "oauth";
}

function providerPreset(providerId) {
  return (state.providerPresets || []).find((preset) => preset.id === providerId);
}

function providerLabel(providerId) {
  const preset = providerPreset(providerId);
  return preset ? preset.name : providerId;
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
  try {
    await api("/api/system/restart", { method: "POST", body: "{}" });
    setTimeout(() => window.location.reload(), 1800);
  } catch (error) {
    alert(error.message);
    button.disabled = false;
    button.textContent = "Restart Gateway";
  }
});
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
document.querySelector("#alias-provider").addEventListener("change", syncAliasProviderDefaults);
document.querySelector("#alias-auth-type").addEventListener("change", syncAliasAuthFields);
document.addEventListener("click", async (event) => {
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
wireForm("#model-alias-form", "/api/models/alias", (form) => {
  const data = formJson(form);
  data.makeDefault = form.elements.makeDefault.checked;
  return data;
});

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

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh().catch(() => {});
});

setInterval(() => {
  if (!document.hidden) refresh().catch(() => {});
}, 2500);

refresh().catch((error) => alert(error.message));
