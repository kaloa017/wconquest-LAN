# Capitals and major cities — 6.13

The existing map, ownership, normal building slot, faction army pool, combat and
offline production limits remain in use. This update deliberately strengthens
strategic locations; it is not an ownership or account reset.

## Bonuses

| Location | Local production | Local recruitment | Local defense |
|---|---|---|---|
| Ordinary territory | 1× | 1× | 1× |
| Major-city tile | 1.5× | 1.5× | 1.25× |
| Player capital | 2× | 2× | 1.75× |
| Capital on a city tile | 3× | 3× | 2.1875× |

A capital adds 12 base troops/min before its recruitment multiplier: 24/min on
ordinary land or 36/min on a city. Barracks and capital military buildings add
their recruitment to this base. Research, terrain, religion and other existing
combat/production effects still apply. Bonuses are local, not empire-wide.
City benefits persist with geography; ownership does not rename or erase cities.
Multiple cities in one tile grant one city bonus. Defense benefits apply to owned
territories; the existing wilderness encounter is unchanged.

## Additional capital buildings

Each capital has six independent district slots, alongside the existing normal
building slot. Each district can reach level 10. Its next cost is its base cost
multiplied by `2.3 ** current_level`, rounded per resource. There is no waiting
timer or new currency; existing resource affordability is enforced atomically.

| Building | Effect per level before local multipliers |
|---|---|
| Capital civic centre | +15% capital production, additive across its levels |
| Sovereign treasury | +1,800 money/min |
| Grand military academy | +60 troops/min |
| Strategic industrial district | +180 metal and +60 steel/min |
| National command bunker | +12% local district defense |
| Capital guard headquarters | +30 troops/min and +6% local district defense |

Command/guard defense adds together, then multiplies with city/capital and other
defenses. Civic production multiplies city/capital production, including district
resource outputs. The income panel and actual settlement use the same functions.
Upgrades settle at old rates before charging; insufficient funds roll back.

Districts are attached to a tile. Moving the capital leaves them dormant; they
reactivate if that owned tile becomes a capital again. The existing 24-hour move
cooldown remains. Capture retains districts for the new owner, initially dormant
because capturing land does not automatically make it their capital. Abandonment,
account deletion releasing land, nuclear clearing and territory deletion remove
districts. Fallout still blocks living/claiming under existing game rules.

## Saved registry and provenance

`data/major-cities.json` and `data/major-cities.csv` save **1,766 cities** on
**1,734 playable tiles**. Definition: Natural Earth `POP_MAX >= 250000`, plus
places flagged as national capitals. Estimates and classifications are from the
dataset, not current census values or a claim to include every settlement.

Source: [Natural Earth populated places](https://github.com/nvkelso/natural-earth-vector/blob/789c9904087846cc3361302857aa2e76b0ae71ff/geojson/ne_10m_populated_places_simple.geojson),
public domain. The pinned source URL, SHA-256 and selection definition are stored
in the JSON header. Rebuild with `python tools/build_cities.py` or supply a local
source with `--source`. Rebuilding reads geography and writes registry files;
it does not open the save. This version uses GRID=0.18.

Each record includes stable source ID, city/country, estimated population,
national-capital flag, source latitude/longitude, tile key, playable tile centre
and relocation flag. Offshore/coastal points first use supported island geometry
or otherwise the closest playable land centre within six grid cells (distance
weighted for latitude). Relocation is explicit, never a change to geography.

The public directory supports city/country/tile search, owned-tile filtering and
map navigation. Downloads: `/api/cities` JSON and `/api/cities.csv` CSV. Static
records contain no account, IP or credential data. Cities load once into the
browser and use cached HTTP responses; searching does not issue requests.
Canvas markers are bounded to 40 at world zoom or 120 when closer, within the
viewport, one per tile. Hover details and selected tile panels identify cities.

## Verification

Isolated tests cover registry validity and land mapping, duplicate-city stacking,
local production/recruitment rates versus collection, district costs and caps,
permissions, concurrent spending, moving/capturing capitals and cleanup triggers.
Live save changes are not needed to test this release. The browser demo uses its
own copied save and a disposable admin capital in Mexico City.

Verification for this release: 218 Python tests and 33 UI tests passed, plus
JavaScript/Python syntax, public-release and whitespace checks. The final
no-capital/dormant-detail changes also passed the targeted eight mechanics tests.
Browser checks verified academy construction and spending, city search, and
jumping to Oslo tile 332,59. The original game.db SHA-256 stayed unchanged.
These checks do not measure sustained Pi performance or player balance at scale.
