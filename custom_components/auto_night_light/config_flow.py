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
    CONF_CUSTOM_PER_LIGHT,
    CONF_DAY_BRIGHTNESS,
    CONF_DAY_COLOR_TEMP_KELVIN,
    CONF_DAY_ENABLED,
    CONF_END_TIME,
    CONF_EXTRA_BRIGHTNESS,
    CONF_EXTRA_COLOR_TEMP_KELVIN,
    CONF_EXTRA_ENABLED,
    CONF_EXTRA_START,
    CONF_LIGHTS,
    CONF_ONLY_WHEN_ON,
    CONF_OVERRIDES,
    CONF_SETTLE_DELAY,
    CONF_SUN_OFFSET,
    CONF_TOLERANCE_BRIGHTNESS,
    CONF_TOLERANCE_KELVIN,
    CONF_TRIGGER_TIME,
    CONF_TURN_ON_LISTEN,
    CONF_USE_SUN,
    CONF_VERIFY_DELAY,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_TEMP_KELVIN,
    DEFAULT_DAY_BRIGHTNESS,
    DEFAULT_DAY_COLOR_TEMP_KELVIN,
    DEFAULT_END_TIME,
    DEFAULT_EXTRA_BRIGHTNESS,
    DEFAULT_EXTRA_COLOR_TEMP_KELVIN,
    DEFAULT_EXTRA_START,
    DEFAULT_SETTLE_DELAY,
    DEFAULT_SUN_OFFSET,
    DEFAULT_TOLERANCE_BRIGHTNESS,
    DEFAULT_TOLERANCE_KELVIN,
    DEFAULT_TURN_ON_LISTEN,
    DEFAULT_VERIFY_DELAY,
    DOMAIN,
    OVR_BRIGHTNESS,
    OVR_COLOR_TEMP_KELVIN,
    OVR_DAY_BRIGHTNESS,
    OVR_DAY_COLOR_TEMP_KELVIN,
    OVR_EXTRA_BRIGHTNESS,
    OVR_EXTRA_COLOR_TEMP_KELVIN,
)

OVR_ENABLE = "ovr_enable"


def _pct_selector(key: str, default: int) -> tuple:
    return vol.Required(key, default=default), NumberSelector(
        NumberSelectorConfig(
            min=1, max=100, unit_of_measurement="%",
            mode=NumberSelectorMode.SLIDER,
        )
    )


def _kelvin_selector(key: str, default: int) -> tuple:
    return vol.Required(key, default=default), NumberSelector(
        NumberSelectorConfig(
            min=1500, max=6500, step=100, unit_of_measurement="K",
            mode=NumberSelectorMode.SLIDER,
        )
    )


def _add_period_fields(
    schema: dict, b_key: str, k_key: str, defaults: dict,
    def_b: int, def_k: int,
) -> None:
    """Add brightness/kelvin fields for one period to a schema dict."""
    b_marker, b_sel = _pct_selector(b_key, defaults.get(b_key, def_b))
    k_marker, k_sel = _kelvin_selector(k_key, defaults.get(k_key, def_k))
    schema[b_marker] = b_sel
    schema[k_marker] = k_sel


def _time_schema(defaults: dict) -> vol.Schema:
    """Step 1 schema: period times, sun integration toggle, extra/day toggles."""
    return vol.Schema(
        {
            vol.Required(
                CONF_USE_SUN, default=defaults.get(CONF_USE_SUN, False)
            ): BooleanSelector(),
            vol.Required(
                CONF_SUN_OFFSET,
                default=defaults.get(CONF_SUN_OFFSET, DEFAULT_SUN_OFFSET),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=-120, max=120, step=5, unit_of_measurement="min",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_TRIGGER_TIME, default=defaults.get(CONF_TRIGGER_TIME, "22:00:00")
            ): TimeSelector(),
            vol.Required(
                CONF_END_TIME, default=defaults.get(CONF_END_TIME, DEFAULT_END_TIME)
            ): TimeSelector(),
            vol.Required(
                CONF_EXTRA_ENABLED,
                default=defaults.get(CONF_EXTRA_ENABLED, False),
            ): BooleanSelector(),
            vol.Required(
                CONF_EXTRA_START,
                default=defaults.get(CONF_EXTRA_START, DEFAULT_EXTRA_START),
            ): TimeSelector(),
            vol.Required(
                CONF_DAY_ENABLED, default=defaults.get(CONF_DAY_ENABLED, False)
            ): BooleanSelector(),
        }
    )


def _lights_schema(defaults: dict) -> vol.Schema:
    """Step 2 schema: light selection + per-light extra settings toggle."""
    return vol.Schema(
        {
            vol.Required(
                CONF_LIGHTS, default=defaults.get(CONF_LIGHTS, [])
            ): EntitySelector(
                EntitySelectorConfig(domain="light", multiple=True)
            ),
            vol.Required(
                CONF_CUSTOM_PER_LIGHT,
                default=defaults.get(
                    CONF_CUSTOM_PER_LIGHT, bool(defaults.get(CONF_OVERRIDES))
                ),
            ): BooleanSelector(),
        }
    )


def _settings_schema(
    defaults: dict, extra_enabled: bool, day_enabled: bool
) -> vol.Schema:
    """Step 3 schema: per-period brightness/kelvin plus advanced parameters."""
    schema: dict = {}
    _add_period_fields(
        schema, CONF_BRIGHTNESS, CONF_COLOR_TEMP_KELVIN,
        defaults, DEFAULT_BRIGHTNESS, DEFAULT_COLOR_TEMP_KELVIN,
    )
    if extra_enabled:
        _add_period_fields(
            schema, CONF_EXTRA_BRIGHTNESS, CONF_EXTRA_COLOR_TEMP_KELVIN,
            defaults, DEFAULT_EXTRA_BRIGHTNESS, DEFAULT_EXTRA_COLOR_TEMP_KELVIN,
        )
    if day_enabled:
        _add_period_fields(
            schema, CONF_DAY_BRIGHTNESS, CONF_DAY_COLOR_TEMP_KELVIN,
            defaults, DEFAULT_DAY_BRIGHTNESS, DEFAULT_DAY_COLOR_TEMP_KELVIN,
        )
    schema.update(
        {
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
                CONF_SETTLE_DELAY,
                default=defaults.get(CONF_SETTLE_DELAY, DEFAULT_SETTLE_DELAY),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=10, step=0.5, unit_of_measurement="s",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            vol.Required(
                CONF_TURN_ON_LISTEN,
                default=defaults.get(CONF_TURN_ON_LISTEN, DEFAULT_TURN_ON_LISTEN),
            ): BooleanSelector(),
            vol.Required(
                CONF_ONLY_WHEN_ON, default=defaults.get(CONF_ONLY_WHEN_ON, False)
            ): BooleanSelector(),
        }
    )
    return vol.Schema(schema)


def _override_schema(
    settings: dict, current: dict | None, extra_enabled: bool, day_enabled: bool
) -> vol.Schema:
    """Per-light override schema, prefilled from current override or globals."""
    current = current or {}
    enabled = bool(current)
    schema: dict = {vol.Required(OVR_ENABLE, default=enabled): BooleanSelector()}
    _add_period_fields(
        schema, OVR_BRIGHTNESS, OVR_COLOR_TEMP_KELVIN,
        current, settings[CONF_BRIGHTNESS], settings[CONF_COLOR_TEMP_KELVIN],
    )
    if extra_enabled:
        _add_period_fields(
            schema, OVR_EXTRA_BRIGHTNESS, OVR_EXTRA_COLOR_TEMP_KELVIN,
            current,
            settings.get(CONF_EXTRA_BRIGHTNESS, DEFAULT_EXTRA_BRIGHTNESS),
            settings.get(CONF_EXTRA_COLOR_TEMP_KELVIN, DEFAULT_EXTRA_COLOR_TEMP_KELVIN),
        )
    if day_enabled:
        _add_period_fields(
            schema, OVR_DAY_BRIGHTNESS, OVR_DAY_COLOR_TEMP_KELVIN,
            current,
            settings.get(CONF_DAY_BRIGHTNESS, DEFAULT_DAY_BRIGHTNESS),
            settings.get(CONF_DAY_COLOR_TEMP_KELVIN, DEFAULT_DAY_COLOR_TEMP_KELVIN),
        )
    return vol.Schema(schema)


async def _per_light_step(flow, user_input, finish):
    """Shared per-light override step logic for config and options flows."""
    if user_input is not None:
        entity = flow._lights[flow._idx]
        if user_input.get(OVR_ENABLE):
            ovr = {
                OVR_BRIGHTNESS: user_input[OVR_BRIGHTNESS],
                OVR_COLOR_TEMP_KELVIN: user_input[OVR_COLOR_TEMP_KELVIN],
            }
            if flow._extra_enabled:
                ovr[OVR_EXTRA_BRIGHTNESS] = user_input[OVR_EXTRA_BRIGHTNESS]
                ovr[OVR_EXTRA_COLOR_TEMP_KELVIN] = user_input[OVR_EXTRA_COLOR_TEMP_KELVIN]
            if flow._day_enabled:
                ovr[OVR_DAY_BRIGHTNESS] = user_input[OVR_DAY_BRIGHTNESS]
                ovr[OVR_DAY_COLOR_TEMP_KELVIN] = user_input[OVR_DAY_COLOR_TEMP_KELVIN]
            flow._overrides[entity] = ovr
        else:
            flow._overrides.pop(entity, None)
        flow._idx += 1

    if flow._idx >= len(flow._lights):
        return await finish()

    entity = flow._lights[flow._idx]
    return flow.async_show_form(
        step_id="per_light",
        data_schema=_override_schema(
            flow._settings,
            flow._overrides.get(entity),
            flow._extra_enabled,
            flow._day_enabled,
        ),
        description_placeholders={
            "entity": entity,
            "position": f"{flow._idx + 1}/{len(flow._lights)}",
        },
    )


class AutoNightLightConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial config flow."""

    VERSION = 3

    def __init__(self) -> None:
        """Store intermediate data between steps."""
        self._times: dict = {}
        self._lights: list[str] = []
        self._custom_per_light: bool = False
        self._settings: dict = {}
        self._overrides: dict[str, dict] = {}
        self._idx: int = 0

    @property
    def _extra_enabled(self) -> bool:
        return bool(self._times.get(CONF_EXTRA_ENABLED))

    @property
    def _day_enabled(self) -> bool:
        return bool(self._times.get(CONF_DAY_ENABLED))

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Step 1: time settings (sun toggle, night window, extra period, day)."""
        if user_input is not None:
            self._times = user_input
            return await self.async_step_lights()
        return self.async_show_form(step_id="user", data_schema=_time_schema({}))

    async def async_step_lights(self, user_input=None) -> ConfigFlowResult:
        """Step 2: pick light entities and whether to configure per-light extras."""
        errors = {}
        if user_input is not None:
            if user_input.get(CONF_LIGHTS):
                self._lights = user_input[CONF_LIGHTS]
                self._custom_per_light = user_input[CONF_CUSTOM_PER_LIGHT]
                return await self.async_step_settings()
            errors["base"] = "no_lights"
        return self.async_show_form(
            step_id="lights", data_schema=_lights_schema({}), errors=errors
        )

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        """Step 3: per-period brightness/kelvin and advanced parameters."""
        if user_input is not None:
            self._settings = user_input
            self._idx = 0
            if self._custom_per_light:
                return await self.async_step_per_light()
            return await self._finish()
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(
                {}, self._extra_enabled, self._day_enabled
            ),
        )

    async def async_step_per_light(self, user_input=None) -> ConfigFlowResult:
        """Step 4+: optional per-light overrides."""
        return await _per_light_step(self, user_input, self._finish)

    async def _finish(self) -> ConfigFlowResult:
        data = {
            **self._times,
            CONF_LIGHTS: self._lights,
            CONF_CUSTOM_PER_LIGHT: self._custom_per_light,
            **self._settings,
            CONF_OVERRIDES: self._overrides,
        }
        return self.async_create_entry(title="自动夜灯", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the options flow."""
        return AutoNightLightOptionsFlow(config_entry)


class AutoNightLightOptionsFlow(OptionsFlow):
    """Allow re-editing times, lights, settings and per-light overrides."""

    def __init__(self, config_entry) -> None:
        """Store the config entry."""
        self._entry = config_entry
        self._times: dict = {}
        self._lights: list[str] = []
        self._custom_per_light: bool = False
        self._settings: dict = {}
        self._overrides: dict[str, dict] = {}
        self._idx: int = 0

    @property
    def _current(self) -> dict:
        return {**self._entry.data, **self._entry.options}

    @property
    def _extra_enabled(self) -> bool:
        return bool(self._times.get(CONF_EXTRA_ENABLED))

    @property
    def _day_enabled(self) -> bool:
        return bool(self._times.get(CONF_DAY_ENABLED))

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Step 1: time settings, prefilled with current values."""
        if user_input is not None:
            self._times = user_input
            return await self.async_step_lights()
        return self.async_show_form(
            step_id="init", data_schema=_time_schema(self._current)
        )

    async def async_step_lights(self, user_input=None) -> ConfigFlowResult:
        """Step 2: re-pick lights and per-light toggle, prefilled."""
        errors = {}
        current = self._current
        if user_input is not None:
            if user_input.get(CONF_LIGHTS):
                self._lights = user_input[CONF_LIGHTS]
                self._custom_per_light = user_input[CONF_CUSTOM_PER_LIGHT]
                self._overrides = {
                    k: v
                    for k, v in current.get(CONF_OVERRIDES, {}).items()
                    if k in self._lights
                }
                return await self.async_step_settings()
            errors["base"] = "no_lights"
        return self.async_show_form(
            step_id="lights", data_schema=_lights_schema(current), errors=errors
        )

    async def async_step_settings(self, user_input=None) -> ConfigFlowResult:
        """Step 3: per-period parameters, prefilled with current values."""
        if user_input is not None:
            self._settings = user_input
            self._idx = 0
            if self._custom_per_light:
                return await self.async_step_per_light()
            return await self._finish()
        return self.async_show_form(
            step_id="settings",
            data_schema=_settings_schema(
                self._current, self._extra_enabled, self._day_enabled
            ),
        )

    async def async_step_per_light(self, user_input=None) -> ConfigFlowResult:
        """Step 4+: optional per-light overrides."""
        return await _per_light_step(self, user_input, self._finish)

    async def _finish(self) -> ConfigFlowResult:
        options = {
            **self._times,
            CONF_LIGHTS: self._lights,
            CONF_CUSTOM_PER_LIGHT: self._custom_per_light,
            **self._settings,
            CONF_OVERRIDES: self._overrides,
        }
        return self.async_create_entry(title="", data=options)
