"""web.py tests: snapshot serialization + hub/standalone dual registration."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime as _datetime
from datetime import time as _time
from types import SimpleNamespace

from custom_components.auto_night_light import web
from custom_components.auto_night_light.manager import LightMachine, LightState


class FakeBus:
    def __init__(self):
        self.fired = []
        self.listen_once = []

    def async_fire(self, event_type, data=None):
        self.fired.append((event_type, data))

    def async_listen_once(self, event_type, cb):
        self.listen_once.append((event_type, cb))
        return lambda: None


class FakeHttp:
    def __init__(self):
        self.views = []
        self.static = []

    def register_view(self, view):
        self.views.append(view)

    async def async_register_static_paths(self, configs):
        self.static.extend(configs)


class FakeHass:
    def __init__(self):
        self.data = {}
        self.bus = FakeBus()
        self.http = FakeHttp()


class FakeRequest:
    def __init__(self, hass):
        self.app = {"hass": hass}


def fake_manager(entry_id="m1", title="自动夜灯", **overrides):
    """A NightLightManager stand-in with only the attributes web.py reads."""
    mgr = SimpleNamespace(
        entry=SimpleNamespace(entry_id=entry_id, title=title),
        machines={
            "light.a": LightMachine(entity_id="light.a"),
            "light.b": LightMachine(
                entity_id="light.b",
                state=LightState.MISMATCH,
                manual_override=True,
                mismatch_steps=2,
                target=(12, 2700),
                applied=(30, 4000),
                last_error=None,
            ),
        },
        start_mode="sunset",
        end_mode="sunrise",
        transition_enabled=False,
        day_enabled=True,
        respect_manual=True,
    )
    # NOTE: _mode_at 故意不打桩——web 层若回归私有直调（ANL-F-003）将
    # AttributeError，让"web 禁触私有"成为硬判据。
    _t22, _t63 = _time(22, 0), _time(6, 30)

    def _anchor_snapshot():
        # 真实语义：全表 + current + 全锚点中最近一次发生（23:00 → 06:30）
        nxt = _datetime(2026, 10, 13, 6, 30, 0)
        return {
            "anchors": [(_t22, "night"), (_t63, "day")],
            "current_mode": "night",
            "next_anchor": nxt,
        }

    mgr.anchor_snapshot = _anchor_snapshot
    for k, v in overrides.items():
        setattr(mgr, k, v)
    return mgr


def test_snapshot_success():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"m1": fake_manager()}
    resp = asyncio.run(web.SnapshotView().get(FakeRequest(hass)))
    payload = json.loads(json.dumps(resp.payload, allow_nan=False))
    m = payload["managers"][0]
    assert m["title"] == "自动夜灯"
    assert m["next_anchor"].startswith("2026-10-13T06:30")  # 全表最近，非夜间开始
    assert m["current_mode"] == "night"  # 来自 anchor_snapshot（web 禁触私有）

    assert [(a["time"], a["mode"]) for a in m["anchors"]] == [
        ("22:00", "night"),
        ("06:30", "day"),
    ]
    la, lb = m["lights"]
    assert la["state"] == "idle" and la["manual_override"] is False
    assert lb["state"] == "mismatch" and lb["manual_override"] is True
    assert lb["mismatch_steps"] == 2
    assert lb["target"] == [12, 2700]
    assert lb["applied"] == [30, 4000]


def test_snapshot_skips_unparseable_anchors_and_none_next():
    """ANL-F-008/012: 解析失败的锚点被跳过（服务端留 WARNING），
    next_anchor 为 None 时页面得 null 而非垃圾。"""
    hass = FakeHass()
    mgr = fake_manager("m2")

    def _broken():
        return {
            "anchors": [(None, "extra_0"), (_time(22, 0), "night")],
            "current_mode": None,
            "next_anchor": None,
        }

    mgr.anchor_snapshot = _broken
    hass.data[web.DOMAIN] = {"m2": mgr}
    resp = asyncio.run(web.SnapshotView().get(FakeRequest(hass)))
    m = resp.payload["managers"][0]
    assert [a["mode"] for a in m["anchors"]] == ["night"]  # None 被跳过
    assert m["next_anchor"] is None
    assert m["current_mode"] is None


def test_anchor_snapshot_next_is_nearest_of_all_anchors():
    """ANL-F-016: F-001 本体——next_anchor 是全锚点表的最近一次发生，
    而非夜间开始锚点（R1 反事实 1：23:00 默认配置 → 次日 06:00）。"""
    import conftest as _cf

    from custom_components.auto_night_light.manager import NightLightManager

    saved = _cf._FakeClock.now_dt
    try:
        _cf._FakeClock.now_dt = _cf._datetime(2026, 10, 12, 23, 0, 0)
        mgr = NightLightManager(
            hass=SimpleNamespace(), entry=SimpleNamespace(
                data={
                    "lights": ["light.a"], "start_mode": "fixed",
                    "trigger_time": "22:00", "end_mode": "fixed",
                    "end_time": "06:00", "extras": [], "day_enabled": True,
                }, options={}
            )
        )
        snap = mgr.anchor_snapshot()
        assert snap["next_anchor"] == _datetime(2026, 10, 13, 6, 0, 0)
        assert snap["current_mode"] == "night"
        assert [(t.strftime("%H:%M"), m) for t, m in snap["anchors"]] == [
            ("22:00", "night"), ("06:00", "day")
        ]
    finally:
        _cf._FakeClock.now_dt = saved


def test_anchor_snapshot_includes_extra_anchor_in_nearest():
    """ANL-F-016: R1 反事实 2——17:00 有 18:00 额外时段时 next=18:00。"""
    import conftest as _cf

    from custom_components.auto_night_light.manager import NightLightManager

    saved = _cf._FakeClock.now_dt
    try:
        _cf._FakeClock.now_dt = _cf._datetime(2026, 10, 12, 17, 0, 0)
        mgr = NightLightManager(
            hass=SimpleNamespace(), entry=SimpleNamespace(
                data={
                    "lights": ["light.a"], "start_mode": "fixed",
                    "trigger_time": "22:00", "end_mode": "fixed",
                    "end_time": "06:00",
                    "extras": [{"start": "18:00",
                                "brightness": 30, "color_temp_kelvin": 3000}],
                    "day_enabled": True,
                }, options={}
            )
        )
        snap = mgr.anchor_snapshot()
        assert snap["next_anchor"] == _datetime(2026, 10, 12, 18, 0, 0)
    finally:
        _cf._FakeClock.now_dt = saved


def test_snapshot_empty():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {}
    resp = asyncio.run(web.SnapshotView().get(FakeRequest(hass)))
    assert resp.payload == {"managers": []}


def test_view_gates():
    hass = FakeHass()
    asyncio.run(web.async_setup_web(hass))
    view = hass.http.views[0]
    assert view.requires_auth is True
    # 桩局限：require_admin 桩只打标记，无法证明真 HA 会拦非管理员
    # （lux LX-F-009 对同款桩已书面接受）——仅验证装饰器被书写。
    assert getattr(view.get, "_require_admin_applied", False) is True


def test_setup_web_idempotent():
    hass = FakeHass()
    asyncio.run(web.async_setup_web(hass))
    asyncio.run(web.async_setup_web(hass))
    assert len(hass.http.views) == 1
    assert len(hass.http.static) == 1
    assert hass.http.static[0].url_path == web.URL_BASE
    assert hass.http.static[0].cache_headers is False


def test_register_hub_mode():
    hass = FakeHass()
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    d = hass.data[web.REGISTRY_KEY].get(web.PAGE_ID)
    assert d is not None
    assert d["id"] == "anl.main"
    assert d["element"] == "anl-page"
    assert d["module_url"].startswith("/auto_night_light/page.js?ver=")
    assert d["version"] == "2.2.0"
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data.get("frontend_panels", {})
    assert (
        "fumiha_hub_page_changed",
        {"id": web.PAGE_ID, "action": "register"},
    ) in hass.bus.fired


def test_register_standalone_mode():
    hass = FakeHass()
    asyncio.run(web.async_setup_web(hass))
    panel = hass.data.get("frontend_panels", {}).get(web.STANDALONE_PANEL_URL_PATH)
    assert panel is not None
    cfg = panel["config"]["_panel_custom"]
    assert cfg["name"] == "anl-page"
    assert cfg["module_url"].startswith("/auto_night_light/page.js?ver=2.2.0")
    assert panel["require_admin"] is True
    assert web.REGISTRY_KEY not in hass.data


def test_mode_switch_standalone_to_hub_on_reregister():
    hass = FakeHass()
    asyncio.run(web.async_setup_web(hass))
    assert hass.data[web.WEB_DATA_KEY]["page_registered"] == "standalone"
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    assert hass.data[web.WEB_DATA_KEY]["page_registered"] == "hub"
    assert web.PAGE_ID in hass.data[web.REGISTRY_KEY]
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data.get("frontend_panels", {})


def test_mode_switch_hub_to_standalone_when_hub_removed():
    hass = FakeHass()
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    assert hass.data[web.WEB_DATA_KEY]["page_registered"] == "hub"
    del hass.data[web.REGISTRY_KEY]
    asyncio.run(web.async_setup_web(hass))
    assert hass.data[web.WEB_DATA_KEY]["page_registered"] == "standalone"
    assert web.STANDALONE_PANEL_URL_PATH in hass.data.get("frontend_panels", {})


def test_started_recheck_switches_standalone_to_hub():
    hass = FakeHass()
    asyncio.run(web.async_setup_web(hass))
    flags = hass.data[web.WEB_DATA_KEY]
    assert flags["page_registered"] == "standalone"
    event_type, cb = hass.bus.listen_once[0]
    assert event_type == "homeassistant_started"
    hass.data[web.REGISTRY_KEY] = {}
    cb(None)
    assert web.PAGE_ID in hass.data[web.REGISTRY_KEY]
    assert flags["page_registered"] == "hub"
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data.get("frontend_panels", {})


def test_started_recheck_noop_when_already_hub():
    hass = FakeHass()
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    _, cb = hass.bus.listen_once[0]
    fired_before = len(hass.bus.fired)
    before = hass.data[web.REGISTRY_KEY][web.PAGE_ID]
    cb(None)
    assert hass.data[web.REGISTRY_KEY][web.PAGE_ID] is before
    assert len(hass.bus.fired) == fired_before


def test_unload_keeps_registration_while_managers_remain():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {"m1": fake_manager()}
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    web.async_unload_web(hass)  # managers remain → nothing torn down
    assert web.PAGE_ID in hass.data[web.REGISTRY_KEY]


def test_unload_hub_mode_pops_descriptor_and_fires():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {}
    hass.data[web.REGISTRY_KEY] = {}
    asyncio.run(web.async_setup_web(hass))
    web.async_unload_web(hass)
    assert web.PAGE_ID not in hass.data[web.REGISTRY_KEY]
    assert (
        "fumiha_hub_page_changed",
        {"id": web.PAGE_ID, "action": "unregister"},
    ) in hass.bus.fired


def test_unload_standalone_mode_removes_panel():
    hass = FakeHass()
    hass.data[web.DOMAIN] = {}
    asyncio.run(web.async_setup_web(hass))
    assert web.STANDALONE_PANEL_URL_PATH in hass.data.get("frontend_panels", {})
    web.async_unload_web(hass)
    assert web.STANDALONE_PANEL_URL_PATH not in hass.data.get("frontend_panels", {})


def test_manifest_declares_web_dependencies():
    from pathlib import Path

    mf = (
        Path(__file__).resolve().parents[1]
        / "custom_components"
        / "auto_night_light"
        / "manifest.json"
    )
    m = json.loads(mf.read_text(encoding="utf-8"))
    assert m["dependencies"] == ["http", "frontend"]
    assert m["after_dependencies"] == ["fumiha_hub"]
    assert m["version"] == "2.2.0"
