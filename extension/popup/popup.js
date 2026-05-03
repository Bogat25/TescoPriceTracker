// ============================================
// POPUP LOGIC — Tesco Price Tracker
// ============================================

import ENV from "../env/config.js";

// Standardize browser namespace (Chrome vs Firefox)
if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

// ── DOM Elements ─────────────────────────────

const toggleSwitch = document.getElementById("toggle-switch");
const openWebsite  = document.getElementById("open-website-btn");

// Auth elements
const loggedOutEl  = document.getElementById("account-logged-out");
const loggedInEl   = document.getElementById("account-logged-in");
const btnLogin     = document.getElementById("btn-login");
const btnLogout    = document.getElementById("btn-logout");
const accountName  = document.getElementById("account-name");
const accountEmail = document.getElementById("account-email");
const accountAvatar = document.getElementById("account-avatar");

// Alerts elements
const alertsSection = document.getElementById("alerts-section");
const alertsBadge   = document.getElementById("alerts-badge");
const alertsList    = document.getElementById("popup-alerts-list");

// ── Helpers ──────────────────────────────────

function updateToggleUI(isEnabled) {
  toggleSwitch.checked = isEnabled;
}

function showLoggedIn(user) {
  loggedOutEl.style.display = "none";
  loggedInEl.style.display = "flex";
  alertsSection.style.display = "block";

  const name = user?.name || "User";
  const email = user?.email || "";
  accountName.textContent = name;
  accountEmail.textContent = email;
  accountAvatar.textContent = name.charAt(0).toUpperCase();
}

function showLoggedOut() {
  loggedOutEl.style.display = "block";
  loggedInEl.style.display = "none";
  alertsSection.style.display = "none";
}

async function loadAlerts() {
  alertsList.innerHTML = '<div class="alerts-loading">Loading...</div>';
  const result = await browser.runtime.sendMessage({ type: "ALERTS_LIST" });

  if (result.error) {
    alertsList.innerHTML = '<div class="alerts-empty">Could not load alerts</div>';
    alertsBadge.textContent = "0";
    return;
  }

  const alerts = result.alerts || [];
  alertsBadge.textContent = alerts.length.toString();

  if (alerts.length === 0) {
    alertsList.innerHTML = '<div class="alerts-empty">No alerts configured yet</div>';
    return;
  }

  alertsList.innerHTML = "";
  // Show max 5 alerts in popup
  const shown = alerts.slice(0, 5);
  for (const alert of shown) {
    const row = document.createElement("div");
    row.className = "alert-row";

    let desc = "";
    if (alert.alertType === "TARGET_PRICE") {
      desc = `#${alert.productId} — ≤ ${alert.targetPrice?.toLocaleString()} Ft`;
    } else {
      desc = `#${alert.productId} — ≥ ${alert.dropPercentage}% drop`;
    }

    const dot = document.createElement("span");
    dot.className = `alert-dot ${alert.enabled ? "alert-dot--on" : "alert-dot--off"}`;

    const text = document.createElement("span");
    text.className = "alert-text";
    text.textContent = desc;

    row.appendChild(dot);
    row.appendChild(text);
    alertsList.appendChild(row);
  }

  if (alerts.length > 5) {
    const more = document.createElement("div");
    more.className = "alerts-more";
    more.textContent = `+${alerts.length - 5} more — open website to manage`;
    alertsList.appendChild(more);
  }
}

// ── Init ─────────────────────────────────────

async function init() {
  // Load toggle state
  const { extensionEnabled } = await browser.storage.local.get("extensionEnabled");
  updateToggleUI(extensionEnabled ?? true);

  // Check auth status
  const authStatus = await browser.runtime.sendMessage({ type: "AUTH_STATUS" });
  if (authStatus?.loggedIn && authStatus?.user) {
    showLoggedIn(authStatus.user);
    loadAlerts();
  } else {
    showLoggedOut();
  }
}

init();

// ── Events ───────────────────────────────────

toggleSwitch.addEventListener("change", async () => {
  const isEnabled = toggleSwitch.checked;
  await browser.storage.local.set({ extensionEnabled: isEnabled });
  updateToggleUI(isEnabled);
  browser.runtime.sendMessage({ type: "TOGGLE_EXTENSION", enabled: isEnabled });
});

btnLogin.addEventListener("click", async () => {
  btnLogin.disabled = true;
  btnLogin.textContent = "Signing in...";

  const result = await browser.runtime.sendMessage({ type: "AUTH_LOGIN" });
  if (result.success) {
    showLoggedIn(result.user);
    loadAlerts();
  } else {
    btnLogin.disabled = false;
    btnLogin.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>
      </svg>
      Sign In
    `;
  }
});

btnLogout.addEventListener("click", async () => {
  await browser.runtime.sendMessage({ type: "AUTH_LOGOUT" });
  showLoggedOut();
});

openWebsite.addEventListener("click", () => {
  browser.tabs.create({ url: ENV.WEBSITE_URL || "https://price-tracker.gavaller.com/" });
  window.close();
});
