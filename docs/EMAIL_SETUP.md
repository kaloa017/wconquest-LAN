# Free account verification email (Brevo)

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
6. Sign in as your named administrator. Under **Players → Email & verification**,
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
  inspect Brevo's dashboard for delivery/bounce details.

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
