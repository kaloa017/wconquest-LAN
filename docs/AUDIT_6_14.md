# Project audit and implementation — 22 October 2026

## A. Summary

Release 6.14 improves the existing Flask/SQLite/Leaflet game. It fixes repeated
away-summary presentation across tabs/reloads, restores summaries for shorter
returning logins, prevents duplicate campaign refunds, corrects historical
naval/air milestones, and adds coherent event feedback/history. The tutorial is
more detailed and navigable. Daily rewards scale with production, following the
owner's explicit additional request. Architecture, normal gameplay routes,
ownership and saved progression remain in place.

This is implementation and regression work, not a penetration-test certification.
Production services, accounts, balances and the live Pi were not modified.

## Inspection coverage

The repository was reviewed by subsystem, building on the earlier architecture
inventory and audit rather than replacing it with a second application.

| Subsystem | Source inspected / traced | Verification |
|---|---|---|
| Authentication/security | app.py, features.py, security.py, two_factor.py, email_verification.py, runtime.py | existing auth, CSRF, TOTP, email, session and admin-boundary tests |
| Ownership/geography/map | app.py, geography.py, map_delivery.py, cities.py, map-performance.js, client.js | territory/delta/geography/capital tests; source review |
| Combat/diplomacy/factions | app.py, expansion.py, economy.py, progression.js | existing role/war/campaign/private-order tests plus settlement replay and strategic-loss events |
| Economy/research/space | config.py, progression_content.py, late_research.py, research.py, space.py, economy.py | production, costs, shares, loans, gifts, expeditions and research regressions |
| Activity/notifications | activity.py, experience.py, playtime.py, player_events.py, experience.js, player-events.js | login-to-collection trace, concurrent claims, read/presentation state, grouping and DOM tests |
| Admin/data/privacy | admin_dashboard.py, guest_analytics.py, traffic_controls.py, server_health.py, policies.py | existing private exports/deletion/roles/analytics tests and account-event recipient test |
| UI | index.html, legacy-client.js and feature layers, interface.js/CSS, product-ui.js/CSS, guided-help.js | 23 major API-fixture renderers, startup, axe/contrast/keyboard tests, local browser checks |
| Operations/tooling | migrations.py, communications_schema.py, requirements, checks.yml, deploy/raspberry-pi, backup/release tools | full isolated suite, migration/backup regressions, syntax, pip consistency and release exclusions |

The game uses HTTP polling and SQLite request transactions, not a WebSocket event
broker. No broker/framework was introduced. Existing proxy trust, cookie, session,
CSRF, recipient and server-side role controls were retained. Security-sensitive
files, uploads, administrative exports and client rendering were included in the
inspection; passing tests does not establish that every possible exploit is absent.

## B. Bugs fixed

| Confirmed behavior and cause | Fix | Evidence |
|---|---|---|
| Two tabs could fetch the same pending away summary; only clicking its close button acknowledged it. Reload before closing could repeat it. | POST presentation claim inside the shared immediate transaction, keyed by account/away episode; archive its snapshot and acknowledge the authoritative activity boundary. | Two parallel clients produce exactly one claimed summary; reconnect GET and repeated claim do not return it again. DOM test removes the dialog without acknowledgment and still cannot redisplay it. |
| A submitted future `since` could move the old acknowledgment watermark past legitimate future episodes. | Validate against the actual pending episode; derive the acknowledgment boundary from stored activity. | Wrong/future episode is rejected; later genuine absence still produces a new summary. |
| Login updated heartbeat before collecting income, making a returning player appear continuously online to the offline-gain tracker. | Settle production before advancing login heartbeat/activity. | Actual password-login regression preserves the summary for a ten-minute absence. |
| Changelog could stack above inactivity confirmation and its dismissal request was blocked while paused. | Defer only release notes until the activity dialog is cleared; reuse existing return lifecycle for retry, with no polling timer added. | DOM regression and local browser flow. |
| `finish_campaign` could refund twice when internal processing called it again with the same stale record. | Load the current active record and transition it conditionally before refunding. | Calling settlement twice returns the force once. No public exploit was demonstrated. |
| Naval/air achievements examined only the latest victory, so a subsequent land victory could mask qualifying earlier wins. | Query distinct historical winning modes. | Naval/air/land sequence awards both achievements once. |
| Important notifications were persistent but silent, and read messages disappeared from the only UI view. | Tiered feedback backed by the same rows, separate presentation/read state and paginated history. | API/DOM tests and browser checks described below. |

### Away-summary semantics

A claim records **presentation**, not proof that a human read the popup. It is an
at-most-once presentation attempt across tabs and sessions. If a connection drops
after the server commits but before the popup renders, the summary remains in the
notification center instead of risking another popup. Read/close state is separate.
New interaction followed by a genuinely new absence can generate a new episode;
there is no arbitrary duplicate-suppression timeout.

## C. Security and integrity findings

- **Medium integrity risk, internal replay:** repeated campaign settlement could
  duplicate returned troops. The shared settlement transition is now conditional
  and uses authoritative persisted troops. Existing command permissions remain.
- **Low integrity risk, account-local input:** away acknowledgment trusted an
  arbitrary timestamp. It can no longer suppress later summaries this way.
- **Security regression prevention:** event history, event presentation and away
  claims always scope SQL to the authenticated account. Guessing another event ID
  cannot present/read that account's event. Presentation endpoints retain CSRF,
  timeout, session and request transaction guards.
- Event content is escaped, actions use supported internal routes, and accepting
  an account merge from the inbox requires explicit confirmation. Server handlers
  remain responsible for authorization and costs.
- Existing role-boundary sweep and tests for private campaigns, faction chat,
  trade discussions, analytics, database exports, email codes and MFA pass.

No critical newly exploitable public authentication bypass was demonstrated in
this pass. No claim of complete security is made. Existing inline handlers still
require CSP `unsafe-inline`; replacing them is a separate architectural cleanup.
Real reverse-proxy trust, OS permissions, dependency advisories, email-provider
configuration and school-network access need operational review on the host.

## D. UI/UX and tutorial

- The bell now opens **Unread** or **Recent history**, with clear read state,
  explicit marking, grouping details and Load older events.
- At most two activity cards are visible; they do not cover the screen with
  modals (one card at a time on phones). They provide dismissal and a working details entry point. A maximum of
  30 toast groups is queued, prioritized; overflow remains discoverable in history.
- Existing tile/menu actions are used for navigation. Legacy actionable offers
  still use their server-validated response routes. War assessment is available
  deliberately from the event center instead of another automatic war modal.
- Tutorial topics explain actual menus, first claim/build, research prerequisites,
  capital districts, city bonuses/search, gifts, notifications, offline production
  and late-game space goals. A topic selector, back/next and existing menu-opening
  actions let players choose their path. It stays optional and revisitable.
- The tutorial focus loop includes its topic selector, not just buttons. Release
  notes wait until the inactivity dialog is cleared.

## E. Notification system

Classification is centralized in `player_events.POLICY`, using typed events
emitted by validated server operations rather than matching message wording.

| Tier | Examples | Feedback |
|---|---|---|
| 1: Important | Capital/city loss, war declaration, strikes, faction removal, moderation, large battle | Distinct non-blocking card, up to 12 seconds; persistent inbox/history |
| 2: Routine/actionable | Ordinary lost territory, smaller offensive, alliance/trade/loan request | Compact card, up to 6 seconds; capture groups and persistent history |
| 3: Low priority | Gifts and exchange results | Bell/feed only |
| 4: Background | General information, archived away earnings, unclassified legacy info | Feed only |

The current large-battle feedback threshold is 1,000 initially committed troops;
it affects presentation only, not combat. Capture groups require the same actor,
event type and fixed two-minute activity window. Capitals/cities are never folded
into ordinary capture groups. Expanding groups preserves each original message.
Grouping occurs on retrieval, so stored events retain their individual IDs/data.

Unread polling uses the existing session timer; no second notification polling
loop was added. A presentation POST occurs only when there are unpresented events.
The transaction claims those IDs once across tabs. Read state changes only through
explicit marking. Dismissed/read events remain in recent history. Old notifications
are marked already presented during migration, keeping their existing read state
without replaying an old backlog. Retention is 500 events and 100 away identifiers
per account; older notification rows are pruned when new events are emitted.

All history is recipient-private. No neighboring-player surveillance feed was
invented. Unknown legacy informational messages stay low priority; converting all
remaining legacy emitters to more specific event types is incremental work.

## Daily reward balance change requested during the audit

Players choose **money** or **three distinct resources** once each UTC day, using
the existing shared `last_daily`/streak state. Money is 10% of seven days at current
money production, including unlocked orbital income: rate × **1,008 minutes**.
At 100,000 money/minute, this is **100,800,000 money**. It is a projection, not an
assertion that the game grants seven days of offline earnings.

Each resource option uses the same scale for its current production with starter
minimums. Selection is stable for the account/day using a server-keyed seed; reload
does not reroll it. Existing streak troop rewards remain. Claiming either choice
consumes the day's shared claim, and concurrent choices cannot both pay. Existing
already-claimed days remain claimed; this change does not reset progress or impose
a new currency. The owner explicitly requested this large late-game reward buff;
its long-term economic effects have not been playtested at scale.

## F. Verification actually run

- `python -m unittest discover -s tests`: **230 passed**, 90.864 seconds on the
  final Python behavior. Includes 12 new event/reward regressions and the existing
  admin, authentication, multiplayer, finance, map, backup and migration coverage.
- `npm run test:ui`: **37 passed** after fixing a missing animation-frame stub
  in the new offline DOM test (a test environment issue). Includes escaped event
  rendering, queue limits, grouping, tutorial focus/topic navigation, daily choices,
  away presentation, release-dialog ordering and full guest/signed-in startup.
- Syntax checks for new/changed JS, Python module parsing, `python -m pip check`,
  `node tests/client_audit.cjs`, `python tools/check_release.py`, and
  `git diff --check`: run. Git may print LF/CRLF normalization notices.
- Targeted event tests initially caught a missing confirmation flag in their
  admin-action fixture; the fixture now follows the real confirmation requirement.
- Earlier full suite: 228 passed before the final login/admin regressions were added.

Browser verification is performed on the separate preview database; screenshots
are local review artifacts. No real email, payment, destructive production action,
live account modification or Pi deployment is part of these checks. There is no
bundled production build step: the game serves JS/CSS files directly.

Actual phone-width browser checks verified tutorial topic selection, the displayed
32,659,200-money projection, claiming the three-resource alternative and both
buttons then locking, marking all events read, retained read history, grouped five
captures from one demo actor and the archived away earnings. The sampled flow
logged no console errors. Final UI refinements also passed six targeted DOM tests.

## G. Important files changed

- `player_events.py`: schema 24, event policy/emission, atomic presentation,
  recipient-scoped history and strategic-capture notifications.
- `static/player-events.js`: shared polling integration, grouping, bounded feedback,
  inbox history/read state and supported navigation/actions.
- `experience.py`, `static/experience.js`, `activity.py`, `runtime.py`: exact-episode
  acknowledgment, serialized collection and login/return lifecycle ordering.
- `expansion.py`, `app.py`, `features.py`: settlement guard, authoritative emitters,
  account-impact feedback and historical naval/air achievement checks.
- `daily_rewards.py`, `static/guided-help.js`: daily choices, projection and stable
  bundle selection; detailed navigable tutorial and deferred release notes.
- `migrations.py`, `config.py`, `index.html`, `static/product-ui.css`: safe backup
  target, release version, script wiring and consistent responsive surfaces.
- `tests/test_player_events.py`, existing UI/fixture/migration tests and CI:
  concurrency, authorization, persistence and interaction coverage.
- README, changelog, migration and privacy documents: behavior, retention and rollout.

## H. Data, deployment and remaining work

The original game.db hash remained
`56f889201e70eefc434d7aeb6812e38ef233b71e84c5e4b753e9d3199797534f`.
Local verification uses its own copied save. Schema 24 is additive; existing
ownership, balances, claims and research are not reset. Notification retention is
deliberately bounded and disclosed. See [migration notes](MIGRATIONS.md).

Before Pi rollout: create a verified private backup, stop wconquest, update the
checkout and runtime requirements, start the game (which migrates once), then run
the supplied Pi health check and verify login, map, away report, bell/history and
daily choices. Keep tunnel configuration unchanged. Rollback requires compatible
code and backup together while stopped and discards post-backup progress.

Remaining limits/priorities:

1. Verify actual Pi/WAN performance, school proxy trust and backup recovery under
   real operational load. Local tests do not establish a simultaneous-player limit.
2. Live email delivery/DNS and quota fallback still need provider setup/testing.
3. Some legacy generic informational emitters lack typed importance metadata;
   they remain safely in the feed. There is no guarantee of exactly-once visible
   delivery after a response is lost; history preserves the event instead.
4. Historical war-capture data is insufficient to safely reconstruct the disabled
   War Hero achievement. Reliable forward capture statistics and a deliberate
   migration/balance decision are needed; do not award it from unrelated wins.
5. Legacy JS wrapping, inline actions and username-based old battle logs remain
   technical debt. No broad rewrite or speculative historical data repair was made.
6. Browser checks sample representative flows; they are not every possible button,
   device, battle, assistive technology or production security scenario.

## I. Overall assessment

The requested paths have stronger persistence, consistent event feedback and
meaningful regression coverage. Duplicate away presentation is addressed at the
server transaction boundary, with clear failure semantics and preserved history.
Existing security controls remain; confirmed integrity weaknesses were corrected.
The game is improved and reviewable locally, but is not claimed bug-free, fully
secure, economically balanced at scale or already deployed to the Pi.
