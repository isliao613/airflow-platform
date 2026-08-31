"""Gap-free reconcile of operator-defined role files against the live DB.

Run by chart/templates/sync-roles-job.yaml on every post-install /
post-upgrade, after `airflow roles import`. Import is kept only to CREATE
declared roles that don't exist yet (one process, cheap); it cannot UPDATE
a role that already exists -- its own docstring: "if a role already exists
in the db, it is not overwritten, even when the permissions change" -- which
after the first deploy is every role in the files.

--desired takes ONE OR MORE JSON files (one per project: demo, project1,
...). They are merged into a single target model -- a role named in two
files gets the UNION of their permissions, with a warning. The set of roles
this job manages is exactly the set of role names across those files. There
is no hard-coded list, so operators can define their own files. For each
managed role it diffs the merged model against `airflow roles export` and
applies only the delta:

  * the role is never deleted -> ab_user_role (who holds the role) is
    untouched -> nobody is dropped from a role mid-upgrade and forced to
    re-login to get it back;
  * add-perms runs before del-perms -> a role never briefly holds LESS than
    its intended permission set;
  * FAB built-in roles (Admin, Public, Op, Viewer, User) are refused --
    letting a user-supplied file redefine them risks privilege escalation
    (Admin) or locking everyone out (Public/Viewer); naming one is a hard
    error, not a silent skip;
  * roles that exist but are absent from the file are reported and left
    alone -- this job never deletes a role;
  * an empty delta issues zero CLI calls -> idempotent on re-runs.

Scaling note: each add-perms / del-perms is a separate `airflow` invocation
(process start + DB connect) and its own commit, so the full delta is not
one transaction. Fine for tens of role x permission changes per deploy; for
a large operator-defined file, replace this with a single in-process pass
over flask_appbuilder's SecurityManager (one connection, one commit), which
is also closer to atomic.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

# FAB ships these. A user-supplied roles file must never redefine them.
BUILTIN_ROLES = {"Admin", "Public", "Op", "Viewer", "User"}

# Per-DAG permission resources ("DAG:<dag_id>", with the colon -- the global
# "DAGs" resource is NOT one of these and stays managed). They are owned by
# `airflow sync-perm --include-dags`, which derives them from each DAG's
# access_control, and are deliberately absent from roles.json. The reconcile
# must not touch them: pruning a DAG:<id> grant here just for sync-perm to
# re-add it seconds later opens exactly the access gap this script exists to
# avoid, plus churns every deploy.
def _dag_scoped(resource: str) -> bool:
    return resource.startswith("DAG:")


def _entry_problem(entry: object) -> str | None:
    if not isinstance(entry, dict):
        return "each entry must be a JSON object"
    for key in ("name", "resource", "action"):
        if key not in entry:
            return f"missing required key {key!r}"
    if not isinstance(entry["name"], str) or not entry["name"].strip():
        return "'name' must be a non-empty string"
    if not isinstance(entry["resource"], str):
        return "'resource' must be a string"
    if not isinstance(entry["action"], str):
        return "'action' must be a string (comma-separated actions, may be empty)"
    if entry["resource"] == "" and entry["action"] != "":
        return "'action' set but 'resource' empty"
    return None


def load(path: str, *, strict: bool):
    """Parse import/export JSON into {role: {resource: {actions}}}.

    strict=True (the operator's file): any malformed entry aborts the run.
    strict=False (`airflow roles export`): malformed entries are skipped.
    An entry with empty resource and action just registers the role name.
    """
    try:
        with open(path) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise SystemExit(f"{path}: no such file")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: invalid JSON: {exc}")
    if not isinstance(data, list):
        raise SystemExit(f"{path}: top level must be a JSON array")

    model: dict[str, dict[str, set[str]]] = {}
    for i, entry in enumerate(data):
        problem = _entry_problem(entry)
        if problem:
            if strict:
                raise SystemExit(f"{path}[{i}]: {problem}")
            continue
        role = model.setdefault(entry["name"], {})
        if entry["resource"] == "":
            continue
        actions = role.setdefault(entry["resource"], set())
        actions.update(a.strip() for a in entry["action"].split(",") if a.strip())
    return model


def load_many(paths: list[str], *, strict: bool):
    """Merge several role files into one {role: {resource: {actions}}} model.

    A role appearing in more than one file gets the union of its
    permissions; that is almost always a mistake across projects, so warn.
    """
    merged: dict[str, dict[str, set[str]]] = {}
    defined_in: dict[str, str] = {}
    for path in paths:
        for role, resources in load(path, strict=strict).items():
            if role in defined_in and defined_in[role] != path:
                print(
                    f"WARNING: role {role!r} is defined in both {defined_in[role]} and "
                    f"{path}; merging their permissions (union)"
                )
            defined_in.setdefault(role, path)
            dst = merged.setdefault(role, {})
            for resource, actions in resources.items():
                dst.setdefault(resource, set()).update(actions)
    return merged


def airflow_roles(*args: str) -> None:
    cmd = ["airflow", "roles", *args]
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def reconcile(role: str, want: dict, have: dict) -> int:
    changes = 0

    # add-perms first: never dip below the intended permission set.
    for resource in sorted(want):
        if _dag_scoped(resource):
            continue
        for action in sorted(want[resource] - have.get(resource, set())):
            airflow_roles("add-perms", role, "--resource", resource, "--action", action)
            changes += 1

    # del-perms second: strip only what is no longer desired. Skip
    # DAG:<dag_id> resources -- sync-perm --include-dags owns those.
    for resource in sorted(have):
        if _dag_scoped(resource):
            continue
        for action in sorted(have[resource] - want.get(resource, set())):
            airflow_roles("del-perms", role, "--resource", resource, "--action", action)
            changes += 1

    return changes


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gap-free reconcile of operator-defined role files against the live DB"
    )
    parser.add_argument(
        "--desired", required=True, nargs="+",
        help="one or more role JSON files (target state); merged into one model",
    )
    parser.add_argument("--current", required=True, help="`airflow roles export` output")
    args = parser.parse_args()

    desired_label = ", ".join(args.desired)
    desired = load_many(args.desired, strict=True)
    current = load(args.current, strict=False)

    if not desired:
        print(f"{desired_label} declares no roles; nothing to reconcile")
        return 0

    clash = sorted(BUILTIN_ROLES & set(desired))
    if clash:
        raise SystemExit(
            f"{desired_label}: refusing to manage FAB built-in role(s): {', '.join(clash)}. "
            "Remove them -- they are owned by FAB, not these files."
        )

    managed = sorted(desired)
    known_resources = {res for role in current.values() for res in role}
    known_actions = {act for role in current.values() for acts in role.values() for act in acts}

    for role in managed:
        for resource, actions in sorted(desired[role].items()):
            if _dag_scoped(resource):
                print(
                    f"WARNING: {role}: {resource!r} is a per-DAG resource; grant DAG access via "
                    "the DAG's access_control (sync-perm), not roles.json -- this entry is ignored"
                )
                continue
            if known_resources and resource not in known_resources:
                print(
                    f"WARNING: {role}: resource {resource!r} is unknown to this Airflow; "
                    "add-perms will still create the binding -- check for a typo"
                )
            for action in sorted(actions - known_actions) if known_actions else ():
                print(f"WARNING: {role}: action {action!r} on {resource!r} is unknown -- check for a typo")

    total = 0
    for role in managed:
        if role not in current:
            airflow_roles("create", role)
        changed = reconcile(role, desired[role], current.get(role, {}))
        total += changed
        print(f"role {role}: {changed} permission change(s)")

    orphans = sorted(set(current) - BUILTIN_ROLES - set(desired))
    if orphans:
        print(
            f"note: role(s) present in the DB but absent from {desired_label}, left untouched "
            f"(this job never deletes roles): {', '.join(orphans)}"
        )

    print(f"reconcile complete: {total} permission change(s) across {len(managed)} managed role(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
