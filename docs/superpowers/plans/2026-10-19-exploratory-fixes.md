# Exploratory QA Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the exploratory UI defects, account model discovery, and AI Council execution defects while preserving SDK-native execution and authorization.

**Architecture:** Keep the React/Zustand frontend and FastAPI/WebSocket backend. Scope composer drafts to conversations, restore workspace metadata before rebuilding navigation, resolve model defaults on the server, and correlate failed commands with visible UI feedback. Use the existing pytest and Python Playwright tooling.

**Tech Stack:** React 19, TypeScript, Zustand, Tailwind CSS 4, FastAPI, SQLite, pytest, Python Playwright.

**Spec:** The confirmed exploratory findings in this conversation; the acceptance requirements below make that scope self-contained.

## Acceptance requirements

1. Files staged in chat A must never appear in or be sent from chat B. Returning to A restores its draft, including uploads that finished while B was selected.
2. Reloading or reconnecting restores the selected conversation, its workspace, sibling conversations, and enabled navigation. Missing or archived conversations recover to a usable workspace view.
3. New conversations use the saved default model unless the caller supplies an explicit valid model. Settings dialogs reflect server settings and canceled edits are discarded.
4. Invalid workspace paths, rejected uploads, and rejected prompts show actionable errors. Failed sends retain a recoverable draft and never masquerade as successful messages.
5. At widths 390, 768, 1024, 1280, and 1440 CSS pixels, chat, navigation, settings, and auxiliary panels remain usable without clipped controls or page-level horizontal scrolling. Conversation renaming must not overlap the model/policy selectors; the rename trigger, input, save, and cancel controls must remain reachable with auxiliary panels open or closed.
6. The favicon referenced by the served index returns 200 with an appropriate image content type.
7. Model selectors reflect successful `agy models` discovery for the current account. Discovery failure must never present a hardcoded list as verified access. Unavailable saved selections remain visible as unavailable and cannot silently become another model.
8. Council member questions route to the selected persona with a nonempty question. The roster reflects the actual configured participants: three voting/debating members plus a synthesis chair by default.
9. Council voting and all three deliberation stages publish real progress, preserve member attribution, report worker failures honestly, and obey Stop. Cancellation terminates owned workers and prevents subsequent stages within five seconds under normal local conditions; exactly one terminal run event is emitted.
10. Replayed tool events and repeated SDK-local tool IDs across runs never cause database uniqueness failures or mix tool output between runs.

## Global constraints

- Preserve token authentication, loopback binding, workspace restrictions, attachment ownership validation, and approval behavior.
- Keep protocol version 1; use existing commands/events and additive optional fields where needed.
- Keep Python >=3.11 and google-antigravity==0.1.16; add no production dependencies.
- Do not alter existing conversations' model selections when changing the default.
- Do not hardcode the account's current model access: on October 19 the CLI reported Gemini 3.8 Flash High/Medium/Low, Sonnet 4.6 Thinking, Opus 4.6 Thinking, and GPT-OSS 120B Medium. This is observed evidence, not a permanent allowlist or guarantee of remaining quota.
- Keep real credentials and model calls out of deterministic regression tests.
- Keep user data and browser-test data outside the source workspace during verification.
- Do not modify the user's existing launcher changes or delete exploratory evidence.
- Council execution must use the same workspace, model validation, tool policy, and approval requirements as ordinary runs. Never auto-approve tools to avoid an interactive worker stall.

## Review focus

- Upload finishes after chat switch: update only the originating draft (Task 2).
- Reload during an active run: resume events without duplicating messages or losing approvals (Task 3).
- Saved conversation was removed or archived: restore a workspace and clear invalid selection (Task 3).
- Settings arrive after initial render: opening the modal shows current server values (Task 4).
- Error arrives after switching chats: preserve its originating draft and identify the failed action (Task 1).

## Test setup and delivery

Extend `tests/backend/test_defect_remediation.py` for protocol/backend regressions. Create `tests/e2e/test_exploratory_regressions.py` and `tests/e2e/cockpit_browser_support.py` for browser regressions and shared server lifecycle helpers. Start an app on a free loopback port using a temporary workspace and data directory, an explicit test token, and an injected `MockAntigravityAdapter`; do not rely on an arbitrary startup sleep. Launch Chromium through `playwright.async_api`, wait for readiness and observable UI state, capture console/page errors, and terminate processes in fixture teardown. Extend the existing integration tests for favicon serving.

Each task follows a failing regression, minimal fix, focused verification cycle. Commit each independently passing task when implementing; do not commit generated SQLite files, uploads, or screenshots.

### Task 1: Show errors and preserve rejected sends

**Files:** Modify `agy_cockpit/frontend/src/services/websocket.ts`, `agy_cockpit/frontend/src/store/useCockpitStore.ts`, `agy_cockpit/frontend/src/components/Composer.tsx`, `agy_cockpit/frontend/src/components/Sidebar.tsx`, and `agy_cockpit/frontend/src/App.tsx`. Create `agy_cockpit/frontend/src/components/NoticeBanner.tsx`. Add regression cases in the browser test files above.

**Interfaces:** Add `UiNotice = { id: string; message: string; conversationId?: string }`, `addNotice(notice: UiNotice): void`, and `dismissNotice(id: string): void` to the store. Change `sendCommand(...): string | null` to return its request ID or null when disconnected. Track pending prompt submissions by request ID with originating conversation and optimistic message ID. Give `sendPrompt(...)` the same return contract; resolve pending submissions on matching `run_started` or `protocol_error`, adding request correlation to the server event if absent.

- [x] Add `test_action_errors_are_visible`: submit an invalid workspace path and unsupported upload; assert a visible `role="alert"` contains the reason, the app remains usable, and a successful retry works.
- [x] Add `test_rejected_prompt_restores_originating_draft`: induce ownership rejection, switch chats before delivering the error, and assert the failed optimistic message is removed or clearly marked failed, the original draft can be retried, and the other chat remains unchanged. Cover a disconnected send too.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/e2e/test_exploratory_regressions.py -k "action_errors or rejected_prompt" -v`; confirm the expected failures.
- [x] Implement the notice banner and correlation above. Convert HTTP upload error details to readable text with a status fallback; never render server messages as HTML. Keep diagnostics in the console as well. Rejected workspace opens must preserve the entered path for correction. Do not automatically retry agent prompts after reconnect.
- [x] Re-run the focused tests; require all to pass. Commit the deliverable.

### Task 2: Isolate composer drafts and asynchronous uploads

**Files:** Modify `agy_cockpit/frontend/src/components/Composer.tsx` and `agy_cockpit/frontend/src/store/useCockpitStore.ts`; extend the browser regressions. Update submission integration from Task 1.

**Interfaces:** Define `ComposerDraft = { text: string; attachments: AttachedFile[] }` and `draftsByConversation: Record<string, ComposerDraft>` in the store. Provide `setDraftText(conversationId: string, text: string): void`, `addDraftAttachment(conversationId: string, attachment: AttachedFile): void`, `removeDraftAttachment(conversationId: string, attachmentId: string): void`, and `clearDraft(conversationId: string): void`. Retain drafts only in memory, without persisting attachment metadata or document text to browser storage.

- [x] Add `test_attachment_drafts_are_isolated`: upload in A, create B, verify B has no staged file, switch to A, and verify its draft remains. Send from A and assert only A's attachment IDs are submitted.
- [x] Add `test_upload_finishes_in_originating_chat`: delay the upload response, switch to B, finish it, and assert only A gains the file. Include removal before send and text-draft isolation.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/e2e/test_exploratory_regressions.py -k "drafts_are_isolated or upload_finishes" -v`; confirm failures before implementation.
- [x] Replace component-wide draft state with the conversation-keyed interfaces. Capture the conversation ID at upload start; update that draft on completion. Keep transient menus and upload indicators scoped/reset on selection changes. Disable duplicate submissions while awaiting acceptance and clear only the accepted submission's draft, preserving any newer edits.
- [x] Re-run Tasks 1 and 2 browser regressions. Preserve backend ownership rejection as a defense; commit the deliverable.

### Task 3: Restore workspace navigation after reload/reconnect

**Files:** Modify `agy_cockpit/frontend/src/services/websocket.ts` and `agy_cockpit/frontend/src/store/useCockpitStore.ts`; extend backend and browser regressions. Modify `agy_cockpit/backend/ws/router.py` only if recovery metadata is unavailable through existing commands.

**Interfaces:** Use the snapshot conversation's `workspace_id`, `list_workspaces`, `open_workspace`, and `list_conversations`. Preserve `agy_active_conversation_id` and `agy_active_run_id` semantics. Workspace hydration must not overwrite a selected conversation or start another run.

- [x] Add `test_reload_restores_workspace_and_sibling_chats`: create A/B, select A, reload, and assert workspace path, both chats, A's messages, and enabled New Conversation. Repeat with a simulated socket disconnect/reconnect.
- [x] Add `test_recovery_missing_conversation` and `test_reload_during_run`: missing/archived IDs clear stale selection while retaining workspace navigation; an active mocked stream resumes with no duplicate messages and retains pending approval.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/e2e/test_exploratory_regressions.py -k "reload or recovery" -v`; confirm failures.
- [x] Hydrate workspace metadata on every connection, including branches that reopen a conversation or resume a run. Restore its workspace and siblings after the snapshot identifies ownership. Handle asynchronous response order explicitly so late list/snapshot events do not change the user's newer selection. On invalid selection, clear its stored run/conversation IDs and open the URL workspace or show the workspace picker.
- [x] Re-run focused browser tests and `tests/protocol/test_transport_and_security.py`; require restored navigation and unchanged authentication. Commit the deliverable.

### Task 4: Honor saved model defaults and synchronize settings

**Files:** Modify `agy_cockpit/backend/ws/router.py`, `agy_cockpit/backend/ws/protocol.py` if its creation default forces a value, and `agy_cockpit/frontend/src/components/SettingsModal.tsx`. Extend `tests/backend/test_defect_remediation.py` and browser regressions.

**Interfaces:** For `create_conversation`, an omitted `model_slug` resolves to `SettingsService`'s current `default_model`; an explicit valid slug wins. Keep `Sidebar.tsx` creation requests free of a hardcoded default. Task 7 replaces the catalog's permissive validation and hardcoded fallback; an unavailable saved default must require a new selection rather than silently selecting another model.

- [x] Add `test_new_conversation_uses_saved_default_model`: save Flash Low, create without a slug, and assert the persisted conversation uses Low. Assert explicit High remains High and changing defaults does not alter existing conversations.
- [x] Add `test_settings_modal_uses_current_values`: delay settings hydration, open the modal, assert persisted model/policy values, cancel edits, reopen, and assert canceled edits were discarded. Save Low and verify a new chat selects Low after reload.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/backend/test_defect_remediation.py -k default_model -v` and browser tests with `-k settings`; confirm failures.
- [x] Resolve creation defaults on the backend. Initialize modal edits on each closed-to-open transition from current store settings; refresh with delayed hydration only while the form is pristine. Do not overwrite dirty edits or reset unrelated policy values. Show save failure through Task 1's notice path; do not treat optimistic state as confirmed persistence.
- [x] Re-run focused tests and existing domain/persistence tests. Commit the deliverable.

### Task 5: Make navigation and auxiliary panels usable on narrow screens

**Additional confirmed defect:** Playwright reproduced rename/model overlap at desktop/tablet widths: at 1024px the input and model selector overlap by 146px and both rename action buttons fail pointer hit testing; at 1280px cancel is obstructed. At 1440px with the right drawer open, the selectors intercept clicks on the rename trigger. `Header.tsx` permits the title area to shrink with `min-w-0`, but its inner edit row/input retain their intrinsic width while the selector row also needs more room. Evidence: repository-root `qa-rename-overlap-1024.png` and `qa-rename-overlap-drawer.png`. The fix must account for available header width when a drawer opens, not just viewport width.

**Files:** Modify `agy_cockpit/frontend/src/App.tsx`, `agy_cockpit/frontend/src/components/Sidebar.tsx`, `agy_cockpit/frontend/src/components/Header.tsx`, `agy_cockpit/frontend/src/components/RightDrawer.tsx`, and `agy_cockpit/frontend/src/store/useCockpitStore.ts`; extend browser regressions.

**Interfaces:** Add `isSidebarOpen: boolean` and `setSidebarOpen(open: boolean): void`. Preserve `activeDrawerTab` behavior. Below 768px, show the sidebar as a dismissible overlay and auxiliary panels over the chat rather than beside it; at 768px and above preserve the desktop sidebar, using an overlay drawer below 1280px to leave sufficient chat width.

- [x] Add `test_responsive_navigation` parametrized over `(390, 844)`, `(768, 1024)`, and `(1440, 1000)`: open/select a chat, type, reach Send, change model, open/close every drawer tab, open settings, and dismiss overlays with Escape. Assert document scroll width is no larger than viewport width and composer width is at least 280px with overlays closed.
- [x] Add `test_rename_does_not_overlap_model_controls`, parametrized over widths 390, 768, 1024, 1280, and 1440 with the drawer open and closed. Enter rename mode using an ordinary Playwright click, type a long title, and assert the input/save/cancel bounding rectangles do not intersect model/policy selector rectangles. Click save and assert the new title persists after reopening the conversation; reopen edit mode and verify both cancel and Escape preserve the saved title. Require controls to pass pointer actionability without forced clicks. Include a long discovered model label from Task 7.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/e2e/test_exploratory_regressions.py -k responsive -v`; confirm the narrow-layout failures.
- [x] Add a labeled navigation toggle, wrapping/compact header controls, and overlay backdrops. Give the rename field an accessible label and its buttons explicit Save conversation name/Cancel rename names. Constrain the edit row/input to available width (`min-w-0` and flexible sizing), reserve space for action buttons, and move selectors to another row or use a focused rename dialog when the available chat-header width cannot fit them. Allow header height to grow if wrapping; do not hide controls behind selectors or fix this through stacking order alone. Make overlays fit the viewport, move focus inside on opening, restore focus on close, prevent keyboard focus entering obscured content, and close navigation after conversation selection. Give icon-only controls accessible names independent of badge counts.
- [x] Re-run the viewport and rename tests and manually inspect screenshots at all five widths, including settings, long titles/filenames, and an open drawer. Commit the deliverable.

### Task 6: Serve the referenced favicon

**Files:** Create `agy_cockpit/frontend/public/favicon.svg`; extend `tests/integration/test_frontend_serving.py`. Keep the existing `/favicon.svg` reference in `agy_cockpit/frontend/index.html`.

- [x] Add `test_favicon_serving`: GET `/favicon.svg`, assert 200, `image/svg+xml`, and SVG content rather than the SPA index. Run `.venv\Scripts\python.exe -m pytest tests/integration/test_frontend_serving.py -k favicon -v` and confirm failure.
- [x] Add a small static SVG using the existing app's visual identity; no generator or asset dependency is needed.
- [x] Run `npm --prefix agy_cockpit/frontend run build`, then the favicon integration test; require success against built assets. Follow existing Git tracking rules for generated static output. Commit the deliverable.

### Task 7: Discover actual account models without stale fallback options

**Evidence:** `ModelCatalogService.list_models()` returned the hardcoded list after 2.09 seconds; the same installed `agy models` command succeeded in 3.86 seconds. The fallback incorrectly includes Gemini 3.7 and 3.1 Pro and omits Opus 4.6 Thinking and GPT-OSS 120B Medium. Gemini 3.6 was absent from both observed lists. Exceptions are swallowed, the constructor seeds the cache with static entries, and `validate_model_slug()` currently accepts every nonempty slug.

**Files:** Modify `agy_cockpit/backend/services/model_catalog_service.py`, `agy_cockpit/backend/app.py`, `agy_cockpit/backend/ws/router.py`, `agy_cockpit/frontend/src/App.tsx`, `agy_cockpit/frontend/src/store/useCockpitStore.ts`, `agy_cockpit/frontend/src/types/models.ts`, `agy_cockpit/frontend/src/components/Header.tsx`, and `agy_cockpit/frontend/src/components/SettingsModal.tsx`. Inspect prompt/run model selection in `agy_cockpit/backend/services/agent_service.py` and modify its call sites if they bypass catalog validation. Create `tests/backend/test_model_catalog.py`; extend integration and browser regressions.

**Interfaces:** Keep the authenticated `/api/models` response's `models` array and add `status: 'ready' | 'stale' | 'unavailable'`, `error: string | null`, and `last_success_at: string | null`. Support explicit refresh via `/api/models?refresh=true`. Refactor the catalog to async `list_models(*, force_refresh: bool = False)` returning this result; update all callers. Use `asyncio.create_subprocess_exec` with the resolved CLI path, captured output, a 15-second timeout, and child termination/reaping on timeout. Use an async lock to coalesce concurrent refreshes, a 300-second successful-result TTL, and a 30-second failure retry interval. Cache only successful discovery in memory; do not seed it from `DEFAULT_MODELS` or frontend placeholders.

- [x] Add `test_model_discovery_accepts_slow_success`: simulate a CLI result taking four seconds, assert the configured timeout allows it, and assert the returned set exactly matches the six observed slugs above. Stub the clock/process rather than sleeping. Include tab/space separation, blank lines, progress/header lines, duplicate slugs, and an empty/malformed success response; only actual model rows may become options.
- [x] Add `test_model_discovery_failure_and_cache`: cover CLI missing, timeout, nonzero exit, and malformed output. With no successful cache, assert empty models and `unavailable`; with a previous success, assert the prior list is labeled `stale` with a visible error. Assert TTL expiry, failure retry interval, explicit refresh, and concurrent requests invoke discovery only once. Test timeout process cleanup and that a slow discovery does not block an unrelated health request.
- [x] Add `test_unavailable_model_is_rejected`: an explicit slug absent from a ready catalog is rejected for creation and prompt submission with a visible protocol error; no silent replacement, run creation, or model request occurs. If discovery is stale/unavailable, require successful refresh before starting a new model request. Preserve historical conversation metadata even when its model disappears. Verify omitted-slug creation still uses a valid saved default from Task 4.
- [x] Add `test_model_options_follow_discovery`: return the six-model fixture from `/api/models`; assert both selectors exclude Gemini 3.7/3.6/3.1 Pro and include Opus and GPT-OSS. Simulate failure on first load and after success; assert unavailable/stale messaging and a working Refresh models action. A saved model missing from the result must appear as a disabled unavailable selection, with Send disabled until the user selects an available model. Keep active runs controllable during catalog refresh/failure.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/backend/test_model_catalog.py -v` and `.venv\Scripts\python.exe -m pytest tests/e2e/test_exploratory_regressions.py -k "model_options or unavailable_model" -v`; confirm failures before implementation.
- [x] Implement async discovery, strict row parsing, deduplication, cache/status semantics, and backend validation. Never infer entitlement merely from a syntactically plausible slug. Keep raw CLI diagnostics in backend logs, with a concise error for the UI. Update the frontend to clear misleading bootstrap options, render discovery state, and refresh both selectors from the same store catalog; reuse Task 1's notices. An existing saved default remains unchanged until the user chooses a replacement.
- [x] Re-run catalog, model-default, integration, and browser regressions; require all to pass. Compare the running app's ready catalog with a fresh `agy models` result without invoking every model or assuming the account's current list is permanent. Commit the deliverable.

**Additional review condition:** Account access changes after a successful cache entry: refresh must remove revoked options, preserve historical titles/model metadata, flag unavailable saved selections, and leave active runs and approval controls intact. Covered by Task 7's cache and browser regressions.

## AI Council remediation

**Verified baseline:** A real vote completed in about 47 seconds with three attributed votes and a correct 2–1 tally. The Ask button submitted only `@Architect`, went through ordinary chat, and failed with `UNIQUE constraint failed: tool_executions.id`. A deliberation remained active after roughly three minutes; Stop recorded cancellation but did not stop the worker, requiring manual termination of the test-owned process tree. All seven existing Council tests passed because they exercise mock responses. The UI advertises six agents while `run_service.py` constructs three members and a separate synthesis chair. Evidence: `qa-council-cancel-stuck.png`.

**Execution order:** After Tasks 1–7, implement Tasks 8, 9, and 10 in order. Task 8 establishes worker lifecycle guarantees; Task 9 uses those interfaces for UI routing/progress. Task 10 removes the independently observed tool persistence failure. Do not infer that long deliberation alone proves a provider failure; the confirmed defects are missing progress and ineffective cancellation.

### Task 8: Make Council cancellation and worker failure handling reliable

**Files:** Modify `agy_cockpit/council/member.py`, `agy_cockpit/council/council.py`, and `agy_cockpit/backend/services/run_service.py`. Extend `tests/test_council.py`; create `tests/backend/test_council_runtime.py` for subprocess/protocol integration tests independent of the existing mock-mode fixture.

**Interfaces:** Add optional `cancellation_token: asyncio.Event | None = None` to `AICouncil.broadcast`, `chat_member`, `deliberate`, and `vote`, forwarding it to every `CouncilMember.chat`. Introduce `CouncilExecutionError(member_id: str, reason: str)`; cancellation propagates as cancellation, not a normal response. Add a configurable `member_timeout_seconds` with a 120-second default. Existing CLI callers continue to work without supplying cancellation.

- [ ] Add `test_council_cancel_stops_owned_workers`, parametrized for voting and deliberation stages 1/2/3. Use controlled fake workers with a descendant process, request cancellation, assert all owned processes are reaped within five seconds, subsequent stages are not launched, and exactly one `run_cancelled` event is emitted. Ensure unrelated processes remain untouched.
- [ ] Add `test_council_worker_failure_is_not_a_vote`: nonzero exit, empty result, malformed stream, member timeout, and missing CLI each produce an explicit failed member/run rather than a fabricated perspective, ABSTAIN vote, or consensus. Test large stderr output to prevent pipe deadlock and cleanup after a sibling worker fails.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/backend/test_council_runtime.py -v`; confirm failures before implementation.
- [ ] Pass the run cancellation token through the orchestrator, check it before every stage, cancel sibling tasks on failure, and clean up every process in `finally`. Read stderr concurrently with stdout; check exit codes and bound each call by the configured timeout. On Windows terminate only the owned process tree and reap it, with a short graceful attempt followed by forced termination within the five-second budget. Surface sanitized errors through Task 1. Remove implicit production mock success when the CLI is missing; keep mock responses available only through explicit test mode/injection.
- [ ] Preserve policy enforcement: inspect the installed CLI stream for approval/tool requests and ensure they reach the existing approval bridge. If the raw CLI route cannot support that bridge, route member calls through the existing agent adapter callbacks; do not leave hidden interactive prompts or bypass approvals. Add `test_council_approval_reject_and_cancel`: reject a modifying tool, then cancel while waiting for approval, and assert no modification occurs and workers exit. Document the verified runtime event shape in the test fixture.
- [ ] Re-run runtime tests and `tests/test_council.py`; require all to pass. Commit the deliverable.

### Task 9: Route Council questions and publish accurate roster/progress

**Files:** Modify `agy_cockpit/frontend/src/components/RightDrawer.tsx`, `agy_cockpit/frontend/src/services/websocket.ts`, `agy_cockpit/frontend/src/store/useCockpitStore.ts`, `agy_cockpit/frontend/src/types/protocol.ts`, `agy_cockpit/frontend/src/types/models.ts`, `agy_cockpit/backend/ws/protocol.py`, `agy_cockpit/backend/ws/router.py`, `agy_cockpit/backend/services/run_service.py`, and `agy_cockpit/council/council.py`. Extend Council runtime and browser regression files.

**Interfaces:** Add an optional `council_action` to `send_prompt` with `{ kind: 'ask' | 'vote' | 'deliberate'; member_id?: string }`; `prompt` contains the actual question/topic. Validate member IDs against the runtime roster. Keep `/council <topic>` and `/vote <motion>` working, but route both typed and panel actions through the same execution path. Add authenticated `GET /api/council` returning `{ members: [{ id, name, title, focus }], chair: { id, name, title, focus } }` from the same persona configuration used to instantiate the Council. Voting includes the three members, not the chair.

**Progress contract:** Publish replayable `council_progress` events with `conversation_id`/`run_id` in the envelope and `{ stage: 'ask' | 'vote' | 'analysis' | 'critique' | 'synthesis', member_id, state: 'running' | 'completed' | 'failed' | 'cancelled', text_delta?: string }` in the payload. Key frontend progress by run and member/stage, honoring existing replay deduplication. Wire existing stage/member/synthesis callbacks instead of simulating streaming after work has completed.

- [ ] Add `test_council_member_question_routing`: click Ask for each listed participant, enter a question in a labeled dialog, and assert the outgoing action identifies that member and only its worker executes. Canceling or entering whitespace sends nothing. Unknown member IDs are visibly rejected. Disable duplicate actions during a run and reject concurrent submissions server-side.
- [ ] Add `test_council_roster_and_progress`: assert the panel matches `/api/council`, distinguishes the chair from voters, and displays attributed live output through analysis, critique, and synthesis. Test switching chats and reconnecting during stage 2: no cross-chat output, duplicate tokens, lost progress, or incorrectly completed member badges.
- [ ] Add `test_council_vote_result_integrity`: three valid decisions produce the correct tally/outcome; malformed/error replies cannot silently become ABSTAIN. Verify each voting prompt uses that member's persona rather than instructing every member to act as the chair. Preserve explicit ABSTAIN and tie behavior.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/backend/test_council_runtime.py tests/e2e/test_exploratory_regressions.py -k council -v`; confirm the new cases fail.
- [ ] Implement the action/roster/progress contracts above using Task 8 cancellation and failure semantics, Task 7 model validation, and Task 1 notices. Present Ask as a real question dialog; obtain roster data from the backend instead of the six hardcoded cards. Retain completed stage results while later stages run; never label partial failure as successful consensus. Reject bare `/council` and `/vote` submissions without a topic rather than starting an unexpected default request.
- [ ] Re-run focused tests; require real pointer interactions and ordinary keyboard navigation, including the header layout from Task 5. Commit the deliverable.

### Task 10: Prevent duplicate tool-event persistence failures

**Files:** Modify `agy_cockpit/backend/services/agent_service.py`, `agy_cockpit/backend/services/run_service.py`, and `agy_cockpit/backend/db/repositories/tool_repository.py`; extend `tests/backend/test_defect_remediation.py` and Council runtime regressions. Avoid a schema migration if run-scoped persisted IDs can use the existing primary-key column.

**Interfaces:** At the run boundary, map each SDK-local tool ID to a stable persisted ID using `uuid.uuid5(uuid.NAMESPACE_URL, f'{run_id}:{sdk_tool_id}')`. Apply the mapping consistently to starts, logs, finishes, approval references, and subagent links. Missing SDK IDs require a per-invocation synthetic identity reused throughout that invocation, not the constant `tool`. A replayed start for the same invocation is idempotent; a repeated ID with conflicting tool identity is a visible error, never an overwrite.

- [x] First trace the failing event path using the original error and the adapter's `tool-{step_idx}-{tool_name}` construction. Add `test_tool_ids_are_scoped_to_run` using identical local IDs in two runs; assert distinct stored rows and correctly associated logs/approvals. Add `test_tool_start_replay_is_idempotent` and `test_missing_tool_ids_do_not_collide` with repeated events and multiple anonymous calls.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/backend/test_defect_remediation.py -k "tool_ids or tool_start_replay" -v`; confirm the relevant failures. Use evidence to distinguish repeated delivery from separate invocations before changing ID generation.
- [x] Implement the stable mapping and idempotent creation above. Preserve historical stored IDs, use primary-key conflict handling only for the same run/invocation, and prevent duplicate finish events from regressing terminal tool state. Do not broadly ignore integrity errors.
- [x] Re-run focused persistence tests and the Council Ask browser flow, including an approved/rejected mocked tool call; require no uniqueness failures and correct tool attribution. Commit the deliverable.

## Final verification and handoff

- [x] Build the frontend with `npm --prefix agy_cockpit/frontend run build`.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/backend tests/protocol tests/integration tests/e2e/test_end_to_end_scenarios.py -v`; require zero failures.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/e2e/test_exploratory_regressions.py tests/e2e/test_playwright_cockpit.py -v`; require zero failures and verify browser tests actually ran rather than skipped. Install the existing browser test extra and Chromium only if missing.
- [x] Repeat the original Playwright reproduction steps against freshly built assets using temporary data outside the repository. Confirm no unexpected page errors, favicon 404, or console-only failures for the tested actions.
- [x] Compare `/api/models` and both model selectors against a successful fresh `agy models` result; verify discovery failure is visible and never restores obsolete hardcoded options.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_council.py tests/backend/test_council_runtime.py -v`; require all to pass. In Playwright, repeat Ask, a real vote, a short full deliberation, and cancellation during active work using separate temporary data. Confirm no owned worker processes remain after cancellation/failure; record actual model/runtime limitations separately from mocked coverage.
- [ ] Review the diff for unrelated changes and check all ten acceptance requirements. Record command results, screenshots, and any untested limitations in the implementation handoff.

**Execution status:** Implementation is in progress on `fix/exploratory-qa`. Tasks 1–7 and 10 are implemented and verified. Their shared implementation is committed together as described below. Tasks 8–9 have worker ownership, cancellation, routing, roster, and progress implemented, but the installed subscription CLI explicitly rejects permission-response control messages. A user decision is pending on read-only subscription Council versus the SDK approval bridge with API credentials. Do not mark the full plan complete until that limitation is resolved and the final verification gates pass.

**Execution ruling:** Shared frontend/store/protocol changes will be committed together after verification, rather than producing intermediate task commits that cannot run independently. Anonymous SDK policy requests have no invocation IDs; preserve unique approval request IDs and leave their optional tool-execution link null instead of fabricating a shared identity.
