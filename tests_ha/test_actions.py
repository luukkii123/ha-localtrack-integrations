"""An unloaded entry must still expose an action with a useful failure."""

import custom_components.localtrack as integration
import pytest
from homeassistant.exceptions import ServiceValidationError


async def test_action_registered_without_loaded_entry(hass):
    assert await integration.async_setup(hass, {})
    assert hass.services.has_service("localtrack", "import_history")
    with pytest.raises(ServiceValidationError, match="not set up"):
        await hass.services.async_call(
            "localtrack", "import_history", {}, blocking=True
        )


async def test_action_rejects_untracked_entity(hass):
    from unittest.mock import AsyncMock

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="localtrack", data={"entities": ["person.example"]})
    entry.add_to_hass(hass)
    runtime = integration.LocalTrackRuntime(hass, entry, AsyncMock())
    hass.data["localtrack"] = {entry.entry_id: runtime}
    await integration.async_setup(hass, {})
    with pytest.raises(ServiceValidationError, match="does not record"):
        await hass.services.async_call(
            "localtrack", "import_history", {"entity_id": "person.other"}, blocking=True
        )
    await integration.async_unload_entry(hass, entry)
    assert hass.services.has_service("localtrack", "import_history")
    with pytest.raises(ServiceValidationError, match="not set up"):
        await hass.services.async_call(
            "localtrack", "import_history", {}, blocking=True
        )
