// ============================================
// POPUP LOGIC — Tesco Price Tracker
// ============================================

import ENV from "../env/config.js";

if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

// ── Translations ──────────────────────────────

const STRINGS = {
  en: {
    loginPrompt:      "Sign in to sync alerts between extension & website",
    signIn:           "Sign In",
    signOut:          "Sign Out",
    switchAccount:    "Switch",
    signingIn:        "Signing in…",
    enableExtension:  "Enable Extension",
    myAlerts:         "My Alerts",
    noAlerts:         "No alerts configured yet",
    couldNotLoad:     "Could not load alerts",
    loading:          "Loading…",
    openWebsite:      "Open Price Tracker Website",
    footer:           "Price history charts & alerts sync with your account.",
    moreAlerts:       (n) => `+${n} more — open website to manage`,
  },
  hu: {
    loginPrompt:      "Jelentkezz be a riasztások szinkronizálásához",
    signIn:           "Bejelentkezés",
    signOut:          "Kijelentkezés",
    switchAccount:    "Váltás",
    signingIn:        "Bejelentkezés…",
    enableExtension:  "Bővítmény engedélyezése",
    myAlerts:         "Riasztásaim",
    noAlerts:         "Nincs beállított riasztás",
    couldNotLoad:     "Nem sikerült betölteni a riasztásokat",
    loading:          "Betöltés…",
    openWebsite:      "Ár Figyelő Megnyitása",
    footer:           "Árelőzmény grafikonok és riasztások szinkronizálva fiókjával.",
    moreAlerts:       (n) => `+${n} további — nyisd meg a webhelyet`,
  },
};

// ── State ────────────────────────────────────

let g_lang  = "hu";
let g_theme = "dark";

// ── DOM Elements ─────────────────────────────

const body          = document.body;
const toggleSwitch  = document.getElementById("toggle-switch");
const openWebsite   = document.getElementById("open-website-btn");

const loggedOutEl   = document.getElementById("account-logged-out");
const loggedInEl    = document.getElementById("account-logged-in");
const btnLogin      = document.getElementById("btn-login");
const btnLogout     = document.getElementById("btn-logout");
const btnSwitch     = document.getElementById("btn-switch-account");
const accountName   = document.getElementById("account-name");
const accountEmail  = document.getElementById("account-email");
const accountAvatar = document.getElementById("account-avatar");

const alertsSection = document.getElementById("alerts-section");
const alertsBadge   = document.getElementById("alerts-badge");
const alertsList    = document.getElementById("popup-alerts-list");

const themeToggle   = document.getElementById("theme-toggle");
const langEnBtn     = document.getElementById("lang-en");
const langHuBtn     = document.getElementById("lang-hu");

// ── i18n ─────────────────────────────────────

function t(key, ...args) {
  const s = STRINGS[g_lang] || STRINGS.en;
  const val = s[key];
  return typeof val === "function" ? val(...args) : (val ?? key);
}

function applyTranslations() {
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.dataset.i18n;
    const text = t(key);
    // For buttons that contain an SVG, update only text nodes
    const svgChild = el.querySelector("svg");
    if (svgChild) {
      const textSpan = el.querySelector("span[data-i18n]") || el.querySelector("span");
      if (textSpan) { textSpan.textContent = text; return; }
      // Replace text nodes only
      Array.from(el.childNodes)
        .filter((n) => n.nodeType === Node.TEXT_NODE)
        .forEach((n) => (n.textContent = " " + text));
    } else {
      el.textContent = text;
    }
  });
}

function applyLangButtons() {
  langEnBtn.classList.toggle("active", g_lang === "en");
  langHuBtn.classList.toggle("active", g_lang === "hu");
}

// ── Theme ─────────────────────────────────────

const MOON_SVG = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
const SUN_SVG  = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

function applyTheme(theme) {
  g_theme = theme;
  body.setAttribute("data-theme", theme);
  themeToggle.innerHTML = theme === "dark" ? MOON_SVG : SUN_SVG;
  themeToggle.title     = theme === "dark" ? "Switch to Light Mode" : "Switch to Dark Mode";
}

// ── UI Helpers ────────────────────────────────

function updateToggleUI(isEnabled) {
  toggleSwitch.checked = isEnabled;
}

function showLoggedIn(user) {
  loggedOutEl.style.display = "none";
  loggedInEl.style.display  = "flex";
  alertsSection.style.display = "block";

  const name  = user?.name  || "User";
  const email = user?.email || "";
  accountName.textContent   = name;
  accountEmail.textContent  = email;
  accountAvatar.textContent = name.charAt(0).toUpperCase();
}

function showLoggedOut() {
  loggedOutEl.style.display   = "block";
  loggedInEl.style.display    = "none";
  alertsSection.style.display = "none";
  applyTranslations(); // Re-apply so Sign In button text is correct
}

async function loadAlerts() {
  alertsList.innerHTML = `<div class="alerts-loading">${t("loading")}</div>`;
  const result = await browser.runtime.sendMessage({ type: "ALERTS_LIST" });

  if (result.error) {
    alertsList.innerHTML = `<div class="alerts-empty">${t("couldNotLoad")}</div>`;
    alertsBadge.textContent = "0";
    return;
  }

  const alerts = result.alerts || [];
  alertsBadge.textContent = alerts.length.toString();

  if (alerts.length === 0) {
    alertsList.innerHTML = `<div class="alerts-empty">${t("noAlerts")}</div>`;
    return;
  }

  // Load cached product names (written by content.js when user visits product pages)
  const stored = await browser.storage.local.get("productNames");
  const productNames = stored.productNames || {};

  alertsList.innerHTML = "";
  const shown = alerts.slice(0, 5);
  for (const alert of shown) {
    const row = document.createElement("div");
    row.className = "alert-row";

    // Prefer cached product name; fall back to shortened ID
    const rawName = productNames[alert.productId];
    const label = rawName
      ? (rawName.length > 22 ? rawName.slice(0, 22).trimEnd() + "…" : rawName)
      : `#${alert.productId}`;

    let desc = "";
    if (alert.alertType === "TARGET_PRICE") {
      desc = `${label} — ≤ ${alert.targetPrice?.toLocaleString()} Ft`;
    } else {
      desc = `${label} — ≥ ${alert.dropPercentage}% drop`;
    }

    const dot = document.createElement("span");
    dot.className = `alert-dot ${alert.enabled ? "alert-dot--on" : "alert-dot--off"}`;

    const text = document.createElement("span");
    text.className   = "alert-text";
    text.textContent = desc;

    row.appendChild(dot);
    row.appendChild(text);
    alertsList.appendChild(row);
  }

  if (alerts.length > 5) {
    const more = document.createElement("div");
    more.className   = "alerts-more";
    more.textContent = t("moreAlerts", alerts.length - 5);
    alertsList.appendChild(more);
  }
}

// ── Login helper (shared by Sign In + Switch Account) ─────────────

async function startLogin() {
  btnLogin.disabled   = true;
  const origHtml      = btnLogin.innerHTML;
  btnLogin.querySelector("span[data-i18n]").textContent = t("signingIn");

  const result = await browser.runtime.sendMessage({ type: "AUTH_LOGIN" });
  if (result.success) {
    showLoggedIn(result.user);
    loadAlerts();
  } else {
    btnLogin.disabled = false;
    btnLogin.querySelector("span[data-i18n]").textContent = t("signIn");
  }
}

// ── Init ─────────────────────────────────────

async function init() {
  // Load preferences
  const stored = await browser.storage.local.get(["extensionEnabled", "popupTheme", "popupLang"]);
  g_theme = stored.popupTheme || "dark";
  g_lang  = stored.popupLang  || "hu";

  applyTheme(g_theme);
  applyLangButtons();
  applyTranslations();
  updateToggleUI(stored.extensionEnabled ?? true);

  // Auth state
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

// Extension on/off toggle
toggleSwitch.addEventListener("change", async () => {
  const isEnabled = toggleSwitch.checked;
  await browser.storage.local.set({ extensionEnabled: isEnabled });
  browser.runtime.sendMessage({ type: "TOGGLE_EXTENSION", enabled: isEnabled });
});

// Sign In
btnLogin.addEventListener("click", startLogin);

// Sign Out
btnLogout.addEventListener("click", async () => {
  await browser.runtime.sendMessage({ type: "AUTH_LOGOUT" });
  showLoggedOut();
});

// Switch Account — uses /switch-account gateway endpoint which signs out
// server-side (kills the Keycloak session) then opens a fresh login prompt,
// so the user cannot silently re-use the existing Keycloak session.
btnSwitch.addEventListener("click", async () => {
  btnSwitch.disabled = true;
  // Hide logged-in state immediately while the auth tab is open
  loggedInEl.style.display    = "none";
  loggedOutEl.style.display   = "block";
  alertsSection.style.display = "none";

  const result = await browser.runtime.sendMessage({ type: "AUTH_SWITCH_ACCOUNT" });
  btnSwitch.disabled = false;
  if (result?.success) {
    showLoggedIn(result.user);
    loadAlerts();
  } else {
    // Switch failed or user closed the tab — stay on logged-out view
    showLoggedOut();
  }
});

// Open website
openWebsite.addEventListener("click", () => {
  browser.tabs.create({ url: ENV.WEBSITE_URL || "https://price-tracker.gavaller.com/" });
  window.close();
});

// Theme toggle
themeToggle.addEventListener("click", async () => {
  const newTheme = g_theme === "dark" ? "light" : "dark";
  applyTheme(newTheme);
  await browser.storage.local.set({ popupTheme: newTheme });
});

// Language toggle
langEnBtn.addEventListener("click", async () => {
  g_lang = "en";
  applyLangButtons();
  applyTranslations();
  await browser.storage.local.set({ popupLang: "en" });
});
langHuBtn.addEventListener("click", async () => {
  g_lang = "hu";
  applyLangButtons();
  applyTranslations();
  await browser.storage.local.set({ popupLang: "hu" });
});
