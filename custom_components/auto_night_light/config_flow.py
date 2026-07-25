"""Config flow for HA Auto Night Light."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TimeSelector,
)

from .const import (
    CONF_BRIGHTNESS,
    CONF_COLOR_TEMP_KELVIN,
    CONF_DAY_BRIGHTNESS,
    CONF_DAY_COLOR_TEMP_KELVIN,
    CONF_DAY_ENABLED,
    CONF_END_TIME,
    CONF_LIGHTS,
    CONF_ONLY_WHEN_ON,
    CONF_SETTLE_DELAY,
    CONF_TOLERANCE_BRIGHTNESS,
    CONF_TOLERANCE_KELVIN,
    CONF_TRIGGER_TIME,
    CONF_TURN_ON_LISTEN,
    CONF_VERIFY_DELAY,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_TEMP_KELVIN,
    DEFAULT_DAY_BRIGHTNESS,
    DEFAULT_DAY_COLOR_TEMP_KELVIN,
    DEFAULT_END_TIME,
    DEFAULT_SETTLE_DELAY,
    DEFAULT_TOLERANCE_BRIGHTNESS,
    DEFAULT_TOLERANCE_KELVIN,
    DEFAULT_TURN_ON_LISTEN,
    DEFAULT_VERIFY_DELAY,
    DOMAIN,
)


def _settings_schema(defaults: dict) -> vol.Schema:
    """Build the schema for target/time settings."""
    return vol.Schema(
        {
            vol.Required(
                CONF_TRIGGER_TIME, default=defaults.get(CONF_TRIGGER_TIME, "22:00:00")
            ): TimeSelector(),
            vol.Required(
                CONF_END_TIME, default=defaults.get(CONF_END_TIME, DEFAULT_END_TIME)
            ): TimeSelector(),
            vol.Required(
                CONF_TURN_ON_LISTEN,
                default=defaults.get(CONF_TURN_ON_LISTEN, DEFAULT_TURN_ON_LISTEN),
            ): BooleanSelector(),
            vol.Required(
                CONF_SETTLE_DELAY,
                default=defaults.get(CONF_SETTLE_DELAY, DEFAULT_SETTLE_DELAY),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=10, step=0.5, unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_DAY_ENABLED, default=defaults.get(CONF_DAY_ENABLED, False)
            ): BooleanSelector(),
            vol.Required(
                CONF_DAY_BRIGHTNESS,
                default=defaults.get(CONF_DAY_BRIGHTNESS, DEFAULT_DAY_BRIGHTNESS),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=255, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_DAY_COLOR_TEMP_KELVIN,
                default=defaults.get(
                    CONF_DAY_COLOR_TEMP_KELVIN, DEFAULT_DAY_COLOR_TEMP_KELVIN
                ),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1500, max=6500, step=100, unit_of_measurement="K",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_BRIGHTNESS, default=defaults.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=255, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_COLOR_TEMP_KELVIN,
                default=defaults.get(CONF_COLOR_TEMP_KELVIN, DEFAULT_COLOR_TEMP_KELVIN),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1500, max=6500, step=100, unit_of_measurement="K",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_TOLERANCE_BRIGHTNESS,
                default=defaults.get(CONF_TOLERANCE_BRIGHTNESS, DEFAULT_TOLERANCE_BRIGHTNESS),
            ): NumberSelector(
                NumberSelectorConfig(min=0, max=64, mode=NumberSelectorMode.SLIDER)
            ),
            vol.Required(
                CONF_TOLERANCE_KELVIN,
                default=defaults.get(CONF_TOLERANCE_KELVIN, DEFAULT_TOLERANCE_KELVIN),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=1000, step=50, unit_of_measurement="K",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_VERIFY_DELAY,
                default=defaults.get(CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=60, unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_ONLY_WHEN_ON, default=defaults.get(CONF_ONLY_WHEN_ON, False)
            ): BooleanSelector(),
        }
    )


def _lights_schema(defaults: dict) -> vol.Schema:
    """Build the schema for light selection."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LIGHTS, default=defaults.get(CONF_LIGHTS, [])
            ): EntitySelector(
                EntitySelectorConfig(domain="light", multiple=True)
            ),
        }
    )


class AutoNightLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Store intermediate data between steps."""
        self._lights: list[str] = []

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Step 1: pick light entities."""
        errors = {}
        if user_input is not None:
            if user_input.get(CONF_LIGHTS):
                self._lights = user_input[CONF_LIGHTS]
                return await self.async_step_settings()
            errors["base"] = "no_lights"
        return self.async_show_form(
            step_id="user", data_schema=_lights_schema({}), errors=errors
        )

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        """Step 2: target time, brightness and color temperature."""
        if user_input is not None:
            data = {CONF_LIGHTS: self._lights, **user_input}
            return self.async_create_entry(title="自动夜灯", data=data)
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema({})
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return AutoNightLightOptionsFlow(config_entry)


class AutoNightLightOptionsFlow(OptionsFlow):
    """Allow re-editing lights and settings after creation."""

    def __init__(self, config_entry) -> None:
        """Store the config entry."""
        self._entry = config_entry

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Step 1: re-pick lights, prefilled with current values."""
        errors = {}
        current = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            if user_input.get(CONF_LIGHTS):
                self._lights = user_input[CONF_LIGHTS]
                return await self.async_step_settings()
            errors["base"] = "no_lights"
        return self.async_show_form(
            step_id="init", data_schema=_lights_schema(current), errors=errors
        )

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        """Step 2: edit settings, prefilled with current values."""
        current = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            options = {CONF_LIGHTS: self._lights, **user_input}
            return self.async_create_entry(title="", data=options)
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(current)
        )
