#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# scripts/deploy_cloud_run.sh
# Deploys the AI Briefing Agent to Google Cloud Run Jobs
# 
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - Docker installed
#   - All secrets uploaded to Secret Manager (see script comments)
#
# Usage:
#   chmod +x scripts/deploy_cloud_run.sh
#   ./scripts/deploy_cloud_run.sh
# ══════════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID env var}"
REGION="${GCP_REGION:-asia-south1}"           # Mumbai - closest to IST users
SERVICE_ACCOUNT="briefing-agent@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE_NAME="gcr.io/${PROJECT_ID}/ai-briefing-agent"
JOB_NAME="ai-daily-briefing"
SCHEDULER_JOB_NAME="ai-briefing-trigger"

echo "🚀 Deploying AI Briefing Agent to Cloud Run"
echo "   Project: ${PROJECT_ID}"
echo "   Region:  ${REGION}"
echo ""

# ── Step 1: Enable required APIs ──────────────────────────────────────────────
echo "📡 Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  gmail.googleapis.com \
  calendar-json.googleapis.com \
  --project="${PROJECT_ID}"

# ── Step 2: Create service account ────────────────────────────────────────────
echo "👤 Creating service account..."
gcloud iam service-accounts create briefing-agent \
  --display-name="AI Briefing Agent" \
  --project="${PROJECT_ID}" 2>/dev/null || echo "Service account already exists."

# Grant Secret Manager access
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/secretmanager.secretAccessor"

# ── Step 3: Upload secrets to Secret Manager ───────────────────────────────────
echo "🔐 Uploading secrets to Secret Manager..."
echo "   (Skipping if already exist - update manually if needed)"

_create_secret() {
  local name=$1
  local value=$2
  if ! gcloud secrets describe "${name}" --project="${PROJECT_ID}" &>/dev/null; then
    echo "${value}" | gcloud secrets create "${name}" \
      --data-file=- \
      --replication-policy=automatic \
      --project="${PROJECT_ID}"
    echo "   Created secret: ${name}"
  else
    echo "   Secret exists: ${name} (skipping)"
  fi
}

# You must set these env vars before running this script:
_create_secret "GEMINI_API_KEY" "${GEMINI_API_KEY:?}"
_create_secret "TELEGRAM_BOT_TOKEN" "${TELEGRAM_BOT_TOKEN:?}"
_create_secret "TELEGRAM_CHAT_ID" "${TELEGRAM_CHAT_ID:?}"
_create_secret "GOOGLE_TOKEN_JSON" "$(cat config/token.json | base64 -w 0)"
_create_secret "GOOGLE_CREDENTIALS_JSON" "$(cat config/credentials.json | base64 -w 0)"

# ── Step 4: Build and push Docker image ───────────────────────────────────────
echo "🐳 Building Docker image..."
docker build -t "${IMAGE_NAME}:latest" .

echo "📤 Pushing image to Container Registry..."
docker push "${IMAGE_NAME}:latest"

# ── Step 5: Deploy as Cloud Run Job ───────────────────────────────────────────
echo "☁️  Deploying Cloud Run Job..."
gcloud run jobs create "${JOB_NAME}" \
  --image="${IMAGE_NAME}:latest" \
  --region="${REGION}" \
  --service-account="${SERVICE_ACCOUNT}" \
  --task-timeout=300 \
  --max-retries=2 \
  --set-env-vars="ENVIRONMENT=production,LOG_LEVEL=INFO,TIMEZONE=Asia/Kolkata" \
  --set-secrets="GEMINI_API_KEY=GEMINI_API_KEY:latest" \
  --set-secrets="TELEGRAM_BOT_TOKEN=TELEGRAM_BOT_TOKEN:latest" \
  --set-secrets="TELEGRAM_CHAT_ID=TELEGRAM_CHAT_ID:latest" \
  --set-secrets="GOOGLE_TOKEN_JSON=GOOGLE_TOKEN_JSON:latest" \
  --set-secrets="GOOGLE_CREDENTIALS_JSON=GOOGLE_CREDENTIALS_JSON:latest" \
  --project="${PROJECT_ID}" 2>/dev/null || \
gcloud run jobs update "${JOB_NAME}" \
  --image="${IMAGE_NAME}:latest" \
  --region="${REGION}" \
  --project="${PROJECT_ID}"

echo "✅ Cloud Run Job deployed: ${JOB_NAME}"

# ── Step 6: Set up Cloud Scheduler ────────────────────────────────────────────
echo "⏰ Setting up Cloud Scheduler (7:00 AM IST daily)..."
gcloud scheduler jobs create http "${SCHEDULER_JOB_NAME}" \
  --location="${REGION}" \
  --schedule="30 1 * * *" \
  --time-zone="UTC" \
  --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
  --http-method=POST \
  --oauth-service-account-email="${SERVICE_ACCOUNT}" \
  --project="${PROJECT_ID}" 2>/dev/null || \
gcloud scheduler jobs update http "${SCHEDULER_JOB_NAME}" \
  --location="${REGION}" \
  --schedule="30 1 * * *" \
  --project="${PROJECT_ID}"

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📋 Next steps:"
echo "   Test manually: gcloud run jobs execute ${JOB_NAME} --region=${REGION}"
echo "   View logs:     gcloud run jobs executions list --job=${JOB_NAME} --region=${REGION}"
echo "   Scheduler:     gcloud scheduler jobs list --location=${REGION}"
