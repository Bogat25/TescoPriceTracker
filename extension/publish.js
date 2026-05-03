// =============================================================
// publish.js — Publish Tesco Price Tracker to browser stores
// =============================================================
// Zero external dependencies — uses only built-in Node.js modules.
// Reads ALL credentials from extension/.env (same file as build.js).
// Gracefully skips any store whose credentials are not filled in.
//
// Usage:
//   node publish.js            — publish to all stores
//   node publish.js chrome     — Chrome only
//   node publish.js firefox    — Firefox only
//   node publish.js edge       — Edge only
//
// Run AFTER: node build.js
//
// ── Where to get credentials ─────────────────────────────────
//   Chrome  → https://developer.chrome.com/docs/webstore/using-api/
//   Firefox → https://addons.mozilla.org/developers → API Keys
//   Edge    → https://partner.microsoft.com/dashboard → API Access
// =============================================================

const https  = require('https');
const fs     = require('fs');
const path   = require('path');
const crypto = require('crypto');

// ── Load store-listing.json ───────────────────────────────────
function loadListing() {
  const p = path.resolve(__dirname, 'store-listing.json');
  if (!fs.existsSync(p)) return null;
  try { return JSON.parse(fs.readFileSync(p, 'utf-8')); }
  catch (e) { console.warn('  ⚠  Could not parse store-listing.json:', e.message); return null; }
}

// ── Load .env ────────────────────────────────────────────────
function loadEnv() {
  const envPath = path.resolve(__dirname, '.env');
  if (!fs.existsSync(envPath)) {
    console.error('ERROR: .env file not found.');
    process.exit(1);
  }
  const env = {};
  for (const line of fs.readFileSync(envPath, 'utf-8').split('\n')) {
    const t = line.trim();
    if (!t || t.startsWith('#')) continue;
    const eq = t.indexOf('=');
    if (eq === -1) continue;
    env[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
  }
  return env;
}

// ── Read version from manifest ────────────────────────────────
function getVersion() {
  return JSON.parse(fs.readFileSync(path.resolve(__dirname, 'manifest.json'), 'utf-8')).version;
}

// ── HTTP helpers ─────────────────────────────────────────────
function httpRequest(options, bodyBuf) {
  return new Promise((resolve, reject) => {
    const req = https.request(options, res => {
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {
        const raw = Buffer.concat(chunks).toString('utf-8');
        if (res.statusCode >= 400) {
          reject(new Error(`HTTP ${res.statusCode} ${res.statusMessage}: ${raw}`));
          return;
        }
        try { resolve({ status: res.statusCode, body: JSON.parse(raw) }); }
        catch { resolve({ status: res.statusCode, body: raw }); }
      });
    });
    req.on('error', reject);
    if (bodyBuf && bodyBuf.length) req.write(bodyBuf);
    req.end();
  });
}

function postForm(urlStr, params) {
  const body = new URLSearchParams(params).toString();
  const u = new URL(urlStr);
  return httpRequest({
    hostname: u.hostname,
    path: u.pathname + u.search,
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'Content-Length': Buffer.byteLength(body),
    },
  }, Buffer.from(body));
}

function putBinary(urlStr, data, contentType, token, extraHeaders = {}) {
  const u = new URL(urlStr);
  return httpRequest({
    hostname: u.hostname,
    path: u.pathname + u.search,
    method: 'PUT',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': contentType,
      'Content-Length': data.length,
      ...extraHeaders,
    },
  }, data);
}

function postBinary(urlStr, data, contentType, token) {
  const u = new URL(urlStr);
  return httpRequest({
    hostname: u.hostname,
    path: u.pathname + u.search,
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': contentType,
      'Content-Length': data.length,
    },
  }, data);
}

function postJson(urlStr, body, token) {
  const buf = Buffer.from(JSON.stringify(body));
  const u = new URL(urlStr);
  return httpRequest({
    hostname: u.hostname,
    path: u.pathname + u.search,
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Content-Length': buf.length,
    },
  }, buf);
}

function postEmpty(urlStr, token) {
  const u = new URL(urlStr);
  return httpRequest({
    hostname: u.hostname,
    path: u.pathname + u.search,
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Length': 0,
    },
  }, Buffer.alloc(0));
}

function buildMultipart(fields, fileName, fileData) {
  const boundary = '----PublishBoundary' + crypto.randomBytes(8).toString('hex');
  const parts = [];

  for (const [key, value] of Object.entries(fields)) {
    parts.push(Buffer.from(
      `--${boundary}\r\n` +
      `Content-Disposition: form-data; name="${key}"\r\n\r\n` +
      `${value}\r\n`
    ));
  }
  parts.push(Buffer.from(
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="upload"; filename="${fileName}"\r\n` +
    `Content-Type: application/zip\r\n\r\n`
  ));
  parts.push(fileData);
  parts.push(Buffer.from(`\r\n--${boundary}--\r\n`));

  return { body: Buffer.concat(parts), boundary };
}

function postMultipart(urlStr, fields, fileName, fileData, token) {
  const { body, boundary } = buildMultipart(fields, fileName, fileData);
  const u = new URL(urlStr);
  return httpRequest({
    hostname: u.hostname,
    path: u.pathname + u.search,
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': `multipart/form-data; boundary=${boundary}`,
      'Content-Length': body.length,
    },
  }, body);
}

// ── Chrome Web Store ─────────────────────────────────────────
// Get credentials at: https://developer.chrome.com/docs/webstore/using-api/
// Required .env vars:
//   CHROME_EXTENSION_ID     — from the Web Store developer dashboard
//   CHROME_CLIENT_ID        — Google OAuth 2.0 client ID (Desktop app type)
//   CHROME_CLIENT_SECRET    — matching client secret
//   CHROME_REFRESH_TOKEN    — long-lived refresh token (run OAuth flow once)

async function publishChrome(env) {
  const id      = env.CHROME_EXTENSION_ID;
  const cid     = env.CHROME_CLIENT_ID;
  const secret  = env.CHROME_CLIENT_SECRET;
  const refresh = env.CHROME_REFRESH_TOKEN;

  if (!id || !cid || !secret || !refresh) {
    console.log('  ⏭  Chrome: credentials not set in .env — skipping');
    return;
  }

  const zipPath = path.resolve(__dirname, 'dist', 'tesco-price-tracker-chrome.zip');
  if (!fs.existsSync(zipPath)) {
    throw new Error('Chrome ZIP missing — run node build.js first.');
  }

  console.log('\n── Chrome Web Store ──');

  // 1. Exchange refresh token for access token
  const tokenRes = await postForm('https://oauth2.googleapis.com/token', {
    client_id:     cid,
    client_secret: secret,
    refresh_token: refresh,
    grant_type:    'refresh_token',
  });
  const token = tokenRes.body.access_token;
  if (!token) throw new Error('Chrome: could not get access token');

  // 2. Upload ZIP
  const zipData = fs.readFileSync(zipPath);
  const upRes = await putBinary(
    `https://www.googleapis.com/upload/chromewebstore/v1.1/items/${id}`,
    zipData,
    'application/zip',
    token,
    { 'X-Goog-Upload-Protocol': 'raw' }
  );
  if (upRes.body.uploadState && upRes.body.uploadState !== 'SUCCESS') {
    throw new Error(`Chrome upload failed: ${JSON.stringify(upRes.body)}`);
  }
  console.log('  ✓ ZIP uploaded');

  // 3. Publish
  await postJson(
    `https://www.googleapis.com/chromewebstore/v1.1/items/${id}/publish`,
    {},
    token
  );
  console.log('  ✓ Published to Chrome Web Store');
}

// ── Firefox AMO ──────────────────────────────────────────────

// Patch listing metadata: summary, description, homepage, support info.
// AMO API v5 supports translatable fields as {"en-US": "...", "hu": "..."}.
async function patchFirefoxListing(extId, listing, jwt) {
  const patch = {};

  if (listing.summary) {
    patch.summary = {};
    if (listing.summary.en) patch.summary['en-US'] = listing.summary.en;
    if (listing.summary.hu) patch.summary['hu']    = listing.summary.hu;
  }
  if (listing.description_html) {
    patch.description = {};
    if (listing.description_html.en) patch.description['en-US'] = listing.description_html.en;
    if (listing.description_html.hu) patch.description['hu']    = listing.description_html.hu;
  }
  if (listing.homepage)     patch.homepage     = listing.homepage;
  if (listing.support_url)  patch.support_url  = listing.support_url;
  if (listing.support_email) patch.support_email = listing.support_email;

  const buf = Buffer.from(JSON.stringify(patch));
  const patchUrl = `https://addons.mozilla.org/api/v5/addons/addon/${encodeURIComponent(extId)}/`;
  const u = new URL(patchUrl);
  await httpRequest({
    hostname: u.hostname,
    path: u.pathname,
    method: 'PATCH',
    headers: {
      'Authorization': `JWT ${jwt}`,
      'Content-Type': 'application/json',
      'Content-Length': buf.length,
    },
  }, buf);
  console.log('  ✓ Listing metadata updated (summary, description, homepage)');
}

// Get credentials at: https://addons.mozilla.org/developers → Tools → Manage API Keys
// Required .env vars:
//   FIREFOX_EXTENSION_ID — your add-on's slug or GUID (e.g. tesco-tracker@gavaller.com)
//   FIREFOX_API_KEY      — JWT issuer (shown as "User" in AMO API Key page)
//   FIREFOX_API_SECRET   — JWT secret

function makeFirefoxJwt(apiKey, apiSecret) {
  const b64url = buf => buf.toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
  const header  = b64url(Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })));
  const payload = b64url(Buffer.from(JSON.stringify({
    iss: apiKey,
    jti: crypto.randomBytes(16).toString('hex'),
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + 300,
  })));
  const sig = b64url(crypto.createHmac('sha256', apiSecret).update(`${header}.${payload}`).digest());
  return `${header}.${payload}.${sig}`;
}

async function publishFirefox(env) {
  const extId     = env.FIREFOX_EXTENSION_ID;
  const apiKey    = env.FIREFOX_API_KEY;
  const apiSecret = env.FIREFOX_API_SECRET;

  if (!extId || !apiKey || !apiSecret) {
    console.log('  ⏭  Firefox: credentials not set in .env — skipping');
    return;
  }

  const version = getVersion();
  const zipPath = path.resolve(__dirname, 'dist', 'tesco-price-tracker-firefox.zip');
  if (!fs.existsSync(zipPath)) {
    throw new Error('Firefox ZIP missing — run node build.js first.');
  }

  console.log('\n── Firefox AMO ──');

  const jwt      = makeFirefoxJwt(apiKey, apiSecret);
  const zipData  = fs.readFileSync(zipPath);

  // Step 1: Upload the file and get a UUID
  const uploadRes = await postMultipart(
    'https://addons.mozilla.org/api/v5/addons/upload/',
    { channel: 'listed' },
    'extension.zip',
    zipData,
    jwt
  );
  const uuid = uploadRes.body.uuid;
  if (!uuid) throw new Error(`Firefox upload failed: ${JSON.stringify(uploadRes.body)}`);
  console.log('  ✓ File uploaded, uuid:', uuid);

  // Step 2: Create / update the version
  const versionUrl = `https://addons.mozilla.org/api/v5/addons/${encodeURIComponent(extId)}/versions/${version}/`;
  const u = new URL(versionUrl);
  const body = Buffer.from(JSON.stringify({ upload: uuid }));
  await httpRequest({
    hostname: u.hostname,
    path: u.pathname,
    method: 'PUT',
    headers: {
      'Authorization': `JWT ${jwt}`,
      'Content-Type': 'application/json',
      'Content-Length': body.length,
    },
  }, body);
  console.log('  ✓ Version submitted to Firefox AMO (enters review queue)');

  // Step 3: Update listing metadata (summary, description, homepage) via PATCH
  const listing = loadListing();
  if (listing) {
    await patchFirefoxListing(extId, listing, makeFirefoxJwt(apiKey, apiSecret));
  } else {
    console.log('  ℹ  store-listing.json not found — skipping metadata update');
  }
}

// ── Edge Add-ons ─────────────────────────────────────────────
// Get credentials at: https://partner.microsoft.com/dashboard →
//   Extensions → your extension → Publish → API Access → Create API credentials
// Required .env vars:
//   EDGE_PRODUCT_ID     — the product ID shown on the dashboard
//   EDGE_CLIENT_ID      — Azure AD app client ID
//   EDGE_CLIENT_SECRET  — Azure AD app client secret
//   EDGE_TENANT_ID      — Azure AD tenant ID (or "common")

async function publishEdge(env) {
  const productId    = env.EDGE_PRODUCT_ID;
  const clientId     = env.EDGE_CLIENT_ID;
  const clientSecret = env.EDGE_CLIENT_SECRET;
  const tenantId     = env.EDGE_TENANT_ID;

  if (!productId || !clientId || !clientSecret || !tenantId) {
    console.log('  ⏭  Edge: credentials not set in .env — skipping');
    return;
  }

  const zipPath = path.resolve(__dirname, 'dist', 'tesco-price-tracker-edge.zip');
  if (!fs.existsSync(zipPath)) {
    throw new Error('Edge ZIP missing — run node build.js first.');
  }

  console.log('\n── Edge Add-ons ──');

  // 1. Get Azure AD access token (client credentials flow)
  const tokenRes = await postForm(
    `https://login.microsoftonline.com/${tenantId}/oauth2/v2.0/token`,
    {
      client_id:     clientId,
      client_secret: clientSecret,
      scope:         'https://api.addons.microsoftedge.microsoft.com/.default',
      grant_type:    'client_credentials',
    }
  );
  const token = tokenRes.body.access_token;
  if (!token) throw new Error('Edge: could not get access token');

  // 2. Upload ZIP package
  const zipData = fs.readFileSync(zipPath);
  await postBinary(
    `https://api.addons.microsoftedge.microsoft.com/v1/products/${productId}/submissions/draft/package`,
    zipData,
    'application/zip',
    token
  );
  console.log('  ✓ ZIP uploaded');

  // 3. Publish submission
  await postEmpty(
    `https://api.addons.microsoftedge.microsoft.com/v1/products/${productId}/submissions`,
    token
  );
  console.log('  ✓ Submitted to Edge Add-ons');
}

// ── Main ─────────────────────────────────────────────────────
async function main() {
  const args   = process.argv.slice(2);
  const stores = args.length ? args : ['chrome', 'firefox', 'edge'];

  console.log('Tesco Price Tracker — Publish to Stores');
  console.log('─'.repeat(40));
  console.log(`  Version : ${getVersion()}`);
  console.log(`  Stores  : ${stores.join(', ')}`);

  const env = loadEnv();
  let anyError = false;

  for (const store of stores) {
    try {
      if      (store === 'chrome')  await publishChrome(env);
      else if (store === 'firefox') await publishFirefox(env);
      else if (store === 'edge')    await publishEdge(env);
      else console.warn(`  ⚠  Unknown store: ${store}`);
    } catch (err) {
      console.error(`  ✗  ${store}: ${err.message}`);
      anyError = true;
    }
  }

  console.log('\n' + '─'.repeat(40));
  if (anyError) {
    console.error('  ✗  Some stores failed — check errors above.');
    process.exit(1);
  } else {
    console.log('  ✓  All done!');
  }
}

main();
