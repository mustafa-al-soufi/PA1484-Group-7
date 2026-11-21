"""Trafiklab Realtime API (departures) and ResRobot (journeys, US5.3).

Answers are read in chunks, one JSON object at a time, to save memory.
Everything blocks: only call it from the background worker.
"""

import json
import time

import urequests

from secrets import RESROBOT_API_KEY, TRAFIKLAB_API_KEY

BASE_URL = "https://realtime-api.trafiklab.se/v1/"
TRIP_URL = "https://api.resrobot.se/v2.1/trip?format=json&passlist=0&numF="
CHUNK_SIZE = 2048  # bytes read at a time

# MicroPython only (None in the PC tests)
_sleep_ms = getattr(time, "sleep_ms", None)
_ticks_ms = getattr(time, "ticks_ms", None)

# While the user scrolls, and CALM_MS after, the fetch waits for the UI
# (at most MAX_PAUSE_MS at a time).
CALM_MS = 500
MAX_PAUSE_MS = 3000
_scrolling = False
_scroll_end = 0  # ticks_ms when the last scroll ended

EXTRA_DEPARTURES = 5  # sorted by time, but a delay can move one: read a few more
DELAY_THRESHOLD_S = 60  # "Delayed" from this many seconds late

TRANSPORT_ALL = "All"  # no filter
# App names -> API names. The API calls ferries BOAT.
TRANSPORT_API_NAMES = {"Bus": "BUS", "Train": "TRAIN", "Ferry": "BOAT"}

# Karlskrona area: a stop must have a child stop in this box (US3.2C)
AREA_LAT_MIN = 56.05
AREA_LAT_MAX = 56.35
AREA_LON_MIN = 15.45
AREA_LON_MAX = 16.05

# Selectable stops in dropdown order (the first is the default). Fixed ids
# from the Realtime API (busiest matching area): no searches at start-up.
STOPS = (
    {"id": "740000230", "name": "Karlskrona Centralstation"},  # train, bus
    {"id": "740032188", "name": "Campus Gräsvik"},  # bus, BTH campus
    {"id": "740020510", "name": "Kungsplan"},  # main bus hub
    {"id": "740001537", "name": "Bergåsa station"},  # train, bus
    {"id": "740020699", "name": "Handelshamnen"},  # ferry
)

_last_error = ""


def get_last_error():
    return _last_error  # '' if the last request worked


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
    """Make text safe for a URL; å, ä, ö become %-codes (US3.2C)."""
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = ""
    for byte in text.encode("utf-8"):
        char = chr(byte)
        encoded += char if char in safe else "%{:02X}".format(byte)
    return encoded


def _in_area(group):
    """True if a child stop of ``group`` is in the Karlskrona area (US3.2C)."""
    for child in group.get("stops") or []:
        lat, lon = child.get("lat"), child.get("lon")
        if lat is None or lon is None:
            continue
        if AREA_LAT_MIN <= lat <= AREA_LAT_MAX and AREA_LON_MIN <= lon <= AREA_LON_MAX:
            return True
    return False


def get_stops():
    """The selectable stops as a new list (the caller may change it)."""
    return [dict(stop) for stop in STOPS]


def set_scrolling(scrolling):
    """Called by the UI when a scroll or swipe starts (True) and ends (False)."""
    global _scrolling, _scroll_end
    _scrolling = scrolling
    if not scrolling and _ticks_ms is not None:
        _scroll_end = _ticks_ms()


def is_scrolling():
    return _scrolling


def _ui_is_busy():
    return _scrolling or time.ticks_diff(_ticks_ms(), _scroll_end) < CALM_MS


def yield_to_ui():
    """Let the UI thread draw, and wait while the user scrolls."""
    if _sleep_ms is None:
        return  # PC tests
    _sleep_ms(1)
    waited = 0
    while waited < MAX_PAUSE_MS and _ui_is_busy():
        _sleep_ms(20)
        waited += 20


def _open(path):
    """GET a Realtime API path; the body is not read yet."""
    url = BASE_URL + path + "?key=" + TRAFIKLAB_API_KEY
    yield_to_ui()  # do not start TLS during a scroll
    try:
        response = urequests.get(url, timeout=10)
    except TypeError:  # older urequests has no timeout
        response = urequests.get(url)
    if response.status_code != 200:
        status = response.status_code
        response.close()
        raise Exception("HTTP " + str(status))
    return response


def _find(buffer, char, start, size):
    position = buffer.find(char, start)
    return size if position < 0 else position


def _iter_json_array(stream, key, needles=None):
    """Yield the objects of the JSON array ``key`` (bytes) from ``stream``.

    Objects are cut out by counting braces. With ``needles`` (bytes), objects
    that contain none of them are skipped before json.loads.
    """
    marker = b'"' + key + b'"'
    # Read until the key; keep the end of the buffer for a key split in two
    buffer = b""
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            return
        buffer += chunk
        key_pos = buffer.find(marker)
        if key_pos >= 0:
            buffer = buffer[key_pos + len(marker) :]
            break
        buffer = buffer[-len(marker) :]

    # find() runs in C: the loop only jumps between quotes, backslashes and
    # braces. ``size`` = not in this chunk.
    in_array = in_string = escaped = False
    depth = 0  # open {
    pieces = []  # parts of an object from earlier chunks
    while True:
        start = 0 if depth > 0 else -1
        size = len(buffer)
        i = 0
        if escaped:  # the last chunk ended after a backslash
            i, escaped = 1, False
        quote = slash = opening = closing = -1
        while i < size:
            if quote < i:
                quote = _find(buffer, b'"', i, size)
            if in_string:
                if slash < i:
                    slash = _find(buffer, b"\\", i, size)
                if slash < quote:
                    i = slash + 2  # skip the escaped character
                    escaped = i > size
                    continue
                if quote == size:
                    break  # the string goes on in the next chunk
                in_string = False
                i = quote + 1
                continue
            if depth > 0:  # in an object only quotes and braces matter
                if opening < i:
                    opening = _find(buffer, b"{", i, size)
                if closing < i:
                    closing = _find(buffer, b"}", i, size)
                i = min(quote, opening, closing)
                if i == size:
                    break
            byte = buffer[i]
            if byte == 34:  # "
                in_string = True
            elif byte == 123:  # {
                if depth == 0:
                    if not in_array:
                        return  # the value is not an array
                    start = i
                depth += 1
            elif byte == 125:  # }
                depth -= 1
                if depth == 0:
                    pieces.append(buffer[start : i + 1])
                    object_bytes = b"".join(pieces)  # one copy only
                    pieces = []
                    start = -1
                    if needles is None or any(n in object_bytes for n in needles):
                        yield json.loads(object_bytes)
            elif depth == 0:
                if byte == 91:  # [
                    in_array = True
                elif byte == 93 and in_array:  # ] ends the array
                    return
            i += 1
        if depth > 0:
            pieces.append(buffer[start:])
        yield_to_ui()
        buffer = stream.read(CHUNK_SIZE)
        if not buffer:
            return


def _status(item):
    if item.get("canceled"):
        return "Canceled"
    if (item.get("delay") or 0) >= DELAY_THRESHOLD_S:
        return "Delayed"
    return "On time"


def _matches_transport(item, transport):
    if transport == TRANSPORT_ALL:
        return True
    mode = ((item.get("route") or {}).get("transport_mode") or "").upper()
    return mode == TRANSPORT_API_NAMES.get(transport, transport.upper())


def _to_departure(item):
    """Only the fields the UI needs."""
    route = item.get("route") or {}
    realtime = item.get("realtime") or item.get("scheduled") or ""  # no live data
    return {
        "sort": realtime,  # ISO time sorts correctly as text
        "time": realtime[11:16],  # HH:MM
        "line": route.get("designation") or route.get("name") or "",
        "destination": route.get("direction") or "",
        "status": _status(item),
        "transport": route.get("transport_mode") or "",
    }


def _sort_key(departure):
    return departure["sort"]


def get_departures(stop_id, limit=15, transport=TRANSPORT_ALL):
    """The next ``limit`` departures of ``transport``: a list, or None on error."""
    response = None
    try:
        response = _open("departures/" + str(stop_id))
        # Skip other types before json.loads (checked again below)
        needles = None
        if transport != TRANSPORT_ALL:
            mode = TRANSPORT_API_NAMES.get(transport, transport.upper()).encode()
            needles = (b'"' + mode + b'"', b'"' + mode.lower() + b'"')
        kept = []
        for item in _iter_json_array(response.raw, b"departures", needles):
            if _matches_transport(item, transport):
                kept.append(_to_departure(item))
                if len(kept) >= limit + EXTRA_DEPARTURES:
                    break  # the rest are later
        kept.sort(key=_sort_key)
        del kept[limit:]
        _clear_error()
        return kept
    except Exception as error:
        _set_error(_describe(error))
        return None
    finally:
        if response is not None:
            response.close()


def _as_list(value):
    """ResRobot gives a list for many items, an object for one."""
    if isinstance(value, list):
        return value
    return [value] if value else []


def _place(place, key):
    return (place or {}).get(key) or ""


# Words in ResRobot line names -> transport types in the app (US3.3)
LINE_TYPES = (("buss", "Bus"), ("tåg", "Train"), ("båt", "Ferry"), ("färja", "Ferry"))


def _line_name(name):
    """"Länstrafik - Buss 6" -> "Bus 6", "Öresundståg 1076" -> "Train 1076"."""
    lower = name.lower()
    number = name.split(" ")[-1]
    for word, label in LINE_TYPES:
        if word in lower:
            return label + " " + number if number.isdigit() else label
    return name


def _to_trip(trip):
    """Keep only what the screen shows. Only JNY legs are rides."""
    legs = _as_list((trip.get("LegList") or {}).get("Leg"))
    if not legs:
        return None
    rides = []
    for leg in legs:
        if leg.get("type") == "JNY":
            rides.append({
                "time": _place(leg.get("Origin"), "time")[:5],
                "stop": _place(leg.get("Origin"), "name").split(" (")[0],  # no "(..kn)"
                "line": _line_name(leg.get("name") or ""),
            })
    return {
        "departure": _place(legs[0].get("Origin"), "time")[:5],
        "arrival": _place(legs[-1].get("Destination"), "time")[:5],
        "changes": max(len(rides) - 1, 0),
        "rides": rides,
    }


def get_trips(origin_id, dest_id, limit=5):
    """The next journeys between two stops, or None if it failed."""
    url = "%s%d&originId=%s&destId=%s&accessId=%s" % (
        TRIP_URL, limit, origin_id, dest_id, RESROBOT_API_KEY)
    response = None
    try:
        yield_to_ui()
        response = urequests.get(url)
        if response.status_code != 200:
            raise Exception("HTTP " + str(response.status_code))
        trips = []
        for item in _iter_json_array(response.raw, b"Trip"):
            trip = _to_trip(item)
            if trip is not None:
                trips.append(trip)
            if len(trips) >= limit:
                break
        _clear_error()
        return trips
    except Exception as error:
        _set_error(_describe(error))
        return None
    finally:
        if response is not None:
            response.close()
