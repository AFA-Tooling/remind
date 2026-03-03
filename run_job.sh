#!/bin/bash
# run_job.sh — Container entrypoint for the AutoRemind Cloud Run Job.
#
# JSON credential secrets are mounted by Cloud Run from Secret Manager as flat
# files at /secrets/<filename>.json (path-based --set-secrets mount).
# Env-var secrets (Supabase, Discord) are injected as environment variables.

set -e  # Exit immediately on any error

CONFIG_DIR="/app/services/config"
mkdir -p "$CONFIG_DIR"

echo "==> Populating secrets into $CONFIG_DIR"

copy_secret() {
    local SRC="$1"
    local DEST="$2"
    local LABEL="$3"
    if [ -f "$SRC" ]; then
        cp "$SRC" "$DEST"
        echo "    ✓ $LABEL"
    else
        echo "    ⚠ Warning: $LABEL not found at $SRC — this step may fail"
    fi
}

copy_secret "/secrets/oauth/oauth_client_secret.json" "$CONFIG_DIR/oauth_client_secret.json" "oauth_client_secret.json"
copy_secret "/secrets/sa/service_account.json"       "$CONFIG_DIR/service_account.json"     "service_account.json"
copy_secret "/secrets/gmail/token.json"              "$CONFIG_DIR/token.json"               "token.json"

echo ""
echo "==> Starting AutoRemind pipeline"
echo ""

exec python services/gradesync_input/main.py

