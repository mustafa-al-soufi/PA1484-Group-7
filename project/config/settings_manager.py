"""Saves and loads the user's default settings (US3.4, US3.5).

The settings are stored as JSON in the flash memory of the ESP32, so they
are still there after a restart. A missing or broken file is not an error,
the defaults are used instead.
"""

import json

SETTINGS_FILE = "settings.json"

# Must match the transport types in the settings screen
VALID_TRANSPORTS = ("All", "Bus", "Train", "Ferry")

# stop_id None means "use the busiest stop"
DEFAULTS = {
    "stop_id": None,
    "stop_name": "",
    "transport": "All",
}


def defaults():
    """Return a new copy of the default settings."""
    return dict(DEFAULTS)


def _clean(data):
    """Return valid settings built from ``data``.

    Unknown keys are dropped and bad values become defaults, so a broken
    file can never crash the app.
    """
    settings = defaults()
    if not isinstance(data, dict):
        return settings

    stop_id = data.get("stop_id")
    if stop_id is not None:
        settings["stop_id"] = str(stop_id)
        settings["stop_name"] = str(data.get("stop_name") or "")

    if data.get("transport") in VALID_TRANSPORTS:
        settings["transport"] = data["transport"]
    return settings


def load():
    """Return the saved settings, or the defaults if there are none."""
    try:
        with open(SETTINGS_FILE) as file:
            return _clean(json.load(file))
    except OSError:
        return defaults()  # nothing saved yet
    except ValueError:
        print("Settings file is damaged, using defaults")
        return defaults()


def save(settings):
    """Save ``settings`` as the new defaults. Returns True if it worked."""
    try:
        with open(SETTINGS_FILE, "w") as file:
            json.dump(_clean(settings), file)
        return True
    except Exception as error:
        print("Could not save settings:", error)
        return False
