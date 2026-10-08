# 6.3.5 — protect existing rounds

- Automatic round resets are disabled by default, including both status polling
  and scheduled tasks. A stale winner in an older save cannot erase an existing
  world. Only an explicit host reset starts a new round with the default config.
- Removed the destructive countdown overlay when automatic resets are disabled.
- Added a regression covering a day-old winner with existing territory/resources.

# 6.3.4 — audit and GitHub release preparation

- Fixed unsafe HTML rendering in announcements, player names and battle history.
- Prevented vehicle loans from transferring another faction member's shared fleet.
- Added malformed-input checks and minimum length for explicit session secrets.
- Preserved armies on faction disband/reset and fixed same-faction reassignment.
- Added schema 11 map-defense invalidation triggers; existing player data is retained.
- Included dedicated islands in blasts and positioned island capitals/EVA correctly.
- Restored win polling and scheduler-only round expiry; kept spectators present.
- Fixed worker startup, geography initialization and concurrent music-file races.
- Discarded stale territory/chat/account responses and handled failed startup.
- Improved tablet boundary, keyboard controls, focus states and dialog focus;
  recovery codes require acknowledgement. Bounded long-running chat/notification UI.
- Reduced stock list queries from 67 to 4 for 64 countries; bounded geolocation queue.
- Added MIT licence, contributor/security guidance, private-file release checks,
  cross-platform CI and audit regression tests. No private saves or artwork bundled.

# 6.3.3

- Fixed coastal landing controls on small islands and preserved inspected terrain
  flags during changed-tile updates.
- Added a compact shoreline mask so grid cells containing coastline count as coastal
  even when no neighbouring cell is entirely water. Ports and naval landings use
  the same server checks.

# 6.3.2

- Added admin resource resets for all eight balances or one selected resource,
  including money. Resets require confirmation and record before/after balances
  in the audit log. Country assets, units, research and stock holdings remain.

# 6.3.1

- Removed permanent coloured outlines and small-island markers from unclaimed islands;
  they now appear only on hover or selection, like regular tiles.
- Larger islands use multiple ordinary grid tiles. Preserved existing whole-island
  ownership and blocked overlapping new claims.
- Added Antarctic year-round ice shelves to playable geography and tundra for new
  Antarctic claims; kept open ocean as water.
- Added a reproducible geography build tool and configurable single-island threshold.

# 6.3.0

- Fixed off-screen mobile territory-purchase notifications and wrapped long claim prices.

- Moved collapsible chat into the side-menu Chat tab: three recent messages when
  collapsed, full conversation and composer when expanded; removed the map widget.
- Redacted donation details and added an easy public setting at the top of config.py.
- Split Geofront into EVA-00, EVA-01 and EVA-02, each unlocking its own cosmetic JPGs.
  Existing Geofront owners keep all three unlocks through an automatic migration.
- Added a centered, accessible 15-step guide with shortcuts to relevant menus.
- Added per-minute/per-hour income tooltips and tap-to-view resource income on mobile.
- Added a persistent one-minute ideas submission cooldown and admin ideas bans.
- Added a clear restart/proxy hint when the running server lacks the Ideas route.
- Updated README, save migration notes, EVA image instructions and private-file ignores.

# 6.2.0

- Reworked desktop/mobile navigation, sheets, forms, buttons, stock charts and dialogs.
- Kept a single Settings menu in the top right; added emoji menu labels.
- Added Donate and private Ideas dialogs, an admin ideas inbox and rank controls.
- Made wonders country-wide without landmark/selected-tile placement restrictions.
- Added country overview suggestions and My country / Explore islands map shortcuts.

# 6.1.0

- Restored the original admin dashboard layout with additional Host tools.
- Added shared music removal and detected LAN join addresses in the admin panel.
- Kept scroll arrows only on the main menu strip.
- Made all request/login/chat/stock-trade throttles unlimited until configured by admins.
- Added cosmetic Donator badges, selectable supporter titles and admin grants/revocations.
- Added authoritative 1:10m land/island checks, tropical terrain and dedicated Pacific
  island territories; preserved legacy tile ownership and blocked duplicate claims.
- Corrected the map referrer policy.

# 6.0.0

- Added safer passwords, recovery codes, session revocation and CSRF protection.
- Added private host request tracking, audit logs and expanded moderation tools.
- Added shared MP3 music with personal mute and volume settings.
- Added eight faction colours and optional fleet sharing.
- Reduced tile/vehicle/voyage costs; increased base plane range to 40 cells.
- Added six ideologies, eight religions with a 24-hour change cooldown and five buildings.
- Made wonders available per player, added landmark wonders and reduced their effects.
- Added a hidden Japan wonder that unlocks cosmetic EVA JPG portraits.
- Added country/faction investments, portfolio, price charts and transaction fees.
- Added changed-tile synchronization, response compression and batched counters.
- Improved navigation, mobile panels, scroll arrows and saved preferences.
- Added Raspberry Pi, Apache, Nginx and no-port-forwarding deployment instructions.

Hosts: edit this file and increment VERSION in config.py for the next popup.
