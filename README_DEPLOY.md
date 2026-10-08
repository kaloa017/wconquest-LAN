# Deployment guide

The current instructions are in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

They cover Raspberry Pi OS, Gunicorn/systemd, Apache/Nginx, HTTPS, trusted client-IP
handling and Cloudflare Tunnel without router port forwarding. For Windows/local
startup, use [README.md](README.md). For existing saves, read
[docs/MIGRATIONS.md](docs/MIGRATIONS.md) before upgrading.

The server already uses Waitress in app.py; do not replace it with Flask's debug
server. Keep game.db on persistent storage and retain its automatic backups.
