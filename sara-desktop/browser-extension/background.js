// Sara Desktop Context — browser extension background service worker
//
// Maintains a WebSocket connection to the local Sara sidecar bridge
// (ws://127.0.0.1:9876) and pushes a {type: "browser_context", url,
// title, domain} message whenever the active tab changes or finishes
// loading. The sidecar enriches focus_span events with that data so
// ACS observations carry "30m on docs.anthropic.com" instead of just
// "30m in chrome.exe".
//
// We don't ship URL contents, only metadata about which page is open.

const BRIDGE_URL = "ws://127.0.0.1:9876";
const KEEPALIVE_MS = 25000;
const RECONNECT_MAX_MS = 30000;

let ws = null;
let reconnectDelay = 1000;
let keepaliveTimer = null;
let connectingPromise = null;

function log(...args) {
  // chrome://extensions/ devtools surfaces these. Quiet otherwise.
  console.log("[Sara]", ...args);
}

function safeDomain(urlStr) {
  try {
    return new URL(urlStr).hostname || "";
  } catch (_e) {
    return "";
  }
}

function shouldSkip(urlStr) {
  if (!urlStr) return true;
  // chrome://, edge://, about:, file://, chrome-extension:// etc. — internal
  // browser pages that aren't interesting to Sara and may include sensitive
  // local paths.
  return !/^https?:\/\//i.test(urlStr);
}

function send(payload) {
  if (!ws || ws.readyState !== WebSocket.OPEN) return false;
  try {
    ws.send(JSON.stringify(payload));
    return true;
  } catch (e) {
    log("send failed", e);
    return false;
  }
}

function connect() {
  if (connectingPromise) return connectingPromise;
  connectingPromise = new Promise((resolve) => {
    try {
      ws = new WebSocket(BRIDGE_URL);
    } catch (e) {
      log("ws construct failed", e);
      scheduleReconnect();
      connectingPromise = null;
      resolve();
      return;
    }

    ws.addEventListener("open", () => {
      log("connected to sidecar");
      reconnectDelay = 1000;
      connectingPromise = null;
      startKeepalive();
      // On connect, snapshot whatever is currently active so the sidecar
      // has fresh state without waiting for a tab change.
      sendCurrentActiveTab();
      resolve();
    });

    ws.addEventListener("close", () => {
      stopKeepalive();
      ws = null;
      connectingPromise = null;
      scheduleReconnect();
      resolve();
    });

    ws.addEventListener("error", (e) => {
      log("ws error", e);
      // close handler will fire next; don't double-schedule
    });

    // The sidecar bridge sends "pong" to our pings and may emit
    // unsolicited messages. We don't act on them; just keep the
    // connection warm.
    ws.addEventListener("message", () => {});
  });
  return connectingPromise;
}

function scheduleReconnect() {
  setTimeout(() => {
    connect();
  }, reconnectDelay);
  reconnectDelay = Math.min(reconnectDelay * 2, RECONNECT_MAX_MS);
}

function startKeepalive() {
  stopKeepalive();
  // Two purposes: prevents the MV3 service worker from being suspended,
  // and lets the sidecar know we're still here.
  keepaliveTimer = setInterval(() => {
    send({ type: "ping" });
  }, KEEPALIVE_MS);
}

function stopKeepalive() {
  if (keepaliveTimer) {
    clearInterval(keepaliveTimer);
    keepaliveTimer = null;
  }
}

function pushTab(tab) {
  if (!tab) return;
  if (shouldSkip(tab.url)) return;
  send({
    type: "browser_context",
    url: tab.url,
    title: tab.title || "",
    domain: safeDomain(tab.url),
  });
}

async function sendCurrentActiveTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (tabs && tabs.length) pushTab(tabs[0]);
  } catch (e) {
    log("sendCurrentActiveTab failed", e);
  }
}

// ── Tab events ─────────────────────────────────────────────────────────────

chrome.tabs.onActivated.addListener(async (info) => {
  try {
    const tab = await chrome.tabs.get(info.tabId);
    pushTab(tab);
  } catch (_e) {
    /* tab gone */
  }
});

chrome.tabs.onUpdated.addListener((_tabId, changeInfo, tab) => {
  // Only fire on completed loads — otherwise typing in the omnibox fires
  // dozens of partial-URL events.
  if (changeInfo.status === "complete" && tab.active) {
    pushTab(tab);
  }
});

chrome.windows.onFocusChanged.addListener(async (windowId) => {
  if (windowId === chrome.windows.WINDOW_ID_NONE) return;
  await sendCurrentActiveTab();
});

// Kick things off
connect();
