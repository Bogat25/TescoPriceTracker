#!/bin/sh
set -eu

TEMPLATE=/scripts/realm-template.json
OUTPUT=/opt/keycloak/data/import/realm.json

mkdir -p /opt/keycloak/data/import

# Defaults preserve the previous "match anything" behavior if env unset.
: "${REALM_REDIRECT_URIS:=*}"
: "${REALM_WEB_ORIGINS:=*}"
: "${REALM_POST_LOGOUT_REDIRECT_URIS:=+}"

# Convert "a, b, c" -> ["a","b","c"] (POSIX sh, no jq)
csv_to_json_array() {
    out=""
    saved_IFS="$IFS"
    IFS=','
    for item in $1; do
        item=$(printf '%s' "$item" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        [ -z "$item" ] && continue
        [ -n "$out" ] && out="$out,"
        escaped=$(printf '%s' "$item" | sed 's/\\/\\\\/g; s/"/\\"/g')
        out="$out\"$escaped\""
    done
    IFS="$saved_IFS"
    printf '[%s]' "$out"
}

# Convert "a, b, c" -> "a##b##c" (Keycloak's separator for this attribute)
csv_to_hash_separated() {
    out=""
    saved_IFS="$IFS"
    IFS=','
    for item in $1; do
        item=$(printf '%s' "$item" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        [ -z "$item" ] && continue
        [ -n "$out" ] && out="$out##"
        out="$out$item"
    done
    IFS="$saved_IFS"
    printf '%s' "$out"
}

# Escape characters that have meaning in sed's replacement when using `|` as delimiter.
sed_escape_replacement() {
    printf '%s' "$1" | sed 's/[&\\|]/\\&/g'
}

REALM_REDIRECT_URIS_JSON=$(csv_to_json_array "$REALM_REDIRECT_URIS")
REALM_WEB_ORIGINS_JSON=$(csv_to_json_array "$REALM_WEB_ORIGINS")
REALM_POST_LOGOUT_REDIRECT_URIS_HASH=$(csv_to_hash_separated "$REALM_POST_LOGOUT_REDIRECT_URIS")

# Confidential admin client used by the alert-service for the daily user sync.
: "${KC_ADMIN_CLIENT_ID:=tesco-alert-admin}"
: "${KC_ADMIN_CLIENT_SECRET:=changeme-admin-secret}"

ESC_REALM=$(sed_escape_replacement "$KEYCLOAK_REALM")
ESC_CLIENT=$(sed_escape_replacement "$KC_CLIENT_ID")
ESC_ADMIN_CLIENT=$(sed_escape_replacement "$KC_ADMIN_CLIENT_ID")
ESC_ADMIN_SECRET=$(sed_escape_replacement "$KC_ADMIN_CLIENT_SECRET")
ESC_REDIRECT=$(sed_escape_replacement "$REALM_REDIRECT_URIS_JSON")
ESC_ORIGINS=$(sed_escape_replacement "$REALM_WEB_ORIGINS_JSON")
ESC_LOGOUT=$(sed_escape_replacement "$REALM_POST_LOGOUT_REDIRECT_URIS_HASH")

sed -e "s|\${KEYCLOAK_REALM}|$ESC_REALM|g" \
    -e "s|\${KC_CLIENT_ID}|$ESC_CLIENT|g" \
    -e "s|\${KC_ADMIN_CLIENT_ID}|$ESC_ADMIN_CLIENT|g" \
    -e "s|\${KC_ADMIN_CLIENT_SECRET}|$ESC_ADMIN_SECRET|g" \
    -e "s|\${REALM_REDIRECT_URIS_JSON}|$ESC_REDIRECT|g" \
    -e "s|\${REALM_WEB_ORIGINS_JSON}|$ESC_ORIGINS|g" \
    -e "s|\${REALM_POST_LOGOUT_REDIRECT_URIS_HASH}|$ESC_LOGOUT|g" \
    "$TEMPLATE" > "$OUTPUT"

echo "Realm config generated:"
echo "  realm=${KEYCLOAK_REALM} clientId=${KC_CLIENT_ID} adminClientId=${KC_ADMIN_CLIENT_ID}"
echo "  redirectUris=$REALM_REDIRECT_URIS_JSON"
echo "  webOrigins=$REALM_WEB_ORIGINS_JSON"
echo "  postLogoutRedirectUris=$REALM_POST_LOGOUT_REDIRECT_URIS_HASH"

exec /opt/keycloak/bin/kc.sh start --import-realm "$@"
