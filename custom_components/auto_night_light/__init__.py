"""HA Auto Night Light integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, SERVICE_TRIGGER_NOW
from .manager import NightLightManager

_LOGGER = logging.getLogger(__name__)


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
