CLUSTER_NAME    := airflow
NAMESPACE       := airflow
RELEASE_NAME    := airflow
CHART_UPSTREAM_REPO := apache-airflow
CHART_UPSTREAM_URL  := https://airflow.apache.org
# Chart is mirrored to Docker Hub as an OCI artifact (see chart-push) so
# `deploy` doesn't depend on the upstream chart repo being reachable. Bump
# CHART_VERSION and re-run `make chart-push` to pick up a new chart release.
CHART_OCI_NAMESPACE := oci://registry-1.docker.io/isliao613
CHART_OCI_REPO      := $(CHART_OCI_NAMESPACE)/airflow
CHART_VERSION   := 1.22.0
AIRFLOW_VERSION := 3.3.0
# Bump the revision suffix (.1, .2, ...) each time the Dockerfile picks up a
# new CVE fix, and update the matching image line in values.yaml to match.
IMAGE           := isliao613/airflow:3.3.0-hardened.1
KIND_CONFIG     := kind-config.yaml
VALUES_FILE     := values.yaml

.PHONY: up down build load push deploy cluster cluster-down status ui logs clean chart-pull chart-push

up: cluster deploy ## Create the kind cluster and deploy Airflow (one-click)

down: clean ## Alias for clean

cluster: ## Create the kind cluster
	@if kind get clusters | grep -qx "$(CLUSTER_NAME)"; then \
		echo "kind cluster '$(CLUSTER_NAME)' already exists"; \
	else \
		kind create cluster --config $(KIND_CONFIG); \
	fi

cluster-down: ## Delete the kind cluster
	kind delete cluster --name $(CLUSTER_NAME)

build: ## Build the CVE-hardened Airflow image
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

deploy: load ## Build, load, and install/upgrade Airflow via Helm (chart from Docker Hub OCI mirror)
	kubectl create namespace $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -
	# Note: no `--wait` here. The chart's DB-migration job is a post-install
	# hook, but Helm's `--wait` blocks on the main Deployments/StatefulSets
	# becoming Ready *before* running post-install hooks. Those pods'
	# init-containers wait on the migration job to finish first, so
	# `--wait` deadlocks. We wait explicitly afterward instead, once the
	# migration hook has actually run.
	helm upgrade --install $(RELEASE_NAME) $(CHART_OCI_REPO) \
		--namespace $(NAMESPACE) \
		--version $(CHART_VERSION) \
		-f $(VALUES_FILE) \
		--timeout 15m
	kubectl rollout status deployment/$(RELEASE_NAME)-api-server -n $(NAMESPACE) --timeout=5m
	kubectl rollout status deployment/$(RELEASE_NAME)-scheduler -n $(NAMESPACE) --timeout=5m
	kubectl rollout status deployment/$(RELEASE_NAME)-dag-processor -n $(NAMESPACE) --timeout=5m
	kubectl rollout status statefulset/$(RELEASE_NAME)-triggerer -n $(NAMESPACE) --timeout=5m
	kubectl rollout status statefulset/$(RELEASE_NAME)-worker -n $(NAMESPACE) --timeout=5m
	@echo ""
	@echo "Airflow $(AIRFLOW_VERSION) is up. UI: http://localhost:8080 (admin/admin)"

status: ## Show pod status
	kubectl get pods -n $(NAMESPACE)

logs: ## Tail scheduler logs
	kubectl logs -n $(NAMESPACE) -l component=scheduler -f --tail=100

ui: ## Print the UI URL
	@echo "http://localhost:8080"

clean: ## Uninstall Airflow and delete the kind cluster
	helm uninstall $(RELEASE_NAME) --namespace $(NAMESPACE) --ignore-not-found
	kind delete cluster --name $(CLUSTER_NAME)
