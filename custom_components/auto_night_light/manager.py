"""Per-light state machine manager for HA Auto Night Light."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
import homeassistant.util.dt as dt_util

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
)

_LOGGER = logging.getLogger(__name__)


class LightState(enum.Enum):
    """State machine states for a single light."""

    IDLE = "idle"  # 等待下一次定时触发
    TURN_ON_PENDING = "turn_on_pending"  # 监听到开灯，等待属性稳定
    PENDING = "pending"  # 触发时间已到，待检查当前状态
    MATCHED = "matched"  # 当前状态已符合预期，跳过控制
    SETTING = "setting"  # 已下发控制指令，等待验证
    VERIFIED = "verified"  # 控制后验证通过
    MISMATCH = "mismatch"  # 控制后仍不符合预期
    OFFLINE = "offline"  # 实体不可用，本轮跳过
    SKIPPED_OFF = "skipped_off"  # 灯当前关闭且配置为不主动开灯


@dataclass
class LightMachine:
    """State machine context for one light."""

    entity_id: str
    state: LightState = LightState.IDLE
    last_error: str | None = field(default=None)
    target: tuple[int, int] | None = field(default=None)  # 最近下发的 (亮度, 色温)


class NightLightManager:
    """Manage scheduled trigger and per-light state machines."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize from config entry."""
        self.hass = hass
        self.entry = entry
        data = {**entry.data, **entry.options}
        self.lights: list[str] = data[CONF_LIGHTS]
        self.trigger_time: str = data[CONF_TRIGGER_TIME]
        self.end_time: str = data.get(CONF_END_TIME, DEFAULT_END_TIME)
        self.brightness: int = data.get(CONF_BRIGHTNESS, DEFAULT_BRIGHTNESS)
        self.kelvin: int = data.get(CONF_COLOR_TEMP_KELVIN, DEFAULT_COLOR_TEMP_KELVIN)
        self.tol_brightness: int = data.get(
            CONF_TOLERANCE_BRIGHTNESS, DEFAULT_TOLERANCE_BRIGHTNESS
        )
        self.tol_kelvin: int = data.get(CONF_TOLERANCE_KELVIN, DEFAULT_TOLERANCE_KELVIN)
        self.verify_delay: int = data.get(CONF_VERIFY_DELAY, DEFAULT_VERIFY_DELAY)
        self.only_when_on: bool = data.get(CONF_ONLY_WHEN_ON, False)
        self.turn_on_listen: bool = data.get(
            CONF_TURN_ON_LISTEN, DEFAULT_TURN_ON_LISTEN
        )
        self.settle_delay: float = data.get(CONF_SETTLE_DELAY, DEFAULT_SETTLE_DELAY)
        self.day_enabled: bool = data.get(CONF_DAY_ENABLED, False)
        self.day_brightness: int = data.get(CONF_DAY_BRIGHTNESS, DEFAULT_DAY_BRIGHTNESS)
        self.day_kelvin: int = data.get(
            CONF_DAY_COLOR_TEMP_KELVIN, DEFAULT_DAY_COLOR_TEMP_KELVIN
        )
        self.machines: dict[str, LightMachine] = {
            light: LightMachine(entity_id=light) for light in self.lights
        }
        self._unsub_time = None
        self._unsub_state = None

    def start(self) -> None:
        """Schedule the daily trigger and the turn-on listener."""
        hour, minute, *_ = (int(p) for p in self.trigger_time.split(":"))
        self._unsub_time = async_track_time_change(
            self.hass, self._async_scheduled_trigger, hour=hour, minute=minute, second=0
        )
        _LOGGER.info(
            "Auto night light scheduled at %02d:%02d for %s", hour, minute, self.lights
        )
        if self.turn_on_listen:
            self._unsub_state = async_track_state_change_event(
                self.hass, self.lights, self._async_light_state_changed
            )
            _LOGGER.info(
                "Turn-on listener active, night window %s -> %s",
                self.trigger_time,
                self.end_time,
            )

    def stop(self) -> None:
        """Cancel the schedule and the listener."""
        if self._unsub_time is not None:
            self._unsub_time()
            self._unsub_time = None
        if self._unsub_state is not None:
            self._unsub_state()
            self._unsub_state = None

    def _in_night_window(self) -> bool:
        """Return True if now is within the night window (supports overnight)."""
        now = dt_util.now().time()
        start = dt_util.parse_time(self.trigger_time)
        end = dt_util.parse_time(self.end_time)
        if start is None or end is None:
            return False
        if start <= end:  # 同日窗口，如 22:00-23:30
            return start <= now <= end
        return now >= start or now <= end  # 跨夜窗口，如 23:00-06:00

    async def _async_light_state_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Handle a configured light turning on inside the night window."""
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        if new_state is None or new_state.state != STATE_ON:
            return
        if old_state is not None and old_state.state not in (
            STATE_OFF,
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            return  # 仅响应 关→开，忽略运行中的属性变化，避免自触发循环
        entity_id = event.data["entity_id"]
        if self._in_night_window():
            brightness, kelvin, mode = self.brightness, self.kelvin, "night"
        elif self.day_enabled:
            brightness, kelvin, mode = self.day_brightness, self.day_kelvin, "day"
        else:
            _LOGGER.debug(
                "%s turned on outside night window and day mode off, ignored",
                entity_id,
            )
            return
        machine = self.machines[entity_id]
        machine.state = LightState.TURN_ON_PENDING
        _LOGGER.info(
            "%s turned on (%s mode), checking after %.1fs settle delay",
            entity_id,
            mode,
            self.settle_delay,
        )
        self.hass.loop.call_later(
            self.settle_delay,
            lambda: self.hass.async_create_task(
                self._async_process_light(entity_id, brightness, kelvin)
            ),
        )

    async def _async_scheduled_trigger(self, _now) -> None:
        """Entry point for the scheduled time trigger."""
        await self.async_trigger(reason="schedule")

    async def async_trigger(self, reason: str = "manual") -> None:
        """Run one check-and-set round for all lights."""
        _LOGGER.info("Auto night light triggered (%s)", reason)
        for entity_id in self.lights:
            await self._async_process_light(entity_id, self.brightness, self.kelvin)

    def _matches(self, state: State, brightness: int, kelvin: int) -> bool:
        """Return True if the light already matches target within tolerance."""
        if state.state != STATE_ON:
            return False
        cur_brightness = state.attributes.get(ATTR_BRIGHTNESS)
        cur_kelvin = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        if cur_brightness is None:
            return False
        if abs(cur_brightness - brightness) > self.tol_brightness:
            return False
        # 灯具不支持色温模式时 kelvin 可能为 None，仅校验亮度
        if cur_kelvin is not None and abs(cur_kelvin - kelvin) > self.tol_kelvin:
            return False
        return True

    async def _async_process_light(
        self, entity_id: str, brightness: int, kelvin: int
    ) -> None:
        """Advance the state machine for one light."""
        machine = self.machines[entity_id]
        machine.state = LightState.PENDING
        state = self.hass.states.get(entity_id)

        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            machine.state = LightState.OFFLINE
            _LOGGER.warning("%s unavailable, skipped", entity_id)
            return

        if state.state != STATE_ON and self.only_when_on:
            machine.state = LightState.SKIPPED_OFF
            _LOGGER.debug("%s is off and only_when_on enabled, skipped", entity_id)
            return

        if self._matches(state, brightness, kelvin):
            machine.state = LightState.MATCHED
            _LOGGER.debug("%s already matches target, no service call", entity_id)
            return

        # 状态不符，下发控制
        machine.state = LightState.SETTING
        machine.target = (brightness, kelvin)
        service_data = {
            ATTR_ENTITY_ID: entity_id,
            ATTR_BRIGHTNESS: brightness,
        }
        if ATTR_COLOR_TEMP_KELVIN in state.attributes or state.state != STATE_ON:
            service_data[ATTR_COLOR_TEMP_KELVIN] = kelvin
        _LOGGER.info(
            "%s mismatch (brightness=%s kelvin=%s), setting to %s/%sK",
            entity_id,
            state.attributes.get(ATTR_BRIGHTNESS),
            state.attributes.get(ATTR_COLOR_TEMP_KELVIN),
            brightness,
            kelvin,
        )
        try:
            await self.hass.services.async_call(
                LIGHT_DOMAIN, SERVICE_TURN_ON, service_data, blocking=True
            )
        except Exception as err:  # noqa: BLE001
            machine.state = LightState.MISMATCH
            machine.last_error = str(err)
            _LOGGER.error("%s service call failed: %s", entity_id, err)
            return

        # 延迟验证，避免灯具状态尚未刷新
        self.hass.loop.call_later(
            self.verify_delay,
            lambda: self.hass.async_create_task(self._async_verify(entity_id)),
        )

    async def _async_verify(self, entity_id: str) -> None:
        """Verify the light reached the target after control."""
        machine = self.machines[entity_id]
        state = self.hass.states.get(entity_id)
        target = machine.target or (self.brightness, self.kelvin)
        if state is not None and self._matches(state, *target):
            machine.state = LightState.VERIFIED
            machine.last_error = None
            _LOGGER.info("%s verified", entity_id)
        else:
            machine.state = LightState.MISMATCH
            _LOGGER.warning(
                "%s still mismatched after control: %s",
                entity_id,
                state.state if state else "missing",
            )
