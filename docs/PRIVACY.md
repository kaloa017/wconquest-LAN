# World Conquest — Privacy policy
Updated 20 October 2026

## Who handles your data
The operator of the server you joined handles its player data. For the
world-conquest.lol community, contact Kasper or a server administrator directly
for privacy questions, access requests or deletion requests. No support email
address has been configured yet. Hosting on a Raspberry Pi at school does not
by itself make this an official school service. The operator must identify the
responsible organisation and contact if the school operates the service.

## What is stored and why
The server stores your username, password hash, recovery-code hashes, account
roles, preferences and game progress to provide your account and run gameplay.
Passwords and new recovery codes are hashed; do not disclose the code shown at signup.
Chat messages, faction messages, ideas, transactions, battle history and moderation
records support multiplayer play, player requests, fairness and dispute handling.
Ideas are also written to a text file with the submitting username, player ID and time.

Client and proxy IP addresses, request counts and timestamps are recorded for
hosting, abuse prevention and moderation. Admins can see IP/request reports;
regular players and moderators do not receive them. Login timestamps, recent
interaction times and presence heartbeats enforce inactivity and war protections.
The activity check records timestamps, not the contents of keystrokes or pointer
movements. It does not automatically renew production just because the page polls.
Visible-browser playtime is stored per account and shown publicly on the Ranks leaderboard and to signed-in players
alongside your username. Hidden/closed tabs do not count. Multiple tabs do not
multiply your time. Totals start with the playtime update, not your original signup.

Account/game processing is intended to provide the requested game service.
Security and moderation records are intended to protect players and the server.
The host is responsible for establishing and documenting the applicable legal
basis, retention periods and any additional processing for its deployment.

## Who can see information
Other players see usernames, public country/faction information, public chat and
online presence. The public Ranks page also shows each non-banned player's last
recorded contact with the game as a relative time and date. This can include
background requests and does not prove the person is at their keyboard.
Administrators additionally see last-seen timestamps in Unix seconds.
Faction chat is limited to the faction; admins may access game
data for hosting and moderation. Private campaign information is limited to the
attacker and current defender through the game API. People with host/database or
backup access can access stored game data. Do not submit sensitive information.

## Cookies, browser storage and external services
A session cookie supports login and request security. Browser storage remembers
tutorial completion. The game does not include advertising analytics.
When guest history is enabled, the existing signed session cookie also holds a
random guest-session marker. The server stores a keyed hash of that marker with
the guest IP, approximate country if available, first/last contact and landing
page count for private hosting, traffic and abuse review. It does not fingerprint
devices, record precise location or identify a guest's real name. Multiple people
can share an IP; clearing cookies can create a new record. This is first-party
server analytics, not a third-party advertising tracker.
Background map tiles come from OpenStreetMap; its tile service receives normal
web requests, including your IP address and requested map tile coordinates.
If the host uses Cloudflare or another reverse proxy/tunnel, that provider handles
connection data under its own policies. Trusted Cloudflare country headers can
provide an approximate country and flag for guests in the public online list;
the list does not expose guest IP addresses or cities. Optional external IP geolocation is disabled by
default; if enabled by the host, IP addresses are sent to ip-api.com, currently
over HTTP, to display approximate locations. Hosting operators should leave this
off unless they have assessed and disclosed that processing appropriately.
Optional donations are handled separately by the payment provider; the game does
not collect card information or directly process payments.
The host may display a customizable advertisement banner. If it contains an
external image, that image host receives image requests, including your IP address.
Clicking its optional link opens the chosen site under that site's privacy policy.
The game does not add advertisement click tracking or third-party advertising scripts.

## Storage and retention
Data is stored on the host's server in the game database, ideas file and backups.
Request caches and some game histories have count limits. There is no general
automatic age-based deletion of accounts, chat, ideas, audit records or backups.
The host must review retention, delete data when no longer needed, and explain its
actual retention schedule to players. Backups may retain older records until the
host rotates them. Keep server files and backups private; they do not belong in GitHub.

## Server dashboard, exports and account deletion
Only administrators can access host uptime, CPU load, memory, storage,
temperature, available power/fan sensors, network traffic totals, game/database
statistics, backup metadata and game/tunnel service state. These checks inspect
the game host; they do not inspect students' devices, browsing history or other
school network traffic. Hardware samples are cached briefly in memory.
The private Analytics tab shows guest records and IP addresses only to admins;
players and moderators are denied by the server API. No guest IP or city is
returned by the public online list. History starts with this update; older
visits are not reconstructed. Analytics access and settings changes are audited.
The host must establish an appropriate legal basis and explain this processing
to its community; school hosting does not automatically authorise collecting
student data.

Administrators can download a consistent game.db copy for backup and support.
It contains private account data, password/recovery hashes and authenticator
keys and must be protected like the server database. CSV and JSON user exports
include usernames, roles, game resources, research, account creation and
last-seen times. They exclude password hashes, recovery secrets, authenticator
keys and IP addresses. Export and account-management actions are audited.

Dashboard account deletion removes the login, progression, authored chat,
private trade discussions and linked transactions from the live database,
releases land and anonymizes structured historical author fields. It is not
complete automatic erasure of every mention: names or other data in free-text
messages, ideas.txt, audit details, downloaded exports, school/proxy logs and
older backups need separate review by the operator. Security records may be
retained where justified by applicable law. When restoring a backup, the
operator must reapply fulfilled deletion requests.

The supplied Pi setup keeps the latest 14 completed scheduled backup folders,
normally one per day. Manual dashboard snapshots are separate database copies,
capped at 10, and remain until the host removes them. Downloaded copies are
controlled by their recipient. The operator must set and communicate retention
for those copies and any additional logs.
Guest history defaults to 30 days from last contact, configurable from 7 to 90
days, with a maximum 20,000 browser/IP records. Old records are pruned on visits
and scheduled game ticks. Admins can disable new collection, shorten retention
or clear live history. Backups remain separate and may contain guest records
until rotated or reviewed. Pre-upgrade backups are also separate from the
scheduled 14-folder rotation.

## School hosting and email
Use a game nickname and a unique password, not a school account password. Do not
submit student numbers, class lists, health information or other sensitive data
in chat or ideas. Players can ask the operator for help understanding this notice.
School-managed networks or devices may have their own logging and policies,
which are outside this game's dashboard.

The current game does not collect email addresses or send verification emails.
Before introducing email verification or email recovery, the operator must
update this notice with the provider, purposes, stored email/token data,
retention and any relevant international transfers. Existing accounts are not
required to provide an email address by this update.

## Your choices and rights
You can change available account preferences and mute shared music. Ask the host
to access, correct, export or delete personal data, restrict processing, or object
to processing where applicable. Some security records may need lawful retention.
You may complain to your local data protection authority; in Norway this is
Datatilsynet (www.datatilsynet.no). No claim of automatic legal compliance is made
for every server using this open-source project.

Host guidance: Norwegian Data Protection Authority, Digital services and personal
data (information and retention requirements):
https://www.datatilsynet.no/contentassets/3583c372d8b44bac839d505e298cae27/digitale-tjenester-engelsk.pdf

## 6.6.0 additions (10 October 2026)
Verified donation totals (NOK) and cosmetic tiers are public on Ranks. Admins
manually record totals; no payment credentials are collected. Private trade
discussions are restricted by the API to the two participants; the latest 100
messages per pair are retained. Host/database/backup access can still read them.
Authenticator setup keys are stored in the private database so the server can
verify time-based codes. They are never public or sent to an external QR provider.
Keep the database and backups private. Return summaries store aggregate positive
resource gains/deliveries while away and are cleared when acknowledged.
