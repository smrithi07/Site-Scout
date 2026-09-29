"""Phase 3a checkpoint: role checks are real and server-side."""
import pytest

from app.core.auth import Role, token_for
from tests.conftest import USER_IDS, headers

# (method, path, roles allowed). Every protected endpoint is listed here; the test below asserts
# each role gets exactly allowed → 2xx/4xx-not-auth, everyone else → 403.
ACCESS = [
    ("GET", "/localities/search?q=Adyar", {Role.BD_MANAGER, Role.BD_EXECUTIVE}),
    ("GET", "/reference/pincodes/600020", {Role.BD_MANAGER, Role.BD_EXECUTIVE, Role.SURVEY_MANAGER}),
    ("GET", "/reference/snapshot", set(Role)),
    ("GET", "/config", set(Role)),
    ("GET", "/auth/me", set(Role)),
    ("GET", "/areas/grid", {Role.BD_MANAGER}),
    ("GET", "/opportunities", {Role.BD_MANAGER}),
    ("GET", "/reference/service-area", set(Role)),
    ("GET", "/reference/stores", {Role.BD_MANAGER, Role.BD_EXECUTIVE}),
    ("GET", "/reference/locate?lat=13.0418&lon=80.2341", {Role.BD_MANAGER, Role.BD_EXECUTIVE}),
    ("GET", "/tasks", {Role.BD_MANAGER, Role.BD_EXECUTIVE}),
    ("GET", "/properties", {Role.BD_MANAGER, Role.BD_EXECUTIVE}),
    ("GET", "/studies", {Role.BD_MANAGER, Role.SURVEY_MANAGER}),
    ("GET", "/my/units", {Role.SURVEY_EXECUTIVE}),
]


@pytest.mark.parametrize("method,path,allowed", ACCESS)
@pytest.mark.parametrize("role", list(Role))
def test_role_matrix(client, method, path, allowed, role):
    status = client.request(method, path, headers=headers(role)).status_code
    if role in allowed:
        assert status == 200, (role, path, status)
    else:
        assert status == 403, (role, path, status)


@pytest.mark.parametrize("method,path,_", ACCESS)
def test_no_token_is_401(client, method, path, _):
    assert client.request(method, path).status_code == 401


@pytest.mark.parametrize("token", ["garbage", "1.deadbeef", f"2.{token_for(1).split('.')[1]}", "", "abc.def"])
def test_forged_or_malformed_tokens_are_401(client, token):
    # Includes the BD Manager's signature on the BD Executive's id — a swapped id must not verify.
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_demo_login_issues_a_working_token(client):
    users = client.get("/auth/demo-users").json()
    assert [u["role"] for u in users] == [r.value for r in Role]
    assert all("token" not in u for u in users)  # the list never exposes tokens
    body = client.post("/auth/demo-login", json={"user_id": USER_IDS[Role.SURVEY_MANAGER]}).json()
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['token']}"}).json()
    assert me["role"] == "survey_manager"
    assert client.post("/auth/demo-login", json={"user_id": 999}).status_code == 404
