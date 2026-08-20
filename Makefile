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
# Single source of truth for the image. `build`/`load` tag from these, and
# `deploy` passes them to Helm with --set, so the image that gets built and the
# one the pods actually run can't drift apart. Bump the revision suffix
# (.1, .2, ...) each time the Dockerfile picks up a new CVE fix.
IMAGE_REPO      := isliao613/airflow
IMAGE_TAG       := 3.3.0-hardened.2
IMAGE           := $(IMAGE_REPO):$(IMAGE_TAG)
KEYCLOAK_IMAGE  := keycloak/keycloak:26.7.2
KIND_CONFIG     := kind-config.yaml
VALUES_FILE     := values.yaml
REALM_FILE      := sso/realm-airflow.json
KEYCLOAK_MANIFEST := sso/keycloak.yaml
ROLES_FILE      := airflow/roles.json
# values.yaml carries a placeholder for the sidecar image so it stays free of
# hardcoded tags; `deploy` renders it from IMAGE. Done with sed rather than
# `--set apiServer.extraContainers[0].image=...` because Helm replaces list
# elements rather than merging into them, which would drop the rest of the
# container spec. Kept on disk (gitignored) as a record of what was deployed.
RENDERED_VALUES := .values.rendered.yaml

# Every kubectl/helm call is pinned to the kind cluster's context. `kind create
# cluster` switches the current context, but the "already exists" path below
# does not, so without this an existing cluster plus a current-context pointing
# somewhere else would deploy Airflow to that other cluster, silently.
KUBE_CONTEXT    := kind-$(CLUSTER_NAME)
KUBECTL         := kubectl --context $(KUBE_CONTEXT)
KUBENS          := $(KUBECTL) --namespace $(NAMESPACE)

.PHONY: up down build load push deploy cluster cluster-down namespace sso sso-perms \
        status ui logs clean chart-pull chart-push whoami

up: cluster sso deploy sso-perms ## Create the cluster, deploy Keycloak + Airflow, wire up permissions (one-click)

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

build: ## Build the CVE-hardened Airflow image (also bakes in dags/ and the SSO config)
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

sso: namespace ## Deploy Keycloak and import the airflow realm
	@# The realm travels as a ConfigMap rather than being baked into an image,
	@# so editing sso/realm-airflow.json and re-running `make sso` is enough.
	$(KUBENS) create configmap airflow-keycloak-realm \
		--from-file=realm-airflow.json=$(REALM_FILE) \
		--dry-run=client -o yaml | $(KUBECTL) apply -f -
	sed 's|KEYCLOAK_IMAGE_PLACEHOLDER|$(KEYCLOAK_IMAGE)|' $(KEYCLOAK_MANIFEST) | $(KUBECTL) apply -f -
	@# Restart on re-run so a changed realm ConfigMap is actually re-imported.
	$(KUBENS) rollout restart deployment/airflow-keycloak
	$(KUBENS) rollout status deployment/airflow-keycloak --timeout=5m

deploy: load namespace ## Build, load, and install/upgrade Airflow via Helm (chart from Docker Hub OCI mirror)
	# Note: no `--wait` here. The chart's DB-migration job is a post-install
	# hook, but Helm's `--wait` blocks on the main Deployments/StatefulSets
	# becoming Ready *before* running post-install hooks. Those pods'
	# init-containers wait on the migration job to finish first, so
	# `--wait` deadlocks. We wait explicitly afterward instead, once the
	# migration hook has actually run.
	sed 's|PLACEHOLDER_SET_FROM_MAKEFILE|$(IMAGE)|' $(VALUES_FILE) > $(RENDERED_VALUES)
	helm upgrade --install $(RELEASE_NAME) $(CHART_OCI_REPO) \
		--kube-context $(KUBE_CONTEXT) \
		--namespace $(NAMESPACE) \
		--version $(CHART_VERSION) \
		-f $(RENDERED_VALUES) \
		--set airflowVersion=$(AIRFLOW_VERSION) \
		--set defaultAirflowRepository=$(IMAGE_REPO) \
		--set defaultAirflowTag=$(IMAGE_TAG) \
		--timeout 15m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-api-server --timeout=5m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-scheduler --timeout=5m
	$(KUBENS) rollout status deployment/$(RELEASE_NAME)-dag-processor --timeout=5m
	$(KUBENS) rollout status statefulset/$(RELEASE_NAME)-triggerer --timeout=5m
	$(KUBENS) rollout status statefulset/$(RELEASE_NAME)-worker --timeout=5m

sso-perms: ## Create the team roles and apply each DAG's access_control
	@# `airflow sync-perm --include-dags` reads access_control off the DAGs
	@# serialized in the database, so the dag processor has to have parsed
	@# dags/ first. Poll for that rather than guessing a sleep duration.
	@echo "waiting for the dag processor to serialize the team DAGs..."
	@pod=$$($(KUBENS) get pod -l component=api-server -o jsonpath='{.items[0].metadata.name}'); \
	for i in $$(seq 1 60); do \
		found=$$($(KUBENS) exec $$pod -c api-server -- airflow dags list -o plain 2>/dev/null | grep -c '^team_[abc]_pipeline' || true); \
		if [ "$$found" -ge 3 ]; then echo "all 3 team DAGs serialized"; break; fi; \
		if [ "$$i" = "60" ]; then echo "ERROR: team DAGs did not appear within 5m"; exit 1; fi; \
		sleep 5; \
	done; \
	echo "creating team roles..."; \
	$(KUBENS) cp $(ROLES_FILE) $$pod:/tmp/roles.json -c api-server; \
	$(KUBENS) exec $$pod -c api-server -- airflow roles import /tmp/roles.json; \
	echo "applying per-DAG access_control..."; \
	$(KUBENS) exec $$pod -c api-server -- airflow sync-perm --include-dags
	@echo ""
	@echo "Airflow $(AIRFLOW_VERSION) is up with Keycloak SSO."
	@echo "  Airflow UI:       http://localhost:8080  (Sign in with keycloak)"
	@echo "  Keycloak console: http://localhost:8081  (admin/admin)"
	@echo ""
	@echo "  alice / alice -> airflow-team-a -> sees team_a_pipeline only"
	@echo "  bob   / bob   -> airflow-team-b -> sees team_b_pipeline only"
	@echo "  carol / carol -> airflow-team-c -> sees team_c_pipeline only"

status: ## Show pod status
	$(KUBENS) get pods

logs: ## Tail scheduler logs
	$(KUBENS) logs -l component=scheduler -f --tail=100

ui: ## Print the UI URLs
	@echo "Airflow:  http://localhost:8080"
	@echo "Keycloak: http://localhost:8081"

clean: ## Uninstall Airflow and delete the kind cluster
	@# Leading `-`: a broken or already-gone cluster must not stop the cluster
	@# delete below, which is the part that actually reclaims the resources.
	-helm uninstall $(RELEASE_NAME) --kube-context $(KUBE_CONTEXT) --namespace $(NAMESPACE) --ignore-not-found
	kind delete cluster --name $(CLUSTER_NAME)
