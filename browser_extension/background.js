// Biblionx service worker: context menu + API proxy (avoids page CORS/mixed-content limits).
const DEFAULTS = { apiBase: "http://127.0.0.1:8000", speed: 1 };
const MENU_ID = "biblionx-translate";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: MENU_ID,
      title: "Translate to LSRD",
      contexts: ["selection"],
    });
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== MENU_ID || !tab || tab.id == null) return;
  const opts = info.frameId != null ? { frameId: info.frameId } : {};
  chrome.tabs
    .sendMessage(tab.id, { type: "biblionx:translate", text: info.selectionText || "" }, opts)
    .catch(() => {});
});

async function getSettings() {
  const s = await chrome.storage.sync.get(DEFAULTS);
  return { apiBase: String(s.apiBase || DEFAULTS.apiBase).replace(/\/+$/, ""), speed: Number(s.speed) || 1 };
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "biblionx:api") return false;
  (async () => {
    const { apiBase } = await getSettings();
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 20000);
      const res = await fetch(`${apiBase}/api/v1/translate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ texto: msg.text }),
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (!res.ok) {
        const retry = Number(res.headers.get("Retry-After")) || 0;
        sendResponse({ ok: false, status: res.status, retryAfter: retry, error: `HTTP ${res.status}`, apiBase });
        return;
      }
      sendResponse({ ok: true, data: await res.json(), apiBase });
    } catch (err) {
      sendResponse({ ok: false, error: String((err && err.message) || err), apiBase });
    }
  })();
  return true; // async response
});

// Sign images are fetched here and handed to the page as data: URLs. A content
// script <img> pointing at http://127.0.0.1 is blocked as mixed content on
// HTTPS pages, but the service worker is not. Only image paths on the configured
// API origin are proxied.
function toBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let bin = "";
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || msg.type !== "biblionx:image") return false;
  (async () => {
    try {
      const { apiBase } = await getSettings();
      const target = new URL(String(msg.url || ""));
      if (target.origin !== new URL(apiBase).origin || !target.pathname.startsWith("/extracted_images/")) {
        sendResponse({ ok: false, error: "URL not allowed" });
        return;
      }
      const res = await fetch(target.href);
      const type = res.headers.get("Content-Type") || "";
      if (!res.ok || !type.startsWith("image/")) {
        sendResponse({ ok: false, error: `HTTP ${res.status}` });
        return;
      }
      sendResponse({ ok: true, dataUrl: `data:${type};base64,${toBase64(await res.arrayBuffer())}` });
    } catch (err) {
      sendResponse({ ok: false, error: String((err && err.message) || err) });
    }
  })();
  return true; // async response
});
