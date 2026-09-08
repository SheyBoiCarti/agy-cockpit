import React, { useState, useEffect } from 'react';
import { Brain, ChevronDown, ChevronRight } from 'lucide-react';

interface ReasoningAccordionProps {
  reasoning: string;
  isStreaming: boolean;
}

export const ReasoningAccordion: React.FC<ReasoningAccordionProps> = ({
  reasoning,
  isStreaming,
}) => {
  const [isOpen, setIsOpen] = useState(true);

  // Auto-collapse when run finishes streaming
  useEffect(() => {
    if (!isStreaming && reasoning) {
      setIsOpen(false);
    } else if (isStreaming) {
      setIsOpen(true);
    }
  }, [isStreaming]);

  if (!reasoning) return null;

  return (
    <div className="my-2 rounded-lg border border-neutral-800 bg-neutral-900/40 text-xs overflow-hidden">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-3 py-1.5 text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/40 transition-colors"
      >
        <div className="flex items-center space-x-2">
          <Brain className={`w-3.5 h-3.5 ${isStreaming ? 'animate-pulse text-indigo-400' : 'text-neutral-400'}`} />
          <span className="font-medium">
            {isStreaming ? 'Thinking...' : 'Reasoning Process'}
          </span>
        </div>
        <div className="flex items-center space-x-1">
          <span className="text-[10px] text-neutral-400">
            {reasoning.length} chars
          </span>
          {isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
        </div>
      </button>

      {isOpen && (
        <div className="p-3 border-t border-neutral-800 bg-neutral-950/40 text-neutral-400 font-mono leading-relaxed max-h-60 overflow-y-auto whitespace-pre-wrap select-text">
          {reasoning}
        </div>
      )}
    </div>
  );
};
