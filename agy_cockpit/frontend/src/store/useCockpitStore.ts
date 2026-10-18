import { create } from 'zustand';
import {
  Workspace,
  Conversation,
  Message,
  Run,
  RunState,
  ToolExecution,
  ApprovalRequest,
  ChangedFile,
  Subagent,
  Artifact,
  Settings,
  ModelOption,
  ToolLogEntry,
} from '../types/models';
import { SyncStatePayload } from '../types/protocol';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'recovering' | 'error';
export type DrawerTab = 'diffs' | 'terminal' | 'subagents' | 'artifacts' | 'council' | null;

interface CockpitState {
  // Connection
  connectionState: ConnectionState;
  connectionError: string | null;
  lastSequence: number;

  // Workspaces
  workspaces: Record<string, Workspace>;
  activeWorkspaceId: string | null;

  // Conversations
  conversations: Record<string, Conversation>;
  activeConversationId: string | null;

  // Messages (normalized)
  messages: Record<string, Message>;
  conversationMessageIds: Record<string, string[]>;

  // Runs
  runs: Record<string, Run>;
  activeRunId: string | null;

  // Live streaming / Active Run state (Keyed by conversationId)
  streamingOutputByConv: Record<string, string>;
  reasoningByConv: Record<string, string>;
  activeToolsByConv: Record<string, Record<string, ToolExecution>>;

  // Backward compatibility
  reasoning: string;
  streamingOutput: string;
  activeTools: Record<string, ToolExecution>;
  pendingApproval: ApprovalRequest | null;
  pendingApprovals: ApprovalRequest[];
  subagents: Record<string, Subagent>;
  artifacts: Record<string, Artifact>;
  changedFiles: Record<string, ChangedFile>;
  toolLogs: Record<string, ToolLogEntry[]>;

  // UI state
  activeDrawerTab: DrawerTab;
  selectedDiffFile: string | null;
  diffData: { original: string; modified: string; language: string; is_binary?: boolean; truncated?: boolean } | null;
  settings: Settings;
  models: ModelOption[];

  // Workspace search / mentions
  mentionQuery: string;
  mentionResults: Array<{ path: string; is_directory: boolean }>;
  isSearchingMention: boolean;

  // Actions
  setConnectionState: (state: ConnectionState, error?: string | null) => void;
  setLastSequence: (seq: number) => void;
  setWorkspaces: (workspaces: Workspace[]) => void;
  setActiveWorkspaceId: (id: string | null) => void;
  setConversations: (conversations: Conversation[]) => void;
  addConversation: (conversation: Conversation) => void;
  setActiveConversationId: (id: string | null) => void;
  updateConversation: (id: string, partial: Partial<Conversation>) => void;
  setMessages: (conversationId: string, messages: Message[]) => void;
  addMessage: (message: Message) => void;
  startRun: (run: Run) => void;
  appendReasoning: (convId: string, delta: string, sequence?: number) => void;
  appendToken: (convId: string, delta: string, sequence?: number) => void;
  toolStarted: (convId: string, toolId: string, name: string, args: Record<string, unknown>, sequence?: number) => void;
  appendToolLog: (toolId: string, chunk: string, is_stderr?: boolean) => void;
  toolFinished: (convId: string, toolId: string, success: boolean, summary?: string, sequence?: number) => void;
  setPendingApproval: (approval: ApprovalRequest | null) => void;
  dequeueApproval: (approvalId?: string) => void;
  fileChanged: (file: ChangedFile) => void;
  subagentUpdated: (subagent: Subagent) => void;
  artifactCreated: (artifact: Artifact) => void;
  finalizeRun: (
    runId: string,
    convId: string,
    state: RunState | string,
    completedAt: string,
    errorCode?: string,
    errorMessage?: string,
    usage?: Record<string, unknown>
  ) => void;
  applySyncState: (payload: SyncStatePayload) => void;
  setActiveDrawerTab: (tab: DrawerTab) => void;
  setSelectedDiffFile: (file: string | null, diffData?: { original: string; modified: string; language: string; is_binary?: boolean; truncated?: boolean } | null) => void;
  setSettings: (settings: Partial<Settings>) => void;
  setModels: (models: ModelOption[]) => void;
  setArtifacts: (artifacts: Artifact[]) => void;
  setMentionSearch: (query: string, results: Array<{ path: string; is_directory: boolean }>, isSearching: boolean) => void;
}

export const useCockpitStore = create<CockpitState>((set) => ({
  connectionState: 'disconnected',
  connectionError: null,
  lastSequence: typeof window !== 'undefined' ? parseInt(sessionStorage.getItem('agy_last_seen_sequence') || '0', 10) || 0 : 0,

  workspaces: {},
  activeWorkspaceId: null,

  conversations: {},
  activeConversationId: typeof window !== 'undefined' ? sessionStorage.getItem('agy_active_conversation_id') || null : null,

  messages: {},
  conversationMessageIds: {},

  runs: {},
  activeRunId: typeof window !== 'undefined' ? sessionStorage.getItem('agy_active_run_id') || null : null,

  streamingOutputByConv: {},
  reasoningByConv: {},
  activeToolsByConv: {},

  reasoning: '',
  streamingOutput: '',
  activeTools: {},
  pendingApproval: null,
  pendingApprovals: [],
  subagents: {},
  artifacts: {},
  changedFiles: {},
  toolLogs: {},

  activeDrawerTab: null,
  selectedDiffFile: null,
  diffData: null,
  settings: {
    policy_preset: 'request-review',
    default_model: 'gemini-3.8-flash-high',
    allowed_workspaces: [],
  },
  models: [
    { slug: 'gemini-3.8-flash-high', label: 'Gemini 3.8 Flash', description: 'Fastest turn-around for everyday tasks' },
    { slug: 'gemini-3.8-pro-high', label: 'Gemini 3.8 Pro', description: 'Deep reasoning, architecture, and large refactors' },
  ],

  mentionQuery: '',
  mentionResults: [],
  isSearchingMention: false,

  setConnectionState: (connectionState, error = null) =>
    set({ connectionState, connectionError: error }),

  setLastSequence: (lastSequence) =>
    set((state) => {
      const nextSeq = Math.max(state.lastSequence, lastSequence);
      if (typeof window !== 'undefined') {
        sessionStorage.setItem('agy_last_seen_sequence', String(nextSeq));
      }
      return { lastSequence: nextSeq };
    }),

  setWorkspaces: (workspaces) =>
    set({
      workspaces: Object.fromEntries(workspaces.map((w) => [w.id, w])),
    }),

  setActiveWorkspaceId: (activeWorkspaceId) =>
    set({ activeWorkspaceId }),

  setConversations: (conversations) =>
    set({
      conversations: Object.fromEntries(conversations.map((c) => [c.id, c])),
    }),

  addConversation: (conversation) =>
    set((state) => {
      if (typeof window !== 'undefined') {
        sessionStorage.setItem('agy_active_conversation_id', conversation.id);
      }
      return {
        conversations: { ...state.conversations, [conversation.id]: conversation },
        activeConversationId: conversation.id,
        conversationMessageIds: {
          ...state.conversationMessageIds,
          [conversation.id]: state.conversationMessageIds[conversation.id] || [],
        },
      };
    }),

  setActiveConversationId: (id) => {
    if (typeof window !== 'undefined') {
      if (id) {
        sessionStorage.setItem('agy_active_conversation_id', id);
      } else {
        sessionStorage.removeItem('agy_active_conversation_id');
      }
    }
    return set({
      activeConversationId: id,
      reasoning: '',
      streamingOutput: '',
      activeTools: {},
      pendingApproval: null,
      pendingApprovals: [],
      activeRunId: null,
      changedFiles: {},
      subagents: {},
      artifacts: {},
      toolLogs: {},
      selectedDiffFile: null,
      diffData: null,
    });
  },

  updateConversation: (id, partial) =>
    set((state) => {
      const existing = state.conversations[id];
      if (!existing) return state;
      return {
        conversations: {
          ...state.conversations,
          [id]: { ...existing, ...partial },
        },
      };
    }),

  setMessages: (conversationId, messages) =>
    set((state) => {
      const newMessages = { ...state.messages };
      const ids: string[] = [];
      for (const m of messages) {
        newMessages[m.id] = m;
        ids.push(m.id);
      }
      return {
        messages: newMessages,
        conversationMessageIds: {
          ...state.conversationMessageIds,
          [conversationId]: ids,
        },
      };
    }),

  addMessage: (message) =>
    set((state) => {
      const existingIds = state.conversationMessageIds[message.conversation_id] || [];
      if (existingIds.includes(message.id)) {
        return {
          messages: { ...state.messages, [message.id]: message },
        };
      }
      return {
        messages: { ...state.messages, [message.id]: message },
        conversationMessageIds: {
          ...state.conversationMessageIds,
          [message.conversation_id]: [...existingIds, message.id],
        },
      };
    }),

  startRun: (run) => {
    if (typeof window !== 'undefined') {
      sessionStorage.setItem('agy_active_run_id', run.id);
      sessionStorage.setItem('agy_last_seen_sequence', '0');
    }
    return set((state) => {
      const convId = run.conversation_id || state.activeConversationId || '';
      return {
        runs: { ...state.runs, [run.id]: run },
        activeRunId: run.id,
        lastSequence: 0,
        streamingOutputByConv: { ...state.streamingOutputByConv, [convId]: '' },
        reasoningByConv: { ...state.reasoningByConv, [convId]: '' },
        activeToolsByConv: { ...state.activeToolsByConv, [convId]: {} },
        reasoning: '',
        streamingOutput: '',
        activeTools: {},
        pendingApproval: null,
        pendingApprovals: [],
        subagents: {},
        artifacts: {},
        // Preserve changedFiles across runs so diffs remain visible
        toolLogs: {},
      };
    });
  },

  appendReasoning: (convId, delta, sequence) =>
    set((state) => {
      const targetConvId = convId || state.activeConversationId || '';
      const prev = state.reasoningByConv[targetConvId] || '';
      const next = prev + delta;
      return {
        reasoningByConv: { ...state.reasoningByConv, [targetConvId]: next },
        reasoning: targetConvId === state.activeConversationId ? next : state.reasoning,
        lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
      };
    }),

  appendToken: (convId, delta, sequence) =>
    set((state) => {
      const targetConvId = convId || state.activeConversationId || '';
      const prev = state.streamingOutputByConv[targetConvId] || '';
      const next = prev + delta;
      return {
        streamingOutputByConv: { ...state.streamingOutputByConv, [targetConvId]: next },
        streamingOutput: targetConvId === state.activeConversationId ? next : state.streamingOutput,
        lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
      };
    }),

  toolStarted: (convId, toolId, name, args, sequence) =>
    set((state) => {
      const targetConvId = convId || state.activeConversationId || '';
      const runId = state.activeRunId || 'run';
      const convTools = state.activeToolsByConv[targetConvId] || {};
      const existing = convTools[toolId] || state.activeTools[toolId];
      const tool: ToolExecution = {
        id: toolId,
        run_id: runId,
        sdk_tool_name: name,
        args,
        state: 'started',
        started_at: new Date().toISOString(),
        logs: existing ? existing.logs : [],
      };
      const nextConvTools = { ...convTools, [toolId]: tool };
      return {
        activeToolsByConv: { ...state.activeToolsByConv, [targetConvId]: nextConvTools },
        activeTools: targetConvId === state.activeConversationId ? nextConvTools : state.activeTools,
        lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
      };
    }),

  appendToolLog: (toolId, chunk, is_stderr = false) =>
    set((state) => {
      const existingLogs = state.toolLogs[toolId] || [];
      // Bounded buffer of 500 chunks to prevent memory ballooning
      const updatedLogs = [...existingLogs.slice(-499), { chunk, is_stderr }];
      return {
        toolLogs: { ...state.toolLogs, [toolId]: updatedLogs },
      };
    }),

  toolFinished: (convId, toolId, success, summary, sequence) =>
    set((state) => {
      const targetConvId = convId || state.activeConversationId || '';
      const convTools = state.activeToolsByConv[targetConvId] || {};
      const existing = convTools[toolId] || state.activeTools[toolId];
      if (!existing) return state;
      const updatedTool: ToolExecution = {
        ...existing,
        state: success ? 'completed' : 'failed',
        finished_at: new Date().toISOString(),
        success,
        output_summary: summary,
      };
      const nextConvTools = { ...convTools, [toolId]: updatedTool };
      return {
        activeToolsByConv: { ...state.activeToolsByConv, [targetConvId]: nextConvTools },
        activeTools: targetConvId === state.activeConversationId ? nextConvTools : state.activeTools,
        lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
      };
    }),

  setPendingApproval: (approval) =>
    set((state) => {
      if (!approval) {
        const next = state.pendingApprovals.slice(1);
        return {
          pendingApprovals: next,
          pendingApproval: next[0] || null,
        };
      }
      const existing = state.pendingApprovals.some((a) => a.id === approval.id);
      const next = existing
        ? state.pendingApprovals.map((a) => (a.id === approval.id ? approval : a))
        : [...state.pendingApprovals, approval];
      return {
        pendingApprovals: next,
        pendingApproval: next[0] || null,
      };
    }),

  dequeueApproval: (approvalId) =>
    set((state) => {
      const next = approvalId
        ? state.pendingApprovals.filter((a) => a.id !== approvalId)
        : state.pendingApprovals.slice(1);
      return {
        pendingApprovals: next,
        pendingApproval: next[0] || null,
      };
    }),

  fileChanged: (file) =>
    set((state) => ({
      changedFiles: { ...state.changedFiles, [file.path]: file },
    })),

  subagentUpdated: (subagent) =>
    set((state) => ({
      subagents: { ...state.subagents, [subagent.id]: subagent },
    })),

  artifactCreated: (artifact) =>
    set((state) => ({
      artifacts: { ...state.artifacts, [artifact.id]: artifact },
    })),

  finalizeRun: (runId, convId, runState, completedAt, errorCode, errorMessage, usage) =>
    set((state) => {
      const existing = state.runs[runId];
      const targetConvId = convId || existing?.conversation_id || state.activeConversationId || '';
      const updatedRun: Run = existing
        ? {
            ...existing,
            state: runState as RunState,
            completed_at: completedAt,
            error_code: errorCode,
            error_message: errorMessage,
            usage,
          }
        : {
            id: runId,
            conversation_id: targetConvId,
            user_message_id: '',
            state: runState as RunState,
            started_at: completedAt,
            completed_at: completedAt,
            error_code: errorCode,
            error_message: errorMessage,
            usage,
          };

      const convOutput = state.streamingOutputByConv[targetConvId] ?? (targetConvId === state.activeConversationId ? state.streamingOutput : '');
      const convReasoning = state.reasoningByConv[targetConvId] ?? (targetConvId === state.activeConversationId ? state.reasoning : '');
      const convTools = state.activeToolsByConv[targetConvId] ?? (targetConvId === state.activeConversationId ? state.activeTools : {});

      // If output was streamed, reasoning captured, or tools invoked, persist an assistant message in state
      let updatedMessages = state.messages;
      let updatedConvMsgIds = state.conversationMessageIds;
      if (
        (convOutput || Object.keys(convTools).length > 0 || convReasoning) &&
        targetConvId
      ) {
        const asstMsgId = `asst-${runId}`;
        const content =
          convOutput ||
          (runState === 'failed' && errorMessage ? `Run failed: ${errorMessage}` : '');
        const asstMsg: Message = {
          id: asstMsgId,
          conversation_id: targetConvId,
          role: 'assistant',
          author_time: completedAt,
          content,
          attachment_ids: [],
          run_id: runId,
          reasoning: convReasoning || undefined,
          tools: Object.values(convTools),
        };
        const currentIds = state.conversationMessageIds[targetConvId] || [];
        if (!currentIds.includes(asstMsgId)) {
          updatedMessages = { ...state.messages, [asstMsgId]: asstMsg };
          updatedConvMsgIds = {
            ...state.conversationMessageIds,
            [targetConvId]: [...currentIds, asstMsgId],
          };
        }
      }

      if (typeof window !== 'undefined') {
        sessionStorage.removeItem('agy_active_run_id');
      }

      return {
        runs: { ...state.runs, [runId]: updatedRun },
        activeRunId: null,
        pendingApproval: null,
        pendingApprovals: [],
        messages: updatedMessages,
        conversationMessageIds: updatedConvMsgIds,
      };
    }),

  applySyncState: (payload) =>
    set((state) => {
      const toolsMap: Record<string, ToolExecution> = {};
      for (const t of payload.tools || []) {
        toolsMap[t.id] = {
          id: t.id,
          run_id: payload.run_id,
          sdk_tool_name: t.sdk_tool_name,
          args: t.args,
          state: t.state as 'started' | 'completed' | 'failed',
          started_at: new Date().toISOString(),
          success: t.success,
          output_summary: t.output_summary,
          logs: [],
        };
      }

      const filesMap: Record<string, ChangedFile> = {};
      for (const p of payload.changed_files || []) {
        filesMap[p] = { path: p, status: 'modified', run_id: payload.run_id };
      }

      const subagentsMap: Record<string, Subagent> = {};
      for (const s of payload.subagents || []) {
        subagentsMap[s.id] = {
          id: s.id,
          parent_id: s.parent_id,
          name_or_role: s.name_or_role,
          state: s.state as 'pending' | 'running' | 'completed' | 'failed' | 'cancelled',
          current_activity: s.current_activity,
          depth: s.depth,
        };
      }

      const artifactsMap: Record<string, Artifact> = {};
      for (const a of payload.artifacts || []) {
        artifactsMap[a.id] = {
          id: a.id,
          kind: a.kind,
          name: a.name,
          mime_type: a.mime_type,
          preview_supported: a.preview_supported,
        };
      }

      const syncApproval = payload.pending_approval
        ? {
            id: payload.pending_approval.id,
            run_id: payload.run_id,
            sdk_tool_name: payload.pending_approval.sdk_tool_name,
            args: payload.pending_approval.args,
            reason: payload.pending_approval.reason,
          }
        : null;

      return {
        activeRunId: payload.run_id,
        reasoning: payload.reasoning || '',
        streamingOutput: payload.output || '',
        activeTools: toolsMap,
        changedFiles: filesMap,
        subagents: subagentsMap,
        artifacts: artifactsMap,
        pendingApproval: syncApproval,
        pendingApprovals: syncApproval ? [syncApproval] : [],
        lastSequence: Math.max(state.lastSequence, payload.last_sequence || 0),
      };
    }),

  setActiveDrawerTab: (activeDrawerTab) =>
    set({ activeDrawerTab }),

  setSelectedDiffFile: (selectedDiffFile, diffData = null) =>
    set({ selectedDiffFile, diffData, activeDrawerTab: 'diffs' }),

  setSettings: (settings) =>
    set((state) => ({ settings: { ...state.settings, ...settings } })),

  setModels: (models) =>
    set({ models }),

  setArtifacts: (artifacts) =>
    set({
      artifacts: Object.fromEntries(artifacts.map((a) => [a.id, a])),
    }),

  setMentionSearch: (mentionQuery, mentionResults, isSearchingMention) =>
    set({ mentionQuery, mentionResults, isSearchingMention }),
}));
