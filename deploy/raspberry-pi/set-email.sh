#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ $EUID -ne 0 ]]; then echo 'Run this script with sudo.' >&2; exit 1; fi
if [[ ! -f /etc/systemd/system/wconquest.service ]]; then echo 'Install the game service first.' >&2; exit 1; fi
read -r -p 'Verified Brevo sender address (e.g. accounts@world-conquest.lol): ' sender </dev/tty
if [[ ! $sender =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$ ]]; then echo 'Enter a valid verified sender address.' >&2; exit 1; fi
read -r -s -p 'Brevo API key (hidden; never paste it in chat): ' email_key </dev/tty
printf '\n'
if [[ ! $email_key =~ ^[A-Za-z0-9_.-]+$ ]]; then echo 'Expected only the Brevo API key.' >&2; exit 1; fi
install -d -m 0700 /etc/wconquest
temporary=$(mktemp /etc/wconquest/.email-env.XXXXXX)
trap 'rm -f -- "$temporary"' EXIT
printf 'BREVO_API_KEY=%s\nEMAIL_FROM=%s\nEMAIL_FROM_NAME="World Conquest"\n' "$email_key" "$sender" > "$temporary"
unset email_key
chmod 0600 "$temporary"
mv -f -- "$temporary" /etc/wconquest/email.env
install -d -m 0755 /etc/systemd/system/wconquest.service.d
printf '[Service]\nEnvironmentFile=/etc/wconquest/email.env\n' > /etc/systemd/system/wconquest.service.d/email.conf
systemctl daemon-reload
systemctl restart wconquest.service
echo 'Credentials installed privately. Enable Email codes in Administration > Players > Email & verification.'
echo 'Use a Brevo Free account only. Do not enable paid upgrades or add a payment method for this setup.'
