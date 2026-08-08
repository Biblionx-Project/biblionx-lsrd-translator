/**
 * Extension Content Script - Biblionx LSRD Translator
 * Handles on-page text selection, the floating button, and the Overlay Player widget.
 */

const API_TRANSLATE_URL = "http://127.0.0.1:8000/api/v1/translate";

let floatingBtn = null;
let overlayModal = null;
let currentSequence = [];
let currentIndex = 0;
let isPlaying = false;
let playInterval = null;
let playSpeedMs = 1500;

document.addEventListener("mouseup", (event) => {
  // Skip if the click happened inside the floating button or modal
  if (event.target.closest('#biblionx-floating-btn') || event.target.closest('#biblionx-overlay-modal')) {
    return;
  }

  const selection = window.getSelection();
  const selectedText = selection ? selection.toString().trim() : "";
  
  if (selectedText.length > 0) {
    showFloatingButton(event.pageX, event.pageY, selectedText);
  } else {
    removeFloatingButton();
  }
});

function showFloatingButton(x, y, text) {
  removeFloatingButton();

  floatingBtn = document.createElement("button");
  floatingBtn.id = "biblionx-floating-btn";
  floatingBtn.innerHTML = `🖐️ Translate to LSRD`;
  floatingBtn.style.left = `${x + 10}px`;
  floatingBtn.style.top = `${y + 10}px`;

  floatingBtn.addEventListener("mousedown", (e) => {
    e.stopPropagation();
    e.preventDefault();
  });

  floatingBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    e.preventDefault();
    removeFloatingButton();
    translateAndPlay(text);
  });

  document.body.appendChild(floatingBtn);
}

function removeFloatingButton() {
  if (floatingBtn) {
    floatingBtn.remove();
    floatingBtn = null;
  }
}

async function translateAndPlay(text) {
  createModal();
  renderLoadingState();

  try {
    const response = await fetch(API_TRANSLATE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ texto: text })
    });

    const data = await response.json();

    if (data.status === "success" && data.secuencia_senas.length > 0) {
      currentSequence = data.secuencia_senas;
      currentIndex = 0;
      renderPlayerState();
      startAutoPlay();
    } else {
      renderErrorState("No signs available for the selected text.");
    }
  } catch (err) {
    console.error("Biblionx API error:", err);
    renderErrorState("Connection error with the LSRD translation REST API (http://127.0.0.1:8000).");
  }
}

function createModal() {
  if (overlayModal) overlayModal.remove();

  overlayModal = document.createElement("div");
  overlayModal.id = "biblionx-overlay-modal";

  overlayModal.innerHTML = `
    <div class="biblionx-modal-content" role="dialog" aria-label="LSRD Player">
      <div class="biblionx-header">
        <h3>🤟 Biblionx - LSRD Translator</h3>
        <button class="biblionx-close-btn" id="biblionx-close">&times;</button>
      </div>
      <div class="biblionx-body" id="biblionx-body">
      </div>
    </div>
  `;

  document.body.appendChild(overlayModal);
  document.getElementById("biblionx-close").addEventListener("click", closeModal);
}

function closeModal() {
  stopAutoPlay();
  if (overlayModal) {
    overlayModal.remove();
    overlayModal = null;
  }
}

function renderLoadingState() {
  const body = document.getElementById("biblionx-body");
  body.innerHTML = `
    <div style="padding: 40px; text-align: center;">
      <div style="font-size: 32px; margin-bottom: 12px;">⏳</div>
      <p style="color: #003366; font-weight: 600;">Processing LSRD grammar and sign images...</p>
    </div>
  `;
}

function renderErrorState(msg) {
  const body = document.getElementById("biblionx-body");
  body.innerHTML = `
    <div style="padding: 30px; text-align: center;">
      <div style="font-size: 32px; margin-bottom: 12px;">⚠️</div>
      <p style="color: #cc0000; font-weight: 600;">${msg}</p>
      <button class="biblionx-btn" id="biblionx-error-close">Close</button>
    </div>
  `;
  document.getElementById("biblionx-error-close").addEventListener("click", closeModal);
}

function renderPlayerState() {
  const item = currentSequence[currentIndex];
  const body = document.getElementById("biblionx-body");

  const titleLemma = item.es_deletreo ? `Fingerspelled: ${item.letra}` : item.palabra_es;
  const descText = item.descripcion_sena || (item.definicion_es ? `Definition: ${item.definicion_es}` : "No description available.");

  body.innerHTML = `
    <div class="biblionx-image-container">
      <img src="${item.url_imagen}" alt="Sign ${titleLemma}" class="biblionx-sign-img" />
    </div>

    <div class="biblionx-sign-info">
      <h2 class="biblionx-lemma">${titleLemma}</h2>
      <div class="biblionx-category">${item.categoria || 'General sign'}</div>
      <div class="biblionx-description">${descText}</div>
    </div>

    <div class="biblionx-controls">
      <button class="biblionx-btn" id="biblionx-prev" ${currentIndex === 0 ? 'disabled' : ''}>⏮️ Previous</button>
      <button class="biblionx-btn" id="biblionx-play">${isPlaying ? '⏸️ Pause' : '▶️ Play'}</button>
      <button class="biblionx-btn" id="biblionx-next" ${currentIndex === currentSequence.length - 1 ? 'disabled' : ''}>Next ⏭️</button>

      <select class="biblionx-speed-select" id="biblionx-speed">
        <option value="2000">0.75x</option>
        <option value="1500" selected>1.0x</option>
        <option value="1000">1.5x</option>
        <option value="750">2.0x</option>
      </select>
    </div>

    <div class="biblionx-progress">
      Sign ${currentIndex + 1} of ${currentSequence.length}
    </div>
  `;

  document.getElementById("biblionx-prev").addEventListener("click", prevSign);
  document.getElementById("biblionx-play").addEventListener("click", togglePlay);
  document.getElementById("biblionx-next").addEventListener("click", nextSign);
  
  const speedSelect = document.getElementById("biblionx-speed");
  speedSelect.value = playSpeedMs.toString();
  speedSelect.addEventListener("change", (e) => {
    playSpeedMs = parseInt(e.target.value);
    if (isPlaying) {
      startAutoPlay();
    }
  });
}

function nextSign() {
  if (currentIndex < currentSequence.length - 1) {
    currentIndex++;
    renderPlayerState();
  } else {
    stopAutoPlay();
  }
}

function prevSign() {
  if (currentIndex > 0) {
    currentIndex--;
    renderPlayerState();
  }
}

function togglePlay() {
  if (isPlaying) {
    stopAutoPlay();
  } else {
    startAutoPlay();
  }
}

function startAutoPlay() {
  stopAutoPlay();
  isPlaying = true;
  playInterval = setInterval(() => {
    if (currentIndex < currentSequence.length - 1) {
      currentIndex++;
      renderPlayerState();
    } else {
      stopAutoPlay();
      renderPlayerState();
    }
  }, playSpeedMs);
  renderPlayerState();
}

function stopAutoPlay() {
  isPlaying = false;
  if (playInterval) {
    clearInterval(playInterval);
    playInterval = null;
  }
}
