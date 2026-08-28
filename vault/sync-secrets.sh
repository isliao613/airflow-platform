#!/usr/bin/env bash
#
# Reads the Airflow-side secret values seeded by vault/seed-secrets.sh back
# out of Vault (a single path, secret/airflow-platform/airflow, holding both
# the OIDC client secret and the API secret key) and materializes them:
#   - One Kubernetes Secret, `vault-airflow-secrets` (named vault-*,
#     deliberately NOT airflow-* -- see below), holding every key seeded in
#     seed-secrets.sh. The chart consumes them by reference:
#     apiSecretKeySecretName, fernetKeySecretName, data.metadataSecretName,
#     postgresql.auth.existingSecret, and the top-level `secret:` list
#     (all in chart/values.yaml) -- the same pattern the chart already uses
#     for its own secrets, just sourced from Vault instead of a literal.
#
#     `connection` is the one key whose NAME is not ours to choose: it is
#     the full metadata DSN (assembled in seed-secrets.sh) and the chart
#     looks it up by that exact name under data.metadataSecretName. With
#     PgBouncer gone, that single reference is all Airflow needs -- no
#     database credential reaches Helm as a value at all.
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
  "${KUBECTL[@]}" exec deploy/airflow-vault -- vault kv get -field="$1" secret/airflow-platform/airflow
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

OIDC_SECRET=$(get client-secret)
API_SECRET_KEY=$(get api-secret-key)
FERNET_KEY=$(get fernet-key)
METADATA_DB_PASSWORD=$(get metadata-db-password)
METADATA_CONNECTION=$(get metadata-connection)
REPLICATION_PASSWORD=$(get replication-password)
MINIO_USER=$(get minio-root-user)
MINIO_PASS=$(get minio-root-password)
MINIO_CONN=$(get minio-logging-conn)

# minio-root-user / minio-root-password are read by minio/minio.yaml (the
# MinIO Deployment and its bucket-init Job); minio-logging-conn is exposed
# to every Airflow container as AIRFLOW_CONN_MINIO_S3 (chart/values.yaml).
"${KUBECTL[@]}" create secret generic vault-airflow-secrets \
  --from-literal=client-secret="$OIDC_SECRET" \
  --from-literal=api-secret-key="$API_SECRET_KEY" \
  --from-literal=fernet-key="$FERNET_KEY" \
  --from-literal=metadata-db-password="$METADATA_DB_PASSWORD" \
  --from-literal=connection="$METADATA_CONNECTION" \
  --from-literal=replication-password="$REPLICATION_PASSWORD" \
  --from-literal=minio-root-user="$MINIO_USER" \
  --from-literal=minio-root-password="$MINIO_PASS" \
  --from-literal=minio-logging-conn="$MINIO_CONN" \
  --dry-run=client -o yaml \
  | "${KUBECTL[@]}" apply -f - >/dev/null

sed \
  -e "s|VAULT_OIDC_CLIENT_SECRET_PLACEHOLDER|$OIDC_SECRET|g" \
  "$REALM_FILE" > "$REALM_RENDERED"

echo "vault/sync-secrets.sh: synced Kubernetes Secret vault-airflow-secrets (client-secret, api-secret-key, fernet-key, metadata-db-password, connection, replication-password, minio-root-user, minio-root-password, minio-logging-conn) and rendered $REALM_RENDERED"
