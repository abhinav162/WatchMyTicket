"""One-shot BookMyShow scrape with everything printed — for debugging watches.

Usage:
    python -m app.debug_scrape "spiderman brand new day" bengaluru 2026-08-05

If no date is given, today is used. When the explore page yields no movie
links, the raw HTML is saved to debug_bms.html so it can be inspected/shared.
"""

import asyncio
import sys
from datetime import date
from pathlib import Path

from curl_cffi.requests import AsyncSession

from app.config import settings
from app.models import Watch
from app.scrapers.bookmyshow import BASE_URL, MOVIE_LINK_RE, BookMyShowScraper, match_events
from app.utils.text import parse_user_date, slugify


async def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    movie, city = sys.argv[1], sys.argv[2]
    show_date = parse_user_date(sys.argv[3]) if len(sys.argv) > 3 else date.today()

    scraper = BookMyShowScraper()
    city_slug = slugify(city)
    print(f"movie={movie!r} city={city!r} date={show_date} region={scraper._region_code(city)}")

    url = f"{BASE_URL}/explore/movies-{city_slug}"
    async with AsyncSession(
        impersonate=settings.bms_impersonate,
        timeout=settings.http_timeout_seconds,
        headers={"Accept-Language": "en-IN,en-US;q=0.9,en;q=0.8"},
    ) as session:
        response = await session.get(url)
        print(f"\nGET {url}\n -> HTTP {response.status_code}, {len(response.text)} bytes")
        html = response.text.replace("\\/", "/")
        candidates = sorted(set(MOVIE_LINK_RE.findall(html)))
        print(f"\n{len(candidates)} movie link(s) found on the explore page:")
        for slug, code in candidates:
            print(f"   {slug}  {code}")
        if not candidates:
            dump = Path("debug_bms.html")
            dump.write_text(response.text)
            print(f"\nNo movie links found — raw HTML saved to {dump.resolve()}")
            print("The page is likely JS-rendered or a challenge page.")
            return

        matched = match_events(response.text, movie)
        print(f"\nfuzzy match for {movie!r}: {matched}")
        if not matched:
            return

    watch = Watch(
        user_id=0, movie=movie, city=city, date=show_date, formats=[], languages=[], theatres=[]
    )
    shows = await scraper.scrape(watch)
    print(f"\n{len(shows)} show(s) on {show_date}:")
    for show in shows[:30]:
        print(f"   {show.theatre} | {show.time} | {show.format} | {show.language}")
    if len(shows) > 30:
        print(f"   ... and {len(shows) - 30} more")
    if not shows:
        print("Event matched but no shows for that date — tickets may not be open yet,")
        print("or the showtimes API returned an empty/unexpected payload.")


if __name__ == "__main__":
    asyncio.run(main())
