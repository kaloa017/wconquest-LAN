# Save upgrades through schema v10 and rollback

Stop the old game, copy the project folder and make a consistent SQLite backup.
Starting the current version creates `backups/game-before-v10-<timestamp>.db` before changing an
existing database. `DB_PATH` can select another location; backups go beside it.
Migrations v6–v10 are transactional and marked in `schema_migrations`; each runs once.
Legacy v4/v5 schema upgrades are retained for older saves. Do not remove backups.

## Changes

- Accounts, passwords, resources, tiles, research, faction membership and existing
  wonders remain. Legacy SHA-256 passwords upgrade to salted Werkzeug hashes on
  successful login. New accounts use salted hashes immediately.
- The known `admin/admin123` credential is disabled while preserving that account.
  Run `python manage.py reset-password --username admin`, or create/promote your
  host account with `create-admin`. No username automatically receives admin rights.
- Old recovery PINs become hashed **single-use** recovery codes. Existing players
  can use their former PIN once, then generate a stronger code in Settings. New
  signups receive a random code once; only its hash is stored. Host-issued codes
  expire in one hour. Password recovery revokes all existing sessions.
- Faction pooled boats/planes are split equally among current members, in ascending
  user ID order. Remainders go to the first members. Every vehicle is preserved.
  Sharing defaults to **off**. Players keep their personal vehicles on leaving.
  Armies remain pooled; contribution weights govern withdrawals to prevent a new
  member immediately leaving with an equal share of someone else's army.
- The first eight legacy factions receive exclusive colour slots in ID order.
  Extra legacy factions are preserved; creation stays blocked at eight or more.
  A host can disband excess factions through the admin tools. Personal RGB colours
  remain in `base_color`.
- Wonders move from a globally unique key to `(key, owner_id)`, with a build tile in v6; v8 removes placement.
  Existing owners retain their wonder without a tile restriction retroactively.
  Existing effects use the new, smaller bonuses; numbers are in `config.py`.
- Added religion/cooldown, UI preferences, changelog version, recovery, music and
  session-revocation columns; request stats, audit, map revisions, stock market,
  scheduler state and contribution tables/indexes/triggers.
- Gameplay writes commit immediately. Only API counters/presence are batched.
  A crash can lose at most the unflushed interval of counters, not committed trades.

## Later upgrades

- **v7:** adds cosmetic Donator status/title. Sets request, login, chat and trade
  throttles to 0 (unlimited) once; subsequent administrator settings are preserved.
  Clears obsolete `water_cells` reports so authoritative geography is used.
- **v8:** adds a displayed rank override independent of administrator permissions.
  Clears wonder placement (`grid_key`) while preserving each owner's wonders and
  resources. Ordinary wonders now apply country-wide without location checks.
- **v9:** splits legacy `eva` (Geofront) records into `eva_00`, `eva_01`, `eva_02`
  for every previous owner, preserving timestamps and granting all three unlocks
  without charging again. Old custom image filenames remain usable as EVA-01 images.
  Existing cosmetic deployments remain; each player still displays one at a time.
- Dedicated `island:<stable-id>` territories coexist with old grid keys. Existing
  grid ownership, buildings, populations and investments are not automatically
  rewritten. An overlapping new island claim is blocked until the old grid owner
  releases that tile, preventing two owners from claiming the same saved land.
- Tropical terrain is generated for new equatorial claims; existing saved biomes
  stay as they were. New wonder/building bonuses use the current balance settings.

- **v10:** adds a persistent idea-submission timestamp and ideas-only ban flag.
  Existing accounts default to allowed and can submit immediately. The one-minute
  interval survives restarts; admins can block/unblock ideas independently of game
  bans or chat mutes. Moderation changes are audited.

The version displayed to players (6.3.6) is separate from SQLite schema version 11.
Normal migration testing uses isolated databases; your live game.db is not a test fixture.

## Backup and rollback

Use `python manage.py backup --output /path/to/backup.db` for a consistent live
backup. Copy `.session-secret` separately if you want sessions to survive a move;
protect that file. Back up `media/world.mp3` and ignored EVA images too.

To roll back: stop the service, restore the old source folder **and** the pre-upgrade
database backup. Keep the newer database separately for inspection. Remove/move
its associated `-wal` and `-shm` files only while the service is stopped; do not
mix an old database with newer WAL files. Start the old version on a private LAN
first. The old version has weaker authentication and should not be exposed online.
There is no automatic downgrade migration. Upgraded hashed passwords require v6.

Unmodified older clients do not send the new CSRF token; reload the page after
upgrading. Previously signed sessions may also require login again.

## Geography update in 6.3.1

No additional database schema change. Large islands now use regular grid cells for
new claims. Existing owned `island:` records keep their ownership, assets and stable
IDs; a legacy large whole-island claim blocks overlapping regular-grid claims.
Small islands remain single territories. New Antarctic land/ice-shelf claims use
tundra; existing stored biomes are preserved. Cached map data uses the release
version in its URL; refresh the browser after restarting the updated server.

## Schema 11 — 6.3.4 audit

Adds four SQLite triggers to invalidate the map defenses of all affected group
members when territory ownership/counts or faction membership changes. Increments
map_epoch once, so clients request a fresh map. The migration is transactional and
idempotent; it does not rewrite accounts, password hashes, resources, armies,
territory ownership, buildings or unlocks. A consistent `before-v11` database
backup is made before upgrading an older save. All earlier migrations still run
for older iterations.

Army fixes affect future disbands and round resets. They cannot reconstruct troops
lost or duplicated by an earlier iteration; inspect affected players and correct
them with host tools if necessary. No public route was renamed or removed. Invalid
JSON field types now return 400, and SECRET_KEY values shorter than 32 characters
prevent startup; replace a weak configured key and expect players to log in again.
The live save was not modified during the audit; compatibility was tested on a
SQLite backup copy and isolated legacy fixtures.

## 6.3.5 — round safety correction

No additional schema migration. AUTO_RESET_ROUNDS is False by default, preventing
status polling or the scheduler from erasing a world with a historical winner.
The explicit admin reset remains available. Restart the server and reload clients.
The original audit's automatic-expiry change was unsafe for existing saves and
has been superseded.

## 6.3.6 — remove win logic

No schema or player-data migration. All victory detection and automatic round
reset paths have been removed, including the former opt-in configuration switch.
Old winner_id/winner_name/win_time rows are ignored; they cannot trigger a reset.
The explicit administrator reset is retained. /api/game/status still supplies
leader/event information and always returns status playing; victory-only fields
threshold, reset_in and automatic_reset are no longer returned. Reload browsers
for the removal of the victory overlay/countdown and obsolete polling.


## 6.4.0 — campaigns and player banking (schema 12–13)

Adds persistent campaigns, exchanges, moderation confirmations, strike events,
casino records, live catalog definitions and player bank offers/loans. Adds moderator,
timeout, rocket and cosmetic username fields. Existing accounts, territory,
resources and paid-for wonders are retained.

## 6.5.0 — queued orders and space (schema 14–15)

Before the first upgrade, the server uses SQLite's backup API to write a consistent
copy to `backups/game-before-v15-<timestamp>.db` (or the configured database filename).
This includes committed WAL data. Start one server process for the upgrade. No world
reset or external save replacement is performed. Accounts, Earth territory,
resources, buildings and existing campaign progress remain compatible.

Schema 14 adds `campaigns.route_json` (empty for existing battles),
`campaigns.origin_faction` (backfilled from the commander's current faction), and
indexes for private participant/status queries. Survivors return to the original
army pool even if the commander changes factions. The original pool of an already
moved commander in a pre-upgrade battle cannot be reconstructed from old saves;
its current faction is the migration's best available information.

Schema 15 creates `space_program`, `space_businesses` and `planet_tiles`.
These start empty and are populated only when players unlock/use space. Planetary
maps are personal; migration does not claim or alter any Earth tiles. All payments,
mission transitions and cargo delivery share the existing request transaction.
Migrations are idempotent. The explicit admin player/world reset includes the new
space tables; player reset also settles active battles before resetting the army.
There are still no automatic wins or round resets.

The UI now restricts defensive orders and battle visibility to the actual defender,
rather than faction mates. `/api/campaigns` returns every active participating battle
plus the 20 latest completed battles. Only the attacker receives queued target keys.
`/api/attack` retains its old fields and accepts an optional `target_keys` list.
`/api/nuke/build` retains single purchases by default and accepts optional `amount`.
The changelog API retains `version`, `show`, `text` and adds `versions`; acknowledgement
optionally accepts the displayed version, with an empty body remaining compatible.

Restart your server and reload browsers after installing the code. Existing older
space-unaware code should use the pre-upgrade backup when rolling back; do not run
an older version against newly earned space progress.
