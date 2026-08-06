# Multi-team Airflow example

Airflow 3's `multi_team` mode (experimental) lets one Airflow deployment
isolate multiple teams' DAGs, connections, variables, and pools, while
sharing the same metadata DB and control plane. Isolation is logical, not a
hard security boundary -- see the
[official docs](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/multi-team.html)
before using this for anything with strict tenant-isolation requirements.

**This is actually wired into `values.yaml` and deployed**, not just a
reference example. `make deploy` installs it; `make teams` creates the two
teams; `make login` prints current passwords.

```
team_data/dags/extract_daily_report.py   -> team_data
team_ml/dags/train_model.py              -> team_ml
dags/hello_world.py                      -> no team (global, dags-folder bundle)
```

## Two chart 1.22.0 limitations discovered the hard way

**1. No per-team executor.** The chart hard-requires `executor` (top-level
value, also used as a Kubernetes label) and `config.core.executor` (what
Airflow actually reads) to be byte-identical -- see `NOTES.txt` in the
chart. Semicolon syntax like `CeleryExecutor;team_data=CeleryExecutor` fails
both as a label (labels can't contain `;`/`=`) and the equality check if set
only on `config.core.executor`. Every team here shares one `CeleryExecutor`.

**2. `multi_team` requires an auth manager that implements `_get_teams()`.**
`FabAuthManager` -- the chart's default, with the login page and `admin`/
`admin` -- only has the abstract stub that raises `NotImplementedError`, and
the api-server crash-loops on boot if you enable `multi_team` without
switching auth managers. Only `SimpleAuthManager` implements it, which is
why `values.yaml` sets:

```yaml
config:
  core:
    auth_manager: "airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager"
    multi_team: "True"
    simple_auth_manager_users: "admin:ADMIN,data_user:USER:team_data,ml_user:USER:team_ml"
```

`simple_auth_manager_users` is `username:role[:team1|team2]`, comma-separated.
SimpleAuthManager is dev-only: plaintext passwords, regenerated and logged
fresh on every api-server restart (no persistent volume backs the password
file here) -- `make login` reads them out of the running pod.

## Bootstrap order matters

`SimpleAuthManager.init()` validates that every team referenced by
`simple_auth_manager_users` already exists as a DB `Team` row, and the
dag-processor needs the same for `dag_bundle_config_list` team associations.
Create teams too late and the api-server crash-loops with:

```
ValueError: Teams defined in the auth manager ({'team_data', 'team_ml'})
are not present in the database (set()).
```

So the working order is: deploy once with `multi_team`/`SimpleAuthManager`
on (api-server will crash-loop -- expected), run `make teams` against the
(healthy) scheduler pod, then it self-heals on its next restart. `make
deploy` again afterward to add the team-scoped DAG bundles once teams exist.

## DAG bundle -> team association

Team is a property of the *bundle*, not something a DAG file declares. Chart
1.22.0's `dagProcessor.dagBundleConfigList` structured helper only forwards
`name`/`classpath`/`kwargs` and silently drops `team_name`, so this is set
directly as a raw JSON string on `config.dag_processor.dag_bundle_config_list`
in `values.yaml` instead -- see the comment there.

## Team-scoped connections, variables, and pools

Connections/variables use a `___` (triple underscore) separator between the
upper-cased team name and the id:

```bash
export AIRFLOW_CONN__TEAM_DATA___WAREHOUSE="postgresql://..."
export AIRFLOW_VAR__TEAM_ML___MODEL_BUCKET="s3://team-ml-models"
```

Pools:

```bash
airflow pools set team_data_pool 10 "Pool for team_data" --team-name team_data
```

## Team-scoped triggerer (if any DAGs use deferrable operators)

```bash
airflow triggerer --team-name team_data
airflow triggerer --team-name team_ml
```

## Constraint to know up front

DAG ids, Variable keys, and Connection ids must still be unique across the
*entire* deployment, even across teams -- multi-team gives you scoped access
and separate resource pools, not a separate namespace for ids.
