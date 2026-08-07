"""HA Auto Night Light integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    ANCHOR_FIXED,
    ANCHOR_SUNRISE,
    ANCHOR_SUNSET,
    CONF_BRIGHTNESS,
    CONF_CUSTOM_PER_LIGHT,
    CONF_DAY_BRIGHTNESS,
    CONF_END_MODE,
    CONF_END_OFFSET,
    CONF_EXTRA_COUNT,
    CONF_EXTRAS,
    CONF_OVERRIDES,
    CONF_START_MODE,
    CONF_START_OFFSET,
    CONF_TOLERANCE_BRIGHTNESS,
    DEFAULT_EXTRA_BRIGHTNESS,
    DEFAULT_EXTRA_COLOR_TEMP_KELVIN,
    DOMAIN,
    EXTRA_BRIGHTNESS,
    EXTRA_COLOR_TEMP_KELVIN,
    EXTRA_NAME,
    EXTRA_START,
    OVR_BRIGHTNESS,
    OVR_DAY_BRIGHTNESS,
    OVR_EXTRA_BRIGHTNESS,
    OVR_EXTRA_COLOR_TEMP_KELVIN,
    OVR_EXTRAS,
    SERVICE_TRIGGER_NOW,
)
from .manager import NightLightManager

_LOGGER = logging.getLogger(__name__)


def _pct(v) -> int:
    """Convert a legacy 1-255 value to percent; leave small values untouched."""
    if isinstance(v, (int, float)) and v > 100:
        return max(1, round(v / 255 * 100))
    return v


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entries to the current version (v5)."""
    if entry.version >= 5:
        return True
    data = dict(entry.data)
    options = dict(entry.options)
    if entry.version < 2:
        _LOGGER.info("Migrating auto night light entry to v2 (brightness percent)")
        for store in (data, options):
            for key in (CONF_BRIGHTNESS, CONF_DAY_BRIGHTNESS):
                if key in store:
                    store[key] = _pct(store[key])
            if CONF_TOLERANCE_BRIGHTNESS in store:
                store[CONF_TOLERANCE_BRIGHTNESS] = _pct(store[CONF_TOLERANCE_BRIGHTNESS])
            for ovr in store.get(CONF_OVERRIDES, {}).values():
                for key in (OVR_BRIGHTNESS, OVR_DAY_BRIGHTNESS):
                    if key in ovr:
                        ovr[key] = _pct(ovr[key])
    if entry.version < 4:
        _LOGGER.info("Migrating auto night light entry to v4 (sun sources/extra list)")
        for store in (data, options):
            # v3 日出日落：use_sun + 单一偏移 -> 来源枚举 + 双偏移
            use_sun = store.pop("use_sun", False)
            store.setdefault("sun_source", "builtin" if use_sun else "none")
            old_offset = store.pop("sun_offset", 0)
            store.setdefault("sunset_offset", old_offset)
            store.setdefault("sunrise_offset", old_offset)
            # v3 单一额外时段 -> 额外时段列表
            store.pop("extra_enabled", None)
            store.pop("extra_end", None)
            if CONF_EXTRAS not in store:
                old_start = store.pop("extra_start", None)
                if old_start is not None:
                    store[CONF_EXTRAS] = [
                        {
                            EXTRA_NAME: "",
                            EXTRA_START: old_start,
                            EXTRA_BRIGHTNESS: store.pop(
                                "extra_brightness", DEFAULT_EXTRA_BRIGHTNESS
                            ),
                            EXTRA_COLOR_TEMP_KELVIN: store.pop(
                                "extra_color_temp_kelvin", DEFAULT_EXTRA_COLOR_TEMP_KELVIN
                            ),
                        }
                    ]
                    store[CONF_EXTRA_COUNT] = 1
                else:
                    store.setdefault(CONF_EXTRAS, [])
                    store.setdefault(CONF_EXTRA_COUNT, 0)
            # v3 布尔逐灯开关 -> 逐灯列表
            custom = store.get(CONF_CUSTOM_PER_LIGHT)
            if isinstance(custom, bool):
                store[CONF_CUSTOM_PER_LIGHT] = (
                    list(store.get(CONF_OVERRIDES, {})) if custom else []
                )
            # v3 逐灯覆盖的单一时段字段 -> 列表键
            for ovr in store.get(CONF_OVERRIDES, {}).values():
                eb = ovr.pop("extra_brightness", None)
                ek = ovr.pop("extra_color_temp_kelvin", None)
                if eb is not None and ek is not None:
                    ovr[OVR_EXTRAS] = {
                        "0": {
                            OVR_EXTRA_BRIGHTNESS: eb,
                            OVR_EXTRA_COLOR_TEMP_KELVIN: ek,
                        }
                    }
    if entry.version < 5:
        _LOGGER.info("Migrating auto night light entry to v5 (per-anchor sources)")
        for store in (data, options):
            # v4 全局时间来源 -> 夜间开始/结束各自独立来源
            source = store.pop("sun_source", "none")
            sunset_offset = store.pop("sunset_offset", 0)
            sunrise_offset = store.pop("sunrise_offset", 0)
            if source == "none":
                store.setdefault(CONF_START_MODE, ANCHOR_FIXED)
                store.setdefault(CONF_END_MODE, ANCHOR_FIXED)
            else:
                store.setdefault(CONF_START_MODE, ANCHOR_SUNSET)
                store.setdefault(CONF_END_MODE, ANCHOR_SUNRISE)
            store.setdefault(CONF_START_OFFSET, sunset_offset)
            store.setdefault(CONF_END_OFFSET, sunrise_offset)
    hass.config_entries.async_update_entry(
        entry, data=data, options=options, version=5
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    manager = NightLightManager(hass, entry)
    manager.start()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = manager
    entry.async_on_unload(manager.stop)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if not hass.services.has_service(DOMAIN, SERVICE_TRIGGER_NOW):

        async def _handle_trigger_now(call: ServiceCall) -> None:
            for mgr in hass.data.get(DOMAIN, {}).values():
                await mgr.async_trigger(reason="service")

        hass.services.async_register(DOMAIN, SERVICE_TRIGGER_NOW, _handle_trigger_now)

    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    manager: NightLightManager = hass.data[DOMAIN].pop(entry.entry_id)
    manager.stop()
    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_TRIGGER_NOW)
        hass.data.pop(DOMAIN)
    return True
