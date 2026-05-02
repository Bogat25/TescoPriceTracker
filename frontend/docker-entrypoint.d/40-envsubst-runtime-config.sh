#!/bin/sh
# Generates /usr/share/nginx/html/runtime-config.js from the bundled template,
# substituting deploy-time env vars so the Angular SPA can read them at runtime
# without being rebuilt. Runs from the official nginx image's entrypoint chain
# (any *.sh in /docker-entrypoint.d/ executes before nginx starts).
set -eu

: "${TESCO_API_BASE_URL:=/api/tesco}"
export TESCO_API_BASE_URL

: "${AUTH_BASE_URL:=/auth}"
export AUTH_BASE_URL

: "${AUTH_LOGIN_URL:=/auth/login}"
export AUTH_LOGIN_URL

: "${AUTH_LOGOUT_URL:=/auth/logout}"
export AUTH_LOGOUT_URL

: "${AUTH_USERINFO_URL:=/auth/userinfo}"
export AUTH_USERINFO_URL

: "${AUTH_ACCOUNT_URL:=/auth/account}"
export AUTH_ACCOUNT_URL

: "${AUTH_TOKEN_URL:=/auth/token}"
export AUTH_TOKEN_URL

template=/usr/share/nginx/html/runtime-config.template.js
output=/usr/share/nginx/html/runtime-config.js

if [ ! -f "$template" ]; then
  echo "runtime-config.template.js not found at $template" >&2
  exit 1
fi

envsubst '${TESCO_API_BASE_URL} ${AUTH_BASE_URL} ${AUTH_LOGIN_URL} ${AUTH_LOGOUT_URL} ${AUTH_USERINFO_URL} ${AUTH_ACCOUNT_URL} ${AUTH_TOKEN_URL}' < "$template" > "$output"
echo "runtime-config.js generated: tescoApiBaseUrl=$TESCO_API_BASE_URL, authBaseUrl=$AUTH_BASE_URL"
