(() => {
  "use strict";

  const DEFAULTS = { apiBase: "http://127.0.0.1:8000", speed: 1 };
  const $ = (id) => document.getElementById(id);
  const status = $("status");

  function fmt(v) { return `${Number(v)}x`; }

  chrome.storage.sync.get(DEFAULTS).then((s) => {
    $("apiBase").value = s.apiBase;
    $("speed").value = s.speed;
    $("speedOut").textContent = fmt(s.speed);
  });

  $("speed").addEventListener("input", (e) => { $("speedOut").textContent = fmt(e.target.value); });

  $("form").addEventListener("submit", async (e) => {
    e.preventDefault();
    let base = $("apiBase").value.trim().replace(/\/+$/, "");
    try {
      const u = new URL(base);
      if (!/^https?:$/.test(u.protocol)) throw new Error("protocol");
      base = u.origin + (u.pathname === "/" ? "" : u.pathname.replace(/\/+$/, ""));
    } catch {
      status.className = "err";
      status.textContent = "Enter a valid http(s) URL.";
      return;
    }
    const local = ["127.0.0.1", "localhost", "[::1]"].includes(new URL(base).hostname);
    if (!local) {
      if (!base.startsWith("https://")) {
        status.className = "err";
        status.textContent = "Remote servers must use https://. Plain http is only allowed for localhost.";
        return;
      }
      const pattern = new URL(base).origin + "/*";
      let granted = false;
      try {
        granted = await chrome.permissions.contains({ origins: [pattern] })
          || await chrome.permissions.request({ origins: [pattern] });
      } catch { granted = false; }
      if (!granted) {
        status.className = "err";
        status.textContent = "Permission denied for that server, so the setting was not saved.";
        return;
      }
    }
    await chrome.storage.sync.set({ apiBase: base, speed: Number($("speed").value) });
    status.className = "ok";
    status.textContent = local ? "Saved." : "Saved. Access to the remote server was granted.";
  });
})();
