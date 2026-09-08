import { PROTOCOL_VERSION, ClientCommand, ServerEvent } from '../types/protocol';
import { useCockpitStore } from '../store/useCockpitStore';

class WebSocketService {
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

    // Start ping interval
    if (this.pingInterval) clearInterval(this.pingInterval);
    this.pingInterval = setInterval(() => {
      this.sendCommand('ping', {});
    }, 25000);

    // If recovering an active run, send resume_run_stream
    if (store.activeConversationId && store.activeRunId) {
      this.sendCommand('resume_run_stream', {
        conversation_id: store.activeConversationId,
        run_id: store.activeRunId,
        after_sequence: store.lastSequence,
      });
    } else if (store.activeConversationId) {
      this.sendCommand('open_conversation', {
        conversation_id: store.activeConversationId,
      });
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
    if (event.sequence !== undefined) {
      const runKey = event.run_id || 'global';
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
        }
        break;

      case 'workspace_opened':
        if (event.payload?.workspace) {
          const ws = event.payload.workspace;
          store.setWorkspaces([ws]);
          store.setActiveWorkspaceId(ws.id);
          this.sendCommand('list_conversations', { workspace_id: ws.id });
        }
        break;

      case 'conversation_list':
        if (event.payload?.conversations) {
          store.setConversations(event.payload.conversations);
        }
        break;

      case 'conversation_created':
        if (event.payload?.conversation) {
          store.addConversation(event.payload.conversation);
        }
        break;

      case 'conversation_snapshot':
        if (event.payload?.conversation) {
          store.addConversation(event.payload.conversation);
          if (event.payload.messages) {
            store.setMessages(event.payload.conversation.id, event.payload.messages);
          }
          if (event.payload.active_run) {
            store.startRun(event.payload.active_run);
          }
        }
        break;

      case 'run_started':
        store.startRun({
          id: event.payload.run_id,
          conversation_id: event.payload.conversation_id,
          user_message_id: event.payload.user_message_id,
          state: 'queued',
          started_at: event.payload.started_at,
        });
        break;

      case 'reasoning_delta':
        store.appendReasoning(event.payload.delta, event.sequence);
        break;

      case 'token_delta':
        store.appendToken(event.payload.delta, event.sequence);
        break;

      case 'tool_started':
        store.toolStarted(
          event.payload.tool_execution_id,
          event.payload.sdk_tool_name,
          event.payload.args,
          event.sequence
        );
        break;

      case 'tool_log':
        store.appendToolLog(event.payload.tool_execution_id, event.payload.chunk);
        break;

      case 'tool_finished':
        store.toolFinished(
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
        store.setPendingApproval(null);
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
        });
        break;

      case 'subagent_update':
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
      case 'artifact_updated':
        store.artifactCreated({
          id: event.payload.id || event.payload.artifact_id,
          kind: event.payload.kind,
          name: event.payload.name,
          mime_type: event.payload.mime_type,
          preview_supported: event.payload.preview_supported,
          size_bytes: event.payload.size_bytes,
        });
        break;

      case 'run_completed':
        store.finalizeRun(
          event.payload.run_id,
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
          'cancelled',
          event.payload.cancelled_at
        );
        break;

      case 'run_failed':
        store.finalizeRun(
          event.payload.run_id,
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

  private handleClose() {
    if (this.pingInterval) clearInterval(this.pingInterval);
    const store = useCockpitStore.getState();
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
  ) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[WS] Cannot send command: socket not open');
      return;
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

    this.ws.send(JSON.stringify(cmd));
  }

  public sendPrompt(prompt: string, attachmentIds: string[] = [], modelSlug?: string) {
    const store = useCockpitStore.getState();
    if (!store.activeConversationId) return;

    // Optimistically add user message to timeline
    const userMsgId = `usr-${crypto.randomUUID()}`;
    store.addMessage({
      id: userMsgId,
      conversation_id: store.activeConversationId,
      role: 'user',
      author_time: new Date().toISOString(),
      content: prompt,
      attachment_ids: attachmentIds,
    });

    this.sendCommand('send_prompt', {
      prompt,
      attachment_ids: attachmentIds,
      model_slug: modelSlug,
    });
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
