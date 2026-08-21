"""Flask-AppBuilder config for the Airflow API server -- Keycloak SSO.

Baked into the image at /opt/airflow/webserver_config.py (see Dockerfile)
rather than passed through the chart's `apiServer.apiServerConfig`, because
that value is rendered as a Helm template and Python dict literals are an
awkward fit for that.

Roles come from Keycloak groups, not from Airflow: AUTH_ROLES_SYNC_AT_LOGIN
re-reads the `groups` claim on every login and rewrites the user's roles, so
group membership in Keycloak is the single source of truth. The team roles
themselves are created by `airflow roles import` (see airflow/roles.json) and
deliberately hold no global `DAGs` permission -- per-DAG access is granted
only by the `access_control` mapping in each DAG file.
"""

from __future__ import annotations

import os

from flask_appbuilder.security.manager import AUTH_OAUTH

# Keycloak is reached at the same URL from the browser and from this pod (via
# the socat sidecar), so the issuer in the tokens lines up on both sides.
KEYCLOAK_BASE_URL = os.environ.get("AIRFLOW_KEYCLOAK_BASE_URL", "http://localhost:8081")
KEYCLOAK_REALM = os.environ.get("AIRFLOW_KEYCLOAK_REALM", "airflow")
_REALM_URL = f"{KEYCLOAK_BASE_URL}/realms/{KEYCLOAK_REALM}"

AUTH_TYPE = AUTH_OAUTH

# First OAuth login creates the Airflow user. Public grants nothing on its own;
# anyone not in one of the three groups below lands here and sees no DAGs.
AUTH_USER_REGISTRATION = True
AUTH_USER_REGISTRATION_ROLE = "Public"
AUTH_ROLES_SYNC_AT_LOGIN = True

AUTH_ROLES_MAPPING = {
    "airflow-team-a": ["team_a"],
    "airflow-team-b": ["team_b"],
    "airflow-team-c": ["team_c"],
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
            "client_secret": os.environ.get(
                "AIRFLOW_KEYCLOAK_CLIENT_SECRET", "airflow-local-dev-secret"
            ),
            "server_metadata_url": f"{_REALM_URL}/.well-known/openid-configuration",
            # FAB appends "openid-connect/userinfo" to this base.
            "api_base_url": f"{_REALM_URL}/protocol/",
            "client_kwargs": {"scope": "openid email profile"},
        },
    }
]
