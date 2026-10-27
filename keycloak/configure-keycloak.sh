#!/bin/sh
# Applies what a realm import cannot, once per deploy after Keycloak is healthy.
# The import skips a realm that already exists, and the bootstrap admin is only
# created on the very first start, so without this a value changed in Infisical
# would never reach a Keycloak that keeps its data:
#
#   1. the master-realm admin password: when the configured one is refused, log
#      in with the last one that worked and change it to the configured one
#   2. the admin client's secret, and its permission to list users
#   3. the session lifetimes
#
# No credential is ever printed. They reach kcadm through KC_CLI_PASSWORD or
# standard input, never as command-line arguments.
set -eu

KCADM=/opt/keycloak/bin/kcadm.sh
CONFIG=/tmp/kcadm.config
LOGIN_ERRORS=/tmp/kcadm-login.err
SERVER="${KEYCLOAK_INTERNAL_URL:-http://keycloak:8080}"
REALM="${KEYCLOAK_REALM:-tesco-tracker}"
ADMIN_CLIENT="${KC_ADMIN_CLIENT_ID:-tesco-alert-admin}"
# On the keycloak-data volume, next to the database the password belongs to.
STATE_DIR="${CREDENTIAL_STATE_DIR:-/opt/keycloak/data/credential-state}"
ADMIN_STATE="$STATE_DIR/bootstrap-admin-password"

: "${KC_BOOTSTRAP_ADMIN_USERNAME:?KC_BOOTSTRAP_ADMIN_USERNAME is required}"
: "${KC_BOOTSTRAP_ADMIN_PASSWORD:?KC_BOOTSTRAP_ADMIN_PASSWORD is required}"

login() {
  KC_CLI_PASSWORD="$1" "$KCADM" config credentials --config "$CONFIG" \
    --server "$SERVER" \
    --realm master \
    --user "$KC_BOOTSTRAP_ADMIN_USERNAME" >/dev/null 2>>"$LOGIN_ERRORS"
}

# A value as the inside of a JSON string, read from standard input.
json_escape() {
  sed 's/\\/\\\\/g; s/"/\\"/g'
}

record_admin_password() {
  if [ -s "$ADMIN_STATE" ] && [ "$(cat "$ADMIN_STATE")" = "$KC_BOOTSTRAP_ADMIN_PASSWORD" ]; then
    return 0
  fi
  if mkdir -p "$STATE_DIR" && chmod 700 "$STATE_DIR" \
    && (umask 077 && printf '%s' "$KC_BOOTSTRAP_ADMIN_PASSWORD" > "$ADMIN_STATE.tmp") \
    && mv "$ADMIN_STATE.tmp" "$ADMIN_STATE"; then
    echo "Recorded the admin password in use, for the next change."
  else
    echo "warning: could not record the admin password in $STATE_DIR; the next change has to be made by hand." >&2
  fi
}

# -- 1. Admin password ---------------------------------------------------------
: > "$LOGIN_ERRORS"
if login "$KC_BOOTSTRAP_ADMIN_PASSWORD"; then
  echo "Logged in with the configured admin password."
elif [ -s "$ADMIN_STATE" ] && login "$(cat "$ADMIN_STATE")"; then
  admin_id=$("$KCADM" get users -r master --config "$CONFIG" \
    -q exact=true -q username="$KC_BOOTSTRAP_ADMIN_USERNAME" \
    --fields id --format csv --noquotes)
  if [ -z "$admin_id" ]; then
    echo "error: the master realm has no user $KC_BOOTSTRAP_ADMIN_USERNAME." >&2
    exit 1
  fi
  printf '{"type":"password","temporary":false,"value":"%s"}' \
    "$(printf '%s' "$KC_BOOTSTRAP_ADMIN_PASSWORD" | json_escape)" \
    | "$KCADM" update "users/$admin_id/reset-password" -r master --config "$CONFIG" -f - -n
  if ! login "$KC_BOOTSTRAP_ADMIN_PASSWORD"; then
    echo "error: the admin password was changed, but the configured one still does not log in." >&2
    exit 1
  fi
  echo "Changed the admin password to the configured one."
else
  echo "error: neither the configured nor the last recorded admin password logs in." >&2
  echo "Change it by hand: docs/deployment.md, 'Rotating the infrastructure credentials'." >&2
  cat "$LOGIN_ERRORS" >&2
  exit 1
fi
record_admin_password

# -- 2. Admin client secret ----------------------------------------------------
if [ -z "${KC_ADMIN_CLIENT_SECRET:-}" ]; then
  echo "KC_ADMIN_CLIENT_SECRET is not set; the $ADMIN_CLIENT secret was left as it is."
else
  client_id=$("$KCADM" get clients -r "$REALM" --config "$CONFIG" \
    -q clientId="$ADMIN_CLIENT" --fields id --format csv --noquotes)
  if [ -z "$client_id" ]; then
    echo "warning: realm $REALM has no client $ADMIN_CLIENT; its secret was not set." >&2
  else
    current=$("$KCADM" get "clients/$client_id/client-secret" -r "$REALM" --config "$CONFIG" \
      --fields value --format csv --noquotes)
    if [ "$current" = "$KC_ADMIN_CLIENT_SECRET" ]; then
      echo "The $ADMIN_CLIENT secret is already the configured one."
    else
      printf '{"secret":"%s"}' "$(printf '%s' "$KC_ADMIN_CLIENT_SECRET" | json_escape)" \
        | "$KCADM" update "clients/$client_id" -r "$REALM" --config "$CONFIG" -f -
      echo "Changed the $ADMIN_CLIENT secret to the configured one."
    fi
  fi
fi

# -- 2b. The admin client may list users -----------------------------------------
# The realm template grants realm-management/view-users to the client's service
# account, but an import never touches an existing realm: without this the
# alert service's nightly user sync is refused with 403. Adding a role the
# account already has is a no-op.
if "$KCADM" get users -r "$REALM" --config "$CONFIG" -q exact=true \
    -q username="service-account-$ADMIN_CLIENT" --fields id --format csv --noquotes | grep -q .; then
  "$KCADM" add-roles -r "$REALM" --config "$CONFIG" \
    --uusername "service-account-$ADMIN_CLIENT" --cclientid realm-management --rolename view-users
  echo "The $ADMIN_CLIENT service account may list users."
else
  echo "warning: $ADMIN_CLIENT has no service account in realm $REALM; user listing not granted." >&2
fi

# -- 3. Session lifetimes ------------------------------------------------------
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

echo "Tesco Keycloak configuration is ready."
