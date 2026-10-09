# 6.5.0 — planned offensives and space tycoon

- Added configurable money and oil travel costs for land departures, queued advances
  and distance-based plane attacks. Routes stop safely when the next step is unaffordable.

- Moved persistent notifications into a bell inbox instead of automatic popups.
- Added a moderation-only role; existing moderators retain senior permissions.

- Added private battle lines and progress markers visible only to the attacker and
  current defender. Faction mates, other players and spectators receive no battle data.
- Added map-based offensive planning: queue adjacent targets and carry surviving
  troops forward automatically. Recheck ownership, war and availability at each step.
- Fixed survivor refunds after faction changes and player resets; active battles
  remain visible regardless of recent history.
- Added F as the air-assault shortcut; typing, dialogs and held keys do not fire it.
- Added late-game Spaceflight, Space Agencies and three orbital income businesses.
- Explore personal 6 × 6 maps on the Moon, Mars and Europa, with persistent mines,
  valuable iridium, cargo holds, timed travel and prepaid return journeys.
- Added a persistent first-unlock space tutorial and an accessible Space menu.
- Changelog announcements now contain only unseen published versions, open at the
  top and acknowledge the version actually shown. First-time players see the current release.
- Audited purchase quantities, added bulk rockets/warheads, and rejected invalid
  unit amounts. Purchases are limited by affordability and safe numeric precision.
- Improved command cards, forms, readable numbers and touch controls. Nuclear blasts
  now use the requested 5–20-cell range; war and collateral protections remain.
- Save migrations 14–15 add queued orders and space tables without resetting Earth,
  accounts or assets. A consistent pre-upgrade backup is created before migration.

# 6.4.1 — war required before combat

- Require an active faction war before land, naval or air attacks on another player.
- Validate every country affected by rocket/nuclear blasts before spending weapons
  or damaging territory; peaceful bystanders and allies are protected.
- Stop ongoing offensives when their war ends; return surviving committed troops.
- Update the faction help text. Neutral territory remains available without war.
- Display balances, prices, population and troop counts with comma separators.
- No save migration or reset.

# 6.4.0 — economy and persistent battles

- Added stronger market, solar, nuclear, bank and shopping-center income.
- Added player bank offers, approved loans, fixed interest and repayment handling.
- Added live admin editing for buildings, wonders, ideologies and religions.
- Added persistent battles with organization, tactics, defensive stances and supply.
- Added rockets, 72-hour fallout, gifts/exchanges, casino play, moderator roles,
  account timeouts and confirmed territory transfers.
- Added cosmetic supporter tiers and username customization.

# 6.3.6 — persistent worlds

- Removed territory-based victory detection, winner recording, all automatic reset
  paths, win-status polling, victory overlays and countdown controls/styles.
- Existing winner records are ignored. The leader/event status API and explicit
  admin reset remain; combat victories and achievements are unchanged.
- Added regressions for claims beyond the former threshold and stale winner saves.
- Documented public-hosting alternatives to Cloudflare without port forwarding.
- No additional save migration or player-data reset.

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
