"""Persistent user settings (US3.4 save, US3.5 reset).

The settings are stored as a small JSON file in the flash file system of the
ESP32, so they survive a restart. A missing or damaged file is never an
error: the built-in defaults are used instead.
"""

import json

# File on the ESP32 file system (created on the first save)
SETTINGS_FILE = "settings.json"

# Transport types that may be stored (must match the settings screen)
VALID_TRANSPORTS = ("All", "Bus", "Train", "Ferry")

# Built-in defaults: the busiest stop (stop_id None) and all transport types
DEFAULTS = {
    "stop_id": None,
    "stop_name": "",
    "transport": "All",
}


def defaults():
    """Return a fresh copy of the built-in default settings."""
    return dict(DEFAULTS)


def _clean(data):
    """Return a valid settings dict built from ``data``.

    Unknown keys are dropped and invalid values fall back to the defaults, so
    a hand-edited or half-written file cannot crash the application.
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
    """Load the saved default settings.

    Returns:
        A dict with 'stop_id', 'stop_name' and 'transport'. If nothing has
        been saved yet, or the file is unreadable, the built-in defaults.
    """
    try:
        with open(SETTINGS_FILE) as file:
            return _clean(json.load(file))
    except OSError:
        # No file yet: nothing has been saved
        return defaults()
    except ValueError:
        # File exists but is not valid JSON
        print("Settings file is damaged, using defaults")
        return defaults()


def save(settings):
    """Save ``settings`` as the new default settings.

    Args:
        settings: Dict with 'stop_id', 'stop_name' and 'transport'.

    Returns:
        True if the file was written, False on failure.
    """
    try:
        with open(SETTINGS_FILE, "w") as file:
            json.dump(_clean(settings), file)
        return True
    except Exception as error:
        print("Could not save settings:", error)
        return False
