(function () {
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const pending = new Map();
  let sequence = 0;
  let attached = false;
  let queue = Promise.resolve();

  // Раньше токен хранился в localStorage; теперь вход только через
  // HttpOnly-cookie, а URL не содержит секретов (не попадает в историю/прокси).
  try {
    localStorage.removeItem("jarvis_remote_token");
  } catch (error) {
    /* storage unavailable */
  }

  function packageReady() {
    return Boolean(
      window.webview2 &&
        window.webview2.api &&
        typeof window.webview2.api.rpc === "function" &&
        window.webview2.transport &&
        window.webview2.transport.wmemo
    );
  }

  function remoteMode() {
    return /^https?:$/.test(window.location.protocol);
  }

  function remoteRpc(id, method, payload) {
    // Авторизация — HttpOnly-cookie от POST /login. Токен в URL не нужен.
    return fetch("/rpc", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        type: "jarvis_request",
        id: id,
        method: method,
        payload: payload || {},
      }),
    })
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        deliver(data);
      })
      .catch(function () {
        /* network error — request will time out via pending timer */
      });
  }

  function pywebviewReady() {
    return Boolean(
      window.pywebview &&
        window.pywebview.api &&
        typeof window.pywebview.api.rpc === "function"
    );
  }

  function available() {
    return Boolean(remoteMode() || packageReady() || pywebviewReady());
  }

  function deliver(data) {
    if (!data || data.type !== "jarvis_response") return;
    const item = pending.get(data.id);
    if (!item) return;
    pending.delete(data.id);
    clearTimeout(item.timer);
    if (data.ok) {
      item.resolve(data.data);
    } else {
      item.reject(new Error(data.error || "Ошибка JARVIS"));
    }
  }

  function onMessage(event) {
    let data;
    try {
      data = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    deliver(data);
  }

  window.__jarvisDeliver = function (text) {
    try {
      deliver(JSON.parse(text));
    } catch (error) {
      /* malformed payload */
    }
  };

  function attach() {
    if (attached || !(window.chrome && window.chrome.webview)) {
      return attached;
    }
    window.chrome.webview.addEventListener("message", onMessage);
    attached = true;
    return true;
  }

  async function waitForBridge(timeout = 8000) {
    const started = Date.now();
    attach();
    while (!available()) {
      if (Date.now() - started > timeout) {
        throw new Error("WebView2 bridge не готов");
      }
      await sleep(40);
      attach();
    }
    return true;
  }

  function sendRequest(id, method, payload) {
    const message = JSON.stringify({
      type: "jarvis_request",
      id: id,
      method: method,
      payload: payload || {},
    });
    if (remoteMode()) {
      return remoteRpc(id, method, payload);
    }
    if (pywebviewReady()) {
      return window.pywebview.api
        .rpc(message)
        .then(function (text) {
          try {
            deliver(JSON.parse(text));
          } catch (error) {
            /* malformed payload */
          }
        })
        .catch(function () {});
    }
    if (window.webview2 && window.webview2.api && window.webview2.api.rpc) {
      return window.webview2.api
        .rpc(message)
        .then(function (text) {
          try {
            deliver(JSON.parse(text));
          } catch (error) {
            /* fall back to the message listener */
          }
        })
        .catch(function () {});
    }
    throw new Error("WebView2 bridge не готов");
  }

  function rpcOnce(method, payload) {
    return waitForBridge().then(
      () =>
        new Promise((resolve, reject) => {
          const id =
            "req-" +
            Date.now().toString(36) +
            "-" +
            (++sequence).toString(36);
          const timer = setTimeout(() => {
            pending.delete(id);
            reject(new Error("Таймаут ответа JARVIS"));
          }, 20000);
          pending.set(id, { resolve, reject, timer });
          try {
            sendRequest(id, method, payload);
          } catch (error) {
            pending.delete(id);
            clearTimeout(timer);
            reject(error);
          }
        })
    );
  }

  function rpc(method, payload) {
    const run = queue.then(() => rpcOnce(method, payload));
    queue = run.catch(() => {});
    return run;
  }

  async function call(name, ...args) {
    return rpc("window_action", {
      action: name,
      args: args,
    });
  }

  window.__JARVIS_API_MODE__ = pywebviewReady()
    ? "pywebview"
    : "package-rpc-ready";
  window.JarvisApi = { waitForBridge, rpc, call };
})();
