// Processed by envsubst at container start (40-envsubst-runtime-config.sh).
// The output replaces /usr/share/nginx/html/runtime-config.js so the SPA
// reads deploy-time config values without a rebuild.
window.__APP_CONFIG__ = {
  tescoApiBaseUrl: '${TESCO_API_BASE_URL}',
  authBaseUrl: '${AUTH_BASE_URL}',
  authLoginUrl: '${AUTH_LOGIN_URL}',
  authLogoutUrl: '${AUTH_LOGOUT_URL}',
  authUserinfoUrl: '${AUTH_USERINFO_URL}',
  authAccountUrl: '${AUTH_ACCOUNT_URL}',
  authTokenUrl: '${AUTH_TOKEN_URL}',
};
