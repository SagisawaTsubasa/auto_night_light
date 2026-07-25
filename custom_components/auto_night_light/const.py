"""Constants for HA Auto Night Light."""

DOMAIN = "auto_night_light"

CONF_LIGHTS = "lights"
CONF_TRIGGER_TIME = "trigger_time"
CONF_END_TIME = "end_time"
CONF_BRIGHTNESS = "brightness"
CONF_COLOR_TEMP_KELVIN = "color_temp_kelvin"
CONF_TOLERANCE_BRIGHTNESS = "tolerance_brightness"
CONF_TOLERANCE_KELVIN = "tolerance_kelvin"
CONF_VERIFY_DELAY = "verify_delay"
CONF_ONLY_WHEN_ON = "only_when_on"
CONF_TURN_ON_LISTEN = "turn_on_listen"
CONF_SETTLE_DELAY = "settle_delay"
CONF_DAY_ENABLED = "day_enabled"
CONF_DAY_BRIGHTNESS = "day_brightness"
CONF_DAY_COLOR_TEMP_KELVIN = "day_color_temp_kelvin"
CONF_OVERRIDES = "overrides"

# 逐灯覆盖的子键
OVR_BRIGHTNESS = "brightness"
OVR_COLOR_TEMP_KELVIN = "color_temp_kelvin"
OVR_DAY_BRIGHTNESS = "day_brightness"
OVR_DAY_COLOR_TEMP_KELVIN = "day_color_temp_kelvin"

DEFAULT_BRIGHTNESS = 64
DEFAULT_COLOR_TEMP_KELVIN = 2200
DEFAULT_END_TIME = "06:00:00"
DEFAULT_TOLERANCE_BRIGHTNESS = 10
DEFAULT_TOLERANCE_KELVIN = 150
DEFAULT_VERIFY_DELAY = 5
DEFAULT_TURN_ON_LISTEN = True
DEFAULT_SETTLE_DELAY = 1
DEFAULT_DAY_BRIGHTNESS = 255
DEFAULT_DAY_COLOR_TEMP_KELVIN = 4000

SERVICE_TRIGGER_NOW = "trigger_now"
