"""A scriptable fake cloud (local aiohttp server) and the iTec fixture."""

import json
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from custom_components.thermia_cloud.client.config import ThermiaConfig

FIXTURES = Path(__file__).parent.parent / "fixtures" / "itec_profile_1005"
AUTH_PATH = "/tenant/B2C_1A_SignUpOrSigninOnline"
SIGN_IN_PAGE = (
    'var SETTINGS = {"csrf":"CSRF-PLACEHOLDER","transId":"StateProperties=TRANS-PLACEHOLDER"};'
)


@dataclass
class Reply:
    status: int = 200
    body: Any = None
    headers: dict[str, str] = field(default_factory=dict)


class FakeCloud:
    """Replies are queued per ``(method, path)`` and consumed in order; ``always`` repeats."""

    def __init__(self) -> None:
        self._queues: dict[tuple[str, str], deque[Reply]] = defaultdict(deque)
        self._sticky: dict[tuple[str, str], Reply] = {}
        self.calls: list[tuple[str, str]] = []
        self.cookies_sent: dict[tuple[str, str], str] = {}
        self.bodies: list[tuple[str, str, Any]] = []  # (method, path, json body)
        self.base_url = ""

    def on(self, method: str, path: str, *replies: Reply) -> None:
        self._queues[(method, path)].extend(replies)

    def always(self, method: str, path: str, reply: Reply) -> None:
        self._sticky[(method, path)] = reply

    def count(self, method: str, path: str) -> int:
        return self.calls.count((method, path))

    async def handle(self, request: web.Request) -> web.Response:
        key = (request.method, request.path)
        self.calls.append(key)
        self.cookies_sent[key] = request.headers.get("Cookie", "")
        if request.can_read_body and request.content_type == "application/json":
            self.bodies.append((request.method, request.path, await request.json()))
        queue = self._queues[key]
        reply = queue.popleft() if queue else self._sticky.get(key, Reply(500, "unscripted"))
        if isinstance(reply.body, str):
            return web.Response(status=reply.status, text=reply.body, headers=reply.headers)
        return web.json_response(reply.body, status=reply.status, headers=reply.headers)

    # -- scripted B2C calls -------------------------------------------------
    def token(self, **kw: Any) -> Reply:
        return Reply(200, token_body(**kw))

    def script_login(self, *, password_ok: bool = True, **token: Any) -> None:
        self.on(
            "GET",
            f"{AUTH_PATH}/oauth2/v2.0/authorize",
            Reply(
                body=SIGN_IN_PAGE, headers={"Set-Cookie": "x-ms-cpim-trans=TRANS-COOKIE; Path=/"}
            ),
        )
        self.on(
            "POST",
            f"{AUTH_PATH}/SelfAsserted",
            Reply(
                body='{"status":"200"}' if password_ok else '{"status":"400","message":"bad"}',
                # B2C expires its transaction cookie here but still wants it on the next call.
                headers={
                    "Set-Cookie": "x-ms-cpim-trans=; Path=/; Expires=Wed, 17-Nov-2016 00:00:00 GMT"
                },
            ),
        )
        self.on(
            "GET",
            f"{AUTH_PATH}/api/CombinedSigninAndSignup/confirmed",
            Reply(302, "", {"Location": "https://online.thermia.se/login?code=CODE-PLACEHOLDER"}),
        )
        self.on("POST", f"{AUTH_PATH}/oauth2/v2.0/token", self.token(**token))


def token_body(
    access: str = "access-1", refresh: str | None = "refresh-1", **extra: Any
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "access_token": access,
        "expires_in": 3600,
        "expires_on": 4_000_000_000,
        "refresh_token_expires_in": 86400,
        **extra,
    }
    if refresh:
        body["refresh_token"] = refresh
    return body


@pytest.fixture
async def cloud(socket_enabled: None) -> AsyncIterator[FakeCloud]:
    """Local server only: ``socket_enabled`` lifts the plugin's block for these tests."""
    fake = FakeCloud()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", fake.handle)
    server = TestServer(app)
    await server.start_server()
    fake.base_url = str(server.make_url("")).rstrip("/")
    yield fake
    await server.close()


@pytest.fixture
def config(cloud: FakeCloud) -> ThermiaConfig:
    return ThermiaConfig(
        api_base_url=cloud.base_url,
        authority=cloud.base_url + AUTH_PATH,
        client_id="client-id",
        scopes=("client-id", "offline_access", "openid"),
    )


def load_group(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads((FIXTURES / f"group_{name}.json").read_text())
    return data


def load_api(name: str) -> Any:
    return json.loads((FIXTURES.parent / "api" / f"{name}.json").read_text())
