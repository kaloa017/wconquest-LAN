# Administrative release notes

These notes are served only through the administrator API in the game and are
not included in the player changelog popup. Source and documentation in the
public GitHub repository remain publicly readable. No credentials belong here.

## 6.12.0

- Reject unauthenticated and non-admin requests to all admin API routes before
  validating request payloads; retain individual endpoint authorization checks.
- Add an automated guest/player authorization sweep across registered admin routes.
- Update cryptography to the patched 50.x series and audit resolved runtime
  dependencies, including Linux deployment dependencies.
- Restyle shared admin controls without adding public admin release notifications.

## 6.10.0

- Consolidate navigation into Overview, Players, World, Community and Analytics.
  Related tools sit under a compact Tool selector; existing server permissions
  and actions remain in place.
- Add Statistics with country data for each player and world aggregates for
  administrators. Balances, unit pools, active commitments, buildings, terrain,
  progression, trade and banking totals stay behind server-side access checks.
- Retire the literal default admin login on upgrade when another active named
  administrator exists. Delete only that account using the existing transactional
  account-cleanup path; no other country is reset. Sole-owner deletion is deferred
  to prevent lockout and recorded in the private audit log. The name admin can no
  longer be registered or used by create-admin; use a personal administrator name.
- Schema 21 adds player_activity.away_ack_activity, preserving existing data.
  Startup takes a before-v21 backup, migrates and retires the default login before
  starting the scheduler. Existing API clients remain compatible with away ACKs.
- Keep draft protection for real editors/settings. Action inputs, auth forms,
  searches and quantities no longer receive redundant Discard changes controls.

## 6.9.0

- Add the server health dashboard, game/tunnel service checks, available Pi
  sensors, storage/memory/CPU information, backup listings and database checks.
- Add account directory, reviewed deletion, roles, session revocation, research
  grants and maintenance/registration controls.
- Add consistent private game.db snapshots and CSV/JSON user exports. User exports
  exclude password/recovery/MFA secrets and IPs. Database copies contain private
  data and must be protected.
- Add private guest IP/country analytics with time-limited retention and a record
  cap. Keep collection disclosed in the Privacy Policy.
# 6.11.0

- Filter declared crawlers, likely humans and unknown/legacy records; all
  analytics charts and totals respect the filter and search.
- Show aggregate landing-page visit and browser-record counts per matching IP.
- Add exact-IP restrictions with expiry, shared-network confirmation, private
  reasons, audit records and protection against banning localhost/current IP.
- Add Brevo email configuration, templates, previews, account verification and
  bounded delivery status. No usable codes, API keys or encrypted outbox payloads
  are returned in these dashboards. Quota-only password fallback is explicit.
- Admin tools and telemetry have no arrival announcements. Privacy disclosures
  remain public. Older notes in this source file remain visible on GitHub.

