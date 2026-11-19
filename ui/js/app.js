(function () {
  const U = window.JarvisUtils;
  const Api = window.JarvisApi;
  const byId = U.byId;
  const escapeHtml = U.escapeHtml;
  const renderMarkdown = U.renderMarkdown;
  const toast = U.toast;
  const normalizeStatus = U.normalizeStatus;
  const formatClock = U.formatClock;
  const formatUptime = U.formatUptime;
  const formatDuration = U.formatDuration;
  const truncate = U.truncate;

  const STATUS_LABELS = {
    starting: "STARTING",
    ready: "READY",
    listening: "LISTENING",
    processing: "PROCESSING",
    thinking: "THINKING",
    speaking: "SPEAKING",
    error: "ERROR",
    stopped: "OFFLINE",
  };

  const STATUS_DESCRIPTIONS = {
    starting: "Запуск подсистем…",
    ready: "Ожидаю команду…",
    listening: "Слушаю команду…",
    processing: "Распознаю речь…",
    thinking: "Анализирую запрос…",
    speaking: "Говорю…",
    error: "Требуется внимание.",
    stopped: "Система остановлена.",
  };

  const MODE_LABELS = { chat: "CHAT", tasks: "TASKS", code: "CODE" };
  const MODE_NAMES = {
    chat: "Просто чат",
    tasks: "Простые задачи",
    code: "Код",
  };

  const PAGE_ORDER = [
    "chat",
    "agent",
    "tasks",
    "commands",
    "journal",
    "settings",
  ];

  const state = {
    page: "chat",
    status: {
      name: "starting",
      label: "STARTING",
      description: "Запуск подсистем…",
    },
    telemetry: { available: false },
    tasks: [],
    messages: [],
    catalog: [],
    filteredCommands: [],
    journal: [],
    agent: [],
    toolFeed: [],
    settings: {},
    mode: "tasks",
    preview: false,
    mic: 0,
    connected: false,
    sending: false,
    polling: false,
    forceScroll: true,
    taskFilter: "all",
    journalFilter: "all",
    commandCategory: "all",
    paletteOpen: false,
    paletteIndex: 0,
    paletteMatches: [],
    startedAt: Date.now(),
    iterations: 0,
    toolCount: 0,
    lastAnswer: "",
  };

  const els = {
    clock: byId("clock"),
    topStatusDot: byId("top-status-dot"),
    topStatusLabel: byId("top-status-label"),
    topCpu: byId("top-cpu"),
    topRam: byId("top-ram"),
    topBat: byId("top-bat"),
    reactor: byId("reactor"),
    reactorStatus: byId("reactor-status"),
    reactorMode: byId("reactor-mode"),
    micFill: byId("mic-fill"),
    micValue: byId("mic-value"),
    connectionDot: byId("connection-dot"),
    connectionLabel: byId("connection-label"),
    footerConnection: byId("footer-connection"),
    footerMode: byId("footer-mode"),
    footerUptime: byId("footer-uptime"),
    modeChip: byId("mode-chip"),
    agentModeChip: byId("agent-mode-chip"),
    modeSelect: byId("mode-select"),
    previewToggle: byId("preview-toggle"),
    messageList: byId("message-list"),
    chatEmpty: byId("chat-empty"),
    chatInput: byId("chat-input"),
    sendButton: byId("send-button"),
    stopButton: byId("stop-button"),
    clearChat: byId("clear-chat"),
    taskFilter: byId("task-filter"),
    tasksList: byId("tasks-list"),
    tasksEmpty: byId("tasks-empty"),
    tasksCount: byId("tasks-count"),
    tasksRefresh: byId("tasks-refresh"),
    ctxTasks: byId("ctx-tasks"),
    ctxTools: byId("ctx-tools"),
    ctxStatus: byId("ctx-status"),
    ctxStatusDescription: byId("ctx-status-description"),
    ctxCpu: byId("ctx-cpu"),
    ctxRam: byId("ctx-ram"),
    ctxDisk: byId("ctx-disk"),
    ctxBat: byId("ctx-bat"),
    ctxUptime: byId("ctx-uptime"),
    commandSearch: byId("command-search"),
    commandCategory: byId("command-category"),
    commandsList: byId("commands-list"),
    commandsCount: byId("commands-count"),
    journalSearch: byId("journal-search"),
    journalFilter: byId("journal-filter"),
    journalList: byId("journal-list"),
    journalRefresh: byId("journal-refresh"),
    journalAudit: byId("journal-audit"),
    journalDoctor: byId("journal-doctor"),
    journalClear: byId("journal-clear"),
    agentTimeline: byId("agent-timeline"),
    agentEmpty: byId("agent-empty"),
    agentStatus: byId("agent-status"),
    agentIterations: byId("agent-iterations"),
    agentTools: byId("agent-tools"),
    agentLast: byId("agent-last"),
    settingsSave: byId("settings-save"),
    setAutonomy: byId("set-autonomy"),
    setChatMode: byId("set-chat-mode"),
    setConfirm: byId("set-confirm"),
    setDryRun: byId("set-dry-run"),
    setTaint: byId("set-taint"),
    setPreview: byId("set-preview"),
    setCategory: byId("set-category"),
    setMaxTools: byId("set-max-tools"),
    setCodeTools: byId("set-code-tools"),
    setMaxIterations: byId("set-max-iterations"),
    setMaxTokens: byId("set-max-tokens"),
    setToolTimeout: byId("set-tool-timeout"),
    setNoiseK: byId("set-noise-k"),
    setMaxSpeech: byId("set-max-speech"),
    setSilence: byId("set-silence"),
    openConfig: byId("open-config"),
    openAudit: byId("open-audit"),
    runDoctor: byId("run-doctor"),
    stopAssistant: byId("stop-assistant"),
    quitApp: byId("quit-app"),
    palette: byId("palette"),
    paletteInput: byId("palette-input"),
    paletteList: byId("palette-list"),
    paletteClose: byId("palette-close"),
  };

  const reactor = new window.JarvisReactor(els.reactor);

  function tick() {
    els.clock.textContent = formatClock(new Date());
    const uptime = (Date.now() - state.startedAt) / 1000;
    els.footerUptime.textContent = "UI uptime: " + formatUptime(uptime);
  }

  async function connect() {
    try {
      await Api.waitForBridge(7000);
      const data = await Api.rpc("bootstrap");
      applyBootstrap(data || {});
      setConnected(true);
      if (!state.polling) {
        state.polling = true;
        poll();
      }
    } catch (error) {
      setConnected(false);
      setTimeout(connect, 1400);
    }
  }

  async function poll() {
    try {
      const data = await Api.rpc("poll");
      setConnected(true);
      if (data && Array.isArray(data.events)) {
        data.events.forEach(handleEvent);
      }
      if (data && data.snapshot) {
        applySnapshot(data.snapshot);
      }
    } catch (error) {
      setConnected(false);
    } finally {
      if (state.polling) {
        setTimeout(poll, 80);
      }
    }
  }

  function applyBootstrap(data) {
    state.telemetry = data.telemetry || { available: false };
    state.tasks = Array.isArray(data.tasks) ? data.tasks : [];
    state.catalog = Array.isArray(data.catalog) ? data.catalog : [];
    state.settings = data.settings && typeof data.settings === "object"
      ? data.settings
      : {};
    state.mode = data.chat_mode || state.settings.chat_mode || "tasks";
    state.preview = Boolean(data.transcript_preview);
    state.mic = Number(data.mic) || 0;
    setStatus(data.status || state.status);
    renderMode();
    renderTelemetry();
    renderMessages();
    renderTasks();
    renderContextTasks();
    renderContextTools();
    renderCatalog();
    renderAgent();
    renderJournal();
    renderSettings();
    updateMic(state.mic);
    if (data.greeting && state.messages.length === 0) {
      els.chatEmpty.querySelector("b").textContent =
        data.greeting + ", сэр.";
    }
  }

  function applySnapshot(snapshot) {
    if (!snapshot) return;
    if (snapshot.status) {
      setStatus(snapshot.status);
    }
    if (snapshot.telemetry) {
      state.telemetry = snapshot.telemetry;
      renderTelemetry();
    }
    if (Array.isArray(snapshot.tasks)) {
      state.tasks = snapshot.tasks;
      renderTasks();
      renderContextTasks();
    }
    if (typeof snapshot.mic === "number") {
      state.mic = snapshot.mic;
      reactor.setMic(Math.min(1, snapshot.mic / 0.03));
      updateMic(snapshot.mic);
    }
    if (snapshot.chat_mode && snapshot.chat_mode !== state.mode) {
      state.mode = snapshot.chat_mode;
      renderMode();
    }
    if (typeof snapshot.transcript_preview === "boolean") {
      state.preview = snapshot.transcript_preview;
      els.previewToggle.checked = state.preview;
      els.setPreview.checked = state.preview;
    }
  }

  function handleEvent(event) {
    if (!event || !event.type) return;
    const type = event.type;
    const payload = event.payload;
    switch (type) {
      case "user":
        appendMessage("user", textOf(payload));
        break;
      case "assistant":
        appendMessage("assistant", textOf(payload));
        break;
      case "error":
        appendMessage("error", textOf(payload));
        appendJournal("error", textOf(payload));
        toast(textOf(payload), "error");
        break;
      case "system":
        handleSystemEvent(textOf(payload));
        break;
      case "transcript_preview":
        switchPage("chat");
        els.chatInput.value = textOf(payload);
        els.chatInput.focus();
        toast("Голос распознан — проверьте текст.", "warning");
        break;
      case "command_catalog":
        state.catalog = Array.isArray(payload) ? payload : [];
        renderCatalog();
        break;
      case "llm_iteration":
        state.iterations = Math.max(
          state.iterations,
          Number(payload && payload.iteration) || 0
        );
        appendAgent({
          type: "iteration",
          iteration: Number(payload && payload.iteration) || 0,
          max: Number(payload && payload.max_iterations) || 0,
        });
        setStatus({
          name: "thinking",
          label: "THINKING",
          description: "Анализирую запрос…",
        });
        break;
      case "llm_tool_call":
        appendAgent({
          type: "tool",
          name: String((payload && payload.name) || "tool"),
          arguments: stringify(payload && payload.arguments),
        });
        setStatus({
          name: "processing",
          label: "PROCESSING",
          description: "Выполняю инструмент…",
        });
        break;
      case "llm_tool_result":
        appendAgent({
          type: "result",
          name: String((payload && payload.name) || "tool"),
          result: String((payload && payload.result) || ""),
          elapsed: Number(payload && payload.elapsed) || 0,
        });
        break;
      case "llm_answer":
        appendAgent({
          type: "answer",
          text: String((payload && payload.text) || ""),
        });
        break;
      default:
        appendJournal("system", type + ": " + stringify(payload));
    }
  }

  function handleSystemEvent(text) {
    if (!text) return;
    appendJournal("system", text);
    if (
      text.indexOf("завершил работу") !== -1 ||
      text.indexOf("Аварийная остановка") !== -1
    ) {
      appendMessage("system", text);
    }
    if (text.indexOf("Настройки сохранены") !== -1) {
      toast(text, "success");
    }
  }

  function appendMessage(role, value) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return;
    state.messages.push({ role: role, text: text, time: Date.now() });
    if (state.messages.length > 350) {
      state.messages.splice(0, state.messages.length - 350);
    }
    state.forceScroll = state.forceScroll || isNearBottom(els.messageList);
    renderMessages();
  }

  function renderMessages() {
    const nearBottom = isNearBottom(els.messageList);
    const fragment = document.createDocumentFragment();
    state.messages.forEach(function (message) {
      const row = document.createElement("div");
      row.className = "message " + message.role;
      const meta = document.createElement("div");
      meta.className = "message-meta";
      const role = {
        user: "ВЫ",
        assistant: "JARVIS",
        error: "ОШИБКА",
        system: "СИСТЕМА",
      }[message.role] || "JARVIS";
      meta.innerHTML =
        "<b>" +
        escapeHtml(role) +
        "</b><span>" +
        escapeHtml(formatClock(message.time)) +
        "</span>";
      const body = document.createElement("div");
      body.className = "message-body";
      if (message.role === "assistant") {
        body.innerHTML = renderMarkdown(message.text);
      } else {
        body.innerHTML = escapeHtml(message.text).replace(/\n/g, "<br>");
      }
      row.appendChild(meta);
      row.appendChild(body);
      fragment.appendChild(row);
    });
    els.messageList.innerHTML = "";
    els.messageList.appendChild(fragment);
    els.chatEmpty.classList.toggle(
      "hidden",
      state.messages.length > 0
    );
    if (state.forceScroll || nearBottom) {
      els.messageList.scrollTop = els.messageList.scrollHeight;
      state.forceScroll = false;
    }
  }

  function appendJournal(kind, value) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return;
    state.journal.push({ kind: kind, text: text, time: Date.now() });
    if (state.journal.length > 600) {
      state.journal.splice(0, state.journal.length - 600);
    }
    if (state.page === "journal") {
      renderJournal();
    }
  }

  function renderJournal() {
    const query = els.journalSearch.value.trim().toLowerCase();
    const filter = state.journalFilter;
    const nearBottom = isNearBottom(els.journalList);
    const lines = [];
    state.journal.forEach(function (entry) {
      if (filter !== "all" && entry.kind !== filter) return;
      if (query && entry.text.toLowerCase().indexOf(query) === -1) return;
      const stamp = escapeHtml(formatClock(entry.time));
      entry.text.split("\n").forEach(function (line) {
        lines.push(
          '<span class="journal-line log-' +
            escapeHtml(entry.kind) +
            '">[' +
            stamp +
            "] " +
            escapeHtml(line) +
            "</span>"
        );
      });
    });
    els.journalList.innerHTML = lines.length
      ? lines.join("\n")
      : "Журнал пуст.";
    if (nearBottom) {
      els.journalList.scrollTop = els.journalList.scrollHeight;
    }
  }

  function appendAgent(entry) {
    state.agent.push(Object.assign({ time: Date.now() }, entry));
    if (state.agent.length > 260) {
      state.agent.splice(0, state.agent.length - 260);
    }
    if (entry.type === "tool") {
      state.toolCount += 1;
      state.toolFeed.unshift({
        name: entry.name,
        status: "running",
        elapsed: 0,
      });
      if (state.toolFeed.length > 6) state.toolFeed.pop();
    }
    if (entry.type === "result") {
      const item = state.toolFeed.find(function (tool) {
        return tool.name === entry.name && tool.status === "running";
      });
      if (item) {
        item.status =
          String(entry.result || "").toLowerCase().indexOf("error") === 0
            ? "error"
            : "success";
        item.elapsed = entry.elapsed;
      }
    }
    if (entry.type === "answer") {
      state.lastAnswer = truncate(entry.text, 80);
    }
    renderAgent();
    renderContextTools();
  }

  function renderAgent() {
    els.agentEmpty.classList.toggle(
      "hidden",
      state.agent.length > 0
    );
    const fragment = document.createDocumentFragment();
    state.agent.forEach(function (entry) {
      let kind = "system";
      let title = "SYSTEM";
      let body = "";
      if (entry.type === "iteration") {
        kind = "iteration";
        title =
          "ШАГ " + entry.iteration + "/" + (entry.max || "?");
        body = "Анализ запроса и выбор следующего действия.";
      } else if (entry.type === "tool") {
        kind = "tool";
        title = "TOOL · " + entry.name;
        body = entry.arguments || "";
      } else if (entry.type === "result") {
        kind = "tool";
        title = "RESULT · " + entry.name;
        body =
          "(" +
          Number(entry.elapsed || 0).toFixed(2) +
          " c) " +
          (entry.result || "");
      } else if (entry.type === "answer") {
        kind = "answer";
        title = "ANSWER";
        body = entry.text || "";
      }
      const row = document.createElement("div");
      row.className = "timeline-item " + kind;
      row.innerHTML =
        '<div class="timeline-head"><b>' +
        escapeHtml(title) +
        "</b><span>" +
        escapeHtml(formatClock(entry.time)) +
        "</span></div>" +
        '<div class="timeline-body">' +
        escapeHtml(truncate(body, 1600)) +
        "</div>";
      fragment.appendChild(row);
    });
    els.agentTimeline.innerHTML = "";
    els.agentTimeline.appendChild(fragment);
    els.agentStatus.textContent =
      STATUS_LABELS[state.status.name] || state.status.label;
    els.agentIterations.textContent = String(state.iterations);
    els.agentTools.textContent = String(state.toolCount);
    els.agentLast.textContent = state.lastAnswer || "—";
  }

  function renderContextTools() {
    els.ctxTools.innerHTML = "";
    if (!state.toolFeed.length) {
      const empty = document.createElement("div");
      empty.className = "mini-empty";
      empty.textContent = "Пока нет вызовов инструментов.";
      els.ctxTools.appendChild(empty);
      return;
    }
    state.toolFeed.slice(0, 4).forEach(function (tool) {
      const row = document.createElement("div");
      row.className = "mini-item";
      const dot = document.createElement("span");
      dot.className = "mini-dot " + tool.status;
      const text = document.createElement("span");
      text.className = "mini-text";
      text.textContent =
        tool.name +
        (tool.status === "running"
          ? " · выполняется"
          : " · " + Number(tool.elapsed || 0).toFixed(1) + " c");
      row.appendChild(dot);
      row.appendChild(text);
      els.ctxTools.appendChild(row);
    });
  }

  function renderContextTasks() {
    els.ctxTasks.innerHTML = "";
    const active = state.tasks.filter(isActiveTask).slice(0, 4);
    if (!active.length) {
      const empty = document.createElement("div");
      empty.className = "mini-empty";
      empty.textContent = "Нет активных задач.";
      els.ctxTasks.appendChild(empty);
      return;
    }
    active.forEach(function (task) {
      const row = document.createElement("div");
      row.className = "mini-item";
      const dot = document.createElement("span");
      dot.className =
        "mini-dot " +
        (normalizeTaskStatus(task.status) === "failed"
          ? "error"
          : "success");
      const text = document.createElement("span");
      text.className = "mini-text";
      text.textContent =
        "#" + task.id + " · " + (task.title || task.status || "");
      row.appendChild(dot);
      row.appendChild(text);
      els.ctxTasks.appendChild(row);
    });
  }

  function renderTasks() {
    const filter = state.taskFilter;
    const tasks = state.tasks.filter(function (task) {
      const status = normalizeTaskStatus(task.status);
      if (filter === "active") return isActiveTask(task);
      if (filter === "done") return status === "done";
      if (filter === "failed") {
        return status === "failed" || status === "cancelled";
      }
      return true;
    });
    els.tasksCount.textContent = String(tasks.length);
    els.tasksList.innerHTML = "";
    els.tasksEmpty.classList.toggle("hidden", tasks.length > 0);
    const fragment = document.createDocumentFragment();
    tasks.forEach(function (task) {
      const status = normalizeTaskStatus(task.status);
      const row = document.createElement("div");
      row.className = "task-card";
      const main = document.createElement("div");
      main.className = "task-main";
      const title = document.createElement("div");
      title.className = "task-title";
      title.textContent = task.title || task.id || "Задача";
      const sub = document.createElement("div");
      sub.className = "task-sub";
      sub.textContent =
        "#" +
        (task.id || "—") +
        " · " +
        (task.status || "unknown") +
        (task.result || task.error
          ? " · " + truncate(task.result || task.error, 100)
          : "");
      main.appendChild(title);
      main.appendChild(sub);
      const chip = document.createElement("span");
      chip.className = "task-status " + status;
      chip.textContent = task.status || status;
      const action = document.createElement("button");
      action.className = "task-action";
      if (isActiveTask(task)) {
        action.textContent = "Отменить";
        action.dataset.taskId = String(task.id);
      } else {
        action.textContent = "—";
        action.disabled = true;
      }
      row.appendChild(main);
      row.appendChild(chip);
      row.appendChild(action);
      fragment.appendChild(row);
    });
    els.tasksList.appendChild(fragment);
  }

  function renderCatalog() {
    const items = getCatalogItems();
    const categories = Array.from(
      new Set(items.map(function (item) {
        return item.category;
      }))
    ).sort();
    const signature = categories.join("|");
    if (els.commandCategory.dataset.signature !== signature) {
      const selected = els.commandCategory.value;
      els.commandCategory.innerHTML = "";
      const all = document.createElement("option");
      all.value = "all";
      all.textContent = "Все категории";
      els.commandCategory.appendChild(all);
      categories.forEach(function (category) {
        const option = document.createElement("option");
        option.value = category;
        option.textContent = category;
        els.commandCategory.appendChild(option);
      });
      els.commandCategory.value = categories.includes(selected)
        ? selected
        : "all";
      els.commandCategory.dataset.signature = signature;
    }

    const query = els.commandSearch.value.trim().toLowerCase();
    const category = els.commandCategory.value;
    const filtered = items.filter(function (item) {
      if (category !== "all" && item.category !== category) return false;
      if (!query) return true;
      return (
        item.name.toLowerCase().indexOf(query) !== -1 ||
        item.description.toLowerCase().indexOf(query) !== -1
      );
    });
    state.filteredCommands = filtered;
    els.commandsCount.textContent = String(filtered.length);
    if (!filtered.length) {
      els.commandsList.innerHTML =
        '<div class="command-empty">Ничего не найдено.</div>';
      return;
    }
    const fragment = document.createDocumentFragment();
    filtered.forEach(function (item, index) {
      const row = document.createElement("button");
      row.className = "command-row";
      row.dataset.commandIndex = String(index);
      row.innerHTML =
        '<span class="command-icon">' +
        escapeHtml(item.name.slice(0, 1).toUpperCase()) +
        "</span>" +
        '<span class="command-copy"><b>' +
        escapeHtml(item.name) +
        "</b><span>" +
        escapeHtml(item.description || "Без описания") +
        "</span></span>";
      fragment.appendChild(row);
    });
    els.commandsList.innerHTML = "";
    els.commandsList.appendChild(fragment);
  }

  function getCatalogItems() {
    return (state.catalog || [])
      .map(function (tool) {
        const fn = tool && tool.function ? tool.function : tool || {};
        const name = String(fn.name || "");
        const description = String(fn.description || "");
        const category = name.indexOf("_") > 0
          ? name.split("_")[0]
          : "core";
        return { name: name, description: description, category: category };
      })
      .filter(function (item) {
        return item.name.length > 0;
      })
      .sort(function (a, b) {
        return a.name.localeCompare(b.name);
      });
  }

  function renderSettings() {
    const settings = state.settings || {};
    els.setAutonomy.value = settings.autonomy || "balanced";
    els.setChatMode.value = settings.chat_mode || state.mode || "tasks";
    els.setConfirm.checked = Boolean(settings.confirm_destructive);
    els.setDryRun.checked = Boolean(settings.dry_run);
    els.setTaint.checked = settings.taint_tracking !== false;
    els.setPreview.checked = Boolean(settings.transcript_preview);
    els.setCategory.checked = settings.category_planning !== false;
    setNumber(els.setMaxTools, settings.max_tools_per_request, 100);
    setNumber(els.setCodeTools, settings.code_tools_per_request, 28);
    setNumber(els.setMaxIterations, settings.max_iterations, 12);
    setNumber(els.setMaxTokens, settings.max_tokens, 3000);
    setNumber(els.setToolTimeout, settings.tool_timeout_seconds, 120);
    setNumber(els.setNoiseK, settings.stt_noise_adapt_k, 3.0);
    setNumber(els.setMaxSpeech, settings.max_speech_seconds, 12.0);
    setNumber(els.setSilence, settings.silence_duration, 0.7);
    els.previewToggle.checked = Boolean(settings.transcript_preview);
  }

  function setNumber(input, value, fallback) {
    input.value = String(value == null ? fallback : value);
  }

  function renderMode() {
    const mode = MODE_LABELS[state.mode] ? state.mode : "tasks";
    state.mode = mode;
    els.modeSelect.value = mode;
    els.setChatMode.value = mode;
    els.modeChip.className = "mode-chip " + mode;
    els.modeChip.textContent = MODE_LABELS[mode];
    els.agentModeChip.className = "mode-chip " + mode;
    els.agentModeChip.textContent = MODE_LABELS[mode];
    els.reactorMode.textContent = MODE_LABELS[mode];
    els.footerMode.textContent = "Режим: " + mode;
    els.modeSelect.title = MODE_NAMES[mode];
  }

  function renderTelemetry() {
    const data = state.telemetry || {};
    const available = data.available !== false;
    const cpu = available ? percentage(data.cpu) : "—";
    const ram = available ? percentage(data.memory) : "—";
    const disk = available ? percentage(data.disk) : "—";
    const battery = data.battery
      ? data.battery.percent + "%" + (data.battery.plugged ? "+" : "")
      : "—";
    els.topCpu.textContent = cpu;
    els.topRam.textContent = ram;
    els.topBat.textContent = battery;
    els.ctxCpu.textContent = cpu;
    els.ctxRam.textContent = ram;
    els.ctxDisk.textContent = disk;
    els.ctxBat.textContent = battery;
    els.ctxUptime.textContent = data.uptime || "—";
  }

  function setStatus(status) {
    const raw = status && typeof status === "object"
      ? status
      : { name: status };
    const name = normalizeStatus(raw.name);
    const label =
      raw.label || STATUS_LABELS[name] || name.toUpperCase();
    const description =
      raw.description ||
      STATUS_DESCRIPTIONS[name] ||
      "Система активна.";
    state.status = { name: name, label: label, description: description };
    els.topStatusLabel.textContent = label;
    els.topStatusDot.className = "status-dot " + name;
    els.ctxStatus.textContent = label;
    els.ctxStatus.className = "status-" + name;
    els.ctxStatusDescription.textContent = description;
    els.reactorStatus.textContent = label;
    els.reactorStatus.className = "status-" + name;
    els.agentStatus.textContent = label;
    document.body.dataset.status = name;
    reactor.setStatus(name);
  }

  function setConnected(connected) {
    state.connected = Boolean(connected);
    els.connectionDot.className =
      "status-dot small " + (connected ? "ready" : "error");
    els.connectionLabel.textContent = connected
      ? "Ядро активно"
      : "Связь потеряна";
    els.footerConnection.textContent = connected
      ? "Соединение: активно"
      : "Соединение: потеряно";
    els.footerConnection.className = connected
      ? "connection-ok"
      : "connection-bad";
  }

  function updateMic(value) {
    const normalized = Math.min(1, Math.max(0, Number(value) || 0) / 0.03);
    els.micFill.style.width = Math.round(normalized * 100) + "%";
    els.micValue.textContent = Math.round(normalized * 100) + "%";
  }

  async function sendMessage() {
    if (state.sending) return;
    const text = els.chatInput.value.trim();
    if (!text) return;
    state.sending = true;
    state.forceScroll = true;
    updateSendButton();
    try {
      await Api.rpc("send_message", { text: text, mode: state.mode });
      els.chatInput.value = "";
      els.chatInput.focus();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      state.sending = false;
      updateSendButton();
    }
  }

  async function stopAssistant() {
    try {
      await Api.rpc("stop");
      toast("Отправлена команда остановки.", "warning");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function updateSendButton() {
    els.sendButton.disabled = state.sending;
    els.sendButton.textContent = state.sending
      ? "Отправка…"
      : "Отправить";
  }

  async function setMode(mode) {
    const previous = state.mode;
    state.mode = mode;
    renderMode();
    try {
      await Api.rpc("set_mode", { mode: mode });
      toast("Режим: " + MODE_NAMES[mode], "success");
    } catch (error) {
      state.mode = previous;
      renderMode();
      toast(error.message, "error");
    }
  }

  async function setPreview(enabled) {
    const previous = state.preview;
    state.preview = Boolean(enabled);
    els.previewToggle.checked = state.preview;
    els.setPreview.checked = state.preview;
    try {
      await Api.rpc("set_preview", { enabled: state.preview });
    } catch (error) {
      state.preview = previous;
      els.previewToggle.checked = previous;
      els.setPreview.checked = previous;
      toast(error.message, "error");
    }
  }

  async function saveSettings() {
    const payload = {
      autonomy: els.setAutonomy.value,
      chat_mode: els.setChatMode.value,
      confirm_destructive: els.setConfirm.checked,
      dry_run: els.setDryRun.checked,
      taint_tracking: els.setTaint.checked,
      transcript_preview: els.setPreview.checked,
      category_planning: els.setCategory.checked,
      max_tools_per_request: Number(els.setMaxTools.value),
      code_tools_per_request: Number(els.setCodeTools.value),
      max_iterations: Number(els.setMaxIterations.value),
      max_tokens: Number(els.setMaxTokens.value),
      tool_timeout_seconds: Number(els.setToolTimeout.value),
      stt_noise_adapt_k: Number(els.setNoiseK.value),
      max_speech_seconds: Number(els.setMaxSpeech.value),
      silence_duration: Number(els.setSilence.value),
    };
    els.settingsSave.disabled = true;
    els.settingsSave.textContent = "Сохранение…";
    try {
      const result = await Api.rpc("save_settings", payload);
      state.settings = Object.assign({}, state.settings, payload);
      state.mode = payload.chat_mode;
      state.preview = payload.transcript_preview;
      renderMode();
      renderSettings();
      toast((result && result.message) || "Настройки сохранены.", "success");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      els.settingsSave.disabled = false;
      els.settingsSave.textContent = "Сохранить";
    }
  }

  async function openPath(kind) {
    try {
      await Api.rpc("open_path", { kind: kind });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function runDoctor() {
    try {
      await Api.rpc("run_doctor");
      switchPage("journal");
      toast("Диагностика запущена. Результат появится в журнале.", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function refreshTasks() {
    try {
      const data = await Api.rpc("poll");
      if (data && data.snapshot) applySnapshot(data.snapshot);
      toast("Список задач обновлён.", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function refreshJournal() {
    try {
      const data = await Api.rpc("get_journal", { lines: 300 });
      state.journal = [
        { kind: "system", text: data.text || "Журнал пуст.", time: Date.now() },
      ];
      renderJournal();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function openAudit() {
    try {
      const data = await Api.rpc("get_audit", { lines: 200 });
      state.journal.push(
        { kind: "system", text: data.text || "Аудит пуст.", time: Date.now() }
      );
      renderJournal();
      switchPage("journal");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function clearJournal() {
    state.journal = [];
    renderJournal();
    toast("Журнал очищен.", "success");
  }

  function switchPage(page) {
    if (!PAGE_ORDER.includes(page)) return;
    state.page = page;
    document.body.dataset.page = page;
    document.querySelectorAll(".nav-item").forEach(function (item) {
      item.classList.toggle("active", item.dataset.page === page);
    });
    document.querySelectorAll("[data-page-panel]").forEach(function (panel) {
      panel.classList.toggle(
        "active",
        panel.dataset.pagePanel === page
      );
    });
    if (page === "tasks") renderTasks();
    if (page === "commands") renderCatalog();
    if (page === "journal") renderJournal();
    if (page === "agent") renderAgent();
    if (page === "settings") renderSettings();
  }

  function insertPrompt(prompt) {
    switchPage("chat");
    els.chatInput.value = prompt;
    els.chatInput.focus();
    els.chatInput.setSelectionRange(prompt.length, prompt.length);
  }

  function promptForCommand(item) {
    return item.description
      ? "Помоги выполнить: " + item.description
      : "Выполни: " + item.name;
  }

  function openPalette() {
    state.paletteOpen = true;
    els.palette.classList.remove("hidden");
    els.paletteInput.value = "";
    renderPalette("");
    setTimeout(function () {
      els.paletteInput.focus();
    }, 20);
  }

  function closePalette() {
    state.paletteOpen = false;
    els.palette.classList.add("hidden");
  }

  function renderPalette(query) {
    const search = String(query || "").trim().toLowerCase();
    const items = getCatalogItems().filter(function (item) {
      if (!search) return true;
      return (
        item.name.toLowerCase().indexOf(search) !== -1 ||
        item.description.toLowerCase().indexOf(search) !== -1
      );
    });
    state.paletteMatches = items.slice(0, 40);
    state.paletteIndex = 0;
    if (!state.paletteMatches.length) {
      els.paletteList.innerHTML =
        '<div class="command-empty">Ничего не найдено.</div>';
      return;
    }
    els.paletteList.innerHTML = "";
    state.paletteMatches.forEach(function (item, index) {
      const row = document.createElement("button");
      row.className = "palette-item" + (index === 0 ? " active" : "");
      row.dataset.paletteIndex = String(index);
      row.innerHTML =
        "<b>" +
        escapeHtml(item.name) +
        "</b><small>" +
        escapeHtml(truncate(item.description, 80)) +
        "</small>";
      els.paletteList.appendChild(row);
    });
  }

  function movePalette(delta) {
    if (!state.paletteMatches.length) return;
    state.paletteIndex =
      (state.paletteIndex + delta + state.paletteMatches.length) %
      state.paletteMatches.length;
    els.paletteList
      .querySelectorAll(".palette-item")
      .forEach(function (item, index) {
        item.classList.toggle(
          "active",
          index === state.paletteIndex
        );
      });
    const active = els.paletteList.querySelector(".palette-item.active");
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  function choosePalette(index) {
    const item = state.paletteMatches[index];
    if (!item) return;
    insertPrompt(promptForCommand(item));
    closePalette();
  }

  function isActiveTask(task) {
    return ["queued", "running", "pending", "starting", "waiting"].includes(
      normalizeTaskStatus(task.status)
    );
  }

  function normalizeTaskStatus(status) {
    const value = String(status || "").toLowerCase();
    if (["completed", "done", "success", "succeeded"].includes(value)) {
      return "done";
    }
    if (["failed", "error"].includes(value)) return "failed";
    if (["cancelled", "canceled"].includes(value)) return "cancelled";
    if (["queued", "pending", "starting", "waiting"].includes(value)) {
      return "queued";
    }
    if (["running", "processing", "in_progress"].includes(value)) {
      return "running";
    }
    return "queued";
  }

  function isNearBottom(element) {
    if (!element) return true;
    return (
      element.scrollTop + element.clientHeight >=
      element.scrollHeight - 90
    );
  }

  function percentage(value) {
    if (value == null || Number.isNaN(Number(value))) return "—";
    return Math.round(Number(value)) + "%";
  }

  function textOf(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (value && typeof value.text === "string") return value.text;
    return stringify(value);
  }

  function stringify(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value);
    } catch (error) {
      return String(value);
    }
  }

  function wireEvents() {
    document.addEventListener("click", function (event) {
      const windowAction = event.target.closest("[data-window-action]");
      if (windowAction) {
        const action = windowAction.dataset.windowAction;
        Api.call(action).catch(function (error) {
          toast(error.message, "error");
        });
        return;
      }

      const nav = event.target.closest(".nav-item[data-page]");
      if (nav) {
        switchPage(nav.dataset.page);
        return;
      }

      const opener = event.target.closest("[data-open-page]");
      if (opener) {
        switchPage(opener.dataset.openPage);
        return;
      }

      const quick = event.target.closest("[data-prompt]");
      if (quick) {
        insertPrompt(quick.dataset.prompt);
        return;
      }

      const command = event.target.closest("[data-command-index]");
      if (command) {
        const item = state.filteredCommands[Number(command.dataset.commandIndex)];
        if (item) insertPrompt(promptForCommand(item));
        return;
      }

      const paletteItem = event.target.closest("[data-palette-index]");
      if (paletteItem) {
        choosePalette(Number(paletteItem.dataset.paletteIndex));
        return;
      }

      if (event.target.closest("[data-palette-close]")) {
        closePalette();
        return;
      }

      const taskAction = event.target.closest("[data-task-id]");
      if (taskAction) {
        Api.rpc("cancel_task", { id: taskAction.dataset.taskId })
          .then(function () {
            toast("Задача отменена.", "success");
          })
          .catch(function (error) {
            toast(error.message, "error");
          });
        return;
      }

      const taskFilter = event.target.closest("[data-task-filter]");
      if (taskFilter) {
        state.taskFilter = taskFilter.dataset.taskFilter;
        els.taskFilter.querySelectorAll(".filter").forEach(function (item) {
          item.classList.toggle("active", item === taskFilter);
        });
        renderTasks();
        return;
      }

      const journalFilter = event.target.closest("[data-journal-filter]");
      if (journalFilter) {
        state.journalFilter = journalFilter.dataset.journalFilter;
        els.journalFilter.querySelectorAll(".filter").forEach(function (item) {
          item.classList.toggle("active", item === journalFilter);
        });
        renderJournal();
      }
    });

    els.sendButton.addEventListener("click", sendMessage);
    els.stopButton.addEventListener("click", stopAssistant);
    els.clearChat.addEventListener("click", function () {
      state.messages = [];
      renderMessages();
      toast("История чата очищена.", "success");
    });

    els.chatInput.addEventListener("keydown", function (event) {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });

    els.modeSelect.addEventListener("change", function () {
      setMode(els.modeSelect.value);
    });

    els.previewToggle.addEventListener("change", function () {
      setPreview(els.previewToggle.checked);
    });

    els.setPreview.addEventListener("change", function () {
      setPreview(els.setPreview.checked);
    });

    els.tasksRefresh.addEventListener("click", refreshTasks);
    els.journalRefresh.addEventListener("click", refreshJournal);
    els.journalAudit.addEventListener("click", openAudit);
    els.journalDoctor.addEventListener("click", runDoctor);
    els.journalClear.addEventListener("click", clearJournal);
    els.settingsSave.addEventListener("click", saveSettings);
    els.openConfig.addEventListener("click", function () {
      openPath("config");
    });
    els.openAudit.addEventListener("click", function () {
      openPath("audit");
    });
    els.runDoctor.addEventListener("click", runDoctor);
    els.stopAssistant.addEventListener("click", stopAssistant);
    els.quitApp.addEventListener("click", function () {
      if (window.confirm("Завершить JARVIS полностью?")) {
        Api.call("quit").catch(function (error) {
          toast(error.message, "error");
        });
      }
    });

    els.commandSearch.addEventListener(
      "input",
      U.debounce(function () {
        renderCatalog();
      }, 120)
    );
    els.commandCategory.addEventListener("change", renderCatalog);
    els.journalSearch.addEventListener(
      "input",
      U.debounce(function () {
        renderJournal();
      }, 120)
    );

    els.paletteClose.addEventListener("click", closePalette);
    els.paletteInput.addEventListener("input", function () {
      renderPalette(els.paletteInput.value);
    });
    els.paletteInput.addEventListener("keydown", function (event) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        movePalette(1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        movePalette(-1);
      } else if (event.key === "Enter") {
        event.preventDefault();
        choosePalette(state.paletteIndex);
      } else if (event.key === "Escape") {
        event.preventDefault();
        closePalette();
      }
    });

    document.addEventListener("keydown", function (event) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (state.paletteOpen) closePalette();
        else openPalette();
        return;
      }
      if (event.key === "Escape" && state.paletteOpen) {
        closePalette();
        return;
      }
      if (
        (event.ctrlKey || event.metaKey) &&
        /^[1-6]$/.test(event.key)
      ) {
        event.preventDefault();
        switchPage(PAGE_ORDER[Number(event.key) - 1]);
      }
    });
  }

  function init() {
    wireEvents();
    document.body.dataset.page = state.page;
    reactor.start();
    tick();
    setInterval(tick, 1000);
    setStatus(state.status);
    renderMode();
    renderMessages();
    renderTasks();
    renderContextTasks();
    renderContextTools();
    renderCatalog();
    renderAgent();
    renderJournal();
    renderSettings();
    Api.rpc("client_ready").catch(function () {});
    connect();
  }

  init();
})();
