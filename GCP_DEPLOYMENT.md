# GCP Deployment Guide for AutoRemind

This guide walks you through deploying AutoRemind to Google Cloud Platform (GCP) using Cloud Run.

## Prerequisites

1. **Google Cloud Account**: Sign up at [cloud.google.com](https://cloud.google.com)
2. **Google Cloud SDK (gcloud)**: Install from [cloud.google.com/sdk](https://cloud.google.com/sdk)
3. **Docker**: Install Docker Desktop or Docker Engine
4. **GCP Project**: Create a new project in the [GCP Console](https://console.cloud.google.com)

## Initial Setup

### 1. Install Google Cloud SDK

```bash
# macOS
brew install google-cloud-sdk

# Or download from: https://cloud.google.com/sdk/docs/install
```

### 2. Authenticate with GCP

```bash
gcloud auth login
gcloud auth application-default login
```

### 3. Set Your Project

```bash
gcloud config set project YOUR_PROJECT_ID
```

Replace `YOUR_PROJECT_ID` with your actual GCP project ID.

### 4. Enable Required APIs

```bash
# Enable Cloud Run API
gcloud services enable run.googleapis.com

# Enable Cloud Build API
gcloud services enable cloudbuild.googleapis.com

# Enable Container Registry API
gcloud services enable containerregistry.googleapis.com
```

## Environment Variables

You'll need to set environment variables in Cloud Run. These should include:

- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_ANON_KEY`: Your Supabase anonymous key
- `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role key (for API endpoints)
- `PORT`: Set automatically by Cloud Run (defaults to 8080)

## Deployment Options

### Option 1: Deploy Using Cloud Build (Recommended)

This uses the `cloudbuild.yaml` file for automated builds and deployments.

1. **Set up Cloud Build trigger** (optional, for CI/CD):
   ```bash
   gcloud builds triggers create github \
     --repo-name=YOUR_REPO \
     --repo-owner=YOUR_GITHUB_USERNAME \
     --branch-pattern="^main$" \
     --build-config=cloudbuild.yaml
   ```

2. **Manual build and deploy**:
   ```bash
   gcloud builds submit --config cloudbuild.yaml
   ```

### Option 2: Deploy Using Docker Directly

1. **Build the Docker image**:
   ```bash
   docker build -t gcr.io/YOUR_PROJECT_ID/autoremind:latest .
   ```

2. **Push to Container Registry**:
   ```bash
   docker push gcr.io/YOUR_PROJECT_ID/autoremind:latest
   ```

3. **Deploy to Cloud Run**:
   ```bash
   gcloud run deploy autoremind \
     --image gcr.io/YOUR_PROJECT_ID/autoremind:latest \
     --platform managed \
     --region us-central1 \
     --allow-unauthenticated \
     --port 8080 \
     --set-env-vars "SUPABASE_URL=your_url,SUPABASE_ANON_KEY=your_key,SUPABASE_SERVICE_ROLE_KEY=your_service_key"
   ```

### Option 3: Deploy Using gcloud run deploy (Simplest)

This builds and deploys in one command:

```bash
gcloud run deploy autoremind \
  --source . \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --set-env-vars "SUPABASE_URL=your_url,SUPABASE_ANON_KEY=your_key,SUPABASE_SERVICE_ROLE_KEY=your_service_key"
```

## Setting Environment Variables

You can set environment variables during deployment or update them later:

### During Deployment:
```bash
gcloud run deploy autoremind \
  --set-env-vars "SUPABASE_URL=your_url,SUPABASE_ANON_KEY=your_key,SUPABASE_SERVICE_ROLE_KEY=your_service_key"
```

### Update Existing Service:
```bash
gcloud run services update autoremind \
  --update-env-vars "SUPABASE_URL=your_url,SUPABASE_ANON_KEY=your_key,SUPABASE_SERVICE_ROLE_KEY=your_service_key"
```

### Using Secret Manager (Recommended for Production):

1. **Create secrets**:
   ```bash
   echo -n "your_supabase_url" | gcloud secrets create supabase-url --data-file=-
   echo -n "your_anon_key" | gcloud secrets create supabase-anon-key --data-file=-
   echo -n "your_service_key" | gcloud secrets create supabase-service-key --data-file=-
   ```

2. **Grant Cloud Run access**:
   ```bash
   gcloud secrets add-iam-policy-binding supabase-url \
     --member="serviceAccount:YOUR_SERVICE_ACCOUNT" \
     --role="roles/secretmanager.secretAccessor"
   ```

3. **Deploy with secrets**:
   ```bash
   gcloud run deploy autoremind \
     --update-secrets="SUPABASE_URL=supabase-url:latest,SUPABASE_ANON_KEY=supabase-anon-key:latest,SUPABASE_SERVICE_ROLE_KEY=supabase-service-key:latest"
   ```

## Testing Locally

Before deploying, test the Docker container locally:

```bash
# Build the image
docker build -t autoremind:local .

# Run the container
docker run -p 8080:8080 \
  -e PORT=8080 \
  -e SUPABASE_URL=your_url \
  -e SUPABASE_ANON_KEY=your_key \
  -e SUPABASE_SERVICE_ROLE_KEY=your_service_key \
  autoremind:local

# Visit http://localhost:8080
```

## Updating the Deployment

After making changes to your code:

1. **Rebuild and redeploy**:
   ```bash
   gcloud run deploy autoremind --source .
   ```

2. **Or if using Cloud Build**:
   ```bash
   gcloud builds submit --config cloudbuild.yaml
   ```

## Monitoring and Logs

### View Logs:
```bash
gcloud run services logs read autoremind --limit 50
```

### View Service Details:
```bash
gcloud run services describe autoremind
```

### View in Console:
Visit [Cloud Run Console](https://console.cloud.google.com/run) to see your service.

## Custom Domain Setup

1. **Map a custom domain**:
   ```bash
   gcloud run domain-mappings create \
     --service autoremind \
     --domain yourdomain.com \
     --region us-central1
   ```

2. **Follow DNS instructions** provided by the command output.

## Cost Optimization

- Cloud Run charges only for:
  - Request processing time
  - Memory allocated
  - CPU allocated during requests
- Free tier includes: 2 million requests/month, 360,000 GB-seconds, 180,000 vCPU-seconds
- Consider setting min instances to 0 for cost savings (cold starts may occur)

## Troubleshooting

### Container won't start:
- Check logs: `gcloud run services logs read autoremind`
- Verify environment variables are set correctly
- Ensure PORT is set to 8080

### 502 Bad Gateway:
- Check that your server is listening on the PORT environment variable
- Verify the container is healthy: `gcloud run services describe autoremind`

### Environment variables not working:
- Ensure they're set in Cloud Run: `gcloud run services describe autoremind`
- Check for typos in variable names
- Restart the service after updating env vars

## Next Steps

- Set up CI/CD with Cloud Build triggers
- Configure custom domains
- Set up monitoring and alerts
- Implement secret management for sensitive data
- Configure auto-scaling parameters

## Additional Resources

- [Cloud Run Documentation](https://cloud.google.com/run/docs)
- [Cloud Build Documentation](https://cloud.google.com/build/docs)
- [Container Registry Documentation](https://cloud.google.com/container-registry/docs)

