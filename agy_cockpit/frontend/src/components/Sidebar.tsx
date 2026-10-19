import React, { useState } from 'react';
import { useCockpitStore } from '../store/useCockpitStore';
import { usePanelFocus } from './usePanelFocus';
import { wsService } from '../services/websocket';
import {
  FolderGit2,
  MessageSquarePlus,
  MessageSquare,
  Archive,
  Settings,
  Circle,
  FolderOpen,
  X,
  Check,
  Users,
} from 'lucide-react';

interface SidebarProps {
  onOpenSettings: () => void;
}

export const Sidebar: React.FC<SidebarProps> = ({ onOpenSettings }) => {
  const isOpen = useCockpitStore(s => s.isSidebarOpen);
  const panelRef = usePanelFocus(isOpen, '(max-width: 767px)', () => useCockpitStore.getState().setSidebarOpen(false));
  const workspaces = useCockpitStore((s) => s.workspaces);
  const activeWorkspaceId = useCockpitStore((s) => s.activeWorkspaceId);
  const conversationsMap = useCockpitStore((s) => s.conversations);
  const activeConversationId = useCockpitStore((s) => s.activeConversationId);
  const activeDrawerTab = useCockpitStore((s) => s.activeDrawerTab);
  const setActiveDrawerTab = useCockpitStore((s) => s.setActiveDrawerTab);
  const connectionState = useCockpitStore((s) => s.connectionState);
  const connectionError = useCockpitStore((s) => s.connectionError);

  const [isOpenWorkspaceModal, setIsOpenWorkspaceModal] = useState(false);
  const [newWorkspacePath, setNewWorkspacePath] = useState('');

  const activeWorkspace = activeWorkspaceId ? workspaces[activeWorkspaceId] : Object.values(workspaces)[0];
  const conversations = Object.values(conversationsMap).filter((c) => !c.is_archived);

  const handleSelectConversation = (convId: string) => {
    useCockpitStore.getState().setSidebarOpen(false);
    if (convId === activeConversationId) return;
    useCockpitStore.getState().setActiveConversationId(convId);
    wsService.sendCommand('open_conversation', { conversation_id: convId });
  };

  const handleCreateConversation = () => {
    if (!activeWorkspace) return;
    wsService.sendCommand('create_conversation', {
      workspace_id: activeWorkspace.id,
      title: 'New Conversation',
    });
  };

  const handleArchiveConversation = (e: React.MouseEvent, convId: string) => {
    e.stopPropagation();
    wsService.sendCommand('archive_conversation', { conversation_id: convId });
    useCockpitStore.getState().updateConversation(convId, { is_archived: true });
    if (activeConversationId === convId) {
      const remaining = conversations.filter((c) => c.id !== convId);
      if (remaining.length > 0) {
        handleSelectConversation(remaining[0].id);
      } else {
        useCockpitStore.getState().setActiveConversationId(null);
      }
    }
  };

  const handleOpenWorkspace = () => {
    if (!newWorkspacePath.trim()) return;
    wsService.sendCommand('open_workspace', {
      canonical_path: newWorkspacePath.trim(),
    });
    setIsOpenWorkspaceModal(false);

  };

  return (
    <aside ref={panelRef} tabIndex={-1} aria-label="Workspace navigation" className={`cockpit-sidebar ${isOpen ? "is-open" : ""} w-64 border-r border-neutral-800 bg-neutral-950 flex flex-col h-full select-none`}>
      <button className="md:hidden p-3 text-right" aria-label="Close navigation" onClick={() => useCockpitStore.getState().setSidebarOpen(false)}>Close ×</button>
      {/* Workspace Header */}
      <div className="p-3 border-b border-neutral-800/80 bg-neutral-900/40">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-2 truncate">
            <FolderGit2 className="w-4 h-4 text-indigo-400 shrink-0" />
            <span className="font-semibold text-xs text-neutral-200 truncate">
              {activeWorkspace ? activeWorkspace.display_name : 'No Workspace'}
            </span>
          </div>
          <button
            onClick={() => setIsOpenWorkspaceModal(true)}
            className="p-1 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 rounded transition-colors"
            title="Open Workspace Path"
          >
            <FolderOpen className="w-3.5 h-3.5" />
          </button>
        </div>
        {activeWorkspace && (
          <div className="text-[11px] font-mono text-neutral-400 truncate mt-1">
            {activeWorkspace.canonical_path}
          </div>
        )}
      </div>

      {/* Navigation Buttons: New Conversation & AI Council */}
      <div className="p-3 border-b border-neutral-800/60 space-y-2">
        <button
          onClick={handleCreateConversation}
          disabled={!activeWorkspace}
          className="w-full flex items-center justify-center space-x-2 py-2 px-3 rounded-lg bg-indigo-600/15 border border-indigo-500/30 text-indigo-300 hover:bg-indigo-600/25 transition-all text-xs font-medium disabled:opacity-40"
        >
          <MessageSquarePlus className="w-4 h-4" />
          <span>New Conversation</span>
        </button>

        <button
          onClick={() => {
            setActiveDrawerTab(activeDrawerTab === 'council' ? null : 'council');
          }}
          className={`w-full flex items-center justify-between py-2 px-3 rounded-lg text-xs font-medium transition-all ${
            activeDrawerTab === 'council'
              ? 'bg-indigo-600/30 text-indigo-200 border border-indigo-500/50 shadow-sm'
              : 'bg-neutral-900/90 text-neutral-300 hover:text-white hover:bg-neutral-800 border border-neutral-800/80'
          }`}
          title="Open AI Council Swarm Panel"
        >
          <div className="flex items-center space-x-2">
            <Users className="w-4 h-4 text-indigo-400 shrink-0" />
            <span className="font-semibold">AI Council</span>
          </div>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-mono font-medium">
            Swarm
          </span>
        </button>
      </div>

      {/* Conversations List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-0.5">
        <div className="px-2 py-1 text-[11px] font-medium text-neutral-400 uppercase tracking-wider">
          Conversations ({conversations.length})
        </div>

        {conversations.length === 0 ? (
          <div className="text-xs text-neutral-400 p-3 text-center">No active chats</div>
        ) : (
          conversations.map((conv) => {
            const isActive = conv.id === activeConversationId;
            return (
              <div
                key={conv.id}
                onClick={() => handleSelectConversation(conv.id)}
                className={`group flex items-center justify-between px-2.5 py-2 rounded-lg cursor-pointer text-xs transition-colors ${
                  isActive
                    ? 'bg-neutral-800 text-neutral-100 font-medium'
                    : 'text-neutral-400 hover:bg-neutral-900 hover:text-neutral-200'
                }`}
              >
                <div className="flex items-center space-x-2 truncate min-w-0">
                  <MessageSquare className="w-3.5 h-3.5 shrink-0 opacity-70" />
                  <span className="truncate">{conv.title}</span>
                </div>

                <button
                  onClick={(e) => handleArchiveConversation(e, conv.id)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-neutral-400 hover:text-rose-400 rounded transition-opacity"
                  title="Archive Conversation"
                >
                  <Archive className="w-3 h-3" />
                </button>
              </div>
            );
          })
        )}
      </div>

      {/* Footer Connection & Settings */}
      <div className="p-3 border-t border-neutral-800 bg-neutral-900/30 flex items-center justify-between text-xs">
        <div
          onClick={connectionState === 'error' || connectionState === 'disconnected' ? onOpenSettings : undefined}
          className={`flex items-center space-x-2 ${
            connectionState === 'error' || connectionState === 'disconnected' ? 'cursor-pointer group' : ''
          }`}
          title={connectionError || (connectionState !== 'connected' ? 'Click to configure token in settings' : 'Connected')}
        >
          <Circle
            className={`w-2.5 h-2.5 fill-current ${
              connectionState === 'connected'
                ? 'text-emerald-400'
                : connectionState === 'recovering'
                ? 'text-amber-400 animate-pulse'
                : 'text-rose-400'
            }`}
          />
          <span className={`text-[11px] capitalize ${
            connectionState === 'error' ? 'text-rose-400 group-hover:underline' : 'text-neutral-400'
          }`}>
            {connectionState === 'error' && connectionError ? 'Auth Error' : connectionState}
          </span>
        </div>

        <button
          onClick={onOpenSettings}
          className="p-1.5 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 rounded-lg transition-colors"
          title="Settings"
        >
          <Settings className="w-4 h-4" />
        </button>
      </div>

      {/* Open Workspace Modal */}
      {isOpenWorkspaceModal && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-neutral-900 border border-neutral-700 rounded-xl max-w-md w-full p-4 shadow-2xl space-y-3">
            <div className="flex items-center justify-between border-b border-neutral-800 pb-2">
              <h3 className="text-sm font-semibold text-neutral-200">Open Workspace</h3>
              <button
                onClick={() => setIsOpenWorkspaceModal(false)}
                className="text-neutral-400 hover:text-neutral-200"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div>
              <label className="block text-xs text-neutral-400 mb-1">
                Canonical Server Path:
              </label>
              <input
                type="text"
                value={newWorkspacePath}
                onChange={(e) => setNewWorkspacePath(e.target.value)}
                placeholder="/home/user/project"
                className="w-full bg-neutral-950 border border-neutral-700 rounded-lg px-3 py-2 text-xs font-mono text-neutral-100 focus:outline-none focus:border-indigo-500"
                autoFocus
              />
            </div>
            <div className="flex justify-end space-x-2 pt-2">
              <button
                onClick={() => setIsOpenWorkspaceModal(false)}
                className="px-3 py-1.5 text-xs text-neutral-400 hover:text-neutral-200"
              >
                Cancel
              </button>
              <button
                onClick={handleOpenWorkspace}
                className="flex items-center space-x-1 px-3 py-1.5 text-xs bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 font-medium"
              >
                <Check className="w-3.5 h-3.5" />
                <span>Open</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
};
