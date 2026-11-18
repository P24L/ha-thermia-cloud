"""The blueprints load with Home Assistant's own blueprint model and name our entities."""

from pathlib import Path

import pytest
from homeassistant.components.automation.config import AUTOMATION_BLUEPRINT_SCHEMA
from homeassistant.components.blueprint import models
from homeassistant.util import yaml

BLUEPRINTS = sorted((Path(__file__).parent.parent / "blueprints" / "automation").rglob("*.yaml"))


def test_there_are_blueprints() -> None:
    assert {p.stem for p in BLUEPRINTS} >= {"alarm_notification", "connection_lost"}


@pytest.mark.parametrize("path", BLUEPRINTS, ids=lambda p: p.stem)
def test_blueprint_is_valid(path: Path) -> None:
    blueprint = models.Blueprint(
        yaml.load_yaml_dict(str(path)),
        expected_domain="automation",
        schema=AUTOMATION_BLUEPRINT_SCHEMA,
    )
    assert blueprint.name and blueprint.inputs
    text = path.read_text()
    assert "integration: thermia_cloud" in text  # entity pickers only offer our entities
