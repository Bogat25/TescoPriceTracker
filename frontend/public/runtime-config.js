// Default runtime configuration used during local `ng serve` development.
// In production this file is overwritten at container start by
// /docker-entrypoint.d/40-envsubst-runtime-config.sh, which substitutes
// TESCO_API_BASE_URL from the environment into runtime-config.template.js.
window.__APP_CONFIG__ = {
  tescoApiBaseUrl: '${TESCO_API_BASE_URL}',
};
