#!/usr/bin/env bash
#
# Fail BACK after postgres/failover.sh: rebuild a clean 1-primary +
# 2-replica cluster with airflow-postgresql-primary-0 as the primary again,
# carrying the data forward from the promoted replica.
#
# WHY THIS IS NOT OPTIONAL. After a failover the cluster is not merely
# degraded, it is booby-trapped: the chart still believes
# airflow-postgresql-primary-0 is the primary, so the next `helm upgrade`
# (i.e. any `make deploy`) will
#   * MERGE the chart's own selector back into the primary Service --
#     Kubernetes does not replace it -- leaving a selector that demands both
#     `component=primary` and `pod-name=<promoted replica>`, which matches
#     nothing, so the Service ends up with ZERO endpoints; and
#   * scale the fenced StatefulSet back to 1, starting a stale
#     primary-0 that CrashLoopBackOffs ("could not locate a valid
#     checkpoint record").
# Airflow keeps working for a while because PgBouncer holds established
# server connections -- the outage lands later, whenever PgBouncer
# restarts. All of the above was reproduced on a live cluster.
#
# So: run failover.sh to survive the incident, then run THIS as soon as
# practical, before the next deploy.
#
# What it does:
#   1. finds the pod that is actually writable (the promoted replica);
#   2. pg_dump's the airflow database out of it;
#   3. resets the primary Service selector to the chart's own labels;
#   4. deletes the postgres StatefulSets and their PVCs (the diverged
#      timelines are unrecoverable without pg_rewind, and this is a POC);
#   5. `helm upgrade` recreates a clean primary + 2 replicas;
#   6. restores the dump into the new primary;
#   7. restarts the Airflow tier.
#
# Usage:
#   KUBE_CONTEXT=kind-airflow NAMESPACE=airflow \
#     RELEASE_NAME=airflow CHART_DIR=chart VALUES=chart/.values.rendered.yaml \
#     ./postgres/failback.sh
set -euo pipefail

KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
HELM_BIN="${HELM_BIN:-helm}"
: "${KUBE_CONTEXT:?KUBE_CONTEXT must be set}"
: "${NAMESPACE:?NAMESPACE must be set}"
RELEASE_NAME="${RELEASE_NAME:-airflow}"
CHART_DIR="${CHART_DIR:-chart}"
VALUES="${VALUES:-chart/.values.rendered.yaml}"
K=("$KUBECTL_BIN" --context "$KUBE_CONTEXT" --namespace "$NAMESPACE")

PRIMARY_SVC="airflow-postgresql-primary"
PRIMARY_STS="airflow-postgresql-primary"
READ_STS="airflow-postgresql-read"
PGPW="${PG_SUPERUSER_PASSWORD:-postgres}"
DUMP="${DUMP:-/tmp/airflow-failback-$$.sql}"

psql_on() { "${K[@]}" exec "$1" -c postgresql -- env PGPASSWORD="$PGPW" psql -qtAX -U postgres -d postgres -c "$2"; }

# --- 1 & 2. dump the live, writable node ------------------------------------
# Resumable: steps 4-5 destroy and recreate the cluster, so if the run dies
# in between there is no writable node left to dump from. Pass DUMP=<file>
# pointing at an already-taken dump to skip straight to the rebuild.
if [ -s "$DUMP" ]; then
  echo "==> reusing existing dump $DUMP ($(wc -l < "$DUMP") lines)"
else
  live=""
  for pod in $("${K[@]}" get pods -l app.kubernetes.io/name=postgresql -o name | sed 's#^pod/##'); do
    [ "$("${K[@]}" get pod "$pod" -o jsonpath='{.status.phase}')" = "Running" ] || continue
    if [ "$(psql_on "$pod" 'SELECT pg_is_in_recovery();' 2>/dev/null || echo t)" = "f" ]; then
      live="$pod"; break
    fi
  done
  [ -n "$live" ] || {
    echo "ERROR: no writable postgres pod found -- nothing to fail back from."
    echo "       If a previous run already dumped, re-run with DUMP=<that file>."
    exit 1; }
  echo "==> live primary is $live"
  echo "==> dumping the airflow database"
  "${K[@]}" exec "$live" -c postgresql -- \
    env PGPASSWORD="$PGPW" pg_dump -U postgres --clean --if-exists -d postgres > "$DUMP"
  echo "    wrote $DUMP ($(wc -l < "$DUMP") lines)"
  [ -s "$DUMP" ] || { echo "ERROR: dump is empty, refusing to destroy the cluster"; exit 1; }
fi

# --- 3. reset the Service selector -----------------------------------------
# `kubectl patch --type json` on /spec/selector replaces the whole map, so
# the pod-name pin failover.sh added is removed rather than merged.
echo "==> resetting $PRIMARY_SVC selector to the chart's labels"
"${K[@]}" patch service "$PRIMARY_SVC" --type json -p '[{"op":"replace","path":"/spec/selector","value":{
  "app.kubernetes.io/component":"primary",
  "app.kubernetes.io/instance":"'"$RELEASE_NAME"'",
  "app.kubernetes.io/name":"postgresql"}}]' >/dev/null

# --- 4. tear down the diverged cluster --------------------------------------
echo "==> deleting postgres StatefulSets and PVCs"
"${K[@]}" delete statefulset "$PRIMARY_STS" "$READ_STS" --ignore-not-found --wait=true
"${K[@]}" delete pvc -l app.kubernetes.io/name=postgresql --ignore-not-found

# --- 5. recreate a clean cluster --------------------------------------------
echo "==> helm upgrade to recreate primary + replicas"
"$HELM_BIN" upgrade "$RELEASE_NAME" "$CHART_DIR" \
  --kube-context "$KUBE_CONTEXT" --namespace "$NAMESPACE" -f "$VALUES" --timeout 15m
"${K[@]}" rollout status "statefulset/$PRIMARY_STS" --timeout=10m

# --- 6. restore --------------------------------------------------------------
echo "==> restoring the dump into ${PRIMARY_STS}-0"
"${K[@]}" exec -i "${PRIMARY_STS}-0" -c postgresql -- \
  env PGPASSWORD="$PGPW" psql -q -U postgres -d postgres < "$DUMP" >/dev/null
echo "    restored"

# --- 7. bounce Airflow --------------------------------------------------------
mapfile -t objs < <("${K[@]}" get deploy,statefulset -o name \
  | grep -E 'airflow-(pgbouncer|scheduler|api-server|dag-processor|triggerer|worker)' || true)
[ ${#objs[@]} -gt 0 ] && "${K[@]}" rollout restart "${objs[@]}"

echo
echo "failback complete -> primary is ${PRIMARY_STS}-0 again, replicas rebuilt."
echo "dump kept at $DUMP"
