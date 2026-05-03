// ============================================
// AUTH MODULE — Tesco Price Tracker Extension
// ============================================
// Handles authentication via an auth gateway.
// Works with either deployment:
//   Production (Gavaller ecosystem):
//     AUTH_GATEWAY_URL = https://gateway.gavaller.com
//   Standalone (TescoPriceTracker):
//     AUTH_GATEWAY_URL = https://price-tracker.gavaller.com/auth
//
// Opens a browser tab → AUTH_GATEWAY_URL/login,
// the gateway performs OIDC with Keycloak, then
// redirects to /extension-relay → /extension-done?ext_code=...
// The extension intercepts the navigation to extension-done,
// closes the tab, and exchanges the ext_code for real tokens.
//
// Stores tokens in browser.storage.local.
// Exposes: login(), logout(), getToken(), getUser(), isLoggedIn()
// ============================================

import ENV from "../env/config.js";

if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

const STORAGE_KEY = "tpt_auth_session";

// Paths are relative to AUTH_GATEWAY_URL, so they work for both:
//   gateway.gavaller.com/extension-done
//   price-tracker.gavaller.com/auth/extension-done
const EXTENSION_DONE_PATH = "/extension-done";
const EXTENSION_TOKEN_PATH = "/extension-token";
const LOGIN_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

// ── Token Storage ────────────────────────────

async function saveSession(session) {
  await browser.storage.local.set({ [STORAGE_KEY]: session });
}

async function loadSession() {
  const result = await browser.storage.local.get(STORAGE_KEY);
  return result[STORAGE_KEY] || null;
}

async function clearSession() {
  await browser.storage.local.remove(STORAGE_KEY);
}

// ── Token Refresh via auth-gateway ───────────

async function refreshToken(session) {
  if (!session || !session.refresh_token) return null;

  const authGatewayBase = ENV.AUTH_GATEWAY_URL.replace(/\/+$/, "");

  try {
    const resp = await fetch(`${authGatewayBase}/extension-refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: session.refresh_token }),
    });

    if (!resp.ok) {
      console.warn("[Auth] Token refresh failed:", resp.status);
      return null;
    }

    const tokens = await resp.json();
    const newSession = {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token || session.refresh_token,
      id_token: session.id_token,
      expires_at: Date.now() + (tokens.expires_in || 300) * 1000,
      user: session.user,
    };
    await saveSession(newSession);
    return newSession;
  } catch (err) {
    console.error("[Auth] Refresh error:", err);
    return null;
  }
}

// ── Public API ───────────────────────────────

/**
 * Get a valid access token, refreshing if needed.
 * Returns null if not logged in.
 */
export async function getToken() {
  let session = await loadSession();
  if (!session) return null;

  // Refresh 30s before expiry
  if (session.expires_at && Date.now() > session.expires_at - 30000) {
    session = await refreshToken(session);
    if (!session) {
      await clearSession();
      return null;
    }
  }
  return session.access_token;
}

/**
 * Get cached user info, or null.
 */
export async function getUser() {
  const session = await loadSession();
  return session?.user || null;
}

/**
 * Check if user is logged in (has a valid session).
 */
export async function isLoggedIn() {
  const token = await getToken();
  return token !== null;
}

/**
 * Start login via the auth gateway tab flow.
 * Works with both the Gavaller ecosystem gateway (gateway.gavaller.com)
 * and the standalone TescoPriceTracker gateway (price-tracker.gavaller.com/auth).
 * 1. Opens a browser tab → AUTH_GATEWAY_URL/login?returnUrl=AUTH_GATEWAY_URL/extension-relay
 * 2. User logs in via Keycloak — handled entirely by the gateway
 * 3. Gateway redirects to AUTH_GATEWAY_URL/extension-done?ext_code=<code>
 * 4. Extension catches the tab URL change, closes tab, fetches tokens
 * Returns { success: true, user } or { success: false, error }.
 */
export async function login() {
  const authGatewayBase = ENV.AUTH_GATEWAY_URL.replace(/\/+$/, "");
  // Use an absolute returnUrl so both the C# and Python validators accept it.
  const returnUrl = `${authGatewayBase}/extension-relay`;
  const loginUrl = `${authGatewayBase}/login?returnUrl=${encodeURIComponent(returnUrl)}`;
  const donePath = `${authGatewayBase}${EXTENSION_DONE_PATH}`;

  return new Promise((resolve) => {
    let authTabId = null;
    let settled = false;
    let timeoutId = null;

    function finish(result) {
      if (settled) return;
      settled = true;
      if (timeoutId) clearTimeout(timeoutId);
      browser.tabs.onUpdated.removeListener(onTabUpdated);
      if (authTabId !== null) {
        browser.tabs.remove(authTabId).catch(() => {});
      }
      resolve(result);
    }

    async function onTabUpdated(tabId, changeInfo) {
      if (tabId !== authTabId) return;
      const url = changeInfo.url || "";
      if (!url.startsWith(donePath)) return;

      let extCode = null;
      try {
        extCode = new URL(url).searchParams.get("ext_code");
      } catch { /* ignore */ }

      if (!extCode) {
        finish({ success: false, error: "No ext_code in callback URL" });
        return;
      }

      try {
        const tokenResp = await fetch(
          `${authGatewayBase}${EXTENSION_TOKEN_PATH}?code=${encodeURIComponent(extCode)}`
        );
        if (!tokenResp.ok) {
          finish({ success: false, error: `Token exchange failed: ${tokenResp.status}` });
          return;
        }
        const tokens = await tokenResp.json();

        // User info is included inline by the gateway relay endpoint
        const user = tokens.name
          ? { name: tokens.name, email: tokens.email || null }
          : null;

        const session = {
          access_token: tokens.access_token,
          refresh_token: tokens.refresh_token,
          id_token: tokens.id_token,
          expires_at: Date.now() + (tokens.expires_in || 300) * 1000,
          user,
        };
        await saveSession(session);
        finish({ success: true, user });
      } catch (err) {
        console.error("[Auth] Login fetch error:", err);
        finish({ success: false, error: err.message || "Token fetch failed" });
      }
    }

    browser.tabs.onUpdated.addListener(onTabUpdated);

    browser.tabs.create({ url: loginUrl }).then((tab) => {
      authTabId = tab.id;
    }).catch((err) => {
      finish({ success: false, error: err.message || "Failed to open auth tab" });
    });

    timeoutId = setTimeout(() => {
      finish({ success: false, error: "Login timed out" });
    }, LOGIN_TIMEOUT_MS);
  });
}

/**
 * Logout: clear local session.
 * The server-side session cookie is managed separately by the auth-gateway.
 */
export async function logout() {
  await clearSession();
  return { success: true };
}
