import urequests
from secrets import TRAFIKLAB_API_KEY

BASE_URL = "https://realtime-api.trafiklab.se/v1/departures/"


def get_departures(stop_id):
    url = BASE_URL + str(stop_id) + "?key=" + TRAFIKLAB_API_KEY
    response = None

    try:
        response = urequests.get(url, timeout=10)

        if response.status_code != 200:
            raise Exception("API error: " + str(response.status_code))

        data = response.json()
        departures = []

        for item in data.get("departures", []):
            route = item.get("route") or {}

            scheduled = item.get("scheduled") or ""
            realtime = item.get("realtime") or scheduled

            if item.get("canceled"):
                status = "Canceled"
            elif (item.get("delay") or 0) > 0:
                status = "Delayed"
            else:
                status = "On time"

            departures.append(
                {
                    "time": realtime[11:16],
                    "line": route.get("designation") or route.get("name") or "",
                    "destination": route.get("direction") or "",
                    "status": status,
                    "transport": route.get("transport_mode") or "",
                }
            )

        return departures

    except Exception as error:
        print("Trafiklab request failed:", type(error).__name__)
        return None

    finally:
        if response is not None:
            response.close()
