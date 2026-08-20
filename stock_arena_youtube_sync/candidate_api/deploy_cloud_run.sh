#!/bin/bash
set -euo pipefail

REGION="${REGION:-asia-northeast1}"
SERVICE="${SERVICE:-stock-arena-candidate-api}"
PROJECT_ID="$(gcloud config get-value project 2>/dev/null)"

if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
  echo "gcloudのプロジェクトが未設定です。"
  exit 1
fi

BUCKET="${PROJECT_ID}-stock-arena-candidate-data"
SA_NAME="stock-arena-candidate-api"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

python3 - <<'PY'
import secrets
from pathlib import Path
p=Path(".generated_keys")
if not p.exists():
    p.write_text(
        "READ_API_KEY="+secrets.token_urlsafe(32)+"\n"+
        "WRITE_API_KEY="+secrets.token_urlsafe(32)+"\n",
        encoding="utf-8"
    )
PY

source ./.generated_keys

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com iam.googleapis.com

if ! gcloud storage buckets describe "gs://${BUCKET}" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" --location="${REGION}" --uniform-bucket-level-access
fi

if ! gcloud iam service-accounts describe "${SA_EMAIL}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" --display-name="STOCK ARENA Candidate API"
fi

gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --member="serviceAccount:${SA_EMAIL}" --role="roles/storage.objectAdmin" >/dev/null

gcloud run deploy "${SERVICE}" \
  --source . \
  --region="${REGION}" \
  --allow-unauthenticated \
  --service-account="${SA_EMAIL}" \
  --set-env-vars="DATA_BUCKET=${BUCKET},READ_API_KEY=${READ_API_KEY},WRITE_API_KEY=${WRITE_API_KEY}"

URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --format='value(status.url)')"

cat > cloud_api_credentials.txt <<EOF
CLOUD_API_URL=${URL}
READ_API_KEY=${READ_API_KEY}
WRITE_API_KEY=${WRITE_API_KEY}
EOF

echo
echo "DEPLOY COMPLETE"
echo "URL: ${URL}"
echo "認証情報: cloud_api_credentials.txt"
