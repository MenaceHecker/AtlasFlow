SHELL := /bin/bash

ifneq (,$(wildcard .env))
  include .env
  export
endif


.PHONY: docker-check
docker-check:
	@docker info >/dev/null 2>&1 || (echo "Docker daemon not running. Start Docker Desktop and retry." && exit 1)


PROJECT ?= atlasflow
AWS_REGION ?= us-east-1
LOCALSTACK_ENDPOINT ?= http://127.0.0.1:4566

export AWS_REGION
export AWS_DEFAULT_REGION=$(AWS_REGION)
export LOCALSTACK_ENDPOINT

.PHONY: up down logs infra infra-destroy fmt validate smoke clean help

help:
	@echo "Targets:"
	@echo "  make up            Start LocalStack"
	@echo "  make down          Stop LocalStack"
	@echo "  make logs          Tail LocalStack logs"
	@echo "  make infra         Terraform apply (LocalStack)"
	@echo "  make infra-destroy Terraform destroy (LocalStack)"
	@echo "  make validate      Terraform validate"
	@echo "  make fmt           Terraform fmt"
	@echo "  make smoke         Run smoke test (S3+SQS+DDB)"
	@echo "  make clean         Tear down + destroy infra"

up:
	@cp -n .env.example .env >/dev/null 2>&1 || true
	docker compose up -d
	@echo "Waiting for LocalStack..."
	@until curl -sf $(LOCALSTACK_ENDPOINT)/_localstack/health >/dev/null; do sleep 1; done
	@echo "LocalStack is healthy at $(LOCALSTACK_ENDPOINT)"

down:
	docker compose down

logs:
	docker compose logs -f localstack

fmt:
	cd infra && terraform fmt -recursive

validate:
	cd infra && terraform init -upgrade >/dev/null && terraform validate

infra:
	cd infra && terraform init -upgrade
	cd infra && terraform apply -auto-approve

infra-destroy:
	cd infra && terraform destroy -auto-approve

smoke:
	bash scripts/smoke.sh

ddb:
	bash scripts/create_ddb.sh

smoke: infra ddb
	bash scripts/smoke.sh

clean: down infra-destroy

api-logs:
	docker compose logs -f api

api-shell:
	docker compose exec api /bin/bash

fmt:
	terraform -chdir=infra fmt -recursive
