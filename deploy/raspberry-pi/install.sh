#!/usr/bin/env bash
# Run on the Pi after placing the application in /opt/wconquest.
set -Eeuo pipefail
umask 022
if [[ $EUID -ne 0 ]]; then echo 'Run with sudo bash deploy/raspberry-pi/install.sh game.example.com' >&2; exit 1; fi
hostname=${1:-}
if [[ ! $hostname =~ ^[a-zA-Z0-9]([a-zA-Z0-9.-]*[a-zA-Z0-9])?$ || $hostname != *.* || $hostname == *..* ]]; then
  echo 'Supply your public DNS hostname, without https://, paths or a port.' >&2; exit 1
fi
project=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
if [[ $project != /opt/wconquest ]]; then echo 'Place the project at /opt/wconquest first.' >&2; exit 1; fi
if [[ $(dpkg --print-architecture) != arm64 ]]; then echo 'This installer requires 64-bit Raspberry Pi OS (arm64).' >&2; exit 1; fi
if [[ ! -d /run/systemd/system ]]; then echo 'This installer requires systemd.' >&2; exit 1; fi

apt-get update
apt-get install -y python3 python3-venv ca-certificates curl
install -d -m 0755 /usr/share/keyrings
curl --fail --silent --show-error --location https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
chmod 0644 /usr/share/keyrings/cloudflare-main.gpg
printf '%s\n' 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' > /etc/apt/sources.list.d/cloudflared.list
chmod 0644 /etc/apt/sources.list.d/cloudflared.list
apt-get update
apt-get install -y cloudflared
if ! id wconquest >/dev/null 2>&1; then useradd --system --user-group --home-dir /var/lib/wconquest --create-home --shell /usr/sbin/nologin wconquest; fi
install -d -o wconquest -g wconquest -m 0700 /var/lib/wconquest /var/backups/wconquest
chown -R wconquest:wconquest /var/lib/wconquest
install -d -o root -g root -m 0700 /etc/wconquest
if systemctl is-active --quiet wconquest; then
  systemctl start wconquest-backup.service
  systemctl stop wconquest
fi
python3 -m venv /opt/wconquest/.venv
/opt/wconquest/.venv/bin/python -m pip install -r /opt/wconquest/requirements.txt
if [[ ! -f /etc/wconquest/game.env ]]; then
  cat > /etc/wconquest/game.env <<EOF
HOST=127.0.0.1
PORT=5055
DB_PATH=/var/lib/wconquest/game.db
COOKIE_SECURE=1
TRUSTED_PROXIES=127.0.0.1/32,::1/128
PROXY_HOPS=1
PROXY_MODE=cloudflare
ALLOWED_HOSTS=$hostname,127.0.0.1,localhost
PUBLIC_HOST=$hostname
AUTH_ATTEMPTS_PER_MINUTE=30
EOF
fi
chmod 0600 /etc/wconquest/game.env
for unit in wconquest.service wconquest-tunnel.service wconquest-backup.service wconquest-backup.timer; do
  install -o root -g root -m 0644 "$project/deploy/raspberry-pi/$unit" "/etc/systemd/system/$unit"
done
systemctl daemon-reload
systemctl enable --now wconquest.service wconquest-backup.timer
healthy=0
for attempt in {1..30}; do
  if /opt/wconquest/.venv/bin/python /opt/wconquest/tools/pi_healthcheck.py --host "$hostname" >/dev/null 2>&1; then healthy=1; break; fi
  sleep 2
done
if [[ $healthy -ne 1 ]]; then
  echo 'Game did not become ready. Check sudo journalctl -u wconquest -n 50 and /etc/wconquest/game.env.' >&2
  exit 1
fi
systemctl start wconquest-backup.service
printf '\nGame installed. Existing game.env and saves were preserved.\n'
printf 'Configure the named tunnel hostname to http://127.0.0.1:5055, then run:\n'
printf '  sudo bash /opt/wconquest/deploy/raspberry-pi/set-tunnel-token.sh\n'
printf 'See /opt/wconquest/docs/RASPBERRY_PI.md for save transfer and checks.\n'
