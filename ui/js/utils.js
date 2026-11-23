(function () {
  function byId(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatClock(date) {
    return new Date(date || Date.now()).toLocaleTimeString("ru-RU", {
      hour12: false,
    });
  }

  function formatDuration(seconds) {
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(value / 60);
    const rest = value % 60;
    return minutes + ":" + String(rest).padStart(2, "0");
  }

  function formatUptime(seconds) {
    const value = Math.max(0, Math.round(Number(seconds) || 0));
    const hours = Math.floor(value / 3600);
    const minutes = Math.floor((value % 3600) / 60);
    if (hours > 0) return hours + " ч " + minutes + " мин";
    return minutes + " мин";
  }

  function truncate(value, limit) {
    const text = String(value == null ? "" : value);
    if (text.length <= limit) return text;
    return text.slice(0, limit) + "…";
  }

  function renderMarkdown(value) {
    let html = escapeHtml(value);
    const codeBlocks = [];
    html = html.replace(
      /```([\w-]*)\n([\s\S]*?)```/g,
      function (_match, _lang, code) {
        const index = codeBlocks.push(
          "<pre><code>" + code.replace(/\s+$/, "") + "</code></pre>"
        ) - 1;
        return "\n@@CODE" + index + "@@\n";
      }
    );
    html = html.replace(/`([^`\n]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<em>$2</em>");
    html = html.replace(/^###\s+(.+)$/gm, "<h3>$1</h3>");
    html = html.replace(/^##\s+(.+)$/gm, "<h2>$1</h2>");
    html = html.replace(/^#\s+(.+)$/gm, "<h1>$1</h1>");
    html = html.replace(/^\s*[-*]\s+(.+)$/gm, "<li>$1</li>");
    html = html.replace(
      /(<li>[\s\S]*?<\/li>)/g,
      function (match) {
        return "<ul>" + match + "</ul>";
      }
    );
    html = html.replace(
      /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noreferrer">$1</a>'
    );
    html = html.replace(/\n/g, "<br>");
    html = html.replace(/@@CODE(\d+)@@/g, function (_match, index) {
      return codeBlocks[Number(index)] || "";
    });
    return html;
  }

  function toast(message, type) {
    const host = byId("toasts");
    if (!host) return;
    const item = document.createElement("div");
    item.className = "toast " + (type || "");
    item.textContent = String(message || "");
    host.appendChild(item);
    setTimeout(function () {
      item.style.opacity = "0";
      item.style.transform = "translateY(5px)";
      setTimeout(function () {
        item.remove();
      }, 180);
    }, 3200);
  }

  function debounce(fn, wait) {
    let timer = null;
    return function () {
      const args = arguments;
      clearTimeout(timer);
      timer = setTimeout(function () {
        fn.apply(null, args);
      }, wait);
    };
  }

  function normalizeStatus(status) {
    const value = String(status || "starting").toLowerCase();
    return [
      "starting",
      "ready",
      "listening",
      "processing",
      "thinking",
      "speaking",
      "error",
      "stopped",
      "mic_off",
    ].includes(value)
      ? value
      : "ready";
  }

  window.JarvisUtils = {
    byId,
    escapeHtml,
    formatClock,
    formatDuration,
    formatUptime,
    truncate,
    renderMarkdown,
    toast,
    debounce,
    normalizeStatus,
  };
})();
