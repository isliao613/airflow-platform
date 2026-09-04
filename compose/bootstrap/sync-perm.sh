#!/usr/bin/env bash
#
# Applies each DAG's `access_control` -- the second half of the compose stack's
# bootstrap (see init.sh for the first half and why they are split).
#
# Run by the `airflow-bootstrap` service, which waits on the api-server,
# scheduler and dag-processor being healthy. It cannot be folded into
# `airflow-init`: `sync-perm --include-dags` reads access_control from the
# SERIALIZED DAGs in the database, and nothing has serialized them until the dag
# processor has made at least one pass -- which cannot happen before init
# finishes, because the dag processor waits on it.
#
# Not fatal if no DAG ever appears: a deployment may legitimately have none, and
# sync-perm is a harmless no-op then.
set -euo pipefail

echo "waiting for the dag processor to serialize DAGs..."
for i in $(seq 1 60); do
  # `-o json` rather than parsing the table: the plain table prints a header
  # row, so a line count says "1 DAG" on an empty deployment.
  found=$(airflow dags list -o json 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null \
    || echo 0)

  if [ "$found" -ge 1 ]; then
    echo "$found DAG(s) serialized"
    break
  fi
  if [ "$i" = "60" ]; then
    echo "WARNING: no DAGs serialized within 5m; continuing"
    break
  fi
  sleep 5
done

echo "applying per-DAG access_control..."
airflow sync-perm --include-dags

echo "sync-perm complete"
