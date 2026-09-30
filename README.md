# Condo Finder

Aggregates Portland / Lake Oswego / Beaverton rental listings from local property managers (including Chroma via RentEngine), Redfin, Zillow, and Craigslist into one
browsable database with a map, filters, and logins and, per household, a shared status, comments and votes.

## Develop

```bash
uv sync
uv run playwright install chromium        # once; needed for RentEngine sources
uv run python manage.py migrate
uv run python manage.py scrape            # scrape all sources once (add --source pearl for one)
uv run python manage.py runserver 127.0.0.1:8000
uv run python manage.py create_owner --email you@example.com --name You   # once per dev database
uv run pytest
```

## Run on the Mac mini (always on)

1. `cp .env.example .env` and set `DJANGO_SECRET_KEY` to a long random string. For the Trends page, also set
   `ANTHROPIC_API_KEY` (create one at console.anthropic.com). Other values are optional.
2. `./deploy/install.sh` — installs a launchd agent that starts gunicorn at login, restarts it on crash,
   and runs scheduled scrapes (default 7am, 11am, 3pm, 7pm, 11pm).
3. System Settings → Users & Groups → enable automatic login for your user (LaunchAgents start at login),
   and System Settings → Energy → prevent automatic sleeping.
4. No firewall prompt is needed: gunicorn listens on localhost only.
5. Create the site admin's account: `uv run python manage.py create_owner --email you@example.com --name "Your name"`.

Logs: `logs/web.log`. Restart after pulling changes: re-run `./deploy/install.sh`.

## Going public with Tailscale Funnel

The app stays on the Mac mini, so scrapers keep a home IP (Zillow and Redfin block most cloud IPs).
Tailscale Funnel gives it a public HTTPS address, `https://<mac-mini>.<tailnet>.ts.net`, with an
automatic certificate. Anyone with an account can use it from any browser, with no Tailscale app
needed. Every page requires a login, and gunicorn listens only on `127.0.0.1:8000`, so Funnel is the
only way in.

Do these once, in order. Run each command in its own step: the site is briefly unreachable
between the install and turning on Funnel.

1. **Pull and set the public address.** Find the Mac mini's full Tailscale name in the
   [admin console](https://login.tailscale.com/admin/machines) (for example
   `mac-mini.tail1234.ts.net`). In `.env`, set `PUBLIC_URL=https://` followed by that name.
   Check that `DJANGO_SECRET_KEY` there is a long random string: with `PUBLIC_URL` set, the app
   refuses to start with a placeholder or a key under 50 characters, and says how to make one.

   ```bash
   git pull
   ```

2. **Install.** This migrates the database (statuses, notes, priorities and Trends reports move to
   the owners' group) and restarts gunicorn on localhost only.

   ```bash
   ./deploy/install.sh
   ```

3. **Create your account, before anyone opens the site.** This makes you the site admin in the
   owners' group, and claims your old notes (now comments). It asks for a password. If you already
   have an admin account (from `createsuperuser`), pass that account's email: it's adopted and moved
   into the owners' group. An account that opens the site before this step gets a group of its own,
   away from your migrated statuses, comments and Trends reports.

   ```bash
   uv run python manage.py create_owner --email you@example.com --name "Your name"
   ```

4. **Try it privately first.** This serves HTTPS to devices on your tailnet only:

   ```bash
   tailscale serve --bg 8000
   ```

   Open `https://<mac-mini>.<tailnet>.ts.net` on a device signed in to Tailscale and log in. (On the
   App Store build the CLI is `/Applications/Tailscale.app/Contents/MacOS/Tailscale`.)

5. **Allow Funnel for the Mac mini.** In the admin console, go to **Access controls** and add the
   `funnel` node attribute. The `tailscale funnel` command prints a link to the exact setting if
   it's missing.

6. **Open it to the internet.**

   ```bash
   tailscale funnel --bg 8000
   ```

   Check with `tailscale funnel status`. To turn it off: `tailscale funnel reset`. If the CLI
   rejects these flags, see `tailscale funnel --help`; the syntax has changed between versions.

7. **Check from outside.** Turn off Wi-Fi on a phone and open the address over cellular: you should
   get the login page. From a terminal, this should print a `302` redirect to `/login/`:

   ```bash
   curl -sI https://<mac-mini>.<tailnet>.ts.net/
   ```

8. **Invite your partner.** Open **Group**, click **New link to join**, copy the link and send it. For
   another household, click **New link for another household** (site admin only).

Keep the Mac mini on the tailnet: in the admin console, open its ⋯ menu → **Disable key expiry**.
Otherwise it drops off after 180 days and the public address stops working.

Passwords: people change their own on the Group page. To reset someone's, run
`uv run python manage.py changepassword <their email>`. There's no lockout after failed logins yet;
add one (django-axes) before opening signup to the public.

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
