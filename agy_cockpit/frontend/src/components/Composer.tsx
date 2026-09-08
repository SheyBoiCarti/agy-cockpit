import React, { useState, useRef, useEffect } from 'react';
import { useCockpitStore } from '../store/useCockpitStore';
import { wsService } from '../services/websocket';
import { Send, Square, Paperclip, AtSign, Loader2 } from 'lucide-react';

export const Composer: React.FC = () => {
  const [text, setText] = useState('');
  const [mentionActive, setMentionActive] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [selectedMentionIdx, setSelectedMentionIdx] = useState(0);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const activeConversationId = useCockpitStore((s) => s.activeConversationId);
  const activeRunId = useCockpitStore((s) => s.activeRunId);
  const isSearchingMention = useCockpitStore((s) => s.isSearchingMention);
  const mentionResults = useCockpitStore((s) => s.mentionResults);
  const selectedModel = useCockpitStore((s) => s.conversations[s.activeConversationId || '']?.model_slug);

  const isRunning = Boolean(activeRunId);

  // Auto-grow textarea height
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [text]);

  const handleSend = () => {
    if (!text.trim() || isRunning || !activeConversationId) return;
    wsService.sendPrompt(text.trim(), [], selectedModel);
    setText('');
    setMentionActive(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleStop = () => {
    wsService.cancelActiveRun();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Mention navigation
    if (mentionActive && mentionResults.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedMentionIdx((prev) => (prev + 1) % mentionResults.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedMentionIdx((prev) => (prev - 1 + mentionResults.length) % mentionResults.length);
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        insertMention(mentionResults[selectedMentionIdx].path);
        return;
      }
      if (e.key === 'Escape') {
        setMentionActive(false);
        return;
      }
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const val = e.target.value;
    setText(val);

    // Detect @ symbol at cursor
    const cursor = e.target.selectionStart || 0;
    const textBeforeCursor = val.slice(0, cursor);
    const lastAtIdx = textBeforeCursor.lastIndexOf('@');

    if (lastAtIdx !== -1 && !textBeforeCursor.slice(lastAtIdx).includes(' ')) {
      const query = textBeforeCursor.slice(lastAtIdx + 1);
      setMentionActive(true);
      setMentionFilter(query);
      setSelectedMentionIdx(0);
      wsService.searchWorkspace(query);
    } else {
      setMentionActive(false);
    }
  };

  const insertMention = (path: string) => {
    if (!textareaRef.current) return;
    const cursor = textareaRef.current.selectionStart || 0;
    const textBeforeCursor = text.slice(0, cursor);
    const lastAtIdx = textBeforeCursor.lastIndexOf('@');
    const textAfterCursor = text.slice(cursor);

    const newText = `${text.slice(0, lastAtIdx)}@${path} ${textAfterCursor}`;
    setText(newText);
    setMentionActive(false);

    setTimeout(() => {
      if (textareaRef.current) {
        textareaRef.current.focus();
        const nextPos = lastAtIdx + path.length + 2;
        textareaRef.current.setSelectionRange(nextPos, nextPos);
      }
    }, 10);
  };

  return (
    <div className="relative border-t border-neutral-800 bg-neutral-900/90 p-4 backdrop-blur-sm">
      {/* Mention Auto-Complete Popup */}
      {mentionActive && (
        <div className="absolute bottom-full left-4 mb-2 w-80 max-h-60 overflow-y-auto bg-neutral-900 border border-neutral-700 rounded-lg shadow-2xl z-50">
          <div className="px-3 py-1.5 text-xs text-neutral-400 border-b border-neutral-800 flex items-center justify-between">
            <span>Files matching "@{mentionFilter}"</span>
            {isSearchingMention && <Loader2 className="w-3 h-3 animate-spin text-neutral-400" />}
          </div>
          {mentionResults.length === 0 ? (
            <div className="px-3 py-2 text-xs text-neutral-400">No matching workspace files</div>
          ) : (
            mentionResults.map((item, idx) => (
              <div
                key={item.path}
                onClick={() => insertMention(item.path)}
                className={`px-3 py-2 text-xs font-mono cursor-pointer flex items-center justify-between ${
                  idx === selectedMentionIdx
                    ? 'bg-indigo-600/30 text-indigo-200'
                    : 'text-neutral-300 hover:bg-neutral-800'
                }`}
              >
                <span className="truncate">{item.path}</span>
                {item.is_directory && <span className="text-[10px] text-neutral-400">dir</span>}
              </div>
            ))
          )}
        </div>
      )}

      <div className="relative flex flex-col rounded-xl border border-neutral-700/80 bg-neutral-950 focus-within:border-indigo-500 focus-within:ring-1 focus-within:ring-indigo-500 transition-all">
        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleTextChange}
          onKeyDown={handleKeyDown}
          disabled={!activeConversationId}
          placeholder={
            !activeConversationId
              ? 'Select or create a conversation to begin...'
              : 'Ask Antigravity anything... (Type @ to mention workspace files)'
          }
          rows={2}
          className="w-full resize-none bg-transparent px-4 py-3 text-sm text-neutral-100 placeholder-neutral-500 focus:outline-none disabled:opacity-50"
        />

        <div className="flex items-center justify-between px-3 py-2 border-t border-neutral-900 bg-neutral-950/40 rounded-b-xl">
          <div className="flex items-center space-x-2">
            <button
              type="button"
              onClick={() => {
                setText((prev) => `${prev}@`);
                setMentionActive(true);
                wsService.searchWorkspace('');
              }}
              className="p-1.5 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 rounded-lg transition-colors"
              title="Mention file (@)"
            >
              <AtSign className="w-4 h-4" />
            </button>
            <button
              type="button"
              className="p-1.5 text-neutral-500 hover:text-neutral-300 hover:bg-neutral-800 rounded-lg transition-colors cursor-pointer"
              title="Add attachment"
            >
              <Paperclip className="w-4 h-4" />
            </button>
          </div>

          <div className="flex items-center space-x-2">
            {isRunning ? (
              <button
                type="button"
                onClick={handleStop}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-rose-600/20 text-rose-300 border border-rose-600/40 hover:bg-rose-600/30 text-xs font-medium transition-colors"
              >
                <Square className="w-3.5 h-3.5 fill-current" />
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSend}
                disabled={!text.trim() || !activeConversationId}
                className="flex items-center space-x-1.5 px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:hover:bg-indigo-600 text-xs font-medium transition-colors"
              >
                <span>Send</span>
                <Send className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
