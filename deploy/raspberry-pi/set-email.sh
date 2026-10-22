#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
if [[ $EUID -ne 0 ]]; then echo 'Run this script with sudo.' >&2; exit 1; fi
if [[ ! -f /etc/systemd/system/wconquest.service ]]; then echo 'Install the game service first.' >&2; exit 1; fi
read -r -p 'Email provider [resend/brevo, default resend]: ' provider </dev/tty
provider=${provider:-resend}
if [[ $provider != resend && $provider != brevo ]]; then echo 'Choose resend or brevo.' >&2; exit 1; fi
read -r -p 'Verified sender address [support@world-conquest.lol]: ' sender </dev/tty
sender=${sender:-support@world-conquest.lol}
if [[ ! $sender =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$ ]]; then echo 'Enter a valid verified sender address.' >&2; exit 1; fi
read -r -s -p 'Provider API key (hidden; never paste it in chat): ' email_key </dev/tty
printf '\n'
if [[ ! $email_key =~ ^[A-Za-z0-9_.-]+$ ]]; then echo 'Expected only the provider API key.' >&2; exit 1; fi
forward_to=''
webhook_secret=''
if [[ $provider == resend ]]; then
  read -r -p 'Personal inbox to forward support emails to (blank disables forwarding): ' forward_to </dev/tty
  if [[ -n $forward_to ]]; then
    if [[ ! $forward_to =~ ^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}$ || ${forward_to,,} == ${sender,,} ]]; then echo 'Enter a different, valid personal inbox.' >&2; exit 1; fi
    read -r -s -p 'Resend webhook signing secret (whsec_..., hidden): ' webhook_secret </dev/tty
    printf '\n'
    if [[ ! $webhook_secret =~ ^whsec_[A-Za-z0-9+/=]+$ ]]; then echo 'Expected a webhook signing secret.' >&2; exit 1; fi
  fi
fi
install -d -m 0700 /etc/wconquest
temporary=$(mktemp /etc/wconquest/.email-env.XXXXXX)
trap 'rm -f -- "$temporary"' EXIT
if [[ $provider == resend ]]; then key_name=RESEND_API_KEY; else key_name=BREVO_API_KEY; fi
printf 'EMAIL_PROVIDER=%s\n%s=%s\nEMAIL_FROM=%s\nEMAIL_REPLY_TO=%s\nEMAIL_FROM_NAME="World Conquest"\nEMAIL_INBOUND_ADDRESS=%s\nEMAIL_FORWARD_TO=%s\nRESEND_WEBHOOK_SECRET=%s\n' "$provider" "$key_name" "$email_key" "$sender" "$sender" "$sender" "$forward_to" "$webhook_secret" > "$temporary"
unset email_key webhook_secret
chmod 0600 "$temporary"
mv -f -- "$temporary" /etc/wconquest/email.env
install -d -m 0755 /etc/systemd/system/wconquest.service.d
printf '[Service]\nEnvironmentFile=/etc/wconquest/email.env\n' > /etc/systemd/system/wconquest.service.d/email.conf
systemctl daemon-reload
systemctl restart wconquest.service
echo 'Credentials installed privately. Enable Email codes in Administration > Email & verification.'
echo 'Use a Free account only. Do not enable paid upgrades or pay-as-you-go.'
echo 'For receiving: enable the domain receiving MX in Resend, then register https://www.world-conquest.lol/integrations/resend/inbound for email.received events.'
