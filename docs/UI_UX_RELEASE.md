# 6.7.0 interface release report

## Result

The application uses a shared interface layer across all 18 primary destinations,
authentication, settings, dialogs, administration and policy pages. Game rules,
server authorization, APIs and save migration behavior are preserved.

## Usability changes

- Replaced the crowded horizontal menu strip with six groups and a menu search.
  Desktop and mobile derive their destinations, descriptions and permissions from
  the same inventory. Existing destinations remain reachable.
- Standardized Country, Resource market, Trading & gifts, Player banks, Stock
  exchange, Operations, Battle history, Rankings, Space program and administration
  names. The active destination is shown explicitly.
- Grouped Settings into appearance, sound, account, supporter and information
  categories, including two-factor and account recovery. Retained account controls
  when preferences refresh. The obsolete duplicate recovery form is hidden while
  its IDs remain compatible with older handlers.
- Moved advanced banner appearance and country actions into labeled disclosures.
  Existing action handlers and server-side confirmations are retained.
- Added draft tracking, explicit discard, keep/discard navigation choices and a
  browser unload warning. Failed requests retain typed data; delayed responses
  do not overwrite newer edits or mark them as saved.
- Added pending request deduplication, busy buttons and persistent inline feedback.
  Shared labels and numeric validation provide field-level help.
- Corrected the authenticator-code input location and semantic login, signup and
  recovery forms. Removed malformed input markup and clarified their actions.

## Shared implementation

- `static/interface.css`: common tokens, typography, spacing, buttons, fields,
  cards, tables, menus, status messages, dialogs and responsive rules. Existing
  feature CSS continues to provide specialized map and feature layouts.
- `static/interface.js`: one route inventory, role-aware search, keyboard menu
  handling, form labeling, draft lifecycle, request feedback and dialog behavior.
- `policies.py`: policy pages use the same tokens, headings and accessible navigation.
- `tests/interface.test.cjs`: offline DOM checks using jsdom and axe-core.
- `tests/ui_fixtures.py`: API-shaped test data from Flask's in-process test client
  and a disposable database. No HTTP server or live player save is used.

## Screen coverage

Audited and applied shared controls/styles to Territory, Country, Research,
Rewards & achievements, Operations, Battle history, Resource market, Trading &
gifts, Player banks, Stock exchange, Chat, Faction, Diplomacy, Rankings, Playtime,
Space program, Moderation and Game editor. The same components also cover the
offensive planner, casino, gift/negotiation dialogs, notifications, tutorial,
donation and ideas dialogs, return/war alerts, account security and all admin
sections, including advertisements, host tools and world controls.

## Accessibility and responsive behavior

Controls have associated labels and visible focus. Menu/settings/admin tabs support
arrow and Home/End navigation. Dialogs have names, focus containment and return;
Escape affects the top dialog and preserves mandatory acknowledgement and inactivity
restrictions. Shared text colors meet 4.5:1 contrast against the shared surfaces.
Important states include readable text rather than color alone. Layout rules cover
desktop, tablet, narrow phones and reduced-motion preferences; tables retain
horizontal scrolling and dense forms reflow.

## Executed validation

- **159 existing Python regression tests passed**, using disposable saves.
- **19 offline interface tests passed**: route/permission inventory; generated
  labels; desktop and mobile menu search; keyboard navigation; draft leave/return;
  duplicate pending requests; delayed failures; settings refresh; redraw recovery;
  inactivity overlays; nested dialog focus; recovery acknowledgement; validation;
  authentication markup; all production scripts initializing together; major
  feature renderers with real API-shaped fixtures; axe semantic checks; token
  contrast calculations.
- Existing JavaScript security/stale-response checks and JavaScript syntax checks
  passed. Python dependency compatibility and Git whitespace checks passed.
- CI now installs the locked development dependencies and runs the offline suite.
  The remote CI matrix has not been run as part of this local task.

## Remaining verification and limitations

The user explicitly requested no further browser connection attempts. No browser
was opened or connected to the game for this overhaul. jsdom verifies DOM behavior,
not rendered geometry. Real viewport screenshots, pointer/touch testing, screen-reader
announcements, actual map-provider behavior and browser-native form presentation
remain manual checks. Axe color-contrast evaluation is disabled in the DOM suite
because it cannot measure rendered colors there; shared token pairs are checked
separately with WCAG luminance calculations. This does not prove contrast for all
legacy inline colors or arbitrary host-configured colors.

The frontend still uses global feature functions and specialized legacy styles.
The shared layer improves their presentation and interaction without claiming a
complete component-framework rewrite. Any future new destination should be added
to the shared route inventory. No SocketIO backend was specified or introduced;
existing polling and notification behavior is retained.
