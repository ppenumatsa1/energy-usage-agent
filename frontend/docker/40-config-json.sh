#!/bin/sh
# Writes the SPA runtime config (/config.json) from environment variables at container start.
set -eu

HTML_ROOT="${HTML_ROOT:-/usr/share/nginx/html}"
AUTH_MODE="${AUTH_MODE:-entra}"
ENTRA_CLIENT_ID="${ENTRA_CLIENT_ID:-}"
ENTRA_AUTHORITY="${ENTRA_AUTHORITY:-}"
API_SCOPE="${API_SCOPE:-}"

case "$AUTH_MODE" in
  entra | dev) ;;
  *)
    echo "$0: AUTH_MODE must be 'entra' or 'dev' (got '$AUTH_MODE')" >&2
    exit 1
    ;;
esac

if [ "$AUTH_MODE" = "entra" ] && { [ -z "$ENTRA_CLIENT_ID" ] || [ -z "$ENTRA_AUTHORITY" ] || [ -z "$API_SCOPE" ]; }; then
  echo "$0: warning: AUTH_MODE=entra but ENTRA_CLIENT_ID, ENTRA_AUTHORITY or API_SCOPE is empty; the app will show a configuration error" >&2
fi

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr -d '\n\r'
}

printf '{"authMode":"%s","clientId":"%s","authority":"%s","apiScope":"%s"}\n' \
  "$(json_escape "$AUTH_MODE")" \
  "$(json_escape "$ENTRA_CLIENT_ID")" \
  "$(json_escape "$ENTRA_AUTHORITY")" \
  "$(json_escape "$API_SCOPE")" > "$HTML_ROOT/config.json"

echo "$0: wrote $HTML_ROOT/config.json (authMode=$AUTH_MODE)"
