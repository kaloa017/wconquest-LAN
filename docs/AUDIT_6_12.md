# 6.12 audit and redesign

## Scope and execution checklist

The two supplied prompts are applied to the existing Flask/SQLite/Leaflet game.
The visual direction uses translucent shell surfaces, solid readable game content
and short transform/opacity transitions. No new framework, database, animation
dependency, mandatory email, gameplay rebalance or production-data edit is planned.

- [x] Inventory Python modules, client layers, tests, deployment and prior audits.
- [x] Trace authoritative state: SQLite transactions and server validations;
  browser panels consume API snapshots and incremental map updates.
- [x] Review existing account/recovery/TOTP/email, economy, campaign, faction,
  space, moderation, analytics, save migration and backup implementations/tests.
- [x] Record baseline Python/UI tests and dependency checks.
- [x] Apply shared materials, typography, controls, navigation and responsive UI.
- [x] Add local reduced-effects options and honor system accessibility settings.
- [x] Fix policy presentation and stale map responses; improve recovery copying,
  connectivity feedback and first-country next actions.
- [x] Check all admin routes reject guests and ordinary players on a test save.
- [x] Run critical-flow regressions, syntax, dependencies and public-package checks.
- [x] Verify representative desktop/mobile game, account, research/admin/policy UI.
- [x] Record verified results, save impact, rollout and remaining limitations.

## Architecture and feature coverage

| Area | Authoritative code / UI | Verification |
|---|---|---|
| Accounts/recovery | features.py, security.py, two_factor.py, email_verification.py | disposable authentication and abuse tests |
| Territory/production | app.py, features.py, geography.py; client.js, map-performance.js | claim/production/geography/delta regressions |
| Buildings/research | config.py, progression_content.py, research.py; research-upgrades.js | costs, requirements and project-boundary tests |
| Economy/trade | economy.py, expansion.py, app.py | transactional purchases, loans, exchanges and shares |
| Factions/combat | expansion.py, app.py; progression.js | roles, declarations, orders and shared pools |
| Space/late game | space.py, late_research.py | unlock, yield, travel and persistence tests |
| Admin/analytics | admin_dashboard.py, guest_analytics.py, traffic_controls.py | role-boundary sweep and dedicated regressions |
| UX/accessibility | interface.js, product-ui.js, product-ui.css | offline renderer/axe checks and local viewport review |
| Privacy/terms | policies.py, docs/PRIVACY.md, docs/TERMS.md | escaped semantic rendering; no claim of legal certification |
| Deployment/data | runtime.py, migrations.py, deploy/raspberry-pi, tools/pi_backup.py | isolated migrations, backups, proxy and release checks |

## Findings

1. Several legacy style layers compete with shared controls. A final, documented
   product layer will own visual tokens/materials without replacing feature logic.
2. Policy documents currently render as a single preformatted text block. Parse
   a small escaped subset into real headings, paragraphs and lists.
3. Map deltas can return out of order from overlapping action/background refreshes.
   Reject older epoch/sequence versions before changing territory data.
4. Recovery dialogs require acknowledgement but lack an explicit copy action.
   Add user-initiated copying without logging or returning credentials elsewhere.
5. Failed background synchronization lacks a clear persistent connection state.
   Use existing API results and browser online/offline events; add no timer/poll.
6. Existing tutorial is revisitable and skippable. Add real-state first-country
   objectives to Country, rather than another forced tutorial for experienced users.
7. Some admin handlers validate payloads before checking roles. Move the shared
   role check ahead of payload validation and retain endpoint guards. The audit
   found inconsistent rejection order, not an unauthorized mutation exploit.
8. Release-number-only cache keys can retain changed local assets. Add cached
   content fingerprints to CSS/JS URLs, including standalone policies.
9. The dependency audit resolved cryptography 48.0.1 with known advisories.
   Raise the supported range to 50.x; the patched resolution is 50.0.2.
   The game uses Fernet, not the affected PKCS7/X509 APIs; exploitability in this
   application was not demonstrated. See the vendor's
   [security release notes](https://cryptography.io/en/latest/changelog/).
10. Actual copied-save startup logged an invalid Leaflet LatLng when a legacy
    fallout island had no current geometry. Skip unknown/non-grid keys without
    modifying saved fallout, and invalidate the overlay cache if islands load.
11. Country's captured renderer bypassed the new objectives wrapper. Route the
    panel through the final renderer and test that navigation path explicitly.
12. Privacy contained obsolete text saying email is never collected alongside
    the optional email disclosure. Correct that contradiction and disclose local
    display preference storage.

Earlier audit documents describe historical versions; their old instruction not
to use browser verification is superseded by the user's later requests to test
locally and show the result. All new tests use disposable/copied saves.

## Executive summary and implementation

This is an incremental improvement of the existing game, not a replacement.
The main changes are adaptive glass shells, stronger shared presentation,
working local accessibility settings, first-country progress, recovery copying,
connection feedback, map ordering/fallout fixes and authorization hardening.

| Files | Purpose |
|---|---|
| static/product-ui.css, index.html | Final visual tokens, responsive surfaces, forms, cards, tables and restrained motion |
| static/product-ui.js | Local settings, existing-request sync feedback, safe code copying and real progress objectives |
| static/client.js, static/legacy-client.js | Reject old map responses; render legacy fallout safely |
| asset_versions.py, community_tools.py | Content fingerprints with no per-request full-file rehash |
| policies.py, docs/PRIVACY.md | Escaped semantic documents, shared styles and accurate email/storage disclosures |
| features.py | Shared admin role guard before payload validation |
| requirements.txt | Patched cryptography runtime series |
| tests/test_product_audit.py, tests/interface.test.cjs, tests/ui_fixtures.py | Authorization inventory, document escaping, asset caching, rendering and interaction regressions |
| .github/workflows/checks.yml, README.md, CHANGELOG.md, docs/ADMIN_CHANGELOG.md | Checks, release guidance and separate administrative notes |

Earlier local 6.10/6.11 work remains in this checkout. It is not all newly created
by this audit. Public notes omit administrative implementation details; repository
source and developer reports are still publicly readable if pushed.

## Testing results

- Baseline: 207 Python tests, 206 passed and one stale hardcoded policy-date
  assertion failed. Replaced that date assertion with an updated-date format check.
  Baseline UI: 27 passed.
- `python -m unittest discover -s tests`: **210 passed**, 113.112 seconds.
- `npm run test:ui`: **32 passed**. Includes real API-shaped fixtures for 23 major
  renderers, full guest/signed-in startup, keyboard/dialog checks, contrast,
  research filtering, old map responses, preferences, recovery copying, fallout
  and the Country navigation integration.
- `python -m unittest discover -s tests -p test_product_audit.py -v`: authorization
  sweep, escaped policy rendering and asset fingerprint tests passed.
- `node --check` for every top-level static JS file, Python AST parse for 31 root
  modules, `python -m pip check`, `python tools/check_release.py` and
  `git diff --check`: passed (Git reports existing LF/CRLF normalization notices).
- `python -m pip_audit -r <resolved-runtime-requirements> --progress-spinner off`:
  initial audit found advisories in cryptography 48.0.1; after updating, **no known
  vulnerabilities found**. The audit included Linux gunicorn despite Windows
  platform markers. This is advisory coverage, not proof of absence of flaws.
- Browser review on a copied save: sign-in, Country, research with 123 focuses,
  compact navigation, admin overview, phone feature sheet, working reduced-effects
  and motion settings, and semantic privacy page. Viewports: 1440x1000,
  390x844 and 820x1180. Phone/tablet page width matched viewport; phone header
  backdrop filter was `none`. Saved screenshots are local review artifacts.

There is no bundler build: Flask serves the local JS/CSS directly. No real email
was sent, destructive admin action performed or production account changed.

## Database impact and safety

This 6.12 change adds **no migration or gameplay rebalance**. The combined local
update includes the earlier additive migrations through schema 22; see
[migration notes](MIGRATIONS.md). Test migrations run on isolated databases.
The original game.db SHA-256 remained
`56f889201e70eefc434d7aeb6812e38ef233b71e84c5e4b753e9d3199797534f`.
Browser verification used a separate backup with a disposable admin account and
the scheduler disabled. Unknown legacy fallout remains in the save; rendering
it safely does not delete or extend it.

## Deployment and rollback

Nothing was pushed, deployed or restarted on the Pi for this request. When this
version is committed and approved for rollout:

1. Create and verify a private Pi backup with the existing backup tooling.
2. Stop the game service, update the checkout to the intended release and run
   `.venv/bin/python -m pip install -r requirements.txt` within /opt/wconquest.
   Cryptography 50.x is now required; do not reuse an older virtual environment
   without upgrading its packages.
3. Start the existing wconquest service. Existing startup migrations apply if
   upgrading across the earlier 6.10/6.11 work. Run the supplied Pi health check
   and verify local login, map selection and the public tunnel.
4. Keep the tunnel configuration unchanged. Asset fingerprints refresh client
   files automatically. Email remains off until configured by the operator;
   follow EMAIL_SETUP.md and never put a provider key in Git or chat.
5. For rollback across migrations, stop the game, restore a compatible private
   backup and code revision together, then restart and health-check. A restore
   discards progress after that backup; retain the failed deployment's save for
   diagnosis. See DEPLOYMENT.md and MIGRATIONS.md for existing host procedures.

## Remaining work and verification limits

- Highest operational priority: test the final version on the actual Pi and
  representative school/mobile networks. No Pi frame-time, thermal, sustained
  concurrency or WAN benchmark was run; no player-capacity claim is justified.
- Email sending, provider DNS/delivery and quota exhaustion were covered with
  isolated tests; live delivery requires the host's provider setup.
- Shared styles cover the entire app, but browser checks sampled major flows.
  The automated suite is broader; neither constitutes every possible button,
  device, gameplay combination or third-party accessibility certification.
- Legacy rendering wrappers still exist. Gradually consolidate them rather than
  removing feature styles wholesale and risking existing mechanics. The final
  product layer deliberately owns materials while feature layers retain layout.
- Existing War Hero achievement is still disabled by its old `False` predicate;
  historical battle data needs a reliable war-capture counter before awarding it.
  Naval/air milestone checks use the most recent win and warrant a separate
  achievement-history correction. No achievements or player rewards were changed
  speculatively during this presentation/security update.
- Content-specific wording and player-created map art were preserved. This pass
  does not certify moderation policy, legal compliance or production security.

Verified improvements are those tied to the tests/browser checks above. Expected
performance benefits from bounded blur and unchanged polling are implementation
properties; actual FPS improvements remain unmeasured on the Pi and player phones.
