# 🎬 Ticket Watcher — Telegram Bot

A Telegram bot that continuously monitors movie ticket availability on BookMyShow and
notifies you the moment matching shows appear — filtered by city, date, format
(IMAX / ScreenX / 4DX / Dolby), language, and (optionally) theatre.

Built to be provider-agnostic: the watch management, comparison, and notification
engine don't change when new ticket providers or event types are added.

## Features

- ➕ Create unlimited watches through a guided Telegram conversation
- 🎞 Optional format, language, and theatre filters (leave any as *Any*)
- ⏱ Background scheduler checks every minute (APScheduler)
- 🔕 Zero duplicate notifications — every show is SHA256-hashed
  (`movie + theatre + date + time + format`) and remembered per watch
- 📋 List / edit / pause / resume / delete watches from the bot
- 🎟 Notifications include an inline **Open BookMyShow** button
- 🌐 REST API (`/watches`) and `/health` endpoint via FastAPI

## Architecture

```
Telegram ⇄ python-telegram-bot ─┐
                                ├── FastAPI app (lifespan)
APScheduler (every minute) ─────┘
      │
      ▼
MonitorService ── BaseScraper (BookMyShow | Mock | future providers)
      │                │
      ▼                ▼
 Comparator ◄──── List[Show]
      │
      ▼ (added shows only)
 TelegramNotifier ──► user chat
      │
      ▼
 NotificationHistory (SQLAlchemy → SQLite/PostgreSQL)
```

Project layout follows the PRD:

```
app/
  main.py            # FastAPI + bot + scheduler wiring
  config.py          # pydantic-settings (.env)
  database.py        # async SQLAlchemy engine/session
  scheduler.py       # APScheduler setup
  models.py          # User, Watch, NotificationHistory
  schemas.py         # Show, WatchCreate/Update/Out
  routers/
    telegram.py      # bot conversation & menus
    watch.py         # REST CRUD
  services/
    monitor.py       # scrape → filter → diff → notify pipeline
    comparator.py    # hash-based state comparison
    notifier.py      # Telegram delivery
  scrapers/
    base.py          # provider interface
    bookmyshow.py    # BookMyShow implementation
    mock.py          # deterministic scraper for demos/dev
  repositories/      # DB access (users, watches, notification history)
  utils/             # hashing, slugs, date parsing
tests/
docker/
```

## Quick start

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.

2. ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env   # paste your TELEGRAM_BOT_TOKEN
   uvicorn app.main:app
   ```

3. Open your bot in Telegram, send `/start`, and create a watch.

To try the full pipeline without scraping BookMyShow, set `SCRAPER=mock` — the
mock provider returns fake shows so you can see notifications end to end.

### Docker

```bash
cp .env.example .env    # set TELEGRAM_BOT_TOKEN
docker compose -f docker/docker-compose.yml up --build
```

This runs the app with PostgreSQL.

## Bot commands

| Command | Action |
| --- | --- |
| `/start` | Home menu (New Watch, My Watches, Settings, Help) |
| `/new` | Start the create-watch conversation |
| `/watches` | List watches with Edit / Pause / Delete buttons |
| `/cancel` | Abort the current conversation |

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers hashing, the comparator, watch filtering, duplicate-notification
prevention, paused-watch handling, and date/text parsing.

## Notes on scraping

BookMyShow has no official API, and its bot protection fingerprints the TLS
handshake — a vanilla HTTP client gets 403 no matter what headers it sends.
The scraper therefore uses [curl_cffi](https://github.com/lexiforest/curl_cffi)
with Chrome impersonation. It resolves the movie's event code from the city's
explore page, then reads the public showtimes endpoint. BMS changes markup
regularly and may still block datacenter IPs, so failures are logged as
one-line warnings and retried on the next tick rather than crashing the
service. If you keep getting `bot protection returned 403`, try a different
impersonation profile via `BMS_IMPERSONATE` (e.g. `chrome124`, `safari`) or run
from a residential network. Polling is conservative (one cycle per watch per minute) — please
respect the platform's terms of service. New providers implement
`app/scrapers/base.py:BaseScraper` and plug in via the `SCRAPER` setting.

## Roadmap

- **V2** — more providers (District, Insider, Paytm), email/Discord/WhatsApp
- **V3** — price-drop alerts, seat prediction, favourite-theatre learning
- **V4** — mobile app, browser extension, shared watch lists
