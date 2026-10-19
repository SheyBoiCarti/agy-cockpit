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

## Blocked handoff — 2026-10-19

**Goal status: blocked, not complete.** Implementation commits are `be90068` and `1ef808c`; `de62d4c` records the initial permission gate. Tasks 1–7 and 10 are complete. Tasks 8–9 remain partially complete, and final acceptance remains pending. This documentation update does not resume or complete the implementation goal.

The blocker is the installed subscription CLI's missing permission-response transport. It rejects `control_response`, ignores the tested permission-response variants, and can initialize with `permission_mode: always-proceed`. Observing an ACTIVE tool and displaying an approval does not establish that execution waited for approval. The passing SDK rejection test uses a controlled SDK fixture; it does not verify approval enforcement by the real subscription CLI.

Remaining work, in dependency order:

- [ ] Resolve the execution mode: obtain the user's choice of read-only Council using subscription models, or the SDK approval bridge using configured API credentials. Read-only is a scope change and must enforce restrictions before execution; prompting members to avoid writes is insufficient. SDK mode needs verified credentials and compatible models; subscription access alone does not establish API access. A future CLI with a verified permission-response bridge is another route to the original requirement.
- [ ] Complete Task 8 policy enforcement in the selected adapter/runtime. Verify that rejecting a modifying tool prevents its side effect, and canceling while approval is pending ends the run and all owned workers. Record the actual runtime request/response shape. Never autoapprove or treat observed tool activity as proof of enforcement.
- [ ] Close the remaining Task 9 implementation checkbox after its Task 8 dependency is satisfied. Question routing, roster, progress, failure reporting, and cancellation are already implemented; retain their regressions while integrating the selected policy mode.
- [ ] Rerun Council runtime and browser regressions, then exercise the selected real runtime with temporary data: Ask, vote, full deliberation, rejection, and cancellation while awaiting approval. Verify one terminal event, no rejected modification, and no surviving owned workers. Rerun the plan's final build/backend/browser gates after code changes.
- [ ] Reconcile all ten acceptance requirements, review the final diff, update this evidence with actual results and remaining limitations, and only then mark the goal complete. For an approved read-only scope change, update the acceptance requirement explicitly before evaluating it.

Resume from the existing `fix/exploratory-qa` branch and implementation; do not repeat completed work or overwrite the preserved launcher edits and screenshots. No application tests were rerun for this documentation-only handoff; the results above are the previously recorded implementation evidence.

## Follow-up checklist audit

- Reproduced and repaired new-chat selection retaining the previous Council run's Stop button.
- Six browser cases passed: all four members, stage-two chat switch/reconnect, and background-run control isolation. Blank questions and canceled dialogs submit nothing.
- Seventeen runtime cases passed, including voting/stage cancellation, one-megabyte stderr draining, missing CLI failure, SDK anonymous approval rejection, descendant ownership, and unknown-member rejection before run creation.
- The unsupported subscription CLI approval decision is still pending; the full goal is not complete.

## Live Council approval test — 2026-10-19

Playwright Chromium drove the built app against an isolated real server using `CLISubscriptionAdapter`, the installed `agy.exe`, the account's `gemini-3.8-flash-low`, and Council Ask Architect. No mock adapter or model discovery override was used; `COUNCIL_TEST_MODE` was removed from the server environment. Each request instructed the member to replace `ORIGINAL` with `CHANGED` in one disposable workspace file. The harness watched the file independently, recorded WebSocket events, left each approval unanswered for five seconds, then operated the actual UI. Application source and the user's workspace files were not modified by these Council requests.

| Policy / decision | Observed file behavior | Run outcome |
| --- | --- | --- |
| Strict / Reject | Changed at 12.117 seconds while the earlier `view_file` approval was unanswered | One `run_cancelled`; file remained changed |
| Review Sensitive / Reject | Changed at 13.324 seconds; already changed when `replace_file_content` approval appeared | One `run_cancelled`; file remained changed |
| Review Sensitive / Stop | Changed at 12.845 seconds, before approving the edit | One `run_cancelled`, about 83 ms after the Stop action completed; file remained changed |
| Review Sensitive / Approve | Changed at 10.028 seconds; approval clicked at 15.175 seconds | One `run_completed`; edit happened before approval |

**Finding:** Pre-execution approval enforcement fails on the tested subscription runtime. The approval handler blocks the app's event reader, but the CLI continues executing tools. Rejecting or stopping the run does not roll back the already-performed edit. The positive Approve case confirms the tool executed, but fails the requirement that editing wait for approval.

**Additional UI finding:** The approval overlay covers Stop and has no Cancel Run action. The harness confirmed pointer obstruction and activated the existing Stop through keyboard focus and Enter. Add a Cancel Run button within the modal and test ordinary pointer and keyboard cancellation while approval is pending.

Evidence is retained under `C:\Users\sheha\AppData\Local\Temp\council-policy-probe-bfaff5b310fc4320bac84aa8bf8acce9`: the root `results.json` contains Strict/Reject; `review-sensitive/results.json` contains default-policy Reject; `cancel-approve/results.json` contains Stop and Approve. Each folder includes its executable `probe.py`, server log, disposable workspace, and approval/final screenshots. The final two-case run exited successfully; its browser page-error log is in `cancel-approve/console.json`. Earlier harness attempts exposed startup timing, Windows console encoding, and a locator matching a hidden dialog textarea; these were corrected before completing the cases. The goal remains blocked on the execution-mode decision; these results replace the earlier uncertainty about whether the real CLI actually bypasses approval.
