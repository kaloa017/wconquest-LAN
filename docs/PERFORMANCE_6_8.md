# 6.8 map and late-game update

This release keeps the same database, territory IDs, accounts, ownership, research
history and in-progress projects. There is no save reset or schema migration.
Do not copy a development database over the Pi save. All automated gameplay tests
use disposable databases; the host's live save is not modified for testing.

## Map delivery and rendering

- Leaflet already used Canvas before this release. Replacing SVG alone would not
  have solved the game’s lag. Ownership now uses one viewport canvas instead of
  one Leaflet Rectangle/event/tooltip object per grid cell. Consecutive cells with
  the same owner/colour merge into horizontal runs. Individual cell boundaries
  appear from zoom 7; a selected cell is highlighted at any zoom. Every cell can
  still be selected and the server validates claims/combat normally.
  Army/building-only updates reuse the ownership index. Map DOM mutations also
  no longer trigger unrelated form/accessibility scans across the interface.
- Below zoom 6, a bundled simplified land overview replaces street tiles. Minor
  roads, settlement labels and small geographical details are absent. At zoom 6
  and above, the existing OpenStreetMap basemap returns at its native zoom detail.
  Labels cannot be independently styled inside raster tiles; this uses two
  deliberate detail levels rather than CSS blurring or filtering image tiles.
- Startup loads island names, centres and bounds, not every island polygon. Full
  geometry is divided into 49 geographical regions. Visible detailed regions load
  on demand; clicking an unloaded island first loads its region. The client keeps
  at most 12 detailed regions, coalesces duplicate requests and retries failures.
  Exact island geometry remains identical to the original data. Simplification
  applies only to the decorative world overview, never gameplay geography.
- Public regional files have content-hashed filenames, gzip sidecars, ETags and a
  one-year immutable cache lifetime, suitable for Cloudflare/CDN caching. The small
  manifest refreshes every five minutes. Terrain masks are also precompressed.
  Player state, CSRF data and ownership deltas stay uncached (`no-store`). Do not
  configure a blanket Cache Everything rule for `/api/*`.
- Ownership stays separate from geographic shapes. The existing delta protocol
  is retained; warm server caches now update just changed rows instead of scanning
  the whole territory table for every small edit. Large changes use a full query
  to avoid excessive small IN queries. SQLite's primary key and existing owner
  indexes are retained. Committed gameplay writes remain immediate.
- Gameplay/ownership polling remains every 12 seconds; nonessential online,
  announcement, shared music and EVA refreshes run every 36 seconds. Income
  tooltip calculations refresh once per minute. Hidden tabs retain existing pause
  behaviour. There are no extra background game workers on the Pi.

The choice to retain Leaflet avoids a map-engine migration during a live save's
deployment. MapLibre/WebGL remains an option if measured on-device frame time
still warrants it; it is not claimed to be benchmarked or implemented here.
References: [Leaflet Canvas](https://leafletjs.com/reference.html#canvas),
[MapLibre data guidance](https://maplibre.org/maplibre-gl-js/docs/guides/large-data/),
[HTTP compression](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Compression).

## Reproducible measurements and limits

Run `node tools/benchmark_map.cjs` after `npm ci`. A synthetic 30,000-cell map
with five countries reduces ownership layer objects from 30,000 to one canvas.
Its low-zoom plan merges into 1,000 runs; the example viewport draws 171 runs.
Initial static geography transfers fall from 1,225,027 bytes (previous compressed
islands plus raw mask) to approximately 371,081 compressed bytes, about 70% less.
Detailed regions are additional when needed; the largest gzipped region is about
131 KB. Previously cached data may make a warm load cheaper in either version.

The script also reports Node planning time and illustrative SVG DOM creation
time, which vary by machine. These are not browser FPS, a direct comparison of
the old Canvas renderer, a Pi throughput benchmark or an end-to-end latency test.
No promise of a particular frame rate or player capacity is made. Automated DOM
checks cover startup, Canvas selection, mobile tile actions and query filtering.
Actual-device pan/zoom smoothness should be checked on a phone and the Pi server.

Regenerate map assets after changing trusted geography:

```sh
python tools/build_map_chunks.py
python tools/check_release.py
```

Keep old content-addressed map files during deployed cache lifetimes so browsers
with an older manifest can still fetch their referenced regions.

## Chat and sharing

Administrators can edit **Moderation → Chat word filter**. Supply up to 200 literal
words/phrases, one per line, or toggle filtering off. An empty list blocks nothing.
The filter covers global/faction chat, private trade discussions, host-posted chat
and host edits. Matching ignores case, Unicode width differences and invisible
format separators, using word boundaries to avoid matching unrelated substrings.
This is a literal filter, not a promise to detect every spelling/leet variation.
Existing chat history is retained; old messages are not retroactively rewritten.
The setting lives in the existing save's game_settings table.

Public HTML now includes Open Graph and Twitter-card metadata and a bundled
1200×630 PNG preview. Discord and other compatible services can embed the game
link without a login. `PUBLIC_HOST` from the Pi installer provides its canonical
hostname; optional `PUBLIC_URL` overrides the full public address. Platforms may
cache previous previews. No external link content is fetched by the game server.

## Late-game progression

The tree grows from 43 to **123 technologies**: 80 new focuses across economy,
industry, military, naval/aviation and space, in four eras. Existing nodes, prices,
completed keys and active research are retained. New focuses cost 100,000,
5,000,000, 250,000,000 and 5,000,000,000 money, with laboratory-adjusted research
times. Search, availability and era filters make the tree manageable.

Specializations affect actual production, claim prices, attack/defense, casualties,
voyage costs, research speed, orbital production, planetary mining, cargo capacity
and expedition time. Related levels add their bonuses. Production is settled at
the old rate before completion grants a new economic effect.

Returning from Europa now leads to Titan, Enceladus and Neptune Orbit. The existing
planetary progress and mines remain intact. Returning with valuable cargo is the
tradeoff against higher travel investment. After the original megaproject chain,
Antimatter Forge, Quantum Trade Relay and Interstellar Colony Fleet add long-term
construction goals gated by advanced research. Existing megaproject levels stay
unchanged; each new project also has five levels.

## Updating the Pi after publishing this release

Stop the old Windows server if it is still running an independent copy of the
world. On the Pi, once this release has been committed and pushed:

```sh
sudo systemctl start wconquest-backup.service
sudo systemctl stop wconquest
sudo git -C /opt/wconquest pull --ff-only
sudo systemctl start wconquest
/opt/wconquest/.venv/bin/python /opt/wconquest/tools/pi_healthcheck.py --tunnel
```

If Git reports an error, stop and resolve it before restarting with mixed code.
The tunnel service and `/var/lib/wconquest/game.db` remain in place. No new runtime
packages are needed. Reload browser assets after the update; HTML includes the
release version in CSS/JS URLs so older CDN copies do not mask the new code.
