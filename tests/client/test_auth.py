import asyncio

import pytest

from custom_components.thermia_cloud.client.auth import ThermiaAuth
from custom_components.thermia_cloud.client.config import ThermiaConfig
from custom_components.thermia_cloud.client.errors import AuthError, LoginFlowError

from .conftest import AUTH_PATH, FakeCloud, Reply

TOKEN = f"{AUTH_PATH}/oauth2/v2.0/token"


async def test_login_happy_path(config: ThermiaConfig, cloud: FakeCloud) -> None:
    cloud.script_login()
    saved: list[str] = []
    auth = ThermiaAuth(config, "user", "pw", on_refresh_token=saved.append)
    token, generation = await auth.get_token()
    await auth.close()
    assert (token, generation) == ("access-1", 1)
    assert saved == ["refresh-1"]
    confirmed = ("GET", f"{AUTH_PATH}/api/CombinedSigninAndSignup/confirmed")
    assert "x-ms-cpim-trans=TRANS-COOKIE" in cloud.cookies_sent[confirmed]


async def test_bad_password_is_auth_error(config: ThermiaConfig, cloud: FakeCloud) -> None:
    cloud.script_login(password_ok=False)
    auth = ThermiaAuth(config, "user", "wrong")
    with pytest.raises(AuthError):
        await auth.get_token()
    await auth.close()


async def test_missing_csrf_is_login_flow_error(config: ThermiaConfig, cloud: FakeCloud) -> None:
    cloud.on("GET", f"{AUTH_PATH}/oauth2/v2.0/authorize", Reply(body="<html/>"))
    auth = ThermiaAuth(config, "user", "pw")
    with pytest.raises(LoginFlowError):
        await auth.get_token()
    await auth.close()


async def test_refresh_token_is_used_and_rotated(config: ThermiaConfig, cloud: FakeCloud) -> None:
    cloud.on("POST", TOKEN, cloud.token(access="access-2", refresh="refresh-2"))
    saved: list[str] = []
    auth = ThermiaAuth(config, "u", "p", refresh_token="refresh-1", on_refresh_token=saved.append)
    token, _ = await auth.get_token()
    await auth.close()
    assert token == "access-2"
    assert saved == ["refresh-2"]


async def test_rejected_refresh_token_falls_back_to_password(
    config: ThermiaConfig, cloud: FakeCloud
) -> None:
    cloud.on("POST", TOKEN, Reply(400, {"error": "invalid_grant"}))
    cloud.script_login(access="access-3")
    auth = ThermiaAuth(config, "u", "p", refresh_token="stale")
    token, _ = await auth.get_token()
    await auth.close()
    assert token == "access-3"


async def test_expiring_token_is_renewed_proactively(
    config: ThermiaConfig, cloud: FakeCloud
) -> None:
    cloud.on(
        "POST",
        TOKEN,
        cloud.token(access="a1", refresh="r1", expires_on=1_000),
        cloud.token(access="a2", refresh="r2"),
    )
    now = [0.0]
    auth = ThermiaAuth(config, "u", "p", refresh_token="r0", clock=lambda: now[0])
    assert (await auth.get_token())[0] == "a1"
    now[0] = 950.0  # inside the refresh margin
    assert (await auth.get_token())[0] == "a2"
    await auth.close()


async def test_concurrent_renewals_are_single_flight(
    config: ThermiaConfig, cloud: FakeCloud
) -> None:
    cloud.on("POST", TOKEN, cloud.token(access="a1", refresh="r1"))
    auth = ThermiaAuth(config, "u", "p", refresh_token="r0")
    results = await asyncio.gather(*(auth.get_token() for _ in range(7)))
    await auth.close()
    assert {r[0] for r in results} == {"a1"}
    assert cloud.count("POST", TOKEN) == 1


async def test_subject_is_read_from_the_access_token(
    config: ThermiaConfig, cloud: FakeCloud
) -> None:
    import base64
    import json

    payload = base64.urlsafe_b64encode(json.dumps({"sub": "account-123"}).encode()).rstrip(b"=")
    jwt = f"h.{payload.decode()}.s"
    cloud.on("POST", TOKEN, cloud.token(access=jwt))
    auth = ThermiaAuth(config, "u", "p", refresh_token="r0")
    await auth.get_token()
    await auth.close()
    assert auth.subject == "account-123"
    assert auth.refresh_token == "refresh-1"
