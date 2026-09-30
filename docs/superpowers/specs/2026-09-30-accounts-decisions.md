# Plan decisions: user accounts and collaboration

Settled in a grill-me session on 2026-09-30. Input for `/superpowers:writing-plans` or
`/superpowers:brainstorming`.

## Goal

Add logins so several households can use Condo Finder, each with its own shared experience, and
make collaboration between partners (e.g. the owner and their girlfriend) a first-class feature.

## Audience and access

- **Invited users now, public signup later.** Build for invite-only groups, without choices that
  block open signup later.
- **Public URL via Tailscale Funnel** (`https://<mac-mini>.<tailnet>.ts.net`, automatic TLS). The app
  stays on the Mac mini, so scraping keeps the residential IP.
- **Retire `http://<mac-mini>:8000`.** Everyone, the owners included, uses the HTTPS URL. gunicorn
  binds to localhost only.
- **Minimal hardening:** every page requires login except login and invite/signup pages; secure
  cookies; `CSRF_TRUSTED_ORIGINS` for the ts.net host. No lockout or 2FA for now. Brute-force risk
  is accepted; add lockout (e.g. django-axes) before public signup.

## Accounts

- **Email + password**, Django's built-in auth. Log in with email; a display name is required at
  signup and shown on comments, votes and Feed activity.
- **No outgoing email for now.** Invites are copy-paste links. Password resets are done by the site
  admin (admin or a management command). Users can change their own password.

## Groups (the unit of collaboration)

- **Search group** owns the shared state: status, comments, votes, default filters, "What we're
  looking for" priorities, Trends reports and picks, Feed.
- **Each user is in exactly one group.** No group switcher.
- **Invites, two kinds:**
  - Site admin creates "new group" invite links for new households.
  - Any member creates "join my group" invite links.
  - Links are single-use and expire.
- **Group settings page:** group name, member list, create/revoke invite links, remove a member,
  leave group, change own password. Everything else via Django admin.
- **Leaving or removal:** the person gets a fresh empty solo group. Their comments stay in the old
  group under their name; their votes are removed from the old group.

## Per-listing collaboration

- **Status:** one shared status per group per listing (New / Interested / Toured / Applied /
  Rejected). Record who changed it and when; show it on the listing and in the Feed.
- **Personal vote:** each member can give 👍 or 👎 per listing.
  - Shown on cards, map pins, table and listing page.
  - Filters such as "both like" and "we disagree".
  - Fed to the Trends Claude ranking as a signal.
- **Notes become a comment thread:** each comment has author and timestamp, is edited or deleted by
  its author only, and appears in the Feed.
- **Migration of existing notes:** each non-empty `Listing.notes` becomes the first comment,
  authored by the owner's account, dated at the listing's last update. Existing statuses,
  priorities and Trends reports move to the owners' group.

## Filters

- **Default filters per group,** editable with "Save as our defaults". New groups start from app
  defaults. The current hard-coded defaults (2 bd / 2 ba / 2 parking / $2,000 min / hide apartments)
  become the owners' group defaults.

## Trends

- **Per group:** priorities, daily Claude report and top-5 picks, with a per-group manual-run cap.
- **Market charts (`trend_stats`) are shared,** computed once.
- **Cost on the owner's API key,** about $0.50 per group per day.

## Feed

- New-listing events stay global.
- Change events show for listings the group tracks.
- Group activity (comments, status changes, votes by members) appears in the Feed.
- **Unread state moves from the `feed_seen_at` cookie to per-user storage,** so it syncs across
  devices.

## Live updates

- **Light HTMX polling** (~30s) for the listing page's comment thread and the Feed unread badge.

## Shared listing data and permissions

- **Site admin only (staff):** price-history edits, field overrides, Refresh from sites, the Sources
  page. Other users see this data read-only.
- Scraped listings, price history and sources stay global, shared by all groups.

## Delivery

- Stack of small PRs per repo conventions. New migrations only; data moves go in data migrations.
- Don't enable Funnel until login protection is live.
- Update `INTENT.md` ("just the two of us" no longer holds), `CLAUDE.md` and
  `docs/architecture.html` as part of the stack.
