"""Constants for HA Auto Night Light."""

DOMAIN = "auto_night_light"

CONF_LIGHTS = "lights"
CONF_TRIGGER_TIME = "trigger_time"
CONF_END_TIME = "end_time"
CONF_SUN_ENTITY = "sun_entity"
CONF_START_MODE = "start_mode"
CONF_START_OFFSET = "start_offset"
CONF_END_MODE = "end_mode"
CONF_END_OFFSET = "end_offset"
CONF_EXTRA_ENABLED = "extra_enabled"
CONF_EXTRA_COUNT = "extra_count"
CONF_EXTRAS = "extras"
CONF_BRIGHTNESS = "brightness"
CONF_COLOR_TEMP_KELVIN = "color_temp_kelvin"
CONF_DAY_ENABLED = "day_enabled"
CONF_DAY_BRIGHTNESS = "day_brightness"
CONF_DAY_COLOR_TEMP_KELVIN = "day_color_temp_kelvin"
CONF_TOLERANCE_BRIGHTNESS = "tolerance_brightness"
CONF_TOLERANCE_KELVIN = "tolerance_kelvin"
CONF_VERIFY_DELAY = "verify_delay"
CONF_ONLY_WHEN_ON = "only_when_on"
CONF_TURN_ON_LISTEN = "turn_on_listen"
CONF_SETTLE_DELAY = "settle_delay"
CONF_CUSTOM_PER_LIGHT = "custom_per_light"
CONF_OVERRIDES = "overrides"

# 锚点时间来源（夜间开始 / 夜间结束各自独立选择）
ANCHOR_FIXED = "fixed"  # 固定时间
ANCHOR_SUNSET = "sunset"  # 日落 + 偏移
ANCHOR_SUNRISE = "sunrise"  # 日出 + 偏移
ANCHOR_MODES = [ANCHOR_FIXED, ANCHOR_SUNSET, ANCHOR_SUNRISE]

DEFAULT_SUN_ENTITY = "sun.sun"
MAX_EXTRA_PERIODS = 5

# 额外时段列表项的子键
EXTRA_NAME = "name"
EXTRA_START = "start"
EXTRA_BRIGHTNESS = "brightness"
EXTRA_COLOR_TEMP_KELVIN = "color_temp_kelvin"

# 逐灯覆盖的子键
OVR_BRIGHTNESS = "brightness"
OVR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
OVR_DAY_BRIGHTNESS = "day_brightness"
OVR_DAY_COLOR_TEMP_KELVIN = "day_color_temp_kelvin"
OVR_EXTRAS = "extras"  # {时段序号(字符串): {"brightness": int, "color_temp_kelvin": int}}
OVR_EXTRA_BRIGHTNESS = "brightness"
OVR_EXTRA_COLOR_TEMP_KELVIN = "color_temp_kelvin"

DEFAULT_BRIGHTNESS = 25
DEFAULT_COLOR_TEMP_KELVIN = 2200
DEFAULT_END_TIME = "06:00:00"
DEFAULT_START_OFFSET = 0
DEFAULT_END_OFFSET = 0
DEFAULT_EXTRA_START = "18:00:00"
DEFAULT_EXTRA_BRIGHTNESS = 60
DEFAULT_EXTRA_COLOR_TEMP_KELVIN = 3000
DEFAULT_TOLERANCE_BRIGHTNESS = 4
DEFAULT_TOLERANCE_KELVIN = 150
DEFAULT_VERIFY_DELAY = 5
DEFAULT_TURN_ON_LISTEN = True
DEFAULT_SETTLE_DELAY = 1
DEFAULT_DAY_BRIGHTNESS = 100
DEFAULT_DAY_COLOR_TEMP_KELVIN = 4000

MODE_NIGHT = "night"
MODE_DAY = "day"
MODE_EXTRA_PREFIX = "extra_"  # extra_0, extra_1, ...

SERVICE_TRIGGER_NOW = "trigger_now"
