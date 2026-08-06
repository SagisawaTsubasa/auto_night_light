"""HA Auto Night Light integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import (
    CONF_BRIGHTNESS,
    CONF_DAY_BRIGHTNESS,
    CONF_OVERRIDES,
    CONF_TOLERANCE_BRIGHTNESS,
    DOMAIN,
    OVR_BRIGHTNESS,
    OVR_DAY_BRIGHTNESS,
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
    """Migrate v1 (brightness 1-255) -> v2 (percent) -> v3 (sun/extra periods)."""
    if entry.version >= 3:
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
    _LOGGER.info("Migrating auto night light entry to v3 (sun/extra periods)")
    # v3 新增键均带默认值；清理已废弃的 extra_end 键
    for store in (data, options):
        store.pop("extra_end", None)
    hass.config_entries.async_update_entry(
        entry, data=data, options=options, version=3
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
