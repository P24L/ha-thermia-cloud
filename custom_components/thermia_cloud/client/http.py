"""One ``request()`` for every API call: auth header, 401 handling, bounded retries."""

from __future__ import annotations

import asyncio
import json as jsonlib
import logging
import random
import re
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp

from .auth import ThermiaAuth
from .errors import ApiError, NetworkError, RateLimitError

_LOGGER = logging.getLogger(__name__)
_NUMBER = re.compile(r"/\d+")

MAX_SERVER_RETRIES = (
    2  # immediate retries for 5xx inside one request; longer waits are the caller's job
)


def _redact(path: str) -> str:
    """Drop numeric ids from a path before logging it."""
    return _NUMBER.sub("/{id}", path)


class ThermiaHttp:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: ThermiaAuth,
        base_url: str,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timeout: float = 30,
    ) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session = session
        self._auth = auth
        self._base_url = base_url.rstrip("/")
        self._sleep = sleep

    async def request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, str] | None = None
    ) -> Any:
        """Return the decoded JSON body. 401 -> re-auth once -> retry once."""
        reauthed = False
        server_retries = 0
        while True:
            token, generation = await self._auth.get_token()
            try:
                async with self._session.request(
                    method,
                    f"{self._base_url}{path}",
                    json=json,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=self._timeout,
                ) as resp:
                    status = resp.status
                    _LOGGER.debug("%s %s -> %s", method, _redact(path), status)
                    if status == 200:
                        text = await resp.text()
                        return jsonlib.loads(text) if text.strip() else None
                    retry_after = resp.headers.get("Retry-After")
            except (aiohttp.ClientError, TimeoutError) as err:
                raise NetworkError(str(err)) from err

            if status == 401 and not reauthed:
                reauthed = True
                await self._auth.renew(generation)
                continue
            if status == 429:
                raise RateLimitError(float(retry_after) if retry_after else None)
            if status >= 500 and server_retries < MAX_SERVER_RETRIES:
                server_retries += 1
                await self._sleep(random.uniform(0.5, 1.5) * server_retries)
                continue
            raise ApiError(status)
