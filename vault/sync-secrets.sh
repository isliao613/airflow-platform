#!/usr/bin/env bash
#
# Reads the Airflow-side secret values seeded by vault/seed-secrets.sh back
# out of Vault and materializes them:
#   - Kubernetes Secrets (named vault-*, deliberately NOT airflow-* -- see
#     below), consumed via apiSecretKeySecretName / the top-level `secret:`
#     list (chart/values.yaml) -- the same pattern the airflow chart already
#     uses for its own metadata/fernet-key secrets, just sourced from Vault
#     instead of a literal value.
#   - $REALM_RENDERED, a copy of $REALM_FILE with its
#     VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER token substituted -- Keycloak's
#     realm import has no equivalent of secretKeyRef, so the client secret
#     has to land in the JSON itself. Gitignored and regenerated every run,
#     same spirit as chart/.values.rendered.yaml.
#
# Idempotent; safe to re-run. `make sso` and `make deploy` both depend on
# `vault` (which runs this), since either can be run standalone without
# `make up` -- same reasoning as both depending on `namespace`.
set -euo pipefail

KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
: "${KUBE_CONTEXT:?KUBE_CONTEXT must be set}"
: "${NAMESPACE:?NAMESPACE must be set}"
: "${REALM_FILE:?REALM_FILE must be set}"
: "${REALM_RENDERED:?REALM_RENDERED must be set}"
KUBECTL=("$KUBECTL_BIN" --context "$KUBE_CONTEXT" --namespace "$NAMESPACE")

get() {
  "${KUBECTL[@]}" exec deploy/airflow-vault -- vault kv get -field="$2" "secret/airflow-platform/$1"
}

apply_secret() {
  local name="$1"; shift
  "${KUBECTL[@]}" create secret generic "$name" "$@" --dry-run=client -o yaml \
    | "${KUBECTL[@]}" apply -f - >/dev/null
}

# Named `vault-*`, NOT `airflow-*`: the airflow chart's own release name is
# "airflow", so a Secret named e.g. `airflow-api-secret-key` collides with
# the name the chart's api-secret-key-secret.yaml template would render if
# apiSecretKeySecretName were ever unset. `helm upgrade` garbage-collects any
# resource that was present in the previous release's manifest but is absent
# from the new one -- so a same-named Secret we manage outside Helm can get
# swept away the moment the chart's own render of that name changes (found by
# actually hitting this: switching apiSecretKey -> apiSecretKeySecretName
# deleted the vault-synced Secret out from under the just-upgraded pods).

OIDC_SECRET=$(get oidc-client client-secret)
API_SECRET_KEY=$(get api-secret-key value)

apply_secret vault-oidc-client-secret \
  --from-literal=client-secret="$OIDC_SECRET"

apply_secret vault-api-secret-key \
  --from-literal=api-secret-key="$API_SECRET_KEY"

sed \
  -e "s|VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER|$OIDC_SECRET|g" \
  "$REALM_FILE" > "$REALM_RENDERED"

echo "vault/sync-secrets.sh: synced Kubernetes Secrets (vault-oidc-client-secret, vault-api-secret-key) and rendered $REALM_RENDERED"
