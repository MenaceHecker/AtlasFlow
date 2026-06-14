# AtlasFlow

AtlasFlow is an event-driven backend platform built as a local-first monorepo. The whole stack runs on your machine using LocalStack and Terraform, so you do not need a real AWS account. It is a good starting point for learning or prototyping event-driven architectures before deploying to the cloud.

## How it works

When a client posts an event to the API, the event gets saved to DynamoDB and a message is placed on an SQS queue. A background worker polls that queue, claims each message with a conditional DynamoDB update to prevent double-processing, does its work, and marks the event as completed or failed. A dead-letter queue catches anything that fails too many times. An admin endpoint lets you replay those messages back to the main queue when you are ready.

## Project layout

```
api/        FastAPI ingestion service (Python)
worker/     SQS polling worker (Python)
infra/      Terraform config for S3, SQS, DLQ, and DynamoDB
scripts/    Smoke test against live LocalStack resources
```

## Prerequisites

- Docker Desktop (for LocalStack)
- Terraform 1.5 or newer
- Python 3.11 or newer
- AWS CLI (only needed for the smoke test)

## Quickstart

**1. Copy the example env file and fill in your values**

```bash
cp .env.example .env
```

At minimum, set `ADMIN_API_KEY` to something random before starting. You can generate one with:

```bash
openssl rand -hex 32
```

**2. Start LocalStack**

```bash
make up
```

This starts the LocalStack container and waits until it is healthy before returning.

**3. Provision the infrastructure**

```bash
make infra
```

This runs `terraform apply` against LocalStack and creates the S3 bucket, SQS queue, dead-letter queue, events table, idempotency table, status index, and idempotency TTL configuration.

If you used an older checkout where `scripts/create_ddb.sh` created the tables, import them once before running `make infra`:

```bash
terraform -chdir=infra import aws_dynamodb_table.events atlasflow-events
terraform -chdir=infra import aws_dynamodb_table.idempotency atlasflow-idempotency
```

**4. Start the API and worker**

```bash
docker compose up api worker
```

The API is available at `http://localhost:8000`. The worker starts polling the queue immediately.

**5. Post an event**

```bash
curl -X POST http://localhost:8000/v1/events \
  -H "Content-Type: application/json" \
  -d '{"type": "order.placed", "payload": {"amount": 42}}'
```

**6. Check the event status**

```bash
curl http://localhost:8000/v1/events/<event_id>
```

## API reference

All routes are prefixed with `/v1`.

### Events

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/events` | Ingest a new event |
| `GET` | `/v1/events/{event_id}` | Fetch a single event by ID |
| `GET` | `/v1/events` | List events with optional filtering and pagination |

**Idempotency**

Pass an `Idempotency-Key` header on POST to deduplicate requests. If you send the same key twice, the second call returns the original event ID without creating a new event.

**Listing and pagination**

```
GET /v1/events?status=CREATED&limit=25&next_token=<token>
```

`status` can be `CREATED`, `PROCESSING`, `COMPLETED`, or `FAILED`. `next_token` is the pagination cursor returned in each response.

### Admin

Admin endpoints require an `X-Admin-Key` header that matches the `ADMIN_API_KEY` environment variable. If the variable is not set, all admin endpoints return `503`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/admin/dlq/replay` | Move messages from the DLQ back to the main queue |

```bash
curl -X POST "http://localhost:8000/v1/admin/dlq/replay?max_messages=10" \
  -H "X-Admin-Key: <your-admin-key>"
```

### Health check

```
GET /health
```

Returns `{"ok": true}` when the API is up.

## Running tests

Tests use `moto` to mock AWS in-process. No LocalStack needed.

```bash
# API tests
.venv/bin/pytest api/tests/ -v

# Worker tests
.venv/bin/pytest worker/tests/ -v
```

Or with the Makefile, which installs dependencies automatically:

```bash
make test
```

## Make targets

```
make up              Start LocalStack
make down            Stop LocalStack
make infra           Provision infrastructure with Terraform
make infra-destroy   Tear down Terraform resources
make smoke           Run a smoke test against live LocalStack resources
make test            Run all unit tests
make logs            Tail LocalStack logs
make api-logs        Tail API container logs
make worker-logs     Tail worker container logs
make clean           Stop containers and destroy infra
```

## Event lifecycle

An event moves through these states:

```
CREATED -> PROCESSING -> COMPLETED
                      -> FAILED
```

Failed events are retried up to 5 times before SQS moves them to the dead-letter queue. The worker uses a conditional DynamoDB update when transitioning from `CREATED` to `PROCESSING`, so if two worker instances pick up the same message, only one will claim it and the other will skip it.
