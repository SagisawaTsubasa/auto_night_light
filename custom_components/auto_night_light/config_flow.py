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
    CONF_OVERRIDES,
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
    OVR_BRIGHTNESS,
    OVR_COLOR_TEMP_KELVIN,
    OVR_DAY_BRIGHTNESS,
    OVR_DAY_COLOR_TEMP_KELVIN,
)

OVR_ENABLE = "ovr_enable"


def _kelvin_selector(key: str, default: int) -> tuple:
    return vol.Required(key, default=default), NumberSelector(
        NumberSelectorConfig(
            min=1500, max=6500, step=100, unit_of_measurement="K",
            mode=NumberSelectorMode.SLIDER,
        )
    )


def _settings_schema(defaults: dict) -> vol.Schema:
    """Build the schema for global target/time settings."""
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
                CONF_BRIGHTNESS, default=defaults.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=100, unit_of_measurement="%",
                    mode=NumberSelectorMode.SLIDER,
                )
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
                NumberSelectorConfig(
                    min=0, max=25, unit_of_measurement="%",
                    mode=NumberSelectorMode.SLIDER,
                )
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
            vol.Required(
                CONF_DAY_ENABLED, default=defaults.get(CONF_DAY_ENABLED, False)
            ): BooleanSelector(),
            vol.Required(
                CONF_DAY_BRIGHTNESS,
                default=defaults.get(CONF_DAY_BRIGHTNESS, DEFAULT_DAY_BRIGHTNESS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=100, unit_of_measurement="%",
                    mode=NumberSelectorMode.SLIDER,
                )
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


def _override_schema(global_settings: dict, current: dict | None) -> vol.Schema:
    """Build the per-light override schema, prefilled from current override or globals."""
    current = current or {}
    enabled = bool(current)
    b = current.get(OVR_BRIGHTNESS, global_settings[CONF_BRIGHTNESS])
    k = current.get(OVR_COLOR_TEMP_KELVIN, global_settings[CONF_COLOR_TEMP_KELVIN])
    db = current.get(OVR_DAY_BRIGHTNESS, global_settings[CONF_DAY_BRIGHTNESS])
    dk = current.get(
        OVR_DAY_COLOR_TEMP_KELVIN, global_settings[CONF_DAY_COLOR_TEMP_KELVIN]
    )
    k_marker, k_sel = _kelvin_selector(OVR_COLOR_TEMP_KELVIN, k)
    dk_marker, dk_sel = _kelvin_selector(OVR_DAY_COLOR_TEMP_KELVIN, dk)
    return vol.Schema(
        {
            vol.Required(OVR_ENABLE, default=enabled): BooleanSelector(),
            vol.Required(OVR_BRIGHTNESS, default=b): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=100, unit_of_measurement="%",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            k_marker: k_sel,
            vol.Required(OVR_DAY_BRIGHTNESS, default=db): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=100, unit_of_measurement="%",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            dk_marker: dk_sel,
        }
    )


async def _per_light_step(flow, user_input, finish):
    """Shared per-light override step logic for config and options flows."""
    if user_input is not None:
        entity = flow._lights[flow._idx]
        if user_input.get(OVR_ENABLE):
            flow._overrides[entity] = {
                OVR_BRIGHTNESS: user_input[OVR_BRIGHTNESS],
                OVR_COLOR_TEMP_KELVIN: user_input[OVR_COLOR_TEMP_KELVIN],
                OVR_DAY_BRIGHTNESS: user_input[OVR_DAY_BRIGHTNESS],
                OVR_DAY_COLOR_TEMP_KELVIN: user_input[OVR_DAY_COLOR_TEMP_KELVIN],
            }
        else:
            flow._overrides.pop(entity, None)
        flow._idx += 1

    if flow._idx >= len(flow._lights):
        return await finish()

    entity = flow._lights[flow._idx]
    return flow.async_show_form(
        step_id="per_light",
        data_schema=_override_schema(flow._settings, flow._overrides.get(entity)),
        description_placeholders={
            "entity": entity,
            "position": f"{flow._idx + 1}/{len(flow._lights)}",
        },
    )


class AutoNightLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 2

    def __init__(self) -> None:
        """Store intermediate data between steps."""
        self._lights: list[str] = []
        self._settings: dict = {}
        self._overrides: dict[str, dict] = {}
        self._idx: int = 0

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
        """Step 2: global time and target parameters."""
        if user_input is not None:
            self._settings = user_input
            self._idx = 0
            return await self.async_step_per_light()
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema({})
        )

    async def async_step_per_light(self, user_input=None) -> ConfigFlowResult:
        """Step 3: optional per-light overrides."""

        async def _finish():
            data = {
                CONF_LIGHTS: self._lights,
                **self._settings,
                CONF_OVERRIDES: self._overrides,
            }
            return self.async_create_entry(title="自动夜灯", data=data)

        return await _per_light_step(self, user_input, _finish)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return AutoNightLightOptionsFlow(config_entry)


class AutoNightLightOptionsFlow(OptionsFlow):
    """Allow re-editing lights, settings and per-light overrides."""

    def __init__(self, config_entry) -> None:
        """Store the config entry."""
        self._entry = config_entry
        self._lights: list[str] = []
        self._settings: dict = {}
        self._overrides: dict[str, dict] = {}
        self._idx: int = 0

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Step 1: re-pick lights, prefilled with current values."""
        errors = {}
        current = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            if user_input.get(CONF_LIGHTS):
                self._lights = user_input[CONF_LIGHTS]
                self._overrides = {
                    k: v
                    for k, v in current.get(CONF_OVERRIDES, {}).items()
                    if k in self._lights
                }
                return await self.async_step_settings()
            errors["base"] = "no_lights"
        return self.async_show_form(
            step_id="init", data_schema=_lights_schema(current), errors=errors
        )

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        """Step 2: edit global settings, prefilled with current values."""
        current = {**self._entry.data, **self._entry.options}
        if user_input is not None:
            self._settings = user_input
            self._idx = 0
            return await self.async_step_per_light()
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(current)
        )

    async def async_step_per_light(self, user_input=None) -> ConfigFlowResult:
        """Step 3: optional per-light overrides."""

        async def _finish():
            options = {
                CONF_LIGHTS: self._lights,
                **self._settings,
                CONF_OVERRIDES: self._overrides,
            }
            return self.async_create_entry(title="", data=options)

        return await _per_light_step(self, user_input, _finish)
