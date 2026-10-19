# Permanent hosting on Raspberry Pi 5 (8 GB)

The Pi runs **both the game and the tunnel**. Your Windows computer can be turned
off after moving the save. This recipe uses 64-bit Raspberry Pi OS, one Waitress
process with four threads, SQLite on persistent storage and a remotely managed
Cloudflare Tunnel. The hostname stays the same across reboots. It needs your own
domain on Cloudflare and a tunnel token. It does not need router port forwarding,
Apache, Nginx, a public game port or a local HTTPS certificate.

Use Ethernet, active cooling and a suitable power supply for continuous operation.
An SSD is preferable for the database and backups. 8 GB is enough to start with
this configuration; player capacity still depends on save size, CPU, disk and
network load and has not been benchmarked on a Pi. Keep Raspberry Pi OS and
cloudflared updated. Hardware guidance: [Raspberry Pi documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).

## 1. Transfer the current project

On Windows, in the project folder:

```powershell
python tools/package_pi.py --output "$env:USERPROFILE\Desktop\wconquest-pi.zip"
scp "$env:USERPROFILE\Desktop\wconquest-pi.zip" pi@raspberrypi.local:~/
```

Replace `pi@raspberrypi.local` with your Pi username/address. This archive includes
the current local fixes, even before committing, and excludes your save, secrets,
media, node_modules and virtual environment. Node.js/npm are only for developer
tests and are not needed to run the game. The archive command refuses to overwrite
an existing ZIP; choose a new filename for subsequent releases.

On the Pi:

```sh
sudo apt update
sudo apt install unzip
sudo mkdir -p /opt/wconquest
sudo unzip ~/wconquest-pi.zip -d /opt/wconquest
```

## 2. Move the existing world before starting the Pi server

To preserve the world, stop your Windows game server, then create a consistent
snapshot in the project folder:

```powershell
python manage.py backup --output "$env:USERPROFILE\Desktop\wconquest-world.db"
scp "$env:USERPROFILE\Desktop\wconquest-world.db" pi@raspberrypi.local:~/
```

On the Pi, before running the installer:

```sh
sudo install -d -m 0700 /var/lib/wconquest
sudo install -m 0600 ~/wconquest-world.db /var/lib/wconquest/game.db
```

If you skip this step the installer creates a new empty world. For a new world,
create your administrator after installation:

```sh
sudo -u wconquest env DB_PATH=/var/lib/wconquest/game.db \
  /opt/wconquest/.venv/bin/python /opt/wconquest/manage.py create-admin --username YourHostName
```

Copy `.session-secret` separately into `/var/lib/wconquest/.session-secret` if you
want existing login sessions preserved; otherwise a fresh secret is generated and
players log in again. If you previously set `SECRET_KEY` externally, preserve that
value in `/etc/wconquest/game.env` instead. Authenticator secrets and player recovery
codes are stored in the database and remain intact either way. Copy shared music
into `/var/lib/wconquest/media/world.mp3`, ideas into `/var/lib/wconquest/ideas.txt`,
and optional EVA images into `/opt/wconquest/static/eva/`. These files are private
and intentionally absent from the code ZIP. The installer sets state ownership.
If transferring more private state after installation, reset ownership with:

```sh
sudo chown -R wconquest:wconquest /var/lib/wconquest
sudo chmod 0700 /var/lib/wconquest
```

Do not run the old Windows world and the new Pi world in parallel: they become
independent saves and cannot be merged automatically. Keep the original intact
until the Pi world is verified. See [migration notes](MIGRATIONS.md).

## 3. Install boot services

Use your actual hostname in place of `game.example.com`:

```sh
cd /opt/wconquest
sudo bash deploy/raspberry-pi/install.sh game.example.com
```

The installer requires ARM64 Linux/systemd, installs Python and cloudflared from
[Cloudflare's signed package repository](https://pkg.cloudflare.com/), creates a
dedicated `wconquest` account and starts the game and daily backup timer. It keeps
an existing `/etc/wconquest/game.env` and database. On later runs, it backs up and
stops an active game before updating the Python environment. Review an existing
environment file if changing hostname. Code stays in `/opt/wconquest`, state in
`/var/lib/wconquest`, and completed backups in `/var/backups/wconquest`.

The game binds **127.0.0.1:5055**, so players connect using the HTTPS hostname,
including players on your LAN. Cookies are HTTPS-only. Loopback is the only
trusted proxy; `PROXY_MODE=cloudflare` preserves real player addresses. The public
host allowlist includes the supplied hostname and loopback health-check names.
One process keeps the scheduler and in-memory state together. Do not add workers
or launch a second `python app.py` against this save.

## 4. Connect a permanent named tunnel

Follow [Cloudflare's tunnel setup](https://developers.cloudflare.com/tunnel/get-started/):

1. Add your domain to Cloudflare and create a remotely managed Cloudflare Tunnel.
2. Add a published application/public hostname such as `game.example.com`.
   Set the service type to **HTTP** and the URL to **127.0.0.1:5055**. Preserve the
   incoming hostname; leave HTTP Host Header overrides empty. Enable redirecting
   public HTTP to HTTPS in the Cloudflare zone. Do not add a Cache Everything rule
   for the game or cache `/api/*`; authentication and state must reach the origin.
3. Copy only the connector token from the dashboard's Linux install command.
   Do **not** run its separate `cloudflared service install` command: this project
   supplies its own service. Do not run a duplicate connector service on the Pi.
4. On the Pi run:

```sh
sudo bash /opt/wconquest/deploy/raspberry-pi/set-tunnel-token.sh
```

Paste the token at the hidden prompt. It is stored root-only, passed through
systemd credentials and never embedded in the process command, source code or
shell history. This uses cloudflared's [`--token-file`](https://developers.cloudflare.com/tunnel/reference/run-parameters/#token-file)
support (2025.4.0 or newer). Rotating the token uses the same command.
The tunnel starts now and after every reboot; both services restart after crashes.
cloudflared reconnects when the network returns. Cloudflare's free random quick
tunnel URLs are not used. The Pi must remain powered and connected.

## 5. Verify before sharing

```sh
sudo systemctl status wconquest wconquest-tunnel --no-pager
/opt/wconquest/.venv/bin/python /opt/wconquest/tools/pi_healthcheck.py --tunnel
sudo systemctl list-timers wconquest-backup.timer
sudo journalctl -u wconquest -u wconquest-tunnel -n 50 --no-pager
```

The health check tests game configuration on loopback and cloudflared's local
readiness endpoint. It does not prove DNS/public routing: visit your HTTPS hostname
from a phone using mobile data, log in, select unclaimed tiles, claim/build, trade
and check Host tools for the correct client IP. Reboot the Pi and repeat. An
internet outage is not a reason to restart a healthy game or roll back the save.

No inbound firewall ports are needed for the tunnel; preserve SSH access for
administration. Cloudflared needs outbound TCP/UDP 7844 to Cloudflare, DNS and
HTTPS for setup/updates; see [network requirements](https://developers.cloudflare.com/tunnel/configuration/#firewall-rules).
If UDP is blocked, cloudflared can use HTTP/2 over TCP. Backups and service logs
must stay private. Never publish your token or the private state directories.

## Backups, restore and maintenance

Daily backups run around 04:00 in the Pi's configured timezone, with up to 15
minutes of random delay, and catch up after a missed run. Keep the latest 14
completed backups. Each includes a verified SQLite snapshot, session-secret file
when present, music/media, ideas and optional EVA files. The backup tool does not
import the game, run migrations or start a second scheduler. Files/media are copied
separately from the database snapshot, so pause uploads during an exact full restore
point if needed. An externally supplied `SECRET_KEY` and the tunnel credential
are not included; store them separately. Copy backups to another device regularly.

```sh
sudo systemctl start wconquest-backup.service
sudo journalctl -u wconquest-backup -n 10 --no-pager
sudo ls -lt /var/backups/wconquest
```

For restore, stop `wconquest-tunnel` and `wconquest`, take a final backup, and move
the current `game.db`, `game.db-wal` and `game.db-shm` into a separate recovery
directory if present. Restore a completed backup's `game.db` into
`/var/lib/wconquest/game.db`; restore its `.session-secret`, media/ideas and EVA
assets to the paths above when needed. Never leave old WAL/SHM files beside a
restored database. Set state ownership to `wconquest:wconquest`, start the game,
check it locally, then start the tunnel. Restoring an older save loses later moves.

For updates, back up first, stop the game, replace public code from a new ZIP,
rerun the installer and check the logs/health check before continuing. Do not
overwrite the state directory or environment file. Update cloudflared through
apt and restart `wconquest-tunnel` afterward; its self-updater is disabled.

Troubleshooting:

- **502:** check `wconquest` logs, the hostname's origin URL and local health check.
- **Tunnel disconnected / 1033:** check `wconquest-tunnel` logs, token and outbound
  networking. Re-run the token script after rotating credentials.
- **400 host error:** add your real hostname to `ALLOWED_HOSTS` in
  `/etc/wconquest/game.env`, then restart `wconquest`.
- **403 origin error or login loop:** retain secure cookies and loopback proxy
  settings; use the HTTPS hostname and remove incorrect Host Header overrides.
- **No space:** check `df -h` and backup sizes. Backups on the same drive do not
  protect against drive failure. Retention removes only this tool's completed
  backup folders, not migration backups or unrelated files.

These files prepare the deployment; they do not provision your Cloudflare account
or install anything on a Pi from your Windows computer. Pi hardware uptime and
public routing must be verified on the actual device.
