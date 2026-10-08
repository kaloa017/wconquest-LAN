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

The version displayed to players (6.3.1) is separate from SQLite schema version 10.
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
