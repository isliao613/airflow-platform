# Flask-AppBuilder auth config for the compose stack: Keycloak SSO.
#
# docker-compose.yaml mounts this at /opt/airflow/webserver_config.py in EVERY
# Airflow component (api-server, scheduler, dag-processor, triggerer, workers),
# not just the api-server -- FAB authorizes against AUTH_ROLES_MAPPING wherever
# it runs, so all components must agree on it. Only the api-server actually
# talks to Keycloak; the rest load this file and never reach the network paths
# below.
#
# This mirrors the kind stack's apiServerConfig / webserverConfig in
# chart/values.yaml. The one difference is the two Keycloak URLs:
#
#   * The kind stack runs a socat sidecar so ONE URL (http://localhost:8181)
#     resolves to Keycloak from both the browser and inside the pod.
#   * Compose has no sidecar. Instead the keycloak service runs with
#     KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true (see docker-compose.yaml): the
#     discovery `issuer` and the login redirect stay pinned to the browser URL
#     (http://localhost:8181), so authlib's `iss` check still lines up, while
#     the token / userinfo / JWKS endpoints in that same discovery document are
#     rewritten to whatever host asked -- so the server-side calls this file
#     makes resolve to the compose-internal address below.
#
# So: KEYCLOAK_INTERNAL_URL is only what THIS process dials for discovery; the
# browser-facing URL never appears here, it comes back inside the discovery doc.
from __future__ import annotations

import os

from flask_appbuilder.security.manager import AUTH_OAUTH

KEYCLOAK_INTERNAL_URL = os.environ.get(
    "AIRFLOW_KEYCLOAK_INTERNAL_URL", "http://keycloak:8080"
)
KEYCLOAK_REALM = os.environ.get("AIRFLOW_KEYCLOAK_REALM", "airflow")
_REALM_URL = f"{KEYCLOAK_INTERNAL_URL}/realms/{KEYCLOAK_REALM}"

AUTH_TYPE = AUTH_OAUTH

# First OAuth login creates the Airflow user. Public grants nothing on its own;
# anyone not in one of the groups below lands here and sees no DAGs.
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Public"

# Re-read the `groups` claim on every login and rewrite the user's roles, so
# Keycloak group membership -- not a role edited in Airflow -- is the single
# source of truth for who is on which team.
AUTH_ROLES_SYNC_AT_LOGIN = True

AUTH_ROLES_MAPPING = {
    "airflow-team-a": ["team_a"],
    "airflow-team-b": ["team_b"],
    "airflow-team-c": ["team_c"],
    # Built-in role -- created by Airflow itself, so it needs no entry in
    # roles/demo.json. Holds the global `DAGs` permission, so this group sees
    # every team's DAG.
    "airflow-admins": ["Admin"],
}

OAUTH_PROVIDERS = [
    {
        # The name "keycloak" is significant: Flask-AppBuilder ships a handler
        # for it that reads the userinfo endpoint and maps the `groups` claim
        # onto role_keys, which is what AUTH_ROLES_MAPPING consumes.
        "name": "keycloak",
        "icon": "fa-key",
        "token_key": "access_token",
        "remote_app": {
            "client_id": os.environ.get("AIRFLOW_KEYCLOAK_CLIENT_ID", "airflow"),
            # No fallback default: this is the OIDC client secret, and a missing
            # env var should fail loudly rather than silently authenticate
            # against a stale value. docker-compose.yaml always sets it.
            "client_secret": os.environ["AIRFLOW_KEYCLOAK_CLIENT_SECRET"],
            "server_metadata_url": f"{_REALM_URL}/.well-known/openid-configuration",
            # FAB appends "openid-connect/userinfo" to this base.
            "api_base_url": f"{_REALM_URL}/protocol/",
            "client_kwargs": {"scope": "openid email profile"},
        },
    }
]
