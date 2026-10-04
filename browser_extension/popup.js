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
  await chrome.storage.sync.set({ apiBase: base, speed: Number($("speed").value) });
  status.className = "ok";
  status.textContent = "Saved.";
});
