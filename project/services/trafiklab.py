"""Trafiklab Realtime API client.

Uses two endpoints (https://www.trafiklab.se/api/our-apis/trafiklab-realtime-apis/):
  * Stop Lookup: find the id of a stop area by name.
  * Timetables:  list departures from a stop area during the next 60 minutes.

Responses for large stop areas (such as all of Karlskrona) can be too big to
parse in one go on an ESP32. The functions below therefore read the HTTP body
in small chunks and decode one JSON object at a time, so memory use stays
constant regardless of response size.

All functions are blocking. Call them from the background worker only.
"""

import gc
import json

import urequests

from secrets import TRAFIKLAB_API_KEY

BASE_URL = "https://realtime-api.trafiklab.se/v1/"

# Number of bytes read from the socket at a time
CHUNK_SIZE = 1024

# A departure counts as delayed when it is at least this many seconds late
DELAY_THRESHOLD_S = 60

# Text describing the most recent failure, empty if the last request succeeded
_last_error = ""


def get_last_error():
    """Return a short description of the last failed request ('' if none)."""
    return _last_error


def _set_error(text):
    """Remember ``text`` as the last error and print it for debugging."""
    global _last_error
    _last_error = str(text)[:40]
    print("Trafiklab error:", _last_error)


def _clear_error():
    """Reset the stored error after a successful request."""
    global _last_error
    _last_error = ""


def _url_encode(text):
    """Percent-encode ``text`` as UTF-8 so names like 'Nättraby' are URL safe."""
    unreserved = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.~"
    encoded = ""
    for byte in text.encode("utf-8"):
        char = chr(byte)
        encoded += char if char in unreserved else "%{:02X}".format(byte)
    return encoded


def _open(path):
    """Send a GET request to the API and return the open response.

    The body is NOT read yet; callers stream it through ``response.raw``.

    Args:
        path: API path after the base URL, for example 'departures/740000002'.

    Returns:
        An open urequests response with status code 200.

    Raises:
        Exception: If the server answers with anything other than HTTP 200.
    """
    url = BASE_URL + path + "?key=" + TRAFIKLAB_API_KEY
    try:
        response = urequests.get(url, timeout=10)
    except TypeError:
        # Older urequests versions do not support the timeout argument
        response = urequests.get(url)

    if response.status_code != 200:
        status = response.status_code
        response.close()
        raise Exception("HTTP " + str(status))
    return response


def _iter_json_array(stream, key):
    """Yield the objects of the top-level JSON array ``key`` one at a time.

    This is a minimal streaming JSON scanner. It skips everything before the
    array, then tracks braces (ignoring braces inside strings) to cut out each
    object and decodes it separately with ``json.loads``.

    Args:
        stream: Object with a ``read(n)`` method, e.g. ``response.raw``.
        key: Name of the array as bytes, for example ``b"departures"``.

    Yields:
        One decoded dict per array element.
    """
    marker = b'"' + key + b'"'
    marker_len = len(marker)

    # Phase 1: skip ahead until the array key is found. Keep a small tail of
    # the buffer so a key split over two chunks is still detected.
    buf = b""
    while True:
        chunk = stream.read(CHUNK_SIZE)
        if not chunk:
            return
        buf += chunk
        pos = buf.find(marker)
        if pos >= 0:
            buf = buf[pos + marker_len :]
            break
        buf = buf[-marker_len:]

    # Phase 2: scan character by character and cut out each object
    in_array = False
    in_string = False
    escaped = False
    depth = 0  # current {} nesting depth inside the array
    partial = b""  # start of an object that began in an earlier chunk

    while True:
        # If an object is still open, it continues at the start of this chunk
        start = 0 if depth > 0 else -1

        for i in range(len(buf)):
            char = buf[i]

            if in_string:
                # Inside a string only the closing quote matters
                if escaped:
                    escaped = False
                elif char == 92:  # backslash
                    escaped = True
                elif char == 34:  # closing quote
                    in_string = False
            elif char == 34:  # opening quote
                in_string = True
            elif char == 123:  # '{'
                if depth == 0:
                    if not in_array:
                        return  # value was not an array
                    start = i
                    partial = b""
                depth += 1
            elif char == 125:  # '}'
                depth -= 1
                if depth == 0:
                    # Complete object: decode and hand it to the caller
                    raw = partial + buf[start : i + 1]
                    yield json.loads(str(raw, "utf-8"))
                    start = -1
                    partial = b""
            elif depth == 0:
                if char == 91:  # '['
                    in_array = True
                elif char == 93 and in_array:  # ']' closes the array
                    return

        # Chunk ended in the middle of an object: remember what we have so far
        if depth > 0:
            partial += buf[start:]

        buf = stream.read(CHUNK_SIZE)
        if not buf:
            return


def find_stop_id(name):
    """Look up the id of a stop area by name using Trafiklab Stop Lookup.

    An exact (case-insensitive) name match is preferred. If there is none,
    the first result is used, which is the stop with the most departures.

    Args:
        name: Stop name to search for, for example 'Karlskrona'.

    Returns:
        The stop area id as a string, or None on failure (see get_last_error).
    """
    response = None
    try:
        gc.collect()
        response = _open("stops/name/" + _url_encode(name))

        wanted = name.lower()
        first_id = None
        for group in _iter_json_array(response.raw, b"stop_groups"):
            group_id = group.get("id")
            if first_id is None:
                first_id = group_id
            if (group.get("name") or "").lower() == wanted:
                _clear_error()
                return group_id

        if first_id is None:
            _set_error("Stop not found: " + name)
            return None

        _clear_error()
        return first_id
    except Exception as error:
        _set_error(type(error).__name__ + " " + str(error))
        return None
    finally:
        if response is not None:
            response.close()
        gc.collect()


def _status(item):
    """Convert a raw departure into 'On time', 'Delayed' or 'Canceled'."""
    if item.get("canceled"):
        return "Canceled"
    if (item.get("delay") or 0) >= DELAY_THRESHOLD_S:
        return "Delayed"
    return "On time"


def _to_departure(item):
    """Reduce a raw API departure to the few fields the UI needs.

    Dropping everything else (alerts, platforms, trip data) keeps the memory
    footprint of each stored departure very small.
    """
    route = item.get("route") or {}
    scheduled = item.get("scheduled") or ""
    # 'realtime' equals 'scheduled' when no realtime data exists
    realtime = item.get("realtime") or scheduled

    return {
        "sort": realtime,  # ISO timestamp, sorts correctly as plain text
        "time": realtime[11:16],  # 'HH:MM' part of 'YYYY-MM-DDTHH:MM:SS'
        "line": route.get("designation") or route.get("name") or "",
        "destination": route.get("direction") or "",
        "status": _status(item),
        "transport": route.get("transport_mode") or "",
    }


def _sort_key(departure):
    """Sort key for departures: earliest first."""
    return departure["sort"]


def get_departures(stop_id, limit=15):
    """Fetch the next departures from a stop area.

    Only the ``limit`` earliest departures are kept in memory at any time.

    Args:
        stop_id: Stop area id (rikshållplats or meta-stop id).
        limit: Maximum number of departures to return.

    Returns:
        A list of departure dicts (empty if there are none), or None if the
        request failed (see get_last_error).
    """
    response = None
    try:
        gc.collect()
        response = _open("departures/" + str(stop_id))

        kept = []
        for item in _iter_json_array(response.raw, b"departures"):
            kept.append(_to_departure(item))
            # Keep the list sorted and drop the latest departure when full
            kept.sort(key=_sort_key)
            if len(kept) > limit:
                kept.pop()

        _clear_error()
        return kept
    except Exception as error:
        _set_error(type(error).__name__ + " " + str(error))
        return None
    finally:
        if response is not None:
            response.close()
        gc.collect()
