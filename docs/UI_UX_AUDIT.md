# Application-wide interface audit

Baseline: 6.6.2. This work updates the existing Flask and polling client; no
unspecified v7 backend or SocketIO integration is introduced. Existing permissions,
game rules, save files and API contracts remain authoritative.

## Findings and implementation scope

| Surface | Problem found | Shared remedy / targeted change |
| --- | --- | --- |
| Desktop navigation | Eighteen destinations compete in a scrolling tab strip; labels differ between menus. | One route inventory, six logical groups, searchable navigation, active context and keyboard tab movement. |
| Mobile navigation and sheets | Separate menu definitions; dense cards, repeated headings and unclear return path. | Same route inventory as desktop, searchable grouped menu, consistent titles and close/focus behavior. |
| Map and territory | Dense action cards, icon-heavy buttons, hover-only context and tiny controls. | Shared card/action styles, wrapping action rows, visible labels, keyboard focus and readable hover information. |
| Country / buildings / wonders | Long mixed overview and advanced progression controls. | Clearer headings, consistent section spacing and collapsible advanced cards. |
| Research | Large focus tree and disabled actions with little explanation. | Consistent node states, explanatory disabled titles, responsive branches and progress labels. |
| Operations / battle planner / reports | Compact stats and inconsistent progress/action hierarchy. | Readable metrics, progress labels, touch targets and consistent report dialogs. |
| Market / stocks | Dense controls and competing links. | Shared form layout, explicit transaction labels and persistent action feedback. |
| Banks | Terms and requests mixed with long loan records. | Clear lender/request/repayment sections and validated, single-submission actions. |
| Trading / negotiation / gifts | Large resource matrix and chat composer; status often only a toast. | Responsive exchange rows, labeled inputs, inline request feedback and draft retention. |
| Factions / diplomacy | Dense membership, treaty and administration controls. | Shared hierarchy and action styles; advanced actions separated without deleting them. |
| Chat / notifications | Several close/action patterns and small notification controls. | Shared dialog accessibility, readable messages and consistent empty/status states. |
| Rewards / rankings / playtime | Inconsistent list/table density and terminology. | Unified typography, rows, empty states, selected states and responsive overflow. |
| Space | Progress, locked actions and many nested business/planet controls. | Shared progress semantics, legible cards and optional advanced sections. |
| Settings / account / recovery / two-factor | Unrelated cards in a long modal; duplicate recovery controls; inconsistent focus. | Grouped appearance, sound, account, supporter and information sections; one recovery flow; common dialog lifecycle. |
| Moderation / supporter management | Mixed consequential and routine actions with dense forms. | Clear labels, persistent status, form feedback; preserve server confirmation requirements. |
| Admin players / announcements / tools / world / factions / host / ads | Different tab patterns, compact tables and long configuration panels. | Accessible tabs, mobile selector, shared tables/forms and separate advanced/danger sections. |
| Live game editor | Large numeric forms and unsaved edits can be replaced by navigation. | Grouped fields, explicit save status, retained drafts, discard and leave safeguards. |
| Donation / ideas / tutorials / away and war alerts | Inconsistent dialog framing and keyboard behavior. | Shared dialog framing, focus containment and acknowledgement protection. |
| Login / signup / recovery | Placeholder-only fields, unclear tab names and malformed input markup. | Visible labels, clearer actions, native constraints and accessible errors. |
| Terms / privacy | Standalone presentation differs from the game. | Same design tokens, semantic page structure and clear current-page navigation. |

## Cross-cutting defects

- Legacy CSS mixes uppercase labels, gradients, small type and several spacing scales.
- Dynamic controls do not consistently have labels, focus, loading or error states.
- Dialog Escape handlers can target a dialog underneath the active one.
- Form handlers sometimes redraw on a failed request and discard typed values.
- Navigation is not a reliable record of all later-added modules and role restrictions.
- Some recovery and advanced controls repeat existing entry points.

The implementation uses shared interface tokens, route metadata, form helpers,
request feedback and dialog lifecycle code. Feature renderers retain their own game
logic. Advanced controls remain available through labeled disclosure sections.

## Verification limits

The user requested that browser connection attempts stop. Validation must therefore
use offline DOM tests, JavaScript syntax checks, static HTML checks and the existing
disposable-database regression suite. Do not report live browser, touch-device,
screen-reader or visual viewport testing as completed. Results and remaining
manual checks are recorded in the release report after implementation.
