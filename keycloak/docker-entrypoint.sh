#!/bin/sh
set -eu

TEMPLATE=/scripts/realm-template.json
OUTPUT=/opt/keycloak/data/import/realm.json

mkdir -p /opt/keycloak/data/import

# Use sed — no extra tools needed, works in the public Keycloak image
sed -e "s|\${KEYCLOAK_REALM}|${KEYCLOAK_REALM}|g" \
    -e "s|\${KC_CLIENT_ID}|${KC_CLIENT_ID}|g" \
    "$TEMPLATE" > "$OUTPUT"

echo "Realm config generated: realm=${KEYCLOAK_REALM} clientId=${KC_CLIENT_ID}"

exec /opt/keycloak/bin/kc.sh start-dev --import-realm "$@"
