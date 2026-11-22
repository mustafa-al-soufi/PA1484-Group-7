# Testing

This document describes how we assure the quality of the Karlskrona Transit
app (NF5): what we test, how to run the tests, and which tests cover each
user story.

## QA strategy

We use three kinds of checks:

1. **Automated unit tests on the PC.** `tests/test_logic.py` runs the app's
   logic with plain Python. A fake LVGL module stands in for the display, and
   a fake API returns the answers we choose. That lets us test sorting,
   filtering, paging, saving settings, error handling and the app's event
   handlers without the board or the internet. The tests also fake the
   board-only modules (`network`, `_thread`, `urequests` and `secrets`), so no
   real Wi-Fi password or API key is needed.
2. **Manual tests on the device.** Whatever needs the real screen, touch,
   Wi-Fi or live Trafiklab data is tested by hand on the LilyGO T4-S3. The
   cases are listed below.
3. **Traceability from requirement to test.** Each user story is a GitHub
   issue, and each unit test names the user story it covers in its docstring.
   The table below links every requirement to its tests, so it is easy to see
   what is covered and what is missing.

We do not use formal code review: changes are committed directly to `main`,
without pull requests or automatic test runs. That is why we run the unit
tests by hand on the PC.

The tests live in `tests/`, outside `project/`, so they are never flashed to
the device.

## How to run the tests

You need Python 3 (we use 3.13). No extra packages are needed. Run this from
the repository root:

```bash
python -m unittest tests/test_logic.py -v
```

Each test prints its name, its docstring (the user story it covers) and `ok`:

```
test_save_as_default (tests.test_logic.TestAppSettings.test_save_as_default)
US3.4: Save as Default stores the current stop and transport type. ... ok
...
----------------------------------------------------------------------
Ran 111 tests in 0.3s

OK
```

The run ends with `OK`. A few lines like `Trafiklab error: Exception HTTP 403`
and `Settings file is damaged, using defaults` are expected: they come from
tests that check the error handling.

## Automated tests per requirement

All test classes are in `tests/test_logic.py`.

| Requirement | What is tested | Tests |
|---|---|---|
| US1.2B Departure screen with live data | Status (On time, Delayed, Canceled), live time, sorting, limit, error messages, rows, columns, colors, two pages and page buttons, cut destinations, å ä ö and safe text, Swedish fonts, the JSON reader | `TestDepartures`, `TestDepartureScreen`, `TestSafeText`, `TestSwedishFonts`, `TestJsonStream`, `TestStopSearch.test_fetch_makes_no_stop_search`, `TestSearch.test_fetch_limit_is_two_pages` |
| US2.1 Swipe between screens | The fetch pauses during swipes and scrolling; nothing new is drawn during a swipe; less to draw per screen | `TestScrollPause`, `TestDrawCost` |
| US3.2B Fixed stops | Five fixed stops, ids, a copy for each caller, the default stop, filled at start-up | `TestStops`, `TestStopSearch.test_default_stop_is_the_first_fixed_stop`, `TestSearch.test_stops_are_filled_at_start_up` |
| US3.2C Stop search | Area filter, busiest first, one per name, URL encoding of å ä ö, its own worker result, results in the settings dropdown | `TestStopSearch.test_filtered_and_sorted`, `TestStops.test_stop_inside_and_outside_karlskrona`, `TestStops.test_swedish_letters_in_url`, `TestWorker.test_stop_search_is_not_a_departure_result`, `TestAppSettings.test_settings_stop_search_fills_the_stop_dropdown` |
| US3.3 Transport type | Filter per type, Ferry = BOAT, All, a new type fetches again | `TestDepartures.test_transport_filter`, `test_ferry_filter_matches_boat`, `test_filter_gives_only_trains`, `TestAppSettings.test_transport_change_fetches_again` |
| US3.4 Save as default | Save and load, missing or damaged file, the old file is replaced safely, the saved stop is used at start-up, the Save button | `TestSettings`, `TestStopSearch.test_saved_stop_is_kept`, `TestAppSettings.test_save_as_default` |
| US3.5 Reset to default | Reset with and without saved settings | `TestAppSettings.test_reset_to_saved_default`, `test_reset_without_saved_default` |
| US4.1 Automatic refresh | A fetch every 60 s reaches the screen; no second fetch while one runs; new departures start on page 1 | `TestAppSettings.test_automatic_refresh_every_60_seconds`, `TestWorker.test_no_new_fetch_while_busy`, `TestDepartureScreen.test_new_departures_start_on_page_one` |
| US4.2B Refresh on the settings screen | Refresh fetches again and reports success or failure | `TestAppSettings.test_refresh_button_updates_departures`, `test_failed_refresh_is_shown` |
| US4.3 Connection status | Wi-Fi state, no Wi-Fi, the status lines after a fetch | `TestWifi`, `TestAppSettings.test_refresh_button_updates_departures`, `test_failed_refresh_is_shown` |
| US5.1 Journey screen | The screen, its Search button, no extra container | `TestJourneyScreen.test_screen_has_search_and_attribution`, `TestDrawCost.test_journey_screen_has_no_root_container` |
| US5.2 Select start and destination | Both dropdowns, different stops, messages, Search starts a journey search | `TestJourneyScreen`, `TestSearch` |
| US5.2B Search start and destination stops | A From or To search fills only its own dropdown | `TestSearch.test_from_and_to_searches_fill_their_own_dropdown` |
| US5.3 Top journeys | Line names, changes, time at each change, at most five, errors, the result list | `TestJourneys`, `TestWorker.test_journey_result_is_not_a_departure_result`, `TestJourneyScreen.test_journeys_are_listed` |
| US5.3B Best journey by arrival | Sorted by arrival, after midnight counts as later, the best one is marked | `TestSearch.test_best_journey_first`, `TestSearch.test_journeys_reach_the_screen` |
| NF3 Trafiklab attribution | The attribution on the departure and journey screens | `TestDepartureScreen.test_attribution_is_shown`, `TestJourneyScreen.test_screen_has_search_and_attribution` |

US1.1 (start screen) and US3.1 (settings screen) contain no logic beyond
building the screen. They are covered by the manual tests below.

The B and C stories (US1.2B, US3.2B, US3.2C, US5.2B, US5.3B) are later
versions of earlier stories. Where both versions are listed, the app meets
both. For example, it shows up to five journeys (US5.3), sorted by arrival
with the best one marked (US5.3B).

## Manual tests on the device

Run these after **Deploy complete project**, with `project/secrets.py` set up
and a working Wi-Fi network (not eduroam). The Result column shows the
outcome and the date of the last run.

| ID | Requirement | Steps | Expected result | Result |
|---|---|---|---|---|
| M1 | US1.1 | Power on the board. | The start screen shows "Karlskrona Transit", the version, Group 7 and the five member names. | Pass (2026-11-21) |
| M2 | US2.1 | Swipe left and right between all four screens. | Each swipe moves to the next or previous screen: start, departures, settings, journeys. | Pass (2026-11-21) |
| M3 | US1.2B | Open the departure screen and wait until it has loaded. | Live departures for Karlskrona Centralstation show time, line, destination and status, in time order. | Pass (2026-11-21) |
| M4 | US1.2B | With more than six departures, press the down and up arrows. | Page 2/2 shows the next departures; the up arrow goes back to 1/2. | Pass (2026-11-21) |
| M5 | US1.2B | Choose a stop with å, ä or ö in its name (for example Campus Gräsvik). | å, ä and ö are shown correctly, not as boxes. | Pass (2026-11-21) |
| M6 | US3.1, US3.2B | Open the settings screen and choose another stop in the Stop dropdown. | The departure screen shows "Loading...", then the departures of the new stop. | Pass (2026-11-21) |
| M7 | US3.2C | Tap the search field, type "Lyckeby" with the on-screen keyboard and press Enter. | The keyboard closes and the dropdown opens with the stops found; picking one shows its departures. | Pass (2026-11-21) |
| M8 | US3.3 | Choose Bus, Train, Ferry and All in the Transport type dropdown. | The departure screen only shows that type; All shows every type. | Pass (2026-11-21) |
| M9 | US3.4 | Choose a stop and a transport type, press Save as Default, then restart the board. | After the restart the saved stop and transport type are used. | Pass (2026-11-21) |
| M10 | US3.5 | Change the stop, then press Reset to Default. | The saved stop and transport type come back and "Reset to default" is shown. | Pass (2026-11-21) |
| M11 | US4.1 | Stay on the departure screen for 2 minutes. | The departures update about every 60 seconds without any input. | Pass (2026-11-21) |
| M12 | US4.2B | Press Refresh on the settings screen. | "Refreshing..." is shown, then "Departures updated". | Pass (2026-11-21) |
| M13 | US4.3 | Turn off the Wi-Fi network (or hotspot) and wait for the next refresh. | The status shows "Live data: Error", and Wi-Fi shows Offline once the connection is lost. | Pass (2026-11-21) |
| M14 | US5.1, US5.2 | Open the journey screen, choose two different stops and press Search. | "Searching..." is shown, then a list of journeys. | Pass (2026-11-21) |
| M15 | US5.2 | Choose the same stop in From and To and press Search. | "Choose two different stops" is shown and nothing is searched. | Pass (2026-11-21) |
| M16 | US5.2B | Search for a stop in the From field, then in the To field. | Each search fills only its own dropdown. | Pass (2026-11-21) |
| M17 | US5.3, US5.3B | Search for a journey between two stops that needs at least one change. | At most five journeys, sorted by arrival; the first is marked "Best" in green; each ride shows its time, line and stop. | Pass (2026-11-21) |
| M18 | NF3 | Look at the departure and journey screens. | "Data: Trafiklab.se (CC BY 4.0)" is shown at the bottom. | Pass (2026-11-21) |

## Known limitations

- **128 KB filesystem.** The deploy writes a 128 KB file system, and every
  file takes whole 4 KB blocks. The project currently uses all of it, so a
  new file or a few hundred extra bytes in a full file can push the last files
  out of the image. The board then starts with a black screen. Check the size
  before adding code.
- **Swipe speed.** Drawing one frame of a swipe takes about 170-195 ms on the
  device, so swipes run at about 5 frames per second and feel slow. About
  70 ms of that is spent even on an empty screen, because each frame is sent
  to the display in ten strips. The unit tests cannot measure this, since the
  PC uses a fake display.
- **What the PC tests cannot check.** The real screen, touch, timers, Wi-Fi
  and the live Trafiklab and ResRobot APIs only exist on the device. They are
  covered by the manual tests above.
