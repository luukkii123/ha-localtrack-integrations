"""Setup dialog: which entities to record, and how much history to keep."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.helpers import selector

from .const import (
    CONF_DOWNSAMPLE_AFTER_DAYS,
    CONF_DOWNSAMPLE_INTERVAL_S,
    CONF_ENTITIES,
    CONF_MIN_DISTANCE_M,
    CONF_MIN_INTERVAL_S,
    CONF_RETENTION_DAYS,
    DEFAULT_DOWNSAMPLE_AFTER_DAYS,
    DEFAULT_DOWNSAMPLE_INTERVAL_S,
    DEFAULT_MIN_DISTANCE_M,
    DEFAULT_MIN_INTERVAL_S,
    DEFAULT_RETENTION_DAYS,
    DOMAIN,
    MAX_DISTANCE_LIMIT_M,
    MAX_DOWNSAMPLE_AFTER_DAYS,
    MAX_DOWNSAMPLE_INTERVAL_S,
    MAX_INTERVAL_LIMIT_S,
    MAX_RETENTION_DAYS,
    MIN_DISTANCE_LIMIT_M,
    MIN_DOWNSAMPLE_AFTER_DAYS,
    MIN_DOWNSAMPLE_INTERVAL_S,
    MIN_INTERVAL_LIMIT_S,
    MIN_RETENTION_DAYS,
    TRACKED_DOMAINS,
)

TITLE = "Local Track"

ENTITY_SELECTOR = selector.EntitySelector(
    selector.EntitySelectorConfig(domain=list(TRACKED_DOMAINS), multiple=True)
)


def _number(minimum: float, maximum: float, unit: str) -> selector.NumberSelector:
    """A plain number box — sliders are useless over four orders of magnitude."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=selector.NumberSelectorMode.BOX,
            unit_of_measurement=unit,
        )
    )


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITIES): ENTITY_SELECTOR,
        vol.Optional(CONF_RETENTION_DAYS, default=DEFAULT_RETENTION_DAYS): _number(
            MIN_RETENTION_DAYS, MAX_RETENTION_DAYS, "d"
        ),
    }
)


class LocalTrackConfigFlow(ConfigFlow, domain=DOMAIN):
    """Creates the single Local Track entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for entities and retention.

        Only one entry is allowed: there is one database file and one websocket
        command, so a second entry would fight the first over both.
        """
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        # One entry, one database file: the domain itself is the stable id.
        # It survives a rename or an IP change, unlike anything host-derived.
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_ENTITIES):
                errors[CONF_ENTITIES] = "no_entities"
            else:
                return self.async_create_entry(title=TITLE, data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(entry: Any) -> LocalTrackOptionsFlow:
        """Offer the options dialog."""
        return LocalTrackOptionsFlow()


class LocalTrackOptionsFlow(OptionsFlow):
    """Change entities, retention and the dedupe thresholds afterwards."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Everything is editable — the entry has no immutable key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_ENTITIES):
                errors[CONF_ENTITIES] = "no_entities"
            else:
                return self.async_create_entry(data=user_input)

        current = {**self.config_entry.data, **self.config_entry.options}
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ENTITIES,
                    default=current.get(CONF_ENTITIES, []),
                ): ENTITY_SELECTOR,
                vol.Optional(
                    CONF_RETENTION_DAYS,
                    default=current.get(CONF_RETENTION_DAYS, DEFAULT_RETENTION_DAYS),
                ): _number(MIN_RETENTION_DAYS, MAX_RETENTION_DAYS, "d"),
                vol.Optional(
                    CONF_MIN_DISTANCE_M,
                    default=current.get(CONF_MIN_DISTANCE_M, DEFAULT_MIN_DISTANCE_M),
                ): _number(MIN_DISTANCE_LIMIT_M, MAX_DISTANCE_LIMIT_M, "m"),
                vol.Optional(
                    CONF_MIN_INTERVAL_S,
                    default=current.get(CONF_MIN_INTERVAL_S, DEFAULT_MIN_INTERVAL_S),
                ): _number(MIN_INTERVAL_LIMIT_S, MAX_INTERVAL_LIMIT_S, "s"),
                vol.Optional(
                    CONF_DOWNSAMPLE_AFTER_DAYS,
                    default=current.get(
                        CONF_DOWNSAMPLE_AFTER_DAYS, DEFAULT_DOWNSAMPLE_AFTER_DAYS
                    ),
                ): _number(MIN_DOWNSAMPLE_AFTER_DAYS, MAX_DOWNSAMPLE_AFTER_DAYS, "d"),
                vol.Optional(
                    CONF_DOWNSAMPLE_INTERVAL_S,
                    default=current.get(
                        CONF_DOWNSAMPLE_INTERVAL_S, DEFAULT_DOWNSAMPLE_INTERVAL_S
                    ),
                ): _number(MIN_DOWNSAMPLE_INTERVAL_S, MAX_DOWNSAMPLE_INTERVAL_S, "s"),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )
