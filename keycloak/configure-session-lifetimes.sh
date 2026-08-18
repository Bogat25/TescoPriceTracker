#!/bin/sh
set -eu

KCADM=/opt/keycloak/bin/kcadm.sh
CONFIG=/tmp/kcadm.config
SERVER="${KEYCLOAK_INTERNAL_URL:-http://keycloak:8080}"
REALM="${KEYCLOAK_REALM:-tesco-tracker}"

: "${KC_BOOTSTRAP_ADMIN_USERNAME:?KC_BOOTSTRAP_ADMIN_USERNAME is required}"
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?KC_BOOTSTRAP_ADMIN_PASSWORD is required}"

"$KCADM" config credentials --config "$CONFIG" \
  --server "$SERVER" \
  --realm master \
  --user "$KC_BOOTSTRAP_ADMIN_USERNAME" \
  --password "$KC_BOOTSTRAP_ADMIN_PASSWORD"

# Realm imports deliberately do not replace an existing realm. Reapply these
# mutable settings through the Admin API on every deployment so retained
# Keycloak data receives the same session policy as a fresh installation.
"$KCADM" update "realms/$REALM" --config "$CONFIG" \
  -s accessTokenLifespan=900 \
  -s ssoSessionIdleTimeout=2592000 \
  -s ssoSessionMaxLifespan=7776000 \
  -s ssoSessionIdleTimeoutRememberMe=5184000 \
  -s ssoSessionMaxLifespanRememberMe=15552000 \
  -s clientSessionIdleTimeout=2592000 \
  -s clientSessionMaxLifespan=7776000 \
  -s rememberMe=true

"$KCADM" get "realms/$REALM" --config "$CONFIG" \
  --fields accessTokenLifespan,ssoSessionIdleTimeout,ssoSessionMaxLifespan \
  | grep -q '2592000'

echo "Tesco Keycloak session lifetime configuration is ready."
