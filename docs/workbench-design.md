# Workbench interaction design

The task workspace keeps session identity, selected task scope and view controls together. Its six compact metrics describe the selected task and descendants, or explicitly describe the whole session when no task is selected. The full metric disclosure uses the same descriptor and formatting functions. Missing counters, unknown human provenance, partial costs and parent-inclusive attribution retain their domain meanings.

Search remains visible. A single filter disclosure owns project, dates, directory, status and sorting. Active filter chips can clear individual values. The authenticated session listing applies filters and sorting before pagination; the browser renders that response without a second filter or reordering pass. Filter values and disclosure state persist in the existing workspace record. Opening disclosures does not fetch data.

Background analysis uses a compact status disclosure with visible completed, running and failed states. Its drawer retains per-session progress, failure explanations and the authenticated resume operation. Existing idempotent submission and resume behavior remains in the service domain. Task views preserve selection and tree expansion. Raw operation bodies remain lazy and pinned to source revision.

## Visual references

Verified 2026-10-20, official React Bits repository revision `e12c22192ac7b4b452c5e2feb9b586d74765d696`:

- [Pill Nav](https://reactbits.dev/components/pill-nav): selection indicator and focus feedback.
- [Animated Content](https://reactbits.dev/animations/animated-content): short content arrival transition.
- [Animated List](https://reactbits.dev/components/animated-list): visible selection and keyboard navigation.
- [Pinned license](https://github.com/DavidHDev/react-bits/blob/e12c22192ac7b4b452c5e2feb9b586d74765d696/LICENSE.md): MIT with Commons Clause License Condition v1.0, copyright 2026 David Haz. This is not unqualified MIT licensing.

These are interaction references. This workbench independently implements native HTML disclosures, CSS transitions and keyboard handlers; no React Bits component, source code or stylesheet is copied or redistributed. It adds no React, animation library, continuous animation loop or dynamic background. Reduced-motion settings disable transitions and content animations. Loading skeletons preserve the existing reduced-motion treatment.

The research view is a separate authenticated component. Its script, stylesheet and saved study data load only when the research tab is first selected. It owns research-specific filters and does not change the task workspace's session filters or submit model requests.
