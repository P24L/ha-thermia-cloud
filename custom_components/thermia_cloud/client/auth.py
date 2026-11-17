"""Azure AD B2C sign-in (authorization code + PKCE) and token refresh.

Written from the protocol description in ``docs/API-NOTES.md`` section 2.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import re
import secrets
import time
from collections.abc import Callable
from urllib.parse import parse_qs, urlencode, urlparse

import aiohttp

from .config import REDIRECT_URI, ThermiaConfig
from .errors import AuthError, LoginFlowError, NetworkError

_LOGGER = logging.getLogger(__name__)

POLICY = "B2C_1A_SignUpOrSigninOnline"
REFRESH_MARGIN = 120  # seconds before expiry at which the token is renewed proactively
_TRANS_ID = re.compile(r'"transId"\s*:\s*"([^"]+)"')
_CSRF = re.compile(r'"csrf"\s*:\s*"([^"]+)"')


def _jwt_subject(token: str) -> str | None:
    """``sub`` of a JWT, read without verifying it (we only need an account identity)."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        sub = claims.get("sub")
    except IndexError, ValueError, AttributeError:
        return None
    return str(sub) if sub else None


class ThermiaAuth:
    """Holds the token, renews it proactively and on demand (single flight)."""

    def __init__(
        self,
        config: ThermiaConfig,
        username: str,
        password: str,
        *,
        refresh_token: str | None = None,
        on_refresh_token: Callable[[str], None] | None = None,
        user_agent: str = "HomeAssistant thermia_cloud",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._config = config
        self._username = username
        self._password = password
        self._refresh_token = refresh_token
        self._on_refresh_token = on_refresh_token
        self._user_agent = user_agent
        self._clock = clock
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._generation = 0
        self._subject: str | None = None
        self._lock = asyncio.Lock()
        # Private session and cookie jar: never share login cookies with anything else.
        self._session: aiohttp.ClientSession | None = None
        self._cookies: dict[str, str] = {}

    @property
    def generation(self) -> int:
        """Incremented on every successful (re)authentication."""
        return self._generation

    @property
    def subject(self) -> str | None:
        """The account's stable ``sub`` claim from the access token (identity of the account)."""
        return self._subject

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def get_token(self) -> tuple[str, int]:
        """Return ``(access_token, generation)``, renewing it when it is about to expire."""
        if self._access_token is None or self._clock() >= self._expires_at - REFRESH_MARGIN:
            await self.renew(self._generation)
        assert self._access_token is not None
        return self._access_token, self._generation

    async def renew(self, seen_generation: int) -> None:
        """Renew the token unless somebody else already did since ``seen_generation``."""
        async with self._lock:
            if self._generation != seen_generation:
                return
            if self._refresh_token and await self._try_refresh():
                return
            await self._login()

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession(
                # Cookies are tracked by hand (see _absorb): the B2C flow expires one of its
                # own cookies mid-flow and still expects it to be sent on the last step.
                cookie_jar=aiohttp.DummyCookieJar(),
                headers={"User-Agent": self._user_agent},
                timeout=aiohttp.ClientTimeout(total=30),
            )
        return self._session

    def _absorb(self, resp: aiohttp.ClientResponse) -> None:
        """Remember cookies set by a response; expiring (empty) ones are deliberately kept."""
        for name, morsel in resp.cookies.items():
            if morsel.value:
                self._cookies[name] = morsel.coded_value

    @property
    def _cookie_header(self) -> dict[str, str]:
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in self._cookies.items())}

    @property
    def _scope(self) -> str:
        return " ".join(self._config.scopes)

    async def _try_refresh(self) -> bool:
        """Use the refresh token; ``False`` means: fall back to the password login."""
        status, body = await self._post_token(
            {
                "grant_type": "refresh_token",
                "client_id": self._config.client_id,
                "scope": self._scope,
                "refresh_token": self._refresh_token or "",
            }
        )
        if status != 200 or "access_token" not in body:
            _LOGGER.debug("Refresh token not accepted (%s), logging in again", body.get("error"))
            self._refresh_token = None
            return False
        self._store(body)
        return True

    async def _post_token(self, form: dict[str, str]) -> tuple[int, dict[str, object]]:
        url = f"{self._config.authority}/oauth2/v2.0/token"
        try:
            async with self._get_session().post(url, data=form) as resp:
                body = await resp.json(content_type=None)
                return resp.status, body if isinstance(body, dict) else {}
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NetworkError(str(err)) from err
        except ValueError as err:
            raise LoginFlowError("token endpoint did not return JSON") from err

    def _store(self, body: dict[str, object]) -> None:
        self._access_token = str(body["access_token"])
        self._subject = _jwt_subject(self._access_token) or self._subject
        expires_on = body.get("expires_on")
        if expires_on is not None:
            self._expires_at = float(str(expires_on))
        else:
            self._expires_at = self._clock() + float(str(body.get("expires_in", 3600)))
        refresh = body.get("refresh_token")
        if refresh:
            # Refresh tokens are rotated on every use: always keep the newest one.
            self._refresh_token = str(refresh)
            if self._on_refresh_token is not None:
                self._on_refresh_token(self._refresh_token)
        self._generation += 1

    async def _login(self) -> None:
        session = self._get_session()
        self._cookies = {}
        authority = self._config.authority
        verifier = secrets.token_urlsafe(48)
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        query = urlencode(
            {
                "client_id": self._config.client_id,
                "scope": self._scope,
                "response_type": "code",
                "redirect_uri": REDIRECT_URI,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "response_mode": "query",
            }
        )
        try:
            async with session.get(f"{authority}/oauth2/v2.0/authorize?{query}") as resp:
                self._absorb(resp)
                html = await resp.text()
                if resp.status != 200:
                    raise LoginFlowError(f"authorize endpoint answered {resp.status}")
            trans, csrf = _TRANS_ID.search(html), _CSRF.search(html)
            if trans is None or csrf is None:
                raise LoginFlowError("transId/csrf not found in the sign-in page")
            # B2C wants ``tx=StateProperties=<id>`` verbatim: do not percent-encode the "=".
            tx = trans.group(1)

            async with session.post(
                f"{authority}/SelfAsserted?tx={tx}&p={POLICY}",
                data={
                    "request_type": "RESPONSE",
                    "signInName": self._username,
                    "password": self._password,
                },
                headers={"X-Csrf-Token": csrf.group(1), **self._cookie_header},
            ) as resp:
                self._absorb(resp)
                text = await resp.text()
                if resp.status >= 500:
                    raise LoginFlowError(f"sign-in endpoint answered {resp.status}")
                if resp.status != 200 or '"status":"400"' in text:
                    raise AuthError("the cloud rejected the credentials")

            async with session.get(
                f"{authority}/api/CombinedSigninAndSignup/confirmed"
                f"?csrf_token={csrf.group(1)}&tx={tx}&p={POLICY}",
                headers=self._cookie_header,
                allow_redirects=False,
            ) as resp:
                location = resp.headers.get("Location", "")
        except (aiohttp.ClientError, TimeoutError) as err:
            raise NetworkError(str(err)) from err

        codes = parse_qs(urlparse(location).query).get("code")
        if not codes:
            raise LoginFlowError("no authorization code in the final redirect")

        status, body = await self._post_token(
            {
                "grant_type": "authorization_code",
                "client_id": self._config.client_id,
                "scope": self._scope,
                "code": codes[0],
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
            }
        )
        if status != 200 or "access_token" not in body:
            raise LoginFlowError(f"token endpoint answered {status}: {body.get('error')}")
        self._store(body)
