import { PROTOCOL_VERSION, ClientCommand, ServerEvent } from '../types/protocol';
import { useCockpitStore } from '../store/useCockpitStore';

export interface CouncilAction { kind: 'ask' | 'vote' | 'deliberate'; member_id?: string }

class WebSocketService {
  private replayFloorByRun = new Map<string, number>();
  private latestWorkspaceRequest: string | null = null;
  private conversationRequests = new Map<string, string>();
  private pendingPrompts = new Map<string, { conversationId: string; prompt: string; attachmentIds: string[]; draft: string }>();
  private ws: WebSocket | null = null;
  private sessionId: string;
  private token: string = '';
  private reconnectTimeout: any = null;
  private reconnectAttempts = 0;
  private maxReconnectDelay = 10000;
  private pingInterval: any = null;
  private processedSequencesByRun = new Map<string, Set<number>>();

  constructor() {
    // Generate or load session ID
    let storedSession = sessionStorage.getItem('agy_session_id');
    if (!storedSession) {
      storedSession = crypto.randomUUID();
      sessionStorage.setItem('agy_session_id', storedSession);
    }
    this.sessionId = storedSession;

    // Load token from URL param or storage
    const params = new URLSearchParams(window.location.search);
    this.token = params.get('token') || localStorage.getItem('agy_token') || '';
    if (this.token) {
      localStorage.setItem('agy_token', this.token);
    }
  }

  public setToken(token: string) {
    this.token = token;
    localStorage.setItem('agy_token', token);
    this.reconnect();
  }

  public connect() {
    if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
      return;
    }

    const store = useCockpitStore.getState();
    store.setConnectionState(this.reconnectAttempts > 0 ? 'recovering' : 'connecting');

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    // Use window.location.host, or proxy port 8000 in dev
    const host = window.location.port === '3000' ? '127.0.0.1:8000' : window.location.host;
    const url = `${protocol}//${host}/ws?token=${encodeURIComponent(this.token)}&session_id=${encodeURIComponent(this.sessionId)}`;

    try {
      this.ws = new WebSocket(url);
    } catch (e: any) {
      store.setConnectionState('error', e.message);
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = this.handleOpen.bind(this);
    this.ws.onmessage = this.handleMessage.bind(this);
    this.ws.onerror = this.handleError.bind(this);
    this.ws.onclose = this.handleClose.bind(this);
  }

  private handleOpen() {
    this.reconnectAttempts = 0;
    const store = useCockpitStore.getState();
    store.setConnectionState('connected', null);

    // Send Hello handshake
    this.sendCommand('hello', {});
    this.sendCommand('list_workspaces', {});

    // Start ping interval
    if (this.pingInterval) clearInterval(this.pingInterval);
    this.pingInterval = setInterval(() => {
      this.sendCommand('ping', {});
    }, 25000);

    if (store.activeConversationId) {
      this.sendCommand('open_conversation', { conversation_id: store.activeConversationId });
    } else {
      const params = new URLSearchParams(window.location.search);
      const initialWorkspace = params.get('workspace');
      if (initialWorkspace) {
        this.sendCommand('open_workspace', { canonical_path: initialWorkspace });
      } else {
        this.sendCommand('list_workspaces', {});
      }
    }
  }

  private handleMessage(event: MessageEvent) {
    try {
      const serverEvent: ServerEvent<any> = JSON.parse(event.data);
      this.routeEvent(serverEvent);
    } catch (err) {
      console.error('[WS] Error parsing message:', err);
    }
  }

  private routeEvent(event: ServerEvent<any>) {
    const store = useCockpitStore.getState();

    // Monotonic sequence check for replayable events per run
    if (typeof event.sequence === 'number') {
      const runKey = event.run_id || 'global';
      if (event.sequence <= (this.replayFloorByRun.get(runKey) || 0)) return;
      let seqSet = this.processedSequencesByRun.get(runKey);
      if (!seqSet) {
        seqSet = new Set<number>();
        this.processedSequencesByRun.set(runKey, seqSet);
      }
      if (seqSet.has(event.sequence)) {
        // Drop duplicate replay
        return;
      }
      seqSet.add(event.sequence);
      store.setLastSequence(event.sequence);
    }

    switch (event.type) {
      case 'hello_ack':
        if (event.payload?.session_id) {
          this.sessionId = event.payload.session_id;
          sessionStorage.setItem('agy_session_id', this.sessionId);
        }
        if (event.payload?.default_model || event.payload?.policy_preset) {
          store.setSettings({
            default_model: event.payload.default_model,
            policy_preset: event.payload.policy_preset,
          });
        }
        break;

      case 'workspace_list':
        if (event.payload?.workspaces) {
          store.setWorkspaces(event.payload.workspaces);
          const conversation = store.conversations[store.activeConversationId || ''];
          if (conversation) {
            store.setActiveWorkspaceId(conversation.workspace_id);
            this.sendCommand('list_conversations', { workspace_id: conversation.workspace_id });
          }
        }
        break;

      case 'workspace_opened':
        if (event.payload?.workspace) {
          const ws = event.payload.workspace;
          if (event.payload.request_id && event.payload.request_id !== this.latestWorkspaceRequest) break;
          const current = store.conversations[store.activeConversationId || ''];
          if (current && current.workspace_id !== ws.id) store.setActiveConversationId(null);
          store.setWorkspaces([ws]);
          store.setActiveWorkspaceId(ws.id);
          this.sendCommand('list_conversations', { workspace_id: ws.id });
        }
        break;

      case 'conversation_list':
        if (event.payload?.conversations && (!event.payload.workspace_id || event.payload.workspace_id === store.activeWorkspaceId)) {
          store.setConversations(event.payload.conversations);
        }
        break;

      case 'conversation_created':
        if (event.payload?.conversation) {
          store.addConversation(event.payload.conversation);
          // Creating a chat selects it, just like clicking an existing chat.
          // Do not retain the previous conversation's Stop/approval controls.
          store.setActiveConversationId(event.payload.conversation.id);
        }
        break;

      case 'conversation_snapshot':
        if (event.payload?.conversation) {
          const conversation = event.payload.conversation;
          // A late snapshot must never select a chat the user has left.
          if (conversation.id !== store.activeConversationId) break;
          if (conversation.is_archived) { store.setActiveConversationId(null); this.sendCommand('open_workspace', { workspace_id: conversation.workspace_id }); break; }
          if (event.payload.workspace) store.setWorkspaces([event.payload.workspace]);
          if (event.payload.conversations) store.setConversations(event.payload.conversations);
          store.addConversation(conversation);
          store.setActiveWorkspaceId(conversation.workspace_id);
          if (event.payload.messages) {
            store.setMessages(event.payload.conversation.id, event.payload.messages);
          }
          if (event.payload.artifacts) {
            store.setArtifacts(event.payload.artifacts);
          }
          if (event.payload.active_run) {
            store.startRun(event.payload.active_run);
            const sync = event.payload.sync_state;
            const runId = event.payload.active_run.id;
            if (sync) {
              store.applySyncState(sync);
              this.replayFloorByRun.set(runId, sync.last_sequence);
              this.processedSequencesByRun.delete(runId);
              store.clearCouncilProgress(runId);
              for (const progress of sync.council_events || []) store.updateCouncilProgress(runId, conversation.id, progress);
            }
            this.sendCommand('resume_run_stream', { conversation_id: conversation.id, run_id: runId, after_sequence: sync?.last_sequence || 0, last_seen_sequence: sync?.last_sequence || 0 });
          } else store.clearConversationRun(conversation.id);
        }
        break;

      case 'conversation_archived':
        if (event.payload?.conversation_id) {
          store.updateConversation(event.payload.conversation_id, { is_archived: true });
        }
        break;

      case 'run_started': {
        const requestId = event.payload.request_id;
        const pending = this.pendingPrompts.get(requestId);
        if (pending) {
          store.addMessage({ id: event.payload.user_message_id, conversation_id: pending.conversationId, role: 'user', author_time: event.payload.started_at, content: pending.prompt, attachment_ids: pending.attachmentIds });
          const draft = store.draftsByConversation[pending.conversationId];
          if (draft && pending.draft) {
            const submitted = JSON.parse(pending.draft);
            if (draft.text === submitted.text) store.setDraftText(pending.conversationId, '');
            for (const attachmentId of pending.attachmentIds) store.removeDraftAttachment(pending.conversationId, attachmentId);
          }
          store.setPendingSubmission(pending.conversationId, null);
          this.pendingPrompts.delete(requestId);
        }
        store.startRun({
          id: event.payload.run_id,
          conversation_id: event.payload.conversation_id,
          user_message_id: event.payload.user_message_id,
          state: 'queued',
          started_at: event.payload.started_at,
        });
        break;

      }
      case 'reasoning_delta':
        store.appendReasoning(event.conversation_id || '', event.payload.delta, event.sequence);
        break;

      case 'token_delta':
        store.appendToken(event.conversation_id || '', event.payload.delta, event.sequence);
        break;

      case 'tool_started':
        store.toolStarted(
          event.conversation_id || '',
          event.payload.tool_execution_id,
          event.payload.sdk_tool_name,
          event.payload.args,
          event.sequence
        );
        break;

      case 'tool_log':
        store.appendToolLog(
          event.payload.tool_execution_id,
          event.payload.chunk,
          Boolean(event.payload.is_stderr)
        );
        break;

      case 'tool_finished':
        store.toolFinished(
          event.conversation_id || '',
          event.payload.tool_execution_id,
          event.payload.success,
          event.payload.output_summary,
          event.sequence
        );
        break;

      case 'approval_required':
        store.setPendingApproval({
          id: event.payload.approval_request_id,
          run_id: event.run_id || '',
          sdk_tool_name: event.payload.sdk_tool_name,
          args: event.payload.args,
          reason: event.payload.reason,
        });
        break;

      case 'approval_resolved':
        store.dequeueApproval(event.payload.approval_request_id);
        break;

      case 'file_changed':
        store.fileChanged({
          path: event.payload.file_path,
          status: event.payload.status,
          run_id: event.payload.run_id,
        });
        break;

      case 'file_diff_data':
        store.setSelectedDiffFile(event.payload.file_path, {
          original: event.payload.original_content,
          modified: event.payload.modified_content,
          language: event.payload.language,
          is_binary: event.payload.is_binary,
          truncated: event.payload.truncated,
        });
        break;

      case 'council_progress':
        store.updateCouncilProgress(event.run_id || '', event.conversation_id || '', event.payload);
        break;

      case 'subagent_update':
        if (event.conversation_id && event.conversation_id !== store.activeConversationId) break;
        store.subagentUpdated({
          id: event.payload.id,
          parent_id: event.payload.parent_id,
          name_or_role: event.payload.name_or_role,
          state: event.payload.state,
          current_activity: event.payload.current_activity,
          depth: event.payload.depth,
        });
        break;

      case 'artifact_created':
      case 'artifact_updated': {
        const artData = event.payload?.artifact || event.payload;
        if (artData?.id || artData?.artifact_id) {
          store.artifactCreated({
            id: artData.id || artData.artifact_id,
            kind: artData.kind,
            name: artData.name,
            mime_type: artData.mime_type,
            preview_supported: artData.preview_supported,
            size_bytes: artData.size_bytes,
          });
        }
        break;
      }

      case 'run_completed':
        store.finalizeRun(
          event.payload.run_id,
          event.conversation_id || '',
          'completed',
          event.payload.completed_at,
          undefined,
          undefined,
          event.payload.usage
        );
        break;

      case 'run_cancelled':
        store.finalizeRun(
          event.payload.run_id,
          event.conversation_id || '',
          'cancelled',
          event.payload.cancelled_at
        );
        break;

      case 'run_failed':
        store.finalizeRun(
          event.payload.run_id,
          event.conversation_id || '',
          'failed',
          event.payload.failed_at,
          event.payload.error_code,
          event.payload.error_message
        );
        break;

      case 'sync_state':
        store.applySyncState(event.payload);
        break;

      case 'workspace_search_results':
        store.setMentionSearch(
          store.mentionQuery,
          (event.payload.results || []).map((r: any) => ({
            path: r.path,
            is_directory: r.is_directory ?? (r.type === 'directory'),
          })),
          false
        );
        break;

      case 'settings_updated':
        if (event.payload?.settings) {
          store.setSettings(event.payload.settings);
        }
        break;

      case 'protocol_error':
        console.error('[WS Protocol Error]:', event.payload);
        store.addNotice({ id: event.payload.request_id || event.event_id, message: event.payload.message || 'Request failed', conversationId: event.conversation_id });
        const rejected = this.pendingPrompts.get(event.payload.request_id);
        if (rejected) { store.setPendingSubmission(rejected.conversationId, null); this.pendingPrompts.delete(event.payload.request_id); }
        if (event.payload?.error_code === 'CONVERSATION_NOT_FOUND' && this.conversationRequests.get(event.payload.request_id) === store.activeConversationId) {
          store.setActiveConversationId(null);
          sessionStorage.removeItem('agy_active_run_id');
          const initialWorkspace = new URLSearchParams(location.search).get('workspace');
          if (initialWorkspace) this.sendCommand('open_workspace', { canonical_path: initialWorkspace });
        }
        if (event.payload?.error_code === 'UNAUTHORIZED') {
          store.setConnectionState('error', 'Unauthorized: Invalid token');
        }
        break;
    }
  }

  private handleError(event: Event) {
    console.error('[WS Error]:', event);
    useCockpitStore.getState().setConnectionState('error', 'WebSocket connection error');
  }

  private handleClose(event?: CloseEvent) {
    if (this.pingInterval) clearInterval(this.pingInterval);
    for (const pending of this.pendingPrompts.values()) useCockpitStore.getState().setPendingSubmission(pending.conversationId, null);
    this.pendingPrompts.clear();
    const store = useCockpitStore.getState();
    if (event && event.code === 1008) {
      store.setConnectionState('error', event.reason || 'Unauthorized or Origin rejected');
      return;
    }
    store.setConnectionState('disconnected');
    this.scheduleReconnect();
  }

  private scheduleReconnect() {
    if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay);
    this.reconnectTimeout = setTimeout(() => {
      this.connect();
    }, delay);
  }

  public reconnect() {
    if (this.ws) {
      this.ws.close();
    }
    this.connect();
  }

  public sendCommand<T = Record<string, unknown>>(
    type: string,
    payload: T,
    conversationId?: string,
    runId?: string
  ): string | null {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      useCockpitStore.getState().addNotice({ id: crypto.randomUUID(), message: 'Disconnected. Reconnect before retrying this action.' });
      return null;
    }

    const store = useCockpitStore.getState();
    const cmd: ClientCommand<T> = {
      protocol_version: PROTOCOL_VERSION,
      type,
      request_id: crypto.randomUUID(),
      session_id: this.sessionId,
      conversation_id: conversationId || store.activeConversationId || undefined,
      run_id: runId || store.activeRunId || undefined,
      payload,
    };

    if (type === 'open_workspace') this.latestWorkspaceRequest = cmd.request_id;
    if (type === 'open_conversation') { this.conversationRequests.set(cmd.request_id, (payload as { conversation_id: string }).conversation_id); if (this.conversationRequests.size > 100) this.conversationRequests.delete(this.conversationRequests.keys().next().value!); }
    this.ws.send(JSON.stringify(cmd));
    return cmd.request_id;
  }

  public sendPrompt(prompt: string, attachmentIds: string[] = [], modelSlug?: string, councilAction?: CouncilAction): string | null {
    const store = useCockpitStore.getState();
    const id = store.activeConversationId;
    if (!id || store.pendingSubmissions[id] || store.activeRunId) return null;
    const requestId = this.sendCommand('send_prompt', { prompt, attachment_ids: attachmentIds, model_slug: modelSlug, council_action: councilAction }, id);
    if (requestId) {
      this.pendingPrompts.set(requestId, { conversationId: id, prompt, attachmentIds, draft: JSON.stringify(store.draftsByConversation[id]) });
      store.setPendingSubmission(id, requestId);
    }
    return requestId;
  }

  public cancelActiveRun() {
    const store = useCockpitStore.getState();
    if (store.activeRunId) {
      this.sendCommand('cancel_run', { run_id: store.activeRunId });
    }
  }

  public respondApproval(approvalId: string, decision: 'approved' | 'rejected') {
    this.sendCommand('action_approval', {
      approval_request_id: approvalId,
      decision,
    });
  }

  public searchWorkspace(query: string) {
    const store = useCockpitStore.getState();
    store.setMentionSearch(query, store.mentionResults, true);
    this.sendCommand('search_workspace', { query, limit: 15 });
  }

  public requestFileDiff(filePath: string) {
    this.sendCommand('get_file_diff', { file_path: filePath });
  }
}

export const wsService = new WebSocketService();
