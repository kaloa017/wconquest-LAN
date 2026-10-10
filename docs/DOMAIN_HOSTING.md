# Host on your own Windows computer with a domain

Use a named Cloudflare Tunnel for a stable hostname without port forwarding.
Publishing through Tunnel does not require a paid Access plan. The domain
registration and your computer/electricity/internet are separate costs. Your
computer must remain on, connected and running the game. GitHub Pages cannot run
this Flask/SQLite application.

## 1. Prepare the host

Back up your save with the existing host backup command. Install dependencies
using the exact Python interpreter you use to run the game:

```powershell
python -m pip install -r requirements.txt
```

If `python` and `pip` point to different installations, use a project virtual
environment or the full path to the desired interpreter. The game runs with
Waitress when you start `python app.py`; do not expose Flask's development server.

## 2. Add a domain

Register a domain, add it to your Cloudflare account and replace its nameservers
at your registrar with the nameservers Cloudflare provides. Wait for the domain
to become active. Use a subdomain such as `game.example.com`.

## 3. Create a named tunnel

In the Cloudflare dashboard, open **Networking → Tunnels**, create a tunnel and
choose the Windows connector. Follow the installation command shown there.
Install `cloudflared` if necessary; reopen PowerShell afterwards so PATH updates.
Keep the connector token private: it is a credential, never a GitHub file or chat
message. You can run the connector in the foreground while testing; service
installation is optional and requires your own Administrator terminal.

Add a **Published application** route:

- Hostname: `game.example.com`
- Service type: HTTP
- Service URL: `127.0.0.1:5055`

The dashboard creates the tunnel DNS route. Do not add an A record pointing to
your home IP. Do not open router ports or Windows inbound port 5055. The connector
initiates outbound connections and the public hostname supplies HTTPS.

## 4. Configure the game

In the PowerShell terminal where you will run the game:

```powershell
$env:HOST = '127.0.0.1'
$env:PORT = '5055'
$env:COOKIE_SECURE = '1'
$env:ALLOWED_HOSTS = 'game.example.com,127.0.0.1,localhost'
$env:TRUSTED_PROXIES = '127.0.0.1/32,::1/128'
$env:PROXY_HOPS = '1'
$env:PROXY_MODE = 'cloudflare'
$env:AUTH_ATTEMPTS_PER_MINUTE = '30'
python app.py
```

Substitute your real domain. Environment values apply to that terminal process;
the app does not automatically load `.env`. Secure cookies require visiting the
HTTPS domain for login, rather than the local HTTP URL. Trust only the local
tunnel connector, never all IPs. Keep `.session-secret`, `game.db`, backups and
tunnel credentials outside public/static folders and out of GitHub.

Visit the public HTTPS hostname from another network, create a normal account,
and confirm that the map, login and POST actions work. Check the admin request
tracking shows the real client address rather than every user appearing as
127.0.0.1. Set the hostname and proxy settings before advertising the URL.

## 5. Protect the host account

Use a unique long password. Enable **Settings → Two-factor authentication** and
back up your authenticator securely. Enable MFA on your Cloudflare and registrar
accounts too. Keep Windows, Python dependencies and `cloudflared` updated. Prefer
running the game as an ordinary dedicated Windows user with access only to its
project/save folder. Keep Windows Firewall enabled and inbound game ports closed.

Authentication endpoints are throttled independently of optional game limits.
Avoid disabling or raising that safety setting on a public deployment. The app
adds origin/CSRF checks, host validation, session expiry and security headers.
There is no guarantee that any website is impossible to hack. The remaining
inline JavaScript event handlers limit CSP strength; the security document
explains this and the follow-up work needed.

If you lose your authenticator, the host can recover locally:

```powershell
python manage.py reset-two-factor --username YourAccount
```

This requires an explicit typed confirmation, is audited and revokes sessions.
Player password recovery alone does not remove two-factor protection.

## Free alternative without a purchased domain

Tailscale Funnel can publish a local service through a `*.ts.net` hostname. It
does not support arbitrary custom domains, and has service/port/bandwidth limits.
Check current plan eligibility for your use. Install and sign in to Tailscale,
then follow its official Funnel guide and publish your loopback game port. Keep
the game listening on 127.0.0.1, use secure cookies and update `ALLOWED_HOSTS` to
the assigned hostname. Do not set `PROXY_MODE=cloudflare` for a different provider.

A TryCloudflare quick tunnel is convenient for temporary tests, but its random
URL is not your stable domain deployment. A public VPS is another option but
usually adds costs and maintenance. A static website host cannot persist this
game's SQLite world or run its Python scheduler.

## Official references (checked 10 October 2026)

- [Create a dashboard-managed tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/)
- [Published application routing](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/)
- [Tailscale Funnel and its limits](https://tailscale.com/docs/features/tailscale-funnel)
- [Tailscale free plan eligibility](https://tailscale.com/docs/reference/free-plans-discounts)
