from collections.abc import AsyncIterator

import aiohttp
import pytest

from custom_components.thermia_cloud.client.api import ThermiaApi
from custom_components.thermia_cloud.client.auth import ThermiaAuth
from custom_components.thermia_cloud.client.config import ThermiaConfig
from custom_components.thermia_cloud.client.http import ThermiaHttp
from custom_components.thermia_cloud.client.sources import PollingSource

from .conftest import AUTH_PATH, FakeCloud, Reply, load_group


@pytest.fixture
async def api(config: ThermiaConfig, cloud: FakeCloud) -> AsyncIterator[ThermiaApi]:
    cloud.on("POST", f"{AUTH_PATH}/oauth2/v2.0/token", cloud.token())
    auth = ThermiaAuth(config, "u", "p", refresh_token="r0")
    async with aiohttp.ClientSession() as session:
        yield ThermiaApi(ThermiaHttp(session, auth, config.api_base_url))
    await auth.close()


async def test_polling_merges_groups_and_skips_empty(api: ThermiaApi, cloud: FakeCloud) -> None:
    base = "/api/v1/Registers/Installations/7/Groups"
    cloud.on("GET", f"{base}/REG_GROUP_HOT_WATER", Reply(body=load_group("REG_GROUP_HOT_WATER")))
    cloud.on(
        "GET", f"{base}/REG_GROUP_TEMPERATURES", Reply(body=load_group("REG_GROUP_TEMPERATURES"))
    )
    cloud.on("GET", f"{base}/REG_GROUP_POOL", Reply(body=[]))
    snapshot = await PollingSource(api, 7).fetch(
        ["REG_GROUP_HOT_WATER", "REG_GROUP_POOL", "REG_GROUP_TEMPERATURES"]
    )
    expected = len(load_group("REG_GROUP_HOT_WATER")) + len(load_group("REG_GROUP_TEMPERATURES"))
    assert len(snapshot.values) == expected
