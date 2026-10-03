"""Per-light state machine manager for HA Auto Night Light."""

from __future__ import annotations

import asyncio
import copy
import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import homeassistant.util.dt as dt_util
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_TRANSITION,
)
from homeassistant.components.light import (
    DOMAIN as LIGHT_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry
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
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_point_in_time,
    async_track_state_change_event,
)
from homeassistant.helpers.sun import get_astral_event_date

from .const import (
    ANCHOR_FIXED,
    ANCHOR_SUNRISE,
    ANCHOR_SUNSET,
    CONF_BRIGHTNESS,
    CONF_COLOR_TEMP_KELVIN,
    CONF_DAY_BRIGHTNESS,
    CONF_DAY_COLOR_TEMP_KELVIN,
    CONF_DAY_ENABLED,
    CONF_END_MODE,
    CONF_END_OFFSET,
    CONF_END_TIME,
    CONF_END_TRANSITION,
    CONF_EXTRAS,
    CONF_LIGHTS,
    CONF_ONLY_WHEN_ON,
    CONF_OVERRIDES,
    CONF_RESPECT_MANUAL,
    CONF_SETTLE_DELAY,
    CONF_START_MODE,
    CONF_START_OFFSET,
    CONF_START_TRANSITION,
    CONF_SUN_ENTITY,
    CONF_TOLERANCE_BRIGHTNESS,
    CONF_TOLERANCE_KELVIN,
    CONF_TRANSITION_ENABLED,
    CONF_TRANSITION_INTERVAL,
    CONF_TRIGGER_TIME,
    CONF_TURN_ON_LISTEN,
    CONF_VERIFY_DELAY,
    DEFAULT_BRIGHTNESS,
    DEFAULT_COLOR_TEMP_KELVIN,
    DEFAULT_DAY_BRIGHTNESS,
    DEFAULT_DAY_COLOR_TEMP_KELVIN,
    DEFAULT_END_OFFSET,
    DEFAULT_END_TIME,
    DEFAULT_EXTRA_BRIGHTNESS,
    DEFAULT_EXTRA_COLOR_TEMP_KELVIN,
    DEFAULT_RESPECT_MANUAL,
    DEFAULT_SETTLE_DELAY,
    DEFAULT_START_OFFSET,
    DEFAULT_SUN_ENTITY,
    DEFAULT_TOLERANCE_BRIGHTNESS,
    DEFAULT_TOLERANCE_KELVIN,
    DEFAULT_TRANSITION_INTERVAL,
    DEFAULT_TRIGGER_TIME,
    DEFAULT_TURN_ON_LISTEN,
    DEFAULT_VERIFY_DELAY,
    EXTRA_BRIGHTNESS,
    EXTRA_COLOR_TEMP_KELVIN,
    EXTRA_START,
    EXTRA_TRANSITION,
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
)
from .schedule import lerp_params, step_datetimes, upcoming_band_start

_LOGGER = logging.getLogger(__name__)

_NOT_IN_BAND = object()  # _band_params 哨兵：当前不在任何过渡带内


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
    # 过渡带内状态（v2.1.0 定点调度引擎）
    band_key: tuple | None = field(default=None)  # 当前所在带身份
    expected: tuple[int, int] | None = field(default=None)  # 本带最近预期值
    manual_override: bool = field(default=False)  # 本带内已被手动接管


@dataclass(frozen=True)
class PlanStep:
    """One scheduled transition step for one light.

    entrance=True 表示该步是带入口（factor=0）：带入口重置预期值为本步
    目标；非入口首观测步（带中途入表/重建）重置为 None——跳过一次接管
    判定，避免把灯具原生渐变的自然滞后误判成手动调节。
    """

    entity_id: str
    brightness: int
    kelvin: int
    band_key: tuple
    entrance: bool = False


class NightLightManager:
    """Manage scheduled trigger and per-light state machines."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize from config entry."""
        self.hass = hass
        self.entry = entry
        data = {**entry.data, **entry.options}
        self.lights: list[str] = data[CONF_LIGHTS]
        self.sun_entity: str = data.get(CONF_SUN_ENTITY, DEFAULT_SUN_ENTITY)
        self.start_mode: str = data.get(CONF_START_MODE, ANCHOR_SUNSET)
        self.start_offset: int = data.get(CONF_START_OFFSET, DEFAULT_START_OFFSET)
        self.end_mode: str = data.get(CONF_END_MODE, ANCHOR_SUNRISE)
        self.end_offset: int = data.get(CONF_END_OFFSET, DEFAULT_END_OFFSET)
        self.trigger_time: str = data.get(CONF_TRIGGER_TIME, DEFAULT_TRIGGER_TIME)
        self.end_time: str = data.get(CONF_END_TIME, DEFAULT_END_TIME)
        self.extras: list[dict] = [dict(e) for e in data.get(CONF_EXTRAS, [])]
        self.transition_enabled: bool = data.get(CONF_TRANSITION_ENABLED, False)
        self.start_transition: int = (
            int(data.get(CONF_START_TRANSITION, 0)) if self.transition_enabled else 0
        )
        self.end_transition: int = (
            int(data.get(CONF_END_TRANSITION, 0))
            if self.transition_enabled and data.get(CONF_DAY_ENABLED, False)
            else 0
        )
        self.transition_interval: int = int(
            data.get(CONF_TRANSITION_INTERVAL, DEFAULT_TRANSITION_INTERVAL)
        )
        self.respect_manual: bool = data.get(
            CONF_RESPECT_MANUAL, DEFAULT_RESPECT_MANUAL
        )
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
        # 逐灯覆盖做深拷贝，避免就地修改 entry.data；同时清理已缩减时段的残留索引
        self.overrides: dict[str, dict] = copy.deepcopy(data.get(CONF_OVERRIDES, {}))
        for ovr in self.overrides.values():
            extras_ovr = ovr.get(OVR_EXTRAS)
            if isinstance(extras_ovr, dict):
                stale = [
                    key
                    for key in extras_ovr
                    if not str(key).isdigit() or int(key) >= len(self.extras)
                ]
                for key in stale:
                    del extras_ovr[key]
        self.machines: dict[str, LightMachine] = {
            light: LightMachine(entity_id=light) for light in self.lights
        }
        self._unsub_time = None
        self._unsub_state = None
        self._unsub_sun = None
        # 定点调度计划：步进时刻 → 取消句柄（v2.1.0 替代间隔轮询）
        self._plan: dict[datetime, list[PlanStep]] = {}
        self._plan_unsub: dict[datetime, callable] = {}
        # async_call_later 句柄集中管理，stop() 时全部取消 (M1)
        self._pending_delays: set = set()
        self._stopped = False
        self._warned_sun_missing: set[str] = set()

    @property
    def _has_transitions(self) -> bool:
        """Return True if any anchor has a transition band configured."""
        if self.start_transition > 0 or self.end_transition > 0:
            return True
        return any(int(e.get(EXTRA_TRANSITION, 0) or 0) > 0 for e in self.extras)

    def params_for(self, entity_id: str, mode: str) -> tuple[int, int]:
        """Resolve effective (brightness, kelvin) for a light, applying overrides."""
        ovr = self.overrides.get(entity_id, {})
        if mode.startswith(MODE_EXTRA_PREFIX):
            idx = int(mode[len(MODE_EXTRA_PREFIX) :])
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
        """Schedule the daily trigger at the night-start anchor."""
        self._stopped = False
        self._schedule_trigger()
        if self._uses_custom_sun_entity():
            self._unsub_sun = async_track_state_change_event(
                self.hass, [self.sun_entity], self._async_sun_entity_changed
            )
        if self._has_transitions:
            self._rebuild_day_plan()
            self._warn_overlapping_bands()
            _LOGGER.info(
                "Transition bands scheduled at fixed step points (%d min interval)",
                self.transition_interval,
            )
        if self.turn_on_listen:
            self._unsub_state = async_track_state_change_event(
                self.hass, self.lights, self._async_light_state_changed
            )
        _LOGGER.info(
            "Auto night light started for %s (start=%s/%s, end=%s/%s)",
            self.lights,
            self.start_mode,
            self.trigger_time,
            self.end_mode,
            self.end_time,
        )

    def stop(self) -> None:
        """Cancel the schedule, the listeners and every pending delay."""
        self._stopped = True
        for unsub in (
            self._unsub_time,
            self._unsub_state,
            self._unsub_sun,
        ):
            if unsub is not None:
                unsub()
        self._unsub_time = None
        self._unsub_state = None
        self._unsub_sun = None
        for unsub in self._plan_unsub.values():
            unsub()
        self._plan_unsub.clear()
        self._plan.clear()
        for cancel in self._pending_delays:
            cancel()
        self._pending_delays.clear()

    def _delay(self, delay: float, action) -> None:
        """Schedule ``action`` after ``delay`` seconds; tracked for stop() (M1)."""
        if self._stopped:
            return
        handle = None

        @callback
        def _wrap(now):
            self._pending_delays.discard(handle)
            action(now)

        handle = async_call_later(self.hass, delay, _wrap)
        self._pending_delays.add(handle)

    def _uses_custom_sun_entity(self) -> bool:
        """Return True if any anchor relies on a non-default sun entity."""
        if self.sun_entity == DEFAULT_SUN_ENTITY:
            return False
        return self.start_mode != ANCHOR_FIXED or self.end_mode != ANCHOR_FIXED

    def _sun_dt(self, event_attr: str, sun_event: str, date) -> datetime | None:
        """Resolve a sun event datetime.

        非默认实体读其 next_setting/next_rising 属性；
        默认 sun.sun（或属性缺失回退）用 HA 天文计算。
        """
        if self.sun_entity != DEFAULT_SUN_ENTITY:
            state = self.hass.states.get(self.sun_entity)
            if state is not None:
                value = dt_util.parse_datetime(state.attributes.get(event_attr, ""))
                if value is not None:
                    return value
            if event_attr not in self._warned_sun_missing:
                self._warned_sun_missing.add(event_attr)
                _LOGGER.warning(
                    "%s missing %s, falling back to astral calculation",
                    self.sun_entity,
                    event_attr,
                )
            else:
                _LOGGER.debug(
                    "%s still missing %s, using astral calculation",
                    self.sun_entity,
                    event_attr,
                )
        try:
            return get_astral_event_date(self.hass, sun_event, date)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Sun event %s unavailable: %s", sun_event, err)
            return None

    def _anchor_time(self, mode: str, fixed: str, offset: int):
        """Resolve one anchor's time-of-day for mode resolution."""
        if mode == ANCHOR_FIXED:
            return dt_util.parse_time(fixed)
        event_attr = "next_setting" if mode == ANCHOR_SUNSET else "next_rising"
        sun_event = SUN_EVENT_SUNSET if mode == ANCHOR_SUNSET else SUN_EVENT_SUNRISE
        value = self._sun_dt(event_attr, sun_event, dt_util.now().date())
        if value is None:
            return dt_util.parse_time(fixed)
        return dt_util.as_local(value + timedelta(minutes=offset)).time()

    def _next_start_dt(self) -> datetime | None:
        """Compute the next occurrence datetime of the night-start anchor."""
        now = dt_util.now()

        def _fixed_next():
            t = dt_util.parse_time(self.trigger_time)
            if t is None:
                return None
            candidate = now.replace(
                hour=t.hour, minute=t.minute, second=0, microsecond=0
            )
            if candidate <= now:
                candidate += timedelta(days=1)
            return candidate

        if self.start_mode == ANCHOR_FIXED:
            return _fixed_next()
        event_attr = (
            "next_setting" if self.start_mode == ANCHOR_SUNSET else "next_rising"
        )
        sun_event = (
            SUN_EVENT_SUNSET if self.start_mode == ANCHOR_SUNSET else SUN_EVENT_SUNRISE
        )
        for days in (0, 1):
            date = (now + timedelta(days=days)).date()
            value = self._sun_dt(event_attr, sun_event, date)
            if value is None:
                break
            candidate = dt_util.as_local(value) + timedelta(minutes=self.start_offset)
            if candidate > now:
                return candidate
            if self.sun_entity != DEFAULT_SUN_ENTITY:
                # 自定义 sun 实体只暴露“下一次”事件这一个数据点，拿不到
                # 之后的下一次（M4）。单日语义：等实体在事件过后刷新属性时
                # 会触发重排，这里先退回固定时间兜底。
                _LOGGER.debug(
                    "%s only exposes its next event; falling back to fixed time",
                    self.sun_entity,
                )
                break
        _LOGGER.warning("Sun-based start anchor unavailable, using fixed time")
        return _fixed_next()

    def _schedule_trigger(self) -> None:
        """(Re)schedule the daily trigger at the night-start anchor."""
        if self._unsub_time is not None:
            self._unsub_time()
            self._unsub_time = None
        when = self._next_start_dt()
        if when is None:
            _LOGGER.error("Cannot schedule trigger: invalid trigger time")
            return
        self._unsub_time = async_track_point_in_time(
            self.hass, self._async_anchor_trigger, when
        )
        _LOGGER.info("Night light trigger scheduled at %s", when)

    async def _async_anchor_trigger(self, _now) -> None:
        """Fire at the night-start anchor, then schedule the next round.

        无论本轮触发是否抛异常，都必须重排下一次触发，否则集成会静默停摆 (M5)。
        """
        try:
            await self.async_trigger(reason="anchor")
        finally:
            if not self._stopped:
                self._schedule_trigger()
                self._rebuild_day_plan()

    async def _async_sun_entity_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Reschedule only when the custom sun entity's next-event times change (L1)."""
        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")
        if new_state is None:
            return
        for attr in ("next_rising", "next_setting"):
            new_value = new_state.attributes.get(attr)
            old_value = (
                old_state.attributes.get(attr) if old_state is not None else None
            )
            if new_value != old_value:
                _LOGGER.debug("%s %s changed, rescheduling", self.sun_entity, attr)
                self._schedule_trigger()
                self._rebuild_day_plan()
                return

    def _warn_overlapping_bands(self) -> None:
        """Warn when transition bands overlap — the earlier band wins (L4)."""
        bands = self._transition_bands()
        for i, (anchor_min, target, dur) in enumerate(bands):
            band_start = (anchor_min - dur) % 1440
            for j, (other_min, other_target, other_dur) in enumerate(bands):
                if i == j:
                    continue
                other_start = (other_min - other_dur) % 1440
                if (other_start - band_start) % 1440 < dur % 1440:
                    _LOGGER.warning(
                        "过渡带重叠：'%s' 的起点落在 '%s' 带内，重叠期间按 '%s' 插值",
                        other_target,
                        target,
                        target,
                    )

    def _night_anchor_times(self) -> tuple:
        """Resolve (night start, night end) anchor times-of-day."""
        return (
            self._anchor_time(self.start_mode, self.trigger_time, self.start_offset),
            self._anchor_time(self.end_mode, self.end_time, self.end_offset),
        )

    def _anchor_modes(self) -> list[tuple]:
        """Return [(anchor_time, mode)] for extras and base anchors.

        额外时段锚点排在基础锚点之前，同一时刻冲突时额外时段优先。
        """
        anchors: list[tuple] = []
        for i, extra in enumerate(self.extras):
            anchors.append(
                (dt_util.parse_time(extra.get(EXTRA_START, "")), f"extra_{i}")
            )
        t_night_start, t_night_end = self._night_anchor_times()
        anchors.append((t_night_start, MODE_NIGHT))
        anchors.append((t_night_end, MODE_DAY if self.day_enabled else None))
        return anchors

    def _mode_at(self, minutes: int) -> str | None:
        """Resolve the active mode at a given minute-of-day (anchor model)."""
        best_mode: str | None = None
        best_delta: int | None = None
        for t, mode in self._anchor_modes():
            if t is None:
                continue
            anchor_min = t.hour * 60 + t.minute
            delta = (minutes - anchor_min) % 1440
            if best_delta is None or delta < best_delta:
                best_mode, best_delta = mode, delta
        return best_mode

    def _transition_bands(self) -> list[tuple]:
        """Return [(anchor_minutes, target_mode, duration_min)] for active bands."""
        bands: list[tuple] = []
        for i, extra in enumerate(self.extras):
            dur = int(extra.get(EXTRA_TRANSITION, 0) or 0)
            t = dt_util.parse_time(extra.get(EXTRA_START, ""))
            if dur > 0 and t is not None:
                bands.append((t.hour * 60 + t.minute, f"extra_{i}", dur))
        t_night_start, t_night_end = self._night_anchor_times()
        if self.start_transition > 0 and t_night_start is not None:
            bands.append(
                (
                    t_night_start.hour * 60 + t_night_start.minute,
                    MODE_NIGHT,
                    self.start_transition,
                )
            )
        if self.end_transition > 0 and t_night_end is not None and self.day_enabled:
            bands.append(
                (
                    t_night_end.hour * 60 + t_night_end.minute,
                    MODE_DAY,
                    self.end_transition,
                )
            )
        return bands

    def _band_params(self, entity_id: str, now_min: int):
        """Interpolate params inside a transition band.

        返回 _NOT_IN_BAND 表示当前不在任何过渡带内；
        返回 None 表示带内但起点无生效模式（本轮不干预）；
        否则返回插值后的 (brightness, kelvin)。
        起点参数取带起点时刻按纯锚点解析的模式快照。
        """
        for anchor_min, target_mode, dur in self._transition_bands():
            band_start = (anchor_min - dur) % 1440
            elapsed = (now_min - band_start) % 1440
            if elapsed >= dur:
                continue
            from_mode = self._mode_at(band_start)
            if from_mode is None:
                return None
            factor = elapsed / dur
            return lerp_params(
                self.params_for(entity_id, from_mode),
                self.params_for(entity_id, target_mode),
                factor,
            )
        return _NOT_IN_BAND

    def current_params(self, entity_id: str) -> tuple[int, int] | None:
        """Resolve the effective (brightness, kelvin) for right now.

        过渡带内返回插值，带外按锚点模式取参；无生效模式返回 None。
        """
        now = dt_util.now().time()
        now_min = now.hour * 60 + now.minute
        if self._has_transitions:
            band = self._band_params(entity_id, now_min)
            if band is not _NOT_IN_BAND:
                return band
        mode = self._mode_at(now_min)
        if mode is None:
            return None
        return self.params_for(entity_id, mode)

    def _rebuild_day_plan(self) -> None:
        """Rebuild the fixed-step transition plan for upcoming bands.

        astral/锚点解析只在重建时发生一次，步进点本身是纯查表下发；
        句柄集中管理，stop()/重建时全部取消。
        """
        for unsub in self._plan_unsub.values():
            unsub()
        self._plan_unsub.clear()
        self._plan.clear()
        if self._stopped or not self._has_transitions:
            return
        now = dt_util.now()
        claimed: set[tuple[datetime, str]] = set()
        for anchor_min, target_mode, dur in self._transition_bands():
            band_start_min = (anchor_min - dur) % 1440
            start = upcoming_band_start(now, band_start_min, dur)
            if start is None:
                continue
            anchor_dt = start + timedelta(minutes=dur)
            from_mode = self._mode_at(band_start_min)
            if from_mode is None:
                _LOGGER.debug(
                    "Band ending at %s has no active from-mode, not scheduled",
                    anchor_dt,
                )
                continue
            band_key = (band_start_min, target_mode, start.date().isoformat())
            for step_dt in step_datetimes(start, anchor_dt, self.transition_interval):
                if step_dt <= now:
                    continue  # 已过去的步进不补发
                factor = (step_dt - start).total_seconds() / 60 / dur
                entrance = step_dt == start
                for entity_id in self.lights:
                    # 重叠带去重：与 _band_params 相同的优先序，先处理的带
                    # 胜出，保证重叠区只有一条带在控（否则接管状态互相踩）
                    claim = (step_dt, entity_id)
                    if claim in claimed:
                        continue
                    claimed.add(claim)
                    b, k = lerp_params(
                        self.params_for(entity_id, from_mode),
                        self.params_for(entity_id, target_mode),
                        factor,
                    )
                    self._plan.setdefault(step_dt, []).append(
                        PlanStep(entity_id, b, k, band_key, entrance)
                    )
        for when, steps in self._plan.items():
            self._plan_unsub[when] = async_track_point_in_time(
                self.hass, self._make_plan_step_callback(when, steps), when
            )
        _LOGGER.info("Transition plan rebuilt: %d step point(s)", len(self._plan))

    def _make_plan_step_callback(self, when: datetime, steps: list[PlanStep]):
        @callback
        def _run(_now) -> None:
            self._plan_unsub.pop(when, None)
            if self._stopped:
                return
            self.hass.async_create_task(self._async_run_steps(steps))

        return _run

    async def _async_run_steps(self, steps: list[PlanStep]) -> None:
        """Execute one step point: band-entry reset, takeover check, steer."""
        for step in steps:
            machine = self.machines.get(step.entity_id)
            if machine is None:
                continue
            if machine.state == LightState.TURN_ON_PENDING:
                # 开灯监听已在处理（settle delay 中），等其重新播种预期，
                # 否则刚开灯的默认态会被误判成手动调节 (P3 竞态)
                continue
            if machine.band_key != step.band_key:
                # 带入口：清接管；预期值仅入口步播种（=起点参数）。
                # 入带时不在曲线上的灯（已处夜间参数/被手动调过）在这里
                # 被判接管，整带保持现状——带内手动优先，锚点归位。
                # 中途入表（重启/重建后首观测步非入口）预期置 None：跳过
                # 一次判定，按旧行为拉回曲线一次后再正常判定 (P1)。
                machine.band_key = step.band_key
                machine.manual_override = False
                machine.expected = (
                    (step.brightness, step.kelvin) if step.entrance else None
                )
            if machine.manual_override:
                _LOGGER.debug("%s manual override active, step skipped", step.entity_id)
                continue
            state = self.hass.states.get(step.entity_id)
            if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                continue
            # 接管判定只在可核验（亮且上报亮度）时进行；关灯/无亮度上报
            # 不判接管 (P2a)
            verifiable = state.state == STATE_ON and (
                state.attributes.get(ATTR_BRIGHTNESS) is not None
            )
            if (
                self.respect_manual
                and verifiable
                and machine.expected is not None
                and not self._matches(state, *machine.expected)
            ):
                machine.manual_override = True
                _LOGGER.info(
                    "%s manual change detected (current %s/%sK, expected "
                    "%s%%/%sK) — light left alone until next anchor",
                    step.entity_id,
                    state.attributes.get(ATTR_BRIGHTNESS),
                    state.attributes.get(ATTR_COLOR_TEMP_KELVIN),
                    machine.expected[0],
                    machine.expected[1],
                )
                continue
            ok = await self._async_process_light(
                step.entity_id,
                step.brightness,
                step.kelvin,
                allow_turn_on=False,
                transition_s=self.transition_interval * 60,
            )
            # 仅在确实生效（已匹配或下发成功）时推进预期；服务失败保持
            # 上次预期，下一步可重试且不会误判接管 (P2b)。不可核验的灯
            # 不推进预期，后续步持续跳过接管判定。
            if ok and verifiable:
                machine.expected = (step.brightness, step.kelvin)

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
        params = self.current_params(entity_id)
        if params is None:
            _LOGGER.debug("%s turned on outside all active periods, ignored", entity_id)
            return
        brightness, kelvin = params
        machine = self.machines.get(entity_id)
        if machine is None:
            _LOGGER.debug(
                "%s not in machine table (stale listener?), skipped", entity_id
            )
            return
        # 关→开重新加入曲线：清接管并重设预期基准
        machine.manual_override = False
        machine.expected = params
        machine.state = LightState.TURN_ON_PENDING
        _LOGGER.info(
            "%s turned on (target %s%%/%sK), checking after %.1fs settle delay",
            entity_id,
            brightness,
            kelvin,
            self.settle_delay,
        )
        self._delay(
            self.settle_delay,
            lambda _now: self.hass.async_create_task(
                self._async_process_light(entity_id, brightness, kelvin)
            ),
        )

    async def async_trigger(self, reason: str = "manual") -> None:
        """Run one check-and-set round for all lights (concurrent per light).

        使用当前时段参数而非硬编码夜间参数 (M2)，白天手动触发不会再把灯
        调到夜间亮度；逐灯并发避免灯具多时串行等待拖长整轮时间 (L5)。
        """
        _LOGGER.info("Auto night light triggered (%s)", reason)

        async def _one(entity_id: str) -> None:
            params = self.current_params(entity_id)
            if params is None:
                _LOGGER.debug("%s outside all active periods, skipped", entity_id)
                return
            machine = self.machines.get(entity_id)
            if machine is not None:
                # 锚点归位：清除带内接管，预期基准重置为当前时段参数
                machine.manual_override = False
                machine.expected = params
            await self._async_process_light(entity_id, *params)

        results = await asyncio.gather(
            *(_one(entity_id) for entity_id in self.lights),
            return_exceptions=True,
        )
        for entity_id, result in zip(self.lights, results):
            if isinstance(result, Exception):
                _LOGGER.error("%s trigger round failed: %s", entity_id, result)

    @staticmethod
    def _to_pct(brightness_byte: int) -> int:
        """Convert HA brightness (0-255) to percent."""
        return round(brightness_byte * 100 / 255)

    @staticmethod
    def _to_byte(brightness_pct: float) -> int:
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
        if cur_brightness is None:
            return False
        if abs(self._to_pct(cur_brightness) - brightness) > self.tol_brightness:
            return False
        # 灯具不支持/未上报色温时仅校验亮度
        if not self._supports_color_temp(state):
            return True
        # 支持色温但当前处于彩光（hs/rgb）模式：状态里没有 color_temp_kelvin，
        # 不能视为已匹配，需要纠回色温 (M3)
        color_mode = state.attributes.get("color_mode")
        if color_mode is not None and color_mode != "color_temp":
            return False
        cur_kelvin = state.attributes.get(ATTR_COLOR_TEMP_KELVIN)
        return cur_kelvin is None or abs(cur_kelvin - kelvin) <= self.tol_kelvin

    async def _async_process_light(
        self,
        entity_id: str,
        brightness: int,
        kelvin: int,
        allow_turn_on: bool = True,
        transition_s: int | None = None,
    ) -> bool:
        """Advance the state machine for one light.

        Returns True when the light matched or the command was accepted.
        """
        if self._stopped:
            return False
        machine = self.machines[entity_id]
        machine.state = LightState.PENDING
        state = self.hass.states.get(entity_id)

        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            machine.state = LightState.OFFLINE
            _LOGGER.warning("%s unavailable, skipped", entity_id)
            return False

        if state.state != STATE_ON and (self.only_when_on or not allow_turn_on):
            machine.state = LightState.SKIPPED_OFF
            _LOGGER.debug("%s is off, skipped", entity_id)
            return False

        if self._matches(state, brightness, kelvin):
            machine.state = LightState.MATCHED
            _LOGGER.debug("%s already matches target, no service call", entity_id)
            return True

        # 状态不符，下发控制
        machine.state = LightState.SETTING
        machine.target = (brightness, kelvin)
        service_data = {
            ATTR_ENTITY_ID: entity_id,
            ATTR_BRIGHTNESS: self._to_byte(brightness),
        }
        if transition_s is not None:
            # 灯具原生渐变：步进之间由灯平滑滑变（不支持的灯自动忽略）
            service_data[ATTR_TRANSITION] = transition_s
        if self._supports_color_temp(state):
            # NumberSelector 可能给出 float，个别灯平台对类型严格校验 (L9)
            service_data[ATTR_COLOR_TEMP_KELVIN] = int(kelvin)
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
            return False

        # 延迟验证，避免灯具状态尚未刷新
        self._delay(
            self.verify_delay,
            lambda _now: self.hass.async_create_task(self._async_verify(entity_id)),
        )
        return True

    async def _async_verify(self, entity_id: str) -> None:
        """Verify the light reached the target after control."""
        if self._stopped:
            return
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
