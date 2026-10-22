# Resend sending, receiving and private support forwarding

Existing worlds are preserved. No email is sent until private provider setup
is complete. Verification codes, templates and spam limits remain in the game.

## Deploy and configure on the Pi

1. Deploy this version and install requirements using the normal deployment
   procedure. The save stays at `/var/lib/wconquest/game.db`.
2. Your verified sending domain is `world-conquest.lol`. Use the sender
   `support@world-conquest.lol`, displayed as World Conquest. Keep open/click
   tracking off for authentication mail.
3. In Resend > Domains > world-conquest.lol, enable Receiving. Add the exact
   receiving MX record Resend displays in Cloudflare. For the root domain the
   name is `@`, not `www` or `send`. Preserve the sending DKIM/SPF and `send` MX,
   and the website tunnel records. If another service already receives root
   mail (including Cloudflare Email Routing), choose which service owns root
   receiving before replacing its MX records. Multiple providers are not copies.
4. In Resend > Webhooks, add
   `https://www.world-conquest.lol/integrations/resend/inbound`, selecting only
   `email.received`. An initial failure before secrets are installed is expected.
   Keep its `whsec_...` signing secret private.
5. Receiving needs a Resend Full access API key to fetch message contents and
   attachment metadata. A sending-only key works for verification alone.
6. Run on the Pi after deploying:

   ```bash
   sudo bash /opt/wconquest/deploy/raspberry-pi/set-email.sh
   ```

   Choose `resend`, accept `support@world-conquest.lol`, enter the API key at
   the hidden prompt, then your personal forwarding inbox and the hidden
   webhook signing secret. The private destination is never hard-coded in Git.
   The script writes root-only `/etc/wconquest/email.env`, installs the service
   environment override, and restarts only the game. Rerunning replaces email
   configuration; preserve your key privately if changing the destination.
7. In Administration > Email & verification, customize and enable email codes.
   The forwarding card shows setup and delivery status, without exposing the
   destination or secrets. Forwarding is configured separately from enabling
   login codes, so support mail can work even when codes are disabled.
8. End-to-end checks: attach your own account email and verify a code; send an
   ordinary message with a small attachment to `support@world-conquest.lol`.
   Check Resend's Receiving dashboard, the webhook delivery, then your personal
   inbox (including junk). Provider acceptance is not proof of inbox delivery.

No live provider call is made by the automated tests. Deployment, secrets,
receiving DNS and a real delivery check remain host setup tasks.

## Forwarding behavior and limits

Only `support@world-conquest.lol` is forwarded, unless EMAIL_INBOUND_ADDRESS is
explicitly changed. Other addresses on the receiving domain remain in Resend.
The public webhook verifies the raw-body Svix signature and five-minute
freshness before queueing a provider email ID. It cannot select destinations
or send arbitrary messages. Repeated events are deduplicated by email ID.

The existing background worker retrieves content from Resend and sends the
forward from the verified sender to the privately configured personal inbox.
Reply-To is the original sender (unverified), so replying in your personal mail
app goes to the correspondent and reveals your personal sender address. To
reply as support, use a Resend-backed sending workflow instead. Keep personal
mail auto-replies disabled for forwarded support messages.

HTML, plain text and attachments up to 10 MiB total are forwarded. Attachment
files are passed back to Resend using its own temporary URLs; the Pi never
renders mail HTML or downloads attachment URLs. Messages with excessive content,
more than one attachment page, malformed addresses or forwarding loops remain
available in Resend and show a generic failure in admin. Pending forward requests are encrypted using the session secret for stable,
idempotent retries, then cleared on completion/failure/expiry (within an hour).
No attachment files are stored on the Pi and message bodies are never shown
in the admin panel. Preserve the session secret alongside the save.

Forwarding is limited to 10 reservations per UTC day; it shares the game's
combined daily allowance (at most 90 for Resend) and monthly allowance (2,700
reservations in the UTC calendar month). Resend's Free limits currently include
100 emails/day and 3,000/month. Both received emails and forwarded copies count
at the provider. A busy inbox or other applications can exhaust the provider
allowance before local limits. Keep the account dedicated; do not enable paid
upgrades/pay-as-you-go. Queued forwards are tried up to three times within an
hour, then stop; originals remain in Resend for manual attention. Signature
replays and retries are deduplicated for seven days; at most 200 inbound IDs
are retained. Quota counters remain for 35 days for monthly accounting.

Only explicit daily/monthly provider quota responses or exhausted local budgets
activate the host's configured password fallback. Generic HTTP 429 rate limits,
network outages and bad API keys do not bypass code authentication. Monthly
fallback can last until the next UTC month. Passwords and TOTP remain required.

Private environment fields are documented in `.env.example`. The API key,
webhook secret and forwarding inbox belong in the Pi's root-only environment,
not in dashboard fields, chat, screenshots or Git. Back that environment file
up privately and separately from public exports.

Official references:
- https://resend.com/docs/api-reference/emails/send-email
- https://resend.com/docs/guides/dns/cloudflare
- https://resend.com/docs/dashboard/receiving/forward-emails
- https://resend.com/docs/api-reference/errors
- https://resend.com/pricing

---

# Legacy Brevo setup

Email is optional until the host configures it. Existing accounts and saves keep
working. This integration sends account verification and login codes; it does
not add email-based password resets or marketing mail.

## One-time provider setup

1. Create your own **Brevo Free** account at https://www.brevo.com/ . Complete
   its account activation and any transactional-sending approval. Do not choose
   a paid plan or enable automatic upgrades. Provider eligibility is determined
   by Brevo; this project cannot guarantee approval or permanent free pricing.
2. In Brevo's sender/domain settings, authenticate `world-conquest.lol`. Add the
   exact DNS records Brevo supplies in Cloudflare. Email records are DNS-only;
   keep the existing game Tunnel record. Do not create duplicate SPF records or
   replace existing mail records blindly.
3. Verify the sender `accounts@world-conquest.lol` (or your chosen address).
   Sending verification is separate from having an inbox for replies.
4. Generate a Brevo API key. Keep it private: do not paste it in chat, the game
   dashboard, screenshots, source files, or GitHub.
5. After deploying this version and updating Python requirements on the Pi, run:

   ```bash
   sudo bash /opt/wconquest/deploy/raspberry-pi/set-email.sh
   ```

   Enter the verified sender address and paste the key at the hidden prompt.
   This installs `/etc/wconquest/email.env` with root-only permissions and a
   service override. The game and tunnel settings are preserved. Back this new
   private environment file up separately; database exports do not include it.
6. Sign in as your named administrator. Under **Email & verification**,
   enable email codes, review the quota fallback, customize the template and
   save. Attach your email through Account settings and request a real code as
   an end-to-end test. The preview uses a dummy code and does not send email.

Brevo documents 300 free sends per day. The game's maximum is **250 reservations
per UTC day**, leaving headroom for tests, retries and messages from outside the
game. It does not monitor all other Brevo applications' usage. Keep this free
provider account dedicated to the game. Local budget resets use UTC; provider
reset times may differ. No API request upgrades or purchases a plan.

## Player behavior

- Registration can include an optional email. Accounts without an email still
  work and receive an add-email reminder after each login once sending is enabled.
- Passwords remain required. An attached email needs an eight-digit code to
  authenticate each new login. Entering a code also verifies a pending address.
- Existing signed-in sessions are not immediately revoked when email is enabled.
- Adding/changing an address requires the current password; replacing a verified
  address also requires a fresh code to the current address.
- A code lasts ten minutes, is single-use, and allows five incorrect attempts.
  Resends have a 60-second cooldown. Limits are ten requests per account/address
  per UTC day and sixty per IP per fixed UTC hour. Shared networks share that
  IP limit. These limits also apply to admin-triggered resends.
- A new resend cancels the previous code. Queued delivery can take several
  seconds. Accepted status is provider acceptance, not proof of inbox delivery;
  inspect the provider's dashboard for delivery/bounce details.

## Quota fallback and failure behavior

The requested default allows password-only login temporarily when the game daily
budget is exhausted or Brevo explicitly reports exhausted credits. Registration
continues without email. TOTP, password checks, account bans and IP restrictions
still apply. A failed code does not silently fall back. Players may submit their
password again with the email-code field empty to use an active quota fallback.

**This intentionally weakens email authentication when quota runs out.** A
determined group could exhaust the global allowance despite individual limits.
Admins can disable fallback, or disable email sending for an outage. Network
errors, invalid provider credentials and individual cooldowns never automatically
disable code checks. Keep private recovery codes and authenticator access safe.

If the provider is unavailable and all admins are signed out, the local host can
explicitly disable email authentication (passwords and TOTP stay required):

```bash
sudo -u wconquest env DB_PATH=/var/lib/wconquest/game.db /opt/wconquest/.venv/bin/python /opt/wconquest/manage.py disable-email
```

Type `DISABLE` at the prompt. This is audited. Fix the provider, then re-enable
email codes in the admin dashboard. The public API has no emergency bypass.

Verification hashes are HMAC protected. Outbox content is encrypted using a key
derived from the existing session secret, cleared after acceptance/failure/
expiry, and never returned by an API or included in ordinary user exports.
Preserve the session secret when moving the save. Delivery metadata is retained
for seven days, with bounded request-limit metadata. API keys stay outside the DB.
Never publish the private save, environment file or session secret.

Official references:
- https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan
- https://developers.brevo.com/reference/send-transac-email
