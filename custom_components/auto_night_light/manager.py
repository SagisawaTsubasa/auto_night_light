"""Per-light state machine manager for HA Auto Night Light."""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from datetime import timedelta

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
    SUN_EVENT_SUNRISE,
    SUN_EVENT_SUNSET,
)
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_sunset,
    async_track_time_change,
)
from homeassistant.helpers.sun import get_astral_event_date
import homeassistant.util.dt as dt_util

from .const import (
    CONF_BRIGHTNESS,
    CONF_COLOR_TEMP_KELVIN,
    CONF_DAY_BRIGHTNESS,
    CONF_DAY_COLOR_TEMP_KELVIN,
    CONF_DAY_ENABLED,
    CONF_END_TIME,
    CONF_EXTRAS,
    CONF_LIGHTS,
    CONF_ONLY_WHEN_ON,
    CONF_OVERRIDES,
    CONF_SETTLE_DELAY,
    CONF_SUN_ENTITY,
    CONF_SUN_SOURCE,
    CONF_SUNRISE_OFFSET,
    CONF_SUNSET_OFFSET,
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
    DEFAULT_EXTRA_BRIGHTNESS,
    DEFAULT_EXTRA_COLOR_TEMP_KELVIN,
    DEFAULT_SETTLE_DELAY,
    DEFAULT_SUN_ENTITY,
    DEFAULT_SUNRISE_OFFSET,
    DEFAULT_SUNSET_OFFSET,
    DEFAULT_TOLERANCE_BRIGHTNESS,
    DEFAULT_TOLERANCE_KELVIN,
    DEFAULT_TURN_ON_LISTEN,
    DEFAULT_VERIFY_DELAY,
    EXTRA_BRIGHTNESS,
    EXTRA_COLOR_TEMP_KELVIN,
    EXTRA_START,
    MODE_DAY,
    MODE_EXTRA_PREFIX,
    MODE_NIGHT,
    OVR_BRIGHTNESS,
    OVR_COLOR_TEMP_KELVIN,
    OVR_DAY_BRIGHTNESS,
    OVR_DAY_COLOR_TEMP_KELVIN,
    OVR_EXTRA_BRIGHTNESS,
    OVR_EXTRA_COLOR_TEMP_KELVIN,
    OVR_EXTRAS,
    SUN_SOURCE_BUILTIN,
    SUN_SOURCE_CUSTOM,
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
        self.sun_source: str = data.get(CONF_SUN_SOURCE, SUN_SOURCE_BUILTIN)
        self.sun_entity: str = data.get(CONF_SUN_ENTITY, DEFAULT_SUN_ENTITY)
        self.sunset_offset: int = data.get(CONF_SUNSET_OFFSET, DEFAULT_SUNSET_OFFSET)
        self.sunrise_offset: int = data.get(
            CONF_SUNRISE_OFFSET, DEFAULT_SUNRISE_OFFSET
        )
        self.trigger_time: str = data[CONF_TRIGGER_TIME]
        self.end_time: str = data.get(CONF_END_TIME, DEFAULT_END_TIME)
        self.extras: list[dict] = [
            dict(e) for e in data.get(CONF_EXTRAS, [])
        ]
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
        self.overrides: dict[str, dict] = data.get(CONF_OVERRIDES, {})
        self.machines: dict[str, LightMachine] = {
            light: LightMachine(entity_id=light) for light in self.lights
        }
        self._unsub_time = None
        self._unsub_state = None
        self._unsub_sun = None

    def params_for(self, entity_id: str, mode: str) -> tuple[int, int]:
        """Resolve effective (brightness, kelvin) for a light, applying overrides."""
        ovr = self.overrides.get(entity_id, {})
        if mode.startswith(MODE_EXTRA_PREFIX):
            idx = int(mode[len(MODE_EXTRA_PREFIX):])
            extra = self.extras[idx]
            ovr_extra = ovr.get(OVR_EXTRAS, {}).get(str(idx), {})
            return (
                ovr_extra.get(
                    OVR_EXTRA_BRIGHTNESS,
                    extra.get(EXTRA_BRIGHTNESS, DEFAULT_EXTRA_BRIGHTNESS),
                ),
                ovr_extra.get(
                    OVR_EXTRA_COLOR_TEMP_KELVIN,
                    extra.get(EXTRA_COLOR_TEMP_KELVIN, DEFAULT_EXTRA_COLOR_TEMP_KELVIN),
                ),
            )
        if mode == MODE_DAY:
            return (
                ovr.get(OVR_DAY_BRIGHTNESS, self.day_brightness),
                ovr.get(OVR_DAY_COLOR_TEMP_KELVIN, self.day_kelvin),
            )
        return (
            ovr.get(OVR_BRIGHTNESS, self.brightness),
            ovr.get(OVR_COLOR_TEMP_KELVIN, self.kelvin),
        )

    def start(self) -> None:
        """Schedule the daily trigger (fixed, builtin sun or custom entity)."""
        if self.sun_source == SUN_SOURCE_BUILTIN:
            offset = timedelta(minutes=self.sunset_offset)
            self._unsub_time = async_track_sunset(
                self.hass, self._async_sunset_trigger, offset=offset
            )
            _LOGGER.info(
                "Auto night light scheduled at sunset %+d min (builtin sun) for %s",
                self.sunset_offset,
                self.lights,
            )
        elif self.sun_source == SUN_SOURCE_CUSTOM:
            self._schedule_custom_sunset()
            self._unsub_sun = async_track_state_change_event(
                self.hass, [self.sun_entity], self._async_sun_entity_changed
            )
            _LOGGER.info(
                "Auto night light scheduled via custom sun entity %s for %s",
                self.sun_entity,
                self.lights,
            )
        else:
            hour, minute, *_ = (int(p) for p in self.trigger_time.split(":"))
            self._unsub_time = async_track_time_change(
                self.hass,
                self._async_scheduled_trigger,
                hour=hour,
                minute=minute,
                second=0,
            )
            _LOGGER.info(
                "Auto night light scheduled at %02d:%02d for %s",
                hour,
                minute,
                self.lights,
            )
        if self.turn_on_listen:
            self._unsub_state = async_track_state_change_event(
                self.hass, self.lights, self._async_light_state_changed
            )
            _LOGGER.info(
                "Turn-on listener active, night window %s -> %s (sun_source=%s)",
                self.trigger_time,
                self.end_time,
                self.sun_source,
            )

    def stop(self) -> None:
        """Cancel the schedule and the listeners."""
        for unsub in (self._unsub_time, self._unsub_state, self._unsub_sun):
            if unsub is not None:
                unsub()
        self._unsub_time = None
        self._unsub_state = None
        self._unsub_sun = None

    def _custom_sun_times(self) -> tuple | None:
        """Read (sunset, sunrise) datetimes from the custom sun entity."""
        state = self.hass.states.get(self.sun_entity)
        if state is None:
            return None
        sunset = dt_util.parse_datetime(
            state.attributes.get("next_setting", "")
        )
        sunrise = dt_util.parse_datetime(
            state.attributes.get("next_rising", "")
        )
        if sunset is None or sunrise is None:
            return None
        return (sunset, sunrise)

    def _schedule_custom_sunset(self) -> None:
        """Schedule the trigger at next_setting + offset of the custom entity."""
        if self._unsub_time is not None:
            self._unsub_time()
            self._unsub_time = None
        times = self._custom_sun_times()
        if times is None:
            _LOGGER.warning(
                "%s missing next_setting/next_rising, custom trigger not scheduled",
                self.sun_entity,
            )
            return
        when = times[0] + timedelta(minutes=self.sunset_offset)
        self._unsub_time = async_track_point_in_time(
            self.hass, self._async_custom_sunset_trigger, when
        )
        _LOGGER.info("Custom sun trigger scheduled at %s", when)

    async def _async_custom_sunset_trigger(self, _now) -> None:
        """Fire at custom sunset + offset, then schedule the next round."""
        await self.async_trigger(reason="sunset")
        self._schedule_custom_sunset()

    async def _async_sun_entity_changed(self, _event) -> None:
        """Reschedule when the custom sun entity updates its times."""
        self._schedule_custom_sunset()

    def _night_anchor_times(self) -> tuple:
        """Resolve (night start, night end) anchor times.

        内置 sun 时用天文计算当日日落/日出，自定义实体时读其
        next_setting/next_rising 属性；均叠加各自偏移。
        失败时回退到固定时间。
        """
        sunset = sunrise = None
        if self.sun_source == SUN_SOURCE_BUILTIN:
            try:
                today = dt_util.now().date()
                sunset = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, today)
                sunrise = get_astral_event_date(self.hass, SUN_EVENT_SUNRISE, today)
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Builtin sun events unavailable (%s), using fixed times", err
                )
        elif self.sun_source == SUN_SOURCE_CUSTOM:
            times = self._custom_sun_times()
            if times is not None:
                sunset, sunrise = times
            else:
                _LOGGER.warning(
                    "%s missing next_setting/next_rising, using fixed times",
                    self.sun_entity,
                )
        if sunset is not None and sunrise is not None:
            return (
                dt_util.as_local(
                    sunset + timedelta(minutes=self.sunset_offset)
                ).time(),
                dt_util.as_local(
                    sunrise + timedelta(minutes=self.sunrise_offset)
                ).time(),
            )
        return (
            dt_util.parse_time(self.trigger_time),
            dt_util.parse_time(self.end_time),
        )

    def current_mode(self) -> str | None:
        """Resolve the active period from time anchors.

        每个配置的时间是一个锚点：从该时刻起生效，直到下一个锚点。
        锚点按 24 小时循环取“最近已过去”的一个；额外时段锚点排在
        基础锚点之前，同一时刻冲突时额外时段优先：
        夜间开始 -> night，夜间结束 -> day（未启用日间则为 None），
        额外时段 i 开始 -> extra_i。
        """
        anchors: list[tuple] = []
        for i, extra in enumerate(self.extras):
            anchors.append(
                (dt_util.parse_time(extra.get(EXTRA_START, "")), f"extra_{i}")
            )
        t_night_start, t_night_end = self._night_anchor_times()
        anchors.append((t_night_start, MODE_NIGHT))
        anchors.append((t_night_end, MODE_DAY if self.day_enabled else None))

        now = dt_util.now().time()
        now_min = now.hour * 60 + now.minute
        best_mode: str | None = None
        best_delta: int | None = None
        for t, mode in anchors:
            if t is None:
                continue
            anchor_min = t.hour * 60 + t.minute
            delta = (now_min - anchor_min) % 1440
            if best_delta is None or delta < best_delta:
                best_mode, best_delta = mode, delta
        return best_mode

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
        mode = self.current_mode()
        if mode is None:
            _LOGGER.debug(
                "%s turned on outside all active periods, ignored", entity_id
            )
            return
        brightness, kelvin = self.params_for(entity_id, mode)
        machine = self.machines.get(entity_id)
        if machine is None:
            _LOGGER.debug("%s not in machine table (stale listener?), skipped", entity_id)
            return
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

    async def _async_sunset_trigger(self) -> None:
        """Entry point for the sunset trigger (sun integration)."""
        await self.async_trigger(reason="sunset")

    async def async_trigger(self, reason: str = "manual") -> None:
        """Run one check-and-set round for all lights."""
        _LOGGER.info("Auto night light triggered (%s)", reason)
        for entity_id in self.lights:
            brightness, kelvin = self.params_for(entity_id, MODE_NIGHT)
            await self._async_process_light(entity_id, brightness, kelvin)

    @staticmethod
    def _to_pct(brightness_byte: int) -> int:
        """Convert HA brightness (0-255) to percent."""
        return round(brightness_byte * 100 / 255)

    @staticmethod
    def _to_byte(brightness_pct: int | float) -> int:
        """Convert percent (1-100) to HA brightness (1-255)."""
        return min(255, max(1, round(brightness_pct * 255 / 100)))

    def _supports_color_temp(self, state: State) -> bool:
        """Return True if the light supports color temperature."""
        modes = state.attributes.get("supported_color_modes")
        if not modes:  # 未上报时乐观假定支持，避免漏发色温
            return True
        return "color_temp" in modes

    def _matches(self, state: State, brightness: int, kelvin: int) -> bool:
        """Return True if the light already matches target within tolerance.

        brightness 参数为百分比（1-100）。
        """
        if state.state != STATE_ON:
            return False
        cur_brightness = state.attributes.get(ATTR_BRIGHTNESS)
        cur_kelvin = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        if cur_brightness is None:
            return False
        if abs(self._to_pct(cur_brightness) - brightness) > self.tol_brightness:
            return False
        # 灯具不支持/未上报色温时仅校验亮度
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
            ATTR_BRIGHTNESS: self._to_byte(brightness),
        }
        if self._supports_color_temp(state):
            service_data[ATTR_COLOR_TEMP_KELVIN] = kelvin
        _LOGGER.info(
            "%s mismatch (brightness=%s kelvin=%s), setting to %s%%/%sK",
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
        target = machine.target or self.params_for(entity_id, MODE_NIGHT)
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
