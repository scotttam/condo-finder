# Condo Finder

Aggregates Portland / Lake Oswego / Beaverton rental listings from local property managers into one
browsable database with a map, filters, shared status + notes, and push alerts.

## Develop

```bash
uv sync
uv run python manage.py migrate
uv run python manage.py scrape            # scrape all sources once (add --source pearl for one)
uv run python manage.py runserver 0.0.0.0:8000
uv run pytest
```

## Run on the Mac mini (always on)

1. `cp .env.example .env` and fill it in (set `SITE_URL` to `http://<mac-mini>.local:8000`, choose an `NTFY_TOPIC`).
2. `./deploy/install.sh` — installs a launchd agent that starts gunicorn at login, restarts it on crash,
   and runs scheduled scrapes (default 7am, 11am, 3pm, 7pm, 11pm).
3. System Settings → Users & Groups → enable automatic login for your user (LaunchAgents start at login),
   and System Settings → Energy → prevent automatic sleeping.
4. Approve the macOS firewall prompt for incoming connections to Python.
5. Create an admin user for data corrections: `uv run python manage.py createsuperuser`.

Logs: `logs/web.log`. Restart after pulling changes: re-run `./deploy/install.sh`.

## Alerts

Install the **ntfy** app on both phones and subscribe to your `NTFY_TOPIC`. You'll get pushes for new
listings matching 2bd/2ba/2 parking (unknowns allowed), price drops on listings marked Interested, and
scrapers that keep failing.

## Adding a property manager

If their listings page is AppFolio (`<name>.appfolio.com/listings`) or Nesthub (`/_system/listings/...`
links), add one entry to `SOURCES` in `listings/scrapers/registry.py`.

## Correcting data

Open a listing → "Correct data in admin". To make a correction survive re-scrapes, put it in the
`overrides` JSON field, e.g. `{"parking_spaces": 2, "has_ac": true}`.
