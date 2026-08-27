#!/usr/bin/env bash
#
# Manual (break-glass) failover for the bundled bitnami/postgresql running
# in replication mode (airflow.postgresql.architecture: replication in
# chart/values.yaml). That chart has NO automatic failover -- the read
# replicas are plain streaming standbys.
#
# This script:
#   1. FENCES the old primary by scaling its StatefulSet to 0. Without this
#      you get split-brain: pg_promote does not stop the old primary, so a
#      node that was only network-partitioned (or a pod that comes back)
#      keeps accepting writes on a diverged timeline, and any non-promoted
#      replica keeps streaming from it. Verified: after promoting without
#      fencing, the old primary still took INSERTs the new primary never
#      saw. Fencing first is what makes the rest safe.
#   2. picks the read replica with the highest replayed WAL position;
#   3. promotes it to a read-write primary (pg_promote);
#   4. repoints the `airflow-postgresql-primary` Service selector at that
#      pod, so everything connecting to it (PgBouncer, and through it every
#      Airflow component) follows -- no connection-string change;
#   5. restarts the Airflow tier so stale DB connections are dropped now
#      rather than after pool_pre_ping notices.
#
# LIMITATION: the fenced primary and any non-promoted replica are left on a
# diverged timeline and will NOT re-follow the new primary on their own, so
# the cluster runs with no redundancy until it is rebuilt (pg_rewind, a
# redeploy, or a restore). Scaling the primary StatefulSet back up WITHOUT
# rebuilding re-introduces the split brain -- see the README. This is a
# dev/POC convenience, not a substitute for Patroni / CloudNativePG / a
# managed HA database.
#
# Usage:
#   KUBE_CONTEXT=kind-airflow NAMESPACE=airflow ./postgres/failover.sh
#   [TARGET=airflow-postgresql-read-1]   # force a specific replica
#   [FENCE=false]                        # skip fencing (unsafe; only when
#                                        #  the old primary is provably gone)
set -euo pipefail

KUBECTL_BIN="${KUBECTL_BIN:-kubectl}"
: "${KUBE_CONTEXT:?KUBE_CONTEXT must be set}"
: "${NAMESPACE:?NAMESPACE must be set}"
K=("$KUBECTL_BIN" --context "$KUBE_CONTEXT" --namespace "$NAMESPACE")

PRIMARY_SVC="airflow-postgresql-primary"
PRIMARY_STS="airflow-postgresql-primary"
PGPW="${PG_SUPERUSER_PASSWORD:-postgres}"

psql_on() { # <pod> <sql>
  "${K[@]}" exec "$1" -c postgresql -- \
    env PGPASSWORD="$PGPW" psql -qtAX -U postgres -d postgres -c "$2"
}

echo "current primary Service endpoints:"
"${K[@]}" get endpoints "$PRIMARY_SVC" -o jsonpath='{.subsets[*].addresses[*].targetRef.name}' && echo

# --- 1. fence the old primary ---------------------------------------------
# Do this BEFORE promoting: two writable primaries, even briefly, means
# writes can land on the node about to be abandoned.
if [ "${FENCE:-true}" = "true" ]; then
  echo "==> fencing the old primary (scaling $PRIMARY_STS to 0)"
  "${K[@]}" scale statefulset "$PRIMARY_STS" --replicas=0
  "${K[@]}" wait --for=delete "pod/${PRIMARY_STS}-0" --timeout=120s 2>/dev/null || true
else
  echo "==> FENCE=false: skipping fencing (old primary may still accept writes)"
fi

# --- 2. choose the promotion target --------------------------------------
target="${TARGET:-}"
if [ -z "$target" ]; then
  best_lsn=""
  while read -r pod; do
    [ -n "$pod" ] || continue
    phase=$("${K[@]}" get pod "$pod" -o jsonpath='{.status.phase}' 2>/dev/null || true)
    if [ "$phase" != "Running" ]; then echo "  $pod: $phase (skip)"; continue; fi
    lsn=$(psql_on "$pod" "SELECT pg_last_wal_replay_lsn();" 2>/dev/null || true)
    echo "  $pod: replay_lsn=${lsn:-<unreachable>}"
    [ -n "$lsn" ] || continue
    if [ -z "$best_lsn" ] || \
       [ "$(psql_on "$pod" "SELECT '$lsn'::pg_lsn > '$best_lsn'::pg_lsn;")" = "t" ]; then
      target="$pod"; best_lsn="$lsn"
    fi
  done < <("${K[@]}" get pods -l app.kubernetes.io/component=read -o name | sed 's#^pod/##')
fi
[ -n "$target" ] || { echo "ERROR: no promotable read replica found"; exit 1; }
echo "==> promoting $target"

# --- 3. promote --------------------------------------------------------------
psql_on "$target" "SELECT pg_promote(wait => true, wait_seconds => 60);" >/dev/null
for _ in $(seq 1 30); do
  [ "$(psql_on "$target" 'SELECT pg_is_in_recovery();' 2>/dev/null || echo t)" = "f" ] && break
  sleep 2
done
[ "$(psql_on "$target" 'SELECT pg_is_in_recovery();')" = "f" ] || {
  echo "ERROR: $target is still in recovery"; exit 1; }
echo "    $target is now read-write"

# --- 4. repoint the primary Service ---------------------------------------
"${K[@]}" patch service "$PRIMARY_SVC" --type json \
  -p "[{\"op\":\"replace\",\"path\":\"/spec/selector\",\"value\":{\"statefulset.kubernetes.io/pod-name\":\"$target\"}}]"
echo "    Service/$PRIMARY_SVC now targets $target"

# --- 5. bounce the Airflow tier -----------------------------------------------
mapfile -t objs < <("${K[@]}" get deploy,statefulset -o name \
  | grep -E 'airflow-(pgbouncer|scheduler|api-server|dag-processor|triggerer|worker)' || true)
[ ${#objs[@]} -gt 0 ] && "${K[@]}" rollout restart "${objs[@]}"

echo
echo "failover complete -> new primary: $target"
echo "the old primary and any other replica are now stale; rebuild redundancy"
echo "with a redeploy (make deploy) or a manual pg_rewind."
