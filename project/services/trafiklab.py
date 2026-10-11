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

# "All" means no transport filter. The API writes BUS, TRAIN and FERRY.
TRANSPORT_ALL = "All"

# A stop is in Karlskrona if one of its child stops is inside this box.
# This removes look-alikes such as "Malmo Karlskronaplan".
AREA_LAT_MIN = 56.05
AREA_LAT_MAX = 56.35
AREA_LON_MIN = 15.45
AREA_LON_MAX = 16.05

# The API cannot list stops near a position, so we search for each locality
# name instead. Add a name here if a stop is missing.
SEARCH_TERMS = (
    "Karlskrona",
    "Lyckeby",
    "Nättraby",
    "Rödeby",
    "Jämjö",
    "Sturkö",
    "Hasslö",
    "Tjurkö",
    "Torhamn",
    "Ramdala",
    "Trummenäs",
    "Aspö",
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
    """Make text safe for a URL, so 'Nättraby' becomes 'N%C3%A4ttraby'."""
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


def _stop_name(group):
    """Return the real name of a stop area.

    The group name is used if a child stop has the same name. Otherwise it
    is only a label, so the shortest child name is used.
    """
    name = group.get("name") or ""
    shortest = None
    for child in group.get("stops") or []:
        child_name = child.get("name") or ""
        if child_name == name:
            return name
        if child_name and (shortest is None or len(child_name) < len(shortest)):
            shortest = child_name
    return shortest or name


def _traffic_key(stop):
    """Sort key that puts the busiest stops first."""
    return -stop["traffic"]


def find_stops(town, limit=40):
    """Find the stop areas in Karlskrona municipality.

    The stops come from one name search per entry in SEARCH_TERMS, filtered
    by coordinates. Meta stops (like "Karlskrona") and stops without traffic
    are skipped. ``town`` is only used in the error text.

    Returns a list of dicts with 'id', 'name' and 'traffic', busiest first,
    or None if nothing could be fetched (see get_last_error).
    """
    stops = []
    seen_ids = set()
    seen_names = set()
    failures = 0
    last_failure = ""

    for term in SEARCH_TERMS:
        response = None
        try:
            gc.collect()
            response = _open("stops/name/" + _url_encode(term))

            for group in _iter_json_array(response.raw, b"stop_groups"):
                group_id = group.get("id")
                traffic = group.get("average_daily_stop_times") or 0

                if group.get("area_type") == "META_STOP":
                    continue
                if traffic <= 0 or group_id in seen_ids:
                    continue
                if not _in_area(group):
                    continue

                name = _stop_name(group)
                if not name or name in seen_names:
                    continue

                seen_ids.add(group_id)
                seen_names.add(name)
                stops.append({"id": group_id, "name": name, "traffic": traffic})
        except Exception as error:
            failures += 1
            last_failure = _describe(error)
        finally:
            if response is not None:
                response.close()
            gc.collect()

    if not stops:
        _set_error(last_failure or "No stops found: " + town)
        return None

    # A few failed searches are fine, the list is just shorter
    if failures:
        print("Trafiklab: %d stop searches failed" % failures)
    _clear_error()

    stops.sort(key=_traffic_key)
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
    return mode == transport.upper()


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
