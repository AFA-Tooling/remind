#!/bin/bash
# deploy_job.sh — One-shot deploy script for the AutoRemind Cloud Run Job.
#
# Usage: bash deploy_job.sh
#
# What this does:
#   1. Configures gcloud project
#   2. Enables required GCP APIs
#   3. Creates secrets in Secret Manager (idempotent — skips existing)
#   4. Builds & pushes the Docker image via Cloud Build
#   5. Creates/updates the Cloud Run Job
#   6. Creates/updates the Cloud Scheduler rule (daily, 9:00 AM Pacific)
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (run `gcloud auth login` first)
#   - Docker installed locally
#   - All secret source files present:
#       services/config/oauth_client_secret.json
#       services/config/service_account.json
#       services/config/token.json           ← must exist (run setup_oauth.py first)
#       .env.local                            ← contains env-var secrets

set -e

# Pass --refresh-secrets to force uploading new secret versions even if they exist.
REFRESH_SECRETS=false
for arg in "$@"; do
    [[ "$arg" == "--refresh-secrets" ]] && REFRESH_SECRETS=true
done

# ─── Configuration ────────────────────────────────────────────────────────────
PROJECT_ID="autoremind-480200"
REGION="us-central1"
JOB_NAME="autoremind-daily-job"
IMAGE="gcr.io/${PROJECT_ID}/autoremind-job"

# Cloud Scheduler: 9:00 AM Pacific Time = 17:00 UTC
# (UTC-8 in winter / PST; Cloud Scheduler uses UTC)
# Use America/Los_Angeles as the timezone so it adjusts for DST automatically
SCHEDULE="0 9 * * *"
SCHEDULE_TIMEZONE="America/Los_Angeles"

# ─── Helpers ──────────────────────────────────────────────────────────────────
info()    { echo -e "\n\033[1;34m▶ $*\033[0m"; }
success() { echo -e "\033[0;32m  ✓ $*\033[0m"; }
warn()    { echo -e "\033[0;33m  ⚠ $*\033[0m"; }

secret_exists() {
    gcloud secrets describe "$1" --project="$PROJECT_ID" &>/dev/null
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

create_or_update_secret_from_value() {
    local NAME="$1"
    local VALUE="$2"

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

# ─── 0. Sanity checks ─────────────────────────────────────────────────────────
info "Pre-flight checks"

REQUIRED_FILES=(
    "services/config/oauth_client_secret.json"
    "services/config/service_account.json"
    "services/config/token.json"
    ".env.local"
    "Dockerfile.job"
    "run_job.sh"
)
for f in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$f" ]; then
        echo "  ✗ ERROR: Missing required file: $f"
        if [ "$f" = "services/config/token.json" ]; then
            echo "    → Run: python services/email-service/setup_oauth.py"
        fi
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
    cloudscheduler.googleapis.com \
    secretmanager.googleapis.com \
    cloudbuild.googleapis.com \
    containerregistry.googleapis.com \
    --project="$PROJECT_ID" \
    --quiet
success "APIs enabled"

# ─── 3. Create / update secrets ───────────────────────────────────────────────
info "Uploading secrets to Secret Manager"

# Load .env.local
set -a
# shellcheck disable=SC1091
source .env.local
set +a

# JSON file secrets
create_or_update_secret_from_file "oauth_client_secret" "services/config/oauth_client_secret.json"
create_or_update_secret_from_file "service_account"     "services/config/service_account.json"
create_or_update_secret_from_file "gmail_token"         "services/config/token.json"

# Env-var secrets
create_or_update_secret_from_value "SUPABASE_URL"              "$SUPABASE_URL"
create_or_update_secret_from_value "SUPABASE_ANON_KEY"         "$SUPABASE_ANON_KEY"
create_or_update_secret_from_value "SUPABASE_SERVICE_ROLE_KEY" "$SUPABASE_SERVICE_ROLE_KEY"
create_or_update_secret_from_value "DISCORD_BOT_TOKEN"         "$DISCORD_BOT_TOKEN"
create_or_update_secret_from_value "DISCORD_CHANNEL_ID"        "$DISCORD_CHANNEL_ID"
create_or_update_secret_from_value "DISCORD_PUBLIC_KEY"        "$DISCORD_PUBLIC_KEY"
create_or_update_secret_from_value "DISCORD_GUILD_ID"          "$DISCORD_GUILD_ID"

# ─── 4. Build & push the Docker image ─────────────────────────────────────────
info "Building & pushing Docker image: $IMAGE"
gcloud builds submit \
    --config cloudbuild.job.yaml \
    --substitutions "_IMAGE=${IMAGE}:latest" \
    --project="$PROJECT_ID" \
    .
success "Image pushed: $IMAGE:latest"

# ─── 5. Get the Cloud Run service agent email ──────────────────────────────────
info "Fetching Cloud Run service account"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")
# Cloud Run Jobs execute as the Compute Engine default service account by default
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
success "Service account: $SERVICE_ACCOUNT"

# Grant the service account access to all secrets
info "Granting secret access to Cloud Run service account"
SECRETS=(
    oauth_client_secret service_account gmail_token
    SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY
    DISCORD_BOT_TOKEN DISCORD_CHANNEL_ID DISCORD_PUBLIC_KEY DISCORD_GUILD_ID
)
for SECRET in "${SECRETS[@]}"; do
    gcloud secrets add-iam-policy-binding "$SECRET" \
        --member="serviceAccount:${SERVICE_ACCOUNT}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" \
        --quiet
done
success "Secret access granted"

# ─── 6. Create / update the Cloud Run Job ─────────────────────────────────────
info "Deploying Cloud Run Job: $JOB_NAME"

# --set-secrets handles both env vars and file mounts:
#   ENV_VAR=SECRET_NAME:version          → injected as environment variable
#   /path/to/file=SECRET_NAME:version    → written as a file at that path
#
# File secrets land at the exact path specified (no subdirectory).
ALL_SECRETS=(
    # Env-var secrets
    "SUPABASE_URL=SUPABASE_URL:latest"
    "SUPABASE_ANON_KEY=SUPABASE_ANON_KEY:latest"
    "SUPABASE_SERVICE_ROLE_KEY=SUPABASE_SERVICE_ROLE_KEY:latest"
    "DISCORD_BOT_TOKEN=DISCORD_BOT_TOKEN:latest"
    "DISCORD_CHANNEL_ID=DISCORD_CHANNEL_ID:latest"
    "DISCORD_PUBLIC_KEY=DISCORD_PUBLIC_KEY:latest"
    "DISCORD_GUILD_ID=DISCORD_GUILD_ID:latest"
    # File-mounted secrets — each in its own subdirectory
    # (Cloud Run only allows one secret mounted per directory)
    "/secrets/oauth/oauth_client_secret.json=oauth_client_secret:latest"
    "/secrets/sa/service_account.json=service_account:latest"
    "/secrets/gmail/token.json=gmail_token:latest"
)

ALL_SECRETS_STR=$(printf "%s," "${ALL_SECRETS[@]}" | sed 's/,$//')

gcloud run jobs deploy "$JOB_NAME" \
    --image "$IMAGE:latest" \
    --region "$REGION" \
    --task-timeout 30m \
    --max-retries 1 \
    --set-secrets "$ALL_SECRETS_STR" \
    --project="$PROJECT_ID" \
    --quiet

success "Cloud Run Job deployed: $JOB_NAME"

# ─── 7. Grant Cloud Scheduler permission to invoke the job ─────────────────────
info "Setting up Cloud Scheduler invoker permissions"
SCHEDULER_SA="autoremind-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

# Create a dedicated SA for the scheduler (if it doesn't exist)
if ! gcloud iam service-accounts describe "$SCHEDULER_SA" --project="$PROJECT_ID" &>/dev/null; then
    gcloud iam service-accounts create autoremind-scheduler \
        --display-name="AutoRemind Scheduler SA" \
        --project="$PROJECT_ID" \
        --quiet
    success "Created scheduler service account: $SCHEDULER_SA"
fi

# Grant it permission to run jobs
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${SCHEDULER_SA}" \
    --role="roles/run.invoker" \
    --quiet
success "Invoker role granted to scheduler SA"

# ─── 8. Create / update the Cloud Scheduler job ───────────────────────────────
info "Configuring Cloud Scheduler (9:00 AM $SCHEDULE_TIMEZONE daily)"

JOB_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"

if gcloud scheduler jobs describe "$JOB_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    gcloud scheduler jobs update http "$JOB_NAME" \
        --location="$REGION" \
        --schedule="$SCHEDULE" \
        --time-zone="$SCHEDULE_TIMEZONE" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="$SCHEDULER_SA" \
        --project="$PROJECT_ID" \
        --quiet
    success "Cloud Scheduler job updated"
else
    gcloud scheduler jobs create http "$JOB_NAME" \
        --location="$REGION" \
        --schedule="$SCHEDULE" \
        --time-zone="$SCHEDULE_TIMEZONE" \
        --uri="$JOB_URI" \
        --http-method=POST \
        --oauth-service-account-email="$SCHEDULER_SA" \
        --project="$PROJECT_ID" \
        --quiet
    success "Cloud Scheduler job created"
fi

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "\033[1;32m✅ Deployment complete!\033[0m"
echo ""
echo "  Cloud Run Job:    $JOB_NAME  ($REGION)"
echo "  Schedule:         $SCHEDULE ($SCHEDULE_TIMEZONE) = 9:00 AM daily"
echo ""
echo "  To trigger manually:"
echo "    gcloud run jobs execute $JOB_NAME --region $REGION"
echo ""
echo "  To stream logs:"
echo "    gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=$JOB_NAME' --limit=50 --format=json | jq -r '.[].jsonPayload.message'"
echo ""
