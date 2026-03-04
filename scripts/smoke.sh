#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${LOCALSTACK_ENDPOINT:-http://127.0.0.1:4566}"
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${TF_VAR_project_name:-atlasflow}"

if ! command -v aws >/dev/null 2>&1; then
  echo "aws CLI not found. Install awscli, then re-run."
  exit 1
fi

echo "==> LocalStack endpoint: $ENDPOINT"

# Fetch Terraform outputs
if [ ! -f "infra/terraform.tfstate" ]; then
  echo "Terraform state not found. Run: make infra"
  exit 1
fi

BUCKET=$(cd infra && terraform output -raw s3_payload_bucket)
QUEUE_URL=$(cd infra && terraform output -raw sqs_events_queue_url)
EVENTS_TABLE="${PROJECT}-events"

echo "==> Using bucket: $BUCKET"
echo "==> Using queue : $QUEUE_URL"
echo "==> Using table : $EVENTS_TABLE"

# 1) Put an object into S3
TMPFILE=$(mktemp)
echo "{\"hello\":\"atlasflow\"}" > "$TMPFILE"

aws --region "$REGION" --endpoint-url "$ENDPOINT" s3api put-object \
  --bucket "$BUCKET" \
  --key "smoke/hello.json" \
  --body "$TMPFILE" >/dev/null
echo "✅ S3 put-object OK"

# 2) Sending message to SQS
MSG_BODY="{\"event_id\":\"smoke-$(date +%s)\",\"s3_key\":\"smoke/hello.json\"}"
aws --region "$REGION" --endpoint-url "$ENDPOINT" sqs send-message \
  --queue-url "$QUEUE_URL" \
  --message-body "$MSG_BODY" >/dev/null
echo "SQS send-message OK"

# 3) Put item into DynamoDB
PK="EVENT#smoke-$(date +%s)"
aws --region "$REGION" --endpoint-url "$ENDPOINT" dynamodb put-item \
  --table-name "$EVENTS_TABLE" \
  --item "{\"pk\":{\"S\":\"$PK\"},\"status\":{\"S\":\"CREATED\"}}" >/dev/null
echo "DynamoDB put-item OK"

rm -f "$TMPFILE"

echo ""
echo "Smoke test passed: S3 + SQS + DynamoDB are wired correctly."
