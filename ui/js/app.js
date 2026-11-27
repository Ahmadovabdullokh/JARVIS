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
    mic_off: "MIC OFF",
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
    mic_off: "Микрофон выключен — можно печатать.",
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
    "camera",
    "settings",
  ];

  // История в памяти держит 350 сообщений, в DOM — последние 120:
  // перерисовка сотен узлов на слабом ноутбуке заметна на глаз.
  const MESSAGE_LIMIT = 350;
  const MESSAGE_DOM_LIMIT = 120;
  const STREAM_MARKDOWN_INTERVAL = 250;

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
    micEnabled: true,
    connected: false,
    sending: false,
    polling: false,
    pendingMessages: [],
    mediaRecorder: null,
    audioChunks: [],
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
    streamIndex: null,
    streamRow: null,
    streamBody: null,
    streamText: "",
    streamRaf: null,
    streamMarkdownAt: 0,
    messageStart: 0,
    showAllMessages: false,
    code: null,
    camera: null,
    gesture: null,
    cameraRenderAt: 0,
    cameraLegendKey: "",
    cameraStreamKey: "",
    cameraStreamError: false,
    cameraStreamErrorAt: 0,
    cameraStreamLoading: false,
    cameraBackground: true,
    performance: null,
    cameraImmersive: true,
    cameraDrawerOpen: false,
    cameraLegendOpen: false,
    cameraProbeBusy: false,
    lastGestureAction: "",
    lastGestureAt: 0,
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
    micButton: byId("mic-button"),
    micToggle: byId("mic-toggle"),
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
    ctxCpuBar: byId("ctx-cpu-bar"),
    ctxRamBar: byId("ctx-ram-bar"),
    ctxDiskBar: byId("ctx-disk-bar"),
    ctxBatBar: byId("ctx-bat-bar"),
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
    codePanel: byId("code-panel"),
    codePlanList: byId("code-plan-list"),
    codeFiles: byId("code-files"),
    codeChecks: byId("code-checks"),
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
    setPerfLite: byId("set-perf-lite"),
    setCategory: byId("set-category"),
    setMaxTools: byId("set-max-tools"),
    setCodeTools: byId("set-code-tools"),
    setMaxIterations: byId("set-max-iterations"),
    setMaxTokens: byId("set-max-tokens"),
    setToolTimeout: byId("set-tool-timeout"),
    setNoiseK: byId("set-noise-k"),
    setMaxSpeech: byId("set-max-speech"),
    setSilence: byId("set-silence"),
    setSpeakText: byId("set-speak-text"),
    openConfig: byId("open-config"),
    openAudit: byId("open-audit"),
    runDoctor: byId("run-doctor"),
    pairingShow: byId("pairing-show"),
    pairingBox: byId("pairing-box"),
    pairingQr: byId("pairing-qr"),
    pairingLink: byId("pairing-link"),
    pairingHint: byId("pairing-hint"),
    stopAssistant: byId("stop-assistant"),
    quitApp: byId("quit-app"),
    palette: byId("palette"),
    paletteInput: byId("palette-input"),
    paletteList: byId("palette-list"),
    paletteClose: byId("palette-close"),
    cameraStateChip: byId("camera-state-chip"),
    cameraToggle: byId("camera-toggle"),
    gestureToggle: byId("gesture-toggle"),
    cameraStream: byId("camera-stream"),
    cameraBackdrop: byId("camera-backdrop"),
    cameraPlaceholder: byId("camera-placeholder"),
    cameraBadge: byId("camera-badge"),
    cameraRec: byId("camera-rec"),
    cameraMeta: byId("camera-meta"),
    cameraSource: byId("camera-source"),
    cameraIndex: byId("camera-index"),
    cameraUrl: byId("camera-url"),
    cameraMirror: byId("camera-mirror"),
    cameraApply: byId("camera-apply"),
    cameraStop: byId("camera-stop"),
    cameraBackgroundToggle: byId("camera-background-toggle"),
    cameraImmersiveToggle: byId("camera-immersive-toggle"),
    cameraSettingsToggle: byId("camera-settings-toggle"),
    cameraDrawer: byId("camera-drawer"),
    cameraDrawerClose: byId("camera-drawer-close"),
    cameraFullscreen: byId("camera-fullscreen"),
    cameraExit: byId("camera-exit"),
    cameraLegendToggle: byId("camera-legend-toggle"),
    cameraLegendPanel: byId("camera-legend-panel"),
    cameraLegendClose: byId("camera-legend-close"),
    cameraLegendBody: byId("camera-legend-body"),
    cameraQualitySelect: byId("camera-quality-select"),
    cameraQualityApply: byId("camera-quality-apply"),
    cameraProbe: byId("camera-probe"),
    cameraProbeResult: byId("camera-probe-result"),
    gestureProfileSelect: byId("gesture-profile-select"),
    gesturePointer: byId("gesture-pointer"),
    gestureState: byId("gesture-state"),
    gestureStateDetail: byId("gesture-state-detail"),
    gestureHand: byId("gesture-hand"),
    gestureLast: byId("gesture-last"),
    gestureLastDetail: byId("gesture-last-detail"),
    gestureAction: byId("gesture-action"),
    gestureProfile: byId("gesture-profile"),
    gestureFps: byId("gesture-fps"),
    gestureLegend: byId("gesture-legend"),
    gestureError: byId("gesture-error"),
    cameraDriven: byId("camera-driven"),
    cameraBackend: byId("camera-backend"),
    cameraResolution: byId("camera-resolution"),
    cameraResolutionDetail: byId("camera-resolution-detail"),
    cameraFps: byId("camera-fps"),
    cameraFpsDetail: byId("camera-fps-detail"),
    cameraQuality: byId("camera-quality"),
    cameraClients: byId("camera-clients"),
  };

  const reactor = new window.JarvisReactor(els.reactor);

  function tick() {
    els.clock.textContent = formatClock(new Date());
    const uptime = (Date.now() - state.startedAt) / 1000;
    els.footerUptime.textContent = "UI uptime: " + formatUptime(uptime);
  }

  function connect() {
    try {
      Api.waitForBridge(7000).then(function () {
        return Api.rpc("bootstrap");
      }).then(function (data) {
        applyBootstrap(data || {});
        setConnected(true);
        hideBootSplash();
        if (!state.polling) {
          state.polling = true;
          poll();
        }
      }).catch(function () {
        setConnected(false);
        setTimeout(connect, 1400);
      });
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
      flushPendingMessages();
    } catch (error) {
      setConnected(false);
    } finally {
      if (state.polling) {
        setTimeout(poll, pollDelay());
      }
    }
  }

  function pollDelay() {
    if (typeof document !== "undefined" && document.hidden) {
      return 1000;
    }
    if (/^https?:$/.test(window.location.protocol)) {
      return 500;
    }
    const perf = state.performance || {};
    const serverDelay = Number(perf.poll_ms);
    if (serverDelay > 0) {
      return Math.max(120, serverDelay);
    }
    return 150;
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
    state.micEnabled = data.mic_enabled !== false;
    state.camera = data.camera || null;
    state.gesture = data.gesture || null;
    state.performance = data.performance || state.performance || null;
    applyProfileDefaults();
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
    renderMicToggle();
    renderCamera();
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
    if (typeof snapshot.mic_enabled === "boolean") {
      state.micEnabled = snapshot.mic_enabled;
      renderMicToggle();
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
    if (snapshot.camera || snapshot.gesture) {
      if (snapshot.camera) state.camera = snapshot.camera;
      if (snapshot.gesture) state.gesture = snapshot.gesture;
      if (Date.now() - state.cameraRenderAt > 350) {
        renderCamera();
      }
      applyCameraChrome();
      syncCameraStream();
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
      case "assistant": {
        const message = state.streamIndex != null
          ? state.messages[state.streamIndex]
          : null;
        if (message) {
          message.text = textOf(payload);
          message.time = Date.now();
          message.streaming = false;
          state.streamIndex = null;
          state.streamText = message.text;
          if (state.streamBody) {
            state.forceScroll = state.forceScroll ||
              isNearBottom(els.messageList);
            scheduleStreamRender(true);
            const stamp = state.streamRow &&
              state.streamRow.querySelector(".message-meta span");
            if (stamp) {
              stamp.textContent = formatClock(message.time);
            }
          } else {
            state.forceScroll = true;
            renderMessages();
          }
        } else {
          appendMessage("assistant", textOf(payload));
        }
        break;
      }
      case "assistant_partial":
        updateStreamMessage(textOf(payload));
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
      case "gesture":
        if (payload && typeof payload === "object") {
          state.lastGestureAction = payload.action || "none";
          state.lastGestureAt = Date.now();
          appendJournal(
            "system",
            "Жест: " + (payload.label || payload.name || "") +
              " → " + (payload.action || "none")
          );
          renderCamera();
        }
        break;
      case "command_catalog":
        state.catalog = Array.isArray(payload) ? payload : [];
        renderCatalog();
        break;
      case "code_state":
        state.code = payload && typeof payload === "object" ? payload : null;
        renderAgent();
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

  function updateStreamMessage(text) {
    if (!text) return;
    const nearBottom = isNearBottom(els.messageList);
    let message = state.streamIndex != null
      ? state.messages[state.streamIndex]
      : null;
    if (!message || message.role !== "assistant") {
      message = {
        role: "assistant",
        text: text,
        time: Date.now(),
        streaming: true,
      };
      state.messages.push(message);
      state.streamIndex = state.messages.length - 1;
      state.streamMarkdownAt = 0;
      if (trimMessageHistory()) {
        // Ветка «показать старые» больше не помещается — полный рендер.
        renderMessages();
      } else {
        const node = appendMessageNode(message);
        state.streamRow = node.row;
        state.streamBody = node.body;
      }
    } else if (message.text === text) {
      return;
    } else {
      message.text = text;
    }
    state.streamText = text;
    state.forceScroll = state.forceScroll || nearBottom;
    scheduleStreamRender(false);
  }

  function scheduleStreamRender(final) {
    if (!state.streamBody) return;
    if (final) {
      if (state.streamRaf != null) {
        cancelAnimationFrame(state.streamRaf);
        state.streamRaf = null;
      }
      flushStreamRender(true);
      return;
    }
    if (state.streamRaf != null) return;
    state.streamRaf = requestAnimationFrame(function () {
      state.streamRaf = null;
      flushStreamRender(false);
    });
  }

  function flushStreamRender(final) {
    const body = state.streamBody;
    if (!body) return;
    const text = state.streamText || "";
    const now = window.performance.now();
    const painted = final ||
      now - state.streamMarkdownAt >= STREAM_MARKDOWN_INTERVAL;
    if (painted) {
      // Markdown и подсветка дешёвы не для каждой дельты, а раз в 250 мс.
      state.streamMarkdownAt = now;
      body.innerHTML = renderMarkdown(text);
      enhanceCodeBlocks(body);
    } else {
      body.textContent = text;
    }
    if (state.forceScroll) {
      els.messageList.scrollTop = els.messageList.scrollHeight;
      state.forceScroll = false;
    }
  }

  function trimMessageHistory() {
    if (state.messages.length <= MESSAGE_LIMIT) return false;
    const drop = state.messages.length - MESSAGE_LIMIT;
    state.messages.splice(0, drop);
    if (state.streamIndex != null) {
      state.streamIndex = Math.max(0, state.streamIndex - drop);
    }
    state.messageStart = Math.max(0, state.messageStart - drop);
    if (state.showAllMessages) {
      // Сообщения выпали из истории — возвращаемся к компактному DOM.
      state.showAllMessages = false;
      return true;
    }
    return false;
  }

  function appendMessageNode(message) {
    const node = buildMessageNode(message);
    if (!state.showAllMessages &&
        state.messages.length - state.messageStart > MESSAGE_DOM_LIMIT) {
      const first = els.messageList.querySelector(".message");
      if (first) {
        first.remove();
        state.messageStart += 1;
      }
    }
    els.messageList.appendChild(node.row);
    ensureOlderButton();
    els.chatEmpty.classList.add("hidden");
    return node;
  }

  function ensureOlderButton() {
    let button = els.messageList.querySelector(".message-older");
    const hidden = state.messageStart;
    if (hidden <= 0) {
      if (button) button.remove();
      return;
    }
    if (!button) {
      button = document.createElement("button");
      button.type = "button";
      button.className = "message-older";
      button.addEventListener("click", function () {
        state.showAllMessages = true;
        renderMessages();
      });
      els.messageList.insertBefore(button, els.messageList.firstChild);
    }
    button.textContent = "ПОКАЗАТЬ СТАРЫЕ · " + hidden;
  }

  function enhanceCodeBlocks(container) {
    container.querySelectorAll("pre").forEach(function (pre) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "code-copy";
      button.textContent = "COPY";
      button.addEventListener("click", function () {
        const code = pre.querySelector("code");
        const text = (code || pre).innerText;
        copyText(text).then(function (ok) {
          button.textContent = ok ? "OK" : "FAIL";
          button.classList.toggle("copied", ok);
          setTimeout(function () {
            button.textContent = "COPY";
            button.classList.remove("copied");
          }, 1400);
        });
      });
      pre.appendChild(button);
    });
  }

  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).then(function () {
        return true;
      }).catch(function () {
        return legacyCopy(text);
      });
    }
    return Promise.resolve(legacyCopy(text));
  }

  function legacyCopy(text) {
    try {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    } catch (error) {
      return false;
    }
  }

  function hideBootSplash() {
    const splash = document.getElementById("boot-splash");
    if (splash) {
      splash.classList.add("done");
    }
  }

  function applyPerfLite(enabled, persist) {
    const active = Boolean(enabled);
    document.body.classList.toggle("perf-lite", active);
    if (els.setPerfLite) {
      els.setPerfLite.checked = active;
    }
    if (persist !== false) {
      try {
        localStorage.setItem("jarvis.lite", active ? "1" : "0");
      } catch (error) {
        /* storage is optional */
      }
    }
    if (reactor.setLite) {
      reactor.setLite(active);
    }
  }

  function hasPref(key) {
    try {
      return localStorage.getItem(key) !== null;
    } catch (error) {
      return false;
    }
  }

  function profileIsLow() {
    return Boolean(state.performance && state.performance.tier === "low");
  }

  function applyProfileDefaults() {
    // Сервер сообщает tier из app/performance.py. Явный выбор
    // пользователя в localStorage всегда главнее.
    const low = profileIsLow();
    if (!hasPref("jarvis.lite")) {
      applyPerfLite(low, false);
    }
    if (!hasPref("jarvis.camera.background")) {
      state.cameraBackground = !low;
      applyCameraChrome();
    }
  }

  function initPerfLite() {
    let enabled = false;
    try {
      enabled = localStorage.getItem("jarvis.lite") === "1";
    } catch (error) {
      enabled = false;
    }
    applyPerfLite(enabled);
  }

  function readPref(key, fallback) {
    try {
      const value = localStorage.getItem(key);
      if (value === null) return fallback;
      return value === "1";
    } catch (error) {
      return fallback;
    }
  }

  function savePref(key, enabled) {
    try {
      localStorage.setItem(key, enabled ? "1" : "0");
    } catch (error) {
      /* storage is optional */
    }
  }

  function initCameraPrefs() {
    state.cameraBackground = readPref("jarvis.camera.background", true);
    state.cameraImmersive = readPref("jarvis.camera.immersive", true);
    applyCameraChrome();
  }

  function applyCameraChrome() {
    const running = cameraRunning();
    const onPage = state.page === "camera";
    const background = state.cameraBackground !== false;
    const immersive = onPage && running && state.cameraImmersive !== false;
    const showBackdrop = running && (onPage || background);
    document.body.classList.toggle("camera-bg", showBackdrop);
    document.body.classList.toggle("camera-immersive", immersive);
    document.body.classList.toggle(
      "camera-live",
      running && !String((state.camera || {}).error || "").trim()
    );
    if (els.cameraBackdrop) {
      els.cameraBackdrop.classList.toggle("is-live", showBackdrop);
    }
    if (els.cameraBackgroundToggle) {
      els.cameraBackgroundToggle.textContent = background
        ? "ФОН ON"
        : "ФОН OFF";
      els.cameraBackgroundToggle.classList.toggle("active", background);
    }
    if (els.cameraImmersiveToggle) {
      els.cameraImmersiveToggle.textContent =
        state.cameraImmersive !== false ? "HUD ON" : "HUD OFF";
      els.cameraImmersiveToggle.classList.toggle(
        "active",
        state.cameraImmersive !== false
      );
    }
    if (els.cameraDrawer) {
      els.cameraDrawer.classList.toggle("open", state.cameraDrawerOpen);
    }
    if (els.cameraLegendPanel) {
      els.cameraLegendPanel.classList.toggle("open", state.cameraLegendOpen);
    }
    if (els.cameraFullscreen) {
      const active = Boolean(
        document.fullscreenElement || document.webkitFullscreenElement
      );
      els.cameraFullscreen.textContent = active ? "WINDOW" : "FULLSCREEN";
    }
  }

  function openCameraDrawer(open) {
    state.cameraDrawerOpen = Boolean(open);
    if (open) state.cameraLegendOpen = false;
    applyCameraChrome();
  }

  function openCameraLegend(open) {
    state.cameraLegendOpen = Boolean(open);
    if (open) state.cameraDrawerOpen = false;
    applyCameraChrome();
  }

  function toggleCameraFullscreen() {
    const active = Boolean(
      document.fullscreenElement || document.webkitFullscreenElement
    );
    const request = document.documentElement.requestFullscreen ||
      document.documentElement.webkitRequestFullscreen;
    const exit = document.exitFullscreen ||
      document.webkitExitFullscreen;
    if (active) {
      if (exit) exit.call(document);
      return;
    }
    if (!request) {
      toast("Fullscreen недоступен в этом окне.", "warning");
      return;
    }
    Promise.resolve(request.call(document.documentElement)).catch(function () {
      toast("Не удалось включить fullscreen.", "error");
    });
  }

  function buildMessageNode(message) {
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
      enhanceCodeBlocks(body);
    } else {
      body.innerHTML = escapeHtml(message.text).replace(/\n/g, "<br>");
    }
    row.appendChild(meta);
    row.appendChild(body);
    return { row: row, body: body };
  }

  function appendMessage(role, value) {
    const text = String(value == null ? "" : value).trim();
    if (!text) return;
    const message = { role: role, text: text, time: Date.now() };
    state.messages.push(message);
    const nearBottom = state.forceScroll || isNearBottom(els.messageList);
    if (trimMessageHistory()) {
      renderMessages();
      return;
    }
    appendMessageNode(message);
    if (nearBottom) {
      els.messageList.scrollTop = els.messageList.scrollHeight;
    }
    state.forceScroll = false;
  }

  function renderMessages() {
    const nearBottom = isNearBottom(els.messageList);
    const total = state.messages.length;
    const span = state.showAllMessages ? total : MESSAGE_DOM_LIMIT;
    state.messageStart = Math.max(0, total - span);
    state.streamRow = null;
    state.streamBody = null;
    const fragment = document.createDocumentFragment();
    for (let index = state.messageStart; index < total; index += 1) {
      const message = state.messages[index];
      const node = buildMessageNode(message);
      if (message.streaming) {
        state.streamRow = node.row;
        state.streamBody = node.body;
      }
      fragment.appendChild(node.row);
    }
    els.messageList.innerHTML = "";
    els.messageList.appendChild(fragment);
    ensureOlderButton();
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
    renderCodeState();
  }

  function renderCodeState() {
    const data = state.code;
    if (!data || !els.codePanel) {
      if (els.codePanel) els.codePanel.hidden = true;
      return;
    }
    els.codePanel.hidden = false;
    const markers = {
      pending: "[ ]",
      running: "[~]",
      done: "[x]",
      failed: "[!]",
      blocked: "[#]",
    };
    const plan = Array.isArray(data.plan) ? data.plan : [];
    els.codePlanList.innerHTML = "";
    if (!plan.length) {
      els.codePlanList.textContent = data.goal || "План пока не составлен.";
    } else {
      plan.forEach(function (item, index) {
        const row = document.createElement("div");
        row.className = "code-row";
        row.textContent =
          (index + 1) +
          ". " +
          (markers[item.status] || "[ ]") +
          " " +
          String(item.step || "");
        els.codePlanList.appendChild(row);
      });
    }
    const files = Array.isArray(data.changed_files)
      ? data.changed_files
      : [];
    els.codeFiles.innerHTML = "";
    if (!files.length) {
      els.codeFiles.textContent = "Изменений пока нет.";
    } else {
      files.slice(-12).forEach(function (path) {
        const row = document.createElement("div");
        row.className = "code-row";
        row.textContent = String(path);
        els.codeFiles.appendChild(row);
      });
    }
    const checks = Array.isArray(data.checks) ? data.checks : [];
    els.codeChecks.innerHTML = "";
    if (!checks.length) {
      els.codeChecks.textContent = data.verified
        ? "Проверено."
        : "Проверок пока нет.";
    } else {
      checks.slice(-5).forEach(function (item) {
        const row = document.createElement("div");
        row.className = "code-row " + (item.ok ? "ok" : "fail");
        row.textContent =
          (item.ok ? "[OK] " : "[FAIL] ") +
          String(item.name || "check") +
          " — " +
          String(item.detail || "").slice(0, 220);
        els.codeChecks.appendChild(row);
      });
    }
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
    els.setSpeakText.checked = settings.speak_text !== false;
    els.previewToggle.checked = Boolean(settings.transcript_preview);
  }

  function setNumber(input, value, fallback) {
    input.value = String(value == null ? fallback : value);
  }

  function cameraRunning() {
    return Boolean(state.camera && state.camera.running);
  }

  function gestureRunning() {
    return Boolean(state.gesture && state.gesture.running);
  }

  function sourceLabel(source) {
    if (source === "phone") return "Камера телефона";
    return source === "network" ? "IP Webcam / сеть" : "Камера ПК";
  }

  function setValueIfIdle(input, value) {
    if (!input || document.activeElement === input) return;
    input.value = value == null ? "" : String(value);
  }

  function renderCamera() {
    state.cameraRenderAt = Date.now();
    const camera = state.camera || {};
    const gesture = state.gesture || {};
    const running = Boolean(camera.running);
    const phoneSource = camera.source === "phone";
    const phoneState = String(camera.phone_state || "");
    const cameraErrorText = String(camera.error || "").trim();
    const live = running && !cameraErrorText &&
      (!phoneSource || phoneState === "live");
    setValueIfIdle(els.cameraSource, camera.source || "pc");
    setValueIfIdle(els.cameraIndex, camera.index == null ? 0 : camera.index);
    setValueIfIdle(els.cameraUrl, camera.url || "");
    const uiSource = els.cameraSource.value || camera.source || "pc";
    els.cameraUrl.disabled = uiSource !== "network";
    els.cameraIndex.disabled = uiSource !== "pc";
    if (document.activeElement !== els.cameraMirror) {
      els.cameraMirror.checked = camera.mirror !== false;
    }
    if (els.cameraStateChip) {
      let chip = "CAMERA OFF";
      if (live) {
        chip = "CAMERA LIVE";
      } else if (running) {
        chip = phoneSource && !cameraErrorText
          ? "CAMERA WAIT" : "CAMERA ERROR";
      }
      els.cameraStateChip.textContent = chip;
      els.cameraStateChip.className =
        "mode-chip " + (live ? "tasks" : "chat");
    }
    if (els.cameraToggle) {
      els.cameraToggle.textContent = running
        ? "Остановить камеру"
        : "Включить камеру";
    }
    if (els.gestureToggle) {
      els.gestureToggle.textContent = gesture.running
        ? "Жесты ON"
        : "Жесты OFF";
      els.gestureToggle.disabled = !running;
    }
    const resolution =
      camera.width && camera.height
        ? camera.width + "x" + camera.height
        : "—";
    const fps = String(camera.capture_fps || camera.fps || 0);
    if (els.cameraBadge) {
      let badge = "OFF";
      if (live) {
        badge = "LIVE";
      } else if (running) {
        badge = phoneSource && !cameraErrorText ? "WAIT" : "ERROR";
      }
      els.cameraBadge.textContent = badge;
    }
    if (els.cameraDriven) {
      els.cameraDriven.textContent = sourceLabel(camera.source);
    }
    if (els.cameraBackend) {
      els.cameraBackend.textContent =
        String(camera.backend || "auto").toUpperCase();
    }
    if (els.cameraResolution) els.cameraResolution.textContent = resolution;
    if (els.cameraResolutionDetail) {
      els.cameraResolutionDetail.textContent = resolution;
    }
    if (els.cameraFps) els.cameraFps.textContent = fps;
    if (els.cameraFpsDetail) els.cameraFpsDetail.textContent = fps;
    if (els.cameraQuality) {
      els.cameraQuality.textContent = String(camera.quality || "—");
    }
    if (els.cameraClients) {
      els.cameraClients.textContent = String(camera.clients || 0);
    }
    if (els.cameraQualitySelect && document.activeElement !==
        els.cameraQualitySelect) {
      els.cameraQualitySelect.value = camera.quality || "balanced";
    }
    const gestureState = gesture.running
      ? (gesture.model_ready ? "ON" : "LOADING")
      : "OFF";
    if (els.gestureState) els.gestureState.textContent = gestureState;
    if (els.gestureStateDetail) {
      els.gestureStateDetail.textContent = gestureState;
    }
    if (els.gestureHand) els.gestureHand.textContent = gesture.hand || "—";
    if (els.gestureLast) {
      els.gestureLast.textContent = gesture.last_gesture_label || "—";
    }
    if (els.gestureLastDetail) {
      els.gestureLastDetail.textContent =
        gesture.last_gesture_label || "—";
    }
    const action = state.lastGestureAction || gesture.last_action || "";
    if (els.gestureAction) {
      els.gestureAction.textContent = action || "—";
    }
    if (els.gestureProfile) {
      els.gestureProfile.textContent =
        gesture.profile_label || gesture.profile || "—";
    }
    if (els.gestureProfileSelect &&
        document.activeElement !== els.gestureProfileSelect) {
      els.gestureProfileSelect.value = gesture.profile || "media";
    }
    if (els.gesturePointer) {
      els.gesturePointer.checked = Boolean(
        gesture.pointer && gesture.pointer.enabled
      );
    }
    if (els.gestureFps) els.gestureFps.textContent = String(gesture.fps || 0);
    const gestureError = String(gesture.error || "").trim();
    if (els.gestureError) {
      els.gestureError.textContent = gestureError;
      els.gestureError.hidden = !gestureError;
    }
    if (els.cameraMeta) {
      if (cameraErrorText) {
        els.cameraMeta.textContent = cameraErrorText;
      } else if (phoneSource) {
        els.cameraMeta.textContent = phoneState === "live"
          ? sourceLabel(camera.source) + " · " +
            (camera.phone_device || "телефон") + " · " +
            resolution + " · " + fps + " fps"
          : "Ожидание кадров с телефона (приложение JARVIS).";
      } else if (running) {
        els.cameraMeta.textContent =
          sourceLabel(camera.source) + " · " + resolution +
          " · " + fps + " fps · " + (camera.quality || "balanced");
      } else {
        els.cameraMeta.textContent = "Оптический контур готов.";
      }
    }
    if (els.cameraPlaceholder) {
      els.cameraPlaceholder.hidden = live && !state.cameraStreamError;
    }
    renderGestureLegend(gesture);
    applyCameraChrome();
    syncCameraStream();
  }

  function renderGestureLegend(gesture) {
    if (!els.gestureLegend && !els.cameraLegendBody) return;
    const gestures = Array.isArray(gesture.gestures)
      ? gesture.gestures
      : [];
    const actionMap = gesture.action_map || {};
    const key = JSON.stringify([
      gesture.profile || "media",
      gestures,
      actionMap,
    ]);
    if (key === state.cameraLegendKey) return;
    state.cameraLegendKey = key;
    const html = gestures.map(function (item) {
      const name = String(item.name || "");
      const action = String(actionMap[name] || "none");
      return (
        '<div class="gesture-legend-row"><b>' +
        escapeHtml(item.label || name) +
        "</b><span>" +
        escapeHtml(action) +
        "</span></div>"
      );
    }).join("");
    if (els.gestureLegend) els.gestureLegend.innerHTML = html;
    if (els.cameraLegendBody) els.cameraLegendBody.innerHTML = html;
  }

  function cameraStreamWanted() {
    if (!cameraRunning()) return false;
    if (profileIsLow() && state.cameraBackground === false) {
      // На слабом железе не тянем MJPEG вне страницы камеры.
      return state.page === "camera";
    }
    return state.page === "camera" || state.cameraBackground !== false;
  }

  function syncCameraStream() {
    if (!els.cameraStream) return;
    const wanted = cameraStreamWanted();
    const onPage = state.page === "camera";
    if (!wanted) {
      if (els.cameraStream.getAttribute("src")) {
        els.cameraStream.removeAttribute("src");
      }
      els.cameraStream.hidden = true;
      state.cameraStreamKey = "";
      state.cameraStreamLoading = false;
      if (els.cameraPlaceholder) els.cameraPlaceholder.hidden = false;
      if (els.cameraBackdrop) els.cameraBackdrop.classList.remove("is-live");
      applyCameraChrome();
      return;
    }
    if (state.cameraStreamKey) {
      els.cameraStream.hidden = false;
      if (els.cameraPlaceholder) {
        els.cameraPlaceholder.hidden = !state.cameraStreamError;
      }
      if (els.cameraBackdrop) {
        els.cameraBackdrop.classList.add("is-live");
      }
      applyCameraChrome();
      return;
    }
    if (state.cameraStreamLoading) return;
    if (state.cameraStreamError &&
        Date.now() - state.cameraStreamErrorAt < 5000) {
      return;
    }
    state.cameraStreamLoading = true;
    const applyUrl = function (url) {
      state.cameraStreamLoading = false;
      if (!url || !cameraStreamWanted()) return;
      state.cameraStreamError = false;
      state.cameraStreamKey = url;
      els.cameraStream.hidden = false;
      if (els.cameraPlaceholder) els.cameraPlaceholder.hidden = true;
      if (els.cameraBackdrop) els.cameraBackdrop.classList.add("is-live");
      els.cameraStream.src = url;
      els.cameraStream.onerror = function () {
        state.cameraStreamError = true;
        state.cameraStreamErrorAt = Date.now();
        state.cameraStreamKey = "";
        els.cameraStream.hidden = true;
        els.cameraStream.removeAttribute("src");
        if (onPage && els.cameraPlaceholder) {
          els.cameraPlaceholder.hidden = false;
        }
        if (els.cameraBackdrop) {
          els.cameraBackdrop.classList.remove("is-live");
        }
        applyCameraChrome();
      };
      applyCameraChrome();
    };
    if (/^https?:$/.test(window.location.protocol)) {
      applyUrl("/camera.mjpg?ts=" + Date.now());
      return;
    }
    Api.rpc("get_camera_stream_url")
      .then(function (data) {
        applyUrl((data && data.url) || "");
      })
      .catch(function () {
        state.cameraStreamLoading = false;
        applyUrl("http://127.0.0.1:8765/camera.mjpg");
      });
  }

  async function applyCamera() {
    const source = els.cameraSource.value;
    const url = els.cameraUrl.value.trim();
    if (source === "network" && !url) {
      toast("Укажите URL потока IP Webcam.", "warning");
      return;
    }
    const payload = {
      enabled: true,
      source: source,
      index: Number(els.cameraIndex.value) || 0,
      url: url,
      mirror: els.cameraMirror.checked,
    };
    if (source === "phone") {
      // Телефон отдаёт готовый кадр: URL не нужен, зеркало
      // по умолчанию выключено (иначе задняя камера отражена).
      delete payload.url;
      delete payload.mirror;
    }
    try {
      const data = await Api.rpc("set_camera", payload);
      applyCameraData(data);
      toast(
        source === "phone"
          ? "Ждём кадры с телефона — запустите камеру в приложении."
          : "Камера подключена.",
        "success"
      );
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function stopCamera() {
    try {
      const data = await Api.rpc("set_camera", { enabled: false });
      applyCameraData(data);
      toast("Камера остановлена.", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function applyCameraData(data, resetStream) {
    if (!data) return;
    if (data.camera) state.camera = data.camera;
    if (data.gesture) state.gesture = data.gesture;
    if (resetStream !== false) state.cameraStreamKey = "";
    state.cameraStreamError = false;
    state.cameraStreamErrorAt = 0;
    state.cameraStreamLoading = false;
    renderCamera();
  }

  async function toggleCamera() {
    if (cameraRunning()) {
      await stopCamera();
      return;
    }
    await applyCamera();
  }

  async function toggleGestures() {
    try {
      const data = await Api.rpc("set_gestures", {
        enabled: !gestureRunning(),
      });
      applyCameraData(data, false);
      toast(
        gestureRunning() ? "Жесты включены." : "Жесты выключены.",
        "success"
      );
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function setCameraQuality() {
    if (!els.cameraQualitySelect) return;
    const quality = els.cameraQualitySelect.value;
    try {
      const data = await Api.rpc("set_camera_quality", {
        quality: quality,
      });
      applyCameraData(data);
      toast("Качество камеры: " + quality + ".", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function setCameraBackground(enabled) {
    state.cameraBackground = Boolean(enabled);
    savePref("jarvis.camera.background", state.cameraBackground);
    applyCameraChrome();
    syncCameraStream();
    try {
      await Api.rpc("set_camera_background", {
        enabled: state.cameraBackground,
        immersive: state.cameraImmersive !== false,
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function toggleImmersive() {
    state.cameraImmersive = state.cameraImmersive === false;
    savePref("jarvis.camera.immersive", state.cameraImmersive);
    applyCameraChrome();
    try {
      await Api.rpc("set_camera_background", {
        enabled: state.cameraBackground !== false,
        immersive: state.cameraImmersive,
      });
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function setGestureProfile(profile) {
    try {
      const data = await Api.rpc("set_gestures_profile", {
        profile: profile,
      });
      applyCameraData(data, false);
      if (profile === "pointer") {
        toast("Курсор включён. Кулак или ладонь — пауза.", "warning");
      } else {
        toast("Профиль жестов: " + profile + ".", "success");
      }
    } catch (error) {
      renderCamera();
      toast(error.message, "error");
    }
  }

  async function setGesturePointer(enabled) {
    try {
      const data = await Api.rpc("set_pointer", {
        enabled: Boolean(enabled),
      });
      applyCameraData(data, false);
      toast(
        enabled ? "Управление курсором включено." : "Курсор выключен.",
        enabled ? "warning" : "success"
      );
    } catch (error) {
      renderCamera();
      toast(error.message, "error");
    }
  }

  async function probeCameras() {
    if (state.cameraProbeBusy) return;
    state.cameraProbeBusy = true;
    if (els.cameraProbe) {
      els.cameraProbe.disabled = true;
      els.cameraProbe.textContent = "Проверка…";
    }
    if (els.cameraProbeResult) {
      els.cameraProbeResult.textContent =
        "Проверяю индексы 0–3. Это может занять несколько секунд.";
    }
    try {
      const data = await Api.rpc("probe_cameras");
      const cameras = Array.isArray(data && data.cameras)
        ? data.cameras
        : [];
      if (els.cameraProbeResult) {
        if (!cameras.length) {
          els.cameraProbeResult.textContent = "Камеры не найдены.";
        } else {
          els.cameraProbeResult.textContent = cameras.map(function (item) {
            return "#" + item.index + " · " + item.backend + " · " +
              (item.width || "?") + "x" + (item.height || "?") +
              " · " + (item.capture_fps || item.measured_fps || 0) +
              " fps" + (item.blank ? " · ЧЁРНЫЙ/ВИРТУАЛЬНЫЙ" : "");
          }).join("\n");
        }
      }
      const best = cameras.find(function (item) {
        return !item.blank && item.width && item.height;
      });
      if (best && els.cameraIndex) {
        els.cameraIndex.value = String(best.index);
      }
      toast(
        cameras.length ? "Проверка камер завершена." : "Камеры не найдены.",
        cameras.length ? "success" : "warning"
      );
    } catch (error) {
      toast(error.message, "error");
      if (els.cameraProbeResult) {
        els.cameraProbeResult.textContent = error.message;
      }
    } finally {
      state.cameraProbeBusy = false;
      if (els.cameraProbe) {
        els.cameraProbe.disabled = false;
        els.cameraProbe.textContent = "Проверить камеры";
      }
    }
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
    setGauge(
      els.ctxCpuBar,
      available ? percentageNumber(data.cpu) : 0
    );
    setGauge(
      els.ctxRamBar,
      available ? percentageNumber(data.memory) : 0
    );
    setGauge(
      els.ctxDiskBar,
      available ? percentageNumber(data.disk) : 0
    );
    setGauge(
      els.ctxBatBar,
      data.battery && !Number.isNaN(Number(data.battery.percent))
        ? Number(data.battery.percent)
        : 0
    );
    els.ctxUptime.textContent = data.uptime || "—";
  }

  function percentageNumber(value) {
    if (value == null || Number.isNaN(Number(value))) return 0;
    return Math.max(0, Math.min(100, Number(value)));
  }

  function setGauge(element, value) {
    if (element) {
      element.style.width = Math.round(value) + "%";
    }
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
    const raw = state.micEnabled === false ? 0 : Number(value) || 0;
    const normalized = Math.min(1, Math.max(0, raw / 0.03));
    els.micFill.style.width = Math.round(normalized * 100) + "%";
    els.micValue.textContent = Math.round(normalized * 100) + "%";
  }

  function queueMessage(text) {
    state.pendingMessages.push({ text: text, mode: state.mode });
    if (state.pendingMessages.length > 20) {
      state.pendingMessages.shift();
    }
    toast("Нет связи — сообщение в очереди (" +
      state.pendingMessages.length + ").", "warning");
  }

  async function flushPendingMessages() {
    if (!state.pendingMessages.length) return;
    while (state.pendingMessages.length && !state.sending) {
      const item = state.pendingMessages[0];
      try {
        await Api.rpc("send_message", {
          text: item.text,
          mode: item.mode || state.mode,
        });
        state.pendingMessages.shift();
      } catch (error) {
        break;
      }
    }
    if (!state.pendingMessages.length) {
      toast("Очередь сообщений отправлена.", "success");
    }
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
      if (/^https?:$/.test(window.location.protocol)) {
        queueMessage(text);
        els.chatInput.value = "";
      } else {
        toast(error.message, "error");
      }
    } finally {
      state.sending = false;
      updateSendButton();
    }
  }

  async function toggleVoiceInput() {
    if (state.mediaRecorder &&
        state.mediaRecorder.state !== "inactive") {
      state.mediaRecorder.stop();
      return;
    }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      toast("Браузер не поддерживает запись с микрофона.", "error");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      state.audioChunks = [];
      state.mediaRecorder = new MediaRecorder(stream);
      state.mediaRecorder.ondataavailable = function (event) {
        if (event.data && event.data.size) {
          state.audioChunks.push(event.data);
        }
      };
      state.mediaRecorder.onstop = async function () {
        stream.getTracks().forEach(function (track) { track.stop(); });
        els.micButton.classList.remove("recording");
        await sendAudioForStt();
      };
      state.mediaRecorder.start();
      els.micButton.classList.add("recording");
      els.micButton.textContent = "■";
      toast("Идёт запись… нажмите MIC ещё раз для остановки.", "system");
    } catch (error) {
      toast("Нет доступа к микрофону: " + error.message, "error");
    }
  }

  async function sendAudioForStt() {
    if (!state.audioChunks.length) return;
    const blob = new Blob(state.audioChunks, {
      type: state.mediaRecorder
        ? state.mediaRecorder.mimeType || "audio/webm"
        : "audio/webm",
    });
    els.micButton.disabled = true;
    try {
      // Авторизация — HttpOnly-cookie; токен не светим в URL.
      const response = await fetch("/stt", {
        method: "POST",
        credentials: "same-origin",
        body: blob,
      });
      const data = await response.json().catch(function () { return {}; });
      if (!response.ok || !data.ok) {
        throw new Error(data.error || "Ошибка распознавания.");
      }
      const text = String(data.text || "").trim();
      if (text) {
        els.chatInput.value = text;
        els.chatInput.focus();
      } else {
        toast("Ничего не распознано.", "warning");
      }
    } catch (error) {
      toast("Голосовой ввод: " + error.message, "error");
    } finally {
      els.micButton.disabled = false;
      els.micButton.textContent = "MIC";
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

  function renderMicToggle() {
    if (!els.micToggle) return;
    const enabled = state.micEnabled !== false;
    els.micToggle.textContent = enabled ? "MIC ON" : "MIC OFF";
    els.micToggle.classList.toggle("off", !enabled);
    els.micToggle.setAttribute("aria-pressed", enabled ? "true" : "false");
    els.micToggle.title = enabled
      ? "Выключить микрофон (шумная комната)"
      : "Включить микрофон";
    if (!enabled) {
      updateMic(0);
    }
  }

  async function toggleMicrophone() {
    const previous = state.micEnabled !== false;
    state.micEnabled = !previous;
    renderMicToggle();
    try {
      const data = await Api.rpc("set_microphone", {
        enabled: state.micEnabled,
      });
      state.micEnabled = Boolean(data && data.enabled);
      renderMicToggle();
      toast(
        state.micEnabled ? "Микрофон включён." : "Микрофон выключен.",
        "system"
      );
    } catch (error) {
      state.micEnabled = previous;
      renderMicToggle();
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
      speak_text: els.setSpeakText.checked,
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

  async function showPairing() {
    if (!els.pairingShow) return;
    if (/^https?:$/.test(window.location.protocol)) {
      toast("QR доступен только в приложении JARVIS на ПК.", "error");
      return;
    }
    els.pairingShow.disabled = true;
    els.pairingShow.textContent = "Готовлю QR…";
    try {
      const data = await Api.rpc("get_pairing");
      els.pairingBox.classList.remove("hidden");
      if (data.qr) {
        els.pairingQr.src = data.qr;
        els.pairingQr.hidden = false;
      } else {
        els.pairingQr.hidden = true;
      }
      els.pairingLink.value = data.link || "";
      const lines = [];
      if (data.url) {
        const tailscalePrimary =
          data.tailscale_url && data.url === data.tailscale_url;
        lines.push(
          (tailscalePrimary
            ? "Адрес (любая сеть, Tailscale): "
            : "Адрес: ") + data.url
        );
      }
      if (data.fallback_url) {
        lines.push("Запасной адрес (домашняя сеть): " + data.fallback_url);
      }
      lines.push(
        "Отсканируйте QR приложением JARVIS или скопируйте ссылку " +
          "и вставьте её в настройках приложения."
      );
      if (data.qr) {
        lines.push("Нажмите на QR, чтобы увеличить его на экране.");
      }
      if (data.hint) lines.push(data.hint);
      els.pairingHint.textContent = lines.join("\n");
    } catch (error) {
      toast(error.message, "error");
    } finally {
      els.pairingShow.disabled = false;
      els.pairingShow.textContent = "Показать QR для телефона";
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
    if (page === "camera") renderCamera();
    if (page === "settings") renderSettings();
    if (page !== "camera") {
      state.cameraDrawerOpen = false;
      state.cameraLegendOpen = false;
    }
    applyCameraChrome();
    syncCameraStream();
    if (reactor.setActive) {
      reactor.setActive(page === "chat");
    }
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
    if (els.micToggle) {
      els.micToggle.addEventListener("click", toggleMicrophone);
    }
    els.micButton.addEventListener("click", toggleVoiceInput);
    if (/^https?:$/.test(window.location.protocol) &&
        navigator.mediaDevices && window.MediaRecorder) {
      els.micButton.hidden = false;
    }
    els.stopButton.addEventListener("click", stopAssistant);
    els.clearChat.addEventListener("click", function () {
      state.messages = [];
      state.streamIndex = null;
      state.streamRow = null;
      state.streamBody = null;
      state.streamText = "";
      state.messageStart = 0;
      state.showAllMessages = false;
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

    els.setPerfLite.addEventListener("change", function () {
      applyPerfLite(els.setPerfLite.checked);
    });

    els.tasksRefresh.addEventListener("click", refreshTasks);
    els.journalRefresh.addEventListener("click", refreshJournal);
    els.journalAudit.addEventListener("click", openAudit);
    els.journalDoctor.addEventListener("click", runDoctor);
    els.journalClear.addEventListener("click", clearJournal);
    els.settingsSave.addEventListener("click", saveSettings);
    if (els.cameraToggle) {
      els.cameraToggle.addEventListener("click", toggleCamera);
      els.gestureToggle.addEventListener("click", toggleGestures);
      els.cameraApply.addEventListener("click", applyCamera);
      els.cameraStop.addEventListener("click", stopCamera);
      els.cameraSource.addEventListener("change", function () {
        const value = els.cameraSource.value;
        els.cameraUrl.disabled = value !== "network";
        els.cameraIndex.disabled = value !== "pc";
      });
    }
    if (els.cameraBackgroundToggle) {
      els.cameraBackgroundToggle.addEventListener("click", function () {
        setCameraBackground(state.cameraBackground === false);
      });
    }
    if (els.cameraImmersiveToggle) {
      els.cameraImmersiveToggle.addEventListener("click", toggleImmersive);
    }
    if (els.cameraSettingsToggle) {
      els.cameraSettingsToggle.addEventListener("click", function () {
        openCameraDrawer(!state.cameraDrawerOpen);
      });
    }
    if (els.cameraDrawerClose) {
      els.cameraDrawerClose.addEventListener("click", function () {
        openCameraDrawer(false);
      });
    }
    if (els.cameraLegendToggle) {
      els.cameraLegendToggle.addEventListener("click", function () {
        openCameraLegend(!state.cameraLegendOpen);
      });
    }
    if (els.cameraLegendClose) {
      els.cameraLegendClose.addEventListener("click", function () {
        openCameraLegend(false);
      });
    }
    if (els.cameraFullscreen) {
      els.cameraFullscreen.addEventListener("click", toggleCameraFullscreen);
      document.addEventListener("fullscreenchange", applyCameraChrome);
      document.addEventListener("webkitfullscreenchange", applyCameraChrome);
    }
    if (els.cameraExit) {
      els.cameraExit.addEventListener("click", function () {
        switchPage("chat");
      });
    }
    if (els.cameraQualityApply) {
      els.cameraQualityApply.addEventListener("click", setCameraQuality);
    }
    if (els.cameraProbe) {
      els.cameraProbe.addEventListener("click", probeCameras);
    }
    if (els.gestureProfileSelect) {
      els.gestureProfileSelect.addEventListener("change", function () {
        setGestureProfile(els.gestureProfileSelect.value);
      });
    }
    if (els.gesturePointer) {
      els.gesturePointer.addEventListener("change", function () {
        setGesturePointer(els.gesturePointer.checked);
      });
    }
    els.openConfig.addEventListener("click", function () {
      openPath("config");
    });
    els.openAudit.addEventListener("click", function () {
      openPath("audit");
    });
    els.runDoctor.addEventListener("click", runDoctor);
    if (els.pairingShow) {
      els.pairingShow.addEventListener("click", showPairing);
    }
    if (els.pairingLink) {
      els.pairingLink.addEventListener("click", function () {
        els.pairingLink.select();
      });
    }
    if (els.pairingQr) {
      els.pairingQr.addEventListener("click", function () {
        if (!els.pairingQr.src || els.pairingQr.hidden) return;
        const overlay = document.createElement("div");
        overlay.className = "qr-overlay";
        const image = document.createElement("img");
        image.alt = "QR-код подключения";
        image.src = els.pairingQr.src;
        overlay.appendChild(image);
        overlay.addEventListener("click", function () {
          overlay.remove();
        });
        document.body.appendChild(overlay);
      });
    }
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
      if (event.key === "Escape" && state.cameraDrawerOpen) {
        openCameraDrawer(false);
        return;
      }
      if (event.key === "Escape" && state.cameraLegendOpen) {
        openCameraLegend(false);
        return;
      }
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(
        (event.target && event.target.tagName) || ""
      );
      if (
        !typing &&
        event.key.toLowerCase() === "f" &&
        state.page === "camera" &&
        cameraRunning()
      ) {
        event.preventDefault();
        toggleCameraFullscreen();
        return;
      }
      if (
        (event.ctrlKey || event.metaKey) &&
        /^[1-7]$/.test(event.key)
      ) {
        event.preventDefault();
        switchPage(PAGE_ORDER[Number(event.key) - 1]);
      }
    });
  }

  function init() {
    wireEvents();
    initPerfLite();
    initCameraPrefs();
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
    renderCamera();
    Api.rpc("client_ready").catch(function () {});
    setTimeout(hideBootSplash, 2600);
    connect();
  }

  init();
})();
