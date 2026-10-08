# Round-reset correction — 6.3.5

The audit incorrectly re-enabled destructive automatic round expiry on an existing
world. Its pre-reset backup contains winner_id and win_time from October 7; the
old status endpoint erased the round after 45 seconds. Restored browser polling
could trigger it immediately. The audit also added scheduler expiry. This was
unsafe behavior to reactivate during a compatibility-preserving audit.

6.3.5 disables both automatic paths by default and suppresses the countdown UI.
A regression covers a stale winner, owned territory and resources across status
polling and scheduler ticks. The full suite now has 48 tests. With host approval, the most-progress compatibility-check copy was restored:
17,656 owned tiles, 593 buildings, all 10 accounts. Its stale winner was cleared,
and the post-reset save was preserved separately. The running server was restarted
and verified as 6.3.5. The report below records the
original 6.3.4 audit; its automatic-reset change is superseded by this correction.

# Audit and release report — 6.3.4

Audit branch: `audit/github-readiness`. The local source is prepared for GitHub;
no push or deployment was performed. Existing host data was excluded from release
files and the live database was not changed by this audit.

## Architecture and baseline

Flask routes in app.py handle SQLite gameplay. features.py installs security,
request-scoped transactions, preferences, stocks, admin tools and public map
snapshots. runtime.py owns connections/session security and trusted-proxy handling;
migrations.py upgrades existing saves. A scheduler handles collection, market
updates and round expiry. config.py centralizes balance. Leaflet with vanilla
JavaScript drives index.html; client.js overrides legacy-client.js. Static styles
are layered in game.css, upgrade.css and polish.css. Bundled masks and GeoJSON
provide authoritative land/coast/island data. Waitress hosts Windows/LAN; docs
provide Gunicorn, systemd, Apache/Nginx and Cloudflare deployment examples.

Baseline before audit edits: **27 Python tests passed**, both JavaScript syntax
checks passed, Python source parsed, dependencies passed pip check. This project
has no build pipeline, linter or type checker configured; none was invented or
claimed to have passed. CI now checks Windows/Linux with Python 3.11–3.14, but that
remote matrix has not run yet.

## Findings

References below point to the relevant location in the final source. Findings were
identified before their corresponding edits; later verification added the cold
geography startup finding. High/medium correctness fixes were made before UI and
performance work.

| Severity | File / line | What is wrong and why it matters | Proposed/applied fix | Status |
|---|---|---|---|---|
| High | `static/legacy-client.js:1120` | Stored announcement HTML could execute scripts; names in online/win/battle views also entered HTML. | Escape all untrusted strings; regression executes the actual announcement renderer. | Fixed |
| High | `app.py:2497` | Loans used the shared faction vehicle pool, transferring vehicles owned by other members. | Lend and return personally owned vehicles only; tests cover both directions. | Fixed |
| High | `migrations.py:162` | Changing tile counts or membership left other group territories showing stale distributed defenses. | Four map-invalidation triggers and one epoch refresh; verify delta output. | Fixed, schema 11 |
| High | `geography.py:51` | Threaded cold startup could publish islands before its cell index was ready. | Serialize initialization; 24 concurrent lookups construct the index once. | Fixed |
| Medium | `features.py:172` | Malformed text/booleans and non-finite admin settings could crash or mutate unintended state. | Validate JSON types and finite settings before legacy handlers. | Fixed |
| Medium | `runtime.py:11` | Configured secrets bypassed length validation; a second worker could read a newly created empty file. | Enforce minimum length and briefly wait for the first writer. | Fixed |
| Medium | `app.py:1` | Admin disband discarded troops held in the faction pool. | Use the normal proportional leave path for every member. | Fixed |
| Medium | `features.py:588` | Force-setting the current faction could delete a sole-member faction before rejoining it. | Treat same-faction assignment as a no-op. | Fixed |
| Medium | `app.py:1780` | Round reset created personal armies in addition to the faction army, duplicating troops on leave. | Keep one faction pool and record contributions for reset members. | Fixed |
| Medium | `app.py:1577` | Dedicated island territories were omitted from grid-only blasts. | Include indexed custom islands within the same distance rule; render island fallout. | Fixed |
| Medium | `app.py:756` | A nominal read-only endpoint could attempt a transaction upgrade while another writer ran. | Choose events only in a write transaction; read endpoint returns the active event or null. | Fixed |
| Medium | `app.py:1` | Winning rounds depended on a player polling to expire. | Scheduler performs expired-round reset even without online players. | Fixed |
| Medium | `app.py:2626` | Accepting a pending merge could dereference an account removed by another merge. | Cancel absorbed-account proposals and reject absent/banned inviters. | Fixed |
| Medium | `features.py:669` | Workers shared one upload temporary filename; music removal could race file metadata reads. | Unique temporary upload paths, atomic replacement and missing-file handling. | Fixed |
| Medium | `static/client.js:7` | Bootstrap failure escaped the API error handler and could leave an unusable screen. | Catch bootstrap/API failures and restore authentication with useful text. | Fixed |
| Medium | `static/legacy-client.js:593` | Late responses could repaint another selected tile; private chat could enter a newly selected conversation. | Check session, selected key, channel, faction and destination identity after awaiting. | Fixed |
| Medium | `static/client.js:40` | New sessions retained cursors/notifications and stopped polling win status or spectator presence. | Reset account state, poll wins/presence, end expired sessions cleanly. | Fixed |
| Medium | `static/legacy-client.js:96` | 768px CSS used mobile layout while JavaScript chose desktop. | Match <=768px; verify mobile sheet at exactly 768px. | Fixed |
| Medium | `static/client.js:258` | Escape could dismiss the only displayed recovery code without completing signup. | Require explicit acknowledgement and focus the active dialog. | Fixed |
| Low | `index.html:202` | Dialog/input labels, clickable controls and focus visibility were incomplete. | Add accessible labels, keyboard activation, focus indication and return focus. | Fixed for changed controls; broader assistive-technology testing remains |
| Low | `static/legacy-client.js:1804` | Rendered chat and seen-notification IDs grew during long sessions. | Bound rendered chat to 200 messages and seen IDs to 2048. | Fixed |
| Low | `static/client.js:205` | Island capital/EVA markers used regular-grid centers or were skipped by the mainland filter. | Redraw capitals with all territories and use island coordinates. | Fixed |
| Low | `features.py:455` | Stock listing looked up faction IDs once per asset (N+1 reads). | Join faction IDs in the existing query without exposing the internal alias. | Fixed and measured |
| Low | `app.py:1` | Optional IP lookups could enqueue repeated clients and grow the pending work. | Deduplicate pending lookups and cap tracked clients/cache. | Fixed |
| High | `.github/workflows/checks.yml:41` | CI invoked a missing release-check script and the repository lacked a licence. | Add tested release checks and MIT licence; protect private data and geography integrity. | Fixed |
| Medium | `app.py:956` | Legacy host terrain-edit route writes water_cells but authoritative terrain ignores those values. | Choose whether host overrides should exist; then synchronize backend and browser masks, or retire the controls explicitly. | Not fixed: requires a terrain-authority decision; do not silently weaken trusted geography |
| Low | `tools/build_terrain.py:39` | Terrain generator assumes the fixed 0.18-degree mask despite importing GRID. | Support regenerating dimensions across server/browser together before changing GRID. | Not fixed: changing grid resolution changes territory IDs and save semantics |
| Low | `static/legacy-client.js:1623` | Superseded definitions and layered wrappers make future changes harder to reason about. | Consolidate incrementally with behavior coverage. | Not rewritten: style-only restructuring was excluded |

## Verification and measurements

- Final server suite: **47 tests** (27 existing, 17 audit regressions, 3 release
  privacy regressions). JavaScript regressions execute announcement rendering,
  delayed territory selection, delayed private chat and failed bootstrap handling.
- JavaScript syntax, dependency compatibility, Python parsing, release integrity
  checks and git whitespace checks pass. No previously passing test regressed.
- Headless Chrome checked 1440px desktop, 768px tablet, 390px phone and 320px narrow
  phone. Checked collapsed/latest chat, expanded composer, tutorial centering,
  income descriptions, redacted donation details, ideas submission, mobile toast
  bounds/no horizontal document overflow, recovery acknowledgement and startup
  failure. No uncaught browser errors in these checks. Visual checks use isolated
  API fixtures; external map/CDN traffic was substituted or blocked. They do not
  establish that a live tile provider, tunnel, Apache or Nginx works on your host.
- A consistent SQLite backup copy of the existing game.db migrated to schema 11
  with identical accounts, password hashes, resource balances, armies, tile
  ownership and buildings. The original save remained untouched. Legacy migration
  and idempotence checks also pass in disposable fixtures.
- Stock benchmark: 64 countries, an investor belonging to a faction, 31 local
  runs with the first discarded. SELECTs **67 -> 4**; median handler time
  **1.702 ms -> 1.486 ms**. Windows warm-cache timings include JSON response
  generation; no network/Pi capacity claim. Other efficiency fixes are structural
  bounds or correctness fixes; no unmeasured speedup is claimed.

## Migration and compatibility

Schema 11 adds four invalidation triggers and refreshes the map epoch once. It
preserves stored game values and creates a consistent before-v11 backup when an
older save is opened. Historical troop loss/duplication cannot be reconstructed;
correct affected players through host tools if needed. Public endpoint names are
preserved. Invalid JSON types now fail with 400. An explicit SECRET_KEY shorter
than 32 characters now prevents startup; replace it with a strong key, which
requires players to log in again. See MIGRATIONS.md for prior upgrade behavior.

## Scope and file coverage

The pass covered Python application modules, route guards, migrations, scheduler,
config/balance, CLI tooling, active and superseded JavaScript definitions, HTML,
all three stylesheets, tests/SQL fixtures, dependency declarations, documentation,
GitHub configuration and ignore rules. Geography files were reviewed by format,
unique IDs, bounds/coast examples, bitset size and gzip parity; binary masks are
not meaningfully line-reviewable. Local saves, credentials, feedback, media and
backups were treated as private runtime data, not public source.

Public file inventory:

- `.editorconfig`
- `.env.example`
- `.gitattributes`
- `.github/ISSUE_TEMPLATE/bug_report.yml`
- `.github/ISSUE_TEMPLATE/feature_request.yml`
- `.github/dependabot.yml`
- `.github/pull_request_template.md`
- `.github/workflows/checks.yml`
- `.gitignore`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `LICENSE`
- `NOTICE.md`
- `README.md`
- `README_DEPLOY.md`
- `SECURITY.md`
- `app.py`
- `config.py`
- `data/coastal-cells.bin`
- `data/countries.geojson`
- `data/land-cells.bin`
- `data/land.geojson`
- `data/pacific-islands.geojson`
- `data/pacific-islands.geojson.gz`
- `docs/AUDIT.md`
- `docs/DEPLOYMENT.md`
- `docs/EVA_IMAGES.md`
- `docs/MIGRATIONS.md`
- `features.py`
- `geography.py`
- `index.html`
- `manage.py`
- `migrations.py`
- `requirements.txt`
- `runtime.py`
- `static/client.js`
- `static/eva/README.md`
- `static/game.css`
- `static/legacy-client.js`
- `static/polish.css`
- `static/upgrade.css`
- `tests/client_audit.cjs`
- `tests/legacy_schema.sql`
- `tests/test_audit.py`
- `tests/test_release.py`
- `tests/test_terrain_supporters.py`
- `tests/test_upgrade.py`
- `tools/build_terrain.py`
- `tools/check_release.py`

## Remaining issues and suggested follow-ups

1. Decide whether admins should override terrain classification. The legacy
   set-water endpoint currently reports success without affecting authoritative
   gameplay; the existing trusted-land protections were retained pending that
   decision. This is a real remaining bug, listed explicitly above.
2. Keep GRID at 0.18. Supporting another grid size requires coordinated mask,
   browser and save migration changes; the generator currently assumes it.
3. Run the new GitHub Actions matrix after pushing, then smoke-test real HTTPS,
   map tiles, Cloudflare and Apache/Nginx on the intended host. Public hosting and
   Cloudflare credentials were not provisioned. Pi capacity remains an estimate.
4. Broaden real touch-device/screen-reader testing. Fixture checks verify changed
   states but do not substitute for a human testing every gameplay screen.
5. Consolidate legacy client overrides only as a separately tested maintenance
   task. Continue dependency updates and consider reproducible pinned deployment
   dependencies. Existing version ranges were preserved.
6. Multi-worker request counters, throttling buckets and caches remain process
   local. The documented one-worker threaded deployment avoids inconsistent
   aggregate host statistics; distributed hosting needs shared state.

MIT permits reuse and modification. NOTICE.md records third-party data/assets.
No MP3 or copyrighted EVA JPG is included. The release check excludes common
private files and detects selected credential patterns; inspect new contributions
because no pattern scanner can recognize every secret.
