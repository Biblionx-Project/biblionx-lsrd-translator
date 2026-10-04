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
  chrome.tabs
    .sendMessage(tab.id, { type: "biblionx:translate", text: info.selectionText || "" })
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
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      sendResponse({ ok: true, data: await res.json(), apiBase });
    } catch (err) {
      sendResponse({ ok: false, error: String((err && err.message) || err), apiBase });
    }
  })();
  return true; // async response
});
