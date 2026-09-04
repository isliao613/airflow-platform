# Thin wrapper over `docker compose`. Every target is one command -- run
# `docker compose ...` directly if you prefer; nothing here is load-bearing.
#
# All configuration lives in .env, which `docker compose` reads on its own; it
# is included here only so the targets below can echo the right port.
-include .env
export

COMPOSE := docker compose

.PHONY: up down build rebuild ps logs logs-scheduler shell test clean help

up: ## Build the image and start the whole stack
	$(COMPOSE) up -d --build
	@echo ""
	@echo "Airflow $(AIRFLOW_VERSION) is up (CeleryExecutor, no SSO)."
	@echo "  Airflow UI: http://localhost:$(AIRFLOW_PORT)"
	@echo ""
	@echo "  alice / alice -> team_a -> sees team_a_pipeline only"
	@echo "  bob   / bob   -> team_b -> sees team_b_pipeline only"
	@echo "  carol / carol -> team_c -> sees team_c_pipeline only"
	@echo "  admin / admin -> Admin  -> sees every DAG"

down: ## Stop and remove the containers, KEEPING the metadata DB and logs
	$(COMPOSE) down

build: ## Build the CVE-hardened image
	$(COMPOSE) build

rebuild: ## Rebuild from scratch (no layer cache -- picks up new Debian CVE fixes)
	$(COMPOSE) build --no-cache

ps: ## Show container status
	@# airflow-init and airflow-bootstrap show as "exited" -- they are one-shot.
	$(COMPOSE) ps

logs: ## Tail every service's logs
	$(COMPOSE) logs -f --tail=100

logs-scheduler: ## Tail scheduler logs
	$(COMPOSE) logs -f --tail=100 airflow-scheduler

shell: ## Open a shell in a throwaway container with the Airflow CLI
	$(COMPOSE) run --rm --no-deps airflow-scheduler bash

test: build ## Run this stack's dags/ unit tests inside its own image
	@# No local Airflow needed: pytest runs in the same image the stack runs.
	@# Unlike a baked-in-DAGs image, nothing is COPYed at build time, so dags/,
	@# tests/ and pytest.ini are all mounted here. Executor and default queue
	@# match docker-compose.yaml (conftest.py sets them too, belt and braces),
	@# so the DagBag parses these DAGs the way the containers do.
	docker run --rm \
		-e AIRFLOW__CORE__EXECUTOR="CeleryExecutor" \
		-e AIRFLOW__OPERATORS__DEFAULT_QUEUE="small" \
		-v "$(PWD)/dags:/opt/airflow/dags:ro" \
		-v "$(PWD)/tests:/opt/airflow/tests:ro" \
		-v "$(PWD)/pytest.ini:/opt/airflow/pytest.ini:ro" \
		--entrypoint bash \
		airflow-platform-compose:$(IMAGE_TAG) \
		-c "pip install --quiet --no-cache-dir 'pytest>=8,<9' && cd /opt/airflow && python -m pytest"

clean: ## Stop everything and DELETE the volumes (metadata DB + task logs)
	$(COMPOSE) down -v --remove-orphans

help: ## List targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-16s %s\n", $$1, $$2}'
