"""Client factory and discovery cache of ``__init__``; sign-in probe of the config flow."""

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermia_cloud import _load_discovery, async_build_client
from custom_components.thermia_cloud.client.config import ThermiaConfig
from custom_components.thermia_cloud.client.errors import AuthError, NetworkError
from custom_components.thermia_cloud.client.models import Installation
from custom_components.thermia_cloud.config_flow import async_probe
from custom_components.thermia_cloud.const import (
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DOMAIN,
)

from .fakes import INSTALLATION_ID, FakeApi

CONFIG = ThermiaConfig("https://api.example.test", "https://auth.example.test/t", "cid", ("cid",))


@pytest.fixture
def entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_REFRESH_TOKEN: "r0"},
    )
    entry.add_to_hass(hass)
    return entry


async def test_rotated_refresh_token_is_written_back(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    with patch("custom_components.thermia_cloud.fetch_config", return_value=CONFIG):
        _, auth, _ = await async_build_client(hass, entry)
    auth._on_refresh_token("r1")  # what ThermiaAuth calls after every refresh
    assert entry.data[CONF_REFRESH_TOKEN] == "r1" and entry.data[CONF_PASSWORD] == "p"
    await auth.close()


async def test_discovery_is_cached_and_reused(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    api = FakeApi()
    first = await _load_discovery(hass, entry, api, INSTALLATION_ID)
    assert len(first.specs) == 26 and "REG_GROUP_POOL" not in first.groups
    calls = len(api.calls)
    second = await _load_discovery(hass, entry, api, INSTALLATION_ID)
    assert len(api.calls) == calls  # served from the cache
    assert second.specs == first.specs and second.history == first.history


async def _store_old_cache(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    api = FakeApi()
    discovery = await _load_discovery(hass, entry, api, INSTALLATION_ID)
    old = discovery.to_json()
    old["fetched_at"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.discovery.{entry.entry_id}")
    await store.async_save({str(INSTALLATION_ID): old})


async def test_stale_cache_is_used_when_the_cloud_is_down(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await _store_old_cache(hass, entry)
    api = FakeApi()
    api.error = NetworkError("down")
    assert (await _load_discovery(hass, entry, api, INSTALLATION_ID)).specs


async def test_stale_cache_is_refreshed_when_the_cloud_answers(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await _store_old_cache(hass, entry)
    api = FakeApi()
    fresh = await _load_discovery(hass, entry, api, INSTALLATION_ID)
    assert api.calls and fresh.age_seconds() < 60


async def test_without_cache_a_down_cloud_raises(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    api = FakeApi()
    api.error = NetworkError("down")
    with pytest.raises(NetworkError):
        await _load_discovery(hass, entry, api, INSTALLATION_ID)


async def test_auth_errors_are_never_hidden_by_the_cache(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await _store_old_cache(hass, entry)
    api = FakeApi()
    api.error = AuthError("bad")
    with pytest.raises(AuthError):
        await _load_discovery(hass, entry, api, INSTALLATION_ID)


async def test_unreadable_cache_is_discarded(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.discovery.{entry.entry_id}")
    await store.async_save({str(INSTALLATION_ID): {"garbage": True}})
    api = FakeApi()
    assert (await _load_discovery(hass, entry, api, INSTALLATION_ID)).specs


class _Auth:
    refresh_token = "rt"

    def __init__(self, *_: Any, subject: str | None = "sub-9", **__: Any) -> None:
        self.subject = subject
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Api:
    def __init__(self, *_: Any) -> None:
        pass

    async def list_installations(self) -> list[Installation]:
        return [Installation(1, "x", "iTec", True, None, None)]


@pytest.mark.parametrize(
    ("subject", "expected"), [("sub-9", "sub-9"), (None, "mail@example.invalid")]
)
async def test_probe_returns_the_account_identity(
    hass: HomeAssistant, subject: str | None, expected: str
) -> None:
    class Auth(_Auth):
        def __init__(self, *a: Any, **k: Any) -> None:
            super().__init__(*a, subject=subject, **k)

    with (
        patch("custom_components.thermia_cloud.config_flow.fetch_config", return_value=CONFIG),
        patch("custom_components.thermia_cloud.config_flow.ThermiaAuth", Auth),
        patch("custom_components.thermia_cloud.config_flow.ThermiaHttp"),
        patch("custom_components.thermia_cloud.config_flow.ThermiaApi", _Api),
    ):
        probe = await async_probe(hass, " Mail@Example.invalid ", "pw")
    assert probe.subject == expected and probe.refresh_token == "rt"
    assert [i.id for i in probe.installations] == [1]
