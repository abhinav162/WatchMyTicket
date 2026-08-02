from datetime import date

from app.models import Watch
from app.scrapers.bookmyshow import BookMyShowScraper, match_event

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


def test_parse_empty_payload():
    scraper = BookMyShowScraper()
    assert scraper._parse_showtimes({}, make_watch(), "url") == []
    assert scraper._parse_showtimes({"ShowDetails": None}, make_watch(), "url") == []


EXPLORE_HTML = """
<a href="/movies/bengaluru/spider-man-brand-new-day/ET00329567">Spider-Man</a>
<a href="/movies/bengaluru/avatar-fire-and-ash/ET00412229">Avatar</a>
<a href="/movies/bengaluru/mission-impossible-8/ET00371405">MI8</a>
"""


def test_match_event_survives_missing_hyphens_and_punctuation():
    assert match_event(EXPLORE_HTML, "spiderman brand new day") == (
        "spider-man-brand-new-day",
        "ET00329567",
    )
    assert match_event(EXPLORE_HTML, "Spider-Man: Brand New Day") == (
        "spider-man-brand-new-day",
        "ET00329567",
    )


def test_match_event_partial_title():
    # a distinctive prefix of the title should still match via containment
    assert match_event(EXPLORE_HTML, "avatar fire and ash") == (
        "avatar-fire-and-ash",
        "ET00412229",
    )


def test_match_event_rejects_unrelated_titles():
    assert match_event(EXPLORE_HTML, "Oppenheimer") is None


def test_match_event_empty_inputs():
    assert match_event("", "spiderman") is None
    assert match_event(EXPLORE_HTML, "") is None


def test_region_code_mapping():
    scraper = BookMyShowScraper()
    assert scraper._region_code("Bengaluru") == "BANG"
    assert scraper._region_code("bangalore") == "BANG"
    assert scraper._region_code("New Delhi") == "NCR"
    assert scraper._region_code("Indore") == "INDORE"  # fallback
