#!/usr/bin/env bash
#
# Single source of truth for this repo's Airflow-side secret VALUES: the
# OIDC client secret and Airflow's own API secret key. These used to be
# hardcoded directly in chart/values.yaml and sso/realm-airflow.json; now
# those files carry placeholder tokens (or apiSecretKeySecretName / a
# `secret:` entry pointing at a Kubernetes Secret) and vault/sync-secrets.sh
# fills them in from what gets seeded here instead.
#
# Deliberately NOT in Vault: the Keycloak admin login and the four demo
# users' passwords. Those are human login credentials, not secrets Airflow
# itself needs to function, so they stay plain literals in sso/keycloak.yaml
# and sso/realm-airflow.json.
#
# Vault runs in dev mode (see vault/vault.yaml) with in-memory storage, so it
# has no state across pod restarts -- `make vault` re-runs this on every
# invocation, same as `make sso` always re-importing the Keycloak realm.
#
# Moving these into Vault changes WHERE they live, not that they're
# throwaway: every value below is still a hardcoded local-development value.
# Replace both of them before this is reachable by anyone but you.
set -euo pipefail

KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
: "${KUBE_CONTEXT:?KUBE_CONTEXT must be set}"
: "${NAMESPACE:?NAMESPACE must be set}"
KUBECTL=("$KUBECTL_BIN" --context "$KUBE_CONTEXT" --namespace "$NAMESPACE")

put() {
  local path="$1"; shift
  "${KUBECTL[@]}" exec deploy/airflow-vault -- vault kv put "secret/airflow-platform/$path" "$@" >/dev/null
}

put oidc-client client-secret="airflow-local-dev-secret"
put api-secret-key value="airflow-local-dev-api-secret-key"

echo "vault/seed-secrets.sh: seeded secret/airflow-platform/{oidc-client,api-secret-key}"
