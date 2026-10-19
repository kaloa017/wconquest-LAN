#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ $EUID -ne 0 ]]; then echo 'Run this script with sudo.' >&2; exit 1; fi
if [[ ! -f /etc/systemd/system/wconquest-tunnel.service ]]; then echo 'Run install.sh first.' >&2; exit 1; fi
read -r -s -p 'Paste only the Cloudflare tunnel token (hidden): ' token </dev/tty
printf '\n'
if [[ -z $token || $token == *[[:space:]]* ]]; then echo 'Expected a single token, not the install command.' >&2; exit 1; fi
temporary=$(mktemp /etc/wconquest/.tunnel-token.XXXXXX)
trap 'rm -f -- "$temporary"' EXIT
printf '%s' "$token" > "$temporary"
unset token
chmod 0600 "$temporary"
mv -f -- "$temporary" /etc/wconquest/tunnel-token
systemctl enable wconquest-tunnel.service
systemctl restart wconquest-tunnel.service
echo 'Tunnel service enabled. Check: sudo journalctl -u wconquest-tunnel -n 30 --no-pager'
