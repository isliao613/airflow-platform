#!/usr/bin/env bash
#
# Single source of truth for this repo's Airflow-side secret VALUES: the
# OIDC client secret and Airflow's own API secret key, held together as one
# Vault secret (secret/airflow-platform/airflow) since both are consumed by
# the same release and there's no reason to split them into separate paths.
# These used to be hardcoded directly in chart/values.yaml and
# sso/realm-airflow.json; now those files carry a placeholder token (or
# apiSecretKeySecretName / a `secret:` entry pointing at a Kubernetes
# Secret) and vault/sync-secrets.sh fills them in from what gets seeded here
# instead.
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

# MinIO backs Airflow's remote task logging (see minio/minio.yaml). Its root
# credentials and the Airflow connection built from them live here too --
# same reasoning as the OIDC/API secrets: something Airflow's backend
# consumes to function. minio-logging-conn is a full Airflow JSON connection
# (endpoint_url + path-style addressing, which MinIO needs) exposed to every
# Airflow container as AIRFLOW_CONN_MINIO_S3 via chart/values.yaml.
MINIO_USER="airflow-logs"
MINIO_PASS="airflow-logs-local-dev-secret"
MINIO_CONN=$(cat <<EOF
{"conn_type":"aws","login":"${MINIO_USER}","password":"${MINIO_PASS}","extra":{"endpoint_url":"http://airflow-minio:9000","region_name":"us-east-1","config_kwargs":{"s3":{"addressing_style":"path"}}}}
EOF
)

# Airflow's Fernet key encrypts Connection passwords and sensitive Variables
# in the metadata DB. Must be 32 bytes, url-safe-base64-encoded -- an
# arbitrary string like the values above would be rejected. This one decodes
# to the readable "airflow-local-dev-fernet-key-32b" so it is obviously a
# local-dev value, same spirit as the literals above. Generate a real one
# with:
#   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#
# ROTATING THIS IS NOT LIKE THE OTHERS: changing it makes every already
# encrypted Connection/Variable in the database undecryptable
# (InvalidToken). Rotate via AIRFLOW__CORE__FERNET_KEY="new,old" and
# re-encrypt, not by editing this in place.
FERNET_KEY="YWlyZmxvdy1sb2NhbC1kZXYtZmVybmV0LWtleS0zMmI="

"${KUBECTL[@]}" exec deploy/airflow-vault -- vault kv put secret/airflow-platform/airflow \
  client-secret="airflow-local-dev-secret" \
  api-secret-key="airflow-local-dev-api-secret-key" \
  fernet-key="$FERNET_KEY" \
  minio-root-user="$MINIO_USER" \
  minio-root-password="$MINIO_PASS" \
  minio-logging-conn="$MINIO_CONN" >/dev/null

echo "vault/seed-secrets.sh: seeded secret/airflow-platform/airflow (client-secret, api-secret-key, fernet-key, minio-root-user, minio-root-password, minio-logging-conn)"
