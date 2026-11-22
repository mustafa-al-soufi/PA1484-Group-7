"""Trafiklab: departures, stop search (US1.2B, US3.2C, US3.3), journeys via
ResRobot (US5.3). ResRobot shares the fetch and JSON reader here: a file of
its own costs 4 KB of flash. Blocks: call from the worker only."""

import json
import time

import urequests

from secrets import RESROBOT_API_KEY, TRAFIKLAB_API_KEY

BASE_URL = "https://realtime-api.trafiklab.se/v1/"
TRIP_URL = "https://api.resrobot.se/v2.1/trip?format=json&passlist=0&numF="
CHUNK_SIZE = 2048

# The fetch waits during scrolls and CALM_MS after, MAX_PAUSE_MS at most
CALM_MS = 500
MAX_PAUSE_MS = 3000

EXTRA_DEPARTURES = 5  # a delay can reorder them: read a few more
DELAY_THRESHOLD_S = 60  # seconds late = "Delayed"

TRANSPORT_ALL = "All"
TRANSPORT_API_NAMES = {"Bus": "BUS", "Train": "TRAIN", "Ferry": "BOAT"}
# Words in ResRobot line names -> transport types in the app (US3.3)
LINE_TYPES = (("buss", "Bus"), ("tåg", "Train"), ("båt", "Ferry"), ("färja", "Ferry"))

# Karlskrona area: a found stop must have a child stop in this box (US3.2C)
AREA_LAT_MIN = 56.05
AREA_LAT_MAX = 56.35
AREA_LON_MIN = 15.45
AREA_LON_MAX = 16.05

# Fixed: the app works without a search. The first is the default.
STOPS = (
    {"id": "740000230", "name": "Karlskrona Centralstation"},  # train, bus
    {"id": "740032188", "name": "Campus Gräsvik"},  # bus, BTH campus
    {"id": "740020510", "name": "Kungsplan"},  # bus hub
    {"id": "740001537", "name": "Bergåsa station"},  # train, bus
    {"id": "740020699", "name": "Handelshamnen"},  # ferry
)

_sleep_ms = getattr(time, "sleep_ms", None)  # None in the PC tests
_ticks_ms = getattr(time, "ticks_ms", None)
_scrolling = False
_scroll_end = None  # ticks_ms; None once calm, so a ticks wrap cannot matter
_last_error = ""

# --- Errors ---


def get_last_error():
    return _last_error


def _set_error(text):
    global _last_error
    _last_error = str(text)[:40]
    print("Trafiklab error:", _last_error)


def _clear_error():
    global _last_error
    _last_error = ""


# --- Stops (US3.2B, US3.2C) ---


def get_stops():
    """A new list: the caller may change it."""
    return [dict(stop) for stop in STOPS]


def _url_encode(text):
    """å, ä, ö and other characters become %-codes."""
    safe = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = ""
    for byte in text.encode("utf-8"):
        char = chr(byte)
        encoded += char if char in safe else "%{:02X}".format(byte)
    return encoded


def _in_area(group):
    for child in group.get("stops") or []:
        lat, lon = child.get("lat"), child.get("lon")
        if lat is None or lon is None:
            continue
        if AREA_LAT_MIN <= lat <= AREA_LAT_MAX and AREA_LON_MIN <= lon <= AREA_LON_MAX:
            return True
    return False


def useful_stops(groups, limit=10):
    """In the area, no META_STOP, with traffic, one per name; busiest first."""
    best = {}
    for group in groups:
        name = group.get("name") or ""
        traffic = group.get("average_daily_stop_times") or 0
        if group.get("area_type") == "META_STOP" or traffic <= 0 or not _in_area(group):
            continue
        if name not in best or traffic > best[name]["traffic"]:
            best[name] = {"id": str(group.get("id")), "name": name, "traffic": traffic}
    stops = sorted(best.values(), key=lambda stop: -stop["traffic"])
    return stops[:limit]


def search_stops(text):
    """A list, or None on error."""
    return _fetch(_realtime("stops/name/" + _url_encode(text)),
                  lambda body: useful_stops(_iter_json_array(body, b"stop_groups")))


# --- Pause during scrolling: TLS and parsing make a swipe stutter ---


def set_scrolling(scrolling):
    global _scrolling, _scroll_end
    _scrolling = scrolling
    if not scrolling and _ticks_ms is not None:
        _scroll_end = _ticks_ms()


def is_scrolling():
    return _scrolling


def _ui_is_busy():
    global _scroll_end
    if _scrolling:
        return True
    if _scroll_end is not None and time.ticks_diff(_ticks_ms(), _scroll_end) < CALM_MS:
        return True
    _scroll_end = None
    return False


def yield_to_ui():
    if _sleep_ms is None:
        return
    _sleep_ms(1)
    waited = 0
    while waited < MAX_PAUSE_MS and _ui_is_busy():
        _sleep_ms(20)
        waited += 20


# --- HTTP ---


def _realtime(path):
    return BASE_URL + path + "?key=" + TRAFIKLAB_API_KEY


def _fetch(url, read):
    """``read(body)`` of GET ``url``, or None on error."""
    response = None
    try:
        yield_to_ui()
        try:
            response = urequests.get(url, timeout=10)
        except TypeError:  # older urequests has no timeout
            response = urequests.get(url)
        if response.status_code != 200:
            raise Exception("HTTP " + str(response.status_code))
        result = read(response.raw)
        _clear_error()
        return result
    except Exception as error:
        _set_error(type(error).__name__ + " " + str(error))
        return None
    finally:
        if response is not None:
            response.close()


# --- JSON reader: answers are too big to json.loads at once ---


def _find_or_end(buffer, char, start, size):
    position = buffer.find(char, start)
    return size if position < 0 else position


def _skip_to_key(stream, marker):
    buffer = b""
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            return None
        buffer += chunk
        position = buffer.find(marker)
        if position >= 0:
            return buffer[position + len(marker):]
        buffer = buffer[-len(marker):]  # the key may be split over two chunks


def _iter_json_array(stream, key, needles=None):
    """Yield the objects of the JSON array ``key`` (bytes) from ``stream``.

    Objects are cut out by counting braces. With ``needles`` (bytes), objects
    that contain none of them are skipped before json.loads.
    """
    buffer = _skip_to_key(stream, b'"' + key + b'"')
    if buffer is None:
        return
    # Byte by byte is slow; find() runs in C: jump to quotes, backslashes, braces
    in_array = in_string = escaped = False
    depth = 0  # open {
    pieces = []  # parts of an object from earlier chunks
    while True:
        start = 0 if depth > 0 else -1
        size = len(buffer)
        i = 0
        if escaped:  # the last chunk ended in a backslash
            i, escaped = 1, False
        quote = slash = opening = closing = -1
        while i < size:
            if quote < i:
                quote = _find_or_end(buffer, b'"', i, size)
            if in_string:
                if slash < i:
                    slash = _find_or_end(buffer, b"\\", i, size)
                if slash < quote:
                    i = slash + 2  # skip the escaped character
                    escaped = i > size
                    continue
                if quote == size:
                    break  # the string goes on in the next chunk
                in_string = False
                i = quote + 1
                continue
            if depth > 0:  # inside an object only quotes and braces matter
                if opening < i:
                    opening = _find_or_end(buffer, b"{", i, size)
                if closing < i:
                    closing = _find_or_end(buffer, b"}", i, size)
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
                    pieces.append(buffer[start:i + 1])
                    object_bytes = b"".join(pieces)
                    pieces = []
                    start = -1
                    if needles is None or any(n in object_bytes for n in needles):
                        yield json.loads(object_bytes)
            elif depth == 0:
                if byte == 91:  # [
                    in_array = True
                elif byte == 93 and in_array:  # ]
                    return
            i += 1
        if depth > 0:
            pieces.append(buffer[start:])
        yield_to_ui()
        buffer = stream.read(CHUNK_SIZE)
        if not buffer:
            return


# --- Departures (US1.2B, US3.3) ---


def _status(item):
    if item.get("canceled"):
        return "Canceled"
    if (item.get("delay") or 0) >= DELAY_THRESHOLD_S:
        return "Delayed"
    return "On time"


def _api_transport(transport):
    return TRANSPORT_API_NAMES.get(transport, transport.upper())


def _matches_transport(item, transport):
    if transport == TRANSPORT_ALL:
        return True
    mode = ((item.get("route") or {}).get("transport_mode") or "").upper()
    return mode == _api_transport(transport)


def _to_departure(item):
    route = item.get("route") or {}
    realtime = item.get("realtime") or item.get("scheduled") or ""
    return {
        "sort": realtime,  # an ISO time sorts correctly as text
        "time": realtime[11:16],  # HH:MM
        "line": route.get("designation") or route.get("name") or "",
        "destination": route.get("direction") or "",
        "status": _status(item),
    }


def _sort_key(departure):
    return departure["sort"]


def get_departures(stop_id, limit=15, transport=TRANSPORT_ALL):
    """The next ``limit`` departures of ``transport``: a list, or None on error."""
    # Objects of other types are skipped before the slow json.loads
    needles = None
    if transport != TRANSPORT_ALL:
        mode = _api_transport(transport).encode()
        needles = (b'"' + mode + b'"', b'"' + mode.lower() + b'"')

    def read(body):
        kept = []
        for item in _iter_json_array(body, b"departures", needles):
            if _matches_transport(item, transport):
                kept.append(_to_departure(item))
                if len(kept) >= limit + EXTRA_DEPARTURES:
                    break  # the rest leave later
        kept.sort(key=_sort_key)
        return kept[:limit]

    return _fetch(_realtime("departures/" + str(stop_id)), read)


# --- Journeys, ResRobot (US5.3) ---


def _as_list(value):
    """ResRobot gives a list for many items, an object for one."""
    if isinstance(value, list):
        return value
    return [value] if value else []


def _place(place, key):
    return (place or {}).get(key) or ""


def _line_name(name):
    """"Länstrafik - Buss 6" -> "Bus 6", "Öresundståg 1076" -> "Train 1076"."""
    lower = name.lower()
    number = name.split(" ")[-1]
    for word, label in LINE_TYPES:
        if word in lower:
            return label + " " + number if number.isdigit() else label
    return name


def _to_trip(trip):
    """Only JNY legs are rides; the others are walks."""
    legs = _as_list((trip.get("LegList") or {}).get("Leg"))
    if not legs:
        return None
    rides = []
    for leg in legs:
        if leg.get("type") == "JNY":
            rides.append({
                "time": _place(leg.get("Origin"), "time")[:5],
                "stop": _place(leg.get("Origin"), "name").split(" (")[0],  # no "(Karlskrona kn)"
                "line": _line_name(leg.get("name") or ""),
            })
    return {
        "departure": _place(legs[0].get("Origin"), "time")[:5],
        "arrival": _place(legs[-1].get("Destination"), "time")[:5],
        "changes": max(len(rides) - 1, 0),
        "rides": rides,
    }


def get_trips(origin_id, destination_id, limit=5):
    """The next journeys between two stops, or None on error."""
    def read(body):
        trips = []
        for item in _iter_json_array(body, b"Trip"):
            trip = _to_trip(item)
            if trip is not None:
                trips.append(trip)
            if len(trips) >= limit:
                break
        return trips

    return _fetch("%s%d&originId=%s&destId=%s&accessId=%s" % (
        TRIP_URL, limit, origin_id, destination_id, RESROBOT_API_KEY), read)
