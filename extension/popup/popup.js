// ============================================
// POPUP LOGIC — Tesco Price Tracker
// ============================================

// Standardize browser namespace (Chrome vs Firefox)
if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

const toggleSwitch = document.getElementById("toggle-switch");
const statusDot    = document.getElementById("status-dot");
const statusText   = document.getElementById("status-text");
const openWebsite  = document.getElementById("open-website-btn");

// ── Helpers ──────────────────────────────────

/** Update the UI to reflect the current enabled state. */
function updateUI(isEnabled) {
  toggleSwitch.checked = isEnabled;
  statusDot.classList.toggle("enabled", isEnabled);
  statusDot.classList.toggle("disabled", !isEnabled);
  statusText.textContent = isEnabled ? "Enabled" : "Disabled";
}

// ── Init ─────────────────────────────────────

browser.storage.local.get("extensionEnabled").then((result) => {
  const isEnabled = result.extensionEnabled ?? true;
  updateUI(isEnabled);
});

// ── Events ───────────────────────────────────

toggleSwitch.addEventListener("change", async () => {
  const isEnabled = toggleSwitch.checked;
  await browser.storage.local.set({ extensionEnabled: isEnabled });
  updateUI(isEnabled);
  browser.runtime.sendMessage({ type: "TOGGLE_EXTENSION", enabled: isEnabled });
});

// Open Price Tracker website in a new tab
openWebsite.addEventListener("click", () => {
  browser.tabs.create({ url: "https://price-tracker.gavaller.com/" });
  window.close();
});
