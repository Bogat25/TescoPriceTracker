// ============================================
// AUTH MODULE — Tesco Price Tracker Extension
// ============================================
// Handles Keycloak OIDC authentication using
// browser.identity.launchWebAuthFlow (Chrome/Edge)
// or a redirect-based approach (Firefox).
//
// Stores tokens in browser.storage.local.
// Exposes: login(), logout(), getToken(), getUser(), isLoggedIn()
// ============================================

import ENV from "../env/config.js";

if (typeof browser === "undefined") {
  globalThis.browser = chrome;
}

const STORAGE_KEY = "tpt_auth_session";

// ── PKCE Helpers ─────────────────────────────

function generateRandomString(length) {
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(16).padStart(2, "0")).join("").slice(0, length);
}

async function sha256(plain) {
  const encoder = new TextEncoder();
  const data = encoder.encode(plain);
  return await crypto.subtle.digest("SHA-256", data);
}

function base64UrlEncode(buffer) {
  const bytes = new Uint8Array(buffer);
  let str = "";
  for (const b of bytes) str += String.fromCharCode(b);
  return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function generatePKCE() {
  const verifier = generateRandomString(64);
  const challenge = base64UrlEncode(await sha256(verifier));
  return { verifier, challenge };
}

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

// ── Token Refresh ────────────────────────────

async function refreshToken(session) {
  if (!session || !session.refresh_token) return null;

  const tokenUrl = `${ENV.KEYCLOAK_URL}/protocol/openid-connect/token`;
  const body = new URLSearchParams({
    grant_type: "refresh_token",
    refresh_token: session.refresh_token,
    client_id: ENV.KEYCLOAK_CLIENT_ID,
  });

  try {
    const resp = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!resp.ok) {
      console.warn("[Auth] Token refresh failed:", resp.status);
      return null;
    }

    const tokens = await resp.json();
    const newSession = {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token || session.refresh_token,
      id_token: tokens.id_token || session.id_token,
      expires_at: Date.now() + (tokens.expires_in || 300) * 1000,
      user: session.user, // Keep cached user info
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
 * Start OIDC login via launchWebAuthFlow.
 * Returns { success: true, user } or { success: false, error }.
 */
export async function login() {
  const { verifier, challenge } = await generatePKCE();

  // The redirect URI for extensions
  const redirectUri = browser.identity.getRedirectURL("callback");

  const authUrl = new URL(`${ENV.KEYCLOAK_URL}/protocol/openid-connect/auth`);
  authUrl.searchParams.set("client_id", ENV.KEYCLOAK_CLIENT_ID);
  authUrl.searchParams.set("response_type", "code");
  authUrl.searchParams.set("redirect_uri", redirectUri);
  authUrl.searchParams.set("scope", "openid profile email");
  authUrl.searchParams.set("code_challenge", challenge);
  authUrl.searchParams.set("code_challenge_method", "S256");
  authUrl.searchParams.set("state", generateRandomString(16));

  try {
    const responseUrl = await browser.identity.launchWebAuthFlow({
      url: authUrl.toString(),
      interactive: true,
    });

    // Extract code from redirect URL
    const url = new URL(responseUrl);
    const code = url.searchParams.get("code");
    if (!code) {
      return { success: false, error: "No authorization code received" };
    }

    // Exchange code for tokens
    const tokenUrl = `${ENV.KEYCLOAK_URL}/protocol/openid-connect/token`;
    const body = new URLSearchParams({
      grant_type: "authorization_code",
      code: code,
      redirect_uri: redirectUri,
      client_id: ENV.KEYCLOAK_CLIENT_ID,
      code_verifier: verifier,
    });

    const tokenResp = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });

    if (!tokenResp.ok) {
      const errText = await tokenResp.text();
      console.error("[Auth] Token exchange failed:", errText);
      return { success: false, error: "Token exchange failed" };
    }

    const tokens = await tokenResp.json();

    // Fetch user info
    const userinfoUrl = `${ENV.KEYCLOAK_URL}/protocol/openid-connect/userinfo`;
    const userinfoResp = await fetch(userinfoUrl, {
      headers: { Authorization: `Bearer ${tokens.access_token}` },
    });

    let user = null;
    if (userinfoResp.ok) {
      const info = await userinfoResp.json();
      user = {
        sub: info.sub,
        name: info.preferred_username || info.name || info.email || "User",
        email: info.email || null,
      };
    }

    const session = {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
      id_token: tokens.id_token,
      expires_at: Date.now() + (tokens.expires_in || 300) * 1000,
      user: user,
    };
    await saveSession(session);

    return { success: true, user };
  } catch (err) {
    console.error("[Auth] Login error:", err);
    return { success: false, error: err.message || "Login cancelled" };
  }
}

/**
 * Logout: revoke tokens and clear session.
 */
export async function logout() {
  const session = await loadSession();

  if (session && session.refresh_token) {
    // Best-effort revoke at Keycloak
    const revokeUrl = `${ENV.KEYCLOAK_URL}/protocol/openid-connect/revoke`;
    try {
      await fetch(revokeUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          client_id: ENV.KEYCLOAK_CLIENT_ID,
          token: session.refresh_token,
          token_type_hint: "refresh_token",
        }).toString(),
      });
    } catch {
      // Best effort
    }
  }

  await clearSession();
  return { success: true };
}
