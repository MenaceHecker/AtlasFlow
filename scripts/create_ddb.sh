#!/usr/bin/env bash

# Load repo env if present
if [ -f "$(dirname "$0")/../.env" ]; then
  set -a
  source "$(dirname "$0")/../.env"
  set +a
fi


set -euo pipefail

ENDPOINT="${LOCALSTACK_ENDPOINT:-http://127.0.0.1:4566}"
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${TF_VAR_project_name:-atlasflow}"

EVENTS_TABLE="${PROJECT}-events"
IDEMP_TABLE="${PROJECT}-idempotency"

echo "==> Endpoint: $ENDPOINT"
echo "==> Region  : $REGION"
echo "==> Tables  : $EVENTS_TABLE, $IDEMP_TABLE"

aws_ddb() {
  aws --region "$REGION" --endpoint-url "$ENDPOINT" dynamodb "$@"
}

exists() {
  aws_ddb describe-table --table-name "$1" >/dev/null 2>&1
}

create_events() {
  echo "==> Creating $EVENTS_TABLE"
  aws_ddb create-table \
    --table-name "$EVENTS_TABLE" \
    --attribute-definitions \
      AttributeName=pk,AttributeType=S \
      AttributeName=status,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    --global-secondary-indexes \
      "IndexName=gsi_status,KeySchema=[{AttributeName=status,KeyType=HASH}],Projection={ProjectionType=ALL}" \
    >/dev/null
}

create_idempotency() {
  echo "==> Creating $IDEMP_TABLE"
  aws_ddb create-table \
    --table-name "$IDEMP_TABLE" \
    --attribute-definitions AttributeName=pk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST \
    >/dev/null

  echo "==> Enabling TTL on $IDEMP_TABLE (attribute: ttl)"
  aws_ddb update-time-to-live \
    --table-name "$IDEMP_TABLE" \
    --time-to-live-specification "Enabled=true,AttributeName=ttl" \
    >/dev/null
}

echo "==> Current tables:"
aws_ddb list-tables | cat

if exists "$EVENTS_TABLE"; then
  echo "✅ $EVENTS_TABLE already exists"
else
  create_events
  echo "✅ Created $EVENTS_TABLE"
fi

if exists "$IDEMP_TABLE"; then
  echo "✅ $IDEMP_TABLE already exists"
else
  create_idempotency
  echo "✅ Created $IDEMP_TABLE"
fi

echo "==> Final tables:"
aws_ddb list-tables | cat

echo "🎉 DynamoDB ready."