import React, { useState } from 'react';
import { useCockpitStore, DrawerTab } from '../store/useCockpitStore';
import { wsService } from '../services/websocket';
import {
  Sparkles,
  Shield,
  FileDiff,
  Terminal,
  Boxes,
  Layers,
  Edit2,
  Check,
  X,
  Sun,
  Moon,
} from 'lucide-react';

export const Header: React.FC = () => {
  const activeConversationId = useCockpitStore((s) => s.activeConversationId);
  const conversation = useCockpitStore((s) =>
    s.activeConversationId ? s.conversations[s.activeConversationId] : null
  );
  const models = useCockpitStore((s) => s.models);
  const settings = useCockpitStore((s) => s.settings);
  const activeDrawerTab = useCockpitStore((s) => s.activeDrawerTab);
  const setActiveDrawerTab = useCockpitStore((s) => s.setActiveDrawerTab);

  const changedFilesCount = useCockpitStore((s) => Object.keys(s.changedFiles).length);
  const subagentsCount = useCockpitStore((s) => Object.keys(s.subagents).length);
  const artifactsCount = useCockpitStore((s) => Object.keys(s.artifacts).length);

  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (typeof window !== 'undefined' && (localStorage.getItem('agy_theme') as 'dark' | 'light')) || 'dark';
  });

  const toggleTheme = () => {
    const nextTheme = theme === 'dark' ? 'light' : 'dark';
    setTheme(nextTheme);
    if (typeof window !== 'undefined') {
      localStorage.setItem('agy_theme', nextTheme);
      if (nextTheme === 'dark') {
        document.documentElement.classList.add('dark');
      } else {
        document.documentElement.classList.remove('dark');
      }
    }
  };

  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editedTitle, setEditedTitle] = useState('');

  const handleStartEditTitle = () => {
    if (!conversation) return;
    setEditedTitle(conversation.title);
    setIsEditingTitle(true);
  };

  const handleSaveTitle = () => {
    if (!activeConversationId || !editedTitle.trim()) {
      setIsEditingTitle(false);
      return;
    }
    wsService.sendCommand('rename_conversation', {
      conversation_id: activeConversationId,
      title: editedTitle.trim(),
    });
    useCockpitStore.getState().updateConversation(activeConversationId, { title: editedTitle.trim() });
    setIsEditingTitle(false);
  };

  const handleModelChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const slug = e.target.value;
    if (activeConversationId) {
      useCockpitStore.getState().updateConversation(activeConversationId, { model_slug: slug });
    }
  };

  const handlePolicyChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const policy = e.target.value;
    wsService.sendCommand('update_settings', { policy_preset: policy });
    useCockpitStore.getState().setSettings({ policy_preset: policy });
  };

  const toggleDrawerTab = (tab: DrawerTab) => {
    setActiveDrawerTab(activeDrawerTab === tab ? null : tab);
  };

  return (
    <header className="h-14 border-b border-neutral-800 bg-neutral-900/70 px-4 flex items-center justify-between backdrop-blur-sm select-none z-10">
      {/* Title & Edit */}
      <div className="flex items-center space-x-2 min-w-0">
        {isEditingTitle ? (
          <div className="flex items-center space-x-1">
            <input
              type="text"
              value={editedTitle}
              onChange={(e) => setEditedTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSaveTitle();
                if (e.key === 'Escape') setIsEditingTitle(false);
              }}
              autoFocus
              className="bg-neutral-800 border border-neutral-700 rounded px-2 py-1 text-sm text-neutral-100 focus:outline-none focus:border-indigo-500"
            />
            <button
              onClick={handleSaveTitle}
              className="p-1 text-emerald-400 hover:bg-neutral-800 rounded"
            >
              <Check className="w-4 h-4" />
            </button>
            <button
              onClick={() => setIsEditingTitle(false)}
              className="p-1 text-neutral-400 hover:bg-neutral-800 rounded"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ) : (
          <div className="flex items-center space-x-2 truncate">
            <h2 className="font-semibold text-sm text-neutral-200 truncate">
              {conversation?.title || 'Antigravity Cockpit'}
            </h2>
            {conversation && (
              <button
                onClick={handleStartEditTitle}
                className="p-1 text-neutral-500 hover:text-neutral-300 hover:bg-neutral-800/80 rounded transition-colors"
                title="Rename conversation"
              >
                <Edit2 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        )}
      </div>

      {/* Selectors & Drawer Toggles */}
      <div className="flex items-center space-x-3">
        {/* Model Selector */}
        <div className="flex items-center space-x-1.5 bg-neutral-950/60 border border-neutral-800 px-2.5 py-1 rounded-lg">
          <Sparkles className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
          <select
            value={conversation?.model_slug || settings.default_model}
            onChange={handleModelChange}
            disabled={!conversation}
            className="bg-transparent text-xs text-neutral-200 focus:outline-none cursor-pointer disabled:opacity-50"
          >
            {models.map((m) => (
              <option key={m.slug} value={m.slug} className="bg-neutral-900 text-neutral-200">
                {m.label}
              </option>
            ))}
          </select>
        </div>

        {/* Policy Selector */}
        <div className="flex items-center space-x-1.5 bg-neutral-950/60 border border-neutral-800 px-2.5 py-1 rounded-lg">
          <Shield className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <select
            value={settings.policy_preset}
            onChange={handlePolicyChange}
            className="bg-transparent text-xs text-neutral-200 focus:outline-none cursor-pointer"
          >
            <option value="request-review" className="bg-neutral-900 text-neutral-200">
              Review Sensitive (Default)
            </option>
            <option value="always-proceed" className="bg-neutral-900 text-neutral-200">
              Always Proceed (Auto-approve)
            </option>
            <option value="strict" className="bg-neutral-900 text-neutral-200">
              Strict (Review All Modifying)
            </option>
          </select>
        </div>

        <div className="h-4 w-px bg-neutral-800" />

        {/* Drawer Tabs */}
        <div className="flex items-center space-x-1">
          {/* Diffs */}
          <button
            onClick={() => toggleDrawerTab('diffs')}
            className={`relative p-2 rounded-lg text-xs font-medium transition-colors flex items-center space-x-1 ${
              activeDrawerTab === 'diffs'
                ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/40'
                : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800'
            }`}
            title="Changed Files & Diffs"
          >
            <FileDiff className="w-4 h-4" />
            {changedFilesCount > 0 && (
              <span className="ml-1 px-1.5 py-0.2 bg-indigo-600 text-white rounded-full text-[10px] font-bold">
                {changedFilesCount}
              </span>
            )}
          </button>

          {/* Terminal */}
          <button
            onClick={() => toggleDrawerTab('terminal')}
            className={`p-2 rounded-lg text-xs font-medium transition-colors ${
              activeDrawerTab === 'terminal'
                ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/40'
                : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800'
            }`}
            title="Command Terminal Output"
          >
            <Terminal className="w-4 h-4" />
          </button>

          {/* Subagents */}
          <button
            onClick={() => toggleDrawerTab('subagents')}
            className={`relative p-2 rounded-lg text-xs font-medium transition-colors flex items-center space-x-1 ${
              activeDrawerTab === 'subagents'
                ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/40'
                : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800'
            }`}
            title="Subagents Tree"
          >
            <Boxes className="w-4 h-4" />
            {subagentsCount > 0 && (
              <span className="ml-1 px-1.5 py-0.2 bg-emerald-600 text-white rounded-full text-[10px] font-bold">
                {subagentsCount}
              </span>
            )}
          </button>

          {/* Artifacts */}
          <button
            onClick={() => toggleDrawerTab('artifacts')}
            className={`relative p-2 rounded-lg text-xs font-medium transition-colors flex items-center space-x-1 ${
              activeDrawerTab === 'artifacts'
                ? 'bg-indigo-600/20 text-indigo-300 border border-indigo-500/40'
                : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800'
            }`}
            title="Generated Artifacts"
          >
            <Layers className="w-4 h-4" />
            {artifactsCount > 0 && (
              <span className="ml-1 px-1.5 py-0.2 bg-amber-600 text-white rounded-full text-[10px] font-bold">
                {artifactsCount}
              </span>
            )}
          </button>

          <div className="h-4 w-px bg-neutral-800 mx-1" />

          {/* Theme Toggle */}
          <button
            onClick={toggleTheme}
            className="p-2 rounded-lg text-xs font-medium text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 transition-colors"
            title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
          >
            {theme === 'dark' ? <Sun className="w-4 h-4 text-amber-400" /> : <Moon className="w-4 h-4 text-indigo-400" />}
          </button>
        </div>
      </div>
    </header>
  );
};
