from datetime import date

from app.models import Watch
from app.scrapers.bookmyshow import BookMyShowScraper, match_events

SAMPLE_PAYLOAD = {
    "ShowDetails": [
        {
            "Date": "20260816",
            "Event": {
                "ChildEvents": [
                    {
                        "EventTitle": "Spider-Man",
                        "EventDimension": "ScreenX",
                        "EventLanguage": "English",
                        "VenueList": [
                            {
                                "VenueName": "PVR Vega Mall",
                                "ShowTimes": [
                                    {"ShowTime": "7:30 PM"},
                                    {"ShowTime": "10:45 PM"},
                                ],
                            },
                            {"VenueName": "", "ShowTimes": [{"ShowTime": "1:00 PM"}]},
                        ],
                    },
                    {
                        "EventTitle": "Spider-Man",
                        "EventDimension": "IMAX",
                        "EventLanguage": "English",
                        "VenueList": [
                            {
                                "VenueName": "INOX Forum",
                                "ShowTimes": [{"ShowTime": "9:00 PM"}, {"ShowTime": ""}],
                            }
                        ],
                    },
                ]
            },
        }
    ]
}


def make_watch() -> Watch:
    return Watch(
        user_id=1,
        movie="Spider-Man",
        city="Bengaluru",
        date=date(2026, 8, 16),
        formats=[],
        languages=[],
        theatres=[],
    )


def test_parse_showtimes():
    scraper = BookMyShowScraper()
    shows = scraper._parse_showtimes(SAMPLE_PAYLOAD, make_watch(), "https://example.com/book")

    assert len(shows) == 3  # empty venue name and empty showtime are skipped
    assert {s.format for s in shows} == {"ScreenX", "IMAX"}
    assert all(s.booking_url == "https://example.com/book" for s in shows)
    screenx = [s for s in shows if s.format == "ScreenX"]
    assert {s.time for s in screenx} == {"7:30 PM", "10:45 PM"}
    assert screenx[0].theatre == "PVR Vega Mall"


# The shape observed live in 2026: ChildEvents describe formats (embedded in
# the title, language in 'EventLang'), venues are a sibling list, and each
# ShowTime carries the ChildEvent's EventCode.
SIBLING_VENUES_PAYLOAD = {
    "ShowDetails": [
        {
            "Date": "20260802",
            "Event": {
                "EventTitle": "Spider-Man: Brand New Day",
                "ChildEvents": [
                    {
                        "EventTitle": "Spider-Man: Brand New Day (Dolby Cinema 2D)",
                        "EventCode": "ET00447841",
                        "EventLang": "English",
                    },
                    {
                        "EventTitle": "Spider-Man: Brand New Day (ScreenX)",
                        "EventCode": "ET00447842",
                        "EventLang": "English",
                    },
                ],
            },
            "Venues": [
                {
                    "VenueName": "PVR Vega City Mall",
                    "ShowTimes": [
                        {"ShowTime": "7:30 PM", "EventCode": "ET00447842"},
                        {"ShowTime": "9:00 PM", "EventCode": "ET00447841"},
                    ],
                },
                {
                    "VenueName": "INOX Forum",
                    "ShowTimes": [{"ShowTime": "10:15 PM", "EventCode": "ET00447841"}],
                },
            ],
        }
    ]
}


def test_parse_sibling_venues_shape():
    scraper = BookMyShowScraper()
    shows = scraper._parse_showtimes(SIBLING_VENUES_PAYLOAD, make_watch(), "https://x/book")

    assert len(shows) == 3
    by_time = {s.time: s for s in shows}
    assert by_time["7:30 PM"].format == "ScreenX"
    assert by_time["7:30 PM"].theatre == "PVR Vega City Mall"
    assert by_time["9:00 PM"].format == "Dolby Cinema 2D"
    assert by_time["10:15 PM"].theatre == "INOX Forum"
    assert all(s.language == "English" for s in shows)


def test_parse_empty_payload():
    scraper = BookMyShowScraper()
    assert scraper._parse_showtimes({}, make_watch(), "url") == []
    assert scraper._parse_showtimes({"ShowDetails": None}, make_watch(), "url") == []


# Explore pages link movies WITHOUT a city segment (real format observed live);
# other pages include the city. Both must be recognised.
EXPLORE_HTML = """
<a href="/movies/spiderman-brand-new-day/ET00447840">Spider-Man</a>
<a href="/movies/spiderman-brand-new-day-3d/ET00502600">Spider-Man 3D</a>
<a href="/movies/avatar-fire-and-ash/ET00412229">Avatar</a>
<a href="/movies/bengaluru/mission-impossible-8/ET00371405">MI8</a>
"""


def test_match_events_survives_hyphens_and_punctuation():
    for title in ("spiderman brand new day", "Spider-Man: Brand New Day"):
        matches = match_events(EXPLORE_HTML, title)
        assert matches[0] == ("spiderman-brand-new-day", "ET00447840")
        # the separate 3D listing is also picked up
        assert ("spiderman-brand-new-day-3d", "ET00502600") in matches


def test_match_events_city_prefixed_urls():
    assert match_events(EXPLORE_HTML, "mission impossible 8") == [
        ("mission-impossible-8", "ET00371405")
    ]


def test_match_events_escaped_json_urls():
    html = '{"url":"\\/movies\\/avatar-fire-and-ash\\/ET00412229"}'
    assert match_events(html, "avatar fire and ash") == [("avatar-fire-and-ash", "ET00412229")]


def test_match_events_rejects_unrelated_titles():
    assert match_events(EXPLORE_HTML, "Oppenheimer") == []


def test_match_events_empty_inputs():
    assert match_events("", "spiderman") == []
    assert match_events(EXPLORE_HTML, "") == []


def test_region_code_mapping():
    scraper = BookMyShowScraper()
    assert scraper._region_code("Bengaluru") == "BANG"
    assert scraper._region_code("bangalore") == "BANG"
    assert scraper._region_code("New Delhi") == "NCR"
    assert scraper._region_code("Indore") == "INDORE"  # fallback
