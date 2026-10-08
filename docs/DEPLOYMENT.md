# Production hosting on Raspberry Pi OS

Use Raspberry Pi OS **64-bit**, preferably an SSD and Ethernet. Substitute your
own hostname for `game.example.com`. Commands below assume `/opt/wconquest`,
dedicated user `wconquest`, and save directory `/var/lib/wconquest`.

## Install

```sh
sudo apt update
sudo apt install python3 python3-venv git apache2 certbot python3-certbot-apache
sudo useradd --system --home /var/lib/wconquest --create-home wconquest
sudo mkdir -p /opt/wconquest
# Copy the project to /opt/wconquest, excluding your old .venv and test databases.
sudo python3 -m venv /opt/wconquest/.venv
sudo /opt/wconquest/.venv/bin/pip install -r /opt/wconquest/requirements.txt
sudo chown -R wconquest:wconquest /var/lib/wconquest
cd /opt/wconquest
sudo -u wconquest env DB_PATH=/var/lib/wconquest/game.db \
  /opt/wconquest/.venv/bin/python manage.py create-admin --username YourHostName
```

For an existing save, copy its database to `/var/lib/wconquest/game.db` **before**
running the host command. The first import backs up and migrates it. Copy media and
EVA images too. Make code/static readable by the service; keep environment secrets
and database outside the publicly served directory.

## Gunicorn and systemd

Create `/etc/wconquest.env`, owned by root with mode `600`:

```ini
DB_PATH=/var/lib/wconquest/game.db
COOKIE_SECURE=1
TRUSTED_PROXIES=127.0.0.1/32,::1/128
PROXY_HOPS=1
# Optional SECRET_KEY: use a long random value, never the old built-in secret.
# Otherwise .session-secret is generated in /var/lib/wconquest and reused.
```

Create `/etc/systemd/system/wconquest.service`:

```ini
[Unit]
Description=World Conquest
After=network-online.target
Wants=network-online.target

[Service]
User=wconquest
Group=wconquest
WorkingDirectory=/opt/wconquest
EnvironmentFile=/etc/wconquest.env
ExecStart=/opt/wconquest/.venv/bin/gunicorn --bind 127.0.0.1:5000 --workers 1 --threads 4 --timeout 60 --forwarded-allow-ips=127.0.0.1,::1 app:app
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/wconquest

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now wconquest
sudo systemctl status wconquest
sudo journalctl -u wconquest -f
```

Do not use `--preload`: background schedulers must start after worker creation.
Start with one worker. SQLite leases prevent duplicated stock ticks, but caches,
rate-limit buckets and scheduler threads are per worker. Flask's development
server is not the production entry point. Waitress is the Windows alternative.
For plain HTTP LAN testing set `COOKIE_SECURE=0`; use `1` for HTTPS production.

## Apache reverse proxy

```sh
sudo a2enmod proxy proxy_http headers ssl deflate
```

Create `/etc/apache2/sites-available/wconquest.conf`:

```apache
<VirtualHost *:80>
  ServerName game.example.com
  ProxyPreserveHost On
  # Overwrite client-supplied forwarding headers. mod_proxy appends the peer IP.
  RequestHeader unset X-Forwarded-For
  RequestHeader set X-Forwarded-Proto "http"
  ProxyPass /static/ !
  Alias /static/ /opt/wconquest/static/
  <Directory /opt/wconquest/static/>
    Require all granted
    Options -Indexes
  </Directory>
  ProxyPass / http://127.0.0.1:5000/
  ProxyPassReverse / http://127.0.0.1:5000/
  AddOutputFilterByType DEFLATE application/javascript text/css text/html
  ErrorLog ${APACHE_LOG_DIR}/wconquest-error.log
  CustomLog ${APACHE_LOG_DIR}/wconquest-access.log combined
</VirtualHost>
```

```sh
sudo a2ensite wconquest
sudo apachectl configtest
sudo systemctl reload apache2
sudo certbot --apache -d game.example.com
sudo certbot renew --dry-run
```

In Certbot's generated **HTTPS** vhost change `X-Forwarded-Proto` to `"https"`.
Redirect HTTP to HTTPS. DNS must point at your public address; HTTP-01 certificate
issuance requires incoming port 80. If you cannot forward ports, use the tunnel
below instead. The current game uses HTTP polling, **no WebSockets**. If you later
add WebSockets, Apache 2.4.47+ supports protocol upgrades through `mod_proxy_http`;
configure a dedicated upgraded endpoint rather than changing all API polling.

## Nginx alternative

Install `nginx certbot python3-certbot-nginx` instead of Apache. Create a server
block under `/etc/nginx/sites-available/wconquest` and enable its symlink:

```nginx
server {
  listen 80;
  server_name game.example.com;
  client_max_body_size 16m;
  gzip on;
  gzip_types text/css application/javascript;
  location /static/ {
    alias /opt/wconquest/static/;
    autoindex off;
  }
  location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

Run `sudo nginx -t`, reload Nginx, then
`sudo certbot --nginx -d game.example.com`. Do not run both proxies on the same port.
If adding WebSockets later, configure HTTP/1.1 and Upgrade/Connection headers only
for that endpoint. Large map JSON is already compressed by Flask.

## Correct private IP tracking

Only configured trusted proxy peers can supply forwarding headers. Direct clients
cannot spoof `X-Forwarded-For`. Keep Gunicorn bound to loopback and trust only
loopback for these examples. `PROXY_HOPS=1` means exactly one sanitized forwarder;
do not increase it without understanding the chain. An Apache/Nginx peer appears
as 127.0.0.1 under “Peer IP”; “Client IP” shows the public or LAN address.
Cloudflare Tunnel → Apache → Flask adds a different chain; the simpler direct
tunnel setup below avoids ambiguous header handling. Never trust all networks.
Test Host → request tracking from a second device and confirm both fields.

## No router port forwarding: Cloudflare Tunnel

Cloudflare Tunnel uses outbound connections, including behind CGNAT. The game
host must stay online; a tunnel does not provide game-server compute or backups.
Use the official [installation guide](https://developers.cloudflare.com/tunnel/get-started/).
Install `cloudflared` from Cloudflare's repository/package for your Pi's ARM64
architecture. Then choose one option:

### Temporary testing URL

```sh
cloudflared tunnel --url http://localhost:5000
```

It prints a random `trycloudflare.com` HTTPS URL. Share that URL with testers.
The URL changes between runs; [quick tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
have limitations and no uptime guarantee. Do not treat them as permanent hosting.
For quick tests keep Flask's real-client tracking on trusted headers only; verify
whether your connector supplies `CF-Connecting-IP` before relying on it.

### Permanent named tunnel

1. Add your domain to your Cloudflare account and follow the official named tunnel
   setup. Create a tunnel in the dashboard and install its connector on the Pi.
   Keep the connector token private; it is not a player recovery code.
2. Add a public hostname `game.example.com` with service
   `http://localhost:5000`. Connect directly to Gunicorn; Apache/Nginx is optional.
3. Add `PROXY_MODE=cloudflare` to `/etc/wconquest.env`; retain loopback-only trust,
   one hop and `COOKIE_SECURE=1`. The application uses Cloudflare's validated
   `CF-Connecting-IP` when the trusted local connector supplies it.
4. Install the connector's system service using the instructions generated by
   Cloudflare. Restart the game and connector, then open the HTTPS hostname from
   outside your Wi-Fi. Check Host → request tracking and try login/music/map.
5. Reboot the Pi and verify both services return. Stop the connector to remove
   public access without touching the LAN game.

The production hostname/account/domain and connector credentials are your setup
steps; they are not automatically provisioned by this repository. Cloudflare
terminates public HTTPS, so Let's Encrypt on the private localhost origin is not
needed for this direct tunnel setup. Use Cloudflare access controls if you want
an additional invite-only gate, and configure them to allow your intended players.

## Firewall, backups and checks

For a direct proxy deployment, allow incoming TCP 80/443 and forward those ports
on the router only if you choose that approach. Keep port 5000 private. With a
tunnel, **no incoming ports or router forwarding are needed**; permit connector
outbound traffic according to the official network requirements. Allow SSH only
where needed before enabling a firewall, so you do not lock yourself out.

Use SQLite's backup API (`manage.py backup`) rather than copying a live WAL
database alone. Schedule backups and monitor free disk space; retain backups on
another device. Restart after changing code/config; review migration logs. Verify
admin endpoints reject ordinary users, a fake forwarded IP is ignored on a direct
connection, stocks move on schedule, and a 24-hour religion cooldown survives restart.
Never serve `/var/lib/wconquest`, `.session-secret`, environment files or backups
through a static alias.

## Alternatives to Cloudflare without port forwarding

These options do not require opening a router port. A tunnel exposes the game
running at http://127.0.0.1:5000; a VPS runs the game on a separate public server.
No connector is installed or enabled automatically by this project.

### Tailscale Funnel — easiest option to try on your own computer

Install [Tailscale](https://tailscale.com/download), sign in and connect the host.
Keep the game running, open a new terminal, then run:

```powershell
tailscale funnel --bg 5000
```

If the CLI is not on PATH on Windows, use the installed executable:

```powershell
& "$env:ProgramFiles\Tailscale	ailscale.exe" funnel --bg 5000
```

Follow the enablement link if prompted to permit Funnel/HTTPS. Share the displayed
HTTPS .ts.net URL: visitors do not need the Tailscale app or a tailnet account.
Funnel provides HTTPS, only supports tailnet .ts.net names, and has
non-configurable bandwidth limits. Its public ports are 443/8443/10000; your game
can still use local port 5000. This is Funnel, not private Tailscale Serve.
The host must remain powered on and connected. See the
[Funnel documentation](https://tailscale.com/docs/features/tailscale-funnel) and
[CLI guide](https://tailscale.com/docs/reference/tailscale-cli/funnel).

### ngrok — simple public HTTPS tunnel

Install [ngrok](https://ngrok.com/download), create/sign in to your account, and
configure the agent with the token from your dashboard. Keep the token private.
Run `ngrok http 5000` and share its HTTPS URL. The free plan currently allows
20,000 HTTP requests and 1 GB of outbound transfer per month and displays a
browser interstitial. Frequent multiplayer polling can consume these quotas
quickly; consider a paid plan for continuous use. See
[free-plan limits](https://ngrok.com/docs/pricing-limits/free-plan-limits).

### playit.gg — an alternative with more HTTPS setup

Run the playit agent on the host and create an HTTPS tunnel in the dashboard.
Its documented website setup uses a configured domain and Caddy for local TLS
termination, then reverse-proxies to http://127.0.0.1:5000. Do not assume the
basic game tunnel supplies browser HTTPS automatically. Follow the
[official HTTPS tutorial](https://playit.gg/support/https-tunnel/).

### Public VPS — suitable for a persistent public game

Rent a Linux VPS with persistent storage and run the game there using the
Gunicorn/systemd/HTTPS steps above, adapting paths and firewall configuration.
A service such as [DigitalOcean Droplets](https://docs.digitalocean.com/products/droplets/how-to/create/)
provides a public server; no home router forwarding or home tunnel is involved.
This costs money and requires server administration but keeps the game running
when your personal computer is off. Transfer game.db using a consistent backup
and preserve the session secret/private assets separately. Never put these in Git.

For non-Cloudflare tunnels, do not use PROXY_MODE=cloudflare. Apply the trusted
proxy guidance above for the actual connector and verify HTTPS/client addresses
in Host tools. Proxy header behavior varies; do not trust forwarded IP headers
from arbitrary internet clients. Choose a provider before enabling a public URL.
