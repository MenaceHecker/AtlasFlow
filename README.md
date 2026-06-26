# AtlasFlow

![CI](https://github.com/MenaceHecker/AtlasFlow/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11-blue)
![Terraform](https://img.shields.io/badge/terraform-1.6-purple)

AtlasFlow is an event-driven backend built as a local-first monorepo. The whole stack runs on the machine with LocalStack and Terraform, so you don't need a real AWS account to develop or test against it.

I built this to get hands-on with the patterns that show up in real event-driven systems: idempotent ingestion, at-least-once delivery, optimistic locking, dead-letter queues, payload offload, Prometheus metrics, and structured observability. Everything that would run on AWS in production runs locally here.

## Architecture

```
 Client
   |
   | POST /v1/events
   v
 +-----------+        put_item        +-------------+
 | FastAPI   |----------------------->| DynamoDB    |
 | (API)     |   (payload to S3       | events table|
 +-----------+    if > 32 KB)         +-------------+
   |                       |
   |          +------------+
   |          | send_message (event_id only)
   |          v
   |    +-----------+      receive_message    +--------+
   |    |    SQS    |<------------------------| Worker |
   |    |  (events) |                         | (poller|
   |    +-----------+                         +--------+
   |          |  (on failure x5)                  |
   |          v                             fetch S3 if
   |    +-----------+                       s3_key present
   |    |    DLQ    |                             |
   |    +-----------+                       update_item
   |          |                             +-------------+
   |    POST /v1/admin/dlq/replay           | DynamoDB    |
   +--------->+                             | events table|
                                            +-------------+

 Metrics scraping:
   Prometheus <-- GET /metrics (API, port 8000)
   Prometheus <-- GET /metrics (Worker, port 9090)
```

**Request flow for a single event:**

1. Client POSTs an event to `/v1/events`
2. API validates the event type and payload shape against the per-type schema registry; unknown types and malformed payloads return `422` immediately
3. API writes the event to DynamoDB (status `CREATED`). If the payload exceeds 32 KB, it is stored in S3 and only the S3 key is written to DynamoDB
4. API enqueues a message to SQS carrying only the `event_id`
5. Worker polls SQS, fetches the full event record from DynamoDB, resolves the payload (inline or from S3), and claims it with a conditional update (`CREATED -> PROCESSING`). If two workers race on the same message, only one wins the claim
6. Worker dispatches to a typed handler based on `event.type`, then writes the result and sets status to `COMPLETED` or `FAILED`
7. SQS retries failed messages up to 5 times before routing them to the DLQ
8. An admin endpoint lets you replay DLQ messages back to the main queue

## Project layout

```
api/            FastAPI ingestion service
worker/         SQS polling worker
infra/          Terraform config (SQS, DLQ, DynamoDB, S3)
tests/          End-to-end integration tests (testcontainers + LocalStack)
scripts/        Smoke test against live LocalStack resources
```

## Prerequisites

- Docker Desktop (for LocalStack and integration tests)
- Terraform 1.5 or newer
- Python 3.11 or newer
- AWS CLI (only needed for the smoke test)

## Quickstart

**1. Copy the example env file**

```bash
cp .env.example .env
```

Set `ADMIN_API_KEY` to something random before you start. You can generate one with:

```bash
openssl rand -hex 32
```

**2. Start LocalStack**

```bash
make up
```

This starts the LocalStack container and waits until it passes its health check before returning.

**3. Provision the infrastructure**

```bash
make infra
```

Runs `terraform apply` against LocalStack and creates the SQS queue, dead-letter queue, events table, idempotency table, status index, S3 bucket, and TTL config.

**4. Start the API and worker**

```bash
docker compose up api worker
```

The API is available at `http://localhost:8000`. The worker starts polling immediately. Worker Prometheus metrics are exposed on `:9090`.

**5. Post an event**

```bash
curl -X POST http://localhost:8000/v1/events \
  -H "Content-Type: application/json" \
  -d '{"type": "ping", "payload": {}}'
```

**6. Check the event status**

```bash
curl http://localhost:8000/v1/events/<event_id>
```

## Event types

The API validates both the event type and the payload shape at ingestion. Unknown types return `422` immediately.

| Type | Description | Required payload fields |
|------|-------------|------------------------|
| `ping` | Health-check / smoke-test — any payload accepted | none |
| `data.transform` | Apply a transformation to a set of string fields | `fields` (dict), `operation` (`uppercase` \| `lowercase` \| `reverse`) |
| `notify` | Simulate sending an outbound notification | `channel`, `recipient`, `message` |

## Event lifecycle

```
CREATED -> PROCESSING -> COMPLETED
                      -> FAILED
```

Failed events are retried up to 5 times before SQS routes them to the dead-letter queue. You can replay them at any time with the admin endpoint.

## API reference

All routes are prefixed with `/v1`. The full interactive docs are at `http://localhost:8000/docs` when the API is running.

### Events

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/v1/events` | Ingest a new event |
| `GET` | `/v1/events/{event_id}` | Fetch a single event by ID |
| `GET` | `/v1/events` | List events with optional filtering and pagination |

**Idempotency**

Pass an `Idempotency-Key` header on POST to deduplicate requests. Sending the same key twice returns the original event ID without creating a duplicate.

**Listing and pagination**

```
GET /v1/events?status=CREATED&limit=25&next_token=<token>
```

`status` accepts `CREATED`, `PROCESSING`, `COMPLETED`, or `FAILED`. `next_token` is the cursor returned in each response for the next page.

### Admin

Admin endpoints require an `X-Admin-Key` header matching the `ADMIN_API_KEY` environment variable. If the variable is not set, the endpoints return `503`.

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

### Metrics

```
GET /metrics              # API (port 8000) — Prometheus text format
GET http://localhost:9090/metrics  # Worker — Prometheus text format
```

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `atlasflow_events_ingested_total` | Counter | `event_type` | New events accepted by the API |
| `atlasflow_api_request_duration_seconds` | Histogram | `method`, `path`, `status_code` | API request latency |
| `atlasflow_worker_messages_processed_total` | Counter | `event_type`, `outcome` | Worker processing outcomes (`completed`, `failed`, `skipped`) |
| `atlasflow_worker_processing_duration_seconds` | Histogram | `event_type` | End-to-end worker processing latency |

## Running tests

### Unit tests (no Docker required)

Tests use `moto` to mock AWS in-process.

```bash
make test          # both API and worker
make test-api      # API only
make test-worker   # worker only
```

### Integration tests (Docker required)

Spins up a real LocalStack container via `testcontainers-python` and exercises the full pipeline end-to-end.

```bash
make test-integration
```

Covers: full event pipeline (ping / data.transform / notify), DLQ replay, idempotency, and schema validation — all against real DynamoDB and SQS.

## Make targets

```
make up                Start LocalStack
make down              Stop LocalStack
make infra             Provision infrastructure with Terraform
make infra-destroy     Tear down Terraform resources
make smoke             Run a smoke test against live LocalStack resources
make test              Run all unit tests (no Docker needed)
make test-api          Run only API unit tests
make test-worker       Run only worker unit tests
make test-integration  Run end-to-end integration tests (Docker required)
make logs              Tail LocalStack logs
make api-logs          Tail API container logs
make worker-logs       Tail worker container logs
make clean             Stop containers and destroy infra
```

## Design decisions

These are the choices I made intentionally, and the reasoning behind each one.

**SQS messages carry only `event_id`**

The message body is just `{"event_id": "..."}`. The actual payload lives in DynamoDB. This keeps messages small regardless of payload size, avoids SQS's 256 KB message limit as a concern, and makes it easy to enrich or correct the event in DynamoDB independently of what's already on the queue.

**Conditional update for claiming events**

When the worker picks up a message, it transitions the event from `CREATED` to `PROCESSING` using a DynamoDB conditional expression. If two worker instances race on the same message (which can happen with at-least-once delivery), only one wins the write. The other detects the failure and skips the message cleanly instead of double-processing it.

**Separate idempotency table with TTL**

Idempotency keys live in their own table with a 60-minute TTL rather than being embedded in the events table. This keeps the events table's schema clean and means the idempotency records expire automatically without a cleanup job. The put-if-not-exists write is atomic, and if the downstream enqueue fails after the key is written, the key is deleted so the caller can retry safely.

**DLQ replay resets event status atomically**

The replay endpoint resets each event from `FAILED` back to `CREATED` using a conditional update before re-enqueueing it. This means you can't accidentally replay an event that's already being processed, and the status in DynamoDB stays consistent with what's on the queue.

**Per-type schema validation at the API boundary**

Each event type registers a Pydantic payload schema. The API validates both the type (unknown types → `422`) and the payload shape before writing anything to DynamoDB. This means malformed events are rejected at the boundary with a clear error rather than silently hitting the worker's fallback handler.

**S3 offload for large payloads**

If an event payload exceeds 32 KB, the API stores it in S3 and writes only the S3 key to DynamoDB. The worker detects the `s3_key` field and fetches the payload before dispatch. This keeps DynamoDB items well under the 400 KB limit regardless of payload size.

**Custom Prometheus registry per service**

Both the API and worker define metrics against a `CollectorRegistry` instance rather than the global default. This avoids conflicts when both packages are loaded in the same Python process (e.g., during integration tests) and makes each service's metrics namespace independent.

**Structured JSON logging throughout**

Both the API and worker emit JSON log lines with fields like `event_id`, `event_type`, `handler`, `duration_ms`, and `total_duration_ms`. This makes it straightforward to filter by event ID across both services in any log aggregator, and `duration_ms` lets you spot slow handlers without adding separate instrumentation.
