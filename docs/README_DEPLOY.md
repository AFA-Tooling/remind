# Google Cloud Deployment Guide for AutoRemind

This guide explains how to deploy the **AutoRemind Worker** (`services/gradesync_input/main.py`) to run daily on Google Cloud.

## Recommended Architecture

We recommend using **Cloud Run Jobs** triggered by **Cloud Scheduler**.

*   **Cloud Run Jobs**: Designed for "run-to-completion" tasks like your automation script. It spins up a container, runs the script, and shuts down when finished. You only pay for the execution time.
*   **Cloud Scheduler**: A fully managed cron job service that triggers the Cloud Run Job on a schedule (e.g., every 24 hours).
*   **Google Secret Manager**: Securely stores your API credentials (`token.json`, `credentials.json`, `.env.local`) so they aren't hardcoded in the image.

---

## 1. Prerequisites

Ensure you have:
1.  A **Google Cloud Project** created.
2.  **Billing enabled** on the project.
3.  **gcloud CLI** installed and authenticated:
    ```bash
    gcloud auth login
    gcloud config set project YOUR_PROJECT_ID
    ```
4.  **APIs Enabled**:
    ```bash
    gcloud services enable run.googleapis.com \
                           scheduler.googleapis.com \
                           secretmanager.googleapis.com \
                           cloudbuild.googleapis.com \
                           artifactregistry.googleapis.com
    ```

---

## 2. Secrets Management (Critical)

Your script relies on `services/shared/settings.py` which expects these **exact files** in `services/config/`:

| File | Purpose | Source |
|------|---------|--------|
| `token.json` | Stores your user "Access Token" (allows sending email as YOU). | **Generated locally** after you run the script once. |
| `oauth_client_secret.json` | Identifies your app to Google. | Downloaded from Google Cloud Console. |
| `service_account.json` | (Optional) Alternative for server-to-server auth. | Downloaded from Google Cloud Console. |

**Crucial Step:** You typically won't have `token.json` in your git repo (it's ignored). You must run the **one-time setup script** locally to generate it:

```bash
# Run this locally to authenticate with Gmail
python3 services/email-service/setup_oauth.py
```

This will open your browser, ask you to log in, and then save the `token.json` file to `services/config/`. Once that file exists, you can upload it to Secret Manager:

```bash
# 1. Upload .env.local
gcloud secrets create autoremind-env --data-file=.env.local

# 2. Upload Gmail Auth Files (Ensure you use the EXACT filenames)
gcloud secrets create gmail-token --data-file=services/config/token.json
gcloud secrets create gmail-client-secret --data-file=services/config/oauth_client_secret.json
```

---

## 3. Build the Docker Image

We use the same `Dockerfile` for both the web server and the worker.

```bash
# Submit build to Cloud Build
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/autoremind:latest
```

---

## 4. Deploy the Cloud Run Job

Create the job definition. We override the default `CMD` (which starts the web server) to run the Python script instead.

```bash
gcloud run jobs create autoremind-worker \
  --image gcr.io/YOUR_PROJECT_ID/autoremind:latest \
  --command python3 \
  --args services/gradesync_input/main.py \
  --region us-central1 \
  --set-secrets "/app/.env.local=autoremind-env:latest" \
  --set-secrets "/app/services/config/token.json=gmail-token:latest" \
  --set-secrets "/app/services/config/oauth_client_secret.json=gmail-client-secret:latest" \
  --max-retries 0 \
  --task-timeout 10m
```

**Explanation of Flags:**
*   `--command python3 --args ...`: Overrides the container's entrypoint to run your script.
*   `--set-secrets`: Mounts the secrets from Secret Manager *as files* inside the container at the specified paths.
    *   **Crucial:** This makes the files appear exactly where your code expects them (e.g., `/app/services/config/token.json`).
    *   Your Python code (in `services/settings` or `main.py`) simply reads the files from disk as if they were local. No code changes are needed!

---

## 5. Schedule Execution (Cloud Scheduler)

Create a scheduler job to trigger the Cloud Run Job every day at 8:00 AM.

```bash
gcloud scheduler jobs create http autoremind-daily-trigger \
  --location us-central1 \
  --schedule "0 8 * * *" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/YOUR_PROJECT_ID/jobs/autoremind-worker:run" \
  --http-method POST \
  --oauth-service-account-email YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com
```

*(Note: You'll need to grant the compute service account permission to invoke the job, or use a dedicated service account).*

---

## 6. Verification

1.  **Run Manually**:
    ```bash
    gcloud run jobs execute autoremind-worker --region us-central1
    ```
2.  **Check Logs**:
    Go to the Cloud Run console -> Jobs -> autoremind-worker -> Logs to see the output.

---

## Future Updates

When you change your code:
1.  Re-run the build command (Step 3).
2.  Update the job to use the new image (if using `:latest` tag, you technically just need to execute it, but it's safer to update the job reference):
    ```bash
    gcloud run jobs update autoremind-worker --image gcr.io/YOUR_PROJECT_ID/autoremind:latest
    ```
