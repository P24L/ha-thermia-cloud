from collections.abc import Iterator
from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thermia_cloud.client.errors import (
    AuthError,
    LoginFlowError,
    NetworkError,
    PolicyAcceptanceError,
)
from custom_components.thermia_cloud.client.models import Installation
from custom_components.thermia_cloud.config_flow import Probe
from custom_components.thermia_cloud.const import (
    CONF_INSTALLATIONS,
    CONF_PASSWORD,
    CONF_REFRESH_TOKEN,
    CONF_USERNAME,
    DOMAIN,
)

CREDS = {CONF_USERNAME: " user@example.invalid ", CONF_PASSWORD: "secret"}


def inst(id_: int, name: str = "Pump") -> Installation:
    return Installation(id_, name, "iTec", True, "1.0", None)


@pytest.fixture(autouse=True)
def no_real_setup() -> Iterator[None]:
    """Setup of the entry arrives with roadmap P4.5; the flow is tested on its own."""
    with patch("custom_components.thermia_cloud.async_setup_entry", create=True, return_value=True):
        yield


def probe(*installations: Installation, subject: str = "sub-1") -> Probe:
    return Probe(subject, "refresh-1", list(installations))


async def start(hass: HomeAssistant):  # type: ignore[no-untyped-def]
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


async def test_single_installation_creates_entry(hass: HomeAssistant) -> None:
    result = await start(hass)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    with patch(
        "custom_components.thermia_cloud.config_flow.async_probe", return_value=probe(inst(7))
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "user@example.invalid"
    assert result["data"] == {
        CONF_USERNAME: "user@example.invalid",
        CONF_PASSWORD: "secret",
        CONF_REFRESH_TOKEN: "refresh-1",
    }
    assert result["options"][CONF_INSTALLATIONS] == [7]
    assert result["result"].unique_id == "sub-1"


async def test_several_installations_ask_which(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch(
        "custom_components.thermia_cloud.config_flow.async_probe",
        return_value=probe(inst(1, "House"), inst(2, "Cottage")),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "installations"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_INSTALLATIONS: ["2"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_INSTALLATIONS] == [2]


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (AuthError("no"), "invalid_auth"),
        (NetworkError("down"), "cannot_connect"),
        (LoginFlowError("html changed"), "cannot_connect"),
        (PolicyAcceptanceError("terms"), "policy_acceptance_required"),
        (RuntimeError("bug"), "unknown"),
    ],
)
async def test_errors_are_shown_and_retry_works(
    hass: HomeAssistant, error: Exception, key: str
) -> None:
    result = await start(hass)
    with patch("custom_components.thermia_cloud.config_flow.async_probe", side_effect=error):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.FORM and result["errors"] == {"base": key}
    with patch(
        "custom_components.thermia_cloud.config_flow.async_probe", return_value=probe(inst(1))
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_same_account_cannot_be_added_twice(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="sub-1", data={}).add_to_hass(hass)
    result = await start(hass)
    with patch(
        "custom_components.thermia_cloud.config_flow.async_probe", return_value=probe(inst(1))
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


async def test_account_without_installations_aborts(hass: HomeAssistant) -> None:
    result = await start(hass)
    with patch("custom_components.thermia_cloud.config_flow.async_probe", return_value=probe()):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "no_installations"
