# Project Agent Instructions

## Mission

Re-innovate the project dashboard UI to be Apple-inspired: clean, premium, glass-like, minimal, consistent, and highly polished, while preserving and validating 100% of dashboard functionality, button mappings, routes, API endpoints, actions, and state behavior.

This is not just a visual redesign. The dashboard must remain fully functional after the redesign.

## Non-Negotiable Rules

1. Do not remove, rename, or break existing dashboard features unless a replacement is implemented and verified.
2. Do not change backend API contracts unless absolutely necessary. If changed, update all callers and tests.
3. Do not create fake placeholder functionality.
4. Do not leave dead buttons, unmapped actions, broken routes, broken links, or unused dashboard controls.
5. Do not rely only on visual inspection. Every dashboard action must be validated.
6. Do not copy Apple logos, trademarks, or proprietary assets. Use Apple-inspired visual principles only.

## Apple-Inspired Dashboard Design Direction

Redesign the dashboard with these principles:

- Minimal, premium, macOS-like visual language.
- Soft rounded cards and controls.
- Subtle shadows, depth, and layering.
- Translucent/glass material where appropriate.
- High contrast readability in both light and dark modes if the app supports themes.
- Smooth hover, active, pressed, focus, and disabled states.
- Consistent spacing, alignment, typography, and icon sizing.
- Clean sidebar/topbar/navigation layout.
- Dashboard cards should look unified, not randomly styled.
- Avoid clutter, harsh borders, inconsistent colors, oversized icons, or cheap-looking gradients.

Create or centralize design tokens where possible:

- radius
- spacing
- typography
- shadows
- blur/transparency
- colors
- button states
- card states
- navigation states

## Required Functional Validation

Before changing UI, inspect the current dashboard and create a complete mapping of:

- Dashboard pages/routes
- Dashboard cards
- Buttons
- Tabs
- Toggles
- Dropdowns
- Forms
- Links
- Navigation items
- API endpoints used by each component
- State variables and stores
- Event handlers
- Backend/service methods
- Expected result of each action

After redesign, verify every item still works.

## Required Implementation Process

### Phase 1: Audit

Inspect the project structure and identify:

- Frontend framework
- Dashboard entry points
- Routing system
- State management
- API client/services
- Existing design system or component library
- Test framework
- Build commands
- Lint commands

Create or update:

`docs/DASHBOARD_FUNCTIONALITY_AUDIT.md`

Include a table like:

| UI Element | File/Component | User Action | Handler | Route/API Endpoint | Expected Result | Verified |
|---|---|---|---|---|---|---|

### Phase 2: Redesign Plan

Before editing heavily, produce a concise implementation plan covering:

- Components to redesign
- Shared UI components to create/refactor
- Files to modify
- Risks to functionality
- Validation strategy

### Phase 3: UI Re-Innovation

Implement the Apple-inspired dashboard redesign.

Prefer reusable components:

- AppShell
- Sidebar
- TopBar
- DashboardCard
- StatCard
- ActionButton
- GlassPanel
- SegmentedControl
- StatusBadge
- SettingsPanel
- Modal/Dialog
- FormField

Make buttons and controls visually consistent.

Every interactive component must include:

- default state
- hover state
- active/pressed state
- focus-visible state
- disabled state
- loading state where applicable

### Phase 4: Functionality Preservation

For every dashboard feature:

- Ensure the click/action handler still points to the correct function.
- Ensure route navigation still works.
- Ensure API calls use the correct endpoint, method, payload, and headers.
- Ensure response handling and error handling still work.
- Ensure loading, success, empty, and error states are visible and polished.
- Ensure no button is visually present without working behavior.

### Phase 5: Endpoint Validation

Validate dashboard endpoints by checking:

- API client definitions
- route paths
- request methods
- payload shape
- response shape
- error handling
- authentication/session requirements

Where tests exist, extend them.
Where tests do not exist, add minimal smoke tests or integration tests.

### Phase 6: Verification

Run the available project checks. Discover the correct commands from the repo.

Common examples:

- npm run lint
- npm run test
- npm run build
- yarn lint
- yarn test
- yarn build
- pnpm lint
- pnpm test
- pnpm build
- dotnet build
- dotnet test
- pytest
- cargo test

Do not claim success unless commands were actually run.

If a command fails because of missing dependencies or environment issues, document the exact failure and what remains unverified.

## Required Final Report

When finished, provide:

1. Summary of design changes.
2. List of modified files.
3. Dashboard functionality mapping summary.
4. Endpoints validated.
5. Tests/checks run with results.
6. Any remaining risks or manual checks needed.

## Definition of Done

The task is done only when:

- Dashboard looks cohesive, premium, and Apple-inspired.
- All dashboard controls remain mapped to their intended functionality.
- All routes/navigation work.
- All endpoint calls are correct.
- Existing tests pass or failures are clearly explained.
- Build passes or failure is clearly explained.
- `docs/DASHBOARD_FUNCTIONALITY_AUDIT.md` is updated.
- No dead UI controls remain.