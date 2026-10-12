"""Pytest configuration for the auto_night_light integration tests.

Adds the integration package to sys.path and installs stub Home Assistant
modules so manager-level transition tests can run standalone (桩模式专用).
"""

import sys as _sys
import types as _types
from datetime import datetime as _datetime
from datetime import time as _time
from pathlib import Path
from typing import Any
from typing import Any as _Any

PACKAGE = Path(__file__).resolve().parents[1] / "custom_components" / "auto_night_light"
_sys.path.insert(0, str(PACKAGE))


import pytest as _pytest


@_pytest.fixture(autouse=True)
def _restore_fake_clock():
    """防止单个测试改写 _FakeClock.now_dt 后泄漏到后续测试。"""
    saved = _FakeClock.now_dt
    yield
    _FakeClock.now_dt = saved


def _ha_module(name: str, **attrs: _Any) -> _types.ModuleType:
    mod = _types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    _sys.modules[name] = mod
    return mod


def _identity(x):
    return x


# 可控的“当前时间”：manager 的锚点/带解析全部经 dt_util.now()
class _FakeClock:
    now_dt = _datetime(2026, 10, 2, 12, 0, 0)


_dt_mod = _types.ModuleType("homeassistant.util.dt")
_dt_mod.now = lambda *a, **k: _FakeClock.now_dt


def _parse_time(value):
    try:
        return _time.fromisoformat(value)
    except (TypeError, ValueError):
        return None  # 真实 HA 的 parse_time 失败返回 None


def _parse_datetime(value):
    # 与真实 HA 对齐：仅接受字符串，datetime/None 输入由被测代码自行处理
    if not isinstance(value, str):
        raise TypeError("parse_datetime expects a string (as real HA does)")
    try:
        return _datetime.fromisoformat(value)
    except ValueError:
        return None


_dt_mod.parse_time = _parse_time
_dt_mod.parse_datetime = _parse_datetime
_dt_mod.as_local = lambda x: x
_dt_mod.utcnow = lambda: _datetime.utcnow()
_ha_module("homeassistant")
_sys.modules["homeassistant"].__path__ = []  # 使其成为包，允许注册子模块
_util_mod = _ha_module("homeassistant.util", dt=_dt_mod)
_util_mod.__path__ = []  # 使其成为包，允许 import homeassistant.util.dt
_sys.modules["homeassistant.util.dt"] = _dt_mod
_ha_module(
    "homeassistant.components.light",
    ATTR_BRIGHTNESS="brightness",
    ATTR_COLOR_TEMP_KELVIN="color_temp_kelvin",
    ATTR_TRANSITION="transition",
    DOMAIN="light",
)
_ha_module("homeassistant.config_entries", ConfigEntry=type("ConfigEntry", (), {}))
_ha_module(
    "homeassistant.const",
    ATTR_ENTITY_ID="entity_id",
    SERVICE_TURN_ON="turn_on",
    STATE_OFF="off",
    STATE_ON="on",
    STATE_UNAVAILABLE="unavailable",
    STATE_UNKNOWN="unknown",
    SUN_EVENT_SUNRISE="sunrise",
    SUN_EVENT_SUNSET="sunset",
)
_ha_module(
    "homeassistant.core",
    Event=type("Event", (), {}),
    EventStateChangedData=type("EventStateChangedData", (), {}),
    HomeAssistant=type("HomeAssistant", (), {}),
    ServiceCall=type("ServiceCall", (), {}),
    State=type("State", (), {}),
    callback=_identity,
)

# 定点调度句柄记录：tests 直接检查 (when, callback) 列表
POINT_IN_TIME_CALLS: list[tuple[_Any, _Any]] = []


def _fake_track_point_in_time(hass, action, when):
    POINT_IN_TIME_CALLS.append((when, action))
    return lambda: POINT_IN_TIME_CALLS.remove((when, action))


def _fake_track_state_change_event(hass, entities, action):
    return lambda: None


CALL_LATER_CALLS: list[tuple[float, Any]] = []


def _fake_async_call_later(hass, delay, action):
    CALL_LATER_CALLS.append((delay, action))
    return lambda: CALL_LATER_CALLS.remove((delay, action))


_ha_module(
    "homeassistant.helpers.event",
    async_call_later=_fake_async_call_later,
    async_track_point_in_time=_fake_track_point_in_time,
    async_track_state_change_event=_fake_track_state_change_event,
)


class _AstralCanary(BaseException):
    """继承 BaseException：绕过 manager._sun_dt 的 except Exception 兜底。"""


def _astral_canary(*_args, **_kwargs):
    raise _AstralCanary("astral 被调用——固定锚点测试不应触达")


_ha_module("homeassistant.helpers.sun", get_astral_event_date=_astral_canary)


class _HomeAssistantError(Exception):
    pass


_ha_module("homeassistant.exceptions", HomeAssistantError=_HomeAssistantError)

# --- web.py 依赖（v2.2.0 页面批次新增） -------------------------------------

# core 补 EVENT_HOMEASSISTANT_STARTED
_sys.modules["homeassistant.core"].EVENT_HOMEASSISTANT_STARTED = "homeassistant_started"

_ha_module("homeassistant.components")
_sys.modules["homeassistant.components"].__path__ = []

# frontend（面板/注册表双路径）
_ha_module(
    "homeassistant.components.frontend",
    DATA_PANELS="frontend_panels",
    async_register_built_in_panel=lambda hass, **kw: hass.data.setdefault(
        "frontend_panels", {}
    ).__setitem__(kw["frontend_url_path"], kw),
    async_remove_panel=lambda hass, path, warn_if_unknown=True: hass.data.get(
        "frontend_panels", {}
    ).pop(path, None),
)


class _StaticPathConfig:
    def __init__(self, url_path, path, cache_headers=True):
        self.url_path = url_path
        self.path = path
        self.cache_headers = cache_headers


class _HomeAssistantView:
    requires_auth = False


def _require_admin(func):
    func._require_admin_applied = True
    return func


_ha_module(
    "homeassistant.components.http",
    HomeAssistantView=_HomeAssistantView,
    StaticPathConfig=_StaticPathConfig,
    require_admin=_require_admin,
)

# loader（manifest 版本缓存戳）
_VERSIONS = {"auto_night_light": "2.2.0"}


def _get_loaded_integration(hass, domain):
    class _Loaded:
        version = _VERSIONS.get(domain)

    return _Loaded()


_ha_module("homeassistant.loader", async_get_loaded_integration=_get_loaded_integration)

# aiohttp：无条件打桩——真实 Response 的负载对象会让 snapshot 断言面
# 随环境漂移（ANL-F-018）；桩保证 resp.payload 恒为 dict。
_ha_module("aiohttp")
_aio_web = _ha_module("aiohttp.web")
_aio_web.Request = type("Request", (), {})


class _StubResponse:
    def __init__(self, payload=None, status=200):
        self.payload = payload
        self.status = status


_aio_web.Response = _StubResponse
_aio_web.json_response = lambda data, status=200: _StubResponse(
    payload=data, status=status
)

# 子模块挂到父模块属性上，供 from homeassistant.util import dt 使用
for name in [m for m in list(_sys.modules) if m.startswith("homeassistant.")]:
    parent_name, _, child = name.rpartition(".")
    parent = _sys.modules.get(parent_name)
    if parent is not None:
        setattr(parent, child, _sys.modules[name])
