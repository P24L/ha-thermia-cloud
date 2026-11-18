"""Connection, last contact and alarm entities."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.thermia_cloud.client.errors import NetworkError
from custom_components.thermia_cloud.const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DOMAIN,
)

from .fakes import INSTALLATION_ID, FakeApi, FakeAuth


@pytest.fixture
def api() -> FakeApi:
    return FakeApi()


@pytest.fixture(autouse=True)
def fake_client(api: FakeApi):  # type: ignore[no-untyped-def]
    with patch(
        "custom_components.thermia_cloud.async_build_client",
        side_effect=lambda *_: (None, FakeAuth(), api),
    ):
        yield


async def setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="sub-1",
        data={CONF_USERNAME: "u", CONF_PASSWORD: "p", CONF_REFRESH_TOKEN: "r"},
        options={CONF_INSTALLATIONS: [INSTALLATION_ID], CONF_SCAN_INTERVAL: 60},
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def state(hass: HomeAssistant, platform: str, key: str):  # type: ignore[no-untyped-def]
    eid = er.async_get(hass).async_get_entity_id(platform, DOMAIN, f"{INSTALLATION_ID}_{key}")
    assert eid, key
    return hass.states.get(eid)


async def poll(hass: HomeAssistant, freezer, minutes: float) -> None:  # type: ignore[no-untyped-def]
    freezer.tick(timedelta(minutes=minutes))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_info_entities_exist_with_the_installation_status(hass: HomeAssistant) -> None:
    await setup(hass)
    assert state(hass, "binary_sensor", "connected").state == "on"
    assert state(hass, "binary_sensor", "active_alarm").state == "off"
    assert state(hass, "sensor", "alarm_count").state == "0"
    # lastOnline is UTC; the sensor is a timezone-aware timestamp
    assert state(hass, "sensor", "last_contact").state == "2026-11-18T18:16:39+00:00"
    registry = er.async_get(hass)
    for platform, key in (("sensor", "last_contact"), ("binary_sensor", "connected")):
        entry = registry.async_get(
            registry.async_get_entity_id(platform, DOMAIN, f"{INSTALLATION_ID}_{key}")
        )
        assert entry.entity_category == "diagnostic"


async def test_alarms_and_the_connection_follow_the_status(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    await setup(hass)
    api.active_alarms = 2
    api.online = False
    api.last_online = "2026-11-18T19:00:00"
    await poll(hass, freezer, 1)  # within five minutes the status is not re-read yet
    assert state(hass, "binary_sensor", "active_alarm").state == "off"
    await poll(hass, freezer, 5)
    assert state(hass, "binary_sensor", "active_alarm").state == "on"
    assert state(hass, "sensor", "alarm_count").state == "2"
    assert state(hass, "binary_sensor", "connected").state == "off"
    assert state(hass, "sensor", "last_contact").state == "2026-11-18T19:00:00+00:00"


async def test_a_failing_status_read_never_fails_the_poll(
    hass: HomeAssistant, api: FakeApi, freezer
) -> None:
    await setup(hass)
    api.status_error = NetworkError("down")
    api.active_alarms = 5
    await poll(hass, freezer, 6)
    # the register values still arrive and the alarm entity keeps its last known state
    assert state(hass, "binary_sensor", "active_alarm").state == "off"
    assert state(hass, "sensor", "alarm_count").state != "unavailable"
