// ============================================
// BACKGROUND SCRIPT — Tesco Price Tracker
// ============================================
// Central message broker: handles API calls,
// authentication, and alert management.
// ============================================

import ENV from "../env/config.js";
import { login, loginSwitchAccount, logout, getToken, getUser, isLoggedIn } from "./auth.js";
import {
  listAlerts,
  listAlertsForProduct,
  createAlert,
  deleteAlert,
  toggleAlert,
} from "./alerts-api.js";

// Standardize browser namespace (Chrome vs Firefox)
if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

// ── Message Listener ─────────────────────────

browser.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handler = MESSAGE_HANDLERS[message.type];
  if (handler) {
    handler(message, sender)
      .then((result) => sendResponse(result))
      .catch((err) => sendResponse({ error: err.message }));
    return true; // Keep channel open for async
  }
  return false;
});

// ── Message Handler Map ──────────────────────

const MESSAGE_HANDLERS = {
  // Extension toggle (existing)
  TOGGLE_EXTENSION: async (msg) => {
    await handleToggle(msg.enabled);
    return { success: true };
  },

  // Price history fetch (existing)
  FETCH_HISTORY: async (msg) => {
    return await fetchHistory(msg.tpnc);
  },

  // ── Auth ────────────────────────────────────
  AUTH_LOGIN: async () => {
    return await login();
  },

  AUTH_SWITCH_ACCOUNT: async () => {
    return await loginSwitchAccount();
  },

  AUTH_LOGOUT: async () => {
    const result = await logout();
    // Broadcast to all content scripts so they can refresh the alerts panel
    const tabs = await browser.tabs.query({});
    for (const tab of tabs) {
      browser.tabs.sendMessage(tab.id, { type: "AUTH_STATE_CHANGED", loggedIn: false }).catch(() => {});
    }
    return result;
  },

  AUTH_STATUS: async () => {
    const loggedIn = await isLoggedIn();
    const user = loggedIn ? await getUser() : null;
    return { loggedIn, user };
  },

  AUTH_GET_TOKEN: async () => {
    const token = await getToken();
    return { token };
  },

  // ── Alerts ──────────────────────────────────
  ALERTS_LIST: async () => {
    return await listAlerts();
  },

  ALERTS_LIST_FOR_PRODUCT: async (msg) => {
    return await listAlertsForProduct(msg.productId);
  },

  ALERTS_CREATE: async (msg) => {
    return await createAlert(msg.alert);
  },

  ALERTS_DELETE: async (msg) => {
    return await deleteAlert(msg.alertId);
  },

  ALERTS_TOGGLE: async (msg) => {
    return await toggleAlert(msg.alertId, msg.enabled);
  },
};

// ── Existing functionality ───────────────────

async function handleToggle(enabled) {
  const tabs = await browser.tabs.query({});
  for (const tab of tabs) {
    if (!tab.url || tab.url.startsWith("about:") || tab.url.startsWith("moz-extension:")) {
      continue;
    }
    try {
      await browser.tabs.sendMessage(tab.id, { type: "SET_ENABLED", enabled });
    } catch {
      // Content script may not be loaded on this tab yet
    }
  }
}

async function fetchHistory(tpnc) {
  try {
    const baseUrl = ENV.API_BASE_URL.replace(/\/+$/, "");
    const response = await fetch(`${baseUrl}/products/${tpnc}`);
    if (!response.ok) {
      throw new Error(`Server returned ${response.status}`);
    }
    const data = await response.json();
    return {
      name: data.name,
      history: data.price_history || { normal: [], discount: [], clubcard: [] },
    };
  } catch (error) {
    console.error("[TescoPriceTracker] Fetch error:", error);
    throw error;
  }
}

// ── Installation / Update ────────────────────

browser.runtime.onInstalled.addListener(async (details) => {
  if (details.reason === "install") {
    await browser.storage.local.set({ extensionEnabled: true });
    console.log("[TescoPriceTracker] Installed — extension enabled by default.");
  }
});
