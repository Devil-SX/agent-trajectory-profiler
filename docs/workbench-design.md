# Workbench interaction design

The task workspace keeps session identity, selected task scope and view controls together. Its six compact metrics describe the selected task and descendants, or explicitly describe the whole session when no task is selected. The full metric disclosure uses the same descriptor and formatting functions. Missing counters, unknown human provenance, partial costs and parent-inclusive attribution retain their domain meanings.

Task search remains visible inside the task panel. A single task-filter disclosure owns its project, dates, directory, status and sorting. Active filter chips can clear individual values. The authenticated session listing applies filters and sorting before pagination; the browser renders that response without a second filter or reordering pass. Filter values and disclosure state persist in the existing workspace record. Opening disclosures does not fetch data.

Background analysis uses a compact status disclosure with visible completed, running and failed states. Its drawer retains per-session progress, failure explanations and the authenticated resume operation. Existing idempotent submission and resume behavior remains in the service domain. Task views preserve selection and tree expansion. Raw operation bodies remain lazy and pinned to source revision.

## Visual references

Verified 2026-10-20, official React Bits repository revision `e12c22192ac7b4b452c5e2feb9b586d74765d696`:

- [Pill Nav](https://reactbits.dev/components/pill-nav): selection indicator and focus feedback.
- [Animated Content](https://reactbits.dev/animations/animated-content): short content arrival transition.
- [Animated List](https://reactbits.dev/components/animated-list): visible selection and keyboard navigation.
- [Pinned license](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/LICENSE.md): MIT with Commons Clause License Condition v1.0, copyright 2026 David Haz. This is not unqualified MIT licensing.

These are interaction references. This workbench independently implements native HTML disclosures, CSS transitions and keyboard handlers; no React Bits component, source code or stylesheet is copied or redistributed. It adds no React, animation library, continuous animation loop or dynamic background. Reduced-motion settings disable transitions and content animations. Loading skeletons preserve the existing reduced-motion treatment.

The research view is a separate authenticated component. Its script, stylesheet and saved study data load only when the research tab is first selected. It owns research-specific filters and does not change the task workspace's session filters or submit model requests.

## Control scope and persistent navigation

The site shell contains only identity, service links and the seven main tabs. Its sticky height is measured from the rendered shell and feeds scroll padding, panel anchors and mobile task context placement. Local controls are actual descendants of their owning tabpanel. Task search, dates, project, directory, status, ordering, selection and batch actions belong to task analysis. Research controls remain inside the research component. Coverage exposes refresh and has no ineffective date or project filters.

Overview, human trends, daily trends and detail views reuse a single statistics-filter component, moved into the selected panel. Each view persists its own project/date/disclosure scope; task and research state are separate. A bounded response cache reuses the same date-scoped overview read across views without transferring filter state. Returning to another scope restores its own data, or loads that scope. Click and keyboard navigation update browser history; back navigation restores the selected view and its local conditions.

Human metrics use the domain coverage status. Positive values with missing measurement contributions are labelled as known subtotals, and a missing contribution count is not described as a missing interaction count. Observed zero remains distinct from unavailable human provenance.

## Duration display

The `trajectory-format` script in the dashboard owns `window.TrajectoryFormat.duration(seconds)`. Dashboard and research use this one formatter for human-facing summaries, tables, task metrics, flame labels and request elapsed times. Numeric API/CSV seconds and chart geometry remain unchanged. Missing, nonfinite and negative inputs display unknown; observed zero displays `0s`. Positive subsecond values retain nonzero milliseconds. Seconds round before hour/minute carry, with no decimal hours or redundant zero units; long durations retain accumulated hours such as `25h1min1s`.
