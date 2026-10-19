# Exploratory fixes verification

Branch: `fix/exploratory-qa`.

**Current status: complete.** The historical blocker below was resolved using native synchronous CLI hooks. See the final verification section for live approval results, remaining limitations, and the acceptance audit.

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

## Evidence before native hook remediation

- Baseline: 57 passed, 1 skipped.
- Pre-bridge backend/protocol/integration/Council/end-to-end suite: 90 passed, 1 skipped, with one existing dependency deprecation warning.
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

## Historical acceptance decision

The installed subscription CLI explicitly rejects NDJSON `control_response` with “not supported yet”; permission-response variants are ignored. The inherited CLI adapter's observation of ACTIVE tools cannot prove pre-execution policy enforcement. This branch must not be described as satisfying the full Council approval requirement on that CLI.

The user was asked to choose read-only Council with subscription models, or the SDK approval bridge when API credentials were available. Implementation was blocked at that point. No tool permissions were automatically broadened to conceal the limitation. The later user request to fix the reproduced bypass resumed implementation, and the native hook solution described below supersedes that choice.

The original launcher edits and exploratory screenshots were preserved. Verification data for the real app was stored outside the repository under the system temporary directory.

## Blocked handoff — 2026-10-19

**Historical goal status at handoff: blocked, not complete.** Implementation commits were `be90068` and `1ef808c`; `de62d4c` records the initial permission gate. Tasks 1–7 and 10 were complete. Tasks 8–9 were partially complete, and final acceptance was pending. The checklist below records what remained before the subsequent native hook remediation.

The blocker is the installed subscription CLI's missing permission-response transport. It rejects `control_response`, ignores the tested permission-response variants, and can initialize with `permission_mode: always-proceed`. Observing an ACTIVE tool and displaying an approval does not establish that execution waited for approval. The passing SDK rejection test uses a controlled SDK fixture; it does not verify approval enforcement by the real subscription CLI.

Historical remaining work, in dependency order (resolved by the final verification below):

- Resolve the execution mode. The initially offered choices were read-only subscription Council or the SDK with API credentials. The subsequent native hook solution preserves the original subscription scope and supersedes that choice.
- Complete Task 8 policy enforcement, proving rejection prevents modification and cancellation stops workers while approval is pending.
- Close the dependent Task 9 implementation checkbox while retaining its routing/roster/progress regressions.
- Rerun the release gates and real Ask/vote/deliberation/rejection/cancellation flows, recording side effects and terminal events.
- Reconcile all ten acceptance requirements and document actual evidence before completing the goal.

The documentation-only handoff preserved the existing branch, launcher edits, and screenshots and did not rerun application tests. Implementation subsequently resumed on that branch; the final section records the fresh tests.

## Follow-up checklist audit

- Reproduced and repaired new-chat selection retaining the previous Council run's Stop button.
- Six browser cases passed: all four members, stage-two chat switch/reconnect, and background-run control isolation. Blank questions and canceled dialogs submit nothing.
- Seventeen runtime cases passed, including voting/stage cancellation, one-megabyte stderr draining, missing CLI failure, SDK anonymous approval rejection, descendant ownership, and unknown-member rejection before run creation.
- At this audit, the unsupported subscription CLI approval decision was pending; the later native hook bridge resolves it.

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

Evidence is retained under `C:\Users\sheha\AppData\Local\Temp\council-policy-probe-bfaff5b310fc4320bac84aa8bf8acce9`: the root `results.json` contains Strict/Reject; `review-sensitive/results.json` contains default-policy Reject; `cancel-approve/results.json` contains Stop and Approve. Each folder includes its executable `probe.py`, server log, disposable workspace, and approval/final screenshots. The final two-case run exited successfully; its browser page-error log is in `cancel-approve/console.json`. Earlier harness attempts exposed startup timing, Windows console encoding, and a locator matching a hidden dialog textarea; these were corrected before completing the cases. At this point the goal remained blocked; the following implementation resolves the reproduced failure.

## Final native hook remediation and verification — 2026-10-19

The user requested the fix after the live failure. The installed CLI's synchronous `PreToolUse` hook provides a separate supported permission mechanism despite the unsupported NDJSON control responses. Its documented input is camelCase `{ toolCall: { name, args }, stepIdx }`; it blocks until the command returns `{ decision: "allow" | "deny" }`. A real denial spike verified this behavior. Source: [Google lifecycle hooks documentation](https://antigravity.google/docs/hooks), also shipped with this CLI under `builtin/skills/agy-customizations/docs/hooks.md`.

The adapter now creates a temporary child customization directory, passes approval requests and full arguments through an atomic-file bridge, and waits for browser approval before returning allow. Known read tools can proceed; other tools, including unfamiliar tool names, request approval. Failure, rejection, and cancellation deny execution. The popup has a visible Cancel Run button targeting its approval's run. Worker teardown also finalizes tools observed only by the hook. Temporary configuration is removed without editing existing hooks or subscription settings. Explicit Always Proceed remains an intentional auto-approval setting.

Before launching any protected workspace turn, the exact CLI executable must pass a disposable-file native denial check: initialized hook, actual denied-tool ERROR event, unchanged file, and successful process exit. Success is cached for that executable's path/file identity and invalidated by an executable change. Cancellation interrupts this check or waiting for it. An unsupported CLI therefore never receives the actual workspace turn; checking ACTIVE telemetry alone is insufficient.

Fresh real Playwright results using `gemini-3.8-flash-low` and the production subscription adapter, including the startup safety check:

| Case | After five seconds awaiting approval | Final file | Terminal outcome |
| --- | --- | --- | --- |
| Review Sensitive / Reject | ORIGINAL | ORIGINAL | One run_cancelled, about 217 ms after the action |
| Review Sensitive / Cancel Run by pointer | ORIGINAL | ORIGINAL | One run_cancelled, about 145 ms after the action |
| Review Sensitive / Approve | ORIGINAL | CHANGED after approval | One run_completed |
| Strict / Reject | ORIGINAL | ORIGINAL | One run_cancelled, about 322 ms after the action |

The approved file changed at 18.577 seconds, after approval completed at 18.475 seconds. No page errors or leftover hook directories were observed. A real three-member vote completed in 28.337 seconds; real deliberation completed analysis, peer critique, and synthesis in 60.672 seconds, with all expected attributed progress and one completion each. No tool permissions were broadened to achieve these results.

Final release gates:

- `npm --prefix agy_cockpit/frontend run build`: passed, existing large-bundle warning.
- `.venv/Scripts/python.exe -m pytest tests/backend tests/protocol tests/integration tests/test_council.py tests/e2e/test_end_to_end_scenarios.py -q`: 104 passed, 1 existing skip, 1 existing dependency deprecation warning.
- `.venv/Scripts/python.exe -m pytest tests/e2e/test_exploratory_regressions.py tests/e2e/test_playwright_cockpit.py -q`: 32 passed in 201.11 seconds. Includes pointer and keyboard Cancel Run from the modal. An initial test incorrectly expected Send to be enabled with an empty composer; its assertion was corrected to enter a new draft, then the complete suite passed.
- Eight bridge regressions cover actual standalone-hook subprocesses and side effects, missing bridge denial, unknown tools, read tools, unsupported CLI mutation before ACTIVE, cancellation with no ACTIVE event, and setup cleanup/error reporting. The new regressions reproduced failures before their fixes.
- Independent review found missing pre-spawn capability verification and incomplete hook-only tool cleanup; failing regressions confirmed both, and both were repaired. Follow-up review found no remaining critical/important issue. Its minor setup-error masking finding was also reproduced and fixed.
- The original local app was idle before restart; it now serves the updated bundle on port 8080. Health returned 200 and account model discovery returned ready with six models. Existing app data and launcher edits were preserved.

Final acceptance audit:

| Requirement | Evidence |
| --- | --- |
| 1. Isolated drafts/uploads/submissions | Browser isolation, late upload, acceptance/rejection regressions |
| 2. Workspace/chat/run/approval recovery | Reload, reconnect, missing/archived conversations, stage-two recovery regressions |
| 3. Saved model defaults/settings | Backend default and browser settings synchronization regressions |
| 4. Visible errors and recoverable drafts | Protocol/upload/workspace/rejected-prompt regressions |
| 5. Responsive layout and rename | Five viewport regressions and prior real drawer measurements |
| 6. Favicon | Passing browser smoke regression and prior real HTTP verification |
| 7. Account model availability | Catalog tests, selector regressions, fresh ready six-model catalog after restart |
| 8. Explicit Council questions/accurate roster | Four-member browser routing cases, runtime roster tests, real Ask with modifying tool |
| 9. Progress/cancel/failure/policy enforcement | Runtime subprocess tests, stage-two browser recovery, four live approval cases, real vote/full deliberation |
| 10. Run-scoped/idempotent tools | Persistence/replay regressions and real tool executions without duplicate-ID failures |

Remaining limitations: the installed CLI still lacks the NDJSON permission-response protocol; the implementation uses verified native hooks instead. A CLI/model/network failure during the initial safety check blocks the workspace turn with an actionable error and can be retried. This verification establishes the tested installed runtime, not OS isolation against arbitrary user-approved commands. No requested implementation item remains pending.

Final evidence directory: `C:\Users\sheha\AppData\Local\Temp\council-policy-fixed-verified`. It contains `probe.py`, `results.json`, per-case approval/final screenshots, `console.json`, `actions.py`, `actions-results.json`, vote/deliberation screenshots, and server logs. The earlier `council-policy-fixed` directory preserves the first successful live run before review hardening. These are temporary local artifacts, not bundled application data.
