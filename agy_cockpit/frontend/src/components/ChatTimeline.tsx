import React, { useRef, useEffect, useState } from 'react';
import { useVirtualizer } from '@tanstack/react-virtual';
import { useCockpitStore } from '../store/useCockpitStore';
import { ToolExecution } from '../types/models';
import { MarkdownView } from './MarkdownView';
import { ToolCard } from './ToolCard';
import { ReasoningAccordion } from './ReasoningAccordion';
import { Bot, User, AlertCircle, CheckCircle2, Clock, Ban } from 'lucide-react';

const EMPTY_MESSAGE_IDS: string[] = [];
const EMPTY_ACTIVE_TOOLS: Record<string, ToolExecution> = {};

export const ChatTimeline: React.FC = () => {
  const scrollRef = useRef<HTMLDivElement>(null);

  const activeConversationId = useCockpitStore((s) => s.activeConversationId);
  const conversation = useCockpitStore((s) =>
    s.activeConversationId ? s.conversations[s.activeConversationId] : null
  );
  const conversationMessageIds = useCockpitStore((s) => s.conversationMessageIds);
  const messageIds = (activeConversationId && conversationMessageIds[activeConversationId]) || EMPTY_MESSAGE_IDS;
  const messagesMap = useCockpitStore((s) => s.messages);

  const activeRunId = useCockpitStore((s) => s.activeRunId);
  const activeRun = useCockpitStore((s) => (s.activeRunId ? s.runs[s.activeRunId] : null));
  const reasoning = useCockpitStore((s) =>
    (s.activeConversationId && s.reasoningByConv[s.activeConversationId]) ||
    (s.activeRunId && s.runs[s.activeRunId]?.conversation_id === s.activeConversationId ? s.reasoning : '')
  );
  const streamingOutput = useCockpitStore((s) =>
    (s.activeConversationId && s.streamingOutputByConv[s.activeConversationId]) ||
    (s.activeRunId && s.runs[s.activeRunId]?.conversation_id === s.activeConversationId ? s.streamingOutput : '')
  );
  const activeTools = useCockpitStore((s) =>
    (s.activeConversationId && s.activeToolsByConv[s.activeConversationId]) ||
    (s.activeRunId && s.runs[s.activeRunId]?.conversation_id === s.activeConversationId ? s.activeTools : EMPTY_ACTIVE_TOOLS)
  );

  const isCurrentRunForThisConv = Boolean(activeRunId && activeRun?.conversation_id === activeConversationId);
  const isStreaming = isCurrentRunForThisConv;
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    if (!activeRunId || !activeRun?.started_at) {
      setElapsedSeconds(0);
      return;
    }
    const start = new Date(activeRun.started_at).getTime();
    const interval = setInterval(() => {
      setElapsedSeconds(Math.max(0, (Date.now() - start) / 1000));
    }, 150);
    return () => clearInterval(interval);
  }, [activeRunId, activeRun?.started_at]);

  const messages = messageIds.map((id) => messagesMap[id]).filter(Boolean);

  const rowVirtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 100,
    overscan: 5,
  });

  // Auto-scroll to bottom when streaming tokens or messages arrive
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messageIds.length, streamingOutput, reasoning, Object.keys(activeTools).length]);

  if (!activeConversationId) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center p-8 text-center text-neutral-500">
        <Bot className="w-12 h-12 mb-3 text-neutral-600" />
        <h3 className="text-lg font-medium text-neutral-300 mb-1">No Conversation Selected</h3>
        <p className="text-sm max-w-sm">
          Select a conversation from the sidebar or start a new conversation to begin pair programming.
        </p>
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 md:p-6 space-y-4">
      {messages.length === 0 && !activeRunId && (
        <div className="flex flex-col items-center justify-center h-full text-center text-neutral-500 py-16">
          <Bot className="w-10 h-10 mb-2 text-indigo-400/70" />
          <h3 className="text-base font-medium text-neutral-200">
            {conversation?.title || 'New Conversation'}
          </h3>
          <p className="text-xs text-neutral-400 mt-1 max-w-md">
            Type a task or question below. Antigravity will stream its reasoning, tool invocations, and answers.
          </p>
        </div>
      )}

      {/* Virtualized Historical Messages */}
      {messages.length > 0 && (
        <div
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: '100%',
            position: 'relative',
          }}
        >
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const msg = messages[virtualRow.index];
            if (!msg) return null;
            return (
              <div
                key={virtualRow.key}
                data-index={virtualRow.index}
                ref={rowVirtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualRow.start}px)`,
                }}
                className="pb-4"
              >
                <div
                  className={`flex gap-3 max-w-4xl mx-auto ${
                    msg.role === 'user' ? 'justify-end' : 'justify-start'
                  }`}
                >
                  {msg.role !== 'user' && (
                    <div className="w-8 h-8 rounded-full bg-indigo-950 border border-indigo-700/50 flex items-center justify-center text-indigo-300 shrink-0">
                      <Bot className="w-4 h-4" />
                    </div>
                  )}

                  <div
                    className={`rounded-2xl px-4 py-3 text-sm leading-relaxed max-w-[85%] ${
                      msg.role === 'user'
                        ? 'bg-neutral-800 text-neutral-100 rounded-br-sm border border-neutral-700/50 shadow-md'
                        : 'bg-neutral-900/80 text-neutral-200 rounded-bl-sm border border-neutral-800 shadow-md'
                    }`}
                  >
                    {msg.role === 'user' ? (
                      <div className="whitespace-pre-wrap font-sans select-text">{msg.content}</div>
                    ) : (
                      <div className="space-y-2">
                        {/* Historical Reasoning Process */}
                        {msg.reasoning && (
                          <ReasoningAccordion reasoning={msg.reasoning} isStreaming={false} />
                        )}

                        {/* Historical Tools Invocations */}
                        {msg.tools && msg.tools.length > 0 && (
                          <div className="space-y-1">
                            {msg.tools.map((tool) => (
                              <ToolCard key={tool.id} tool={tool} />
                            ))}
                          </div>
                        )}

                        {msg.content ? (
                          <MarkdownView content={msg.content} />
                        ) : null}
                      </div>
                    )}

                    <div className="mt-1 text-[10px] text-neutral-400 text-right">
                      {new Date(msg.author_time).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  </div>

                  {msg.role === 'user' && (
                    <div className="w-8 h-8 rounded-full bg-neutral-800 border border-neutral-700 flex items-center justify-center text-neutral-300 shrink-0">
                      <User className="w-4 h-4" />
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Active Streaming Turn */}
      {isCurrentRunForThisConv && (
        <div className="flex gap-3 max-w-4xl mx-auto justify-start">
          <div className="w-8 h-8 rounded-full bg-indigo-950 border border-indigo-700/50 flex items-center justify-center text-indigo-300 shrink-0 animate-pulse">
            <Bot className="w-4 h-4" />
          </div>

          <div className="flex-1 bg-neutral-900/80 rounded-2xl rounded-bl-sm px-4 py-3 border border-neutral-800 shadow-md space-y-2">
            {/* Reasoning Accordion */}
            {reasoning && (
              <ReasoningAccordion reasoning={reasoning} isStreaming={isStreaming} />
            )}

            {/* Live Tool Executions */}
            {Object.values(activeTools).length > 0 && (
              <div className="space-y-1">
                {Object.values(activeTools).map((tool) => (
                  <ToolCard key={tool.id} tool={tool} />
                ))}
              </div>
            )}

            {/* Streamed Assistant Content */}
            {streamingOutput ? (
              <div className="relative">
                <MarkdownView content={streamingOutput} />
                {isStreaming && (
                  <span className="inline-block w-1.5 h-3.5 bg-indigo-400 animate-pulse ml-1 align-middle rounded-xs" />
                )}
              </div>
            ) : (
              <div className="flex items-center space-x-2 text-xs text-neutral-400 py-1">
                <div className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
                </div>
                <span>
                  {reasoning
                    ? `Reasoning in progress (${elapsedSeconds.toFixed(1)}s)...`
                    : `Deliberating with Gemini (${elapsedSeconds.toFixed(1)}s)...`}
                </span>
              </div>
            )}

            {/* Status Footer */}
            <div className="pt-2 border-t border-neutral-800/60 flex items-center justify-between text-[11px] text-neutral-400">
              <div className="flex items-center space-x-1.5">
                {activeRun?.state === 'running_tool' ? (
                  <>
                    <Clock className="w-3.5 h-3.5 text-amber-400" />
                    <span className="text-amber-300 font-mono">Running tool...</span>
                  </>
                ) : activeRun?.state === 'thinking' ? (
                  <>
                    <Bot className="w-3.5 h-3.5 text-indigo-400 animate-pulse" />
                    <span className="text-indigo-300 font-medium">Reasoning...</span>
                  </>
                ) : activeRun?.state === 'cancelled' ? (
                  <>
                    <Ban className="w-3.5 h-3.5 text-neutral-400" />
                    <span className="text-neutral-400">Run cancelled</span>
                  </>
                ) : activeRun?.state === 'failed' ? (
                  <>
                    <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
                    <span className="text-rose-400 font-medium">{activeRun.error_message || 'Failed'}</span>
                  </>
                ) : (
                  <>
                    <CheckCircle2 className="w-3.5 h-3.5 text-indigo-400 animate-spin" />
                    <span>Generating response...</span>
                  </>
                )}
              </div>

              {activeRun?.started_at && (
                <span>Started {new Date(activeRun.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
