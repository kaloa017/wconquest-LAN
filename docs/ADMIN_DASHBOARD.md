# Server dashboard — 6.9

Open the admin dashboard; **Server dashboard** is now its landing section.
The existing Players, World, Factions & Chat, Tools, Country control, Game editor,
Advertisements and Host tools remain available. The dashboard links to each of
them and to Moderation, including chat word filters.

## Health

The private admin API reports host and game process uptime, CPU usage between
samples, CPU cores and clock, Linux load averages, RAM/swap, process memory,
storage, temperature, available fan RPM and Pi voltage/throttling flags. It also
shows network byte/error/drop totals, four fixed systemd unit states, local
Cloudflare connector readiness, database/WAL size, schema, query time, scheduler
timing, game counts and backup metadata. API request totals and the p95 of the
latest 512 handler timings are process-local, not an end-to-end latency benchmark.

Host samples cache for 10 seconds. The open, visible dashboard refreshes every
15 seconds; it stops polling when closed. CPU's first sample is unavailable.
Windows supports disk/RAM/uptime but generally lacks Pi sensors and systemd.
Missing readings remain **Unavailable**, rather than reporting zero or healthy.
Kernel/firmware permissions may prevent some Pi readings for the restricted
service account. Nothing executes arbitrary commands, reads service environment
or reveals the Cloudflare token. Health checks do not inspect other school devices.

Pi firmware warning bits follow Raspberry Pi's documented `get_throttled` values:
https://www.raspberrypi.com/documentation/computers/os.html#get_throttled
Current problems and warnings since boot are listed separately. A green dashboard
does not prove the SD card, power supply or school network is fault-free.

## Accounts, last seen and deletion

Accounts is a paginated, searchable directory. Inspect roles, resource balances,
progress, MFA enabled/disabled and last contact in local display time, ISO UTC
and Unix seconds. No authenticator key is included in these views.
Admins can change staff role, revoke sessions, clear mute/timeout and grant
research with server-checked prerequisites. Existing tools handle bans, renames,
resources, donations, faction changes, expeditions and offensives.

Deletion requires an impact review, an exact typed username, a reason and final
confirmation. The signed review expires after five minutes and is tied to the
acting admin and the reviewed account/counts. Changed records require re-review.
The acting account and last active admin cannot be deleted; self-demotion and
self-ban are blocked in the existing endpoints too.

Deleting an account ends involved offensives and returns survivors to their
original pool; leaves its faction, transferring leadership or dissolving it;
releases land, removes buildings/deployed units and personal progression;
removes authored chat, private trade discussions, notifications and linked
trade/loan records. Outstanding loans are cancelled without further repayment.
Delisted country/dissolved faction shares held by others cash out at the last
quote less the usual fee. Unrelated players and territories are retained.

This is operational account deletion, not a promise that all personal-data
mentions have vanished. Review ideas.txt, free text, audit details, exports,
proxy logs and backups separately. Do not restore deleted accounts accidentally.

Ranks includes a public paginated last-seen directory. Last seen means the latest
recorded contact with the server, including polling; it is not physical presence.
IP addresses remain private. Banned accounts are omitted from the public list.

## Downloads and backups

**Download game.db** takes an online SQLite snapshot of committed data, including
WAL contents, rather than copying a potentially incomplete live file. The download
is authenticated, CSRF-protected, audited and non-cacheable. It contains private
password/recovery hashes and MFA keys. It excludes the separate session secret,
media, ideas file and tunnel credentials. Only download it to trusted devices.

**Users CSV** opens in spreadsheets; dangerous text prefixes are neutralized.
**Users JSON** has format_version, export time and a users array, with native
research arrays. Both include names, account roles, game resources, research and
creation/last-seen times. Neither includes password/recovery/MFA secrets or IPs.

Manual snapshots go in `admin-backups` beside DB_PATH, mode 0600. Ten snapshots
maximum; no automatic deletion or public download listing is added. They contain
the database only. The existing scheduled Pi backup service remains responsible
for full private backups, retaining the latest 14 completed backup folders.
Unreadable backup directories are reported honestly; no extra sudo rights are needed.
Database quick-check/foreign-key checks run only when requested, with a time limit.
Restore and OS/service lifecycle actions remain local host operations.

## Maintenance, registration and policies

Admins can close registration and set maintenance text. Maintenance blocks
non-admin POST changes except login/logout/recovery. Reads remain available;
production and scheduled game processing continue. It is not a frozen simulation.
Defaults keep registrations open and maintenance off. Controls use the existing
game_settings table. Schema 20 adds guest analytics only and preserves game data;
an automatic pre-upgrade SQLite backup is created before changing the schema.

The Privacy Policy and Terms describe public last seen, dashboard access,
exports/deletion/backup retention, school hosting and moderation effects.
The host must still establish its actual operator/contact, lawful basis and
retention arrangements. School hosting alone does not make the game school-run.
Guidance: https://www.datatilsynet.no/personvern-pa-ulike-omrader/skole-barn-unge/

Email remains unimplemented and optional as a future feature. Free receiving
via Cloudflare Email Routing and transactional sending via a provider such as
Resend are separate services. Set up and verify DNS/provider credentials before
adding email collection; update the policy before storing addresses or tokens.

## Guest country flags

For the Pi's trusted Cloudflare tunnel configuration, country comes from a valid
CF-IPCountry header only alongside a valid CF-Connecting-IP from the trusted peer.
Untrusted or unknown country headers are ignored. The online list displays the
country name once with its flag and never sends the IP or city. Country reflects
an approximate IP location; VPNs and shared school addresses can affect it. The
guest tracker groups by IP, so several guests behind one NAT can appear as one.

Ensure Cloudflare **IP Geolocation** or its **Add visitor location headers**
managed transform is enabled if CF-IPCountry is absent. This is a Cloudflare
setting, not a game secret. Local/LAN visitors show Local network or Country
unavailable. The fix does not enable the optional legacy external IP lookup.
https://developers.cloudflare.com/network/ip-geolocation/

## Private guest analytics

Analytics shows guest IP, approximate country, first/last contact, Unix seconds,
landing page counts, country totals and new-record counts by first-seen date.
The admin-guarded API denies players and moderators; hiding the tab is not the
access control. Reads/settings changes are audited and responses are non-cacheable.

A random marker in the existing signed session cookie is stored only as a keyed
hash paired with the client IP. No fingerprint or raw cookie is stored. Records
represent browser/IP combinations, not verified people. No account ID is linked
to guest history, so account deletion cannot automatically identify a person's
guest records; review those separately by known IP when applicable.
Landing-page loads increment counts; spectator heartbeats update presence at
most once per minute and do not inflate pageviews. Signed-in visits are not
added to guest history. Old visits are not reconstructed.

Retention defaults to 30 days from last contact, configurable from 7 to 90 days.
A trigger caps records at 20,000; old inserted records may be evicted at that cap.
Expiry is pruned on visits and scheduler ticks. Admins can disable collection
or use the typed-confirmation purge. Backups and existing request reports remain
separate. The host must establish its legal basis for community/school use.

Schema 20 creates guest_visits, an index and the cap trigger. Existing players,
land and progression are untouched. The private pre-upgrade backup is
backups/game-before-v20-<timestamp>.db; the scheduled backup service does not age
that directory out automatically. Review its retention separately.

## Update the Pi after publishing the code

Use the existing backup/update procedure in PERFORMANCE_6_8.md. Keep DB_PATH,
/var/lib/wconquest, the session secret and tunnel token intact. No new runtime
packages, root dashboard access or service account permission changes are required.
Tested locally on disposable saves; physical Pi readings require verification on
the Pi after deployment.
