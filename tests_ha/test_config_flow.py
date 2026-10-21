"""Guard selection validation, singleton setup and persisted options."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def test_user_recovers_from_empty_selection(hass):
    result = await hass.config_entries.flow.async_init(
        "localtrack", context={"source": "user"}
    )
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": []}
    )
    assert result["errors"] == {"entities": "no_entities"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"entities": ["person.example"], "retention_days": 30}
    )
    assert result["type"] == "create_entry"
    assert result["result"].unique_id == "localtrack"
    assert result["data"] == {"entities": ["person.example"], "retention_days": 30}


@pytest.mark.parametrize("unique_id", [None, "localtrack"])
async def test_singleton_including_legacy_entry(hass, unique_id):
    entry = MockConfigEntry(
        domain="localtrack", unique_id=unique_id, data={"entities": ["person.example"]}
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        "localtrack", context={"source": "user"}
    )
    assert result["reason"] == "single_instance_allowed"


async def test_options_recover_and_persist(hass):
    entry = MockConfigEntry(
        domain="localtrack",
        data={"entities": ["person.example"]},
        options={"retention_days": 40},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "init"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"entities": []}
    )
    assert result["errors"] == {"entities": "no_entities"}
    settings = {
        "entities": ["person.other"],
        "retention_days": 50,
        "min_distance_m": 25,
        "min_interval_s": 60,
        "downsample_after_days": 10,
        "downsample_interval_s": 120,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], settings
    )
    assert result["type"] == "create_entry"
    assert entry.options == settings
