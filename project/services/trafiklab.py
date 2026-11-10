"""Trafiklab Realtime API: find stops and get departures.

The ESP32 has little memory, so the answers are read in small chunks and
one JSON object at a time. All functions block, so only call them from the
background worker.
"""

import gc
import json

import urequests

from secrets import TRAFIKLAB_API_KEY

BASE_URL = "https://realtime-api.trafiklab.se/v1/"

# Bytes read from the connection at a time
CHUNK_SIZE = 1024

# A departure is "Delayed" when it is at least this many seconds late
DELAY_THRESHOLD_S = 60

# "All" means no transport filter
TRANSPORT_ALL = "All"

# The names in the app and the names the API uses for them. The API writes
# BOAT for ferries, so "Ferry" must be translated.
TRANSPORT_API_NAMES = {
    "Bus": "BUS",
    "Train": "TRAIN",
    "Ferry": "BOAT",
}

# A stop must have a child stop inside this box. This removes stops with
# the same name in other towns.
AREA_LAT_MIN = 56.05
AREA_LAT_MAX = 56.35
AREA_LON_MIN = 15.45
AREA_LON_MAX = 16.05

# The five stops that can be selected, in dropdown order. The first one is
# shown at start-up when no default is saved.
#   name:   the text shown in the app
#   search: names sent to the API, tried in order until the stop is found
#   match:  whole words that must be in the stop name, so "Karlskrona C"
#           does not match "Karlskrona Campus Grasvik"
STOPS = (
    {
        # Train and bus
        "name": "Karlskrona Centralstation",
        "search": ("Karlskrona",),
        "match": ("karlskrona c", "karlskrona centralstation", "karlskrona station"),
    },
    {
        # Bus, BTH campus
        "name": "Campus Gräsvik",
        "search": ("Gräsvik",),
        "match": ("gräsvik",),
    },
    {
        # Bus, the main bus hub in the city centre
        "name": "Kungsplan",
        "search": ("Kungsplan",),
        "match": ("kungsplan",),
    },
    {
        # Train and bus, the second train station in Karlskrona
        "name": "Bergåsa station",
        "search": ("Bergåsa",),
        "match": ("bergåsa",),
    },
    {
        # Ferry, the commuter boats to Sturkö and Trummenäs run all year
        "name": "Handelshamnen",
        "search": ("Handelshamnen",),
        "match": ("handelshamnen",),
    },
)

# Description of the last failure, "" if the last request worked
_last_error = ""


def get_last_error():
    """Return a short text about the last failed request ('' if none)."""
    return _last_error


def _set_error(text):
    global _last_error
    _last_error = str(text)[:40]
    print("Trafiklab error:", _last_error)


def _clear_error():
    global _last_error
    _last_error = ""


def _describe(error):
    """Turn an exception into text like 'OSError -202'."""
    return type(error).__name__ + " " + str(error)


def _url_encode(text):
    """Make text safe for a URL.

    Letters like å, ä and ö are not allowed in a URL, so they are replaced
    with %-codes that the server turns back into the right letters.
    """
    safe_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = ""
    for byte in text.encode("utf-8"):
        char = chr(byte)
        encoded += char if char in safe_chars else "%{:02X}".format(byte)
    return encoded


def _open(path):
    """Send a GET request and return the open response.

    The body is not read yet. Raises an exception if the status is not 200.
    """
    url = BASE_URL + path + "?key=" + TRAFIKLAB_API_KEY
    try:
        response = urequests.get(url, timeout=10)
    except TypeError:
        # Older urequests has no timeout argument
        response = urequests.get(url)

    if response.status_code != 200:
        status = response.status_code
        response.close()
        raise Exception("HTTP " + str(status))
    return response


def _iter_json_array(stream, key):
    """Yield the objects of a JSON array one at a time.

    ``stream`` is anything with read(n), for example response.raw, and ``key``
    is the name of the array as bytes, for example b"departures". Each object
    is cut out by counting braces and then decoded with json.loads.
    """
    marker = b'"' + key + b'"'
    marker_len = len(marker)

    # Step 1: read until the key is found. Keep the end of the buffer so a
    # key that is split between two chunks is still found.
    buffer = b""
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            return
        buffer += chunk
        key_pos = buffer.find(marker)
        if key_pos >= 0:
            buffer = buffer[key_pos + marker_len :]
            break
        buffer = buffer[-marker_len:]

    # Step 2: go through the bytes and cut out each object
    in_array = False
    in_string = False
    escaped = False
    depth = 0  # how many { are open right now
    partial = b""  # start of an object from an earlier chunk

    while True:
        # An object that is still open continues at the start of this chunk
        start = 0 if depth > 0 else -1

        for i in range(len(buffer)):
            byte = buffer[i]

            if in_string:
                # Inside a string only the closing quote matters
                if escaped:
                    escaped = False
                elif byte == 92:  # backslash
                    escaped = True
                elif byte == 34:  # quote
                    in_string = False
            elif byte == 34:  # quote
                in_string = True
            elif byte == 123:  # {
                if depth == 0:
                    if not in_array:
                        return  # the value was not an array
                    start = i
                    partial = b""
                depth += 1
            elif byte == 125:  # }
                depth -= 1
                if depth == 0:
                    # The object is complete
                    object_bytes = partial + buffer[start : i + 1]
                    yield json.loads(str(object_bytes, "utf-8"))
                    start = -1
                    partial = b""
            elif depth == 0:
                if byte == 91:  # [
                    in_array = True
                elif byte == 93 and in_array:  # ] ends the array
                    return

        # The chunk ended inside an object: save what we have so far
        if depth > 0:
            partial += buffer[start:]

        buffer = stream.read(CHUNK_SIZE)
        if not buffer:
            return


def _in_area(group):
    """Return True if a child stop of ``group`` is inside Karlskrona."""
    for child in group.get("stops") or []:
        lat = child.get("lat")
        lon = child.get("lon")
        if lat is None or lon is None:
            continue
        if AREA_LAT_MIN <= lat <= AREA_LAT_MAX and AREA_LON_MIN <= lon <= AREA_LON_MAX:
            return True
    return False


def _padded(text):
    """Lower-case ``text`` with spaces around every word, for word matching."""
    text = str(text or "").lower()
    for char in ",()-/":
        text = text.replace(char, " ")
    return " " + text + " "


def _matches(group, words):
    """Return True if the group name or a child name contains one of ``words``."""
    names = [group.get("name")]
    for child in group.get("stops") or []:
        names.append(child.get("name"))

    for name in names:
        padded = _padded(name)
        for word in words:
            if " " + word + " " in padded:
                return True
    return False


def _search(term, best):
    """Search the API for ``term`` and update ``best`` with the stops found.

    ``best`` has one place per entry in STOPS. Every stop area in the answer
    is checked against all entries, so one search can find several stops.
    If several stop areas match an entry, the busiest one is kept.
    """
    response = None
    try:
        gc.collect()
        response = _open("stops/name/" + _url_encode(term))

        for group in _iter_json_array(response.raw, b"stop_groups"):
            if not _in_area(group):
                continue

            # Busy stop areas win. Areas without traffic and meta stops
            # (a whole town) are only used if nothing better matches.
            traffic = group.get("average_daily_stop_times") or 0
            if group.get("area_type") == "META_STOP":
                traffic = -1

            for index, entry in enumerate(STOPS):
                if not _matches(group, entry["match"]):
                    continue
                if best[index] is None or traffic > best[index]["traffic"]:
                    best[index] = {
                        "id": group.get("id"),
                        "name": entry["name"],
                        "traffic": traffic,
                    }
    finally:
        if response is not None:
            response.close()
        gc.collect()


def find_stops(town, limit=40):
    """Find the stops in STOPS, in the same order as in STOPS.

    Each stop is searched with its own search names first and then with
    ``town`` as a last try. A stop that cannot be found is skipped, so the
    list can be shorter.

    Returns a list of dicts with 'id', 'name' and 'traffic', or None if no
    stop could be found (see get_last_error).
    """
    best = [None] * len(STOPS)
    searched = []  # each name is only sent to the API once
    last_failure = ""

    for index, entry in enumerate(STOPS):
        for term in list(entry["search"]) + [town]:
            if best[index] is not None:
                break
            if term in searched:
                continue
            searched.append(term)
            try:
                _search(term, best)
            except Exception as error:
                last_failure = _describe(error)
                print("Trafiklab: search failed:", term, last_failure)

    stops = []
    for index, stop in enumerate(best):
        if stop is None:
            print("Trafiklab: stop not found:", STOPS[index]["name"])
            continue
        if any(found["id"] == stop["id"] for found in stops):
            continue
        print("Trafiklab: stop found:", stop["name"], stop["id"])
        stops.append(stop)

    if not stops:
        _set_error(last_failure or "No stops found: " + town)
        return None

    _clear_error()
    return stops[:limit]


def _status(item):
    """Return 'On time', 'Delayed' or 'Canceled' for a raw departure."""
    if item.get("canceled"):
        return "Canceled"
    if (item.get("delay") or 0) >= DELAY_THRESHOLD_S:
        return "Delayed"
    return "On time"


def _matches_transport(item, transport):
    """Return True if the departure should be shown for this transport type."""
    if transport == TRANSPORT_ALL:
        return True
    route = item.get("route") or {}
    mode = (route.get("transport_mode") or "").upper()
    return mode == TRANSPORT_API_NAMES.get(transport, transport.upper())


def _to_departure(item):
    """Keep only the fields the UI needs, to save memory."""
    route = item.get("route") or {}
    scheduled = item.get("scheduled") or ""
    # "realtime" is missing when there is no live data
    realtime = item.get("realtime") or scheduled

    return {
        "sort": realtime,  # ISO time, sorts correctly as text
        "time": realtime[11:16],  # the HH:MM part
        "line": route.get("designation") or route.get("name") or "",
        "destination": route.get("direction") or "",
        "status": _status(item),
        "transport": route.get("transport_mode") or "",
    }


def _sort_key(departure):
    """Sort key that puts the earliest departure first."""
    return departure["sort"]


def get_departures(stop_id, limit=15, transport=TRANSPORT_ALL):
    """Get the next departures from a stop area.

    Departures of other transport types are dropped before they are stored,
    so filtering on 'Train' still fills the list with trains. Only the
    ``limit`` earliest departures are kept in memory.

    Returns a list (empty if there are none), or None if the request failed
    (see get_last_error).
    """
    response = None
    try:
        gc.collect()
        response = _open("departures/" + str(stop_id))

        kept = []
        for item in _iter_json_array(response.raw, b"departures"):
            if not _matches_transport(item, transport):
                continue
            kept.append(_to_departure(item))
            # Keep the list sorted and drop the latest one when it is full
            kept.sort(key=_sort_key)
            if len(kept) > limit:
                kept.pop()

        _clear_error()
        return kept
    except Exception as error:
        _set_error(_describe(error))
        return None
    finally:
        if response is not None:
            response.close()
        gc.collect()
