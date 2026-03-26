#!/bin/bash
# deploy_web.sh — One-shot deploy script for the AutoRemind web server (Cloud Run service).
#
# Usage: bash deploy_web.sh
#        bash deploy_web.sh --refresh-secrets   # Rotate secrets
#
# What this does:
#   1. Configures gcloud project
#   2. Enables required GCP APIs
#   3. Creates secrets in Secret Manager (idempotent — skips existing)
#   4. Builds & pushes the Docker image via Cloud Build
#   5. Deploys to Cloud Run service with secrets as env vars

set -e

REFRESH_SECRETS=false
for arg in "$@"; do
    [[ "$arg" == "--refresh-secrets" ]] && REFRESH_SECRETS=true
done

# ─── Configuration ────────────────────────────────────────────────────────────
PROJECT_ID="autoremind-480200"
REGION="us-central1"
SERVICE_NAME="autoremind"
IMAGE="gcr.io/${PROJECT_ID}/autoremind"

# ─── Helpers ──────────────────────────────────────────────────────────────────
info()    { echo -e "\n\033[1;34m▶ $*\033[0m"; }
success() { echo -e "\033[0;32m  ✓ $*\033[0m"; }
warn()    { echo -e "\033[0;33m  ⚠ $*\033[0m"; }

secret_exists() {
    gcloud secrets describe "$1" --project="$PROJECT_ID" &>/dev/null
}

create_or_update_secret_from_value() {
    local NAME="$1"
    local VALUE="$2"

    if [ -z "$VALUE" ]; then
        echo "  ✗ ERROR: Value for secret '$NAME' is empty. Check .env.local."
        exit 1
    fi

    if secret_exists "$NAME"; then
        if [ "$REFRESH_SECRETS" = true ]; then
            echo -n "$VALUE" | gcloud secrets versions add "$NAME" \
                --data-file=- \
                --project="$PROJECT_ID" \
                --quiet
            success "Updated secret: $NAME"
        else
            success "Skipped (already exists): $NAME"
        fi
    else
        echo -n "$VALUE" | gcloud secrets create "$NAME" \
            --data-file=- \
            --project="$PROJECT_ID" \
            --quiet
        success "Created secret: $NAME"
    fi
}

create_or_update_secret_from_file() {
    local NAME="$1"
    local FILE="$2"

    if [ ! -f "$FILE" ]; then
        echo "  ✗ ERROR: Required file not found: $FILE"
        exit 1
    fi

    if secret_exists "$NAME"; then
        if [ "$REFRESH_SECRETS" = true ]; then
            gcloud secrets versions add "$NAME" \
                --data-file="$FILE" \
                --project="$PROJECT_ID" \
                --quiet
            success "Updated secret: $NAME"
        else
            success "Skipped (already exists): $NAME"
        fi
    else
        gcloud secrets create "$NAME" \
            --data-file="$FILE" \
            --project="$PROJECT_ID" \
            --quiet
        success "Created secret: $NAME"
    fi
}

# ─── 0. Sanity checks ─────────────────────────────────────────────────────────
info "Pre-flight checks"

REQUIRED_FILES=(
    "services/config/firebase_service_account.json"
    "services/config/oauth_client_secret.json"
    "services/config/token.json"
    ".env.local"
    "Dockerfile"
)
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  ✗ ERROR: Missing required file: $f"
        exit 1
    fi
    success "Found $f"
done

# ─── 1. Set project ───────────────────────────────────────────────────────────
info "Setting gcloud project to $PROJECT_ID"
gcloud config set project "$PROJECT_ID" --quiet
success "Project set"

# ─── 2. Enable APIs ───────────────────────────────────────────────────────────
info "Enabling required GCP APIs (may take ~1 min first time)"
gcloud services enable \
    run.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com \
    --project="$PROJECT_ID" \
    --quiet
success "APIs enabled"

# ─── 3. Create / update secrets ───────────────────────────────────────────────
info "Uploading secrets to Secret Manager"

# Parse env vars from .env.local
_env_get() { grep "^${1}=" .env.local | head -1 | cut -d= -f2-; }

FIREBASE_PROJECT_ID="$(_env_get FIREBASE_PROJECT_ID)"
FIREBASE_API_KEY="$(_env_get FIREBASE_API_KEY)"
FIREBASE_AUTH_DOMAIN="$(_env_get FIREBASE_AUTH_DOMAIN)"

# FIREBASE_SERVICE_ACCOUNT_JSON is the full JSON file content as a string
FIREBASE_SERVICE_ACCOUNT_JSON=$(cat services/config/firebase_service_account.json)

# Env-var secrets
create_or_update_secret_from_value "FIREBASE_PROJECT_ID"           "$FIREBASE_PROJECT_ID"
create_or_update_secret_from_value "FIREBASE_API_KEY"              "$FIREBASE_API_KEY"
create_or_update_secret_from_value "FIREBASE_AUTH_DOMAIN"          "$FIREBASE_AUTH_DOMAIN"
create_or_update_secret_from_value "FIREBASE_SERVICE_ACCOUNT_JSON" "$FIREBASE_SERVICE_ACCOUNT_JSON"

# File-mounted secrets (for Python email service)
create_or_update_secret_from_file "oauth_client_secret"     "services/config/oauth_client_secret.json"
create_or_update_secret_from_file "firebase_service_account" "services/config/firebase_service_account.json"
create_or_update_secret_from_file "gmail_token"             "services/config/token.json"

# ─── 4. Grant secret access to Cloud Run service account ─────────────────────
info "Fetching Cloud Run service account"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
success "Service account: $COMPUTE_SA"

info "Granting secret access to Cloud Run service account"
SECRETS=(
    FIREBASE_PROJECT_ID
    FIREBASE_API_KEY
    FIREBASE_AUTH_DOMAIN
    FIREBASE_SERVICE_ACCOUNT_JSON
    oauth_client_secret
    firebase_service_account
    gmail_token
)
for SECRET in "${SECRETS[@]}"; do
    gcloud secrets add-iam-policy-binding "$SECRET" \
        --member="serviceAccount:${COMPUTE_SA}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" \
        --quiet
done
success "Secret access granted"

# ─── 5. Build & push the Docker image ────────────────────────────────────────
info "Building & pushing Docker image: $IMAGE"
gcloud builds submit \
    --config cloudbuild.yaml \
    --substitutions "SHORT_SHA=$(git rev-parse --short HEAD)" \
    --project="$PROJECT_ID" \
    .
success "Image pushed: $IMAGE:latest"

# ─── 6. Deploy Cloud Run service ─────────────────────────────────────────────
info "Deploying Cloud Run service: $SERVICE_NAME"

gcloud run deploy "$SERVICE_NAME" \
    --image "$IMAGE:latest" \
    --region "$REGION" \
    --platform managed \
    --allow-unauthenticated \
    --port 8080 \
    --set-env-vars "FIREBASE_SERVICE_ACCOUNT_PATH=/app/services/config/firebase_service_account.json" \
    --set-secrets "\
FIREBASE_PROJECT_ID=FIREBASE_PROJECT_ID:latest,\
FIREBASE_API_KEY=FIREBASE_API_KEY:latest,\
FIREBASE_AUTH_DOMAIN=FIREBASE_AUTH_DOMAIN:latest,\
FIREBASE_SERVICE_ACCOUNT_JSON=FIREBASE_SERVICE_ACCOUNT_JSON:latest,\
/secrets/oauth/oauth_client_secret.json=oauth_client_secret:latest,\
/secrets/firebase_sa/firebase_service_account.json=firebase_service_account:latest,\
/secrets/gmail/token.json=gmail_token:latest" \
    --project="$PROJECT_ID" \
    --quiet

success "Cloud Run service deployed: $SERVICE_NAME"

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "\033[1;32m✅ Web deployment complete!\033[0m"
echo ""

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
    --region "$REGION" \
    --project="$PROJECT_ID" \
    --format="value(status.url)")

echo "  Service:  $SERVICE_NAME ($REGION)"
echo "  URL:      $SERVICE_URL"
echo ""
echo "  To view logs:"
echo "    gcloud run services logs read $SERVICE_NAME --region $REGION --limit 50"
echo ""
