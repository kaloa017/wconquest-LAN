# World Conquest LAN — v6.5.0

Persistent multiplayer strategy on a real-world grid: claim tiles, recruit armies,
build an economy, research technology, form factions and fight for territory.
Flask serves the game; SQLite stores accounts and saves. The browser uses Leaflet.

## Start on Windows or Linux

```sh
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py create-admin --username YourHostName
python app.py
```

Open http://localhost:5055. Other LAN players use the host's LAN address and port
5055. `app.py` runs Waitress, a production WSGI server. Raspberry Pi deployment
uses Gunicorn instead; see [Deployment](docs/DEPLOYMENT.md). No default password
or special username grants administrator access. Passwords need eight characters.

Before upgrading, stop the old server and back up its folder. A consistent SQLite
backup is automatically created in `backups/` before the current save migration. Keep it.
Read [Migration notes](docs/MIGRATIONS.md), especially faction fleets and recovery.
Do not run old and new servers against the same database.

## Changes included in this version

### Interface and everyday play

- Reworked the desktop and mobile layout, colours, spacing, buttons, forms and
  dialogs. The mobile bottom menu opens a scrollable sheet with a clear title,
  close button and drag-to-close handle; Map reliably returns to the map.
- Grouped navigation with emoji icons, descriptions and consistent Market/Stocks
  controls. Scroll arrows remain only on the main menu strip, with click/hold support.
- Territory purchase notifications and long claim prices wrap within the mobile
  viewport, including when the notification is visible.
- One Settings menu, reached by the gear at the top right. It contains saved music,
  map-colour and fleet-sharing preferences plus account/recovery controls.
- A centered status strip with Help, weather, morale and daily reward indicators.
  A 15-step beginner guide explains claiming, income, buildings, combat, transport,
  factions, country choices, wonders, stocks, chat, rewards and settings. Relevant
  steps have buttons to open their menu; Help reopens the guide at any time.
- Money and resource pills show actual server-calculated production per minute and
  per hour on hover or keyboard focus. On mobile, expand Resources and tap a pill.
  Values refresh during normal user polling; trades and one-off rewards are excluded.
- Chat collapses **inside the side-menu Chat tab**, next to the territory menus.
  The compact view shows the three newest messages. Expanding restores the full
  conversation, composer and existing admin chat tools. Global/faction previews
  stay separate, and expanding scrolls to the newest messages. There is no floating
  chat widget on the map.
- My country returns the map to your capital/owned land; Explore islands jumps to
  a random island. Country has a quick overview and suggestions for the next move.
- An Ideas button lets logged-in players submit feedback. It is saved privately
  to `ideas.txt` beside `game.db`; Host tools show the latest 64 KB. Ideas are limited
  to one accepted submission per minute per account, even when general throttles
  are unlimited; tune `IDEAS_COOLDOWN` near the top of `config.py`. Hosts can block/
  unblock ideas per player without banning gameplay. Neither ideas
  nor IP tracking are exposed to normal players.
- Editable `CHANGELOG.md` is shown once per player per version. Increment `VERSION`
  in `config.py` when publishing an update.

### Host tools, accounts and music

- Restored the earlier admin dashboard layout: Players, Announce, Tools, World,
  and Factions & Chat, with additional Host tools alongside it.
- Private client/peer IP tracking, per-user request totals, sortable top requesters
  and audit records. The panel shows LAN join URLs detected on the host.
- Ban/unban, kick, mute, edit resources, assign/delete tiles, force faction,
  reset players, recovery codes, chat management, ideas submission bans and existing world controls.
- Resource-reset controls in Players and Host tools clear all eight balances
  (including money) or a single chosen resource to **zero**, with confirmation and
  before/after audit entries. They keep units, territory, buildings, research,
  wonders and stocks; normal production continues.
- Hosts can grant/revoke a cosmetic Donator badge and set a displayed player rank.
  Donators can choose a supporter title. These never grant admin permissions,
  income bonuses or combat advantages; donations do not automatically assign ranks.
- The admin cheat menu requires action confirmation and records use in the audit
  log, with the requested fairness warnings.
- Request, login, chat and stock-trade throttles default to **unlimited**. In Host
  tools, 0 means unlimited; positive limits persist across restarts. Upgrade v7
  clears old finite throttle settings once. Gameplay rules such as religion's
  cooldown, stock fees/position limits and vehicle costs still apply.
- Salted passwords, CSRF checks, session revocation and single-use account recovery.
  Players receive a recovery code at signup; admins can issue expiring reset codes.
- One validated MP3 (maximum 15 MB), replace/remove controls, and each player's
  saved mute/volume preferences. Removing it stops clients at their next sync.

### Geography, progression and economy

- Server-authoritative land checks use bundled Natural Earth 1:10m land and minor
  islands rather than browser pixels. This improves Iceland and other coastlines.
  Stale client-reported water flags are cleared; owned save tiles are preserved.
- Coastline checks recognise shorelines inside partially coastal grid cells,
  even when all neighbouring cells also touch land. Small island landing/Port
  controls retain the coastal flag through map updates.
- Tropical terrain produces food near the equator. The bundled Pacific-region
  dataset contains 3,268 distinct island polygons: 3,084 small islands remain single
  territories and 184 larger islands use the ordinary grid. Unclaimed islands have
  no persistent coloured outline or marker; they appear only on hover/selection.
  Owned island tiles display ownership like regular territories. An island overlapping a previously
  owned grid tile cannot be claimed again until that legacy ownership is released.
- Antarctica includes mainland land and bundled year-round ice-shelf polygons,
  with tundra for new Antarctic claims. Open ocean remains water. The current
  Web Mercator map/grid reaches about 85° south; the South Pole itself lies beyond
  the supported map projection.
- Eight maximum new factions with exclusive colour-wheel segments, personal RGB
  colours and saved faction-colour display preferences. Optional per-player sharing
  of boats and planes defaults to off and is enforced on the server.
- Cheaper tile claims, transports and landings; single-vehicle landing defaults
  with a quantity selector; base plane range increased to 40 cells.
- Six additional ideologies, eight religions with attack/secondary modifiers and
  a stored 24-hour religion-change cooldown displayed in the UI.
- Added Farm, Lumberyard, Refinery, Solar Farm and Radar Station. Building production
  and balance values live in `config.py` alongside costs, ranges and wonder effects.
- Every player can own each wonder once. Ordinary wonders apply to the **whole
  country**, require at least one owned tile, and have reduced bonuses. No landmark
  or selected-tile requirement remains.
- Scheduled country/faction stock exchange, buy/sell, portfolio and price-history
  chart. Prices use a bounded random walk with mean reversion and country activity/
  territory/event influences; fees, position limits and self-investment checks apply.

### Server, compatibility and deployment

- Changed-tile synchronization avoids assembling/resending the whole map on an
  unchanged poll; public map responses support gzip and cached geography downloads.
- Request-scoped transactions protect spending. Gameplay commits immediately;
  request counters and presence are batched every 30 seconds. History/log growth
  is bounded. The map's browser referrer policy was corrected for tile requests.
- Waitress replaces the development server on Windows; Gunicorn/systemd examples
  cover Raspberry Pi/Linux, with Apache/Nginx proxy and HTTPS instructions.
- Cloudflare Tunnel instructions make public hosting possible without router port
  forwarding. A tunnel is not automatically installed, authenticated or started.
- Automatic, idempotent save upgrades through schema v11 with a consistent pre-upgrade
  backup. Accounts, balances, ownership and prior unlocks are retained; see
  [Migration notes](docs/MIGRATIONS.md) for intentional balance/permission changes.

## Can it run on a Raspberry Pi 4 with 8 GB?

Yes, this architecture is a reasonable fit for a small server. Start with **10–30
simultaneous players**, around **5,000 owned tiles**, and one Gunicorn process with
four threads. This is a conservative planning estimate, not a measured Pi capacity
or performance guarantee. Combat bursts, large empires, mobile browsers and slow
storage may reduce capacity. Measure before inviting more players.

Budget roughly **150–500 MB RAM** for the Python service once geography is loaded,
plus the OS/proxy/tunnel; this is an estimate to verify on your device. CPU should
be intermittent for a small game, with peaks during map changes, geography load
and scheduled collection. A 30-player unchanged map poll load is about 2.5 polls/s
at the default 12-second polling interval; user/chat/presence calls add load.

Use 64-bit Raspberry Pi OS, a cooled Pi, Ethernet and an SSD if available. Start
with `--workers 1 --threads 4`; SQLite permits one writer at a time. More workers
duplicate caches and per-process request-limit buckets and usually do not help.
Do not use Gunicorn `--preload`: the scheduler starts per process at import time.
Stock updates run every five minutes. `SAVE_INTERVAL=30` batches counters; raising
it reduces writes but delays online presence and can lose that interval of counters
on a crash. Game purchases are never delayed. WAL and batched counters reduce SD
card churn, but gameplay still writes; use a good card or preferably an SSD. Keep
regular backups on another device. Monitor RSS, CPU, disk latency and response
timings; public API replies expose `Server-Timing`.

## Hosting without port forwarding

[Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/) makes outbound
connections from the host, so no incoming router port is required, including
behind CGNAT. The deployment guide covers a stable named tunnel and temporary
quick tunnels. A stable public hostname requires your Cloudflare account/domain
and installing a tunnel connector; the repository cannot create those credentials
for you. The game remains private until you deliberately start the tunnel.

## Audit fixes in 6.3.4

- Escape host announcements and player names wherever they render as HTML.
- Vehicle loans transfer only the lender's personally owned boats/planes. Optional
  faction sharing never permits lending or returning another member's fleet.
- Reject malformed text, toggle and non-finite settings values with a useful error.
  Explicit SECRET_KEY values must contain at least 32 characters.
- Preserve faction troops on admin disband, avoid duplicate armies after a round
  reset, and make assigning a player's existing faction a safe no-op.
- Refresh distributed defenses on every affected faction territory when ownership
  or membership changes. Explosions also affect dedicated island territories.
- Reset an expired winning round without requiring an online player. Poll win
  status again in the browser; refresh spectator presence while spectating.
- Avoid startup races when workers create the session key or load geography;
  use unique temporary music uploads and tolerate concurrent music removal.
- Discard late territory/chat responses after selection, channel or account changes.
  End expired login sessions cleanly and show connection/startup errors.
- Align tablet controls at 768px, add keyboard access and visible focus to controls,
  preserve recovery-code acknowledgement, and focus the active dialog. Bound chat
  elements and notification IDs during long sessions. Island capitals and EVA
  positions use their actual island coordinates.
- Batch stock faction reads: 67 to 4 SELECTs in a 64-country local benchmark.
  Deduplicate and bound optional spectator geolocation work.

See [Audit report](docs/AUDIT.md) for findings, tests, measurements and limitations.

## GitHub publication

The project is licensed under [MIT](LICENSE); copying and modifying it are allowed.
Third-party data/assets retain the terms in [NOTICE](NOTICE.md). Public source
excludes saves, IP/audit records, ideas, payment details, session keys, MP3s, EVA
artwork and tunnel credentials. Keep COMMUNITY.vipps_number blank when publishing.
Run `python tools/check_release.py` before committing or preparing a source archive;
run `python tools/check_release.py --archive` in an extracted source archive.
The check complements reviewing your own changes; it cannot recognize every secret.

GitHub Actions checks Windows/Linux with Python 3.11–3.14, dependencies, release
privacy/integrity, JavaScript syntax and regression tests. Node is a development
check dependency, not required to host the game. No separate build, linter or type
checker is configured. See [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md).
`.env.example` documents environment variables; the application does not load it
or `.env` automatically. Set variables in your shell/service before starting.

## Persistent worlds in 6.3.6

Victory detection, territory-based win thresholds, winner recording, countdowns
and automatic round resets have been removed completely. Claims and combat keep
the world running indefinitely; the Conqueror achievement and combat victories
still work. Historical winner settings in older saves are ignored. The status
API remains available for leader/event information and always reports playing.
Only the existing explicit admin reset can start a fresh world. Saves need no
additional migration. Restart the server and reload clients after updating.

See [Cloudflare alternatives](docs/DEPLOYMENT.md#alternatives-to-cloudflare-without-port-forwarding)
for Tailscale Funnel, ngrok, playit.gg and running on a public VPS.
Combat against another player requires an active faction war. Join or create a
faction, then have its leader declare war in the Faction menu. Land, naval and air
attacks follow this rule; rockets and nukes also check every country in their blast
area. A strike is rejected before spending weapons if it would damage an ally or
a country outside the war. Neutral land does not need a declaration. Ongoing
offensives stop and return surviving troops when peace is agreed.


## Planned battles and air assaults (6.5)

Open **Operations → Plan an offensive**, select a friendly starting tile and choose
adjacent targets on the map. Enter a troop count and tactic, then start the route.
Survivors advance automatically after each victory. The server checks war status,
ownership, fallout and competing battles again before each advance. Organization,
food and a friendly supply source determine whether an offensive can keep going.
You can change tactics or retreat; defenders can hold, entrench or counterattack.
The attacker sees the remaining route; the current defender sees only the current
battle. Only those two players see private map markers or battle data.

For an air assault, select a reachable tile and use its button or press **F**.
The shortcut does nothing while typing, viewing a dialog or planning a route.
War is required against player-owned territory; neutral land stays accessible.

## Space tycoon (6.5)

After the Manhattan Project, research **Spaceflight** (250,000,000 base money), then
build your own **Space Agency** (50,000,000 money plus steel, uranium and gems).
The **Space** menu introduces a persistent first-unlock tutorial. Buy communications
satellites, orbital tourism and laboratory contracts for passive money/resources.
Contract quantities have no arbitrary purchase cap; costs and production are shown
before purchase and configured in `config.py`.

Explore the Moon, Mars and Europa. Both travel legs are charged at departure;
returning is always prepaid. Every player gets an identical **personal 6 × 6 map**,
so nobody can monopolize a planet. Build on the landing tile, expand to adjacent
tiles and upgrade mines through three tiers. Mines persist, but produce cargo only
while your expedition is on the surface. Cargo has a 10,000-unit capacity. On return,
steel, uranium and gems arrive on Earth and iridium is automatically sold. Delivery
is atomic and occurs once. Returning from each planet unlocks the next, with higher
agency-level requirements and greater mineral yields.

Orbital contracts continue earning during travel. Accumulation is bounded to the
existing two-hour offline window; server downtime never triggers unlimited catch-up.
Space figures are starting balance choices, configurable under `SPACE_*` in
`config.py`; they have not been validated in a long-running multiplayer economy.
The existing Space Program and Dyson Sphere wonders remain separate country bonuses.

## Update announcements and purchase quantities (6.5)

The changelog popup shows releases newer than the player's stored last-seen version,
excluding future releases. New players see the current release only. The popup
opens at the top and remembers the version actually acknowledged. Edit `CHANGELOG.md`
and increment `VERSION` in `config.py` when releasing another update.

Troops, boats, planes, rockets, warheads, shares and orbital contracts accept bulk
quantities limited by affordability (or owned stock when selling), rather than an
arbitrary per-purchase maximum. Safe integer precision limits remain. Building tiers,
unique wonders, travel gates, cargo capacity and casino bet limits are gameplay
rules and remain in place. See `docs/MIGRATIONS.md` for the save upgrade notes.


## Economy and community additions (6.4)

Money buildings now produce 30/min (Market), 45/min (Solar Farm), 180/min (Nuclear
Plant), 120/min (Bank) and 300/min (Shopping Center), per level before modifiers.
Banks can advertise fixed total interest and repayment terms. Borrowers review the
full amount due; lenders approve before funds transfer. Repayments transfer existing
money, and overdue loans collect available money without compounding interest.

Players can send gifts or propose two-sided exchanges of resources, personally
owned vehicles, weapons and territory with its building. Exchanges recheck both
parties' stock when accepted. Casino play uses in-game money only and retains its
published odds and per-level bet limits. Rockets clear a two-cell radius without
adding new fallout; nuclear fallout lasts 72 hours. Strikes must respect active
wars and cannot damage other peaceful countries or allies.

Admins can appoint moderators. Moderators can mute/timeout users and use an audited,
three-confirmation territory-transfer flow. The live **Game editor** lets admins
add or edit buildings, wonders, ideologies and religions without opening files.
Supporter, Patron, Champion and Legend tiers offer cosmetic username colours,
fonts and optional RGB animation; they grant no gameplay or moderation powers.

## Verification

Run `python -m unittest discover -s tests -v`, then `node tests/client_audit.cjs`.
The tests use disposable saves and disable the scheduler. This update adds route,
privacy, bulk-purchase, migration, cargo-capacity and concurrent-delivery tests.
There is no configured bundler, linter or type checker; browser scripts can be
checked with `node --check`.

An optional offline browser check is provided in `tools/make_ui_fixtures.py` and
`tools/check_progression_ui.cjs`. It needs Node with Playwright and Chrome (override
`CHROME_PATH` if necessary). It never launches or contacts the real game server:

```sh
python tools/make_ui_fixtures.py /path/to/preview/fixtures.json
node tools/check_progression_ui.cjs /path/to/preview/fixtures.json /path/to/preview/screenshots
```

It checks desktop, 768px tablet and 390px/320px phone layouts, the planner, hotkey,
private markers, space tutorial/countdown, existing menus and changelog scrolling.
The preview intercepts network requests; external background map tiles are omitted.
Real-device touch testing and a longer live economy playtest remain useful follow-ups.
# Notification inbox and moderation roles

Notifications stay in the top-right bell inbox until dismissed; new messages update
the unread count without covering the map or menus. Alliance responses and other
notification actions remain available inside the inbox.

Admins can grant Moderator (chat mute/unmute and gameplay timeout/clear only) or
Senior moderator (the same controls plus audited territory transfers). Neither role
can change ranks, economy settings, resources or game definitions. Existing moderators
retain Senior moderator permissions. Moderators cannot moderate peers, senior
moderators or admins; senior moderators may moderate the weaker role. All actions
still require a reason and are recorded in the audit log.
# Military travel costs

Each land offensive departure costs 0.10 money and 0.01 oil per troop. Queued
advances cost 25% more, using the surviving troop count and rounding up each
resource. For example, 1,000 troops cost 100 money and 10 oil on departure,
then 125 money and 13 oil per queued advance. If funds run out,
the queued advance stops, captured land stays yours, and survivors return to their
original army pool. Travel already completed is not refunded.

Air assaults cost 20 money and 1 oil per plane per tile of flight distance;
two planes flying ten tiles cost 400 money and 20 oil. You must have both before
takeoff. A valid attack spends travel resources even if the battle is lost.
These costs come from the commanding player's own balance, including when using
shared armies or planes. Prices are in `MILITARY_TRAVEL_COST` in `config.py`.
The queued land surcharge is `QUEUED_ADVANCE_COST_MULTIPLIER`; it never affects planes.
No save migration is needed.
