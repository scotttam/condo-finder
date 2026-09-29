# Condo Finder

Aggregates Portland / Lake Oswego / Beaverton rental listings from local property managers (including Chroma via RentEngine), Redfin, Zillow, and Craigslist into one
browsable database with a map, filters, and shared status + notes.

## Develop

```bash
uv sync
uv run playwright install chromium        # once; needed for RentEngine sources
uv run python manage.py migrate
uv run python manage.py scrape            # scrape all sources once (add --source pearl for one)
uv run python manage.py runserver 0.0.0.0:8000
uv run pytest
```

## Run on the Mac mini (always on)

1. `cp .env.example .env` and set `DJANGO_SECRET_KEY` to a long random string. For the Trends page, also set
   `ANTHROPIC_API_KEY` (create one at console.anthropic.com). Other values are optional.
2. `./deploy/install.sh` — installs a launchd agent that starts gunicorn at login, restarts it on crash,
   and runs scheduled scrapes (default 7am, 11am, 3pm, 7pm, 11pm).
3. System Settings → Users & Groups → enable automatic login for your user (LaunchAgents start at login),
   and System Settings → Energy → prevent automatic sleeping.
4. Approve the macOS firewall prompt for incoming connections to Python.
5. Create an admin user for data corrections: `uv run python manage.py createsuperuser`.

Logs: `logs/web.log`. Restart after pulling changes: re-run `./deploy/install.sh`.

## Access from anywhere (Tailscale)

The app stays on the Mac mini, so scrapers keep running from a home internet connection (Zillow and
Redfin block most cloud-server IPs). Tailscale gives both of you a private, encrypted connection
to it from any network, and nothing is exposed to the public internet.

1. **Mac mini:** install Tailscale ([tailscale.com/download](https://tailscale.com/download) or the Mac App
   Store) and sign in. This creates your tailnet. Allow it to start at login.
2. **Keep it connected:** in the [admin console](https://login.tailscale.com/admin/machines), open the
   Mac mini's ⋯ menu → **Disable key expiry**. Otherwise it drops off the tailnet after 180 days.
3. **Your devices:** install Tailscale on your phone and laptop and sign in with the same account.
   Open `http://<mac-mini-name>:8000`. MagicDNS, on by default, resolves the machine name.
4. **Your partner:** in the admin console, open the Mac mini's ⋯ menu → **Share…** and send her the
   invite. She installs Tailscale, signs in with her own account, accepts, and opens
   `http://<mac-mini-name>.<your-tailnet>.ts.net:8000` (shared machines need the full name, shown
   in the console). She gets access to this one machine, not the rest of your network.
5. **Test:** turn off Wi-Fi on a phone and open the link over cellular.

Plain `http://` is fine here because Tailscale already encrypts the connection. The admin login is
reachable by both of you, so give the admin user a real password (`uv run python manage.py
changepassword <user>`).

## Scraper health

The **Sources** page shows each site's last successful scrape, listing count, and consecutive
failures with the last error. A scrape that returns 0 listings counts as a failure, so a blocked or
changed site never marks its listings off-market.

## Adding a property manager

If their listings page is AppFolio (`<name>.appfolio.com/listings`) or Nesthub (`/_system/listings/...`
links), add one entry to `SOURCES` in `listings/scrapers/registry.py`.

Portal sources (Redfin, Zillow, Craigslist) fetch detail pages only for listings not yet described,
capped per run (`max_detail_fetches` in the registry), so the first few runs fill in details gradually.
Realtor.com isn't scraped: it's protected by Kasada bot protection.

Property managers whose listings are embedded from **RentEngine** (`rentengine.io/c/<slug>`, e.g. Chroma)
sit behind a Vercel bot checkpoint, so they're loaded in headless Chromium via Playwright. To add
another one, add a `"platform": "rentengine"` entry with its `slug`. `deploy/install.sh` installs
Chromium; in development run `uv run playwright install chromium` once.

## Correcting data

Open a listing → "Correct data in admin". To make a correction survive re-scrapes, put it in the
`overrides` JSON field, e.g. `{"parking_spaces": 2, "has_ac": true}`.
