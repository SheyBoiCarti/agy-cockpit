# Exploratory fixes verification

Branch: `fix/exploratory-qa`.

## Implemented

- Visible workspace/upload/protocol errors; correlated prompt acceptance and rejection.
- Conversation-scoped drafts, attachments, upload activity, and pending submissions. Accepted attachments are cleared without losing newer edits.
- Canonical workspace/conversation/run recovery, all pending approvals, replay watermarks, and stale-run cleanup. Background run events retain their own chat's controls.
- Server-side saved model defaults and settings dialog synchronization.
- Responsive navigation/drawer overlays and focus management; rename controls occupy a separate flexible row.
- Served favicon and rebuilt bundled frontend.
- Async account model discovery with a 15-second timeout, coalesced refreshes, successful-result caching, explicit stale/unavailable states, and validation before runs.
- Explicit Council actions, runtime roster, attributed stage/member progress, honest vote/failure handling, cancellation, and owned process-tree cleanup.
- Stable run-scoped tool IDs and idempotent replay handling, including anonymous SDK call correlation.

## Evidence

- Baseline: 57 passed, 1 skipped.
- Latest backend/protocol/integration/Council/end-to-end suite: 90 passed, 1 skipped, with one existing dependency deprecation warning.
- Additional SDK anonymous-approval rejection test: passed; a rejected file modification did not occur. Domain/persistence follow-up: 15 passed. Final Council/runtime follow-up: 20 passed.
- Browser release suite: 24 passed in 135.89 seconds. Two additional missing/archived recovery cases passed afterward; the pending-draft acceptance case also passed in its targeted rerun. The legacy smoke test now uses the isolated readiness-checked fixture.
- Production build completed successfully. Existing large-bundle warnings remain.
- Independent review identified recovery, cross-chat state, anonymous policy IDs, and exited-parent process ownership problems; these were repaired and regression tests were added. The final focused review found no further important issue beyond the CLI approval limitation below.
- Real account discovery returned exactly Gemini 3.8 Flash High/Medium/Low, Claude Sonnet 4.6 Thinking, Claude Opus 4.6 Thinking, and GPT-OSS 120B Medium.
- Real Council vote completed with a correct 2 Approve / 1 Reject tally. Markdown-emphasized decision words are accepted; genuine error replies are rejected.
- Real Council deliberation completed independent analysis, peer critique, and final synthesis with visible progress.
- Real Council cancellation completed in 476 ms; no member processes remained under the test server.
- At 1440px with the drawer open, renaming had no selector overlap. At 1024px the rename field measured 680px with no model-selector overlap. At a 390px viewport the composer measured 356px.
- Screenshots: `.playwright-mcp/fixed-header-1024.png` and `.playwright-mcp/fixed-mobile.png`. No unexpected console errors were observed in the real verification session.

## Remaining acceptance decision

The installed subscription CLI explicitly rejects NDJSON `control_response` with “not supported yet”; permission-response variants are ignored. The inherited CLI adapter's observation of ACTIVE tools cannot prove pre-execution policy enforcement. This branch must not be described as satisfying the full Council approval requirement on that CLI.

The user has been asked to choose read-only Council with subscription models, or the SDK approval bridge when API credentials are available. That question remains pending. No tool permissions have been automatically broadened to conceal the limitation. The full implementation goal is blocked pending this decision; it must be resumed, implemented, and verified before completion can be claimed.

The original launcher edits and exploratory screenshots were preserved. Verification data for the real app was stored outside the repository under the system temporary directory.

## Follow-up checklist audit

- Reproduced and repaired new-chat selection retaining the previous Council run's Stop button.
- Six browser cases passed: all four members, stage-two chat switch/reconnect, and background-run control isolation. Blank questions and canceled dialogs submit nothing.
- Seventeen runtime cases passed, including voting/stage cancellation, one-megabyte stderr draining, missing CLI failure, SDK anonymous approval rejection, descendant ownership, and unknown-member rejection before run creation.
- The unsupported subscription CLI approval decision is still pending; the full goal is not complete.
