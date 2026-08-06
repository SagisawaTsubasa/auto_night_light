"""Constants for HA Auto Night Light."""

DOMAIN = "auto_night_light"

CONF_LIGHTS = "lights"
CONF_TRIGGER_TIME = "trigger_time"
CONF_END_TIME = "end_time"
CONF_USE_SUN = "use_sun"
CONF_SUN_OFFSET = "sun_offset"
CONF_EXTRA_ENABLED = "extra_enabled"
CONF_EXTRA_START = "extra_start"
CONF_BRIGHTNESS = "brightness"
CONF_COLOR_TEMP_KELVIN = "color_temp_kelvin"
CONF_EXTRA_BRIGHTNESS = "extra_brightness"
CONF_EXTRA_COLOR_TEMP_KELVIN = "extra_color_temp_kelvin"
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

# 逐灯覆盖的子键
OVR_BRIGHTNESS = "brightness"
OVR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
OVR_EXTRA_BRIGHTNESS = "extra_brightness"
OVR_EXTRA_COLOR_TEMP_KELVIN = "extra_color_temp_kelvin"
OVR_DAY_BRIGHTNESS = "day_brightness"
OVR_DAY_COLOR_TEMP_KELVIN = "day_color_temp_kelvin"

DEFAULT_BRIGHTNESS = 25
DEFAULT_COLOR_TEMP_KELVIN = 2200
DEFAULT_END_TIME = "06:00:00"
DEFAULT_SUN_OFFSET = 0
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

SUN_ENTITY = "sun.sun"  # 保留：供未来直接读取 sun 实体状态使用

MODE_NIGHT = "night"
MODE_EXTRA = "extra"
MODE_DAY = "day"

SERVICE_TRIGGER_NOW = "trigger_now"
