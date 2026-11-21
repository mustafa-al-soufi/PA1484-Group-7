"""Saves and loads the user's default settings (US3.4, US3.5).

Stored as JSON in the flash, so they survive a restart. A missing or
broken file is not an error: the defaults are used.
"""

import json

SETTINGS_FILE = "settings.json"
VALID_TRANSPORTS = ("All", "Bus", "Train", "Ferry")  # as in the settings screen
DEFAULTS = {"stop_id": None, "stop_name": "", "transport": "All"}  # None = first stop


def defaults():
    return dict(DEFAULTS)


def _clean(data):
    """Valid settings from ``data``: unknown keys dropped, bad values = defaults."""
    settings = defaults()
    if not isinstance(data, dict):
        return settings
    if data.get("stop_id") is not None:
        settings["stop_id"] = str(data["stop_id"])
        settings["stop_name"] = str(data.get("stop_name") or "")
    if data.get("transport") in VALID_TRANSPORTS:
        settings["transport"] = data["transport"]
    return settings


def load():
    """The saved settings, or the defaults if there are none."""
    try:
        with open(SETTINGS_FILE) as file:
            return _clean(json.load(file))
    except OSError:
        return defaults()  # nothing saved yet
    except ValueError:
        print("Settings file is damaged, using defaults")
        return defaults()


def save(settings):
    """Save ``settings`` as the new defaults. True if it worked."""
    try:
        with open(SETTINGS_FILE, "w") as file:
            json.dump(_clean(settings), file)
        return True
    except Exception as error:
        print("Could not save settings:", error)
        return False
