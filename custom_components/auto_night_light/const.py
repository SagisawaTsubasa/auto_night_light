"""Constants for HA Auto Night Light."""

DOMAIN = "auto_night_light"

CONF_LIGHTS = "lights"
CONF_TRIGGER_TIME = "trigger_time"
CONF_END_TIME = "end_time"
CONF_SUN_SOURCE = "sun_source"
CONF_SUN_ENTITY = "sun_entity"
CONF_SUNSET_OFFSET = "sunset_offset"
CONF_SUNRISE_OFFSET = "sunrise_offset"
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

# 日出日落时间来源
SUN_SOURCE_NONE = "none"  # 固定时间
SUN_SOURCE_BUILTIN = "builtin"  # HA 内置 sun 集成
SUN_SOURCE_CUSTOM = "custom"  # 自定义实体（需含 next_rising/next_setting 属性）
SUN_SOURCES = [SUN_SOURCE_NONE, SUN_SOURCE_BUILTIN, SUN_SOURCE_CUSTOM]

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
DEFAULT_SUNSET_OFFSET = 0
DEFAULT_SUNRISE_OFFSET = 0
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
