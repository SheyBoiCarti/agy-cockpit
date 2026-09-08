import React, { useState, useRef, useEffect } from 'react';
import { useCockpitStore } from '../store/useCockpitStore';
import { wsService } from '../services/websocket';
import { Send, Square, Paperclip, AtSign, Loader2, X, Boxes, FileDiff, HelpCircle, Trash2 } from 'lucide-react';

interface AttachedFile {
  id: string;
  name: string;
  size: number;
}

const SLASH_COMMANDS = [
  { command: '/diff', label: 'View Diff', description: 'Open changed-files panel', icon: FileDiff },
  { command: '/agents', label: 'Subagents', description: 'Open subagents panel', icon: Boxes },
  { command: '/clear', label: 'Clear Input', description: 'Clear composer text only', icon: Trash2 },
  { command: '/help', label: 'Help', description: 'Show supported slash commands', icon: HelpCircle },
];

export const Composer: React.FC = () => {
  const [text, setText] = useState('');
  const [mentionActive, setMentionActive] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [selectedMentionIdx, setSelectedMentionIdx] = useState(0);

  const [slashActive, setSlashActive] = useState(false);
  const [selectedSlashIdx, setSelectedSlashIdx] = useState(0);

  const [attachments, setAttachments] = useState<AttachedFile[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const activeConversationId = useCockpitStore((s) => s.activeConversationId);
  const activeRunId = useCockpitStore((s) => s.activeRunId);
  const setActiveDrawerTab = useCockpitStore((s) => s.setActiveDrawerTab);
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

  const matchingSlashCommands = SLASH_COMMANDS.filter((sc) =>
    sc.command.toLowerCase().startsWith(text.trim().toLowerCase())
  );

  const executeSlashCommand = (cmd: string) => {
    const trimmed = cmd.trim().toLowerCase();
    setSlashActive(false);
    if (trimmed === '/diff') {
      setActiveDrawerTab('diffs');
      setText('');
    } else if (trimmed === '/agents') {
      setActiveDrawerTab('subagents');
      setText('');
    } else if (trimmed === '/clear') {
      setText('');
      setAttachments([]);
    } else if (trimmed === '/help') {
      setText('');
      setActiveDrawerTab('diffs');
    }
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed && attachments.length === 0) return;
    if (isRunning || !activeConversationId) return;

    // Check for slash command invocation
    if (trimmed.startsWith('/')) {
      const match = SLASH_COMMANDS.find((sc) => sc.command.toLowerCase() === trimmed.toLowerCase());
      if (match) {
        executeSlashCommand(match.command);
        return;
      }
    }

    const attachmentIds = attachments.map((a) => a.id);
    wsService.sendPrompt(trimmed, attachmentIds, selectedModel);
    setText('');
    setAttachments([]);
    setMentionActive(false);
    setSlashActive(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  };

  const handleStop = () => {
    wsService.cancelActiveRun();
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0 || !activeConversationId) return;
    setIsUploading(true);
    try {
      const files = Array.from(e.target.files);
      for (const file of files) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('conversation_id', activeConversationId);

        const res = await fetch('/api/attachments', {
          method: 'POST',
          body: formData,
        });

        if (!res.ok) {
          throw new Error(`Upload failed: ${res.statusText}`);
        }

        const data = await res.json();
        if (data.attachment) {
          setAttachments((prev) => [
            ...prev,
            {
              id: data.attachment.id,
              name: data.attachment.filename || data.attachment.file_name,
              size: data.attachment.size_bytes ?? data.attachment.byte_size ?? 0,
            },
          ]);
        }
      }
    } catch (err) {
      console.error('Failed to upload attachment:', err);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Slash commands navigation
    if (slashActive && matchingSlashCommands.length > 0) {
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedSlashIdx((prev) => (prev + 1) % matchingSlashCommands.length);
        return;
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedSlashIdx((prev) => (prev - 1 + matchingSlashCommands.length) % matchingSlashCommands.length);
        return;
      }
      if (e.key === 'Enter' || e.key === 'Tab') {
        e.preventDefault();
        executeSlashCommand(matchingSlashCommands[selectedSlashIdx].command);
        return;
      }
      if (e.key === 'Escape') {
        setSlashActive(false);
        return;
      }
    }

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

    // Slash command trigger check
    if (val.startsWith('/') && !val.includes(' ')) {
      setSlashActive(true);
      setSelectedSlashIdx(0);
      setMentionActive(false);
      return;
    } else {
      setSlashActive(false);
    }

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
      {/* Hidden file input for attachments */}
      <input
        type="file"
        ref={fileInputRef}
        className="hidden"
        multiple
        onChange={handleFileUpload}
      />

      {/* Slash Commands Auto-Complete Popup */}
      {slashActive && matchingSlashCommands.length > 0 && (
        <div className="absolute bottom-full left-4 mb-2 w-80 max-h-60 overflow-y-auto bg-neutral-900 border border-neutral-700 rounded-lg shadow-2xl z-50">
          <div className="px-3 py-1.5 text-xs text-neutral-400 border-b border-neutral-800 flex items-center justify-between">
            <span>Slash Commands</span>
            <span className="text-[10px] text-neutral-500">Enter or Tab to run</span>
          </div>
          {matchingSlashCommands.map((item, idx) => {
            const Icon = item.icon;
            return (
              <div
                key={item.command}
                onClick={() => executeSlashCommand(item.command)}
                className={`px-3 py-2 text-xs cursor-pointer flex items-center justify-between ${
                  idx === selectedSlashIdx
                    ? 'bg-indigo-600/30 text-indigo-200'
                    : 'text-neutral-300 hover:bg-neutral-800'
                }`}
              >
                <div className="flex items-center space-x-2 truncate">
                  <Icon className="w-3.5 h-3.5 text-indigo-400 shrink-0" />
                  <span className="font-mono font-medium text-neutral-100">{item.command}</span>
                  <span className="text-neutral-400 truncate text-[11px]">{item.description}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

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
        {/* Attachment Chips */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 px-3 pt-2.5 pb-1 border-b border-neutral-800/60">
            {attachments.map((att) => (
              <div
                key={att.id}
                className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-neutral-800 border border-neutral-700 text-xs text-neutral-200"
              >
                <Paperclip className="w-3 h-3 text-indigo-400 shrink-0" />
                <span className="truncate max-w-[160px]" title={att.name}>{att.name}</span>
                <span className="text-[10px] text-neutral-400 font-mono">
                  ({Math.round(att.size / 1024)}KB)
                </span>
                <button
                  type="button"
                  onClick={() => removeAttachment(att.id)}
                  className="p-0.5 hover:text-rose-400 text-neutral-400 rounded transition-colors"
                  title="Remove attachment"
                >
                  <X className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        <textarea
          ref={textareaRef}
          value={text}
          onChange={handleTextChange}
          onKeyDown={handleKeyDown}
          disabled={!activeConversationId}
          placeholder={
            !activeConversationId
              ? 'Select or create a conversation to begin...'
              : 'Ask Antigravity anything... (Type @ to mention files, / for commands)'
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
              onClick={() => fileInputRef.current?.click()}
              disabled={!activeConversationId || isUploading}
              className="p-1.5 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 disabled:opacity-40 rounded-lg transition-colors cursor-pointer"
              title="Add attachment"
            >
              {isUploading ? (
                <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />
              ) : (
                <Paperclip className="w-4 h-4" />
              )}
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
                disabled={(!text.trim() && attachments.length === 0) || !activeConversationId}
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
