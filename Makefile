CLUSTER_NAME    := airflow
NAMESPACE       := airflow
RELEASE_NAME    := airflow
CHART_UPSTREAM_REPO := apache-airflow
CHART_UPSTREAM_URL  := https://airflow.apache.org
# Chart is mirrored to Docker Hub as an OCI artifact (see chart-push) so
# `deploy` doesn't depend on the upstream chart repo being reachable. Bump
# CHART_VERSION and re-run `make chart-push` to pick up a new chart release --
# then also bump the matching `version:` under `dependencies:` in
# chart/Chart.yaml and re-run `make dep-build` (deploy does this
# automatically), since that's what actually pins the version `helm upgrade`
# installs; CHART_VERSION here only drives chart-pull/chart-push.
CHART_OCI_NAMESPACE := oci://registry-1.docker.io/isliao613
CHART_OCI_REPO      := $(CHART_OCI_NAMESPACE)/airflow
CHART_VERSION   := 1.22.0
AIRFLOW_VERSION := 3.3.1
# Single source of truth for the image. `build`/`load` tag from these, and
# `deploy` renders them into the chart values (see RENDERED_VALUES below), so
# the image that gets built and the one the pods actually run can't drift
# apart. Bump the revision suffix (.1, .2, ...) each time the Dockerfile picks
# up a new CVE fix.
IMAGE_REPO      := isliao613/airflow
IMAGE_TAG       := 3.3.1-hardened.1
IMAGE           := $(IMAGE_REPO):$(IMAGE_TAG)
KEYCLOAK_IMAGE  := keycloak/keycloak:26.7.2
# Dev-mode Vault holding this repo's local secret values (see
# vault/seed-secrets.sh) instead of them being hardcoded in chart/values.yaml,
# sso/keycloak.yaml, and sso/realm-airflow.json.
VAULT_IMAGE     := hashicorp/vault:2.0.4
# Dev-mode MinIO backing Airflow remote task logging, so the Celery workers
# can run as stateless Deployments (see minio/minio.yaml and
# airflow.workers.persistence.enabled in chart/values.yaml).
MINIO_IMAGE     := minio/minio:RELEASE.2025-04-22T22-12-26Z
MC_IMAGE        := minio/mc:RELEASE.2025-04-16T18-13-26Z
KIND_CONFIG     := kind-config.yaml
# This repo's umbrella chart (wraps the airflow chart as a dependency, plus
# its own templates/ for the team-roles-job hook) lives in its own folder,
# separate from the Dockerfile/dags/sso concerns at repo root.
CHART_DIR       := chart
VALUES_FILE     := $(CHART_DIR)/values.yaml
REALM_FILE      := sso/realm-airflow.json
KEYCLOAK_MANIFEST := sso/keycloak.yaml
VAULT_MANIFEST  := vault/vault.yaml
MINIO_MANIFEST  := minio/minio.yaml
# values.yaml carries placeholders (image, version, tags) so it stays free of
# hardcoded values; `deploy` renders them all from Makefile variables in one
# sed pass. Done with sed rather than `--set` so there's exactly one place
# (this file) to look for what's actually deployed, and because the sidecar
# image specifically can't be done with `--set` -- Helm replaces list
# elements rather than merging into them, which would drop the rest of the
# container spec. Kept on disk (gitignored) as a record of what was deployed.
RENDERED_VALUES := $(CHART_DIR)/.values.rendered.yaml
# realm-airflow.json carries VAULT_*_PLACEHOLDER tokens (user passwords, OIDC
# client secret) instead of literal values; vault/sync-secrets.sh renders
# this file from what's seeded in Vault. Gitignored, regenerated every run,
# same spirit as RENDERED_VALUES above.
REALM_RENDERED  := sso/.realm-airflow.rendered.json

# Every kubectl/helm call is pinned to the kind cluster's context. `kind create
# cluster` switches the current context, but the "already exists" path below
# does not, so without this an existing cluster plus a current-context pointing
# somewhere else would deploy Airflow to that other cluster, silently.
KUBE_CONTEXT    := kind-$(CLUSTER_NAME)
KUBECTL         := kubectl --context $(KUBE_CONTEXT)
KUBENS          := $(KUBECTL) --namespace $(NAMESPACE)

.PHONY: up down build load push deploy dep-build cluster cluster-down namespace sso vault minio \
        db-failover db-failback test status ui logs clean chart-pull chart-push whoami

up: cluster sso deploy ## Create the cluster, deploy Keycloak + Airflow, wire up permissions (one-click)

down: clean ## Alias for clean

cluster: ## Create the kind cluster
	@if kind get clusters | grep -qx "$(CLUSTER_NAME)"; then \
		echo "kind cluster '$(CLUSTER_NAME)' already exists"; \
	else \
		kind create cluster --config $(KIND_CONFIG); \
	fi
	@# Refresh the kubeconfig entry even on the "already exists" path, so the
	@# $(KUBE_CONTEXT) referenced everywhere below is guaranteed to resolve.
	kind export kubeconfig --name $(CLUSTER_NAME)

cluster-down: ## Delete the kind cluster
	kind delete cluster --name $(CLUSTER_NAME)

whoami: ## Show which cluster the targets will act on
	@echo "context:   $(KUBE_CONTEXT)"
	@$(KUBECTL) config view --minify -o jsonpath='{.clusters[0].cluster.server}' 2>/dev/null && echo "" || echo "(context not found -- run 'make cluster')"

namespace: ## Ensure the airflow namespace exists
	$(KUBECTL) create namespace $(NAMESPACE) --dry-run=client -o yaml | $(KUBECTL) apply -f -

build: ## Build the CVE-hardened Airflow image (also bakes in dags/)
	docker build -t $(IMAGE) .

load: build ## Load the hardened image into the kind cluster
	kind load docker-image $(IMAGE) --name $(CLUSTER_NAME)

push: build ## Push the hardened image to the registry (run manually, not part of `up`)
	docker push $(IMAGE)

chart-pull: ## Pull the upstream apache-airflow chart package for mirroring
	helm repo add $(CHART_UPSTREAM_REPO) $(CHART_UPSTREAM_URL) >/dev/null 2>&1 || true
	helm repo update $(CHART_UPSTREAM_REPO)
	helm pull $(CHART_UPSTREAM_REPO)/airflow --version $(CHART_VERSION)

chart-push: chart-pull ## Mirror the chart to Docker Hub as an OCI artifact (run manually, not part of `up`)
	helm push airflow-$(CHART_VERSION).tgz $(CHART_OCI_NAMESPACE)
	rm -f airflow-$(CHART_VERSION).tgz

sso: namespace vault ## Deploy Keycloak and import the airflow realm
	@# The realm travels as a ConfigMap rather than being baked into an image,
	@# so editing sso/realm-airflow.json and re-running `make sso` is enough.
	@# $(REALM_RENDERED) (not $(REALM_FILE) itself) is what actually gets
	@# imported -- it's $(REALM_FILE) with its VAULT_*_PLACEHOLDER tokens
	@# (user passwords, OIDC client secret) substituted from Vault by the
	@# `vault` prerequisite above.
	$(KUBENS) create configmap airflow-keycloak-realm \
		--from-file=realm-airflow.json=$(REALM_RENDERED) \
		--dry-run=client -o yaml | $(KUBECTL) apply -f -
	sed 's|KEYCLOAK_IMAGE_PLACEHOLDER|$(KEYCLOAK_IMAGE)|' $(KEYCLOAK_MANIFEST) | $(KUBECTL) apply -f -
	@# Restart on re-run so a changed realm ConfigMap is actually re-imported.
	$(KUBENS) rollout restart deployment/airflow-keycloak
	$(KUBENS) rollout status deployment/airflow-keycloak --timeout=5m

vault: namespace ## Deploy Vault (dev mode), seed it, and sync secrets into Kubernetes Secrets + the rendered realm file
	@# Dev-mode Vault has no state across pod restarts, so seed+sync always
	@# re-run -- cheap, and necessary since `sso`/`deploy` can each run this
	@# standalone (same reasoning as both depending on `namespace`).
	sed 's|VAULT_IMAGE_PLACEHOLDER|$(VAULT_IMAGE)|' $(VAULT_MANIFEST) | $(KUBECTL) apply -f -
	$(KUBENS) rollout status deployment/airflow-vault --timeout=2m
	KUBE_CONTEXT=$(KUBE_CONTEXT) NAMESPACE=$(NAMESPACE) ./vault/seed-secrets.sh
	KUBE_CONTEXT=$(KUBE_CONTEXT) NAMESPACE=$(NAMESPACE) REALM_FILE=$(REALM_FILE) REALM_RENDERED=$(REALM_RENDERED) ./vault/sync-secrets.sh

minio: namespace vault ## Deploy dev-mode MinIO for Airflow remote task logging and (re)create the log bucket
	@# emptyDir storage, so the bucket is gone on pod restart -- the
	@# bucket-init Job re-creates it every run, same spirit as `vault`
	@# re-seeding. `vault` above materializes the minio-root-* keys the
	@# Deployment and the Job mount.
	$(KUBENS) delete job airflow-minio-mkbucket --ignore-not-found
	sed -e 's|MINIO_IMAGE_PLACEHOLDER|$(MINIO_IMAGE)|' -e 's|MC_IMAGE_PLACEHOLDER|$(MC_IMAGE)|' $(MINIO_MANIFEST) | $(KUBECTL) apply -f -
	$(KUBENS) rollout status deployment/airflow-minio --timeout=2m
	$(KUBENS) wait --for=condition=complete job/airflow-minio-mkbucket --timeout=2m

dep-build: ## Fetch the airflow chart dependency into chart/charts/ (from the Docker Hub OCI mirror)
	helm dependency build $(CHART_DIR)

db-failover: ## Manually fail the metadata DB over to the freshest read replica (break-glass; see postgres/failover.sh)
	@# PG_SUPERUSER_PASSWORD comes from the same Vault-synced Secret the
	@# cluster itself uses, so the break-glass path can't drift from it.
	KUBE_CONTEXT=$(KUBE_CONTEXT) NAMESPACE=$(NAMESPACE) \
	  PG_SUPERUSER_PASSWORD=$$($(KUBENS) get secret vault-airflow-secrets -o jsonpath='{.data.metadata-db-password}' | base64 -d) \
	  ./postgres/failover.sh

db-failback: ## Rebuild a clean primary+replicas after a failover, carrying the data over (RUN BEFORE THE NEXT deploy)
	@# Not optional: until this runs, `helm upgrade` (any `make deploy`)
	@# leaves the primary Service with zero endpoints and restarts a stale
	@# primary-0. See the comment header in postgres/failback.sh.
	KUBE_CONTEXT=$(KUBE_CONTEXT) NAMESPACE=$(NAMESPACE) RELEASE_NAME=$(RELEASE_NAME) \
	  CHART_DIR=$(CHART_DIR) VALUES=$(RENDERED_VALUES) \
	  PG_SUPERUSER_PASSWORD=$$($(KUBENS) get secret vault-airflow-secrets -o jsonpath='{.data.metadata-db-password}' | base64 -d) \
	  ./postgres/failback.sh

deploy: load namespace vault minio dep-build ## Build, load, and install/upgrade Airflow + the team-roles-job hook via Helm, as one release
	# `vault` above ensures the airflow-oidc-client-secret and
	# airflow-api-secret-key Kubernetes Secrets exist -- chart/values.yaml
	# references them via `secret:` / apiSecretKeySecretName rather than
	# literal values.
	# Note: no `--wait` here. The airflow subchart's DB-migration job is a
	# post-install hook, but Helm's `--wait` blocks on the main Deployments/
	# StatefulSets becoming Ready *before* running post-install hooks. Those
	# pods' init-containers wait on the migration job to finish first, so
	# `--wait` deadlocks. We wait explicitly afterward instead, once the
	# migration and team-roles hooks have actually run (Helm always blocks on
	# hooks regardless of --wait, so by the time this command returns, the
	# team-roles-job hook -- which creates the team roles and applies each
	# DAG's access_control -- has already completed).
	sed \
		-e 's|PLACEHOLDER_SET_FROM_MAKEFILE|$(IMAGE)|' \
		-e 's|AIRFLOW_VERSION_PLACEHOLDER|$(AIRFLOW_VERSION)|' \
		-e 's|IMAGE_REPO_PLACEHOLDER|$(IMAGE_REPO)|g' \
		-e 's|IMAGE_TAG_PLACEHOLDER|$(IMAGE_TAG)|g' \
		$(VALUES_FILE) > $(RENDERED_VALUES)
	helm upgrade --install $(RELEASE_NAME) $(CHART_DIR) \
		--kube-context $(KUBE_CONTEXT) \
		--namespace $(NAMESPACE) \
		-f $(RENDERED_VALUES) \
		--timeout 15m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-api-server --timeout=5m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-scheduler --timeout=5m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-dag-processor --timeout=5m
	$(KUBENS) rollout status statefulset/$(RELEASE_NAME)-triggerer --timeout=5m
	@# Workers are Deployments (workers.persistence.enabled: false), one per
	@# class in airflow.workers.celery.sets.
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-worker-small --timeout=5m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-worker-medium --timeout=5m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-worker-large --timeout=5m
	@echo ""
	@echo "Airflow $(AIRFLOW_VERSION) is up with Keycloak SSO."
	@echo "  Airflow UI:       http://localhost:8080  (Sign in with keycloak)"
	@echo "  Keycloak console: http://localhost:8181  (admin/admin)"
	@echo ""
	@echo "  alice / alice -> airflow-team-a -> sees team_a_pipeline only"
	@echo "  bob   / bob   -> airflow-team-b -> sees team_b_pipeline only"
	@echo "  carol / carol -> airflow-team-c -> sees team_c_pipeline only"
	@echo "  admin / admin -> airflow-admins -> sees all three (Airflow Admin)"

test: build ## Run the dags/ unit tests inside the hardened image (has Airflow 3.3.1 + the DAGs)
	@# No local Airflow needed: pytest runs in the same image the cluster runs,
	@# which already has Airflow and the DAGs at /opt/airflow/dags. tests/ is
	@# NOT in the image (the Dockerfile only COPYs dags/), so it is mounted
	@# here, along with chart/ for the roles.json / values.yaml cross-checks.
	@# Executor is set so hello_kubernetes' task-level
	@# executor="KubernetesExecutor" resolves during DAG parsing.
	docker run --rm \
		-e AIRFLOW__CORE__EXECUTOR="CeleryExecutor,KubernetesExecutor" \
		-v "$(PWD)/tests:/opt/airflow/tests:ro" \
		-v "$(PWD)/pytest.ini:/opt/airflow/pytest.ini:ro" \
		-v "$(PWD)/chart:/opt/airflow/chart:ro" \
		--entrypoint bash \
		$(IMAGE) -c "pip install --quiet --no-cache-dir 'pytest>=8,<9' && cd /opt/airflow && python -m pytest"

status: ## Show pod status
	$(KUBENS) get pods

logs: ## Tail scheduler logs
	$(KUBENS) logs -l component=scheduler -f --tail=100

ui: ## Print the UI URLs
	@echo "Airflow:  http://localhost:8080"
	@echo "Keycloak: http://localhost:8181"

clean: ## Uninstall Airflow and delete the kind cluster
	@# Leading `-`: a broken or already-gone cluster must not stop the cluster
	@# delete below, which is the part that actually reclaims the resources.
	-helm uninstall $(RELEASE_NAME) --kube-context $(KUBE_CONTEXT) --namespace $(NAMESPACE) --ignore-not-found
	kind delete cluster --name $(CLUSTER_NAME)
