"""Web layer: snapshot REST view, static assets and the page registration.

Same architecture as the lux_balance page (v0.3.0, review-closed): the page
(``static/page.js`` → ``<anl-page>``) renders inside the Fumiha Hub shell
when it is loaded, or registers a standalone sidebar panel otherwise. The
hub coupling is contract-only (``hass.data["fumiha_hub_registry"]`` + bus
event) — this module never imports ``fumiha_hub``. This integration has ZERO
entity platforms: the page is its only runtime-visual surface.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import (
    HomeAssistantView,
    StaticPathConfig,
    require_admin,
)
from homeassistant.core import (
    EVENT_HOMEASSISTANT_STARTED,
    Event,
    HomeAssistant,
    callback,
)
from homeassistant.loader import async_get_loaded_integration

from .const import DOMAIN
from .manager import NightLightManager

_LOGGER = logging.getLogger(__name__)

WEB_DATA_KEY = f"{DOMAIN}_web_registered"

URL_BASE = "/auto_night_light"
API_BASE = "/api/auto_night_light"

PAGE_ID = "anl.main"
PAGE_TITLE = "夜灯助手"
PAGE_ICON = "mdi:weather-night"
PAGE_ELEMENT = "anl-page"
STANDALONE_PANEL_URL_PATH = "auto-night-light"

REGISTRY_KEY = "fumiha_hub_registry"
BUS_EVENT_PAGE_CHANGED = "fumiha_hub_page_changed"


def _manifest_version(hass: HomeAssistant) -> str:
    try:
        return async_get_loaded_integration(hass, DOMAIN).version or "dev"
    except Exception:  # noqa: BLE001 — version is only a cache buster
        _LOGGER.debug("Could not resolve integration version for page URL")
        return "dev"


def _descriptor(hass: HomeAssistant) -> dict:
    version = _manifest_version(hass)
    return {
        "id": PAGE_ID,
        "title": PAGE_TITLE,
        "icon": PAGE_ICON,
        "order": 20,
        "version": version,
        "module_url": f"{URL_BASE}/page.js?ver={version}",
        "element": PAGE_ELEMENT,
    }


def _fmt_time(t) -> str | None:
    return t.strftime("%H:%M") if t is not None else None


def _serialize_manager(mgr: NightLightManager) -> dict:
    """One manager snapshot; sync reads only, safe in a handler."""
    lights = []
    for entity_id, machine in mgr.machines.items():
        lights.append(
            {
                "entity_id": entity_id,
                "state": machine.state.value,
                "manual_override": machine.manual_override,
                "mismatch_steps": machine.mismatch_steps,
                "target": list(machine.target) if machine.target else None,
                "applied": list(machine.applied) if machine.applied else None,
                "last_error": machine.last_error,
            }
        )
    snap = mgr.anchor_snapshot()
    # Unparseable anchors are already filtered (and warned once) inside
    # anchor_snapshot — the web layer never sees them (ANL-F-013).
    anchors = [
        {"time": _fmt_time(t), "mode": mode}
        for t, mode in snap["anchors"]
        if _fmt_time(t) is not None
    ]
    next_anchor = snap["next_anchor"]
    return {
        "entry_id": mgr.entry.entry_id,
        "title": mgr.entry.title,
        "lights": lights,
        "anchors": anchors,
        "current_mode": snap["current_mode"],
        "next_anchor": next_anchor.isoformat() if next_anchor else None,
        "start_mode": mgr.start_mode,
        "end_mode": mgr.end_mode,
        "transition_enabled": mgr.transition_enabled,
        "day_enabled": mgr.day_enabled,
        "respect_manual": mgr.respect_manual,
    }


class SnapshotView(HomeAssistantView):
    """GET /api/auto_night_light/snapshot — all managers in one payload."""

    url = f"{API_BASE}/snapshot"
    name = "api:auto_night_light:snapshot"
    requires_auth = True

    @require_admin
    async def get(self, request: web.Request) -> web.Response:
        hass = request.app["hass"]
        managers: dict = hass.data.get(DOMAIN) or {}
        payload = [_serialize_manager(mgr) for mgr in managers.values()]
        payload.sort(key=lambda m: m["title"])
        return web.json_response({"managers": payload})


def _register_page(hass: HomeAssistant, flags: dict) -> None:
    """(Re-)register the page in whichever mode fits right now.

    Same re-evaluation contract as lux_balance (probe = registry key
    existence, maintained truthfully by the hub).
    """
    mode = "hub" if REGISTRY_KEY in hass.data else "standalone"
    current = flags.get("page_registered")
    if current == mode:
        return
    if current is not None:
        _teardown_page(hass, flags)

    if mode == "hub":
        registry = hass.data.setdefault(REGISTRY_KEY, {})
        if PAGE_ID not in registry:
            registry[PAGE_ID] = _descriptor(hass)
            hass.bus.async_fire(
                BUS_EVENT_PAGE_CHANGED, {"id": PAGE_ID, "action": "register"}
            )
            _LOGGER.info("夜灯助手页面已注册到文羽面板壳")
        flags["page_registered"] = "hub"
        return

    panels = hass.data.get(frontend.DATA_PANELS) or {}
    if STANDALONE_PANEL_URL_PATH not in panels:
        version = _manifest_version(hass)
        frontend.async_register_built_in_panel(
            hass,
            component_name="custom",
            frontend_url_path=STANDALONE_PANEL_URL_PATH,
            sidebar_title=PAGE_TITLE,
            sidebar_icon=PAGE_ICON,
            config={
                "_panel_custom": {
                    "name": PAGE_ELEMENT,
                    "embed_iframe": False,
                    "trust_external": False,
                    "module_url": f"{URL_BASE}/page.js?ver={version}",
                }
            },
            require_admin=True,
        )
        _LOGGER.info("未检测到文羽面板壳，夜灯助手页面注册为独立侧边栏面板")
    flags["page_registered"] = "standalone"


def _teardown_page(hass: HomeAssistant, flags: dict) -> None:
    mode = flags.pop("page_registered", None)
    if mode == "hub":
        registry = hass.data.get(REGISTRY_KEY)
        if registry is not None and registry.pop(PAGE_ID, None) is not None:
            hass.bus.async_fire(
                BUS_EVENT_PAGE_CHANGED, {"id": PAGE_ID, "action": "unregister"}
            )
    elif mode == "standalone":
        frontend.async_remove_panel(
            hass, STANDALONE_PANEL_URL_PATH, warn_if_unknown=False
        )


async def async_setup_web(hass: HomeAssistant) -> None:
    """Register static assets and the API view (once per HA run), then the
    page in whichever mode fits."""
    flags: dict = hass.data.setdefault(WEB_DATA_KEY, {})

    if not flags.get("views"):
        hass.http.register_view(SnapshotView())
        flags["views"] = True

    if not flags.get("static"):
        static_dir = Path(__file__).parent / "static"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(URL_BASE, str(static_dir), cache_headers=False)]
        )
        flags["static"] = True

    _register_page(hass, flags)

    if not flags.get("started_recheck"):
        flags["started_recheck"] = hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _make_started_recheck(hass, flags)
        )


def _make_started_recheck(hass: HomeAssistant, flags: dict):
    @callback
    def _recheck(event: Event) -> None:
        _LOGGER.debug("HA started: re-checking page registration mode")
        _register_page(hass, flags)

    return _recheck


@callback
def async_unload_web(hass: HomeAssistant) -> None:
    """Unregister the page when the LAST manager goes away; views/static stay."""
    if hass.data.get(DOMAIN):
        return
    flags: dict = hass.data.get(WEB_DATA_KEY) or {}

    unsub = flags.pop("started_recheck", None)
    if unsub is not None:
        unsub()

    _teardown_page(hass, flags)
