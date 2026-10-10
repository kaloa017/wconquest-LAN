# Security reports

Report exploitable account, permission, recovery, upload or data-disclosure issues
privately using GitHub's private vulnerability reporting if it is enabled for
this repository. If it is unavailable, ask the maintainer for a private contact
without posting exploit details publicly.

Do not upload real game.db files, player IPs, session secrets, recovery codes or
Cloudflare connector tokens in issues or pull requests. Include the affected
version, reproduction steps using test accounts, and the impact.

Only the current release is maintained. Host operators should keep dependencies
updated, use HTTPS for public hosting and back up saves before upgrades.

## Public hosting protections (6.6.0)

Use HTTPS with COOKIE_SECURE=1, a narrow ALLOWED_HOSTS allowlist and trusted
loopback proxy networks. Do not expose the SQLite save or session/tunnel/MFA
secrets. Optional TOTP MFA is recommended for every admin; password recovery
does not bypass it. Local MFA reset requires a typed confirmation and is audited.

Authentication has a bounded per-IP/account attempt tracker, separate from game
limits. JSON bodies are capped at 256 KB; upload limits remain separate. Origin
and fetch-site checks supplement CSRF tokens. Sessions expire after 12 hours;
password/MFA changes revoke other sessions through auth_version. CSP blocks
external scripts, eval, framing, objects and foreign form targets. External
HTTPS images remain allowed for the map and advertisements.

Known limitation: legacy inline handlers still need CSP unsafe-inline. Removing
those handlers and enabling a nonce-based policy is a follow-up, not a completed
claim in this release. MFA keys reside in the private database; OS permissions,
encrypted backups and disk protection are necessary. Authentication throttles
are process-local: use one worker or a shared gateway limiter when scaling.
Keep runtime dependencies updated and independently penetration-test before
large public deployments. This pass does not guarantee immunity to hacking.
