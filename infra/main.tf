locals {
  name = var.project_name
}

resource "random_id" "suffix" {
  byte_length = 3
}

# --- S3 (payloads/results) ---
resource "aws_s3_bucket" "payloads" {
  bucket        = "${local.name}-payloads-${random_id.suffix.hex}"
  force_destroy = true
}

# LocalStack sometimes expects this for path-style access
resource "aws_s3_bucket_public_access_block" "payloads" {
  bucket                  = aws_s3_bucket.payloads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --- SQS and DLQ ---
resource "aws_sqs_queue" "dlq" {
  name                      = "${local.name}-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "events" {
  name                       = "${local.name}-events"
  visibility_timeout_seconds = 30

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

# --- DynamoDB (events and idempotency) ---
resource "aws_dynamodb_table" "events" {
  name         = "${local.name}-events"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  # Useful query dimensions later 
  attribute {
    name = "status"
    type = "S"
  }

  global_secondary_index {
    name            = "gsi_status"
    hash_key        = "status"
    projection_type = "ALL"
  }
}

resource "aws_dynamodb_table" "idempotency" {
  name         = "${local.name}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}
