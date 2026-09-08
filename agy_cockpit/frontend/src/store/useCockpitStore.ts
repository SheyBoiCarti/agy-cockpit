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
} from '../types/models';
import { SyncStatePayload } from '../types/protocol';

export type ConnectionState = 'disconnected' | 'connecting' | 'connected' | 'recovering' | 'error';
export type DrawerTab = 'diffs' | 'terminal' | 'subagents' | 'artifacts' | null;

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

  // Live streaming / Active Run state
  reasoning: string;
  streamingOutput: string;
  activeTools: Record<string, ToolExecution>;
  pendingApproval: ApprovalRequest | null;
  subagents: Record<string, Subagent>;
  artifacts: Record<string, Artifact>;
  changedFiles: Record<string, ChangedFile>;
  toolLogs: Record<string, string[]>;

  // UI state
  activeDrawerTab: DrawerTab;
  selectedDiffFile: string | null;
  diffData: { original: string; modified: string; language: string; is_binary?: boolean } | null;
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
  appendReasoning: (delta: string, sequence?: number) => void;
  appendToken: (delta: string, sequence?: number) => void;
  toolStarted: (toolId: string, name: string, args: Record<string, unknown>, sequence?: number) => void;
  appendToolLog: (toolId: string, chunk: string) => void;
  toolFinished: (toolId: string, success: boolean, summary?: string, sequence?: number) => void;
  setPendingApproval: (approval: ApprovalRequest | null) => void;
  fileChanged: (file: ChangedFile) => void;
  subagentUpdated: (subagent: Subagent) => void;
  artifactCreated: (artifact: Artifact) => void;
  finalizeRun: (
    runId: string,
    state: RunState,
    completedAt: string,
    errorCode?: string,
    errorMessage?: string,
    usage?: Record<string, unknown>
  ) => void;
  applySyncState: (payload: SyncStatePayload) => void;
  setActiveDrawerTab: (tab: DrawerTab) => void;
  setSelectedDiffFile: (file: string | null, diffData?: { original: string; modified: string; language: string; is_binary?: boolean } | null) => void;
  setSettings: (settings: Partial<Settings>) => void;
  setModels: (models: ModelOption[]) => void;
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

  reasoning: '',
  streamingOutput: '',
  activeTools: {},
  pendingApproval: null,
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
      activeRunId: null,
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
    }
    return set((state) => ({
      runs: { ...state.runs, [run.id]: run },
      activeRunId: run.id,
      reasoning: '',
      streamingOutput: '',
      activeTools: {},
      pendingApproval: null,
      subagents: {},
      artifacts: {},
      changedFiles: {},
      toolLogs: {},
    }));
  },

  appendReasoning: (delta, sequence) =>
    set((state) => ({
      reasoning: state.reasoning + delta,
      lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
    })),

  appendToken: (delta, sequence) =>
    set((state) => ({
      streamingOutput: state.streamingOutput + delta,
      lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
    })),

  toolStarted: (toolId, name, args, sequence) =>
    set((state) => {
      const runId = state.activeRunId || 'run';
      const existing = state.activeTools[toolId];
      const tool: ToolExecution = {
        id: toolId,
        run_id: runId,
        sdk_tool_name: name,
        args,
        state: 'started',
        started_at: new Date().toISOString(),
        logs: existing ? existing.logs : [],
      };
      return {
        activeTools: { ...state.activeTools, [toolId]: tool },
        lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
      };
    }),

  appendToolLog: (toolId, chunk) =>
    set((state) => {
      const existingLogs = state.toolLogs[toolId] || [];
      // Bounded buffer of 500 chunks to prevent memory ballooning
      const updatedLogs = [...existingLogs.slice(-499), chunk];
      return {
        toolLogs: { ...state.toolLogs, [toolId]: updatedLogs },
      };
    }),

  toolFinished: (toolId, success, summary, sequence) =>
    set((state) => {
      const existing = state.activeTools[toolId];
      if (!existing) return state;
      return {
        activeTools: {
          ...state.activeTools,
          [toolId]: {
            ...existing,
            state: success ? 'completed' : 'failed',
            finished_at: new Date().toISOString(),
            success,
            output_summary: summary,
          },
        },
        lastSequence: sequence ? Math.max(state.lastSequence, sequence) : state.lastSequence,
      };
    }),

  setPendingApproval: (pendingApproval) =>
    set({ pendingApproval }),

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

  finalizeRun: (runId, runState, completedAt, errorCode, errorMessage, usage) =>
    set((state) => {
      const existing = state.runs[runId];
      const updatedRun: Run = existing
        ? {
            ...existing,
            state: runState,
            completed_at: completedAt,
            error_code: errorCode,
            error_message: errorMessage,
            usage,
          }
        : {
            id: runId,
            conversation_id: state.activeConversationId || '',
            user_message_id: '',
            state: runState,
            started_at: completedAt,
            completed_at: completedAt,
            error_code: errorCode,
            error_message: errorMessage,
            usage,
          };

      // If output was streamed, reasoning captured, or tools invoked, persist an assistant message in state
      let updatedMessages = state.messages;
      let updatedConvMsgIds = state.conversationMessageIds;
      if (
        (state.streamingOutput || Object.keys(state.activeTools).length > 0 || state.reasoning) &&
        state.activeConversationId
      ) {
        const asstMsgId = `asst-${runId}`;
        const content =
          state.streamingOutput ||
          (runState === 'failed' && errorMessage ? `Run failed: ${errorMessage}` : '');
        const asstMsg: Message = {
          id: asstMsgId,
          conversation_id: state.activeConversationId,
          role: 'assistant',
          author_time: completedAt,
          content,
          attachment_ids: [],
          run_id: runId,
          reasoning: state.reasoning || undefined,
          tools: Object.values(state.activeTools),
        };
        const currentIds = state.conversationMessageIds[state.activeConversationId] || [];
        if (!currentIds.includes(asstMsgId)) {
          updatedMessages = { ...state.messages, [asstMsgId]: asstMsg };
          updatedConvMsgIds = {
            ...state.conversationMessageIds,
            [state.activeConversationId]: [...currentIds, asstMsgId],
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

      return {
        activeRunId: payload.run_id,
        reasoning: payload.reasoning || '',
        streamingOutput: payload.output || '',
        activeTools: toolsMap,
        changedFiles: filesMap,
        subagents: subagentsMap,
        artifacts: artifactsMap,
        pendingApproval: payload.pending_approval
          ? {
              id: payload.pending_approval.id,
              run_id: payload.run_id,
              sdk_tool_name: payload.pending_approval.sdk_tool_name,
              args: payload.pending_approval.args,
              reason: payload.pending_approval.reason,
            }
          : null,
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

  setMentionSearch: (mentionQuery, mentionResults, isSearchingMention) =>
    set({ mentionQuery, mentionResults, isSearchingMention }),
}));
