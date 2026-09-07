#!/usr/bin/env bash
#
# One-shot init for the compose stack, run by the `airflow-init` service before
# any long-running service starts (they `depends_on` it with
# service_completed_successfully). Idempotent: `docker compose up` re-runs it
# every time and it must be a no-op on an already-initialised database.
#
# Bootstrap is split in two, because the two halves need different things to
# already be running:
#
#   init.sh      -- migrations, role import + reconcile, local users. Runs
#                   BEFORE the scheduler, because nothing here needs a DAG.
#   sync-perm.sh -- `airflow sync-perm --include-dags`. Runs AFTER the dag
#                   processor has serialized the DAGs, because sync-perm reads
#                   access_control from the serialized DAGs in the database,
#                   not from the files on disk.
#
# The role files come from ./roles (one *.json per project) and the reconcile
# logic from ./bootstrap, both mounted by docker-compose.yaml. This stack owns
# both outright -- nothing here is read from outside compose/.
set -euo pipefail

ROLES_DIR="${ROLES_DIR:-/opt/airflow/roles}"
RECONCILE="${RECONCILE:-/opt/airflow/bootstrap/reconcile_roles.py}"

echo "== database =="
# `db migrate` covers Airflow's own tables. The FAB auth manager keeps a
# SEPARATE alembic history for users/roles/permissions, migrated by
# `fab-db migrate`, and nothing runs it implicitly -- without it the role and
# user commands below fail on missing tables. Both are idempotent.
airflow db migrate
airflow fab-db migrate

echo
echo "== roles =="
shopt -s nullglob
ROLE_FILES=("$ROLES_DIR"/*.json)

if [ ${#ROLE_FILES[@]} -eq 0 ]; then
  echo "no *.json role files under $ROLES_DIR; skipping role reconcile"
else
  echo "role files: ${ROLE_FILES[*]}"
  # `roles import` is kept only to CREATE roles that don't exist yet: it
  # cannot UPDATE an existing role ("if a role already exists in the db, it is
  # not overwritten, even when the permissions change"), and after the first
  # `make up` every declared role already exists -- the Postgres volume
  # survives `docker compose down`.
  echo "creating any missing roles (import can't update existing ones)..."
  for f in "${ROLE_FILES[@]}"; do
    echo "  import $f"
    airflow roles import "$f"
  done

  # reconcile_roles.py then diffs the merged role files against the live DB and
  # applies only the delta -- add-perms before del-perms, never deletes a role,
  # refuses FAB built-ins, leaves DAG:<dag_id> resources to sync-perm.
  echo "reconciling roles to the merged role files (delta only, add before delete)..."
  airflow roles export -p /tmp/current-roles.json
  python3 "$RECONCILE" \
    --desired "${ROLE_FILES[@]}" \
    --current /tmp/current-roles.json
fi

echo
echo "== users =="
# Identities come from Keycloak (see the `keycloak` service and
# config/webserver_config.py): a Keycloak group maps to an Airflow role at
# login, and under AUTH_TYPE=AUTH_OAUTH the local login form is gone, so local
# FAB users cannot sign in. This block is therefore skipped unless
# CREATE_LOCAL_USERS=true -- set that in .env only if you have also disabled
# SSO and want the old local-users-in-the-metadata-DB behaviour back.
#
# When it does run it only CREATES users; it does not reconcile the role of a
# user that already exists -- the Postgres volume outlives `make down`, so a
# role change made by hand is not silently reverted on the next `make up`. The
# team roles must already exist, which is why this runs after the role block
# above -- `users create --role team_a` errors on an unknown role.
create_user() {
  local username=$1 role=$2 firstname=$3 lastname=$4 password=$5

  if airflow users list -o json \
      | python3 -c 'import json,sys; print("\n".join(u["username"] for u in json.load(sys.stdin)))' \
      | grep -qx "$username"; then
    echo "  user $username already exists (role not changed)"
    return 0
  fi

  echo "  creating $username -> $role"
  airflow users create \
    --username "$username" \
    --role "$role" \
    --firstname "$firstname" \
    --lastname "$lastname" \
    --email "$username@example.com" \
    --password "$password"
}

if [ "${CREATE_LOCAL_USERS:-false}" = "true" ]; then
  create_user admin "Admin"  Admin User     "${ADMIN_PASSWORD:-admin}"
  create_user alice "team_a" Alice Anderson "${ALICE_PASSWORD:-alice}"
  create_user bob   "team_b" Bob   Brown    "${BOB_PASSWORD:-bob}"
  create_user carol "team_c" Carol Clark    "${CAROL_PASSWORD:-carol}"
else
  echo "  CREATE_LOCAL_USERS != true -- skipping local users (identities come from Keycloak)"
fi

echo
echo "== init complete =="
