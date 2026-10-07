# World Conquest — Deployment & Persistence Guide

## Why progress resets

The game uses **SQLite** stored as a file (`game.db`). On free hosting platforms
like Render, the filesystem is **ephemeral** — it wipes on every redeploy or
server restart. You need to persist the file explicitly.

---

## Fix: Persistent disk on Render (recommended)

1. In your Render service → go to **Disks** → Add Disk
   - Mount path: `/data`
   - Size: 1 GB (free tier allows 1 GB)
2. Set env var: `DB_PATH=/data/game.db`
3. The game will now load and save from that disk across restarts.

## Fix: Local / self-hosted

If running locally, `game.db` saves in the same folder as `app.py`. Progress
persists automatically across restarts — nothing to configure.

---

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `DB_PATH` | `./game.db` | Path to SQLite file — point to a persistent disk |
| `SECRET_KEY` | built-in | Change to a long random string in production |
| `PORT` | `5000` | Set automatically by Render |

### For Render: add to your start command
```
web: python app.py
```

### Update app.py port for Render
At the bottom of `app.py`, change:
```python
app.run(debug=True, host='0.0.0.0', port=5000)
```
to:
```python
app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
```

---

## Requirements

```
flask>=3.0
requests  # optional, not currently used (geolocation uses stdlib urllib)
```

`requirements.txt`:
```
flask
```

---

## Admin: Download DB Backup

While logged in as admin, visit:
```
/api/admin/export_db
```
This downloads a `.sql` dump of the entire database you can keep as a backup.

---

## What Changed (summary)

### Persistence
- `DB_PATH` now reads from environment variable

### Guest / Spectator Mode
- Visitors can click "Watch Map Without Logging In" on the login screen
- They see the live map, leaderboard, and territory info
- They appear in the Online widget as `🇳🇴 Guest` (flag from their IP)
- Trying to take any action (claim, attack, etc.) prompts them to log in

### Economy Rebalance
| Thing | Before | After |
|---|---|---|
| Starting money | 100 | 200 |
| Starting food/wood/metal | 50 | 100 |
| Starting oil | 10 | 25 |
| Troop cost | 10💰 | 8💰 (6 with gunpowder) |
| Boat cost | 1000💰 | 800💰 |
| Plane cost | 1000💰 | 1200💰 |
| Plains yield | 6/min | 9/min |
| Forest yield | 8/min | 12/min |
| Mountains yield | 6/min | 9/min |
| Desert yield | 4/min | 7/min |
| City yield | 15/min | 18/min |
| Oil yield | 10/min | 14/min |
| Sell: food | 1💰 | 2💰 |
| Sell: wood | 2💰 | 4💰 |
| Sell: metal | 3💰 | 6💰 |
| Sell: oil | 5💰 | 10💰 |
| Claim cost | 30💰 flat | 25→40→80→150→400→1200 (tiered) |
| Offline cap | 60 min | 120 min |


---

## v4 changes

### Map
- Tiles now come from **OpenStreetMap** (no API key). A CSS filter gives it the dark look. OSM's tile policy is fine for a small hobby
  game; if traffic grows, change the URL in `initMap()` to another free/self-hosted tile server.

### Combat (rewritten)
- **One national army** (`users.army`) attacks and defends for the whole realm. Capacity = 60 + 30 per tile + Barracks (+25% Logistics).
- Defense on a tile = your army shared across your territories (`army / tiles^0.55`) + 3 militia, times home-ground, terrain, Fortress and Castle Walls.
- Attack modifiers: research, **weather**, **morale** (wins raise it, losses lower it), world events, faction unity. Both sides roll +-8% luck.
- **Weather** is computed from the 10-minute time slot + region, in JS on each client and in Python on the server (same formula,
  checked identical), so there is no polling, no server load, and it cannot be spoofed.
- Without Espionage you only see a +-30% estimate of enemy defense.
- Each battle runs in one SQLite transaction, so double-clicks/races can no longer duplicate or lose troops.

### Boats & planes
- Port (needs Shipbuilding, coastal tile only): boats launch from ports to coastal targets, range 4 (+2 Navigation, +1 per port level above 1).
  Boats cost 250 money + 20 wood, carry 12 troops, 80% return after a win.
- Airport (needs Air Force, any tile): planes take off from airports within range 5 (+3 Blitzkrieg, +2 Jets, +1 per airport level above 1).
  Planes cost 700 money + 40 metal + 30 oil, carry 5 paratroopers, 70% return after a win.
- Coast info: the client already has the land polygons, so it reports which cells are water (`/api/water/report`) and the server
  caches the first report per cell. Admins can correct a cell with `/api/admin/set_water`.

### New content
8 buildings (3 levels each), 9 new techs, factions (shared chat, treasury, rally), global + faction chat, daily rewards with streaks,
14 achievements, random world events, and many new admin tools (events, multipliers, give resources/territory, mute, clear chat, disband factions).

### Upgrading an existing game.db
Nothing to do: `migrate_v4()` runs on startup, adds the new columns/tables and converts old per-tile garrisons into your national army.
Flask debug mode is now off by default; set `DEBUG=1` to enable it.
