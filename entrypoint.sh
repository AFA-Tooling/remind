#!/bin/sh
# Link/copy mounted secrets to where settings.py expects them.
# Gracefully skip if secrets aren't mounted (e.g. local Docker run).

mkdir -p /app/services/config

echo "[entrypoint] Checking secret mounts..."
echo "[entrypoint] /secrets/ contents:" && ls -R /secrets/ 2>&1 || echo "[entrypoint] /secrets/ does not exist"

[ -f /secrets/oauth/oauth_client_secret.json ] && \
    ln -sf /secrets/oauth/oauth_client_secret.json /app/services/config/oauth_client_secret.json && \
    echo "[entrypoint] Linked oauth_client_secret.json"

[ -f /secrets/firebase_sa/firebase_service_account.json ] && \
    ln -sf /secrets/firebase_sa/firebase_service_account.json /app/services/config/firebase_service_account.json && \
    echo "[entrypoint] Linked firebase_service_account.json"

# token.json must be a writable copy so the Gmail SDK can save refreshed tokens
# Use cat instead of cp — Cloud Run secret mounts are symlinks that cp refuses to copy
[ -f /secrets/gmail/token.json ] && \
    cat /secrets/gmail/token.json > /app/services/config/token.json && \
    echo "[entrypoint] Copied token.json"

echo "[entrypoint] Config dir contents:" && ls -la /app/services/config/

exec node src/server.js
