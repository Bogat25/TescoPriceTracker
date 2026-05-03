// ============================================
// ALERTS API MODULE — Tesco Price Tracker
// ============================================
// Communicates with the alert-service backend.
// All requests include Bearer token from auth.
// ============================================

import ENV from "../env/config.js";
import { getToken } from "./auth.js";

if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

// ALERTS_API_URL should be the public-facing prefix, e.g.
// "https://price-tracker.gavaller.com/api/alerts"
// nginx then rewrites /api/alerts/* → /api/v1/alerts/*
const ALERTS_BASE = ENV.ALERTS_API_URL.replace(/\/+$/, "");

/**
 * Make an authenticated request to the alerts API.
 */
async function authFetch(path, options = {}) {
  const token = await getToken();
  if (!token) {
    return { error: "not_authenticated", message: "Please log in first" };
  }

  const url = `${ALERTS_BASE}${path}`;
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };

  try {
    const resp = await fetch(url, { ...options, headers });

    if (resp.status === 401) {
      return { error: "unauthorized", message: "Session expired. Please log in again." };
    }

    if (resp.status === 204) {
      return { success: true };
    }

    if (!resp.ok) {
      const text = await resp.text();
      return { error: "api_error", message: `API returned ${resp.status}: ${text}` };
    }

    return await resp.json();
  } catch (err) {
    console.error("[Alerts] Fetch error:", err);
    return { error: "network_error", message: err.message };
  }
}

// ── Public API ───────────────────────────────

/**
 * List all alerts for the current user.
 */
export async function listAlerts() {
  return authFetch("/alerts");
}

/**
 * List alerts for a specific product.
 */
export async function listAlertsForProduct(productId) {
  const result = await authFetch("/alerts");
  if (result.error) return result;
  // Filter client-side by productId
  const alerts = (result.alerts || []).filter((a) => a.productId === productId);
  return { alerts };
}

/**
 * Create a new alert.
 * @param {object} alert - { productId, alertType, targetPrice?, dropPercentage?, basePriceAtCreation? }
 */
export async function createAlert(alert) {
  return authFetch("/alerts", {
    method: "POST",
    body: JSON.stringify(alert),
  });
}

/**
 * Delete an alert by ID.
 */
export async function deleteAlert(alertId) {
  return authFetch(`/alerts/${alertId}`, { method: "DELETE" });
}

/**
 * Toggle an alert on/off.
 */
export async function toggleAlert(alertId, enabled) {
  return authFetch(`/alerts/${alertId}/toggle`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

/**
 * Get email preferences.
 */
export async function getEmailPrefs() {
  return authFetch("/alerts/prefs");
}

/**
 * Set email preferences.
 */
export async function setEmailPrefs(emailEnabled) {
  return authFetch("/alerts/prefs", {
    method: "PATCH",
    body: JSON.stringify({ emailEnabled }),
  });
}
